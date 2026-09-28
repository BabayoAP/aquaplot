"""Stages 3 and 4 and the certainty rule (PRD §6.3, §6.4, FR-8, §9). No network."""

import pytest
from fastapi.testclient import TestClient

from aquaplot.app import app
from aquaplot.area import AreaService
from aquaplot.identify import Candidate, Identification, IdentifyError, NullIdentifier, OllamaIdentifier
from aquaplot.inat import InatClient
from aquaplot.places import PlaceResolver
from aquaplot.pipeline import Pipeline
from aquaplot.schema import Classification, Label, Regime, PlaceRef, Region
from aquaplot.status import StatusResolver

from conftest import make_image

OC_REF = PlaceRef(id=2738, name="Orange County", display_name="Orange County, US, CA", kind="county or province")
US_REF = PlaceRef(id=1, name="US", display_name="United States", kind="country")
IRVINE = Region(source="exif", lat=33.68, lon=-117.83, place=OC_REF, country=US_REF, chain=["Orange County, US, CA"])
SAN_DIEGO = Region(source="user", lat=32.7, lon=-117.2)  # coordinates known, place never resolved
NOWHERE = Region(source="none")


def taxon(id_, name, common, iconic="Plantae", rank="species"):
    return {"id": id_, "name": name, "preferred_common_name": common, "rank": rank, "iconic_taxon_name": iconic,
            "observations_count": 100, "default_photo": {"square_url": f"https://img/{id_}.jpg"}}


TAXA = {
    "Cortaderia selloana": taxon(64240, "Cortaderia selloana", "Pampas Grass"),
    "Cenchrus setaceus": taxon(430581, "Cenchrus setaceus", "Fountain Grass"),
    "Pennisetum setaceum": taxon(430581, "Cenchrus setaceus", "Fountain Grass"),  # iNaturalist resolves the synonym
    "Artemisia californica": taxon(53357, "Artemisia californica", "California Sagebrush"),
    "Leersia oryzoides": taxon(64177, "Leersia oryzoides", "Rice Cutgrass"),
    "Zosterops simplex": taxon(1289467, "Zosterops simplex", "Swinhoe's White-eye", "Aves"),
    "Mysterium": taxon(999, "Mysterium", None, rank="genus"),
}
OC = {"id": 2738, "display_name": "Orange County, US, CA", "admin_level": 20}
CA = {"id": 14, "display_name": "California, US", "admin_level": 10}
USA = {"id": 1, "display_name": "United States", "admin_level": 0}
ESTABLISHMENT = {
    53357: ("native", OC),
    64177: ("native", CA),
    1289467: ("introduced", USA),
    999: (None, None),
}
NEARBY = {"results": {"standard": [
    {"id": 1, "name": "US", "display_name": "United States", "admin_level": 0},
    {"id": 14, "name": "California", "display_name": "California, US", "admin_level": 10},
    {"id": 2738, "name": "Orange County", "display_name": "Orange County, US, CA", "admin_level": 20},
]}}


async def fake_inat(path, params):
    if path == "/places/nearby":
        return NEARBY
    if path == "/taxa":
        hit = TAXA.get(params["q"])
        return {"results": [hit] if hit else []}
    if path.startswith("/taxa/"):
        tid = int(path.split("/")[-1])
        means, place = ESTABLISHMENT.get(tid, ("introduced", OC))
        em = {"establishment_means": means, "place": place} if means else None
        return {"results": [{"id": tid, "establishment_means": em}]}
    raise AssertionError(path)


async def fake_inat_without_places(path, params):
    """iNaturalist up, but the point falls outside every standard place it knows."""
    if path == "/places/nearby":
        return {"results": {"standard": []}}
    return await fake_inat(path, params)


class FakeIdentifier:
    name = "fake"

    def __init__(self, *candidates, framing="close_up", error=None, box=()):
        self.candidates = list(candidates)
        self.framing = framing
        self.error = error
        self.box = list(box)
        self.calls = []

    async def identify(self, image, description, region):
        self.calls.append((image is not None, description, region.source))
        if self.error:
            raise IdentifyError(self.error)
        return Identification(candidates=self.candidates, framing=self.framing, subject_box=self.box, reasoning="test")


class SequencedIdentifier:
    """Answers one scripted Identification per call, recording the image it was given (Stage 2 tests)."""

    name = "fake"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.images = []

    async def identify(self, image, description, region):
        self.images.append(image)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make_pipeline(*candidates, **kw):
    inat = InatClient(fetch=fake_inat)
    return Pipeline(identifier=FakeIdentifier(*candidates, **kw), status=StatusResolver(inat), places=PlaceResolver(inat))


