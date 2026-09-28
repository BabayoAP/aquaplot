"""The assessment pipeline, the review loop, the store and the HTTP surface. No network, no model."""

import json

import pytest
from fastapi.testclient import TestClient

from aquaplot.app import app
from aquaplot.assess import Review, StreamAssessor, Submission, reassess, warm_season
from aquaplot.bioindex import TaxonObservation
from aquaplot.habitat import Reading
from aquaplot.observe import HabitatCall, SeenTaxon, StreamObservation
from aquaplot.schema import PlaceRef, Region
from aquaplot.store import Store, longest_run, site_key, trend_of

from conftest import make_image

COIMBRA = Region(
    source="user",
    lat=40.2111,
    lon=-8.4291,
    place=PlaceRef(id=7, name="Coimbra", display_name="Coimbra, PT", kind="municipality"),
    country=PlaceRef(id=1, name="PT", display_name="Portugal", kind="country"),
)

SCENE = StreamObservation(
    photo_kind="stream_scene",
    reasoning="Concrete channel, green tint, litter on the margin.",
    habitat=[
        HabitatCall(key="water_clarity", value="turbid", confidence=0.8),
        HabitatCall(key="algae", value="bloom", confidence=0.55),
        HabitatCall(key="bank_modification", value="fully_channelised", confidence=0.9),
        HabitatCall(key="flow", value="stagnant", confidence=0.85),
        HabitatCall(key="litter", value="heavy", confidence=0.9),
        HabitatCall(key="access", value="contact", confidence=0.6),
    ],
    cannot_tell=["substrate"],
)
TRAY = StreamObservation(
    photo_kind="specimen",
    reasoning="Red worms and midge larvae; one red crayfish.",
    taxa=[
        SeenTaxon(name="Chironomidae", confidence=0.85, count=20),
        SeenTaxon(name="Oligochaeta", confidence=0.7, count=8),
        SeenTaxon(name="Asellidae", confidence=0.5, count=3),
        SeenTaxon(name="Procambarus clarkii", rank="species", confidence=0.9, count=1),
    ],
)


class FakeObserver:
    """Returns canned observations, one per photo, without ever touching a model."""

    name = "fake"

    def __init__(self, *observations, error=None):
        self.observations = list(observations)
        self.error = error
        self.calls = 0

    async def observe(self, image, description, region):
        self.calls += 1
        if self.error:
            raise self.error
        return self.observations[min(self.calls - 1, len(self.observations) - 1)]


class FakeImage:
    image = None
    gps = None


async def run(observer=None, **kw):
    submission = Submission(**{"photos": (FakeImage(), FakeImage()), "region": COIMBRA, **kw})
    return await StreamAssessor(observer=observer or FakeObserver(SCENE, TRAY)).assess(submission)


# ---- the pipeline ---------------------------------------------------------


async def test_photos_become_a_band_a_pressure_score_and_a_one_health_read_out():
    a = await run(site_name="Ribeira da Fonte")
    d = a.as_dict()
    assert d["band"] == "Bad"
    assert d["pressures"]["band"] == "severe"
    assert d["one_health"]["overall"] in ("concern", "alert")
    assert d["one_health"]["headline"].startswith("Ribeira da Fonte")
    assert d["ecology"]["families"] >= 3


async def test_the_pipeline_works_with_no_model_at_all():
    """No API key, no local model: a citizen who fills the form by hand still gets everything."""
    from aquaplot.observe import NullObserver

    a = await StreamAssessor(observer=NullObserver()).assess(
        Submission(
            region=COIMBRA,
            answers=(Reading(key="algae", value="bloom", source="citizen"), Reading(key="odour", value="sewage", source="citizen")),
            taxa=(TaxonObservation(name="Chironomidae", confirmed_by="citizen"),),
        )
    )
    assert a.signal.findings and a.ecology.families == 1
    assert a.observer == "none"
    assert any("no photo was submitted" in p for p in a.penalties)


