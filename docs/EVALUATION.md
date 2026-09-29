# Does the second opinion work?

AquaPlot does not claim that a vision model can identify stream invertebrates from a phone
photo. It claims something narrower that can be checked: **when a volunteer records the wrong
animal, the model's blind second opinion catches it often enough to be worth asking, without
burying correct answers in questions.** This document is how that is measured.

## The method

`src/aquaplot/evaluation.py`, run by `scripts/evaluate_observer.py`, takes a folder of photos
whose contents are known and does three things.

1. **What the model sees.** Each photo goes to the model once, exactly as in the app. Every
   labelled animal is then counted as *right to family*, *right to order only*, *wrong* or
   *missed*. Order-only is kept apart from wrong on purpose: the prompt tells the model that
   "some kind of mayfly" is the correct answer when the family is not visible, and a model that
   does that is behaving well.
2. **Mistakes caught.** For every labelled animal, each family it is commonly confused with is
   substituted in turn: another family in the same order, or a family from an order in the
   confusion table in `secondopinion.py` (mayfly and stonefly, shrimp and hoglouse, bloodworm and
   sludge worm, and so on). The second opinion is run against the model's real output for that
   photo. A mistake is **caught** when the review would ask about it, and **caught with the right
   answer** when the question offers the true animal.
3. **False alarms.** The second opinion is run on the *correct* list. Every question it raises
   there is one a volunteer who was right would have to answer.

Only step 1 costs anything. The model's raw answers are saved to `observations.json`, and
steps 2 and 3 can be rerun from that file for free with `--rescore` whenever a rule changes.

## One design choice the numbers will show

A mistake *towards a tolerant family* (recording a bloodworm as a sludge worm, say) is only
caught if the model sees the real animal. The review deliberately does not question a tolerant
family the model merely failed to find: that cannot raise the band, and asking about it would
be noise. A sensitive family the model could not find *is* questioned, because sensitive
families are what lift a stream's reading, and they are the identifications worth a second look.

## Running it with your own key

Every figure below was taken on a set of photographs this repository pins, so you can rebuild
that exact set and put your own model against the same pictures. Three commands:

```sh
cp .env.example .env                                    # put ANTHROPIC_API_KEY in it; .env is git-ignored
.venv/bin/python scripts/fetch_inat_eval.py --from-labels eval/inat/labels-subset.csv
.venv/bin/python scripts/evaluate_observer.py eval/inat/labels-subset.csv \
    --observer claude --out eval/claude-results
```

That is **32 photos, one model call each**, one per family across 32 families. `labels.csv` is
the full set, 101 photos, and costs three times as much. The run prints how many calls it is
about to spend and waits for a keypress; `--yes` skips that.

Four things the harness does so that a number you get back means something:

- **The set is pinned, not searched for.** `--from-labels` re-fetches the exact observations the
  committed `labels.csv` names, by iNaturalist observation id, so your photographs are
  byte-identical to the ones the recorded figures came from. Searching again is *not*
  reproducible: `fetch_inat_eval.py` orders by votes, and both the votes and the pool of
  research-grade observations move under it. Photos are fetched rather than committed because
  they are 11 MB of other people's CC-BY-NC work; the labels that identify them are committed.
- **It will not quietly measure something else.** `--observer claude` refuses to start unless
  Claude is the backend that will answer. Without it, a key you forgot to export means the run
  falls through to a local Ollama model, and a table headed with the wrong model is worse than
  no table at all.
- **It stops when the backend does.** Three failures in a row (a rejected key, an exhausted
  balance, a dropped connection) end the run and name the cause, because a hundred error rows
  score identically to a model that saw nothing.
- **It never pays twice.** Answers are saved as they arrive, so an interrupted run resumes;
  failures are *not* resumed, so a photo that errored is sent again once the cause is fixed.
  Scoring is a pure function of `observations.json`, so `--rescore` re-runs the whole table for
  free after a rule changes.

Your own tray photos are the better test. Put them in a folder with a `labels.csv`:

```csv
photo,families,note
tray-01.jpg,Heptageniidae;Gammaridae;Chironomidae,Ribeira de Coselhas, riffle below the bridge
```

A set like that cannot be rebuilt from iNaturalist and does not pretend to be: `--from-labels`
skips any row it cannot trace to an observation rather than guessing at one.

## Reading the result honestly

- **iNaturalist photos flatter the model.** They are one animal, chosen and framed by someone
  who wanted it identified. A tray of mixed animals in gravel is harder. Report the two sets
  separately and never quote the iNaturalist figure as field performance.
- **The confusion list is the simulation.** "Caught" means caught for the mistakes listed in
  `CONFUSIONS` and same-order swaps. Real volunteer errors will include others.
- **Small numbers are small.** Thirty photos give a direction, not a rate. Quote counts
  ("caught 41 of 60 simulated mistakes") rather than bare percentages.

## The other half: how good does the observer have to be?

Everything above needs a model and labelled photographs. The question underneath it does not:
**given an observer of a stated quality, how much of a volunteer's mistake does the review
catch, and how much noise does a volunteer who was right have to wade through?** That is a
property of `secondopinion.py`, so `scripts/evaluate_rules.py` measures it by handing
`score_outcomes` a *synthetic* observer with two dials (how often it misses an animal that is
there, and how often it answers "some kind of mayfly" instead of naming the family) and
sweeping them.

