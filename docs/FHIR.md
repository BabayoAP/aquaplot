# FHIR R4 export

`GET /api/assess/{id}/fhir` returns one assessment as a FHIR R4 collection Bundle.
`GET /api/fhir/CodeSystem/stream-health` returns the CodeSystem every project code belongs to.

`GET /api/assess/{id}/oah-app` returns the same check as a OneAquaHealth Citizen Science App submission.

**Validated, against the project's own profiles.** The example bundles in
[`fhir/examples/`](fhir/examples/) and the CodeSystem in
[`fhir/CodeSystem-stream-health.json`](fhir/CodeSystem-stream-health.json) pass the official HL7
FHIR validator (R4 4.0.1, terminology checked against tx.fhir.org) **with the OneAquaHealth IG
loaded**, with **no errors and no warnings**. The only notes are informational: component codes
that come from AquaPlot's CodeSystem where the IG's value set, bound as *preferred*, has no
family-level or answer-level concept. See [Validating it yourself](#validating-it-yourself).

## Why an ecosystem reading belongs in FHIR at all

The One Health argument only pays off if a stream reading can reach the systems that hold
health data. Today it cannot: stream monitoring lives in environmental-agency spreadsheets and
health surveillance lives in HL7, and the two never meet. That is the fragmentation this
hackathon's Track 7 names, and it is a mapping problem, not a research problem.

FHIR fits without bending the specification, because `Observation.subject` and
`Flag.subject` both admit a **Location**. A monitoring point is a Location; a stream assessment
is an Observation about it; an instruction to keep out of the water is a Flag on it.

## Conforming to the OneAquaHealth IG

The OneAquaHealth project publishes its own FHIR Implementation Guide,
[`hl7-eu/oah`](https://github.com/hl7-eu/oah) (canonical `http://hl7.eu/fhir/ig/oah`, 0.1.0,
draft). AquaPlot's bundles use it where it applies:

- **`Location` conforms to `location-oah`.** It carries the required identifier (AquaPlot's site
  key) and `mode = instance`. (The IG's examples also give a SNOMED CT *River* type; that draws a
  warning against base FHIR's extensible binding for `Location.type`, and the profile does not
  require a type, so it is left out.) When the check
  was made within 200 m of one of the project's 106 research sites, a second identifier gives
  the project's own site code (`https://oneaquahealth.eu/location-id`, e.g. `C3`), which is
  what lets a receiver join a citizen reading to the laboratory data filed under that site.
- **One `observation-indicators-oah` Observation per IG indicator the check has evidence for**,
  coded from the IG's CodeSystem (`temporarySystem-oah-eu`):

  | IG code | From |
  |---|---|
  | `macroinvertebreates` | the families in the tray (value: family count; one component per family, `present`) |
  | `diptera` | fly larvae among them: Culicidae, Psychodidae, Chironomidae… |
  | `foam` (Foam/colour/smell) | colour, foam or sheen, and smell; `present` if any was other than natural |
  | `riparianVegetation` | bank vegetation, and shade |
  | `morophology` | banks, bed and sludge |
  | `hydrology` | flow |
  | `filamentous-algae` | algae, mapped to the IG's `absent` / `present` / `extensive` |
  | `invasiveOrganisms` | a listed invasive species the citizen identified |

  The IG's codes are used verbatim, spelling included (`macroinvertebreates`, `morophology`):
  a code is an identifier, not prose.

**Only what a person stands behind becomes an OAH indicator.** The profile fixes `status` to
`final`. A habitat answer only the vision model gave, or an animal nobody confirmed, is not a
final observation by anyone, so it is left out of the OAH Observations and stays in AquaPlot's
own panel, which is `preliminary` until a person confirms something. The same rule governs the
[OneAquaHealth app export](#the-oneaquahealth-citizen-science-app).

The WFD band, the biotic index, the certainty, the second opinion and the One Health findings
have no code in the IG, so they stay in AquaPlot's own resources (below), unprofiled.

## The OneAquaHealth Citizen Science App

`GET /api/assess/{id}/oah-app` returns the check as the body the project's app submits
(`CitizenSubmissionPutDTO`, `PUT /api/citizens/submit` on `api.enora-oah.eu`), using the app's
published answer codes (`FAS`/`NOR`/`STA`/`DRY` for flow, `CL`/`MU`/`FO`/`CO` for water colour,
and so on). The codes and the research sites are a snapshot of the project's public API in
`src/aquaplot/data/oah_reference.json`, refreshed by `scripts/fetch_oah_reference.py`; the app
never calls the API at run time.

Every carried field names the AquaPlot answer it came from, and everything that did not translate
is listed with its reason: a "partly reinforced" bank that the app would split into concrete or
laid stones, answers only the model gave, photos (the app takes uploaded file ids), and the
questions AquaPlot does not ask (dams, pipes, how the place made you feel). AquaPlot prepares the
body; submitting needs an app account. Example:
[`oah/app-submission-iberia-after-review.json`](oah/app-submission-iberia-after-review.json).

## The Bundle

| Resource | Id | What it carries |
|---|---|---|
| `Location` | `site-{id}` | Profile `location-oah`. Name, identifiers (AquaPlot site key; OneAquaHealth site code when at a research site), coordinates, the municipality and country resolved from them |
| `Observation` ×0–8 | `oah-{indicator}-{id}` | Profile `observation-indicators-oah`, `status = final`. One per IG indicator the person gave evidence for (see above). |
| `Observation` | `status-{id}` | The panel. `valueCodeableConcept` is the WFD band; `method` names the index (BMWP/ASPT, or IBMWP/IASPT in Iberia). Components carry the index total and mean, scoring families, EPT families, the habitat pressure index, the assessment certainty, the band as an ordinal 5–1, the number of human-confirmed observations, **who identified the animals** (`identified-by-citizen` / `-model` / `-none`) and, when the model gave a second opinion, **what it found**: independent agreements, answers the citizen adopted from it, answers the citizen kept, and disagreements still open. For IBMWP, the index's own class from the total is included and labelled as understating a single tray. `note` carries the screening caveat, the second-opinion summary and every limitation. `status` is `preliminary` until a human has confirmed something, then `amended`. |
| `Observation` | `survey-{id}` | The raw biological evidence: one component per family with the score it contributed; a family the index does not score is present with `dataAbsentReason = not-applicable`. `note` carries the plain-language signals. |
| `Observation` | `habitat-{id}` | The field form, answer by answer; each answer's `text` says *who* gave it: the model or the citizen. |
| `Observation` ×3 | `onehealth-{domain}-{id}` | One per domain. `valueCodeableConcept` is the level; `interpretation` maps it to HL7 v3 ObservationInterpretation (`N`, `A`, `H`, `HH`); components carry each finding's evidence; `note` carries each finding's action. |
| `Flag` | `flag-{rule}-{id}` | One per finding at alert level. This is the resource a receiving system can surface to a clinician or a public-health officer without parsing anything else. Category `safety` plus the One Health domain. |
| `Provenance` | `prov-{id}` | Who and what produced it: the citizen as author, AquaPlot and its model backend as assembler, the bioindicator catalogue and index, the habitat form version, iNaturalist. |

Every entry's `fullUrl` is a `urn:uuid` derived deterministically from the assessment, and every
reference inside the bundle points at one, so the graph resolves without a server and
re-exporting the same assessment yields the same identifiers. No custom extensions are used:
everything AquaPlot-specific is a coded component. Empty elements are pruned, since FHIR forbids
them. Every resource carries a generated narrative.

## About the codes

**There is no LOINC code for "BMWP score".** Inventing one that looks real would be the worst
possible thing to do in a standards track, so:

- Every AquaPlot-specific code comes from one project CodeSystem,
  `https://github.com/BabayoAP/aquaplot/fhir/CodeSystem/stream-health` (`status: draft`,
  `experimental: true`). It is **generated from the same vocabularies the app runs on** (the
  bioindicator catalogue, the habitat form, the One Health rules, both indices), so it cannot
  drift from what the exporter emits, and a test asserts every code in a bundle is defined in it.
  Each coding's `display` is the CodeSystem's; the wording for a particular case ("Biological
  condition: Poor") goes in `text`.
- Where a genuine standard applies, it is used unchanged: `observation-category`,
  `v3-ObservationInterpretation`, `flag-category`, `location-physical-type`,
  `provenance-participant-type`, `data-absent-reason`, and UCUM for units.
- A test asserts the string `loinc` never appears in a generated bundle.

## What would make this standard

1. **Map the CodeSystem.** The band maps to an ordinal concept; the pressure and certainty
   indices are percentages; BMWP, ASPT and EPT richness need either LOINC submissions or a
   binding to an environmental terminology. This is a terminology exercise with a known shape,
   not a redesign.
2. **Propose codes to the OneAquaHealth IG** for what it does not yet cover: the ecological status
   class, BMWP/IBMWP and ASPT, and family-level macroinvertebrate concepts (its CodeSystem notes
   that specialised macroinvertebrate concepts are still to be added). AquaPlot's status panel
   could then carry `observation-indicators-oah` too.
3. **Decide the subject convention with a receiving system.** Location-as-subject is valid R4
   and reads naturally, but an environmental-health programme may prefer a `Group` for a
   catchment. Both are one field.
4. **Agree the Flag lifecycle.** AquaPlot emits `active` flags with a start period. Who clears
   them, and on what evidence, is an operational decision that belongs with the authority
   receiving them. The natural answer is a later assessment at the same site.

## Trying it

```sh
curl -s localhost:8000/api/assess/<id>/fhir | jq '.entry[].resource.resourceType'
```

## Validating it yourself

Download `validator_cli.jar` from the
[HL7 FHIR core releases](https://github.com/hapifhir/org.hl7.fhir.core/releases) (Java 11+).
The OneAquaHealth IG is not yet on the FHIR package registry, so first build its conformance
resources from source with [SUSHI](https://fshschool.org) (Node 18+), then run the validator:

```sh
git clone --depth 1 https://github.com/hl7-eu/oah && (cd oah && npx fsh-sushi build .)
mkdir oah-conf && cp oah/fsh-generated/resources/{StructureDefinition,CodeSystem,ValueSet}-*.json oah-conf/

.venv/bin/python scripts/export_fhir_examples.py     # regenerates docs/fhir/ and docs/oah/ through the real pipeline
java -jar validator_cli.jar docs/fhir/examples/*.json docs/fhir/CodeSystem-stream-health.json \
    -version 4.0.1 -ig docs/fhir/CodeSystem-stream-health.json -ig oah-conf
```

Loading the CodeSystem with `-ig` lets the validator check every project code and display
rather than skip them; loading `oah-conf` makes it validate each resource that declares
`meta.profile` against the IG's profile, and check every IG code and display. The three examples
cover an Iberian check at OneAquaHealth research site C3 identified by the citizen with an open
disagreement, the same check after the citizen settled it, and a hand-filled Belgian check with
no model and a health alert.

An earlier version of this exporter did not pass: entry `fullUrl`s were not valid UUIDs, the
Provenance used extensions with no published definition, and a check with no findings produced
empty arrays. Running the validator found them.
