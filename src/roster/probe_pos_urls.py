#!/usr/bin/env python3
"""
Discover the real POS download URL pattern per year.

NBER's documented pattern (pos{year}.csv.zip) yields an empty archive for
pre-2011 years, and directory listings return 403, so candidate filenames have
to be probed directly. POS files were split into OTHER (hospitals and
non-hospital facilities) and CLIA (labs) from 1997, and naming drifted over
time, so several patterns are tried per year.

Reports the first working URL and its size for each year.

Usage:
    python3 src/roster/probe_pos_urls.py --years 1990 1995 2000 2005 2010 2018
"""

import argparse
import sys
import urllib.error
import urllib.request

BASES = ["https://data.nber.org/pos/{year}", "https://data.nber.org/cms/pos"]
PATTERNS = [
    "pos{year}.csv.zip",
    "posother{year}.csv.zip",
    "pos_other{year}.csv.zip",
    "other{year}.csv.zip",
    "pos{year}other.csv.zip",
    "pos{year}.dta.zip",
    "pos{year}.sas7bdat.zip",
    "pos{year}.csv",
]
UA = {"User-Agent": "NHHES-research/0.1 (academic use)"}


def head(url):
    """Return content length in bytes, or None if unavailable."""
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+",
                    default=[1990, 1995, 2000, 2005, 2010, 2011, 2018, 2024])
    args = ap.parse_args()

    for year in args.years:
        found = []
        for base in BASES:
            for pat in PATTERNS:
                url = f"{base.format(year=year)}/{pat.format(year=year)}"
                size = head(url)
                # A 22-byte zip is an empty archive, not a usable file.
                if size and size > 1000:
                    found.append((url, size))
                    break
            if found:
                break
        if found:
            url, size = found[0]
            print(f"  {year}  {size/1e6:>7.1f} MB  {url}")
        else:
            print(f"  {year}  {'--':>7}     NONE FOUND")
    return 0


if __name__ == "__main__":
    sys.exit(main())
