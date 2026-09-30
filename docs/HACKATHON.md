# IEEE OneAquaHealth Global Hackathon 2026: submission notes

**Deadline:** Oct 4, 2026, 9:00 pm PDT. **Submission:** track alignment, project
description, a 3–5 minute demo video, a public repository, and a working prototype.

## One paragraph

AquaPlot turns a walk past an urban stream into a health reading, with the volunteer in charge
of it. A citizen photographs the stream, scoops gravel from a shallow fast patch into a pale
tray, and identifies what lives there from a guide organised by shape rather than by taxonomy.
A vision model looks at the same tray photo **without seeing their answers** and raises
questions only where it saw something different (*you marked a stonefly; this may be a
mayfly; count the tails*), ranked by whether the answer would change the stream's reading. The
citizen decides. Published indices (BMWP, or the Iberian IBMWP in Portugal and Spain) and a
readable rule engine then turn the evidence into a Water Framework Directive screening band, a
visual pressure score and findings for ecosystem, human and animal health, each with its
evidence and an action. A health alert waits for a person to confirm what it rests on.

A second visit to the same spot becomes a trend. The weather before and after a visit shows
whether sewage came from a storm overflow or a misconnected drain, and warns of heavy rain or
heat ahead. A finding that says "report this" comes with a report to send. Every assessment
exports as a FHIR R4 Bundle that conforms to the OneAquaHealth project's own FHIR IG and passes
the official HL7 validator, so a reading about the stream can reach health systems. A check
made at one of the project's 106 research sites is linked to it by the project's own site code,
and can be exported as a submission to the project's Citizen Science App, in the app's own
answer codes.

## Track alignment

### Track 3: AI-Supported Assessment

The track asks for AI that supports stream assessment **without replacing human judgement**,
for a problem it names precisely: *citizen observations can be inconsistent and error-prone.*
AquaPlot's answer is a specific division of labour, and each part of it is enforced in code
and covered by tests.

- **The citizen identifies; the model checks, blind.** The person's own identifications are
  what get scored. The model is shown the same tray photo without their list, so when it
  agrees, that is independent evidence. `secondopinion.py` turns the difference between
  the two lists into three kinds of question: a likely confusion, with the feature that
  separates the pair; an animal the model saw that the citizen did not mark; a sensitive family
  it could not find. Every question carries the band the stream would get if the model were
  right, and the decisive ones come first. *(Validation checks, human-in-the-loop.)*
- **The model observes; the rules decide.** `observe.py` asks the model only for observations
  in a fixed vocabulary generated from the field form, each with a confidence, and explicitly
  allows it to answer "I cannot tell from this photo". Every judgement (band, pressure, health
  finding) comes from published indices and readable rules, and each finding names its rule,
  its evidence and its action. *(Explainable AI.)*
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
  concern, dated dry and stagnant findings as a sign of urban drought, and an incident report
  that backs a complaint with evidence.
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
| **Technical implementation (20%)** | One JSON file generates the prompt, the validator, the UI, the scoring and the FHIR CodeSystem. Every network call is injectable, so 305 tests run with no network and no model. The FHIR export is validated against the OneAquaHealth IG's profiles with the HL7 validator. The central claim is *measured*, not asserted: [EVALUATION.md](EVALUATION.md) sweeps observer quality against the review rules and shows an observer missing 40% of the animals still catches 68% of simulated volunteer mistakes, at 0.32 unnecessary questions per tray. That is the case for a model that is only allowed to raise questions. Missing inputs don't break it: no model, no place, no coordinates and no photo each lower a named certainty factor instead of causing an error. |
| **Usability & UX (15%)** | Five steps, plain language throughout, identification by shape, a searchable ID guide, a printable field guide, keyboard and screen-reader support, and a result that opens with one sentence about people before any number. It works offline, because riverbanks often have no signal. |
| **Feasibility & scalability (15%)** | Geography, including which biotic index applies, is resolved from coordinates rather than hard-coded. Free-tier deployable: SQLite, no build step, no services, and it degrades to a hand-filled form with no API key. Another national index is a score column and a few lines; another data source is one adapter. It connects through the project's own FHIR IG and app schema instead of inventing a new route. CSV, GeoJSON and FHIR mean the data outlives this deployment. |

## Build timeline and prior work

