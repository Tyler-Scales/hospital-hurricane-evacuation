#!/usr/bin/env python3
"""
Empirical NHC track-forecast error, by lead time and era.

Why not use the published NHC cone: the official cone radius is set annually
from the prior five years of errors, so replicating it across 1990-2025 means
sourcing and validating 36 separate published tables. We already hold both the
forecasts (OFCL a-decks) and the verifying positions (HURDAT2), so the error
distribution can be computed directly. That is reproducible from the repo
alone, and it is era-correct by construction: forecast skill improved
enormously over the study period, and a hospital deciding in 1995 faced far
more positional uncertainty at 48 h than one deciding in 2022.

NHC's cone is the 2/3-probability circle, so the 67th percentile of error is
the directly comparable statistic and is reported as `p67_nm`.

This feeds the dyad frame as the uncertainty covariate paired with forecast
distance: a hospital 80 nm off the forecast track faced very different risk in
1995 than in 2022, and the model must see that.

Usage:
    python3 src/hazard/forecast_error.py
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geometry import haversine_nm  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
TRACKS = REPO / "data" / "interim" / "hurdat2_tracks.csv"
OFCL = REPO / "data" / "interim" / "ofcl_forecasts.csv"
OUT = REPO / "data" / "interim" / "forecast_error.csv"

EPOCH = datetime(1970, 1, 1)
STANDARD_TAUS = [12, 24, 36, 48, 72, 96, 120]
ERAS = [(1990, 1999), (2000, 2009), (2010, 2017), (2018, 2025)]


def to_hours(dt):
    return (dt - EPOCH).total_seconds() / 3600.0


def load_actual_tracks():
    """storm_id -> (hours[], lat[], lon[]) sorted by time, for interpolation."""
    raw = defaultdict(list)
    with TRACKS.open() as fh:
        for r in csv.DictReader(fh):
            dt = datetime.strptime(r["date"] + r["time"], "%Y%m%d%H%M")
            raw[r["storm_id"]].append((to_hours(dt), float(r["lat"]), float(r["lon"])))

    out = {}
    for sid, pts in raw.items():
        pts.sort()
        h = np.array([p[0] for p in pts])
        # Landfall records share a timestamp with synoptic fixes in some
        # vintages; np.interp requires strictly increasing x.
        keep = np.concatenate(([True], np.diff(h) > 0))
        out[sid] = (h[keep],
                    np.array([p[1] for p in pts])[keep],
                    np.array([p[2] for p in pts])[keep])
    return out


def main():
    for p in (TRACKS, OFCL):
        if not p.exists():
            print(f"Missing {p}", file=sys.stderr)
            return 1

    actual = load_actual_tracks()
    records = []

    with OFCL.open() as fh:
        for r in csv.DictReader(fh):
            tau = int(r["tau"])
            if tau <= 0:
                continue
            sid = r["storm_id"]
            if sid not in actual:
                continue

            cycle = datetime.strptime(r["cycle"], "%Y%m%d%H")
            verify_h = to_hours(cycle + timedelta(hours=tau))
            h, la, lo = actual[sid]
            # Only verify inside the observed track window; extrapolating past
            # dissipation would manufacture huge spurious errors.
            if verify_h < h[0] or verify_h > h[-1]:
                continue

            err = float(haversine_nm(float(r["lat"]), float(r["lon"]),
                                     np.interp(verify_h, h, la),
                                     np.interp(verify_h, h, lo)))
            records.append({"storm_id": sid, "year": int(sid[4:8]),
                            "cycle": r["cycle"], "tau": tau, "error_nm": err})

    if not records:
        print("No verifiable forecasts found.", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["storm_id", "year", "cycle", "tau", "error_nm"])
        w.writeheader()
        w.writerows(records)

    print(f"Verified {len(records):,} OFCL forecasts against best track\n")
    print("Mean track error (nm) by lead time and era:")
    header = "  era          n     " + "".join(f"{t:>7}h" for t in STANDARD_TAUS)
    print(header)
    print("  " + "-" * (len(header) - 2))

    for lo_y, hi_y in ERAS:
        sub = [r for r in records if lo_y <= r["year"] <= hi_y]
        if not sub:
            continue
        cells = []
        for tau in STANDARD_TAUS:
            e = [r["error_nm"] for r in sub if r["tau"] == tau]
            cells.append(f"{np.mean(e):>7.0f}" if e else f"{'-':>7}")
        print(f"  {lo_y}-{hi_y % 100:02d} {len(sub):>7,}  " + " ".join(cells))

    print("\n67th-percentile error (nm), comparable to the NHC cone radius:")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for lo_y, hi_y in ERAS:
        sub = [r for r in records if lo_y <= r["year"] <= hi_y]
        if not sub:
            continue
        cells = []
        for tau in STANDARD_TAUS:
            e = [r["error_nm"] for r in sub if r["tau"] == tau]
            cells.append(f"{np.percentile(e, 67):>7.0f}" if e else f"{'-':>7}")
        print(f"  {lo_y}-{hi_y % 100:02d} {len(sub):>7,}  " + " ".join(cells))

    print(f"\nWrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
