"""Where is this stream, administratively? (FR-6)

SpeciesGuard, the project Riffle grew out of, hard-coded one county: it fetched
Orange County's polygon and asked "inside or outside". That was right for a tool
about one county's invasive plants and wrong for this one. OneAquaHealth runs in
Benevento, Coimbra, Ghent, Oslo and Toulouse, the hackathon is global, and
"native", "introduced" and "invasive" are all *place-relative* statements - a
species is not invasive, it is invasive somewhere. A tool that can only answer for
one county cannot answer the question at all.

So the place is resolved from the coordinates instead of assumed. iNaturalist
publishes the standard administrative places containing a point, with an
``admin_level`` (0 country, 10 state or region, 20 county or province, 30
municipality). Riffle takes the most specific one as the place to ask status
questions about, and keeps the rest as a fallback chain: if no establishment
record exists for the municipality, the region usually has one, and an answer
from the region is worth reporting *and* worth discounting. ``Place.confidence``
carries that discount so the certainty arithmetic downstream stays honest.

A failed lookup never blocks an assessment. The biological index, the habitat
pressure and the One Health findings are all computable without knowing which
municipality you are standing in; only the invasive-status question needs it, and
that question degrades to "unknown place" with the reason recorded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

from .inat import InatClient, InatError
from .schema import PlaceRef, Region

# How much to trust an establishment answer, by how specific the place that
# answered was. Priors, not measured calibration.
CONFIDENCE_BY_ADMIN_LEVEL: dict[int, float] = {30: 0.9, 20: 0.9, 10: 0.8, 0: 0.7}
CONFIDENCE_UNKNOWN_PLACE = 0.6

NEARBY_HALF_DEGREE = 0.02  # ~2 km box around the point; /places/nearby needs a box, not a point


@dataclass(frozen=True, slots=True)
class Place:
    id: int
    name: str
    display_name: str
    admin_level: int | None

    @property
    def confidence(self) -> float:
        if self.admin_level is None:
            return CONFIDENCE_UNKNOWN_PLACE
        return CONFIDENCE_BY_ADMIN_LEVEL.get(self.admin_level, CONFIDENCE_UNKNOWN_PLACE)

    @property
    def kind(self) -> str:
        return {30: "municipality", 20: "county or province", 10: "region or state", 0: "country"}.get(
            self.admin_level if self.admin_level is not None else -1, "place"
        )

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "display_name": self.display_name, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class Locality:
    """The administrative chain containing a point, most specific first."""

    places: tuple[Place, ...]

    @property
    def best(self) -> Place | None:
        return self.places[0] if self.places else None

    @property
    def country(self) -> Place | None:
        return next((p for p in self.places if p.admin_level == 0), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "place": self.best.as_dict() if self.best else None,
            "country": self.country.as_dict() if self.country else None,
            "chain": [p.display_name for p in self.places],
        }


@dataclass
class PlaceResolver:
    """Coordinates to an administrative chain, through the shared cached iNaturalist client."""

    inat: InatClient

    async def refine(self, region: "Region") -> "Region":
        """Fill in a Region's administrative place. A failure leaves the region as it was.

        Resolving the place can only make the answer better, so it must never be
        able to fail the assessment: an unresolved place costs a certainty
        penalty and a sentence, not a 502.
        """
        if region.lat is None or region.lon is None:
            return region
        locality = await self.locate(region.lat, region.lon)
        if not locality.places:
            return region
        best, country = locality.best, locality.country
        return region.model_copy(
            update={
                "place": _ref(best),
                "country": _ref(country),
                "chain": [p.display_name for p in locality.places],
            }
        )

    async def locality(self, region: "Region") -> Locality:
        if region.lat is None or region.lon is None:
            return Locality(places=())
        return await self.locate(region.lat, region.lon)

    async def locate(self, lat: float, lon: float) -> Locality:
        d = NEARBY_HALF_DEGREE
        try:
            raw = await self.inat.get(
                "/places/nearby",
                {
                    "swlat": round(lat - d, 4), "swlng": round(lon - d, 4),
                    "nelat": round(lat + d, 4), "nelng": round(lon + d, 4),
                    "per_page": 20,
                },
            )
        except InatError:
            return Locality(places=())
        standard = ((raw.get("results") or {}).get("standard")) or []
        places = [
            Place(
                id=p["id"],
                name=p.get("name", ""),
                display_name=p.get("display_name") or p.get("name", ""),
                admin_level=p.get("admin_level"),
            )
            for p in standard
            if isinstance(p.get("id"), int)
        ]
        # Most specific first: a municipality answers better than its country.
        places.sort(key=lambda p: -(p.admin_level if p.admin_level is not None else -1))
        return Locality(places=tuple(places))


def _ref(place: Place | None) -> PlaceRef | None:
    if place is None:
        return None
    return PlaceRef(id=place.id, name=place.name, display_name=place.display_name, kind=place.kind)


# ---- OneAquaHealth pilot cities ----------------------------------------------


def pilot_sites() -> dict[str, Any]:
    """The five OneAquaHealth research cities, as map presets and demo entry points."""
    return json.loads(resources.files("riffle.data").joinpath("pilot_sites.json").read_text())


# ISO 3166-1 alpha-2 codes of EU member states. iNaturalist names its country
# places by code, and no place is called "European Union", so a list whose scope
# is the Union is resolved through membership rather than string matching.
EU_MEMBER_CODES = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
)
