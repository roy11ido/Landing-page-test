#!/usr/bin/env python3
"""Build data/places.json: every US city / town with its state, main county and ZIP codes.

Used by the app for city autocomplete, ZIP -> city/county lookup and county links.
Source: USPS ZIP code list bundled in the `zipcodes` package (pip install zipcodes).

Usage:
    python3 build_places.py --out .
"""
import argparse
import collections
import datetime as dt
import json
import os

import zipcodes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    a = ap.parse_args()

    by_place = collections.defaultdict(lambda: {"zips": [], "counties": collections.Counter()})
    for z in zipcodes.list_all():
        if not z.get("active") or z.get("zip_code_type") not in ("STANDARD", "PO BOX") or not z.get("county"):
            continue
        key = (z["city"].strip(), z["state"])
        by_place[key]["zips"].append(z["zip_code"])
        by_place[key]["counties"][z["county"]] += 1

    counties, cidx, places = [], {}, []
    for (city, st), d in by_place.items():
        county = d["counties"].most_common(1)[0][0]
        ck = f"{county}|{st}"
        if ck not in cidx:
            cidx[ck] = len(counties)
            counties.append(ck)
        places.append([city, st, cidx[ck], sorted(d["zips"])])
    places.sort(key=lambda p: (-len(p[3]), p[0]))

    out = {
        "v": 1,
        "built": dt.date.today().isoformat(),
        "src": "USPS ZIP code list (zipcodes package)",
        "counties": counties,
        "places": places,
    }
    with open(os.path.join(a.out, "places.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(places)} places, {len(counties)} counties")


if __name__ == "__main__":
    main()
