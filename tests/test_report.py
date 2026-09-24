"""The authority report and the data exports: the two ways a reading leaves the app."""

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from aquaplot import report
from aquaplot.app import app
from aquaplot.assess import StreamAssessor, Submission
from aquaplot.bioindex import TaxonObservation
from aquaplot.habitat import Reading
from aquaplot.onehealth import Level
from aquaplot.schema import PlaceRef, Region
from aquaplot.store import Store, haversine_m

from test_assessment import COIMBRA, SCENE, TRAY, FakeImage, FakeObserver


async def build(**kw):
    submission = Submission(**{"photos": (FakeImage(), FakeImage()), "region": COIMBRA, **kw})
    return await StreamAssessor(observer=FakeObserver(SCENE, TRAY)).assess(submission)


# ---- the report -----------------------------------------------------------


async def test_the_report_leads_with_what_is_being_asked_for():
    """An officer triages on the request, not on the findings, so the request comes first."""
    a = await build(site_name="Ribeira da Fonte", answers=(Reading(key="odour", value="sewage", source="citizen"),))
    md = report.markdown(a)
    body = md.split("\n")
    assert body[0].startswith("# Watercourse condition report — Ribeira da Fonte")
    assert body[2].startswith("**Requesting")
    assert md.index("Requesting") < md.index("## Biological condition")


async def test_a_clean_stream_still_produces_a_baseline_report():
    a = await StreamAssessor(observer=FakeObserver(SCENE)).assess(
        Submission(
            region=COIMBRA,
            answers=tuple(Reading(key=k, value=v, source="citizen") for k, v in [("algae", "none"), ("flow", "fast")]),
            taxa=tuple(TaxonObservation(name=n, confirmed_by="citizen") for n in
                       ["Perlidae", "Heptageniidae", "Leptoceridae", "Goeridae", "Gammaridae", "Elmidae"]),
        )
    )
    md = report.markdown(a)
    assert "For your records" in md and "baseline" in md
    assert "No finding at concern level or above" in md


async def test_the_report_attributes_every_observation_to_a_person_or_a_model():
    """An agency is entitled to know which half of the evidence had eyes on it."""
    a = await build(answers=(Reading(key="odour", value="sewage", source="citizen"),))
    md = report.markdown(a)
    assert "| model |" in md and "| citizen |" in md  # habitat table
    assert "model, unconfirmed" in md  # taxon table
    assert f"confirmed on site by the observer: **{a.confirmations}**" in md


async def test_the_report_states_its_own_limits_rather_than_footnoting_them():
    a = await build()
    md = report.markdown(a)
    assert "Screening estimate" in md
    assert "not a medical, water-quality or regulatory determination" in md
    assert "Stated limitations of this assessment" in md
    for penalty in a.penalties:
        assert penalty in md


async def test_the_report_carries_the_series_when_a_site_has_one():
    a = await build(site_name="Ribeira da Fonte")
    history = [
        {"created_at": "2026-08-01T10:00:00+00:00", "band": "Good", "pressure": 12.0, "overall_level": "ok"},
        {"created_at": "2026-07-01T10:00:00+00:00", "band": "High", "pressure": 5.0, "overall_level": "ok"},
    ]
    md = report.markdown(a, history)
    assert "## Previous assessments at this site" in md
    assert "2026-08-01" in md and "stronger evidence than any single visit" in md
    assert "## Previous assessments" not in report.markdown(a, history[:1])  # one visit is not a series


async def test_the_band_name_is_not_printed_twice():
    a = await build()
    assert f"**Screening class:** {a.ecology.band.value} — {a.ecology.band.value}" not in report.markdown(a)


async def test_the_printable_page_is_self_contained_and_escapes_its_content():
    a = await build(site_name='Brook <script>alert(1)</script> & co')
    page = report.printable(a)
    assert page.startswith("<!doctype html>") and "</html>" in page
    assert "<style>" in page and "http-equiv" not in page
    assert "<script>alert(1)</script>" not in page.replace("<\\/script>", "")
    assert "&lt;script&gt;" in page
    assert "window.print()" in page  # the toolbar still works


# ---- exports --------------------------------------------------------------


@pytest.fixture
def api(client):
    app.state.store = Store(":memory:")
    app.state.assessor = StreamAssessor(observer=FakeObserver(SCENE, TRAY))
    return client


def _seed(api, lat="40.2111", lon="-8.4291", name="Ribeira da Fonte"):
    return api.post("/api/assess", data={"lat": lat, "lon": lon, "site_name": name,
                                         "answers": json.dumps({"odour": "sewage"})}).json()


def test_report_endpoints_serve_html_and_markdown(api):
    created = _seed(api)
    page = api.get(f"/api/assess/{created['id']}/report")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "Watercourse condition report" in page.text

    md = api.get(f"/api/assess/{created['id']}/report.md")
    assert md.status_code == 200
    assert "markdown" in md.headers["content-type"]
    assert "attachment" in md.headers["content-disposition"]
    assert md.text.startswith("# Watercourse condition report")

    assert api.get("/api/assess/nope/report").status_code == 404
    assert api.get("/api/assess/nope/report.md").status_code == 404


