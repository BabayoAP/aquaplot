"""OneAquaHealth interoperability: research sites, and the citizen app's own submission shape."""

import json

import pytest

from aquaplot import oah
from aquaplot.app import app
from aquaplot.assess import Assessment, StreamAssessor
from aquaplot.bioindex import TaxonObservation, score
from aquaplot.habitat import Reading
from aquaplot.habitat import assess as assess_habitat
from aquaplot.onehealth import Context, evaluate
from aquaplot.schema import Region
from aquaplot.store import Store

VALE_DAS_FLORES = (40.19307, -8.41945)  # OneAquaHealth research site C3, Coimbra


def check(answers, taxa=("Baetidae", "Leuctridae"), where=VALE_DAS_FLORES) -> Assessment:
    status = score([TaxonObservation(name=n, confidence=1.0, confirmed_by="citizen") for n in taxa])
    habitat = assess_habitat([Reading(key=k, value=v, source=s) for k, v, s in answers])
    return Assessment(
        id="abc",
        created_at="2026-09-27T10:00:00+00:00",
        site_name=None,
        region=Region(source="user", lat=where[0], lon=where[1]) if where else Region(source="none"),
        photos=0,
        photo_kinds=[],
        ecology=status,
        pressures=habitat,
        signal=evaluate(Context(status=status, habitat=habitat, invasives=(), site_name=None, warm_season=True)),
        invasives=[],
        certainty=50.0,
        penalties=[],
        needs_confirmation=[],
        observer="none",
        identified_by="citizen",
    )


def test_the_snapshot_holds_the_projects_research_sites_in_all_five_cities():
    sites = oah.research_sites()
    assert len(sites) >= 100
    assert {s.city for s in sites} == {"Benevento", "Coimbra", "Ghent", "Oslo", "Toulouse"}
    assert len({s.code for s in sites}) == len(sites)


def test_a_check_at_a_research_site_is_matched_to_it_and_one_elsewhere_is_not():
    site, distance = oah.research_site_at(*VALE_DAS_FLORES)
    assert site.code == "C3" and distance < 10
    assert oah.research_site_at(40.2111, -8.4291) is None  # Coimbra's centroid is not a stream reach
    assert oah.research_site_at(None, None) is None


def test_the_app_submission_uses_only_the_apps_own_answer_codes():
    a = check(
        [
            ("flow", "fast", "citizen"),
            ("substrate", "boulders_cobbles", "citizen"),
            ("bank_modification", "natural", "citizen"),
            ("riparian_vegetation", "continuous_natural", "citizen"),
            ("foam_or_sheen", "white_foam", "citizen"),
        ]
    )
    sub = oah.app_submission(a)
    body = sub["body"]
    assert sub["schema"] == "CitizenSubmissionPutDTO" and body["researchSite"] == "C3"
    assert body["waterFlow"] in oah.app_codes("water_flows")
    assert body["waterColor"] == "FO" and body["waterColor"] in oah.app_codes("water_colors")
    assert body["bottomChannelType"] in oah.app_codes("channel_types")
    assert body["banksChannelType"] in oah.app_codes("bank_types")
    assert set(body["habitats"]) <= set(oah.app_codes("habitats")) and "RF" in body["habitats"]
    assert body["overallAssessment"] in oah.app_codes("stream_assessments")
    assert body["isVegetationCoveredLeft"] is True and body["isVegetationCoveredRight"] is True
    assert all(c["from"] for c in sub["carried"])  # every field says where it came from


def test_an_answer_only_the_model_gave_is_not_carried_and_says_so():
    sub = oah.app_submission(check([("flow", "stagnant", "model"), ("water_clarity", "turbid", "citizen")]))
    assert "waterFlow" not in sub["body"]
    assert sub["body"]["waterColor"] == "MU"
    assert any("only the vision model gave" in n and "flow" in n for n in sub["not_carried"])


def test_away_from_a_research_site_it_targets_a_personal_site_and_explains_why():
    sub = oah.app_submission(check([("flow", "slow", "citizen")], where=(51.5, -0.12)))
    assert sub["schema"] == "CitizenSubmissionGeneratedSitePutDTO" and "researchSite" not in sub["body"]
    assert any("personal site" in n for n in sub["not_carried"])


def test_ambiguous_answers_are_listed_not_forced():
    sub = oah.app_submission(check([("bank_modification", "partly_reinforced", "citizen"), ("riparian_vegetation", "patchy", "citizen")]))
    assert "banksChannelType" not in sub["body"] and "isVegetationCoveredLeft" not in sub["body"]
    assert sum("partly reinforced" in n or "patchy" in n for n in sub["not_carried"]) == 2


def test_with_no_animals_the_overall_assessment_comes_from_the_visible_pressure():
    sub = oah.app_submission(check([("riparian_vegetation", "bare_or_paved", "citizen"), ("substrate", "concrete", "citizen")], taxa=()))
    assert sub["body"]["overallAssessment"] in {"MODERATE", "POOR"}
    assert "visual pressure" in next(c["from"] for c in sub["carried"] if c["field"] == "overallAssessment")


# ---- over HTTP ---------------------------------------------------------------


class NoModel:
    name = "none"

    async def observe(self, *args, **kwargs):  # pragma: no cover - never called without photos
        raise AssertionError


@pytest.fixture
def api(client):
    app.state.store = Store(":memory:")
    app.state.assessor = StreamAssessor(observer=NoModel())
    return client


def test_a_stored_check_exports_as_an_app_submission_and_names_its_research_site(api):
    res = api.post(
        "/api/assess",
        data={
            "lat": str(VALE_DAS_FLORES[0]),
            "lon": str(VALE_DAS_FLORES[1]),
            "answers": json.dumps({"flow": "fast", "water_clarity": "clear"}),
            "taxa": json.dumps(["Baetidae"]),
        },
    )
    assert res.status_code == 200
    assert res.json()["research_site"]["code"] == "C3"
    sub = api.get(f"/api/assess/{res.json()['id']}/oah-app").json()
    assert sub["body"]["waterFlow"] == "FAS" and sub["body"]["waterColor"] == "CL"
    bundle = api.get(f"/api/assess/{res.json()['id']}/fhir").json()
    assert "C3" in json.dumps(bundle)


def test_the_research_sites_are_served_for_the_map(api):
    body = api.get("/api/oah/sites").json()
    assert len(body["sites"]) >= 100 and body["match_radius_m"] == oah.MATCH_RADIUS_M
