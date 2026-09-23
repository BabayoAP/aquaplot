"""Stage 3, species identification (PRD §6.3), behind one small interface.

Three backends implement ``Identifier``:

* ``ClaudeIdentifier``: the Claude API with structured output. Best accuracy,
  needs ``ANTHROPIC_API_KEY``. The natural choice for the deployed live link.
* ``OllamaIdentifier``: a local vision-language model served by Ollama. Keyless
  and offline, usable on a laptop in the field, accuracy depends on the model.
* ``NullIdentifier``: no model. Returns nothing so the pipeline falls back to the
  M0 placeholder and says so in the evidence trail.

``select_identifier`` picks by environment at startup so the same code runs on a
laptop with Ollama, a server with a Claude key, or a bare container. Whichever is
chosen is named in every result's evidence trail (PRD §5.2 transparency).

Both model backends answer with the *same* schema (``Identification``): ranked
candidates as scientific names with a confidence in [0, 1]. Names are then
resolved against iNaturalist's taxonomy in the status stage, so a model that
misspells or picks a synonym still lands on a real taxon or is rejected loudly.
"""

from __future__ import annotations

import base64
import io
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx
from PIL import Image
from pydantic import BaseModel, Field

from .schema import Region

MAX_SIDE = 1024  # px for Claude; enough for identification, keeps tokens and upload small
OLLAMA_MAX_SIDE = 512  # px; vision tokens scale with pixels and local models are slow
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "300"))

SYSTEM_PROMPT = """You are a field biologist identifying organisms for a freshwater citizen-science screening tool. Observations come from urban streams and their banks anywhere in the world.
Given a photo and/or a written description, name the most likely species. Consider plants, insects, fungi, aquatic species, vertebrates and microscopic organisms.
Rules:
- Use the accepted scientific (Latin binomial) name for each candidate. If only genus-level confidence is justified, give the genus and set rank to "genus".
- Rank up to five candidates, best first. Confidences are probabilities in [0, 1] that this candidate is correct; they need not sum to 1.
- Prefer species known to occur near the stated location when the image is ambiguous, but do not force it.
- Set framing to how the subject was photographed: microscopic, extreme_macro, close_up, mid_distance or far.
- If there is a photo, set subject_box to the tightest box around the main organism as [x0, y0, x1, y1], fractions of the image width and height from the top-left corner (0 to 1). Leave it empty when the subject fills the frame or nothing can be localized.
- Keep reasoning to one or two sentences about the diagnostic features you used.
- Never refuse; if the input is unusable, return an empty candidate list and say why in reasoning."""


class Candidate(BaseModel):
    scientific_name: str = Field(description="Latin binomial, or genus if rank is genus")
    common_name: str | None = None
    rank: Literal["species", "genus", "family"] = "species"
    confidence: float = Field(ge=0.0, le=1.0)


class Identification(BaseModel):
    candidates: list[Candidate] = Field(default_factory=list, description="Best first, at most five.")
    framing: Literal["microscopic", "extreme_macro", "close_up", "mid_distance", "far", "unknown"] = "unknown"
    subject_box: list[float] = Field(
        default_factory=list,
        description="[x0, y0, x1, y1] around the main organism as fractions of width and height; empty if none.",
    )
    reasoning: str = ""

    def box(self) -> tuple[float, float, float, float] | None:
        """The subject box if it is well-formed and strictly inside the frame, else None."""
        b = self.subject_box
        if len(b) != 4 or any(not (0.0 <= v <= 1.0) for v in b):
            return None
        x0, y0, x1, y1 = b
        if x1 - x0 < 0.01 or y1 - y0 < 0.01:
            return None
        return (x0, y0, x1, y1)


class IdentifyError(RuntimeError):
    """The model backend failed; the pipeline degrades to the placeholder."""


class Identifier(Protocol):
    name: str

    async def identify(self, image: Image.Image | None, description: str, region: Region) -> Identification: ...


def _user_text(description: str, region: Region) -> str:
    parts = []
    if region.source != "none":
        parts.append(f"Location: {region.lat:.3f}, {region.lon:.3f} ({region.where}).")
    else:
        parts.append("Location: unknown.")
    if description:
        parts.append(f"Observer's description: {description}")
    parts.append("Identify the organism.")
    return " ".join(parts)


def encode_jpeg(image: Image.Image, max_side: int = MAX_SIDE) -> bytes:
    img = image.copy()
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


# ---- Null ---------------------------------------------------------------------