def test_csv_export_is_one_row_per_live_assessment(api):
    _seed(api)
    res = api.get("/api/export.csv")
    assert res.status_code == 200 and "csv" in res.headers["content-type"]
    rows = list(csv.DictReader(io.StringIO(res.text)))
    assert len(rows) == 1
    assert rows[0]["band"] and rows[0]["site_name"] == "Ribeira da Fonte"
    # Derived indices are rounded: full float precision is noise that reads as accuracy.
    assert len(rows[0]["pressure"].split(".")[-1]) <= 1


def test_geojson_export_is_one_feature_per_site_with_its_trend(api):
    _seed(api)
    fc = api.get("/api/export.geojson").json()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 1
    feature = fc["features"][0]
    assert feature["geometry"]["coordinates"] == [-8.4291, 40.2111]  # GeoJSON is lon, lat
    assert feature["properties"]["trend"] == "new"
    assert "Screening estimates" in fc["properties"]["caveat"]


def test_exports_are_empty_but_valid_before_anything_is_recorded(api):
    assert list(csv.DictReader(io.StringIO(api.get("/api/export.csv").text))) == []
    assert api.get("/api/export.geojson").json()["features"] == []


# ---- returning to a site --------------------------------------------------


def test_nearby_finds_a_site_you_already_monitor(api):
    _seed(api)
    # Four metres along the bank: the same stretch, by any sensible reading.
    near = api.get("/api/sites/nearby", params={"lat": 40.21114, "lon": -8.42912}).json()["nearby"]
    assert len(near) == 1
    assert near[0]["name"] == "Ribeira da Fonte" and near[0]["metres_away"] <= 10
    assert near[0]["assessments"] == 1 and near[0]["band"]


def test_nearby_does_not_reach_across_the_catchment(api):
    _seed(api)
    assert api.get("/api/sites/nearby", params={"lat": 40.2300, "lon": -8.4291}).json()["nearby"] == []
    assert api.get("/api/sites/nearby", params={"lat": 40.2300, "lon": -8.4291, "radius_m": 5000}).json()["nearby"]


def test_nearby_rejects_impossible_coordinates(api):
    assert api.get("/api/sites/nearby", params={"lat": 200, "lon": 0}).status_code == 422
    assert api.get("/api/sites/nearby", params={"lat": 0, "lon": 0, "radius_m": 99999}).status_code == 422


def test_nearby_route_is_not_shadowed_by_the_site_key_route(api):
    """/api/sites/nearby must be declared before /api/sites/{site_key} or it becomes a site lookup."""
    assert api.get("/api/sites/nearby", params={"lat": 0, "lon": 0}).status_code == 200


def test_distance_is_measured_on_a_sphere_not_a_grid():
    assert haversine_m(40.2111, -8.4291, 40.2111, -8.4291) == 0
    assert 95 < haversine_m(40.2111, -8.4291, 40.2120, -8.4291) < 105
    # A degree of longitude is much shorter near the pole than at the equator.
    assert haversine_m(0, 0, 0, 1) > haversine_m(60, 0, 60, 1) * 1.9


# ---- the field-app surfaces -----------------------------------------------


def test_the_service_worker_is_served_from_the_root_with_a_root_scope(api):
    """A worker served from /static could only ever control /static."""
    res = api.get("/sw.js")
    assert res.status_code == 200
    assert res.headers["service-worker-allowed"] == "/"
    assert "javascript" in res.headers["content-type"]
    assert "no-cache" in res.headers["cache-control"]  # a stale worker is very hard to dislodge


def test_the_worker_caches_what_a_whole_assessment_needs_offline(api):
    js = api.get("/sw.js").text
    for path in ("/api/form", "/api/guide"):
        assert path in js  # the questions and the identification guide
    assert 'request.method !== "GET"' in js  # writes belong to the outbox, not the worker


def test_the_app_is_installable(api):
    manifest = api.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    body = manifest.json()
    assert body["start_url"] == "/" and body["display"] == "standalone" and body["icons"]
    assert api.get("/icon.svg").status_code == 200
    assert "<svg" in api.get("/icon.svg").text


def test_the_check_page_registers_the_worker_and_owns_an_outbox(api):
    page = api.get("/").text
    assert 'navigator.serviceWorker.register("/sw.js")' in page
    assert 'rel="manifest"' in page
    assert "queueSubmission" in page and "flushOutbox" in page
    assert 'window.addEventListener("online"' in page


def test_the_site_history_page_is_served_for_any_key(api):
    page = api.get("/site/40.211,-8.429")
    assert page.status_code == 200
    assert "Ecological class over time" in page.text
    assert "Every visit" in page.text


def test_the_field_guide_is_served_as_a_printable_page_and_as_markdown(api):
    """It is product, not only documentation: a river-day group needs paper."""
    page = api.get("/field-guide")
    assert page.status_code == 200
    assert "<h1>How to check a stream</h1>" in page.text
    assert "window.print()" in page.text
    for section in ("Safety", "Choosing a spot", "Take a sample", "Put everything back"):
        assert section in page.text

    raw = api.get("/api/field-guide.md")
    assert raw.status_code == 200 and "markdown" in raw.headers["content-type"]
    assert raw.text.startswith("# How to check a stream")
    assert len(raw.text.split()) > 800  # a stub would pass every other assertion here


def test_the_field_guide_is_reachable_from_the_step_that_needs_it(api):
    page = api.get("/").text
    assert page.count('href="/field-guide"') >= 2  # the nav, and the photograph step
