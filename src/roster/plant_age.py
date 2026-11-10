#!/usr/bin/env python3
"""
Time-varying capital age per hospital: "average age of plant", in years, from
CMS HCRIS Medicare cost reports.

    avg age of plant = accumulated depreciation / annual depreciation expense

WHY THIS MEASURE. The covariate we need is "how old is the physical plant this
hospital has to ride a storm out in". Calendar building age cannot answer that,
and the CMS POS original-participation date certainly cannot: 59% of active
hospitals sit exactly on the 1966 Medicare floor, so it is a constant, not a
covariate. Average age of plant is the literature-standard capital-age proxy in
hospital finance (AHA, RAND Hospital Data, HFMA, health-services research). Its
key virtue here is that it reflects RENOVATION, not construction date -- a 1920s
hospital that gutted and rebuilt its plant in 2010 shows an age of ~5 years,
because the rebuild reset accumulated depreciation while depreciation expense
jumped. That is exactly the thing that matters for storm resilience: modern
generators, elevated switchgear, current wind-borne-debris envelope.

WHY TIME-VARYING. Plant age moves. A hospital's plant at Katrina (2005) is not
its plant at Milton (2024), and the national median itself drifted from ~9.8y
(FY2000) to ~11.8y (FY2023) as capital spending slowed. One row per CCN per
fiscal year lets the analysis join each storm-hospital dyad to the cost report
in force at the time.

WHERE THE NUMBERS COME FROM (worksheet coordinates -- see VALIDATION below).

  Form CMS-2552-10 (FY2010 onward), HCRIS zip HOSP10FY{YYYY}.zip
    accumulated depreciation  Wksht G, cols 1-4, lines 14, 16, 18, 20, 22,
                              24, 26, 28  (summed; stored as negative/credit,
                              absolute value taken)
    depreciation expense      Wksht A-7 Part III, line 3 (total), col 9
    total fixed assets (net)  Wksht G, cols 1-4, line 30  [tie-out check only]
    HCRIS keys: G000000 / A700003; LINE_NUM 5-char, CLMN_NUM 5-char ("00900")

  Form CMS-2552-96 (FY1996-2011), HCRIS zip HOSPFY{YYYY}.zip
    accumulated depreciation  Wksht G, cols 1-4, lines 13.01, 14.01, 15.01,
                              16.01, 17.01, 18.01, 19.01  (summed; stored
                              positive on this form)
    depreciation expense      Wksht A-7 Part III, line 5 (total), col 9
    total fixed assets (net)  Wksht G, cols 1-4, line 21  [tie-out check only]
    HCRIS keys: G000000 / A700003; LINE_NUM 5-char, CLMN_NUM 4-char ("0900")

  Verified against the blank CMS forms and the Pub. 15-2 instruction text:
    Wksht G  2552-10  https://www.costreportdata.com/worksheets/Form_G000.pdf
    Wksht G  instr    https://www.costreportdata.com/instructions/Instr_G000.pdf
    Wksht A-7 2552-10 https://www.costreportdata.com/worksheets/Form_A701.pdf
    A-7 instr sec4015 https://www.costreportdata.com/instructions/Instr_A701.pdf
    Wksht G  2552-96  https://www.costreportdata.com/worksheets/Form_G00.pdf
    A-7 P3/P4 2552-96 https://www.costreportdata.com/worksheets/Form_A73.pdf
    A-7 instr sec3612 https://www.costreportdata.com/instructions/Instr_A71.pdf
    AHA DataQuery cost report field dictionary (specifies A-7 Part III)
      https://www.ahadata.com/system/files/media/file/2020/04/AHA%20DataQuery%20Cost%20Report%20Fields%20Dictionary.pdf

  Four things about these files silently produce garbage if missed:
    1. 2552-96 puts accumulated depreciation on ".01" SUBLINES of each asset
       line; 2552-10 gives it its own whole lines.
    2. 2552-96 writes CLMN_NUM in 4 characters where 2552-10 uses 5, so a
       hardcoded "00900" matches nothing on the older files.
    3. The sign convention flips: 2552-10 credits are negative, 2552-96 are
       positive, though both instruction sets ask for negative.
    4. Accumulated depreciation is a LINE, not a column. Worksheet G's columns
       are fund types, not gross/net pairs.

  Depreciation expense is taken from A-7 Part III rather than Part II. Part II
  is the directly-assigned figure before Worksheet A-6/A-8 reclassifications;
  Part III is post-adjustment and has much better coverage (~97.5% of reports
  vs ~77%). Part II is deliberately NOT used as a fallback -- it would recover
  only ~19 hospital-years per year while making the denominator inconsistent
  across the panel.

VALIDATION. The coordinates are not asserted, they are checked. Worksheet G is
a balance sheet, so it carries its own proof: gross fixed asset lines MINUS the
accumulated depreciation lines MUST equal the "total fixed assets" line, which
is reported independently. This script recomputes that identity for every
report and prints the failure rate; observed failure rates are 0.1-1.9% per
year (rounding and a handful of malformed filings). Likewise the A-7 total line
is checked to be the sum of its component lines (0.0-0.3% failure). Finally the
resulting age distribution is printed and should land at a median of roughly
10-12 years -- if a coordinate is wrong the median collapses toward 0 or
explodes past 100.

Three external checks the extract passes:
  * The median rises essentially monotonically across the study window --
    9.47y (FY2000), 9.59 (FY2005), 10.02 (FY2010), 10.34 (FY2012), 10.36
    (FY2015), 10.66 (FY2017), 11.08 (FY2019), 11.34 (FY2021), 11.55 (FY2023)
    -- tracking the documented post-2000 slowdown in hospital capital
    spending. A wrong coordinate on one form version would break this across
    the 2552-96 / 2552-10 seam at FY2010; it does not.
  * University Medical Center New Orleans (CCN 190005), the replacement for
    Charity Hospital and opened in August 2015, reports an age of plant of
    1.61 years in FY2015. A brand-new building reads as brand new.
  * Mission Hospital, Asheville (CCN 340002) reads 11.04y in FY2015 and 1.63y
    in FY2019 -- HCA acquired Mission Health in February 2019 and restated the
    assets. That is the change-of-ownership artefact below, caught in the act.

CAVEATS THE ANALYSIS MUST CARRY.
  * Change-of-ownership revaluation. On acquisition the buyer restates assets
    to fair value and RESETS accumulated depreciation to zero. The hospital
    then looks brand new (age < 2y) though not one brick moved -- see the
    Mission Hospital example above. Roughly 12-13% of hospital-years sit below
    3 years, and CHOWs are a large part of that. If ownership change is in the
    model, this variable is partly endogenous to it. The cheap defence is to
    flag hospital-years whose age DROPS sharply year over year: a genuine
    rebuild and a paper revaluation look identical here, and only the first
    one actually helps a hospital survive a storm.
  * Not winsorized. Values are emitted as computed. A small tail (~5%) exceeds
    40 years, and a few dozen filings report a token depreciation expense (a
    few dollars) that yields absurd ages in the millions. The raw numerator and
    denominator are both in the output so the analysis can filter for itself;
    a plausibility window of 1-60 years is a reasonable default.
  * Zero or missing depreciation expense yields a BLANK age, never inf.
  * Consolidated filings. A multi-hospital system filing one cost report under
    one CCN reports systemwide plant, so the age describes the system, not the
    building.
  * fiscal_year is the HCRIS file year, i.e. the federal fiscal year containing
    the cost report's BEGIN date -- the standard "HCRIS FY2019" convention. The
    balance-sheet figures are as of the period END date, which may fall in the
    following calendar year.
  * FY2010 and FY2011 are transition years filed on both forms (providers moved
    to 2552-10 for periods beginning on/after 5/1/2010). Both zips are read and
    deduplicated; source_form records which form won.

Output: data/interim/hospital_plant_age.csv
    ccn, fiscal_year, accumulated_depreciation, depreciation_expense,
    avg_age_plant_years, source_form

Usage:
    python3 src/roster/plant_age.py
    python3 src/roster/plant_age.py --years 2005 2019 --drop-zips
"""

