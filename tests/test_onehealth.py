"""The One Health rule engine and the FHIR export. Rules are the safety-critical part: test them hard."""

import re

import pytest

from riffle import fhir
from riffle.assess import Assessment
from riffle.bioindex import TaxonObservation, score
from riffle.habitat import Reading, assess as assess_habitat
from riffle.onehealth import Context, Domain, Level, evaluate
from riffle.schema import PlaceRef, Region

CLEAN = ["Perlidae", "Heptageniidae", "Leptoceridae", "Rhyacophilidae", "Gammaridae", "Elmidae", "Ancylidae", "Goeridae"]
FOUL = ["Oligochaeta", "Chironomidae", "Asellidae", "Physidae"]


def context(taxa=FOUL, answers=(), invasives=(), site="Test Brook", warm=True):
    return Context(
        status=score([TaxonObservation(name=n, confidence=0.9) for n in taxa]),
        habitat=assess_habitat([Reading(key=k, value=v, source=s) for k, v, s in answers]),
        invasives=invasives,
        site_name=site,
        warm_season=warm,
    )


def rules(signal):
    return {f.rule: f for f in signal.findings}


# ---- the rules ------------------------------------------------------------


def test_a_healthy_stream_raises_nothing_and_says_why_that_matters_for_people():
    s = evaluate(context(CLEAN, [("water_clarity", "clear", "citizen"), ("algae", "none", "citizen"), ("flow", "fast", "citizen")]))
    assert s.worst is Level.OK
    assert "human.wellbeing" in rules(s)
    assert "nothing visible that puts people or animals at risk" in s.headline


def test_a_confirmed_bloom_with_contact_is_an_alert_for_people_and_animals():
    s = evaluate(context(answers=[("algae", "bloom", "citizen"), ("access", "play_or_drinking", "citizen")]))
    assert rules(s)["human.cyanobacteria"].level is Level.ALERT
    assert rules(s)["animal.drinking_water"].level is Level.ALERT
    assert s.levels[Domain.HUMAN] is Level.ALERT


def test_an_unconfirmed_bloom_is_held_below_alert_until_a_person_confirms_it():
    """Riffle will not tell a parent to keep their child out of the water on a model's unreviewed guess."""
    s = evaluate(context(answers=[("algae", "bloom", "model"), ("access", "play_or_drinking", "model")]))
    finding = rules(s)["human.cyanobacteria"]
    assert finding.level is Level.CONCERN
    assert not finding.confirmed
    assert any("no person has confirmed" in b for b in finding.because)
    assert "Confirm the observation in the app" in finding.action


def test_sewage_evidence_accumulates_into_an_alert():
    one = evaluate(context(answers=[("odour", "sewage", "citizen")]))
    assert rules(one)["human.faecal_contamination"].level is Level.CONCERN
    two = evaluate(context(answers=[("odour", "sewage", "citizen"), ("litter", "sanitary", "citizen")]))
    assert rules(two)["human.faecal_contamination"].level is Level.ALERT


def test_exposure_escalates_a_water_quality_problem_into_a_health_one():
    unwatched = evaluate(context(answers=[("foam_or_sheen", "oil_sheen", "citizen")]))
    paddled = evaluate(context(answers=[("foam_or_sheen", "oil_sheen", "citizen"), ("access", "contact", "citizen")]))
    assert rules(unwatched)["human.chemical_exposure"].level is Level.CONCERN
    assert rules(paddled)["human.chemical_exposure"].level is Level.ALERT


def test_mosquito_rule_needs_larvae_and_stagnant_water_and_warmth_to_reach_concern():
    watch = evaluate(context(FOUL, [("flow", "slow", "citizen")]))
    assert rules(watch)["human.vector_breeding"].level is Level.WATCH
    concern = evaluate(context(FOUL + ["Culicidae"], [("flow", "stagnant", "citizen")]))
    assert rules(concern)["human.vector_breeding"].level is Level.CONCERN
    cold = evaluate(context(FOUL + ["Culicidae"], [("flow", "stagnant", "citizen")], warm=False))
    assert rules(cold)["human.vector_breeding"].level is Level.WATCH
    assert any("season is cool" in b for b in rules(cold)["human.vector_breeding"].because)


def test_invasive_species_produce_a_biosecurity_finding_with_an_action():
    s = evaluate(context(invasives=("Red Swamp Crayfish (Procambarus clarkii)",)))
    finding = rules(s)["animal.invasive_species"]
    assert finding.domain is Domain.ANIMAL
    assert "crayfish plague" in " ".join(finding.because)
    assert "check, clean and dry" in finding.action.lower() or "clean and dry" in finding.action.lower()


def test_provisional_biology_cannot_raise_an_ecosystem_alert():
    """Two tolerant families is enough to worry. It is not enough to declare a stream dead."""
    thin = evaluate(context(["Oligochaeta", "Chironomidae"]))
    assert rules(thin)["ecosystem.biological_condition"].level is Level.CONCERN
    assert "(provisional)" in rules(thin)["ecosystem.biological_condition"].title
    full = evaluate(context(FOUL))
    assert rules(full)["ecosystem.biological_condition"].level is Level.ALERT
    assert "(provisional)" not in rules(full)["ecosystem.biological_condition"].title


