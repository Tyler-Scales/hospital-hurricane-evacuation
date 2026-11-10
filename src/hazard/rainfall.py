#!/usr/bin/env python3
"""
Storm-total rainfall at each hospital, from PRISM daily 4 km precipitation.

Method (per the Phase 1 source scout, all endpoints verified):
  1. For every screened storm, define the storm window: calendar days on which
     the HURDAT2 center sits inside the CONUS-influence box (22-50N, 107-60W),
     padded +1 day on each side (PRISM days are 12Z-12Z accumulations labeled
     by period END date, so trailing rain lands on the next label).
  2. Download each needed day once (deduped across storms) from
     data.prism.oregonstate.edu; ~1 MB per day, LZW GeoTIFF inside a zip.
  3. Read grids with tifffile; index every dyad hospital's (row, col) with
     numpy; sum across the window.

Grid constants (from PRISM metadata, verified): 621 x 1405, cell 1/24 deg,
upper-left corner ULX=-125.0208333, ULY=49.9375, values mm, nodata -9999.

Output: data/interim/rainfall.csv  (storm_id, ccn, rain_total_mm,
        rain_max_daily_mm, n_days) — only for pairs present in dyad_frame.csv.

CONUS only; PR/USVI hospitals get no value. 4 km cell means undershoot extreme
gauge bullseyes (Katrina check: ~10.4 in cell-max vs 16.43 in gauge) — fine for
relative exposure across hospitals, not for absolute thresholds.

Usage:
    python3 src/hazard/rainfall.py [--sleep 0.5]
"""

import argparse
import csv
import io
import sys
import time
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
TRACKS = REPO / "data" / "interim" / "hurdat2_tracks.csv"
UNIVERSE = REPO / "data" / "interim" / "storm_universe.csv"
DYADS = REPO / "data" / "interim" / "dyad_frame.csv"
COORDS = REPO / "data" / "interim" / "hospital_coords.csv"
CACHE = REPO / "data" / "raw" / "prism"
OUT = REPO / "data" / "interim" / "rainfall.csv"

PRISM = "https://data.prism.oregonstate.edu/time_series/us/an/4km/ppt/daily/{y}/prism_ppt_us_25m_{ymd}.zip"
UA = {"User-Agent": "NHHES-research/0.1 (academic use; contact tyler.wallace@scalestreet.com)"}
ULX, ULY, CELL = -125.0208333, 49.9375, 1.0 / 24.0
NROW, NCOL = 621, 1405
BOX = (22.0, 50.0, -107.0, -60.0)   # lat_min, lat_max, lon_min, lon_max


def storm_windows():
    """storm_id -> sorted list of YYYYMMDD PRISM labels."""
    pos = defaultdict(list)
    with TRACKS.open() as fh:
        for r in csv.DictReader(fh):
            pos[r["storm_id"]].append((r["date"], float(r["lat"]), float(r["lon"])))
    keep = {r["storm_id"] for r in csv.DictReader(UNIVERSE.open())
            if r["passes_screen"] == "True"}

    win = {}
    for sid, obs in pos.items():
        if sid not in keep:
            continue
        days = {d for d, la, lo in obs
                if BOX[0] <= la <= BOX[1] and BOX[2] <= lo <= BOX[3]}
        if not days:
            continue
        padded = set()
        for d in days:
            dt = datetime.strptime(d, "%Y%m%d")
            for k in (-1, 0, 1):
                padded.add((dt + timedelta(days=k)).strftime("%Y%m%d"))
        win[sid] = sorted(padded)
    return win


def fetch_day(ymd):
    dest = CACHE / ymd[:4] / f"{ymd}.zip"
    if dest.exists() and dest.stat().st_size > 10000:
        return dest
    url = PRISM.format(y=ymd[:4], ymd=ymd)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
            if len(raw) < 10000:
                return None
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            return dest
        except Exception:
            time.sleep(4 * (attempt + 1))
    return None


def read_grid(path):
    import tifffile
    with zipfile.ZipFile(path) as z:
        tifs = [n for n in z.namelist() if n.lower().endswith((".tif", ".tiff"))]
        if not tifs:
            return None
        with z.open(tifs[0]) as fh:
            arr = tifffile.imread(io.BytesIO(fh.read()))
    return arr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    coords = {}
    with COORDS.open() as fh:
        for r in csv.DictReader(fh):
            coords[r["ccn"]] = (float(r["lat"]), float(r["lon"]))

    pairs = defaultdict(set)   # storm_id -> {ccn}
    with DYADS.open() as fh:
        for r in csv.DictReader(fh):
            if r["ccn"] in coords:
                pairs[r["storm_id"]].add(r["ccn"])

    win = storm_windows()
    need_days = sorted({d for sid in pairs for d in win.get(sid, ())})
    print(f"storms with dyads: {len(pairs)}; unique PRISM days needed: {len(need_days)}")

    # precompute row/col per ccn
    rc = {}
    for ccn, (la, lo) in coords.items():
        col = int((lo - ULX) / CELL)
        row = int((ULY - la) / CELL)
        if 0 <= row < NROW and 0 <= col < NCOL:
            rc[ccn] = (row, col)

    # accumulate: day -> grid read once; add into per-(storm,ccn) sums
    day_users = defaultdict(list)   # ymd -> [storm_id]
    for sid in pairs:
        for d in win.get(sid, ()):
            day_users[d].append(sid)

    total = defaultdict(float)
    daymax = defaultdict(float)
    ndays = defaultdict(int)
    missing_days = 0

    for i, ymd in enumerate(need_days):
        path = fetch_day(ymd)
        if path is None:
            missing_days += 1
            continue
        grid = read_grid(path)
        if grid is None:
            missing_days += 1
            continue
        for sid in day_users[ymd]:
            for ccn in pairs[sid]:
                p = rc.get(ccn)
                if p is None:
                    continue
                v = float(grid[p[0], p[1]])
                if v < 0:      # nodata
                    continue
                key = (sid, ccn)
                total[key] += v
                daymax[key] = max(daymax[key], v)
                ndays[key] += 1
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(need_days)} days processed", flush=True)
        time.sleep(args.sleep)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["storm_id", "ccn", "rain_total_mm", "rain_max_daily_mm", "n_days"])
        for (sid, ccn), t in sorted(total.items()):
            w.writerow([sid, ccn, f"{t:.1f}", f"{daymax[(sid, ccn)]:.1f}",
                        ndays[(sid, ccn)]])

    print(f"\npairs with rainfall: {len(total):,}   missing days: {missing_days}")
    print(f"Wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
