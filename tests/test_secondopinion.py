"""The citizen identifies, the model double-checks. No network, no model."""

from aquaplot import bioindex
from aquaplot.assess import Review, StreamAssessor, Submission, reassess
from aquaplot.bioindex import TaxonObservation
from aquaplot.observe import NullObserver, SeenTaxon, StreamObservation
from aquaplot.secondopinion import compare

from test_assessment import COIMBRA, SCENE, FakeImage, FakeObserver


def mine(*names):
    return tuple(TaxonObservation(name=n, confirmed_by="citizen") for n in names)


def model(*pairs):
    return [TaxonObservation(name=n, confidence=c) for n, c in pairs]


def tray(*pairs):
    return StreamObservation(photo_kind="specimen", taxa=[SeenTaxon(name=n, confidence=c) for n, c in pairs])


async def citizen_run(names, *model_pairs, observer=None):
    obs = observer or FakeObserver(SCENE, tray(*model_pairs))
    return await StreamAssessor(observer=obs).assess(
        Submission(photos=(FakeImage(), FakeImage()), region=COIMBRA, taxa=mine(*names))
    )


# ---- the comparison ---------------------------------------------------------


def test_matching_identifications_are_agreement_not_questions():
    op = compare(mine("Heptageniidae", "Gammaridae"), model(("Heptageniidae", 0.9), ("Gammarus pulex", 0.8)), bioindex.score)
    assert len(op.agreed) == 2 and op.open == []


def test_an_order_level_model_answer_agrees_with_a_family_in_that_order():
    op = compare(mine("Perlidae"), model(("Plecoptera", 0.9)), bioindex.score)
    assert op.agreed and not op.open


def test_a_classic_confusion_comes_with_the_feature_that_separates_them():
    op = compare(mine("Perlidae", "Gammaridae"), model(("Heptageniidae", 0.8), ("Gammaridae", 0.9)), bioindex.score)
    [item] = op.open
    assert item["kind"] == "disagree"
    assert "tails" in item["how_to_tell"]
    assert item["citizen_label"].startswith("Stonefly") and item["model_label"].startswith("Mayfly")


def test_a_disagreement_that_would_change_the_band_is_asked_first():
    # Stonefly + bloodworm reads Moderate; mayfly (swimmer) + bloodworm reads Bad.
    op = compare(
        mine("Perlidae", "Chironomidae"),
        model(("Baetidae", 0.8), ("Chironomidae", 0.9), ("Asellidae", 0.6)),
        bioindex.score,
    )
    first = op.open[0]
    assert first["kind"] == "disagree" and first["changes_band"] and first["priority"] == 1
    assert first["band_if_model_right"] == "Bad"


def test_the_model_suggests_what_the_citizen_missed():
    op = compare(mine("Gammaridae"), model(("Gammaridae", 0.9), ("Hydropsychidae", 0.8)), bioindex.score)
    [item] = op.open
    assert item["kind"] == "model_only" and item["model_label"].startswith("Caddisfly")


def test_a_sensitive_family_the_model_could_not_find_is_worth_a_second_look():
    op = compare(mine("Perlidae", "Gammaridae"), model(("Gammaridae", 0.9)), bioindex.score)
    [item] = op.open
    assert item["kind"] == "unsupported"


def test_a_tolerant_family_the_model_missed_is_not_nagged_about():
    """Being wrong about one bloodworm does not move a band; asking would be noise."""
    op = compare(mine("Chironomidae", "Gammaridae"), model(("Gammaridae", 0.9)), bioindex.score)
    assert op.open == []


def test_a_guessing_model_gets_no_vote():
    op = compare(mine("Gammaridae"), model(("Gammaridae", 0.9), ("Perlidae", 0.3)), bioindex.score)
    assert op.open == []


def test_a_dismissed_item_stays_dismissed():
    first = compare(mine("Gammaridae"), model(("Gammaridae", 0.9), ("Hydropsychidae", 0.8)), bioindex.score)
    key = first.open[0]["key"]
    again = compare(mine("Gammaridae"), model(("Gammaridae", 0.9), ("Hydropsychidae", 0.8)), bioindex.score, dismissed=[key])
    assert again.open == [] and again.dismissed == [key]


# ---- inside the pipeline ------------------------------------------------------


async def test_when_the_citizen_identifies_their_list_is_what_gets_scored():
    a = await citizen_run(["Perlidae", "Gammaridae"], ("Chironomidae", 0.95), ("Oligochaeta", 0.9))
    names = {t.family for t in a.ecology.scored}
    assert names == {"Perlidae", "Gammaridae"}
    assert a.identified_by == "citizen"
    assert {i["check"] for i in a.needs_confirmation if i["kind"] == "second_opinion"} >= {"model_only"}


async def test_the_model_is_asked_blind():
    """Agreement is only evidence if the model never saw the citizen's answer."""
    seen = []

    class Spy(FakeObserver):
        async def observe(self, image, description, region):
            seen.append(description)
            return await super().observe(image, description, region)

    await citizen_run(["Perlidae"], ("Perlidae", 0.9), observer=Spy(SCENE, tray(("Perlidae", 0.9))))
    assert all("Perlidae" not in d for d in seen)