import argparse
import collections
import csv
import datetime
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROSTER = REPO / "data" / "interim" / "hospital_roster.csv"
RAW = REPO / "data" / "raw" / "hcris"
OUT = REPO / "data" / "interim" / "hospital_plant_age.csv"
LOG = REPO / "data" / "interim" / "plant_age_log.txt"

BASE = "https://downloads.cms.gov/files/hcris/{stem}.zip"
UA = {"User-Agent": "NHHES-research/0.1 (academic use)"}
FIELDS = ["ccn", "fiscal_year", "accumulated_depreciation", "depreciation_expense",
          "avg_age_plant_years", "source_form"]

# Fiscal years to pull. 2552-96 covers 1996-2011, 2552-10 covers 2010-present.
# Spaced to sit close to the storms in the study: Katrina/Rita (2005), Ike
# (2008), Sandy (2012), Harvey/Irma (2017), Michael (2018), Ida (2021), Ian
# (2022), Milton (2024). Each extra year costs ~140 MB and ~15 s.
DEFAULT_YEARS = [2000, 2005, 2010, 2012, 2015, 2017, 2019, 2021, 2023]

# Per-form worksheet coordinates. See module docstring for provenance.
FORMS = {
    "2552-10": {
        "stem": "HOSP10FY{y}",
        "prefix": "HOSP10_{y}",
        "first_year": 2010,
        "last_year": 9999,
        # Worksheet G columns are FUND types (1 general, 2 specific purpose,
        # 3 endowment, 4 plant). Column 1 carries ~99.5% of the value, but a
        # handful of fund-accounting filers put plant only in column 4, so
        # sum across all four.
        "cols": {"00100", "00200", "00300", "00400"},
        "accum_lines": {"01400", "01600", "01800", "02000",
                        "02200", "02400", "02600", "02800"},
        "gross_lines": {"01200", "01300", "01500", "01700", "01900",
                        "02100", "02300", "02500", "02700", "02900"},
        "total_line": "03000",   # Worksheet G line 30, total fixed assets (net)
        "dep_wksht": "A700003",  # Worksheet A-7 Part III
        "dep_line": "00300",     # line 3, total
        "dep_col": "00900",      # column 9, depreciation
        "dep_parts": {"00100", "00200"},   # component lines, for the sum check
    },
    "2552-96": {
        "stem": "HOSPFY{y}",
        "prefix": "HOSP_{y}",
        "first_year": 1996,
        "last_year": 2011,
        "cols": {"0100", "0200", "0300", "0400"},
        "accum_lines": {"01301", "01401", "01501",
                        "01601", "01701", "01801", "01901"},
        "gross_lines": {"01200", "01300", "01400", "01500",
                        "01600", "01700", "01800", "01900", "02000"},
        "total_line": "02100",   # Worksheet G line 21, total fixed assets (net)
        "dep_wksht": "A700003",  # Worksheet A-7 Part III
        "dep_line": "00500",     # line 5, total
        "dep_col": "0900",
        "dep_parts": {"00100", "00200", "00300", "00400"},
    },
}


