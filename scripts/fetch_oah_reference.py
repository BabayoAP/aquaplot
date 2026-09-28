#!/usr/bin/env python3
"""Snapshot the OneAquaHealth project's public reference data into the package.

Two things come from the project's own API (https://api.enora-oah.eu, public
endpoints, no account):

* the research sites, ``GET /api/sites/all`` - the 106 urban stream reaches in
  Benevento, Coimbra, Ghent, Oslo and Toulouse where the project samples, each
  with the code its lab data is filed under;
* the vocabularies of its Citizen Science App, ``GET /api/citizens/{list}`` - the
  answer codes a citizen submission uses for water flow, water colour, habitats,
  vegetation, channel and bank types, fallen biomass and the overall assessment.

The app reads the snapshot, never the API: a stream check must work at a riverbank
with no signal, and tests must never reach the network. Re-run this to refresh it.

    .venv/bin/python scripts/fetch_oah_reference.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

API = "https://api.enora-oah.eu/api"
VOCABULARIES = (
    "water_flows",
    "water_colors",
    "habitats",
    "vegetation_types",
    "channel_types",
    "channel_forms",
    "bank_types",
    "fallen_biomass",
    "stream_assessments",
)
OUT = Path(__file__).resolve().parent.parent / "src" / "aquaplot" / "data" / "oah_reference.json"


def main() -> None:
    with httpx.Client(timeout=30) as client:
        sites = client.get(f"{API}/sites/all").raise_for_status().json()
        vocab = {name: client.get(f"{API}/citizens/{name}").raise_for_status().json() for name in VOCABULARIES}
    snapshot = {
        "version": f"oah-{datetime.now(UTC):%Y-%m-%d}",
        "source": API,
        "note": (
            "Snapshot of the OneAquaHealth project's public API: its research sites and the answer codes of its "
            "Citizen Science App. Regenerate with scripts/fetch_oah_reference.py; the app never calls the API itself."
        ),
        "sites": [
            {
                "code": s["code"],
                "name": s["name"],
                "city": s["city"]["name"],
                "city_code": s["city"]["id"],
                "lat": s["latitude"],
                "lon": s["longitude"],
                "altitude_m": s.get("altitude"),
            }
            for s in sites
            if s.get("latitude") is not None and s.get("longitude") is not None
        ],
        "app_vocabularies": vocab,
    }
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(snapshot['sites'])} sites and {len(vocab)} vocabularies -> {OUT}")


if __name__ == "__main__":
    main()
