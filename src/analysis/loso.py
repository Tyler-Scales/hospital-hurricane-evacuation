#!/usr/bin/env python3
"""Leave-one-storm-out re-estimation of the primary FSIP model.

Refits P(FSIP | sheltered, non-leveed) on storm intensity + Category-3 surge
zone + log beds, dropping each storm in turn. Writes data/interim/loso_results.csv
and prints the range of the surge and size odds ratios.

Run: python3 src/analysis/loso.py
"""
import warnings
from pathlib import Path
import sys
import numpy as np, pandas as pd, statsmodels.api as sm
warnings.filterwarnings('ignore')
sys.path.insert(0, str(Path(__file__).resolve().parent)); from scaling import primary_scales, standardize
REPO = Path(__file__).resolve().parents[2]
df = pd.read_csv(REPO / 'data/interim/dyad_frame_full.csv', low_memory=False)
lab = df[df.action.notna() & (df.action != '')]
sh = lab[lab.action.isin(['SIP_OK', 'POST_FSIP']) & (lab.tier.astype(str) == '2')].copy()   # analytic period 2004-2025
sh['fsip'] = (sh.action == 'POST_FSIP').astype(int)
s3 = sh.surge_cat3_ft.astype(str)
sh = sh[s3 != 'leveed'].copy()
sh['surge'] = (pd.to_numeric(sh.surge_cat3_ft, errors='coerce') > 0).astype(float)
sh['lb'] = np.log1p(pd.to_numeric(sh.beds, errors='coerce'))
sh['vm'] = pd.to_numeric(sh.vmax_close_kt, errors='coerce')
base = sh.dropna(subset=['vm', 'surge', 'lb'])
SCALES = primary_scales(base)
rows = []
for sid in sorted(base.storm_id.unique()):
    d = base[base.storm_id != sid]
    X = standardize(sm.add_constant(d[['vm', 'surge', 'lb']].astype(float)), ['vm', 'surge', 'lb'], SCALES)
    try:
        r = sm.Logit(d.fsip, X).fit(disp=0, maxiter=300)
        rows.append({'left_out': sid, 'storm': base[base.storm_id == sid].storm.iloc[0],
                     'n': len(d), 'events': int(d.fsip.sum()),
                     'or_surge': np.exp(r.params['surge']), 'or_size': np.exp(r.params['lb']),
                     'or_vmax': np.exp(r.params['vm'])})
    except Exception as e:
        rows.append({'left_out': sid, 'storm': '', 'n': len(d), 'events': int(d.fsip.sum()),
                     'or_surge': np.nan, 'or_size': np.nan, 'or_vmax': np.nan})
out = pd.DataFrame(rows)
out.to_csv(REPO / 'data/interim/loso_results.csv', index=False)
print(f"storms left out: {len(out)} (base n={len(base)}, events={int(base.fsip.sum())})")
print(f"surge OR range {out.or_surge.min():.2f}–{out.or_surge.max():.2f}; size OR range {out.or_size.min():.2f}–{out.or_size.max():.2f}; vmax {out.or_vmax.min():.2f}–{out.or_vmax.max():.2f}")
print(f"storms whose removal changes surge OR most: {out.sort_values('or_surge').iloc[[0,-1]][['storm','or_surge']].to_dict('records')}")
