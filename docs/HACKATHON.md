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
second visit to the same spot becomes a trend, the weather either side of the visit says whether
sewage came from a storm overflow or a misconnection and warns of heavy rain or heat ahead, a finding that says "report this" comes with a
report to send, and every assessment exports as a FHIR R4 Bundle that conforms to the
OneAquaHealth project's own FHIR IG and passes the official HL7 validator, so an ecosystem
reading can reach the health systems on the other side of the One Health link. A check made at
one of the project's 106 research sites is linked to it by the project's own site code, and can
be exported as the project's Citizen Science App submission in the app's own answer codes.

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
- **Something a judge can try without a stream.** *Use the sample photos* on the first step
  loads two openly licensed photographs whose model reading was recorded once and is replayed,
  labelled as a recording, so the second opinion can be seen on a deployment with no model key.
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
- **Track 6, Resilience Informatics.** A predictive outlook: every monitored site's latest
  reading re-run through the same rules with the next 48 hours' forecast (Open-Meteo), so a site
  that has shown sewage and has heavy rain coming is flagged before the overflow runs, and open,
  slow water is flagged before a heatwave's oxygen crash. The weather either side of each visit
  is stored with it and changes what a finding means: sewage after heavy rain sends the
  authority to the overflow records, sewage in dry weather to misconnected drains. Plus repeat
  visits as series rather than pins, an early-warning feed of sites whose latest state reached
  concern, dated dry and stagnant findings as the urban drought signal, and an incident report
  that turns a complaint into evidence.
