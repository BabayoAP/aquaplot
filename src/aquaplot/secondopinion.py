"""A second opinion on the citizen's identifications (docs/ASSESSMENT.md, Stage 3b).

When the person identifies the animals in their tray themselves, the vision model
is not asked to replace that answer. It is asked, blind, what it can see in the same
photograph, and this module compares the two lists. The citizen's list is what gets
scored; the model's list only ever produces *questions*:

* **disagree** - you marked a family, the model saw a different one it is easily
  confused with. The card says how to tell them apart.
* **model_only** - the model thinks something is in the tray that you did not mark.
* **unsupported** - you marked a sensitive family the model could not find. Sensitive
  families are the ones that lift a band, so they are the ones worth a second look.

The model is never told what the citizen said. If it were, agreement would be an
echo; asked blind, agreement is independent evidence and disagreement is a real
flag. Each item carries the band the stream would get if the model were right, so
the review can ask about the disagreements that matter first and let the rest go.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .bioindex import BY_FAMILY, EcologicalStatus, Match, TaxonObservation, resolve

MIN_MODEL_CONFIDENCE = 0.5  # below this the model is guessing and gets no vote
SENSITIVE_SCORE = 8

# Classic confusions between groups, with the feature that separates them. Every
# entry is something a volunteer can check in a white tray without a microscope.
CONFUSIONS: dict[frozenset[str], str] = {
    frozenset({"Ephemeroptera", "Plecoptera"}): (
        "Count the tails and look at the sides of the body. Mayfly nymphs usually have three tails and "
        "feathery or plate-like gills along the sides of the abdomen; stonefly nymphs have two tails and "
        "no gills on the abdomen."
    ),
    frozenset({"Ephemeroptera", "Odonata"}): (
        "Look at the tail end. Damselfly nymphs end in three flat, leaf-shaped paddles and have a long, "
        "slender body; mayfly tails are thin threads, and mayflies have gills along the sides."
    ),
    frozenset({"Amphipoda", "Isopoda"}): (
        "Watch how it moves. A freshwater shrimp is flattened side to side and swims or scuttles on its side; "
        "a water hoglouse is flattened top to bottom and walks, like a woodlouse."
    ),
    frozenset({"Diptera", "Annelida"}): (
        "Look for a head. A midge larva (bloodworm) has a small hard head capsule and tiny stumpy legs at "
        "both ends; a sludge worm has no head capsule and no legs at all."
    ),
    frozenset({"Hirudinea", "Turbellaria"}): (
        "Look at the ends. A leech has a sucker at each end and loops along; a flatworm is paper-flat, "
        "has no suckers, glides smoothly and often shows two eye-spots."
    ),
    frozenset({"Trichoptera", "Diptera"}): (
        "Look at the back end and the legs. A caseless caddis larva has three pairs of proper legs behind "
        "the head and two hooks at the tail; fly larvae have no true legs."
    ),
}


GROUP_WORDS: dict[str, str] = {
    "Ephemeroptera": "mayfly", "Plecoptera": "stonefly", "Trichoptera": "caddisfly", "Odonata": "dragonfly or damselfly",
    "Coleoptera": "water beetle", "Diptera": "fly larva", "Gastropoda": "snail", "Bivalvia": "clam or mussel",
    "Hirudinea": "leech", "Amphipoda": "freshwater shrimp", "Isopoda": "water hoglouse", "Decapoda": "crayfish",
    "Annelida": "worm", "Megaloptera": "alderfly larva", "Hemiptera": "water bug", "Turbellaria": "flatworm",
}  # fmt: skip


def label(m: Match) -> str:
    """What a person calls it: the family's plain name, or 'some kind of mayfly' for a group-level answer."""
    if m.family:
        return m.family.plain_name
    return f"some kind of {GROUP_WORDS.get(m.group or '', m.group or 'animal')}"


