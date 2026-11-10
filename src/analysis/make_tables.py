import sys, pandas as pd, numpy as np, warnings, statsmodels.api as sm
warnings.filterwarnings('ignore')
sys.path.insert(0, 'src/analysis'); from scaling import primary_scales, standardize
SCALES = {}
df=pd.read_csv('data/interim/dyad_frame_full.csv',low_memory=False)
out=[]
W=out.append

def num(d,c): return pd.to_numeric(d[c],errors='coerce')
def med_iqr(s,f='{:.0f}'):
    s=s.dropna()
    return f"{f.format(s.median())} ({f.format(s.quantile(.25))}–{f.format(s.quantile(.75))})"

lab=df[df.action.notna()&(df.action!='')].copy()
unl=df[~(df.action.notna()&(df.action!=''))]

W("**Table 1.** Characteristics of the hospital–storm dyad cohort\n")
W(f"| Characteristic | Full cohort (n={len(df):,}) | Labeled subset (n={len(lab):,}) |")
W("|---|---|---|")
def row(name,fn):
    W(f"| {name} | {fn(df)} | {fn(lab)} |")
row("Storms, n", lambda d: f"{d.storm_id.nunique()}")
row("Hospitals, n", lambda d: f"{d.ccn.nunique()}")
row("Certified beds, median (IQR)", lambda d: med_iqr(num(d,'beds')))
row("Ground elevation, ft, median (IQR)", lambda d: med_iqr(num(d,'elev_ft_usgs'),'{:.1f}'))
row("Storm intensity at closest approach, kt, median (IQR)", lambda d: med_iqr(num(d,'vmax_close_kt')))
row("Closest approach, nmi, median (IQR)", lambda d: med_iqr(num(d,'min_track_nm')))
row("Storm-total rainfall, mm, median (IQR)", lambda d: med_iqr(num(d,'rain_total_mm')))
row("Average age of plant, y, median (IQR)", lambda d: med_iqr(num(d,'plant_age_years'),'{:.1f}'))
def pct(d,mask): return f"{mask.sum():,} ({mask.mean()*100:.0f}%)"
def pct_t2(d):
    t=d[d.tier.astype(str)=='2']; m=t.in34.astype(str)=='True'
    return f"{m.sum():,} ({m.mean()*100:.0f}% of {len(t):,} pairs, 2004–2025)"
row("Inside realized 34-kt wind field (2004–2025 pairs)", pct_t2)
row("Inside Category-3 surge zone", lambda d: pct(d,pd.to_numeric(d.surge_cat3_ft.astype(str).where(d.surge_cat3_ft.astype(str)!='leveed'),errors='coerce')>0))
row("Levee-protected (SLOSH)", lambda d: pct(d,d.surge_cat3_ft.astype(str)=='leveed'))
row("FEMA special flood hazard area", lambda d: pct(d,d.fld_zone.astype(str).str.upper().str.startswith(('A','V'))))
row("Critical access hospital", lambda d: pct(d,d.is_cah.astype(str)=='True'))
row("For-profit ownership", lambda d: pct(d,d.ownership.isin(['for_profit','physician_owned_for_profit'])))

W("\n\n**Table 2.** Empirical NHC official track forecast error by era, nautical miles\n")
fe=pd.read_csv('data/interim/forecast_error.csv')
eras=[(1990,1999),(2000,2009),(2010,2017),(2018,2025)]
taus=[12,24,36,48,72,96,120]
W("| Era | n forecasts | "+" | ".join(f"{t} h" for t in taus)+" |")
W("|---|---|"+"---|"*len(taus))
for lo,hi in eras:
    s=fe[(fe.year>=lo)&(fe.year<=hi)]
    cells=[]
    for t in taus:
        e=s[s.tau==t].error_nm
        cells.append(f"{np.percentile(e,67):.0f}" if len(e)>30 else "—")
    W(f"| {lo}–{hi} | {len(s):,} | "+" | ".join(cells)+" |")
