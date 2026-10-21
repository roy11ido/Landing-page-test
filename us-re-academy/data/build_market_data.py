#!/usr/bin/env python3
"""Build per-state market data for the app from the U.S. Census Bureau (ACS 5-year).

Reads the ACS table-based summary files on www2.census.gov (no API key needed) and
writes <out>/index.json and <out>/<ST>.json (one file per state, keyed by ZIP / ZCTA).
Population growth compares the latest 5-year release with the one 3 years earlier.
Standard library only.

Usage:
    python3 build_market_data.py --out .            # latest available ACS 5-year
    python3 build_market_data.py --out . --year 2024
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

SF = "https://www2.census.gov/programs-surveys/acs/summary_file/{y}/table-based-SF/data/5YRData/acsdt5y{y}-{t}.dat"
REL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520"
ZCTA, COUNTY = "860Z200US", "0500000US"
GROWTH_YEARS = 3

STATES = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
    "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
    "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY", "72": "PR",
}

# Per-ZIP fields, in the order the app decodes them (keep in sync with decodeZip in the app).
ZVARS = [
    ("pop", "b01003", "B01003_E001"),     # total population
    ("income", "b19013", "B19013_E001"),  # median household income
    ("units", "b25002", "B25002_E001"),   # housing units
    ("vacant", "b25002", "B25002_E003"),  # vacant units
    ("occ", "b25003", "B25003_E001"),     # occupied units
    ("owner", "b25003", "B25003_E002"),   # owner-occupied units
    ("rent", "b25064", "B25064_E001"),    # median gross rent
    ("value", "b25077", "B25077_E001"),   # median home value
    ("built", "b25035", "B25035_E001"),   # median year structure built
    ("labor", "b23025", "B23025_E003"),   # civilian labor force
    ("unemp", "b23025", "B23025_E005"),   # unemployed
]
# Median real estate taxes paid (owner-occupied); appended after the place name, with median value gives an effective rate.
TAX = ("b25103", "B25103_E001")
# County employment by industry (13 sectors) for a diversification index.
INDUSTRY = [f"C24050_E{n:03d}" for n in range(2, 15)]


def open_url(url, tries=4):
    for i in range(tries):
        try:
            return urllib.request.urlopen(url, timeout=300)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise
            err = e
        except (urllib.error.URLError, TimeoutError) as e:
            err = e
        time.sleep(2 ** (i + 1))
    raise SystemExit(f"failed after {tries} tries: {url} ({err})")


def fetch(url):
    with open_url(url) as r:
        return r.read()


def table(year, name, columns, prefixes=(ZCTA, COUNTY)):
    """Stream one summary-file table and keep only the requested columns for ZCTA / county rows."""
    out = {}
    with open_url(SF.format(y=year, t=name)) as r:
        head = r.readline().decode().rstrip("\r\n").split("|")
        idx = [head.index(c) for c in columns]
        for raw in r:
            line = raw.decode("utf-8", "replace")
            if not line.startswith(prefixes):
                continue
            c = line.rstrip("\r\n").split("|")
            out[c[0]] = [c[i] for i in idx]
    print(f"  {year} {name}: {len(out)} rows", file=sys.stderr)
    return out


def num(v):
    """Census uses large negative sentinels for missing values."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x < -1000:
        return None
    return int(x) if x.is_integer() else round(x, 2)


def latest_year(start):
    for y in range(start, start - 4, -1):
        try:
            open_url(SF.format(y=y, t="b01003"), tries=1).close()
            return y
        except urllib.error.HTTPError:
            continue
    raise SystemExit("no ACS 5-year summary file found")


def relationship(name, geo_col, name_col):
    """ZCTA -> (geoid, name) of the related geography with the largest land overlap."""
    text = fetch(f"{REL}/{name}").decode("utf-8-sig")
    lines = text.splitlines()
    head = lines[0].split("|")
    iz, ig, iname, iarea = head.index("GEOID_ZCTA5_20"), head.index(geo_col), head.index(name_col), head.index("AREALAND_PART")
    best = {}
    for line in lines[1:]:
        c = line.split("|")
        z, g = c[iz], c[ig]
        if not z or not g:
            continue
        area = int(c[iarea] or 0)
        if z not in best or area > best[z][2]:
            best[z] = (g, c[iname], area)
    return {z: (g, n) for z, (g, n, _) in best.items()}


