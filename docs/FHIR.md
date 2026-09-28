# FHIR R4 export

`GET /api/assess/{id}/fhir` returns one assessment as a FHIR R4 collection Bundle.
`GET /api/fhir/CodeSystem/stream-health` returns the CodeSystem every project code belongs to.

**Validated.** The example bundles in [`fhir/examples/`](fhir/examples/) and the CodeSystem in
[`fhir/CodeSystem-stream-health.json`](fhir/CodeSystem-stream-health.json) pass the official HL7
FHIR validator (6.10.4, R4 4.0.1, terminology checked against tx.fhir.org) with **no errors and
no warnings**. See [Validating it yourself](#validating-it-yourself).

## Why an ecosystem reading belongs in FHIR at all

The One Health argument only pays off if a stream reading can reach the systems that hold
health data. Today it cannot: stream monitoring lives in environmental-agency spreadsheets and
health surveillance lives in HL7, and the two never meet. That is the fragmentation this
hackathon's Track 7 names, and it is a mapping problem, not a research problem.

FHIR turns out to fit with no abuse of the specification, because `Observation.subject` and
`Flag.subject` both admit a **Location**. A monitoring point is a Location; a stream assessment
is an Observation about it; an instruction to keep out of the water is a Flag on it.

## The Bundle

| Resource | Id | What it carries |
|---|---|---|
| `Location` | `site-{id}` | Name, coordinates, the municipality and country resolved from them |
| `Observation` | `status-{id}` | The panel. `valueCodeableConcept` is the WFD band; `method` names the index (BMWP/ASPT, or IBMWP/IASPT in Iberia). Components carry the index total and mean, scoring families, EPT families, the habitat pressure index, the assessment certainty, the band as an ordinal 5–1, the number of human-confirmed observations, **who identified the animals** (`identified-by-citizen` / `-model` / `-none`) and, when the model gave a second opinion, **what it found**: independent agreements, answers the citizen adopted from it, answers the citizen kept, and disagreements still open. For IBMWP, the index's own class from the total is included and labelled as understating a single tray. `note` carries the screening caveat, the second-opinion summary and every limitation. `status` is `preliminary` until a human has confirmed something, then `amended`. |
| `Observation` | `survey-{id}` | The raw biological evidence: one component per family with the score it contributed; a family the index does not score is present with `dataAbsentReason = not-applicable`. `note` carries the plain-language signals. |
| `Observation` | `habitat-{id}` | The field form, answer by answer; each answer's `text` says *who* gave it — the model or the citizen. |
| `Observation` ×3 | `onehealth-{domain}-{id}` | One per domain. `valueCodeableConcept` is the level; `interpretation` maps it to HL7 v3 ObservationInterpretation (`N`, `A`, `H`, `HH`); components carry each finding's evidence; `note` carries each finding's action. |
| `Flag` | `flag-{rule}-{id}` | One per finding at alert level — the resource a receiving system can surface to a clinician or a public-health officer without parsing anything else. Category `safety` plus the One Health domain. |
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
  `experimental: true`). It is **generated from the same vocabularies the app runs on** — the
  bioindicator catalogue, the habitat form, the One Health rules, both indices — so it cannot
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
2. **Publish a StructureDefinition** for the status panel, constraining which components are
   required. Bundles carry no `meta.profile` until that profile exists: claiming conformance to
   a profile nobody can fetch is exactly what a validator flags.
3. **Decide the subject convention with a receiving system.** Location-as-subject is valid R4
   and reads naturally, but an environmental-health programme may prefer a `Group` for a
   catchment. Both are one field.
4. **Agree the Flag lifecycle.** AquaPlot emits `active` flags with a start period. Who clears
   them, and on what evidence, is an operational decision that belongs with the authority
   receiving them — the natural answer is a later assessment at the same site.

## Trying it

```sh
curl -s localhost:8000/api/assess/<id>/fhir | jq '.entry[].resource.resourceType'
```

## Validating it yourself

Download `validator_cli.jar` from the
[HL7 FHIR core releases](https://github.com/hapifhir/org.hl7.fhir.core/releases) (Java 11+), then:

```sh
.venv/bin/python scripts/export_fhir_examples.py     # regenerates docs/fhir/ through the real pipeline
java -jar validator_cli.jar docs/fhir/examples/*.json docs/fhir/CodeSystem-stream-health.json \
    -version 4.0.1 -ig docs/fhir/CodeSystem-stream-health.json
```

Loading the CodeSystem with `-ig` lets the validator check every project code and display
rather than skip them. The three examples cover an Iberian check identified by the citizen with
an open disagreement, the same check after the citizen settled it, and a hand-filled Belgian
check with no model and a health alert.

An earlier version of this exporter did not pass: entry `fullUrl`s were not valid UUIDs, the
Provenance used extensions with no published definition, and a check with no findings produced
empty arrays. Running the validator is what found them.
