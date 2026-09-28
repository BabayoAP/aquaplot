"""Export an assessment as a FHIR R4 Bundle (FR-9, Track 7: digital health standards).

The One Health argument only pays off if an ecosystem reading can reach the
systems that already hold health data. Today it cannot: stream monitoring lives in
environmental agency spreadsheets and health surveillance lives in HL7, and the
two never meet, which is exactly the fragmentation this hackathon's Track 7 names.

FHIR R4 turns out to fit an environmental observation with no abuse of the spec,
because ``Observation.subject`` and ``Flag.subject`` both admit a **Location**.
So a AquaPlot assessment becomes:

* one ``Location`` with the site's coordinates and municipality,
* one ``Observation`` panel for the ecological status, carrying the index total and
  mean, EPT richness, the habitat pressure score, the certainty, who identified the
  animals and what the model's second opinion found, and the WFD band,
* one ``Observation`` for the macroinvertebrate survey, one component per family
  with its sensitivity score, so the raw evidence travels with the conclusion,
* one ``Observation`` per One Health domain, whose ``interpretation`` is the
  level the rule engine reached,
* one ``Flag`` per finding at alert level - the resource a receiving system can
  surface to a clinician or a public-health officer without parsing anything else,
* one ``Provenance`` recording who observed, what assembled it and which catalogue
  versions were used.

Entries are addressed by ``urn:uuid`` full URLs derived deterministically from the
assessment, and every reference inside the bundle uses them, so a receiver can
resolve the whole graph without a server. The bundles are checked with the
official HL7 validator (docs/FHIR.md says how).

**About the codes.** There is no LOINC code for "BMWP score". Inventing one that
looks real would be the worst possible thing to do in a standards track, so every
project code lives in one CodeSystem at ``CODE_SYSTEM``, which ``code_system()``
generates from the same vocabularies the app runs on and ``/api/fhir/CodeSystem``
serves. Where a genuine standard code exists - UCUM for units, observation-category,
observation-interpretation, flag-category, data-absent-reason - it is used.
Mapping the CodeSystem to LOINC or an environmental terminology is the next step,
and it is a mapping exercise, not a redesign.
"""

from __future__ import annotations

import html
import inspect
import re
import uuid
from typing import Any

from . import bioindex, habitat, onehealth
from .assess import Assessment
from .bioindex import Band
from .onehealth import Domain, Level

CODE_SYSTEM = "https://github.com/BabayoAP/aquaplot/fhir/CodeSystem/stream-health"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, CODE_SYSTEM)

# HL7 terminology, used unchanged where it applies.
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
INTERPRETATION = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"
FLAG_CATEGORY = "http://terminology.hl7.org/CodeSystem/flag-category"
PARTICIPANT = "http://terminology.hl7.org/CodeSystem/provenance-participant-type"
DATA_ABSENT = "http://terminology.hl7.org/CodeSystem/data-absent-reason"
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

# Fixed codes: the ones not generated from a vocabulary.
FIXED_CODES: dict[str, str] = {
    "stream-ecological-status": "Urban stream ecological status, citizen screening",
    "benthic-macroinvertebrate-survey": "Benthic macroinvertebrate survey",
    "stream-habitat-assessment": "Visual stream habitat and pressure assessment",
    "wfd-ecological-status": "Ecological status class (Water Framework Directive scale)",
    "wfd-ecological-status-ordinal": "Ecological status as an ordinal, 5 high to 1 bad",
    "scoring-families": "Number of scoring macroinvertebrate families",
    "ept-families": "Number of EPT (mayfly, stonefly, caddisfly) families",
    "habitat-pressure": "Visual habitat pressure index, 0 none to 100 severe",
    "assessment-certainty": "Certainty of this assessment, as evidenced",
    "human-confirmations": "Observations a person confirmed or supplied",
    "taxa-identified-by": "Who identified the macroinvertebrates",
    "identified-by-citizen": "The citizen, with or without a model's second opinion",
    "identified-by-model": "A vision model, as proposals for a person to confirm",
    "identified-by-none": "No macroinvertebrates were identified",
    "second-opinion-independent-agreements": "Identifications a vision model agreed with, shown the photo without the citizen's answers",
    "second-opinion-adopted": "Identifications the citizen changed to the model's after comparing",
    "second-opinion-kept-own": "Disagreements where the citizen kept their own identification after comparing",
    "second-opinion-unresolved": "Disagreements with the model not yet settled",
    "one-health": "One Health assessment",
}


def _id(*parts: str) -> str:
    """A FHIR resource id: [A-Za-z0-9-.] only, 64 characters at most."""
    joined = "-".join(str(p) for p in parts if p)
    return re.sub(r"[^A-Za-z0-9.-]", "-", joined)[:64]


