"""Area viewer data layer (docs/AREA-VIEWER.md, FR-A1 to FR-A6).

The map page needs three things about a rectangle of the earth: where organisms
of a given status were seen, which species dominate there, and how the counts
have moved year over year. All three come from the iNaturalist API, which is
the only public source with per-observation geometry, photos and a
"introduced / native / threatened" establishment flag that is *place-relative*
(PRD §6.5: status is not a property of the species, it depends on where).

Design choices that matter:

* Everything goes through one injectable ``fetch`` callable, so tests run with
  canned JSON and never touch the network, and a future GBIF or Cal-IPC source is
  one more adapter rather than a rewrite.
* Responses are cached in memory for a few minutes. iNaturalist asks clients for
  about one request per second and a daily ceiling; a user panning a map would
  blow through that without a cache.
* "Introduced" is not "invasive". iNaturalist flags non-native establishment,
  while Cal-IPC and CDFW decide what is invasive. The seed list in
  ``data/status_seed.json`` marks the small set of taxa whose invasive status is
  documented, and the feature says so instead of upgrading every introduced
  sighting to "invasive".
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from importlib import resources
from typing import Any, Literal

from .inat import CACHE_TTL_SECONDS, Fetcher, InatClient, InatError, inat_fetch

AreaError = InatError  # kept for callers; the map and the status stage share one upstream

Status = Literal["introduced", "native", "threatened"]
STATUSES: tuple[Status, ...] = ("introduced", "native", "threatened")

# iNaturalist iconic taxa the UI exposes as "groups". Anything else is rejected
# so the query string cannot be used to smuggle arbitrary parameters upstream.
ICONIC_TAXA = frozenset(
    {"Plantae", "Insecta", "Aves", "Mammalia", "Reptilia", "Amphibia", "Actinopterygii", "Fungi", "Mollusca", "Arachnida"}
)

MAX_LIMIT = 200  # iNaturalist per_page ceiling
DEFAULT_TREND_YEARS = 12  # window shown when the user sets no year_from


@dataclass(frozen=True, slots=True)
class BBox:
    south: float
    west: float
    north: float
    east: float

    def __post_init__(self) -> None:
        if not (-90 <= self.south < self.north <= 90):
            raise ValueError("latitude bounds must satisfy -90 <= south < north <= 90")
        if not (-180 <= self.west < self.east <= 180):
            raise ValueError("longitude bounds must satisfy -180 <= west < east <= 180")


@dataclass(frozen=True, slots=True)
class AreaQuery:
    bbox: BBox | None = None
    place_id: int | None = None  # any iNaturalist place: a municipality, a province, a country
    taxa: tuple[str, ...] = ()
    year_from: int | None = None
    year_to: int | None = None
    limit: int = MAX_LIMIT
    taxon_id: int | None = None  # restrict to one iNaturalist taxon (and its descendants)

    def __post_init__(self) -> None:
        if self.bbox is None and self.place_id is None:
            raise ValueError("a bounding box or a place id is required")
        bad = set(self.taxa) - ICONIC_TAXA
        if bad:
            raise ValueError(f"unknown taxa group(s): {', '.join(sorted(bad))}")
        if self.year_from is not None and self.year_to is not None and self.year_from > self.year_to:
            raise ValueError("year_from must not exceed year_to")
        if not 1 <= self.limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")

    def params(self, status: Status) -> dict[str, Any]:
        p: dict[str, Any] = {status: "true", "quality_grade": "research", "geo": "true", "verifiable": "true"}
        if self.bbox is not None:
            p.update(swlat=self.bbox.south, swlng=self.bbox.west, nelat=self.bbox.north, nelng=self.bbox.east)
        if self.place_id is not None:
            p["place_id"] = self.place_id
        if self.taxa:
            p["iconic_taxa"] = ",".join(sorted(self.taxa))
        if self.year_from is not None:
            p["d1"] = f"{self.year_from}-01-01"
        if self.year_to is not None:
            p["d2"] = f"{self.year_to}-12-31"
        if self.taxon_id is not None:
            p["taxon_id"] = self.taxon_id
        return p


@dataclass(frozen=True, slots=True)
class ListedTaxon:
    scientific_name: str  # the name iNaturalist currently accepts
    common_name: str
    group: str
    rating: str
    source: str
    synonyms: tuple[str, ...] = ()  # older names still used by field guides, lists and vision models
    scope: str = ""  # the jurisdiction whose list this entry comes from
    habitat: str = "terrestrial"  # freshwater | riparian | terrestrial
    why: str = ""  # the One Health consequence, in plain language

    def names(self) -> tuple[str, ...]:
        return (self.scientific_name, *self.synonyms)

    @property
    def aquatic(self) -> bool:
        return self.habitat in ("freshwater", "riparian")

    def summary(self) -> str:
        return f"{self.common_name} ({self.scientific_name})"


def load_seed() -> tuple[str, list[ListedTaxon]]:
    raw = json.loads(resources.files("riffle.data").joinpath("status_seed.json").read_text())
    return raw["version"], [ListedTaxon(**{**e, "synonyms": tuple(e.get("synonyms", ()))}) for e in raw["entries"]]


def match_listed(scientific_name: str | None, listed: list[ListedTaxon]) -> ListedTaxon | None:
    """Exact species match on the accepted name or a synonym, or a subspecies of a
    listed species (``Trachemys scripta elegans``).

    Taxonomy moves: fountain grass is *Pennisetum setaceum* on the Cal-IPC list
    and *Cenchrus setaceus* on iNaturalist. Matching only one spelling silently
    drops the ring on the map and the Invasive label in the classifier, so every
    entry carries both.
    """
    if not scientific_name:
        return None
    name = scientific_name.strip().lower()
    for entry in listed:
        for base in entry.names():
            base = base.lower()
            if name == base or name.startswith(base + " "):
                return entry
    return None


def match_listed_any(names: list[str | None], listed: list[ListedTaxon]) -> ListedTaxon | None:
    """First seed hit across several spellings of one taxon (model's name, iNaturalist's name)."""
    for n in names:
        hit = match_listed(n, listed)
        if hit is not None:
            return hit
    return None


@dataclass
class AreaService:
    fetch: Fetcher = inat_fetch
    ttl: float = CACHE_TTL_SECONDS
    clock: Callable[[], float] = time.monotonic
    inat: InatClient = field(init=False)
    seed_version: str = field(init=False)
    listed: list[ListedTaxon] = field(init=False)

    def __post_init__(self) -> None:
        self.inat = InatClient(fetch=self.fetch, ttl=self.ttl, clock=self.clock)
        self.seed_version, self.listed = load_seed()

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        return await self.inat.get(path, params)

    async def observations(self, query: AreaQuery, status: Status) -> dict[str, Any]:
        """FR-A2: sightings as GeoJSON, one feature per observation."""
        params = query.params(status) | {"per_page": query.limit, "photos": "true", "order_by": "observed_on", "order": "desc"}
        raw = await self._get("/observations", params)
        features = [f for f in (self._feature(o, status) for o in raw.get("results", [])) if f is not None]
        return {
            "type": "FeatureCollection",
            "features": features,
            "total": raw.get("total_results", len(features)),
            "status": status,
            "source": "iNaturalist research-grade observations",
            "seed_version": self.seed_version,
        }

    def _feature(self, obs: dict[str, Any], status: Status) -> dict[str, Any] | None:
        geo = obs.get("geojson") or {}
        coords = geo.get("coordinates")
        if not coords or len(coords) != 2:
            return None  # obscured or missing location; the map cannot place it
        taxon = obs.get("taxon") or {}
        photos = obs.get("photos") or []
        photo = photos[0].get("url") if photos else None
        listed = match_listed(taxon.get("name"), self.listed)
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(coords[0]), float(coords[1])]},
            "properties": {
                "id": obs.get("id"),
                "uri": obs.get("uri"),
                "observed_on": obs.get("observed_on"),
                "scientific_name": taxon.get("name"),
                "common_name": taxon.get("preferred_common_name"),
                "rank": taxon.get("rank"),
                "group": taxon.get("iconic_taxon_name"),
                "status": status,
                "listed": listed.rating if listed else None,
                "listed_source": listed.source if listed else None,
                "photo": photo.replace("square", "medium") if photo else None,
                "place_guess": obs.get("place_guess"),
            },
        }

    async def species(self, query: AreaQuery, status: Status, top: int = 15) -> list[dict[str, Any]]:
        """FR-A4: which species dominate the area, most-observed first."""
        raw = await self._get("/observations/species_counts", query.params(status) | {"per_page": top})
        out = []
        for row in raw.get("results", []):
            taxon = row.get("taxon") or {}
            listed = match_listed(taxon.get("name"), self.listed)
            out.append(
                {
                    "count": row.get("count", 0),
                    "taxon_id": taxon.get("id"),
                    "scientific_name": taxon.get("name"),
                    "common_name": taxon.get("preferred_common_name"),
                    "group": taxon.get("iconic_taxon_name"),
                    "listed": listed.rating if listed else None,
                    "photo": (taxon.get("default_photo") or {}).get("square_url"),
                }
            )
        return out

    async def trend(self, query: AreaQuery) -> dict[str, Any]:
        """FR-A5: research-grade observations per year for each status in the area.

        Raw counts rise with iNaturalist's own growth, so the page also shows the
        introduced share of all sightings, which is the number that says whether
        the mix is shifting.
        """
        by_status: dict[str, dict[str, int]] = {}
        for status in STATUSES:
            raw = await self._get(
                "/observations/histogram", query.params(status) | {"date_field": "observed", "interval": "year"}
            )
            by_status[status] = {k[:4]: int(v) for k, v in (raw.get("results", {}).get("year") or {}).items()}
        seen = sorted(int(y) for counts in by_status.values() for y in counts)
        if not seen:
            return {"years": [], **{s: [] for s in STATUSES}, "introduced_share_pct": []}
        end = query.year_to if query.year_to is not None else seen[-1]
        if query.year_from is not None:
            start = query.year_from
        else:
            # iNaturalist holds a trickle of digitised records back to the 1960s.
            # Unfiltered, they flatten the chart and make the share sentence
            # compare against a year with three sightings.
            start = max(seen[0], end - DEFAULT_TREND_YEARS + 1)
        # A continuous axis: a year with no sightings is a zero, not a gap.
        years = [str(y) for y in range(start, end + 1)]
        series = {s: [by_status[s].get(y, 0) for y in years] for s in STATUSES}
        share = []
        for i, _ in enumerate(years):
            total = series["introduced"][i] + series["native"][i]
            share.append(round(100 * series["introduced"][i] / total, 1) if total else None)
        return {"years": years, **series, "introduced_share_pct": share}

    def listed_taxa(self) -> dict[str, Any]:
        return {"version": self.seed_version, "entries": [asdict(e) for e in self.listed]}
