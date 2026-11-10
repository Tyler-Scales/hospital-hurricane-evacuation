#!/usr/bin/env python3
"""
Geocode every roster CCN: street-level via the Census Bureau batch geocoder,
ZIP-centroid fallback via the Census ZCTA gazetteer.

Why not HIFLD: it is a current-only snapshot, so hospitals that closed in 1998
are absent. POS files carry street addresses for every CCN ever certified
(cumulative), so geocoding POS addresses covers closed facilities too.

Precision tiers written to the output:
    census_street   rooftop/interpolated street match  (good for surge/flood zone)
    osm_name        OpenStreetMap (Nominatim) point for the named facility, used
                    when the POS address is a PO box or fails the Census
                    geocoder; accepted only if the result is a hospital-class
                    feature in the same state within 40 km of the ZIP centroid
                    (good for surge/flood zone)
    zip_centroid    ~1-3 km error                      (fine for wind exposure only;
                                                        NOT acceptable for surge zone)

Audit note (Sept 2026): the original ZIP fallback read the gazetteer's
ALAND_SQMI/AWATER_SQMI columns as lat/lon, so every ZIP-fallback hospital had
coordinates near (0,0) and silently fell out of the cohort (2,801 CCNs,
including Tampa General). The gazetteer is now parsed by column name.

Output: data/interim/hospital_coords.csv
    ccn, lat, lon, method, matched_address

Usage:
    python3 src/roster/geocode.py
"""

import csv
import io
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "raw" / "cms"
ROSTER = REPO / "data" / "interim" / "hospital_roster.csv"
OUT = REPO / "data" / "interim" / "hospital_coords.csv"
GAZ_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/Gaz_zcta_national.zip"
STREET_CACHE = REPO / "data" / "interim" / "census_street_hits.csv"
OSM_CACHE = REPO / "data" / "interim" / "osm_name_hits.csv"
LINKED = REPO / "data" / "registry" / "registry_linked.csv"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSM_UA = {"User-Agent": "NHHES-research/0.1 (academic use; tylerwallace@uga.edu)"}
PRECISE = {"census_street", "osm_name"}
GAZ_CACHE = REPO / "data" / "raw" / "gazetteer_zcta.zip"
BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
UA = {"User-Agent": "NHHES-research/0.1 (academic use)"}
BATCH_SIZE = 1000          # keep well under the 10k cap; big batches time out
TIMEOUT = 600


def load_roster_ccns():
    ccns = set()
    with ROSTER.open() as fh:
        for r in csv.DictReader(fh):
            if r["ccn"]:
                ccns.add(r["ccn"])
    return ccns


def collect_addresses(ccns):
    """CCN -> (street, city, state, zip), preferring the newest POS file.

    The 2018 cumulative file covers nearly every CCN ever certified; older
    files fill the few purged from later vintages. 1990's adapter-era file
    lacks a separate city column, so it contributes only street+zip."""
    addr = {}
    dta = ("dta", "prov2720", "prov3225", "prov3230", "prov2905", "prov1680")
    csvk = ("csv", "st_adr", "city_name", "state_cd", "zip_cd", "prvdr_num")
    sources = [("pos2018.csv.zip", *csvk), ("pos2015.csv.zip", *csvk),
               ("pos2010.dta.zip", *dta), ("pos2005.dta.zip", *dta),
               ("pos2000.dta.zip", *dta), ("pos1995.dta.zip", *dta)]
    for fname, kind, f_addr, f_city, f_state, f_zip, f_ccn in sources:
        path = CACHE / fname
        if not path.exists():
            continue
        missing = ccns - set(addr)
        if not missing:
            break
        for rec in _records(path, kind):
            ccn = _s(rec.get(f_ccn))
            if ccn not in missing or ccn in addr:
                continue
            street = _s(rec.get(f_addr))
            if not street:
                continue
            addr[ccn] = (street, _s(rec.get(f_city)), _s(rec.get(f_state)),
                         _s(rec.get(f_zip))[:5])
        print(f"  {fname}: cumulative address coverage {len(addr)}/{len(ccns)}")
    return addr


