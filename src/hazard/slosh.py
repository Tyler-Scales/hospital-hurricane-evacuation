#!/usr/bin/env python3
"""
Storm-surge inundation class at each hospital, from NOAA SLOSH MOM GeoTIFFs.

Why: the study needs a per-hospital surge-exposure covariate that does not
depend on which storms actually hit. The SLOSH Maximum of MOMs (MOM) product
gives, per Saffir-Simpson category, the worst-case inundation depth class at
each grid cell across thousands of simulated storms — a fixed hazard surface
we can sample at hospital coordinates.

Method:
  1. Read hospital points from data/interim/hospital_coords.csv. Only
     method == 'census_street' rows are sampled: ZIP-centroid coordinates are
     far too imprecise for a ~10 m (0.32 arcsec) surge grid (a centroid can
     sit miles from the building, across the wet/dry line).
  2. For each category 1-5, find the matching GeoTIFF(s) in data/raw/slosh/
     (filenames contain 'Category1'..'Category5'; matched case-insensitively).
     Where a product ships both tide scenarios, the high-tide variant
     ('HighTide' / 'HIGH' / 'agl' naming) is preferred: MOM is a worst-case
     product, and NHC's published hazard maps use the high-tide run.
     Multiple non-overlapping regional files per category (e.g. CONUS + PR)
     are all sampled; the first raster whose bounds contain the point wins.
  3. The CONUS v4 rasters are 84-gigapixel BigTIFFs; never load them whole.
     Instead decode only the 128x128 tile containing each target pixel via
     tifffile's low-level page metadata + imagecodecs (validated against
     tifffile.imread on the small PR product in src/hazard/test_slosh.py).

What the files actually look like (inspected 2026-08):
  - PR_SLOSH_MOM_Inundation (11/2018): classic TIFF, LZW, no predictor,
    10580x31329, GCS NAD83 (EPSG:4269), nodata 255, classes 1..16 present.
  - US_SLOSH_MOM_Inundation_v4 (dated 20260617): BigTIFF, LERC compression
    (34887, LercParameters (4, 0) = no additional compression), no predictor,
    243836x347032, GCS NAD83 (EPSG:4269), nodata 255. Covers lon -98.06 to
    -66.89, lat 24.49 to 46.40 (Gulf + East coasts only). Its VAT defines
    classes 1..20 and 99 only; the pixels also contain literal 0s, which the
    band histogram/VAT exclude entirely -> 0 is a second flavor of
    dry/not-modeled, treated like nodata here.

Class values (thematic uint8):
  1..21  depth bins in feet above ground: 1 = '0-1 ft' ... 20 = '19-20 ft',
         21 = '>20 ft'  -> decoded to the bin's LOWER edge (class k -> k-1 ft)
  99     leveed area (SLOSH does not model overtopping) -> 'leveed'
  0 / nodata (GDAL_NODATA tag, 255 in all products seen) = dry/not inundated
         -> 0 ft. Points outside every raster's bounds get blank cells
         (e.g. Pacific-coast hospitals: not in this product, unknown != dry).

Output: data/interim/hospital_surge.csv
  ccn, surge_cat1..surge_cat5 (raw class values),
  surge_cat1_ft..surge_cat5_ft (decoded feet / 'leveed').

Usage:
    python3 src/hazard/slosh.py [--zip data/raw/slosh_mom_v4.zip]
    (--zip first extracts any *.tif members into data/raw/slosh/)
"""

import argparse
import csv
import math
import re
import sys
import zipfile
import zlib
from pathlib import Path

import imagecodecs
import numpy as np
import tifffile

REPO = Path(__file__).resolve().parents[2]
COORDS = REPO / "data" / "interim" / "hospital_coords.csv"
SLOSH_DIR = REPO / "data" / "raw" / "slosh"
OUT = REPO / "data" / "interim" / "hospital_surge.csv"

LEVEED = 99
CATS = (1, 2, 3, 4, 5)

# GeoKey ids (GeoTIFF spec)
GT_MODEL_TYPE = 1024          # 1 = projected, 2 = geographic
GEOGRAPHIC_TYPE = 2048        # EPSG geographic CS code (e.g. 4269 = NAD83)
PROJECTED_TYPE = 3072         # EPSG projected CS code


def parse_geokeys(page):
    """GeoKeyDirectoryTag -> {key_id: value} for SHORT-valued keys."""
    tag = page.tags.get(34735)
    if tag is None:
        return {}
    d = tag.value
    keys = {}
    nkeys = d[3]
    for i in range(nkeys):
        kid, loc, cnt, val = d[4 + 4 * i: 8 + 4 * i]
        if loc == 0:            # value stored inline as SHORT
            keys[kid] = val
    return keys


