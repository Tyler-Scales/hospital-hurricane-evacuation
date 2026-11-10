#!/usr/bin/env python3
"""
Sanity checks for the hazard geometry primitives.

Run: python3 src/hazard/test_geometry.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geometry import (  # noqa: E402
    bearing_deg, haversine_nm, in_wind_field, interpolate_track,
    min_distance_to_track, quadrant_index,
)

FAILS = []


def check(name, got, want, tol=1e-6):
    ok = np.allclose(got, want, atol=tol)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got}, want {want}")
    if not ok:
        FAILS.append(name)


print("haversine")
# One degree of latitude is 60 nm by definition of the nautical mile.
check("1 deg lat == 60 nm", haversine_nm(0, 0, 1, 0), 60.0, tol=0.12)
check("identical points == 0", haversine_nm(29.95, -90.07, 29.95, -90.07), 0.0)
# One degree of longitude at 60N is 30 nm (cos 60 = 0.5).
check("1 deg lon at 60N == 30 nm", haversine_nm(60, 0, 60, 1), 30.0, tol=0.1)

print("\nbearing")
check("due north", bearing_deg(0, 0, 1, 0), 0.0, tol=1e-4)
check("due east", bearing_deg(0, 0, 0, 1), 90.0, tol=1e-4)
check("due south", bearing_deg(1, 0, 0, 0), 180.0, tol=1e-4)
check("due west", bearing_deg(0, 1, 0, 0), 270.0, tol=1e-4)

print("\nquadrant (NE=0 SE=1 SW=2 NW=3)")
check("bearings -> quadrants", quadrant_index([45, 135, 225, 315]), [0, 1, 2, 3])
check("boundaries", quadrant_index([0, 90, 180, 270, 359.9]), [0, 1, 2, 3, 3])

print("\nin_wind_field")
# Storm at origin. Hospital 0.5 deg north (30 nm) -> NE quadrant.
# NE radius 50 nm should capture it; NE radius 20 nm should not.
radii_big = np.array([[50.0, 50.0, 50.0, 50.0]])
radii_small = np.array([[20.0, 50.0, 50.0, 50.0]])
check("inside NE r=50", in_wind_field(0.5, 0.0, [0.0], [0.0], radii_big), [True])
check("outside NE r=20", in_wind_field(0.5, 0.0, [0.0], [0.0], radii_small), [False])
# Asymmetric field: hospital due SOUTH (SW/SE boundary -> bearing 180 = SE idx 1).
check("asymmetric quadrant respected",
      in_wind_field(-0.5, 0.0, [0.0], [0.0], radii_small), [True])
# A reported radius of 0 is a real zero-extent quadrant, not missing.
check("zero radius excludes",
      in_wind_field(0.5, 0.0, [0.0], [0.0], np.array([[0.0, 50, 50, 50]])), [False])
# NaN radii (pre-2004 HURDAT2) must not raise and must return False.
check("NaN radius -> False",
      in_wind_field(0.5, 0.0, [0.0], [0.0], np.array([[np.nan] * 4])), [False])

print("\nmin_distance_to_track")
check("closest of three fixes",
      min_distance_to_track(0.0, 0.0, [1.0, 0.25, 2.0], [0.0, 0.0, 0.0]),
      15.0, tol=0.05)

print("\ninterpolate_track")
la, lo, t = interpolate_track([0.0, 6.0], [0.0, 0.0], [0.0, 6.0], step_hours=1.0)
check("hourly densification length", len(t), 7)
check("midpoint interpolated", la[3], 3.0, tol=1e-9)

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S): {FAILS}")
    sys.exit(1)
print("all geometry checks passed")