def _full_url(resource_type: str, resource_id: str) -> str:
    return f"urn:uuid:{uuid.uuid5(NAMESPACE, f'{resource_type}/{resource_id}')}"


def _ref(resource_type: str, resource_id: str) -> dict[str, str]:
    return {"reference": _full_url(resource_type, resource_id)}


def _code(code: str, display: str, text: str | None = None) -> dict[str, Any]:
    """A project coding. ``display`` is always the CodeSystem's; wording for this case goes in ``text``."""
    return {"coding": [{"system": CODE_SYSTEM, "code": code, "display": _DISPLAYS.get(code, display)}], "text": text or display}


def _quantity(value: float, unit: str, ucum: str | None = None) -> dict[str, Any]:
    q: dict[str, Any] = {"value": value, "unit": unit}
    if ucum:
        q.update(system=UCUM, code=ucum)
    return q


def _component(code: str, display: str, **value: Any) -> dict[str, Any]:
    return {"code": _code(code, display), **value}


def _interpretation(level: Level) -> list[dict[str, Any]]:
    code, display = LEVEL_INTERPRETATION[level]
    return [{"coding": [{"system": INTERPRETATION, "code": code, "display": display}]}]


def _taxon_code(t: bioindex.ScoredTaxon) -> str:
    return _id("taxon", (t.family or t.group or t.name).lower())


def _habitat_code(key: str) -> str:
    return _id("habitat", key.replace("_", "-"))


def _answer_code(key: str, value: str) -> str:
    return _id(key.replace("_", "-"), value.replace("_", "-"))


def _rule_code(rule_id: str) -> str:
    return _id("rule", rule_id.replace(".", "-").replace("_", "-"))


def _subject(a: Assessment) -> dict[str, str]:
    return _ref("Location", _id("site", a.id))


def _status_ref(a: Assessment) -> dict[str, str]:
    return _ref("Observation", _id("status", a.id))


CITIZEN = {"display": "Citizen scientist"}


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
            FIXED_CODES["wfd-ecological-status"],
            valueCodeableConcept=_code(f"wfd-{eco.band.value.lower()}", eco.band.value),
        ),
        _component("wfd-ecological-status-ordinal", FIXED_CODES["wfd-ecological-status-ordinal"], valueInteger=BAND_ORDINAL[eco.band]),
        _component(
            f"{eco.index.key}-total", f"{eco.index.total} total score", valueQuantity=_quantity(round(eco.bmwp, 1), "score")
        ),
    ]
    if eco.aspt is not None:
        components.append(
            _component(
                eco.index.mean.lower(),
                f"Average Score Per Taxon ({eco.index.total}/families)",
                valueQuantity=_quantity(round(eco.aspt, 2), "score"),
            )
        )
    components += [
        _component("scoring-families", FIXED_CODES["scoring-families"], valueInteger=eco.families),
        _component("ept-families", FIXED_CODES["ept-families"], valueInteger=eco.ept_families),
        _component("habitat-pressure", FIXED_CODES["habitat-pressure"], valueQuantity=_quantity(round(pressure.pressure, 1), "%", "%")),
        _component("assessment-certainty", FIXED_CODES["assessment-certainty"], valueQuantity=_quantity(round(a.certainty, 1), "%", "%")),
        _component("human-confirmations", FIXED_CODES["human-confirmations"], valueInteger=a.confirmations),
        _component(
            "taxa-identified-by",
            FIXED_CODES["taxa-identified-by"],
            valueCodeableConcept=_code(f"identified-by-{a.identified_by}", FIXED_CODES[f"identified-by-{a.identified_by}"]),
        ),
    ]
    if eco.total_class is not None:
        components.append(
            _component(
                f"{eco.index.key}-total-class",
                f"{eco.index.total} class from the total (assumes a standardised sample; understates a single tray)",
                valueCodeableConcept=_code(f"wfd-{eco.total_class.value.lower()}", eco.total_class.value),
            )
        )
    s = a.second_opinion
    if s is not None and s.available:
        for code, count in (
            ("second-opinion-independent-agreements", len(s.agreed) - len(s.adopted)),
            ("second-opinion-adopted", len(s.adopted)),
            ("second-opinion-kept-own", len(s.dismissed)),
            ("second-opinion-unresolved", len(s.open)),
        ):
            components.append(_component(code, FIXED_CODES[code], valueInteger=count))

    notes = [{"text": eco.caveat}, {"text": eco.meaning}]
    if eco.evidence_limited:
        notes.append({"text": "Evidence-limited: too few taxa were found to support a firmer class."})
    if s is not None:
        notes.append({"text": s.summary()})
    if a.penalties:
        notes.append({"text": "Limitations: " + "; ".join(a.penalties)})

    return {
        "resourceType": "Observation",
        "id": _id("status", a.id),
        "status": "preliminary" if a.confirmations == 0 else "amended",
        "category": [{"coding": [{"system": OBS_CATEGORY, "code": "survey", "display": "Survey"}]}],
        "code": _code("stream-ecological-status", FIXED_CODES["stream-ecological-status"]),
        "subject": _subject(a),
        "effectiveDateTime": a.created_at,
        "performer": [CITIZEN],
        "method": _code(f"{eco.index.key}-photo-screening", f"{eco.index.name} family-level screening from citizen photographs"),
        "valueCodeableConcept": _code(f"wfd-{eco.band.value.lower()}", eco.band.value),
        "component": components,
        "note": notes,
    }


