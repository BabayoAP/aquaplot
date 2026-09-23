# riffle

**SpeciesGuard**: automated invasive vs. native species classification from imagery,
plus a satellite area viewer of biodiversity pressure, scoped to Orange County, CA.
Built for [NextStep Hacks 2026](docs/HACKATHON.md) (theme: Earth Forward).

The product spec is [PRD.md](PRD.md); the area viewer spec is
[docs/AREA-VIEWER.md](docs/AREA-VIEWER.md). Every module docstring cites the
section it implements.

## What works today

**Area viewer** (`/map`). Esri satellite basemap with toggleable layers, live from
public data: introduced, native and threatened species sightings from iNaturalist
(clustered, with photo popups), a dark ring on sightings of Cal-IPC/CDFW-listed
invasives, an introduced-species heatmap, and Hansen/GFW tree-cover loss 2001–2024.
Filter by taxonomic group, year range, and the real Orange County polygon. The side
panel shows the most-seen species in view and sightings per year for each status.

**Classifier** (`/`). Single page that takes a photo (camera or upload, JPEG/PNG/HEIC)
or a text description, resolves a region from EXIF GPS or the browser's location
and checks it against the real county polygon, identifies the species with a
pluggable model (Claude API, or a local Ollama vision model, or none), locates the
subject in the frame and re-identifies from a crop when it is small (the PRD's
detect → crop → classify stage), resolves native/introduced status for Orange
County from iNaturalist plus a 76-entry seed list of Cal-IPC/CDFW/USGS/UC IPM
listed invasives, and returns one of three labels with a certainty percentage and
a full evidence trail: candidates considered, model reasoning, subject box, status
source and place, and every factor that pulled the certainty down. The result
links to the area viewer filtered to that species around the photo's location.
Details: [docs/CLASSIFIER.md](docs/CLASSIFIER.md).

## Run

