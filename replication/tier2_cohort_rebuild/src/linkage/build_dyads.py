#!/usr/bin/env python3
"""
Build the hospital-storm dyad frame: the study's analysis denominator.

One row per (hospital, storm) pair where the hospital was plausibly threatened,
carrying:

  REALIZED hazard (hindsight; the outcome side)
    in34/in50/in64   inside the storm's 34/50/64-kt wind field at any point
                     (quadrant radii vs bearing, evaluated on the hourly-
                     densified track with radii interpolated in time; the
                     6-hourly-only test missed small fast storms, e.g. Charley
                     over Punta Gorda)
    min_track_nm     closest approach of the (hourly-densified) track
    vmax_close_kt    storm intensity at closest approach
    fwd_speed_kt     storm forward speed at closest approach

  DECISION-TIME information (T-48h before that hospital's closest approach;
  the exposure side — what an administrator could actually know)
    fcst_cycle       advisory cycle used (latest cycle <= t_close - 48h)
    fcst_min_nm      min distance, hospital to that cycle's forecast track
    fcst_vmax_kt     max forecast intensity over the cycle's 0-72h taus
    cone_p67_nm      era-specific 67th-pct 48-h track error (empirical cone)
    in_cone          fcst_min_nm <= cone_p67_nm + storm r34 proxy

  FACILITY covariates (vintage nearest the storm year)
    beds, ownership, pa_eligible, is_cah, part_year (facility-age proxy),
    elev_ft (street-geocoded only), coord_method

  LABELS (from the linked registry, AUTO + ADJUDICATED tiers; several
  campuses can share one CCN, so labels are resolved per CCN-storm:
  POST_FSIP > mixed PRE/SIP -> PRE_PARTIAL > PRE_FULL > PRE_PARTIAL > SIP_OK
  > UNCLEAR; POST_REEVAC (re-evacuation after a pre-landfall evacuation) casts
  no vote)
    action, action_confidence

Cohort rule (per protocol): a dyad enters if in34 OR in_cone. Hospitals never
threatened by a storm generate no row for it.

Tier note: pre-2004 storms lack best-track wind radii, so in34/in50/in64 are
empty there (Tier 1); realized exposure for those storms is min_track_nm +
vmax only until the calibrated swath proxy (Task #8) lands.

Usage:
    python3 src/linkage/build_dyads.py
"""

import csv
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hazard"))
from geometry import bearing_deg, haversine_nm, interpolate_track, quadrant_index  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
TRACKS = REPO / "data" / "interim" / "hurdat2_tracks.csv"
OFCL = REPO / "data" / "interim" / "ofcl_forecasts.csv"
UNIVERSE = REPO / "data" / "interim" / "storm_universe.csv"
ROSTER = REPO / "data" / "interim" / "hospital_roster.csv"
COORDS = REPO / "data" / "interim" / "hospital_coords.csv"
ELEV = REPO / "data" / "interim" / "hospital_elevation.csv"
LINKED = REPO / "data" / "registry" / "registry_linked.csv"
OUT = REPO / "data" / "interim" / "dyad_frame.csv"

EPOCH = datetime(1970, 1, 1)
SCREEN_NM = 400.0          # hospitals farther than this at closest approach are skipped
R34_PROXY_NM = 100.0       # typical 34-kt radius, used only in the cone-inclusion rule
GENESIS = {"TD", "TS", "HU", "SS", "SD"}   # first such fix = cyclone genesis
PRECISE = {"census_street", "osm_name"}
CONF_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "": 0}

# Empirical p67 48-h track error by era (nm), from forecast_error.py output.
CONE_P67_48H = [(1990, 1999, 196.0), (2000, 2009, 131.0),
                (2010, 2017, 87.0), (2018, 2030, 72.0)]


def hours(dt):
    return (dt - EPOCH).total_seconds() / 3600.0


