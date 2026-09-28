# IEEE OneAquaHealth Global Hackathon 2026 — submission notes

**Deadline:** Oct 4, 2026, 9:00 pm PDT. **Submission:** track alignment, project
description, a 3–5 minute demo video, a public repository, and a working prototype.

## One paragraph

AquaPlot turns a walk past an urban stream into a health reading, with the volunteer in charge
of it. A citizen photographs the reach, scoops gravel from a shallow fast patch into a pale
tray, and identifies what lives there from a guide organised by shape rather than by taxonomy.
A vision model looks at the same tray photograph **without seeing their answers** and raises
questions only where it saw something different — *you marked a stonefly; this may be a
mayfly; count the tails* — ranked by whether the answer would change the stream's reading. The
citizen decides. Published indices (BMWP, or the Iberian IBMWP in Portugal and Spain) and a
readable rule engine then turn the evidence into a Water Framework Directive screening band, a
visual pressure score and findings for ecosystem, human and animal health, each carrying its
evidence and its action. A health alert waits for a person to confirm what it rests on. A
second visit to the same spot becomes a trend, a finding that says "report this" comes with a
report to send, and every assessment exports as a FHIR R4 Bundle that passes the official HL7
validator, so an ecosystem reading can reach the health systems on the other side of the One
Health link.

## Track alignment

### Track 3: AI-Supported Assessment

The track asks for AI that supports stream assessment **without replacing human judgement**,
for a problem it names precisely: *citizen observations can be inconsistent and error-prone.*
AquaPlot's answer is a specific division of labour, and each part of it is enforced in code
and covered by tests.

- **The citizen identifies; the model checks, blind.** The person's own identifications are
  what get scored. The model is shown the same tray photo without their list, so its agreement
  is independent evidence rather than an echo. `secondopinion.py` turns the difference between
  the two lists into three kinds of question: a likely confusion, with the feature that
  separates the pair; an animal the model saw that the citizen did not mark; a sensitive family
  it could not find. Every question carries the band the stream would get if the model were
  right, and the decisive ones come first. *(Validation checks, human-in-the-loop.)*
- **The model observes; the rules decide.** `observe.py` asks the model only for observations
  in a fixed vocabulary generated from the field form, with a confidence each and an explicit
  licence to answer "I cannot tell from this photo". Every determination — band, pressure,
  health finding — comes from published indices and readable rules, and each finding names its
  rule, its evidence and its action. *(Explainable AI.)*
- **A health alert waits for a person.** `onehealth.py` will not raise an alert on unconfirmed
  model output; it holds it at *concern*, says why, and the review asks for exactly the
  observation it rests on. A review never calls the model again, so a correction cannot be
  silently overwritten, and taking the model's answer is recorded as that, never as agreement.
  *(Human-in-the-loop.)*
- **Prompts that ask the right question.** The model's prompt is generated from the same JSON
  as the form and the validator, tells it that an honest "some kind of mayfly" beats a confident
  wrong family, and never asks it about what a photo cannot show, such as smell. *(AI prompts.)*
- **A way to know whether any of it works.** `scripts/evaluate_observer.py` measures, on
  labelled photos, what the model sees, how many simulated volunteer mistakes the second
  opinion catches, and how many questions a correct list still draws. See
  [EVALUATION.md](EVALUATION.md).

### Also serves

- **Track 1, Citizen Science UX.** Five steps, no account, no jargon; an animal picker grouped by
  shape and searchable by what you can see; `why` on every question; a printable field guide;
  keyboard and screen-reader support; and it works with no signal, keeping photographs and
  answers on the phone until coverage returns.
- **Track 2, Data-to-Insight.** Dashboard, map, a page per site with its class over time, an
  alert feed, and the whole dataset as CSV and GeoJSON.
- **Track 6, Resilience Informatics.** Repeat visits become series rather than pins; an
  early-warning feed of sites whose latest state reached concern; dated dry and stagnant
  findings as the urban drought signal; and an incident report that turns a complaint into
  evidence.
- **Track 7, Digital Health Standards.** A FHIR R4 export that passes the HL7 validator with no
  errors or warnings, a published CodeSystem generated from the app's own vocabularies, and no
  code pretending to be LOINC. See [FHIR.md](FHIR.md).

## How it relates to the OneAquaHealth app

The project already has a citizen-science app for stream assessment. AquaPlot is designed to
sit beside it: the identification check, the One Health read-out, the authority report and the
FHIR hand-off are the parts it adds, and everything it records leaves as CSV, GeoJSON or FHIR so
it can feed the project's data rather than compete with it. The field form is modelled on the
project's published site-characterisation protocol, and the five research cities ship as entry
points.

## Against the judging criteria

