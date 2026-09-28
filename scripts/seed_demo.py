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

from aquaplot.demo import VISITS  # one dataset, shared with AQUAPLOT_SEED_DEMO


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="base URL of a running AquaPlot")
    args = parser.parse_args()

    # Over HTTP a visit is dated when it arrives, so the series here are compressed
    # into one moment; AQUAPLOT_SEED_DEMO=1 seeds in-process with real dates instead.
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
