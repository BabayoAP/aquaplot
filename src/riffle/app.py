"""HTTP surface for the single-page app (PRD §5.0, M0) and the area viewer (docs/AREA-VIEWER.md).

Classification: one endpoint does the work. It accepts an image, a description,
or both; when both arrive the image wins because the text path is strictly lower
confidence (PRD §9) and exists only as a fallback for when no usable image
exists (FR-2).

Area viewer: thin routes over ``AreaService``. Query validation lives in
``AreaQuery`` so a bad viewport or an unknown taxa group is a 422 here and a
``ValueError`` everywhere else.

Classification is rate-limited per client address because the deployed demo
runs with a paid model key and no accounts. The limit is generous for a person
and cheap for a script to hit; ``RIFFLE_CLASSIFY_LIMIT=0`` disables it.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .area import AreaError, AreaQuery, AreaService, BBox, Status
from .identify import select_identifier
from .inputs import InvalidImage, decode_image, resolve_region
from .pipeline import PIPELINE_VERSION, Pipeline
from .places import OrangeCountyPlace
from .schema import Classification
from .status import StatusResolver

STATIC_DIR = Path(__file__).parent / "static"
CLASSIFY_LIMIT = int(os.environ.get("RIFFLE_CLASSIFY_LIMIT", "20"))  # requests per client per window
CLASSIFY_WINDOW_SECONDS = 600


@dataclass
class RateLimiter:
    """Sliding-window counter per client key, in memory (one process, no accounts)."""

    limit: int = CLASSIFY_LIMIT
    window: float = CLASSIFY_WINDOW_SECONDS
    _hits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))

    def retry_after(self, key: str, now: float | None = None) -> float:
        """0 if the request is allowed (and recorded), else seconds until the next slot."""
        if self.limit <= 0:
            return 0.0
        now = time.monotonic() if now is None else now
        q = self._hits[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return q[0] + self.window - now
        q.append(now)
        return 0.0


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")  # Render, Fly and Railway sit behind a proxy
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


app = FastAPI(title="SpeciesGuard", version=PIPELINE_VERSION)
app.state.area = AreaService()
app.state.pipeline = Pipeline(
    identifier=select_identifier(),
    status=StatusResolver(app.state.area.inat),
    places=OrangeCountyPlace(app.state.area.inat),
)
app.state.limiter = RateLimiter()


@app.get("/api/health")
def health() -> dict[str, str | int]:
    return {
        "status": "ok",
        "pipeline_version": PIPELINE_VERSION,
        "identifier": app.state.pipeline.identifier.name,
        "status_seed": app.state.area.seed_version,
        "classify_limit_per_10min": app.state.limiter.limit,
    }


async def _upstream(coro):
    try:
        return await coro
    except AreaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/classify", response_model=Classification)
async def classify(
    request: Request,
    image: UploadFile | None = File(default=None),
    description: str | None = Form(default=None),
    lat: float | None = Form(default=None),
    lon: float | None = Form(default=None),
) -> Classification:
    description = (description or "").strip()
    # Browsers submit an empty file part when the picker was left untouched.
    image_bytes = await image.read() if image is not None else b""
    if not image_bytes and not description:
        raise HTTPException(status_code=422, detail="provide an image or a description")

    wait = app.state.limiter.retry_after(client_key(request))
    if wait > 0:
        raise HTTPException(
            status_code=429,
            detail=f"too many classifications from this address; try again in {max(1, round(wait / 60))} min",
            headers={"Retry-After": str(int(wait) + 1)},
        )

    if image_bytes:
        try:
            decoded = decode_image(image_bytes)
        except InvalidImage as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        region = resolve_region(decoded.gps, lat, lon)
        return await _upstream(app.state.pipeline.classify(decoded, description, region))

    region = resolve_region(None, lat, lon)
    return await _upstream(app.state.pipeline.classify(None, description, region))


# ---- Area viewer -----------------------------------------------------------


def _area_query(
    south: float | None = None,
    west: float | None = None,
    north: float | None = None,
    east: float | None = None,
    oc: bool = Query(default=False, description="Restrict to the Orange County polygon"),
    taxa: str | None = Query(default=None, description="Comma-separated iconic taxa, e.g. Plantae,Insecta"),
    year_from: int | None = Query(default=None, ge=1900, le=2100),
    year_to: int | None = Query(default=None, ge=1900, le=2100),
    limit: int = Query(default=200, ge=1, le=200),
    taxon_id: int | None = Query(default=None, ge=1),
) -> AreaQuery:
    try:
        bbox = None
        if any(v is not None for v in (south, west, north, east)):
            if None in (south, west, north, east):
                raise ValueError("south, west, north and east must all be given")
            bbox = BBox(south=south, west=west, north=north, east=east)  # type: ignore[arg-type]
        groups = tuple(t.strip() for t in taxa.split(",") if t.strip()) if taxa else ()
        return AreaQuery(
            bbox=bbox, orange_county_only=oc, taxa=groups, year_from=year_from, year_to=year_to, limit=limit, taxon_id=taxon_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


AreaQueryDep = Annotated[AreaQuery, Depends(_area_query)]


@app.get("/api/area/observations")
async def area_observations(query: AreaQueryDep, status: Status = "introduced"):
    return await _upstream(app.state.area.observations(query, status))


@app.get("/api/area/species")
async def area_species(query: AreaQueryDep, status: Status = "introduced", top: int = Query(default=15, ge=1, le=50)):
    return await _upstream(app.state.area.species(query, status, top))


@app.get("/api/area/trend")
async def area_trend(query: AreaQueryDep):
    return await _upstream(app.state.area.trend(query))


@app.get("/api/area/listed")
def area_listed():
    return app.state.area.listed_taxa()


# ---- Pages -----------------------------------------------------------------


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/map", include_in_schema=False)
def map_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "map.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