def how_to_tell(a: Match, b: Match) -> str:
    """The distinguishing feature, if we know one, else the two field descriptions side by side."""
    if a.group and b.group and a.group != b.group:
        known = CONFUSIONS.get(frozenset({a.group, b.group}))
        if known:
            return known
    parts = [f"{label(m)}: {m.family.look_for}" for m in (a, b) if m.family]
    return " / ".join(parts) if parts else "Compare what you see with the ID guide."


def compatible(a: Match, b: Match) -> bool:
    """Do two identifications agree? Same family, or one is order-level and the order matches."""
    if a.family and b.family:
        return a.family.family == b.family.family
    return a.group is not None and a.group == b.group


def confusable(a: Match, b: Match) -> bool:
    return (a.group is not None and a.group == b.group) or frozenset({a.group, b.group}) in CONFUSIONS


def _key(m: Match) -> str:
    return (m.family.family if m.family else f"group:{m.group}").lower()


@dataclass
class SecondOpinion:
    """What the model thought of the citizen's list, and what is still open."""

    available: bool
    reason: str = ""
    agreed: list[str] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    dismissed: list[str] = field(default_factory=list)
    model_taxa: list[dict[str, Any]] = field(default_factory=list)
    adopted: list[str] = field(default_factory=list)  # agreements that exist because the person took the model's answer

    @property
    def open(self) -> list[dict[str, Any]]:
        return [i for i in self.items if i["key"] not in self.dismissed]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SecondOpinion:
        """Rebuild from a stored assessment. Dismissed items were never stored, and do not need to be."""
        return cls(
            available=d.get("available", False),
            reason=d.get("reason", ""),
            agreed=list(d.get("agreed", [])),
            items=list(d.get("open", [])),
            dismissed=list(d.get("dismissed", [])),
            model_taxa=list(d.get("model_taxa", [])),
            adopted=list(d.get("adopted", [])),
        )

    def summary(self) -> str:
        """One sentence for a report: what the independent check found."""
        if not self.available:
            return f"No independent check of the identifications: {self.reason}."
        text = (
            f"A vision model, shown the sample photograph without the observer's identifications, independently "
            f"agreed on {len(self.agreed) - len(self.adopted)} of them"
        )
        if self.adopted:
            text += f"; the observer adopted its identification on {len(self.adopted)} after comparing"
        if self.dismissed:
            text += f"; the observer kept their own identification on {len(self.dismissed)} after comparing"
        if self.open:
            text += f"; {len(self.open)} difference(s) remain unresolved"
        return text + "."

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "agreed": self.agreed,
            "open": self.open,
            "dismissed": self.dismissed,
            "adopted": self.adopted,
            "independent_agreements": len(self.agreed) - len(self.adopted),
            "model_taxa": self.model_taxa,
        }


