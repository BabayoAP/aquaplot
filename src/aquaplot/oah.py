"""OneAquaHealth interoperability: the project's research sites and its citizen app's submission.

AquaPlot is meant to feed the OneAquaHealth project's data, not to compete with it
(docs/HACKATHON.md). That promise is only worth something if a check can land in
the project's own systems in the project's own terms, so this module holds the two
things that make it concrete, both read from ``data/oah_reference.json`` - a
snapshot of the project's public API, refreshed by ``scripts/fetch_oah_reference.py``
and never fetched at run time:

* **The research sites.** The 106 urban stream reaches in Benevento, Coimbra,
  Ghent, Oslo and Toulouse where the project samples and files its lab data under
  a code such as ``C3``. A check made within ``MATCH_RADIUS_M`` of one is at that
  site, and says so: a citizen reading taken where the laboratory also samples is
  worth more to the project than one anywhere else, because it can be compared.
* **The Citizen Science App's submission.** ``app_submission`` translates a check
  into the body the project's app sends (``CitizenSubmissionPutDTO``), using the
  app's own answer codes. The two forms ask overlapping, not identical, questions,
  so every field says which AquaPlot answer it came from, and everything that did
  not translate is listed with the reason rather than dropped quietly.

**Only what a person stands behind is carried.** A habitat answer the vision
model gave and nobody confirmed is not a citizen observation, and the project's
app has no way to say otherwise, so it stays behind and is listed as such. The
FHIR export applies the same rule to the project's indicator profile (fhir.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

from .bioindex import Band
from .store import haversine_m

MATCH_RADIUS_M = 200.0  # a research site is a reach, not a point; further than this is another stretch
API = "https://api.enora-oah.eu/api"


@dataclass(frozen=True, slots=True)
class ResearchSite:
    code: str
    name: str
    city: str
    lat: float
    lon: float

    def as_dict(self, distance_m: float | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "name": self.name, "city": self.city, "lat": self.lat, "lon": self.lon}
        if distance_m is not None:
            out["distance_m"] = round(distance_m)
        return out


@cache
def reference() -> dict[str, Any]:
    return json.loads(resources.files("aquaplot.data").joinpath("oah_reference.json").read_text(encoding="utf-8"))


def research_sites() -> list[ResearchSite]:
    return [ResearchSite(code=s["code"], name=s["name"], city=s["city"], lat=s["lat"], lon=s["lon"]) for s in reference()["sites"]]


def app_codes(vocabulary: str) -> dict[str, str]:
    """One of the Citizen Science App's answer lists, code to name."""
    return {row["code"]: row["name"] for row in reference()["app_vocabularies"][vocabulary]}


def research_site_at(lat: float | None, lon: float | None, radius_m: float = MATCH_RADIUS_M) -> tuple[ResearchSite, float] | None:
    """The OneAquaHealth research site this point is at, with the distance, if any."""
    if lat is None or lon is None:
        return None
    best = min(((s, haversine_m(lat, lon, s.lat, s.lon)) for s in research_sites()), key=lambda p: p[1], default=None)
    return best if best is not None and best[1] <= radius_m else None


# ---- the Citizen Science App submission ---------------------------------------

# AquaPlot answer -> app code, where the meaning is the same. "moderate" flow has
# no app equivalent between fast and slow; the app's "Slow (B)" is the nearer one.
FLOW = {"fast": "FAS", "moderate": "NOR", "slow": "NOR", "stagnant": "STA", "dry": "DRY"}
BED = {"boulders_cobbles": "NAT", "gravel": "NAT", "sand": "NAT", "silt": "NAT", "concrete": "ART"}
BANKS = {"natural": "NAT", "fully_channelised": "ART"}
BAND_TO_OVERALL = {Band.HIGH: "GOOD", Band.GOOD: "GOOD", Band.MODERATE: "MODERATE", Band.POOR: "POOR", Band.BAD: "POOR"}
PRESSURE_TO_OVERALL = {"none": "GOOD", "low": "GOOD", "moderate": "MODERATE", "high": "POOR", "severe": "POOR"}

NEVER_CARRIED = (
    "photographs: the app takes uploaded file ids, so photos must be attached in the app itself",
    "how the place made you feel (joy, serenity, anger, fear): AquaPlot does not ask",
    "dams, pipes, discharges, water abstraction, construction and water height: AquaPlot does not ask",
    "the macroinvertebrates: the app's citizen form has no place for them; they travel in the FHIR export instead",
)


def person_backed(a) -> dict[str, Any]:
    """The habitat answers a person gave or confirmed, by key. Model-only answers are left out."""
    return {r.key: r for r in (*a.pressures.readings, *a.pressures.exposure) if r.source == "citizen"}


