#!/usr/bin/env python3
"""
Build the time-varying acute-care hospital roster, 1990-2025.

A hospital enters a storm's cohort only if it was open on that storm's date, so
the roster must be a per-year snapshot rather than a single current list. Using
a modern hospital list for a 1995 storm would both invent hospitals that did not
yet exist and erase ones that have since closed, biasing the denominator in
opposite directions across the study period.

Source and format vary by era (established by probe_pos_urls.py):
    1990        NBER CSV, pre-PROVNNNN 52-column schema (dedicated adapter)
    1991-2010   NBER Stata only (the CSV zips are empty stubs)
    2011-2018   NBER CSV
    2019-2025   CMS quarterly files from data.cms.gov

Variable names changed in 2011 from PROVNNNN positional codes to mnemonics.
The mapping below comes from NBER's published crosswalk
(pos-prov-to-2011-suggested-crosswalk.txt; city->prov3225 is crosswalk line 432
and further validated at 96% exact city match across 111,930 shared CCNs).

Study population (verified against Flex Monitoring and AHA benchmarks):
    provider category 01, subtype in {01 short-term acute, 11 critical access}.
Critical Access Hospitals are small rural acute-care hospitals; the 1997 BBA
conversion wave moved ~1,300 hospitals from subtype 01 to 11 UNDER NEW CCNs
(13xx range) with the old CCN terminated code 07 — counting only subtype 01
therefore fabricates a phantom 40% "closure" wave. Federal (VA/DoD) hospitals
carry alpha-suffix CCNs and unstable subtype coding across vintages; they are
flagged, not silently mixed into the community denominator. Subtype 20 rows
are hospital-based transplant-program duplicates of their parent CCN and are
dropped.

CCN is preserved as a first-class key throughout, because it is the join key to
Medicare claims and HCUP for any future patient-outcome linkage.

Usage:
    python3 src/roster/build_roster.py --years 2005 2018
    python3 src/roster/build_roster.py                 # default year set
"""

import argparse
import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "raw" / "cms"
OUT = REPO / "data" / "interim" / "hospital_roster.csv"

NBER_CSV = "https://data.nber.org/pos/{year}/pos{year}.csv.zip"
NBER_DTA = "https://data.nber.org/pos/{year}/pos{year}.dta.zip"
UA = {"User-Agent": "NHHES-research/0.1 (academic use)"}
TIMEOUT = 300

# Modern mnemonic -> legacy PROVNNNN, per NBER's published crosswalk.
XWALK = {
    "prvdr_num": "prov1680",
    "fac_name": "prov0475",
    "prvdr_ctgry_cd": "prov0075",
    "prvdr_ctgry_sbtyp_cd": "prov0085",
    "state_cd": "prov3230",
    "city_name": "prov3225",
    "zip_cd": "prov2905",
    "gnrl_cntl_type_cd": "prov2885",
    "crtfd_bed_cnt": "prov0755",
    "pgm_trmntn_cd": "prov4770",
    "trmntn_exprtn_dt": "prov4500",
    "orgnl_prtcptn_dt": "prov1565",
}

HOSPITAL_CATEGORY = "01"
# Study acute-care population: short-term acute (01) + critical access (11).
ACUTE_SUBTYPES = {"01", "11"}
CAH_SUBTYPE = "11"
TRANSPLANT_DUPE_SUBTYPE = "20"

# Atlantic and Gulf states, plus inland states a wind swath can reach.
COASTAL_STATES = {
    "TX", "LA", "MS", "AL", "FL", "GA", "SC", "NC", "VA", "WV", "MD", "DC",
    "DE", "PA", "NJ", "NY", "CT", "RI", "MA", "VT", "NH", "ME",
}

# GNRL_CNTL_TYPE_CD for HOSPITALS (provider category 01). The coding is
# CATEGORY-SPECIFIC: non-hospital categories use an entirely different table.
# Source: CMS QIES POS record layout (P.QWB.POSQ.OTHER.LAYOUT.MAR23.pdf,
# layout "Hospital, CATEGORY = 01"). Verified empirically: UAB/SUNY Downstate
# (state)=06, Bellevue/NYC=07, Parkland/Harris County/Jackson Memorial/Lee
# Memorial (districts & authorities)=08, HCA/Tenet facilities=04.
OWNERSHIP = {
    "01": "church_nonprofit",
    "02": "private_nonprofit",
    "03": "other_nonprofit",
    "04": "for_profit",
    "05": "government_federal",
    "06": "government_state",
    "07": "government_local",
    "08": "government_hospital_district",
    "09": "physician_owned_for_profit",
    "10": "tribal",
}
# FEMA Public Assistance (Stafford Act): government and eligible private
# non-profits only. For-profit (04, 09) ineligible; federal (05) facilities are
# not PA applicants. PAPPG v5.0, FP 104-009-2, applicant eligibility ch.
PA_ELIGIBLE = {"01", "02", "03", "06", "07", "08", "10"}