def fetch(stem):
    """Download an HCRIS zip if not already cached. Returns the local path."""
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / f"{stem}.zip"
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest
    url = BASE.format(stem=stem)
    part = dest.with_suffix(".zip.part")
    print(f"  downloading {url}", flush=True)
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=180) as r, part.open("wb") as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
    except Exception as exc:
        part.unlink(missing_ok=True)
        print(f"  FAILED {stem}: {exc}")
        return None
    part.rename(dest)
    print(f"  cached {dest.name} ({dest.stat().st_size/1e6:.0f} MB)")
    return dest


def member(zf, prefix, kind):
    """HCRIS names members like HOSP10_2019_nmrc.csv; tolerate case drift."""
    for name in zf.namelist():
        if name.lower().endswith(f"{kind}.csv") and name.lower().startswith(prefix.lower()):
            return name
    for name in zf.namelist():
        if name.lower().endswith(f"{kind}.csv"):
            return name
    return None


def read_rpt(zf, name, keep_ccns):
    """
    RPT record layout: RPT_REC_NUM, PRVDR_CTRL_TYPE_CD, PRVDR_NUM, NPI,
    RPT_STUS_CD, FY_BGN_DT, FY_END_DT, PROC_DT, INITL_RPT_SW, LAST_RPT_SW,
    TRNSMTL_NUM, FI_NUM, ADR_VNDR_CD, FI_CREAT_DT, UTIL_CD, NPR_DT, SPEC_IND,
    FI_RCPT_DT.  We keep only reports for roster CCNs.
    """
    out = {}
    with zf.open(name) as fh:
        for r in csv.reader(io.TextIOWrapper(fh, "latin-1")):
            if len(r) < 8 or r[2] not in keep_ccns:
                continue
            days = proc = None
            try:
                bgn = datetime.datetime.strptime(r[5], "%m/%d/%Y")
                end = datetime.datetime.strptime(r[6], "%m/%d/%Y")
                days = (end - bgn).days + 1
            except ValueError:
                pass
            try:
                proc = datetime.datetime.strptime(r[7], "%m/%d/%Y")
            except ValueError:
                pass
            out[r[0]] = {"ccn": r[2], "days": days or 0,
                         "proc": proc or datetime.datetime.min,
                         "rec": int(r[0]) if r[0].isdigit() else 0}
    return out


