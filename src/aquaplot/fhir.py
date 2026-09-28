"""Export an assessment as a FHIR R4 Bundle (FR-9, Track 7: digital health standards).

The One Health argument only pays off if an ecosystem reading can reach the
systems that already hold health data. Today it cannot: stream monitoring lives in
environmental agency spreadsheets and health surveillance lives in HL7, and the
two never meet, which is exactly the fragmentation this hackathon's Track 7 names.

FHIR R4 turns out to fit an environmental observation with no abuse of the spec,
because ``Observation.subject`` and ``Flag.subject`` both admit a **Location**.
So a AquaPlot assessment becomes:

* one ``Location`` with the site's coordinates and municipality,
* one ``Observation`` panel for the ecological status, carrying BMWP, ASPT, EPT
  richness, the habitat pressure score and the WFD band as components,
* one ``Observation`` for the macroinvertebrate survey, one component per family
  with its sensitivity score, so the raw evidence travels with the conclusion,
* one ``Observation`` per One Health domain, whose ``interpretation`` is the
  level the rule engine reached,
* one ``Flag`` per finding at alert level - the resource a receiving system can
  surface to a clinician or a public-health officer without parsing anything else,
* one ``Provenance`` recording which model observed, which catalogue versions were
  used and how many observations a human confirmed.

**About the codes.** There is no LOINC code for "BMWP score". Inventing one that
looks real would be the worst possible thing to do in a standards track, so every
code here comes from a project CodeSystem at ``CODE_SYSTEM``, is marked as
provisional in ``docs/FHIR.md``, and sits in a standard ``category`` (``survey``)
with standard structure around it. Where a genuine standard code exists - UCUM for
units, observation-category, observation-interpretation, flag-category - it is
used. Mapping this CodeSystem to LOINC or to an environmental terminology is the
next step, and it is a mapping exercise, not a redesign.
"""

from __future__ import annotations

import re
from typing import Any

from .assess import Assessment
from .bioindex import Band
from .onehealth import Domain, Level

CODE_SYSTEM = "https://github.com/BabayoAP/aquaplot/fhir/CodeSystem/stream-health"
PROFILE = "https://github.com/BabayoAP/aquaplot/fhir/StructureDefinition/stream-assessment"

# HL7 terminology, used unchanged where it applies.
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
INTERPRETATION = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"
FLAG_CATEGORY = "http://terminology.hl7.org/CodeSystem/flag-category"
UCUM = "http://unitsofmeasure.org"

# The rule engine's levels, mapped to HL7 v3 ObservationInterpretation. "N" normal,
# "A" abnormal, "H"/"HH" for the two escalating levels: the nearest honest fit in a
# value set built for laboratory results.
LEVEL_INTERPRETATION: dict[Level, tuple[str, str]] = {
    Level.OK: ("N", "Normal"),
    Level.WATCH: ("A", "Abnormal"),
    Level.CONCERN: ("H", "High"),
    Level.ALERT: ("HH", "Critical high"),
}

BAND_ORDINAL: dict[Band, int] = {Band.HIGH: 5, Band.GOOD: 4, Band.MODERATE: 3, Band.POOR: 2, Band.BAD: 1}


def _id(*parts: str) -> str:
    """A FHIR resource id: [A-Za-z0-9-.] only, 64 characters at most."""
    joined = "-".join(str(p) for p in parts if p)
    return re.sub(r"[^A-Za-z0-9.-]", "-", joined)[:64]


def _code(code: str, display: str) -> dict[str, Any]:
    return {"coding": [{"system": CODE_SYSTEM, "code": code, "display": display}], "text": display}


def _quantity(value: float, unit: str, ucum: str | None = None) -> dict[str, Any]:
    q: dict[str, Any] = {"value": value, "unit": unit}
    if ucum:
        q.update(system=UCUM, code=ucum)
    return q


def _component(code: str, display: str, **value: Any) -> dict[str, Any]:
    return {"code": _code(code, display), **value}


def location_resource(a: Assessment) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "resourceType": "Location",
        "id": _id("site", a.id),
        "status": "active",
        "name": a.site_name or "Unnamed stream site",
        "description": "Urban freshwater monitoring point recorded by a citizen scientist",
        "mode": "instance",
        "physicalType": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/location-physical-type", "code": "area", "display": "Area"}]
        },
    }
    if a.region.lat is not None and a.region.lon is not None:
        resource["position"] = {"latitude": a.region.lat, "longitude": a.region.lon}
    if a.region.place is not None:
        resource["address"] = {"text": a.region.place.display_name}
        if a.region.country is not None:
            resource["address"]["country"] = a.region.country.name
    return resource


