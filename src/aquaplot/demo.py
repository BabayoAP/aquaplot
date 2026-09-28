"""The demo dataset, and seeding it into an empty deployment.

A free hosting tier gives a container an ephemeral disk: every restart and every
redeploy starts with an empty database. An empty dashboard and an empty map are
the worst first impression a tool can make when its argument is that a *series*
of readings is worth more than one, and a judge opening the live link once will
see exactly that. So with ``AQUAPLOT_SEED_DEMO=1`` the app fills an empty store
at startup, through the same assessor a citizen's check goes through.

Nothing here is a real observation. Every site is labelled "(demo data)" so it can
never be mistaken for a citizen's record. The visits are dated in the past so the
site pages show series over months rather than several readings in one second; a
visit dated in the past gets no weather, because the weather lookup only answers
for a visit made now (weather.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from . import bioindex, habitat
from .assess import StreamAssessor, Submission
from .schema import Region

CLEAN = {"water_clarity": "clear", "water_colour": "natural", "algae": "none", "foam_or_sheen": "natural_foam",
         "litter": "scattered", "riparian_vegetation": "continuous_natural", "bank_modification": "natural",
         "flow": "fast", "substrate": "boulders_cobbles", "sediment_deposit": "none", "shade": "shaded",
         "odour": "earthy", "access": "path_only"}
COIMBRA_BEFORE = {"water_clarity": "slightly_turbid", "water_colour": "natural", "algae": "patchy", "foam_or_sheen": "none",
                  "litter": "scattered", "riparian_vegetation": "patchy", "bank_modification": "partly_reinforced",
                  "flow": "moderate", "substrate": "gravel", "sediment_deposit": "light", "shade": "partial",
                  "odour": "none", "access": "contact"}
COIMBRA_AFTER = {"water_clarity": "turbid", "water_colour": "grey", "algae": "extensive", "foam_or_sheen": "white_foam",
                 "litter": "heavy", "riparian_vegetation": "patchy", "bank_modification": "partly_reinforced",
                 "flow": "slow", "substrate": "silt", "sediment_deposit": "heavy", "shade": "partial",
                 "odour": "sewage", "access": "contact"}
GHENT_BEFORE = {"water_clarity": "turbid", "water_colour": "green", "algae": "extensive", "foam_or_sheen": "none",
                "litter": "heavy", "riparian_vegetation": "mown_grass", "bank_modification": "fully_channelised",
                "flow": "slow", "substrate": "silt", "sediment_deposit": "heavy", "shade": "open",
                "odour": "musty", "access": "contact"}
GHENT_AFTER = {**GHENT_BEFORE, "water_clarity": "slightly_turbid", "litter": "scattered",
               "riparian_vegetation": "patchy", "sediment_deposit": "light"}

# Each entry is one visit; ``days_ago`` dates it. Sites that appear more than once are
# the point of the exercise: they are what turns a reading into a trend. Ribeira da
# Fonte declines after a discharge; Hovinbekken holds; the Leie channel improves
# after its margin was left unmown.
VISITS: list[dict[str, Any]] = [
    {"who": "demo-oslo", "site_name": "Hovinbekken, Oslo (demo data)", "lat": 59.9245, "lon": 10.7890, "days_ago": 150,
     "answers": CLEAN, "taxa": ["Perlidae", "Heptageniidae", "Leptoceridae", "Rhyacophilidae", "Gammaridae", "Elmidae", "Ancylidae"]},
    {"who": "demo-oslo", "site_name": "Hovinbekken, Oslo (demo data)", "lat": 59.9245, "lon": 10.7890, "days_ago": 60,
     "answers": CLEAN,
     "taxa": ["Perlidae", "Heptageniidae", "Leptoceridae", "Rhyacophilidae", "Goeridae", "Gammaridae", "Elmidae", "Ancylidae"]},
    {"who": "demo-coimbra", "site_name": "Ribeira da Fonte, Coimbra (demo data)", "lat": 40.2038, "lon": -8.4194, "days_ago": 120,
     "answers": COIMBRA_BEFORE,
     "taxa": ["Baetidae", "Hydropsychidae", "Gammaridae", "Elmidae", "Ancylidae", "Limnephilidae", "Leptophlebiidae"]},
    {"who": "demo-coimbra", "site_name": "Ribeira da Fonte, Coimbra (demo data)", "lat": 40.2038, "lon": -8.4194, "days_ago": 70,
     "answers": COIMBRA_BEFORE, "taxa": ["Baetidae", "Hydropsychidae", "Gammaridae", "Elmidae", "Ancylidae", "Limnephilidae"]},
    {"who": "demo-coimbra", "site_name": "Ribeira da Fonte, Coimbra (demo data)", "lat": 40.2039, "lon": -8.4195, "days_ago": 12,
     "answers": COIMBRA_AFTER, "taxa": ["Asellidae", "Chironomidae", "Oligochaeta", "Erpobdellidae", "Physidae"]},
    {"who": "demo-ghent", "site_name": "Leie side channel, Ghent (demo data)", "lat": 51.0489, "lon": 3.7255, "days_ago": 140,
     "answers": GHENT_BEFORE, "taxa": ["Asellidae", "Chironomidae", "Physidae", "Oligochaeta"]},
    {"who": "demo-ghent", "site_name": "Leie side channel, Ghent (demo data)", "lat": 51.0489, "lon": 3.7255, "days_ago": 20,
     "answers": GHENT_AFTER, "taxa": ["Baetidae", "Gammaridae", "Asellidae", "Chironomidae", "Physidae", "Dreissenidae"]},
    {"who": "demo-toulouse", "site_name": "Hers-Mort tributary, Toulouse (demo data)", "lat": 43.5966, "lon": 1.4722, "days_ago": 30,
     "answers": {"water_clarity": "clear", "water_colour": "natural", "algae": "patchy", "foam_or_sheen": "none",
                 "litter": "none", "riparian_vegetation": "continuous_natural", "bank_modification": "natural",
                 "flow": "stagnant", "substrate": "sand", "sediment_deposit": "light", "shade": "open",
                 "odour": "none", "access": "play_or_drinking"},
     "taxa": ["Culicidae", "Chironomidae", "Baetidae", "Corixidae", "Lymnaeidae", "Coenagrionidae"]},
    {"who": "demo-benevento", "site_name": "Torrente San Nicola, Benevento (demo data)", "lat": 41.1268, "lon": 14.7715, "days_ago": 25,
     "answers": {"water_clarity": "clear", "water_colour": "natural", "algae": "patchy", "foam_or_sheen": "none",
                 "litter": "scattered", "riparian_vegetation": "patchy", "bank_modification": "partly_reinforced",
                 "flow": "moderate", "substrate": "gravel", "sediment_deposit": "light", "shade": "partial",
                 "odour": "none", "access": "contact"},
     "taxa": ["Baetidae", "Caenidae", "Hydropsychidae", "Gammaridae", "Elmidae", "Procambarus clarkii"]},
]


def submission_of(visit: dict[str, Any], now: datetime) -> Submission:
    return Submission(
        region=Region(source="user", lat=visit["lat"], lon=visit["lon"]),
        site_name=visit["site_name"],
        answers=tuple(habitat.Reading(key=k, value=v, source="citizen") for k, v in visit["answers"].items()),
        taxa=tuple(bioindex.TaxonObservation(name=n, confirmed_by="citizen") for n in visit["taxa"]),
        when=now - timedelta(days=visit["days_ago"]),
    )


async def seed(assessor: StreamAssessor, store, now: datetime | None = None) -> int:
    """Fill an empty store with the demo visits. Returns how many were stored (0 if not empty)."""
    if store.summary()["assessments"]:
        return 0
    now = now or datetime.now(UTC)
    stored = 0
    for visit in sorted(VISITS, key=lambda v: -v["days_ago"]):
        result = await assessor.assess(submission_of(visit, now))
        store.save(result, visit["who"])
        stored += 1
    return stored
