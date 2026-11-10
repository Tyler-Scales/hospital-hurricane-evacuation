"""Append the source-verification audit's located URLs to the registry's `sources` column.

The September 9, 2026 audit (`Final/source_verification_2026-09-09.csv`) fetched all 391 URLs
cited by the 104 registry records behind the primary analysis and, for 85 of them, located an
additional working or corroborating source in the `additional_source` column. Only the nine
citations tied to the September 10 label and date corrections were written back into
`Final/evacuation_registry.csv`; this script merges the rest.

Append-only: existing citations are never removed or reordered, and URLs already present are
skipped. The `sources` column is free text that no analysis or linkage code reads, so no label,
count, or model estimate can change -- the replication script is re-run afterwards to confirm.

    python3 src/linkage/merge_audit_sources.py            # dry run, prints the diff
    python3 src/linkage/merge_audit_sources.py --apply     # writes, after a .bak copy
"""
import csv, re, shutil, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "Final" / "evacuation_registry.csv"
AUDIT = REPO / "Final" / "source_verification_2026-09-09.csv"
SEP = " | "
URL_RE = re.compile(r"https?://[^\s|,;)\]]+")


def urls(text):
    """URLs in order of appearance, trailing sentence punctuation stripped."""
    out = []
    for u in URL_RE.findall(text or ""):
        u = u.rstrip(".,;:'\"")
        if u not in out:
            out.append(u)
    return out


def key(u):
    """Normalized form for duplicate detection: scheme, www, trailing slash, case."""
    u = u.lower().split("://", 1)[-1]
    if u.startswith("www."):
        u = u[4:]
    return u.rstrip("/")


def main(apply_changes):
    audit = list(csv.DictReader(open(AUDIT)))
    rows = list(csv.DictReader(open(REGISTRY)))
    fields = list(rows[0].keys())

    index = {}
    for r in rows:
        index.setdefault((r["hospital"].strip(), r["storm"].strip(), str(r["year"]).strip()), r)

    changed = added = skipped_dup = 0
    unmatched = []
    wayback = []

    for a in audit:
        found = a.get("additional_source", "").strip()
        if not found:
            continue
        k = (a["hospital"].strip(), a["storm"].strip(), str(a["year"]).strip())
        reg = index.get(k)
        if reg is None:
            unmatched.append(k)
            continue

        have = {key(u) for u in urls(reg["sources"])}
        new = [u for u in urls(found) if key(u) not in have]
        skipped_dup += len(urls(found)) - len(new)
        if not new:
            continue

        label = reg["action"]
        if reg["action"] != a["action"]:
            label = f"{reg['action']} (audit row read {a['action']}; relabeled Sept 10)"
        print(f"* {a['hospital'][:44]} | {a['storm']} {a['year']} | {label}")
        for u in new:
            print(f"    + {u}")
            if re.search(r"wayback|web\.archive", found, re.I):
                wayback.append((a["hospital"], u))
        reg["sources"] = (reg["sources"].strip() + SEP + SEP.join(new)).strip(SEP)
        changed += 1
        added += len(new)

    print(f"\nrows changed {changed} | URLs added {added} | already present {skipped_dup}")
    if unmatched:
        print(f"UNMATCHED audit rows ({len(unmatched)}): {unmatched}")
    if wayback:
        print(f"\n{len(wayback)} added URLs come from audit notes mentioning the Internet Archive;")
        print("the live page may not resolve. Annotations stay in the verification file.")
    print("max URLs in one row after merge:",
          max(len(urls(r["sources"])) for r in rows))

    if not apply_changes:
        print("\nDRY RUN -- nothing written. Re-run with --apply.")
        return
    shutil.copy(REGISTRY, REGISTRY.with_suffix(".csv.bak"))
    with open(REGISTRY, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {REGISTRY} (backup at {REGISTRY.name}.bak)")


if __name__ == "__main__":
    main("--apply" in sys.argv)
