"""Visual site characterisation: the pressures you can see without a laboratory (FR-4).

Invertebrates say *how healthy the stream is*. They do not say *why*. A stretch
scoring Poor because it was concreted in 1968 needs a different intervention from
one scoring Poor because a foul sewer is misconnected upstream, and a citizen
standing on the bank can tell those apart in ten seconds - if someone asks the
right questions in words they already use.

So this module is a structured field form, not a free-text note. Its vocabulary
lives in ``data/habitat_indicators.json`` and drives four things from that one
file: the vision model's output schema, this module's validation, the questions
the guided workflow asks, and the pressure arithmetic below. Adding an indicator
is one edit to the JSON.

Two decisions worth naming:

* **Some indicators are not visible in a photo.** Smell is the clearest example:
  it separates a stream cloudy from yesterday's rain from a sewage discharge, and
  no camera reports it. Those fields are marked ``photo_visible: false``, the
  model is never asked for them, and the workflow puts them to the person. This
  is the concrete reason a human stays in the loop rather than a slogan about it.
* **Exposure is not pressure.** Whether children paddle here does not make the
  water dirtier, but it decides whether dirty water is a public-health problem.
  Indicators flagged ``exposure`` are kept out of the pressure score and handed
  to ``onehealth.py`` instead.

The output is a 0-100 pressure score - 0 meaning nothing visible is wrong - with
every indicator's contribution itemised, because a single number nobody can take
apart is not evidence a city can act on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

MAX_SCORE = 3  # the 0-3 scale every indicator option uses


@dataclass(frozen=True, slots=True)
class Option:
    value: str
    label: str
    score: int | None  # None = "cannot tell"; contributes nothing and is reported as a gap
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Indicator:
    key: str
    question: str
    why: str
    weight: float
    photo_visible: bool
    options: tuple[Option, ...]
    exposure: bool = False

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(o.value for o in self.options)

    def option(self, value: str) -> Option | None:
        return next((o for o in self.options if o.value == value), None)


def _load() -> tuple[str, list[Indicator]]:
    raw = json.loads(resources.files("aquaplot.data").joinpath("habitat_indicators.json").read_text())
    indicators = [
        Indicator(
            key=row["key"],
            question=row["question"],
            why=row["why"],
            weight=float(row.get("weight", 1.0)),
            photo_visible=bool(row.get("photo_visible", True)),
            exposure=bool(row.get("exposure", False)),
            options=tuple(Option(value=o["value"], label=o["label"], score=o.get("score"), note=o.get("note")) for o in row["options"]),
        )
        for row in raw["indicators"]
    ]
    return raw["version"], indicators


FORM_VERSION, INDICATORS = _load()
BY_KEY: dict[str, Indicator] = {i.key: i for i in INDICATORS}
PHOTO_INDICATORS: tuple[Indicator, ...] = tuple(i for i in INDICATORS if i.photo_visible)
PERSON_ONLY: tuple[Indicator, ...] = tuple(i for i in INDICATORS if not i.photo_visible)
EXPOSURE_KEYS: frozenset[str] = frozenset(i.key for i in INDICATORS if i.exposure)


def form_schema() -> dict[str, Any]:
    """The whole vocabulary, as the UI and the docs consume it."""
    return {
        "version": FORM_VERSION,
        "indicators": [
            {
                "key": i.key,
                "question": i.question,
                "why": i.why,
                "photo_visible": i.photo_visible,
                "exposure": i.exposure,
                "options": [{"value": o.value, "label": o.label, "note": o.note} for o in i.options],
            }
            for i in INDICATORS
        ],
    }


def model_vocabulary() -> str:
    """The photo-judgeable part of the form, rendered for the vision model's prompt.

    Generated rather than hand-written so the prompt cannot drift away from the
    options the server will accept - the classic failure of prompt-plus-validator
    pairs maintained separately.
    """
    lines = []
    for i in PHOTO_INDICATORS:
        opts = " | ".join(f"{o.value}" for o in i.options)
        lines.append(f"- {i.key}: one of [{opts}]. {i.question} {i.why}")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Reading:
    """One indicator answered, by whoever answered it."""

    key: str
    value: str
    source: str = "model"  # model | citizen
    confidence: float = 1.0

    @property
    def effective_confidence(self) -> float:
        return 1.0 if self.source == "citizen" else max(0.0, min(1.0, self.confidence))


@dataclass(frozen=True, slots=True)
class ScoredReading:
    key: str
    question: str
    value: str
    label: str
    score: int | None
    weight: float
    source: str
    confidence: float
    note: str | None
    why: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "question": self.question,
            "value": self.value,
            "label": self.label,
            "score": self.score,
            "source": self.source,
            "confidence": round(self.confidence, 2),
            "note": self.note,
            "why": self.why,
        }


@dataclass
class HabitatPressure:
    pressure: float  # 0-100; 0 = nothing visibly wrong
    band: str  # none | low | moderate | high | severe
    readings: list[ScoredReading] = field(default_factory=list)
    exposure: list[ScoredReading] = field(default_factory=list)
    top_pressures: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)  # option notes that demand action
    missing: list[str] = field(default_factory=list)  # questions nobody answered
    unanswered_by_person: list[str] = field(default_factory=list)  # person-only questions still open
    invalid: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    form_version: str = FORM_VERSION

    @property
    def answered(self) -> int:
        return len([r for r in self.readings if r.score is not None])

    def value(self, key: str) -> str | None:
        return next((r.value for r in (*self.readings, *self.exposure) if r.key == key), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pressure": round(self.pressure, 1),
            "band": self.band,
            "answered": self.answered,
            "of": len([i for i in INDICATORS if not i.exposure]),
            "readings": [r.as_dict() for r in self.readings],
            "exposure": [r.as_dict() for r in self.exposure],
            "top_pressures": self.top_pressures,
            "flags": self.flags,
            "missing": self.missing,
            "ask_the_person": self.unanswered_by_person,
            "invalid": self.invalid,
            "penalties": self.penalties,
            "form_version": self.form_version,
        }


PRESSURE_BANDS: tuple[tuple[float, str], ...] = ((70, "severe"), (45, "high"), (25, "moderate"), (10, "low"))


def band_for(pressure: float) -> str:
    for threshold, name in PRESSURE_BANDS:
        if pressure >= threshold:
            return name
    return "none"


def assess(readings: list[Reading]) -> HabitatPressure:
    """Score a set of answers. Later answers for the same indicator win, and a
    citizen's answer always beats the model's, which is what makes the review
    step in the workflow real rather than decorative.
    """
    chosen: dict[str, Reading] = {}
    invalid: list[str] = []
    for r in readings:
        indicator = BY_KEY.get(r.key)
        if indicator is None or indicator.option(r.value) is None:
            invalid.append(f"{r.key}={r.value}")
            continue
        current = chosen.get(r.key)
        if current is None or (r.source == "citizen") or (current.source != "citizen"):
            chosen[r.key] = r

    scored: list[ScoredReading] = []
    exposure: list[ScoredReading] = []
    for indicator in INDICATORS:
        r = chosen.get(indicator.key)
        if r is None:
            continue
        opt = indicator.option(r.value)
        assert opt is not None  # validated above
        row = ScoredReading(
            key=indicator.key,
            question=indicator.question,
            value=opt.value,
            label=opt.label,
            score=opt.score,
            weight=indicator.weight,
            source=r.source,
            confidence=r.effective_confidence,
            note=opt.note,
            why=indicator.why,
        )
        (exposure if indicator.exposure else scored).append(row)

    answered = [r for r in scored if r.score is not None]
    weighted = sum(r.score * r.weight for r in answered)
    possible = sum(MAX_SCORE * r.weight for r in answered)
    pressure = 100 * weighted / possible if possible else 0.0

    top = [
        r.label.split(" - ")[0].rstrip(".")
        for r in sorted(answered, key=lambda r: -(r.score or 0) * r.weight)
        if (r.score or 0) >= 2
    ][:4]
    flags = [f"{r.label}: {r.note}" for r in (*scored, *exposure) if r.note and (r.score or 0) >= 2]

    missing = [i.key for i in INDICATORS if not i.exposure and i.key not in chosen]
    cannot_tell = [r.key for r in scored if r.score is None]
    unanswered_person = [i.key for i in PERSON_ONLY if i.key not in chosen or chosen[i.key].source != "citizen"]

    penalties: list[str] = []
    if invalid:
        penalties.append(f"{len(invalid)} habitat answer(s) were outside the form's vocabulary and were discarded: {', '.join(invalid[:4])}")
    if missing:
        penalties.append(f"{len(missing)} habitat question(s) went unanswered ({', '.join(missing)}), so the pressure score covers less of the site")
    if cannot_tell:
        penalties.append(f"{len(cannot_tell)} question(s) were answered 'cannot tell' ({', '.join(cannot_tell)})")
    model_only = [r for r in answered if r.source == "model"]
    if model_only and len(model_only) == len(answered):
        penalties.append("every habitat answer came from the model; no person has confirmed any of them")
    shaky = [r for r in answered if r.source == "model" and r.confidence < 0.6]
    if shaky:
        penalties.append(f"{len(shaky)} habitat answer(s) were low-confidence model guesses ({', '.join(r.key for r in shaky)})")

    return HabitatPressure(
        pressure=pressure,
        band=band_for(pressure),
        readings=scored,
        exposure=exposure,
        top_pressures=top,
        flags=flags,
        missing=missing,
        unanswered_by_person=unanswered_person,
        invalid=invalid,
        penalties=penalties,
    )