async def test_an_unsettled_decisive_disagreement_costs_certainty_and_says_so():
    agreed = await citizen_run(["Perlidae", "Chironomidae"], ("Perlidae", 0.9), ("Chironomidae", 0.9))
    disputed = await citizen_run(["Perlidae", "Chironomidae"], ("Baetidae", 0.9), ("Chironomidae", 0.9))
    assert disputed.certainty < agreed.certainty
    assert any("disagreed" in p for p in disputed.penalties)
    assert not any("disagreed" in p for p in agreed.penalties)


async def test_a_model_suggestion_that_is_a_listed_invasive_goes_first_but_is_not_counted():
    a = await citizen_run(["Gammaridae"], ("Gammaridae", 0.9), ("Procambarus clarkii", 0.85))
    first = a.second_opinion.open[0]
    assert first.get("invasive") and first["priority"] == 1
    assert a.invasives == []  # nothing enters the invasive check until a person says it was there


async def test_with_no_tray_photo_there_is_no_second_opinion_and_it_says_why():
    a = await StreamAssessor(observer=FakeObserver(SCENE)).assess(
        Submission(photos=(FakeImage(),), region=COIMBRA, taxa=mine("Gammaridae"))
    )
    assert not a.second_opinion.available and "tray" in a.second_opinion.reason


async def test_with_no_model_the_citizen_list_still_scores():
    a = await StreamAssessor(observer=NullObserver()).assess(Submission(region=COIMBRA, taxa=mine("Gammaridae", "Perlidae")))
    assert a.ecology.families == 2 and not a.second_opinion.available


async def test_keeping_your_own_answer_settles_the_question_without_calling_the_model():
    a = await citizen_run(["Perlidae", "Gammaridae"], ("Heptageniidae", 0.8), ("Gammaridae", 0.9))
    [item] = a.second_opinion.open
    after = await reassess(a.as_dict(), Review(dismissed=(item["key"],)))
    assert after.second_opinion.open == []
    assert {t.family for t in after.ecology.scored} == {"Perlidae", "Gammaridae"}


async def test_switching_to_the_models_answer_changes_the_score_and_closes_the_question():
    a = await citizen_run(["Perlidae", "Gammaridae"], ("Heptageniidae", 0.8), ("Gammaridae", 0.9))
    [item] = a.second_opinion.open
    after = await reassess(
        a.as_dict(), Review(rejected_taxa=(item["citizen_name"],), added_taxa=(item["model_name"],))
    )
    assert {t.family for t in after.ecology.scored} == {"Heptageniidae", "Gammaridae"}
    assert after.second_opinion.open == []
    assert after.supersedes == a.id


async def test_taking_the_models_answer_is_not_reported_as_independent_agreement():
    a = await citizen_run(["Perlidae", "Gammaridae"], ("Heptageniidae", 0.8), ("Gammaridae", 0.9))
    [item] = a.second_opinion.open
    after = await reassess(a.as_dict(), Review(rejected_taxa=(item["citizen_name"],), added_taxa=(item["model_name"],)))
    d = after.second_opinion.as_dict()
    assert len(d["agreed"]) == 2 and d["independent_agreements"] == 1


def test_a_group_level_answer_is_worded_the_way_a_person_says_it():
    op = compare(mine("Plecoptera"), model(("Baetidae", 0.8)), bioindex.score)
    assert "some kind of stonefly" in op.open[0]["question"]


# ---- over HTTP: the review, the report and the FHIR export all carry it -------


def test_the_second_opinion_survives_the_review_the_report_and_the_fhir_export(client):
    import json

    from aquaplot.app import app
    from aquaplot.store import Store

    from conftest import make_image

    app.state.store = Store(":memory:")
    app.state.assessor = StreamAssessor(observer=FakeObserver(SCENE, tray(("Baetidae", 0.8), ("Chironomidae", 0.9))))
    photos = [("photos", ("reach.jpg", make_image(), "image/jpeg")), ("photos", ("tray.jpg", make_image(), "image/jpeg"))]
    first = client.post("/api/assess", files=photos, data={"taxa": json.dumps(["Perlidae", "Chironomidae"])}).json()
    assert first["identified_by"] == "citizen"
    [item] = [q for q in first["needs_confirmation"] if q["kind"] == "second_opinion"]
    assert item["check"] == "disagree" and item["changes_band"]

    reviewed = client.post(f"/api/assess/{first['id']}/review", json={"dismissed": [item["key"]]}).json()
    assert reviewed["second_opinion"]["open"] == [] and reviewed["second_opinion"]["dismissed"] == [item["key"]]
    assert not any("disagreed" in p for p in reviewed["penalties"])

    md = client.get(f"/api/assess/{reviewed['id']}/report.md").text
    assert "Independent check" in md and "kept their own identification on 1" in md

    prov = [e["resource"] for e in client.get(f"/api/assess/{reviewed['id']}/fhir").json()["entry"] if e["resource"]["resourceType"] == "Provenance"][0]
    exts = {e["url"].rsplit("/", 1)[-1]: e for e in prov["extension"]}
    assert exts["taxa-identified-by"]["valueCode"] == "citizen"
    kept = {e["url"]: e["valueInteger"] for e in exts["model-second-opinion"]["extension"]}
    assert kept["keptOwn"] == 1 and kept["independentAgreements"] == 1
