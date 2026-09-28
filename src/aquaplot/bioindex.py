"""Biotic index from the invertebrates a citizen found in a stream (PRD §6.3, FR-3).

The question this module answers is the oldest one in freshwater ecology: *given
the animals living on the stream bed, how healthy is the water?* Benthic
macroinvertebrates answer it better than a spot chemical reading because they
cannot leave. A sample integrates weeks of conditions, so it catches the sewage
misconnection that discharged on Tuesday and was gone by the time anyone sampled.
OneAquaHealth's field protocols put this group first for urban streams, which is
why AquaPlot's whole assessment hangs off it.

The index is BMWP/ASPT, or its Iberian adaptation IBMWP/IASPT where the
coordinates resolve to Portugal or Spain (docs/ASSESSMENT.md, Stage 4):

* Every family carries a score from 1 (survives almost anything) to 10 (only in
  clean, cold, well-oxygenated water). ``data/bioindicators.json`` holds both
  tables; a family an index does not score is recorded but adds nothing to it.
* **BMWP** is the sum of the scores of the families present. It rewards finding
  more families, so it is sensitive to how hard someone looked.
* **ASPT** is BMWP divided by the number of scoring families: the *average*
  sensitivity of what lives there. It barely moves with sampling effort, so it is
  the number this module bands on and the one a phone-based assessment can
  honestly report.
* **EPT** counts the families in Ephemeroptera, Plecoptera and Trichoptera
  (mayflies, stoneflies, caddisflies). They are the first to disappear, so their
  presence or absence is the single most legible signal for a non-specialist.

The band names are the Water Framework Directive's five classes, because that is
the vocabulary European city authorities already act on. AquaPlot reports a
*screening* band, never a WFD classification: a real classification needs a
standardised kick-sample, laboratory identification and a reference-site
comparison (see ``EcologicalStatus.caveat`` and docs/ASSESSMENT.md).

Honesty rules baked in here, not bolted on later:

* Effort caps the claim. Three families found under one stone cannot earn *High*,
  so ``richness_cap`` lowers an over-confident band and says why.
* Identification uncertainty is carried, not averaged away. Each observation
  arrives with a confidence, and the returned ``confidence`` falls when the
  identifications behind the band were shaky.
* Unmatched taxa are reported, never silently dropped: a name this module could
  not place is a hole in the evidence and appears in ``unmatched``.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import resources
from typing import Any

EPT_ORDERS = frozenset({"Ephemeroptera", "Plecoptera", "Trichoptera"})

# ASPT thresholds. The classical British reading of ASPT is "above 6, clean;
# 5-6, doubtful; 4-5, probable moderate pollution; below 4, probable severe
# pollution". These cut points keep that reading and split it across the WFD's
# five classes so the output speaks the language a city water department uses.
ASPT_BANDS: tuple[tuple[float, str], ...] = (
    (6.5, "High"),
    (5.6, "Good"),
    (4.6, "Moderate"),
    (3.6, "Poor"),
)

# How many scoring families a sample must contain before a band may be claimed.
# A citizen who turns two stones and finds one mayfly has not shown the stream is
# pristine; they have shown a mayfly lives there.
RICHNESS_CAP: tuple[tuple[int, str], ...] = (
    (8, "High"),
    (5, "Good"),
    (2, "Moderate"),
    (1, "Poor"),
)

MIN_FAMILIES_FOR_INDEX = 1
FIRM_SAMPLE_FAMILIES = 3  # below this, the reading is thin in either direction


class Band(StrEnum):
    """Water Framework Directive ecological status classes, best first."""

    HIGH = "High"
    GOOD = "Good"
    MODERATE = "Moderate"
    POOR = "Poor"
    BAD = "Bad"

    @property
    def rank(self) -> int:
        return BAND_ORDER.index(self)

    def worse_of(self, other: "Band") -> "Band":
        return self if self.rank >= other.rank else other


BAND_ORDER: tuple[Band, ...] = (Band.HIGH, Band.GOOD, Band.MODERATE, Band.POOR, Band.BAD)

BAND_MEANING: dict[Band, str] = {
    Band.HIGH: "The invertebrates here are the ones that only live in clean, well-oxygenated water.",
    Band.GOOD: "A healthy mix, including some sensitive animals. The stream is working.",
    Band.MODERATE: "Sensitive animals are thinning out. Something is putting the stream under pressure.",
    Band.POOR: "Mostly pollution-tolerant animals. The stream is degraded and losing its sensitive species.",
    Band.BAD: "Almost nothing but the animals that survive very low oxygen. This stretch is in serious trouble.",
}


@dataclass(frozen=True, slots=True)
class Family:
    """One row of ``data/bioindicators.json``. A score of None means that index does not score the family."""

    family: str
    common_name: str
    group: str
    bmwp: int | None
    ept: bool
    plain_name: str
    look_for: str
    means: str
    vector: bool = False
    ibmwp: int | None = None

    @property
    def reference_score(self) -> int | None:
        """The score used to describe the animal to a person, whichever index is in use."""
        return self.bmwp if self.bmwp is not None else self.ibmwp

    @property
    def sensitivity(self) -> str:
        s = self.reference_score
        if s is None:
            return "not scored"
        if s >= 8:
            return "sensitive"
        if s >= 5:
            return "moderate"
        return "tolerant"


@dataclass(frozen=True, slots=True)
class BioticIndex:
    """A family-score table, and what to call its total and its mean.

    ``total_classes`` are the index's own classes read from the total score, where
    it has published ones. They assume a standardised multi-habitat sample, which a
    citizen's tray is not, so the screening band is always read from the mean and
    the total class is reported beside it as a reference that understates a small
    sample.
    """

    key: str
    name: str
    total: str
    mean: str
    citation: str
    total_classes: tuple[tuple[float, str], ...] = ()

    def family_score(self, f: Family) -> int | None:
        return getattr(f, self.key)

    def total_class(self, total: float) -> "Band | None":
        if not self.total_classes:
            return None
        for threshold, name in self.total_classes:
            if total >= threshold:
                return Band(name)
        return Band.BAD


BMWP = BioticIndex("bmwp", "BMWP / ASPT", "BMWP", "ASPT", "Armitage et al. (1983)")
IBMWP = BioticIndex(
    "ibmwp",
    "IBMWP / IASPT",
    "IBMWP",
    "IASPT",
    "Alba-Tercedor et al. (2002), family scores as in MAGRAMA (2011)",
    # Alba-Tercedor's quality classes on the total: >100, 61-100, 36-60, 16-35, <=15.
    total_classes=((101, "High"), (61, "Good"), (36, "Moderate"), (16, "Poor")),
)
INDICES: dict[str, BioticIndex] = {i.key: i for i in (BMWP, IBMWP)}

# Countries whose national practice is built on the Iberian adaptation. Matched
# against the country iNaturalist resolves from the coordinates, by code or name.
IBERIAN_COUNTRIES = frozenset({"pt", "es", "ad", "portugal", "spain", "españa", "andorra"})


def index_for(country_names: list[str]) -> BioticIndex:
    """The index to use where these coordinates resolved to. BMWP unless the country is Iberian."""
    return IBMWP if any(n.strip().lower() in IBERIAN_COUNTRIES for n in country_names if n) else BMWP


def _load() -> tuple[str, list[Family]]:
    raw = json.loads(resources.files("aquaplot.data").joinpath("bioindicators.json").read_text(encoding="utf-8"))
    return raw["version"], [Family(**row) for row in raw["families"]]


CATALOGUE_VERSION, CATALOGUE = _load()
BY_FAMILY: dict[str, Family] = {f.family.lower(): f for f in CATALOGUE}


# Median family score per order, for the honest half-answer. A citizen photo
# often supports "that is a stonefly" and no more; refusing to score that throws
# away the most informative thing they saw. The result is marked ``coarse`` and
# carries a certainty penalty rather than being passed off as a family-level ID.
def _group_scores(index: BioticIndex) -> dict[str, float]:
    out: dict[str, float] = {}
    for group in {f.group for f in CATALOGUE}:
        scores = [s for f in CATALOGUE if f.group == group and (s := index.family_score(f)) is not None]
        if scores:
            out[group] = statistics.median(scores)
    return out


GROUP_SCORES_BY_INDEX: dict[str, dict[str, float]] = {key: _group_scores(i) for key, i in INDICES.items()}
GROUP_SCORES: dict[str, float] = GROUP_SCORES_BY_INDEX["bmwp"]
# An order that only one index scores still needs a reference score for resolve().
REFERENCE_GROUP_SCORES: dict[str, float] = {**GROUP_SCORES_BY_INDEX["ibmwp"], **GROUP_SCORES}

# Genus and vernacular spellings a vision model or a citizen actually types.
# Kept small and explicit: a wrong alias silently changes a stream's band, so
# every entry is one a reviewer can check by eye.
ALIASES: dict[str, str] = {
    "gammarus": "Gammaridae",
    "asellus": "Asellidae",
    "tubifex": "Oligochaeta",
    "tubificidae": "Oligochaeta",
    "naididae": "Oligochaeta",
    "lumbriculidae": "Oligochaeta",
    "clitellata": "Oligochaeta",
    "oligochaete": "Oligochaeta",
    "baetis": "Baetidae",
    "ecdyonurus": "Heptageniidae",
    "rhithrogena": "Heptageniidae",
    "hydropsyche": "Hydropsychidae",
    "rhyacophila": "Rhyacophilidae",
    "chironomus": "Chironomidae",
    "bloodworm": "Chironomidae",
    "bloodworms": "Chironomidae",
    "simulium": "Simuliidae",
    "culex": "Culicidae",
    "aedes": "Culicidae",
    "anopheles": "Culicidae",
    "culiseta": "Culicidae",
    "mosquito": "Culicidae",
    "mosquito larva": "Culicidae",
    "eristalis": "Syrphidae",
    "rat-tailed maggot": "Syrphidae",
    "dreissena": "Dreissenidae",
    "dreissena polymorpha": "Dreissenidae",
    "zebra mussel": "Dreissenidae",
    "potamopyrgus": "Hydrobiidae",
    "potamopyrgus antipodarum": "Hydrobiidae",
    "ancylus": "Ancylidae",
    "planorbis": "Planorbidae",
    "lymnaea": "Lymnaeidae",
    "radix": "Lymnaeidae",
    "physa": "Physidae",
    "physella": "Physidae",
    "erpobdella": "Erpobdellidae",
    "pisidium": "Sphaeriidae",
    "sphaerium": "Sphaeriidae",
    "austropotamobius": "Astacidae",
    "astacus": "Astacidae",
    "procambarus": "Cambaridae",
    "pacifastacus": "Cambaridae",
    "faxonius": "Cambaridae",
    "orconectes": "Cambaridae",
    "red swamp crayfish": "Cambaridae",
    "signal crayfish": "Cambaridae",
    "marbled crayfish": "Cambaridae",
    "calopteryx": "Calopterygidae",
    "agriidae": "Calopterygidae",
    "coenagriidae": "Coenagrionidae",
    "ischnura": "Coenagrionidae",
    "scirtidae": "Hydrophilidae",
    "planaria": "Planariidae",
    "dugesia": "Planariidae",
    "polycelis": "Planariidae",
    "leech": "Erpobdellidae",
    "leeches": "Erpobdellidae",
    "water louse": "Asellidae",
    "water hoglouse": "Asellidae",
    "hoglouse": "Asellidae",
    "freshwater shrimp": "Gammaridae",
    "sludge worm": "Oligochaeta",
    "sludge worms": "Oligochaeta",
    "riffle beetle": "Elmidae",
    "river limpet": "Ancylidae",
    "pea clam": "Sphaeriidae",
}

# Order names, as a model might return them. Value is the order used against
# GROUP_SCORES; the extra spellings exist because "mayfly" is what people say.
GROUP_ALIASES: dict[str, str] = {
    "ephemeroptera": "Ephemeroptera",
    "mayfly": "Ephemeroptera",
    "mayflies": "Ephemeroptera",
    "plecoptera": "Plecoptera",
    "stonefly": "Plecoptera",
    "stoneflies": "Plecoptera",
    "trichoptera": "Trichoptera",
    "caddisfly": "Trichoptera",
    "caddisflies": "Trichoptera",
    "odonata": "Odonata",
    "dragonfly": "Odonata",
    "damselfly": "Odonata",
    "coleoptera": "Coleoptera",
    "water beetle": "Coleoptera",
    "diptera": "Diptera",
    "true fly": "Diptera",
    "fly larva": "Diptera",
    "gastropoda": "Gastropoda",
    "snail": "Gastropoda",
    "snails": "Gastropoda",
    "bivalvia": "Bivalvia",
    "mussel": "Bivalvia",
    "clam": "Bivalvia",
    "hirudinea": "Hirudinea",
    "amphipoda": "Amphipoda",
    "isopoda": "Isopoda",
    "decapoda": "Decapoda",
    "crayfish": "Decapoda",
    "annelida": "Annelida",
    "megaloptera": "Megaloptera",
    "hemiptera": "Hemiptera",
    "turbellaria": "Turbellaria",
    "flatworm": "Turbellaria",
}


def _normalise(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


@dataclass(frozen=True, slots=True)
class Match:
    """What a submitted taxon name resolved to.

    ``coarse`` is True when only the order was recognised, so the score is the
    order's median rather than a family's own. That distinction is the difference
    between "a Heptageniidae was found" and "something mayfly-shaped was found",
    and the pipeline must be able to see it.
    """

    name: str  # exactly what the caller submitted
    family: Family | None
    group: str | None
    score: float
    coarse: bool

    @property
    def ept(self) -> bool:
        return self.family.ept if self.family else (self.group in EPT_ORDERS)

    @property
    def label(self) -> str:
        if self.family:
            return self.family.plain_name
        return f"{self.group or self.name} (group only)"


def resolve(name: str) -> Match | None:
    """Family name, genus, vernacular name or order to a scoreable Match, else None.

    Species binomials resolve through their genus ("Gammarus pulex" to
    Gammaridae), which is exactly right here: BMWP scores families, so the
    species half of the name carries no extra index information.
    """
    key = _normalise(name)
    if not key:
        return None
    for candidate in (key, ALIASES.get(key, ""), key.split()[0], ALIASES.get(key.split()[0], "")):
        if candidate and candidate.lower() in BY_FAMILY:
            fam = BY_FAMILY[candidate.lower()]
            return Match(name=name, family=fam, group=fam.group, score=float(fam.reference_score or 0), coarse=False)
        if candidate and candidate in ALIASES and ALIASES[candidate].lower() in BY_FAMILY:
            fam = BY_FAMILY[ALIASES[candidate].lower()]
            return Match(name=name, family=fam, group=fam.group, score=float(fam.reference_score or 0), coarse=False)
    group = GROUP_ALIASES.get(key) or GROUP_ALIASES.get(key.split()[0])
    if group and group in REFERENCE_GROUP_SCORES:
        return Match(name=name, family=None, group=group, score=REFERENCE_GROUP_SCORES[group], coarse=True)
    return None


@dataclass(frozen=True, slots=True)
class TaxonObservation:
    """One animal a citizen or the model says was present.

    ``confidence`` is the identification confidence in [0, 1]; ``confirmed_by``
    records human-in-the-loop review (Track 3). A citizen who ticks "yes, that is
    a mayfly" raises the confidence of that single observation to certainty,
    which is the whole point of keeping people in the loop rather than trusting
    the model's own number.
    """

    name: str
    confidence: float = 1.0
    abundance: int | None = None  # individuals seen, when counted
    confirmed_by: str | None = None  # "citizen" once a person has ticked it

    @property
    def effective_confidence(self) -> float:
        return 1.0 if self.confirmed_by else max(0.0, min(1.0, self.confidence))


@dataclass(frozen=True, slots=True)
class ScoredTaxon:
    name: str
    plain_name: str
    family: str | None
    group: str | None
    score: float
    sensitivity: str
    ept: bool
    coarse: bool
    confidence: float
    confirmed: bool
    means: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "plain_name": self.plain_name,
            "family": self.family,
            "group": self.group,
            "bmwp": self.score,
            "sensitivity": self.sensitivity,
            "ept": self.ept,
            "family_level": not self.coarse,
            "confidence": round(self.confidence, 2),
            "confirmed": self.confirmed,
            "means": self.means,
        }


@dataclass
class EcologicalStatus:
    """The banded answer, with everything needed to argue with it."""

    band: Band
    bmwp: float
    aspt: float | None
    families: int
    ept_families: int
    sensitive_families: int
    tolerant_families: int
    confidence: float
    scored: list[ScoredTaxon] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    vectors: list[str] = field(default_factory=list)
    evidence_limited: bool = False
    capped: bool = False  # the richness cap lowered the band the index alone would have given
    catalogue_version: str = CATALOGUE_VERSION
    index: BioticIndex = BMWP
    recorded: list[ScoredTaxon] = field(default_factory=list)  # identified, but this index does not score them
    total_class: Band | None = None  # the index's own class from the total, where it publishes one

    @property
    def meaning(self) -> str:
        if not self.evidence_limited:
            return BAND_MEANING[self.band]
        if self.capped:
            return (
                f"Provisional: too few animals were found to claim better than '{self.band.value}'. "
                "That is a limit of the sample, not proof that the stream is degraded - look again, "
                "turning more stones, to firm it up."
            )
        return (
            f"Provisional: '{self.band.value}' rests on only {self.families} "
            f"famil{'y' if self.families == 1 else 'ies'}. {BAND_MEANING[self.band]} A fuller sample would settle it."
        )

    @property
    def caveat(self) -> str:
        return (
            f"Screening estimate from a photo-based sample using {self.index.total} family scores "
            f"({self.index.citation}), banded on {self.index.mean}; not a Water Framework Directive "
            "classification. A formal classification needs a standardised kick sample, laboratory "
            "identification and comparison against a reference site."
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "band": self.band.value,
            "meaning": self.meaning,
            # "bmwp" and "aspt" hold the total and the mean of whichever index was used;
            # the names predate the second index and are kept so stored rows still read.
            "bmwp": round(self.bmwp, 1),
            "aspt": round(self.aspt, 2) if self.aspt is not None else None,
            "index_key": self.index.key,
            "total_label": self.index.total,
            "mean_label": self.index.mean,
            "citation": self.index.citation,
            "total_class": self.total_class.value if self.total_class else None,
            "families": self.families,
            "ept_families": self.ept_families,
            "sensitive_families": self.sensitive_families,
            "tolerant_families": self.tolerant_families,
            "confidence": round(self.confidence, 1),
            "taxa": [t.as_dict() | {"scored": True} for t in self.scored]
            + [t.as_dict() | {"scored": False, "bmwp": None} for t in self.recorded],
            "unmatched": self.unmatched,
            "signals": self.signals,
            "penalties": self.penalties,
            "vectors": self.vectors,
            "evidence_limited": self.evidence_limited,
            "capped_by_effort": self.capped,
            "catalogue_version": self.catalogue_version,
            "index": self.index.name,
            "caveat": self.caveat,
        }


def _band_for_aspt(aspt: float) -> Band:
    for threshold, name in ASPT_BANDS:
        if aspt >= threshold:
            return Band(name)
    return Band.BAD


def _richness_cap(families: int) -> Band:
    """The best band this much evidence is allowed to support."""
    for needed, name in RICHNESS_CAP:
        if families >= needed:
            return Band(name)
    return Band.BAD


def score(observations: list[TaxonObservation], index: BioticIndex = BMWP) -> EcologicalStatus:
    """Turn a list of identified animals into a banded ecological status.

    Duplicate families collapse to one entry, because BMWP scores *families
    present*, not individuals: ten bloodworms and one bloodworm are the same
    evidence about the family living there. The highest-confidence submission for
    a family wins, so a citizen-confirmed sighting outranks a shaky model guess
    for the same animal.

    A family the chosen index does not score (an introduced crayfish under BMWP,
    say) is kept in ``recorded``: it still counts as seen, still feeds the One
    Health rules and the invasive check, and adds nothing to the index.
    """
    group_scores = GROUP_SCORES_BY_INDEX[index.key]
    by_family: dict[str, tuple[Match, TaxonObservation]] = {}
    unmatched: list[str] = []
    for obs in observations:
        match = resolve(obs.name)
        if match is None:
            if obs.name.strip():
                unmatched.append(obs.name.strip())
            continue
        key = (match.family.family if match.family else f"group:{match.group}").lower()
        current = by_family.get(key)
        if current is None or obs.effective_confidence > current[1].effective_confidence:
            by_family[key] = (match, obs)

    # A coarse order-level entry adds nothing once a family from that order is in.
    family_groups = {m.group for m, _ in by_family.values() if not m.coarse}
    for key in [k for k, (m, _) in by_family.items() if m.coarse and m.group in family_groups]:
        del by_family[key]

    def index_score(match: Match) -> float | None:
        if match.family:
            s = index.family_score(match.family)
            return None if s is None else float(s)
        return group_scores.get(match.group or "")

    def entry(match: Match, obs: TaxonObservation, value: float | None) -> ScoredTaxon:
        return ScoredTaxon(
            name=obs.name,
            plain_name=match.label,
            family=match.family.family if match.family else None,
            group=match.group,
            score=value if value is not None else 0.0,
            sensitivity=(match.family.sensitivity if match.family else _coarse_sensitivity(value or 0.0))
            if value is not None
            else "not scored",
            ept=match.ept,
            coarse=match.coarse,
            confidence=obs.effective_confidence,
            confirmed=obs.confirmed_by is not None,
            means=match.family.means if match.family else f"Recognised only as far as {match.group}; the family would sharpen this.",
        )

    valued = [(m, o, index_score(m)) for m, o in by_family.values()]
    scored = [entry(m, o, v) for m, o, v in sorted((x for x in valued if x[2] is not None), key=lambda x: -x[2])]
    recorded = [entry(m, o, None) for m, o, v in valued if v is None]
    all_seen = [*scored, *recorded]
    vectors = sorted({t.plain_name for t in all_seen if t.family and BY_FAMILY[t.family.lower()].vector})
    not_scored_signal = (
        [
            f"Also recorded but not scored by {index.total}: {', '.join(sorted(t.plain_name for t in recorded))}. "
            "They still count for the health and invasive-species checks."
        ]
        if recorded
        else []
    )

    penalties: list[str] = []
    if unmatched:
        penalties.append(
            f"{len(unmatched)} reported taxon/taxa could not be matched to a scoring family "
            f"({', '.join(sorted(set(unmatched))[:4])}); they contributed nothing to the score"
        )

    if len(scored) < MIN_FAMILIES_FOR_INDEX:
        # The placeholder never depends on ``unmatched``. A name this catalogue
        # could not place is a hole in the evidence, not evidence of pollution:
        # it is usually a typo, a common name, or a family from outside Europe.
        # Banding those as 'Bad' would make reporting an animal we cannot score
        # look worse than reporting nothing at all, and would put a false alarm
        # in front of the volunteer who tried hardest to name what they found.
        return EcologicalStatus(
            band=Band.MODERATE,
            bmwp=0.0,
            aspt=None,
            families=0,
            ept_families=0,
            sensitive_families=0,
            tolerant_families=0,
            confidence=0.0,
            scored=[],
            unmatched=unmatched,
            signals=["No scoreable invertebrates were identified, so the biological index could not be calculated.", *not_scored_signal],
            evidence_limited=True,
            penalties=penalties + ["no scoreable invertebrates identified; the band is a placeholder, not a reading"],
            vectors=vectors,
            index=index,
            recorded=recorded,
        )

    bmwp = sum(t.score for t in scored)
    aspt = bmwp / len(scored)
    ept_families = sum(1 for t in scored if t.ept)
    sensitive = sum(1 for t in scored if t.score >= 8)
    tolerant = sum(1 for t in scored if t.score <= 3)

    band = _band_for_aspt(aspt)
    cap = _richness_cap(len(scored))
    capped = band.worse_of(cap)
    if capped is not band:
        penalties.append(
            f"only {len(scored)} scoring famil{'y' if len(scored) == 1 else 'ies'} were found, "
            f"which cannot support a '{band.value}' reading; capped at '{capped.value}'"
        )
    band = capped
    # Thin in either direction. A cap that bit means the sample was too small to
    # claim good; a sample of two tolerant families is equally too small to
    # declare a stream dead. Both are limits of the evidence, not findings.
    capped_from = _band_for_aspt(aspt)
    evidence_limited = capped is not capped_from or len(scored) < FIRM_SAMPLE_FAMILIES

    coarse = [t for t in scored if t.coarse]
    if coarse:
        penalties.append(
            f"{len(coarse)} animal(s) were identified only to order ({', '.join(sorted({t.group or '?' for t in coarse}))}); "
            "the group's median score was used"
        )
    shaky = [t for t in scored if t.confidence < 0.6 and not t.confirmed]
    if shaky:
        penalties.append(f"{len(shaky)} identification(s) were below 60 % confidence and no person has confirmed them")

    signals = _signals(scored, ept_families, sensitive, tolerant, aspt, index) + not_scored_signal
    total_class = index.total_class(bmwp)
    if total_class is not None:
        signals.append(
            f"The {index.total} total is {bmwp:.0f}. On {index.total}'s own scale that is class '{total_class.value}', "
            "but that scale assumes a standardised sample across every habitat in the reach; one tray finds far fewer "
            f"families, so the total reads low. The band above is read from the {index.mean} instead."
        )

    # Confidence in the band: how sure we are of the animals, softened by how
    # thin the sample is and how much of it is only order-level.
    id_confidence = statistics.mean([t.confidence for t in scored])
    effort = min(1.0, len(scored) / 8)
    resolution = 1.0 - 0.3 * (len(coarse) / len(scored))
    confidence = round(100 * id_confidence * (0.55 + 0.45 * effort) * resolution, 1)

    return EcologicalStatus(
        band=band,
        bmwp=bmwp,
        aspt=aspt,
        families=len(scored),
        ept_families=ept_families,
        sensitive_families=sensitive,
        tolerant_families=tolerant,
        confidence=confidence,
        scored=scored,
        unmatched=unmatched,
        signals=signals,
        penalties=penalties,
        vectors=vectors,
        evidence_limited=evidence_limited,
        capped=capped is not capped_from,
        index=index,
        recorded=recorded,
        total_class=total_class,
    )


def _coarse_sensitivity(score_value: float) -> str:
    if score_value >= 8:
        return "sensitive"
    if score_value >= 5:
        return "moderate"
    return "tolerant"


def _signals(
    scored: list[ScoredTaxon], ept: int, sensitive: int, tolerant: int, aspt: float, index: BioticIndex = BMWP
) -> list[str]:
    """Plain-language readings of the sample, in the order a person would notice them."""
    out: list[str] = []
    if ept == 0:
        out.append(
            "No mayflies, stoneflies or caddisflies were found. These three groups are the first to "
            "disappear when oxygen drops or pollution arrives, so their absence is the clearest warning sign in the sample."
        )
    else:
        names = sorted({t.group for t in scored if t.ept and t.group})
        out.append(
            f"{ept} sensitive famil{'y' if ept == 1 else 'ies'} from the mayfly/stonefly/caddisfly groups "
            f"({', '.join(names)}) were found. These animals do not persist in polluted water."
        )
    if tolerant and tolerant == len(scored):
        out.append(
            "Everything identified is a pollution-tolerant animal. That pattern points to organic "
            "enrichment - sewage, run-off or decomposing material using up the oxygen."
        )
    elif tolerant > sensitive and tolerant:
        out.append(
            f"Tolerant animals outnumber sensitive ones ({tolerant} to {sensitive}), the usual signature of a "
            "stream under continuous pressure rather than a one-off spill."
        )
    if sensitive >= 3:
        out.append(f"{sensitive} families scoring 8 or more were present, which is characteristic of a well-oxygenated stretch.")
    if any(t.family == "Oligochaeta" for t in scored) and any(t.family == "Chironomidae" for t in scored) and ept == 0:
        out.append(
            "Sludge worms and bloodworms together, with no sensitive families, is the classic community of an "
            "oxygen-starved bed. Look upstream for a discharge or a misconnected drain."
        )
    out.append(f"Average sensitivity of the families present ({index.mean}) is {aspt:.1f} out of 10.")
    return out