def scan_nmrc(zf, name, spec, wanted):
    """
    Stream the long-format numeric table, keeping only the handful of cells we
    need for reports we care about. The NMRC member is 400-700 MB uncompressed,
    so it is read row by row straight out of the zip and never materialized.

    NMRC layout: RPT_REC_NUM, WKSHT_CD, LINE_NUM, CLMN_NUM, ITM_VAL_NUM.
    """
    acc = collections.defaultdict(float)
    gross = collections.defaultdict(float)
    parts = collections.defaultdict(float)
    total_fixed = collections.defaultdict(float)
    dep = {}
    gcols, dcol = spec["cols"], spec["dep_col"]
    dws, dline = spec["dep_wksht"], spec["dep_line"]
    accum_lines, gross_lines = spec["accum_lines"], spec["gross_lines"]
    total_line = spec["total_line"]
    # Component lines carry .01/.02 sublines for extra cost centres, so match
    # on the whole-line prefix rather than the exact line number.
    part_prefixes = {p[:3] for p in spec["dep_parts"]}
    n = 0
    with zf.open(name) as fh:
        for r in csv.reader(io.TextIOWrapper(fh, "latin-1")):
            n += 1
            if n % 50_000_000 == 0:
                print(f"    ... {n/1e6:.0f}M rows", flush=True)
            if len(r) < 5:
                continue
            ws = r[1]
            # Cheap reject first: only two worksheets matter out of ~200.
            if ws == "G000000":
                if r[3] not in gcols or r[0] not in wanted:
                    continue
                line, rec = r[2], r[0]
                try:
                    val = float(r[4])
                except ValueError:
                    continue
                if line in accum_lines:
                    # 2552-10 files store this as a credit (negative), 2552-96
                    # files store the same figure positive. Both instruction
                    # sets say negative; the 96 filers simply did not comply.
                    acc[rec] += abs(val)
                elif line in gross_lines:
                    gross[rec] += val
                elif line == total_line:
                    total_fixed[rec] += val
            elif ws == dws:
                if r[3] != dcol or r[0] not in wanted:
                    continue
                line, rec = r[2], r[0]
                try:
                    val = float(r[4])
                except ValueError:
                    continue
                if line == dline:
                    dep[rec] = val
                elif line[:3] in part_prefixes:
                    parts[rec] += val
    return acc, gross, total_fixed, dep, parts