def clean_place(n):
    for suffix in (" city", " village", " town", " CDP", " borough", " municipality", " township"):
        if n.endswith(suffix):
            return n[: -len(suffix)]
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--year", type=int)
    a = ap.parse_args()
    year = a.year or latest_year(dt.date.today().year - 1)
    past_year = year - GROWTH_YEARS
    print(f"ACS 5-year {year} (growth vs {past_year})", file=sys.stderr)

    cols = {}
    for _, t, c in ZVARS:
        cols.setdefault(t, []).append(c)
    cols.setdefault(TAX[0], []).append(TAX[1])
    data = {t: table(year, t, cs) for t, cs in cols.items()}
    past = table(past_year, "b01003", ["B01003_E001"], (ZCTA,))
    ind = table(year, "c24050", ["C24050_E001"] + INDUSTRY, (COUNTY,))

    def val(geo, t, c):
        row = data[t].get(geo)
        return num(row[cols[t].index(c)]) if row else None

    county_of = relationship("tab20_zcta520_county20_natl.txt", "GEOID_COUNTY_20", "NAMELSAD_COUNTY_20")
    place_of = relationship("tab20_zcta520_place20_natl.txt", "GEOID_PLACE_20", "NAMELSAD_PLACE_20")

    counties = {}
    for geo, row in ind.items():
        fips = geo[len(COUNTY):]
        total = num(row[0])
        hhi = round(sum((num(x) / total) ** 2 for x in row[1:] if num(x) is not None), 4) if total else None
        labor, unemp = val(geo, "b23025", "B23025_E003"), val(geo, "b23025", "B23025_E005")
        tax, value = val(geo, *TAX), val(geo, "b25077", "B25077_E001")
        rate = round(tax / value * 100, 2) if tax and value else None
        counties[fips] = [None, hhi, round(unemp / labor * 100, 1) if labor and unemp is not None else None, rate]
    for z, (fips, name) in county_of.items():
        if fips in counties and counties[fips][0] is None:
            counties[fips][0] = name

    zips = {geo[len(ZCTA):]: geo for geo in data["b01003"] if geo.startswith(ZCTA)}

    out = {}
    zip3 = {}
    for z, geo in zips.items():
        cty = county_of.get(z)
        if not cty:
            continue
        st = STATES.get(cty[0][:2])
        if not st:
            continue
        place = clean_place(place_of[z][1]) if z in place_of else ""
        p = past.get(geo)
        row = [val(geo, t, c) for _, t, c in ZVARS] + [num(p[0]) if p else None, cty[0], place, val(geo, *TAX)]
        s = out.setdefault(st, {"z": {}, "c": {}, "p": {}})
        s["z"][z] = row
        s["c"][cty[0]] = counties.get(cty[0], [cty[1], None, None, None])
        if place:
            s["p"].setdefault(place.lower(), []).append(z)
        zip3.setdefault(z[:3], {}).setdefault(st, 0)
        zip3[z[:3]][st] += 1

    built = dt.date.today().isoformat()
    src = f"U.S. Census Bureau, American Community Survey 5-year {year}"
    os.makedirs(a.out, exist_ok=True)
    for st, s in out.items():
        s.update({"v": 1, "year": year, "past": past_year, "built": built, "src": src})
        with open(os.path.join(a.out, f"{st}.json"), "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, separators=(",", ":"))
    index = {
        "v": 1, "year": year, "past": past_year, "built": built, "src": src,
        "zip3": {k: max(v, key=v.get) for k, v in sorted(zip3.items())},
        "states": {st: len(s["z"]) for st, s in sorted(out.items())},
    }
    with open(os.path.join(a.out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, separators=(",", ":"))
    print(f"wrote {len(out)} states, {sum(index['states'].values())} ZIPs", file=sys.stderr)


if __name__ == "__main__":
    main()