# 1990's prov2885 uses a 9-value pre-1991 control coding. Recode to the modern
# hospital scheme, established by modal mapping over 7,128 CCNs joined
# 1990->1995 (e.g. 1990 03 -> proprietary 704/…, 09 -> federal 47/48).
# 1990 code 02 cannot distinguish private vs other nonprofit; map to 02.
OWNERSHIP_1990_RECODE = {
    "01": "01", "02": "02", "03": "04", "04": "06", "05": "07",
    "06": "07", "07": "07", "08": "08", "09": "05",
}

# SSA numeric state codes (alphabetic order with territories interleaved),
# used by the 1990 file's `state` column (== CCN[:2] in 100% of category-01
# rows). Only study-relevant states need mapping; others fall out at the
# coastal filter.
SSA_STATE = {
    "01": "AL", "07": "CT", "08": "DE", "09": "DC", "10": "FL", "11": "GA",
    "19": "LA", "20": "ME", "21": "MD", "22": "MA", "25": "MS", "30": "NH",
    "31": "NJ", "33": "NY", "34": "NC", "39": "PA", "41": "RI", "42": "SC",
    "44": "TN", "45": "TX", "47": "VT", "48": "VA", "51": "WV",
}

FIELDS = ["year", "ccn", "name", "city", "state", "zip", "subtype",
          "is_acute", "is_cah", "is_federal", "ownership_code", "ownership",
          "pa_eligible", "beds", "termination_code", "termination_date",
          "participation_date", "source"]


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def get_pos_file(year):
    """Return (path, kind) for a year, downloading and caching as needed."""
    for kind, tpl in (("csv", NBER_CSV), ("dta", NBER_DTA)):
        dest = CACHE / f"pos{year}.{kind}.zip"
        if dest.exists() and dest.stat().st_size > 1000:
            return dest, kind
    for kind, tpl in (("csv", NBER_CSV), ("dta", NBER_DTA)):
        dest = CACHE / f"pos{year}.{kind}.zip"
        try:
            raw = fetch(tpl.format(year=year))
        except Exception:
            continue
        if len(raw) <= 1000:      # 22-byte empty zip stub
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return dest, kind
    return None, None


def load_records(path, kind):
    """Yield dicts keyed by lowercased column name."""
    if kind == "csv":
        with zipfile.ZipFile(path) as z:
            with z.open(z.namelist()[0]) as fh:
                reader = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"))
                for row in reader:
                    yield {(k or "").lower().strip(): v for k, v in row.items()}
    else:
        import pandas as pd
        with zipfile.ZipFile(path) as z:
            with z.open(z.namelist()[0]) as fh:
                df = pd.read_stata(io.BytesIO(fh.read()), convert_categoricals=False)
        df.columns = [c.lower().strip() for c in df.columns]
        for rec in df.to_dict("records"):
            yield rec


def getval(rec, modern):
    """Read a field by modern name, falling back to its legacy PROVNNNN name.

    Guards against pandas NaN (v != v): the current files encode missing as
    '' strings, but that is an accident of their dtypes, not a contract.
    """
    for key in (modern, XWALK.get(modern)):
        if key is None or key not in rec:
            continue
        v = rec[key]
        if v is None or v != v or v == "":
            continue
        return str(v).strip()
    return ""


def code2(v):
    """Normalize a 1-2 digit code, mapping era-specific missing markers
    (CSV-era '.', Stata-era '') to '' instead of fabricating '0.' or '00'."""
    v = v.strip()
    return "" if v in ("", ".") else v.zfill(2)


def norm_date(v, file_year):
    """Emit uniform YYYYMMDD. The 1995 file ships 6-digit YYMMDD; a snapshot
    file cannot contain dates after its own vintage, so pre-2000 files get a
    '19' century unconditionally."""
    v = v.strip()
    if len(v) == 6 and v.isdigit() and file_year < 2000:
        return "19" + v
    return v


def make_row(year, ccn, name, city, state, zip5, subtype, own, beds,
             term_code, term_date, part_date, source):
    ownership = OWNERSHIP.get(own, "unknown") if own else ""
    return {
        "year": year,
        "ccn": ccn,
        "name": name,
        "city": city,
        "state": state,
        "zip": zip5,
        "subtype": subtype,
        "is_acute": subtype in ACUTE_SUBTYPES,
        "is_cah": subtype == CAH_SUBTYPE,
        "is_federal": bool(ccn) and not ccn.isdigit(),
        "ownership_code": own,
        "ownership": ownership,
        # '' (unknown) when ownership is missing, never a fabricated False.
        "pa_eligible": (own in PA_ELIGIBLE) if own else "",
        "beds": beds.split(".")[0] if beds else "",
        "termination_code": term_code,
        "termination_date": term_date,
        "participation_date": part_date,
        "source": source,
    }


