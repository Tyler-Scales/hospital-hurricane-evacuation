#!/usr/bin/env python3
"""
Phase 0 data-availability audit: NHC ATCF a-deck OFCL coverage.

The study's methodological core is reconstructing the official NHC forecast
as it stood at T-72h/T-48h/T-24h before landfall. That requires OFCL rows in
the ATCF a-decks. This script establishes, per year, how many Atlantic storms
have a-decks at all and how many carry usable OFCL forecast entries.

Output: data/interim/atcf_coverage_audit.csv  (+ console summary)

Usage:
    python3 src/hazard/audit_atcf.py --start 1990 --end 2025
    python3 src/hazard/audit_atcf.py --start 2004 --end 2005 --workers 4
"""

import argparse
import csv
import gzip
import io
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ARCHIVE = "https://ftp.nhc.noaa.gov/atcf/archive"
ADECK_RE = re.compile(r"a(al|ep)\d{6}\.dat\.gz")
TIMEOUT = 90
UA = {"User-Agent": "NHHES-research-audit/0.1 (academic use)"}

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "interim" / "atcf_coverage_audit.csv"


def fetch(url, retries=3):
    """GET with retries. Returns bytes, or None on persistent failure."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ! fetch failed {url}: {e}", file=sys.stderr)
                return None
    return None


def list_adecks(year, basin="al"):
    """Return sorted a-deck filenames for a year/basin."""
    body = fetch(f"{ARCHIVE}/{year}/")
    if body is None:
        return []
    text = body.decode("utf-8", "replace")
    found = {m.group(0) for m in ADECK_RE.finditer(text)}
    return sorted(f for f in found if f.startswith(f"a{basin}"))


def parse_adeck(raw):
    """
    Parse an ATCF a-deck. Returns (total_rows, ofcl_rows, n_cycles, lead_times).

    ATCF format is comma-delimited, fixed column order:
      1 BASIN, 2 CY, 3 YYYYMMDDHH (warning time), 4 TECHNUM, 5 TECH,
      6 TAU (forecast lead hours), 7 LatN/S, 8 LonE/W, 9 VMAX, 10 MSLP, ...
    """
    try:
        text = gzip.decompress(raw).decode("utf-8", "replace")
    except OSError:
        return None

    total = 0
    ofcl = 0
    cycles = set()
    leads = set()

    for line in io.StringIO(text):
        if not line.strip():
            continue
        total += 1
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        if parts[4] != "OFCL":
            continue
        ofcl += 1
        cycles.add(parts[2])
        try:
            leads.add(int(parts[5]))
        except ValueError:
            pass

    return total, ofcl, len(cycles), sorted(leads)


def audit_storm(year, fname):
    raw = fetch(f"{ARCHIVE}/{year}/{fname}")
    if raw is None:
        return {"year": year, "storm": fname, "status": "fetch_failed",
                "total_rows": 0, "ofcl_rows": 0, "advisory_cycles": 0, "max_lead_h": 0}
    parsed = parse_adeck(raw)
    if parsed is None:
        return {"year": year, "storm": fname, "status": "bad_gzip",
                "total_rows": 0, "ofcl_rows": 0, "advisory_cycles": 0, "max_lead_h": 0}
    total, ofcl, cycles, leads = parsed
    return {
        "year": year,
        "storm": fname,
        "status": "ok" if ofcl > 0 else "no_ofcl",
        "total_rows": total,
        "ofcl_rows": ofcl,
        "advisory_cycles": cycles,
        "max_lead_h": max(leads) if leads else 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1990)
    ap.add_argument("--end", type=int, default=2025)
    ap.add_argument("--basin", default="al")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    jobs = []
    for year in range(args.start, args.end + 1):
        names = list_adecks(year, args.basin)
        print(f"{year}: {len(names)} a-decks listed", flush=True)
        jobs.extend((year, n) for n in names)

    if not jobs:
        print("No a-decks found — check network or archive layout.", file=sys.stderr)
        return 1

    print(f"\nAuditing {len(jobs)} storm files with {args.workers} workers...\n", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        rows = list(ex.map(lambda j: audit_storm(*j), jobs))

    rows.sort(key=lambda r: (r["year"], r["storm"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # Year-level summary
    print(f"{'year':<6}{'storms':>7}{'w/OFCL':>8}{'%':>7}{'OFCL rows':>11}{'max lead':>10}")
    print("-" * 49)
    by_year = {}
    for r in rows:
        by_year.setdefault(r["year"], []).append(r)
    for year in sorted(by_year):
        rs = by_year[year]
        n = len(rs)
        k = sum(1 for r in rs if r["ofcl_rows"] > 0)
        tot_ofcl = sum(r["ofcl_rows"] for r in rs)
        mx = max((r["max_lead_h"] for r in rs), default=0)
        print(f"{year:<6}{n:>7}{k:>8}{100*k/n if n else 0:>6.0f}%{tot_ofcl:>11}{mx:>9}h")

    print(f"\nWrote {OUT.relative_to(REPO)}  ({len(rows)} storm-files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