def status_observation(a: Assessment) -> dict[str, Any]:
    """The headline panel: the band, and every number behind it as a component."""
    eco, pressure = a.ecology, a.pressures
    components = [
        _component(
            "wfd-ecological-status",
            "Ecological status class (Water Framework Directive scale)",
            valueCodeableConcept=_code(f"wfd-{eco.band.value.lower()}", eco.band.value),
        ),
        _component(
            "wfd-ecological-status-ordinal",
            "Ecological status as an ordinal, 5 high to 1 bad",
            valueInteger=BAND_ORDINAL[eco.band],
        ),
        _component(
            f"{eco.index.key}-total", f"{eco.index.total} total score", valueQuantity=_quantity(round(eco.bmwp, 1), "score")
        ),
        _component("scoring-families", "Number of scoring macroinvertebrate families", valueInteger=eco.families),
        _component("ept-families", "Number of EPT (mayfly, stonefly, caddisfly) families", valueInteger=eco.ept_families),
        _component(
            "habitat-pressure",
            "Visual habitat pressure index, 0 none to 100 severe",
            valueQuantity=_quantity(round(pressure.pressure, 1), "%", "%"),
        ),
        _component(
            "assessment-certainty",
            "Certainty of this assessment, as evidenced",
            valueQuantity=_quantity(round(a.certainty, 1), "%", "%"),
        ),
    ]
    if eco.aspt is not None:
        components.insert(
            3,
            _component(
                eco.index.mean.lower(),
                f"Average Score Per Taxon ({eco.index.total}/families)",
                valueQuantity=_quantity(round(eco.aspt, 2), "score"),
            ),
        )
    if eco.total_class is not None:
        components.append(
            _component(
                f"{eco.index.key}-total-class",
                f"{eco.index.total} class from the total (assumes a standardised sample; understates a single tray)",
                valueCodeableConcept=_code(f"wfd-{eco.total_class.value.lower()}", eco.total_class.value),
            )
        )

    notes = [{"text": eco.caveat}, {"text": eco.meaning}]
    if eco.evidence_limited:
        notes.append({"text": "Evidence-limited: too few taxa were found to support a better class."})
    if a.penalties:
        notes.append({"text": "Limitations: " + "; ".join(a.penalties)})

    return {
        "resourceType": "Observation",
        "id": _id("status", a.id),
        "meta": {"profile": [PROFILE]},
        "status": "preliminary" if a.confirmations == 0 else "amended",
        "category": [{"coding": [{"system": OBS_CATEGORY, "code": "survey", "display": "Survey"}]}],
        "code": _code("stream-ecological-status", "Urban stream ecological status, citizen screening"),
        "subject": {"reference": f"Location/site-{a.id}"},
        "effectiveDateTime": a.created_at,
        "method": _code(
            f"{eco.index.key}-photo-screening", f"{eco.index.name} family-level screening from citizen photographs"
        ),
        "valueCodeableConcept": _code(f"wfd-{a.ecology.band.value.lower()}", a.ecology.band.value),
        "component": components,
        "note": notes,
    }


def survey_observation(a: Assessment) -> dict[str, Any]:
    """The raw biological evidence: every family found, with the score it contributed."""
    return {
        "resourceType": "Observation",
        "id": _id("survey", a.id),
        "status": "final",
        "category": [{"coding": [{"system": OBS_CATEGORY, "code": "survey", "display": "Survey"}]}],
        "code": _code("benthic-macroinvertebrate-survey", "Benthic macroinvertebrate survey"),
        "subject": {"reference": f"Location/site-{a.id}"},
        "effectiveDateTime": a.created_at,
        "derivedFrom": [{"reference": f"Observation/status-{a.id}"}],
        "component": [
            _component(
                _id("taxon", (t.family or t.group or t.name).lower()),
                f"{t.family or t.group} ({t.plain_name})",
                valueQuantity=_quantity(t.score, f"{a.ecology.index.total} sensitivity score"),
                interpretation=[{"text": t.sensitivity}],
            )
            for t in a.ecology.scored
        ]
        + [
            _component(
                _id("taxon", (t.family or t.group or t.name).lower()),
                f"{t.family or t.group} ({t.plain_name})",
                dataAbsentReason={
                    "coding": [{"system": "http://terminology.hl7.org/CodeSystem/data-absent-reason", "code": "not-applicable"}],
                    "text": f"Recorded; not scored by {a.ecology.index.total}",
                },
            )
            for t in a.ecology.recorded
        ],
        "note": [{"text": s} for s in a.ecology.signals],
    }


def pressure_observation(a: Assessment) -> dict[str, Any]:
    """The visual field form, answer by answer, with who answered each one."""
    return {
        "resourceType": "Observation",
        "id": _id("habitat", a.id),
        "status": "final",
        "category": [{"coding": [{"system": OBS_CATEGORY, "code": "survey", "display": "Survey"}]}],
        "code": _code("stream-habitat-assessment", "Visual stream habitat and pressure assessment"),
        "subject": {"reference": f"Location/site-{a.id}"},
        "effectiveDateTime": a.created_at,
        "derivedFrom": [{"reference": f"Observation/status-{a.id}"}],
        "component": [
            _component(
                _id("habitat", row.key.replace("_", "-")),
                row.question,
                valueCodeableConcept=_code(_id(row.key.replace("_", "-"), row.value.replace("_", "-")), row.label),
                interpretation=[{"text": f"reported by {row.source}"}],
            )
            for row in (*a.pressures.readings, *a.pressures.exposure)
        ],
    }


