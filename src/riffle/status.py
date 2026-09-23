"""Species plus place to Native / Invasive / Naturalized, anywhere (FR-7).

Two sources, consulted in this order:

1. The project's seed list of documented invasives, now carrying the aquatic and
   riparian species of Union concern under EU Regulation 1143/2014 alongside the
   Californian entries Riffle inherited. A hit is the only way to earn the
   *Invasive* label, because "invasive" is a policy determination by a named
   authority, not a biological property of an organism.
2. iNaturalist's establishment means for the taxon *at the place the observer is
   standing*. iNaturalist resolves this through place ancestry - municipality,
   then region, then country - and reports which place answered, so the certainty
   drops as the answer gets coarser. Native gives *Native*; introduced gives
   *Naturalized/Non-native*.

The place is no longer a constant. SpeciesGuard asked every question of Orange
County; Riffle asks it of whatever municipality ``places.PlaceResolver`` found
under the observer's coordinates, which is what lets the same deployment answer
for a stream in Coimbra and one in Oslo. When no place could be resolved the
lookup still runs globally and the answer is discounted and labelled.

Every result records the source and its version so a later reviewer can see what
the call was based on, and the status stage never invents a label when both
sources are silent: it returns the neutral Naturalized label at low confidence
and says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .area import ListedTaxon, load_seed, match_listed_any
from .inat import InatClient, InatError
from .places import CONFIDENCE_BY_ADMIN_LEVEL, EU_MEMBER_CODES, Locality, Place
from .schema import Label

# How much to trust a status answer, by where it came from. These are priors,
# not measured calibration.
CONFIDENCE_SEED = 0.95
CONFIDENCE_COARSE = 0.6  # an answer from a place whose specificity we cannot tell
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


def _scope_covers(scope: str, locality: Locality) -> bool:
    """Does a list's jurisdiction plausibly cover where the observer is standing?

    "European Union" is resolved through the member-state list, because no
    iNaturalist place is called that. Everything else is crude string containment
    against the administrative chain. It is a hint that drives a caveat sentence
    and a small confidence discount, never a legal determination, so being wrong
    costs a sentence rather than a label.
    """
    tokens = {t for p in locality.places for t in re.split(r"[^a-z0-9]+", p.display_name.lower()) if len(t) >= 2}
    country = locality.country
    for part in (x.strip() for x in scope.split(";")):
        if not part:
            continue
        if part.lower() == "european union":
            if country is not None and country.name.upper() in EU_MEMBER_CODES:
                return True
            continue
        # "California, US" matches a chain containing either word. Loose on purpose:
        # a false positive costs a missing caveat, a false negative costs a wrong one.
        if any(word.strip().lower() in tokens for word in part.split(",") if len(word.strip()) >= 2):
            return True
    return False


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

    async def establishment(self, taxon_id: int, place: Place | None) -> tuple[str | None, dict[str, Any] | None]:
        params = {"place_id": place.id} if place is not None else {}
        raw = await self.inat.get(f"/taxa/{taxon_id}", params)
        results = raw.get("results") or []
        if not results:
            return None, None
        em = results[0].get("establishment_means") or {}
        return em.get("establishment_means"), em.get("place")

    async def resolve(self, scientific_name: str, locality: Locality | None = None) -> StatusResult:
        place = locality.best if locality is not None else None
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
            # A list is a statement about a jurisdiction. Saying so is the difference
            # between "this species is invasive" (false as stated) and "this species
            # is on the EU Union list, and you are in the EU" (actionable).
            elsewhere = locality is not None and bool(locality.places) and bool(listed.scope) and not _scope_covers(listed.scope, locality)
            return StatusResult(
                label=Label.INVASIVE, confidence=CONFIDENCE_SEED if not elsewhere else 0.7,
                source=listed.source, version=self.seed_version,
                taxon=taxon, establishment="introduced", place=listed.scope or "seed list",
                note=(
                    f"'{listed.scope}' is the jurisdiction that lists this species; the observation is in "
                    f"{place.display_name}, so the listing is indicative rather than binding here"
                    if elsewhere else None
                ),
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
            means, answered = await self.establishment(taxon.id, place)
        except InatError as exc:
            return StatusResult(
                label=Label.NATURALIZED, confidence=CONFIDENCE_UNKNOWN, source="none", version=self.seed_version,
                taxon=taxon, establishment=None, place=None,
                note=f"status source unavailable ({exc}); species identified but status could not be looked up",
            )
        where = place.display_name if place is not None else "this region"
        if means is None:
            return StatusResult(
                label=Label.NATURALIZED, confidence=CONFIDENCE_UNKNOWN, source="iNaturalist establishment means",
                version=self.seed_version, taxon=taxon, establishment=None, place=None,
                note=f"iNaturalist has no establishment record for this taxon in {where}; neutral label used",
            )
        answered = answered or {}
        place_id = answered.get("id")
        place_name = answered.get("display_name") or answered.get("name")
        admin_level = answered.get("admin_level")
        confidence = CONFIDENCE_BY_ADMIN_LEVEL.get(admin_level, CONFIDENCE_COARSE)
        # Only claim the answer is coarser than the observation when there is an
        # observation place to compare it with.
        same = place is None or place_id == place.id
        note = None if same else f"status comes from {place_name}, which is broader than {where}"
        label = Label.NATIVE if means in ("native", "endemic") else Label.NATURALIZED
        return StatusResult(
            label=label, confidence=confidence, source="iNaturalist establishment means", version=self.seed_version,
            taxon=taxon, establishment=means, place=place_name, note=note,
        )
