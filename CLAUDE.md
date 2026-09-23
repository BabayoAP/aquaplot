# riffle

Build strictly against `PRD.md` (product name SpeciesGuard). Cite the PRD section
in every module docstring and name tests after the acceptance criterion they check.
Record any deviation from the PRD in README "Decisions and deviations" with the reason.

- Python 3.12 in `.venv` (system python is 3.9). `uv venv --python 3.12 .venv`,
  then `uv pip install --python .venv/bin/python -e ".[dev]"`.
- Tests: `.venv/bin/python -m pytest`. Run: `.venv/bin/uvicorn riffle.app:app --reload`.
- The result contract in `src/riffle/schema.py` is the interface between the
  page and the pipeline. Extend it, do not break it.
- FR-8: never return a "needs review" label. Always one of the three labels plus a
  certainty percentage, with reasons in `evidence.certainty_penalties`.
- Milestone order is PRD §11 (M0, M1, M2, M6 done, Stage 2 crop pass done; see PRD §12). Region is Orange County, CA only in v1.
- Species model backends live in `src/riffle/identify.py`; tests inject fakes and must
  never call Claude, Ollama or the network. `docs/CLASSIFIER.md` explains the certainty rule;
  bump `PIPELINE_VERSION` whenever that rule changes.
- The area viewer is specified in `docs/AREA-VIEWER.md` (FR-A1..A10). Its data layer is
  `src/riffle/area.py`; tests inject a fake fetcher and must never hit the network.
- "Introduced" (iNaturalist) is not "invasive" (Cal-IPC/CDFW). Keep that distinction in
  UI copy and docs. The seed list in `src/riffle/data/status_seed.json` is unverified;
  `scientific_name` is iNaturalist's accepted name, `synonyms` hold the older names, and
  new entries must be checked against `/v1/taxa?q=` before they go in.
- Hackathon: NextStep Hacks 2026, deadline Sep 20 2026 2 pm PDT. `docs/HACKATHON.md`
  holds the submission checklist and the required before/during timeline.