```sh
.venv/bin/python scripts/evaluate_rules.py --repeats 200
```

**This measures the rules, not any model.** It says nothing about whether a vision model can
identify a mayfly nymph in a phone photograph; the observer is a simulation with a dial on it
and the trays are drawn from the catalogue rather than photographed in a stream. It is
deterministic from its seed, so the table below reruns in a second and a regression in the
review logic shows up as a falling catch rate.

## Results

### Rule layer, synthetic observer (2026-09-28, rerun)

6 trays spanning a clean upland riffle to a drain, 200 runs per row, seed 1000, 198 simulated
volunteer mistakes per run. Reproduce with
`.venv/bin/python scripts/evaluate_rules.py --repeats 200 --markdown`.

| Animals the observer misses | Answered to order only | Mistakes caught | ...with the right animal offered | False-alarm questions per tray |
|---|---|---|---|---|
| 0% | 0% | 100% | 100% | 0.00 |
| 0% | 30% | 87% | 70% | 0.00 |
| 20% | 0% | 83% | 71% | 0.16 |
| 20% | 30% | 73% | 50% | 0.16 |
| 40% | 0% | 68% | 48% | 0.32 |
| 40% | 30% | 61% | 33% | 0.32 |
| 60% | 0% | 51% | 28% | 0.44 |
| 60% | 30% | 47% | 19% | 0.44 |

Reading it:

- **An observer does not have to be good to be worth asking.** One that misses two animals in
  every five still catches 68% of simulated mistakes, at a cost of one unnecessary question
  roughly every three trays. This is the case for a model that only ever raises questions. It
  is the row to quote, because a model missing 40% of a mixed tray is a pessimistic estimate of
  what these models do.
- **A perfect observer never interrupts a volunteer who was right** (0.00 false alarms at 0%
  miss). Every false alarm in the table comes from the model failing to find an animal the
  volunteer correctly recorded, which is by design: a *sensitive* family the model could not
  find is worth a second look, because sensitive families are what lift a stream's reading.
- **Answering only to order costs the suggestion, not the catch.** At 30% order-only the catch
  rate falls 13 points but the share where the right animal is offered falls 30. The question
  still gets asked; it just says "some kind of mayfly" rather than naming the family. That is
  the honest thing to show, and it's why order-level answers are counted apart from wrong ones.
- **The two bottom rows moved when blanket questioning stopped counting as a catch.** They read
  56%/0.53 and 52%/0.53 before `secondopinion.compare` learned to treat an observer that named
  *nothing* as no second opinion rather than as one that disagreed with everything. An observer
  missing 60% of a small tray sometimes sees none of it, and questioning every family on the
  strength of that caught mistakes the way a stopped clock tells the time. Fewer catches, a
  fifth fewer false alarms, and what remains is signal.

### Model layer, local backend (2026-09-28)

**Observer:** Ollama / `qwen2.5vl:3b` (the keyless path; 3.8 B parameters, Q4_K_M, on a laptop).
**Photos:** 32 from iNaturalist — research-grade, openly licensed, European, insects restricted
to larva or nymph — one per family, spread across the catalogue's whole score range (1 to 10)
and 14 taxonomic groups. The exact photographs are pinned by
[`eval/inat/labels-subset.csv`](../eval/inat/labels-subset.csv), and the model's raw answers and
this report are committed beside them in [`eval/inat-results/`](../eval/inat-results/), so the
table below can be checked rather than taken on trust. Reproduce it with:

```sh
.venv/bin/python scripts/fetch_inat_eval.py --from-labels eval/inat/labels-subset.csv
AQUAPLOT_OBSERVER=ollama .venv/bin/python scripts/evaluate_observer.py \
    eval/inat/labels-subset.csv --observer ollama --out eval/inat-results
```

or rescore the recorded answers without a model at all, with `--rescore`.

| | Count | Share |
|---|---|---|
| Right to family | 0 | 0% |
| Right to order only | 0 | 0% |
| Wrong | 0 | 0% |
| Missed | 32 | 100% |
| Mistakes caught | 0 of 249 | 0% |
| Photos where a correct list drew a question | 0 of 32 | 0% |

**It named no animal, on any photo.** Not wrongly — at all. This is not the harness failing to
reach it: the model returned valid structured output on all 32, raised no error, and got
`photo_kind` right every time (`single_organism`, 32 of 32). It read the photograph and
declined the only question that mattered. These are single-animal photos, lit and framed by
someone who wanted them identified — the set that *flatters* a model — and it still scored
zero, so there is nothing here to attribute to tray clutter.

Two things follow.

- **The keyless deployment has no second opinion**, and the app now says so instead of
  implying otherwise. Finding this is what prompted the rule above: an observer that names
  nothing is reported as no second opinion rather than one that disagreed with everything.
  Before that, this backend turned every sensitive family a volunteer got right into an "are
  you sure?" — 0 of 32 false-alarm photos above would have been 32 of 32.
- **Claude is still unmeasured.** This measures the backend that needs no key, because that is
  the one we could run. Do not read a row of zeros for a 3.8 B local model as a result about
  the model the deployment uses, in either direction. Running the same 32 photos with
  `ANTHROPIC_API_KEY` set is one command and is the next thing to do.

Nothing in the submission claims the second opinion catches real mistakes on real trays. That
claim still needs a run against Claude, and better, against photographs of actual kick-sample
trays rather than iNaturalist portraits.
