# Product Requirements Document

## SpeciesGuard — Automated Invasive vs. Native Species Classification from Imagery

**Status:** Draft v1.1 — scope decisions incorporated
**Owner:** Harrison
**Doc type:** PRD (Product Requirements Document)
**Project type:** Passion project (not a commercial product) — scoped accordingly: favor what's buildable and fun to iterate on over enterprise-grade rigor.

---

## 1. Problem Statement

Identifying whether an organism observed in the field is invasive or native is currently a bottleneck across conservation, agriculture, land management, and citizen science. Existing workflows depend on human experts to review submitted photos, cross-reference range maps, and apply taxonomic judgment — a process that is slow, inconsistent, and doesn't scale. Platforms like iNaturalist have shown that CNN-based species recognition at the *species level* works at scale, but converting "this is species X" into "this is invasive *here*" still typically requires a human to check a status list, and the underlying models are built for well-composed, close-up photos of a single subject — not for the full range of image quality and distance a user might realistically capture (close-up macro of a leaf vein or insect eye, all the way out to a distant landscape shot where the organism is a small part of the frame).

**Goal:** Build a system that takes a single image (or, per the fallback path, a text description) of a plant, animal, insect, or fungus and — without any human in the loop — outputs a determination of **invasive**, **native**, or **uncertain/needs review**, regardless of whether the image is an extreme close-up or a far-away macro/landscape-scale shot.

---

## 2. Goals and Non-Goals

