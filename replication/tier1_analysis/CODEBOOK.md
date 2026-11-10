# Codebook: hospital_storm_dyads.csv, evacuation_registry.csv, fsip_intervals.csv, fsip_dates_adjudicated.csv, link_overrides.csv

Final release, 2026-09-07 (see ../CHANGELOG.md).

## hospital_storm_dyads.csv (80,189 rows; one row per hospital x storm, 1990–2025)

A row exists when the hospital was inside the storm's observed 34-kt wind field
(`in34`) OR inside the forecast threat area 48 h before tropical-storm-force
winds arrived (`in_cone`), after a 400-nmi closest-approach screen.

| Column | Meaning |
|---|---|
| storm_id | HURDAT2 id (ALnnYYYY) |
| storm, year | Storm name (upper case) and season |
| ccn | CMS Certification Number (6 chars; F-suffix = federal VA/DoD) |
| name, state | Hospital name and state from the most recent roster vintage (2018); beds, ownership, and critical-access status come from the vintage nearest the storm |
| tier | 1 = 1990–2003 (no wind radii; descriptive), 2 = 2004–2025 (analytic) |
| in34, in50, in64 | True/False: inside the 34/50/64-kt quadrant wind field at any hour (blank for tier 1) |
| min_track_nm | Closest approach of the hourly-densified track, nautical miles, measured while the system was at least tropical-storm strength where such a point lay within 400 nmi |
| vmax_close_kt | Best-track intensity (kt) at closest approach |
| fwd_speed_kt | Storm forward speed at closest approach |
| anchor | Decision-clock anchor: `ts_wind_onset` (first hour inside the 34-kt field) or `closest_approach` |
| fcst_cycle | Official NHC forecast cycle (YYYYMMDDHH) issued at or before anchor minus 48 h |
| fcst_min_nm | Shortest distance from hospital to that cycle's forecast positions (12-h steps, 0–72 h; not interpolated between positions) |
| fcst_vmax_kt | Highest forecast intensity over 0–72 h in that cycle |
| cone_p67_nm | Era 67th-percentile 48-h track error: 196 (1990–99), 131 (2000–09), 87 (2010–17), 72 (2018–25) |
| in_cone | fcst_min_nm <= cone_p67_nm + 100 (forecast threat area) |
| beds | Certified beds, POS vintage nearest the storm year |
| ownership | CMS hospital ownership class (for_profit, physician_owned_for_profit, private_nonprofit, church_nonprofit, other_nonprofit, government_*) |
| pa_eligible | Eligible for FEMA Public Assistance (non-profit or government) |
| is_cah | Critical access hospital |
| is_federal | Federal (VA/DoD) facility |
| part_year | Year of original Medicare participation |
| coord_method | census_street (rooftop/interpolated), osm_name (OpenStreetMap facility point), zip_centroid (ZIP center; no surge/elevation/flood values) |
| action | Registry label: SIP_OK, POST_FSIP (failed shelter-in-place), PRE_FULL, PRE_PARTIAL, UNCLEAR; blank = no documented decision |
| action_confidence | HIGH / MEDIUM / LOW label confidence |
| elev_ft_usgs | Ground elevation (USGS 3DEP), feet |
| fld_zone, sfha, static_bfe | FEMA NFHL flood zone, special-flood-hazard flag, base flood elevation |
| surge_cat1_ft ... surge_cat5_ft | SLOSH MOM high-tide inundation depth (ft) by category; 0 = dry; the string `leveed` = inside a levee-protected polygon (no depth) |
| surge_any | True/False/leveed: any category-1–5 inundation |
| rain_total_mm, rain_max_daily_mm | PRISM 4-km storm-window rainfall at the hospital point |
| plant_age_years, plant_age_fy | HCRIS average age of plant (years) and the fiscal year used |

