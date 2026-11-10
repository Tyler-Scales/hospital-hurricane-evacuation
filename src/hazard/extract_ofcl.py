#!/usr/bin/env python3
"""
Download and parse every Atlantic ATCF a-deck into a tidy OFCL forecast table.

This is the decision-time information set: for each storm, each advisory cycle,
and each forecast lead (TAU), the official NHC forecast position and intensity.
Everything downstream that grades a hospital's decision against what was
knowable at T-48h reads from this table.

ATCF a-deck columns (comma-delimited, positional):
   0 BASIN      1 CY         2 YYYYMMDDHH (advisory/warning time)
   3 TECHNUM    4 TECH       5 TAU (forecast lead, hours)
   6 LatN/S     7 LonE/W     8 VMAX (kt)   9 MSLP (mb)   10 TY (dev level)
  11 RAD       12 WINDCODE  13-16 RAD1-4 (quadrant wind radii, nm)

Lat/lon are TENTHS of a degree with a hemisphere suffix ("232N" -> 23.2N).

OFCL rows repeat per wind-radius threshold (34/50/64 kt) for the same TAU, so
the same forecast position appears up to three times. We keep one row per
(storm, cycle, tau) and carry the 34-kt quadrant radii where present.

Raw files are cached under data/raw/atcf/ so reruns are offline.

Usage:
    python3 src/hazard/extract_ofcl.py                 # 1990-2025, all AL storms
    python3 src/hazard/extract_ofcl.py --start 2004 --end 2005
    python3 src/hazard/extract_ofcl.py --no-download   # parse cache only
"""

import argparse
import csv
import gzip
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ARCHIVE = "https://ftp.nhc.noaa.gov/atcf/archive"
TIMEOUT = 90
UA = {"User-Agent": "NHHES-research/0.1 (academic use)"}

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "raw" / "atcf"
OUT = REPO / "data" / "interim" / "ofcl_forecasts.csv"

FIELDS = ["storm_id", "cycle", "tau", "lat", "lon", "vmax_kt", "mslp_mb",
          "dev_level", "r34_ne", "r34_se", "r34_sw", "r34_nw"]


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ! {url}: {e}", file=sys.stderr)
                return None
    return None


def list_year(year):
    body = fetch(f"{ARCHIVE}/{year}/")
    if body is None:
        return []
    text = body.decode("utf-8", "replace")
    return sorted({m.group(0) for m in re.finditer(r"aal\d{6}\.dat\.gz", text)})


def ensure_cached(year, fname, download=True):
    """Return path to cached a-deck, downloading if needed."""
    dest = CACHE / str(year) / fname
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    if not download:
        return None
    raw = fetch(f"{ARCHIVE}/{year}/{fname}")
    if raw is None:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return dest


def _coord(tok):
    """'232N' -> 23.2 ; '751W' -> -75.1 ; returns None if unparseable."""
    tok = tok.strip()
    if len(tok) < 2 or tok[-1] not in "NSEW":
        return None
    try:
        val = int(tok[:-1]) / 10.0
    except ValueError:
        return None
    return -val if tok[-1] in "WS" else val


def _int(tok):
    tok = tok.strip()
    if not tok:
        return None
    try:
        v = int(tok)
    except ValueError:
        return None
    # ATCF uses 0 as "not reported" for MSLP/radii in many vintages; keep 0
    # for radii (a real zero-extent quadrant) but treat -999 as missing.
    return None if v == -999 else v


def parse_adeck(path):
    """Yield one dict per (cycle, tau) OFCL forecast."""
    try:
        with gzip.open(path, "rt", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return []

    storm_id = path.name[1:9].upper()  # aal122005.dat.gz -> AL122005
    best = {}  # (cycle, tau) -> row

    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 11 or parts[4] != "OFCL":
            continue

        cycle, tau = parts[2], _int(parts[5])
        lat, lon = _coord(parts[6]), _coord(parts[7])
        if tau is None or lat is None or lon is None:
            continue

        key = (cycle, tau)
        row = best.get(key)
        if row is None:
            row = {
                "storm_id": storm_id,
                "cycle": cycle,
                "tau": tau,
                "lat": lat,
                "lon": lon,
                "vmax_kt": _int(parts[8]),
                "mslp_mb": _int(parts[9]),
                "dev_level": parts[10] if len(parts) > 10 else "",
                "r34_ne": None, "r34_se": None, "r34_sw": None, "r34_nw": None,
            }
            best[key] = row

        # Attach 34-kt quadrant radii when this line carries them.
        rad = _int(parts[11]) if len(parts) > 11 else None
        wcode = parts[12] if len(parts) > 12 else ""
        if rad == 34 and wcode == "NEQ" and len(parts) > 16:
            for i, q in enumerate(("r34_ne", "r34_se", "r34_sw", "r34_nw")):
                row[q] = _int(parts[13 + i])

    return list(best.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1990)
    ap.add_argument("--end", type=int, default=2025)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()

    download = not args.no_download

    jobs = []
    for year in range(args.start, args.end + 1):
        if download:
            names = list_year(year)
        else:
            ydir = CACHE / str(year)
            names = sorted(p.name for p in ydir.glob("aal*.dat.gz")) if ydir.exists() else []
        jobs.extend((year, n) for n in names)
    print(f"{len(jobs)} a-deck files across {args.end - args.start + 1} years")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        paths = list(ex.map(lambda j: ensure_cached(j[0], j[1], download), jobs))
    paths = [p for p in paths if p is not None]
    print(f"{len(paths)} cached locally")

    rows = []
    for p in paths:
        rows.extend(parse_adeck(p))
    rows.sort(key=lambda r: (r["storm_id"], r["cycle"], r["tau"]))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    storms = {r["storm_id"] for r in rows}
    cycles = {(r["storm_id"], r["cycle"]) for r in rows}
    with_radii = sum(1 for r in rows if r["r34_ne"] is not None)
    print(f"\nstorms:            {len(storms)}")
    print(f"advisory cycles:   {len(cycles):,}")
    print(f"forecast rows:     {len(rows):,}")
    print(f"rows w/ 34kt radii:{with_radii:,} ({100*with_radii/len(rows):.0f}%)")
    print(f"\nWrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
