# How a photo becomes a band

This document is the specification for `assess.py` and everything it composes. It exists so
a reviewer can disagree with a specific decision rather than with the system in general.

## The question

Urban streams fail European water quality targets more often than any other water body type,
and the reason is usually invisible in a spot sample: a misconnected sewer that discharges on
Tuesday, a road drain that only matters when it rains, a channel concreted in 1968. Regulators
cannot sample often enough to catch any of it. The people who walk past every day can — if
someone asks them the right questions in words they already use, and turns their answers into
something a water department will act on.

## Stage 1 — Input

`inputs.py` decodes JPEG, PNG or HEIC, applies EXIF orientation before anything sees the
pixels, and reads the GPS IFD. Location precedence is EXIF, then the browser's geolocation,
then nothing: EXIF records where the *photo* was taken, the browser records where it was
*uploaded*, and for a stream reading the difference is the whole point. Coordinates are used
and echoed once, never stored beyond the assessment row itself.

## Stage 2 — Place

`places.py` asks iNaturalist for the standard administrative places containing the point and
takes the most specific — municipality over province over country. Everything that follows
about native, introduced or invasive status is asked of *that* place, because none of those
words mean anything without one. A failed lookup costs a certainty factor of 0.9 and a
sentence; it never fails the assessment, because the biological index and the habitat
pressures do not depend on knowing which municipality you are standing in.

## Stage 3 — Observation

`observe.py` sends each photo to a vision-language model with a prompt whose option lists are
**generated** from `data/habitat_indicators.json`, so the prompt and the server-side validator
cannot drift apart. The model returns:

- `photo_kind` — a stream scene, a specimen tray, a single organism, or not a stream at all.
- `habitat` — answers to the indicators visible in *this* photo, each with a confidence.
- `taxa` — invertebrates visible, to family where the diagnostic features are visible and to
  order where they are not.
- `cannot_tell` — indicators it was asked about and genuinely could not judge.

The model is told, in the prompt, that "I cannot tell from this photo" is a correct answer.
Fabricated certainty is the failure mode that would matter most here, and the whole rest of
the design assumes it has been discouraged.

Indicators marked `photo_visible: false` are never asked of the model. There is exactly one
today — smell — and it is the indicator that separates a stream cloudy from yesterday's rain
from a sewage discharge. It is the concrete reason a person stays in the loop.

## Stage 4 — The biological index

`bioindex.py` scores the invertebrates with **BMWP/ASPT**, the family-level index used across
Europe. Each family carries a score from 1 (survives almost anything) to 10 (clean, cold,
well-oxygenated water only). BMWP is their sum; **ASPT** is the mean, and the mean is what the
band is read from because it barely moves with how hard someone looked.

| ASPT | Band |
|---|---|
| ≥ 6.5 | High |
| 5.6 – 6.5 | Good |
| 4.6 – 5.6 | Moderate |
| 3.6 – 4.6 | Poor |
| < 3.6 | Bad |

Three rules keep it honest:

- **Effort caps the claim.** Fewer than 8 scoring families cannot support *High*, fewer than 5
  cannot support *Good*, fewer than 2 cannot support *Moderate*. The cap lowers the band and
  names itself in the penalties.
- **A thin sample is provisional in both directions.** Under three families, the reading is
  marked provisional whichever way it points, because two tolerant families is a reason to
  look again rather than proof that a stream is dead.
- **Coarse identifications are scored, then flagged.** An honest "that's a stonefly" is scored
  from the order's median and marked `coarse`; a family-level answer for the same order
  replaces it.

The band names are the Water Framework Directive's five classes because that is the vocabulary
European city authorities already act on. AquaPlot reports a **screening** band and says so in
every response.

## Stage 5 — Visual pressures

`habitat.py` scores twelve indicators from 0 (nothing wrong) to 3 (severe), weighted, into a
0–100 pressure index with every contribution itemised. A thirteenth — who uses the water — is
flagged `exposure` and kept *out* of the pressure score: whether children paddle here does not
make the water dirtier, but it decides whether dirty water is a public-health problem, so it
goes to the rule engine instead.

Where the model and the citizen answer the same question, **the citizen wins**. That single
line is what makes the review step in the workflow real rather than decorative.

## Stage 6 — Invasive check

`status.py` matches every reported name against `data/status_seed.json` — the aquatic and
riparian species of Union concern under EU Regulation 1143/2014, plus inherited Californian
entries — on both iNaturalist's accepted name and the older synonyms lists still use. A hit is
the only way to earn the *Invasive* label, because invasive is a determination by a named
authority, not a property of an organism. When the listing jurisdiction does not cover where
the observer is standing, the result says so instead of asserting it.

## Stage 7 — The rules

`onehealth.py`. See [ONE-HEALTH.md](ONE-HEALTH.md) for every rule.

## The certainty number

    certainty = biological confidence
              × habitat coverage      (0.6 + 0.4 × answered/12)
              × place factor          (1.0 resolved · 0.9 unresolved · 0.85 no coordinates)
              × photo factor          (1.0 with a photo · 0.95 without)

Biological confidence itself falls with shaky identifications, thin samples and order-level
answers. Every factor below 1.0 appends a sentence to `penalties`, so the number can always be
taken apart. These are **priors, not measured calibration**; `ASSESSMENT_VERSION` changes
whenever the rule does.

## The confirmation queue

`needs_confirmation` is ordered by how much confirming each item would change the output:

1. Observations holding a health finding below alert level. `RULE_EVIDENCE` maps each rule to
   the habitat answers it rests on, so the queue asks for the one that actually matters.
2. The questions only a person standing there can answer.
3. Low-confidence or order-only identifications.

`POST /api/assess/{id}/review` folds the answers back in and recomputes — **without calling the
model again**. Re-running it would let the model quietly overwrite the correction a person just
made, which would make the review theatre. The new assessment carries `supersedes`, and the row
it replaces leaves every count, trend and feed while staying fetchable by id as the record of
what the model said before a person corrected it.

## Failure behaviour

| What fails | What happens |
|---|---|
| The vision model errors or refuses | The photo contributes nothing; the penalty names it; everything else runs. |
| A photo is not of a stream | It is dropped, with the model's reason quoted. |
| iNaturalist is down | The seed list still answers for invasives; the place is unresolved; the certainty falls; nothing raises. |
| No model is configured | The citizen fills the form; band, pressures, findings, trends and FHIR are unchanged. |
| No coordinates | The reading is stored but cannot join a series, and the penalty says exactly that. |