def tie_out(acc, gross, total_fixed, dep, parts, label):
    """Prove the coordinates on the data itself, and report how often they hold."""
    checked = [k for k in total_fixed if k in gross]
    bad = sum(1 for k in checked
              if abs((gross[k] - acc.get(k, 0.0)) - total_fixed[k]) > 2.0)
    if checked:
        print(f"    Wksht G balance check (gross - accum == total fixed): "
              f"{len(checked)-bad}/{len(checked)} exact "
              f"({bad/len(checked):.2%} fail)  [{label}]")
    dchecked = [k for k in dep if k in parts]
    dbad = sum(1 for k in dchecked if abs(parts[k] - dep[k]) > 2.0)
    if dchecked:
        print(f"    Wksht A-7 total check (components == total line): "
              f"{len(dchecked)-dbad}/{len(dchecked)} exact "
              f"({dbad/len(dchecked):.2%} fail)")
    return (bad / len(checked)) if checked else None


def pick(cands):
    """
    Multiple reports per CCN per fiscal year are normal: amended filings,
    reopenings, and short periods around a change of ownership or fiscal year
    change. RULE: take the report covering the LONGEST fiscal period (a full
    12-month report beats a 2-month stub, and the annual depreciation expense
    in the denominator is only comparable across hospitals at full-year
    length); break ties on the latest PROC_DT, which is the amended/reopened
    version rather than the superseded original; break remaining ties on the
    highest RPT_REC_NUM.
    """
    return max(cands, key=lambda c: (c["days"], c["proc"], c["rec"]))


def harvest(year, form, keep_ccns, drop_zips):
    """Return {ccn: row} for one fiscal year on one form version."""
    spec = FORMS[form]
    if not (spec["first_year"] <= year <= spec["last_year"]):
        return {}
    stem = spec["stem"].format(y=year)
    path = fetch(stem)
    if path is None:
        return {}

    prefix = spec["prefix"].format(y=year)
    with zipfile.ZipFile(path) as zf:
        rpt_name = member(zf, prefix, "rpt")
        nmrc_name = member(zf, prefix, "nmrc")
        if not rpt_name or not nmrc_name:
            print(f"  {stem}: missing rpt/nmrc member, skipping")
            return {}
        rpt = read_rpt(zf, rpt_name, keep_ccns)
        if not rpt:
            print(f"  {stem}: no roster CCNs present, skipping")
            return {}
        print(f"  {stem}: {len(rpt)} reports for roster CCNs; scanning {nmrc_name}",
              flush=True)
        acc, gross, total_fixed, dep, parts = scan_nmrc(zf, nmrc_name, spec, set(rpt))

    tie_out(acc, gross, total_fixed, dep, parts, form)

    by_ccn = collections.defaultdict(list)
    for rec, meta in rpt.items():
        if rec not in acc and rec not in dep:
            continue
        by_ccn[meta["ccn"]].append({**meta, "rec_id": rec})

    rows = {}
    for ccn, cands in by_ccn.items():
        best = pick(cands)
        rec = best["rec_id"]
        a, d = acc.get(rec), dep.get(rec)
        if not a and not d:
            continue
        age = ""
        if a and d and d > 0:
            age = f"{a / d:.3f}"
        rows[ccn] = {
            "ccn": ccn,
            "fiscal_year": year,
            "accumulated_depreciation": f"{a:.0f}" if a else "",
            "depreciation_expense": f"{d:.0f}" if d is not None else "",
            "avg_age_plant_years": age,
            "source_form": form,
            "_days": best["days"],
        }
    print(f"  {stem}: {len(rows)} hospitals with usable capital data")
    if drop_zips:
        path.unlink(missing_ok=True)
        print(f"  removed {path.name}")
    return rows


