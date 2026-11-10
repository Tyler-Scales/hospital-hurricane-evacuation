#!/usr/bin/env python3
"""Build Final/NHHES_record_check.xlsx: 55 registry records for a person to confirm.

The 55 are the double-coded events in Final/student_coding_packet/.sealed_key.csv
(a random subset of the September stratified sample of 90). For each record the
sheet shows what the registry says happened, when, why (failures only), and
clickable source links; the checker marks Correct? Yes, No, or Can't tell.

Sources come from Final/evacuation_registry.csv as bare URLs (the
"[added 2026-09-09 source verification]" tag is stripped, duplicates removed).
Two hospital names that carried coding notes are shortened.

Usage:  python3 src/analysis/make_record_check.py
"""
import csv
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "Final" / "NHHES_record_check.xlsx"
read = lambda p: list(csv.DictReader(open(REPO / p, encoding="utf-8")))

key = [r for r in read("Final/student_coding_packet/.sealed_key.csv") if r["double_coded"] == "True"]
reg = read("Final/evacuation_registry.csv")
mech = read("Final/fsip_mechanisms.csv")
dates = read("Final/fsip_dates_adjudicated.csv")
wins = read("Final/sipok_observation_windows.csv")

CLEAN_NAMES = {"138b1a033f": "Unnamed Houma hospital (possibly Chabert or Terrebonne General)",
               "2d450570c7": "Vermont State Hospital (state psychiatric hospital)"}
OUTCOME = {"PRE_FULL": "Evacuated all patients before the storm",
           "PRE_PARTIAL": "Moved some patients out before the storm, kept the rest",
           "SIP_OK": "Stayed open through the storm; no patients forced out",
           "POST_FSIP": "Stayed open, then had to evacuate after the storm hit",
           "POST_REEVAC": "Evacuated before the storm, then had to move patients again",
           "UNCLEAR": "Unclear from the sources"}


def nice(iso):
    d = date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def registry_row(k):
    m = [r for r in reg if (r["storm"], r["year"], r["hospital"], r["action"]) ==
         (k["storm"], k["year"], k["hospital"], k["action"])]
    assert len(m) == 1, k["event_id"]
    return m[0]


rows = []
for k in key:
    g = registry_row(k)
    urls = list(dict.fromkeys(re.findall(r"https?://\S+", g["sources"].replace("|", " "))))
    when, why = g["timing"], ""
    if k["action"] == "POST_FSIP":
        d = [x for x in dates if x["storm"] == k["storm"] and x["year"] == k["year"]
             and k["hospital"].lower().startswith(x["hospital_prefix"].lower())]
        m = [x for x in mech if x["storm"] == k["storm"] and x["year"] == k["year"]
             and x["hospital"][:24].lower() == k["hospital"][:24].lower()]
        assert len(d) == 1 and len(m) == 1, k["event_id"]
        when = (f"Patients started moving {'on' if d[0]['precision'] == 'exact' else 'about'} "
                f"{nice(d[0]['evac_start_best'])}")
        parts = m[0]["mechanisms"].split("|")
        why = "; ".join([parts[0]] + [p[:1].lower() + p[1:] for p in parts[1:]])
    elif k["action"] == "SIP_OK":
        w = [x for x in wins if x["storm"] == k["storm"] and x["year"] == k["year"]
             and x["hospital"] == k["hospital"]]
        if len(w) == 1 and w[0]["observed_through"]:
            when = f"Still open, no patients forced out, on {nice(w[0]['observed_through'])}"
    rows.append({"hospital": CLEAN_NAMES.get(k["event_id"], k["hospital"]),
                 "place": f"{k['city']}, {k['state']}", "storm": k["storm"], "year": int(k["year"]),
                 "what": OUTCOME[k["action"]], "when": when, "why": why, "urls": urls,
                 "id": k["event_id"]})
rows.sort(key=lambda r: (r["year"], r["storm"], r["hospital"]))
nsrc = max(len(r["urls"]) for r in rows)

F = "Arial"
base, bold = Font(name=F, size=10), Font(name=F, size=10, bold=True)
grey_it = Font(name=F, size=10, italic=True, color="808080")
link = Font(name=F, size=10, color="0563C1", underline="single")
head_fill = PatternFill("solid", start_color="D9E2EC")
input_fill = PatternFill("solid", start_color="FFF2CC")
thin = Side(style="thin", color="BFBFBF")
box = Border(top=thin, bottom=thin, left=thin, right=thin)
wrap = Alignment(wrap_text=True, vertical="top")

wb = Workbook()
ws = wb.active
ws.title = "Check"
heads = (["#", "Hospital", "City, State", "Storm", "Year", "What our records say happened", "When",
          "Why they evacuated (only for evacuations after the storm)", "Correct?",
          "Notes (if No, what the sources show, with a link)"]
         + [f"Source {i}" for i in range(1, nsrc + 1)] + ["ID"])
