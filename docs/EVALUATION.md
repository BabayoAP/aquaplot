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

## Running it

A starter set from iNaturalist: research-grade, openly licensed, European, and for insects only
photos annotated as larva or nymph.

```sh
.venv/bin/python scripts/fetch_inat_eval.py --per-family 3 --out eval/inat
ANTHROPIC_API_KEY=... .venv/bin/python scripts/evaluate_observer.py eval/inat/labels.csv --out eval/inat-results
```

Around 150 photos at three per family. Each is one model call.

Your own tray photos are the better test. Put them in a folder with a `labels.csv`:

```csv
photo,families,note
tray-01.jpg,Heptageniidae;Gammaridae;Chironomidae,Ribeira de Coselhas, riffle below the bridge
```

## Reading the result honestly

- **iNaturalist photos flatter the model.** They are one animal, chosen and framed by someone
  who wanted it identified. A tray of mixed animals in gravel is harder. Report the two sets
  separately and never quote the iNaturalist figure as field performance.
- **The confusion list is the simulation.** "Caught" means caught for the mistakes listed in
  `CONFUSIONS` and same-order swaps. Real volunteer errors will include others.
- **Small numbers are small.** Thirty photos give a direction, not a rate. Quote counts
  ("caught 41 of 60 simulated mistakes") rather than bare percentages.

## Results

Not yet run. Record each run here with the date, the model, the photo set and the four headline
numbers: right to family, caught, caught with the right answer, false-alarm photos.
