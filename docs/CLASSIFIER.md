# Classifier — how a photo becomes "Invasive, 72 %"

> **Inherited feature.** This is SpeciesGuard's single-organism classifier, kept working in
> AquaPlot and served at `/classify`. AquaPlot's own product is the guided stream check at `/`,
> specified in [ASSESSMENT.md](ASSESSMENT.md). What changed here: the region is no longer
> Orange County but whatever administrative place the coordinates resolve to
> ([places.py](../src/aquaplot/places.py)), and the seed list now carries the EU Union list
> alongside the Californian entries, with each result naming the jurisdiction that lists a
> species. Read "Orange County" below as "the place the observation was made".

Implements PRD §6 (the four-stage pipeline), FR-8 (always answer, with a
certainty) and §9 (the certainty carries the honesty). This page is the
reader's guide; the rule itself lives in `src/aquaplot/pipeline.py`.

## Stages

| Stage | PRD | Where | State |
|---|---|---|---|
| 1 Input normalisation, regime, region | §6.1, FR-6 | `inputs.py`, `places.py`, regime from the model | Done; region checked against the county polygon |
| 2 Detection and cropping | §6.2 | `pipeline.py`, box from the model | Done as detect → crop → re-identify with the same model (below). A dedicated small-object detector is M4. |
| 3 Species identification | §6.3 | `identify.py` | Done, pluggable |
| 4 Status resolution | §6.4 | `status.py` | Done |
| Combine into label + certainty | FR-8, §9 | `pipeline.py` | Done |

## Stage 3: which model answers

The server picks one backend at startup and names it in every result
(`evidence.identifier`) and in `/api/health`.

| Backend | Chosen when | Notes |
|---|---|---|
| `claude` | `ANTHROPIC_API_KEY` is set | Claude (`claude-opus-5` by default, override with `CLAUDE_MODEL`) with structured output, so the reply is always a validated `Identification`; medium effort, 8192-token cap because the model thinks before answering. Best accuracy. The intended backend for the deployed live link. Two calls per photo when Stage 2 crops. |
| `ollama` | A running Ollama has a vision model pulled (`qwen2.5vl`, `llava`, `gemma3`, …), or `OLLAMA_MODEL` names one | Local, keyless, offline. Same prompt and same JSON schema as Claude, enforced by Ollama's `format`. Photos are sent at 512 px and output is capped, because vision tokens dominate the cost. Measured on an 8 GB Apple laptop with `qwen2.5vl:3b`: 90–150 s per photo, correct on California sagebrush, wrong species but right family on pampas grass. Treat it as a demo backend; see "Local model limits" below. |
| `none` | Neither | The M0 placeholder: neutral label, 0 % certainty, and the evidence trail says no model is configured. |

Both model backends receive the same system prompt (a field-biologist brief
scoped to Orange County), the photo downscaled (1024 px for Claude, 512 px for Ollama), the observer's
description if any, and the resolved location. They return up to five
candidates as scientific names with probabilities, plus the framing regime and
one sentence of reasoning. Names are never trusted as-is: Stage 4 resolves them
against iNaturalist's taxonomy, so a misspelling or synonym either lands on a
real taxon or is reported as unknown.

## Stage 2: the model as its own detector

Every photo pass returns `subject_box`, the tightest box around the main
organism as fractions of the oriented frame. If the box covers under a quarter
of the frame and the crop is at least 64 px on a side, the pipeline crops to
the box (15 % margin), sends the crop through the same identifier, and keeps
the pass with the higher top confidence. The whole-frame pass still decides
the framing regime and the box; the crop only decides the species. The result
records both (`evidence.subject_box`, `evidence.identified_from_crop`) and the
page draws the box over the preview.

A malformed or frame-filling box, a failed second call, or a crop that is less
confident than the whole frame all fall back to the whole-frame answer, so the
stage can only help.

## Stage 4: status, from two sources

