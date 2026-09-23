# NextStep Hacks 2026 — submission notes

Hackathon: **NextStep Hacks 2026** (HackAlphaX, Devpost). Theme **Earth Forward**.
Deadline **Sep 20, 2026, 2:00 pm PDT**. Tracks: Beginner Friendly, Machine Learning/AI,
Social Good. Requirements: a video demo/pitch of at most 5 minutes, a repository link,
and a live link where applicable.

## What this project is, in one paragraph

SpeciesGuard is a two-part tool for biodiversity in Orange County, CA. The **classifier**
takes a photo of a plant, animal, insect or fungus, identifies it with Claude or a local
vision model, checks the species against iNaturalist's place-relative establishment data
and a list of Cal-IPC/CDFW invasives, and returns native, invasive or naturalized for
*here*, always with a certainty percentage and an evidence trail rather than a refusal.
The **area viewer** is a satellite map of the county where introduced, native and
threatened species sightings, listed invasives, tree-cover loss and sighting trends can
be layered, filtered and inspected point by point, live from public data.

## Timeline disclosure (required by the rules)

The hackathon ran Aug 21 to Sep 20, 2026 (extended one week).

| When | What |
|---|---|
| Sep 11, 2026 | Product requirements document drafted (PRD.md). No code. |
| Sep 14, 2026 | GitHub repository created with a two-line README. No code. |
| Sep 16, 2026 | Classifier interface and contract, EXIF/geolocation, species identification (Claude / Ollama backends), status resolution against iNaturalist and the seed list, the certainty rule; the area viewer (server data layer, map page); tests and docs. |
| Sep 17, 2026 | Stage 2 detect → crop → re-identify with the subject box drawn on the result; county polygon check; seed list grown to 76 entries with synonyms (fixed a name mismatch that hid fountain grass); graceful iNaturalist outage handling; rate limit for the public demo; camera/library pickers and HEIC preview fallback; tests to 68. |

Everything in the repository was built during the hackathon window. No prior codebase
was reused.

## Mapping to the theme

Earth Forward asks for technology aimed at a pressing environmental problem. Invasive
species are the second-largest driver of biodiversity loss after habitat destruction, and
identifying them is bottlenecked on expert review. The project attacks that from both
ends: an automated call on a single organism, and a county-wide view of where the
pressure is. Both are scoped to the builder's own community (Orange County), which is
what the theme statement asks for, and the data sources are the same ones local
conservation groups use, so results are directly actionable.

## Mapping to the judging criteria

| Criterion | Where it lands |
|---|---|
| Originality | Existing tools do species ID *or* map sightings. Combining a place-relative invasive call with a layered satellite viewer, with an always-answer certainty design, is the new part. |
| Adherence to track | Conservation, ecosystem monitoring, biodiversity loss: squarely inside the theme statement's list. |
| Completion | Every endpoint and page works against live data; 68 tests pass without the network; photo → subject box → crop → species → county status → label + certainty runs end to end, degrades when upstream is down, and the UI states which model answered. |
| Learning | First project with iNaturalist and Global Forest Watch data, Leaflet clustering and heatmaps, EXIF GPS parsing, and a calibrated-certainty output design. |
| Design | Phone-first layout, dark mode, clusters that expand on zoom, popups with photos, a bottom-sheet panel on mobile, attribution and caveats on the page. |
| Technology | Pluggable species identification (Claude structured output or a local Ollama VLM, same schema), the vision model doubling as a detector for a detect → crop → classify pass, taxonomy resolution with synonym handling and place-relative status via iNaturalist, point-in-polygon county check, an explainable five-factor certainty rule, FastAPI proxy with TTL cache and rate limiting, injectable fetchers for network-free tests, four public data sources composed live, HEIC decoding, EXIF orientation and GPS. |

## Submission checklist

- [ ] Video ≤ 5 min (script below).
- [ ] Repository link: https://github.com/BabayoAP/aquaplot. **The repo is private today**: make it public (Settings → Danger zone → Change visibility) before submitting.
- [ ] Live link (deploy notes below).
- [ ] Devpost "built with": Python, FastAPI, Claude API, Ollama, Leaflet, iNaturalist API, Global Forest Watch, Esri.
- [ ] Set `ANTHROPIC_API_KEY` on the deployed instance so judges get Claude-quality identification (Claude is a sponsor; the prize includes Claude credits). Without it the live link runs the placeholder.
- [ ] Devpost description includes the timeline table above verbatim.
- [ ] Devpost description states that Claude Code was used as a pair programmer throughout (the rules do not forbid AI tools and Claude is a sponsor, but the "Learning" criterion is judged on what *you* learned, so say what you decided and what you learned).
- [ ] Confirm eligibility: students only, 13+, no company affiliation (see "Rules to keep in mind").
- [ ] Open the live link once before judging starts so the free instance is awake.

## Video script (target 4 min)

1. **0:00–0:30 Problem.** One sentence on invasive species and the expert bottleneck. Show
   Cal-IPC list and an iNaturalist page side by side: "status lives here, sightings live
   there, imagery lives somewhere else".
2. **0:30–1:30 Area viewer.** Open `/map`. Zoom into a park. Toggle introduced, point at a
   dark-ringed pampas grass, open the popup. Toggle native, then threatened. Switch group
   to Plants, set years 2020–2026, hit Apply. Show the species panel and trend line, read
   the introduced-share sentence aloud.
3. **1:30–2:00 Habitat layer.** Toggle tree-cover loss, pan to a riparian corridor.
   Toggle the heatmap.
4. **2:00–3:00 Classifier.** On a phone or with a phone-shaped window, upload a photo of
   pampas grass with GPS. Show the result: Invasive, the certainty, the candidates, the
   model's one-line reasoning, the Cal-IPC source, then "what lowered the certainty".
   Then a far shot of the same plant across a slope: point at the subject box drawn on
   the preview and the "cropped and identified again" line. Repeat with a native
   (California sagebrush) and with a text-only description to show the certainty drop.
   Click the deep link to the map filtered to that species.
5. **3:00–3:30 Under the hood.** Show `area.py` docstring, the test run, the cache.
6. **3:30–4:00 What's next.** A dedicated small-object detector for far shots (M4),
   calibration testing of the certainty rule (M7), replacing the seed list with the
   full Cal-IPC inventory, multi-organism results, fire-perimeter layer.

## Deploying a live link

The app is one process with no database, so any container host works. A `Dockerfile` is
in the repo root.

```sh
docker build -t aquaplot .
docker run -p 8000:8000 aquaplot
```

**Render (free tier, one click).** The repo has a `render.yaml` blueprint. Sign in at
<https://dashboard.render.com>, choose *New → Blueprint*, pick this repository, and
accept the defaults. The free instance sleeps after 15 minutes idle and takes about
30 s to wake, so open the link once before the judges do. Alternatively:
<https://render.com/deploy?repo=https://github.com/BabayoAP/aquaplot>.

The blueprint prompts for `ANTHROPIC_API_KEY` and sets a 20-per-10-minute
classification limit per address. Railway and Fly.io also work: Docker build,
expose port 8000, same environment variables. Camera capture and device geolocation require HTTPS, which all of these
provide by default.

## Rules to keep in mind

- Students only, ages 13+. Individual submission is fine.
- Submitting to another hackathon this month is allowed if the other one allows it.
- Judges are the HackAlphaX team, so the video must stand on its own: no assumed context.
