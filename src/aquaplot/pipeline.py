"""The four-stage pipeline (PRD §6): localize, identify, resolve status, combine.

Stage 1 (regime) is answered by the identifier as a side output and the region
is refined against the county polygon (``places.py``). Stage 2 (detection and
cropping, PRD §6.2) uses the same vision model as a detector: the first pass
returns a subject box along with its candidates, and when the subject is small
in the frame the pipeline crops to it and identifies again, keeping whichever
pass was more confident. That is the detect → crop → classify pattern the PRD
cites from camera-trap pipelines, without a second model. Stage 3 is
``identify.py``; Stage 4 is ``status.py``. This module owns the one rule the
PRD cares most about (FR-8, §9): the system always commits to a label and a
certainty, and the certainty must honestly shrink with every weakness in the
evidence.

Certainty, in percent, is the product of five factors:

    species confidence  (the model's own probability for the top candidate)
  × status confidence   (how authoritative the status source was, status.py)
  × region factor       (1.0 inside Orange County, less when outside or unknown)
  × input factor        (1.0 for a photo, 0.7 for text only, PRD §9)
  × regime factor       (1.0 close, less for mid-distance and far shots, PRD §9)

Every factor below 1.0 appears as a sentence in ``evidence.certainty_penalties``
so the user can see what pulled the number down. These factors are priors, not
measured calibration; PRD §8 makes calibration testing M7 work, and the
pipeline version string changes whenever the rule does so results are comparable.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .identify import Identification, Identifier, IdentifyError, NullIdentifier
from .inputs import DecodedImage
from .places import PlaceResolver
from .schema import Classification, Evidence, Label, Regime, Region, SpeciesCandidate
from .status import StatusResolver, StatusResult

PIPELINE_VERSION = "m4-crop-regime-v1"

REGION_FACTOR_IN = 1.0  # the place resolved, so the status question had a real jurisdiction
REGION_FACTOR_OUT = 0.8  # coordinates known, place lookup failed
REGION_FACTOR_UNKNOWN = 0.85  # no coordinates at all
INPUT_FACTOR_TEXT = 0.7
REGIME_FACTOR = {Regime.MID_DISTANCE: 0.92, Regime.FAR: 0.85}  # PRD §9: distant shots carry more error in v1

# Stage 2 thresholds. A subject under a quarter of the frame is worth a second
# look at full resolution; a crop smaller than this holds no extra detail.
CROP_MAX_AREA = 0.25
CROP_MARGIN = 0.15  # context kept around the box, as a fraction of the box size
CROP_MIN_SIDE = 64  # px


def _region_factor(region: Region) -> tuple[float, list[str]]:
    if region.source == "none":
        return REGION_FACTOR_UNKNOWN, [
            "no location was available, so native/introduced status could not be asked of any particular place"
        ]
    if region.place is None:
        return REGION_FACTOR_OUT, [
            "the coordinates could not be resolved to an administrative place, so the status answer is global rather than local"
        ]
    return REGION_FACTOR_IN, []


def _regime(framing: str) -> Regime:
    try:
        return Regime(framing)
    except ValueError:
        return Regime.UNKNOWN


def _regime_factor(regime: Regime) -> tuple[float, list[str]]:
    factor = REGIME_FACTOR.get(regime, 1.0)
    if factor < 1.0:
        return factor, [f"subject photographed at {regime.value.replace('_', ' ')} range; distant shots are less reliable in v1 (PRD §9)"]
    return 1.0, []


def crop_to_box(image: Image.Image, box: tuple[float, float, float, float], margin: float = CROP_MARGIN) -> Image.Image:
    """Crop the oriented frame to a normalized box, padded by ``margin`` of the box size and clamped to the image."""
    w, h = image.size
    x0, y0, x1, y1 = box
    bw, bh = (x1 - x0) * w, (y1 - y0) * h
    left = max(0, int((x0 * w) - margin * bw))
    top = max(0, int((y0 * h) - margin * bh))
    right = min(w, int((x1 * w) + margin * bw) + 1)
    bottom = min(h, int((y1 * h) + margin * bh) + 1)
    return image.crop((left, top, right, bottom))


def _top_confidence(ident: Identification) -> float:
    return max((c.confidence for c in ident.candidates), default=0.0)


@dataclass
class Pipeline:
    identifier: Identifier
    status: StatusResolver | None
    places: PlaceResolver | None = None

    async def classify(self, decoded: DecodedImage | None, description: str, region: Region) -> Classification:
        input_kind = "image" if decoded is not None else "text"
        penalties: list[str] = []
        image = decoded.image if decoded is not None else None

        # Stage 1: resolve the coordinates to an administrative place, which is
        # the jurisdiction every status question below is asked of.
        locality = None
        if self.places is not None:
            region = await self.places.refine(region)
            locality = await self.places.locality(region)

        # Stage 3 on the whole frame (also yields the Stage 2 subject box).
        try:
            ident = await self.identifier.identify(image, description, region)
        except IdentifyError as exc:
            ident = Identification(reasoning=str(exc))
            penalties.append(f"species model failed ({exc}); no identification")

        # Stage 2: if the subject is small in the frame, crop to it and look again.
        box = ident.box() if image is not None else None
        identified_from_crop = False
        if box is not None:
            x0, y0, x1, y1 = box
            crop = crop_to_box(image, box)
            if (x1 - x0) * (y1 - y0) < CROP_MAX_AREA and min(crop.size) >= CROP_MIN_SIDE:
                try:
                    second = await self.identifier.identify(crop, description, region)
                except IdentifyError:
                    second = None
                if second is not None and second.candidates and _top_confidence(second) >= _top_confidence(ident):
                    # Keep the whole-frame framing and box: they describe the photo, the crop does not.
                    ident = second.model_copy(update={"framing": ident.framing, "subject_box": ident.subject_box})
                    identified_from_crop = True

        candidates = [
            SpeciesCandidate(scientific_name=c.scientific_name, common_name=c.common_name, rank=c.rank, confidence=c.confidence)
            for c in sorted(ident.candidates, key=lambda c: c.confidence, reverse=True)[:5]
        ]
        if not candidates:
            return self._placeholder(input_kind, region, ident, penalties, box)

        top = candidates[0]

        # Stage 4: status
        if self.status is None:
            status = StatusResult(Label.NATURALIZED, 0.35, "none", "none", None, None, None, "no status source configured")
        else:
            status = await self.status.resolve(top.scientific_name, locality)
        if status.taxon is not None:
            top = top.model_copy(
                update={
                    "scientific_name": status.taxon.scientific_name,
                    "common_name": status.taxon.common_name or top.common_name,  # iNaturalist's name is canonical
                    "taxon_id": status.taxon.id,
                    "photo": status.taxon.photo,
                    "inat_url": f"https://www.inaturalist.org/taxa/{status.taxon.id}",
                }
            )
            candidates[0] = top
        if status.note:
            penalties.append(status.note)
        if top.rank != "species":
            penalties.append(f"identification is only confident to {top.rank} level")
        if top.confidence < 0.6:
            penalties.append("species model was unsure; several candidates were close")

        # Combine
        regime = _regime(ident.framing)
        region_factor, region_penalties = _region_factor(region)
        penalties += region_penalties
        input_factor = 1.0
        if input_kind == "text":
            input_factor = INPUT_FACTOR_TEXT
            penalties.append("text-only input is inherently lower confidence than an image (PRD §9)")
        regime_factor, regime_penalties = _regime_factor(regime)
        penalties += regime_penalties
        certainty = round(100 * top.confidence * status.confidence * region_factor * input_factor * regime_factor, 1)

        return Classification(
            input_kind=input_kind,
            regime=regime,
            region=region,
            label=status.label,
            certainty=max(0.0, min(100.0, certainty)),
            top_candidate=top,
            evidence=Evidence(
                detections=1,
                subject_box=list(box) if box is not None else None,
                identified_from_crop=identified_from_crop,
                candidates_considered=candidates,
                status_source=status.source,
                status_db_version=status.version,
                establishment=status.establishment,
                status_place=status.place,
                identifier=self.identifier.name,
                reasoning=ident.reasoning or None,
                certainty_penalties=penalties,
            ),
            pipeline_version=PIPELINE_VERSION,
        )

    def _placeholder(
        self, input_kind: str, region: Region, ident: Identification, penalties: list[str], box: tuple[float, ...] | None = None
    ) -> Classification:
        # FR-8: never withhold a label. Naturalized is the one label that prompts
        # neither removal nor protection, so it is the least harmful guess.
        if isinstance(self.identifier, NullIdentifier):
            penalties.insert(0, "no species model configured on this server; label is the neutral placeholder")
        elif not penalties:
            penalties.append(f"species model could not identify an organism: {ident.reasoning or 'no reason given'}")
        _, region_penalties = _region_factor(region)
        penalties += region_penalties
        if input_kind == "text":
            penalties.append("text-only input is inherently lower confidence than an image (PRD §9)")
        return Classification(
            input_kind=input_kind,
            regime=_regime(ident.framing),
            region=region,
            label=Label.NATURALIZED,
            certainty=0.0,
            top_candidate=None,
            evidence=Evidence(
                detections=0,
                subject_box=list(box) if box is not None else None,
                identifier=self.identifier.name,
                reasoning=ident.reasoning or None,
                certainty_penalties=penalties,
            ),
            pipeline_version=PIPELINE_VERSION,
        )