def compare(
    citizen: Sequence[TaxonObservation],
    model: Sequence[TaxonObservation],
    score: Callable[[list[TaxonObservation]], EcologicalStatus],
    dismissed: Sequence[str] = (),
    adopted: Sequence[str] = (),
) -> SecondOpinion:
    """Compare the citizen's identifications with what the model saw, blind, in the same tray."""
    mine = [(o, m) for o in citizen if (m := resolve(o.name))]
    theirs = [(o, m) for o in model if o.confidence >= MIN_MODEL_CONFIDENCE and (m := resolve(o.name))]
    model_taxa = [{"name": o.name, "confidence": round(o.confidence, 2)} for o in model]

    # A model that named nothing it is sure of has not disagreed with the
    # observer; it has failed to read the tray, and the two are not the same
    # evidence. Compared anyway, every sensitive family the observer got right
    # becomes an "are you sure?", because an unsupported question asks exactly
    # that - and the read-out would go on to say the model "independently agreed
    # on 0 of 4", which reads as a model that looked and disagreed. Whether a
    # specific animal is missing from the model's list is only meaningful once
    # there is a list. Small local vision models return an empty list on tray
    # photographs routinely, so this is the ordinary case on a keyless
    # deployment, not a rare one.
    if mine and not theirs:
        return unavailable(
            "the model did not identify anything it was sure enough of in the sample photo, so there was nothing "
            "to check the identifications against",
            model,
        )

    base = score(list(citizen))
    agreed: list[str] = []
    unsupported: list[tuple[TaxonObservation, Match]] = []
    remaining = list(theirs)
    for obs, match in mine:
        partner = next((pair for pair in remaining if compatible(match, pair[1])), None)
        if partner:
            agreed.append(label(match))
            remaining.remove(partner)
        else:
            unsupported.append((obs, match))

    items: list[dict[str, Any]] = []

    def impact(taxa: list[TaxonObservation]) -> dict[str, Any]:
        other = score(taxa)
        return {"band_if_model_right": other.band.value, "changes_band": other.band != base.band}

    for obs, match in unsupported:
        rivals = sorted((p for p in remaining if confusable(match, p[1])), key=lambda p: -p[0].confidence)
        if rivals:
            m_obs, m_match = rivals[0]
            remaining.remove(rivals[0])
            swapped = [o for o in citizen if o is not obs] + [TaxonObservation(name=m_obs.name, confidence=1.0, confirmed_by="citizen")]
            effect = impact(swapped)
            items.append(
                {
                    "kind": "disagree",
                    "key": f"disagree:{_key(match)}:{_key(m_match)}",
                    "citizen_name": obs.name,
                    "citizen_label": label(match),
                    "model_name": m_obs.name,
                    "model_label": label(m_match),
                    "confidence": round(m_obs.confidence, 2),
                    "question": f"You marked {label(match)}. The model thinks this may be {label(m_match)}. Which is it?",
                    "how_to_tell": how_to_tell(match, m_match),
                    **effect,
                    "priority": 1 if effect["changes_band"] else 2,
                }
            )
        elif match.score >= SENSITIVE_SCORE:
            effect = impact([o for o in citizen if o is not obs])
            items.append(
                {
                    "kind": "unsupported",
                    "key": f"unsupported:{_key(match)}",
                    "citizen_name": obs.name,
                    "citizen_label": label(match),
                    "model_name": None,
                    "model_label": None,
                    "confidence": None,
                    "question": f"The model could not find the {label(match)} you marked. Are you sure it was there?",
                    "how_to_tell": (
                        f"{match.family.look_for} " if match.family else ""
                    ) + "Sensitive animals lift the reading the most, so they are worth a second look. "
                    "It may simply have been out of shot.",
                    **effect,
                    "priority": 1 if effect["changes_band"] else 3,
                }
            )

    for m_obs, m_match in remaining:
        effect = impact([*citizen, TaxonObservation(name=m_obs.name, confidence=1.0, confirmed_by="citizen")])
        look = BY_FAMILY[m_match.family.family.lower()].look_for if m_match.family else ""
        items.append(
            {
                "kind": "model_only",
                "key": f"model_only:{_key(m_match)}",
                "citizen_name": None,
                "citizen_label": None,
                "model_name": m_obs.name,
                "model_label": label(m_match),
                "confidence": round(m_obs.confidence, 2),
                "question": f"The model thinks there may also be {label(m_match)} in your tray. Did you see one?",
                "how_to_tell": look or "Check the tray against the ID guide.",
                **effect,
                "priority": 1 if effect["changes_band"] else 2,
            }
        )

    items.sort(key=lambda i: i["priority"])
    return SecondOpinion(
        available=True,
        agreed=agreed,
        items=items,
        dismissed=list(dict.fromkeys(dismissed)),
        model_taxa=model_taxa,
        adopted=[a for a in dict.fromkeys(adopted) if a in agreed],
    )


def unavailable(reason: str, model: Sequence[TaxonObservation] = ()) -> SecondOpinion:
    return SecondOpinion(
        available=False, reason=reason, model_taxa=[{"name": o.name, "confidence": round(o.confidence, 2)} for o in model]
    )
