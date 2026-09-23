# FHIR R4 export

`GET /api/assess/{id}/fhir` returns one assessment as a FHIR R4 collection Bundle.

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
| `Observation` | `status-{id}` | The panel. `valueCodeableConcept` is the WFD band; components carry BMWP, ASPT, scoring families, EPT families, the habitat pressure index, the assessment certainty, and the band as an ordinal 5–1. `note` carries the screening caveat and every limitation. `status` is `preliminary` until a human has confirmed something, then `amended`. |
| `Observation` | `survey-{id}` | The raw biological evidence: one component per family with the sensitivity score it contributed and its interpretation (`sensitive` / `moderate` / `tolerant`). `note` carries the plain-language signals. |
| `Observation` | `habitat-{id}` | The field form, answer by answer, each interpreted with *who* answered it — `reported by model` or `reported by citizen`. |
| `Observation` ×3 | `onehealth-{domain}-{id}` | One per domain. `valueCodeableConcept` is the level; `interpretation` maps it to HL7 v3 ObservationInterpretation (`N`, `A`, `H`, `HH`); components carry each finding's evidence; `note` carries each finding's action. |
| `Flag` | `flag-{rule}-{id}` | One per finding at alert level — the resource a receiving system can surface to a clinician or a public-health officer without parsing anything else. Category `safety` plus the One Health domain. |
| `Provenance` | `prov-{id}` | Who and what produced it: the citizen, AquaPlot and its model backend, the bioindicator catalogue version, the habitat form version, iNaturalist. Extensions record the number of human confirmations and the assessment certainty. |

## About the codes

**There is no LOINC code for "BMWP score".** Inventing one that looks real would be the worst
possible thing to do in a standards track, so:

- Every AquaPlot-specific code comes from one project CodeSystem,
  `https://github.com/BabayoAP/aquaplot/fhir/CodeSystem/stream-health`, and is marked provisional.
- Where a genuine standard applies, it is used unchanged: `observation-category`,
  `v3-ObservationInterpretation`, `flag-category`, `location-physical-type`,
  `provenance-participant-type`, and UCUM for units.
- A test asserts the string `loinc` never appears in a generated bundle.

## What would make this standard

1. **Map the CodeSystem.** The band maps to an ordinal concept; the pressure and certainty
   indices are percentages; BMWP, ASPT and EPT richness need either LOINC submissions or a
   binding to an environmental terminology. This is a terminology exercise with a known shape,
   not a redesign.
2. **Publish a StructureDefinition** for the status panel. `meta.profile` already points at
   `.../StructureDefinition/stream-assessment`; the profile itself is not yet written.
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

Validate with the HL7 Java validator if you have it; the structure is plain R4 and the only
non-standard element is the CodeSystem URL, which a validator will report as unknown rather
than invalid.
