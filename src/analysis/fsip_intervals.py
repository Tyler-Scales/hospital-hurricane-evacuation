#!/usr/bin/env python3
"""Interval from US landfall to post-impact evacuation for every FSIP event.

Landfall: the HURDAT2 'L' record over the US (lat >= 24.4, -98 <= lon <= -66)
nearest in space to the hospital among those at or before the evacuation date
(Katrina's Louisiana landfall for New Orleans hospitals, not its Florida
crossing four days earlier). Evacuation date: the adjudicated start of forced patient movement from
data/registry/fsip_dates_adjudicated.csv (best estimate, bounds, precision grade).

Writes data/interim/fsip_intervals.csv. Run: python3 src/analysis/fsip_intervals.py
"""
import re
from datetime import date, datetime
from pathlib import Path
import numpy as np, pandas as pd

REPO = Path(__file__).resolve().parents[2]
reg = pd.read_csv(REPO / 'data/registry/registry_linked.csv', dtype=str, keep_default_na=False)
tr = pd.read_csv(REPO / 'data/interim/hurdat2_tracks.csv', dtype=str)
su = pd.read_csv(REPO / 'data/interim/storm_universe.csv', dtype=str)
co = pd.read_csv(REPO / 'data/interim/hospital_coords.csv', dtype=str).set_index('ccn')
sid = {(r['name'].upper(), r['year']): r['storm_id'] for _, r in su.iterrows()}
L = tr[tr.record_id == 'L'].copy()
L['dt'] = pd.to_datetime(L.date + L.time.str.zfill(4), format='%Y%m%d%H%M')
L['lat'] = L.lat.astype(float); L['lon'] = L.lon.astype(float)
L = L[(L.lat >= 24.4) & (L.lon.between(-98.0, -66.0))]          # US landfalls only
STATE = {'LA': (30.0, -90.5), 'FL': (28.0, -82.0), 'TX': (29.5, -95.5), 'MS': (30.4, -89.1),
         'NC': (35.0, -79.0), 'SC': (33.5, -80.0), 'NY': (40.7, -73.9), 'NJ': (40.7, -74.1),
         'TN': (36.0, -82.3), 'VT': (44.3, -72.7), 'AL': (31.0, -87.0), 'GA': (32.0, -82.0)}
MON = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
# Adjudicated evacuation dates (data/registry/fsip_dates_adjudicated.csv): one row per
# FSIP event with the best-estimate start of forced patient movement, lower and upper
# bounds, the end date where known, a precision grade (exact / approximate / bounded),
# and the narrative basis. Replaces the earlier keyword date parser, which selected
# reopening or report dates for several Katrina and Michael events (review 2026-09-07).
ADJ = pd.read_csv(REPO / 'data/registry/fsip_dates_adjudicated.csv', dtype=str, keep_default_na=False)


def adjudicated(r):
    m = ADJ[(ADJ.storm == r.storm) & (ADJ.year == r.year) & ADJ.hospital_prefix.apply(lambda p: r.hospital.startswith(p))]
    if len(m) != 1:
        raise SystemExit(f"no unique adjudicated date for {r.storm} {r.year} {r.hospital} ({len(m)} matches)")
    a = m.iloc[0]
    d = lambda v: datetime.strptime(v, '%Y-%m-%d').date() if v else None
    return d(a.evac_start_best), d(a.evac_start_lo), d(a.evac_start_hi), d(a.evac_end), a.precision, a.basis, a.get('bounds_type', '')


rows = []
for _, r in reg[reg.action == 'POST_FSIP'].iterrows():
    y = int(r.year); s = sid.get((r.storm.upper(), r.year)); Ls = L[L.storm_id == s]
    ev, lo, hi, end, prec, basis, btype = adjudicated(r)
    hl = ho = np.nan
    if r.ccn in co.index and co.loc[r.ccn, 'method'] != 'zip_centroid' or (r.ccn in co.index and 17 < float(co.loc[r.ccn, 'lat']) < 50):
        hl, ho = float(co.loc[r.ccn, 'lat']), float(co.loc[r.ccn, 'lon'])
    if np.isnan(hl):
        hl, ho = STATE.get(r.state, (np.nan, np.nan))
    lf = None
    if len(Ls) and not np.isnan(hl):
        # nearest US landfall in space among those on or before the (upper-bound) evacuation start;
        # if the failure preceded every landfall (Hermine/Bayonet Point) fall back to the nearest overall
        cand = Ls[Ls.dt.dt.date <= hi] if hi is not None else Ls
        if not len(cand):
            cand = Ls
        dd = np.hypot(cand.lat - hl, (cand.lon - ho) * 0.87)
        lf = cand.loc[dd.idxmin(), 'dt'].date()
    days = (ev - lf).days if (ev is not None and lf is not None) else None
    rows.append({'storm': r.storm, 'year': y, 'hospital': r.hospital, 'state': r.state, 'ccn': r.ccn,
                 'landfall_utc': lf, 'evac_start_best': ev, 'evac_start_lo': lo, 'evac_start_hi': hi, 'evac_end': end,
                 'precision': prec, 'bounds_type': btype, 'days_best': days,
                 'days_lo': (lo - lf).days if (lo and lf) else None, 'days_hi': (hi - lf).days if (hi and lf) else None,
                 'basis': basis})
t = pd.DataFrame(rows)
t.to_csv(REPO / 'data/interim/fsip_intervals.csv', index=False)
d = t.days_best.dropna().astype(float)
ex = t[t.precision != 'bounded'].days_best.dropna().astype(float)
print(t[['storm', 'year', 'hospital', 'landfall_utc', 'evac_start_best', 'evac_start_lo', 'evac_start_hi', 'days_best', 'precision']].to_string(max_colwidth=38))
print(f"\nFSIP events {len(t)} | precision: {t.precision.value_counts().to_dict()}")
post = t[t.days_best >= 0]
print(f"all {len(t)}, best estimate: median {d.median():.0f} (IQR {d.quantile(.25):.0f}-{d.quantile(.75):.0f}) | before landfall {(d < 0).sum()} | post-landfall same/next day (0-1) {int((post.days_best <= 1).sum())} | days 0-2 {int((post.days_best <= 2).sum())} | within 4 d {int((post.days_best <= 4).sum())} | max {d.max():.0f}")
print(f"bounds entirely within days 0-2: {int(((t.days_lo >= 0) & (t.days_hi <= 2)).sum())} | bounds overlapping 0-2: {int(((t.days_hi >= 0) & (t.days_lo <= 2)).sum())} | inferred/partly stated bounds among bounded: {t[t.precision == 'bounded'].bounds_type.str.split(' ').str[0].value_counts().to_dict()}")
print(f"exact+approximate only (n={len(ex)}): median {ex.median():.0f} (IQR {ex.quantile(.25):.0f}-{ex.quantile(.75):.0f}) | within 7 d {(ex <= 7).sum()} | max {ex.max():.0f}")
print("bounded events and their bounds:"); print(t[t.precision == 'bounded'][['storm', 'hospital', 'days_lo', 'days_hi']].to_string(max_colwidth=40))
print("max upper bound among all:", t.days_hi.max(), "| events with days_hi > 7:", t[t.days_hi > 7][['storm','hospital','days_hi']].values.tolist())