Python 3.12 or newer. With [uv](https://docs.astral.sh/uv/):

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/uvicorn riffle.app:app --reload
```

Open <http://127.0.0.1:8000> (classifier) or <http://127.0.0.1:8000/map> (area
viewer). To use it from a phone on the same network, run with `--host 0.0.0.0` and
open the machine's LAN address. Browser camera capture and geolocation need HTTPS on
a phone unless the host is `localhost`.

```sh
.venv/bin/python -m pytest        # 68 tests, no network
docker build -t riffle . && docker run -p 8000:8000 riffle
```

Deploy: [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/BabayoAP/riffle)
(uses `render.yaml`; free tier).

## Layout

| Path | Spec | What it does |
|---|---|---|
| `src/riffle/identify.py` | PRD §6.3 | Stage 3: `Identifier` interface with Claude, Ollama and null backends; one prompt, one JSON schema. |
| `src/riffle/status.py` | PRD §6.4 | Stage 4: seed list (accepted names and synonyms), then iNaturalist establishment means for Orange County via place ancestry; degrades if iNaturalist is down. |
| `src/riffle/places.py` | PRD §7, FR-6 | Point-in-polygon test against iNaturalist's Orange County boundary, refining the bounding box. |
| `src/riffle/pipeline.py` | PRD §6, FR-8, §9 | Runs the stages, including Stage 2 crop-and-reidentify, and applies the certainty rule. |
| `src/riffle/inat.py` | | Cached iNaturalist client shared by the map and the status stage. |
| `src/riffle/area.py` | AREA-VIEWER FR-A2..A6 | GeoJSON conversion, listed-invasive tagging, species counts, trend. |
| `src/riffle/data/status_seed.json` | PRD §6.4, AREA-VIEWER §6 | Seed of the status database: hand-picked listed invasives with rating and source. |
| `src/riffle/static/map.html` | AREA-VIEWER FR-A1..A10 | Leaflet page. No build step. |
| `src/riffle/schema.py` | PRD §5.1 FR-8, §5.2, §6.4 | Classification result contract. |
| `src/riffle/inputs.py` | PRD §6.1, FR-1, FR-6 | Decode JPEG/PNG/HEIC, EXIF orientation and GPS, region resolution. |
| `src/riffle/app.py` | PRD §5.0, AREA-VIEWER §5 | FastAPI routes and pages, per-address rate limit on classification. |
| `src/riffle/static/index.html` | PRD §5.0, M0 | Classifier page. |
| `tests/` | | Named after the requirement they check. The area tests use a fake fetcher. |
| `docs/` | | Feature spec and hackathon submission notes. |

## Species model

| `ANTHROPIC_API_KEY` set | Ollama running with a vision model | Backend used |
|---|---|---|
| yes | any | Claude (`claude-opus-5`; override with `CLAUDE_MODEL`) |
| no | yes (`ollama pull qwen2.5vl:3b`) | local model via Ollama (`OLLAMA_MODEL` to pick one); 1.5–2.5 min per photo on an 8 GB laptop |
| no | no | none: placeholder label at 0 %, stated in the result |

`/api/health` reports which one is active; `RIFFLE_IDENTIFIER=claude|ollama|none`
forces a choice. `/api/classify` allows 20 requests per client address per 10 minutes
(`RIFFLE_CLASSIFY_LIMIT`, 0 to disable) so a public demo cannot drain the key. Measured end to end with the local model: a California sagebrush
photo taken in Irvine → **Native, 85.5 %**, resolved to iNaturalist taxon 53357, status
"native in Orange County", no penalties.

## Data sources

| Source | Used for | Terms |
|---|---|---|
| [iNaturalist API](https://api.inaturalist.org/v1/docs/) | Sightings, species counts, yearly histograms (research-grade only) | Free, attribution, ~1 req/s |
| [Global Forest Watch](https://www.globalforestwatch.org/) (Hansen/UMD/Google/USGS/NASA) | Tree-cover loss tiles | CC BY 4.0, attribution |
| Esri World Imagery and Reference | Basemap and labels | Esri attribution |
| Cal-IPC Inventory, CDFW, USGS NAS, UC IPM | Seed list of listed invasives | Public lists; seed is unverified |

## Decisions and deviations

- **Only the seed list can say "Invasive".** iNaturalist's establishment flag gives
  Native or Naturalized; "invasive" is a policy label, so it needs a listed source
  (Cal-IPC, CDFW, USGS NAS, UC IPM). A species iNaturalist calls introduced but no
  list names is reported as Naturalized/Non-native, never upgraded.
- **Certainty factors are priors, not calibration.** The rule in `pipeline.py`
  multiplies model confidence, status-source confidence, a region factor and an
  input factor. It orders outcomes sensibly and explains itself, but PRD §8
  calibration testing has not been run; `pipeline_version` tracks the rule.
- **"Introduced" is not "invasive".** iNaturalist flags non-native establishment;
  Cal-IPC and CDFW decide invasiveness. The map keeps both words apart and only rings
  taxa in the seed list. The seed is small and expert-unverified, and its version is
  echoed in every response.
- **Region is a bounding box first, then the county polygon.** PRD §7 says v1 only
  needs "is this in Orange County". The box answers instantly and offline; the
  pipeline then refines it with iNaturalist's boundary for place 2738 (cached), so
  Long Beach or Corona no longer count as in-county. If the fetch fails the box stands.
- **Stage 2 detection uses the vision model as the detector.** PRD §6.2 asks for a
  detector tuned per regime; v1 instead asks the same model for a subject box, and
  when the subject covers under a quarter of the frame, crops to it and identifies
  again at full resolution, keeping the more confident pass. One model, two calls,
  and the box is drawn on the result page. A dedicated small-object detector is M4.
- **Distant framing lowers certainty.** PRD §9 says not to imply uniform confidence
  across regimes, so mid-distance and far shots carry a factor (0.92 and 0.85) and a
  named penalty. Like the other factors it is a prior, not calibration.
- **Seed entries carry iNaturalist's accepted name plus synonyms.** Fountain grass is
  *Pennisetum setaceum* on the Cal-IPC list and *Cenchrus setaceus* on iNaturalist;
  before synonyms it silently missed the ring on the map and the Invasive label.
  Matching now checks the model's spelling and iNaturalist's name against both.
- **An iNaturalist outage degrades, it does not fail.** The seed list still answers
  offline; anything else returns the neutral label at low confidence with the outage
  named in the evidence (PRD §5.2). The map still returns a 502, since it has nothing
  to show without upstream.
- **Placeholder label is Naturalized/Non-native.** PRD FR-8 forbids a "needs review"
  answer, so M0 returns one of the three labels. Naturalized is the only one that prompts
  neither removal nor protection (PRD §9 asymmetric cost).
- **Image beats text when both are sent.** FR-2 makes text a fallback for when no
  usable image exists, and PRD §9 makes it strictly lower confidence.
- **Coordinates are never stored** (PRD §5.2 privacy). They are used for the in-county
  test and echoed in the response once; the map cache is keyed by viewport only.
- **Tree-cover loss as the first habitat layer.** The only free, keyless, tile-served
  change layer with clear attribution. It under-represents scrub and grassland change,
  which is most of Orange County; fire perimeters are the planned second layer.
