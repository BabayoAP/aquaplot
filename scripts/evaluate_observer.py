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


async def observe_all(cases, folder: Path, observer) -> list[dict]:
    raw = []
    for n, case in enumerate(cases, 1):
        print(f"[{n}/{len(cases)}] {case.photo}", file=sys.stderr)
        entry = {"photo": case.photo, "photo_kind": "", "taxa": [], "error": None}
        try:
            image = decode_image((folder / case.photo).read_bytes())
            seen = await observer.observe(image.image, "", Region(source="none"))
            entry["photo_kind"] = seen.photo_kind
            entry["taxa"] = [{"name": t.name, "confidence": t.confidence, "rank": t.rank} for t in seen.taxa]
            entry["reasoning"] = seen.reasoning
        except (OSError, InvalidImage, IdentifyError) as exc:
            entry["error"] = str(exc)
        raw.append(entry)
    return raw


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
        payload = {
            "observer": observer.name,
            "model": getattr(observer, "model", None),
            "observations": asyncio.run(observe_all(cases, args.labels.parent, observer)),
        }
        stored.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    report = score_outcomes(outcomes_from(cases, payload["observations"]))
    label = payload["observer"] + (f" / {payload['model']}" if payload.get("model") else "")
    (args.out / "report.md").write_text(report.markdown(label), encoding="utf-8")
    (args.out / "report.json").write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    print(report.markdown(label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
