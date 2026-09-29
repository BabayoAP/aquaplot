# How a photo becomes a band

This document is the specification for `assess.py` and everything it composes. It exists so
a reviewer can disagree with a specific decision rather than with the system in general.

## The question

Urban streams fail European water quality targets more often than any other water body type,
and the reason is usually invisible in a spot sample: a misconnected sewer that discharges on
Tuesday, a road drain that only matters when it rains, a channel concreted in 1968. Regulators
cannot sample often enough to catch any of it. The people who walk past every day can, if
someone asks them the right questions in words they already use and turns their answers into
something a water department will act on.

## Stage 1: Input

`inputs.py` decodes JPEG, PNG or HEIC, applies EXIF orientation before anything sees the
pixels, and reads the GPS IFD. Location precedence is EXIF, then the browser's geolocation,
then nothing: EXIF records where the *photo* was taken, the browser records where it was
*uploaded*, and for a stream reading it's where the photo was taken that matters. Coordinates are used
and echoed once, never stored beyond the assessment row itself.

## Stage 2: Place

`places.py` asks iNaturalist for the standard administrative places containing the point and
takes the most specific one (municipality over province over country). Everything that follows
about native, introduced or invasive status is asked of *that* place, because none of those
words mean anything without one. A failed lookup costs a certainty factor of 0.9 and a
sentence; it never fails the assessment, because the biological index and the habitat
pressures do not depend on knowing which municipality you are standing in.

## Stage 3: Observation

`observe.py` sends each photo to a vision-language model with a prompt whose option lists are
**generated** from `data/habitat_indicators.json`, so the prompt and the server-side validator
cannot drift apart. The model returns:

- `photo_kind`: a stream scene, a specimen tray, a single organism, or not a stream at all.
- `habitat`: answers to the indicators visible in *this* photo, each with a confidence.
- `taxa`: invertebrates visible, to family where the diagnostic features are visible and to
  order where they are not.
- `cannot_tell`: indicators it was asked about and genuinely could not judge.

The model is told, in the prompt, that "I cannot tell from this photo" is a correct answer.
Fabricated certainty is the failure mode that would matter most here, and the whole rest of
the design assumes it has been discouraged.

Indicators marked `photo_visible: false` are never asked of the model. Today there is exactly
one, smell, and it is what tells a stream that is cloudy from yesterday's rain apart from a
sewage discharge. It is the practical reason a person stays in the loop.

## Stage 3b: Who identifies the animals

Identifying a 5 mm larva to family from a phone photo is hard for a trained person with a hand
lens. It is the least defensible thing a vision model could be asked to do here, so AquaPlot
does not ask it to decide.

**The citizen identifies.** Step 3 of the check is a picker built from the catalogue, grouped by
shape ("Mayflies", "Snails and limpets"), searchable by what a person can see ("three tails",
"case", "red worm"), with a "some kind of…" option per group for an honest group-level answer.
When the citizen supplies a list, **that list is what gets scored.**

**The model gives a second opinion, blind.** The same tray photo goes to the model without the
citizen's answers, because the model agreeing only counts as evidence if it could not have
copied them. `secondopinion.py`
compares the two lists and produces *questions*, never changes:

| The model… | The card asks | Answers |
|---|---|---|
| saw a family commonly confused with one you marked | "You marked a stonefly. The model thinks this may be a mayfly. Which is it?" with the feature that tells them apart (count the tails) | Mine is right · It's the model's |
| saw something you did not mark | "The model thinks there may also be a net-spinning caddis. Did you see one?" | Yes, add it · No, it's not there |
| could not find a *sensitive* family you marked | "The model could not find the stonefly you marked. Are you sure?" | Yes, I'm sure · No, remove it |

A tolerant family the model merely failed to find is not questioned: it cannot lift the band,
and asking would be noise. Every question carries the band the stream would get if the model
were right, and the ones that would change it come first. A suggestion that is a listed invasive
goes to the top, but it only enters the invasive check if the person says it was there.

Keeping your own answer dismisses the question; taking the model's swaps the animal. Either way
the model is not called again. An agreement that exists only because the person took the
model's answer is reported as that, never as independent agreement. Unsettled disagreements
that would change the band cost certainty (0.9 each, floor 0.7) and say so.

