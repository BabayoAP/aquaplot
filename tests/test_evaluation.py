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


# ---- the rule-layer sweep (scripts/evaluate_rules.py) -------------------------


def _sweep():
    """Import the script the way a developer runs it, from the repository root."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "evaluate_rules.py"
    spec = importlib.util.spec_from_file_location("evaluate_rules", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_rule_sweep_is_deterministic():
    """The published table has to be reproducible from the seed, or it is an anecdote."""
    rules = _sweep()
    first = rules.sweep(0.4, 0.3, repeats=20, seed=7)
    again = rules.sweep(0.4, 0.3, repeats=20, seed=7)
    assert first == again


def test_a_worse_observer_catches_fewer_mistakes_and_asks_more_of_a_correct_volunteer():
    """The whole point of the sweep: the curve has to move the way the design says.

    An observer that misses more animals must catch less and interrupt more, and a
    perfect one must catch everything without questioning a volunteer who was right.
    """
    rules = _sweep()
    perfect = rules.sweep(0.0, 0.0, repeats=20, seed=7)
    poor = rules.sweep(0.6, 0.0, repeats=20, seed=7)

    assert perfect["caught"] == 1.0 and perfect["alarms_per_photo"] == 0.0
    assert poor["caught"] < perfect["caught"]
    assert poor["alarms_per_photo"] > perfect["alarms_per_photo"]


def test_answering_only_to_order_costs_the_suggestion_but_not_the_catch():
    """'Some kind of mayfly' is a correct answer, so it must still raise the
    question - it just cannot offer the family as the alternative."""
    rules = _sweep()
    exact = rules.sweep(0.0, 0.0, repeats=20, seed=7)
    coarse = rules.sweep(0.0, 0.6, repeats=20, seed=7)

    assert coarse["right_answer"] < exact["right_answer"]
    assert coarse["caught"] > 0.5


# ---- rebuilding the labelled set (scripts/fetch_inat_eval.py) ----------------


def _fetch():
    """Import the fetch script the way a developer runs it, from the repository root."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "fetch_inat_eval.py"
    spec = importlib.util.spec_from_file_location("fetch_inat_eval", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_labelled_photo_names_the_observation_it_came_from():
    """The published figures are only checkable if the exact photographs can be got
    back, and searching iNaturalist again returns a different set. Each row carries
    its observation link, so each row can be re-fetched by id."""
    fetch = _fetch()
    row = {
        "photo": "perlidae-91628632.jpg",
        "note": "(c) somebody, some rights reserved (CC BY-NC) - https://www.inaturalist.org/observations/91628632",
    }
    assert fetch.observation_id(row) == 91628632


def test_a_hand_written_label_falls_back_to_the_filename():
    """Somebody labelling photos they already have writes no note; the id in the
    name that fetch wrote is still enough to rebuild from."""
    fetch = _fetch()
    assert fetch.observation_id({"photo": "baetidae-165625583.jpg", "note": ""}) == 165625583


def test_a_photo_with_no_traceable_observation_is_not_guessed_at():
    fetch = _fetch()
    assert fetch.observation_id({"photo": "tray-01.jpg", "note": "Ribeira de Coselhas, riffle below the bridge"}) is None


def test_every_committed_label_can_be_rebuilt():
    """A committed labels.csv whose rows cannot be traced back to an observation is
    a measurement nobody can reproduce, which is the thing this file exists to stop."""
    from pathlib import Path

    fetch = _fetch()
    import csv

    for name in ("labels.csv", "labels-subset.csv"):
        path = Path(__file__).resolve().parent.parent / "eval" / "inat" / name
        with path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert rows, f"{name} is empty"
        untraceable = [r["photo"] for r in rows if fetch.observation_id(r) is None]
        assert not untraceable, f"{name}: {untraceable}"
