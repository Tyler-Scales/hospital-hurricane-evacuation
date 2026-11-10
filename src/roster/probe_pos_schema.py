#!/usr/bin/env python3
"""
Probe Provider of Services (POS) file schemas across eras.

The roster needs a consistent hospital universe from 1990 to 2025, but POS
variable names changed in 2011 (from PROVNNNN-style positional names to
mnemonics like PRVDR_NUM). Before writing the extractor we need to know, for
each era, which columns carry: CMS Certification Number, facility name,
address, state, provider category/subtype, ownership, bed count, and the
participation and termination dates that make the roster time-varying.

Downloads one file per probe year into data/raw/cms/ and reports the schema.

Usage:
    python3 src/roster/probe_pos_schema.py --years 1995 2005 2018
"""

import argparse
import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

# Format availability is era-dependent: 1990 and 2011+ ship usable CSV zips,
# but 1991-2010 CSV zips are empty stubs and only Stata is populated.
# probe_pos_urls.py established this; see protocol/phase1_roster.md.
NBER_CSV = "https://data.nber.org/pos/{year}/pos{year}.csv.zip"
NBER_DTA = "https://data.nber.org/pos/{year}/pos{year}.dta.zip"
TIMEOUT = 300
UA = {"User-Agent": "NHHES-research/0.1 (academic use)"}

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "raw" / "cms"

# Concepts the roster needs, with the substrings that identify them in either
# the modern mnemonic scheme or the older layouts.
WANTED = {
    "ccn": ("PRVDR_NUM", "PROVIDER_NUMBER", "PROV0001"),
    "name": ("FAC_NAME", "FACILITY_NAME", "PROV0475", "NAME"),
    "category": ("PRVDR_CTGRY_CD", "PROV0018", "CATEGORY"),
    "subtype": ("PRVDR_CTGRY_SBTYP_CD", "PROV0019", "SBTYP"),
    "state": ("STATE_CD", "PROV0010", "STATE"),
    "city": ("CITY_NAME", "PROV0008", "CITY"),
    "zip": ("ZIP_CD", "PROV0011", "ZIP"),
    "ownership": ("GNRL_CNTL_TYPE_CD", "PROV0130", "CNTL_TYPE"),
    "beds": ("CRTFD_BED_CNT", "BED_CNT", "PROV0230"),
    "term_code": ("PGM_TRMNTN_CD", "PROV0059", "TRMNTN_CD"),
    "term_date": ("TRMNTN_EXPRTN_DT", "PROV0060", "TRMNTN_DT"),
    "participation": ("ORGNL_PRTCPTN_DT", "PROV0058", "PRTCPTN_DT"),
}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def get_year(year):
    """Fetch a year's POS file, preferring CSV and falling back to Stata."""
    for kind, url_tpl in (("csv", NBER_CSV), ("dta", NBER_DTA)):
        dest = CACHE / f"pos{year}.{kind}.zip"
        if dest.exists() and dest.stat().st_size > 1000:
            return dest, kind
        url = url_tpl.format(year=year)
        try:
            raw = fetch(url)
        except Exception:
            continue
        # Empty zip archives are 22 bytes; treat them as absent.
        if len(raw) <= 1000:
            continue
        print(f"  downloaded {url} ({len(raw)/1e6:.1f} MB)")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return dest, kind
    print(f"  ! no usable file for {year}")
    return None, None


def read_header(path, kind):
    """Return (member_name, header_cols, sample_rows, n_rows)."""
    if kind == "csv":
        with zipfile.ZipFile(path) as z:
            member = z.namelist()[0]
            with z.open(member) as fh:
                reader = csv.reader(io.TextIOWrapper(fh, encoding="latin-1"))
                header = next(reader)
                sample = [next(reader) for _ in range(3)]
                nrows = 3 + sum(1 for _ in reader)
        return member, header, sample, nrows

    import pandas as pd  # imported lazily; only needed for the Stata era
    with zipfile.ZipFile(path) as z:
        member = z.namelist()[0]
        with z.open(member) as fh:
            df = pd.read_stata(io.BytesIO(fh.read()), convert_categoricals=False)
    return (member, list(df.columns),
            df.head(3).astype(str).values.tolist(), len(df))


def probe(year):
    path, kind = get_year(year)
    if path is None:
        return
    size_mb = path.stat().st_size / 1e6
    member, header, sample, nrows = read_header(path, kind)

    print(f"\n{'='*66}\n{year}  [{kind}]  ({size_mb:.1f} MB zipped, {member}, "
          f"{nrows:,} rows, {len(header)} cols)\n{'='*66}")

    upper = [h.upper().strip() for h in header]
    for concept, candidates in WANTED.items():
        hits = [h for h in upper if any(c in h for c in candidates)]
        mark = "OK " if hits else "?? "
        print(f"  {mark}{concept:<14} {hits[:4]}")

    print(f"\n  first 18 columns: {upper[:18]}")
    if sample:
        print(f"  sample row 1:     {sample[0][:8]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=[1995, 2005, 2018])
    args = ap.parse_args()
    for y in args.years:
        probe(y)
    return 0


if __name__ == "__main__":
    sys.exit(main())
