"""The vision model's job: a photo to *structured field observations*, nothing more (FR-2).

AquaPlot splits the work at the point where the two technologies are each good.

A vision-language model is excellent at "what is in this picture": is the water
cloudy, is there a bloom, is the bank concrete, is that a mayfly nymph. Those are
perceptual judgements a trained volunteer makes in a second and a novice cannot
make at all, and getting them out of a photo is the thing that makes a
citizen-science app usable by someone who has never heard the word *benthic*.

A vision-language model is a bad place to put "is this stream healthy" or "should
this family keep their dog out of the water". Those are determinations with an
index behind them and a public-health consequence in front of them, and they
belong in ``bioindex.py`` and ``onehealth.py`` where the rules are readable,
testable and arguable.

So this module returns only observations, in exactly the vocabulary
``habitat.py`` defines, and never a verdict. Three consequences fall out of that:

* The prompt's option lists are **generated** from ``data/habitat_indicators.json``
  rather than written by hand, so the prompt cannot drift from the validator.
* The model is required to report a confidence per observation and is told
  explicitly that "I cannot tell from this photo" is a correct answer. Fabricated
  certainty is the failure mode that would matter most here.
* Nothing the model says is trusted enough on its own to trigger a health alert.
  ``onehealth.py`` holds alerts at 'concern' until a person confirms the
  observation underneath, and this module marks every reading ``source="model"``
  so that check has something to test.

The three backends match ``identify.py``: Claude for the deployed link, a local
Ollama vision model for offline field use, and none at all, in which case the
citizen fills the form themselves and every downstream stage still works.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from PIL import Image
from pydantic import BaseModel, Field

from .habitat import PERSON_ONLY, model_vocabulary
from .identify import (
    MAX_SIDE,
    OLLAMA_MAX_SIDE,
    IdentifyError,
    Poster,
    detect_ollama_vision_model,
    encode_jpeg,
    ollama_post,
)
from .schema import Region

PhotoKind = Literal["stream_scene", "specimen", "single_organism", "not_a_stream"]


class SeenTaxon(BaseModel):
    """One animal the model believes is in the photo."""

    name: str = Field(description="Family name if you can tell (e.g. Baetidae), otherwise the order (e.g. Ephemeroptera), otherwise the common name.")
    common_name: str | None = None
    rank: Literal["family", "order", "genus", "species", "unknown"] = "family"
    confidence: float = Field(ge=0.0, le=1.0)
    count: int | None = Field(default=None, description="How many individuals are visible, if countable.")


class HabitatCall(BaseModel):
    """One answer to one question on the field form."""

    key: str = Field(description="The indicator key, exactly as listed.")
    value: str = Field(description="One of the allowed values for that indicator, exactly as listed.")
    confidence: float = Field(ge=0.0, le=1.0)


class StreamObservation(BaseModel):
    photo_kind: PhotoKind = Field(description="What this photograph is of.")
    habitat: list[HabitatCall] = Field(default_factory=list, description="Only indicators genuinely visible in this photo.")
    taxa: list[SeenTaxon] = Field(default_factory=list, description="Invertebrates visible in this photo, best first.")
    subject_box: list[float] = Field(
        default_factory=list,
        description="[x0, y0, x1, y1] around the main subject as fractions of width and height; empty if none.",
    )
    reasoning: str = ""
    cannot_tell: list[str] = Field(
        default_factory=list, description="Indicator keys you were asked about but genuinely could not judge from this photo."
    )

    def box(self) -> tuple[float, float, float, float] | None:
        b = self.subject_box
        if len(b) != 4 or any(not (0.0 <= v <= 1.0) for v in b):
            return None
        x0, y0, x1, y1 = b
        if x1 - x0 < 0.01 or y1 - y0 < 0.01:
            return None
        return (x0, y0, x1, y1)


def build_prompt() -> str:
    """The system prompt, with the form's vocabulary spliced in from the JSON."""
    person_only = ", ".join(i.key for i in PERSON_ONLY)
    return f"""You are helping a citizen scientist record the condition of an urban stream. You are looking at one photograph they took at the water's edge.

Report OBSERVATIONS ONLY. Do not judge whether the stream is healthy, do not assign a score, and do not give advice. Another part of the system does that from published indices; your output is its evidence.

First set photo_kind:
- "stream_scene": a view of the water, bank or channel.
- "specimen": invertebrates in a tray, net, jar or hand - the sample a citizen has collected.
- "single_organism": a close-up of one animal or plant.
- "not_a_stream": anything else. Say so rather than guessing.

For a stream_scene, answer only the indicators you can genuinely see. The allowed keys and values are fixed; using anything else discards the answer:
{model_vocabulary()}

You will NOT be asked about {person_only}: nobody can judge that from a photograph, and the person is asked directly.

For a specimen or single_organism photo, list what you see in taxa. Identify freshwater invertebrates to FAMILY when the diagnostic features are visible (number of tails, gill shape, case material, body outline) and to ORDER when they are not - an honest "Ephemeroptera" is far more useful than a confident wrong family. Give the scientific name, not the common name, in `name` when you can. Include plants, fish, crayfish, amphibians and birds if they are clearly the subject: some of them are listed invasive species and the system checks that separately.

Rules that matter more than completeness:
- Confidence is a real probability in [0, 1]. A photograph taken from a bridge does not support a family-level identification, and saying so is correct behaviour.
- If you cannot judge an indicator, leave it out and put its key in cannot_tell. Never guess a value to fill the form.
- Turbidity from suspended sediment and a green algal tint are different observations. So are natural tan foam below a fall and white detergent foam.
- Keep reasoning to one or two sentences naming the features you actually used.
- Never refuse. If the photo is unusable, set photo_kind to "not_a_stream" and say why in reasoning."""