| Criterion | Where to look |
|---|---|
| **Impact & alignment with the OneAquaHealth mission** | Benthic macroinvertebrates, the indicator group the project's protocols put first, scored with the index Iberian practice uses where the project's Coimbra pilot is. Mosquito larvae and parasite-host snails carried through to human and animal findings. Every finding ends in an action split between the citizen, the community and the authority, and the authority's action arrives as a document the citizen can send. |
| **Innovation & creativity** | The model as a *blind second opinion* on the volunteer rather than the identifier: questions ranked by whether the answer changes the band, with the feature that settles each. Plus an alert that waits for a human and a review that supersedes a visit instead of inventing one. |
| **Architecture** | One JSON file generates the prompt, the validator, the UI, the scoring and the FHIR CodeSystem. Every network call is injectable, so 210 tests run with no network and no model. The FHIR export is validated against the HL7 validator. The whole system degrades: no model, no place, no coordinates and no photo each cost a named certainty factor instead of an error. |
| **UX** | Five steps, plain language throughout, identification by shape, a searchable ID guide, a printable field guide, keyboard and screen-reader support, and a result that opens with one sentence about people before any number. It works offline, because riverbanks do not have signal. |
| **Scale** | Geography, including which biotic index applies, is resolved from coordinates rather than hard-coded. Free-tier deployable: SQLite, no build step, no services, and it degrades to a hand-filled form with no API key. Another national index is a score column and a few lines; another data source is one adapter; CSV, GeoJSON and FHIR mean the data outlives this deployment. |

## Build timeline and prior work

AquaPlot is a fork of the author's own earlier project, **SpeciesGuard**
([BabayoAP/nativeview](https://github.com/BabayoAP/nativeview)), a terrestrial
invasive-species classifier built for NextStep Hacks 2026 (Sep 11–17, 2026). That is stated
here, in the README and in the first commit message rather than left to be discovered.

| When | What |
|---|---|
| Sep 11–17, 2026 | **Prior work, not part of this submission.** SpeciesGuard: the classification pipeline, the certainty rule and evidence trail, the cached iNaturalist client, pluggable model backends, and the area viewer. Its PRD is at [PRD-SPECIESGUARD.md](PRD-SPECIESGUARD.md) and its own submission notes at [HACKATHON-NEXTSTEP.md](HACKATHON-NEXTSTEP.md). |
| Sep 23, 2026 | **Built for this hackathon.** The freshwater domain: the BMWP/ASPT index and its 53-family catalogue; the visual field form and its vocabulary; the One Health rule engine; the assessment pipeline, its certainty rule and its review loop; the generalised geography and the EU Union-list entries; persistence, site trends, the alert feed and badges; the FHIR R4 exporter; the guided citizen workflow, the dashboard and the AquaPlot layer on the map. |
| Sep 24, 2026 | The authority report and its printable page; CSV and GeoJSON export; nearby-site detection so a repeat visit joins its series; the per-site history page and its chart; the offline service worker, the IndexedDB outbox and the web manifest; the progress rail, focus management and the searchable ID guide; the field guide; the API reference and the contributing guide. |
| Sep 27, 2026 | Citizen-first identification and the blind second opinion; the IBMWP index and index choice by country, with the catalogue's scores checked against published tables; the evaluation harness and the iNaturalist test-set builder; the FHIR export brought to zero validator errors and the CodeSystem published. |

By `git diff --shortstat` against the imported commit: about 5,900 lines of new Python and
2,100 of new interface, and 142 of the 210 tests. `git log` separates the imported commit from
everything after it.

## Submission checklist

- [ ] **Repository made public** (it is private today)
- [x] Source and documentation ([API](API.md), [field guide](FIELD-GUIDE.md), [rules](ONE-HEALTH.md), [FHIR](FHIR.md), [evaluation](EVALUATION.md), [contributing](../CONTRIBUTING.md))
- [x] Working prototype, runnable in three commands, with a test suite that needs no network
- [x] Track alignment stated (above)
- [x] Project description (this file and the README)
- [x] Prior work disclosed
- [ ] Evaluation run and the results recorded in [EVALUATION.md](EVALUATION.md)
- [ ] Live link deployed (`render.yaml` blueprint is in the repository)
- [ ] Demo video, 3–5 minutes
- [ ] Submitted on Devpost before Oct 4, 2026, 9:00 pm PDT

## Demo script (for the video)

1. **The problem, at a real stream.** Open `/`, locate, name the spot.
2. **Two photographs.** The reach, then the tray. Say what a riffle is and why the sample comes
   from there.
3. **You identify.** Open the animal list, search "two tails", pick a stonefly; pick the
   bloodworms. Say it: the person decides what is in the tray.
4. **The two questions a camera cannot answer.** Smell, and who gets into the water.
5. **The second opinion.** The card: *you marked a stonefly; the model thinks this may be a
   mayfly; count the tails and look for gills on the sides.* Point at the line that says the
   band changes if the model is right. Say that the model never saw your answer. Choose. This
   is the part judges have not seen elsewhere.
6. **The result.** Band first, then the sentence about people, then "identified by you,
   double-checked by the model". Read one finding's evidence and action aloud — that is the
   explainability claim, on screen.
7. **The alert loop.** An alert held at concern until you confirm the observation under it.
8. **The thing you send.** Open the report. It is dated, located, attributed, says who
   identified the animals and what the independent check found, and states its own limits.
9. **The trend.** `/site/{key}`: the class plotted across visits, and a site that declined.
10. **Offline.** Airplane mode, complete a check, show it queued, reconnect, watch it send.
11. **Interoperability.** `/api/assess/{id}/fhir`, then the validator output: no errors, no
    warnings. One sentence about not inventing LOINC codes.
12. **Scale.** `/map`, jump to Coimbra: the same check scores with IBMWP there, because the
    index is resolved from the coordinates, not hard-coded.