def p67(year):
    for lo, hi, v in CONE_P67_48H:
        if lo <= year <= hi:
            return v
    return 100.0


def load_storms():
    """storm_id -> dict of track arrays."""
    raw = defaultdict(list)
    with TRACKS.open() as fh:
        for r in csv.DictReader(fh):
            raw[r["storm_id"]].append(r)
    out = {}
    for sid, obs in raw.items():
        obs.sort(key=lambda o: (o["date"], o["time"]))
        # Drop fixes before the system was first designated a (sub)tropical
        # cyclone: a pre-genesis nor'easter (e.g. Wanda 2021) is not a
        # hurricane hazard, whereas post-tropical fixes (Sandy at landfall)
        # are retained.
        first = next((k for k, o in enumerate(obs) if o.get("status", "").strip() in GENESIS), None)
        if first is None:
            continue
        obs = obs[first:]
        t, la, lo, vm, radii = [], [], [], [], []
        for o in obs:
            dt = datetime.strptime(o["date"] + o["time"], "%Y%m%d%H%M")
            h = hours(dt)
            if t and h <= t[-1]:
                continue
            t.append(h); la.append(float(o["lat"])); lo.append(float(o["lon"]))
            vm.append(int(o["vmax_kt"]) if o["vmax_kt"] else 0)
            radii.append([float(o[q]) if o[q] else np.nan
                          for q in ("r34_ne", "r34_se", "r34_sw", "r34_nw")])
            radii[-1] += [float(o[q]) if o[q] else np.nan
                          for q in ("r50_ne", "r50_se", "r50_sw", "r50_nw")]
            radii[-1] += [float(o[q]) if o[q] else np.nan
                          for q in ("r64_ne", "r64_se", "r64_sw", "r64_nw")]
        out[sid] = {
            "t": np.array(t), "lat": np.array(la), "lon": np.array(lo),
            "vmax": np.array(vm, dtype=float), "radii": np.array(radii),
        }
    return out


def load_forecasts():
    """storm_id -> {cycle_hours: [(tau, lat, lon, vmax)]}"""
    out = defaultdict(lambda: defaultdict(list))
    with OFCL.open() as fh:
        for r in csv.DictReader(fh):
            ch = hours(datetime.strptime(r["cycle"], "%Y%m%d%H"))
            tau = int(r["tau"])
            if tau > 72:
                continue
            out[r["storm_id"]][ch].append(
                (tau, float(r["lat"]), float(r["lon"]),
                 int(r["vmax_kt"]) if r["vmax_kt"] else 0))
    return out


def load_hospitals():
    """One record per CCN: coords, interval, nearest-vintage covariates."""
    coords, elev = {}, {}
    with COORDS.open() as fh:
        for r in csv.DictReader(fh):
            coords[r["ccn"]] = (float(r["lat"]), float(r["lon"]), r["method"])
    if ELEV.exists():
        with ELEV.open() as fh:
            for r in csv.DictReader(fh):
                if r["elev_ft"]:
                    elev[r["ccn"]] = float(r["elev_ft"])

    by_ccn = defaultdict(list)
    with ROSTER.open() as fh:
        for r in csv.DictReader(fh):
            if r["ccn"] in coords and in_population(r["ccn"]):
                by_ccn[r["ccn"]].append(r)

    hosp = []
    for ccn, rows in by_ccn.items():
        # Interval and status come from ALL vintages of the CCN (not just the
        # acute-flagged ones): a legacy record flagged non-acute only in later
        # files must still carry its later termination date.
        if not any(r["is_acute"] == "True" for r in rows) and not ccn.endswith("F"):
            continue
        newest = max(rows, key=lambda r: int(r["year"]))
        part = min((r["participation_date"] for r in rows
                    if re.fullmatch(r"\d{8}", r["participation_date"] or "")), default="")
        # Active interval: participation .. termination, judged by the LATEST
        # vintage only. Judging by any() was a bug: a hospital active in the
        # 1995 file and closed by 2005 was treated as never terminated, which
        # let ~25% of dyads through for hospitals already closed at storm time.
        # POS is cumulative, so the newest vintage carries the authoritative
        # status; a reopened CCN shows code 00 there and stays open-ended.
        if (newest["termination_code"] or "").strip().lstrip("0") == "":
            term = ""
        else:
            term = newest["termination_date"] if re.fullmatch(r"\d{8}", newest["termination_date"] or "") else ""
        lat, lon, method = coords[ccn]
        hosp.append({
            "ccn": ccn, "name": newest["name"], "city": newest["city"],
            "state": newest["state"], "lat": lat, "lon": lon,
            "coord_method": method, "elev_ft": elev.get(ccn, ""),
            "beds": newest["beds"], "ownership": newest["ownership"],
            "pa_eligible": newest["pa_eligible"],
            "is_cah": newest["is_cah"], "is_federal": newest["is_federal"],
            "part_date": part, "term_date": term,
            "vintages": {int(r["year"]): r for r in rows},
        })
    return hosp


