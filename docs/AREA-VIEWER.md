# Area viewer: feature spec

> **Inherited feature.** This is SpeciesGuard's area viewer, kept working in AquaPlot and
> served at `/map`, where it now also draws AquaPlot's own stream assessments coloured by
> ecological band. What changed: the Orange County scope switch became a `place_id` filter
> that accepts any iNaturalist place, the default view is the world rather than one county,
> and a selector jumps to the five OneAquaHealth research cities. Read "Orange County" below
> as "the place in view".

**Status:** v1 shipped 2026-09-16. Addendum to [PRD.md](../PRD.md) (SpeciesGuard v1.1);
this document is the PRD for the feature and uses the same conventions
(numbered requirements, explicit non-goals, decisions with reasons).

## 1. Problem

The classifier answers "what is *this* organism, here?". Land managers, restoration
volunteers and curious residents also need the inverse question: "what is going on in
*this place*?". Where are the introduced species concentrated, is that hillside still
native scrub, has anything threatened been seen near the trail, and is tree cover
being lost there. Today that means opening iNaturalist, Cal-IPC, Global Forest Watch
and a satellite map in four tabs and mentally overlaying them.

## 2. Goal

A Google-Maps-style satellite viewer of the local area where layers of biodiversity
pressure can be switched on, filtered and inspected point by point, live from public
data, with no account and no install.

### Non-goals (v1)

- Not an infestation-severity or population estimate. Points are sightings, and
  sighting density tracks where people walk as much as where organisms live.
- Not a legal invasive determination. "Introduced" comes from iNaturalist's
  establishment flag; the listed-invasive ring comes from a small seed list. See §6.
- Not offline. Every layer is fetched live.
- Not a reporting tool. Users report through iNaturalist itself (every popup links there).

## 3. Users and use cases

| User | Use |
|---|---|
| Restoration volunteer | Before a work day, see which listed invasives cluster around the site and which natives to avoid trampling. |
| Hiker / resident | Pan to a park, toggle threatened sightings, learn what to look for. |
| Student / educator | Compare the introduced share of sightings across years or between two parks. |
| The classifier's own user | After a photo is classified, jump to the map at that photo's GPS position to see what else has been seen there. |

## 4. Requirements

- **FR-A1 Satellite basemap.** Esri World Imagery with a separately toggleable place-label
  overlay, scale bar, zoom, and a "my location" control.
- **FR-A2 Sighting layers.** Three independently toggleable point layers, each fed by
  iNaturalist research-grade observations in the current viewport: *introduced*, *native*,
  *threatened*. Points cluster when dense and expand on zoom. Each point opens a popup
  with the photo, common and scientific name, date, place guess and a link to the
  observation. Obscured-location observations are dropped because they cannot be placed.
- **FR-A3 Listed-invasive marking.** Introduced sightings whose taxon is in the project's
  status seed list are drawn with a dark ring and their popup names the rating and source.
- **FR-A4 Species panel.** The most-observed species for the selected status in the
  viewport, with counts, thumbnails and listed-invasive tags.
- **FR-A5 Trend panel.** Sightings per year in the viewport for all three statuses, plus
  the introduced share of native+introduced sightings for the first and last year shown.
- **FR-A6 Filters.** Taxonomic group (plants, insects, birds, mammals, reptiles,
  amphibians, fish, fungi, mollusks, arachnids), year range, and an Orange County-only
  switch that clips to the real county polygon rather than a box.
- **FR-A7 Habitat-loss layer.** Hansen/UMD tree-cover loss 2001–2024 raster tiles from
  Global Forest Watch, toggleable, with attribution.
- **FR-A8 Density heatmap.** Heat layer built from the introduced sightings in view.
- **FR-A9 Deep link from the classifier.** The classification result links to
  `/map?lat=…&lon=…&z=14` when the photo or device supplied a location.
- **FR-A10 Graceful failure.** An upstream outage shows a message in the panel and leaves
  the last good layer on the map; it never blanks the page.

### Non-functional

- Reload on pan/zoom is debounced (350 ms) and stale responses are discarded, so fast
  panning never paints an old viewport's points over a new one.
- Server-side cache (10 min, 512 entries) keeps the app inside iNaturalist's guidance of
  roughly one request per second and a daily ceiling.
