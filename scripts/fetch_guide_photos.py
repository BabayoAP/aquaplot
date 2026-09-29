#!/usr/bin/env python3
"""Fetch one openly licensed reference photo per family for the animal picker and the ID guide.

Each photo shows the stage a volunteer actually finds in a tray. For the insects that live in
water only while young (mayflies, stoneflies, caddisflies, dragonflies and damselflies, true
flies, alderflies) that means nymphs and larvae, never the winged adult. The water beetles and
water bugs live in the water as adults, and the catalogue describes them that way, so they are
shown as adults. Everything else is shown at any stage.

Research-grade observations from Europe come first, most-faved first, falling back to anywhere.
Licences without a non-commercial clause are preferred; CC BY-NC is used only when nothing else
exists. Each photo is saved twice as WebP in ``static/guide/``: a 200 px square for the picker,
and the whole frame up to 800 px for the enlarged view. ``data/guide_photos.json`` records the
photographer's attribution, the licence and the observation, which the app shows beside the
photo. The app itself never calls iNaturalist for these: they ship with it, and the service
worker keeps them for offline use.

    .venv/bin/python scripts/fetch_guide_photos.py                 # every family without a photo
    .venv/bin/python scripts/fetch_guide_photos.py --families Perlidae --skip 123456
                                                                   # replace a poor photo
    .venv/bin/python scripts/fetch_guide_photos.py --refresh       # redo the files from the
                                                                   # observations already chosen
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from aquaplot.bioindex import CATALOGUE

API = "https://api.inaturalist.org/v1"
EUROPE = 97391
OPEN = "cc0,cc-by,cc-by-sa"
NON_COMMERCIAL = "cc-by-nc,cc-by-nc-sa"
LIFE_STAGE, NYMPH, LARVA = 1, 5, 6
YOUNG_IN_WATER = {"Ephemeroptera", "Plecoptera", "Trichoptera", "Odonata", "Diptera", "Megaloptera"}
SIZE = 200
LARGE = 800
# Where iNaturalist files a catalogue family under another name, or the catalogue's group is broader
# than the animal a volunteer finds in a tray.
INAT_NAMES = {
    "Ancylidae": "Ancylinae",    # river limpets: a subfamily of Planorbidae on iNaturalist
    "Oligochaeta": "Tubificinae",  # the aquatic sludge worms, not earthworms
    "Syrphidae": "Eristalis",      # the rat-tailed maggot; most hoverfly larvae live on land
}
PAUSE = 1.1  # iNaturalist asks for about one request a second

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "aquaplot"
PHOTO_DIR = PACKAGE / "static" / "guide"
MANIFEST = PACKAGE / "data" / "guide_photos.json"


def choose(results: list[dict], skip: set[int]) -> dict | None:
    """The first observation with a photo that has not been ruled out by hand."""
    return next((o for o in results if o.get("photos") and o["id"] not in skip), None)


def entry(family: str, obs: dict) -> dict:
    photo = obs["photos"][0]
    return {
        "file": f"{family.lower()}.webp",
        "large": f"{family.lower()}-large.webp",
        "attribution": photo["attribution"],
        "licence": photo["license_code"],
        "observation": f"https://www.inaturalist.org/observations/{obs['id']}",
    }


def thumbnail(data: bytes, size: int = SIZE) -> bytes:
    """Centre-cropped square WebP, small enough that all 53 come to about a megabyte."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    image = ImageOps.fit(image, (size, size), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "WEBP", quality=74, method=6)
    return out.getvalue()


def enlarged(data: bytes, size: int = LARGE) -> bytes:
    """The whole frame, no crop, at most ``size`` px on its long edge: what the enlarged view shows."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    image.thumbnail((size, size), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "WEBP", quality=76, method=6)
    return out.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--families", help="comma-separated subset to fetch or replace, e.g. Perlidae,Baetidae")
    parser.add_argument("--skip", default="", help="comma-separated observation ids to pass over (poor photos)")
    parser.add_argument("--refresh", action="store_true",
                        help="rebuild the files from the observations already in the manifest, without searching again")
    args = parser.parse_args()

    wanted = {f.strip().lower() for f in args.families.split(",")} if args.families else None
    skip = {int(s) for s in args.skip.split(",") if s.strip()}
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"photos": {}}
    photos: dict = manifest.setdefault("photos", {})
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)

    def get(client: httpx.Client, path: str, **params) -> dict:
        time.sleep(PAUSE)
        r = client.get(f"{API}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def save(client: httpx.Client, family: str, obs: dict) -> None:
        url = obs["photos"][0]["url"].replace("/square.", "/large.")
        time.sleep(PAUSE)
        data = client.get(url, timeout=60).content
        (PHOTO_DIR / f"{family.lower()}.webp").write_bytes(thumbnail(data))
        (PHOTO_DIR / f"{family.lower()}-large.webp").write_bytes(enlarged(data))
        photos[family] = entry(family, obs)
        print(f"{family}: {photos[family]['licence']} {photos[family]['observation']}", file=sys.stderr)

    headers = {"User-Agent": "AquaPlot ID guide (github.com/BabayoAP/aquaplot)"}
    with httpx.Client(headers=headers) as client:
        for fam in CATALOGUE:
            if wanted is not None and fam.family.lower() not in wanted:
                continue
            if args.refresh:
                if fam.family not in photos:
                    continue
                obs_id = photos[fam.family]["observation"].rsplit("/", 1)[-1]
                obs = get(client, f"/observations/{obs_id}")["results"][0]
                save(client, fam.family, obs)
                continue
            if wanted is None and fam.family in photos:
                continue
            name = INAT_NAMES.get(fam.family, fam.family)
            taxa = get(client, "/taxa", q=name, per_page=5)["results"]
            taxon = next((t for t in taxa if t["name"].lower() == name.lower()), None)
            if taxon is None:
                print(f"skip {fam.family}: not found on iNaturalist", file=sys.stderr)
                continue
            obs = None
            for licences in (OPEN, NON_COMMERCIAL):
                for place in (EUROPE, None):
                    params = {"taxon_id": taxon["id"], "quality_grade": "research", "photos": "true",
                              "photo_license": licences, "per_page": 10, "order_by": "votes"}
                    if place:
                        params["place_id"] = place
                    if fam.group in YOUNG_IN_WATER:
                        params.update(term_id=LIFE_STAGE, term_value_id=f"{NYMPH},{LARVA}")
                    obs = choose(get(client, "/observations", **params)["results"], skip)
                    if obs:
                        break
                if obs:
                    break
            if obs is None:
                print(f"skip {fam.family}: no openly licensed photo found", file=sys.stderr)
                continue
            save(client, fam.family, obs)

    manifest["note"] = (
        "One reference photo per family for the animal picker and the ID guide, fetched from iNaturalist by "
        "scripts/fetch_guide_photos.py. Each shows the stage a volunteer finds in a tray; the attribution, licence "
        "and observation are shown beside the photo."
    )
    manifest["photos"] = dict(sorted(photos.items()))
    MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(photos)} of {len(CATALOGUE)} families have a photo", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
