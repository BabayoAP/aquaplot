"""The assessment pipeline: photos and answers in, a banded One Health read-out out (FR-1).

This is the module that composes everything else, and the order is deliberate:

    photos ─▶ observe.py      structured field observations (model)
             ├──────────────▶ habitat.py   visual pressures, model + citizen answers merged
             └──────────────▶ bioindex.py  BMWP/ASPT band from the invertebrates
    coords ─▶ places.py       which municipality is this?
    taxa   ─▶ status.py       is any of this a listed invasive species, here?
                     └──────▶ onehealth.py rules over all of the above
                                      └──▶ Assessment

Three properties of the composition are the point of it.

**The model is never load-bearing.** Every stage below ``observe.py`` runs on
whatever observations exist, wherever they came from. With no API key and no
local model, a citizen who fills the form by hand gets the same band, the same
findings and the same actions. The model makes the app usable by a novice; it is
not what makes it work.

**Certainty is multiplicative and itemised**, inherited from SpeciesGuard's rule
that a fully automatic call must never look more confident than its weakest
input. Each factor below 1.0 leaves a sentence in ``penalties`` saying what it
was, so the number can always be taken apart.

**The human loop is a queue, not a gesture.** ``needs_confirmation`` names the
specific observations whose confirmation would change the output - the ones
holding a health alert down to 'concern', the shaky identifications, the
questions only a person standing there can answer. Confirming them and
re-running produces a different, better-evidenced assessment, and
``confirmations`` records who did it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import bioindex, habitat, oah, onehealth, secondopinion
from .area import ListedTaxon, load_seed, match_listed
from .identify import IdentifyError
from .inputs import DecodedImage
from .observe import RecordedObservation, StreamObservation, StreamObserver
from .places import PlaceResolver
from .schema import Label, Region
from .secondopinion import SecondOpinion
from .status import StatusResolver
from .weather import Weather, WeatherResolver

ASSESSMENT_VERSION = "aquaplot-assess-v3"  # v3: weather either side of the visit enters the rules

# Certainty factors. Priors, not measured calibration.
FACTOR_PLACE_UNKNOWN = 0.9  # the band does not depend on the place; the invasive check does
FACTOR_NO_COORDS = 0.85
FACTOR_NO_PHOTO = 0.95  # a hand-filled form is evidence, just without a picture to re-check
COVERAGE_FLOOR = 0.6  # how much a completely unanswered habitat form can drag the number down
FACTOR_OPEN_DISAGREEMENT = 0.9  # per open second-opinion item that would change the band
DISAGREEMENT_FLOOR = 0.7

SAMPLE_KINDS = frozenset({"specimen", "single_organism"})


def warm_season(lat: float | None, when: datetime) -> bool:
    """Is it the half of the year when mosquitoes develop quickly here?

    Crude by design: month and hemisphere. It only ever moves a vector finding
    between 'watch' and 'concern', and getting it wrong in the tropics costs a
    softer warning, not a missed one.
    """
    northern = lat is None or lat >= 0
    month = when.month
    return (4 <= month <= 10) if northern else (month >= 10 or month <= 4)


@dataclass(frozen=True, slots=True)
class InvasiveHit:
    name: str
    listed: ListedTaxon
    confidence: float
    in_jurisdiction: bool
    note: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.listed.summary(),
            "reported_as": self.name,
            "group": self.listed.group,
            "habitat": self.listed.habitat,
            "rating": self.listed.rating,
            "source": self.listed.source,
            "scope": self.listed.scope,
            "why_it_matters": self.listed.why,
            "confidence": round(self.confidence, 2),
            "listed_for_this_place": self.in_jurisdiction,
            "note": self.note,
        }


@dataclass
class Assessment:
    """One stream check. Everything a reviewer needs to agree or disagree with it."""

    id: str
    created_at: str
    site_name: str | None
    region: Region
    photos: int
    photo_kinds: list[str]
    ecology: bioindex.EcologicalStatus
    pressures: habitat.HabitatPressure
    signal: onehealth.Signal
    invasives: list[InvasiveHit]
    certainty: float
    penalties: list[str]
    needs_confirmation: list[dict[str, Any]]
    observer: str
    model_notes: list[str] = field(default_factory=list)
    confirmations: int = 0
    supersedes: str | None = None  # the assessment this one replaces after a human review
    version: str = ASSESSMENT_VERSION
    identified_by: str = "model"  # "citizen" when the person identified the animals themselves
    second_opinion: SecondOpinion | None = None
    weather: Weather | None = None  # the 48 hours either side of the visit, stored so a review sees the same

    def as_dict(self) -> dict[str, Any]:
        research = oah.research_site_at(self.region.lat, self.region.lon)
        return {
            "research_site": research[0].as_dict(research[1]) if research else None,
            "identified_by": self.identified_by,
            "second_opinion": self.second_opinion.as_dict() if self.second_opinion else None,
            "weather": self.weather.as_dict() if self.weather else None,
            "id": self.id,
            "created_at": self.created_at,
            "site_name": self.site_name,
            "region": self.region.model_dump(),
            "photos": self.photos,
            "photo_kinds": self.photo_kinds,
            "band": self.ecology.band.value,
            "one_health": self.signal.as_dict(),
            "ecology": self.ecology.as_dict(),
            "pressures": self.pressures.as_dict(),
            "invasives": [i.as_dict() for i in self.invasives],
            "certainty": round(self.certainty, 1),
            "penalties": self.penalties,
            "needs_confirmation": self.needs_confirmation,
            "observer": self.observer,
            "model_notes": self.model_notes,
            "confirmations": self.confirmations,
            "supersedes": self.supersedes,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class Submission:
    """What the citizen sent. Photos are optional; so is everything else, one at a time."""

    photos: tuple[DecodedImage, ...] = ()
    description: str = ""
    region: Region = field(default_factory=lambda: Region(source="none"))
    answers: tuple[habitat.Reading, ...] = ()  # the citizen's own form answers
    taxa: tuple[bioindex.TaxonObservation, ...] = ()  # invertebrates the citizen identified or confirmed
    site_name: str | None = None
    when: datetime | None = None
    index: str | None = None  # force a biotic index ("bmwp" | "ibmwp"); otherwise chosen from the country


@dataclass
class StreamAssessor:
    observer: StreamObserver
    status: StatusResolver | None = None
    places: PlaceResolver | None = None
    weather: WeatherResolver | None = None

    def __post_init__(self) -> None:
        self.seed_version, self.listed = load_seed()

    async def assess(self, submission: Submission) -> Assessment:
        when = submission.when or datetime.now(UTC)
        region = submission.region
        locality = None
        penalties: list[str] = []

        # 1. Where are we? Only the invasive check needs this, so a failure is a
        #    discount and a sentence, never an error.
        if self.places is not None and region.lat is not None:
            region = await self.places.refine(region)
            locality = await self.places.locality(region)

        # Which family-score table applies here is a fact about the place, resolved
        # from the coordinates like everything else, unless the caller names one.
        index = bioindex.INDICES.get(submission.index or "") or bioindex.index_for(_country_names(region))

        # 2. What is in the photos?
        model_readings: list[habitat.Reading] = []
        model_taxa: list[bioindex.TaxonObservation] = []
        photo_kinds: list[str] = []
        notes: list[str] = []
        declined: set[str] = set()  # indicators the model looked at and would not guess
        recorded: list[RecordedObservation] = []  # sample photos answered from their recording
        for image in submission.photos:
            try:
                seen = await self.observer.observe(image.image, submission.description, region)
            except IdentifyError as exc:
                penalties.append(f"one photo could not be read by the vision model ({exc}); it contributed nothing")
                continue
            if isinstance(seen, RecordedObservation):
                recorded.append(seen)
            photo_kinds.append(seen.photo_kind)
            if seen.reasoning:
                notes.append(seen.reasoning)
            if seen.photo_kind == "not_a_stream":
                penalties.append(f"one photo was not of a stream or a sample and was ignored ({seen.reasoning or 'no reason given'})")
                continue
            model_readings.extend(_readings_from(seen))
            model_taxa.extend(_taxa_from(seen))
            # A model that says "I cannot tell from this photo" is behaving well, and
            # the answer is not lost: it becomes a question for the person instead.
            declined.update(k for k in seen.cannot_tell if k in habitat.BY_KEY)

        if submission.photos and not photo_kinds:
            penalties.append("no photo could be used, so everything below rests on what the observer entered by hand")
        if not submission.photos:
            penalties.append("no photo was submitted; the reading cannot be re-checked by anyone later")

        # 3. Habitat pressures: the model first, the person on top. habitat.assess
        #    gives a citizen answer precedence over a model answer for the same key.
        pressures = habitat.assess([*model_readings, *submission.answers])
        penalties.extend(pressures.penalties)
        open_to_person = sorted(declined - {r.key for r in pressures.readings} - {r.key for r in pressures.exposure})
        if open_to_person:
            penalties.append(
                f"the model could not judge {len(open_to_person)} indicator(s) from the photos "
                f"({', '.join(open_to_person)}) and said so rather than guessing; they are waiting for you"
            )

        # 4. Biological index. When the person identified the animals themselves,
        #    their list is what is scored and the model's list becomes a second
        #    opinion that can only raise questions. Otherwise the model's list is a
        #    proposal, scored unconfirmed and queued for the person to check.
        citizen_led = bool(submission.taxa)
        if citizen_led:
            scored_taxa = list(submission.taxa)
            second = self._second_opinion(submission.taxa, model_taxa, photo_kinds, index, bool(recorded))
        else:
            scored_taxa = [*model_taxa]
            second = None
        ecology = bioindex.score(scored_taxa, index)
        penalties.extend(ecology.penalties)

        # 5. Is anything here on an invasive list for this jurisdiction?
        invasives = await self._invasives(scored_taxa, locality)
        if second is not None:
            _flag_invasive_suggestions(second, self.listed)

        # 6. One Health rules over all of it, with the weather either side of the visit.
        weather = None
        if self.weather is not None and region.lat is not None and region.lon is not None:
            weather = await self.weather.around(region.lat, region.lon, when)
        signal = onehealth.evaluate(
            onehealth.Context(
                status=ecology,
                habitat=pressures,
                invasives=tuple(i.listed.summary() for i in invasives),
                site_name=submission.site_name,
                warm_season=warm_season(region.lat, when),
                weather=weather,
            )
        )

        certainty, more = certainty_of(region, pressures, ecology, bool(photo_kinds), second)
        penalties.extend(more)

        observer = self.observer.name
        if recorded:
            by = recorded[0].recorded_by
            observer = f"{by}, recorded" if len(recorded) == len(photo_kinds) else f"{observer} and {by}, recorded"
            notes.insert(
                0,
                f"{len(recorded)} of the photos {'is a' if len(recorded) == 1 else 'are'} bundled sample"
                f"{'' if len(recorded) == 1 else 's'}. What the model saw in "
                f"{'it' if len(recorded) == 1 else 'them'} was recorded from {by} on {recorded[0].recorded_on} "
                "and replayed, not read live.",
            )

        return Assessment(
            id=uuid.uuid4().hex[:12],
            created_at=when.isoformat(),
            site_name=submission.site_name,
            region=region,
            photos=len(submission.photos),
            photo_kinds=photo_kinds,
            ecology=ecology,
            pressures=pressures,
            signal=signal,
            invasives=invasives,
            certainty=certainty,
            penalties=_dedupe(penalties),
            needs_confirmation=_confirmation_queue(ecology, pressures, signal, open_to_person, second),
            observer=observer,
            model_notes=notes,
            confirmations=_confirmations(pressures, ecology),
            identified_by="citizen" if citizen_led else ("model" if model_taxa else "none"),
            second_opinion=second,
            weather=weather,
        )

    def _second_opinion(
        self,
        citizen: tuple[bioindex.TaxonObservation, ...],
        model: list[bioindex.TaxonObservation],
        photo_kinds: list[str],
        index: bioindex.BioticIndex,
        replayed: bool = False,
    ) -> SecondOpinion:
        if self.observer.name == "none" and not replayed:
            why = getattr(self.observer, "reason", None) or "no vision model is configured"
            return secondopinion.unavailable(f"{why}, so nobody double-checked the identifications")
        if not SAMPLE_KINDS & set(photo_kinds):
            return secondopinion.unavailable(
                "there was no photo of the sample tray, so the model had nothing to compare your identifications against",
                model,
            )
        return secondopinion.compare(citizen, model, lambda taxa: bioindex.score(taxa, index))

    async def _invasives(self, taxa: list[bioindex.TaxonObservation], locality) -> list[InvasiveHit]:
        """Check every reported name against the seed list, and confirm species-rank hits upstream.

        The seed answers offline and instantly, which matters in the field. The
        status resolver is only consulted to attach the jurisdiction caveat, and
        its failure leaves the seed's answer standing.
        """
        hits: list[InvasiveHit] = []
        seen: set[str] = set()
        for obs in taxa:
            key = obs.name.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            listed = match_listed(obs.name, self.listed)
            if listed is None:
                continue
            in_jurisdiction, note = True, None
            if self.status is not None and locality is not None and locality.places:
                try:
                    result = await self.status.resolve(listed.scientific_name, locality)
                    if result.label is Label.INVASIVE and result.note:
                        in_jurisdiction, note = False, result.note
                except Exception:  # an upstream outage must not remove a listing the seed already has
                    note = "jurisdiction could not be confirmed upstream; the listing stands on the seed list alone"
            hits.append(
                InvasiveHit(
                    name=obs.name, listed=listed, confidence=obs.effective_confidence, in_jurisdiction=in_jurisdiction, note=note
                )
            )
        return hits


def certainty_of(
    region: Region,
    pressures: habitat.HabitatPressure,
    ecology: bioindex.EcologicalStatus,
    had_photo: bool,
    second: SecondOpinion | None = None,
) -> tuple[float, list[str]]:
    """How much of this assessment is actually evidenced, as a percentage.

    Multiplicative, like SpeciesGuard's certainty rule and for the same reason: a
    result must never look more confident than its weakest input, and every factor
    below 1.0 has to leave a sentence behind saying what it was.
    """
    penalties: list[str] = []
    scoreable = len([i for i in habitat.INDICATORS if not i.exposure])
    coverage = COVERAGE_FLOOR + (1 - COVERAGE_FLOOR) * (pressures.answered / scoreable if scoreable else 1)
    if pressures.answered < scoreable:
        penalties.append(
            f"{pressures.answered} of {scoreable} habitat questions were answered; each unanswered one "
            "leaves part of the site undescribed"
        )
    place_factor = 1.0
    if region.source == "none":
        place_factor = FACTOR_NO_COORDS
        penalties.append("no location was recorded, so the reading cannot be mapped, compared or repeated")
    elif region.place is None:
        place_factor = FACTOR_PLACE_UNKNOWN
        penalties.append("the coordinates could not be resolved to a municipality, so the invasive-species check is global rather than local")
    photo_factor = 1.0 if had_photo else FACTOR_NO_PHOTO
    biology = (ecology.confidence / 100) if ecology.families else 0.4
    if not ecology.families:
        penalties.append("no invertebrates were identified, so the biological half of the assessment is missing")
    disagreement = 1.0
    if second is not None:
        decisive = [i for i in second.open if i["changes_band"]]
        if decisive:
            disagreement = max(DISAGREEMENT_FLOOR, FACTOR_OPEN_DISAGREEMENT ** len(decisive))
            penalties.append(
                f"the model disagreed with {len(decisive)} of your identifications in a way that would change the band, "
                "and that has not been settled yet"
            )
    return round(100 * biology * coverage * place_factor * photo_factor * disagreement, 1), penalties


def _flag_invasive_suggestions(second: SecondOpinion, listed: list[ListedTaxon]) -> None:
    """A suggestion the model made that is a listed invasive goes to the top of the queue.

    It is still only a question: nothing enters the invasive check until a person says it was there.
    """
    for item in second.items:
        if item["model_name"] and (hit := match_listed(item["model_name"], listed)):
            item["invasive"] = hit.summary()
            item["priority"] = 1
            item["question"] += f" It may be {hit.summary()}, a listed invasive species."
    second.items.sort(key=lambda i: i["priority"])


def _readings_from(seen: StreamObservation) -> list[habitat.Reading]:
    return [
        habitat.Reading(key=call.key, value=call.value, source="model", confidence=call.confidence)
        for call in seen.habitat
    ]


def _taxa_from(seen: StreamObservation) -> list[bioindex.TaxonObservation]:
    return [
        bioindex.TaxonObservation(name=t.name, confidence=t.confidence, abundance=t.count)
        for t in seen.taxa
        if t.name.strip()
    ]


def _country_names(region: Region) -> list[str]:
    return [region.country.name, region.country.display_name] if region.country else []


def _confirmations(pressures: habitat.HabitatPressure, ecology: bioindex.EcologicalStatus) -> int:
    return len([r for r in pressures.readings if r.source == "citizen"]) + len(
        [t for t in (*ecology.scored, *ecology.recorded) if t.confirmed]
    )


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for i in items:
        if i not in out:
            out.append(i)
    return out


# Which habitat answers each rule rests on. Confirming one of these is what lifts
# a finding the engine is holding below alert level, so the queue asks for it first.
RULE_EVIDENCE: dict[str, tuple[str, ...]] = {
    "human.cyanobacteria": ("algae",),
    "human.faecal_contamination": ("odour", "litter", "water_colour", "foam_or_sheen"),
    "human.chemical_exposure": ("foam_or_sheen", "odour", "water_colour"),
    "human.vector_breeding": ("flow", "litter"),
    "animal.drinking_water": ("algae", "odour", "water_colour"),
}


def _confirmation_queue(
    ecology: bioindex.EcologicalStatus,
    pressures: habitat.HabitatPressure,
    signal: onehealth.Signal,
    declined: list[str] | None = None,
    second: SecondOpinion | None = None,
) -> list[dict[str, Any]]:
    """The human-in-the-loop queue, ordered by how much confirming each item would change.

    An observation holding a health alert down to 'concern' is worth far more than
    a third mayfly family, and the app should ask for it first.
    """
    queue: list[dict[str, Any]] = []
    if second is not None:
        queue.extend({**item, "kind": "second_opinion", "check": item["kind"]} for item in second.open)

    blocking_keys = {k for f in signal.findings if not f.confirmed for k in RULE_EVIDENCE.get(f.rule, ())}
    for row in pressures.readings:
        if row.source != "model":
            continue
        blocking = row.key in blocking_keys
        if blocking or row.confidence < 0.75:
            queue.append(
                {
                    "kind": "habitat",
                    "key": row.key,
                    "question": row.question,
                    "model_said": row.label,
                    "confidence": round(row.confidence, 2),
                    "why_it_matters": "This observation is holding a health finding below alert level until a person confirms it."
                    if blocking
                    else "The model was not confident about this.",
                    "priority": 1 if blocking else 3,
                }
            )

    asked = {q["key"] for q in queue}
    for key in [*pressures.unanswered_by_person, *(declined or [])]:
        if key in asked:
            continue
        asked.add(key)
        indicator = habitat.BY_KEY[key]
        declined_here = key in (declined or [])
        queue.append(
            {
                "kind": "habitat",
                "key": key,
                "question": indicator.question,
                "model_said": None,
                "confidence": None,
                "why_it_matters": (
                    f"The model looked and could not tell from your photo. {indicator.why}"
                    if declined_here
                    else indicator.why
                ),
                "priority": 2,
            }
        )

    for taxon in (*ecology.scored, *ecology.recorded):
        if taxon.confirmed:
            continue
        if taxon.confidence < 0.7 or taxon.coarse:
            queue.append(
                {
                    "kind": "taxon",
                    "key": taxon.name,
                    "question": f"Is this {taxon.plain_name}?",
                    "model_said": taxon.plain_name,
                    "confidence": round(taxon.confidence, 2),
                    "why_it_matters": (
                        f"Identified only to {taxon.group}; a family-level answer would sharpen the index."
                        if taxon.coarse
                        else f"This animal contributes {taxon.score:.0f} of the sensitivity score."
                        if taxon.sensitivity != "not scored"
                        else "The index does not score this animal, but the health checks use it."
                    ),
                    "priority": 3 if taxon.coarse else 2,
                }
            )

    queue.sort(key=lambda q: q["priority"])
    return queue


# ---- the human half of the loop ----------------------------------------------


def readings_of(previous: dict[str, Any]) -> list[habitat.Reading]:
    """Rebuild the habitat answers from a stored assessment."""
    rows = [*previous.get("pressures", {}).get("readings", []), *previous.get("pressures", {}).get("exposure", [])]
    return [
        habitat.Reading(key=r["key"], value=r["value"], source=r.get("source", "model"), confidence=r.get("confidence", 1.0))
        for r in rows
    ]


def taxa_of(previous: dict[str, Any]) -> list[bioindex.TaxonObservation]:
    """Rebuild the identified invertebrates from a stored assessment."""
    return [
        bioindex.TaxonObservation(
            name=t["name"],
            confidence=t.get("confidence", 1.0),
            confirmed_by="citizen" if t.get("confirmed") else None,
        )
        for t in previous.get("ecology", {}).get("taxa", [])
    ]


@dataclass(frozen=True, slots=True)
class Review:
    """What a person changed after looking at what the model proposed.

    ``corrections`` is deliberately the same shape as ``confirmations``: correcting
    the model is worth more than agreeing with it, and the interface should make
    both equally easy. Rejecting a taxon removes it from the index entirely, which
    is the only way a wrong identification can be undone.
    """

    answers: tuple[habitat.Reading, ...] = ()  # confirmed or corrected habitat answers
    confirmed_taxa: tuple[str, ...] = ()
    rejected_taxa: tuple[str, ...] = ()
    added_taxa: tuple[str, ...] = ()
    dismissed: tuple[str, ...] = ()  # second-opinion items the person looked at and kept their own answer
    site_name: str | None = None


async def reassess(previous: dict[str, Any], review: Review) -> Assessment:
    """Recompute a stored assessment with a person's confirmations folded in.

    The vision model is not called again, and must not be: the photograph has not
    changed, and re-running it would let the model quietly overwrite a correction
    a human just made. Only the scoring runs again.
    """
    rejected = {n.strip().lower() for n in review.rejected_taxa}
    taxa = [t for t in taxa_of(previous) if t.name.strip().lower() not in rejected]
    confirmed = {n.strip().lower() for n in review.confirmed_taxa}
    taxa = [
        bioindex.TaxonObservation(name=t.name, confidence=t.confidence, confirmed_by="citizen")
        if t.name.strip().lower() in confirmed
        else t
        for t in taxa
    ]
    taxa += [bioindex.TaxonObservation(name=n, confidence=1.0, confirmed_by="citizen") for n in review.added_taxa if n.strip()]

    pressures = habitat.assess([*readings_of(previous), *review.answers])
    index = bioindex.INDICES.get(previous.get("ecology", {}).get("index_key", "bmwp"), bioindex.BMWP)
    ecology = bioindex.score(taxa, index)
    region = Region.model_validate(previous["region"])
    when = datetime.fromisoformat(previous["created_at"])
    still_listed = [i for i in previous.get("invasives", []) if i.get("reported_as", "").strip().lower() not in rejected]
    seeded = {entry.summary(): entry for entry in load_seed()[1]}
    weather = Weather.from_dict(previous.get("weather"))  # the visit's weather, never refetched

    signal = onehealth.evaluate(
        onehealth.Context(
            status=ecology,
            habitat=pressures,
            invasives=tuple(i["name"] for i in still_listed),
            site_name=review.site_name or previous.get("site_name"),
            warm_season=warm_season(region.lat, when),
            weather=weather,
        )
    )
    # The second opinion is recomputed from the model's stored list, never by asking
    # the model again. What the person settled stays settled: keeping their own
    # answer dismisses the item, and switching to the model's makes the two agree.
    second = None
    stored_second = previous.get("second_opinion")
    if previous.get("identified_by") == "citizen" and stored_second:
        model = [
            bioindex.TaxonObservation(name=t["name"], confidence=t.get("confidence", 0.0))
            for t in stored_second.get("model_taxa", [])
        ]
        if stored_second.get("available"):
            took_models = [
                secondopinion.label(m)
                for name in review.added_taxa
                if (m := bioindex.resolve(name))
                and any((o := bioindex.resolve(t.name)) and secondopinion.compatible(m, o) for t in model)
            ]
            second = secondopinion.compare(
                taxa,
                model,
                lambda t: bioindex.score(t, index),
                dismissed=[*stored_second.get("dismissed", []), *review.dismissed],
                adopted=[*stored_second.get("adopted", []), *took_models],
            )
            _flag_invasive_suggestions(second, load_seed()[1])
        else:
            second = secondopinion.unavailable(stored_second.get("reason", ""), model)

    penalties = _dedupe([*pressures.penalties, *ecology.penalties])
    certainty, more = certainty_of(region, pressures, ecology, bool(previous.get("photo_kinds")), second)
    hits = [
        InvasiveHit(
            name=i.get("reported_as", i["name"]),
            listed=seeded[i["name"]],
            confidence=i.get("confidence", 1.0),
            in_jurisdiction=i.get("listed_for_this_place", True),
            note=i.get("note"),
        )
        for i in still_listed
        if i["name"] in seeded
    ]

    return Assessment(
        id=uuid.uuid4().hex[:12],
        created_at=datetime.now(UTC).isoformat(),
        site_name=review.site_name or previous.get("site_name"),
        region=region,
        photos=previous.get("photos", 0),
        photo_kinds=list(previous.get("photo_kinds", [])),
        ecology=ecology,
        pressures=pressures,
        signal=signal,
        invasives=hits,
        certainty=certainty,
        penalties=penalties + more,
        needs_confirmation=_confirmation_queue(ecology, pressures, signal, second=second),
        identified_by=previous.get("identified_by", "model"),
        second_opinion=second,
        weather=weather,
        observer=previous.get("observer", "none"),
        model_notes=list(previous.get("model_notes", [])),
        confirmations=_confirmations(pressures, ecology),
        # A review is the same visit, looked at again. Saying so is what stops a
        # careful volunteer's corrections from showing up as a second trip to the
        # stream and inventing a trend that never happened.
        supersedes=previous["id"],
    )