class NullIdentifier:
    name = "none"

    async def identify(self, image, description, region) -> Identification:
        return Identification(reasoning="no species model configured")


# ---- Claude -------------------------------------------------------------------


class ClaudeIdentifier:
    """Claude with structured output. ``client`` is injectable for tests."""

    name = "claude"

    def __init__(self, client: Any = None, model: str = "claude-opus-5"):
        if client is None:
            import anthropic

            client = anthropic.AsyncAnthropic()
        self.client = client
        self.model = model

    async def identify(self, image, description, region) -> Identification:
        content: list[dict[str, Any]] = []
        if image is not None:
            data = base64.standard_b64encode(encode_jpeg(image)).decode()
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
        content.append({"type": "text", "text": _user_text(description, region)})
        try:
            # Opus 5 thinks by default and thinking counts against max_tokens, so
            # the cap is well above what the JSON itself needs.
            response = await self.client.messages.parse(
                model=self.model,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
                output_format=Identification,
                output_config={"effort": "medium"},
            )
        except Exception as exc:  # anthropic.APIError and friends; the caller only needs "it failed"
            raise IdentifyError(f"Claude request failed: {exc}") from exc
        if getattr(response, "stop_reason", None) == "refusal":
            raise IdentifyError("Claude declined to answer")
        parsed = response.parsed_output
        if parsed is None:
            raise IdentifyError("Claude returned no structured output")
        return parsed


# ---- Ollama -------------------------------------------------------------------

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
VISION_MODEL_HINTS = ("vl", "llava", "vision", "gemma3", "minicpm-v", "moondream", "bakllava")

Poster = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


async def ollama_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        try:
            res = await client.post(f"{OLLAMA_URL}{path}", json=body)
            res.raise_for_status()
            return res.json()
        except httpx.TimeoutException as exc:
            raise IdentifyError(f"Ollama timed out after {OLLAMA_TIMEOUT:.0f}s; the model may be too large for this machine") from exc
        except httpx.HTTPError as exc:
            raise IdentifyError(f"Ollama request failed: {exc or exc.__class__.__name__}") from exc


def detect_ollama_vision_model(timeout: float = 1.5) -> str | None:
    """A vision-capable model already pulled into a running Ollama, else None."""
    override = os.environ.get("OLLAMA_MODEL")
    if override:
        return override
    try:
        tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=timeout).json()
    except Exception:
        return None
    for m in tags.get("models", []):
        name = m.get("name", "")
        if any(h in name.lower() for h in VISION_MODEL_HINTS):
            return name
    return None


@dataclass
class OllamaIdentifier:
    model: str
    post: Poster = ollama_post
    name: str = "ollama"

    async def identify(self, image, description, region) -> Identification:
        message: dict[str, Any] = {"role": "user", "content": _user_text(description, region)}
        if image is not None:
            message["images"] = [base64.standard_b64encode(encode_jpeg(image, OLLAMA_MAX_SIDE)).decode()]
        body = {
            "model": self.model,
            "stream": False,
            "format": Identification.model_json_schema(),
            "keep_alive": "30m",  # a reload costs more than the answer on small machines
            "options": {"temperature": 0, "num_predict": 320},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, message],
        }
        raw = await self.post("/api/chat", body)
        text = (raw.get("message") or {}).get("content", "")
        try:
            return Identification.model_validate(json.loads(text))
        except (ValueError, TypeError) as exc:
            raise IdentifyError(f"Ollama returned malformed output: {exc}") from exc


# ---- selection ----------------------------------------------------------------


def select_identifier(env: dict[str, str] | None = None) -> Identifier:
    """``AQUAPLOT_IDENTIFIER`` (claude | ollama | none) forces a backend; otherwise
    Claude if a key is present, else a local Ollama vision model, else none."""
    env = os.environ if env is None else env
    forced = env.get("AQUAPLOT_IDENTIFIER", "").lower()
    if forced == "none":
        return NullIdentifier()
    if forced == "claude" or (not forced and env.get("ANTHROPIC_API_KEY")):
        return ClaudeIdentifier(model=env.get("CLAUDE_MODEL", "claude-opus-5"))
    if forced == "ollama":
        return OllamaIdentifier(model=env.get("OLLAMA_MODEL") or detect_ollama_vision_model() or "qwen2.5vl:3b")
    model = detect_ollama_vision_model()
    if model:
        return OllamaIdentifier(model=model)
    return NullIdentifier()
