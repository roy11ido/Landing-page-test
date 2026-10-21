#!/usr/bin/env python3
"""Build per-state market data for the app from the U.S. Census Bureau (ACS 5-year).

Writes <out>/index.json and <out>/<ST>.json (one file per state, keyed by ZIP / ZCTA).
Standard library only. Optional: set CENSUS_API_KEY to raise the API rate limit.

Usage:
    python3 build_market_data.py --out .            # latest available ACS 5-year
    python3 build_market_data.py --out . --year 2024
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.census.gov/data"
REL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520"
ZCTA = "zip code tabulation area:*"

STATES = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
    "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
    "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY", "72": "PR",
}

# Per-ZIP fields, in the order the app decodes them (keep in sync with ZFIELDS in the app).
ZVARS = [
    ("pop", "B01003_001E"),        # total population
    ("income", "B19013_001E"),     # median household income
    ("units", "B25002_001E"),      # housing units
    ("vacant", "B25002_003E"),     # vacant units
    ("occ", "B25003_001E"),        # occupied units
    ("owner", "B25003_002E"),      # owner-occupied units
    ("rent", "B25064_001E"),       # median gross rent
    ("value", "B25077_001E"),      # median home value
    ("built", "B25035_001E"),      # median year structure built
    ("labor", "B23025_003E"),      # civilian labor force
    ("unemp", "B23025_005E"),      # unemployed
]
# County industry shares (percent of employed), used for a diversification index.
INDUSTRY = [f"DP03_00{n}PE" for n in range(33, 46)]
COUNTY_UNEMP = "DP03_0009PE"


def fetch(url, tries=4):
    key = os.environ.get("CENSUS_API_KEY")
    if key and url.startswith(API):
        url += ("&" if "?" in url else "?") + "key=" + urllib.parse.quote(key)
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                raise
            err = e
        except (urllib.error.URLError, TimeoutError) as e:
            err = e
        time.sleep(2 ** (i + 1))
    raise SystemExit(f"failed after {tries} tries: {url} ({err})")


def acs(year, variables, geo, dataset="acs/acs5"):
    url = f"{API}/{year}/{dataset}?get={','.join(variables)}&for={urllib.parse.quote(geo)}"
    rows = json.loads(fetch(url))
    head, body = rows[0], rows[1:]
    return [dict(zip(head, r)) for r in body]


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
            acs(y, ["B01003_001E"], "zip code tabulation area:43205")
            return y
        except urllib.error.HTTPError:
            continue
    raise SystemExit("no ACS 5-year release found")


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
    print(f"ACS 5-year {year}", file=sys.stderr)

    zips = {r["zip code tabulation area"]: r for r in acs(year, [v for _, v in ZVARS], ZCTA)}
    past = {r["zip code tabulation area"]: num(r["B01003_001E"]) for r in acs(year - 5, ["B01003_001E"], ZCTA)}
    county_of = relationship("tab20_zcta520_county20_natl.txt", "GEOID_COUNTY_20", "NAMELSAD_COUNTY_20")
    place_of = relationship("tab20_zcta520_place20_natl.txt", "GEOID_PLACE_20", "NAMELSAD_PLACE_20")

    counties = {}
    for r in acs(year, INDUSTRY + [COUNTY_UNEMP, "NAME"], "county:*", "acs/acs5/profile"):
        fips = r["state"] + r["county"]
        shares = [num(r[v]) for v in INDUSTRY]
        hhi = round(sum((s / 100) ** 2 for s in shares if s is not None), 4) if all(s is not None for s in shares) else None
        counties[fips] = [r["NAME"].split(",")[0], hhi, num(r[COUNTY_UNEMP])]

    out = {}
    zip3 = {}
    for z, r in zips.items():
        cty = county_of.get(z)
        if not cty:
            continue
        st = STATES.get(cty[0][:2])
        if not st:
            continue
        place = clean_place(place_of[z][1]) if z in place_of else ""
        row = [num(r[v]) for _, v in ZVARS] + [past.get(z), cty[0], place]
        s = out.setdefault(st, {"z": {}, "c": {}, "p": {}})
        s["z"][z] = row
        s["c"][cty[0]] = counties.get(cty[0], [cty[1], None, None])
        if place:
            s["p"].setdefault(place.lower(), []).append(z)
        zip3.setdefault(z[:3], {}).setdefault(st, 0)
        zip3[z[:3]][st] += 1

    built = dt.date.today().isoformat()
    src = f"U.S. Census Bureau, American Community Survey 5-year {year}"
    os.makedirs(a.out, exist_ok=True)
    for st, s in out.items():
        s.update({"v": 1, "year": year, "built": built, "src": src})
        with open(os.path.join(a.out, f"{st}.json"), "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, separators=(",", ":"))
    index = {
        "v": 1, "year": year, "built": built, "src": src,
        "zip3": {k: max(v, key=v.get) for k, v in sorted(zip3.items())},
        "states": {st: len(s["z"]) for st, s in sorted(out.items())},
    }
    with open(os.path.join(a.out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, separators=(",", ":"))
    print(f"wrote {len(out)} states, {sum(index['states'].values())} ZIPs", file=sys.stderr)


if __name__ == "__main__":
    main()