def domain_observations(a: Assessment) -> list[dict[str, Any]]:
    """One Observation per One Health domain, carrying the rule engine's level."""
    out = []
    for domain in Domain:
        level = a.signal.levels[domain]
        code, display = LEVEL_INTERPRETATION[level]
        findings = [f for f in a.signal.findings if f.domain is domain]
        out.append(
            {
                "resourceType": "Observation",
                "id": _id("onehealth", domain.value, a.id),
                "status": "final",
                "category": [
                    {"coding": [{"system": OBS_CATEGORY, "code": "exam", "display": "Exam"}]},
                    {"coding": [{"system": CODE_SYSTEM, "code": "one-health", "display": "One Health assessment"}]},
                ],
                "code": _code(f"one-health-{domain.value}", f"One Health signal: {domain.value} health"),
                "subject": {"reference": f"Location/site-{a.id}"},
                "effectiveDateTime": a.created_at,
                "derivedFrom": [{"reference": f"Observation/status-{a.id}"}],
                "valueCodeableConcept": _code(f"level-{level.value}", level.value),
                "interpretation": [{"coding": [{"system": INTERPRETATION, "code": code, "display": display}]}],
                "component": [
                    _component(
                        _id("finding", f.rule.replace(".", "-")),
                        f.title,
                        valueString="; ".join(f.because),
                        interpretation=[{"text": f.level.value}],
                    )
                    for f in findings
                ],
                "note": [{"text": f"{f.title}: {f.action}"} for f in findings],
            }
        )
    return out


def flags(a: Assessment) -> list[dict[str, Any]]:
    """A Flag per alert-level finding: the thing a receiving system can act on directly."""
    return [
        {
            "resourceType": "Flag",
            "id": _id("flag", f.rule.replace(".", "-"), a.id),
            "status": "active",
            "category": [
                {"coding": [{"system": FLAG_CATEGORY, "code": "safety", "display": "Safety"}]},
                {"coding": [{"system": CODE_SYSTEM, "code": f"one-health-{f.domain.value}", "display": f"{f.domain.value} health"}]},
            ],
            "code": {
                "coding": [{"system": CODE_SYSTEM, "code": _id(f.rule.replace(".", "-")), "display": f.title}],
                "text": f"{f.title}. {f.action}",
            },
            "subject": {"reference": f"Location/site-{a.id}"},
            "period": {"start": a.created_at},
        }
        for f in a.signal.findings
        if f.level is Level.ALERT
    ]


def provenance(a: Assessment) -> dict[str, Any]:
    """Who and what produced this, including how much of it a human confirmed."""
    return {
        "resourceType": "Provenance",
        "id": _id("prov", a.id),
        "target": [{"reference": f"Observation/status-{a.id}"}],
        "recorded": a.created_at,
        "agent": [
            {
                "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type", "code": "author"}]},
                "who": {"display": "Citizen scientist"},
            },
            {
                "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type", "code": "assembler"}]},
                "who": {"display": f"AquaPlot {a.version} (vision model: {a.observer})"},
            },
        ],
        "entity": [
            {"role": "source", "what": {"display": f"Bioindicator catalogue {a.ecology.catalogue_version}"}},
            {"role": "source", "what": {"display": f"Habitat form {a.pressures.form_version}"}},
            {"role": "source", "what": {"display": "iNaturalist API (taxonomy, establishment means, administrative places)"}},
        ],
        "extension": [
            {"url": f"{CODE_SYSTEM}/human-confirmations", "valueInteger": a.confirmations},
            {"url": f"{CODE_SYSTEM}/assessment-certainty-percent", "valueDecimal": round(a.certainty, 1)},
            {"url": f"{CODE_SYSTEM}/taxa-identified-by", "valueCode": a.identified_by},
            *(
                [
                    {
                        "url": f"{CODE_SYSTEM}/model-second-opinion",
                        "extension": [
                            {"url": "independentAgreements", "valueInteger": len(s.agreed) - len(s.adopted)},
                            {"url": "adopted", "valueInteger": len(s.adopted)},
                            {"url": "keptOwn", "valueInteger": len(s.dismissed)},
                            {"url": "unresolved", "valueInteger": len(s.open)},
                        ],
                    }
                ]
                if (s := a.second_opinion) is not None and s.available
                else []
            ),
        ],
    }


def bundle(a: Assessment) -> dict[str, Any]:
    """The whole assessment as one FHIR R4 collection Bundle."""
    resources: list[dict[str, Any]] = [
        location_resource(a),
        status_observation(a),
        survey_observation(a),
        pressure_observation(a),
        *domain_observations(a),
        *flags(a),
        provenance(a),
    ]
    return {
        "resourceType": "Bundle",
        "id": _id("aquaplot", a.id),
        "type": "collection",
        "timestamp": a.created_at,
        "entry": [{"fullUrl": f"urn:uuid:{r['resourceType'].lower()}-{r['id']}", "resource": r} for r in resources],
    }
