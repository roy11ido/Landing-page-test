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

# Large counties Wikidata has no website for, and consolidated city-counties (use the city site).
# Counties without a county government (most of CT, MA, RI) are intentionally left out.
OVERRIDES = {
    "Maricopa County|AZ": "https://www.maricopa.gov",
    "Bexar County|TX": "https://www.bexar.org",
    "Hillsborough County|FL": "https://www.hillsboroughcounty.org",
    "Westchester County|NY": "https://www.westchestergov.com",
    "Palm Beach County|FL": "https://www.pbcgov.org",
    "Hamilton County|OH": "https://www.hamiltoncountyohio.gov",
    "Salt Lake County|UT": "https://www.saltlakecounty.gov",
    "Lee County|FL": "https://www.leegov.com",
    "Lake County|FL": "https://www.lakecountyfl.gov",
    "Linn County|IA": "https://www.linncountyiowa.gov",
    "Queens County|NY": "https://www.nyc.gov",
    "Kings County|NY": "https://www.nyc.gov",
    "New York County|NY": "https://www.nyc.gov",
    "Bronx County|NY": "https://www.nyc.gov",
    "Richmond County|NY": "https://www.nyc.gov",
    "Philadelphia County|PA": "https://www.phila.gov",
    "San Francisco County|CA": "https://www.sf.gov",
    "Honolulu County|HI": "https://www.honolulu.gov",
    "Davidson County|TN": "https://www.nashville.gov",
    "Fayette County|KY": "https://www.lexingtonky.gov",
    "Roanoke City|VA": "https://www.roanokeva.gov",
}

# Addresses confirmed by the user; these replace whatever Wikidata has.
CORRECTIONS = {
    "Hamilton County|IN": "https://www.hamiltoncounty.in.gov/",
}

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
    for k, v in OVERRIDES.items():
        sites.setdefault(k, v)
    # most county sites now only work over https; old Wikidata entries still say http
    sites = {k: "https://" + v[len("http://"):] if v.startswith("http://") else v for k, v in sites.items()}
    sites.update(CORRECTIONS)
    with open(os.path.join(a.out, "county_sites.json"), "w", encoding="utf-8") as f:
        json.dump(sites, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(f"{len(sites)} county websites")


if __name__ == "__main__":
    main()
