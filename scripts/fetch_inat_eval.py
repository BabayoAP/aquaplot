#!/usr/bin/env python3
"""Build a labelled evaluation set from openly licensed iNaturalist photos.

For each family in the bioindicator catalogue, fetch a few research-grade
observations from Europe (by default) that carry an open photo licence, and for
insects only those annotated as larva or nymph - the stage a volunteer finds in a
tray, not the adult on a streetlight. Photos are written next to a ``labels.csv``
that ``evaluate_observer.py`` reads, with the photographer's attribution and the
observation link in the ``note`` column.

    .venv/bin/python scripts/fetch_inat_eval.py --per-family 3 --out eval/inat

Searching again does not give the same set back: it is ordered by votes, and both
the votes and the pool of research-grade observations move. So the set a number
was measured on is pinned by its ``labels.csv``, which is committed, and rebuilt
from it by observation id:

    .venv/bin/python scripts/fetch_inat_eval.py --from-labels eval/inat/labels.csv

That is the mode to use before running ``evaluate_observer.py``, so your figures
and the ones in docs/EVALUATION.md are about the same photographs.

These are single-animal photos, usually well lit and well framed. They measure
identification, and they flatter it: a real tray photo is harder. Say so wherever
the numbers are quoted (docs/EVALUATION.md does).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

import httpx

from aquaplot.bioindex import CATALOGUE

API = "https://api.inaturalist.org/v1"
UA = "AquaPlot evaluation (github.com/BabayoAP/aquaplot)"
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


OBSERVATION_URL = re.compile(r"inaturalist\.org/observations/(\d+)")
OBSERVATION_LIKE = re.compile(r"[1-9]\d{5,}")


def observation_id(row: dict) -> int | None:
    """The iNaturalist observation a labelled photo came from, or None.

    The link in ``note`` is the record. The ``family-12345.jpg`` filename is a
    fallback for a labels.csv whose notes were rewritten, and it has to be a
    careful one: somebody's own ``tray-01.jpg`` must not be mistaken for
    observation 1 and overwritten with a stranger's photograph. So the fallback
    only fires on something that looks like an iNaturalist id - six digits or
    more, no leading zero - and a set of personal photos simply reports that it
    cannot be rebuilt, which is true.
    """
    found = OBSERVATION_URL.search(row.get("note") or "")
    if found:
        return int(found.group(1))
    tail = Path(row["photo"]).stem.rsplit("-", 1)[-1]
    return int(tail) if OBSERVATION_LIKE.fullmatch(tail) else None


def rebuild(client: httpx.Client, labels: Path) -> int:
    """Re-fetch exactly the photos a committed labels.csv names.

    A measurement is only checkable if the set it was taken on can be got back,
    and searching again does not do that (see the module docstring). Each row
    names its observation, so each row can be fetched by id. Photos already on
    disk are left alone, so an interrupted rebuild resumes.

    An observation whose photo has gone - deleted, or its licence changed - is
    reported and skipped, because a quietly smaller set would quietly change
    every figure taken from it.
    """
    with labels.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    folder = labels.parent
    folder.mkdir(parents=True, exist_ok=True)
    missing = []
    for i, row in enumerate(rows, 1):
        target = folder / row["photo"]
        if target.exists():
            continue
        obs_id = observation_id(row)
        if obs_id is None:
            missing.append((row["photo"], "no observation id in the note or the filename"))
            continue
        try:
            results = get(client, f"/observations/{obs_id}")["results"]
            photo = results[0]["photos"][0]
        except (httpx.HTTPError, IndexError, KeyError) as exc:
            missing.append((row["photo"], f"observation {obs_id}: {exc}"))
            continue
        time.sleep(PAUSE)
        target.write_bytes(client.get(photo["url"].replace("/square.", "/medium."), timeout=60).content)
        print(f"[{i}/{len(rows)}] {row['photo']}", file=sys.stderr)
    have = sum(1 for row in rows if (folder / row["photo"]).exists())
    print(f"{have} of {len(rows)} photos present in {folder}", file=sys.stderr)
    for name, why in missing:
        print(f"  missing {name}: {why}", file=sys.stderr)
    if missing:
        print(
            "The set is incomplete, so figures from it are not comparable with figures\n"
            "taken on the whole set. Say which photos were absent wherever you quote them.",
            file=sys.stderr,
        )
    return 1 if missing else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("eval/inat"))
    parser.add_argument("--per-family", type=int, default=2)
    parser.add_argument("--place-id", type=int, default=EUROPE, help="iNaturalist place id (default Europe); 0 for anywhere")
    parser.add_argument("--families", help="comma-separated subset, e.g. Perlidae,Baetidae")
    parser.add_argument(
        "--from-labels",
        type=Path,
        help="rebuild exactly the photos this committed labels.csv names, by observation id, instead of searching",
    )
    args = parser.parse_args()

    if args.from_labels:
        with httpx.Client(headers={"User-Agent": UA}) as client:
            return rebuild(client, args.from_labels)

    wanted = {f.strip().lower() for f in args.families.split(",")} if args.families else None
    families = [f for f in CATALOGUE if wanted is None or f.family.lower() in wanted]
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(headers={"User-Agent": UA}) as client:
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