W("\n*67th-percentile error, directly comparable to the NHC forecast cone radius.*")

W("\n\n**Table 3.** Hospitals with documented decisions compared with the full cohort\n")
# Wind-field membership is defined only from 2004 (HURDAT2 radii); comparing
# on the full 1990-2025 frame silently codes every pre-2004 pair as "outside"
# and inflated the ratio (5.1x). Restrict that row to 2004-2025.
lab2=lab[lab.tier.astype(str)=='2']; unl2=unl[unl.tier.astype(str)=='2']
W(f"| Characteristic | Documented decisions (n={len(lab):,}) | Rest of cohort (n={len(unl):,}) | Ratio |")
W("|---|---|---|---|")
for nm,c in [("Inside 34-kt wind field, % (2004–2025 pairs)","in34"),("Median intensity at closest approach, kt","vmax_close_kt"),
             ("Median closest approach, nmi","min_track_nm"),("Median elevation, ft","elev_ft_usgs"),
             ("Median certified beds","beds"),("Median rainfall, mm","rain_total_mm")]:
    if c=="in34":
        a=(lab2.in34.astype(str)=='True').mean()*100; b=(unl2.in34.astype(str)=='True').mean()*100
        W(f"| {nm} | {a:.0f} (n={len(lab2):,}) | {b:.0f} (n={len(unl2):,}) | {a/b:.1f}× |")
    else:
        a=num(lab,c).median(); b=num(unl,c).median()
        W(f"| {nm} | {a:.1f} | {b:.1f} | {a/b:.1f}× |")
W("\n*Documented decisions come from the hardest-hit end of the cohort, not from a representative sample.*")

# Sensitivity of the wind-field ratio to the forecast-threat allowance (0/50/100 nmi),
# recomputed on 2004-2025 pairs with the cohort re-derived from stored columns.
fm=num(df,'fcst_min_nm'); cp=num(df,'cone_p67_nm'); t2=df.tier.astype(str)=='2'; i34=df.in34.astype(str)=='True'; islab=df.action.notna()&(df.action!='')
W("\n*Allowance sensitivity (2004–2025):* ")
for allow in (0,50,100):
    keep=t2&(i34|(fm<=cp+allow))
    a=(i34[keep&islab]).mean()*100; b=(i34[keep&~islab]).mean()*100
    W(f"  allowance {allow} nmi: cohort n={keep.sum():,}, documented n={(keep&islab).sum()}, inside 34-kt {a:.0f}% vs {b:.0f}% ({a/b:.1f}×)")

sh=lab[lab.action.isin(['SIP_OK','POST_FSIP'])&(lab.tier.astype(str)=='2')].copy()   # analytic period 2004-2025
sh['fsip']=(sh.action=='POST_FSIP').astype(int)
s3=sh.surge_cat3_ft.astype(str)
sh['lev']=(s3=='leveed')
sh['surge']=pd.to_numeric(s3.where(s3!='leveed'),errors='coerce')>0
sh.loc[sh.lev,'surge']=np.nan
sh['elev']=num(sh,'elev_ft_usgs')
sh['sfha']=sh.fld_zone.astype(str).str.upper().str.startswith(('A','V')).where(sh.fld_zone.notna())   # unknown zone stays unknown

W("\n\n**Table 4.** Unadjusted FSIP rates among sheltering hospitals by exposure stratum, 2004–2025\n")
W("| Stratum | Exposed | Not exposed |")
W("|---|---|---|")
def strat(nm,col,valid=None):
    d=sh if valid is None else sh[valid]
    d=d[d[col].notna()]
    y=d[d[col]==True]; n=d[d[col]==False]
    W(f"| {nm} | {y.fsip.mean()*100:.0f}% ({y.fsip.sum()}/{len(y)}) | {n.fsip.mean()*100:.0f}% ({n.fsip.sum()}/{len(n)}) |")
