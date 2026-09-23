"""The biological index and the visual field form. Pure arithmetic and vocabulary: no network, no model."""

import pytest

from riffle import habitat
from riffle.bioindex import (
    CATALOGUE,
    Band,
    TaxonObservation,
    resolve,
    score,
)

CLEAN = ["Perlidae", "Heptageniidae", "Leptoceridae", "Rhyacophilidae", "Gammaridae", "Elmidae", "Ancylidae", "Goeridae"]
FOUL = ["Oligochaeta", "Chironomidae", "Asellidae", "Physidae", "Erpobdellidae"]


def obs(names, confidence=0.9, **kw):
    return [TaxonObservation(name=n, confidence=confidence, **kw) for n in names]


# ---- resolution -----------------------------------------------------------


def test_family_genus_species_and_vernacular_all_resolve():
    """A citizen types 'bloodworm', a model returns 'Chironomus plumosus'. Both are the same family."""
    assert resolve("Chironomidae").family.family == "Chironomidae"
    assert resolve("Chironomus plumosus").family.family == "Chironomidae"
    assert resolve("bloodworm").family.family == "Chironomidae"
    assert resolve("  BAETIS  ").family.family == "Baetidae"


def test_order_only_identification_is_scored_but_marked_coarse():
    """'That is a stonefly' is real information and must not be thrown away, only labelled."""
    match = resolve("stonefly")
    assert match.coarse and match.family is None and match.group == "Plecoptera"
    assert match.score > 7  # stoneflies are sensitive whichever family it was
    assert "group only" in match.label


def test_unknown_names_resolve_to_nothing_rather_than_something_close():
    assert resolve("Tyrannosaurus") is None
    assert resolve("") is None


def test_catalogue_entries_are_well_formed():
    for f in CATALOGUE:
        assert 1 <= f.bmwp <= 10
        assert f.plain_name and f.look_for and f.means
        assert f.ept == (f.group in {"Ephemeroptera", "Plecoptera", "Trichoptera"})
    assert len({f.family for f in CATALOGUE}) == len(CATALOGUE)


# ---- scoring --------------------------------------------------------------


def test_a_clean_stream_community_bands_high():
    s = score(obs(CLEAN))
    assert s.band is Band.HIGH and s.ept_families == 5
    assert s.aspt == pytest.approx(s.bmwp / s.families)
    assert not s.evidence_limited


def test_a_polluted_stream_community_bands_bad_and_names_the_signature():
    s = score(obs(FOUL))
    assert s.band is Band.BAD and s.ept_families == 0
    joined = " ".join(s.signals)
    assert "No mayflies, stoneflies or caddisflies" in joined
    assert "oxygen-starved bed" in joined  # worms plus bloodworms, the classic pair


def test_effort_caps_the_claim():
    """One mayfly under one stone does not prove the stream is pristine."""
    thin = score(obs(["Perlidae"]))
    assert thin.band is not Band.HIGH and thin.evidence_limited
    assert any("cannot support" in p for p in thin.penalties)
    assert "Provisional" in thin.meaning


def test_duplicate_families_collapse_and_the_confirmed_one_wins():
    s = score(
        [
            TaxonObservation(name="Baetidae", confidence=0.3),
            TaxonObservation(name="Baetidae", confidence=0.4, confirmed_by="citizen"),
        ]
    )
    assert s.families == 1 and s.scored[0].confirmed and s.scored[0].confidence == 1.0


def test_an_order_level_guess_is_dropped_once_a_family_from_it_is_known():
    s = score(obs(["stonefly", "Perlidae"]))
    assert s.families == 1 and s.scored[0].family == "Perlidae"


def test_unmatched_names_are_reported_not_silently_dropped():
    s = score(obs(CLEAN + ["Wibblidae"]))
    assert s.unmatched == ["Wibblidae"]
    assert any("could not be matched" in p for p in s.penalties)


def test_no_identifiable_animals_produces_no_reading():
    s = score(obs(["Wibblidae"]))
    assert s.families == 0 and s.confidence == 0.0 and s.evidence_limited
    assert any("placeholder, not a reading" in p for p in s.penalties)


def test_confidence_falls_with_shaky_identifications_and_thin_samples():
    sure = score(obs(CLEAN, confidence=1.0))
    unsure = score(obs(CLEAN, confidence=0.5))
    thin = score(obs(CLEAN[:3], confidence=1.0))
    assert sure.confidence > unsure.confidence
    assert sure.confidence > thin.confidence


def test_disease_vector_taxa_are_surfaced_for_the_one_health_rules():
    s = score(obs(["Culicidae", "Chironomidae"]))
    assert any("Mosquito" in v for v in s.vectors)


# ---- the habitat form -----------------------------------------------------


def test_every_option_scores_on_the_same_scale_or_admits_it_cannot_tell():
    for indicator in habitat.INDICATORS:
        assert indicator.options
        for option in indicator.options:
            assert option.score is None or 0 <= option.score <= habitat.MAX_SCORE


def test_the_model_prompt_is_generated_from_the_form_and_omits_person_only_fields():
    """One file drives the prompt, the validator and the UI, so they cannot drift apart."""
    vocabulary = habitat.model_vocabulary()
    assert "water_clarity" in vocabulary and "clear | slightly_turbid" in vocabulary
    assert "odour" not in vocabulary  # no camera can smell
    assert [i.key for i in habitat.PERSON_ONLY] == ["odour"]


def test_a_citizen_answer_overrides_the_model_for_the_same_question():
    p = habitat.assess(
        [
            habitat.Reading(key="algae", value="none", source="model", confidence=0.9),
            habitat.Reading(key="algae", value="bloom", source="citizen"),
        ]
    )
    assert p.value("algae") == "bloom"
    assert [r.source for r in p.readings if r.key == "algae"] == ["citizen"]


def test_invalid_answers_are_discarded_and_reported():
    p = habitat.assess([habitat.Reading(key="algae", value="purple"), habitat.Reading(key="nonsense", value="x")])
    assert p.invalid == ["algae=purple", "nonsense=x"]
    assert any("outside the form's vocabulary" in x for x in p.penalties)


def test_pressure_rises_with_severity_and_exposure_is_kept_out_of_it():
    good = habitat.assess([habitat.Reading(key=k, value=v) for k, v in [("water_clarity", "clear"), ("algae", "none"), ("flow", "fast")]])
    bad = habitat.assess([habitat.Reading(key=k, value=v) for k, v in [("water_clarity", "opaque"), ("algae", "bloom"), ("flow", "stagnant")]])
    assert good.pressure == 0 and good.band == "none"
    assert bad.pressure == 100 and bad.band == "severe"
    exposed = habitat.assess([habitat.Reading(key="access", value="play_or_drinking"), habitat.Reading(key="algae", value="none")])
    assert exposed.pressure == 0  # who uses the water does not make it dirtier
    assert exposed.value("access") == "play_or_drinking"


def test_cannot_tell_answers_count_as_gaps_not_as_good_news():
    p = habitat.assess([habitat.Reading(key="substrate", value="not_visible")])
    assert p.answered == 0 and p.pressure == 0
    assert any("cannot tell" in x for x in p.penalties)


def test_the_person_only_question_stays_on_the_queue_until_a_person_answers_it():
    from_model = habitat.assess([habitat.Reading(key="odour", value="none", source="model")])
    assert "odour" in from_model.unanswered_by_person
    from_person = habitat.assess([habitat.Reading(key="odour", value="none", source="citizen")])
    assert from_person.unanswered_by_person == []