def extract_1990(path, kind):
    """1990 predates the PROVNNNN layout for key fields: category lives in
    `category`, state is SSA-numeric in `state`, acute status in prov2890,
    termination date in prov2810, and prov2885 uses the pre-1991 ownership
    coding. City comes from prov0115 ('City and State', e.g. 'DOTHAN AL')."""
    out = []
    for rec in load_records(path, kind):
        if code2(getval(rec, "category")) != HOSPITAL_CATEGORY:
            continue
        state = SSA_STATE.get(getval(rec, "state").zfill(2), "")
        if state not in COASTAL_STATES:
            continue

        city_state = getval(rec, "prov0115")
        city = " ".join(city_state.split()[:-1]) if city_state else ""

        own_1990 = code2(getval(rec, "prov2885"))
        own = OWNERSHIP_1990_RECODE.get(own_1990, "") if own_1990 else ""

        # Blank or '0' termination = active. Subtype does not exist in 1990;
        # acute status is prov2890=='01' (validated 99.7% against 1995).
        term_raw = getval(rec, "termination").strip()
        is_acute = code2(getval(rec, "prov2890")) == "01"

        out.append(make_row(
            year=1990,
            ccn=getval(rec, "prov1680"),
            name=getval(rec, "prov0475"),
            city=city,
            state=state,
            zip5=getval(rec, "prov2905")[:5],
            subtype="01" if is_acute else "",
            own=own,
            beds=getval(rec, "prov0755"),
            term_code="00" if term_raw in ("", "0") else term_raw.zfill(2),
            term_date=norm_date(getval(rec, "prov2810"), 1990),
            part_date=norm_date(getval(rec, "prov1565"), 1990),
            source=f"nber_{kind}_1990adapter",
        ))
    return out


def extract_year(year):
    path, kind = get_pos_file(year)
    if path is None:
        raise RuntimeError(f"{year}: no POS file available")

    if year == 1990:
        rows = extract_1990(path, kind)
    else:
        rows = []
        for rec in load_records(path, kind):
            if code2(getval(rec, "prvdr_ctgry_cd")) != HOSPITAL_CATEGORY:
                continue
            state = getval(rec, "state_cd").upper()[:2]
            if state not in COASTAL_STATES:
                continue
            subtype = code2(getval(rec, "prvdr_ctgry_sbtyp_cd"))
            if subtype == TRANSPLANT_DUPE_SUBTYPE:
                continue

            rows.append(make_row(
                year=year,
                ccn=getval(rec, "prvdr_num"),
                name=getval(rec, "fac_name"),
                city=getval(rec, "city_name"),
                state=state,
                zip5=getval(rec, "zip_cd")[:5],
                subtype=subtype,
                own=code2(getval(rec, "gnrl_cntl_type_cd")),
                beds=getval(rec, "crtfd_bed_cnt"),
                term_code=code2(getval(rec, "pgm_trmntn_cd")),
                term_date=norm_date(getval(rec, "trmntn_exprtn_dt"), year),
                part_date=norm_date(getval(rec, "orgnl_prtcptn_dt"), year),
                source=f"nber_{kind}",
            ))

    # A schema drift that filters everything must fail loudly, not vanish.
    if not rows:
        raise RuntimeError(
            f"{year}: 0 rows extracted from {path.name} — schema mismatch? "
            f"Check the file's header against XWALK before proceeding.")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+",
                    default=[1990, 1995, 2000, 2005, 2010, 2015, 2018])
    args = ap.parse_args()

    all_rows = []
    for year in args.years:
        rows = extract_year(year)
        community = [r for r in rows if not r["is_federal"]]
        acute = [r for r in community if r["is_acute"]]
        active = [r for r in acute if r["termination_code"] == "00"]
        cah = sum(1 for r in active if r["is_cah"])
        print(f"  {year}: {len(rows):>5} hospital records  "
              f"({len(acute)} community acute [01+11], "
              f"{len(active)} active, of which {cah} CAH)")
        all_rows.extend(rows)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(all_rows)

    ccns = {r["ccn"] for r in all_rows if r["ccn"]}
    print(f"\ntotal rows:      {len(all_rows):,}")
    print(f"distinct CCNs:   {len(ccns):,}")
    print(f"Wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