def open_raster(path):
    """Open a tiled SLOSH GeoTIFF for targeted single-pixel reads.

    Returns a dict with the open handles, geotransform, tile layout, and an
    empty per-file tile cache. Never reads the pixel data itself.
    """
    tf = tifffile.TiffFile(path)
    page = tf.pages[0]
    if not page.is_tiled:
        raise SystemExit(f"{path.name}: not tiled; targeted reader assumes tiles")
    if page.samplesperpixel != 1 or page.bitspersample != 8:
        raise SystemExit(f"{path.name}: expected single-band uint8, got "
                         f"{page.samplesperpixel} band(s) x {page.bitspersample} bit")

    keys = parse_geokeys(page)
    model = keys.get(GT_MODEL_TYPE)
    if model != 2:
        ascii_tag = page.tags.get(34737)
        raise SystemExit(
            f"{path.name}: CRS is not geographic (GTModelType={model}, "
            f"ProjectedCSType={keys.get(PROJECTED_TYPE)}). GeoKeys: {keys}. "
            f"GeoAscii: {ascii_tag.value if ascii_tag else None}. "
            "Targeted reader only handles lon/lat grids; add a projection here.")

    sx, sy = page.tags[33550].value[:2]                  # ModelPixelScaleTag
    i0, j0, _, x0, y0, _ = page.tags[33922].value[:6]    # ModelTiepointTag
    nodata_tag = page.tags.get(42113)                    # GDAL_NODATA
    nodata = int(float(nodata_tag.value)) if nodata_tag else 255

    comp = int(page.compression)
    if comp not in (1, 5, 8, 32946, 34887):   # none, LZW, deflate, LERC
        raise SystemExit(f"{path.name}: unsupported compression {page.compression}")
    lerc_tag = page.tags.get(50674)           # LercParameters: (version, extra)
    lerc_extra = int(lerc_tag.value[1]) if lerc_tag else 0

    length, width = page.shape[:2]
    return {
        "path": path,
        "tf": tf,
        "fh": open(path, "rb"),
        "ulx": x0 - i0 * sx,
        "uly": y0 + j0 * sy,
        "sx": sx,
        "sy": sy,
        "width": width,
        "length": length,
        "tw": page.tilewidth,
        "tl": page.tilelength,
        "tiles_across": (width + page.tilewidth - 1) // page.tilewidth,
        "offsets": page.dataoffsets,
        "counts": page.databytecounts,
        "compression": comp,
        "lerc_extra": lerc_extra,
        "predictor": int(page.predictor),
        "nodata": nodata,
        "epsg": keys.get(GEOGRAPHIC_TYPE),
        "bigtiff": tf.is_bigtiff,
        "cache": {},
    }


def close_raster(g):
    g["fh"].close()
    g["tf"].close()
    g["cache"].clear()


def _decode_tile(g, ti):
    """Decode one tile to a (tilelength, tilewidth) uint8 array, cached."""
    tile = g["cache"].get(ti)
    if tile is not None:
        return tile
    n = g["tw"] * g["tl"]
    count = g["counts"][ti]
    if count == 0:
        # sparse tile (no data written): treat as nodata / dry
        tile = np.full((g["tl"], g["tw"]), g["nodata"], dtype=np.uint8)
    else:
        g["fh"].seek(g["offsets"][ti])
        raw = g["fh"].read(count)
        if g["compression"] == 34887:                 # LERC
            if g["lerc_extra"] == 1:                  # + deflate wrapper
                raw = zlib.decompress(raw)
            elif g["lerc_extra"] == 2:                # + zstd wrapper
                raw = imagecodecs.zstd_decode(raw)
            arr, mask = imagecodecs.lerc_decode(raw, masks=True)
            tile = np.ascontiguousarray(arr, dtype=np.uint8).reshape(g["tl"], g["tw"])
            if mask is not None:                      # invalid px -> nodata
                bad = ~mask.reshape(g["tl"], g["tw"]).astype(bool)
                tile = tile.copy()
                tile[bad] = g["nodata"]
        else:
            if g["compression"] == 5:
                data = imagecodecs.lzw_decode(raw)
            elif g["compression"] in (8, 32946):
                data = zlib.decompress(raw)
            else:
                data = raw
            arr = np.frombuffer(data, dtype=np.uint8)
            if arr.size < n:  # writer truncated an edge tile; pad with nodata
                arr = np.concatenate([arr, np.full(n - arr.size, g["nodata"], np.uint8)])
            tile = arr[:n].reshape(g["tl"], g["tw"])
            if g["predictor"] == 2:
                tile = np.cumsum(tile, axis=1, dtype=np.uint8)
    g["cache"][ti] = tile
    return tile


