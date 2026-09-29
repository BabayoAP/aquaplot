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
model, or ``AQUAPLOT_OBSERVER``). Bringing your own key:

    cp .env.example .env     # put your key in it; .env is git-ignored
    .venv/bin/python scripts/fetch_inat_eval.py --from-labels eval/inat/labels-subset.csv
    .venv/bin/python scripts/evaluate_observer.py eval/inat/labels-subset.csv \
        --observer claude --out eval/claude-results

``--observer`` is worth passing: without it a key you forgot to set means the run
quietly measures whatever else is installed, and a table headed with the wrong
model is worse than no table. Method and reading guide: docs/EVALUATION.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from aquaplot.bioindex import TaxonObservation
from aquaplot.evaluation import Outcome, load_labels, score_outcomes
from aquaplot.identify import IdentifyError
from aquaplot.inputs import InvalidImage, decode_image
from aquaplot.observe import select_observer
from aquaplot.schema import Region


def load_env_file(path: Path) -> None:
    """Read ``KEY=value`` lines from a .env into the environment, without a dependency.

    A key belongs in a git-ignored file rather than in shell history or in a
    command somebody pastes into a terminal recording. Anything already set in
    the environment wins, so the file is a default and never a surprise.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def check_observer(observer, wanted: str | None) -> str | None:
    """Why this run should not start, or None.

    Measuring a backend the caller did not ask for is the failure that wastes a
    key: the report is headed with the model that answered, but by then the
    photos are spent and the number is about something else.
    """
    if observer.name == "none":
        return "No vision model is configured (set ANTHROPIC_API_KEY or run Ollama). Nothing to evaluate."
    if wanted and observer.name != wanted:
        got = observer.name
        extra = " ANTHROPIC_API_KEY is not set." if wanted == "claude" and not os.environ.get("ANTHROPIC_API_KEY") else ""
        return f"You asked for {wanted} but the configured backend is {got}.{extra}"
    return None


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


ABORT_AFTER = 3


class RunAborted(RuntimeError):
    """The backend stopped answering, so the run was stopped rather than recorded."""


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

    failed_in_a_row = 0
    last_error = ""
    stop = asyncio.Event()

    async def run(case):
        nonlocal counter, failed_in_a_row, last_error
        if stop.is_set():
            return
        async with limit:
            if stop.is_set():
                return
            entry = await observe_one(case, folder, observer)
        async with lock:
            counter += 1
            done[case.photo] = entry
            save(done)
            note = f" - {entry['error']}" if entry["error"] else ""
            print(f"[{counter}/{len(todo)}] {case.photo}{note}", file=sys.stderr)
            # A rejected key, an exhausted balance or a dropped network fails every
            # photo the same way. Recording that as a hundred rows of nothing looks
            # exactly like a model that saw nothing, so stop and say which it was.
            failed_in_a_row = failed_in_a_row + 1 if entry["error"] else 0
            last_error = entry["error"] or last_error
            if failed_in_a_row >= ABORT_AFTER:
                stop.set()

    await asyncio.gather(*(run(c) for c in todo))
    if stop.is_set():
        raise RunAborted(f"{ABORT_AFTER} calls in a row failed. The last said: {last_error}")
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
    parser.add_argument(
        "--observer",
        choices=["claude", "ollama"],
        help="refuse to run unless this is the backend that answers; stops a missing key measuring something else",
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="KEY=value file to read the key from (default .env)")
    parser.add_argument("-y", "--yes", action="store_true", help="do not ask before spending calls")
    args = parser.parse_args()

    load_env_file(args.env_file)
    cases = load_labels(args.labels)
    args.out.mkdir(parents=True, exist_ok=True)
    stored = args.out / "observations.json"

    if args.rescore:
        payload = json.loads(stored.read_text(encoding="utf-8"))
    else:
        observer = select_observer()
        if (complaint := check_observer(observer, args.observer)) is not None:
            print(complaint, file=sys.stderr)
            return 2
        missing = [c.photo for c in cases if not (args.labels.parent / c.photo).exists()]
        if missing:
            # Scoring a photo that is not there records it as an error and drags the
            # table down, so say what to run instead of measuring a hole.
            print(
                f"{len(missing)} of {len(cases)} photos are missing from {args.labels.parent}, "
                f"starting with {missing[0]}.\n"
                f"Rebuild the set first:\n"
                f"  python scripts/fetch_inat_eval.py --from-labels {args.labels}",
                file=sys.stderr,
            )
            return 2
        wanted = {c.photo for c in cases}
        done: dict[str, dict] = {}
        if stored.exists():
            previous = json.loads(stored.read_text(encoding="utf-8"))
            # Only resume answers from the same backend: mixing two models' output
            # into one table would report a score no single observer achieved.
            if previous.get("model") == getattr(observer, "model", None) and previous.get("observer") == observer.name:
                # A failure is not an answer. Resuming one would bake a rejected key or a
                # dropped connection into the table permanently, and the photo it was
                # meant to score would never be sent again.
                done = {o["photo"]: o for o in previous.get("observations", []) if o["photo"] in wanted and not o.get("error")}

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

        label = observer.name + (f" / {observer.model}" if getattr(observer, "model", None) else "")
        to_call = len(cases) - len(done)
        print(f"{to_call} photo(s) to send to {label}, one call each.", file=sys.stderr)
        if to_call and not args.yes and sys.stdin.isatty():
            if input("Press enter to spend them, or Ctrl-C to stop: ").strip().lower() in {"n", "no"}:
                return 1
        try:
            observations = asyncio.run(observe_all(cases, args.labels.parent, observer, save, done, args.concurrency))
        except RunAborted as exc:
            print(
                f"\nStopped: {exc}\nAnswers already recorded are kept in {stored}; fix the cause and run again to carry on.",
                file=sys.stderr,
            )
            return 2
        payload = {"observer": observer.name, "model": getattr(observer, "model", None), "observations": observations}

    report = score_outcomes(outcomes_from(cases, payload["observations"]))
    label = payload["observer"] + (f" / {payload['model']}" if payload.get("model") else "")
    (args.out / "report.md").write_text(report.markdown(label), encoding="utf-8")
    (args.out / "report.json").write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    print(report.markdown(label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