def in_population(ccn):
    """Acute-care population by CCN structure.

    Kept: SSNNNN with NNNN in 0001-0879 (short-term hospitals) or 1300-1399
    (critical access), and federal SSNNNF (VA/DoD, flagged is_federal).
    Dropped: E-suffix (non-participating non-federal emergency hospitals, mostly
    long defunct), other alpha suffixes/positions (subunits, special numbers),
    and LTACH 2000-2299, rehabilitation 3025-3099, children's 3300-3399,
    psychiatric 4000-4499 ranges even where a vintage flags them subtype 01."""
    if len(ccn) != 6:
        return False
    tail = ccn[2:]
    if tail.isdigit():
        n = int(tail)
        return 1 <= n <= 879 or 1300 <= n <= 1399
    return tail[:3].isdigit() and tail[3] == "F"


def resolve_label(votes):
    """votes: [(action, confidence)] for one CCN-storm (several campuses may
    share a certification). Returns (action, confidence)."""
    acts = [a for a, _ in votes if a != "POST_REEVAC"]
    if not acts:
        return "", ""
    if "POST_FSIP" in acts:
        act = "POST_FSIP"
    elif any(a.startswith("PRE") for a in acts) and "SIP_OK" in acts:
        act = "PRE_PARTIAL"
    elif "PRE_FULL" in acts:
        act = "PRE_FULL"
    elif "PRE_PARTIAL" in acts:
        act = "PRE_PARTIAL"
    elif "SIP_OK" in acts:
        act = "SIP_OK"
    else:
        act = "UNCLEAR"
    pool = [c for a, c in votes if a == act] or [c for a, c in votes]
    conf = max(pool, key=lambda c: CONF_RANK.get(c, 0))
    return act, conf


def load_labels():
    """(storm_name_upper, year, ccn) -> (action, confidence)"""
    votes = defaultdict(list)
    if not LINKED.exists():
        return {}
    with LINKED.open() as fh:
        for r in csv.DictReader(fh):
            # AUTO = above the fuzzy-match threshold; ADJUDICATED = confirmed or
            # corrected by human-in-the-loop review (several AUTO-scoring matches
            # were wrong, e.g. Naval Hospital Pensacola -> Baptist Pensacola).
            if r["match_tier"] in ("AUTO", "ADJUDICATED") and r["ccn"]:
                votes[(r["storm"].upper(), int(r["year"]), r["ccn"])].append(
                    (r["action"], r["confidence"]))
    return {k: resolve_label(v) for k, v in votes.items()}


def active_on(h, storm_start):
    """Was the hospital participating on the storm date?"""
    d = storm_start  # YYYYMMDD string
    if h["part_date"] and len(h["part_date"]) == 8 and h["part_date"] > d:
        return False
    if h["term_date"] and len(h["term_date"]) == 8 and h["term_date"] < d:
        return False
    return True


