#!/usr/bin/env python3
"""
Sensitivity suite for the FSIP model (analytic period 2004-2025 unless stated).

  BASE  primary model on 2004-2025 non-leveed sheltering pairs
  S1    cluster-robust SEs (hospital, storm)   -> pairs are not independent
  S2    leave-Katrina-out                      -> one storm supplies ~25% of events
  S3    exclude LOW-confidence labels          -> registry coding quality
  S4    leveed as its own indicator            -> highest-risk stratum was excluded
  S5    all years 1990-2025                    -> the pre-2004 pairs (no wind radii)
  S6    Firth penalized likelihood             -> events-per-variable ~10

Run: python3 src/analysis/sensitivity.py
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd, statsmodels.api as sm
warnings.filterwarnings('ignore')
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent)); from firth import firth_logit; from scaling import primary_scales, standardize
df = pd.read_csv(REPO / 'data/interim/dyad_frame_full.csv', low_memory=False)
lab = df[df.action.notna() & (df.action != '')].copy()
sh = lab[lab.action.isin(['SIP_OK', 'POST_FSIP'])].copy()
sh['fsip'] = (sh.action == 'POST_FSIP').astype(int)
s3 = sh.surge_cat3_ft.astype(str)
sh['lev'] = (s3 == 'leveed').astype(float)
sh['surge'] = (pd.to_numeric(s3.where(s3 != 'leveed'), errors='coerce') > 0).astype(float)
sh.loc[sh.lev == 1, 'surge'] = 0.0
sh['lb'] = np.log1p(pd.to_numeric(sh.beds, errors='coerce'))
sh['vm'] = pd.to_numeric(sh.vmax_close_kt, errors='coerce')
sh['fp'] = sh.ownership.isin(['for_profit', 'physician_owned_for_profit']).astype(float)
t2 = sh[sh.tier.astype(str) == '2']

SCALES = {}

def design(d, preds):
    dd = d[['fsip'] + preds].dropna()
    X = standardize(sm.add_constant(dd[preds].astype(float)), preds, SCALES)
    return dd, X

def fit(d, preds, label, cluster=None, firth=False):
    dd = d[['fsip'] + preds + ([cluster] if cluster else [])].dropna()
    X = standardize(sm.add_constant(dd[preds].astype(float)), preds, SCALES)
    if firth:
        b, se, info = firth_logit(dd.fsip.values, X.values, return_info=True)
        print(f"{label}  (n={len(dd)}, ev={int(dd.fsip.sum())}, Firth; converged={info['converged']} in {info['iterations']} iterations; SEs from inverse Fisher information at the penalized estimates)")
        for i, c in enumerate(X.columns):
            if c in preds: print(f"    {c:<8} OR={np.exp(b[i]):5.2f} [{np.exp(b[i]-1.96*se[i]):5.2f},{np.exp(b[i]+1.96*se[i]):6.2f}]")
        return
    m = sm.Logit(dd['fsip'], X)
    r = m.fit(disp=0, maxiter=300, cov_type='cluster', cov_kwds={'groups': pd.factorize(dd[cluster])[0]}) if cluster else m.fit(disp=0, maxiter=300)
    ci = r.conf_int()
    print(f"{label}  (n={len(dd)}, ev={int(dd.fsip.sum())}, pseudo-R2={r.prsquared:.3f})")
    for c in preds:
        print(f"    {c:<8} OR={np.exp(r.params[c]):5.2f} [{np.exp(ci.loc[c,0]):5.2f},{np.exp(ci.loc[c,1]):6.2f}] p={r.pvalues[c]:.3f}")

base = t2[t2.lev == 0]
_b = base.dropna(subset=['vm', 'surge', 'lb']).copy()
_b['lr'] = np.log1p(pd.to_numeric(_b.rain_total_mm, errors='coerce')); _b['age'] = pd.to_numeric(_b.plant_age_years, errors='coerce'); _b['el'] = pd.to_numeric(_b.elev_ft_usgs, errors='coerce')
SCALES.update(primary_scales(_b))
print("Fixed scaling (SD in primary sample):", {k: round(v, 3) for k, v in SCALES.items()}, "| one size unit = %.2f-fold in beds" % np.exp(SCALES['lb']))
print(f"Primary sample clusters: {_b.ccn.nunique()} hospitals, {_b.storm_id.nunique()} storms")
print("BASE  2004-2025, non-leveed sheltering pairs"); fit(base, ['vm', 'surge', 'lb'], "  base")
print("\nS1  cluster-robust SEs"); fit(base, ['vm', 'surge', 'lb'], "  clustered by hospital", cluster='ccn'); fit(base, ['vm', 'surge', 'lb'], "  clustered by storm", cluster='storm_id')
print("\nS2  leave-Katrina-out"); fit(base[base.storm != 'KATRINA'], ['vm', 'surge', 'lb'], "  no Katrina")
print("\nS3  exclude LOW-confidence labels"); fit(base[base.action_confidence != 'LOW'], ['vm', 'surge', 'lb'], "  HIGH+MEDIUM only")
print("\nS3b ownership added"); fit(base, ['vm', 'surge', 'lb', 'fp'], "  for-profit ownership")
print("\nS4  leveed as indicator (all 2004-2025 sheltering pairs)"); fit(t2, ['vm', 'surge', 'lev', 'lb'], "  with leveed dummy"); fit(t2[t2.storm != 'KATRINA'], ['vm', 'surge', 'lev', 'lb'], "  with leveed dummy, no Katrina")
print("\nS5  all years 1990-2025"); fit(sh[sh.lev == 0], ['vm', 'surge', 'lb'], "  all years, non-leveed")
print("\nS6  Firth penalized likelihood"); fit(base, ['vm', 'surge', 'lb'], "  Firth", firth=True)
# S8  campus-uncertain pairs: the certification number carried more than one registry facility
#     in that storm (multi-campus systems), so the modeled site may not be the campus that failed
MULTI = base.groupby(['storm_id', 'ccn']).size()
reg = pd.read_csv(REPO / 'data/registry/registry_linked.csv', dtype=str, keep_default_na=False)
reg['year'] = reg.year.astype(int)
def n_rows(r): return int(((reg.ccn == r.ccn) & (reg.year == r.year) & (reg.storm.str.upper() == str(r.storm).upper())).sum())
base = base.copy(); base['reg_rows'] = [n_rows(r) for _, r in base.iterrows()]
multi = base[base.reg_rows > 1]
print(f"\nS8  excluding campus-uncertain pairs (CCN carried >1 registry facility in the storm): {len(multi)} pairs excluded, {int(multi.fsip.sum())} FSIP: " + "; ".join(sorted(set(multi.storm.str.title() + ' ' + multi.name.str.title()))))
fit(base[base.reg_rows <= 1], ['vm', 'surge', 'lb'], "  without multi-campus certifications")
print("\nS9  2004-2018 only (period covered by the Provider of Services roster)"); fit(base[base.year <= 2018], ['vm', 'surge', 'lb'], "  2004-2018")
FLAG = [('KATRINA', '250045'), ('HARVEY', '450289'), ('HARVEY', '450147')]   # Hancock, Harris Health/Ben Taub, DeTar: second-reader flags still in the sheltering set
mask = pd.Series([(str(r.storm).upper(), str(r.ccn)) in FLAG for _, r in base.iterrows()], index=base.index)
print(f"\nS10 excluding the {int(mask.sum())} pairs an independent second reader flagged as ambiguous on mechanism, movement, or timing"); fit(base[~mask], ['vm', 'surge', 'lb'], "  without second-reader flags")
print("\nRainfall + plant age (2004-2025)"); m2 = base.copy(); m2['lr'] = np.log1p(pd.to_numeric(m2.rain_total_mm, errors='coerce')); m2['age'] = pd.to_numeric(m2.plant_age_years, errors='coerce'); fit(m2, ['vm', 'surge', 'lr', 'age', 'lb'], "  rain + age"); fit(m2[m2.age >= 3], ['vm', 'surge', 'lr', 'age', 'lb'], "  rain + age, plant age >= 3 y")
m3 = base.copy(); m3['el'] = pd.to_numeric(m3.elev_ft_usgs, errors='coerce'); fit(m3, ['vm', 'surge', 'el', 'lb'], "  surge + elevation jointly")
lv = t2[t2.lev == 1]; print(f"\nLeveed (2004-2025): FSIP {lv.fsip.mean():.0%} ({int(lv.fsip.sum())}/{len(lv)}); Katrina {int((lv.storm=='KATRINA').sum())}/{len(lv)}; excl Katrina {int(lv[lv.storm!='KATRINA'].fsip.sum())}/{len(lv[lv.storm!='KATRINA'])}")
print(f"Sheltering 2004-2025: {len(t2)} pairs, {t2.ccn.nunique()} hospitals, FSIP {int(t2.fsip.sum())} ({t2.fsip.mean():.0%}), FSIP hospitals {t2[t2.fsip==1].ccn.nunique()}; 1990-2003 sheltering pairs {len(sh)-len(t2)} (FSIP {int(sh.fsip.sum()-t2.fsip.sum())})")
print(f"SD log beds (base): {design(base,['vm','surge','lb'])[0].lb.std():.2f}")