### 2.1 Goals
- Fully automated pipeline: image or description in, classification out — zero human review in the default path.
- Robust across the full zoom spectrum: macro/close-up (e.g., a beetle's carapace, a leaf's stomata) to wide/far shots (e.g., a hillside with a shrub visible at 50+ meters).
- Species identification *and* invasive/native status determination, since status is location-dependent and not an inherent property of the species.
- Text-only fallback: if no usable image exists, accept a natural-language description and still produce a best-effort classification with appropriately wider uncertainty bounds.
- **Always return an answer, paired with a projected certainty rate** — rather than withholding a call behind an "uncertain, needs review" gate, the system commits to a best guess every time and lets the confidence percentage carry the honesty (see Section 6.4 and 9 for how this changes the status-resolution logic and risk framing versus the original draft).
- Usable by non-experts (the "no human interaction" requirement implies the *user* isn't expected to be a taxonomist either).
- **Geographic scope: start with Orange County, CA.** Architecture and data pipeline should be designed so scaling to other counties/states/countries later is a data-and-status-database expansion, not a re-architecture — but v1 build effort, data collection, and accuracy targets are all scoped to Orange County first.
- **Organism scope: broad from the start** — plants, insects, fungi, aquatic species, and vertebrates, *plus* cellular/microscopic-level imagery. This last category (cells) is a meaningfully different imaging modality (microscopy rather than photography) and is called out separately in Sections 6 and 7.

### 2.2 Non-Goals (v1)
- Not a real-time video/tracking system (single-image and single-description inputs only in v1).
- Not a population-density or infestation-severity estimator — status classification only, not "how bad is it."
- Not a legal or regulatory determination tool. Output is decision support, not an official regulatory finding (invasive status is legally defined per jurisdiction and changes over time).
- Not a replacement for expert verification in high-stakes actions (e.g., authorizing eradication/spraying) — see Section 9, Risk & Guardrails.
- Not attempting brand-new species discovery or novel taxonomy.

---

## 3. Background & Prior Art

Research and existing tools were reviewed to ground the technical approach:

- **iNaturalist's Vision API / CNN models** are trained on millions of labeled, community-verified photos and are the de facto standard for species-level image recognition, but they operate one well-framed image at a time and don't natively output invasive/native status — that's typically joined afterward against a status database (this is exactly the pattern used by tools like iMapInvasives' automated confirming workflow, which pairs iNaturalist's model with geolocation to auto-confirm reports above a confidence threshold).
- **Detection-then-classification pipelines** (e.g., MegaDetector/SpeciesNet for camera traps) first localize the organism in the frame (bounding box / crop) and *then* classify the crop — this consistently outperforms classifying the raw, uncropped image, especially when the subject is small in the frame. This is directly relevant to the close-up-to-far-away requirement.
- **Global models have geographic and taxonomic gaps.** Global classifiers (e.g., SpeciesNet, ~2,500 classes) don't cover all regions/species; regional fine-tuning improves accuracy for local deployments. This matters because "invasive" is inherently a *place-based* label — the same species is invasive in one region and native in another.
- **Object-detection approaches (YOLO variants) for invasive species** have been used for small/dense/difficult targets (e.g., aquatic invasives with occlusion, cluttered backgrounds), reinforcing that a single monolithic classifier struggles across the full range of framing/distance conditions.
- **Data sources available for training:** iNaturalist research-grade observations, GBIF (Global Biodiversity Information Facility) occurrence + imagery data, USDA/state invasive species lists, and existing Kaggle-style labeled sets — though these are strongest for macro/close-up photography and comparatively sparse for distant/landscape-scale shots, which is a known gap this program needs to explicitly address (see Section 6.3).

**Implication for this PRD:** a single end-to-end classifier is unlikely to hit acceptable accuracy across the full close-up-to-distant spectrum. The architecture in Section 6 is deliberately a multi-stage pipeline rather than one model.

---

## 4. Users & Use Cases

| User | Use case |
|---|---|
| Land manager / park ranger | Snap a photo in the field, get an immediate flag on whether something needs removal follow-up |
| Home gardener / hiker | Point phone camera at a plant/insect, find out if it's a species of concern |
| Agricultural inspector | Rapidly triage large volumes of field photos or drone/macro imagery |
| Conservation nonprofit / citizen science platform | Batch-process a backlog of user-submitted photos without expert bottleneck |
| Researcher without a usable photo | Provide a written description (e.g., from a written field log or a partially damaged photo) and still get a best-effort read |

**Core user story:** "As someone standing in front of a plant/animal with only my phone camera, I want to know — right now, without waiting on an expert — whether this is a native species or one I should report/remove, regardless of whether I can get a clean close-up or I'm only able to photograph it from a distance."

**Note on scope framing:** since this is a passion project rather than a commercial product (v1 targeting Orange County, single builder), the "user" for v1 is effectively Harrison — build for personal exploration and field use first, and treat multi-user/platform concerns as later scaling questions rather than v1 requirements.

### 5.0 Interface decision

No existing app to integrate with, and picking the "best" interface: for a passion project, the lowest-friction path to something usable is a **simple single-page web app** — snap or upload a photo (mobile browser camera input works natively), optionally paste a description if no photo, get a result back on the same page. No native app build, no app-store overhead, works immediately from a phone in the field via a bookmarked URL. Revisit a dedicated mobile app only if this gets used enough to justify it.

---

## 5. Key Requirements

### 5.1 Functional Requirements
1. Accept a single still image (JPEG/PNG/HEIC) as primary input.
2. Accept free-text natural-language description as a fallback input when no image is available or the image is unusable.
3. Automatically detect image "regime" (extreme macro / close-up / mid-range / distant-wide) and route accordingly — the user should not have to tell the system how the photo was taken.
4. Localize the organism(s) in the frame before classification (detection/segmentation step) when the subject is not already frame-filling.
5. Identify the most likely species (or genus-level grouping when species-level confidence is too low).
6. Resolve geolocation (from EXIF GPS if present, else user-provided or IP-approximated region, else "unknown region" fallback) since invasive/native status is region-dependent.
7. Cross-reference the identified species + region against an invasive/native status database to produce the final label.
8. Always output one of **Native**, **Invasive**, or **Naturalized/Non-native (not officially listed invasive)** — the single most likely label — **paired with a projected certainty percentage**, rather than deflecting to a "needs review" non-answer. A low certainty score (e.g., 40%) is itself the signal to the user that the call is shaky; the system doesn't refuse to call it.
9. Support multi-organism images (return per-organism results when multiple distinct subjects are detected).
10. No required human-in-the-loop step for the system to produce an output (a human can optionally review later, but the pipeline must complete end-to-end without one).

### 5.2 Non-Functional Requirements
- **Latency:** target under 5 seconds per single-image request for interactive/mobile use; batch mode may relax this.
- **Availability:** degrade gracefully — if geolocation is unavailable, still return a species ID with a caveat rather than failing outright.
- **Transparency:** every output includes the evidence trail (what was detected, what species match(es) were considered, what status source was used) so downstream review is possible even though it isn't required.
- **Extensibility:** status database and species-recognition model must be independently updatable (invasive species lists change; new species get added) without retraining the whole pipeline.
- **Privacy:** if EXIF/geolocation data is used, handle per applicable data-privacy norms; don't retain precise user location beyond what's needed for the classification.

---

## 6. Proposed System Architecture

A four-stage pipeline, chosen specifically to handle the close-up-to-distant range without forcing one model to do everything.

### 6.1 Stage 1 — Input Normalization & Regime Detection
- Accepts image or text.
- If image: run a lightweight classifier/heuristic (subject-to-frame ratio, estimated GSD/scale cues, EXIF focal length + estimated distance) to bucket the shot into a **framing regime**: **microscopic/cellular**, extreme macro, close-up, mid-distance, or far/landscape.
- **Microscopic/cellular is a distinct modality, not just an extreme of "macro."** A cell image (e.g., from a microscope camera or slide scan) has no EXIF distance/focal-length signal in the same sense, no natural background/habitat context, and needs its own detection path (cell/organelle segmentation rather than object detection in a natural scene). Treat it as a fifth, separately-modeled regime from the outset rather than trying to force it through the same macro pipeline.
- This regime tag determines which downstream detector/classifier variant is used in Stage 2, since a model tuned for cropped macro shots performs poorly on a wide landscape frame — and a microscopy image needs an entirely different detector — (this mirrors why camera-trap pipelines crop to a "snip" before classifying rather than classifying the raw frame).

### 6.2 Stage 2 — Detection & Localization
- Run an object-detector (YOLO-family or similar) tuned per regime to find and crop the organism(s) of interest out of the frame.
- For extreme macro/close-up images where the subject already fills the frame, this stage may pass through with minimal cropping.
- For far/landscape images, this stage does the heavy lifting: small-object detection tuned for low pixel-coverage subjects, similar to approaches used for aquatic/riparian invasive detection at a distance.
- Output: one or more cropped, normalized sub-images, each representing a single candidate organism.

### 6.3 Stage 3 — Species Classification
- Each cropped sub-image goes through a fine-grained species classifier (CNN/vision-transformer backbone), pretrained on large public species datasets (iNaturalist-style corpora, GBIF imagery) and fine-tuned on region-specific and framing-regime-specific data.
- **Known gap to solve explicitly in training data collection:** public datasets skew heavily toward clean, close-up photography. A dedicated data augmentation and/or targeted collection effort is required for the mid-distance/far-away regime (synthetic scale/blur augmentation of macro images, plus sourcing real distant-shot imagery, e.g. from drone/UAV invasive-mapping datasets) to avoid the model silently failing on exactly the hard case this product exists to solve.
- Output: ranked list of candidate species with confidence scores; falls back to genus/family-level label if no species-level candidate clears a confidence floor.
- **Text-fallback path:** when only a description is available, route through a language-model-based matcher against species descriptions/taxonomic keys instead of the image classifier; expect materially wider uncertainty and communicate that in the output.

### 6.4 Stage 4 — Status Resolution
- Take the (species, confidence) output from Stage 3 plus resolved geolocation/region.
- Query an invasive/native status database (built from authoritative sources — national/state invasive species councils, GBIF-linked status flags, USDA/APHIS-style lists, and regional equivalents outside the US) keyed by species + jurisdiction.
- Combine species-ID confidence and status-lookup certainty into a single calibrated final certainty percentage, and **always surface the top label at that certainty** rather than gating behind a threshold — e.g. "Invasive — 72% certainty" or "Native — 38% certainty" are both valid, complete outputs. The certainty number is the mechanism for honesty, not a hidden gate.
- Return final structured result with evidence trail (what species were considered, what status source and database version was used, and what pulled certainty down — e.g. poor geolocation, ambiguous framing regime, or a low-confidence species match).

### 6.5 Why not one end-to-end model?
A single model trained to go straight from "any image" to "invasive/native" would need to implicitly learn detection, framing-regime handling, fine-grained species ID, *and* region-conditional status lookup all at once — status in particular is not a visual property of the organism, so it can't be learned from pixels alone regardless of model size. The staged approach lets each component be improved, audited, and re-trained independently, and matches the pattern used by the most successful existing systems in this space (detect → crop → classify → cross-reference).

---

## 7. Data Strategy

| Need | Source |
|---|---|
| Close-up/macro labeled species images | iNaturalist research-grade exports, GBIF imagery, existing Kaggle invasive-species sets |
| Distant/landscape-scale labeled imagery | UAV/drone invasive-mapping datasets, targeted new collection (this is the biggest gap — plan for active data collection, not just public sets) |
| Microscopic/cellular imagery | Public microbiology/parasitology image sets (e.g., cell/pathogen microscopy datasets used in bio research and diagnostics), plus any slide-scanner captures Harrison can generate directly — this category has essentially no overlap with the other regimes' data sources and needs its own sourcing effort |
| Aquatic species imagery | iNaturalist aquatic observations, GBIF marine/freshwater occurrence data, underwater-survey datasets used in prior invasive-aquatic detection work (e.g., HydroSpot-YOLO-style surveillance footage) |
| Invasive/native status ground truth — **Orange County / California specific** | California Invasive Species Council / Cal-IPC plant list, California Department of Fish and Wildlife, GBIF status flags filtered to the region, county agricultural commissioner resources |
| Region/geolocation mapping | EXIF GPS, reverse-geocoding, GBIF occurrence-range data — v1 only needs to resolve "is this in Orange County" plus a coarse fallback |
| Text-description fallback training data | Field-guide descriptions, taxonomic key text, paired with existing image-labeled species for cross-modal training |

**Data risks to track:** long-tailed class distribution (a handful of species dominate observation counts, most have very few labeled examples — matches what's been observed in camera-trap datasets); geographic bias in public datasets (heavily skewed toward North America/Europe); label drift (a species' invasive status can change as it spreads or as local policy changes, so the status database needs a refresh cadence, not a one-time load).

---

## 8. Success Metrics

- **Species ID top-1 accuracy**, tracked *separately per framing regime* (macro / close-up / mid / far) — a single blended accuracy number would hide the exact failure mode this product needs to avoid.
- **Status classification accuracy** (given correct species ID) — measures the status database/lookup layer independent of vision accuracy.
- **End-to-end accuracy** (image in → correct final label out), the metric users actually experience.
- **Calibration**: does the "uncertain" bucket actually correlate with cases that would be wrong if forced to guess? (Expected calibration error.)
- **Coverage**: % of real-world submitted images that fall into a framing regime the system handles well vs. degrade on.
- **Latency** (p50/p95) per regime.
- **False-invasive rate** and **false-native rate**, tracked separately — these have asymmetric real-world costs (see Section 9).

---

## 9. Risks & Guardrails

- **Asymmetric error cost, now that every call gets an answer:** A false "native" on an actual invasive species delays removal action and lets it spread; a false "invasive" on an actual native species can trigger unnecessary/harmful removal of a protected or ecologically important species. Because v1 always commits to a top label rather than deflecting to "needs review," **the certainty percentage is doing all the safety work that a refusal gate would otherwise do** — it must be well-calibrated (a 50% certainty result should be right about half the time, not routinely wrong), or a confidently-displayed low number becomes misleading. Calibration testing (Section 8) is therefore higher-stakes under this design than it would be with a hard uncertainty gate.
- **No human-in-the-loop by design, but high-stakes actions need a check:** the PRD's "no human interaction" requirement is about the *classification* step, not necessarily about what happens next. Recommend the product surface a clear distinction between "informational classification" (fully automated, fine) and "actionable recommendation" (e.g., "report for removal") — the latter should be flagged as decision support, not an autonomous action-trigger, especially for legally protected or regulated species.
- **Regional/legal drift:** "invasive" is a jurisdiction-specific, policy-defined status, not a fixed biological fact — the status database needs an explicit versioning and update process, and outputs should be timestamped against the status-database version used.
- **Distant-image accuracy ceiling:** be upfront in the product (and internally) that far-away/macro-landscape classification will likely have a materially higher uncertain/error rate than close-up classification, at least in v1, given the data gap described in Section 6.3 and 7. Don't let the UI imply uniform confidence across regimes.
- **Text-only fallback is inherently lower-confidence** — should never be presented with the same confidence framing as an image-based result.

---

## 10. Scope Decisions (resolved)

1. **Geography:** Orange County, CA for v1. Architecture designed to scale later (regional data + status-database swap-in), but v1 effort, targets, and data collection are Orange-County-scoped only.
2. **Organism categories:** broad — plants, insects, fungi, aquatic species, vertebrates, *and* cellular/microscopic imagery. Cellular imagery is treated as its own framing regime with its own detection/classification path (Section 6.1, 6.3) and its own data sourcing plan (Section 7), since it shares almost nothing with natural-scene photography.
3. **Interface:** no pre-existing app to integrate with. Decided: a simple single-page web app (photo upload/capture + optional text description) as the fastest path to something usable, given this is a passion project — see Section 5.0.
4. **Certainty framing:** the system always returns its best-guess label paired with a projected certainty percentage rather than withholding behind an "uncertain" gate. This shifts the safety/honesty burden onto calibration quality (Section 9) rather than a refusal threshold.
5. **Batch vs. real-time:** both are acceptable end states; build whichever is easier to stand up first. In practice, single-image/interactive is very likely the faster path to a working demo (no batch orchestration, no queueing), so it's the default build order in Section 11 — but this isn't a hard requirement, and if batch turns out easier given tooling on hand, that's a fine place to start instead.

---

## 11. Milestones (Proposed)

| Phase | Scope |
|---|---|
| **M0 — Interface skeleton** | Single-page web app: photo upload/capture + text-description fallback field, no ML yet — just gets input flowing and something to point a browser at. |
| **M1 — Species ID core (Orange County plants + vertebrates, close-up only)** | Detection + classification pipeline on close-up/macro imagery, using public datasets, scoped to plants and vertebrates first (best public data coverage). No status layer yet. |
| **M2 — Status resolution** | Add Orange County / California status-database lookup (Cal-IPC, CDFW); produce first end-to-end Native/Invasive output *with certainty percentage* for close-up imagery. |
| **M3 — Organism-category expansion** | Extend species ID to insects, fungi, and aquatic species within Orange County. |
| **M4 — Framing-regime expansion** | Extend to mid-distance and far/landscape imagery; targeted data collection for the distance gap; per-regime certainty-calibration tracking live. |
| **M5 — Cellular/microscopic regime** | Add the separate microscopy detection + classification path and its own data pipeline — deliberately sequenced last since it's the most self-contained, least-overlapping-with-everything-else category. |
| **M6 — Text-fallback path** | Add description-only input path with appropriately downgraded certainty framing. |
| **M7 — Hardening** | Calibration tuning (critical given the always-answer design), status-database versioning/update pipeline, multi-organism-per-image support, batch-mode support if not already covered by M0's interface choice. |

---

*v1.1: incorporates Harrison's scope decisions — Orange County first, full organism breadth including cellular imagery, simple web-app interface, always-answer-with-certainty output design, and either build order for batch vs. real-time.*

---

## 12. Addendum v1.2 (2026-09-16) — Area viewer

A second surface was added alongside the classifier: a satellite map of the local area
where biodiversity-pressure layers (introduced, native and threatened species sightings,
listed invasives, tree-cover loss, sighting trends) can be toggled, filtered and inspected.
It answers the inverse of the classifier's question: not "what is this organism, here?"
but "what is going on in this place?". Full requirements (FR-A1 to FR-A10), data sources,
caveats and decisions are in [docs/AREA-VIEWER.md](docs/AREA-VIEWER.md). The status seed
list introduced for it is the first piece of the M2 status database (§6.4).

Milestone status as of 2026-09-16: M0 done; M1 (species ID) done via a pluggable
model backend rather than a fine-tuned classifier, see [docs/CLASSIFIER.md](docs/CLASSIFIER.md);
M2 (status resolution) done for Orange County using iNaturalist establishment means
plus a seed list of listed invasives; M6 (text fallback) done through the same model
backend with the §9 confidence downgrade.

Update 2026-09-17: Stage 2 (§6.2) done in a first form, using the vision model as
its own detector (subject box, crop, re-identify, keep the more confident pass); the
regime tag now also feeds the certainty (§9); region resolution uses the county
polygon (§7); the status seed carries iNaturalist-accepted names plus synonyms and
answers offline. Not done: M3 category expansion (the model backend is
category-agnostic, but nothing has been measured per category), the M4 dedicated
small-object detector and distance data collection, M5 microscopy, M7 calibration,
multi-organism results (FR-9) and batch mode.

The project is being submitted to NextStep Hacks 2026 (theme "Earth Forward");
see [docs/HACKATHON.md](docs/HACKATHON.md).
