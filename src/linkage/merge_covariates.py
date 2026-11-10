#!/usr/bin/env python3
"""
Merge facility- and storm-level covariates into the dyad frame.

Adds, where available:
    elev_ft_usgs     USGS 3DEP ground elevation (street-geocoded only)
    fld_zone, sfha   FEMA NFHL flood zone / special-flood-hazard flag
    static_bfe       base flood elevation where published
    surge_cat1..5_ft SLOSH MOM inundation depth by storm category
    surge_any        inundated in >= 1 category
    rain_total_mm    PRISM storm-window rainfall at the hospital
    rain_max_daily_mm

Each source is optional: pipelines run on their own clocks, and this merges
whatever exists so the frame is always usable. Missing values stay empty rather
than being imputed — a hospital with no flood-zone lookup is unknown, not
out-of-floodplain, and the model must see that difference.

Output: data/interim/dyad_frame_full.csv

Usage:
    python3 src/linkage/merge_covariates.py
"""

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTER = REPO / "data" / "interim"
DYADS = INTER / "dyad_frame.csv"
OUT = INTER / "dyad_frame_full.csv"

SRC_ELEV = INTER / "hospital_elevation.csv"
SRC_FLOOD = INTER / "hospital_flood_zone.csv"
SRC_SURGE = INTER / "hospital_surge.csv"
SRC_RAIN = INTER / "rainfall.csv"
SRC_AGE = INTER / "hospital_plant_age.csv"

NEW_COLS = ["elev_ft_usgs", "fld_zone", "sfha", "static_bfe",
            "surge_cat1_ft", "surge_cat2_ft", "surge_cat3_ft",
            "surge_cat4_ft", "surge_cat5_ft", "surge_any",
            "rain_total_mm", "rain_max_daily_mm",
            "plant_age_years", "plant_age_fy"]

# Flex Monitoring / CAHMPAS exclusion rules for average age of plant: the ratio
# explodes when depreciation expense approaches zero (a handful of reports give
# ages in the millions of years), and negative ages are nonsensical.
AGE_MIN, AGE_MAX = 0.0, 60.0


def load_by_ccn(path, cols):
    """ccn -> {col: value}; returns {} if the pipeline has not produced output."""
    if not path.exists():
        print(f"  (absent) {path.name}")
        return {}
    out = {}
    with path.open() as fh:
        for r in csv.DictReader(fh):
            out[r["ccn"]] = {c: r.get(c, "") for c in cols if c in r}
    print(f"  {path.name}: {len(out)} hospitals")
    return out


def main():
    print("loading covariate sources:")
    elev = load_by_ccn(SRC_ELEV, ["elev_ft"])
    flood = load_by_ccn(SRC_FLOOD, ["fld_zone", "sfha", "static_bfe"])
    surge = load_by_ccn(SRC_SURGE, [f"surge_cat{i}_ft" for i in range(1, 6)])

    rain = {}
    if SRC_RAIN.exists():
        with SRC_RAIN.open() as fh:
            for r in csv.DictReader(fh):
                rain[(r["storm_id"], r["ccn"])] = (r["rain_total_mm"],
                                                   r["rain_max_daily_mm"])
        print(f"  rainfall.csv: {len(rain)} storm-hospital pairs")
    else:
        print("  (absent) rainfall.csv")

    # Plant age is time-varying: a hospital's capital age at Katrina differs
    # from its age at Milton, so each dyad takes the reporting year nearest
    # its storm year rather than a single current value.
    age = {}
    if SRC_AGE.exists():
        kept = 0
        with SRC_AGE.open() as fh:
            for r in csv.DictReader(fh):
                try:
                    v = float(r["avg_age_plant_years"])
                except (ValueError, TypeError):
                    continue
                if not (AGE_MIN < v <= AGE_MAX):
                    continue
                age.setdefault(r["ccn"], {})[int(r["fiscal_year"])] = v
                kept += 1
        print(f"  hospital_plant_age.csv: {len(age)} hospitals, {kept} usable obs")
    else:
        print("  (absent) hospital_plant_age.csv")

    rows = []
    with DYADS.open() as fh:
        reader = csv.DictReader(fh)
        base_cols = reader.fieldnames
        for r in reader:
            ccn = r["ccn"]
            e = elev.get(ccn, {})
            f = flood.get(ccn, {})
            s = surge.get(ccn, {})

            depths = [s.get(f"surge_cat{i}_ft", "") for i in range(1, 6)]
            numeric = [d for d in depths if d not in ("", "leveed")]
            any_surge = ""
            if numeric:
                any_surge = any(float(d) > 0 for d in numeric)
            elif "leveed" in depths:
                any_surge = "leveed"

            rn = rain.get((r["storm_id"], ccn), ("", ""))

            plant_age = plant_fy = ""
            by_year = age.get(ccn)
            if by_year:
                fy = min(by_year, key=lambda y: abs(y - int(r["year"])))
                plant_age, plant_fy = f"{by_year[fy]:.1f}", fy

            r.update({
                "elev_ft_usgs": e.get("elev_ft", ""),
                "fld_zone": f.get("fld_zone", ""),
                "sfha": f.get("sfha", ""),
                "static_bfe": f.get("static_bfe", ""),
                **{f"surge_cat{i}_ft": depths[i - 1] for i in range(1, 6)},
                "surge_any": any_surge,
                "rain_total_mm": rn[0],
                "rain_max_daily_mm": rn[1],
                "plant_age_years": plant_age,
                "plant_age_fy": plant_fy,
            })
            rows.append(r)

    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=base_cols + NEW_COLS)
        w.writeheader()
        w.writerows(rows)

    def cov(col):
        n = sum(1 for r in rows if r.get(col) not in ("", None))
        return f"{n:,} ({100*n/len(rows):.0f}%)"

    print(f"\ndyads: {len(rows):,}")
    for c in ("elev_ft_usgs", "fld_zone", "surge_cat3_ft", "rain_total_mm", "plant_age_years"):
        print(f"  {c:<16} {cov(c)}")
    labeled = [r for r in rows if r["action"]]
    print(f"  labeled dyads:   {len(labeled)}")
    print(f"\nWrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
