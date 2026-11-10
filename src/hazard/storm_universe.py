#!/usr/bin/env python3
"""
Build the storm-level universe for NHHES.

Produces one row per Atlantic storm 1990-2025 with the attributes needed to
decide whether it enters the study, plus landfall characterisation for the
descriptive tier.

Screening note: this is a COARSE screen, deliberately generous. Final cohort
membership is decided by the hospital join in src/linkage/, where a dyad is
included if the hospital sits inside the realized 34-kt swath or the T-48h
forecast cone. A storm passes the screen here if any best-track point comes
within SCREEN_NM of the US Atlantic/Gulf coastline, which keeps coast-parallel
storms that never made landfall but still put hospitals in tropical-storm-force
winds. Those are genuine decision events and dropping them would bias the
calibration analysis toward hindsight.

Usage:
    python3 src/hazard/storm_universe.py
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geometry import haversine_nm  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
TRACKS = REPO / "data" / "interim" / "hurdat2_tracks.csv"
OFCL = REPO / "data" / "interim" / "ofcl_forecasts.csv"
OUT = REPO / "data" / "interim" / "storm_universe.csv"

SCREEN_NM = 300.0

# US Atlantic/Gulf coastline, Texas-Mexico border to Eastport, Maine.
# Used ONLY for storm screening and landfall attribution, never for exposure.
#
# Vertex spacing must stay well under LANDFALL_NM or real landfalls fall
# outside the radius and are silently dropped. Concave stretches need the most
# vertices: sparse sampling across Florida's Big Bend originally lost Idalia
# (2023) and Helene (2024, Cat 4), and sparse south Texas lost Bret (1999).
# test_storm_universe.py locks this against regression.
US_COAST = [
    # South and central Texas
    (-97.15, 25.95), (-97.35, 26.50), (-97.40, 27.00), (-97.30, 27.40),
    (-97.40, 27.80), (-96.80, 28.20), (-96.00, 28.60), (-95.30, 28.90),
    # Upper Texas and Louisiana
    (-94.80, 29.30), (-93.90, 29.70), (-93.30, 29.80), (-92.50, 29.60),
    (-91.80, 29.50), (-91.00, 29.20), (-90.00, 29.20), (-89.40, 29.30),
    (-89.00, 29.00),
    # Mississippi, Alabama, Florida panhandle
    (-89.10, 30.40), (-88.00, 30.25), (-87.20, 30.35), (-86.50, 30.40),
    (-85.70, 30.15), (-85.30, 29.90), (-85.00, 29.70),
    # Florida Big Bend (concave: densely sampled)
    (-84.40, 29.90), (-84.00, 30.10), (-83.60, 29.90), (-83.40, 29.60),
    (-83.10, 29.30), (-83.00, 29.10),
    # Florida west coast and Keys
    (-82.80, 28.10), (-82.60, 27.30), (-82.20, 26.90), (-82.00, 26.50),
    (-81.80, 26.10), (-81.40, 25.70), (-81.10, 25.10), (-81.80, 24.55),
    # Florida east coast
    (-80.10, 25.80), (-80.00, 26.70), (-80.10, 27.50), (-80.50, 28.40),
    (-80.90, 29.20), (-81.40, 30.30),
    # Georgia and the Carolinas
    (-81.20, 31.20), (-80.80, 32.00), (-79.80, 32.80), (-79.20, 33.20),
    (-78.90, 33.70), (-78.00, 33.80), (-77.30, 34.30), (-76.50, 34.60),
    (-75.90, 35.00), (-75.50, 35.20), (-75.70, 35.90), (-76.00, 36.90),
    # Mid-Atlantic
    (-75.50, 37.60), (-75.10, 38.30), (-74.90, 38.90), (-74.40, 39.40),
    (-74.10, 40.00), (-74.00, 40.50),
    # New England
    (-72.80, 40.80), (-72.00, 41.00), (-71.40, 41.50), (-70.60, 41.60),
    (-70.00, 41.80), (-70.90, 42.40), (-70.60, 43.00), (-70.20, 43.70),
    (-69.20, 44.10), (-68.20, 44.40), (-67.50, 44.70), (-67.00, 44.90),
]
COAST_LON = np.array([p[0] for p in US_COAST])
COAST_LAT = np.array([p[1] for p in US_COAST])

SS = [(137, 5), (113, 4), (96, 3), (83, 2), (64, 1)]  # Saffir-Simpson, kt

LANDFALL_NM = 50.0

# Non-US landmasses close enough to the US coast that a pure distance test
# misattributes their landfalls. Grand Bahama sits ~54 nm off Palm Beach, so
# Matthew's 2016 Bahamas landfall (115 kt) was being recorded as a US landfall;
# its actual US landfall was Cat 1 in South Carolina. Boxes are (lon_min,
# lon_max, lat_min, lat_max). The Bahamas box stops at lon -79.5, safely east
# of the entire US mainland at those latitudes (Palm Beach is -80.05).
EXCLUDE_BOXES = {
    "bahamas": (-79.5, -72.5, 20.5, 27.5),
    "cuba_hispaniola": (-85.0, -68.0, 17.0, 23.5),
    "yucatan_mexico": (-98.0, -86.5, 15.0, 22.0),
    "atlantic_canada": (-70.0, -52.0, 45.0, 60.0),
}


def in_excluded_region(lat, lon):
    for lon_min, lon_max, lat_min, lat_max in EXCLUDE_BOXES.values():
        if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
            return True
    return False


def dist_to_us_coast(lat, lon):
    """Minimum distance in nm from a point to the coarse US coastline."""
    return float(np.min(haversine_nm(COAST_LAT, COAST_LON, lat, lon)))


def is_us_landfall(lat, lon):
    """A landfall counts as US if it is near the US coast and not on a
    neighbouring landmass that happens to lie within the same radius."""
    if in_excluded_region(lat, lon):
        return False
    return dist_to_us_coast(lat, lon) <= LANDFALL_NM


def saffir_simpson(vmax_kt):
    if vmax_kt is None:
        return None
    for thresh, cat in SS:
        if vmax_kt >= thresh:
            return cat
    return 0  # tropical storm or weaker


def load_tracks():
    storms = defaultdict(list)
    with TRACKS.open() as fh:
        for r in csv.DictReader(fh):
            storms[r["storm_id"]].append(r)
    return storms


def load_ofcl_cycles():
    counts = defaultdict(set)
    if not OFCL.exists():
        return counts
    with OFCL.open() as fh:
        for r in csv.DictReader(fh):
            counts[r["storm_id"]].add(r["cycle"])
    return counts


def main():
    if not TRACKS.exists():
        print(f"Missing {TRACKS}. Run parse_hurdat2.py first.", file=sys.stderr)
        return 1

    storms = load_tracks()
    ofcl = load_ofcl_cycles()
    rows = []

    for storm_id, obs in sorted(storms.items()):
        lats = np.array([float(o["lat"]) for o in obs])
        lons = np.array([float(o["lon"]) for o in obs])
        vmax = [int(o["vmax_kt"]) for o in obs if o["vmax_kt"]]

        coast_d = np.array([dist_to_us_coast(la, lo) for la, lo in zip(lats, lons)])
        min_coast = float(coast_d.min())

        # Landfalls: HURDAT2 record_id 'L' marks the center crossing a coastline.
        us_lf = [o for o in obs
                 if o["record_id"].strip() == "L"
                 and is_us_landfall(float(o["lat"]), float(o["lon"]))]

        # Report BOTH first and peak landfall. Reporting only the first badly
        # understates storms that clip one coast weakly then strike another
        # hard: Katrina's first US landfall was 70 kt in Florida, four days
        # before the 110 kt Louisiana landfall that defines the event.
        first_lf = us_lf[0] if us_lf else None
        peak_lf = max(us_lf, key=lambda o: int(o["vmax_kt"] or 0)) if us_lf else None
        first_vmax = int(first_lf["vmax_kt"]) if first_lf and first_lf["vmax_kt"] else None
        peak_vmax_lf = int(peak_lf["vmax_kt"]) if peak_lf and peak_lf["vmax_kt"] else None

        has_radii = any(o["r34_ne"] for o in obs)

        rows.append({
            "storm_id": storm_id,
            "name": obs[0]["storm_name"].strip(),
            "year": int(obs[0]["date"][:4]),
            "start_date": obs[0]["date"],
            "end_date": obs[-1]["date"],
            "n_obs": len(obs),
            "peak_vmax_kt": max(vmax) if vmax else None,
            "peak_category": saffir_simpson(max(vmax)) if vmax else None,
            "min_dist_us_coast_nm": round(min_coast, 1),
            "passes_screen": min_coast <= SCREEN_NM,
            "us_landfalls": len(us_lf),
            "first_us_landfall": first_lf["date"] + first_lf["time"] if first_lf else "",
            "first_landfall_vmax_kt": first_vmax,
            "peak_us_landfall": peak_lf["date"] + peak_lf["time"] if peak_lf else "",
            "landfall_vmax_kt": peak_vmax_lf,
            "landfall_category": saffir_simpson(peak_vmax_lf) if peak_vmax_lf else None,
            "has_wind_radii": has_radii,
            "n_ofcl_cycles": len(ofcl.get(storm_id, ())),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # Summary
    screened = [r for r in rows if r["passes_screen"]]
    landfalling = [r for r in rows if r["us_landfalls"] > 0]
    hur_lf = [r for r in landfalling if (r["landfall_category"] or 0) >= 1]
    major_lf = [r for r in landfalling if (r["landfall_category"] or 0) >= 3]
    no_fcst = [r for r in screened if r["n_ofcl_cycles"] == 0]

    print(f"Atlantic storms 1990-2025:        {len(rows)}")
    print(f"  pass {SCREEN_NM:.0f} nm US coast screen:  {len(screened)}")
    print(f"  with >=1 US landfall:           {len(landfalling)}")
    print(f"    landfall at hurricane force:  {len(hur_lf)}")
    print(f"    landfall as major (Cat 3+):   {len(major_lf)}")
    print(f"  screened but NO OFCL forecasts: {len(no_fcst)}")

    print("\nScreened storms by tier:")
    t1 = [r for r in screened if r["year"] <= 2003]
    t2 = [r for r in screened if r["year"] >= 2004]
    print(f"  Tier 1 descriptive (1990-2003): {len(t1)}")
    print(f"  Tier 2 analytic    (2004-2025): {len(t2)}")

    print("\nMajor-hurricane US landfalls (Cat 3+), for verification:")
    for r in sorted(major_lf, key=lambda x: x["year"]):
        print(f"  {r['year']}  {r['name']:<12} {r['storm_id']}  "
              f"landfall {r['landfall_vmax_kt']}kt (Cat {r['landfall_category']})  "
              f"{r['n_ofcl_cycles']} advisory cycles")

    print(f"\nWrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
