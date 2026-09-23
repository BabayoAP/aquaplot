#!/usr/bin/env python3
"""Fill a running AquaPlot with a realistic demo dataset.

A fresh deployment has an empty dashboard and an empty map, which is the worst
possible first impression of a tool whose whole argument is that a *series* of
readings is worth more than one. This script posts a small, plausible set of
assessments across the five OneAquaHealth research cities so that anyone opening
the demo sees trends, an alert feed and a declining site immediately.

It goes through the public HTTP API rather than the database, so it exercises
exactly what a citizen's browser does - including the place lookup, which needs
the network.

    .venv/bin/uvicorn aquaplot.app:app &
    .venv/bin/python scripts/seed_demo.py --url http://127.0.0.1:8000

Nothing here is a real observation. Every site is labelled "(demo data)" so it
can never be mistaken for a citizen's record.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

# Each entry is one visit. Sites that appear twice are the point of the exercise:
# they are what turns a reading into a trend, and one of them declines.
VISITS: list[dict] = [
    {
        "who": "demo-oslo",
        "site_name": "Hovinbekken, Oslo (demo data)",
        "lat": 59.9245, "lon": 10.7890,
        "answers": {"water_clarity": "clear", "water_colour": "natural", "algae": "none", "foam_or_sheen": "natural_foam",
                    "litter": "scattered", "riparian_vegetation": "continuous_natural", "bank_modification": "natural",
                    "flow": "fast", "substrate": "boulders_cobbles", "sediment_deposit": "none", "shade": "shaded",
                    "odour": "earthy", "access": "path_only"},
        "taxa": ["Perlidae", "Heptageniidae", "Leptoceridae", "Rhyacophilidae", "Goeridae", "Gammaridae", "Elmidae", "Ancylidae"],
    },
    {
        "who": "demo-coimbra",
        "site_name": "Ribeira da Fonte, Coimbra (demo data)",
        "lat": 40.2038, "lon": -8.4194,
        "answers": {"water_clarity": "slightly_turbid", "water_colour": "natural", "algae": "patchy", "foam_or_sheen": "none",
                    "litter": "scattered", "riparian_vegetation": "patchy", "bank_modification": "partly_reinforced",
                    "flow": "moderate", "substrate": "gravel", "sediment_deposit": "light", "shade": "partial",
                    "odour": "none", "access": "contact"},
        "taxa": ["Baetidae", "Hydropsychidae", "Gammaridae", "Elmidae", "Ancylidae", "Limnephilidae"],
    },
    {
        # The same stretch, a month later, after a dry spell and a discharge.
        "who": "demo-coimbra",
        "site_name": "Ribeira da Fonte, Coimbra (demo data)",
        "lat": 40.2039, "lon": -8.4195,
        "answers": {"water_clarity": "turbid", "water_colour": "grey", "algae": "extensive", "foam_or_sheen": "white_foam",
                    "litter": "heavy", "riparian_vegetation": "patchy", "bank_modification": "partly_reinforced",
                    "flow": "slow", "substrate": "silt", "sediment_deposit": "heavy", "shade": "partial",
                    "odour": "sewage", "access": "contact"},
        "taxa": ["Asellidae", "Chironomidae", "Oligochaeta", "Erpobdellidae", "Physidae"],
    },
    {
        "who": "demo-ghent",
        "site_name": "Leie side channel, Ghent (demo data)",
        "lat": 51.0489, "lon": 3.7255,
        "answers": {"water_clarity": "slightly_turbid", "water_colour": "green", "algae": "extensive", "foam_or_sheen": "none",
                    "litter": "scattered", "riparian_vegetation": "mown_grass", "bank_modification": "fully_channelised",
                    "flow": "slow", "substrate": "silt", "sediment_deposit": "light", "shade": "open",
                    "odour": "musty", "access": "contact"},
        "taxa": ["Baetidae", "Gammaridae", "Asellidae", "Chironomidae", "Physidae", "Dreissenidae"],
    },
    {
        "who": "demo-toulouse",
        "site_name": "Hers-Mort tributary, Toulouse (demo data)",
        "lat": 43.5966, "lon": 1.4722,
        "answers": {"water_clarity": "clear", "water_colour": "natural", "algae": "patchy", "foam_or_sheen": "none",
                    "litter": "none", "riparian_vegetation": "continuous_natural", "bank_modification": "natural",
                    "flow": "stagnant", "substrate": "sand", "sediment_deposit": "light", "shade": "open",
                    "odour": "none", "access": "play_or_drinking"},
        "taxa": ["Culicidae", "Chironomidae", "Baetidae", "Corixidae", "Lymnaeidae", "Coenagrionidae"],
    },
    {
        "who": "demo-benevento",
        "site_name": "Torrente San Nicola, Benevento (demo data)",
        "lat": 41.1268, "lon": 14.7715,
        "answers": {"water_clarity": "clear", "water_colour": "natural", "algae": "patchy", "foam_or_sheen": "none",
                    "litter": "scattered", "riparian_vegetation": "patchy", "bank_modification": "partly_reinforced",
                    "flow": "moderate", "substrate": "gravel", "sediment_deposit": "light", "shade": "partial",
                    "odour": "none", "access": "contact"},
        "taxa": ["Baetidae", "Caenidae", "Hydropsychidae", "Gammaridae", "Elmidae", "Procambarus clarkii"],
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="base URL of a running AquaPlot")
    args = parser.parse_args()

    with httpx.Client(base_url=args.url.rstrip("/"), timeout=60) as client:
        try:
            health = client.get("/api/health").json()
        except httpx.HTTPError as exc:
            print(f"Cannot reach AquaPlot at {args.url}: {exc}", file=sys.stderr)
            return 1
        print(f"AquaPlot {health['assessment_version']}, observer '{health['observer']}', "
              f"{health['assessments_stored']} assessments already stored.\n")

        for visit in VISITS:
            res = client.post(
                "/api/assess",
                headers={"X-AquaPlot-Contributor": visit["who"]},
                data={
                    "lat": visit["lat"], "lon": visit["lon"], "site_name": visit["site_name"],
                    "answers": json.dumps(visit["answers"]), "taxa": json.dumps(visit["taxa"]),
                },
            )
            if res.status_code != 200:
                print(f"  ! {visit['site_name']}: {res.status_code} {res.text[:200]}", file=sys.stderr)
                continue
            a = res.json()
            print(f"  {a['band']:9s} {a['one_health']['overall']:8s} {a['certainty']:5.1f}%  {visit['site_name']}")

        sites = client.get("/api/sites").json()["sites"]
        alerts = client.get("/api/alerts").json()["alerts"]
        print(f"\n{len(sites)} sites, {len(alerts)} needing attention.")
        for s in sites:
            if s["trend"]["direction"] != "new":
                print(f"  trend: {s['name']} — {s['trend']['detail']}")
        print(f"\nOpen {args.url}/dashboard and {args.url}/map")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
