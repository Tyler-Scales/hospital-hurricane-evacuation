# Rebuild the analysis file from interim inputs

From this folder (paths are relative to the folder root):

    python3 src/linkage/build_dyads.py        # -> data/interim/dyad_frame.csv
    python3 src/linkage/merge_covariates.py   # -> data/interim/dyad_frame_full.csv

Expected: 80,189 pairs, 193 storms, 3,241 hospitals, 214 labeled pairs (with the final `data/registry/registry_linked.csv`; the penultimate registry gave 213 because one Sandy event was linked to a legacy certification outside the population).
`dyad_frame_full.csv` minus the duplicate `elev_ft` column equals
`tier1_analysis/hospital_storm_dyads.csv`.

Inputs: HURDAT2 best tracks (hurdat2_tracks.csv), NHC official forecasts from
ATCF a-decks (ofcl_forecasts.csv), the screened storm list (storm_universe.csv),
the CMS POS hospital roster 1990-2018 (hospital_roster.csv), the linked registry and its inputs (data/registry/: registry_events.csv, link_overrides.csv, adjudication_verdicts.json, registry_linked.csv; regenerate the last with src/linkage/link_registry.py), hospital
coordinates with precision method (hospital_coords.csv), and the per-hospital
covariate files (elevation, surge, flood zone, plant age) plus per-pair rainfall.
The scripts use only the Python standard library and numpy (merge uses csv).


No output snapshots are shipped: `dyad_frame.csv` and `dyad_frame_full.csv` are produced by the two commands above and, minus the duplicate `elev_ft` column, must equal `tier1_analysis/hospital_storm_dyads.csv` cell for cell (verified 2026-09-09: 80,189 rows, 42 columns, zero unequal cells).