Analysis conventions (as in the manuscript): analytic period = tier 2 (2004–2025);
sheltering pairs = action in {SIP_OK, POST_FSIP}; FSIP = POST_FSIP (complete or
partial post-impact evacuation); primary model sample = 2004–2025 sheltering pairs
not `leveed` with non-missing intensity, surge, and beds; comparisons using flood
zone or elevation drop pairs with unknown values (complete case); Category-3 surge zone
= surge_cat3_ft > 0; hospital size = log(1 + beds); continuous predictors are
centered on each sample's mean and divided by FIXED divisors, the standard deviations in
the primary sample (log(1+beds) 0.925; intensity 26.7 kt; log(1+rain mm) 0.864; plant age
8.70 y; elevation 343.8 ft), so one unit means the same thing in every model; logistic
regression via maximum likelihood; Firth penalized likelihood (firth.py) with Wald
intervals from the penalized information matrix; cluster-robust SEs by hospital (81
clusters) and by storm (24), fitted separately. Multi-campus certifications (sensitivity
S8) are primary pairs whose (storm, year, ccn) key carries more than one registry row.
Decision model (Supplementary Table S3 / Table A.3): 2004-2025 pairs with a documented
evacuation or sheltering decision (UNCLEAR excluded), outcome = PRE_FULL or PRE_PARTIAL;
cone ratio and forecast intensity standardized within that sample, hospital size with the
primary-sample divisor.


## evacuation_registry.csv (261 rows; one row per documented facility decision)

| Column | Meaning |
|---|---|
| storm, year, hospital, city, state | As reported in the sources |
| action | SIP_OK, POST_FSIP, POST_REEVAC (re-evacuation after a pre-landfall evacuation; not FSIP), PRE_FULL, PRE_PARTIAL, UNCLEAR |
| timing, patients_moved, deaths_documented, detail | Abstracted narrative fields |
| confidence | HIGH / MEDIUM / LOW |
| sources | Citations (URLs) |
| ccn, matched_name, matched_city, match_score, match_tier | Link to the CMS certification (AUTO = automatic match; ADJUDICATED = human-reviewed; NO_CCN / UNSURE / UNMATCHED = not linked) |

Where several campuses share one CCN, the pair label in the cohort file follows:
POST_FSIP > mixed PRE/SIP -> PRE_PARTIAL > PRE_FULL > PRE_PARTIAL > SIP_OK > UNCLEAR.

## fsip_intervals.csv (63 rows; one per POST_FSIP registry event)

| Column | Meaning |
|---|---|
| storm, year, hospital, state, ccn | Registry keys |
| landfall_utc | Date (UTC) of the HURDAT2 US landfall record nearest the hospital among those on or before the evacuation start upper bound; nearest overall when the failure preceded every landfall |
| evac_start_best, evac_start_lo, evac_start_hi | Adjudicated date forced patient movement began: best estimate and bounds |
| evac_end | Completion date where the narrative gives one |
| precision | exact (stated date), approximate (within about a day), bounded (narrative gives only a window; best = midpoint, rounded down for a half day) |
| bounds_type | For bounded events: stated (window given by a source), partly stated (one endpoint from a source or the host hospital's dates), inferred (window assumed from regional context; an assumption, not a source-established endpoint); otherwise not applicable |
| days_best, days_lo, days_hi | evac_start minus landfall_utc, in days, for best estimate and bounds (negative = before landfall) |
| basis | Narrative basis for the adjudicated dates |

## fsip_dates_adjudicated.csv (63 rows)

Source table for the above, keyed by storm, year, and a hospital-name prefix; same date and precision columns plus `bounds_type` and `basis`. Reopening dates, report dates, and article dates were never used as evacuation dates.

## link_overrides.csv (25 rows)

Manual registry-to-CCN links applied after automatic matching, each with the reason (storm, year, hospital, ccn, matched_name, note). Applied by `src/linkage/link_registry.py`, which is deterministic (sorted candidate iteration; ties broken toward the roster vintage nearest the storm year).