async def test_a_citizen_answer_beats_the_model_for_the_same_question():
    a = await run(answers=(Reading(key="algae", value="none", source="citizen"),))
    assert a.pressures.value("algae") == "none"
    assert "human.cyanobacteria" not in {f.rule for f in a.signal.findings}


async def test_a_photo_that_is_not_a_stream_is_ignored_and_said_so():
    observer = FakeObserver(StreamObservation(photo_kind="not_a_stream", reasoning="this is a cat"))
    a = await run(observer=observer)
    assert any("not of a stream" in p for p in a.penalties)
    assert a.pressures.answered == 0


async def test_a_model_failure_degrades_instead_of_failing_the_request():
    from aquaplot.identify import IdentifyError

    a = await run(observer=FakeObserver(error=IdentifyError("model down")))
    assert any("could not be read by the vision model" in p for p in a.penalties)
    assert a.ecology.families == 0


async def test_listed_invasive_species_are_flagged_with_the_jurisdiction_that_lists_them():
    a = await run()
    assert [i.listed.scientific_name for i in a.invasives] == ["Procambarus clarkii"]
    hit = a.invasives[0].as_dict()
    assert "European Union" in hit["scope"] and hit["habitat"] == "freshwater"
    assert "crayfish plague" in hit["why_it_matters"]
    assert "animal.invasive_species" in {f.rule for f in a.signal.findings}


async def test_certainty_falls_when_the_evidence_is_thinner():
    full = await run()
    unlocated = await run(**{"region": Region(source="none")})
    assert unlocated.certainty < full.certainty
    assert any("no location was recorded" in p for p in unlocated.penalties)


async def test_every_certainty_penalty_is_a_sentence_a_person_can_read():
    a = await run()
    assert a.penalties
    for p in a.penalties:
        assert len(p.split()) >= 4 and p == p.strip()


def test_warm_season_flips_with_the_hemisphere():
    from datetime import UTC, datetime

    july = datetime(2026, 7, 1, tzinfo=UTC)
    assert warm_season(40.0, july) and not warm_season(-33.0, july)


# ---- the human half of the loop -------------------------------------------


async def test_the_confirmation_queue_asks_first_for_what_is_holding_an_alert_back():
    a = await run()
    queue = a.needs_confirmation
    assert queue
    top = queue[0]
    assert top["priority"] == 1 and top["kind"] == "habitat"
    assert "holding a health finding below alert level" in top["why_it_matters"]
    assert {q["key"] for q in queue if q["priority"] == 1} <= {"algae", "litter", "flow", "odour", "water_colour", "foam_or_sheen"}


async def test_the_person_only_question_is_always_on_the_queue():
    a = await run()
    assert "odour" in {q["key"] for q in a.needs_confirmation}


async def test_confirming_an_observation_raises_the_finding_it_was_holding_back():
    a = await run()
    before = next(f for f in a.signal.findings if f.rule == "human.cyanobacteria")
    assert before.level.value == "concern" and not before.confirmed

    after = await reassess(a.as_dict(), Review(answers=(Reading(key="algae", value="bloom", source="citizen"),)))
    raised = next(f for f in after.signal.findings if f.rule == "human.cyanobacteria")
    assert raised.level.value == "alert" and raised.confirmed
    assert after.confirmations > a.confirmations


async def test_rejecting_an_identification_removes_it_from_the_index():
    a = await run()
    before = a.ecology.families
    after = await reassess(a.as_dict(), Review(rejected_taxa=("Asellidae",)))
    assert after.ecology.families == before - 1
    assert "Asellidae" not in {t.family for t in after.ecology.scored}


async def test_a_review_never_calls_the_model_again():
    """A second model pass could overwrite the correction a person just made."""
    observer = FakeObserver(SCENE, TRAY)
    a = await StreamAssessor(observer=observer).assess(Submission(photos=(FakeImage(),), region=COIMBRA))
    calls = observer.calls
    await reassess(a.as_dict(), Review(confirmed_taxa=("Chironomidae",)))
    assert observer.calls == calls


