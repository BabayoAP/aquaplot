"""One Health reasoning: what a stream reading means for people and animals (FR-5).

This is the module the hackathon is actually about. Everything upstream produces
*ecology*: a band, a pressure score, a list of animals. None of that answers the
question a resident, a parent or a city public-health officer is asking, which is
"so what, for us?". OneAquaHealth's premise is that the two are one question -
degraded urban water produces pathogens, disease vectors, exposure and lost
wellbeing - and this module is where AquaPlot makes that link explicit instead of
implying it.

It is a **rule engine, deliberately not a model.** Every finding carries the rule
that fired, the evidence that triggered it, and an action. Three reasons:

* A health-adjacent claim must be auditable. "Do not let your dog in the water"
  has to be traceable to "the model reported a blue-green surface bloom", not to
  a weight in a network.
* The rules encode published public-health practice, and a reviewer with domain
  knowledge can read this file and correct it. That is not true of a fine-tune.
* An LLM is the right tool for turning a photo into structured observations, and
  the wrong tool for deciding whether to warn a parent. The split is the point.

Levels are ``ok`` < ``watch`` < ``concern`` < ``alert``. ``alert`` means a person
should change what they do today; it is reserved for rules with a direct exposure
pathway, and the module refuses to raise one on model-only evidence that no human
has confirmed - it downgrades and says the confirmation is what is missing.

Nothing here is a medical or regulatory determination. Every output carries
``DISCLAIMER`` and names the authority that can make one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

from .bioindex import Band, EcologicalStatus
from .habitat import HabitatPressure
from .weather import Weather

DISCLAIMER = (
    "AquaPlot is a citizen-science screening tool. It is not a medical, water-quality or "
    "regulatory determination. If a finding concerns you, report it to your local water "
    "authority or environmental agency, who can sample and test."
)


class Domain(StrEnum):
    ECOSYSTEM = "ecosystem"
    HUMAN = "human"
    ANIMAL = "animal"


class Level(StrEnum):
    OK = "ok"
    WATCH = "watch"
    CONCERN = "concern"
    ALERT = "alert"

    @property
    def rank(self) -> int:
        return LEVEL_ORDER.index(self)


LEVEL_ORDER: tuple[Level, ...] = (Level.OK, Level.WATCH, Level.CONCERN, Level.ALERT)

# When two domains tie at the same level, the human consequence leads. A person
# reading one sentence should hear "keep out of the water" before "ASPT is 2.0".
HEADLINE_PRIORITY: tuple[Domain, ...] = (Domain.HUMAN, Domain.ANIMAL, Domain.ECOSYSTEM)

DOMAIN_TITLE = {
    Domain.ECOSYSTEM: "Ecosystem health",
    Domain.HUMAN: "Human health",
    Domain.ANIMAL: "Animal health",
}


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str  # stable id, so a finding can be argued with, suppressed or audited
    domain: Domain
    level: Level
    title: str
    because: tuple[str, ...]  # the evidence, in the words the observer used
    action: str
    confirmed: bool = True  # False when the trigger rests on unconfirmed model output

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "domain": self.domain.value,
            "level": self.level.value,
            "title": self.title,
            "because": list(self.because),
            "action": self.action,
            "needs_confirmation": not self.confirmed,
        }


@dataclass
class Signal:
    """The whole One Health read-out for one assessment."""

    levels: dict[Domain, Level]
    findings: list[Finding]
    headline: str
    actions_now: list[str] = field(default_factory=list)
    actions_community: list[str] = field(default_factory=list)
    actions_authority: list[str] = field(default_factory=list)

    @property
    def worst(self) -> Level:
        return max(self.levels.values(), key=lambda level: level.rank)

    def as_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "overall": self.worst.value,
            "domains": [
                {
                    "domain": d.value,
                    "title": DOMAIN_TITLE[d],
                    "level": self.levels[d].value,
                    "findings": [f.as_dict() for f in self.findings if f.domain is d],
                }
                for d in Domain
            ],
            "actions": {
                "you_now": self.actions_now,
                "your_community": self.actions_community,
                "the_authority": self.actions_authority,
            },
            "disclaimer": DISCLAIMER,
        }


@dataclass(frozen=True, slots=True)
class Context:
    """Everything the rules read. Assembled by ``assess.py``."""

    status: EcologicalStatus
    habitat: HabitatPressure
    invasives: tuple[str, ...] = ()  # listed invasive species recognised at the site
    site_name: str | None = None
    warm_season: bool = True  # mosquito development is temperature-driven
    weather: Weather | None = None  # the 48 hours either side of the visit, when they could be had

    def answer(self, key: str) -> str | None:
        return self.habitat.value(key)

    def source_of(self, key: str) -> str | None:
        return next((r.source for r in (*self.habitat.readings, *self.habitat.exposure) if r.key == key), None)

    def confirmed(self, *keys: str) -> bool:
        return all(self.source_of(k) == "citizen" for k in keys)

    @property
    def contact(self) -> bool:
        """Is anyone actually exposed to this water?"""
        return self.answer("access") in ("contact", "play_or_drinking")

    @property
    def high_contact(self) -> bool:
        return self.answer("access") == "play_or_drinking"


Rule = Callable[[Context], Finding | None]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


def _escalate(level: Level, ctx: Context, when_contact: Level) -> Level:
    """Exposure turns a water-quality problem into a health problem."""
    return when_contact if ctx.contact and when_contact.rank > level.rank else level


# ---- Human health ------------------------------------------------------------


@rule
def cyanobacteria(ctx: Context) -> Finding | None:
    """Blue-green blooms are the one visual sign with an acute human pathway."""
    if ctx.answer("algae") != "bloom":
        return None
    level = Level.ALERT if ctx.contact else Level.CONCERN
    return Finding(
        rule="human.cyanobacteria",
        domain=Domain.HUMAN,
        level=level,
        title="Possible harmful algal bloom - avoid contact with the water",
        because=(
            "a surface bloom, scum or paint-like mat was recorded",
            *(("people or dogs get into the water here",) if ctx.contact else ()),
        ),
        action=(
            "Keep out of the water and keep children and dogs out, including from spray. Do not let animals "
            "drink it. Report the bloom to your local environmental agency - only a laboratory can confirm "
            "whether it is toxin-producing cyanobacteria."
        ),
        confirmed=ctx.confirmed("algae"),
    )


@rule
def faecal_contamination(ctx: Context) -> Finding | None:
    """Sewage indicators. Any one of these is enough; together they are conclusive enough to act on."""
    evidence = []
    if ctx.answer("odour") == "sewage":
        evidence.append("a sewage or rotten-egg smell was reported at the bank")
    if ctx.answer("litter") == "sanitary":
        evidence.append("wet wipes or sanitary waste were caught on the banks, which only arrive via a sewer overflow")
    if ctx.answer("water_colour") in ("grey", "black"):
        evidence.append(f"the water was recorded as {ctx.answer('water_colour')}")
    if ctx.answer("foam_or_sheen") == "white_foam":
        evidence.append("persistent white foam was recorded, which suggests detergent from a misconnected drain")
    if not evidence:
        return None
    level = Level.CONCERN if len(evidence) == 1 else Level.ALERT
    level = _escalate(level, ctx, Level.ALERT)
    # The weather does not make the sewage more or less real; it says where it came from.
    w = ctx.weather
    if w is not None and w.heavy_rain_before:
        evidence.append(
            f"{w.rain_past_48h_mm:g} mm of rain fell in the 48 hours before, which is consistent with a storm overflow"
        )
    elif w is not None and w.dry_before:
        evidence.append(
            "it had not rained in the 48 hours before, so an overflow is unlikely; a misconnected drain or a leak is the "
            "more likely source"
        )
    return Finding(
        rule="human.faecal_contamination",
        domain=Domain.HUMAN,
        level=level,
        title="Signs of sewage reaching the stream",
        because=tuple(evidence),
        action=(
            "Do not enter the water and wash your hands before eating. Report it to the water company and the "
            "environmental regulator today, with the time, the photo and this location - overflow and "
            "misconnection cases are made from exactly this kind of dated citizen record."
        ),
        confirmed=ctx.confirmed(*[k for k in ("odour", "litter", "water_colour", "foam_or_sheen") if ctx.answer(k)][:1]),
    )


@rule
def mosquito_breeding(ctx: Context) -> Finding | None:
    """The vector pathway OneAquaHealth tracks: standing urban water plus warmth."""
    stagnant = ctx.answer("flow") in ("stagnant", "slow")
    larvae = any("Mosquito" in v for v in ctx.status.vectors)
    if not (stagnant or larvae):
        return None
    evidence = []
    if larvae:
        evidence.append("mosquito larvae were identified in the sample")
    if stagnant:
        evidence.append(f"the water was {'standing with no flow' if ctx.answer('flow') == 'stagnant' else 'barely moving'}")
    if ctx.answer("litter") in ("scattered", "heavy"):
        evidence.append("litter was present, and containers hold the small pockets of water mosquitoes prefer")
    if not ctx.warm_season:
        evidence.append("the season is cool, so development is slow at present")
    level = Level.CONCERN if (larvae and stagnant and ctx.warm_season) else Level.WATCH
    return Finding(
        rule="human.vector_breeding",
        domain=Domain.HUMAN,
        level=level,
        title="Conditions suit mosquito breeding",
        because=tuple(evidence),
        action=(
            "Remove containers and litter that hold water near the bank, and tell the municipality about standing "
            "water that does not drain. Restoring flow is the durable fix; insecticide is not, and it removes the "
            "stream's own insect life along with the mosquitoes."
        ),
        confirmed=ctx.confirmed("flow") if not larvae else True,
    )


@rule
def chemical_sheen(ctx: Context) -> Finding | None:
    if ctx.answer("foam_or_sheen") != "oil_sheen" and ctx.answer("odour") != "chemical" and ctx.answer("water_colour") != "orange":
        return None
    evidence = []
    if ctx.answer("foam_or_sheen") == "oil_sheen":
        evidence.append("a rainbow film was seen on the surface, typical of oil or fuel from a road drain")
    if ctx.answer("odour") == "chemical":
        evidence.append("a chemical or solvent smell was reported")
    if ctx.answer("water_colour") == "orange":
        evidence.append("the water was orange or rust-red, which points to iron or drainage through made ground")
    return Finding(
        rule="human.chemical_exposure",
        domain=Domain.HUMAN,
        level=_escalate(Level.CONCERN, ctx, Level.ALERT),
        title="Possible chemical contamination",
        because=tuple(evidence),
        action=(
            "Keep out of the water and do not disturb the sediment. Report it with the location and time - a "
            "fresh sheen is traceable upstream to its outfall, an old one is not."
        ),
        confirmed=ctx.confirmed("foam_or_sheen") or ctx.confirmed("odour"),
    )


@rule
def storm_runoff(ctx: Context) -> Finding | None:
    """The first flush: an urban stream is at its dirtiest in the days after heavy rain."""
    w = ctx.weather
    if w is None or not w.heavy_rain_before:
        return None
    return Finding(
        rule="human.storm_runoff",
        domain=Domain.HUMAN,
        level=Level.CONCERN if ctx.contact else Level.WATCH,
        title="Heavy rain has just washed the streets into this stream",
        because=(
            f"{w.rain_past_48h_mm:g} mm of rain fell here in the 48 hours before this check (Open-Meteo)",
            "after heavy rain an urban stream carries road run-off and, where sewers are combined, overflow; "
            "bacteria stay high for one to three days",
            *(("people or dogs get into the water here",) if ctx.contact else ()),
        ),
        action=(
            "Stay out of the water, keep dogs out, and wash hands after any contact until two dry days have passed. "
            "A reading taken this soon after rain shows the stream at its worst: check it again in dry weather "
            "before drawing conclusions from the difference."
        ),
    )


@rule
def rain_ahead(ctx: Context) -> Finding | None:
    """The early warning: heavy rain is forecast, so contact with the water should be planned around it."""
    w = ctx.weather
    if w is None or not w.heavy_rain_ahead:
        return None
    # A site that has already shown sewage is the one where rain is most likely to set an overflow running.
    sewage_seen = ctx.answer("odour") == "sewage" or ctx.answer("litter") == "sanitary"
    return Finding(
        rule="human.rain_ahead",
        domain=Domain.HUMAN,
        level=Level.CONCERN if sewage_seen else Level.WATCH,
        title="Heavy rain is forecast - plan water contact around it",
        because=(
            f"{w.rain_next_48h_mm:g} mm of rain is forecast here in the next 48 hours (Open-Meteo)",
            *(("sewage signs have been recorded here, so rain is likely to set an overflow running",) if sewage_seen else ()),
        ),
        action=(
            "Put off paddling, dog swims and river-day kick samples until two dry days after the rain. If you can, "
            "come back within a day of it: a before-and-after pair at the same spot is the clearest evidence of "
            "whether an overflow feeds this stream."
        ),
    )


@rule
def wellbeing(ctx: Context) -> Finding | None:
    """The other half of One Health: what a stream in good condition gives people."""
    if ctx.status.band.rank > Band.GOOD.rank or ctx.habitat.pressure >= 25:
        return None
    return Finding(
        rule="human.wellbeing",
        domain=Domain.HUMAN,
        level=Level.OK,
        title="A stream in this condition is a public-health asset",
        because=(
            f"the biological reading is '{ctx.status.band.value}' with low visible pressure",
            "accessible, clean urban water lowers heat stress, supports recreation and measurably improves mental wellbeing",
        ),
        action="Keep recording it. Evidence that a stretch is in good condition is what protects it from the next development proposal.",
    )


# ---- Animal health -----------------------------------------------------------


@rule
def animal_drinking(ctx: Context) -> Finding | None:
    hazards = []
    if ctx.answer("algae") == "bloom":
        hazards.append("a surface algal bloom, which can produce toxins that kill dogs within hours of drinking or swimming")
    if ctx.answer("odour") == "sewage" or ctx.answer("litter") == "sanitary":
        hazards.append("signs of sewage, which carries pathogens that affect dogs and livestock as well as people")
    if ctx.answer("water_colour") in ("grey", "black") or ctx.answer("odour") == "chemical":
        hazards.append("discoloured or chemically smelling water")
    if not hazards:
        return None
    drinking = ctx.high_contact
    return Finding(
        rule="animal.drinking_water",
        domain=Domain.ANIMAL,
        level=Level.ALERT if drinking else Level.CONCERN,
        title="Do not let animals drink here or swim",
        because=tuple(hazards + (["animals were recorded drinking from or entering this water"] if drinking else [])),
        action="Keep dogs on a lead past this stretch and carry water for them. Warn other owners; a sign at the access point works.",
        confirmed=ctx.confirmed("algae") or ctx.confirmed("odour"),
    )


@rule
def parasite_hosts(ctx: Context) -> Finding | None:
    hosts = [v for v in ctx.status.vectors if "snail" in v.lower()]
    if not hosts or not ctx.contact:
        return None
    return Finding(
        rule="animal.parasite_hosts",
        domain=Domain.ANIMAL,
        level=Level.WATCH,
        title="Snails that can host water-borne parasites are present",
        because=(
            f"{', '.join(hosts)} were identified",
            "these families host flukes whose larvae cause swimmer's itch in people and liver fluke in grazing animals",
            "people or animals enter this water",
        ),
        action="Not a reason to avoid the stream, but do not let livestock graze the wet margin, and rinse off after wading.",
    )


@rule
def invasive_pressure(ctx: Context) -> Finding | None:
    if not ctx.invasives:
        return None
    return Finding(
        rule="animal.invasive_species",
        domain=Domain.ANIMAL,
        level=Level.CONCERN,
        title="Invasive species recorded at this site",
        because=(
            f"{', '.join(ctx.invasives)} was identified here",
            "invasive freshwater species displace native ones, and some carry diseases native species have no defence against - "
            "introduced crayfish spread crayfish plague, which is lethal to European native crayfish",
        ),
        action=(
            "Do not move animals, plants or wet equipment between water bodies. Check, clean and dry boots and nets "
            "before your next visit, and record the sighting - early detection is the only cheap stage of an invasion."
        ),
    )


# ---- Ecosystem ---------------------------------------------------------------


@rule
def biological_condition(ctx: Context) -> Finding | None:
    band = ctx.status.band
    level = {
        Band.HIGH: Level.OK,
        Band.GOOD: Level.OK,
        Band.MODERATE: Level.WATCH,
        Band.POOR: Level.CONCERN,
        Band.BAD: Level.ALERT,
    }[band]
    if ctx.status.evidence_limited and level.rank > Level.CONCERN.rank:
        # A thin sample can raise a concern. It cannot, on its own, declare a stream dead.
        level = Level.CONCERN
    because = [ctx.status.meaning]
    if ctx.status.aspt is not None:
        because.append(
            f"{ctx.status.families} scoring famil{'y' if ctx.status.families == 1 else 'ies'} were identified, "
            f"average sensitivity ({ctx.status.index.mean}) {ctx.status.aspt:.1f}, of which {ctx.status.ept_families} are mayflies, stoneflies or caddisflies"
        )
    return Finding(
        rule="ecosystem.biological_condition",
        domain=Domain.ECOSYSTEM,
        level=level,
        title=f"Biological condition: {band.value}" + (" (provisional)" if ctx.status.evidence_limited else ""),
        because=tuple(because),
        action=(
            "Repeat this check at the same spot each season. A single reading is a snapshot; a series is evidence."
            if level.rank <= Level.WATCH.rank
            else "Repeat the check upstream and downstream of this point. Where the invertebrates change is where the problem enters."
        ),
        confirmed=not ctx.status.evidence_limited,
    )


@rule
def habitat_degradation(ctx: Context) -> Finding | None:
    structural = [
        ctx.answer("bank_modification") == "fully_channelised",
        ctx.answer("substrate") == "concrete",
        ctx.answer("riparian_vegetation") in ("bare_or_paved", "mown_grass"),
    ]
    if not any(structural):
        return None
    because = []
    if ctx.answer("bank_modification") == "fully_channelised":
        because.append("the channel is concrete or culverted, so there is nowhere for invertebrates, plants or fish to live")
    elif ctx.answer("bank_modification") == "partly_reinforced":
        because.append("the banks are partly reinforced")
    if ctx.answer("substrate") == "concrete":
        because.append("the bed is artificial, so the gaps between stones that larvae need do not exist")
    if ctx.answer("riparian_vegetation") == "bare_or_paved":
        because.append("there is no vegetated buffer, so run-off reaches the water unfiltered")
    elif ctx.answer("riparian_vegetation") == "mown_grass":
        because.append("mown grass runs to the water's edge, which filters and shades far less than a natural margin")
    return Finding(
        rule="ecosystem.habitat_degradation",
        domain=Domain.ECOSYSTEM,
        level=Level.CONCERN if sum(structural) >= 2 else Level.WATCH,
        title="Physical habitat is the limiting factor here",
        because=tuple(because),
        action=(
            "Water quality alone will not fix this stretch. Ask your municipality about de-culverting, softening "
            "the banks and letting a margin grow unmown - the cheapest of those is simply mowing less."
        ),
    )


@rule
def thermal_and_drought(ctx: Context) -> Finding | None:
    if ctx.answer("shade") != "open" and ctx.answer("flow") not in ("dry", "stagnant"):
        return None
    because = []
    if ctx.answer("shade") == "open":
        because.append("the water is fully exposed to the sun, so it warms and loses oxygen on hot days")
    if ctx.answer("flow") == "dry":
        because.append("the bed was dry, which is a climate-resilience signal worth dating precisely")
    elif ctx.answer("flow") == "stagnant":
        because.append("flow has stopped, leaving isolated pools that heat and deoxygenate")
    return Finding(
        rule="ecosystem.thermal_resilience",
        domain=Domain.ECOSYSTEM,
        level=Level.WATCH if ctx.answer("flow") not in ("dry", "stagnant") else Level.CONCERN,
        title="Low resilience to heat and drought",
        because=tuple(because),
        action=(
            "Record the date each time you find it dry or stagnant. Planting bankside trees is the single most "
            "effective local action: shade holds summer temperature down by several degrees."
        ),
    )


@rule
def heat_ahead(ctx: Context) -> Finding | None:
    """A hot spell on water that is open, slow or choked with algae is an oxygen crash waiting for a still night."""
    w = ctx.weather
    if w is None or not w.heat_ahead:
        return None
    exposed = []
    if ctx.answer("shade") == "open":
        exposed.append("the water is fully exposed to the sun")
    if ctx.answer("flow") in ("slow", "stagnant"):
        exposed.append("the water is barely moving")
    if ctx.answer("algae") in ("extensive", "bloom"):
        exposed.append("there is a lot of algae, which uses up oxygen overnight")
    if not exposed:
        return None
    return Finding(
        rule="ecosystem.heat_ahead",
        domain=Domain.ECOSYSTEM,
        level=Level.CONCERN if len(exposed) >= 2 else Level.WATCH,
        title="A hot spell is forecast and this water has little defence against it",
        because=(f"up to {w.max_temp_next_48h_c:g} °C is forecast here in the next 48 hours (Open-Meteo)", *exposed),
        action=(
            "If you can, look again at dawn during the heat, when oxygen is lowest: fish gasping at the surface or "
            "dead fish should be reported to the environmental agency at once, because an oxygen crash can be "
            "mitigated only while it is happening."
        ),
    )


@rule
def sedimentation(ctx: Context) -> Finding | None:
    if ctx.answer("sediment_deposit") != "heavy" and ctx.answer("water_clarity") not in ("turbid", "opaque"):
        return None
    because = []
    if ctx.answer("sediment_deposit") == "heavy":
        because.append("thick silt or black sludge covers the bed, so the spaces sensitive larvae live in are filled")
    if ctx.answer("water_clarity") in ("turbid", "opaque"):
        because.append(f"the water was {ctx.answer('water_clarity').replace('_', ' ')}")
        if ctx.weather is not None and ctx.weather.heavy_rain_before:
            because.append(f"{ctx.weather.rain_past_48h_mm:g} mm of rain fell in the previous 48 hours, so some of the cloudiness is storm-driven")
        elif ctx.weather is not None and ctx.weather.dry_before:
            because.append("it had not rained in the previous 48 hours, so the cloudiness has a constant source")
    return Finding(
        rule="ecosystem.sedimentation",
        domain=Domain.ECOSYSTEM,
        level=Level.CONCERN if ctx.answer("sediment_deposit") == "heavy" else Level.WATCH,
        title="Sediment is smothering the bed",
        because=tuple(because),
        action=(
            "Look upstream for bare soil, construction or a road drain discharging directly. Note whether it had "
            "rained in the previous day: storm-driven turbidity and constant turbidity have different causes."
        ),
    )


# ---- Assembly ----------------------------------------------------------------


def evaluate(ctx: Context) -> Signal:
    """Run every rule, downgrade what no person has confirmed, and assemble the read-out."""
    findings: list[Finding] = []
    for r in RULES:
        found = r(ctx)
        if found is None:
            continue
        if found.level is Level.ALERT and not found.confirmed:
            # An alert tells someone to change their behaviour today. AquaPlot will
            # not do that on the strength of a model's unreviewed guess; it asks
            # for the tick instead.
            found = Finding(
                rule=found.rule,
                domain=found.domain,
                level=Level.CONCERN,
                title=found.title,
                because=(*found.because, "held below alert level because no person has confirmed the observation behind it"),
                action=found.action + " Confirm the observation in the app to raise this to a full alert.",
                confirmed=False,
            )
        findings.append(found)

    levels = {d: Level.OK for d in Domain}
    for f in findings:
        if f.level.rank > levels[f.domain].rank:
            levels[f.domain] = f.level
    findings.sort(key=lambda f: (-f.level.rank, HEADLINE_PRIORITY.index(f.domain)))

    return Signal(
        levels=levels,
        findings=findings,
        headline=_headline(ctx, levels, findings),
        actions_now=_dedupe(f.action for f in findings if f.level.rank >= Level.CONCERN.rank),
        actions_community=_community_actions(ctx, findings),
        actions_authority=_authority_actions(ctx, findings),
    )


def _dedupe(items) -> list[str]:
    seen: list[str] = []
    for i in items:
        if i not in seen:
            seen.append(i)
    return seen


def _headline(ctx: Context, levels: dict[Domain, Level], findings: list[Finding]) -> str:
    where = ctx.site_name or "This stretch"
    band = ctx.status.band.value
    worst = max(levels.values(), key=lambda level: level.rank)
    if worst is Level.OK:
        return f"{where} reads {band.lower()} biologically, with nothing visible that puts people or animals at risk."
    top = next(f for f in findings if f.level is worst)
    who = {Domain.HUMAN: "for people", Domain.ANIMAL: "for animals", Domain.ECOSYSTEM: "for the stream itself"}[top.domain]
    return f"{where} reads {band.lower()} biologically. The clearest issue {who} is: {top.title.lower()}."


def _community_actions(ctx: Context, findings: list[Finding]) -> list[str]:
    out = [
        "Check the same spot again in a month. AquaPlot compares readings at a site over time, and a trend is what "
        "moves a municipality when a single complaint does not."
    ]
    if any(f.rule == "ecosystem.habitat_degradation" for f in findings):
        out.append("Ask your local authority to leave a two-metre margin unmown along the bank. It costs less than mowing it.")
    if any(f.rule.startswith("human.") and f.level.rank >= Level.CONCERN.rank for f in findings):
        out.append("Tell other people who use this stretch what you found, and put the date on it.")
    if ctx.habitat.value("litter") in ("scattered", "heavy"):
        out.append("A litter pick here is worth organising, and it is the easiest way to get neighbours to the water's edge.")
    if any(f.rule == "animal.invasive_species" for f in findings):
        out.append("Run a 'check, clean, dry' reminder for anyone who uses the water - it is how invasions are slowed.")
    return out


def _authority_actions(ctx: Context, findings: list[Finding]) -> list[str]:
    out: list[str] = []
    if any(f.rule == "human.faecal_contamination" for f in findings):
        w = ctx.weather
        if w is not None and w.heavy_rain_before:
            out.append("Check the overflow event records for outfalls upstream of this point: the sewage signs followed heavy rain.")
        elif w is not None and w.dry_before:
            out.append("Trace the surface-water network upstream for misconnected foul drains: the sewage signs appeared in dry weather, when overflows should not be running.")
        else:
            out.append("Trace the sewer network upstream of this point for misconnections and overflow activations around this date.")
    if any(f.rule == "human.cyanobacteria" for f in findings):
        out.append("Sample for cyanobacteria and toxins, and sign the access points until results are back.")
    if any(f.rule == "human.chemical_exposure" for f in findings):
        out.append("Inspect surface-water outfalls upstream; a fresh sheen is traceable, a weathered one is not.")
    if ctx.status.band.rank >= Band.POOR.rank and not ctx.status.evidence_limited:
        out.append("This reach warrants a standardised kick-sample: the citizen screening puts it below good status.")
    if any(f.rule == "ecosystem.thermal_resilience" for f in findings):
        out.append("Include this reach in riparian shading and de-culverting programmes; it is thermally exposed.")
    if any(f.rule == "human.vector_breeding" for f in findings):
        out.append("Add this point to the vector-surveillance round; standing water plus urban warmth is the breeding combination.")
    return out