def test_structural_pressures_are_named_separately_from_water_quality():
    s = evaluate(context(answers=[("bank_modification", "fully_channelised", "citizen"), ("substrate", "concrete", "citizen")]))
    finding = rules(s)["ecosystem.habitat_degradation"]
    assert finding.level is Level.CONCERN
    assert "Water quality alone will not fix this" in finding.action


def test_every_finding_carries_a_rule_evidence_and_an_action():
    s = evaluate(context(answers=[("algae", "bloom", "citizen"), ("odour", "sewage", "citizen"), ("access", "contact", "citizen")]))
    assert s.findings
    for f in s.findings:
        assert f.rule and f.because and f.action
        assert f.domain in set(Domain)


def test_the_headline_leads_with_the_human_consequence():
    s = evaluate(context(answers=[("algae", "bloom", "citizen"), ("access", "contact", "citizen")]))
    assert "for people" in s.headline


def test_actions_are_split_by_who_can_actually_take_them():
    s = evaluate(context(answers=[("odour", "sewage", "citizen"), ("litter", "heavy", "citizen")]))
    d = s.as_dict()["actions"]
    assert d["you_now"] and d["your_community"] and d["the_authority"]
    assert any("sewer network" in a for a in d["the_authority"])
    assert any("litter pick" in a for a in d["your_community"])


def test_the_disclaimer_travels_with_every_read_out():
    assert "not a medical" in evaluate(context()).as_dict()["disclaimer"]


# ---- FHIR -----------------------------------------------------------------


@pytest.fixture
def assessment():
    ctx = context(
        FOUL + ["Culicidae"],
        [("algae", "bloom", "citizen"), ("odour", "sewage", "citizen"), ("access", "play_or_drinking", "citizen")],
    )
    return Assessment(
        id="abc123",
        created_at="2026-09-23T10:00:00+00:00",
        site_name="Ribeira da Fonte",
        region=Region(
            source="exif",
            lat=40.2111,
            lon=-8.4291,
            place=PlaceRef(id=1, name="Coimbra", display_name="Coimbra, PT", kind="municipality"),
            country=PlaceRef(id=2, name="PT", display_name="Portugal", kind="country"),
        ),
        photos=2,
        photo_kinds=["stream_scene", "specimen"],
        ecology=ctx.status,
        pressures=ctx.habitat,
        signal=evaluate(ctx),
        invasives=[],
        certainty=61.2,
        penalties=["three habitat questions went unanswered"],
        needs_confirmation=[],
        observer="claude",
        confirmations=3,
    )


def test_bundle_holds_the_site_the_panel_the_evidence_and_the_flags(assessment):
    bundle = fhir.bundle(assessment)
    kinds = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert bundle["resourceType"] == "Bundle" and bundle["type"] == "collection"
    assert kinds.count("Location") == 1 and kinds.count("Provenance") == 1
    assert kinds.count("Observation") == 6  # status, survey, habitat, and one per One Health domain
    assert "Flag" in kinds


def test_every_resource_id_is_a_legal_fhir_id(assessment):
    legal = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
    for entry in fhir.bundle(assessment)["entry"]:
        assert legal.match(entry["resource"]["id"]), entry["resource"]["id"]


def test_observations_hang_off_the_location_not_a_fabricated_patient(assessment):
    for entry in fhir.bundle(assessment)["entry"]:
        resource = entry["resource"]
        if "subject" in resource:
            assert resource["subject"]["reference"].startswith("Location/")


def test_the_panel_carries_the_index_numbers_as_components(assessment):
    panel = next(e["resource"] for e in fhir.bundle(assessment)["entry"] if e["resource"]["id"].startswith("status-"))
    codes = {c["code"]["coding"][0]["code"] for c in panel["component"]}
    assert {"bmwp-total", "aspt", "ept-families", "habitat-pressure", "wfd-ecological-status"} <= codes
    assert panel["valueCodeableConcept"]["text"] == assessment.ecology.band.value


def test_alert_findings_become_flags_a_receiving_system_can_act_on(assessment):
    flags = [e["resource"] for e in fhir.bundle(assessment)["entry"] if e["resource"]["resourceType"] == "Flag"]
    assert flags
    for flag in flags:
        assert flag["status"] == "active"
        assert flag["subject"]["reference"].startswith("Location/")
        assert flag["code"]["text"]


def test_provenance_records_the_model_the_catalogues_and_the_human_confirmations(assessment):
    prov = next(e["resource"] for e in fhir.bundle(assessment)["entry"] if e["resource"]["resourceType"] == "Provenance")
    agents = " ".join(a["who"]["display"] for a in prov["agent"])
    assert "Citizen scientist" in agents and "claude" in agents
    confirmations = next(x for x in prov["extension"] if x["url"].endswith("human-confirmations"))
    assert confirmations["valueInteger"] == 3


def test_no_code_pretends_to_be_a_standard_it_is_not(assessment):
    """Inventing a LOINC code would be the worst possible move in a standards track."""
    text = str(fhir.bundle(assessment))
    assert "loinc" not in text.lower()
    assert fhir.CODE_SYSTEM in text


def test_the_bundle_is_json_serialisable(assessment):
    import json

    assert json.loads(json.dumps(fhir.bundle(assessment)))["id"].startswith("riffle-")