def pixel_value(g, row, col):
    """Raw class value at pixel (row, col); decodes only that pixel's tile."""
    ti = (row // g["tl"]) * g["tiles_across"] + (col // g["tw"])
    tile = _decode_tile(g, ti)
    return int(tile[row % g["tl"], col % g["tw"]])


def value_at(g, lat, lon):
    """Raw class value at (lat, lon), or None if outside the raster bounds."""
    col = int(math.floor((lon - g["ulx"]) / g["sx"]))
    row = int(math.floor((g["uly"] - lat) / g["sy"]))
    if not (0 <= row < g["length"] and 0 <= col < g["width"]):
        return None
    return pixel_value(g, row, col)


def decode_ft(value, nodata):
    """Class value -> feet (bin lower edge), 'leveed', or '' if unexpected."""
    if value == nodata or value == 0:   # 0: unclassed dry pixels in CONUS v4
        return 0
    if value == LEVEED:
        return "leveed"
    if 1 <= value <= 21:
        return value - 1
    return ""


def find_category_files(slosh_dir):
    """{category: [tif paths]} with low-tide variants dropped when a high-tide
    sibling exists for the same category."""
    tifs = sorted(p for p in slosh_dir.glob("*.tif*")
                  if p.suffix.lower() in (".tif", ".tiff"))
    by_cat = {c: [] for c in CATS}
    for p in tifs:
        m = re.search(r"cat(?:egory)?[ _\-]?([1-5])", p.name, re.I)
        if m:
            by_cat[int(m.group(1))].append(p)
    for c in CATS:
        names = by_cat[c]
        has_high = any(re.search(r"high|agl", p.stem, re.I) for p in names)
        if has_high:
            by_cat[c] = [p for p in names if not re.search(r"low", p.stem, re.I)]
    return by_cat


def extract_zip(zpath, dest):
    """Pull *.tif members out of a SLOSH product zip into dest (flat)."""
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith((".tif", ".tiff")):
                continue
            out = dest / Path(info.filename).name
            if out.exists() and out.stat().st_size == info.file_size:
                print(f"  cached   {out.name}")
                continue
            print(f"  extract  {out.name}  ({info.file_size/1e6:.0f} MB)")
            with z.open(info) as src, out.open("wb") as dst:
                while True:
                    chunk = src.read(1 << 22)
                    if not chunk:
                        break
                    dst.write(chunk)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--zip", type=Path, default=None,
                    help="SLOSH product zip to extract *.tif from first")
    ap.add_argument("--slosh-dir", type=Path, default=SLOSH_DIR)
    ap.add_argument("--coords", type=Path, default=COORDS)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if args.zip:
        print(f"extracting GeoTIFFs from {args.zip.name}")
        args.slosh_dir.mkdir(parents=True, exist_ok=True)
        extract_zip(args.zip, args.slosh_dir)

    by_cat = find_category_files(args.slosh_dir)
    missing = [c for c in CATS if not by_cat[c]]
    if missing:
        raise SystemExit(f"no GeoTIFF found for categories {missing} in "
                         f"{args.slosh_dir} — download/extract a SLOSH MOM product first")
    for c in CATS:
        print(f"cat{c}: {', '.join(p.name for p in by_cat[c])}")

    hospitals = []
    with args.coords.open() as fh:
        for r in csv.DictReader(fh):
            if r["method"] in ("census_street", "osm_name"):
                hospitals.append((r["ccn"], float(r["lat"]), float(r["lon"])))
    print(f"\nhospitals with street-level coords: {len(hospitals)} "
          "(zip-centroid rows skipped: too imprecise for the surge grid)")

    # results[ccn][cat] = raw class value (int) or None (out of coverage)
    results = {ccn: dict.fromkeys(CATS) for ccn, _, _ in hospitals}
    nodata_by_cat = {}
    unexpected = {}

    for c in CATS:
        remaining = list(hospitals)
        for path in by_cat[c]:
            g = open_raster(path)
            nodata_by_cat[c] = g["nodata"]
            print(f"cat{c} <- {path.name}: {g['length']}x{g['width']} px, "
                  f"EPSG:{g['epsg']}, cell {g['sx']*3600:.1f} arcsec, "
                  f"nodata {g['nodata']}, bigtiff={g['bigtiff']}")
            still_out = []
            hits = 0
            for ccn, lat, lon in remaining:
                v = value_at(g, lat, lon)
                if v is None:
                    still_out.append((ccn, lat, lon))
                    continue
                results[ccn][c] = v
                hits += 1
                if v not in (g["nodata"], LEVEED, 0) and not 1 <= v <= 21:
                    unexpected[v] = unexpected.get(v, 0) + 1
            print(f"        in bounds: {hits}  ({len(g['cache'])} tiles decoded)")
            close_raster(g)
            remaining = still_out
        print(f"cat{c}: outside all rasters: {len(remaining)}")

    if unexpected:
        print(f"WARNING unexpected class values (raw kept, _ft blank): {unexpected}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    header = (["ccn"] + [f"surge_cat{c}" for c in CATS]
              + [f"surge_cat{c}_ft" for c in CATS])
    n_wet = 0
    with args.out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for ccn, _, _ in hospitals:
            raw = [results[ccn][c] for c in CATS]
            ft = [decode_ft(v, nodata_by_cat[c]) if v is not None else ""
                  for c, v in zip(CATS, raw)]
            w.writerow([ccn] + ["" if v is None else v for v in raw] + ft)
            if any(v is not None and 1 <= v <= 21 for v in raw):
                n_wet += 1
    print(f"\nhospitals inundated in at least one category: {n_wet}")
    print(f"Wrote {args.out.relative_to(REPO)} ({len(hospitals)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
