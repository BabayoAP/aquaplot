"""A public test with a paid model: a few live readings per tester, and the key never runs away."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from aquaplot import allowance
from aquaplot.app import RateLimiter, app
from aquaplot.assess import StreamAssessor
from aquaplot.observe import SampleReplay, StreamObservation
from aquaplot.store import Store

from test_assessment import FakeObserver

SCENE = StreamObservation(photo_kind="stream_scene", reasoning="clear water over gravel")


class PaidFake(FakeObserver):
    """Stands in for Claude: named like the paid backend, counts every call it would bill."""

    name = "claude"


def photo(shade: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (shade, 120, 90)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def paid(client):
    fake = PaidFake(SCENE)
    app.state.limiter = RateLimiter()  # the per-address rate limit is shared across tests; start clean
    app.state.store = Store(":memory:")
    app.state.assessor = StreamAssessor(observer=SampleReplay(fake))
    app.state.live_limits = allowance.LiveLimits(per_tester=2, per_network=10, per_day=40)
    yield client, fake
    app.state.live_limits = allowance.LiveLimits.from_env()


def check(client, tester="tester-a", shade=10, headers=None):
    return client.post("/api/assess", files=[("photos", ("stream.jpg", photo(shade), "image/jpeg"))],
                       data={"answers": json.dumps({"odour": "none"}), "taxa": json.dumps(["Gammaridae"])},
                       headers={"X-AquaPlot-Contributor": tester, **(headers or {})})


def test_a_tester_gets_two_live_readings_and_the_third_check_runs_by_hand(paid):
    client, fake = paid
    assert client.get("/api/live-readings", headers={"X-AquaPlot-Contributor": "tester-a"}).json()["left"] == 2
    first, second = check(client), check(client, shade=20)
    assert first.status_code == second.status_code == 200 and fake.calls == 2
    third = check(client, shade=30)
    assert third.status_code == 200  # the check still works
    assert fake.calls == 2  # but the model was not called, and nothing was billed
    body = third.json()
    assert body["observer"] == "none"
    assert "used the 2 live photo readings" in body["second_opinion"]["reason"]
    status = client.get("/api/live-readings", headers={"X-AquaPlot-Contributor": "tester-a"}).json()
    assert status["left"] == 0 and "each tester" in status["reason"]


def test_another_tester_still_has_their_own_readings(paid):
    client, fake = paid
    check(client), check(client, shade=20), check(client, shade=30)
    assert check(client, tester="tester-b", shade=40).json()["observer"] == "claude"
    assert fake.calls == 3


def test_the_sample_photos_never_use_a_reading(paid):
    client, fake = paid
    samples = client.get("/api/samples").json()["photos"]
    files = [("photos", (p["file"], client.get(p["url"]).content, "image/jpeg")) for p in samples]
    for _ in range(3):
        res = client.post("/api/assess", files=files, data={"taxa": json.dumps(["Perlidae"])},
                          headers={"X-AquaPlot-Contributor": "tester-a"})
        assert res.status_code == 200 and res.json()["observer"].endswith("recorded")
    assert fake.calls == 0
    assert client.get("/api/live-readings", headers={"X-AquaPlot-Contributor": "tester-a"}).json()["left"] == 2


def test_a_check_with_no_photos_uses_no_reading(paid):
    client, fake = paid
    res = client.post("/api/assess", data={"answers": json.dumps({"odour": "sewage"})},
                      headers={"X-AquaPlot-Contributor": "tester-a"})
    assert res.status_code == 200 and fake.calls == 0
    assert client.get("/api/live-readings", headers={"X-AquaPlot-Contributor": "tester-a"}).json()["used"] == 0


def test_the_daily_limit_holds_across_testers_whatever_id_they_send(paid):
    client, fake = paid
    app.state.live_limits = allowance.LiveLimits(per_tester=2, per_network=0, per_day=3)
    observers = [check(client, tester=f"fresh-id-{i}", shade=10 + i).json()["observer"] for i in range(5)]
    assert observers == ["claude", "claude", "claude", "none", "none"] and fake.calls == 3


def test_clearing_the_browser_does_not_buy_more_than_the_network_allows(paid):
    client, fake = paid
    app.state.live_limits = allowance.LiveLimits(per_tester=2, per_network=3, per_day=40)
    net = {"X-Forwarded-For": "203.0.113.7"}
    observers = [check(client, tester=f"new-browser-{i}", shade=10 + i, headers=net).json()["observer"] for i in range(4)]
    assert observers == ["claude", "claude", "claude", "none"]
    elsewhere = check(client, tester="someone-else", shade=90, headers={"X-Forwarded-For": "198.51.100.2"})
    assert elsewhere.json()["observer"] == "claude"


def test_counts_survive_a_restart(tmp_path):
    path = str(tmp_path / "aquaplot.db")
    limits = allowance.LiveLimits(per_tester=2).as_counts()
    store = Store(path)
    assert store.claim_live_reading("t", "n", "2026-09-30", limits)[0]
    assert store.claim_live_reading("t", "n", "2026-09-30", limits)[0]
    restarted = Store(path)
    granted, counts = restarted.claim_live_reading("t", "n", "2026-09-30", limits)
    assert not granted and counts["tester"] == 2


def test_zero_turns_a_limit_off(paid):
    client, fake = paid
    app.state.live_limits = allowance.LiveLimits(per_tester=0, per_network=0, per_day=0)
    for i in range(4):
        assert check(client, shade=10 + i).json()["observer"] == "claude"
    assert client.get("/api/live-readings", headers={"X-AquaPlot-Contributor": "tester-a"}).json()["left"] is None


def test_a_free_local_model_is_not_limited(client):
    app.state.limiter = RateLimiter()
    app.state.store = Store(":memory:")
    fake = FakeObserver(SCENE)  # named "fake": not a paid backend
    app.state.assessor = StreamAssessor(observer=SampleReplay(fake))
    app.state.live_limits = allowance.LiveLimits(per_tester=1, per_network=1, per_day=1)
    try:
        for i in range(3):
            assert check(client, shade=10 + i).status_code == 200
        assert fake.calls == 3
        assert client.get("/api/live-readings").json() == {"limited": False}
    finally:
        app.state.live_limits = allowance.LiveLimits.from_env()


def test_limits_are_read_from_the_environment():
    limits = allowance.LiveLimits.from_env({"AQUAPLOT_LIVE_PER_TESTER": "5", "AQUAPLOT_LIVE_PER_DAY": "0"})
    assert (limits.per_tester, limits.per_network, limits.per_day) == (5, 10, 0)


def test_the_check_page_says_how_many_readings_are_left(client):
    page = client.get("/").text
    assert 'api("/api/live-readings")' in page and "showLiveReadings();" in page