# ---- status resolution ----------------------------------------------------


async def test_seed_listed_taxon_is_invasive():
    r = await StatusResolver(InatClient(fetch=fake_inat)).resolve("Cortaderia selloana")
    assert r.label == Label.INVASIVE and r.confidence == 0.95 and r.source == "Cal-IPC Inventory"
    assert r.taxon.id == 64240


async def test_native_in_orange_county_is_native_at_full_confidence():
    r = await StatusResolver(InatClient(fetch=fake_inat)).resolve("Artemisia californica")
    assert r.label == Label.NATIVE and r.confidence == 0.9 and r.note is None
    assert r.place == "Orange County, US, CA"


async def test_status_from_coarser_place_is_less_certain_and_says_so():
    """The observer stood in a county; iNaturalist only knows the answer for the state. Say so."""
    inat = InatClient(fetch=fake_inat)
    here = await PlaceResolver(inat).locate(33.68, -117.83)
    r = await StatusResolver(inat).resolve("Leersia oryzoides", here)
    assert r.label == Label.NATIVE and r.confidence == 0.8
    assert "California" in r.note and "broader than Orange County" in r.note
    r = await StatusResolver(inat).resolve("Zosterops simplex", here)
    assert r.label == Label.NATURALIZED and r.confidence == 0.7  # answered only at country level
    assert "United States" in r.note


async def test_unknown_taxon_and_missing_record_fall_to_neutral():
    r = await StatusResolver(InatClient(fetch=fake_inat)).resolve("Nonexistus fakeus")
    assert r.label == Label.NATURALIZED and r.taxon is None and "not a known" in r.note
    r = await StatusResolver(InatClient(fetch=fake_inat)).resolve("Mysterium")
    assert r.label == Label.NATURALIZED and r.confidence == 0.35 and "no establishment record" in r.note


async def test_seed_matches_synonym_and_inaturalist_accepted_name():
    # The Cal-IPC list says Pennisetum setaceum, iNaturalist says Cenchrus setaceus. Both must be Invasive.
    r = await StatusResolver(InatClient(fetch=fake_inat)).resolve("Pennisetum setaceum")
    assert r.label == Label.INVASIVE and r.taxon.scientific_name == "Cenchrus setaceus"
    r = await StatusResolver(InatClient(fetch=fake_inat)).resolve("Cenchrus setaceus")
    assert r.label == Label.INVASIVE and r.source == "Cal-IPC Inventory"


async def test_inaturalist_outage_degrades_instead_of_failing():
    from aquaplot.inat import InatError

    async def down(path, params):
        raise InatError("iNaturalist request failed: 503")

    resolver = StatusResolver(InatClient(fetch=down))
    r = await resolver.resolve("Cortaderia selloana")  # the seed list answers offline
    assert r.label == Label.INVASIVE and r.taxon is None
    r = await resolver.resolve("Artemisia californica")
    assert r.label == Label.NATURALIZED and r.confidence == 0.35 and "unavailable" in r.note
    p = Pipeline(identifier=FakeIdentifier(Candidate(scientific_name="Artemisia californica", confidence=0.9)), status=resolver)
    c = await p.classify(None, "grey shrub", IRVINE)  # PRD §5.2: species ID with a caveat, not an error
    assert c.top_candidate.scientific_name == "Artemisia californica" and any("unavailable" in s for s in c.evidence.certainty_penalties)


# ---- Stage 2: detect, crop, identify again (PRD §6.2) ---------------------


def big_image():
    from aquaplot.inputs import decode_image

    return decode_image(make_image(size=(800, 600)))


async def test_small_subject_is_cropped_and_reidentified():
    whole = Identification(candidates=[Candidate(scientific_name="Cortaderia selloana", confidence=0.4)], framing="far", subject_box=[0.4, 0.3, 0.6, 0.5])
    crop = Identification(candidates=[Candidate(scientific_name="Cortaderia selloana", confidence=0.9)], framing="close_up", reasoning="plumes")
    ident = SequencedIdentifier(whole, crop)
    p = Pipeline(identifier=ident, status=StatusResolver(InatClient(fetch=fake_inat)))
    c = await p.classify(big_image(), "", IRVINE)
    assert len(ident.images) == 2
    assert ident.images[1].size[0] < 800 and ident.images[1].size[1] < 600  # the second look is a crop
    assert c.evidence.identified_from_crop is True and c.evidence.subject_box == [0.4, 0.3, 0.6, 0.5]
    assert c.top_candidate.confidence == 0.9 and c.regime == Regime.FAR  # framing describes the photo, not the crop
    assert c.evidence.reasoning == "plumes"