1. **Seed list** (`data/status_seed.json`, Cal-IPC, CDFW, USGS NAS, UC IPM, CDFA,
   OC Vector Control; 76 entries). A hit is the only route to the *Invasive* label,
   because invasiveness is a policy determination, not a biological one. Each entry
   holds iNaturalist's accepted name plus synonyms, and the match is tried on the
   model's spelling and on the name iNaturalist resolved it to.
2. **iNaturalist establishment means for the taxon in Orange County.** iNaturalist
   answers through place ancestry (county, then California, then the US) and says
   which place answered. *native* or *endemic* gives *Native*; *introduced* gives
   *Naturalized/Non-native*.

If neither source knows, or iNaturalist is unreachable, the label is
*Naturalized/Non-native* at low status confidence and the evidence trail says why.
The seed list works offline, so a listed invasive is still called *Invasive*
during an outage.

## The certainty rule

```
certainty % = 100 × species confidence × status confidence × region factor × input factor × regime factor
```

| Factor | Values | Penalty text shown to the user |
|---|---|---|
| species confidence | model's probability for the top candidate | "species model was unsure" below 0.6; "only confident to genus level" |
| status confidence | seed list 0.95 · iNat at Orange County 0.90 · at California 0.80 · coarser 0.65 · unknown 0.35 | "status comes from California, not Orange County specifically" etc. |
| region factor | in Orange County 1.0 · outside 0.8 · unknown 0.85 | "outside Orange County…" / "no geolocation…" |
| input factor | photo 1.0 · text only 0.7 | "text-only input is inherently lower confidence" |
| regime factor | close/macro/microscopic 1.0 · mid-distance 0.92 · far 0.85 | "subject photographed at far range; distant shots are less reliable in v1" |

Worked example: pampas grass photographed in Irvine, model 0.9 → seed-listed
*Invasive* at 0.95 → 100 × 0.9 × 0.95 × 1.0 × 1.0 = **85.5 %**, no penalties.
Same species described in words from San Diego, model 0.5 → 100 × 0.5 × 0.95 ×
0.8 × 0.7 = **26.6 %**, three penalties listed. The same plant photographed across
a canyon (far), model 0.9 after the crop → 100 × 0.9 × 0.95 × 0.85 = **72.7 %**,
one penalty.

These factors are priors chosen to order outcomes sensibly, not measured
calibration. PRD §8 and §9 make calibration the highest-stakes M7 task under the
always-answer design; `pipeline_version` changes whenever the rule changes so
results stay comparable.

## Local model limits

`qwen2.5vl:3b` needs about 3.7 GB resident. On an 8 GB machine anything else that
is memory-hungry (a headless browser, a second model) pushes it into swap and
generation drops from ~1 token/s to ~0.1, which is why the Ollama timeout is
generous (`OLLAMA_TIMEOUT`, default 300 s) and why the UI warns that a local
model can take a while. A 16 GB machine or a 7B model changes both speed and
accuracy. `AQUAPLOT_IDENTIFIER=none` turns identification off explicitly;
`AQUAPLOT_IDENTIFIER=claude|ollama` forces a backend.

## Failure behaviour (FR-8, §5.2 degrade gracefully)

- Model errors or times out → placeholder label, 0 %, penalty names the error
  (the timeout message says the model may be too large for the machine).
- Model returns no candidates → placeholder, with the model's reason.
- iNaturalist down → species still identified; seed-listed species still *Invasive*;
  otherwise neutral label at 35 % status confidence with the outage in the penalties.
- Too many requests from one address → HTTP 429 with `Retry-After`
  (`AQUAPLOT_CLASSIFY_LIMIT` per 10 minutes, default 20, 0 disables).
- Location missing → status evaluated for Orange County by assumption, with a penalty.

## Trying it

```sh
# local model
ollama pull qwen2.5vl:3b
.venv/bin/uvicorn aquaplot.app:app --reload        # health shows "identifier": "ollama"

# Claude
ANTHROPIC_API_KEY=sk-ant-... .venv/bin/uvicorn aquaplot.app:app --reload
```

The result page links straight to the area viewer filtered to the identified
taxon around the photo's location, so "is this pampas grass?" turns into
"how much pampas grass is around here?" in one tap.
