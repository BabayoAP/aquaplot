# Contributing

The fastest way to improve AquaPlot is usually not to write code. In order of
value:

1. **Correct a One Health rule.** They are in one readable file and each one is
   listed in [docs/ONE-HEALTH.md](docs/ONE-HEALTH.md) with its trigger, evidence
   and action. If you are a public-health officer, a freshwater ecologist or a
   vector biologist and one of them is wrong, saying so is worth more than any
   feature.
2. **Correct the bioindicator scores or the identification hints.** BMWP is a
   British index; family sensitivity genuinely varies by ecoregion, and the plain
   -language hints are written by someone who is not a local expert.
3. **Check the invasive seed list** against the authority it cites.
4. Then code.

## Setup

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest              # must pass with no network and no model
.venv/bin/uvicorn aquaplot.app:app --reload
.venv/bin/python scripts/seed_demo.py   # demo data, so the dashboard is not empty
```

## Rules the codebase depends on

These are not style preferences. Breaking one changes what the system claims
about somebody's drinking water.

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
- **Every certainty factor below 1.0 leaves a sentence.** A number nobody can take
  apart is not evidence. Bump `ASSESSMENT_VERSION` when the rule changes.
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
tray who has never heard of the order — shapes, counts of tails, what the case is
made of. If a vision model or a citizen is likely to type a genus or a vernacular
name, add it to `ALIASES` in `bioindex.py` in lower case.

### A habitat indicator

`src/aquaplot/data/habitat_indicators.json`, **and nowhere else**. That one file
generates the model's prompt, the server's validator, the questions on the page
and the pressure scoring. Set `photo_visible: false` if no camera could judge it,
and `exposure: true` if it describes who is exposed rather than how degraded the
water is — exposure is kept out of the pressure score and handed to the rules.

### A One Health rule

A function in `onehealth.py` decorated with `@rule`, taking a `Context` and
returning a `Finding` or `None`. It must carry a stable id, the evidence in the
words the observer used, and an action a specific person can take. Add it to
[docs/ONE-HEALTH.md](docs/ONE-HEALTH.md) — a test fails if a rule is undocumented.

### A different biotic index

`bioindex.py` bands on ASPT through `_band_for_aspt` and `RICHNESS_CAP`. A
country-specific index (IBMWP, IBE, a national ASPT variant) is a second scoring
table and a second band function, not a rewrite. This is the most valuable
technical contribution available: BMWP is British, and AquaPlot applies it across
Europe, which the README says plainly and should stop having to.

### A data source

`area.py` and `inat.py` take an injectable `fetch`. A GBIF, Cal-IPC or national
agency source is another adapter.

## Tests

Name a test after the behaviour it protects, not the function it calls —
`test_an_unconfirmed_bloom_is_held_below_alert_until_a_person_confirms_it`, not
`test_evaluate_3`. If you fix a bug, the test that fails without the fix is the
deliverable; the fix is the easy part.

## Honesty

The project's credibility rests on refusing to overclaim. If you add a number, add
the sentence that says what would make it wrong. If you add a claim about health,
add the authority it defers to. A screening tool that oversells itself costs the
next volunteer their credibility too.
