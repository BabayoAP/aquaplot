# AquaPlot

*Plot the health of your local water.*

**The citizen identifies. The AI double-checks, blind. The rules decide.**

**The problem.** The animals living in a stream are the best evidence of its health, and the
hardest thing for a volunteer to name: a flat-headed mayfly and a stonefly look alike to a
beginner, and one wrong name can move a stream's reading. Letting an AI identify them instead
teaches nobody anything, hides the AI's mistakes, and puts a machine's guess in a health record.
The hackathon's Track 3 names the problem directly: *citizen observations can be inconsistent
and error-prone.*

**Try it in 90 seconds:** run it (below) and open `/try`: real photographs are pre-loaded, you
name the animal, and the AI, which never saw your answer, asks you to count its tails.
`/about` is the two-minute version of this page.

| You identify | The AI asks, blind | The reading | The trend |
|---|---|---|---|
| ![Picking the animal](docs/screenshots/1-identify.png) | ![The second opinion](docs/screenshots/2-second-opinion.png) | ![The result](docs/screenshots/3-result.png) | ![A site declining](docs/screenshots/5-site-trend.png) |

A citizen scoops gravel from a shallow, fast patch of an urban stream into a pale tray,
photographs it, and picks what they see from a guide organised by shape — "three tails",
"a case made of sand". A vision model looks at the same photograph **without seeing their
answers** and asks about the places it saw something different: *you marked a stonefly; this
may be a mayfly — count the tails.* The citizen decides. AquaPlot then returns a **Water
Framework Directive screening band**, a **visual pressure score**, and what it means for the
**people and animals** around the stream, with every finding traceable to the observation
behind it and every health alert held back until a person has confirmed what it rests on.