async def test_adding_a_species_the_model_missed_changes_the_band():
    a = await run()
    better = await reassess(a.as_dict(), Review(added_taxa=("Perlidae", "Heptageniidae", "Leptoceridae")))
    assert better.ecology.band.rank < a.ecology.band.rank  # rank 0 is High
    assert better.ecology.ept_families == 3


# ---- the store ------------------------------------------------------------


def test_nearby_visits_join_the_same_site():
    assert site_key(40.21110, -8.42910) == site_key(40.21115, -8.42905)
    assert site_key(40.2111, -8.4291) != site_key(40.2199, -8.4291)
    assert site_key(None, None) is None


def test_longest_run_counts_consecutive_months():
    assert longest_run(["2026-01", "2026-02", "2026-03", "2026-06"]) == 3
    assert longest_run([]) == 0


def test_trend_reads_the_direction_of_the_last_two_visits():
    assert trend_of([{"band_ordinal": 2, "band": "Poor"}])["direction"] == "new"
    assert trend_of([{"band_ordinal": 2, "band": "Poor"}, {"band_ordinal": 4, "band": "Good"}])["direction"] == "declining"
    assert trend_of([{"band_ordinal": 4, "band": "Good"}, {"band_ordinal": 2, "band": "Poor"}])["direction"] == "improving"


async def test_a_second_visit_turns_a_reading_into_a_trend():
    store = Store(":memory:")
    store.save(await run(site_name="Ribeira da Fonte"), contributor="anon-1")
    assert store.sites()[0]["trend"]["direction"] == "new"

    healthier = FakeObserver(
        SCENE,
        StreamObservation(
            photo_kind="specimen",
            taxa=[SeenTaxon(name=n, confidence=0.9) for n in ("Perlidae", "Heptageniidae", "Leptoceridae", "Goeridae", "Gammaridae")],
        ),
    )
    store.save(await run(observer=healthier, site_name="Ribeira da Fonte"), contributor="anon-1")

    sites = store.sites()
    assert len(sites) == 1 and sites[0]["assessments"] == 2
    assert sites[0]["trend"]["direction"] == "improving"
    assert sites[0]["name"] == "Ribeira da Fonte"


async def test_a_review_replaces_a_visit_rather_than_inventing_one():
    """Otherwise the most careful volunteers would manufacture trends by checking the model's work."""
    store = Store(":memory:")
    first = await run(site_name="Ribeira da Fonte")
    store.save(first, contributor="anon-1")
    reviewed = await reassess(first.as_dict(), Review(confirmed_taxa=("Chironomidae",)))
    assert reviewed.supersedes == first.id
    store.save(reviewed, contributor="anon-1")

    site = store.sites()[0]
    assert site["assessments"] == 1 and site["trend"]["direction"] == "new"
    assert store.history(site["site_key"])[0]["id"] == reviewed.id
    # The superseded version stays fetchable: it is the record of what the model
    # said before a person corrected it.
    assert store.get(first.id)["id"] == first.id


async def test_badges_reward_returning_and_reviewing_not_volume():
    store = Store(":memory:")
    a = await run()
    store.save(a, contributor="anon-1")
    progress = store.progress("anon-1")
    assert {b["key"] for b in progress["badges"]} >= {"first-check", "sentinel"}
    assert progress["next"] is not None

    store.save(await run(), contributor="anon-1")  # a genuine second visit to the same spot
    assert "returner" in {b["key"] for b in store.progress("anon-1")["badges"]}
    assert store.progress("unknown-person")["assessments"] == 0


