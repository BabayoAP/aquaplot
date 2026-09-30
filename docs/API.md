# API reference

Everything the interface does, it does through this API, and nothing is reserved
for the first-party pages. Interactive reference with request bodies and response
schemas: **`/docs`** on a running instance.

Base URL is the deployment root. There is no authentication and there are no
accounts; a contributor is an opaque id the browser generates and keeps.

## Recording an assessment

### `POST /api/assess`

`multipart/form-data`. Everything is optional individually, but at least one of a
photo, a habitat answer, a species name or a description must be present.

| Field | Type | Notes |
|---|---|---|
| `photos` | file, repeatable | JPEG, PNG or HEIC, up to 25 MB each. Send the reach and the sample tray. |
| `description` | string | Free text from the observer. |
| `lat`, `lon` | float | Used only if no photo carries EXIF GPS. EXIF wins, because it records where the *photo* was taken. |
| `site_name` | string | What people call the spot. |
| `answers` | JSON object | `{"odour": "sewage", "algae": "bloom"}`. Keys and values must come from `/api/form`; an unknown key is a 422, not a silent drop. |
| `taxa` | JSON array | `["Gammaridae", "Chironomidae"]`, or a group for an honest group-level answer (`"Plecoptera"`). **Sending this makes the check citizen-identified:** this list is what gets scored, and the model's view of the tray photo becomes a blind second opinion that can only raise questions. Omit it and the model's identifications are scored as unconfirmed proposals. |
| `index` | string | `bmwp` or `ibmwp`. Omit it and the index follows the country the coordinates resolve to (IBMWP in Portugal and Spain). |

Send `X-AquaPlot-Contributor: <opaque id>` to have the assessment counted towards
a contributor's record. Omit it and the assessment is still stored, anonymously.

Rate limited per client address (default 20 per 10 minutes, `AQUAPLOT_CLASSIFY_LIMIT`).

```sh
curl -X POST http://localhost:8000/api/assess \
  -F photos=@reach.jpg -F photos=@tray.jpg \
  -F lat=40.2111 -F lon=-8.4291 -F 'site_name=Ribeira da Fonte' \
  -F 'answers={"odour":"sewage","access":"play_or_drinking"}' \
  -F 'taxa=["Gammaridae"]'
```

The response is the full assessment: `band`, `ecology`, `pressures`, `one_health`,
`invasives`, `certainty`, `penalties`, `needs_confirmation`, `region`, `identified_by`,
`second_opinion` and `weather` (rain in the 48 hours before and forecast for the 48 after,
from Open-Meteo; `null` with no coordinates, for a visit entered long afterwards, or when the
lookup fails; `AQUAPLOT_WEATHER=off` disables it). `observer` names the model backend, or says
`recorded` when the photos were the bundled samples (`GET /api/samples`). See [ASSESSMENT.md](ASSESSMENT.md) for what each number means.

`ecology` names its index (`index`, `index_key`, `total_label`, `mean_label`,
`citation`). For historical reasons `ecology.bmwp` and `ecology.aspt` hold the total
and the mean of *whichever* index was used. Each entry in `ecology.taxa` says whether
the index scored it (`scored: false` for, say, mosquito larvae under BMWP; they still
count for the health checks).

`second_opinion` is `null` when the model proposed the identifications, and otherwise:

```json
{
  "available": true,
  "agreed": ["Midge larva (bloodworm)"],
  "independent_agreements": 1,
  "adopted": [],
  "dismissed": [],
  "open": [{
    "kind": "disagree",
    "key": "disagree:perlidae:baetidae",
    "question": "You marked Stonefly. The model thinks this may be Mayfly (swimmer). Which is it?",
    "how_to_tell": "Count the tails and look at the sides of the body. ...",
    "citizen_name": "Perlidae", "model_name": "Baetidae",
    "band_if_model_right": "Bad", "changes_band": true, "priority": 1
  }],
  "model_taxa": [{"name": "Baetidae", "confidence": 0.8}]
}
```

Open items also appear in `needs_confirmation` with `kind: "second_opinion"` and
`check` set to `disagree`, `model_only` or `unsupported`.

### `POST /api/assess/{id}/review`

Fold a person's confirmations and corrections in. **The vision model is not called
again**, because re-running it could overwrite the correction just made.

```json
{
  "answers": {"algae": "bloom"},
  "confirmed_taxa": ["Chironomidae"],
  "rejected_taxa": ["Asellidae"],
  "added_taxa": ["Perlidae"],
  "dismissed": ["disagree:perlidae:baetidae"],
  "site_name": "Ribeira da Fonte"
}
```

Settling a second-opinion question is expressed in the same terms: *keep mine* or
*not there* sends the item's `key` in `dismissed`; *it's the model's* sends the
citizen's name in `rejected_taxa` and the model's in `added_taxa`; *add it* sends the
model's name in `added_taxa`.

Returns a **new** assessment carrying `supersedes`. The row it replaces drops out
of every count, trend and feed but stays fetchable by id, as the record of what
the model said before a person corrected it.

### `GET /api/assess/{id}`

The stored assessment, exactly as produced.

## Getting an assessment out

