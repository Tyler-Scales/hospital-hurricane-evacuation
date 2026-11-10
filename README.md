# Failed Shelter-in-Place Among US Hospitals in Atlantic and Gulf Tropical Cyclones, 1990–2025

> **In progress.** This is working research. It has not been peer reviewed, a person has not yet
> checked the registry records against their sources, and the numbers below may change before
> publication. Please don't cite it yet.

**National Hospital Hurricane Evacuation Study (NHHES).** Tyler Wallace, PhD (University of
Georgia) and Curt Harris, PhD (Augusta University).

## What this is

When a hurricane approaches, a hospital either evacuates before the storm or shelters in place.
This project asks what happens when a hospital shelters in place and the shelter fails.

It has two parts:

- **A national cohort** of 80,189 hospital–storm pairs: every acute-care hospital inside the
  forecast threat area of every Atlantic and Gulf landfalling storm, 1990–2025 (3,241 hospitals,
  193 storms, 21 states and DC).
- **A registry** of 261 hospital decisions documented in public sources (news stories, state
  reports, hospital statements) across 31 storms. AI tools did much of the gathering and coding,
  and every record links to its sources.

Early findings: 60 hospitals sheltered in place and then had to evacuate anyway, almost always
within two days of landfall. Power or water failure forced evacuation as often as flooding or
building damage.

## What's in this repository

| Path | Contents |
|---|---|
| `Final/hospital_storm_dyads.csv` | The analysis dataset: one row per hospital–storm pair |
| `Final/evacuation_registry.csv` | The registry: 261 decisions with outcome labels and source links |
| `Final/fsip_mechanisms.csv` | Hand-coded condition that forced each failed shelter-in-place |
| `Final/fsip_dates_adjudicated.csv`, `Final/fsip_intervals.csv` | Evacuation dates and days from landfall for each failure |
| `Final/sipok_observation_windows.csv` | For each hospital that sheltered successfully, the latest date a source shows it operating |
| `Final/decision_outcome_table.csv` | Every labeled pair with what the storm delivered |
| `Final/hospital_decisions_and_outcomes.csv` | Every documented decision with its outcome |
| `Final/registry_aggregate_benchmarks.csv` | Official storm-level counts used to judge how complete the registry is |
| `Final/registry_link_overrides.csv` | Manual links from reported hospital names to CMS provider numbers |
| `Final/source_verification_*.csv` | A September 2026 audit of the registry's sources |
| `src/` | The pipeline: hospital roster, storm and hazard data, linkage, models, tables |
| `data/registry/` | Registry working files |
| `data/interim/` | Intermediate files: roster, geocodes, hazards, forecasts, the pair frame |
| `replication/` | Replication package: re-runs every reported number and checks it |

Raw downloads (NHC forecast files, HURDAT2, CMS Provider of Services and cost reports, PRISM
rainfall, NOAA SLOSH surge rasters) are not included because of their size. All are public, and
the scripts in `src/` fetch or read them.

## Reproduce the results

Requires Python 3 with pandas, numpy, and statsmodels. No network access is needed.

```sh
python3 replication/tier1_analysis/replicate_analysis.py
```

It should end with `PASSED: zero discrepancies`. `replication/tier1_analysis/METHODS_TEXT.md` and
`replication/tier1_analysis/CODEBOOK.md` describe the files and variables. Some counts in the
codebook are out of date and will be corrected.

## Known limitations

- The registry is built from public reporting, so it holds the decisions someone wrote about.
  It is not a census of every hospital's decision.
- No person has yet checked the records against their sources. A check of a 55-record sample
  is under way.
- Associations between hospital siting and failure are weak and imprecise. No conclusion here
  rests on them.

## Data sources

NOAA National Hurricane Center (HURDAT2 best tracks, ATCF official forecasts), CMS Provider of
Services files and Healthcare Cost Report Information System, NOAA SLOSH Maximum of Maximums
surge maps, PRISM daily precipitation, USGS 3DEP elevation, FEMA National Flood Hazard Layer, US
Census geocoder and gazetteer, and public news, state, and hospital reports for the registry.