- Works at phone width: the panel becomes a bottom sheet behind a "Layers" button.
- No API keys. Everything used is public and attribution is shown on the page.

## 5. Architecture

```
browser (Leaflet, map.html)
  │  GET /api/area/observations?south&west&north&east&oc&taxa&year_from&year_to&status
  │  GET /api/area/species?…&status&top
  │  GET /api/area/trend?…
  ▼
FastAPI (app.py)  ──▶  AreaQuery (validation)  ──▶  AreaService (area.py)
                                                       │  in-memory TTL cache
                                                       ▼
                                             iNaturalist API v1 (observations,
                                             species_counts, histogram)
tiles fetched directly by the browser: Esri imagery + labels, GFW tree-cover loss
```

Why a server proxy instead of calling iNaturalist from the browser: the cache, one
place to enforce the parameter allowlist, one place to tag listed invasives, and the
status seed stays server-side so the M2 status database can replace it without a
frontend change.

### Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/area/observations` | GeoJSON FeatureCollection; `total` is the upstream count, `features` capped at 200. |
| `GET /api/area/species` | Ranked list `{count, scientific_name, common_name, group, listed, photo}`. |
| `GET /api/area/trend` | `{years, introduced[], native[], threatened[], introduced_share_pct[]}`. |
| `GET /api/area/listed` | The seed list and its version. |
| `GET /map` | The page. |

Common query parameters: `south west north east` (all four or none), `oc` (bool),
`taxa` (comma-separated iconic taxa), `year_from`, `year_to`, `limit` (≤200). A bad
viewport or unknown group is a 422; an upstream failure is a 502 with the reason.

## 6. Data sources and their limits

| Layer | Source | Terms / attribution | Caveat |
|---|---|---|---|
| Sightings | iNaturalist API v1, research-grade only | Free, attribution required, ~1 req/s | Observer effort bias: dense where people are, sparse in closed or private land. |
| Introduced / native / threatened | iNaturalist establishment means and conservation status, relative to the observation's place | as above | "Introduced" is *non-native*, not *invasive*. Threatened is IUCN/NatureServe-style status, not local rarity. |
| Listed invasive ring | `src/aquaplot/data/status_seed.json` (76 entries hand-picked from Cal-IPC Inventory, CDFW, USGS NAS, UC IPM, CDFA, OC Vector Control; iNaturalist-accepted names plus synonyms) | Seed only | Unverified by an expert. Its version is echoed in every response. To be replaced by the full Cal-IPC inventory. |
| Tree-cover loss | Hansen/UMD/Google/USGS/NASA via Global Forest Watch tiles | Attribution required (CC BY 4.0) | 30 m resolution, tree cover ≥30 %, so it shows canopy loss, not scrub or grassland change, and Orange County has little canopy outside riparian corridors and parks. |
| Imagery | Esri World Imagery and Reference tiles | Esri attribution required | Capture dates vary by tile. |

Privacy: the browser sends its viewport, and optionally its geolocation to centre the map.
Nothing is stored server-side beyond the response cache keyed by query.

## 7. Decisions

- **Live data over a bundled snapshot.** A snapshot would be reproducible but stale within
  days and would hide the point of the feature: watching the county change. The cache
  and the fake fetcher in tests give reproducibility where it matters.
- **iNaturalist over GBIF.** GBIF has more records but no place-relative establishment
  flag and fewer photos; iNaturalist is also what the M1 classifier will train on.
- **Tree-cover loss as the first habitat-loss layer.** It is the only global,
  free, tile-served, well-attributed change layer available without a key. Fire
  perimeters (NASA FIRMS, CAL FIRE) and land-cover change would be better fits for
  Southern California scrub and are the first candidates for a second layer.
- **Point cap of 200 per layer.** iNaturalist's page ceiling. The panel shows "200 of
  N" so the user knows to zoom in. Paging was left out because the heatmap and
  clusters already convey density.

## 8. Future work

- Second habitat layer: CAL FIRE perimeters or NASA FIRMS active fire (needs key).
- Protected areas (CPAD) and OC Parks boundaries as context polygons.
- Time slider that animates the year filter.
- "Your classifications" layer once M1 produces species IDs, closing the loop
  between the two halves of the product.
- Replace the seed list with the M2 status database and show Cal-IPC rating in the
  species panel for every taxon, not only the seeded ones.
