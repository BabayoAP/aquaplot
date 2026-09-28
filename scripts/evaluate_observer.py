#!/usr/bin/env python3
"""Measure how well the model's second opinion catches volunteers' mistakes.

Put photos of sample trays (or single animals) in a folder with a ``labels.csv``:

    photo,families,note
    tray-01.jpg,Heptageniidae;Gammaridae;Chironomidae,Ribeira de Coselhas riffle
    tray-02.jpg,Asellidae;Oligochaeta,

Family names must be ones in ``data/bioindicators.json`` (genus and common-name
aliases are accepted and resolved). Then:

    .venv/bin/python scripts/evaluate_observer.py eval/labels.csv --out eval/results

The model is called once per photo and its raw output is saved to
``observations.json``. Scoring is a pure function of that file, so after changing
the rules you can rescore for free:

    .venv/bin/python scripts/evaluate_observer.py eval/labels.csv --out eval/results --rescore

The backend follows the app's rules (``ANTHROPIC_API_KEY``, a local Ollama vision
model, or ``AQUAPLOT_OBSERVER``). Method and reading guide: docs/EVALUATION.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from aquaplot.bioindex import TaxonObservation
from aquaplot.evaluation import Outcome, load_labels, score_outcomes
from aquaplot.identify import IdentifyError
from aquaplot.inputs import InvalidImage, decode_image
from aquaplot.observe import select_observer
from aquaplot.schema import Region


async def observe_one(case, folder: Path, observer) -> dict:
    entry = {"photo": case.photo, "photo_kind": "", "taxa": [], "error": None}
    try:
        image = decode_image((folder / case.photo).read_bytes())
        seen = await observer.observe(image.image, "", Region(source="none"))
        entry["photo_kind"] = seen.photo_kind
        entry["taxa"] = [{"name": t.name, "confidence": t.confidence, "rank": t.rank} for t in seen.taxa]
        entry["reasoning"] = seen.reasoning
    except (OSError, InvalidImage, IdentifyError) as exc:
        entry["error"] = str(exc)
    return entry


async def observe_all(cases, folder: Path, observer, save, done: dict[str, dict], concurrency: int = 1) -> list[dict]:
    """Call the model once per photo, saving after each answer and skipping the ones already in ``done``.

    A hundred photos on a local vision model is hours, and the answers are the
    only expensive thing here - scoring them is free and rerunnable. Writing the
    file only at the end meant an interrupted run threw away every call it had
    already paid for, so each answer is saved as it arrives and a rerun picks up
    where the last one stopped. Delete observations.json to start again.

    ``concurrency`` is 1 by default because a local Ollama serves one request at
    a time anyway; raise it for a hosted model, where the wait is the network.
    """
    todo = [c for c in cases if c.photo not in done]
    if done:
        print(f"{len(done)} already recorded; {len(todo)} to go.", file=sys.stderr)
    counter = 0
    lock = asyncio.Lock()
    limit = asyncio.Semaphore(max(1, concurrency))

    async def run(case):
        nonlocal counter
        async with limit:
            entry = await observe_one(case, folder, observer)
        async with lock:
            counter += 1
            done[case.photo] = entry
            save(done)
            note = f" - {entry['error']}" if entry["error"] else ""
            print(f"[{counter}/{len(todo)}] {case.photo}{note}", file=sys.stderr)

    await asyncio.gather(*(run(c) for c in todo))
    return [done[c.photo] for c in cases if c.photo in done]


def outcomes_from(cases, raw: list[dict]) -> list[Outcome]:
    by_photo = {r["photo"]: r for r in raw}
    out = []
    for case in cases:
        r = by_photo.get(case.photo, {"error": "no observation recorded", "photo_kind": "", "taxa": []})
        out.append(
            Outcome(
                case=case,
                photo_kind=r.get("photo_kind", ""),
                model_taxa=[TaxonObservation(name=t["name"], confidence=t["confidence"]) for t in r.get("taxa", [])],
                error=r.get("error"),
            )
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("labels", type=Path, help="labels.csv; photos are read from the same folder")
    parser.add_argument("--out", type=Path, default=Path("eval-results"))
    parser.add_argument("--rescore", action="store_true", help="reuse observations.json instead of calling the model")
    parser.add_argument("--concurrency", type=int, default=1, help="photos in flight at once; raise it for a hosted model")
    args = parser.parse_args()

    cases = load_labels(args.labels)
    args.out.mkdir(parents=True, exist_ok=True)
    stored = args.out / "observations.json"

    if args.rescore:
        payload = json.loads(stored.read_text(encoding="utf-8"))
    else:
        observer = select_observer()
        if observer.name == "none":
            print("No vision model is configured (set ANTHROPIC_API_KEY or run Ollama). Nothing to evaluate.", file=sys.stderr)
            return 2
        print(f"Calling {observer.name} once for each of {len(cases)} photos.", file=sys.stderr)
        wanted = {c.photo for c in cases}
        done: dict[str, dict] = {}
        if stored.exists():
            previous = json.loads(stored.read_text(encoding="utf-8"))
            # Only resume answers from the same backend: mixing two models' output
            # into one table would report a score no single observer achieved.
            if previous.get("model") == getattr(observer, "model", None) and previous.get("observer") == observer.name:
                done = {o["photo"]: o for o in previous.get("observations", []) if o["photo"] in wanted}

        def save(answers: dict[str, dict]) -> None:
            stored.write_text(
                json.dumps(
                    {
                        "observer": observer.name,
                        "model": getattr(observer, "model", None),
                        "observations": [answers[c.photo] for c in cases if c.photo in answers],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        observations = asyncio.run(observe_all(cases, args.labels.parent, observer, save, done, args.concurrency))
        payload = {"observer": observer.name, "model": getattr(observer, "model", None), "observations": observations}
        save(done)

    report = score_outcomes(outcomes_from(cases, payload["observations"]))
    label = payload["observer"] + (f" / {payload['model']}" if payload.get("model") else "")
    (args.out / "report.md").write_text(report.markdown(label), encoding="utf-8")
    (args.out / "report.json").write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    print(report.markdown(label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
