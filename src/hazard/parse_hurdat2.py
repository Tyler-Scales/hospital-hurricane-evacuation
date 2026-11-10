#!/usr/bin/env python3
"""
Parse HURDAT2 Atlantic best-track into a tidy table, and report wind-radii
coverage by year.

Wind radii (34/50/64-kt, four quadrants) define the realized wind swath that
determines cohort inclusion. HURDAT2 carries them only from 2004 onward; before
that they are -999. This script quantifies that break, which is the empirical
justification for the study's 1990-2003 / 2004-present two-tier design.

HURDAT2 format: header line then N data lines.
  Header: AL011851,            UNNAMED,     14,
  Data:   YYYYMMDD, HHMM, R, SS, LAT, LON, VMAX, MSLP, then 12 wind-radii
          columns (34kt NE/SE/SW/NW, 50kt NE/SE/SW/NW, 64kt NE/SE/SW/NW),
          then RMW (added 2021+ revision).

Usage:
    python3 src/hazard/parse_hurdat2.py
    python3 src/hazard/parse_hurdat2.py --since 1990
"""

import argparse
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "data" / "raw" / "hurdat2" / "hurdat2-atlantic.txt"
OUT = REPO / "data" / "interim" / "hurdat2_tracks.csv"

RADII_COLS = [
    "r34_ne", "r34_se", "r34_sw", "r34_nw",
    "r50_ne", "r50_se", "r50_sw", "r50_nw",
    "r64_ne", "r64_se", "r64_sw", "r64_nw",
]
FIELDS = (["storm_id", "storm_name", "date", "time", "record_id", "status",
           "lat", "lon", "vmax_kt", "mslp_mb"] + RADII_COLS + ["rmw_nm"])


def _coord(tok):
    """'28.0N' -> 28.0 ; '94.8W' -> -94.8"""
    tok = tok.strip()
    if not tok:
        return None
    val = float(tok[:-1])
    return -val if tok[-1] in "WS" else val


def _num(tok):
    """HURDAT2 uses -999 for missing."""
    try:
        v = int(tok.strip())
    except ValueError:
        return None
    return None if v == -999 else v


def parse(path):
    rows = []
    with path.open() as fh:
        lines = [ln.rstrip("\n") for ln in fh if ln.strip()]

    i = 0
    while i < len(lines):
        parts = [p.strip() for p in lines[i].split(",")]
        storm_id, storm_name, n_rec = parts[0], parts[1], int(parts[2])
        i += 1
        for _ in range(n_rec):
            d = [p.strip() for p in lines[i].split(",")]
            i += 1
            rec = {
                "storm_id": storm_id,
                "storm_name": storm_name,
                "date": d[0],
                "time": d[1],
                "record_id": d[2],
                "status": d[3],
                "lat": _coord(d[4]),
                "lon": _coord(d[5]),
                "vmax_kt": _num(d[6]),
                "mslp_mb": _num(d[7]),
            }
            for j, col in enumerate(RADII_COLS):
                rec[col] = _num(d[8 + j]) if len(d) > 8 + j else None
            rec["rmw_nm"] = _num(d[20]) if len(d) > 20 else None
            rows.append(rec)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=1851)
    args = ap.parse_args()

    if not SRC.exists():
        print(f"Missing {SRC}. Download HURDAT2 first.", file=sys.stderr)
        return 1

    rows = parse(SRC)
    rows = [r for r in rows if int(r["date"][:4]) >= args.since]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    # Wind-radii coverage by year: % of hurricane-force observations carrying r34
    print(f"{'year':<6}{'storms':>7}{'obs':>7}{'w/ r34':>8}{'coverage':>10}")
    print("-" * 38)
    by_year = {}
    for r in rows:
        by_year.setdefault(int(r["date"][:4]), []).append(r)

    for year in sorted(by_year):
        rs = by_year[year]
        storms = len({r["storm_id"] for r in rs})
        have = sum(1 for r in rs if r["r34_ne"] is not None)
        pct = 100 * have / len(rs) if rs else 0
        print(f"{year:<6}{storms:>7}{len(rs):>7}{have:>8}{pct:>9.0f}%")

    print(f"\nWrote {OUT.relative_to(REPO)}  ({len(rows):,} track observations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
