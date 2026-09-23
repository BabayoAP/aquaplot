# IEEE OneAquaHealth Global Hackathon 2026 — submission notes

**Deadline:** Sep 30, 2026, 9:00 pm PDT. **Submission:** track alignment, project
description, a 3–5 minute demo video, a public repository, and a working prototype.

## One paragraph

Riffle turns a walk past an urban stream into a health reading. A citizen photographs the
reach, scoops gravel from a shallow fast patch into a pale tray and photographs what moves,
and answers the two questions a camera cannot answer — what it smells like, and who gets into
the water. A vision model reads structured field observations out of the photographs; published
indices and a readable rule engine turn those observations into a Water Framework Directive
band, a visual pressure score, and findings for ecosystem, human and animal health, each
carrying the evidence and the action it implies. A health alert is held at *concern* until a
person confirms the observation it rests on, and the app asks for exactly that observation
first. Assessments are keyed to the spot on the ground, so a second visit becomes a trend
rather than a new pin, and any assessment exports as a FHIR R4 Bundle so an ecosystem reading
can reach the health systems on the other side of the One Health link.

## Track alignment

**Primary — Track 3: AI-Supported Assessment.** The split between what the model does and what
the rules do is the architecture, not a caveat on it. `observe.py` asks a vision-language model
only for *observations* in a fixed, generated vocabulary, with a per-observation confidence and
an explicit licence to answer "I cannot tell from this photo". `bioindex.py` and `onehealth.py`
make every determination from published indices and readable rules, and each finding names the
rule id, the evidence and the action. The human-in-the-loop is a mechanism: `onehealth.py`
refuses to raise an alert on unconfirmed model output, `assess.py` ranks the confirmation queue
by what confirming would change, and `reassess` folds corrections back in without re-running
the model — so a correction cannot be silently overwritten. Tests cover each of those.

**Track 1: Citizen Science UX.** Four steps at the water's edge, no account, no jargon. Every
question is rendered from `/api/form` — the same file that generates the model's prompt and the
server's validator — and every option is written in plain language with a one-line *why*. The
ID guide describes 53 families by what to look for and what finding them means, never by
taxonomy. The flow works with no model configured at all.

**Track 2: Data-to-Insight.** `/dashboard` and `/map`. One row per place on the ground, the
band distribution, monthly activity, and which sites scored worse than their previous visit.
`/api/sites`, `/api/insights` and `/api/alerts` are the same data for anyone else's tools.

**Track 6: Resilience Informatics.** The site grid and the supersede rule exist so trends are
real. `/api/alerts` is an early-warning feed of sites whose *latest* state reached concern or
alert. The thermal and drought rule asks citizens to date every dry or stagnant finding,
because that is the climate signal nobody is currently collecting in cities.

**Track 7: Digital Health Standards.** `fhir.py` exports a FHIR R4 Bundle hung off a Location:
an Observation panel for the status, Observations for the raw survey and the field form, one
per One Health domain with an HL7 interpretation code, a Flag per alert, and a Provenance
recording the model and the human confirmations. No code pretends to be LOINC, and
[FHIR.md](FHIR.md) says exactly what would have to happen to make the CodeSystem standard.

**Track 5: Community & Gamification.** Anonymous contributor ids, and badges that reward the
behaviours which make the data useful — returning to the same site, confirming or correcting
the model, covering more than one stream — rather than volume, which would reward spamming
the map.

## Against the judging criteria

| Criterion | Where to look |
|---|---|
| **Impact & alignment with the OneAquaHealth mission** | The field form is modelled on the project's own site-characterisation protocol; benthic macroinvertebrates are the indicator group those protocols put first; mosquitoes and parasite-host snails are carried through to human and animal findings; the five research cities ship as entry points. Every finding ends in an action, split between the citizen, the community and the authority. |
| **Innovation & creativity** | Using the model as an *observer* and rules as the *decider*, and making that split load-bearing: an alert that waits for a human, a confirmation queue ranked by what it would change, and a review that supersedes a visit instead of inventing one. |
| **Architecture** | One JSON file generates the prompt, the validator, the UI and the scoring. Every network call is injectable, so 141 tests run with no network and no model. The whole system degrades: no model, no place, no coordinates and no photo each cost a named certainty factor instead of an error. |
| **UX** | Four steps, plain language throughout, `why` on every question, the ID guide, and a result that opens with one sentence about people before any number. |
| **Scale** | Geography is resolved from coordinates anywhere on Earth rather than hard-coded. Free-tier deployable: SQLite, no build step, no services. A country-specific biotic index is one adapter in `bioindex.py`; a GBIF or Cal-IPC source is one adapter in `area.py`. |

## Build timeline and prior work

Riffle is a fork of the author's own earlier project, **SpeciesGuard**
([BabayoAP/nativeview](https://github.com/BabayoAP/nativeview)), a terrestrial
invasive-species classifier built for NextStep Hacks 2026 (Sep 11–17, 2026). That is stated
here, in the README and in the first commit message rather than left to be discovered.

| When | What |
|---|---|
| Sep 11–17, 2026 | **Prior work, not part of this submission.** SpeciesGuard: the classification pipeline, the certainty rule and evidence trail, the cached iNaturalist client, pluggable model backends, and the area viewer. Its PRD is at [PRD-SPECIESGUARD.md](PRD-SPECIESGUARD.md) and its own submission notes at [HACKATHON-NEXTSTEP.md](HACKATHON-NEXTSTEP.md). |
| Sep 23, 2026 | **Built for this hackathon.** The freshwater domain: the BMWP/ASPT index and its 53-family catalogue; the visual field form and its vocabulary; the One Health rule engine; the assessment pipeline, its certainty rule and its review loop; the generalised geography and the EU Union-list entries; persistence, site trends, the alert feed and badges; the FHIR R4 exporter; the guided citizen workflow, the dashboard and the Riffle layer on the map; 73 new tests. |

Roughly 2,600 lines of new Python and 1,400 of new interface. `git log` separates the imported
commit from everything after it.

## Submission checklist

- [x] Public repository with source and documentation
- [x] Working prototype, runnable in three commands, with a test suite that needs no network
- [x] Track alignment stated (above)
- [x] Project description (this file and the README)
- [x] Prior work disclosed
- [ ] Live link deployed (`render.yaml` blueprint is in the repository)
- [ ] Demo video, 3–5 minutes
- [ ] Submitted on Devpost before Sep 30, 2026, 9:00 pm PDT

## Demo script (for the video)

1. **The problem, at a real stream.** Open `/`, locate, name the spot.
2. **Two photographs.** The reach, then the tray. Say what a riffle is and why the sample comes
   from there.
3. **The two questions a camera cannot answer.** Smell, and who gets into the water.
4. **The result.** Band first, then the sentence about people. Point at one finding and read
   its evidence and its action aloud — that is the explainability claim, on screen.
5. **The loop.** Show an alert held at concern, confirm the observation, watch it become an
   alert. This is the part judges have not seen elsewhere.
6. **The trend.** `/dashboard`: a site that declined between visits, and what it asks the
   authority for.
7. **Interoperability.** `/api/assess/{id}/fhir`, one scroll through the Flags, and the
   sentence about not inventing LOINC codes.
8. **Scale.** `/map`, jump to another research city; say that the geography is resolved, not
   hard-coded.