def _records(path, kind):
    if kind == "csv":
        with zipfile.ZipFile(path) as z:
            with z.open(z.namelist()[0]) as fh:
                for row in csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1")):
                    yield {(k or "").lower().strip(): v for k, v in row.items()}
    else:
        import pandas as pd
        with zipfile.ZipFile(path) as z:
            with z.open(z.namelist()[0]) as fh:
                df = pd.read_stata(io.BytesIO(fh.read()), convert_categoricals=False)
        df.columns = [c.lower().strip() for c in df.columns]
        for rec in df.to_dict("records"):
            yield rec


def _s(v):
    if v is None or v != v:
        return ""
    return str(v).strip()


def census_batch(items):
    """items: list of (ccn, street, city, state, zip). Returns ccn -> (lat, lon, matched)."""
    out = {}
    for i in range(0, len(items), BATCH_SIZE):
        chunk = items[i:i + BATCH_SIZE]
        body = io.StringIO()
        w = csv.writer(body)
        for ccn, street, city, state, zp in chunk:
            w.writerow([ccn, street, city, state, zp])

        boundary = uuid.uuid4().hex
        payload = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="benchmark"\r\n\r\n'
            f"Public_AR_Current\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="addressFile"; filename="addr.csv"\r\n'
            f"Content-Type: text/csv\r\n\r\n"
            f"{body.getvalue()}\r\n"
            f"--{boundary}--\r\n"
        ).encode()

        req = urllib.request.Request(
            BATCH_URL, data=payload,
            headers={**UA, "Content-Type": f"multipart/form-data; boundary={boundary}"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    text = r.read().decode("utf-8", "replace")
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  ! batch {i//BATCH_SIZE} failed: {e}", file=sys.stderr)
                    text = ""
                else:
                    time.sleep(10)

        matched = 0
        for row in csv.reader(io.StringIO(text)):
            # id, input_addr, match_flag, match_type, matched_addr, "lon,lat", tiger_id, side
            if len(row) >= 6 and row[2] == "Match":
                try:
                    lon, lat = (float(x) for x in row[5].split(","))
                except ValueError:
                    continue
                out[row[0]] = (lat, lon, row[4])
                matched += 1
        print(f"  batch {i//BATCH_SIZE + 1}: {matched}/{len(chunk)} street-matched")
    return out


def zip_centroids():
    if not GAZ_CACHE.exists():
        GAZ_CACHE.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(GAZ_URL, headers=UA)
        with urllib.request.urlopen(req, timeout=300) as r:
            GAZ_CACHE.write_bytes(r.read())
    cent = {}
    with zipfile.ZipFile(GAZ_CACHE) as z:
        with z.open(z.namelist()[0]) as fh:
            rdr = csv.reader(io.TextIOWrapper(fh, encoding="utf-8"), delimiter="\t")
            header = [h.strip().upper() for h in next(rdr)]
            ig, ila, ilo = (header.index("GEOID"), header.index("INTPTLAT"),
                            header.index("INTPTLONG"))
            for parts in rdr:
                try:
                    la, lo = float(parts[ila]), float(parts[ilo])
                except (ValueError, IndexError):
                    continue
                if 17.0 <= la <= 72.0 and -180.0 <= lo <= -64.0:
                    cent[parts[ig].strip()] = (la, lo)
    return cent


PO_BOX = re.compile(r"\b(P\.?\s*O\.?\s*(BOX|DRAWER)|POST\s+OFFICE\s+BOX|DRAWER|BOX)\s*[A-Z0-9-]*", re.I)


def clean_street(street):
    """Strip PO-box fragments and suite noise; return '' if nothing street-like remains."""
    s = PO_BOX.sub(" ", street.upper())
    s = re.sub(r"\b(SUITE|STE|UNIT|FLOOR|FL|BLDG|BUILDING)\b\.?\s*[A-Z0-9-]*", " ", s)
    s = re.sub(r"[#,]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if re.search(r"\d", s) and len(s) > 5 else ""


def plausible(lat, lon):
    return 17.0 <= lat <= 50.0 and -107.0 <= lon <= -64.0


def km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (0.5 - math.cos((lat2 - lat1) * p) / 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2)
    return 12742 * math.asin(math.sqrt(a))


GENERIC = {"HOSPITAL", "HOSP", "MEDICAL", "MED", "CENTER", "CTR", "CENTRE", "REGIONAL",
           "COMMUNITY", "COMM", "MEMORIAL", "MEM", "GENERAL", "GEN", "COUNTY", "CO",
           "HEALTH", "HEALTHCARE", "SYSTEM", "INC", "LLC", "THE", "OF", "AND", "AT",
           "SAINT", "ST", "CAMPUS", "PARISH", "CITY", "UNIVERSITY", "UNIV"}


def name_agrees(roster_name, city, display_name):
    """At least one identifying token of the roster name (not generic, not the
    city) must appear in the OSM display name; guards same-town wrong-facility
    hits such as a rehabilitation or behavioral facility."""
    toks = {re.sub(r"[^A-Z0-9]", "", t) for t in roster_name.upper().replace("-", " ").replace("'", "").split()}
    ctoks = {t for t in (city or "").upper().split()}
    toks = {t for t in toks if t and t not in GENERIC and t not in ctoks and len(t) > 2}
    if not toks:
        return True   # nothing identifying to test ("COMMUNITY HOSPITAL")
    dn = re.sub(r"[^A-Z0-9 ]", " ", display_name.upper().replace("'", "").replace("\u2019", ""))
    return any(t in dn.split() for t in toks)


def osm_lookup(name, city, state, anchor):
    """Nominatim point for a named hospital; None unless hospital-class, same
    state, within 40 km of the ZIP-centroid anchor (guards wrong-city hits), and
    sharing an identifying name token with the roster name."""
    q = urllib.parse.urlencode({"q": f"{name}, {city}, {state}", "format": "jsonv2",
                                "limit": 5, "countrycodes": "us", "addressdetails": 1})
    req = urllib.request.Request(f"{NOMINATIM}?{q}", headers=OSM_UA)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                res = json.load(r)
            break
        except Exception:
            if attempt == 2:
                return None
            time.sleep(5)
    for x in res:
        cat, typ = x.get("category", ""), x.get("type", "")
        ok = (cat == "amenity" and typ in ("hospital", "clinic", "doctors", "nursing_home")) \
            or (cat == "healthcare") or (cat == "building" and typ == "hospital")
        if not ok:
            continue
        try:
            la, lo = float(x["lat"]), float(x["lon"])
        except (KeyError, ValueError):
            continue
        st = (x.get("address") or {}).get("ISO3166-2-lvl4", "")
        if st and st.split("-")[-1] != state:
            continue
        if anchor and km(la, lo, *anchor) > 40.0:
            continue
        if not name_agrees(name, city, x.get("display_name", "")):
            continue
        return (la, lo, x.get("display_name", "")[:120])
    return None


def main():
    ccns = load_roster_ccns()
    print(f"roster CCNs to geocode: {len(ccns)}")
    addr = collect_addresses(ccns)

    roster = {}
    with ROSTER.open() as fh:
        for r in csv.DictReader(fh):
            if not r["ccn"]:
                continue
            h = roster.setdefault(r["ccn"], {"zip": "", "acute": False, "open": False,
                                             "name": "", "city": "", "state": r["state"],
                                             "year": -1})
            if r["zip"] and r["zip"][:5] not in h.setdefault("zips", []):
                h["zips"].append(r["zip"][:5])
            if r["zip"] and not h["zip"]:
                h["zip"] = r["zip"][:5]
            if r["is_acute"] == "True":
                h["acute"] = True
            if int(r["year"]) > h["year"]:
                h.update(year=int(r["year"]), name=r["name"], city=r["city"],
                         state=r["state"],
                         open=((r["termination_code"] or "").strip().lstrip("0") == ""))
    linked = set()
    if LINKED.exists():
        for r in csv.DictReader(LINKED.open()):
            if r["ccn"]:
                linked.add(r["ccn"])

    # Stage 1+2: Census street matches (cached), retrying every unmatched CCN
    # whose POS address still contains a street after PO-box cleaning.
    hits = {}
    if STREET_CACHE.exists():
        with STREET_CACHE.open() as fh:
            for r in csv.DictReader(fh):
                hits[r["ccn"]] = (float(r["lat"]), float(r["lon"]), r["matched"])
        print(f"loaded {len(hits)} cached street matches")
    items = []
    for c in sorted(addr):
        if c in hits:
            continue
        street, city, state, zp = addr[c]
        cs = clean_street(street)
        if cs:
            items.append((c, cs, city or roster.get(c, {}).get("city", ""), state, zp))
    if items:
        print(f"\nstreet geocoding {len(items)} cleaned addresses via Census batch API...")
        new = census_batch(items)
        new = {c: v for c, v in new.items() if plausible(v[0], v[1])}
        hits.update(new)
        with STREET_CACHE.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["ccn", "lat", "lon", "matched"])
            w.writeheader()
            for ccn, (lat, lon, matched) in sorted(hits.items()):
                w.writerow({"ccn": ccn, "lat": lat, "lon": lon, "matched": matched})

    print("\nloading ZIP centroids...")
    cents = zip_centroids()

    # Stage 3: OSM name lookup for acute-care CCNs still lacking a precise point.
    # Limited to certifications that matter for the study: open in the latest
    # vintage, or carrying a registry event, or with a street-type address that
    # the Census geocoder could not place (older closed hospitals are left at
    # the ZIP centroid, which is adequate for wind exposure).
    osm = {}
    if OSM_CACHE.exists():
        for r in csv.DictReader(OSM_CACHE.open()):
            if r["lat"]:
                osm[r["ccn"]] = (float(r["lat"]), float(r["lon"]), r["matched"])
            else:
                osm[r["ccn"]] = None
    todo = []
    for c in sorted(ccns):
        h = roster.get(c)
        if c in hits or c in osm or not h or not h["acute"]:
            continue
        if not c[2:].isdigit() and not c.endswith("F"):
            continue
        if h["open"] or c in linked or c in addr:
            todo.append(c)
    print(f"\nOSM name lookup for {len(todo)} acute CCNs ({sum(1 for v in osm.values() if v)} cached)...")
    for n, c in enumerate(todo, 1):
        h = roster[c]
        zp = h["zip"] or addr.get(c, ("", "", "", ""))[3]
        anchor = cents.get(zp)
        res = osm_lookup(h["name"], h["city"] or addr.get(c, ("", "", "", ""))[1], h["state"], anchor)
        if res is None and " " in h["name"]:
            short = re.sub(r"\b(INC|LLC|L L C|THE)\b", "", h["name"]).strip()
            res = osm_lookup(short + " hospital", h["city"], h["state"], anchor)
        osm[c] = res
        time.sleep(1.1)
        if n % 50 == 0:
            _flush_osm(osm)
            print(f"  {n}/{len(todo)}  found so far: {sum(1 for v in osm.values() if v)}", flush=True)
    _flush_osm(osm)

    rows, tally = [], {"census_street": 0, "osm_name": 0, "zip_centroid": 0, "unresolved": 0}
    for ccn in sorted(ccns):
        if ccn in hits:
            lat, lon, matched = hits[ccn]
            rows.append({"ccn": ccn, "lat": lat, "lon": lon,
                         "method": "census_street", "matched_address": matched})
        elif osm.get(ccn):
            lat, lon, matched = osm[ccn]
            rows.append({"ccn": ccn, "lat": lat, "lon": lon,
                         "method": "osm_name", "matched_address": matched})
        else:
            zps = [z for z in roster.get(ccn, {}).get("zips", []) + [addr.get(ccn, ("", "", "", ""))[3]] if z in cents]
            zp = zps[-1] if zps else ""   # newest vintage ZIP that the gazetteer knows
            if zp:
                lat, lon = cents[zp]
                rows.append({"ccn": ccn, "lat": lat, "lon": lon,
                             "method": "zip_centroid", "matched_address": f"ZCTA {zp}"})
            else:
                tally["unresolved"] += 1
                continue
        tally[rows[-1]["method"]] += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["ccn", "lat", "lon", "method", "matched_address"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n{tally}")
    print(f"Wrote {OUT.relative_to(REPO)} ({len(rows)} rows)")
    return 0


def _flush_osm(osm):
    with OSM_CACHE.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["ccn", "lat", "lon", "matched"])
        w.writeheader()
        for c, v in sorted(osm.items()):
            w.writerow({"ccn": c, "lat": v[0] if v else "", "lon": v[1] if v else "",
                        "matched": v[2] if v else ""})


if __name__ == "__main__":
    sys.exit(main())
