#!/usr/bin/env python3
"""
Link registry events (hospital name as reported by news/AARs) to roster CCNs.

Names in news coverage rarely match POS facility names exactly ("Memorial
Medical Center" vs "MEMORIAL MEDICAL CENTER - NEW ORLEANS"; "HCA Florida
Fawcett Hospital" vs "FAWCETT MEMORIAL HOSPITAL"), so matching is fuzzy:
state-restricted, scored on name-token overlap + sequence similarity + city
agreement, matched against the union of every name a CCN has carried in any
roster year (names drift across vintages; the union catches renames).

Outputs data/registry/registry_linked.csv: every event with its best CCN,
match score, and tier (AUTO / REVIEW / UNMATCHED). Nothing below the AUTO
threshold silently enters analysis — REVIEW rows need a human eye.

Usage:
    python3 src/linkage/link_registry.py
"""

import csv
import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROSTER = REPO / "data" / "interim" / "hospital_roster.csv"
EVENTS = REPO / "data" / "registry" / "registry_events.csv"
OUT = REPO / "data" / "registry" / "registry_linked.csv"
VERDICTS = REPO / "data" / "registry" / "adjudication_verdicts.json"
OVERRIDES = REPO / "data" / "registry" / "link_overrides.csv"

AUTO_THRESHOLD = 0.80
REVIEW_THRESHOLD = 0.55

# Tokens that carry no identity: generic hospital-ese and chain prefixes that
# news adds or drops freely.
STOP = {
    "HOSPITAL", "HOSPITALS", "MEDICAL", "CENTER", "CENTRE", "REGIONAL",
    "HEALTH", "HEALTHCARE", "SYSTEM", "THE", "OF", "AND", "AT", "INC",
    "CAMPUS", "FACILITY", "HCA", "FLORIDA", "ADVENTHEALTH", "ASCENSION",
    "CHRISTUS", "BAPTIST",  # kept in city scoring; dropped only for tokens
    "ST", "SAINT", "MEMORIAL",
}
SYNONYM = {"UNIV": "UNIVERSITY", "MED": "MEDICAL", "CTR": "CENTER",
           "HOSP": "HOSPITAL", "COMM": "COMMUNITY", "GEN": "GENERAL"}


def norm(s):
    s = re.sub(r"\(.*?\)", " ", s.upper())
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    toks = [SYNONYM.get(t, t) for t in s.split()]
    return " ".join(toks)


def sig_tokens(s):
    return {t for t in norm(s).split() if t not in STOP and len(t) > 1}


def score(event_name, event_city, cand_name, cand_city):
    en, cn = norm(event_name), norm(cand_name)
    et, ct = sig_tokens(event_name), sig_tokens(cand_name)

    # Names made entirely of generic tokens ("Memorial Regional Hospital")
    # produce empty significant sets; fall back to all-token comparison so an
    # exact generic name still scores as a match.
    if not et or not ct:
        et = set(en.split())
        ct = set(cn.split())

    seq = SequenceMatcher(None, en, cn).ratio()
    jac = len(et & ct) / len(et | ct) if (et or ct) else 0.0
    s = 0.45 * seq + 0.55 * jac

    if event_city and cand_city:
        if norm(event_city) == norm(cand_city):
            s += 0.15
        elif sig_tokens(event_city) & sig_tokens(cand_city):
            s += 0.08
    # exact significant-token containment (news shortens: "Fawcett" ⊂
    # "FAWCETT MEMORIAL") deserves a floor
    if et and et <= ct:
        s = max(s, 0.72 + (0.15 if event_city and cand_city
                           and norm(event_city) == norm(cand_city) else 0))
    return min(s, 1.0)


def city_agrees(event_city, cand_city):
    """True when the reported city and the roster city plausibly coincide.
    Empty roster city is treated as unknown (agrees)."""
    if not event_city or not cand_city:
        return True
    ec = norm(event_city.split("(")[0].split("/")[0])
    cc = norm(cand_city)
    if ec == cc:
        return True
    et, ct = set(ec.split()) - {"ST", "SAINT", "FORT", "FT", "NORTH", "SOUTH",
                                "EAST", "WEST", "BEACH", "CITY"}, set(cc.split())
    return bool(et & ct)


