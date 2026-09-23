# AquaPlot

A citizen stream-health tool for the IEEE OneAquaHealth Global Hackathon 2026.
Build against [README.md](README.md), [docs/ASSESSMENT.md](docs/ASSESSMENT.md) and
[docs/ONE-HEALTH.md](docs/ONE-HEALTH.md). Cite the document a module implements in its
docstring, and name tests after the behaviour they protect, not the function they call.

- Python 3.12 in `.venv` (system python is 3.9). `uv venv --python 3.12 .venv`,
  then `uv pip install --python .venv/bin/python -e ".[dev]"`.
- Tests: `.venv/bin/python -m pytest`. Run: `.venv/bin/uvicorn aquaplot.app:app --reload`.
- **The model observes, the rules decide.** `observe.py` may return only structured
  observations. Any determination about health belongs in `bioindex.py` or `onehealth.py`,
  where it is readable and testable. Do not move judgement into the prompt.
- **An alert waits for a human.** `onehealth.evaluate` downgrades an unconfirmed alert to
  concern and says so. If you add a rule that can reach alert, list the habitat answers it
  rests on in `assess.RULE_EVIDENCE` so the confirmation queue knows what to ask for.
- **A review must never call the model again** (`assess.reassess`). Re-running it would let
  the model overwrite a correction a person just made.
- **`data/habitat_indicators.json` is the single source of truth** for the field form: the
  model prompt, the server validator, the UI questions and the pressure scoring are all
  generated from it. Add an indicator there and nowhere else.
- Certainty is multiplicative and every factor below 1.0 must leave a sentence in the
  penalties. Bump `ASSESSMENT_VERSION` whenever the rule changes.
- Tests inject fakes and must never reach Claude, Ollama or the network. Every network call
  goes through an injectable callable for that reason.
- "Introduced" (iNaturalist establishment) is not "invasive" (a listing by an authority).
  Keep the distinction in copy, in the seed and in the UI. Seed entries carry iNaturalist's
  accepted name in `scientific_name` and older names in `synonyms`; matching checks both.
- The band is a **screening** estimate, never a Water Framework Directive classification, and
  every surface that shows it must say so.
- Geography is resolved from coordinates, never assumed. Nothing may hard-code a place.
- `src/aquaplot/{identify,pipeline,schema,inputs,area,inat}.py` and the `/classify` page are
  inherited from SpeciesGuard and still work; keep them working.
