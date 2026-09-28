#!/usr/bin/env python3
"""Write the project CodeSystem and example FHIR bundles to docs/fhir/.

The examples are built through the real pipeline with a scripted stand-in for the
vision model, so they are exactly what the app exports. Validate them with the
official HL7 validator (https://github.com/hapifhir/org.hl7.fhir.core/releases):

    .venv/bin/python scripts/export_fhir_examples.py
    java -jar validator_cli.jar docs/fhir/examples/*.json docs/fhir/CodeSystem-stream-health.json \\
        -version 4.0.1 -ig docs/fhir/CodeSystem-stream-health.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from aquaplot import fhir
from aquaplot.assess import Review, StreamAssessor, Submission, reassess
from aquaplot.bioindex import TaxonObservation
from aquaplot.habitat import Reading
from aquaplot.observe import HabitatCall, NullObserver, SeenTaxon, StreamObservation
from aquaplot.schema import PlaceRef, Region

OUT = Path(__file__).resolve().parent.parent / "docs" / "fhir"
WHEN = datetime(2026, 9, 27, 10, 30, tzinfo=UTC)

COIMBRA = Region(
    source="user",
    lat=40.2056,
    lon=-8.4195,
    place=PlaceRef(id=1, name="Coimbra", display_name="Coimbra, Portugal", kind="municipality"),
    country=PlaceRef(id=2, name="Portugal", display_name="Portugal", kind="country"),
)
GHENT = Region(
    source="user",
    lat=51.0543,
    lon=3.7174,
    place=PlaceRef(id=3, name="Gent", display_name="Gent, Belgium", kind="municipality"),
    country=PlaceRef(id=4, name="Belgium", display_name="Belgium", kind="country"),
)


class Scripted:
    """Stands in for the vision model: the reach first, then the tray."""

    name = "example-model"

    def __init__(self, scene: StreamObservation, tray: StreamObservation):
        self.photos = [scene, tray]

    async def observe(self, image, description, region):
        return self.photos.pop(0)


class Photo:
    image = None
    gps = None


def citizen(*names: str) -> tuple[TaxonObservation, ...]:
    return tuple(TaxonObservation(name=n, confirmed_by="citizen") for n in names)


async def build() -> dict[str, object]:
    scene = StreamObservation(
        photo_kind="stream_scene",
        habitat=[
            HabitatCall(key="water_clarity", value="slightly_turbid", confidence=0.8),
            HabitatCall(key="algae", value="bloom", confidence=0.7),
            HabitatCall(key="flow", value="slow", confidence=0.8),
        ],
    )
    tray = StreamObservation(
        photo_kind="specimen",
        taxa=[SeenTaxon(name="Baetidae", confidence=0.8), SeenTaxon(name="Chironomidae", confidence=0.9)],
    )
    iberian = await StreamAssessor(observer=Scripted(scene, tray)).assess(
        Submission(
            photos=(Photo(), Photo()),
            region=COIMBRA,
            site_name="Ribeira de Coselhas (example)",
            taxa=citizen("Perlidae", "Chironomidae", "Culicidae"),
            answers=(Reading(key="access", value="contact", source="citizen"), Reading(key="odour", value="none", source="citizen")),
            when=WHEN,
        )
    )
    disagreement = iberian.second_opinion.open[0]
    reviewed = await reassess(iberian.as_dict(), Review(dismissed=(disagreement["key"],)))
    reviewed.created_at = WHEN.isoformat()
    by_hand = await StreamAssessor(observer=NullObserver()).assess(
        Submission(
            region=GHENT,
            site_name="Coupure, Gent (example)",
            taxa=citizen("Asellidae", "Oligochaeta", "Planorbidae"),
            answers=(Reading(key="odour", value="sewage", source="citizen"), Reading(key="access", value="contact", source="citizen")),
            when=WHEN,
        )
    )
    return {
        "citizen-identified-iberia": iberian,
        "citizen-identified-iberia-after-review": reviewed,
        "hand-filled-no-model-belgium": by_hand,
    }


def main() -> int:
    examples = OUT / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    (OUT / "CodeSystem-stream-health.json").write_text(json.dumps(fhir.code_system(), indent=2) + "\n", encoding="utf-8")
    for name, assessment in asyncio.run(build()).items():
        (examples / f"{name}.json").write_text(json.dumps(fhir.bundle(assessment), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {name}: {assessment.ecology.index.name}, band {assessment.ecology.band.value}, {assessment.signal.worst.value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
