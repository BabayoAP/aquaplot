"""Output contract for a classification (PRD §5.1 FR-8, §5.2 Transparency, §6.4).

This shape is fixed in M0, before any model exists, so that the interface and
every later milestone build against the same result. Two PRD rules drive it:

* The system *always* commits to one of three labels with a certainty
  percentage. There is no "needs review" label, so the certainty number carries
  all the honesty (PRD §9). ``certainty`` is therefore mandatory, not optional.
* Every result carries an evidence trail: what was detected, which species were
  considered, which status source and version was consulted, and what pulled the
  certainty down. That trail is what makes a fully automated call auditable later.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Label(StrEnum):
    NATIVE = "Native"
    INVASIVE = "Invasive"
    NATURALIZED = "Naturalized/Non-native"


class Regime(StrEnum):
    """Framing regime (PRD §6.1). ``unknown`` exists only for the text path."""

    MICROSCOPIC = "microscopic"
    EXTREME_MACRO = "extreme_macro"
    CLOSE_UP = "close_up"
    MID_DISTANCE = "mid_distance"
    FAR = "far"
    UNKNOWN = "unknown"


class Region(BaseModel):
    """Where the observation was made, at the coarseness v1 needs (PRD §7)."""

    source: Literal["exif", "user", "none"]
    lat: float | None = None
    lon: float | None = None
    in_orange_county: bool | None = Field(
        default=None,
        description="None when no coordinates were available at all.",
    )


class SpeciesCandidate(BaseModel):
    scientific_name: str
    common_name: str | None = None
    rank: Literal["species", "genus", "family"] = "species"
    confidence: float = Field(ge=0.0, le=1.0)
    taxon_id: int | None = Field(default=None, description="iNaturalist taxon id once resolved.")
    photo: str | None = None
    inat_url: str | None = None


class Evidence(BaseModel):
    detections: int = Field(description="Organisms localized in the frame (0 for text input).")
    subject_box: list[float] | None = Field(
        default=None,
        description="Where the model found the subject: [x0, y0, x1, y1] as fractions of the oriented frame (PRD §6.2).",
    )
    identified_from_crop: bool = Field(
        default=False,
        description="True when the subject was small in the frame and the final identification came from a crop of it.",
    )
    candidates_considered: list[SpeciesCandidate] = []
    status_source: str | None = None
    status_db_version: str | None = None
    establishment: str | None = Field(default=None, description="native | introduced | endemic as recorded by the status source.")
    status_place: str | None = Field(default=None, description="Which place the status answer came from.")
    identifier: str | None = Field(default=None, description="Which species model answered: claude | ollama | none.")
    reasoning: str | None = Field(default=None, description="The model's one-line justification.")
    certainty_penalties: list[str] = Field(
        default_factory=list,
        description="Human-readable reasons the certainty is lower than it could be.",
    )


class Classification(BaseModel):
    input_kind: Literal["image", "text"]
    regime: Regime
    region: Region
    label: Label
    certainty: float = Field(ge=0.0, le=100.0, description="Percent, calibrated (PRD §9).")
    top_candidate: SpeciesCandidate | None = None
    evidence: Evidence
    pipeline_version: str
