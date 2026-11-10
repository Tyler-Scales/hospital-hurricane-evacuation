#!/usr/bin/env python3
"""
Sanity checks for the HCRIS average-age-of-plant extract.

These are guardrails against a silently wrong worksheet coordinate. If a
line/column mapping drifts, the ratio does not error -- it just returns
nonsense, and nonsense that is a plausible-looking float is the dangerous kind.
The checks below pin the things that must be true if the coordinates are right:
the national median sits in the published 8-14 year band, the central mass of
the distribution is in a physically sensible range, the series ages over time
(hospital plant has been getting older since 2000), and nothing is infinite.

Skips gracefully when the output file has not been built yet.

Run: python3 src/roster/test_plant_age.py
"""

import csv
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "interim" / "hospital_plant_age.csv"
FIELDS = ["ccn", "fiscal_year", "accumulated_depreciation", "depreciation_expense",
          "avg_age_plant_years", "source_form"]
CCN_RE = re.compile(r"^[0-9]{5}[0-9A-Z]$")

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


if not OUT.exists():
    print(f"SKIP: {OUT.relative_to(REPO)} not built yet "
          f"(run: python3 src/roster/plant_age.py)")
    sys.exit(0)

with OUT.open() as fh:
    reader = csv.DictReader(fh)
    header = reader.fieldnames
    rows = list(reader)

print(f"loaded {len(rows)} rows from {OUT.relative_to(REPO)}\n")

print("schema")
check("column names and order", header == FIELDS, f"got {header}")
check("non-empty", len(rows) > 1000, f"{len(rows)} rows")

print("\nkey integrity")
check("ccn format (5 digits + alphanumeric)",
      all(CCN_RE.match(r["ccn"]) for r in rows),
      "offenders: " + ", ".join(sorted({r["ccn"] for r in rows
                                        if not CCN_RE.match(r["ccn"])})[:5]))
years = sorted({int(r["fiscal_year"]) for r in rows})
check("fiscal years plausible", all(1996 <= y <= 2030 for y in years), str(years))
keys = [(r["ccn"], r["fiscal_year"]) for r in rows]
check("one row per ccn per fiscal year", len(keys) == len(set(keys)),
      f"{len(keys) - len(set(keys))} duplicate keys")
check("source_form recognised",
      {r["source_form"] for r in rows} <= {"2552-10", "2552-96"},
      str(sorted({r["source_form"] for r in rows})))

print("\nnumeric hygiene")
ages, bad_parse = [], 0
for r in rows:
    v = r["avg_age_plant_years"]
    if v == "":
        continue
    try:
        ages.append(float(v))
    except ValueError:
        bad_parse += 1
check("age parses as float or is blank", bad_parse == 0, f"{bad_parse} unparseable")
check("no infinities or NaN",
      all(math.isfinite(a) for a in ages),
      f"{sum(1 for a in ages if not math.isfinite(a))} non-finite")
check("no negative ages", all(a >= 0 for a in ages),
      f"{sum(1 for a in ages if a < 0)} negative")

# The divide-by-zero contract: a blank age must be explained by a missing or
# non-positive denominator, never by a silent drop of a valid computation.
unexplained = 0
for r in rows:
    if r["avg_age_plant_years"] != "":
        continue
    d = r["depreciation_expense"]
    a = r["accumulated_depreciation"]
    if d != "" and a != "" and float(d) > 0 and float(a) > 0:
        unexplained += 1
check("blank age only where denominator is zero/missing", unexplained == 0,
      f"{unexplained} rows blank despite usable inputs")

print("\ndistribution (the coordinate check)")
ages.sort()
n = len(ages)
q = lambda p: ages[int(p * (n - 1))]
median, p25, p75 = q(0.50), q(0.25), q(0.75)
print(f"    n={n}  p25={p25:.2f}  median={median:.2f}  p75={p75:.2f}  max={ages[-1]:.1f}")
check("median age of plant in published 8-14y band",
      8.0 <= median <= 14.0, f"median={median:.2f}")
check("interquartile range physically sensible",
      2.0 <= p25 <= 9.0 and 10.0 <= p75 <= 22.0, f"p25={p25:.2f} p75={p75:.2f}")
in_band = sum(1 for a in ages if 3 <= a <= 40) / n
check("at least 70% of hospital-years fall in 3-40y",
      in_band >= 0.70, f"{in_band:.1%}")
# ~1% of filings report a token depreciation expense (a few dollars) against a
# real accumulated balance, which yields an absurd ratio. That is a filing
# artefact, not a coordinate error -- but a wrong coordinate would blow this
# well past a couple of percent, so it is still a useful ceiling.
check("under 2% absurd (>100y)",
      sum(1 for a in ages if a > 100) / n < 0.02,
      f"{sum(1 for a in ages if a > 100) / n:.2%}")

print("\nper-year behaviour")
by_year = defaultdict(list)
for r in rows:
    if r["avg_age_plant_years"]:
        by_year[int(r["fiscal_year"])].append(float(r["avg_age_plant_years"]))
meds = {}
for y in sorted(by_year):
    v = sorted(by_year[y])
    meds[y] = v[len(v) // 2]
    print(f"    FY{y}  n={len(v):5d}  median={meds[y]:6.2f}")
check("every year has a plausible median",
      all(7.0 <= m <= 15.0 for m in meds.values()),
      str({y: round(m, 2) for y, m in meds.items()}))
# Hospital plant has aged nationally since 2000; a coordinate error on one form
# version would usually break this ordering between the 2552-96 and 2552-10 eras.
if len(meds) >= 2:
    first, last = min(meds), max(meds)
    check("plant ages over the study window",
          meds[last] > meds[first],
          f"FY{first}={meds[first]:.2f} -> FY{last}={meds[last]:.2f}")

print("\ncoverage")
per_ccn = Counter(r["ccn"] for r in rows)
repeat = sum(1 for k in per_ccn.values() if k > 1)
check("time-varying: most CCNs observed in >1 year",
      repeat > 0.5 * len(per_ccn),
      f"{repeat}/{len(per_ccn)} distinct CCNs seen in 2+ of {len(years)} years")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
    sys.exit(1)
print("all checks passed")
sys.exit(0)
