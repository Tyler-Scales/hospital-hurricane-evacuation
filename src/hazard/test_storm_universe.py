#!/usr/bin/env python3
"""
Regression test for US landfall attribution.

Landfall classification has two failure modes, both of which bit during
development and both of which are silent:

  FALSE NEGATIVE - a real landfall sits farther from the nearest coastline
    vertex than LANDFALL_NM, so it is dropped. Sparse sampling across Florida's
    Big Bend lost Idalia (2023) and Helene (2024, Cat 4); sparse south Texas
    lost Bret (1999).

  FALSE POSITIVE - a landfall on a nearby non-US landmass is attributed to the
    US. Grand Bahama is ~54 nm off Palm Beach, so Matthew's 2016 Bahamas
    landfall (115 kt) was recorded as a US major hurricane. Its actual US
    landfall was Cat 1 in South Carolina.

This test pins both directions against the NHC record.

Run: python3 src/hazard/test_storm_universe.py
"""

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UNIVERSE = REPO / "data" / "interim" / "storm_universe.csv"

# Continental US landfalls at Category 3 or stronger, 1990-2024, per NHC.
# 2025 is deliberately excluded so a new season cannot fail the test; any
# 2025 major landfall found is reported for human review instead.
EXPECTED_MAJOR = {
    (1992, "ANDREW"), (1995, "OPAL"), (1996, "FRAN"), (1999, "BRET"),
    (2004, "CHARLEY"), (2004, "IVAN"), (2004, "JEANNE"),
    (2005, "DENNIS"), (2005, "KATRINA"), (2005, "RITA"), (2005, "WILMA"),
    (2017, "HARVEY"), (2017, "IRMA"), (2018, "MICHAEL"),
    (2020, "LAURA"), (2020, "ZETA"), (2021, "IDA"), (2022, "IAN"),
    (2023, "IDALIA"), (2024, "HELENE"), (2024, "MILTON"),
}

# Storms that made a US landfall but BELOW Cat 3, and so must not appear in the
# major list. Matthew guards the Bahamas false positive specifically.
EXPECTED_NOT_MAJOR = {
    (2016, "MATTHEW"),   # US landfall was Cat 1, South Carolina
    (2008, "IKE"),       # Cat 2 at Galveston
    (2012, "SANDY"),     # post-tropical at New Jersey landfall
    (2018, "FLORENCE"),  # Cat 1 at North Carolina
    (2020, "SALLY"),     # Cat 2 at Gulf Shores
}

# Storms whose landfall intensity we pin exactly, in knots.
EXPECTED_VMAX = {
    (2005, "KATRINA"): 110,   # Buras, Louisiana - NOT the 70 kt Florida clip
    (2018, "MICHAEL"): 140,   # Mexico Beach, Cat 5
    (1992, "ANDREW"): 145,    # Homestead, Cat 5
    (2024, "HELENE"): 120,    # Big Bend, Cat 4
}


def main():
    if not UNIVERSE.exists():
        print(f"Missing {UNIVERSE}. Run storm_universe.py first.", file=sys.stderr)
        return 1

    rows = list(csv.DictReader(UNIVERSE.open()))
    majors, vmax_by_storm, all_lf = set(), {}, set()

    for r in rows:
        if not r["landfall_category"]:
            continue
        key = (int(r["year"]), r["name"].strip().upper())
        all_lf.add(key)
        vmax_by_storm[key] = int(r["landfall_vmax_kt"] or 0)
        if int(r["landfall_category"]) >= 3:
            majors.add(key)

    fails = []

    missing = EXPECTED_MAJOR - majors
    if missing:
        fails.append(f"MISSING major landfalls: {sorted(missing)}")

    wrong = majors & EXPECTED_NOT_MAJOR
    if wrong:
        fails.append(f"WRONGLY classified as major: {sorted(wrong)}")

    for key, want in EXPECTED_VMAX.items():
        got = vmax_by_storm.get(key)
        if got != want:
            fails.append(f"{key} landfall vmax: got {got} kt, want {want} kt")

    extra = {m for m in majors if m[0] <= 2024} - EXPECTED_MAJOR
    if extra:
        print(f"NOTE  unexpected pre-2025 majors (verify manually): {sorted(extra)}")
    extra_2025 = {m for m in majors if m[0] >= 2025}
    if extra_2025:
        print(f"NOTE  2025 majors found (not asserted): {sorted(extra_2025)}")

    print(f"\nmajor US landfalls found: {len(majors)}  (expected >= {len(EXPECTED_MAJOR)})")
    print(f"all US landfalling storms: {len(all_lf)}")

    if fails:
        print("\nFAILURES:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("\nall landfall attribution checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
