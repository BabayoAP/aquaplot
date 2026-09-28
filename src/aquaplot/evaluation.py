"""Measure the second opinion on labelled photos (docs/EVALUATION.md).

The claim AquaPlot makes for its model is narrow on purpose: not "it identifies
larvae", but "it catches the mistakes a volunteer makes". That claim can be
measured, and this module measures it on any folder of photos whose contents are
known:

1. **What the model sees.** For each photo, the model's list is compared with the
   true families: right to family, right only to order, wrong, or missed. Answering
   at order level is counted separately from being wrong, because saying "some kind
   of mayfly" when it cannot tell is the behaviour the prompt asks for.
2. **Mistakes caught.** For each true family, a realistic volunteer mistake is
   simulated - the same animal recorded as a family it is commonly confused with -
   and the second opinion is run against the model's real output for that photo.
   A mistake counts as caught when the review would ask about it.
3. **False alarms.** The second opinion is run on the *correct* list. Any question
   it raises there is noise a volunteer would have to wade through.

Only step 1 calls the model, once per photo. Steps 2 and 3 are pure functions of
its stored output, so they cost nothing to rerun when the rules change.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import bioindex
from .bioindex import BY_FAMILY, CATALOGUE, TaxonObservation, resolve
from .secondopinion import CONFUSIONS, MIN_MODEL_CONFIDENCE, compare


@dataclass
class Case:
    """One labelled photo."""

    photo: str
    truth: list[str]  # family names, as in data/bioindicators.json
    note: str = ""


@dataclass
class Outcome:
    case: Case
    photo_kind: str
    model_taxa: list[TaxonObservation]
    error: str | None = None


def load_labels(path: Path) -> list[Case]:
    """``photo,families[,note]`` with families separated by ``;``. Unknown names are an error, not a skip."""
    cases = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            names = [n.strip() for n in (row.get("families") or "").split(";") if n.strip()]
            unknown = [n for n in names if resolve(n) is None or resolve(n).family is None]
            if unknown:
                raise ValueError(f"{row['photo']}: not a family in the catalogue: {', '.join(unknown)}")
            cases.append(Case(photo=row["photo"], truth=[resolve(n).family.family for n in names], note=row.get("note", "")))
    return cases


def mistakes_for(family: str) -> list[str]:
    """Families a volunteer plausibly records instead of this one: same group, or a known confusion."""
    f = BY_FAMILY[family.lower()]
    partner_groups = {g for pair in CONFUSIONS for g in pair if f.group in pair and g != f.group}
    return [c.family for c in CATALOGUE if c.family != f.family and (c.group == f.group or c.group in partner_groups)]


@dataclass
class Report:
    photos: int = 0
    unusable: int = 0
    truths: int = 0
    family_right: int = 0
    order_only: int = 0
    wrong: int = 0
    missed: int = 0
    model_extras: int = 0
    mistakes: int = 0
    caught: int = 0
    caught_with_right_answer: int = 0
    false_alarm_photos: int = 0
    false_alarm_questions: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)

    def rate(self, part: int, whole: int) -> str:
        return f"{100 * part / whole:.0f}%" if whole else "n/a"

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "rows"} | {"rows": self.rows}

    def markdown(self, observer: str) -> str:
        usable = self.photos - self.unusable
        lines = [
            f"# Second-opinion evaluation ({observer})",
            "",
            f"{self.photos} labelled photos, {usable} usable, {self.truths} animals in them.",
            "",
            "## What the model sees",
            "",
            "| | Count | Share of animals |",
            "|---|---|---|",
            f"| Right to family | {self.family_right} | {self.rate(self.family_right, self.truths)} |",
            f"| Right to order only (declined to guess the family) | {self.order_only} | {self.rate(self.order_only, self.truths)} |",
            f"| Wrong | {self.wrong} | {self.rate(self.wrong, self.truths)} |",
            f"| Missed | {self.missed} | {self.rate(self.missed, self.truths)} |",
            "",
            f"It also reported {self.model_extras} animal(s) that were not in the labels.",
            "",
            "## Does it catch a volunteer's mistake?",
            "",
            f"Each true animal was swapped for a family it is commonly confused with: {self.mistakes} simulated mistakes.",
            "",
            f"- **Caught** (the review would ask about it): {self.caught} ({self.rate(self.caught, self.mistakes)})",
            f"- **Caught and suggested the right animal:** {self.caught_with_right_answer} "
            f"({self.rate(self.caught_with_right_answer, self.mistakes)})",
            "",
            "## False alarms when the volunteer was right",
            "",
            f"- Photos where a correct list still drew a question: {self.false_alarm_photos} of {usable} "
            f"({self.rate(self.false_alarm_photos, usable)})",
            f"- Questions raised in total: {self.false_alarm_questions}",
            "",
            "Mistakes towards a *tolerant* family are only caught when the model sees the real animal: "
            "by design the review does not question a tolerant family it merely failed to find, because "
            "that cannot lift the band.",
        ]
        return "\n".join(lines) + "\n"


def score_outcomes(outcomes: list[Outcome]) -> Report:
    """Everything after the model call. Pure, so it can be rerun whenever the rules change."""
    r = Report(photos=len(outcomes))
    for o in outcomes:
        if o.error or o.photo_kind == "not_a_stream":
            r.unusable += 1
            r.rows.append({"photo": o.case.photo, "unusable": o.error or "model said not a stream"})
            continue
        seen = [(t, m) for t in o.model_taxa if t.confidence >= MIN_MODEL_CONFIDENCE and (m := resolve(t.name))]
        used: set[int] = set()
        row: dict[str, Any] = {"photo": o.case.photo, "truth": o.case.truth, "model": [t.name for t in o.model_taxa]}
        for fam in o.case.truth:
            f = BY_FAMILY[fam.lower()]
            r.truths += 1
            exact = next((i for i, (_, m) in enumerate(seen) if i not in used and m.family and m.family.family == f.family), None)
            coarse = next((i for i, (_, m) in enumerate(seen) if i not in used and not m.family and m.group == f.group), None)
            if exact is not None:
                r.family_right += 1
                used.add(exact)
            elif coarse is not None:
                r.order_only += 1
                used.add(coarse)
            else:
                wrong = next((i for i, (_, m) in enumerate(seen) if i not in used and m.group == f.group), None)
                if wrong is not None:
                    r.wrong += 1
                    used.add(wrong)
                else:
                    r.missed += 1
        r.model_extras += len(seen) - len(used)

        truth_obs = [TaxonObservation(name=n, confirmed_by="citizen") for n in o.case.truth]
        clean = compare(truth_obs, o.model_taxa, bioindex.score)
        if clean.open:
            r.false_alarm_photos += 1
            r.false_alarm_questions += len(clean.open)
        row["false_alarms"] = [i["question"] for i in clean.open]

        caught_here = 0
        for fam in o.case.truth:
            for wrong_family in mistakes_for(fam):
                r.mistakes += 1
                citizen = [t for t in truth_obs if t.name != fam] + [TaxonObservation(name=wrong_family, confirmed_by="citizen")]
                op = compare(citizen, o.model_taxa, bioindex.score)
                flagged = [
                    i for i in op.open
                    if i.get("citizen_name") == wrong_family
                    or (i["kind"] == "model_only" and _is(i["model_name"], fam))
                ]
                if flagged:
                    r.caught += 1
                    caught_here += 1
                    if any(i.get("model_name") and _is(i["model_name"], fam) for i in flagged):
                        r.caught_with_right_answer += 1
        row["mistakes_caught"] = caught_here
        r.rows.append(row)
    return r


def _is(name: str, family: str) -> bool:
    m = resolve(name)
    return bool(m and m.family and m.family.family == family)