def summarize(values):
    v = sorted(values)
    n = len(v)
    if not n:
        return None
    q = lambda p: v[int(p * (n - 1))]
    return {"n": n, "min": v[0], "p25": q(0.25), "median": q(0.50),
            "p75": q(0.75), "max": v[-1],
            "in_band": sum(1 for x in v if 3 <= x <= 40) / n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=DEFAULT_YEARS)
    ap.add_argument("--drop-zips", action="store_true",
                    help="delete each HCRIS zip after reading it (saves ~700 MB)")
    ap.add_argument("--force", action="store_true",
                    help="re-extract years already present in the output")
    args = ap.parse_args()

    if not ROSTER.exists():
        print(f"missing {ROSTER.relative_to(REPO)} -- run build_roster.py first")
        return 1
    with ROSTER.open() as fh:
        keep_ccns = {r["ccn"] for r in csv.DictReader(fh) if r["ccn"]}
    print(f"roster: {len(keep_ccns)} distinct CCNs")

    done = collections.OrderedDict()
    if OUT.exists() and not args.force:
        with OUT.open() as fh:
            for r in csv.DictReader(fh):
                done[(r["ccn"], int(r["fiscal_year"]))] = r
        have = sorted({k[1] for k in done})
        print(f"cached: {len(done)} rows covering {have}")

    for year in sorted(args.years):
        if not args.force and any(k[1] == year for k in done):
            print(f"\nFY{year}: already in output, skipping (use --force to redo)")
            continue
        print(f"\nFY{year}")
        merged = {}
        for form in ("2552-96", "2552-10"):
            for ccn, row in harvest(year, form, keep_ccns, args.drop_zips).items():
                prev = merged.get(ccn)
                # Transition years appear on both forms: keep the longer period,
                # and on an exact tie prefer the newer form.
                if prev is None or row["_days"] > prev["_days"]:
                    merged[ccn] = row
        for ccn, row in merged.items():
            row.pop("_days", None)
            done[(ccn, year)] = row
        _flush(done)

    _flush(done)

    ages = [float(r["avg_age_plant_years"]) for r in done.values()
            if r["avg_age_plant_years"]]
    print(f"\n{'='*72}\nwrote {len(done)} hospital-year rows to "
          f"{OUT.relative_to(REPO)}")
    lines = []
    for year in sorted({int(r["fiscal_year"]) for r in done.values()}):
        yv = [float(r["avg_age_plant_years"]) for r in done.values()
              if int(r["fiscal_year"]) == year and r["avg_age_plant_years"]]
        s = summarize(yv)
        if s:
            line = (f"  FY{year}  n={s['n']:5d}  min={s['min']:6.2f}  "
                    f"p25={s['p25']:6.2f}  median={s['median']:6.2f}  "
                    f"p75={s['p75']:6.2f}  max={s['max']:12.1f}  "
                    f"3-40y={s['in_band']:.1%}")
            print(line)
            lines.append(line)
    s = summarize(ages)
    if s:
        line = (f"  ALL   n={s['n']:5d}  min={s['min']:6.2f}  "
                f"p25={s['p25']:6.2f}  median={s['median']:6.2f}  "
                f"p75={s['p75']:6.2f}  max={s['max']:12.1f}  "
                f"3-40y={s['in_band']:.1%}")
        print(line)
        lines.append(line)
    blank = sum(1 for r in done.values() if not r["avg_age_plant_years"])
    print(f"  blank age (zero/missing depreciation expense): {blank}")
    LOG.write_text("age of plant, years, by HCRIS fiscal year\n" +
                   "\n".join(lines) + f"\n  blank age: {blank}\n")
    return 0


def _flush(done):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for key in sorted(done, key=lambda k: (k[0], k[1])):
            w.writerow(done[key])


if __name__ == "__main__":
    sys.exit(main())
