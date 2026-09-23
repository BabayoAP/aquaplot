"""M0 acceptance: input flows through the single-page app and a full contract comes back."""

import pytest

from riffle.schema import Classification, Label

from conftest import make_image

IRVINE = (33.6846, -117.8265)


def test_index_serves_the_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "SpeciesGuard" in res.text
    assert 'capture="environment"' in res.text  # phone camera input (PRD §5.0)


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_empty_request_is_rejected(client):
    res = client.post("/api/classify", data={"description": "   "})
    assert res.status_code == 422


def test_bad_image_is_a_400_not_a_crash(client):
    res = client.post("/api/classify", files={"image": ("x.jpg", b"garbage", "image/jpeg")})
    assert res.status_code == 400
    assert "decode" in res.json()["detail"]


def test_image_returns_full_contract_with_exif_region(client):
    res = client.post("/api/classify", files={"image": ("x.jpg", make_image(gps=IRVINE), "image/jpeg")})
    assert res.status_code == 200
    result = Classification.model_validate(res.json())
    assert result.input_kind == "image"
    assert result.label in set(Label)  # FR-8: always one of the three labels
    assert 0 <= result.certainty <= 100
    assert result.region.source == "exif" and (result.region.lat, result.region.lon) == pytest.approx(IRVINE, abs=1e-4)
    assert any("no species model" in p for p in result.evidence.certainty_penalties)  # must say why certainty is 0


def test_image_wins_over_description_when_both_sent(client):
    res = client.post(
        "/api/classify",
        files={"image": ("x.png", make_image("PNG"), "image/png")},
        data={"description": "a shrub", "lat": "32.7157", "lon": "-117.1611"},
    )
    result = Classification.model_validate(res.json())
    assert result.input_kind == "image"
    assert result.region.source == "user" and result.region.place is None


def test_text_fallback_is_flagged_lower_confidence(client):
    res = client.post("/api/classify", data={"description": "yellow pea-like flowers on spiny stems"})
    assert res.status_code == 200
    result = Classification.model_validate(res.json())
    assert result.input_kind == "text"
    assert result.region.source == "none"
    assert any("lower confidence" in p for p in result.evidence.certainty_penalties)
    assert any("no location was available" in p for p in result.evidence.certainty_penalties)


def test_empty_file_part_falls_through_to_description(client):
    # Browsers send an empty file field when the picker was left untouched.
    res = client.post(
        "/api/classify",
        files={"image": ("", b"", "application/octet-stream")},
        data={"description": "a beetle"},
    )
    assert res.status_code == 200
    assert res.json()["input_kind"] == "text"


def test_classify_is_rate_limited_per_client(client):
    from riffle.app import RateLimiter, app

    app.state.limiter = RateLimiter(limit=2)
    try:
        assert client.post("/api/classify", data={"description": "   "}).status_code == 422  # rejected before it counts
        for _ in range(2):
            assert client.post("/api/classify", data={"description": "a beetle"}).status_code == 200
        res = client.post("/api/classify", data={"description": "a beetle"})
        assert res.status_code == 429 and "Retry-After" in res.headers
        assert "try again" in res.json()["detail"]
    finally:
        app.state.limiter = RateLimiter()


def test_rate_limiter_window_slides():
    from riffle.app import RateLimiter

    rl = RateLimiter(limit=1, window=10)
    assert rl.retry_after("a", now=0) == 0
    assert rl.retry_after("a", now=4) == pytest.approx(6)
    assert rl.retry_after("b", now=4) == 0  # another client is independent
    assert rl.retry_after("a", now=10.1) == 0
    assert RateLimiter(limit=0).retry_after("a", now=0) == 0  # disabled
