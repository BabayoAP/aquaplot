"""Stage 4, status resolution (PRD §6.4): species plus place to Native / Invasive / Naturalized.

Two sources, consulted in this order:

1. The project's seed list of documented invasives (Cal-IPC, CDFW, USGS, UC IPM).
   A hit is the only way to earn the *Invasive* label, because "invasive" is a
   policy determination, not a biological one (PRD §9 regional/legal drift).
2. iNaturalist's establishment means for the taxon *in Orange County*. iNaturalist
   resolves this through place ancestry (county, then California, then the US),
   and reports which place answered, so the certainty can drop as the answer gets
   coarser. Native gives *Native*; introduced gives *Naturalized/Non-native*.

Every result records the source and its version so a later reviewer can see what
the call was based on, and the status stage never invents a label when both
sources are silent: it returns the neutral Naturalized label at low confidence
and says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .area import ListedTaxon, load_seed, match_listed_any
from .inat import ORANGE_COUNTY_PLACE_ID, InatClient, InatError
from .schema import Label

# How much to trust a status answer, by where it came from. These are priors,
# not measured calibration (PRD §8 lists calibration as M7 work).
CONFIDENCE_SEED = 0.95
CONFIDENCE_BY_PLACE = {ORANGE_COUNTY_PLACE_ID: 0.9, 14: 0.8}  # 14 = California
CONFIDENCE_COARSE = 0.65  # US / North America / anything else
CONFIDENCE_UNKNOWN = 0.35


@dataclass(frozen=True, slots=True)
class Taxon:
    id: int
    scientific_name: str
    common_name: str | None
    rank: str
    group: str | None
    photo: str | None
    observations: int


@dataclass(frozen=True, slots=True)
class StatusResult:
    label: Label
    confidence: float
    source: str
    version: str
    taxon: Taxon | None
    establishment: str | None  # native | introduced | endemic | ... | None
    place: str | None  # which place answered, e.g. "Orange County, US, CA"
    note: str | None  # a penalty-worthy caveat, or None


class StatusResolver:
    def __init__(self, inat: InatClient):
        self.inat = inat
        self.seed_version, self.listed = load_seed()

    async def find_taxon(self, scientific_name: str) -> Taxon | None:
        """Resolve a model's name to a real iNaturalist taxon, exact match first."""
        # Rank filter matters: iNaturalist has "complex" and "hybrid" taxa that share
        # a species' exact name (Quercus agrifolia complex vs. the species) and can
        # outrank it. Those carry no establishment record, so they would turn a
        # famous native into "unknown".
        raw = await self.inat.get(
            "/taxa", {"q": scientific_name, "per_page": 5, "is_active": "true", "rank": "species,genus,subspecies,variety,family"}
        )
        results = raw.get("results", [])
        wanted = scientific_name.strip().lower()
        exact = [t for t in results if t.get("name", "").lower() == wanted]
        pick = exact[0] if exact else next((t for t in results if t.get("rank") in ("species", "genus")), None)
        if pick is None:
            return None
        return Taxon(
            id=pick["id"],
            scientific_name=pick["name"],
            common_name=pick.get("preferred_common_name"),
            rank=pick.get("rank", "species"),
            group=pick.get("iconic_taxon_name"),
            photo=(pick.get("default_photo") or {}).get("square_url"),
            observations=pick.get("observations_count", 0),
        )

    async def establishment(self, taxon_id: int) -> tuple[str | None, dict[str, Any] | None]:
        raw = await self.inat.get(f"/taxa/{taxon_id}", {"place_id": ORANGE_COUNTY_PLACE_ID})
        results = raw.get("results") or []
        if not results:
            return None, None
        em = results[0].get("establishment_means") or {}
        return em.get("establishment_means"), em.get("place")

    async def resolve(self, scientific_name: str) -> StatusResult:
        # PRD §5.2: an iNaturalist outage must not fail the request. The seed list
        # still answers offline; anything else degrades to the neutral label with
        # the outage named in the evidence trail.
        outage: str | None = None
        try:
            taxon = await self.find_taxon(scientific_name)
        except InatError as exc:
            taxon, outage = None, str(exc)
        # Match the seed on the model's spelling *and* iNaturalist's accepted name:
        # a model may say "Pennisetum setaceum" while iNaturalist resolves it to
        # "Cenchrus setaceus", or the other way round. Either must earn the label.
        listed: ListedTaxon | None = match_listed_any(
            [scientific_name, taxon.scientific_name if taxon else None], self.listed
        )
        if listed is not None:
            return StatusResult(
                label=Label.INVASIVE, confidence=CONFIDENCE_SEED, source=listed.source, version=self.seed_version,
                taxon=taxon, establishment="introduced", place="Orange County, US, CA (seed list)", note=None,
            )
        if taxon is None:
            note = (
                f"status source unavailable ({outage}); species identified but status could not be looked up"
                if outage
                else f"'{scientific_name}' is not a known iNaturalist taxon; status could not be looked up"
            )
            return StatusResult(
                label=Label.NATURALIZED, confidence=CONFIDENCE_UNKNOWN, source="none", version=self.seed_version,
                taxon=None, establishment=None, place=None, note=note,
            )
        try:
            means, place = await self.establishment(taxon.id)
        except InatError as exc:
            return StatusResult(
                label=Label.NATURALIZED, confidence=CONFIDENCE_UNKNOWN, source="none", version=self.seed_version,
                taxon=taxon, establishment=None, place=None,
                note=f"status source unavailable ({exc}); species identified but status could not be looked up",
            )
        if means is None:
            return StatusResult(
                label=Label.NATURALIZED, confidence=CONFIDENCE_UNKNOWN, source="iNaturalist establishment means",
                version=self.seed_version, taxon=taxon, establishment=None, place=None,
                note="iNaturalist has no establishment record for this taxon in California; neutral label used",
            )
        place_id = (place or {}).get("id")
        place_name = (place or {}).get("display_name") or (place or {}).get("name")
        confidence = CONFIDENCE_BY_PLACE.get(place_id, CONFIDENCE_COARSE)
        note = None if place_id == ORANGE_COUNTY_PLACE_ID else f"status comes from {place_name}, not Orange County specifically"
        label = Label.NATIVE if means in ("native", "endemic") else Label.NATURALIZED
        return StatusResult(
            label=label, confidence=confidence, source="iNaturalist establishment means", version=self.seed_version,
            taxon=taxon, establishment=means, place=place_name, note=note,
        )