async def test_frame_filling_subject_is_not_cropped():
    whole = Identification(candidates=[Candidate(scientific_name="Cortaderia selloana", confidence=0.8)], framing="close_up", subject_box=[0.05, 0.05, 0.95, 0.95])
    ident = SequencedIdentifier(whole)
    c = await Pipeline(identifier=ident, status=StatusResolver(InatClient(fetch=fake_inat))).classify(big_image(), "", IRVINE)
    assert len(ident.images) == 1 and c.evidence.identified_from_crop is False
    assert c.evidence.subject_box == [0.05, 0.05, 0.95, 0.95]


async def test_crop_that_does_not_help_is_discarded():
    whole = Identification(candidates=[Candidate(scientific_name="Cortaderia selloana", confidence=0.7)], framing="mid_distance", subject_box=[0.1, 0.1, 0.4, 0.4])
    crop = Identification(candidates=[Candidate(scientific_name="Arundo donax", confidence=0.5)], framing="close_up")
    ident = SequencedIdentifier(whole, crop)
    c = await Pipeline(identifier=ident, status=StatusResolver(InatClient(fetch=fake_inat))).classify(big_image(), "", IRVINE)
    assert len(ident.images) == 2 and c.evidence.identified_from_crop is False
    assert c.top_candidate.scientific_name == "Cortaderia selloana"


async def test_crop_failure_keeps_whole_frame_answer():
    whole = Identification(candidates=[Candidate(scientific_name="Cortaderia selloana", confidence=0.7)], framing="far", subject_box=[0.1, 0.1, 0.3, 0.3])
    ident = SequencedIdentifier(whole, IdentifyError("timeout"))
    c = await Pipeline(identifier=ident, status=StatusResolver(InatClient(fetch=fake_inat))).classify(big_image(), "", IRVINE)
    assert c.label == Label.INVASIVE and c.evidence.identified_from_crop is False


def test_malformed_boxes_are_ignored():
    assert Identification(subject_box=[0.1, 0.1, 0.5]).box() is None
    assert Identification(subject_box=[0.1, 0.1, 1.5, 0.5]).box() is None
    assert Identification(subject_box=[0.5, 0.5, 0.5, 0.5]).box() is None
    assert Identification(subject_box=[0.1, 0.2, 0.3, 0.4]).box() == (0.1, 0.2, 0.3, 0.4)


def test_crop_to_box_pads_and_clamps():
    from PIL import Image

    from aquaplot.pipeline import crop_to_box

    img = Image.new("RGB", (1000, 500))
    assert crop_to_box(img, (0.4, 0.4, 0.6, 0.6), margin=0.0).size == (201, 101)
    assert crop_to_box(img, (0.0, 0.0, 0.2, 0.2), margin=0.5).size == (301, 151)  # padding clamped at the edge


# ---- certainty rule -------------------------------------------------------


async def test_distant_framing_lowers_certainty_and_says_so():
    p = make_pipeline(Candidate(scientific_name="Cortaderia selloana", confidence=0.9), framing="far")
    c = await p.classify(big_image(), "", IRVINE)
    assert c.regime == Regime.FAR
    assert c.certainty == pytest.approx(100 * 0.9 * 0.95 * 0.85, abs=0.1)
    assert any("far range" in s for s in c.evidence.certainty_penalties)


# ---- region refinement (places.py) -----------------------------------------


SQUARE = {"type": "Polygon", "coordinates": [[[-118.0, 33.5], [-117.5, 33.5], [-117.5, 33.9], [-118.0, 33.9], [-118.0, 33.5]]]}


async def fake_places(path, params):
    """iNaturalist /places/nearby: the administrative chain containing a point."""
    assert path == "/places/nearby"
    return {
        "results": {
            "standard": [
                {"id": 1, "name": "US", "display_name": "United States", "admin_level": 0},
                {"id": 14, "name": "California", "display_name": "California, US", "admin_level": 10},
                {"id": 2738, "name": "Orange County", "display_name": "Orange County, US, CA", "admin_level": 20},
            ]
        }
    }


async def test_coordinates_resolve_to_the_most_specific_place():
    """FR-6: the jurisdiction a status question is asked of comes from the coordinates."""
    from aquaplot.places import PlaceResolver

    resolver = PlaceResolver(InatClient(fetch=fake_places))
    refined = await resolver.refine(Region(source="user", lat=33.45, lon=-118.1))
    assert refined.place is not None
    assert refined.place.display_name == "Orange County, US, CA"  # county beats state beats country
    assert refined.country is not None and refined.country.display_name == "United States"
    assert refined.chain[0] == "Orange County, US, CA"


