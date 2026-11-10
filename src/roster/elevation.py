#!/usr/bin/env python3
"""
Ground elevation (feet) for every geocoded hospital, via the USGS Elevation
Point Query Service (3DEP). Results cached incrementally so the script is
resumable; EPQS is public, keyless, and occasionally flaky, hence retries and
a tolerant failure mode (missing elevations are recorded as empty, and only
street-precise coordinates get an elevation at all — ZIP centroids can sit on
a hill two miles from the hospital, and a wrong elevation is worse than none
for surge reasoning).

Output: data/interim/hospital_elevation.csv  (ccn, lat, lon, elev_ft, method)

Usage:
    python3 src/roster/elevation.py [--workers 6]
"""

import argparse
import csv
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COORDS = REPO / "data" / "interim" / "hospital_coords.csv"
OUT = REPO / "data" / "interim" / "hospital_elevation.csv"
EPQS = "https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&wkid=4326&units=Feet&includeDate=false"
UA = {"User-Agent": "NHHES-research/0.1 (academic use)"}


def query(lat, lon, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(EPQS.format(lat=lat, lon=lon), headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
            v = d.get("value")
            if v is not None and v != "":
                return float(v)
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    done = {}
    if OUT.exists():
        with OUT.open() as fh:
            for r in csv.DictReader(fh):
                done[r["ccn"]] = r

    todo = []
    with COORDS.open() as fh:
        for r in csv.DictReader(fh):
            if r["ccn"] in done:
                continue
            if r["method"] not in ("census_street", "osm_name"):
                done[r["ccn"]] = {"ccn": r["ccn"], "lat": r["lat"], "lon": r["lon"],
                                  "elev_ft": "", "method": r["method"]}
                continue
            todo.append(r)

    print(f"querying elevation for {len(todo)} street-geocoded hospitals "
          f"({len(done)} already resolved/skipped)")

    def work(r):
        e = query(float(r["lat"]), float(r["lon"]))
        return {"ccn": r["ccn"], "lat": r["lat"], "lon": r["lon"],
                "elev_ft": f"{e:.1f}" if e is not None else "",
                "method": r["method"]}

    n = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for row in ex.map(work, todo):
            done[row["ccn"]] = row
            n += 1
            if n % 250 == 0:
                _flush(done)
                print(f"  {n}/{len(todo)}", flush=True)

    _flush(done)
    got = sum(1 for r in done.values() if r["elev_ft"] != "")
    print(f"\nelevations resolved: {got}/{len(done)}")
    print(f"Wrote {OUT.relative_to(REPO)}")
    return 0


def _flush(done):
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["ccn", "lat", "lon", "elev_ft", "method"])
        w.writeheader()
        w.writerows(done.values())


if __name__ == "__main__":
    sys.exit(main())