async def test_the_alert_feed_shows_a_site_as_it_is_now_not_as_it_was():
    store = Store(":memory:")
    bad = await run()
    store.save(bad)
    assert len(store.alerts()) == 1

    restored = await reassess(
        bad.as_dict(),
        Review(
            answers=tuple(
                Reading(key=k, value=v, source="citizen")
                for k, v in [
                    ("algae", "none"),
                    ("flow", "fast"),
                    ("litter", "none"),
                    ("water_clarity", "clear"),
                    ("bank_modification", "natural"),
                    ("riparian_vegetation", "continuous_natural"),
                    ("shade", "shaded"),
                    ("sediment_deposit", "none"),
                    ("odour", "none"),
                ]
            ),
            added_taxa=("Perlidae", "Heptageniidae", "Leptoceridae", "Goeridae", "Gammaridae"),
            rejected_taxa=("Chironomidae", "Oligochaeta", "Asellidae"),
        ),
    )
    store.save(restored)
    assert restored.ecology.band.value in ("High", "Good")

    feed = store.alerts()
    assert len(feed) == 1  # one row per site, and it is the current one
    assert feed[0]["id"] == restored.id and feed[0]["level"] == "concern"
    # The water is clean again; what is left is the crayfish, which does not wash away.
    assert {f["rule"] for f in feed[0]["findings"]} == {"animal.invasive_species"}


async def test_the_summary_counts_what_the_dashboard_shows():
    store = Store(":memory:")
    store.save(await run(), contributor="anon-1")
    summary = store.summary()
    assert summary["assessments"] == 1 and summary["sites"] == 1 and summary["contributors"] == 1
    assert summary["by_band"] and summary["by_month"]


async def test_a_check_with_no_coordinates_is_not_counted_as_a_place_on_the_ground():
    """The dashboard's site count has to agree with the map and the table under it.

    A reading with no coordinates is real and still counted as an assessment, but
    it is not somewhere anyone can go back to, so it is not a site.
    """
    store = Store(":memory:")
    store.save(await run(), contributor="anon-1")
    store.save(await run(region=Region(source="none")), contributor="anon-1")

    summary = store.summary()
    assert summary["assessments"] == 2
    assert summary["sites"] == 1 == len(store.sites())


async def test_the_alert_feed_leaves_out_readings_that_have_no_site():
    """Every unlocated reading shares one key, so admitting them would collapse
    them into a single nameless row and drop all but the newest."""
    store = Store(":memory:")
    store.save(await run(region=Region(source="none")), contributor="anon-1")
    store.save(await run(region=Region(source="none")), contributor="anon-2")

    assert store.alerts() == []
    assert store.summary()["assessments"] == 2  # still stored, still counted, still exported


# ---- HTTP -----------------------------------------------------------------


@pytest.fixture
def api(client):
    app.state.store = Store(":memory:")
    app.state.assessor = StreamAssessor(observer=FakeObserver(SCENE, TRAY))
    return client


