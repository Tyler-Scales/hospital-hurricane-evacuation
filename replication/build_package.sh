#!/bin/sh
# Rebuild Final/replication_package.zip from replication/ and verify it from a clean extraction.
# Ships: top-level docs, tier1_analysis/ (re-runs every reported number), tier2_cohort_rebuild/.
# Excludes reviewer3*/ and replication_results/ (review-round working files, not part of the package).
set -e
cd "$(dirname "$0")"
OUT=../Final/replication_package.zip
rm -f "$OUT"
zip -qrX "$OUT" CHANGELOG.md CHATGPT_PROMPT.md FINDINGS.md README.md tier1_analysis tier2_cohort_rebuild \
    -x '*/.DS_Store' '*/__pycache__/*'
T=$(mktemp -d)
unzip -q "$OUT" -d "$T"
(cd "$T/tier1_analysis" && python3 replicate_analysis.py | tail -1)
grep -q 'FAILURE MECHANISMS' "$T/tier1_analysis/replicate_analysis.py" || { echo "package lacks Table 2 checks"; exit 1; }
rm -rf "$T"
echo "wrote $OUT"
