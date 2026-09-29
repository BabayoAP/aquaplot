"""The ID photos: one per family, credited, served by the app, and kept for use at the stream."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

from PIL import Image

from aquaplot.bioindex import CATALOGUE

ROOT = Path(__file__).resolve().parent.parent


def _fetcher():
    spec = importlib.util.spec_from_file_location("fetch_guide_photos", ROOT / "scripts" / "fetch_guide_photos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_family_in_the_picker_has_a_photo_the_app_serves_itself(client):
    families = client.get("/api/guide").json()["families"]
    assert len(families) == len(CATALOGUE) and all(f["photo"] for f in families)
    for f in families:
        assert f["photo"]["url"].startswith("/static/guide/")  # never hot-linked from iNaturalist
        res = client.get(f["photo"]["url"])
        assert res.status_code == 200 and res.headers["content-type"] == "image/webp"


def test_every_photo_names_its_photographer_its_licence_and_its_observation(client):
    for f in client.get("/api/guide").json()["families"]:
        photo = f["photo"]
        assert photo["attribution"].strip(), f["family"]
        assert photo["licence"] in {"cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa"}, f["family"]
        assert photo["observation"].startswith("https://www.inaturalist.org/observations/"), f["family"]


def test_photos_exist_only_for_families_the_catalogue_knows():
    photos = json.loads((ROOT / "src/aquaplot/data/guide_photos.json").read_text(encoding="utf-8"))["photos"]
    assert set(photos) <= {f.family for f in CATALOGUE}


def test_the_worker_keeps_the_photos_for_use_without_a_signal(client):
    js = client.get("/sw.js").text
    assert 'url.pathname.startsWith("/static/guide/")' in js  # each photo is kept once seen
    assert "cache-guide-photos" in js  # and the whole set can be fetched ahead of time
    assert 'path.startsWith("/static/guide/")' in js  # but nothing else can be fetched that way


def test_a_visitor_saving_data_is_not_sent_the_photos_unasked(client):
    page = client.get("/").text
    assert "navigator.connection.saveData" in page and "cache-guide-photos" in page
    assert 'img.loading = "lazy"' in page  # without the background download, photos load as groups open


def test_a_photo_ruled_out_by_hand_is_passed_over_for_the_next_one():
    results = [{"id": 1, "photos": [{}]}, {"id": 2, "photos": []}, {"id": 3, "photos": [{}]}]
    assert _fetcher().choose(results, skip={1})["id"] == 3


def test_photos_are_cut_to_a_small_square_webp():
    buf = io.BytesIO()
    Image.new("RGB", (640, 360), (40, 110, 120)).save(buf, "JPEG")
    out = Image.open(io.BytesIO(_fetcher().thumbnail(buf.getvalue())))
    assert out.format == "WEBP" and out.size == (200, 200)