If the citizen skips identification, the model's list becomes a proposal, scored unconfirmed
and queued for confirmation as before. With no model or no tray photo, there is no second
opinion and the result says why. `docs/EVALUATION.md` describes how the second opinion is
measured.

## Stage 4: The biological index

`bioindex.py` scores the invertebrates against a family-score table. Each family carries a
score from 1 (survives almost anything) to 10 (clean, cold, well-oxygenated water only). The
total is their sum; the mean per scoring family is what the band is read from, because it
barely moves with how hard someone looked.

**Which table depends on where you are**, resolved from the coordinates like everything else:

| Index | Where | Source |
|---|---|---|
| **BMWP / ASPT** | Default | Armitage et al. (1983) |
| **IBMWP / IASPT** | Portugal, Spain, Andorra | Alba-Tercedor et al. (2002); family scores as tabulated in MAGRAMA (2011) |

Both columns in `data/bioindicators.json` were checked against the tables distributed with the
`biomonitoR` R package. They differ on nine families (Ephemerellidae 10→7, Caenidae 7→4, the
water beetles and water bugs 5→3, drain-fly larvae unscored→4). A caller can also name the
index explicitly (`index=bmwp|ibmwp`).

A family an index does not score (the American crayfish and the zebra mussel in both indices;
mosquito, drain-fly and rat-tailed maggot larvae in BMWP) is **recorded, not scored**: it appears in the
result and the report, feeds the One Health rules (mosquito larvae, snail hosts) and the
invasive check, and adds nothing to the index.

IBMWP publishes its own quality classes on the *total* (>100, 61–100, 36–60, 16–35, ≤15). Those
assume a standardised sample across every habitat in the reach, which typically finds several
times more families than one tray. Read from a tray, the total always reads low, so the band is
read from IASPT with the same thresholds as ASPT, and the total's class is shown beside it,
labelled as understating a small sample.

| Mean (ASPT or IASPT) | Band |
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

## Stage 5: Visual pressures

`habitat.py` scores twelve indicators from 0 (nothing wrong) to 3 (severe), weighted, into a
0–100 pressure index with every contribution itemised. A thirteenth, who uses the water, is
flagged `exposure` and kept *out* of the pressure score: whether children paddle here does not
make the water dirtier, but it decides whether dirty water is a public-health problem, so it
goes to the rule engine instead.

Where the model and the citizen answer the same question, **the citizen wins**. That one line
is why the review step in the workflow actually changes the result.

## Stage 6: Invasive check

`status.py` matches every reported name against `data/status_seed.json` (the aquatic and
riparian species of Union concern under EU Regulation 1143/2014, plus inherited Californian
entries) on both iNaturalist's accepted name and the older synonyms lists still use. A hit is
the only way to earn the *Invasive* label, because invasive is a determination by a named
authority, not a property of an organism. When the listing jurisdiction does not cover where
the observer is standing, the result says so instead of asserting it.

## Stage 7: The rules

`onehealth.py`. See [ONE-HEALTH.md](ONE-HEALTH.md) for every rule.

## The certainty number

    certainty = biological confidence
              × habitat coverage      (0.6 + 0.4 × answered/12)
              × place factor          (1.0 resolved · 0.9 unresolved · 0.85 no coordinates)
              × photo factor          (1.0 with a photo · 0.95 without)
              × disagreement factor   (0.9 per unsettled band-changing second-opinion question, floor 0.7)

Biological confidence itself falls with shaky identifications, thin samples and order-level
answers. Every factor below 1.0 appends a sentence to `penalties`, so the number can always be
taken apart. These are **priors, not measured calibration**; `ASSESSMENT_VERSION` changes
whenever the rule does.

## The confirmation queue

`needs_confirmation` is ordered by how much confirming each item would change the output:

1. Second-opinion questions that would change the band, and model suggestions that are listed
   invasives.
2. Observations holding a health finding below alert level. `RULE_EVIDENCE` maps each rule to
   the habitat answers it rests on, so the queue asks for the one that actually matters.
3. The questions only a person standing there can answer, and the remaining second-opinion
   questions.
4. Low-confidence or order-only identifications.

`POST /api/assess/{id}/review` folds the answers back in and recomputes, **without calling the
model again**. Re-running it would let the model quietly overwrite the correction a person just
made, which would make the review pointless. The new assessment carries `supersedes`, and the row
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