def app_submission(a) -> dict[str, Any]:
    """A check as the body the OneAquaHealth Citizen Science App submits, with its working shown."""
    answers = person_backed(a)
    body: dict[str, Any] = {"latitude": a.region.lat, "longitude": a.region.lon}
    carried: list[dict[str, str]] = []
    not_carried: list[str] = []

    def put(field: str, code: Any, came_from: str) -> None:
        body[field] = code
        carried.append({"field": field, "value": code if isinstance(code, str) else json.dumps(code), "from": came_from})

    def value(key: str) -> str | None:
        return answers[key].value if key in answers else None

    site = research_site_at(a.region.lat, a.region.lon)
    if site is not None:
        body["researchSite"] = site[0].code
        endpoint, schema = f"PUT {API}/citizens/submit", "CitizenSubmissionPutDTO"
    else:
        body["userGeneratedSite"] = None
        endpoint, schema = f"PUT {API}/citizens/user-generated-sites/submit", "CitizenSubmissionGeneratedSitePutDTO"
        not_carried.append(
            "the site: this check is not at one of the project's research sites, so it needs a personal site "
            "created in the app first (PUT /citizens/user-generated-sites/insert), whose id goes in userGeneratedSite"
        )

    if (flow := value("flow")) in FLOW:
        put("waterFlow", FLOW[flow], f"flow = {flow}")

    colour, foam, clarity = value("water_colour"), value("foam_or_sheen"), value("water_clarity")
    if foam in ("natural_foam", "white_foam"):
        put("waterColor", "FO", f"foam_or_sheen = {foam}")
    elif (colour and colour != "natural") or foam == "oil_sheen":
        put("waterColor", "CO", f"water_colour = {colour}" if colour and colour != "natural" else "foam_or_sheen = oil_sheen")
    elif clarity in ("slightly_turbid", "turbid", "opaque"):
        put("waterColor", "MU", f"water_clarity = {clarity}")
    elif clarity == "clear":
        put("waterColor", "CL", "water_clarity = clear")

    substrate = value("substrate")
    if substrate in BED:
        put("bottomChannelType", BED[substrate], f"substrate = {substrate}")
    habitats = []
    if substrate == "boulders_cobbles":
        habitats.append("SD")
    if flow == "fast" and substrate in ("boulders_cobbles", "gravel"):
        habitats.append("RF")
    if habitats:
        put("habitats", habitats, f"flow = {flow}, substrate = {substrate}")

    banks = value("bank_modification")
    if banks in BANKS:
        put("banksChannelType", BANKS[banks], f"bank_modification = {banks}")
    elif banks == "partly_reinforced":
        not_carried.append("partly reinforced banks: the app separates concrete from laid stones, and AquaPlot does not ask which")

    # AquaPlot asks about the banks together; the app asks left and right. The
    # same answer goes to both, and only where it means the same thing.
    riparian = value("riparian_vegetation")
    if riparian == "continuous_natural":
        put("isVegetationCoveredLeft", True, "riparian_vegetation = continuous_natural (both banks)")
        put("isVegetationCoveredRight", True, "riparian_vegetation = continuous_natural (both banks)")
    elif riparian == "mown_grass":
        for side in ("Left", "Right"):
            put(f"isVegetationCovered{side}", True, "riparian_vegetation = mown_grass (both banks)")
            put(f"vegetationType{side}", "H", "riparian_vegetation = mown_grass (both banks)")
    elif riparian == "bare_or_paved":
        for side in ("Left", "Right"):
            put(f"isVegetationCovered{side}", False, "riparian_vegetation = bare_or_paved (both banks)")
            put(f"imperviousAreas{side}", True, "riparian_vegetation = bare_or_paved (both banks)")
    elif riparian == "patchy":
        not_carried.append("patchy bank vegetation: the app asks whether each bank is covered, and 'patchy' is neither")

    if a.ecology.families:
        overall = BAND_TO_OVERALL[a.ecology.band]
        put("overallAssessment", overall, f"the screening band ({a.ecology.band.value}), not the observer's own impression")
    else:
        overall = PRESSURE_TO_OVERALL.get(a.pressures.band, "MODERATE")
        put("overallAssessment", overall, f"the visual pressure ({a.pressures.band}), since no animals were identified")

    unconfirmed = sorted(r.key for r in (*a.pressures.readings, *a.pressures.exposure) if r.source != "citizen")
    if unconfirmed:
        not_carried.append(
            f"{len(unconfirmed)} answer(s) only the vision model gave ({', '.join(unconfirmed)}): confirm them in the review to carry them"
        )

    return {
        "target": "OneAquaHealth Citizen Science App",
        "endpoint": endpoint,
        "schema": schema,
        "research_site": site[0].as_dict(site[1]) if site else None,
        "body": body,
        "carried": carried,
        "not_carried": [*not_carried, *NEVER_CARRIED],
        "vocabulary": reference()["version"],
        "note": (
            "Built from the app's published answer codes. Only answers a person gave or confirmed are carried. "
            "Submitting needs an app account; AquaPlot prepares the body and does not send it."
        ),
    }
