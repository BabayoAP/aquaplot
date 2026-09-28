"""The evaluation harness scores stored model output; it never calls a model itself."""

import pytest

from aquaplot.bioindex import TaxonObservation
from aquaplot.evaluation import Case, Outcome, load_labels, mistakes_for, score_outcomes


def outcome(truth, *seen, kind="specimen", error=None):
    return Outcome(
        case=Case(photo="p.jpg", truth=list(truth)),
        photo_kind=kind,
        model_taxa=[TaxonObservation(name=n, confidence=c) for n, c in seen],
        error=error,
    )


def test_a_plausible_mistake_is_a_family_people_actually_confuse():
    swaps = mistakes_for("Perlidae")
    assert "Leuctridae" in swaps  # another stonefly
    assert "Heptageniidae" in swaps  # a mayfly: the tails-and-gills confusion
    assert "Chironomidae" not in swaps


def test_a_model_that_sees_everything_catches_every_mistake_and_raises_no_false_alarm():
    r = score_outcomes([outcome(["Perlidae", "Gammaridae"], ("Perlidae", 0.9), ("Gammaridae", 0.9))])
    assert r.family_right == 2 and r.wrong == r.missed == 0
    assert r.caught == r.mistakes > 0
    assert r.caught_with_right_answer == r.mistakes
    assert r.false_alarm_photos == 0


def test_answering_at_order_level_is_counted_apart_from_being_wrong():
    r = score_outcomes([outcome(["Heptageniidae"], ("Ephemeroptera", 0.8))])
    assert r.order_only == 1 and r.wrong == 0


def test_a_blind_model_catches_only_what_it_can_see():
    r = score_outcomes([outcome(["Chironomidae"], kind="specimen")])
    assert r.missed == 1
    assert r.caught < r.mistakes  # a swap between tolerant families is invisible without the animal


def test_a_model_that_reports_something_absent_counts_as_a_false_alarm():
    r = score_outcomes([outcome(["Gammaridae"], ("Gammaridae", 0.9), ("Hydropsychidae", 0.8))])
    assert r.model_extras == 1 and r.false_alarm_photos == 1


def test_an_unusable_photo_is_reported_not_scored():
    r = score_outcomes([outcome(["Gammaridae"], error="HTTP 500")])
    assert r.unusable == 1 and r.truths == 0
    assert "1 usable" not in r.markdown("fake")


def test_labels_with_a_name_the_catalogue_does_not_know_are_refused(tmp_path):
    p = tmp_path / "labels.csv"
    p.write_text("photo,families\na.jpg,Gammaridae;Unicornidae\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unicornidae"):
        load_labels(p)


def test_labels_accept_genus_and_common_names(tmp_path):
    p = tmp_path / "labels.csv"
    p.write_text("photo,families\na.jpg,Gammarus;bloodworm\n", encoding="utf-8")
    [case] = load_labels(p)
    assert case.truth == ["Gammaridae", "Chironomidae"]
