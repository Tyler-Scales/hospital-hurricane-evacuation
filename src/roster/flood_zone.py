#!/usr/bin/env python3
"""
FEMA flood zone per hospital via NFHL ArcGIS REST point queries (layer 28,
S_FLD_HAZ_AR). Street-geocoded hospitals only — a ZIP-centroid flood zone is
noise. Resumable (incremental cache), polite (~3 req/s), with the 30 m/100 m
distance fallback for polygon sliver gaps.

CAVEAT carried into analysis: NFHL is the CURRENTLY effective FIRM — a static
2026 snapshot, not the zone in effect at each historical storm. Treat as a
time-invariant physical-siting covariate.

Output: data/interim/hospital_flood_zone.csv
    ccn, fld_zone, zone_subty, sfha, static_bfe, query_tier

Usage:
    python3 src/roster/flood_zone.py
"""

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COORDS = REPO / "data" / "interim" / "hospital_coords.csv"
OUT = REPO / "data" / "interim" / "hospital_flood_zone.csv"
URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
UA = {"User-Agent": "NHHES-research/0.1 (academic use)"}
FIELDS = ["ccn", "fld_zone", "zone_subty", "sfha", "static_bfe", "query_tier"]


def query(lat, lon, distance=None):
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE",
        "returnGeometry": "false",
        "f": "json",
    }
    if distance:
        params["distance"] = str(distance)
        params["units"] = "esriSRUnit_Meter"
    for attempt in range(4):
        try:
            req = urllib.request.Request(URL + "?" + urllib.parse.urlencode(params),
                                         headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.loads(r.read())
            if "error" in d:
                raise RuntimeError(d["error"].get("message", "arcgis error"))
            return d.get("features", [])
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def main():
    done = {}
    if OUT.exists():
        with OUT.open() as fh:
            for r in csv.DictReader(fh):
                done[r["ccn"]] = r

    todo = []
    with COORDS.open() as fh:
        for r in csv.DictReader(fh):
            if r["method"] in ("census_street", "osm_name") and r["ccn"] not in done:
                todo.append(r)
    print(f"querying NFHL for {len(todo)} hospitals ({len(done)} cached)")

    n = 0
    for r in todo:
        lat, lon = float(r["lat"]), float(r["lon"])
        feats, tier = query(lat, lon), "point"
        if feats is not None and not feats:
            feats, tier = query(lat, lon, 30), "30m"
        if feats is not None and not feats:
            feats, tier = query(lat, lon, 100), "100m"

        if feats:
            a = feats[0].get("attributes", {})
            row = {"ccn": r["ccn"], "fld_zone": a.get("FLD_ZONE") or "",
                   "zone_subty": a.get("ZONE_SUBTY") or "",
                   "sfha": a.get("SFHA_TF") or "",
                   "static_bfe": a.get("STATIC_BFE") if a.get("STATIC_BFE", -9999) != -9999 else "",
                   "query_tier": tier}
        else:
            row = {"ccn": r["ccn"], "fld_zone": "", "zone_subty": "",
                   "sfha": "", "static_bfe": "",
                   "query_tier": "failed" if feats is None else "no_polygon"}
        done[r["ccn"]] = row
        n += 1
        if n % 200 == 0:
            _flush(done)
            print(f"  {n}/{len(todo)}", flush=True)
        time.sleep(0.30)

    _flush(done)
    got = sum(1 for r in done.values() if r["fld_zone"])
    sfha = sum(1 for r in done.values() if r["sfha"] == "T")
    print(f"\nzones resolved: {got}/{len(done)}  (SFHA=True: {sfha})")
    print(f"Wrote {OUT.relative_to(REPO)}")
    return 0


def _flush(done):
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(done.values())


if __name__ == "__main__":
    sys.exit(main())
