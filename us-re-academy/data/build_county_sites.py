#!/usr/bin/env python3
"""Build data/county_sites.json: official website for every US county, keyed "Summit County|OH".

Sources: Wikidata (FIPS code P882 + official website P856) and the Census ZCTA-county
relationship file for county names. Needs network access to query.wikidata.org and www2.census.gov.

Usage:
    python3 build_county_sites.py --out .
"""
import argparse
import json
import os
import urllib.parse
import urllib.request

from build_market_data import REL, STATES, fetch

SPARQL = """
SELECT ?fips ?site WHERE {
  ?c wdt:P882 ?fips ; wdt:P856 ?site .
  FILTER(STRLEN(?fips) = 5)
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    a = ap.parse_args()

    names = {}
    text = fetch(f"{REL}/tab20_zcta520_county20_natl.txt").decode("utf-8-sig").splitlines()
    head = text[0].split("|")
    ig, iname = head.index("GEOID_COUNTY_20"), head.index("NAMELSAD_COUNTY_20")
    for line in text[1:]:
        c = line.split("|")
        if c[ig]:
            names[c[ig]] = c[iname]

    req = urllib.request.Request(
        "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(SPARQL),
        headers={"User-Agent": "us-invest-app/1.0 (county website lookup)", "Accept": "application/sparql-results+json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        rows = json.load(r)["results"]["bindings"]

    sites = {}
    for b in rows:
        fips, site = b["fips"]["value"], b["site"]["value"]
        st = STATES.get(fips[:2])
        if not st or fips not in names or not site.startswith("http"):
            continue
        key = f"{names[fips]}|{st}"
        # keep the shortest URL when Wikidata lists several (usually the homepage)
        if key not in sites or len(site) < len(sites[key]):
            sites[key] = site
    with open(os.path.join(a.out, "county_sites.json"), "w", encoding="utf-8") as f:
        json.dump(sites, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(f"{len(sites)} county websites")


if __name__ == "__main__":
    main()
