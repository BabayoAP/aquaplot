"""The weather either side of a visit: what one look at a stream cannot see (Track 6).

A citizen standing at a stream sees it at one moment. Two facts about that moment
change what the reading means for people, and neither is visible in a photo:

* **Did it just rain hard?** In the day or two after heavy rain an urban stream
  carries road run-off and, where sewers are combined, storm overflow. Bacteria
  stay high for one to three days, which is why bathing-water authorities advise
  against swimming after heavy rain. It also decides what a sewage sign *means*:
  sewage after a storm points at an overflow, sewage in dry weather at a
  misconnected drain or a leak, and those go to different people.
* **Is heavy rain or heat coming?** That is the early warning: plan contact with
  the water around the rain, and expect an oxygen crash in open, slow or
  algae-choked water in a hot spell.

The numbers come from Open-Meteo (free, no key, CC BY 4.0), fetched once when a
check is made and stored with it. A review or an export reuses the stored numbers,
so the rules see the same weather the visit did. The fetch is injectable, tests
never reach the network, and a failure leaves the check without weather rather
than without a result: this is context, never a precondition.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
SOURCE = "Open-Meteo (open-meteo.com), CC BY 4.0"

HEAVY_RAIN_MM = 10.0  # in 48 hours; a commonly used threshold for storm run-off and overflow risk
HOT_DAY_C = 30.0
WINDOW = timedelta(hours=48)

Fetcher = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class WeatherError(RuntimeError):
    pass


async def open_meteo_fetch(url: str, params: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=8) as client:
        try:
            res = await client.get(url, params=params)
            res.raise_for_status()
            return res.json()
        except httpx.HTTPError as exc:
            raise WeatherError(f"Open-Meteo request failed: {exc}") from exc


@dataclass(frozen=True, slots=True)
class Weather:
    rain_past_48h_mm: float
    rain_next_48h_mm: float
    max_temp_next_48h_c: float | None
    at: str  # the moment the windows are measured from, ISO 8601 UTC

    @property
    def heavy_rain_before(self) -> bool:
        return self.rain_past_48h_mm >= HEAVY_RAIN_MM

    @property
    def dry_before(self) -> bool:
        return self.rain_past_48h_mm < 1.0

    @property
    def heavy_rain_ahead(self) -> bool:
        return self.rain_next_48h_mm >= HEAVY_RAIN_MM

    @property
    def heat_ahead(self) -> bool:
        return self.max_temp_next_48h_c is not None and self.max_temp_next_48h_c >= HOT_DAY_C

    def as_dict(self) -> dict[str, Any]:
        return {
            "rain_past_48h_mm": self.rain_past_48h_mm,
            "rain_next_48h_mm": self.rain_next_48h_mm,
            "max_temp_next_48h_c": self.max_temp_next_48h_c,
            "at": self.at,
            "source": SOURCE,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Weather | None:
        if not d:
            return None
        return cls(
            rain_past_48h_mm=float(d["rain_past_48h_mm"]),
            rain_next_48h_mm=float(d["rain_next_48h_mm"]),
            max_temp_next_48h_c=None if d.get("max_temp_next_48h_c") is None else float(d["max_temp_next_48h_c"]),
            at=d["at"],
        )


def summarise(payload: dict[str, Any], when: datetime) -> Weather:
    """Sum Open-Meteo's hourly series into the 48 hours before and after ``when``."""
    hourly = payload.get("hourly") or {}
    times, rain, temp = hourly.get("time") or [], hourly.get("precipitation") or [], hourly.get("temperature_2m") or []
    if not times or len(rain) != len(times):
        raise WeatherError("Open-Meteo returned no hourly series")
    when = when.astimezone(UTC)
    before = after = 0.0
    hottest: float | None = None
    for i, stamp in enumerate(times):
        t = datetime.fromisoformat(stamp).replace(tzinfo=UTC)
        if when - WINDOW <= t < when:
            before += rain[i] or 0.0
        elif when <= t < when + WINDOW:
            after += rain[i] or 0.0
            if i < len(temp) and temp[i] is not None:
                hottest = temp[i] if hottest is None else max(hottest, temp[i])
    return Weather(round(before, 1), round(after, 1), None if hottest is None else round(hottest, 1), when.isoformat())


@dataclass
class WeatherResolver:
    fetch: Fetcher = open_meteo_fetch

    async def ahead(self, points: list[tuple[float, float]], now: datetime | None = None) -> list[Weather | None]:
        """The next 48 hours at many sites, in one request (Open-Meteo takes lists of coordinates).

        The dashboard's outlook calls this; nothing before ``now`` is counted.
        """
        if not points:
            return []
        now = (now or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
        params = {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in points),
            "longitude": ",".join(f"{lon:.4f}" for _, lon in points),
            "hourly": "precipitation,temperature_2m",
            "forecast_days": 3,
            "timezone": "UTC",
        }
        try:
            raw = await self.fetch(OPEN_METEO, params)
        except WeatherError:
            return [None] * len(points)
        payloads = raw if isinstance(raw, list) else [raw]
        out: list[Weather | None] = []
        for i in range(len(points)):
            try:
                out.append(summarise(payloads[i], now))
            except (IndexError, WeatherError, KeyError, TypeError, ValueError):
                out.append(None)
        return out

    async def around(self, lat: float, lon: float, when: datetime) -> Weather | None:
        """The weather either side of a visit, or None if it cannot be had.

        Only for a visit made now: the forecast endpoint keeps two days of history,
        and a visit entered long afterwards gets no weather rather than the wrong one.
        """
        if abs(datetime.now(UTC) - when.astimezone(UTC)) > timedelta(hours=6):
            return None
        params = {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "hourly": "precipitation,temperature_2m",
            "past_days": 2,
            "forecast_days": 3,
            "timezone": "UTC",
        }
        try:
            return summarise(await self.fetch(OPEN_METEO, params), when)
        except (WeatherError, KeyError, TypeError, ValueError):
            return None
