"""The weather either side of a visit: context for the rules, the early warning, never a precondition."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from aquaplot import fhir
from aquaplot.assess import Review, StreamAssessor, Submission, reassess
from aquaplot.bioindex import TaxonObservation
from aquaplot.habitat import Reading
from aquaplot.observe import NullObserver
from aquaplot.onehealth import Level, evaluate
from aquaplot.weather import Weather, WeatherError, WeatherResolver, summarise

from test_assessment import COIMBRA
from test_onehealth import CLEAN, context, rules

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)

WET = Weather(rain_past_48h_mm=24.5, rain_next_48h_mm=0.0, max_temp_next_48h_c=19.0, at=NOW.isoformat())
DRY = Weather(rain_past_48h_mm=0.0, rain_next_48h_mm=0.0, max_temp_next_48h_c=21.0, at=NOW.isoformat())
STORM_COMING = replace(DRY, rain_next_48h_mm=31.0)
HEATWAVE = replace(DRY, max_temp_next_48h_c=36.5)


def with_weather(weather, **kw):
    return replace(context(**kw), weather=weather)


def hourly(start, rain, temp=None):
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(len(rain))]
    return {"hourly": {"time": times, "precipitation": rain, "temperature_2m": temp or [15.0] * len(rain)}}


# ---- reading Open-Meteo -----------------------------------------------------


def test_rain_is_summed_into_the_48_hours_either_side_of_the_visit():
    start = NOW - timedelta(hours=72)
    rain = [5.0] * 24 + [1.0] * 48 + [2.0] * 48 + [9.0] * 24  # 3 days before, 3 days after
    temp = [10.0] * 72 + [31.0] + [12.0] * 71
    w = summarise(hourly(start, rain, temp), NOW)
    assert w.rain_past_48h_mm == 48.0  # the day before that is outside the window
    assert w.rain_next_48h_mm == 96.0
    assert w.max_temp_next_48h_c == 31.0


async def test_an_outage_leaves_the_check_without_weather_not_without_a_result():
    async def down(url, params):
        raise WeatherError("timeout")

    assert await WeatherResolver(fetch=down).around(40.2, -8.4, datetime.now(UTC)) is None


async def test_a_visit_entered_long_afterwards_gets_no_weather_rather_than_the_wrong_one():
    calls = []

    async def fetch(url, params):
        calls.append(params)
        return hourly(NOW, [0.0] * 5)

    assert await WeatherResolver(fetch=fetch).around(40.2, -8.4, datetime.now(UTC) - timedelta(days=3)) is None
    assert calls == []


# ---- the rules --------------------------------------------------------------


def test_heavy_rain_before_the_visit_is_a_concern_where_people_get_in():
    quiet = rules(evaluate(with_weather(WET)))["human.storm_runoff"]
    paddled = rules(evaluate(with_weather(WET, answers=[("access", "contact", "citizen")])))["human.storm_runoff"]
    assert quiet.level is Level.WATCH and paddled.level is Level.CONCERN
    assert "24.5 mm" in quiet.because[0]


def test_heavy_rain_forecast_is_an_early_warning():
    found = rules(evaluate(with_weather(STORM_COMING, taxa=CLEAN)))
    assert found["human.rain_ahead"].level is Level.WATCH
    assert "31 mm" in found["human.rain_ahead"].because[0]
    assert "human.storm_runoff" not in found


def test_a_hot_spell_matters_only_where_the_water_cannot_defend_itself():
    exposed = [("shade", "open", "citizen"), ("flow", "slow", "citizen")]
    sheltered = [("shade", "shaded", "citizen"), ("flow", "fast", "citizen")]
    assert rules(evaluate(with_weather(HEATWAVE, answers=exposed)))["ecosystem.heat_ahead"].level is Level.CONCERN
    assert "ecosystem.heat_ahead" not in rules(evaluate(with_weather(HEATWAVE, answers=sheltered)))


def test_the_weather_says_where_sewage_came_from_and_who_should_look():
    sewage = [("odour", "sewage", "citizen")]
    after_rain = evaluate(with_weather(WET, answers=sewage))
    in_dry = evaluate(with_weather(DRY, answers=sewage))
    assert any("storm overflow" in b for b in rules(after_rain)["human.faecal_contamination"].because)
    assert any("misconnected drain" in b for b in rules(in_dry)["human.faecal_contamination"].because)
    assert any("overflow event records" in a for a in after_rain.actions_authority)
    assert any("misconnected foul drains" in a for a in in_dry.actions_authority)


def test_without_weather_every_rule_behaves_as_before():
    s = evaluate(context(answers=[("odour", "sewage", "citizen")]))
    assert not {"human.storm_runoff", "human.rain_ahead", "ecosystem.heat_ahead"} & set(rules(s))
    assert any("overflow activations" in a for a in s.actions_authority)


def test_the_new_rules_are_in_the_published_codesystem():
    assert {"human.storm_runoff", "human.rain_ahead", "ecosystem.heat_ahead"} <= set(fhir.RULE_IDS)


# ---- stored with the visit ---------------------------------------------------


class CountingWeather(WeatherResolver):
    def __init__(self, weather):
        self.weather, self.calls = weather, 0

    async def around(self, lat, lon, when):
        self.calls += 1
        return self.weather


async def test_the_visits_weather_is_stored_and_a_review_reuses_it_without_asking_again():
    resolver = CountingWeather(WET)
    first = await StreamAssessor(observer=NullObserver(), weather=resolver).assess(
        Submission(region=COIMBRA, taxa=(TaxonObservation(name="Baetidae", confirmed_by="citizen"),))
    )
    stored = first.as_dict()
    assert stored["weather"]["rain_past_48h_mm"] == 24.5 and "Open-Meteo" in stored["weather"]["source"]
    reviewed = await reassess(stored, Review(answers=(Reading(key="access", value="contact", source="citizen"),)))
    assert resolver.calls == 1
    assert reviewed.weather == WET
    assert {f.rule: f for f in reviewed.signal.findings}["human.storm_runoff"].level is Level.CONCERN


async def test_no_coordinates_no_weather_request():
    resolver = CountingWeather(WET)
    result = await StreamAssessor(observer=NullObserver(), weather=resolver).assess(
        Submission(taxa=(TaxonObservation(name="Baetidae", confirmed_by="citizen"),))
    )
    assert resolver.calls == 0 and result.weather is None


def test_the_fhir_export_carries_the_weather_finding_the_visit_had(client):
    import json

    from aquaplot.app import app
    from aquaplot.store import Store

    app.state.store = Store(":memory:")
    app.state.assessor = StreamAssessor(observer=NullObserver(), weather=CountingWeather(WET))
    made = client.post(
        "/api/assess", data={"lat": "40.2111", "lon": "-8.4291", "taxa": json.dumps(["Baetidae"])}
    ).json()
    assert made["weather"]["rain_past_48h_mm"] == 24.5
    codes = json.dumps(client.get(f"/api/assess/{made['id']}/fhir").json())
    assert "rule-human-storm-runoff" in codes


def test_the_report_dates_the_rain_so_an_authority_can_match_it_to_overflow_records(client):
    import json

    from aquaplot.app import app
    from aquaplot.store import Store

    app.state.store = Store(":memory:")
    app.state.assessor = StreamAssessor(observer=NullObserver(), weather=CountingWeather(WET))
    made = client.post(
        "/api/assess",
        data={"lat": "40.2111", "lon": "-8.4291", "answers": json.dumps({"odour": "sewage"}), "taxa": json.dumps(["Baetidae"])},
    ).json()
    md = client.get(f"/api/assess/{made['id']}/report.md").text
    assert "24.5 mm of rain in the 48 hours before the visit" in md
    assert "overflow event records" in md


# ---- the outlook: the same rules, re-run with the next 48 hours ---------------


async def test_the_forecast_for_many_sites_is_one_request():
    calls = []

    async def fetch(url, params):
        calls.append(params)
        return [hourly(NOW, [1.0] * 72), hourly(NOW, [0.0] * 72, [33.0] * 72)]

    a, b = await WeatherResolver(fetch=fetch).ahead([(40.2, -8.4), (51.05, 3.72)], now=NOW)
    assert len(calls) == 1 and calls[0]["latitude"] == "40.2000,51.0500"
    assert a.rain_next_48h_mm == 48.0 and b.heat_ahead


class Forecast(CountingWeather):
    """Visits get no weather; the outlook gets heavy rain at every site."""

    async def around(self, lat, lon, when):
        return None

    async def ahead(self, points, now=None):
        self.calls += 1
        return [STORM_COMING] * len(points)


def test_the_outlook_puts_the_site_that_has_shown_sewage_first(client):
    import json

    from aquaplot.app import app
    from aquaplot.store import Store

    app.state.store = Store(":memory:")
    app.state.outlook_cache = None
    forecast = Forecast(None)
    app.state.assessor = StreamAssessor(observer=NullObserver(), weather=forecast)
    for lat, answers, name in ((40.2111, {"odour": "sewage"}, "Below the outfall"), (40.25, {"odour": "none"}, "Upstream")):
        client.post(
            "/api/assess",
            data={"lat": str(lat), "lon": "-8.4291", "site_name": name, "answers": json.dumps(answers), "taxa": json.dumps(["Baetidae"])},
        )
    body = client.get("/api/outlook").json()
    assert [s["name"] for s in body["sites"]] == ["Below the outfall", "Upstream"]
    first, second = body["sites"]
    assert first["level"] == "concern" and second["level"] == "watch"
    assert any("overflow running" in b for b in first["findings"][0]["because"])
    client.get("/api/outlook")
    assert forecast.calls == 1  # cached
