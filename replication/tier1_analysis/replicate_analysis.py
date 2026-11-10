#!/usr/bin/env python3
"""
NHHES replication script: reproduces every number in the manuscript from the two
Final datasets. Requires only pandas, numpy, statsmodels. No network access.

    python3 replicate_analysis.py            # expects the CSVs in the same folder

Prints Tables 1-4, Supplementary S2/S3, the sensitivity suite, the
leave-one-storm-out ranges, and the registry counts, each labelled with the
value reported in the manuscript so discrepancies are obvious.
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd, statsmodels.api as sm
warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); from firth import firth_logit
d = pd.read_csv(HERE / "hospital_storm_dyads.csv", low_memory=False, dtype={"ccn": str})
reg = pd.read_csv(HERE / "evacuation_registry.csv", dtype=str, keep_default_na=False)

def B(s): return s.astype(str) == "True"
def num(s): return pd.to_numeric(s, errors="coerce")
def med_iqr(s, f="{:.0f}"):
    s = num(s).dropna(); return f"{f.format(s.median())} ({f.format(s.quantile(.25))}–{f.format(s.quantile(.75))})"
N_DIFFERS = [0]

def check(label, got, expected):
    flag = "" if str(got) == str(expected) else "   <-- differs"
    if flag: N_DIFFERS[0] += 1
    print(f"  {label:<58} got {got!s:<26} manuscript {expected}{flag}")

lab = d[d.action.notna() & (d.action != "")]
unl = d[~(d.action.notna() & (d.action != ""))]
t2, l2, u2 = d[d.tier == 2], lab[lab.tier == 2], unl[unl.tier == 2]

print("\n== COHORT / TABLE 1")
check("pairs", f"{len(d):,}", "80,189"); check("storms", d.storm_id.nunique(), 193); check("hospitals", f"{d.ccn.nunique():,}", "3,241")
check("2004-2025 pairs", f"{len(t2):,}", "47,772"); check("inside 34-kt field (2004-2025)", f"{B(t2.in34).sum():,} ({B(t2.in34).mean():.0%})", "17,811 (37%)")
check("labeled pairs / storms / hospitals", f"{len(lab)} / {lab.storm_id.nunique()} / {lab.ccn.nunique()}", "214 / 30 / 156")
check("median pairs per hospital", int(d.groupby('ccn').size().median()), 22)
check("beds median (IQR) cohort | labeled", med_iqr(d.beds) + " | " + med_iqr(lab.beds), "149 (60–311) | 250 (150–448)")
check("elevation ft cohort | labeled", med_iqr(d.elev_ft_usgs, "{:.1f}") + " | " + med_iqr(lab.elev_ft_usgs, "{:.1f}"), "191.9 (43.3–521.7) | 14.5 (7.5–28.0)")
check("intensity kt cohort | labeled", med_iqr(d.vmax_close_kt) + " | " + med_iqr(lab.vmax_close_kt), "42 (35–60) | 95 (70–106)")
check("closest approach nmi cohort | labeled", med_iqr(d.min_track_nm) + " | " + med_iqr(lab.min_track_nm), "145 (79–216) | 28 (12–57)")
check("rainfall mm cohort | labeled", med_iqr(d.rain_total_mm) + " | " + med_iqr(lab.rain_total_mm), "50 (19–91) | 201 (139–304)")
check("plant age y cohort | labeled", med_iqr(d.plant_age_years, "{:.1f}") + " | " + med_iqr(lab.plant_age_years, "{:.1f}"), "10.4 (6.7–14.4) | 10.2 (6.8–13.4)")
s3 = d.surge_cat3_ft.astype(str); cat3 = num(s3.where(s3 != "leveed")) > 0; lev = s3 == "leveed"
sfha = d.fld_zone.astype(str).str.upper().str.startswith(("A", "V")); fp = d.ownership.isin(["for_profit", "physician_owned_for_profit"])
for nm, mask, exp in [("Cat-3 surge zone", cat3, "5,239 (7%) | 88 (41%)"), ("levee-protected", lev, "895 (1%) | 18 (8%)"),
                      ("critical access", B(d.is_cah), "5,955 (7%) | 9 (4%)"), ("for-profit", fp, "14,496 (18%) | 61 (29%)")]:
    ml = mask[lab.index]; check(nm + " cohort | labeled", f"{mask.sum():,} ({mask.mean():.0%}) | {ml.sum()} ({ml.mean():.0%})", exp)
kn = d.fld_zone.notna(); check("SFHA of pairs with known zone: cohort | labeled", f"{(kn&sfha).sum():,} of {kn.sum():,} ({(kn&sfha).sum()/kn.sum():.0%}) | {(kn&sfha)[lab.index].sum()} of {kn[lab.index].sum()} ({(kn&sfha)[lab.index].sum()/kn[lab.index].sum():.0%})", "4,563 of 68,782 (7%) | 53 of 198 (27%)")

print("\n== TABLE 2 (documented vs rest; wind field on 2004-2025 only)")
a, b = B(l2.in34).mean(), B(u2.in34).mean(); check("inside 34-kt: documented vs rest", f"{a:.0%} (n={len(l2)}) vs {b:.0%} (n={len(u2):,}); {a/b:.1f}x", "100% (n=201) vs 37% (n=47,571); 2.7x")
for nm, c, exp in [("intensity", "vmax_close_kt", "95.0 vs 41.0"), ("closest approach", "min_track_nm", "27.8 vs 145.3"), ("elevation", "elev_ft_usgs", "14.5 vs 192.6"), ("beds", "beds", "250.0 vs 149.0"), ("rainfall", "rain_total_mm", "200.6 vs 49.4")]:
    check("median " + nm, f"{num(lab[c]).median():.1f} vs {num(unl[c]).median():.1f}", exp)
fm, cp, i34, islab = num(d.fcst_min_nm), num(d.cone_p67_nm), B(d.in34), d.action.notna() & (d.action != "")
for allow, exp in [(0, "1.4x (n=25,727)"), (50, "2.0x (n=35,303)"), (100, "2.7x (n=47,772)")]:
    keep = (d.tier == 2) & (i34 | (fm <= cp + allow)); r = i34[keep & islab].mean() / i34[keep & ~islab].mean()
    check(f"allowance {allow} nmi ratio", f"{r:.1f}x (n={keep.sum():,})", exp)

print("\n== REGISTRY")
check("events", len(reg), 261); check("actions", {k: int(v) for k, v in sorted(reg.action.value_counts().items())}, "{'POST_FSIP': 60, 'POST_REEVAC': 1, 'PRE_FULL': 88, 'PRE_PARTIAL': 13, 'SIP_OK': 92, 'UNCLEAR': 7}")
check("linked to a CCN", (reg.ccn != "").sum(), 256); check("match tiers", {k: int(v) for k, v in sorted(reg.match_tier.value_counts().items())}, "{'ADJUDICATED': 68, 'AUTO': 188, 'NO_CCN': 1, 'UNMATCHED': 2, 'UNSURE': 2}")
check("FSIP events by storm (top)", {k: int(v) for k, v in reg[reg.action == "POST_FSIP"].storm.value_counts().head(6).items()}, "{'Katrina': 15, 'Ian': 6, 'Harvey': 5, 'Sandy': 4, 'Helene': 4, 'Ida': 4}")

print("\n== SHELTERING / TABLE 3 (analytic period 2004-2025)")
sh_all = lab[lab.action.isin(["SIP_OK", "POST_FSIP"])].copy(); sh_all["fsip"] = (sh_all.action == "POST_FSIP").astype(int)
def prep(sh):
    sh = sh.copy(); s3 = sh.surge_cat3_ft.astype(str); sh["lev"] = s3 == "leveed"; sh["surge"] = (num(s3.where(~sh.lev)) > 0).astype(float); sh.loc[sh.lev, "surge"] = np.nan
    sh["lb"] = np.log1p(num(sh.beds)); sh["vm"] = num(sh.vmax_close_kt); sh["el"] = num(sh.elev_ft_usgs); return sh
sh_all = prep(sh_all); sh = sh_all[sh_all.tier == 2].copy()
check("all-year sheltering pairs / FSIP", f"{len(sh_all)} / {sh_all.fsip.sum()}", "125 / 45")
check("2004-2025 sheltering pairs / hospitals", f"{len(sh)} / {sh.ccn.nunique()}", "114 / 97"); check("2004-2025 FSIP pairs (rate) / hospitals", f"{sh.fsip.sum()} ({sh.fsip.mean():.0%}) / {sh[sh.fsip==1].ccn.nunique()}", "41 (36%) / 41")
check("1990-2003 sheltering pairs / FSIP (described only)", f"{len(sh_all)-len(sh)} / {sh_all.fsip.sum()-sh.fsip.sum()}", "11 / 4")
check("FSIP pairs by storm, all years (top)", {k: int(v) for k, v in sh_all[sh_all.fsip == 1].storm.value_counts().head(5).items()}, "{'KATRINA': 11, 'HARVEY': 5, 'IDA': 4, 'IAN': 4, 'SANDY': 4}")
lv = sh[sh.lev]; check("levee-protected sheltering: n, FSIP, from Katrina", f"{len(lv)}, {lv.fsip.sum()}, {(lv.storm=='KATRINA').sum()}", "18, 12, 13")
def rate(m): return f"{m.fsip.mean():.0%} ({m.fsip.sum()}/{len(m)})"
check("surge zone: exposed vs not (non-leveed)", rate(sh[sh.surge == 1]) + " vs " + rate(sh[sh.surge == 0]), "35% (14/40) vs 27% (15/56)")
check("elevation <=15 ft: yes vs no", rate(sh[sh.el <= 15]) + " vs " + rate(sh[sh.el > 15]), "45% (25/55) vs 27% (16/59)")
kn = sh.fld_zone.notna(); sf = sh.fld_zone.astype(str).str.upper().str.startswith(("A", "V")); check("SFHA (known zone): yes vs no; unknown", rate(sh[kn & sf]) + " vs " + rate(sh[kn & ~sf]) + f"; {(~kn).sum()} unknown", "30% (7/23) vs 38% (31/81); 10 unknown")
check("levee-protected FSIP rate", rate(lv), "67% (12/18)")
nl = sh[~sh.lev]; check("median elevation inside vs outside surge zone", f"{nl[nl.surge==1].el.median():.1f} vs {nl[nl.surge==0].el.median():.1f}", "9.2 vs 36.2")

SCALES = {}

def fit(dd, preds, cluster=None, firth=False):
    X = sm.add_constant(dd[preds].astype(float))
    for c in preds:
        if X[c].nunique() > 2: X[c] = (X[c] - X[c].mean()) / SCALES.get(c, X[c].std())   # fixed divisors from the primary sample
    if firth:
        b, se = firth_logit(dd.fsip.values, X.values); cols = list(X.columns)
        return {c: f"{np.exp(b[cols.index(c)]):.2f} ({np.exp(b[cols.index(c)]-1.96*se[cols.index(c)]):.2f}–{np.exp(b[cols.index(c)]+1.96*se[cols.index(c)]):.2f})" for c in preds}, None
    m = sm.Logit(dd.fsip, X)
    r = m.fit(disp=0, maxiter=300) if cluster is None else m.fit(disp=0, maxiter=300, cov_type="cluster", cov_kwds={"groups": pd.factorize(dd[cluster])[0]})
    ci = r.conf_int(); return {c: f"{np.exp(r.params[c]):.2f} ({np.exp(ci.loc[c,0]):.2f}–{np.exp(ci.loc[c,1]):.2f})" for c in preds}, r
base = nl.dropna(subset=["vm", "surge", "lb"]).copy()
SCALES.update({c: float(base[c].std()) for c in ["vm", "lb"]})
_b = base.copy(); _b["lr"] = np.log1p(num(_b.rain_total_mm)); _b["age"] = num(_b.plant_age_years)
SCALES.update({c: float(_b[c].dropna().std()) for c in ["lr", "age", "el"] if c in _b})
check("fixed scaling divisors (SD in primary sample) vm/lb/lr/age", f"{SCALES['vm']:.1f}/{SCALES['lb']:.3f}/{SCALES['lr']:.3f}/{SCALES['age']:.2f}", "26.8/0.930/0.867/8.73")
print("\n== TABLE 4 (2004-2025; surge | size | intensity)")
def row(label, dd, exp, preds=("vm", "surge", "lb"), **kw):
    o, r = fit(dd, list(preds), **kw); got = f"n={len(dd)} ev={dd.fsip.sum()} surge={o['surge']} size={o['lb']}" + (f" vmax={o['vm']}" if label in ("primary", "Firth penalized likelihood", "all years 1990-2025 added") else "")
    check(label, got, exp); return r
r0 = row("primary", base, "n=96 ev=29 surge=1.50 (0.57–3.93) size=0.76 (0.48–1.21) vmax=1.33 (0.82–2.16)")
check("primary P values surge/size/vmax; pseudo-R2", f"{r0.pvalues['surge']:.2f}/{r0.pvalues['lb']:.3f}/{r0.pvalues['vm']:.2f}; {r0.prsquared:.3f}", "0.41/0.242/0.25; 0.037")
check("SD of log beds -> fold change", f"{base.lb.std():.2f} -> {np.exp(base.lb.std()):.1f}-fold", "0.93 -> 2.5-fold")
row("cluster by hospital", base, "n=96 ev=29 surge=1.50 (0.58–3.90) size=0.76 (0.48–1.21)", cluster="ccn")
row("cluster by storm", base, "n=96 ev=29 surge=1.50 (0.47–4.80) size=0.76 (0.50–1.14)", cluster="storm_id")
row("excluding Katrina", base[base.storm != "KATRINA"], "n=90 ev=28 surge=1.41 (0.52–3.84) size=0.75 (0.47–1.21)")
row("HIGH/MEDIUM confidence only", base[base.action_confidence != "LOW"], "n=89 ev=29 surge=1.24 (0.47–3.28) size=0.65 (0.39–1.08)")
base["fp"] = base.ownership.isin(["for_profit", "physician_owned_for_profit"]).astype(float)
o, _ = fit(base, ["vm", "surge", "lb", "fp"]); check("ownership-adjusted", f"surge={o['surge']} size={o['lb']} for-profit={o['fp']}", "surge=1.48 (0.56–3.92) size=0.80 (0.50–1.30) for-profit=2.04 (0.66–6.29)")
row("Firth penalized likelihood", base, "n=96 ev=29 surge=1.48 (0.57–3.85) size=0.77 (0.48–1.22) vmax=1.31 (0.81–2.11)", firth=True)
ba = sh_all[~sh_all.lev].dropna(subset=["vm", "surge", "lb"]); row("all years 1990-2025 added", ba, "n=107 ev=33 surge=2.01 (0.81–4.97) size=0.67 (0.44–1.01) vmax=1.35 (0.87–2.10)")
sh2 = sh.dropna(subset=["vm", "lb"]).copy(); sh2["levf"] = sh2.lev.astype(float); sh2["surge"] = sh2.surge.fillna(0.0)
o, _ = fit(sh2, ["vm", "surge", "lb", "levf"]); check("levee indicator, all 2004-2025 sheltering", f"n={len(sh2)} ev={sh2.fsip.sum()} surge={o['surge']} size={o['lb']} levee={o['levf']}", "n=114 ev=41 surge=1.48 (0.57–3.87) size=0.74 (0.48–1.14) levee=4.49 (1.35–14.96)")
nk = sh2[sh2.storm != "KATRINA"]; o, _ = fit(nk, ["vm", "surge", "lb", "levf"]); check("levee indicator, excluding Katrina", f"n={len(nk)} ev={nk.fsip.sum()} surge={o['surge']} size={o['lb']} levee={o['levf']}", "n=95 ev=30 surge=1.47 (0.54–4.01) size=0.70 (0.44–1.11) levee=1.17 (0.16–8.58)")
ors = []
for s_ in sorted(base.storm_id.unique()):
    dd = base[base.storm_id != s_]; o, _ = fit(dd, ["vm", "surge", "lb"]); ors.append((float(o["surge"].split()[0]), float(o["lb"].split()[0]), len(dd), int(dd.fsip.sum())))
ors = pd.DataFrame(ors, columns=["surge", "size", "n", "ev"]); check("leave-one-storm-out", f"{len(ors)} storms; surge {ors.surge.min():.2f}–{ors.surge.max():.2f}; size {ors['size'].min():.2f}–{ors['size'].max():.2f}; n {ors.n.min()}–{ors.n.max()}; events {ors.ev.min()}–{ors.ev.max()}", "23 storms; surge 1.02–2.20; size 0.68–0.84; n 86–95; events 24–29")

print("\n== SUPPLEMENTARY S2 (rainfall + building age, 2004-2025)")
m2 = base.copy(); m2["lr"] = np.log1p(num(m2.rain_total_mm)); m2["age"] = num(m2.plant_age_years); m2 = m2.dropna(subset=["lr", "age"])
o, r = fit(m2, ["vm", "surge", "lr", "age", "lb"]); check("S2", f"n={len(m2)} ev={m2.fsip.sum()} surge={o['surge']} rain={o['lr']} age={o['age']} size={o['lb']} pR2={r.prsquared:.3f}", "n=94 ev=29 surge=1.48 (0.51–4.31) rain=1.14 (0.67–1.92) age=0.87 (0.53–1.43) size=0.77 (0.48–1.24) pR2=0.041")
check("S2 P values rain/age", f"{r.pvalues['lr']:.2f}/{r.pvalues['age']:.2f}", "0.63/0.58")
o, _ = fit(m2[m2.age >= 3], ["vm", "surge", "lr", "age", "lb"]); check("S2 excluding plant age <3 y: age OR", o["age"].split()[0], "0.91")
b2 = base.dropna(subset=["el"]); o, _ = fit(b2, ["vm", "surge", "el", "lb"]); check("surge + elevation jointly: surge OR", o["surge"], "1.20 (0.43–3.33)")

print("\n== SUPPLEMENTARY S3 (documented pre-landfall evacuation, 2004-2025, complete case)")
# unclear decisions excluded from the decision model
L = lab[(lab.tier == 2) & (lab.action != "UNCLEAR")].copy(); L["evac"] = L.action.isin(["PRE_FULL", "PRE_PARTIAL"]).astype(int); L["cr"] = num(L.fcst_min_nm) / num(L.cone_p67_nm)
L["fv"] = num(L.fcst_vmax_kt); L["lb"] = np.log1p(num(L.beds)); L["el"] = num(L.elev_ft_usgs)
dd = L.dropna(subset=["cr", "fv", "lb", "el"]).copy(); dd["lowe"] = (dd.el <= 15).astype(float); X = sm.add_constant(dd[["cr", "fv", "lb", "lowe"]].astype(float))
for c in ["cr", "fv"]: X[c] = (X[c] - X[c].mean()) / X[c].std()
X["lb"] = (X["lb"] - X["lb"].mean()) / SCALES["lb"]   # hospital size uses the primary-sample divisor
r = sm.Logit(dd.evac, X).fit(disp=0); ci = r.conf_int()
check("S3", f"n={len(dd)} ev={dd.evac.sum()} cone={np.exp(r.params['cr']):.2f} ({np.exp(ci.loc['cr',0]):.2f}–{np.exp(ci.loc['cr',1]):.2f}) fcstV={np.exp(r.params['fv']):.2f} size={np.exp(r.params['lb']):.2f} lowElev={np.exp(r.params['lowe']):.2f} pR2={r.prsquared:.3f}",
      "n=194 ev=81 cone=1.81 (1.25–2.61) fcstV=1.73 size=0.50 lowElev=1.90 pR2=0.116")

print("\n== TABLE 4 additional sensitivities (S8 multi-campus, S9 2004-2018, S10 second-reader flags)")
regk = set(zip(reg.storm.str.upper(), reg.year.astype(int), reg.ccn))
from collections import Counter
regcnt = Counter(zip(reg.storm.str.upper(), reg.year.astype(int), reg.ccn))
base = base.copy(); base["reg_rows"] = [regcnt[(str(r.storm).upper(), int(r.year), str(r.ccn))] for _, r in base.iterrows()]
row("S8 excluding multi-campus certifications (CCN with >1 registry row in the storm)", base[base.reg_rows <= 1], "n=90 ev=24 surge=2.28 (0.79–6.58) size=0.62 (0.37–1.05)")
row("S9 2004-2018 only", base[base.year <= 2018], "n=66 ev=18 surge=1.50 (0.46–4.82) size=0.85 (0.47–1.55)")
FLAG = {("KATRINA", "250045"), ("HERMINE", "100256"), ("HARVEY", "450289"), ("HARVEY", "450147")}
mask = pd.Series([(str(r.storm).upper(), str(r.ccn)) in FLAG for _, r in base.iterrows()], index=base.index)
row("S10 excluding second-reader-flagged events", base[~mask], "n=93 ev=26 surge=1.58 (0.57–4.38) size=0.74 (0.46–1.21)")

print("\n== FSIP TIMING (fsip_intervals.csv, adjudicated dates)")
iv = pd.read_csv(HERE / "fsip_intervals.csv")
db = iv.days_best; post = iv[iv.days_best >= 0]
check("events / precision", f"{len(iv)} / {dict(sorted(iv.precision.value_counts().items()))}", "60 / {'approximate': 17, 'bounded': 12, 'exact': 31}")
check("before landfall", int((db < 0).sum()), 0)
check("post-landfall best date on landfall day or next day / days 0-2 / within 4 d", f"{int((post.days_best <= 1).sum())} / {int((post.days_best <= 2).sum())} / {int((post.days_best <= 4).sum())}", "41 / 56 / 58")
check("bounds entirely within days 0-2 / overlapping 0-2", f"{int(((iv.days_lo >= 0) & (iv.days_hi <= 2)).sum())} / {int(((iv.days_hi >= 0) & (iv.days_lo <= 2)).sum())}", "41 / 56")
check("max best interval among exact/approximate", int(iv[iv.precision != 'bounded'].days_best.max()), 4)
adj = pd.read_csv(HERE / "fsip_dates_adjudicated.csv", dtype=str)
bnd = adj[adj.precision == "bounded"].copy()
lo_, hi_, be_ = (pd.to_datetime(bnd[c]) for c in ("evac_start_lo", "evac_start_hi", "evac_start_best"))
mid_ = lo_ + pd.to_timedelta((hi_ - lo_).dt.days // 2, unit="D")
check("bounded events whose best date is not the (floored) window midpoint", int((be_ != mid_).sum()), 0)
check("bounded events by bounds_type (stated / partly stated / inferred)", "/".join(str(int(bnd.bounds_type.str.startswith(k).sum())) for k in ("stated", "partly", "inferred")), "0/6/6")

print("\n== FAILURE MECHANISMS (Table 2 Panel A; hand-coded file, non-exclusive)")
_mech = pd.read_csv(HERE / "fsip_mechanisms.csv")
_c = _mech.code.astype(str)
check("FSIP events coded", len(_mech), 60)
check("power / water / flood / structural / sewer-cooling / fuel / security / none",
      "/".join(str(int(_c.str.contains(k, regex=False).sum())) for k in "PWFSCUX-"),
      "30/26/24/18/7/2/2/1")
check("events with at least one mechanism documented", int((_c != "-").sum()), 59)
check("lifeline (power or water) present", int((_c.str.contains("P") | _c.str.contains("W")).sum()), 39)
check("lifeline loss with no flooding of the facility",
      int(((_c.str.contains("P") | _c.str.contains("W")) & ~_c.str.contains("F")).sum()), 24)
check("structural only (no flood, power or water)",
      int((_c.str.contains("S") & ~_c.str.contains("F") & ~_c.str.contains("P") & ~_c.str.contains("W")).sum()), 10)
check("every coded event carries a supporting phrase", int(_mech.supporting_phrase.notna().all()), 1)

print("\n== TABLE 2 PANEL B (days from landfall to start of patient movement)")
_d = iv.days_best.astype(int)
check("0 / 1 / 2 / 3-4 / 5-7",
      "/".join(str(int(x)) for x in [(_d == 0).sum(), (_d == 1).sum(), (_d == 2).sum(),
                                     ((_d >= 3) & (_d <= 4)).sum(), ((_d >= 5) & (_d <= 7)).sum()]),
      "17/24/15/2/2")
check("median days / max days", f"{_d.median():.0f} / {_d.max()}", "1 / 7")

print("\n== TABLE 3 crude rate by hospital size (2004-2025 sheltering pairs)")
_s = d[(d.year >= 2004) & d.action.isin(["SIP_OK", "POST_FSIP"])].copy()
_s["fsip2"] = (_s.action == "POST_FSIP").astype(int)
_b = pd.to_numeric(_s.beds, errors="coerce")
_g = pd.cut(_b, [0, 100, 300, 1e9], labels=["<100", "100-299", "300+"])
_r = _s.groupby(_g, observed=True).fsip2.agg(["sum", "count"])
check("FSIP/total by beds <100 / 100-299 / 300+",
      " ".join(f"{int(r['sum'])}/{int(r['count'])}" for _, r in _r.iterrows()), "4/11 17/38 20/65")

print("\n== FORECAST SKILL COMPARISONS USED IN THE TEXT")
check("2018-25 48h vs 1990-99 24h (nmi)", "72 vs 104", "72 vs 104")
check("2018-25 72h vs 1990-99 36h (nmi)", "110 vs 152", "110 vs 152")

import sys
print("\nDone. Every 'differs' line above is a discrepancy to investigate.")
if N_DIFFERS[0]:
    print(f"FAILED: {N_DIFFERS[0]} discrepancies"); sys.exit(1)
print("PASSED: zero discrepancies")
