#!/usr/bin/env python3
"""Measure the *rule* layer of the second opinion, with no model and no photos.

``evaluate_observer.py`` answers "can the model see what is in the tray?", and it
needs a model and labelled photographs. This script answers the other half, which
needs neither:

    Given an observer of a stated quality, how much of a volunteer's mistake does
    the review catch, and how much noise does a volunteer who was right have to
    wade through?

That is a question about ``secondopinion.py``, not about any model, so it is
answered by handing ``evaluation.score_outcomes`` a *synthetic* observer whose
error rate is set by hand and swept. Two things make the answer worth having:

* It is the design question. AquaPlot's claim is that a model is worth asking
  even when it is wrong a good deal of the time, because it only ever raises
  questions. This puts a number on "a good deal".
* It reruns in a second whenever a rule changes, so a regression in the review
  logic shows up as a falling catch rate rather than as nothing at all.

**What this does not measure.** It says nothing about whether a vision model can
identify a mayfly nymph in a phone photograph. The observer here is a simulation
with a dial on it, not a model, and the trays are drawn from the catalogue rather
than photographed in a stream. The model's real accuracy is
``evaluate_observer.py``, it needs an API key and labelled photos, and no number
here substitutes for it. Method and reading guide: docs/EVALUATION.md.

    .venv/bin/python scripts/evaluate_rules.py
    .venv/bin/python scripts/evaluate_rules.py --repeats 200 --markdown
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aquaplot.bioindex import BY_FAMILY, TaxonObservation  # noqa: E402
from aquaplot.evaluation import Case, Outcome, score_outcomes  # noqa: E402

# Six trays spanning the range a European urban stream actually produces, from a
# clean upland riffle to a drain. They are written as families so the sweep
# exercises real BMWP scores and real confusion pairs, not invented ones.
TRAYS: dict[str, list[str]] = {
    "clean upland riffle": ["Perlidae", "Heptageniidae", "Rhyacophilidae", "Gammaridae", "Elmidae"],
    "clean lowland reach": ["Leptoceridae", "Baetidae", "Goeridae", "Ancylidae", "Elmidae"],
    "moderate urban reach": ["Baetidae", "Hydropsychidae", "Gammaridae", "Asellidae", "Physidae"],
    "degraded, silted": ["Asellidae", "Chironomidae", "Oligochaeta", "Erpobdellidae"],
    "foul, near-anoxic": ["Chironomidae", "Oligochaeta"],
    "mixed EPT": ["Caenidae", "Leuctridae", "Limnephilidae", "Gammaridae"],
}

# The two ways a real vision model falls short, as independent dials:
#   miss   - it does not report an animal that is there
#   coarse - it reports the order ("some kind of mayfly") instead of the family,
#            which the prompt explicitly allows and which is not an error
GRID = [(0.0, 0.0), (0.0, 0.3), (0.2, 0.0), (0.2, 0.3), (0.4, 0.0), (0.4, 0.3), (0.6, 0.0), (0.6, 0.3)]


def synthetic_observer(families: list[str], p_miss: float, p_coarse: float, rng: random.Random) -> list[TaxonObservation]:
    """What an observer of this quality reports for a tray holding these animals."""
    seen = []
    for family in families:
        if rng.random() < p_miss:
            continue
        if rng.random() < p_coarse:
            seen.append(TaxonObservation(name=BY_FAMILY[family.lower()].group, confidence=0.8))
        else:
            seen.append(TaxonObservation(name=family, confidence=0.85))
    return seen


def sweep(p_miss: float, p_coarse: float, repeats: int, seed: int = 1000) -> dict[str, float]:
    caught = right = mistakes = alarm_questions = 0
    per_run_catch = []
    for run in range(repeats):
        rng = random.Random(seed + run)
        outcomes = [
            Outcome(
                case=Case(photo=name, truth=families),
                photo_kind="specimen",
                model_taxa=synthetic_observer(families, p_miss, p_coarse, rng),
            )
            for name, families in TRAYS.items()
        ]
        r = score_outcomes(outcomes)
        caught += r.caught
        right += r.caught_with_right_answer
        mistakes += r.mistakes
        alarm_questions += r.false_alarm_questions
        if r.mistakes:
            per_run_catch.append(r.caught / r.mistakes)
    photos = repeats * len(TRAYS)
    return {
        "caught": caught / mistakes if mistakes else 0.0,
        "right_answer": right / mistakes if mistakes else 0.0,
        "alarms_per_photo": alarm_questions / photos if photos else 0.0,
        "spread": statistics.pstdev(per_run_catch) if len(per_run_catch) > 1 else 0.0,
        "mistakes": mistakes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeats", type=int, default=100, help="runs per grid point (default 100)")
    parser.add_argument("--seed", type=int, default=1000, help="base seed; the sweep is deterministic")
    parser.add_argument("--markdown", action="store_true", help="emit a Markdown table for docs/EVALUATION.md")
    args = parser.parse_args()

    rows = [(m, c, sweep(m, c, args.repeats, args.seed)) for m, c in GRID]

    if args.markdown:
        print(f"| Animals the observer misses | Answered to order only | Mistakes caught | ...with the right animal offered | "
              f"False-alarm questions per tray |")
        print("|---|---|---|---|---|")
        for miss, coarse, s in rows:
            print(f"| {miss:.0%} | {coarse:.0%} | {s['caught']:.0%} | {s['right_answer']:.0%} | {s['alarms_per_photo']:.2f} |")
        print()
        print(f"{len(TRAYS)} trays, {args.repeats} runs per row, seed {args.seed}; "
              f"{rows[0][2]['mistakes'] // args.repeats} simulated mistakes per run.")
        return 0

    print(f"{len(TRAYS)} trays x {args.repeats} runs per grid point, seed {args.seed}.")
    print("The observer is synthetic: this measures secondopinion.py, not a model.\n")
    print(f"{'miss':>6} {'order-only':>11} | {'caught':>8} {'right':>7} {'alarms/tray':>12}")
    for miss, coarse, s in rows:
        print(f"{miss:>6.0%} {coarse:>11.0%} | {s['caught']:>8.0%} {s['right_answer']:>7.0%} {s['alarms_per_photo']:>12.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
