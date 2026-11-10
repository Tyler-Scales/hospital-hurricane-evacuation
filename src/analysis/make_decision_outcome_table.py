#!/usr/bin/env python3
"""Pair-level table of every documented decision with its outcome.

One row per labeled hospital-storm pair (n=214): the decision, what the storm
actually delivered at that hospital, the facility's physical setting, and for
failures the hand-coded mechanism. Sorted chronologically by storm.

Writes Final/decision_outcome_table.csv and .xlsx.
"""
import pandas as pd
import numpy as np
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "Final" / "decision_outcome_table.csv"

CATEGORY = {
    "SIP_OK": "Sheltered successfully",
    "POST_FSIP": "Failed shelter-in-place",
    "PRE_FULL": "Evacuated before landfall (full)",
    "PRE_PARTIAL": "Evacuated before landfall (partial)",
    "UNCLEAR": "Unclear",
}


def main():
    d = pd.read_csv(REPO / "Final" / "hospital_storm_dyads.csv",
                    usecols=["storm", "year", "ccn", "name", "state", "action", "in34", "in64",
                             "vmax_close_kt", "min_track_nm", "rain_total_mm", "surge_cat3_ft",
                             "elev_ft_usgs", "beds"])
    lab = d[d.action.notna() & d.action.astype(str).ne("")].copy()
    for c in ("in34", "in64"):
        lab[c] = lab[c].astype(str).str.lower().isin(["true", "1", "1.0"])
    num = lambda s: pd.to_numeric(s, errors="coerce")

    lab["category"] = lab.action.map(CATEGORY)
    # HURDAT2 wind radii begin in 2004; before that, membership is not determinable
    lab["storm_delivered"] = np.where(
        lab.year < 2004, "Not determinable (HURDAT2 wind radii begin 2004)",
        np.where(~lab.in34, "No TS-force winds reached the hospital",
                 np.where(lab.in64, "Hurricane-force winds", "TS-force winds only")))
    lab["surge_zone"] = np.where(
        lab.surge_cat3_ft.astype(str) == "leveed", "levee-protected",
        np.where(num(lab.surge_cat3_ft).fillna(0) > 0, "Cat-3 surge zone", "outside surge zone"))

    # failure mechanisms, keyed on CCN + storm + year (multi-campus pairs get the union)
    mech = pd.read_csv(REPO / "data" / "registry" / "fsip_mechanisms.csv").dropna(subset=["ccn"])
    key = lambda df: (df.ccn.astype(str).str.strip() + "|"
                      + df.storm.str.upper().str.strip() + "|" + df.year.astype(str))
    mech["_k"] = key(mech)
    agg = (mech.groupby("_k").mechanisms
           .apply(lambda s: "; ".join(sorted({m for row in s for m in str(row).split("|")})))
           .reset_index())
    lab["_k"] = key(lab)
    lab = lab.merge(agg, on="_k", how="left")

    # storm start date, for chronological ordering
    t = pd.read_csv(REPO / "data" / "interim" / "hurdat2_tracks.csv",
                    usecols=["storm_name", "date"])
    t["year"] = t.date.astype(str).str[:4].astype(int)
    start = (t.groupby(["storm_name", "year"]).date.min().reset_index()
             .rename(columns={"date": "storm_start"}))
    start["_sn"] = start.storm_name.str.upper().str.strip()
    start["storm_date"] = pd.to_datetime(start.storm_start, format="%Y%m%d").dt.strftime("%Y-%m-%d")
    lab["_sn"] = lab.storm.str.upper().str.strip()
    lab = lab.merge(start[["_sn", "year", "storm_date"]], on=["_sn", "year"], how="left")
    assert lab.storm_date.notna().all(), "some storms did not match a HURDAT2 start date"

    out = (lab[["storm_date", "storm", "year", "name", "state", "ccn", "category",
                "storm_delivered", "vmax_close_kt", "min_track_nm", "rain_total_mm",
                "elev_ft_usgs", "surge_zone", "beds", "mechanisms"]]
           .rename(columns={"name": "hospital", "vmax_close_kt": "storm_intensity_kt",
                            "min_track_nm": "closest_approach_nmi", "rain_total_mm": "storm_rain_mm",
                            "elev_ft_usgs": "elevation_ft", "mechanisms": "failure_mechanisms"})
           .sort_values(["storm_date", "storm", "category", "hospital"]))
    out.to_csv(OUT, index=False)
    try:
        out.to_excel(OUT.with_suffix(".xlsx"), index=False)
    except Exception as e:  # openpyxl not installed
        print(f"xlsx skipped: {e}")
    print(f"wrote {OUT.relative_to(REPO)} — {len(out)} pairs, "
          f"{out.storm.nunique()} storms, {out.category.nunique()} categories")
    print(out.category.value_counts().to_string())


if __name__ == "__main__":
    main()