Built for the [IEEE OneAquaHealth Global Hackathon 2026](docs/HACKATHON.md).
**Track 3: AI-Supported Assessment** — AI that supports stream assessment without replacing
human judgement. See [track alignment](docs/HACKATHON.md#track-alignment).

```
tray photo ──▶ citizen picks the animals ─────────────────────┐  scored
           └─▶ observe.py (blind) ─▶ secondopinion.py ─▶ questions only, ranked by
                                                          whether the answer changes the band
reach photo ─▶ observe.py ─▶ habitat.py   visual pressures; a citizen answer beats the model's
coords ─────▶ places.py                   which municipality, which country, which index
     └──────▶ weather.py                  rain before the visit, rain and heat in the next 48 h
                 └─▶ bioindex.py          BMWP/ASPT, or IBMWP/IASPT in Portugal and Spain
                 └─▶ status.py            is any of this on an invasive list, here?
                        └─▶ onehealth.py  rules → ecosystem / human / animal findings + actions
                               └─▶ assessment ─▶ store.py    trends, sites, early warning
                                             ├▶ report.py   what you send your water authority
                                             ├▶ fhir.py     FHIR R4, HL7-validated
                                             └▶ csv/geojson for everyone else
```

## Why this shape

Four decisions define the project, and each one is visible in the code.

**The person identifies; the model gives a blind second opinion.** Naming a 5 mm larva from
a phone photo is hard for a trained ecologist with a hand lens, so AquaPlot never asks a model
to decide it. The citizen's own identifications are what get scored. The model, shown the same
tray without their answers, produces only questions — a likely confusion with the feature that
separates the two, an animal they may have missed, a sensitive family it could not find — each
carrying the band the stream would get if the model were right. Asked blind, its agreement is
independent evidence; taking its answer is recorded as that, never as agreement. Whether this
catches real mistakes is measurable, and [EVALUATION.md](docs/EVALUATION.md) is how.

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

**Certainty is multiplicative and itemised.** Inherited from the project AquaPlot grew out
of: a result must never look more confident than its weakest input. Every factor below 1.0
leaves a sentence behind — *8 of 12 habitat questions were answered*, *2 animals were
identified only to order*, *the coordinates could not be resolved to a municipality* — so
the number can always be taken apart.

## Where this fits

OneAquaHealth already has a Citizen Science App: a volunteer at one of the project's research
sites (or a personal site) records photos, the channel and banks, flow, water colour, habitats,
vegetation and an overall Good / Moderate / Poor judgement. It does not ask what lives in the
water. AquaPlot is built to sit beside it, not to replace it. What it adds is the part the app
leaves out and the part after it: the animals, identified by the volunteer and checked by a
model; a One Health reading of what they found; a report an authority can act on; and a record
a health system can import.

It speaks the project's own terms, from a snapshot of the project's public API:

- **The 106 research sites.** A check made within 200 m of one (Vale das Flores in Coimbra is
  `C3`) says so on the result, on the map and in every export, so a citizen reading can be set
  beside the laboratory data the project files under the same code.
- **The app's own submission.** `GET /api/assess/{id}/oah-app` gives the check as the body the
  app submits (`CitizenSubmissionPutDTO`), in the app's answer codes, with every field's source
  and every answer that did not translate listed with the reason.
- **The project's FHIR IG.** The export conforms to the OneAquaHealth IG
  ([`hl7-eu/oah`](https://github.com/hl7-eu/oah)): its Location profile, and its indicator
  Observation profile for macroinvertebrates, Diptera, foam/colour/smell, riparian vegetation,
  morphology, hydrology, algae and invasive organisms. It passes the HL7 validator with the IG
  loaded, with no errors and no warnings.

Only what a person gave or confirmed crosses into the project's formats. What the vision model
alone saw stays in AquaPlot, marked preliminary. Nothing is locked in either way: every
assessment also leaves as CSV and GeoJSON.

## What works today

**The guided check** (`/`). Five short steps at the water's edge: where you are, two
photographs (the reach and the sample tray), **the animals you found**, the two questions only
a person standing there can answer (smell, and who uses the water), then the places where you
and the model differ. The animal picker is grouped by shape, searchable by what you can see,
and offers "some kind of mayfly" when the family is beyond you. Every habitat question is
rendered from `/api/form`, the same file the model's prompt and the server's validator are
generated from, so the words on the screen cannot drift from the vocabulary the system accepts.
The result gives the band, what it means in plain language, who identified the animals and how
often the model independently agreed, findings for all three One Health domains, and actions
split by who can actually take them: you now, your community, your authority.

**The second opinion** (`secondopinion.py`). Three kinds of question — a disagreement with
the separating feature (tails, gills, how it moves), something the model saw that you did not
mark, a sensitive family it could not find — ranked by whether the answer changes the band. A
suggestion that is a listed invasive goes first and still enters the invasive check only if
you say it was there. *Keep mine* or *it's the model's*: either way the model is not called
again. Unsettled band-changing disagreements cost certainty and say so.

**The biological index.** 53 macroinvertebrate families scored under **BMWP/ASPT** or, where
the coordinates resolve to Portugal or Spain, the Iberian **IBMWP/IASPT** — both tables
checked against published ones. Banded on the WFD's five classes from the mean, because a tray
never approaches the effort an index's own total classes assume; IBMWP's total class is shown
beside it, labelled as reading low. Effort caps the claim: three families under one stone
cannot earn *High*, and two tolerant families cannot prove a stream is dead. An order-level
answer ("some kind of stonefly") is scored from the group median and flagged, not thrown away.
An animal an index does not score (mosquito larvae under BMWP) is recorded, not scored, and
still feeds the health rules.

**The One Health rules.** Fifteen rules over the index, the pressures, the invasive check, the
exposure answer and the weather either side of the visit: harmful algal blooms, sewage indicators, chemical sheen, mosquito
breeding, parasite-host snails, invasive biosecurity, habitat degradation, thermal and
drought resilience, sedimentation, storm run-off after heavy rain, heavy rain and heat ahead,
and the wellbeing a stream in good condition provides.
Exposure escalates: the same water quality is a different finding where children paddle.

**The weather a visit cannot see** (`weather.py`). The 48 hours either side of a check come
from Open-Meteo (free, no key) and are stored with it. Rain just before a visit means the stream
is at its dirtiest and a paddle can wait; sewage signs after rain point at a storm overflow and
in dry weather at a misconnected drain, and the authority is asked to look in the right place.
Heavy rain or heat in the forecast is the early warning. A failed lookup costs the context,
never the result.

**Trends and early warning** (`/dashboard`, `/map`, `/site/{key}`). Assessments are keyed to a
~100 m site grid, so a second visit to roughly the same spot extends a series instead of
dropping a new pin — and when you locate yourself near somewhere you have been, the app asks
whether it is the same spot rather than deciding for you. Each site has its own page with the
ecological class plotted over every visit. The dashboard leads with where the water stands,
which sites declined since their last visit, what needs a budget, and **the next 48 hours**:
every site's latest reading re-run through the same rules with the forecast, so the site that
showed sewage and has heavy rain coming is flagged before the rain arrives. A review *replaces* a
visit rather than adding one, so the volunteers who check the model's work most carefully
cannot manufacture trends by doing so.

**Something to actually send** (`/api/assess/{id}/report`). Every serious finding tells the
observer to report it; this is the thing they report *with*. A self-contained incident report
— printable, or Markdown for pasting into a contact form — that leads with what is being
asked for, attributes every observation to a person or to the model, carries the site's
series when it has one, and states its own limits in the body rather than in a footnote
nobody forwards. Plus `/api/export.csv` for the spreadsheet a council officer will actually
open and `/api/export.geojson` for QGIS.

**It works with no signal.** A riverbank under tree cover is where mobile coverage fails, and
a tool that needs connectivity at the moment of observation gets used from the car park
afterwards, from memory. A service worker caches the page and the vocabularies a whole
assessment needs; a submission that cannot reach the server is kept on the phone — answers
and photographs — and sends itself when coverage returns. The queue is visible and can be
flushed by hand, because this is data somebody walked to a stream to collect. It installs to
a home screen.

**A protocol people can hold** (`/field-guide`). What to bring, safety first, how to choose a
riffle and why it is the fair place to judge a stream, how to kick-sample without a net, how
to photograph a tray so the animals are visible, a best-news-first identification table, and
check-clean-dry. Printable, because a river-day group needs paper.

**FHIR R4 export** (`/api/assess/{id}/fhir`), **validated with the official HL7 validator —
no errors, no warnings.** The assessment as a Bundle: a `Location`, an `Observation` panel
carrying the index, EPT richness, the band, who identified the animals and what the second
opinion found; the raw survey and the habitat form as their own Observations; one Observation
per One Health domain with an HL7 interpretation code; a `Flag` per alert; a `Provenance`. Every
project code belongs to one CodeSystem generated from the app's own vocabularies and served at
`/api/fhir/CodeSystem/stream-health`. No code pretends to be LOINC. Validated examples are in
[docs/fhir/](docs/fhir/); see [docs/FHIR.md](docs/FHIR.md).

**A way to find out whether it works** (`scripts/evaluate_observer.py`). Calls the model once
per labelled photo, then measures what it saw, how many simulated volunteer mistakes the second
opinion would catch, and how many questions a correct list still draws. A starter set of
openly licensed larva and nymph photos comes from iNaturalist with `scripts/fetch_inat_eval.py`.
See [docs/EVALUATION.md](docs/EVALUATION.md).

**A sample check anyone can try** (`/`, *Use the sample photos*). Two openly licensed
photographs, a reach and a tray with one nymph in it, placed at OneAquaHealth research site C3.
A vision model's reading of each was recorded once, with the same prompt, and is replayed when
those photographs come back, so the blind second opinion can be seen on a server with no model
key. The replay is labelled as a recording on the page, in the result, the report and the FHIR
Provenance; any other photo is read live. Credits are in `data/samples.json`.

**It works with no model at all.** With no API key and no local model, nothing is read off
the photos, nobody double-checks the identifications, and the citizen answers the form
themselves — and the band, the pressure score, the findings, the actions, the trends and the
FHIR export are all computed the same way. The model makes AquaPlot safer for a novice; it is
not what makes it work.

## Run

Python 3.12 or newer. With [uv](https://docs.astral.sh/uv/):

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest                       # 247 tests, no network, no model
.venv/bin/uvicorn aquaplot.app:app --reload        # http://127.0.0.1:8000
```

Open `/about` for the two-minute tour, `/try` for the sample check, `/` to check a stream, `/site/{key}` for one spot's history, `/dashboard` for the
insights, `/map` for the map, `/field-guide` for the sampling protocol, `/docs` for the
interactive API reference.

A fresh install has an empty dashboard, which is the worst first impression of a tool whose
argument is that a *series* is worth more than one reading. Start with `AQUAPLOT_SEED_DEMO=1`
and an empty database is filled at startup with a small, clearly-labelled demo dataset across
the five research cities, dated over five months, with one site that declines and one that
improves (`src/aquaplot/demo.py`; the Render blueprint sets it, because a free instance's disk
is wiped on every restart). Or post the same visits to a running server through the public API:

```sh
.venv/bin/python scripts/seed_demo.py --url http://127.0.0.1:8000
```

### Choosing a vision model

| `ANTHROPIC_API_KEY` set | Ollama running with a vision model | Backend |
|---|---|---|
| yes | any | Claude (`claude-opus-5`; override with `CLAUDE_MODEL`) |
| no | yes (`ollama pull qwen2.5vl:3b`) | local model via Ollama (`OLLAMA_MODEL` to pick one) |
| no | no | none: the citizen fills the form, everything else is unchanged |

`AQUAPLOT_OBSERVER=claude|ollama|none` forces a choice and `/api/health` reports which is
active. `AQUAPLOT_DB` sets the SQLite path (default `aquaplot.db`). `AQUAPLOT_CLASSIFY_LIMIT`
caps assessments per client address per 10 minutes (default 20, `0` disables) so a public
demo cannot drain an API key. `AQUAPLOT_WEATHER=off` stops the Open-Meteo lookups.

## Where things live

| Path | What |
|---|---|
| `src/aquaplot/observe.py` | The vision model's only job: photo → structured observations. Three backends, one schema, and the labelled replay for the sample photos. |
| `src/aquaplot/secondopinion.py` | The citizen's list against the model's blind one: questions, the feature that settles each, the band at stake. |
| `src/aquaplot/bioindex.py` | BMWP/ASPT and IBMWP/IASPT, index choice by country, WFD bands, the effort cap, the coarse-identification rule. |
| `src/aquaplot/habitat.py` | The visual field form: scoring, validation, model-vs-citizen precedence. |
| `src/aquaplot/onehealth.py` | The rule engine. Every finding carries a rule id, its evidence and an action. |
| `src/aquaplot/assess.py` | Composes the stages; the certainty rule; the confirmation queue; `reassess` for review. |
| `src/aquaplot/places.py` | Coordinates → administrative chain, anywhere; the OneAquaHealth research cities. |
| `src/aquaplot/status.py` | Species + place → Native / Invasive / Naturalized, with the listing jurisdiction. |
| `src/aquaplot/weather.py` | The 48 hours either side of a visit and the 48-hour outlook, from Open-Meteo. Injectable, stored with the check. |
| `src/aquaplot/demo.py` | The labelled demo dataset, seeded into an empty store at startup with `AQUAPLOT_SEED_DEMO=1`. |
| `src/aquaplot/store.py` | SQLite: sites on a ~100 m grid, trends, the alert feed, badges. |
| `src/aquaplot/fhir.py` | FHIR R4 Bundle export, conforming to the OneAquaHealth IG profiles, and the project CodeSystem. |
| `src/aquaplot/oah.py` | The OneAquaHealth research sites, and a check as the project's Citizen Science App submission. |
| `src/aquaplot/evaluation.py` | Scores stored model output on labelled photos: accuracy, mistakes caught, false alarms. |
| `src/aquaplot/report.py` | The incident report a citizen sends an authority, as Markdown and as a printable page. |
| `src/aquaplot/data/bioindicators.json` | 53 families: BMWP and IBMWP scores, what to look for, what finding it means. |
| `src/aquaplot/data/habitat_indicators.json` | The field form. Drives the prompt, the validator, the UI and the scoring. |
| `src/aquaplot/data/status_seed.json` | 101 listed invasives with jurisdiction, habitat and One Health relevance. |
| `src/aquaplot/data/pilot_sites.json` | The five OneAquaHealth research cities. |
| `src/aquaplot/data/oah_reference.json` | Snapshot of the OneAquaHealth public API: 106 research sites and the Citizen Science App's answer codes. Refresh with `scripts/fetch_oah_reference.py`. |
| `src/aquaplot/data/field_guide.md` | The sampling protocol. Served at `/field-guide`; one copy, read by people and by the program. |
| `src/aquaplot/static/about.html` | AquaPlot in two minutes, at `/about`: the problem, the moment worth seeing, what is and is not claimed. `/try` opens the sample check. |
| `src/aquaplot/static/check.html` | The guided citizen workflow, including the animal picker and the second-opinion cards. |
| `src/aquaplot/static/site.html` | One spot: its series, its chart, every visit's report. |
| `src/aquaplot/static/dashboard.html` | The insights dashboard. |
| `src/aquaplot/static/sw.js` | Service worker: the app shell and the vocabularies, cached for the riverbank. |
| `src/aquaplot/static/map.html` | Leaflet map: AquaPlot sites and the OneAquaHealth research sites over iNaturalist layers. No build step. |
| `src/aquaplot/{identify,pipeline,schema,inputs,area,inat}.py` | Inherited from SpeciesGuard; see lineage below. |

## Documentation

- [docs/FIELD-GUIDE.md](docs/FIELD-GUIDE.md) — how to check a stream: what to bring, safety, sampling, photographing a tray. Also served at `/field-guide`.
- [docs/API.md](docs/API.md) — every endpoint, with examples. Interactive version at `/docs`.
- [docs/ASSESSMENT.md](docs/ASSESSMENT.md) — how a photo becomes a band, stage by stage, who identifies, and what the certainty number means.
- [docs/EVALUATION.md](docs/EVALUATION.md) — how the second opinion is measured, and how to read the numbers honestly.
- [docs/ONE-HEALTH.md](docs/ONE-HEALTH.md) — every rule, its trigger, its evidence and its action.
- [docs/FHIR.md](docs/FHIR.md) — the resources, the codes, validating it yourself, and what would have to happen to make it standard.
- [docs/HACKATHON.md](docs/HACKATHON.md) — track alignment, the judging criteria, the build timeline and the timed demo script.
- [docs/DEVPOST.md](docs/DEVPOST.md) — the submission text, section by section.
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to correct a rule, add a family, or swap in a country-specific index.
- [docs/AREA-VIEWER.md](docs/AREA-VIEWER.md), [docs/CLASSIFIER.md](docs/CLASSIFIER.md) — the inherited features.

## Lineage

AquaPlot is a fork of **SpeciesGuard** ([BabayoAP/nativeview](https://github.com/BabayoAP/nativeview)),
a terrestrial invasive-species classifier the same author built for NextStep Hacks 2026.
What carried over: the pipeline shape, the certainty rule and its insistence on an evidence
trail, the cached iNaturalist client, the pluggable model backends, and the area viewer.
What is new here: the freshwater domain entirely — the citizen-first identification and the
blind second opinion, both biotic indices, the field form, the One Health rule engine, the
assessment pipeline and its review loop, persistence and trends, the authority report, FHIR
and tabular export, the evaluation harness, the generalised geography, the offline field app,
and every page except the classifier. By `git diff --shortstat` against the imported commit:
about 6,900 lines of new Python and 2,100 of new interface, and 179 of the 247 tests. SpeciesGuard's
code was written on Sep 16–17, 2026, inside this hackathon's Sep 16–30 development window
([its commit history](https://github.com/BabayoAP/nativeview/commits)). The original project's PRD is kept at
[docs/PRD-SPECIESGUARD.md](docs/PRD-SPECIESGUARD.md) and its submission notes at
[docs/HACKATHON-NEXTSTEP.md](docs/HACKATHON-NEXTSTEP.md), so the boundary between the two is
on the record rather than implied.

## Honesty about what this is not

- **Not a Water Framework Directive classification.** A formal classification needs a
  standardised three-minute kick sample, laboratory identification and a reference-site
  comparison. AquaPlot is a screening tool, and every result says so.
- **Not a medical, water-quality or regulatory determination.** Findings name the authority
  that can make one and tell the user to contact it.
- **The second opinion has not yet been measured on real trays.** The harness to measure it
  exists and is documented; until it has been run, "it catches volunteers' mistakes" is the
  design intent, not a result.
- **The certainty factors are priors, not measured calibration.** They order outcomes
  sensibly and explain themselves; no calibration study has been run. `assessment_version`
  changes whenever the rules do, so results stay comparable.
- **The seed invasive list is unverified.** It cites Cal-IPC, CDFW, USGS, UC IPM and EU
  Regulation 1143/2014, and every entry must be re-checked against those authorities before
  it is used for anything beyond screening.
- **Two indices, not every national method.** BMWP everywhere, IBMWP in Portugal and Spain.
  Portugal's WFD method is the multimetric IPtI and Italy's is IBE; neither is implemented.
  Adding an index is a score column and a few lines (see [CONTRIBUTING.md](CONTRIBUTING.md)).
  The catalogue has 53 families; IBMWP scores 125, and a family outside the catalogue is
  reported as unmatched rather than guessed.
- **The FHIR CodeSystem is provisional.** It is published, complete and validated, but it is
  a project terminology marked `draft`; no code pretends to be LOINC, and
  [docs/FHIR.md](docs/FHIR.md) states exactly what would have to happen to make it standard.

## Data sources

| Source | Used for | Terms |
|---|---|---|
| [iNaturalist API](https://api.inaturalist.org/v1/docs/) | Taxonomy, establishment means, administrative places, sightings | Free, attribution, ~1 req/s |
| BMWP family scores (Armitage et al. 1983) | The biological index | Published methodology, widely reproduced |
| IBMWP family scores (Alba-Tercedor et al. 2002; MAGRAMA 2011) | The index in Portugal and Spain | Published methodology; checked against the tables in the `biomonitoR` R package |
| EU Regulation (EU) 1143/2014 Union list | Invasive species of Union concern | Public |
| Cal-IPC Inventory, CDFW, USGS NAS, UC IPM | Inherited Californian invasive entries | Public lists |
| [Open-Meteo](https://open-meteo.com) | Rain and temperature either side of a visit, and the 48-hour outlook | Free, no key, CC BY 4.0 |
| Sample photos: John Rostron (geograph.org.uk, CC BY-SA 2.0); Johan Kjær Prehn (iNaturalist, CC BY 4.0) | The sample check | Credited in `data/samples.json` and on the page |
| [OneAquaHealth field protocols](https://zenodo.org/records/20344421) | The shape of the site-characterisation form | CC, cited |
| [Global Forest Watch](https://www.globalforestwatch.org/) (Hansen/UMD/Google/USGS/NASA) | Tree-cover loss tiles | CC BY 4.0 |
| Esri World Imagery and Reference | Basemap and labels | Esri attribution |

## Licence

MIT. See [LICENSE](LICENSE).
