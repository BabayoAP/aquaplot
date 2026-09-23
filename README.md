# Riffle

**From a photo at the water's edge to a stream-health reading and a One Health signal.**

A citizen scoops gravel from a shallow, fast patch of an urban stream into a pale tray,
photographs what moves, photographs the reach, and answers two questions a camera cannot
answer. Riffle returns a **Water Framework Directive band** for the stream, a **visual
pressure score**, and what that means for the **people and animals** around it — with
every finding traceable to the observation behind it, and an alert held back until a
person has confirmed the observation it rests on.

Built for the [IEEE OneAquaHealth Global Hackathon 2026](docs/HACKATHON.md).
Primary track: **AI-Supported Assessment**. See [track alignment](docs/HACKATHON.md#track-alignment).

```
photos ─▶ observe.py     the vision model reports structured observations, never a verdict
          ├────────────▶ bioindex.py   BMWP / ASPT band from the invertebrates found
          └────────────▶ habitat.py    visual pressures, model and citizen answers merged
coords ─▶ places.py      which municipality is this? (anywhere on Earth)
taxa   ─▶ status.py      is any of this on an invasive list, here?
                  └────▶ onehealth.py  rules → ecosystem / human / animal findings + actions
                                 └───▶ assessment ─▶ store.py (trends) · fhir.py (interop)
```

## Why this shape

Three decisions define the project, and each one is visible in the code.

**The model observes; the rules decide.** A vision-language model is excellent at *what
is in this picture* — is the water cloudy, is that a bloom, is the bank concrete, is that
a mayfly nymph. It is the wrong place to put *should this family keep their dog out of
the water*. So `observe.py` returns only structured observations in a fixed vocabulary,
and `bioindex.py` and `onehealth.py` — readable, testable, arguable rules over published
indices — produce every determination. A finding names the rule that fired, the evidence
that triggered it, and the action it implies.

**An alert waits for a human.** `onehealth.py` will not raise an alert on model output no
person has reviewed. It downgrades to *concern*, says why in the evidence, and the app
puts that exact observation at the top of the confirmation queue. Confirming it raises the
alert. Human-in-the-loop here is a mechanism with a test, not a slogan.

**Certainty is multiplicative and itemised.** Inherited from the project Riffle grew out
of: a result must never look more confident than its weakest input. Every factor below 1.0
leaves a sentence behind — *8 of 12 habitat questions were answered*, *2 animals were
identified only to order*, *the coordinates could not be resolved to a municipality* — so
the number can always be taken apart.

## What works today

**The guided check** (`/`). Four steps at the water's edge: where you are, two photographs
(the reach and the sample tray), the two questions only a person standing there can answer
(smell, and who uses the water), then confirm or correct what the model proposed. Every
question on the page is rendered from `/api/form`, the same file the model's prompt and the
server's validator are generated from, so the words on the screen cannot drift from the
vocabulary the system accepts. The result gives the band, what it means in plain language,
findings for all three One Health domains, and actions split by who can actually take them:
you now, your community, your authority.

**The biological index.** BMWP/ASPT over 53 macroinvertebrate families, banded on the WFD's
five classes. Sampling effort caps the claim — three families under one stone cannot earn
*High*, and two tolerant families cannot prove a stream is dead; both come back marked
*provisional* with the reason. An identification to order only ("that's a stonefly") is
scored from the group median and flagged coarse rather than thrown away.

**The One Health rules.** Twelve rules over the index, the pressures, the invasive check and
the exposure answer: harmful algal blooms, sewage indicators, chemical sheen, mosquito
breeding, parasite-host snails, invasive biosecurity, habitat degradation, thermal and
drought resilience, sedimentation, and the wellbeing a stream in good condition provides.
Exposure escalates: the same water quality is a different finding where children paddle.

**Trends and early warning** (`/dashboard`, `/map`). Assessments are keyed to a ~100 m site
grid, so a second visit to roughly the same spot extends a series instead of dropping a new
pin. The dashboard leads with where the water stands, which sites declined since their last
visit, and what needs a budget. A review *replaces* a visit rather than adding one, so the
volunteers who check the model's work most carefully cannot manufacture trends by doing so.

**FHIR R4 export** (`/api/assess/{id}/fhir`). The assessment as a Bundle: a `Location`, an
`Observation` panel carrying BMWP, ASPT, EPT richness and the band, the raw survey and the
habitat form as their own Observations, one Observation per One Health domain with an HL7
interpretation code, a `Flag` per alert, and a `Provenance` recording which model observed
and how many observations a human confirmed. No code pretends to be LOINC; see
[docs/FHIR.md](docs/FHIR.md).

**It works with no model at all.** With no API key and no local model, nothing is read off
the photos and the citizen answers the form themselves — and the band, the pressure score,
the findings, the actions, the trends and the FHIR export are all identical. The model makes
Riffle usable by a novice; it is not what makes it work.

## Run

Python 3.12 or newer. With [uv](https://docs.astral.sh/uv/):

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest                       # 141 tests, no network, no model
.venv/bin/uvicorn riffle.app:app --reload        # http://127.0.0.1:8000
```

Open `/` to check a stream, `/dashboard` for the insights, `/map` for the map, `/docs` for
the OpenAPI reference.

### Choosing a vision model

| `ANTHROPIC_API_KEY` set | Ollama running with a vision model | Backend |
|---|---|---|
| yes | any | Claude (`claude-opus-5`; override with `CLAUDE_MODEL`) |
| no | yes (`ollama pull qwen2.5vl:3b`) | local model via Ollama (`OLLAMA_MODEL` to pick one) |
| no | no | none: the citizen fills the form, everything else is unchanged |

`RIFFLE_OBSERVER=claude|ollama|none` forces a choice and `/api/health` reports which is
active. `RIFFLE_DB` sets the SQLite path (default `riffle.db`). `RIFFLE_CLASSIFY_LIMIT`
caps assessments per client address per 10 minutes (default 20, `0` disables) so a public
demo cannot drain an API key.

## Where things live

| Path | What |
|---|---|
| `src/riffle/observe.py` | The vision model's only job: photo → structured observations. Three backends, one schema. |
| `src/riffle/bioindex.py` | BMWP/ASPT, WFD bands, the effort cap, the coarse-identification rule. |
| `src/riffle/habitat.py` | The visual field form: scoring, validation, model-vs-citizen precedence. |
| `src/riffle/onehealth.py` | The rule engine. Every finding carries a rule id, its evidence and an action. |
| `src/riffle/assess.py` | Composes the stages; the certainty rule; the confirmation queue; `reassess` for review. |
| `src/riffle/places.py` | Coordinates → administrative chain, anywhere; the OneAquaHealth research cities. |
| `src/riffle/status.py` | Species + place → Native / Invasive / Naturalized, with the listing jurisdiction. |
| `src/riffle/store.py` | SQLite: sites on a ~100 m grid, trends, the alert feed, badges. |
| `src/riffle/fhir.py` | FHIR R4 Bundle export. |
| `src/riffle/data/bioindicators.json` | 53 families: BMWP score, what to look for, what finding it means. |
| `src/riffle/data/habitat_indicators.json` | The field form. Drives the prompt, the validator, the UI and the scoring. |
| `src/riffle/data/status_seed.json` | 101 listed invasives with jurisdiction, habitat and One Health relevance. |
| `src/riffle/data/pilot_sites.json` | The five OneAquaHealth research cities. |
| `src/riffle/static/check.html` | The guided citizen workflow. |
| `src/riffle/static/dashboard.html` | The insights dashboard. |
| `src/riffle/static/map.html` | Leaflet map: Riffle sites over iNaturalist layers. No build step. |
| `src/riffle/{identify,pipeline,schema,inputs,area,inat}.py` | Inherited from SpeciesGuard; see lineage below. |

## Documentation

- [docs/ASSESSMENT.md](docs/ASSESSMENT.md) — how a photo becomes a band, stage by stage, and what the certainty number means.
- [docs/ONE-HEALTH.md](docs/ONE-HEALTH.md) — every rule, its trigger, its evidence and its action.
- [docs/FHIR.md](docs/FHIR.md) — the resources, the codes, and what would have to happen to make them standard.
- [docs/HACKATHON.md](docs/HACKATHON.md) — track alignment, the judging criteria, and the build timeline.
- [docs/AREA-VIEWER.md](docs/AREA-VIEWER.md), [docs/CLASSIFIER.md](docs/CLASSIFIER.md) — the inherited features.

## Lineage

Riffle is a fork of **SpeciesGuard** ([BabayoAP/nativeview](https://github.com/BabayoAP/nativeview)),
a terrestrial invasive-species classifier the same author built for NextStep Hacks 2026.
What carried over: the pipeline shape, the certainty rule and its insistence on an evidence
trail, the cached iNaturalist client, the pluggable model backends, and the area viewer.
What is new here: the freshwater domain entirely — the biotic index, the field form, the
One Health rule engine, the assessment pipeline and its review loop, persistence and trends,
FHIR export, the generalised geography, and the citizen workflow. Roughly 2,600 lines of new
Python and 1,400 of new interface, with 73 new tests. The original project's PRD is kept at
[docs/PRD-SPECIESGUARD.md](docs/PRD-SPECIESGUARD.md) and its submission notes at
[docs/HACKATHON-NEXTSTEP.md](docs/HACKATHON-NEXTSTEP.md), so the boundary between the two is
on the record rather than implied.

## Honesty about what this is not

- **Not a Water Framework Directive classification.** A formal classification needs a
  standardised three-minute kick sample, laboratory identification and a reference-site
  comparison. Riffle is a screening tool, and every result says so.
- **Not a medical, water-quality or regulatory determination.** Findings name the authority
  that can make one and tell the user to contact it.
- **The certainty factors are priors, not measured calibration.** They order outcomes
  sensibly and explain themselves; no calibration study has been run. `assessment_version`
  changes whenever the rules do, so results stay comparable.
- **The seed invasive list is unverified.** It cites Cal-IPC, CDFW, USGS, UC IPM and EU
  Regulation 1143/2014, and every entry must be re-checked against those authorities before
  it is used for anything beyond screening.
- **BMWP is a British index applied across Europe.** Family sensitivity scores vary by
  ecoregion; a country-specific index (IBMWP, IBE, ASPT variants) would be more accurate and
  is the obvious next step, one adapter away in `bioindex.py`.

## Data sources

| Source | Used for | Terms |
|---|---|---|
| [iNaturalist API](https://api.inaturalist.org/v1/docs/) | Taxonomy, establishment means, administrative places, sightings | Free, attribution, ~1 req/s |
| BMWP / ASPT family scores | The biological index | Published methodology, widely reproduced |
| EU Regulation (EU) 1143/2014 Union list | Invasive species of Union concern | Public |
| Cal-IPC Inventory, CDFW, USGS NAS, UC IPM | Inherited Californian invasive entries | Public lists |
| [OneAquaHealth field protocols](https://zenodo.org/records/20344421) | The shape of the site-characterisation form | CC, cited |
| [Global Forest Watch](https://www.globalforestwatch.org/) (Hansen/UMD/Google/USGS/NASA) | Tree-cover loss tiles | CC BY 4.0 |
| Esri World Imagery and Reference | Basemap and labels | Esri attribution |

## Licence

MIT. See [LICENSE](LICENSE).
