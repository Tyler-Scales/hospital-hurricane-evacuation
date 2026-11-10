#!/usr/bin/env python3
"""
Validation for the targeted SLOSH tile reader.

The extractor never loads the big CONUS rasters whole, so its low-level tile
decoding must be proven exact against tifffile's reference reader on a raster
small enough to load fully — the Puerto Rico MOM product. Skips gracefully if
the PR files are absent.

Run: python3 src/hazard/test_slosh.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from slosh import (  # noqa: E402
    SLOSH_DIR, decode_ft, close_raster, open_raster, pixel_value, value_at,
)

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(name)


print("class -> feet mapping")
check("class 1 (0-1 ft) -> 0", decode_ft(1, 255) == 0)
check("class 20 (19-20 ft) -> 19", decode_ft(20, 255) == 19)
check("class 21 (>20 ft) -> 20", decode_ft(21, 255) == 20)
check("99 -> leveed", decode_ft(99, 255) == "leveed")
check("nodata -> 0 (dry)", decode_ft(255, 255) == 0)
check("unexpected -> ''", decode_ft(200, 255) == "")

pr = sorted(SLOSH_DIR.glob("PR_Category*_MOM_Inundation_HighTide.tif"))
if not pr:
    print("\nPR rasters not found in data/raw/slosh/ — skipping reader "
          "validation (download PR_SLOSH_MOM_Inundation.zip to enable)")
    sys.exit(1 if FAILS else 0)

import tifffile  # noqa: E402

rng = np.random.default_rng(42)
for path, n_random, n_wet in [(pr[0], 100, 100), (pr[-1], 25, 25)]:
    print(f"\ntargeted reader vs tifffile.imread: {path.name}")
    ref = tifffile.imread(path)
    g = open_raster(path)
    check("shape agrees", (g["length"], g["width"]) == ref.shape,
          f"{ref.shape}")

    # random pixels anywhere + random pixels known to be inundated, so the
    # comparison is not dominated by the huge nodata ocean.
    rows = rng.integers(0, ref.shape[0], n_random)
    cols = rng.integers(0, ref.shape[1], n_random)
    wet = np.argwhere(ref != g["nodata"])
    pick = wet[rng.integers(0, len(wet), n_wet)]
    rows = np.concatenate([rows, pick[:, 0]])
    cols = np.concatenate([cols, pick[:, 1]])

    mism = 0
    for r, c in zip(rows, cols):
        if pixel_value(g, int(r), int(c)) != int(ref[r, c]):
            mism += 1
    check(f"{len(rows)} pixels match exactly", mism == 0,
          f"mismatches: {mism}")

    # geotransform round-trip: lat/lon of a pixel center must map back to it
    mism = 0
    for r, c in pick[:25]:
        lat = g["uly"] - (r + 0.5) * g["sy"]
        lon = g["ulx"] + (c + 0.5) * g["sx"]
        if value_at(g, lat, lon) != int(ref[r, c]):
            mism += 1
    check("lat/lon lookup matches at 25 wet pixel centers", mism == 0,
          f"mismatches: {mism}")

    check("out-of-bounds -> None", value_at(g, 0.0, 0.0) is None)
    close_raster(g)
    del ref

conus = sorted(SLOSH_DIR.glob("us_Category*_MOM_Inundation_HIGH.tif"))
if conus:
    # The 84-gigapixel CONUS BigTIFF cannot be imread; validate the LERC tile
    # path against tifffile's own segment decoder (page.decode) instead. The
    # tile-indexing/geotransform machinery is already proven exact on PR.
    path = conus[0]
    print(f"\ntargeted LERC reader vs tifffile page.decode: {path.name}")
    g = open_raster(path)
    page = g["tf"].pages[0]
    check("BigTIFF detected", g["bigtiff"])
    counts = np.asarray(g["counts"])
    nonempty = np.flatnonzero(counts > 0)
    pick = nonempty[rng.integers(0, len(nonempty), 40)]
    mism = 0
    for ti in pick:
        ti = int(ti)
        g["fh"].seek(g["offsets"][ti])
        ref = page.decode(g["fh"].read(counts[ti]), ti)[0].reshape(g["tl"], g["tw"])
        r = (ti // g["tiles_across"]) * g["tl"]
        c = (ti % g["tiles_across"]) * g["tw"]
        for dr, dc in [(0, 0), (17, 63), (127, 127), (64, 1)]:
            if pixel_value(g, r + dr, c + dc) != int(ref[dr, dc]):
                mism += 1
    check("160 pixels across 40 LERC tiles match", mism == 0,
          f"mismatches: {mism}")
    close_raster(g)
else:
    print("\nCONUS rasters not found — skipping LERC validation")

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S): {FAILS}")
    sys.exit(1)
print("all slosh checks passed")