strat("Category-3 surge zone","surge")
sh['low']=sh.elev<=15
strat("Ground elevation ≤15 ft","low", sh.elev.notna())
strat("FEMA special flood hazard area","sfha", sh.fld_zone.notna())
lv=sh[sh.lev]
W(f"| Levee-protected (separate stratum) | {lv.fsip.mean()*100:.0f}% ({lv.fsip.sum()}/{len(lv)}) | — |")
W(f"\n*Overall FSIP rate among sheltering hospitals: {sh.fsip.mean()*100:.0f}% ({sh.fsip.sum()}/{len(sh)}).*")

def model(d,y,preds,title,note,scales=None):
    dd=d[[y]+preds].dropna()
    X=sm.add_constant(dd[preds].astype(float))
    sc = SCALES if scales is None else scales
    X=standardize(X,preds,sc)
    units = {c: (dd[c].std() if c not in sc else sc[c]) for c in preds if X[c].nunique()>2}
    r=sm.Logit(dd[y],X).fit(disp=0,maxiter=300); ci=r.conf_int()
    W(f"\n\n**{title}**\n")
    W(f"| Predictor | Adjusted OR | 95% CI | *P* |")
    W("|---|---|---|---|")
    for c in preds:
        W(f"| {note[c]} | {np.exp(r.params[c]):.2f} | {np.exp(ci.loc[c,0]):.2f}–{np.exp(ci.loc[c,1]):.2f} | {r.pvalues[c]:.3f} |")
    W(f"\n*n={len(dd)}, events={int(dd[y].sum())}, pseudo-R²={r.prsquared:.3f}. One unit of each continuous predictor: " + "; ".join(f"{note[c]} = {units[c]:.3g}" for c in units) + ".*")

sh['lb']=np.log1p(num(sh,'beds')); sh['vm']=num(sh,'vmax_close_kt')
sh['lr']=np.log1p(num(sh,'rain_total_mm')); sh['age']=num(sh,'plant_age_years')
sh['sg']=sh.surge.astype(float)
sh['el']=sh.elev
_b=sh[~sh.lev].dropna(subset=['vm','sg','lb']); SCALES.update(primary_scales(_b))
print("Fixed scales:", {k: round(v,3) for k,v in SCALES.items()})
model(sh,'fsip',['vm','sg','lb'],"Table 5. Multivariable model of failed shelter-in-place among sheltering hospitals",
      {'vm':'Storm intensity at closest approach (per SD)','sg':'Category-3 surge zone','lb':'Facility size (per SD of log beds)'})
model(sh,'fsip',['vm','sg','lr','age','lb'],"Table 5b. FSIP model with prespecified null covariates",
      {'vm':'Storm intensity (per SD)','sg':'Category-3 surge zone','lr':'Storm-total rainfall (log, per SD)',
       'age':'Average age of plant (per SD)','lb':'Facility size (per SD of log beds)'})

lab=lab[(lab.tier.astype(str)=='2')&(lab.action!='UNCLEAR')].copy()   # analytic period; unclear decisions excluded from the decision model
lab['evac']=lab.action.isin(['PRE_FULL','PRE_PARTIAL']).astype(int)
lab['cr']=num(lab,'fcst_min_nm')/num(lab,'cone_p67_nm')
lab['fv']=num(lab,'fcst_vmax_kt'); lab['lb']=np.log1p(num(lab,'beds'))
lab['lowe']=(num(lab,'elev_ft_usgs')<=15).astype(float).where(num(lab,'elev_ft_usgs').notna())
model(lab,'evac',['cr','fv','lb','lowe'],"Supplementary Table S1. Correlates of documented pre-landfall evacuation in the news-ascertained sample",
      {'cr':'Cone ratio (forecast distance / era cone width)','fv':'Forecast intensity (per SD)',
       'lb':'Facility size (per SD of log beds)','lowe':'Ground elevation ≤15 ft'})

open('manuscripts/dmphp_tables.md','w').write("\n".join(out))
print("\n".join(out))
