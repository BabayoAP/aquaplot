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
- **When the citizen identifies, their list is what gets scored.** The model's view of the tray
  is a second opinion that may only raise questions (`secondopinion.py`). Never pass the
  citizen's identifications to the model: agreement is only evidence if it was given blind.
  Taking the model's answer in a review is recorded as `adopted`, never as agreement.
- **The biotic index is chosen from the resolved country** (`bioindex.index_for`), and the band
  is always read from the mean. A family an index does not score is `recorded`, not scored,
  and must still reach the One Health rules. Every score column must name its published source.
- **FHIR codings take their `display` from `fhir.code_system()`**; case-specific wording goes
  in `text`. Run the HL7 validator after changing `fhir.py` (docs/FHIR.md).
- **Only what a person gave or confirmed crosses into OneAquaHealth formats**: the app submission
  (`oah.app_submission`) and the `observation-indicators-oah` Observations, whose profile fixes
  `status = final`. OAH codes are used verbatim, typos included. Validate with the OAH IG loaded
  (docs/FHIR.md). `data/oah_reference.json` is a snapshot refreshed by
  `scripts/fetch_oah_reference.py`; the app never calls the OAH API at run time.
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
- **Never blind search-and-replace the word "riffle".** "Riffle beetle" is the Elmidae family
  and a riffle is the stretch a kick sample is taken from; both appear in
  `data/bioindicators.json` and in the `ALIASES` table in `bioindex.py`, whose keys must stay
  lower case because lookup lower-cases its input.
- The field guide at `src/aquaplot/data/field_guide.md` is product, not documentation: the app
  serves it at `/field-guide`. `docs/FIELD-GUIDE.md` points at it; do not fork a second copy.
- Anything that can be sent must be sendable by a person: `report.py` (authority report),
  `fhir.py` (health systems), CSV and GeoJSON (everyone else). A finding that says "report
  this" and gives the user nothing to send is a bug.
- The outbox in `check.html` owns offline writes, not the service worker. Data somebody walked
  to a stream to collect must be visible and manually flushable, never an invisible sync.
- See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add a family, an indicator, a rule or an index.