def main():
    # Candidate pool: union of names per CCN per state across all roster years,
    # with the CCN's participation/termination window (latest vintage) so a
    # storm can prefer the certification that was actually active that year.
    cands = defaultdict(set)   # state -> {(ccn, name, city)}
    window = {}                # ccn -> (part_year, term_year or 9999)
    latest = {}
    vintages = defaultdict(set)   # (ccn, name, city) -> roster years carrying that name
    with ROSTER.open() as fh:
        for r in csv.DictReader(fh):
            if r["ccn"] and r["name"]:
                cands[r["state"]].add((r["ccn"], r["name"], r["city"]))
                vintages[(r["ccn"], r["name"], r["city"])].add(int(r["year"]))
                y = int(r["year"])
                if r["ccn"] not in latest or y > latest[r["ccn"]][0]:
                    latest[r["ccn"]] = (y, r)
    for ccn, (_, r) in latest.items():
        pm = re.match(r"(\d{4})\d{4}$", (r["participation_date"] or "").strip())
        tm = re.match(r"(\d{4})\d{4}$", (r["termination_date"] or "").strip())
        code = (r["termination_code"] or "").strip().lstrip("0")
        part = int(pm.group(1)) if pm else 0
        term = int(tm.group(1)) if (code and tm) else 9999
        window[ccn] = (part, term)

    verdicts = {}
    if VERDICTS.exists():
        for v in json.load(VERDICTS.open()):
            verdicts[(v["storm"], str(v["year"]), v["event_hospital"])] = v
    overrides = {}
    if OVERRIDES.exists():
        for o in csv.DictReader(OVERRIDES.open()):
            overrides[(o["storm"], str(o["year"]), o["hospital"])] = o

    events = list(csv.DictReader(EVENTS.open()))
    out, tally = [], defaultdict(int)

    for e in events:
        state = e["state"].strip().upper()
        year = int(e["year"])
        best = (0.0, "", "", "", False); best_gap = 10**6
        # Deterministic iteration (sets iterate in hash order, which varies run to
        # run) and a deterministic tie-break: among equal adjusted scores prefer the
        # candidate whose roster name is from the vintage nearest the storm year,
        # so a name a certification carried decades away from the storm does not
        # outrank the certification that carried it at the time.
        for ccn, name, city in sorted(cands.get(state, ())):
            sc = score(e["hospital"], e.get("city", ""), name, city)
            part, term = window.get(ccn, (0, 9999))
            active = part <= year <= term
            # A certification that was not active in the storm year is almost
            # never the right link (predecessor/successor CCNs share names).
            adj = sc + (0.0 if active else -0.15)
            gap = min(abs(v - year) for v in vintages[(ccn, name, city)])
            if adj > best[0] or (adj == best[0] and gap < best_gap):
                best = (adj, ccn, name, city, active); best_gap = gap

        sc, ccn, mname, mcity, active = best
        if sc >= AUTO_THRESHOLD and city_agrees(e.get("city", ""), mcity) and active:
            tier = "AUTO"
        elif sc >= REVIEW_THRESHOLD:
            tier = "REVIEW"
        else:
            tier, ccn, mname, mcity = "UNMATCHED", "", "", ""

        key = (e["storm"], str(e["year"]), e["hospital"])
        v = verdicts.get(key)
        if v:
            if v.get("verdict") == "MATCH" and v.get("ccn"):
                ccn, mname, tier = v["ccn"], v.get("matched_name", mname), "ADJUDICATED"
                mcity = next((c for cc, n, c in cands.get(state, ()) if cc == ccn), mcity)
            elif v.get("verdict") in ("NO_CCN", "UNSURE"):
                tier, ccn, mname, mcity = v["verdict"], "", "", ""
        o = overrides.get(key)
        if o:
            if o["ccn"]:
                ccn, mname, tier = o["ccn"], o["matched_name"], "ADJUDICATED"
                mcity = next((c for cc, n, c in cands.get(state, ()) if cc == ccn), "")
            else:
                tier, ccn, mname, mcity = "NO_CCN", "", "", ""
        tally[tier] += 1
        out.append({**e, "ccn": ccn, "matched_name": mname,
                    "matched_city": mcity, "match_score": f"{sc:.3f}",
                    "match_tier": tier})

    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    print(f"events: {len(events)}  tiers: {dict(tally)}")
    print(f"Wrote {OUT.relative_to(REPO)}")
    print("\nREVIEW rows (need human adjudication):")
    for r in out:
        if r["match_tier"] == "REVIEW":
            print(f"  {r['match_score']}  {r['storm']} {r['year']}  {r['hospital'][:45]:<47} [{r['city'][:18]:<18}] -> "
                  f"{r['matched_name'][:38]:<40} [{r['matched_city'][:16]}] {r['ccn']}")
    print("\nUNMATCHED rows:")
    for r in out:
        if r["match_tier"] == "UNMATCHED":
            print(f"  {r['storm']} {r['year']}  {r['hospital'][:60]}  [{r['city']}, {r['state']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