| Endpoint | Returns |
|---|---|
| `GET /api/assess/{id}/report` | A printable incident report for a water authority. |
| `GET /api/assess/{id}/report.md` | The same report as Markdown, for pasting into a contact form. |
| `GET /api/assess/{id}/fhir` | A FHIR R4 collection Bundle conforming to the OneAquaHealth IG's profiles, validated with the HL7 validator. See [FHIR.md](FHIR.md). |
| `GET /api/assess/{id}/oah-app` | The check as a OneAquaHealth Citizen Science App submission (`CitizenSubmissionPutDTO`) in the app's answer codes: `body`, the `carried` fields with their sources, what was `not_carried` and why, and the matched `research_site`. Not sent anywhere. |
| `GET /api/fhir/CodeSystem/stream-health` | The project CodeSystem every non-standard code in a bundle belongs to. |
| `GET /api/export.csv` | Every live assessment, one row each. Superseded revisions excluded. `biotic_index`, `index_total` and `index_mean` say which scale each row's numbers are on. |
| `GET /api/export.geojson` | Monitored sites as points, with their trend. |

## Sites and insight

| Endpoint | Returns |
|---|---|
| `GET /api/sites` | One row per monitored spot with its latest band and trend. Optional `south`/`west`/`north`/`east` viewport (all four or none). |
| `GET /api/sites/nearby?lat=&lon=&radius_m=` | Sites near a point, nearest first, so a returning volunteer can say "same spot". Default radius 250 m, max 5 km. |
| `GET /api/sites/{site_key}` | Every visit at one spot, newest first, plus the trend. |
| `POST /api/sites/{site_key}/name` | `{"name": "..."}`. Lets people give a stretch the name they use for it. |
| `GET /api/insights` | The dashboard's headline numbers, band and level distributions, monthly activity. |
| `GET /api/alerts?days=30` | Sites whose **latest** assessment reached concern or alert. The early-warning feed. |
| `GET /api/outlook` | The next 48 hours: each site's latest reading re-run through the rules with Open-Meteo's forecast, keeping the forward-looking findings (heavy rain ahead, heat ahead). Worst first; cached for 30 minutes; one forecast request covers every site. |
| `GET /api/me/progress` | One contributor's record and badges. Requires `X-AquaPlot-Contributor`; returns an empty record without it. |

A `site_key` is `lat,lon` rounded to three decimals, which is roughly a hundred
metres. That is what groups repeat visits to "the same spot".

## Reference data

These exist so the interface is *generated* rather than hand-maintained, and so
anyone else can build against the same vocabulary.

| Endpoint | Returns |
|---|---|
| `GET /api/form` | The visual field form: every indicator, its question, its options, its `why`, and whether a photograph can answer it. |
| `GET /api/guide` | The bioindicator catalogue: 53 families with their BMWP and IBMWP scores (`null` where an index does not score the family), sensitivity, what to look for and what finding it means. |
| `GET /api/field-guide.md` | The sampling protocol as Markdown. Rendered for printing at `/field-guide`. |
| `GET /api/samples` | The sample check: two openly licensed photos (URLs, credits, licences), where the sample is placed, and who recorded the model's reading of them. Posting these photos to `/api/assess` replays the recording instead of calling a model. |
| `GET /api/pilots` | The five OneAquaHealth research cities, with viewports. |
| `GET /api/oah/sites` | The OneAquaHealth project's 106 research sites (code, name, city, coordinates), from a snapshot of its public API, and the radius within which a check is linked to one. |
| `GET /api/live-readings` | How many live photo readings this tester has left when the paid model is on: `limited`, `per_tester`, `used`, `left` and, at zero, the `reason`. `{"limited": false}` otherwise. See `allowance.py`. |
| `GET /api/health` | Liveness, plus every version that shapes a result: assessment, catalogue, form, seed, and which model backend is active. |

## Inherited from SpeciesGuard

Still supported; see [CLASSIFIER.md](CLASSIFIER.md) and [AREA-VIEWER.md](AREA-VIEWER.md).

| Endpoint | Returns |
|---|---|
| `POST /api/classify` | One organism from one photo: native / invasive / naturalized, with an evidence trail. |
| `GET /api/area/observations` | iNaturalist research-grade sightings in a viewport as GeoJSON. |
| `GET /api/area/species` | Most-observed species in a viewport. |
| `GET /api/area/trend` | Sightings per year by establishment status. |
| `GET /api/area/listed` | The invasive seed list. |

## Errors

| Status | Means |
|---|---|
| 400 | An image could not be decoded. |
| 404 | No assessment or site with that id. |
| 422 | A field is outside the accepted vocabulary; the message names it. |
| 429 | Rate limited; `Retry-After` is set. Also from `/api/classify` once the tester's live readings are used up. (`/api/assess` never refuses for that: past the limit it runs without the model and says why.) |
| 502 | An upstream source (iNaturalist) failed in a place the request could not degrade around. |

Assessment endpoints keep working when something is missing: a model outage, an
unresolvable place, a missing photo and a dead iNaturalist each cost a named
certainty penalty instead of causing an error.

## Pages

| Path | What |
|---|---|
| `/` | The guided stream check. |
| `/site/{site_key}` | One spot's history, with the class-over-time chart. |
| `/dashboard` | Insights across every site. |
| `/map` | Assessments over satellite imagery and iNaturalist layers. |
| `/field-guide` | The printable sampling protocol. |
| `/classify` | The inherited single-organism classifier. |
| `/docs` | Interactive OpenAPI reference. |

## Offline

`/sw.js` is a service worker with root scope. It caches the check page, `/api/form`
and `/api/guide`, so a whole assessment can be completed with no connection; the
page keeps unsent assessments in IndexedDB and flushes them when the browser comes
back online. The worker never queues writes. The outbox is in the page, where it
is visible and can be sent by hand.