- **Track 7, Digital Health Standards.** A FHIR R4 export that conforms to the OneAquaHealth IG
  ([`hl7-eu/oah`](https://github.com/hl7-eu/oah)): `location-oah` for the site, carrying the
  project's own site code at a research site, and `observation-indicators-oah` for every IG
  indicator the check has evidence for, coded from the IG's CodeSystem. It passes the HL7
  validator with the IG loaded, with no errors or warnings. The profile fixes `status = final`,
  so only evidence a person gave or confirmed goes into one. What the IG has no code for yet
  (the WFD band, BMWP, the second opinion) is in a published CodeSystem generated from the
  app's own vocabularies, and no code pretends to be LOINC. See [FHIR.md](FHIR.md).

## How it relates to the OneAquaHealth app

The project's Citizen Science App records a site's channel, banks, flow, water colour,
habitats, vegetation and an overall Good / Moderate / Poor judgement. It does not ask what lives
in the water. AquaPlot is designed to sit beside it: the animals and the check on them, the One
Health read-out, the authority report and the FHIR hand-off are the parts it adds. It meets the
project in the project's own terms, from a snapshot of the project's public API
(`api.enora-oah.eu`):

- **Research sites.** The 106 sites in Benevento, Coimbra, Ghent, Oslo and Toulouse are on the
  map. A check within 200 m of one is linked to it by code on the result page, in the FHIR
  Location's identifier and in the app export. A citizen reading where the project's laboratory
  also samples is the one the project can compare against its own data.
- **The app's submission.** `GET /api/assess/{id}/oah-app` builds the app's
  `CitizenSubmissionPutDTO` from the answers a person gave or confirmed, in the app's answer
  codes. Each field names its source, and each answer that did not translate is listed with the
  reason. AquaPlot does not send it, because submitting needs an app account.
- **The FHIR IG.** As above.

The field form is modelled on the project's published field sampling protocol
([Zenodo 20344421](https://zenodo.org/records/20344421)).

## Against the judging criteria

Weights are from the Devpost rules; each criterion is scored 1–10.

| Criterion | Where to look |
|---|---|
| **Impact & alignment with the OneAquaHealth mission (30%)** | Benthic macroinvertebrates, the indicator group the project's protocols put first, scored with the index Iberian practice uses where the project's Coimbra pilot is. These are exactly what the project's own Citizen Science App does not ask about. Mosquito larvae and parasite-host snails are carried through to human and animal findings. Checks at the project's 106 research sites are linked to them by the project's site code, and every check can leave in the project's own formats: its app's submission and its FHIR IG. Every finding ends in an action split between the citizen, the community and the authority, and the authority's action arrives as a document the citizen can send. |
| **Innovation & creativity (20%)** | The model as a *blind second opinion* on the volunteer rather than the identifier: questions ranked by whether the answer changes the band, with the feature that settles each. Plus an alert that waits for a human, a review that supersedes a visit instead of inventing one, and one rule applied to every hand-off: only what a person stands behind crosses into the project's formats. |
| **Technical implementation (20%)** | One JSON file generates the prompt, the validator, the UI, the scoring and the FHIR CodeSystem. Every network call is injectable, so 244 tests run with no network and no model. The FHIR export is validated against the OneAquaHealth IG's profiles with the HL7 validator. The whole system degrades: no model, no place, no coordinates and no photo each cost a named certainty factor instead of an error. |
| **Usability & UX (15%)** | Five steps, plain language throughout, identification by shape, a searchable ID guide, a printable field guide, keyboard and screen-reader support, and a result that opens with one sentence about people before any number. It works offline, because riverbanks do not have signal. |
| **Feasibility & scalability (15%)** | Geography, including which biotic index applies, is resolved from coordinates rather than hard-coded. Free-tier deployable: SQLite, no build step, no services, and it degrades to a hand-filled form with no API key. Another national index is a score column and a few lines; another data source is one adapter. The project's own FHIR IG and app schema are the integration path, not a new one. CSV, GeoJSON and FHIR mean the data outlives this deployment. |

## Build timeline and prior work

AquaPlot is a fork of the author's own earlier project, **SpeciesGuard**
([BabayoAP/nativeview](https://github.com/BabayoAP/nativeview)), a terrestrial
invasive-species classifier built for NextStep Hacks 2026 (Sep 11–17, 2026). That is stated
here, in the README and in the first commit message rather than left to be discovered.

| When | What |
|---|---|
| Sep 16–17, 2026 | **SpeciesGuard, the author's earlier project, built for another hackathon.** The classification pipeline, the certainty rule and evidence trail, the cached iNaturalist client, pluggable model backends, and the area viewer. Its code was committed on Sep 16 and 17, inside this hackathon's development window (Sep 16–30), as [its commit history](https://github.com/BabayoAP/nativeview/commits) shows. Only its PRD (Sep 11) and a two-line README (Sep 14) are older, and neither is code. Its PRD is at [PRD-SPECIESGUARD.md](PRD-SPECIESGUARD.md) and its own submission notes at [HACKATHON-NEXTSTEP.md](HACKATHON-NEXTSTEP.md). |
| Sep 23, 2026 | **Built for this hackathon.** The freshwater domain: the BMWP/ASPT index and its 53-family catalogue; the visual field form and its vocabulary; the One Health rule engine; the assessment pipeline, its certainty rule and its review loop; the generalised geography and the EU Union-list entries; persistence, site trends, the alert feed and badges; the FHIR R4 exporter; the guided citizen workflow, the dashboard and the AquaPlot layer on the map. |
| Sep 24, 2026 | The authority report and its printable page; CSV and GeoJSON export; nearby-site detection so a repeat visit joins its series; the per-site history page and its chart; the offline service worker, the IndexedDB outbox and the web manifest; the progress rail, focus management and the searchable ID guide; the field guide; the API reference and the contributing guide. |
| Sep 27, 2026 | Citizen-first identification and the blind second opinion; the IBMWP index and index choice by country, with the catalogue's scores checked against published tables; the evaluation harness and the iNaturalist test-set builder; the FHIR export brought to zero validator errors and the CodeSystem published. |
| Sep 28, 2026 | The sample check (openly licensed photos with a recorded, labelled model reading, so the second opinion works without a model key); the weather either side of a visit and three weather rules; the 48-hour outlook on the dashboard. |
| Sep 28, 2026 | OneAquaHealth interoperability: the 106 research sites and the Citizen Science App's answer codes from the project's public API; a check as the app's submission; the FHIR export brought into conformance with the project's IG (`hl7-eu/oah`) and validated against its profiles; the research sites on the map. |

By `git diff --shortstat` against the imported commit: about 6,900 lines of new Python and
2,100 of new interface, and 176 of the 244 tests. `git log` separates the imported commit from
everything after it.

## Submission checklist

- [ ] **Repository made public** (it is private today)
- [x] Source and documentation ([API](API.md), [field guide](FIELD-GUIDE.md), [rules](ONE-HEALTH.md), [FHIR](FHIR.md), [evaluation](EVALUATION.md), [contributing](../CONTRIBUTING.md))
- [x] Working prototype, runnable in three commands, with a test suite that needs no network
- [x] Track alignment stated (above)
- [x] Project description (this file and the README)
- [x] Prior work disclosed
- [ ] Evaluation run and the results recorded in [EVALUATION.md](EVALUATION.md). With no API key,
      one option is to have Claude Code run it by looking at the iNaturalist photos with the labels
      hidden, disclosed as exactly that rather than as `observe.ClaudeObserver` API calls; decide first
- [ ] Before judging opens (Oct 1): open the live link so the free instance is awake, and try
      *Use the sample photos* on it once
- [ ] Live link deployed (`render.yaml` blueprint is in the repository)
- [ ] Demo video, 3–5 minutes (the sample check on step 1 makes it possible without a stream)
- [ ] Eligibility confirmed: registered on Devpost, and the Devpost overview says "students
      only" and "team participation" (the rules page says individuals or teams)
- [ ] Submitted on Devpost before Oct 4, 2026, 9:00 pm PDT

## Demo script (for the video)

1. **The problem, at a real stream.** Open `/`, locate, name the spot. (No stream to hand: *Use the
   sample photos* runs steps 2–6 on real photographs, placed at research site C3.)
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
7. **The weather.** Point at the weather line on the result, then open `/dashboard` and scroll to
   *The next 48 hours*: the same rules, re-run with the forecast. (If nothing is forecast that
   day, say so; the tests show the rain case.)
8. **The alert loop.** An alert held at concern until you confirm the observation under it.
9. **The thing you send.** Open the report. It is dated, located, attributed, says who
   identified the animals and what the independent check found, and states its own limits.
10. **The trend.** `/site/{key}`: the class plotted across visits, and a site that declined.
11. **Offline.** Airplane mode, complete a check, show it queued, reconnect, watch it send.
12. **The project's own terms.** Do the check at Vale das Flores in Coimbra: the result names
    OneAquaHealth research site C3. Open *Export for the OneAquaHealth app*: the app's own
    codes, each field's source, and what did not translate and why. Then
    `/api/assess/{id}/fhir`: the Location carries `C3`, the indicators use the project's IG
    profiles, and the validator, run with the IG loaded, reports no errors and no warnings.
    Say it once: only what a person confirmed is marked final.
13. **Scale.** `/map`, with the 106 research sites shown. Jump to Coimbra: the same check scores
    with IBMWP there, because the index is resolved from the coordinates, not hard-coded.
