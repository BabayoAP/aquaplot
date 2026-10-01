"""A browser's own Claude key (the Developers page): its checks get a live reading, and the key goes nowhere else."""

from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from aquaplot import allowance
from aquaplot.app import RateLimiter, app
from aquaplot.assess import StreamAssessor
from aquaplot.observe import NullObserver, SampleReplay, claude_client
from aquaplot.store import Store

from test_live_readings import SCENE, PaidFake, check

KEY = "sk-ant-test-" + "k" * 24
HEADERS = {"X-AquaPlot-Claude-Key": KEY}


def rejected(status: int, cls: type[anthropic.APIStatusError]) -> anthropic.APIStatusError:
    request = httpx2.Request("GET", "https://api.anthropic.com/v1/models/claude-opus-5-5")
    return cls("rejected", response=httpx2.Response(status, request=request), body=None)


class FakeClaude:
    """Stands in for an Anthropic client on one key: answers with a canned reading, bills nothing."""

    def __init__(self, key: str, error: Exception | None = None):
        self.key = key
        self.error = error
        self.calls: list[object] = []
        self.closed = False
        self.messages = SimpleNamespace(parse=self._parse)
        self.models = SimpleNamespace(retrieve=self._retrieve)

    async def _parse(self, **request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason="end_turn", parsed_output=SCENE)

    async def close(self):
        self.closed = True

    async def _retrieve(self, model):
        self.calls.append(model)
        if self.error:
            raise self.error
        return SimpleNamespace(id=model)


class Clients(list):
    """Every client the app builds for a browser's key, in order. Set ``error`` to make Anthropic refuse."""

    error: Exception | None = None


@pytest.fixture
def clients():
    made = Clients()

    def build(key):
        made.append(FakeClaude(key, made.error))
        return made[-1]

    app.state.claude_client = build
    yield made
    app.state.claude_client = claude_client


@pytest.fixture
def no_model(client, clients):
    """A server with no vision model of its own, like the public demo without a key."""
    app.state.limiter = RateLimiter()
    app.state.key_check_limiter = RateLimiter(limit=10)
    app.state.store = Store(":memory:")
    app.state.assessor = StreamAssessor(observer=SampleReplay(NullObserver()))
    return client, clients


@pytest.fixture
def paid(client, clients):
    """A server paying for its own Claude key, with two live readings per tester."""
    fake = PaidFake(SCENE)
    app.state.limiter = RateLimiter()
    app.state.store = Store(":memory:")
    app.state.assessor = StreamAssessor(observer=SampleReplay(fake))
    app.state.live_limits = allowance.LiveLimits(per_tester=2, per_network=10, per_day=40)
    yield client, clients, fake
    app.state.live_limits = allowance.LiveLimits.from_env()


def test_a_browser_with_its_own_key_gets_a_claude_reading_on_a_server_with_no_model(no_model):
    client, clients = no_model
    res = check(client, headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["observer"] == "claude"
    assert [c.key for c in clients] == [KEY] and len(clients[0].calls) == 1  # one photo, one request, on that key


def test_a_check_without_a_key_still_runs_by_hand(no_model):
    client, clients = no_model
    assert check(client).json()["observer"] == "none"
    assert clients == []


def test_the_key_is_never_stored_or_returned(no_model):
    client, _ = no_model
    res = check(client, headers=HEADERS)
    assert KEY not in res.text
    assessment = res.json()["id"]
    for path in (f"/api/assess/{assessment}", f"/api/assess/{assessment}/fhir", f"/api/assess/{assessment}/report",
                 "/api/export.csv", "/api/export.geojson"):
        assert KEY not in client.get(path).text, path


def test_a_key_anthropic_rejects_leaves_the_check_running_by_hand_and_saying_why(no_model):
    client, clients = no_model
    clients.error = rejected(401, anthropic.AuthenticationError)
    res = check(client, headers=HEADERS)
    assert res.status_code == 200  # never a 4xx: the outbox would drop a check somebody walked to a stream for
    body = res.json()
    assert any("could not be read by the vision model" in p for p in body["penalties"])
    assert KEY not in res.text


def test_checks_on_a_browsers_own_key_use_none_of_the_servers_live_readings(paid):
    client, clients, server_model = paid
    for shade in (10, 20, 30):
        assert check(client, shade=shade, headers=HEADERS).json()["observer"] == "claude"
    assert server_model.calls == 0 and len(clients) == 3
    assert client.get("/api/live-readings", headers={"X-AquaPlot-Contributor": "tester-a"}).json()["left"] == 2


def test_a_tester_whose_readings_are_spent_can_still_use_their_own_key(paid):
    client, clients, _ = paid
    check(client), check(client, shade=20)
    assert check(client, shade=30).json()["observer"] == "none"  # the server's readings are spent
    assert check(client, shade=40, headers=HEADERS).json()["observer"] == "claude"
    assert len(clients) == 1


def test_the_sample_photos_replay_their_recording_even_with_a_key(no_model):
    client, clients = no_model
    samples = client.get("/api/samples").json()["photos"]
    files = [("photos", (p["file"], client.get(p["url"]).content, "image/jpeg")) for p in samples]
    res = client.post("/api/assess", files=files, data={"taxa": json.dumps(["Perlidae"])}, headers=HEADERS)
    assert res.json()["observer"].endswith("recorded")
    assert all(c.calls == [] for c in clients)  # the key was never asked to read them


def test_a_saved_key_can_be_checked_before_a_check_depends_on_it(no_model):
    client, clients = no_model
    res = client.post("/api/claude-key/check", headers=HEADERS)
    assert res.status_code == 200
    assert res.json() == {"ok": True, "model": app.state.claude_model}
    assert clients[0].calls == [app.state.claude_model]  # a model lookup, which costs nothing


@pytest.mark.parametrize(
    ("status", "error", "says"),
    [
        (401, anthropic.AuthenticationError, "did not accept this key"),
        (403, anthropic.PermissionDeniedError, "not allowed to use"),
        (404, anthropic.NotFoundError, "cannot see the model"),
        (529, anthropic.InternalServerError, "answered with an error (529)"),
    ],
)
def test_a_key_that_will_not_work_is_explained_in_plain_words(no_model, status, error, says):
    client, clients = no_model
    clients.error = rejected(status, error)
    res = client.post("/api/claude-key/check", headers=HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False and says in body["reason"]
    assert KEY not in res.text


def test_each_client_built_for_a_key_is_closed_when_its_request_ends(no_model):
    client, clients = no_model
    check(client, headers=HEADERS)
    client.post("/api/claude-key/check", headers=HEADERS)
    clients.error = rejected(401, anthropic.AuthenticationError)
    check(client, shade=20, headers=HEADERS)
    client.post("/api/claude-key/check", headers=HEADERS)
    assert len(clients) == 4 and all(c.closed for c in clients)


def test_the_server_is_not_a_free_tester_for_other_peoples_keys(no_model):
    client, clients = no_model
    for n in range(10):
        assert client.post("/api/claude-key/check", headers={"X-AquaPlot-Claude-Key": f"{KEY}{n}"}).status_code == 200
    res = client.post("/api/claude-key/check", headers=HEADERS)
    assert res.status_code == 429 and "Retry-After" in res.headers
    assert len(clients) == 10  # the eleventh never reached Anthropic


def test_checking_a_key_needs_a_key(no_model):
    client, clients = no_model
    assert client.post("/api/claude-key/check").status_code == 422
    assert clients == []


def test_the_developers_page_is_reachable_from_the_check_page(client):
    assert client.get("/developers").status_code == 200
    assert 'href="/developers"' in client.get("/").text