AquaPlot is a fork of the author's own earlier project, **SpeciesGuard**
([BabayoAP/nativeview](https://github.com/BabayoAP/nativeview)), a terrestrial
invasive-species classifier built for NextStep Hacks 2026 (Sep 11–17, 2026). This is stated
here, in the README and in the first commit message.

| When | What |
|---|---|
| Sep 16–17, 2026 | **SpeciesGuard, the author's earlier project, built for another hackathon.** The classification pipeline, the certainty rule and evidence trail, the cached iNaturalist client, pluggable model backends, and the area viewer. Its code was committed on Sep 16 and 17, inside this hackathon's development window (Sep 16–30), as [its commit history](https://github.com/BabayoAP/nativeview/commits) shows. Only its PRD (Sep 11) and a two-line README (Sep 14) are older, and neither is code. Its PRD is at [PRD-SPECIESGUARD.md](PRD-SPECIESGUARD.md) and its own submission notes at [HACKATHON-NEXTSTEP.md](HACKATHON-NEXTSTEP.md). |
| Sep 23, 2026 | **Built for this hackathon.** The freshwater domain: the BMWP/ASPT index and its 53-family catalogue; the visual field form and its vocabulary; the One Health rule engine; the assessment pipeline, its certainty rule and its review loop; the generalised geography and the EU Union-list entries; persistence, site trends, the alert feed and badges; the FHIR R4 exporter; the guided citizen workflow, the dashboard and the AquaPlot layer on the map. |
| Sep 24, 2026 | The authority report and its printable page; CSV and GeoJSON export; nearby-site detection so a repeat visit joins its series; the per-site history page and its chart; the offline service worker, the IndexedDB outbox and the web manifest; the progress rail, focus management and the searchable ID guide; the field guide; the API reference and the contributing guide. |
| Sep 27, 2026 | Citizen-first identification and the blind second opinion; the IBMWP index and index choice by country, with the catalogue's scores checked against published tables; the evaluation harness and the iNaturalist test-set builder; the FHIR export brought to zero validator errors and the CodeSystem published. |
| Sep 28, 2026 | The sample check (openly licensed photos with a recorded, labelled model reading, so the second opinion works without a model key); the weather either side of a visit and three weather rules; the 48-hour outlook on the dashboard. |
| Sep 28, 2026 | The two-minute path for judges (`/about`, `/try`); demo data seeded at startup with real dates, and a Render blueprint that works on the free plan; screenshots; the Devpost text and a timed demo script. |
| Sep 28, 2026 | OneAquaHealth interoperability: the 106 research sites and the Citizen Science App's answer codes from the project's public API; a check as the app's submission; the FHIR export brought into conformance with the project's IG (`hl7-eu/oah`) and validated against its profiles; the research sites on the map. |

By `git diff --shortstat` against the imported commit: about 6,900 lines of new Python and
2,100 of new interface, and 237 of the 305 tests. `git log` separates the imported commit from
everything after it.

## Submission checklist

- [x] **Repository made public** (2026-09-28): <https://github.com/BabayoAP/aquaplot>
- [x] Source and documentation ([API](API.md), [field guide](FIELD-GUIDE.md), [rules](ONE-HEALTH.md), [FHIR](FHIR.md), [evaluation](EVALUATION.md), [contributing](../CONTRIBUTING.md))
- [x] Working prototype, runnable in three commands, with a test suite that needs no network
- [x] Track alignment stated (above)
- [x] Project description: [DEVPOST.md](DEVPOST.md) is written to paste into Devpost's fields
- [x] Prior work disclosed
- [x] **Rule-layer evaluation run and recorded** in [EVALUATION.md](EVALUATION.md) (2026-09-28):
      `scripts/evaluate_rules.py` sweeps a synthetic observer's error rate against
      `secondopinion.py`. Headline: an observer missing 40% of the animals still catches 68% of
      simulated volunteer mistakes at 0.32 unnecessary questions per tray. Needs no model, no
      photos and no key, and is deterministic from its seed
- [x] **Model-layer evaluation run on the keyless backend** (2026-09-28), recorded in
      [EVALUATION.md](EVALUATION.md#model-layer-local-backend-2026-09-28): 32 labelled
      iNaturalist photos through Ollama / `qwen2.5vl:3b`. It named no animal on any of them,
      while getting `photo_kind` right 32 of 32 — so the keyless path has no second opinion,
      and the app now says so rather than questioning every family the volunteer got right.
      The labelled set and the harness are built, so this is a real measurement rather than a
      plan for one
- [ ] **Model-layer evaluation against Claude** — the same 32 photos with `ANTHROPIC_API_KEY`
      set, one command (`scripts/evaluate_observer.py eval/inat/labels-subset.csv --out
      eval/claude-results`). This is the one that speaks to the deployed model; the local
      backend's zeros say nothing about it. Do not quote the rule-layer table as evidence the
      model works
- [ ] Before judging opens (Oct 1): open the live link so the free instance is awake, and try
      *Use the sample photos* on it once
- [ ] Live link deployed (`render.yaml` blueprint is in the repository: free plan, no disk, demo data seeded at startup). Put `<live link>/about` in the Devpost description and `<live link>/try` as the first link
- [ ] Demo video, 3–5 minutes (the sample check on step 1 makes it possible without a stream)
- [ ] Eligibility confirmed: registered on Devpost. **The two Devpost pages contradict each
      other.** The overview sidebar says "Students only" and "Team required", while the rules
      page (checked 2026-09-28) says *"Open to individuals or teams (each participant can join
      only one team)"* and states no student requirement. The rules page normally governs, but
      a solo entry is the case the sidebar would exclude, so email the hackathon manager and get
      the answer in writing before the deadline rather than after it
- [ ] Submitted on Devpost before Oct 4, 2026, 9:00 pm PDT

## Demo script (for the video)

Target **3 min 30 s**; the rules allow 3–5. Built around what judges say decides hackathons:
lead with the problem, show one thing working within about 90 seconds, put the judge in the
user's shoes, be direct about what works and what does not, and have the video finished before
the deadline rather than on it. Record from the live link, at phone width, with the demo data
seeded. Rehearse it out loud once and time it.

**0:00–0:20 · The problem.** *"The animals in a stream are the best evidence of its health, and
the hardest thing for a volunteer to name. This is a flat-headed mayfly. To a beginner it looks
like a stonefly, and that one name can change a stream's reading. OneAquaHealth's own track brief
says it: citizen observations are inconsistent and error-prone. If an AI names the animals
instead, nobody learns anything, and nobody can tell when it is wrong."*

**0:20–1:30 · The moment.** Open `/try`. The photos are already loaded. Search "two tails",
pick a stonefly, answer the smell and access questions, submit. The card: *"You marked some
kind of stonefly. The model thinks this may be Mayfly (flat-headed)."* Say: *"The AI looked at
the same photo without seeing my answer. It doesn't overrule me; it asks, and tells me what to
look at: count the tails."* Count them on the photo: three. Take the mayfly. *"It never saw
my answer, so when it agrees with me, that means something. And when I take its answer, the
app records that I adopted it, not that we agreed."*

**1:30–2:10 · The reading and its reasons.** The band, then the sentence about people. Open one
finding: its evidence and its action, and the rain forecast line if the weather has one. Point
at "provisional": one animal cannot prove a stream healthy or dead, and the app says so. Then
the confirmation rule in one sentence: an alert waits for a person to confirm what it rests on.

**2:10–2:50 · In OneAquaHealth's own terms.** The result names research site C3. Open *Export
for the OneAquaHealth app* (the app's own answer codes, and what did not translate and why),
then the FHIR Bundle: *"It conforms to the project's own FHIR IG, and the HL7 validator reports
no errors and no warnings. Only what a person confirmed is marked final."* Open the report: the
thing a citizen actually sends the water authority.

**2:50–3:20 · Looking forward.** `/dashboard`: the declining Coimbra site and its chart, then
*The next 48 hours*: the same rules re-run with the forecast. Heavy rain at a site where sewage
was seen means an overflow is likely.

**3:20–3:30 · Honest close.** *"What works: all of this, offline, with or without an AI, in 255
tests. What we have not claimed yet: that the second opinion catches real mistakes on real
trays. The harness to measure it is built, and running it is the next step. That's AquaPlot:
you name the animals, an AI checks you without seeing your answer, and the rules make the
call."*

If a judge asks about something not built, it was scoped out on purpose: a national index per
country (one score column each), mapping to the project's expert macroinvertebrate codes (the
codes are undocumented), and sending the app submission (it needs an app account).