widths = [5, 34, 22, 10, 7, 30, 30, 30, 12, 44] + [16] * nsrc + [12]
last = len(heads)

ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=10)
ws["A1"] = ("For each row, open the sources and mark Correct? as Yes, No, or Can't tell. If No, say what "
            "the sources show in Notes. Fill in only the yellow columns. Row 3 is an example. The How to "
            "tab explains the rules.")
ws["A1"].font, ws["A1"].alignment = bold, Alignment(wrap_text=True, vertical="center")
ws.row_dimensions[1].height = 42
for c, (h, w) in enumerate(zip(heads, widths), start=1):
    cell = ws.cell(row=2, column=c, value=h)
    cell.font, cell.fill, cell.alignment, cell.border = bold, head_fill, wrap, box
    ws.column_dimensions[cell.column_letter].width = w
for c in (9, 10):
    ws.cell(row=2, column=c).fill = PatternFill("solid", start_color="FFD966")

example = ["Ex.", "Example Hospital", "Anytown, FL", "Ian", 2022, OUTCOME["POST_FSIP"],
           "Patients started moving on Sep 29, 2022", "Loss of water supply", "No",
           "The second source says patients started moving Sep 30, not Sep 29. https://www.example.com/story"]
for c, v in enumerate(example, start=1):
    cell = ws.cell(row=3, column=c, value=v)
    cell.font, cell.alignment, cell.border = grey_it, wrap, box
ws.cell(row=3, column=11, value="example.com").font = grey_it

for i, r in enumerate(rows, start=1):
    rr = i + 3
    vals = [i, r["hospital"], r["place"], r["storm"], r["year"], r["what"], r["when"], r["why"], None, None]
    for c, v in enumerate(vals, start=1):
        cell = ws.cell(row=rr, column=c, value=v)
        cell.font, cell.alignment, cell.border = base, wrap, box
    for c in (9, 10):
        ws.cell(row=rr, column=c).fill = input_fill
    for j, u in enumerate(r["urls"]):
        host = urlparse(u).netloc
        cell = ws.cell(row=rr, column=11 + j, value=(host[4:] if host.startswith("www.") else host) or u)
        cell.hyperlink, cell.font, cell.alignment, cell.border = u, link, wrap, box
    ws.cell(row=rr, column=last, value=r["id"]).font = Font(name=F, size=8, color="A6A6A6")

dv = DataValidation(type="list", formula1='"Yes,No,Can\'t tell"', allow_blank=True,
                    error="Choose Yes, No, or Can't tell.", errorTitle="Correct?")
ws.add_data_validation(dv)
dv.add(f"I3:I{len(rows) + 3}")
ws.freeze_panes = "C3"
ws.auto_filter.ref = f"A2:{ws.cell(row=2, column=last).column_letter}{len(rows) + 3}"

how = wb.create_sheet("How to")
how.column_dimensions["A"].width = 100
lines = [
    ("How to check a row", bold),
    ("1. Open the sources (the blue links to the right of each row). If a link is dead, try web.archive.org. You can also search for other sources.", base),
    ("2. Check three things: what happened, when, and why (the why column is filled only for hospitals that had to evacuate after the storm).", base),
    ("3. Mark Correct?: Yes if the sources support all of it. No if any part is wrong. Can't tell if the sources don't say.", base),
    ("4. If No, write what the sources show in Notes and paste the link.", base),
    ("", base),
    ("What the outcomes mean", bold),
    ("Evacuated all patients before the storm: everyone was moved out before storm conditions reached the hospital.", base),
    ("Moved some patients out before the storm, kept the rest: for example an ICU or NICU was transferred and the hospital stayed open.", base),
    ("Stayed open through the storm; no patients forced out: a source says the hospital kept operating.", base),
    ("Stayed open, then had to evacuate after the storm hit: patients were forced out after storm conditions arrived because something broke down.", base),
    ("Evacuated before the storm, then had to move patients again: rare.", base),
    ("", base),
    ("Rules", bold),
    ("A Yes needs a source that says so. Don't fill gaps with what seems likely.", base),
    ("Sending patients home isn't an evacuation. Moving them to another hospital is.", base),
    ("Before the storm means before storm conditions reached the hospital, not before landfall.", base),
    ("If some patients left before the storm and the rest were forced out after, the hospital had to evacuate after the storm.", base),
    ("If city water or power failed and that forced patients out, the hospital had to evacuate after the storm.", base),
    ("Moving patients to another floor of the same building isn't an evacuation.", base),
    ("Don't use AI tools for this.", base),
    ("", base),
    ("Questions: Tyler Wallace, tylerwallace@uga.edu", base),
]
for i, (t, f) in enumerate(lines, start=1):
    c = how.cell(row=i, column=1, value=t)
    c.font, c.alignment = f, Alignment(wrap_text=True, vertical="top")

wb.save(OUT)
print(f"wrote {OUT.relative_to(REPO)}: {len(rows)} records, {sum(len(r['urls']) for r in rows)} source links")