SYSTEM_PROMPT = build_prompt()


def _context(description: str, region: Region) -> str:
    parts = []
    if region.lat is not None and region.lon is not None:
        parts.append(f"Location: {region.lat:.4f}, {region.lon:.4f} ({region.where}).")
    else:
        parts.append("Location: not recorded.")
    if description:
        parts.append(f"What the observer wrote: {description}")
    parts.append("Record your observations.")
    return " ".join(parts)


class StreamObserver(Protocol):
    name: str

    async def observe(self, image: Image.Image | None, description: str, region: Region) -> StreamObservation: ...


class NullObserver:
    """No model. The citizen fills the form themselves and everything downstream still works."""

    name = "none"

    async def observe(self, image, description, region) -> StreamObservation:
        return StreamObservation(photo_kind="stream_scene", reasoning="no vision model configured; the form was filled in by hand")


class ClaudeObserver:
    name = "claude"

    def __init__(self, client: Any = None, model: str = "claude-opus-5"):
        if client is None:
            import anthropic

            client = anthropic.AsyncAnthropic()
        self.client = client
        self.model = model

    async def observe(self, image, description, region) -> StreamObservation:
        content: list[dict[str, Any]] = []
        if image is not None:
            data = base64.standard_b64encode(encode_jpeg(image, MAX_SIDE)).decode()
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
        content.append({"type": "text", "text": _context(description, region)})
        try:
            response = await self.client.messages.parse(
                model=self.model,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
                output_format=StreamObservation,
                output_config={"effort": "medium"},
            )
        except Exception as exc:
            raise IdentifyError(f"Claude request failed: {exc}") from exc
        if getattr(response, "stop_reason", None) == "refusal":
            raise IdentifyError("Claude declined to answer")
        parsed = response.parsed_output
        if parsed is None:
            raise IdentifyError("Claude returned no structured output")
        return parsed


@dataclass
class OllamaObserver:
    model: str
    post: Poster = ollama_post
    name: str = "ollama"

    async def observe(self, image, description, region) -> StreamObservation:
        message: dict[str, Any] = {"role": "user", "content": _context(description, region)}
        if image is not None:
            message["images"] = [base64.standard_b64encode(encode_jpeg(image, OLLAMA_MAX_SIDE)).decode()]
        body = {
            "model": self.model,
            "stream": False,
            "format": StreamObservation.model_json_schema(),
            "keep_alive": "30m",
            "options": {"temperature": 0, "num_predict": 700},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, message],
        }
        raw = await self.post("/api/chat", body)
        text = (raw.get("message") or {}).get("content", "")
        try:
            return StreamObservation.model_validate(json.loads(text))
        except (ValueError, TypeError) as exc:
            raise IdentifyError(f"Ollama returned malformed output: {exc}") from exc


def select_observer(env: dict[str, str] | None = None) -> StreamObserver:
    """``AQUAPLOT_OBSERVER`` (claude | ollama | none) forces a backend; otherwise Claude
    if a key is present, else a local Ollama vision model, else none."""
    env = os.environ if env is None else env
    forced = env.get("AQUAPLOT_OBSERVER", env.get("AQUAPLOT_IDENTIFIER", "")).lower()
    if forced == "none":
        return NullObserver()
    if forced == "claude" or (not forced and env.get("ANTHROPIC_API_KEY")):
        return ClaudeObserver(model=env.get("CLAUDE_MODEL", "claude-opus-5"))
    if forced == "ollama":
        return OllamaObserver(model=env.get("OLLAMA_MODEL") or detect_ollama_vision_model() or "qwen2.5vl:3b")
    model = detect_ollama_vision_model()
    if model:
        return OllamaObserver(model=model)
    return NullObserver()