async def test_place_lookup_is_skipped_without_coordinates():
    from aquaplot.places import PlaceResolver

    assert (await PlaceResolver(InatClient(fetch=fake_places)).refine(NOWHERE)).place is None


async def test_place_lookup_failure_never_fails_the_classification():
    """A place lookup can only improve the answer, so its failure must degrade, not raise."""
    from aquaplot.inat import InatError
    from aquaplot.places import PlaceResolver

    async def down(path, params):
        if path == "/places/nearby":
            raise InatError("503")
        return await fake_inat(path, params)

    resolver = PlaceResolver(InatClient(fetch=down))
    region = Region(source="user", lat=33.45, lon=-118.1)
    assert (await resolver.refine(region)).place is None
    p = Pipeline(
        identifier=FakeIdentifier(Candidate(scientific_name="Artemisia californica", confidence=1.0)),
        status=StatusResolver(InatClient(fetch=down)),
        places=resolver,
    )
    c = await p.classify(None, "shrub", region)
    assert any("could not be resolved to an administrative place" in s for s in c.evidence.certainty_penalties)


async def test_photo_in_county_of_listed_invasive():
    p = make_pipeline(Candidate(scientific_name="Cortaderia selloana", confidence=0.9))
    from aquaplot.inputs import decode_image

    c = await p.classify(decode_image(make_image()), "", IRVINE)
    assert c.label == Label.INVASIVE
    assert c.certainty == pytest.approx(100 * 0.9 * 0.95, abs=0.1)
    assert c.top_candidate.taxon_id == 64240 and c.top_candidate.inat_url.endswith("/64240")
    assert c.regime == Regime.CLOSE_UP and c.evidence.identifier == "fake"
    assert c.evidence.status_source == "Cal-IPC Inventory" and c.evidence.establishment == "introduced"
    assert c.evidence.certainty_penalties == []


async def test_unresolvable_place_and_text_input_stack_penalties():
    """Every weakness in the evidence must show up as its own sentence and its own factor."""
    inat = InatClient(fetch=fake_inat_without_places)
    p = Pipeline(
        identifier=FakeIdentifier(Candidate(scientific_name="Artemisia californica", confidence=0.5)),
        status=StatusResolver(inat),
        places=PlaceResolver(inat),
    )
    c = await p.classify(None, "grey aromatic shrub", SAN_DIEGO)
    assert c.input_kind == "text" and c.label == Label.NATIVE
    assert c.certainty == pytest.approx(100 * 0.5 * 0.9 * 0.8 * 0.7, abs=0.1)
    joined = " ".join(c.evidence.certainty_penalties)
    assert "could not be resolved to an administrative place" in joined and "text-only" in joined and "unsure" in joined


async def test_no_location_at_all_is_penalised_and_said_so():
    p = make_pipeline(Candidate(scientific_name="Artemisia californica", confidence=1.0))
    from aquaplot.inputs import decode_image

    c = await p.classify(decode_image(make_image()), "", NOWHERE)
    assert c.certainty == pytest.approx(100 * 0.9 * 0.85, abs=0.1)
    assert any("no location was available" in s for s in c.evidence.certainty_penalties)


async def test_genus_level_answer_is_flagged():
    p = make_pipeline(Candidate(scientific_name="Mysterium", rank="genus", confidence=0.8))
    c = await p.classify(None, "something", IRVINE)
    assert c.top_candidate.rank == "genus"
    assert any("genus level" in s for s in c.evidence.certainty_penalties)


async def test_model_failure_still_returns_a_label():
    p = make_pipeline(error="Ollama request failed: timeout")
    c = await p.classify(None, "a shrub", IRVINE)
    assert c.label == Label.NATURALIZED and c.certainty == 0.0 and c.top_candidate is None
    assert any("species model failed" in s for s in c.evidence.certainty_penalties)


async def test_null_identifier_is_the_m0_placeholder():
    p = Pipeline(identifier=NullIdentifier(), status=StatusResolver(InatClient(fetch=fake_inat)))
    c = await p.classify(None, "a shrub", IRVINE)
    assert c.label == Label.NATURALIZED and c.certainty == 0.0 and c.evidence.identifier == "none"
    assert "no species model configured" in c.evidence.certainty_penalties[0]


