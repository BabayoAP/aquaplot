"""The sample check: recorded model readings for the bundled photos, labelled as recordings."""

import io
import json
from pathlib import Path

from PIL import Image

from aquaplot.assess import StreamAssessor, Submission
from aquaplot.inputs import decode_image
from aquaplot.observe import (
    NullObserver,
    RecordedObservation,
    SampleReplay,
    StreamObservation,
    load_samples,
    select_observer,
)

from test_assessment import COIMBRA, SCENE, FakeObserver
from test_secondopinion import mine

SAMPLES = Path(__file__).parent.parent / "src" / "aquaplot" / "static" / "samples"


def sample_bytes(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


def recompressed(name: str) -> bytes:
    """What a phone or a messaging app does to a photo on the way: smaller, re-encoded."""
    img = Image.open(SAMPLES / name).convert("RGB")
    img = img.resize((img.width * 2 // 3, img.height * 2 // 3))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def test_every_recording_fits_the_schema_the_live_model_answers_in():
    for s in load_samples().samples:
        StreamObservation.model_validate(s.observation)
        assert (SAMPLES / s.file).exists() and s.credit and s.licence and s.source


async def test_a_sample_photo_is_answered_from_its_recording_even_after_recompression():
    replay = SampleReplay(NullObserver())
    for raw in (sample_bytes("tray.jpg"), recompressed("tray.jpg")):
        seen = await replay.observe(decode_image(raw).image, "", COIMBRA)
        assert isinstance(seen, RecordedObservation)
        assert seen.sample == "tray.jpg" and seen.taxa[0].name == "Heptageniidae"


async def test_any_other_photo_goes_to_the_live_observer():
    from conftest import make_image

    live = FakeObserver(SCENE)
    seen = await SampleReplay(live).observe(decode_image(make_image()).image, "", COIMBRA)
    assert seen is SCENE and not isinstance(seen, RecordedObservation)


def test_every_backend_is_wrapped_and_keeps_its_own_name():
    observer = select_observer({"AQUAPLOT_OBSERVER": "none"})
    assert isinstance(observer, SampleReplay) and observer.name == "none"


async def test_the_sample_check_gets_a_second_opinion_with_no_model_configured():
    photos = tuple(decode_image(sample_bytes(f)) for f in ("reach.jpg", "tray.jpg"))
    result = await StreamAssessor(observer=SampleReplay(NullObserver())).assess(
        Submission(photos=photos, region=COIMBRA, taxa=mine("Perlidae"))
    )
    assert result.second_opinion.available
    [item] = [q for q in result.needs_confirmation if q["kind"] == "second_opinion"]
    assert "Stonefly" in item["question"] and "Mayfly" in item["question"]
    # Labelled as a recording wherever the observer is shown.
    assert result.observer == "claude-opus-5-5, recorded"
    assert "recorded from claude-opus-5-5" in result.model_notes[0] and "not read live" in result.model_notes[0]
    # The reach recording fills the habitat form, still as the model's unconfirmed answers.
    assert result.pressures.value("riparian_vegetation") == "continuous_natural"
    assert all(r.source == "model" for r in result.pressures.readings)


async def test_a_sample_mixed_with_a_live_photo_names_both_observers():
    from conftest import make_image

    photos = (decode_image(make_image()), decode_image(sample_bytes("tray.jpg")))
    result = await StreamAssessor(observer=SampleReplay(FakeObserver(SCENE))).assess(
        Submission(photos=photos, region=COIMBRA, taxa=mine("Heptageniidae"))
    )
    assert result.observer == "fake and claude-opus-5-5, recorded"


def test_the_sample_set_is_served_with_its_credits(client):
    body = client.get("/api/samples").json()
    assert {p["file"] for p in body["photos"]} == {"reach.jpg", "tray.jpg"}
    assert all(p["licence"] and p["credit"] for p in body["photos"])
    assert body["location"]["lat"] and "not taken there" in body["location"]["explanation"]
    assert client.get(body["photos"][0]["url"]).status_code == 200
    json.dumps(body)


def test_the_two_minute_path_leads_with_the_problem_and_one_link_into_the_sample(client):
    about = client.get("/about")
    assert about.status_code == 200 and "The problem." in about.text and 'href="/try"' in about.text
    hop = client.get("/try", follow_redirects=False)
    assert hop.status_code == 307 and hop.headers["location"] == "/?sample=1"
    assert "?sample" in client.get("/").text or "has(\"sample\")" in client.get("/").text
