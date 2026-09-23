"""One cached client for the iNaturalist API, shared by the area viewer and the status stage.

iNaturalist asks clients for roughly one request per second and a daily ceiling.
Both the map (a user panning) and the classifier (several lookups per photo) would
blow through that without a cache, so caching lives here rather than in each
caller. The ``fetch`` callable is injectable so tests run on canned JSON and never
touch the network.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

INAT_API = "https://api.inaturalist.org/v1"
ORANGE_COUNTY_PLACE_ID = 2738  # iNaturalist place for Orange County, CA (admin level 20)
USER_AGENT = "riffle/0.1 (+https://github.com/BabayoAP/riffle)"

CACHE_TTL_SECONDS = 600
CACHE_MAX_ENTRIES = 512

Fetcher = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class InatError(RuntimeError):
    """Upstream data source failed; the API turns this into a 502."""


async def inat_fetch(path: str, params: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}) as client:
        try:
            res = await client.get(f"{INAT_API}{path}", params=params)
            res.raise_for_status()
            return res.json()
        except httpx.HTTPError as exc:
            raise InatError(f"iNaturalist request failed: {exc}") from exc


@dataclass
class InatClient:
    fetch: Fetcher = inat_fetch
    ttl: float = CACHE_TTL_SECONDS
    clock: Callable[[], float] = time.monotonic
    _cache: dict[str, tuple[float, dict[str, Any]]] = field(default_factory=dict)

    async def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        now = self.clock()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        data = await self.fetch(path, params)
        if len(self._cache) >= CACHE_MAX_ENTRIES:
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest]
        self._cache[key] = (now + self.ttl, data)
        return data