def test_assess_endpoint_accepts_photos_answers_and_species(api):
    res = api.post(
        "/api/assess",
        files=[("photos", ("scene.jpg", make_image(), "image/jpeg")), ("photos", ("tray.jpg", make_image(), "image/jpeg"))],
        data={
            "site_name": "Ribeira da Fonte",
            "lat": "40.2111",
            "lon": "-8.4291",
            "answers": json.dumps({"odour": "sewage"}),
            "taxa": json.dumps(["Gammaridae"]),
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["band"] and body["one_health"]["headline"]
    assert body["pressures"]["readings"]
    assert any(t["name"] == "Gammaridae" and t["confirmed"] for t in body["ecology"]["taxa"])


def test_an_empty_submission_is_rejected_with_a_useful_message(api):
    res = api.post("/api/assess", data={})
    assert res.status_code == 422 and "at least a photo" in res.json()["detail"]


def test_unknown_habitat_keys_are_rejected_rather_than_silently_ignored(api):
    res = api.post("/api/assess", data={"answers": json.dumps({"vibes": "good"})})
    assert res.status_code == 422 and "vibes" in res.json()["detail"]


def test_an_assessment_can_be_fetched_reviewed_and_exported_as_fhir(api):
    created = api.post(
        "/api/assess",
        files=[("photos", ("scene.jpg", make_image(), "image/jpeg"))],
        data={"lat": "40.2111", "lon": "-8.4291"},
    ).json()

    assert api.get(f"/api/assess/{created['id']}").json()["id"] == created["id"]
    assert api.get("/api/assess/nope").status_code == 404

    reviewed = api.post(f"/api/assess/{created['id']}/review", json={"answers": {"algae": "bloom"}}).json()
    assert reviewed["id"] != created["id"]
    assert reviewed["confirmations"] > created["confirmations"]

    bundle = api.get(f"/api/assess/{reviewed['id']}/fhir").json()
    assert bundle["resourceType"] == "Bundle"
    assert any(e["resource"]["resourceType"] == "Flag" for e in bundle["entry"])


def test_sites_insights_and_alerts_reflect_what_was_stored(api):
    api.post("/api/assess", data={"lat": "40.2111", "lon": "-8.4291", "answers": json.dumps({"odour": "sewage"})})
    sites = api.get("/api/sites").json()["sites"]
    assert len(sites) == 1
    assert api.get("/api/sites", params={"south": 0, "west": 0, "north": 1, "east": 1}).json()["sites"] == []
    assert api.get("/api/sites", params={"south": 0}).status_code == 422

    history = api.get(f"/api/sites/{sites[0]['site_key']}").json()
    assert history["assessments"] and history["trend"]["direction"] == "new"
    assert api.post(f"/api/sites/{sites[0]['site_key']}/name", json={"name": "Our brook"}).json()["name"] == "Our brook"
    assert api.get("/api/sites").json()["sites"][0]["name"] == "Our brook"

    assert api.get("/api/insights").json()["assessments"] == 1
    assert api.get("/api/alerts").json()["alerts"]


def test_progress_is_anonymous_and_opt_in(api):
    api.post("/api/assess", data={"lat": "40.2", "lon": "-8.4", "taxa": json.dumps(["Gammaridae"])},
             headers={"X-AquaPlot-Contributor": "anon-42"})
    assert api.get("/api/me/progress").json()["assessments"] == 0  # no header, no record
    mine = api.get("/api/me/progress", headers={"X-AquaPlot-Contributor": "anon-42"}).json()
    assert mine["assessments"] == 1 and mine["badges"]


def test_reference_endpoints_drive_the_interface(api):
    form = api.get("/api/form").json()
    assert {i["key"] for i in form["indicators"]} >= {"water_clarity", "algae", "odour", "access"}
    assert any(i["photo_visible"] is False for i in form["indicators"])

    guide = api.get("/api/guide").json()
    assert guide["families"][0]["bmwp"] == 10 and guide["families"][0]["look_for"]

    pilots = api.get("/api/pilots").json()["sites"]
    assert {p["city"] for p in pilots} == {"Coimbra", "Benevento", "Ghent", "Oslo", "Toulouse"}


def test_health_reports_every_version_that_shaped_a_result(api):
    body = api.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["observer"] == "fake"
    assert body["bioindicator_catalogue"] and body["habitat_form"] and body["status_seed"]


async def test_a_model_that_declines_to_guess_turns_its_declines_into_questions():
    """'I cannot tell from this photo' is correct behaviour, and the answer must not be lost."""
    shy = FakeObserver(
        StreamObservation(
            photo_kind="stream_scene",
            reasoning="Taken from too far away to judge anything.",
            cannot_tell=["water_clarity", "algae", "substrate", "not_a_real_key"],
        )
    )
    a = await run(observer=shy)
    assert any("could not judge 3 indicator" in p for p in a.penalties)
    asked = {q["key"] for q in a.needs_confirmation}
    assert {"water_clarity", "algae", "substrate"} <= asked
    assert "not_a_real_key" not in asked
    declined = next(q for q in a.needs_confirmation if q["key"] == "substrate")
    assert declined["why_it_matters"].startswith("The model looked and could not tell")
