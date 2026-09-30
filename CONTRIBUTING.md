# Contributing

The fastest way to improve AquaPlot is usually not to write code. In order of
value:

1. **Correct a One Health rule.** They are in one readable file and each one is
   listed in [docs/ONE-HEALTH.md](docs/ONE-HEALTH.md) with its trigger, evidence
   and action. If you are a public-health officer, a freshwater ecologist or a
   vector biologist and one of them is wrong, saying so is worth more than any
   feature.
2. **Correct the bioindicator scores or the identification hints.** Both score
   columns were checked against published tables, but family sensitivity genuinely
   varies by ecoregion, and the plain-language hints are written by someone who is
   not a local expert.
3. **Add a confusion to the second opinion.** `CONFUSIONS` in `secondopinion.py` lists
   pairs of groups volunteers mix up, with the feature that separates them in a white
   tray. If you run volunteer training days you know better ones.
4. **Check the invasive seed list** against the authority it cites.
5. Then code.

## Setup

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest              # must pass with no network and no model
.venv/bin/uvicorn aquaplot.app:app --reload
.venv/bin/python scripts/seed_demo.py   # demo data, so the dashboard is not empty
```

## Rules the codebase depends on

Breaking any of these changes what the system claims about somebody's drinking
water.

- **The model observes; the rules decide.** `observe.py` may return only
  structured observations. Anything that concludes something belongs in
  `bioindex.py` or `onehealth.py`, where it is readable and testable. Do not move
  judgement into the prompt.
- **An alert waits for a human.** `onehealth.evaluate` holds an unconfirmed alert
  at `concern` and says so. A new rule that can reach `alert` must list the
  habitat answers it rests on in `assess.RULE_EVIDENCE`, or the confirmation queue
  cannot tell the user what to confirm.
- **A review never calls the model again** (`assess.reassess`). A second pass
  could overwrite the correction a person just made.
- **Every certainty factor below 1.0 leaves a sentence.** Otherwise nobody can see
  what lowered the number. Bump `ASSESSMENT_VERSION` when the rule changes.
- **Tests never touch the network or a model.** Every outbound call goes through
  an injectable callable for exactly this reason.
- **Never blind search-and-replace the word "riffle".** "Riffle beetle" is the
  Elmidae family and a riffle is the stretch a sample is taken from. Both are in
  the catalogue *and* the identification alias table.

## Adding things

### A bioindicator family

`src/aquaplot/data/bioindicators.json`. Needs `family`, `common_name`, `group`,
`bmwp` (1–10), `ept`, `plain_name`, `look_for`, `means`, and `vector: true` if it
carries a human or animal health signal. Write `look_for` for someone holding a
tray who has never heard of the order: shapes, counts of tails, what the case is
made of. If a vision model or a citizen is likely to type a genus or a vernacular
name, add it to `ALIASES` in `bioindex.py` in lower case.

Then give it a reference photo: `.venv/bin/python scripts/fetch_guide_photos.py --families <Family>`.
Look at the result in `static/guide/`. It must show the stage found in a tray (a nymph or larva for
mayflies, stoneflies, caddisflies, dragonflies and flies), and the whole animal. If it doesn't, run it
again with `--skip <observation id>` to take the next photo. If you change the photo set, bump
`PHOTOS` in `static/sw.js` so phones fetch the new ones.

### A habitat indicator

`src/aquaplot/data/habitat_indicators.json`, **and nowhere else**. That one file
generates the model's prompt, the server's validator, the questions on the page
and the pressure scoring. Set `photo_visible: false` if no camera could judge it,
and `exposure: true` if it describes who is exposed rather than how degraded the
water is. Exposure is kept out of the pressure score and handed to the rules.

### A One Health rule

A function in `onehealth.py` decorated with `@rule`, taking a `Context` and
returning a `Finding` or `None`. It must carry a stable id, the evidence in the
words the observer used, and an action a specific person can take. Add it to
[docs/ONE-HEALTH.md](docs/ONE-HEALTH.md). A test fails if a rule is undocumented.

### A different biotic index

BMWP and the Iberian IBMWP are both in. Another national index (Italy's IBE, a
Scandinavian ASPT variant) is:

1. a score column in `data/bioindicators.json`, `null` where the index does not score
   a family, with the published table it came from named in the file's `note`;
2. a `BioticIndex` in `bioindex.py` and an entry in `INDICES`, with its own
   `total_classes` if it publishes classes on the total;
3. the countries it applies to in `index_for`;
4. a test that pins a few scores where it differs from BMWP, as `tests/test_indices.py` does.

The band is always read from the mean, because a single tray never approaches the
sampling effort an index's own total classes assume.

### A data source

`area.py` and `inat.py` take an injectable `fetch`. A GBIF, Cal-IPC or national
agency source is another adapter.

## Tests

Name a test after the behaviour it protects, not the function it calls:
`test_an_unconfirmed_bloom_is_held_below_alert_until_a_person_confirms_it`, not
`test_evaluate_3`. If you fix a bug, the test that fails without the fix is the
deliverable; the fix is the easy part.

## Honesty

The project's credibility rests on refusing to overclaim. If you add a number, add
the sentence that says what would make it wrong. If you add a claim about health,
add the authority it defers to. A screening tool that oversells itself costs the
next volunteer their credibility too.
