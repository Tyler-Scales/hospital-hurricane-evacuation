# National Hospital Hurricane Evacuation Registry — SEED

**Built:** 2026-08-14, via 10 parallel research agents over public sources.
**Status:** Seed, not census. This is the starting corpus for Phase 2 systematic
abstraction, not its output. Every row carries sources and a confidence grade.

## Files

| File | Contents |
|---|---|
| `registry_events.csv` | 261 named-hospital events, ~35 storms, 1992–2024 |
| `registry_aggregates.csv` | 95 storm-level official/press claims (e.g. "AHCA: 21 hospitals evacuated") — the ascertainment benchmarks |
| `seed_raw.json` | Raw structured agent output, pre-normalization |
| `registry_linked.csv` | Events linked to CMS Certification Numbers by `src/linkage/link_registry.py` (deterministic since 2026-09-07; 188 AUTO, 68 ADJUDICATED, 5 unlinked) |
| `link_overrides.csv` | 25 manual link overrides with reasons |
| `adjudication_verdicts.json` | Human-in-the-loop verdicts for REVIEW-tier matches |
| `fsip_dates_adjudicated.csv` | Hand-adjudicated start of forced patient movement for all 63 FSIP events (best estimate, bounds, end, precision, basis), 2026-09-07 |

## Event coding

| Action | n | Meaning |
|---|---|---|
| `PRE_FULL` | 86 | Complete pre-landfall evacuation |
| `PRE_PARTIAL` | 13 | Some units moved pre-landfall |
| `SIP_OK` | 91 | Sheltered in place, documented as riding it out |
| `POST_FSIP` | 63 | **Failed shelter-in-place** — sheltered, then forced post-impact evacuation under degraded conditions (primary study outcome) |
| `UNCLEAR` | 7 | Conflicting accounts, both sourced (17 at seed; 10 resolved by source re-review 2026-09-07) |
| `POST_REEVAC` | 1 | Evacuated again after a pre-landfall evacuation (Tidelands Georgetown, Florence 2018); not FSIP |

Confidence: 122 HIGH / 119 MEDIUM / 20 LOW.

## Verification anchors — all recovered

Memorial Medical Center, Charity, University, Tulane (Katrina → FSIP);
NYU Langone, Bellevue (Sandy → FSIP); Memorial Hermann TMC (Allison 2001 → FSIP);
Bay Medical Center (Michael → FSIP); UTMB Galveston (Ike → **PRE_FULL**, correctly —
UTMB evacuated ~450 patients ahead of landfall; the workflow brief's FSIP
characterization was wrong and the researcher overrode it).

## First-pass ascertainment vs official aggregates

| Storm | Named here (PRE_*) | Official count | First-pass sensitivity |
|---|---|---|---|
| Milton 2024 | 8 | 21 (AHCA) | ~38% |
| Ian 2022 | 4 (+6 FSIP) | 16 "evacuating" (AHCA) | ~63% combined |

This gap is expected and is itself a study datum: it measures what one
research pass over open web sources recovers versus regulator-reported truth.
Phase 2 (systematic news-archive abstraction: NewsBank, ProQuest, LexisNexis,
state AARs) exists to close it, and the aggregate benchmarks quantify what
remains missing.

## Known limitations

1. **SIP_OK is not a random sample of sheltering** — it captures only hospitals
   whose sheltering was newsworthy. The dyad frame (roster × hazard), not this
   registry, supplies the denominator of hospitals that faced each storm.
2. Deaths are **floor counts** from public reporting, never rates.
3. Storm-name normalization applied; hospital names are as-reported and need
   CCN linkage against the roster (fuzzy name+city+state match) before analysis.
4. Coverage is thinnest for the 1990s groups, as expected from archive decay.