def nearest_vintage(h, year):
    ys = sorted(h["vintages"])
    best = min(ys, key=lambda y: abs(y - year))
    return h["vintages"][best]


def main():
    storms = load_storms()
    forecasts = load_forecasts()
    hospitals = load_hospitals()
    labels = load_labels()

    uni = {r["storm_id"]: r for r in csv.DictReader(UNIVERSE.open())
           if r["passes_screen"] == "True"}
    print(f"storms passing screen: {len(uni)}; hospitals with coords: {len(hospitals)}")

    hlat = np.array([h["lat"] for h in hospitals])
    hlon = np.array([h["lon"] for h in hospitals])

    rows = []
    for sid, meta in sorted(uni.items()):
        trk = storms.get(sid)
        if trk is None or len(trk["t"]) < 2:
            continue
        year = int(meta["year"])
        sname = meta["name"].strip().upper()

        # hourly-densified closest approach. Closest approach is taken over
        # hours when the system was at least tropical-storm strength (vmax >=
        # 34 kt) whenever such an hour lies within the screen; otherwise over
        # the whole track. HURDAT2 keeps a regenerated remnant under the same
        # storm id (Ivan 2004 re-entered the Gulf as a depression a week after
        # its hurricane passage), and the remnant's pass is not the threat the
        # decision was made against.
        fl, fo, ft = interpolate_track(trk["lat"], trk["lon"], trk["t"])
        dmat = haversine_nm(fl[:, None], fo[:, None], hlat[None, :], hlon[None, :])
        vm_h = np.interp(ft, trk["t"], trk["vmax"])
        d_ts = np.where((vm_h >= 34.0)[:, None], dmat, np.inf)
        min_ts = d_ts.min(axis=0)
        use_ts = min_ts <= SCREEN_NM
        min_d = np.where(use_ts, min_ts, dmat.min(axis=0))
        argmin = np.where(use_ts, d_ts.argmin(axis=0), dmat.argmin(axis=0))

        near = np.where(min_d <= SCREEN_NM)[0]
        if near.size == 0:
            continue

        # wind-field membership per 6-hourly obs, vectorized over hospitals.
        # onset34 records when the facility FIRST entered the 34-kt field:
        # the operational deadline. Hospital plans key movement to the onset
        # of tropical-storm-force winds, not to landfall or closest approach,
        # because patient transport must be complete before gusts reach
        # ~40 mph (EMS vehicles cannot operate above that).
        in34 = np.zeros(len(hospitals), dtype=bool)
        in50 = np.zeros(len(hospitals), dtype=bool)
        in64 = np.zeros(len(hospitals), dtype=bool)
        onset34 = np.full(len(hospitals), np.nan)
        has_radii = not np.all(np.isnan(trk["radii"][:, :4]))
        if has_radii:
            # Radii are reported at synoptic fixes only (landfall 'L' records
            # carry none); interpolate each quadrant radius in time onto the
            # hourly track, leaving NaN outside the span of reported values.
            rad_h = np.full((len(ft), 12), np.nan)
            for col in range(12):
                v = trk["radii"][:, col]
                ok = ~np.isnan(v)
                if ok.sum() >= 1:
                    tv = trk["t"][ok]
                    rad_h[:, col] = np.interp(ft, tv, v[ok])
                    rad_h[(ft < tv[0]) | (ft > tv[-1]), col] = np.nan
            for i in range(len(ft)):
                d = dmat[i]
                q = quadrant_index(bearing_deg(fl[i], fo[i], hlat, hlon))
                for jbase, arr in ((0, in34), (4, in50), (8, in64)):
                    rad = rad_h[i, jbase:jbase + 4][q]
                    with np.errstate(invalid="ignore"):
                        mask = np.where(np.isnan(rad), False, d <= rad)
                    if jbase == 0:
                        newly = mask & np.isnan(onset34)
                        onset34[newly] = ft[i]
                    arr |= mask

        fcst = forecasts.get(sid, {})
        cycles = sorted(fcst)

        for j in near:
            h = hospitals[j]
            if not active_on(h, meta["start_date"]):
                continue
            t_close = ft[argmin[j]]
            vmax_close = float(np.interp(t_close, trk["t"], trk["vmax"]))
            # forward speed via central difference around closest approach
            k = argmin[j]
            k0, k1 = max(0, k - 3), min(len(ft) - 1, k + 3)
            fwd = (haversine_nm(fl[k0], fo[k0], fl[k1], fo[k1])
                   / max(ft[k1] - ft[k0], 1e-6))

            # Decision clock: anchored to the onset of tropical-storm-force
            # (34-kt) winds at the facility where observed, since that is the
            # deadline hospital plans actually work against; closest approach
            # is the fallback for facilities the 34-kt field never reached
            # (and for pre-2004 storms without wind radii).
            if not np.isnan(onset34[j]):
                t_ref, anchor = onset34[j], "ts_wind_onset"
            else:
                t_ref, anchor = t_close, "closest_approach"
            target = t_ref - 48.0
            usable = [c for c in cycles if c <= target]
            fcst_min = fcst_vmax = cone = in_cone = cyc_str = ""
            if usable:
                c = usable[-1]
                pts = fcst[c]
                fla = np.array([p[1] for p in pts])
                flo = np.array([p[2] for p in pts])
                fcst_min = float(haversine_nm(fla, flo, h["lat"], h["lon"]).min())
                fcst_vmax = max(p[3] for p in pts)
                cone = p67(year)
                in_cone = fcst_min <= cone + R34_PROXY_NM
                cyc_str = datetime.utcfromtimestamp(c * 3600).strftime("%Y%m%d%H")

            include = bool(in34[j]) or (in_cone is True)
            if not include:
                continue

            vint = nearest_vintage(h, year)
            if vint["is_acute"] != "True" and not h["ccn"].endswith("F"):
                continue   # converted to LTACH/psych by this storm year; federal
                           # (F-suffix) hospitals lack the subtype flag after 2000
            action, conf = labels.get((sname, year, h["ccn"]), ("", ""))

            rows.append({
                "storm_id": sid, "storm": meta["name"].strip(), "year": year,
                "ccn": h["ccn"], "name": h["name"], "state": h["state"],
                "tier": 2 if year >= 2004 else 1,
                "in34": bool(in34[j]) if has_radii else "",
                "in50": bool(in50[j]) if has_radii else "",
                "in64": bool(in64[j]) if has_radii else "",
                "min_track_nm": round(float(min_d[j]), 1),
                "vmax_close_kt": round(vmax_close),
                "fwd_speed_kt": round(float(fwd), 1),
                "anchor": anchor,
                "fcst_cycle": cyc_str,
                "fcst_min_nm": round(fcst_min, 1) if fcst_min != "" else "",
                "fcst_vmax_kt": fcst_vmax,
                "cone_p67_nm": cone,
                "in_cone": in_cone,
                "beds": vint["beds"], "ownership": vint["ownership"],
                "pa_eligible": vint["pa_eligible"], "is_cah": vint["is_cah"],
                "is_federal": h["is_federal"],
                "part_year": h["part_date"][:4] if h["part_date"] else "",
                "elev_ft": h["elev_ft"] if h["coord_method"] in PRECISE else "",
                "coord_method": h["coord_method"],
                "action": action, "action_confidence": conf,
            })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    t2 = [r for r in rows if r["tier"] == 2]
    lab = [r for r in rows if r["action"]]
    print(f"\ndyads written:       {len(rows):,}")
    print(f"  Tier 2 (2004+):    {len(t2):,}")
    print(f"  in 34-kt swath:    {sum(1 for r in t2 if r['in34'] is True or r['in34']=='True'):,}")
    print(f"  registry-labeled:  {len(lab)}")
    print(f"Wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
