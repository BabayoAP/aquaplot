#!/usr/bin/env python3
"""Build a labelled evaluation set from openly licensed iNaturalist photos.

For each family in the bioindicator catalogue, fetch a few research-grade
observations from Europe (by default) that carry an open photo licence, and for
insects only those annotated as larva or nymph - the stage a volunteer finds in a
tray, not the adult on a streetlight. Photos are written next to a ``labels.csv``
that ``evaluate_observer.py`` reads, with the photographer's attribution and the
observation link in the ``note`` column.

    .venv/bin/python scripts/fetch_inat_eval.py --per-family 3 --out eval/inat

These are single-animal photos, usually well lit and well framed. They measure
identification, and they flatter it: a real tray photo is harder. Say so wherever
the numbers are quoted (docs/EVALUATION.md does).
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import httpx

from aquaplot.bioindex import CATALOGUE

API = "https://api.inaturalist.org/v1"
EUROPE = 97391
LICENCES = "cc-by,cc-by-nc,cc0,cc-by-sa,cc-by-nc-sa"
LIFE_STAGE, NYMPH, LARVA = 1, 5, 6
INSECT_ORDERS = {"Ephemeroptera", "Plecoptera", "Trichoptera", "Odonata", "Coleoptera", "Diptera", "Megaloptera", "Hemiptera"}
PAUSE = 1.1  # iNaturalist asks for about one request a second


def get(client: httpx.Client, path: str, **params) -> dict:
    time.sleep(PAUSE)
    r = client.get(f"{API}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("eval/inat"))
    parser.add_argument("--per-family", type=int, default=2)
    parser.add_argument("--place-id", type=int, default=EUROPE, help="iNaturalist place id (default Europe); 0 for anywhere")
    parser.add_argument("--families", help="comma-separated subset, e.g. Perlidae,Baetidae")
    args = parser.parse_args()

    wanted = {f.strip().lower() for f in args.families.split(",")} if args.families else None
    families = [f for f in CATALOGUE if wanted is None or f.family.lower() in wanted]
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(headers={"User-Agent": "AquaPlot evaluation (github.com/BabayoAP/aquaplot)"}) as client:
        for fam in families:
            taxa = get(client, "/taxa", q=fam.family, per_page=5)["results"]
            taxon = next((t for t in taxa if t["name"].lower() == fam.family.lower()), None)
            if taxon is None:
                print(f"skip {fam.family}: not found on iNaturalist", file=sys.stderr)
                continue
            params = {
                "taxon_id": taxon["id"],
                "quality_grade": "research",
                "photos": "true",
                "photo_license": LICENCES,
                "per_page": args.per_family,
                "order_by": "votes",
            }
            if args.place_id:
                params["place_id"] = args.place_id
            if fam.group in INSECT_ORDERS:
                params.update(term_id=LIFE_STAGE, term_value_id=f"{NYMPH},{LARVA}")
            found = get(client, "/observations", **params)["results"]
            print(f"{fam.family}: {len(found)}", file=sys.stderr)
            for obs in found:
                photo = obs["photos"][0]
                url = photo["url"].replace("/square.", "/medium.")
                name = f"{fam.family.lower()}-{obs['id']}.jpg"
                time.sleep(PAUSE)
                (args.out / name).write_bytes(client.get(url, timeout=60).content)
                rows.append(
                    {
                        "photo": name,
                        "families": fam.family,
                        "note": f"{photo['attribution']} - https://www.inaturalist.org/observations/{obs['id']}",
                    }
                )
    with (args.out / "labels.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["photo", "families", "note"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} photos written to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
