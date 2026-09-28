"""The Iberian index, chosen from the place, and animals an index does not score. No network, no model."""

import json

from aquaplot.assess import Review, StreamAssessor, Submission, reassess
from aquaplot.bioindex import BMWP, BY_FAMILY, IBMWP, Band, TaxonObservation, index_for, score
from aquaplot.observe import NullObserver
from aquaplot.schema import PlaceRef, Region

from test_assessment import COIMBRA

GHENT = Region(
    source="user",
    lat=51.0543,
    lon=3.7174,
    place=PlaceRef(id=8, name="Gent", display_name="Gent, BE", kind="municipality"),
    country=PlaceRef(id=2, name="BE", display_name="Belgium", kind="country"),
)


def mine(*names):
    return [TaxonObservation(name=n, confirmed_by="citizen") for n in names]


def test_the_iberian_scores_are_the_published_ones_where_they_differ():
    # Values from MAGRAMA (2011) as distributed with biomonitoR; BMWP from Armitage et al. (1983).
    for family, bmwp, ibmwp in [("Ephemerellidae", 10, 7), ("Caenidae", 7, 4), ("Corixidae", 5, 3), ("Perlidae", 10, 10)]:
        f = BY_FAMILY[family.lower()]
        assert (f.bmwp, f.ibmwp) == (bmwp, ibmwp)


def test_the_index_follows_the_country_the_coordinates_resolved_to():
    assert index_for(["PT", "Portugal"]) is IBMWP
    assert index_for(["ES"]) is IBMWP
    assert index_for(["BE", "Belgium"]) is BMWP
    assert index_for([]) is BMWP  # no place, no assumption


def test_the_same_tray_can_read_differently_under_the_two_indices():
    sample = mine("Ephemerellidae", "Caenidae", "Corixidae", "Gammaridae", "Baetidae")
    uk, iberia = score(sample, BMWP), score(sample, IBMWP)
    assert uk.aspt > iberia.aspt
    assert iberia.index is IBMWP and iberia.as_dict()["mean_label"] == "IASPT"


def test_the_iberian_total_class_is_reported_but_never_used_for_the_band():
    """A tray finds a handful of families; IBMWP's classes assume thirty. The band comes from the mean."""
    s = score(mine("Perlidae", "Heptageniidae", "Leptoceridae", "Gammaridae", "Elmidae"), IBMWP)
    assert s.total_class is Band.MODERATE  # total 41
    assert s.band is Band.GOOD  # mean 8.2, capped at Good by five families
    assert any("reads low" in sig for sig in s.signals)
    assert score(mine("Perlidae"), BMWP).total_class is None


def test_an_animal_the_index_does_not_score_is_still_recorded_and_still_matters_for_health():
    s = score(mine("Culicidae", "Gammaridae"), BMWP)
    assert s.families == 1 and [t.family for t in s.recorded] == ["Culicidae"]
    assert any("Mosquito" in v for v in s.vectors)
    assert any(t["family"] == "Culicidae" and t["scored"] is False for t in s.as_dict()["taxa"])


def test_a_sample_of_only_unscored_animals_is_a_placeholder_that_keeps_them():
    s = score(mine("Culicidae"), BMWP)
    assert s.families == 0 and s.evidence_limited and s.vectors


def test_under_ibmwp_the_mosquito_is_scored():
    assert score(mine("Culicidae"), IBMWP).families == 1


async def test_a_check_in_portugal_uses_ibmwp_and_one_in_belgium_uses_bmwp():
    pt = await StreamAssessor(observer=NullObserver()).assess(Submission(region=COIMBRA, taxa=tuple(mine("Caenidae"))))
    be = await StreamAssessor(observer=NullObserver()).assess(Submission(region=GHENT, taxa=tuple(mine("Caenidae"))))
    assert pt.ecology.index is IBMWP and be.ecology.index is BMWP
    assert pt.ecology.bmwp == 4 and be.ecology.bmwp == 7


async def test_the_index_can_be_named_explicitly():
    a = await StreamAssessor(observer=NullObserver()).assess(Submission(region=COIMBRA, taxa=tuple(mine("Caenidae")), index="bmwp"))
    assert a.ecology.index is BMWP


async def test_a_review_keeps_the_index_the_visit_was_scored_with():
    a = await StreamAssessor(observer=NullObserver()).assess(Submission(region=COIMBRA, taxa=tuple(mine("Caenidae"))))
    after = await reassess(a.as_dict(), Review(added_taxa=("Perlidae",)))
    assert after.ecology.index is IBMWP


def test_the_export_says_which_index_each_row_used(client):
    from aquaplot.app import app
    from aquaplot.store import Store

    app.state.store = Store(":memory:")
    app.state.assessor = StreamAssessor(observer=NullObserver())
    ok = client.post("/api/assess", data={"taxa": json.dumps(["Caenidae"]), "index": "ibmwp"})
    assert ok.status_code == 200 and ok.json()["ecology"]["total_label"] == "IBMWP"
    csv_text = client.get("/api/export.csv").text
    header, row = csv_text.splitlines()[:2]
    assert "biotic_index" in header and "ibmwp" in row
    assert client.post("/api/assess", data={"taxa": json.dumps(["Caenidae"]), "index": "saprobic"}).status_code == 422