def survey_observation(a: Assessment) -> dict[str, Any]:
    """The raw biological evidence: every family found, with the score it contributed."""
    total = a.ecology.index.total
    return {
        "resourceType": "Observation",
        "id": _id("survey", a.id),
        "status": "final",
        "category": [{"coding": [{"system": OBS_CATEGORY, "code": "survey", "display": "Survey"}]}],
        "code": _code("benthic-macroinvertebrate-survey", FIXED_CODES["benthic-macroinvertebrate-survey"]),
        "subject": _subject(a),
        "effectiveDateTime": a.created_at,
        "performer": [CITIZEN],
        "derivedFrom": [_status_ref(a)],
        "component": [
            {
                "code": _code(_taxon_code(t), f"{t.family or t.group} ({t.plain_name})", f"{t.plain_name}: {t.sensitivity}"),
                "valueQuantity": _quantity(t.score, f"{total} sensitivity score"),
            }
            for t in a.ecology.scored
        ]
        + [
            {
                "code": _code(_taxon_code(t), f"{t.family or t.group} ({t.plain_name})"),
                "dataAbsentReason": {
                    "coding": [{"system": DATA_ABSENT, "code": "not-applicable", "display": "Not Applicable"}],
                    "text": f"Recorded; not scored by {total}",
                },
            }
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
        "code": _code("stream-habitat-assessment", FIXED_CODES["stream-habitat-assessment"]),
        "subject": _subject(a),
        "effectiveDateTime": a.created_at,
        "performer": [CITIZEN],
        "derivedFrom": [_status_ref(a)],
        "component": [
            _component(
                _habitat_code(row.key),
                row.question,
                valueCodeableConcept=_code(_answer_code(row.key, row.value), row.label, f"{row.label} (reported by {row.source})"),
            )
            for row in (*a.pressures.readings, *a.pressures.exposure)
        ],
    }


def domain_observations(a: Assessment) -> list[dict[str, Any]]:
    """One Observation per One Health domain, carrying the rule engine's level."""
    out = []
    for domain in Domain:
        level = a.signal.levels[domain]
        findings = [f for f in a.signal.findings if f.domain is domain]
        out.append(
            {
                "resourceType": "Observation",
                "id": _id("onehealth", domain.value, a.id),
                "status": "final",
                "category": [
                    {"coding": [{"system": OBS_CATEGORY, "code": "exam", "display": "Exam"}]},
                    {"coding": [{"system": CODE_SYSTEM, "code": "one-health", "display": FIXED_CODES["one-health"]}]},
                ],
                "code": _code(f"one-health-{domain.value}", f"One Health signal: {domain.value} health"),
                "subject": _subject(a),
                "effectiveDateTime": a.created_at,
                "performer": [CITIZEN],
                "derivedFrom": [_status_ref(a)],
                "valueCodeableConcept": _code(f"level-{level.value}", level.value),
                "interpretation": _interpretation(level),
                "component": [
                    {
                        "code": _code(_rule_code(f.rule), f.title),
                        "valueString": "; ".join(f.because),
                        "interpretation": _interpretation(f.level),
                    }
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
                {"coding": [{"system": CODE_SYSTEM, "code": f"one-health-{f.domain.value}", "display": f"One Health signal: {f.domain.value} health"}]},
            ],
            "code": _code(_rule_code(f.rule), f.title, f"{f.title}. {f.action}"),
            "subject": _subject(a),
            "period": {"start": a.created_at},
        }
        for f in a.signal.findings
        if f.level is Level.ALERT
    ]


def provenance(a: Assessment) -> dict[str, Any]:
    """Who observed, what assembled the result, and from which reference data."""
    return {
        "resourceType": "Provenance",
        "id": _id("prov", a.id),
        "target": [_status_ref(a)],
        "recorded": a.created_at,
        "agent": [
            {"type": {"coding": [{"system": PARTICIPANT, "code": "author", "display": "Author"}]}, "who": CITIZEN},
            {
                "type": {"coding": [{"system": PARTICIPANT, "code": "assembler", "display": "Assembler"}]},
                "who": {"display": f"AquaPlot {a.version} (vision model: {a.observer})"},
            },
        ],
        "entity": [
            {"role": "source", "what": {"display": f"Bioindicator catalogue {a.ecology.catalogue_version} ({a.ecology.index.name})"}},
            {"role": "source", "what": {"display": f"Habitat form {a.pressures.form_version}"}},
            {"role": "source", "what": {"display": "iNaturalist API (taxonomy, establishment means, administrative places)"}},
        ],
    }


def _summary(resource: dict[str, Any]) -> str:
    code = resource.get("code", {})
    parts = [code.get("text") or resource.get("name") or resource["resourceType"]]
    value = resource.get("valueCodeableConcept", {}).get("text")
    if value:
        parts.append(value)
    return ": ".join(parts)


def _prune(node: Any) -> Any:
    """FHIR forbids empty arrays and objects; drop them rather than special-case every list."""
    if isinstance(node, dict):
        pruned = {k: _prune(v) for k, v in node.items()}
        return {k: v for k, v in pruned.items() if v not in ([], {}, None)}
    if isinstance(node, list):
        return [x for x in (_prune(v) for v in node) if x not in ([], {}, None)]
    return node


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
    for r in resources:
        r["text"] = {
            "status": "generated",
            "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{html.escape(_summary(r))}</div>',
        }
    return _prune(
        {
            "resourceType": "Bundle",
            "id": _id("aquaplot", a.id),
            "type": "collection",
            "timestamp": a.created_at,
            "entry": [{"fullUrl": _full_url(r["resourceType"], r["id"]), "resource": r} for r in resources],
        }
    )


# ---- the CodeSystem every project code belongs to ------------------------------

# Rule ids are string literals inside each rule function; reading them from the
# module keeps the CodeSystem from drifting when a rule is added.
RULE_IDS: tuple[str, ...] = tuple(sorted(set(re.findall(r'rule="([a-z_.]+)"', inspect.getsource(onehealth)))))


def code_system() -> dict[str, Any]:
    """The project CodeSystem, generated from the vocabularies the app itself runs on."""
    concepts: dict[str, str] = dict(FIXED_CODES)
    for band in Band:
        concepts[f"wfd-{band.value.lower()}"] = band.value
    for level in Level:
        concepts[f"level-{level.value}"] = level.value
    for domain in Domain:
        concepts[f"one-health-{domain.value}"] = f"One Health signal: {domain.value} health"
    for index in bioindex.INDICES.values():
        concepts[f"{index.key}-total"] = f"{index.total} total score"
        concepts[index.mean.lower()] = f"Average Score Per Taxon ({index.total}/families)"
        concepts[f"{index.key}-photo-screening"] = f"{index.name} family-level screening from citizen photographs"
        if index.total_classes:
            concepts[f"{index.key}-total-class"] = (
                f"{index.total} class from the total (assumes a standardised sample; understates a single tray)"
            )
    for f in bioindex.CATALOGUE:
        concepts[_id("taxon", f.family.lower())] = f"{f.family} ({f.plain_name})"
    for group in sorted({f.group for f in bioindex.CATALOGUE}):
        concepts[_id("taxon", group.lower())] = f"{group} (identified to order only)"
    for ind in habitat.INDICATORS:
        concepts[_habitat_code(ind.key)] = ind.question
        for opt in ind.options:
            concepts[_answer_code(ind.key, opt.value)] = opt.label
    for rule_id in RULE_IDS:
        domain, name = rule_id.split(".", 1)
        concepts[_rule_code(rule_id)] = f"One Health rule: {domain} health, {name.replace('_', ' ')}"
    return {
        "resourceType": "CodeSystem",
        "id": "stream-health",
        "text": {
            "status": "generated",
            "div": '<div xmlns="http://www.w3.org/1999/xhtml">AquaPlot stream health codes (provisional), '
            f"{len(concepts)} concepts.</div>",
        },
        "url": CODE_SYSTEM,
        "version": f"{bioindex.CATALOGUE_VERSION}+{habitat.FORM_VERSION}",
        "name": "AquaPlotStreamHealth",
        "title": "AquaPlot stream health (provisional)",
        "status": "draft",
        "experimental": True,
        "publisher": "AquaPlot",
        "description": (
            "Provisional project codes for citizen stream-health screening: biotic index components, "
            "macroinvertebrate taxa, visual habitat indicators and One Health rule findings. Not a "
            "standard terminology; see docs/FHIR.md for the path to LOINC or an environmental terminology."
        ),
        "caseSensitive": True,
        "content": "complete",
        "count": len(concepts),
        "concept": [{"code": code, "display": display} for code, display in sorted(concepts.items())],
    }


_DISPLAYS: dict[str, str] = {c["code"]: c["display"] for c in code_system()["concept"]}