async def test_identifier_gets_image_description_and_region():
    ident = FakeIdentifier(Candidate(scientific_name="Artemisia californica", confidence=0.9))
    p = Pipeline(identifier=ident, status=StatusResolver(InatClient(fetch=fake_inat)))
    from aquaplot.inputs import decode_image

    await p.classify(decode_image(make_image()), "grey shrub", IRVINE)
    assert ident.calls == [(True, "grey shrub", "exif")]


# ---- Ollama backend (fake HTTP) --------------------------------------------


async def test_ollama_backend_parses_structured_reply():
    seen = {}

    async def post(path, body):
        seen.update(path=path, body=body)
        return {"message": {"content": '{"candidates": [{"scientific_name": "Cortaderia selloana", "confidence": 0.7}], "framing": "far", "reasoning": "plumes"}'}}

    ident = OllamaIdentifier(model="qwen2.5vl:3b", post=post)
    from aquaplot.inputs import decode_image

    out = await ident.identify(decode_image(make_image()).image, "tall grass", IRVINE)
    assert out.candidates[0].scientific_name == "Cortaderia selloana" and out.framing == "far"
    assert seen["path"] == "/api/chat" and seen["body"]["model"] == "qwen2.5vl:3b"
    assert seen["body"]["messages"][1]["images"] and "Orange County, US, CA" in seen["body"]["messages"][1]["content"]
    assert seen["body"]["format"]["type"] == "object"


async def test_ollama_backend_rejects_garbage():
    async def post(path, body):
        return {"message": {"content": "I think it's a plant"}}

    with pytest.raises(IdentifyError, match="malformed"):
        await OllamaIdentifier(model="x", post=post).identify(None, "plant", IRVINE)


async def test_a_non_json_reply_from_ollama_costs_a_photo_not_the_whole_check(monkeypatch):
    """A 200 carrying HTML - a captive portal or a proxy - must not escape as a 500.

    Every other Ollama failure arrives as an IdentifyError, which the assessor
    turns into a named penalty and carries on. A raw decode error would end a
    citizen's check with no reading at all.
    """
    import httpx

    from aquaplot import identify

    real_client = httpx.AsyncClient  # captured before the patch: identify.httpx is the module itself

    def portal(*args, **kwargs):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<html>sign in</html>"))
        return real_client(transport=transport)

    monkeypatch.setattr(identify.httpx, "AsyncClient", portal)
    with pytest.raises(IdentifyError, match="not JSON"):
        await identify.ollama_post("/api/chat", {})


def test_identifier_selection_is_overridable(monkeypatch):
    from aquaplot.identify import ClaudeIdentifier, select_identifier

    monkeypatch.setattr("aquaplot.identify.detect_ollama_vision_model", lambda: "qwen2.5vl:3b")
    assert select_identifier({"AQUAPLOT_IDENTIFIER": "none"}).name == "none"
    assert select_identifier({"AQUAPLOT_IDENTIFIER": "ollama", "OLLAMA_MODEL": "llava:7b"}).model == "llava:7b"
    assert select_identifier({}).name == "ollama"  # auto-detected local model
    claude = select_identifier({"ANTHROPIC_API_KEY": "sk-test", "CLAUDE_MODEL": "claude-sonnet-5"})
    assert isinstance(claude, ClaudeIdentifier) and claude.model == "claude-sonnet-5"
    monkeypatch.setattr("aquaplot.identify.detect_ollama_vision_model", lambda: None)
    assert select_identifier({}).name == "none"


# ---- HTTP ------------------------------------------------------------------


@pytest.fixture
def client():
    app.state.area = AreaService(fetch=fake_inat)
    app.state.pipeline = make_pipeline(Candidate(scientific_name="Cortaderia selloana", common_name="Pampas Grass", confidence=0.85))
    return TestClient(app)


def test_end_to_end_image_classification(client):
    res = client.post("/api/classify", files={"image": ("x.jpg", make_image(gps=(33.68, -117.83)), "image/jpeg")})
    assert res.status_code == 200
    c = Classification.model_validate(res.json())
    assert c.label == Label.INVASIVE and c.certainty > 70
    assert c.top_candidate.common_name == "Pampas Grass"
    assert res.json()["evidence"]["identifier"] == "fake"


def test_health_names_the_identifier(client):
    assert client.get("/api/health").json()["identifier"] == "fake"


def test_map_taxon_filter_is_passed_upstream(client):
    calls = []

    async def spy(path, params):
        calls.append(params)
        return {"results": [], "total_results": 0}

    app.state.area = AreaService(fetch=spy)
    res = client.get("/api/area/observations", params={"place_id": 2738, "taxon_id": 64240})
    assert res.status_code == 200 and calls[-1]["taxon_id"] == 64240
