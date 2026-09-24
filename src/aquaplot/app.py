"""HTTP surface: the stream assessment, the area viewer and the inherited classifier.

Three groups of routes, and the split says what AquaPlot is.

``/api/assess`` and its neighbours are the product: photos and answers in, a
banded One Health read-out out, stored so the next visit to the same spot becomes
a trend. ``/api/assess/{id}/review`` is the human half of the loop and never
re-runs the model - re-running it would let the model overwrite the correction a
person just made.

``/api/sites``, ``/api/insights`` and ``/api/alerts`` are the data-to-insight
surface the dashboard and the map draw from, and ``/api/assess/{id}/fhir``
exports a single assessment into the standard the health systems on the other
side of the One Health link already speak.

``/api/classify`` and ``/api/area/*`` are inherited from SpeciesGuard and kept
working: identifying an organism and browsing what has been recorded nearby are
both still useful, and the invasive check in a stream assessment runs through the
same status resolver.

Classification: one endpoint does the work. It accepts an image, a description,
or both; when both arrive the image wins because the text path is strictly lower
confidence (PRD §9) and exists only as a fallback for when no usable image
exists (FR-2).

Area viewer: thin routes over ``AreaService``. Query validation lives in
``AreaQuery`` so a bad viewport or an unknown taxa group is a 422 here and a
``ValueError`` everywhere else.

Classification is rate-limited per client address because the deployed demo
runs with a paid model key and no accounts. The limit is generous for a person
and cheap for a script to hit; ``AQUAPLOT_CLASSIFY_LIMIT=0`` disables it.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field

from . import bioindex, fhir, habitat, onehealth, report
from .area import AreaError, AreaQuery, AreaService, BBox, Status
from .assess import ASSESSMENT_VERSION, Assessment, Review, StreamAssessor, Submission, reassess
from .identify import select_identifier
from .inputs import InvalidImage, decode_image, resolve_region
from .observe import select_observer
from .pipeline import PIPELINE_VERSION, Pipeline
from .places import PlaceResolver, pilot_sites
from .schema import Classification
from .status import StatusResolver
from .store import Store, site_key

STATIC_DIR = Path(__file__).parent / "static"
CLASSIFY_LIMIT = int(os.environ.get("AQUAPLOT_CLASSIFY_LIMIT", "20"))  # requests per client per window
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


app = FastAPI(
    title="AquaPlot",
    version=ASSESSMENT_VERSION,
    description=(
        "Guided citizen stream checks. A photo and a few plain-language answers become a "
        "BMWP/ASPT biological band, a visual pressure score and a One Health read-out for "
        "people, animals and the ecosystem - with every finding traceable to the observation "
        "behind it. Built for the IEEE OneAquaHealth Global Hackathon 2026."
    ),
)
app.state.area = AreaService()
app.state.pipeline = Pipeline(
    identifier=select_identifier(),
    status=StatusResolver(app.state.area.inat),
    places=PlaceResolver(app.state.area.inat),
)
app.state.limiter = RateLimiter()
app.state.store = Store()
app.state.assessor = StreamAssessor(
    observer=select_observer(),
    status=StatusResolver(app.state.area.inat),
    places=PlaceResolver(app.state.area.inat),
)


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "assessment_version": ASSESSMENT_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "observer": app.state.assessor.observer.name,
        "identifier": app.state.pipeline.identifier.name,
        "status_seed": app.state.area.seed_version,
        "bioindicator_catalogue": bioindex.CATALOGUE_VERSION,
        "habitat_form": habitat.FORM_VERSION,
        "assessments_stored": app.state.store.summary()["assessments"],
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


# ---- Stream assessment -------------------------------------------------------


class ReviewBody(BaseModel):
    """What a person changed after reading what the model proposed."""

    answers: dict[str, str] = Field(default_factory=dict, description="Habitat indicator key to the value the person chose.")
    confirmed_taxa: list[str] = Field(default_factory=list, description="Names the person confirmed.")
    rejected_taxa: list[str] = Field(default_factory=list, description="Names the person says are wrong; removed from the index.")
    added_taxa: list[str] = Field(default_factory=list, description="Animals the person found that the model missed.")
    site_name: str | None = None


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def contributor_of(request: Request) -> str | None:
    """An opaque id the browser generates and keeps. No account, no way back to a person."""
    value = (request.headers.get("x-aquaplot-contributor") or "").strip()
    return value[:64] or None


def _readings(raw: str | None, source: str) -> list[habitat.Reading]:
    """Parse ``{"algae": "bloom", ...}`` into form answers, rejecting unknown keys loudly."""
    if not raw:
        return []
    try:
        answers = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"answers must be a JSON object: {exc}") from exc
    if not isinstance(answers, dict):
        raise HTTPException(status_code=422, detail="answers must be a JSON object of indicator to value")
    unknown = [k for k in answers if k not in habitat.BY_KEY]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown habitat indicator(s): {', '.join(sorted(unknown))}")
    return [habitat.Reading(key=k, value=str(v), source=source) for k, v in answers.items()]


def _taxa(raw: str | None) -> list[bioindex.TaxonObservation]:
    if not raw:
        return []
    try:
        names = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"taxa must be a JSON array of names: {exc}") from exc
    if not isinstance(names, list):
        raise HTTPException(status_code=422, detail="taxa must be a JSON array of names")
    return [bioindex.TaxonObservation(name=str(n), confidence=1.0, confirmed_by="citizen") for n in names if str(n).strip()]


@app.post("/api/assess", tags=["assessment"])
async def assess(
    request: Request,
    photos: list[UploadFile] = File(default_factory=list, description="One or more photos: the reach, and the sample tray."),
    description: str | None = Form(default=None),
    lat: float | None = Form(default=None),
    lon: float | None = Form(default=None),
    site_name: str | None = Form(default=None),
    answers: str | None = Form(default=None, description='JSON object of habitat answers, e.g. {"odour": "sewage"}'),
    taxa: str | None = Form(default=None, description='JSON array of invertebrate names the observer identified'),
):
    """Assess one stream visit.

    Everything is optional except having *something*: a photo, a habitat answer or
    a taxon name. A visit with no photo and no model still produces a band, a
    pressure score and a One Health read-out, because a citizen who filled the
    form by hand has done the real work either way.
    """
    citizen_answers = _readings(answers, "citizen")
    citizen_taxa = _taxa(taxa)
    blobs = [b for b in [await p.read() for p in photos] if b]
    if not blobs and not citizen_answers and not citizen_taxa and not (description or "").strip():
        raise HTTPException(status_code=422, detail="send at least a photo, a habitat answer or a species name")

    wait = app.state.limiter.retry_after(client_key(request))
    if wait > 0:
        raise HTTPException(
            status_code=429,
            detail=f"too many assessments from this address; try again in {max(1, round(wait / 60))} min",
            headers={"Retry-After": str(int(wait) + 1)},
        )

    decoded = []
    gps = None
    for blob in blobs:
        try:
            image = decode_image(blob)
        except InvalidImage as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        decoded.append(image)
        gps = gps or image.gps  # the first photo carrying GPS wins; it is the one taken at the water

    result = await _upstream(
        app.state.assessor.assess(
            Submission(
                photos=tuple(decoded),
                description=(description or "").strip(),
                region=resolve_region(gps, lat, lon),
                answers=tuple(citizen_answers),
                taxa=tuple(citizen_taxa),
                site_name=(site_name or "").strip() or None,
            )
        )
    )
    app.state.store.save(result, contributor_of(request))
    return result.as_dict()


@app.get("/api/assess/{assessment_id}", tags=["assessment"])
def get_assessment(assessment_id: str):
    stored = app.state.store.get(assessment_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="no assessment with that id")
    return stored


@app.post("/api/assess/{assessment_id}/review", tags=["assessment"])
async def review_assessment(assessment_id: str, body: ReviewBody, request: Request):
    """Fold a person's confirmations and corrections into a stored assessment.

    The vision model is deliberately not called again. The photograph has not
    changed, and a second model pass could quietly overwrite the correction the
    person just made - which would make the review theatre rather than review.
    """
    previous = app.state.store.get(assessment_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="no assessment with that id")
    unknown = [k for k in body.answers if k not in habitat.BY_KEY]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown habitat indicator(s): {', '.join(sorted(unknown))}")
    result = await reassess(
        previous,
        Review(
            answers=tuple(habitat.Reading(key=k, value=v, source="citizen") for k, v in body.answers.items()),
            confirmed_taxa=tuple(body.confirmed_taxa),
            rejected_taxa=tuple(body.rejected_taxa),
            added_taxa=tuple(body.added_taxa),
            site_name=body.site_name,
        ),
    )
    app.state.store.save(result, contributor_of(request))
    return result.as_dict()


@app.get("/api/assess/{assessment_id}/fhir", tags=["assessment", "interoperability"])
def assessment_as_fhir(assessment_id: str):
    """The assessment as a FHIR R4 collection Bundle (see docs/FHIR.md for the codes)."""
    stored = app.state.store.get(assessment_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="no assessment with that id")
    return fhir.bundle(_rehydrate(stored))


@app.get("/api/assess/{assessment_id}/report", response_class=HTMLResponse, tags=["assessment"], include_in_schema=True)
def assessment_report(assessment_id: str):
    """A printable incident report for a water authority or environmental regulator.

    Every serious finding tells the observer to report it. This is the thing they
    report *with*: self-contained, forwardable without editing, and readable by
    someone who has never heard of AquaPlot.
    """
    a, history = _stored_assessment(assessment_id)
    return HTMLResponse(report.printable(a, history))


@app.get("/api/assess/{assessment_id}/report.md", response_class=PlainTextResponse, tags=["assessment"])
def assessment_report_markdown(assessment_id: str):
    """The same report as Markdown, for pasting into a contact form or an email."""
    a, history = _stored_assessment(assessment_id)
    return PlainTextResponse(
        report.markdown(a, history),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="aquaplot-report-{a.id}.md"'},
    )


def _stored_assessment(assessment_id: str):
    stored = app.state.store.get(assessment_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="no assessment with that id")
    a = _rehydrate(stored)
    key = site_key(a.region.lat, a.region.lon)
    return a, (app.state.store.history(key) if key else [])


# ---- Sites, insights and early warning ---------------------------------------


@app.get("/api/sites", tags=["insight"])
def sites(
    south: float | None = None,
    west: float | None = None,
    north: float | None = None,
    east: float | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
):
    """Every monitored spot, with its latest band and whether it is improving or declining."""
    bbox = None
    if any(v is not None for v in (south, west, north, east)):
        if None in (south, west, north, east):
            raise HTTPException(status_code=422, detail="south, west, north and east must all be given")
        bbox = (south, west, north, east)
    return {"sites": app.state.store.sites(bbox, limit)}


@app.get("/api/sites/nearby", tags=["insight"])
def sites_nearby(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_m: float = Query(default=250, ge=10, le=5000),
):
    """Sites already monitored near a point, so a returning volunteer can say "same spot".

    The decision is put to the person rather than taken from them: only they know
    whether they are standing where they stood in June.
    """
    return {"nearby": app.state.store.nearby(lat, lon, radius_m)}


@app.get("/api/sites/{site_key}", tags=["insight"])
def site_history(site_key: str):
    history = app.state.store.history(site_key)
    if not history:
        raise HTTPException(status_code=404, detail="no assessments at that site")
    from .store import trend_of

    return {
        "site_key": site_key,
        "name": app.state.store.name_of(site_key) or history[0].get("site_name") or history[0].get("place_name"),
        "assessments": history,
        "trend": trend_of(history),
    }


@app.post("/api/sites/{site_key}/name", tags=["insight"])
def name_site(site_key: str, body: RenameBody):
    """Let the people who use a stretch call it what they call it, not what a gazetteer calls it."""
    if not app.state.store.history(site_key):
        raise HTTPException(status_code=404, detail="no assessments at that site")
    app.state.store.rename(site_key, body.name.strip())
    return {"site_key": site_key, "name": body.name.strip()}


@app.get("/api/insights", tags=["insight"])
def insights():
    """The numbers the dashboard leads with."""
    return app.state.store.summary()


@app.get("/api/alerts", tags=["insight"])
def alerts(days: int = Query(default=30, ge=1, le=365)):
    """Sites whose most recent assessment reached concern or alert: the early-warning feed."""
    return {"days": days, "alerts": app.state.store.alerts(days)}


@app.get("/api/export.csv", tags=["insight", "interoperability"])
def export_csv():
    """Every live assessment as CSV, for a spreadsheet or an R session.

    One row per assessment, superseded revisions excluded. This is the format a
    council officer or a university group will actually open, and refusing to
    provide it is how citizen-science data ends up stranded in someone's app.
    """
    rows = app.state.store.export_rows()
    columns = [
        "id", "created_at", "site_key", "site_name", "place_name", "lat", "lon", "band", "band_ordinal",
        "bmwp", "aspt", "families", "ept_families", "pressure", "certainty", "overall_level",
        "invasives", "confirmations", "observer", "version",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="aquaplot-assessments.csv"'},
    )


@app.get("/api/export.geojson", tags=["insight", "interoperability"])
def export_geojson():
    """Monitored sites as GeoJSON, for QGIS or any web map."""
    sites = app.state.store.sites()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                "properties": {
                    k: v for k, v in s.items() if k not in ("lat", "lon")
                } | {"trend": s["trend"]["direction"], "trend_detail": s["trend"]["detail"]},
            }
            for s in sites
            if s["lat"] is not None and s["lon"] is not None
        ],
        "properties": {
            "source": "AquaPlot citizen stream assessments",
            "caveat": "Screening estimates, not Water Framework Directive classifications.",
        },
    }


@app.get("/api/me/progress", tags=["engagement"])
def progress(request: Request):
    """One anonymous contributor's record and badges. Returns an empty record when no id is sent."""
    contributor = contributor_of(request)
    if contributor is None:
        return {"assessments": 0, "sites": 0, "confirmations": 0, "badges": [], "next": None}
    return app.state.store.progress(contributor)


# ---- Reference data the UI is generated from ---------------------------------


@app.get("/api/form", tags=["reference"])
def form():
    """The habitat field form. The guided workflow's questions are rendered from this."""
    return habitat.form_schema()


@app.get("/api/guide", tags=["reference"])
def guide():
    """The bioindicator catalogue: what to look for, and what finding it means."""
    return {
        "version": bioindex.CATALOGUE_VERSION,
        "index": "BMWP / ASPT",
        "families": [
            {
                "family": f.family,
                "plain_name": f.plain_name,
                "common_name": f.common_name,
                "group": f.group,
                "bmwp": f.bmwp,
                "sensitivity": f.sensitivity,
                "ept": f.ept,
                "look_for": f.look_for,
                "means": f.means,
                "vector": f.vector,
            }
            for f in sorted(bioindex.CATALOGUE, key=lambda f: (-f.bmwp, f.family))
        ],
    }


@app.get("/api/pilots", tags=["reference"])
def pilots():
    """The five OneAquaHealth research cities, as map and demo entry points."""
    return pilot_sites()


def _rehydrate(stored: dict[str, Any]) -> "Assessment":
    """Rebuild an Assessment object from a stored payload, for the FHIR exporter.

    The index, the pressures and the rules are recomputed from the stored
    observations rather than read back from the stored conclusions, so an exported
    bundle always matches what the current rules say about that evidence. The
    stored ``band`` and ``certainty`` stay authoritative for the row; this rebuild
    is for export, and the version that produced the row travels with it.
    """
    from .assess import Assessment, InvasiveHit, readings_of, taxa_of
    from .schema import Region as _Region

    ecology = bioindex.score(taxa_of(stored))
    pressures = habitat.assess(readings_of(stored))
    signal = onehealth.evaluate(
        onehealth.Context(
            status=ecology,
            habitat=pressures,
            invasives=tuple(i["name"] for i in stored.get("invasives", [])),
            site_name=stored.get("site_name"),
        )
    )
    seeded = {e.summary(): e for e in app.state.assessor.listed}
    return Assessment(
        id=stored["id"],
        created_at=stored["created_at"],
        site_name=stored.get("site_name"),
        region=_Region.model_validate(stored["region"]),
        photos=stored.get("photos", 0),
        photo_kinds=stored.get("photo_kinds", []),
        ecology=ecology,
        pressures=pressures,
        signal=signal,
        invasives=[
            InvasiveHit(
                name=i.get("reported_as", i["name"]),
                listed=seeded[i["name"]],
                confidence=i.get("confidence", 1.0),
                in_jurisdiction=i.get("listed_for_this_place", True),
                note=i.get("note"),
            )
            for i in stored.get("invasives", [])
            if i["name"] in seeded
        ],
        certainty=stored.get("certainty", 0.0),
        penalties=stored.get("penalties", []),
        needs_confirmation=stored.get("needs_confirmation", []),
        observer=stored.get("observer", "none"),
        model_notes=stored.get("model_notes", []),
        confirmations=stored.get("confirmations", 0),
        supersedes=stored.get("supersedes"),
        version=stored.get("version", ASSESSMENT_VERSION),
    )


# ---- Area viewer -----------------------------------------------------------


def _area_query(
    south: float | None = None,
    west: float | None = None,
    north: float | None = None,
    east: float | None = None,
    place_id: int | None = Query(default=None, ge=1, description="Restrict to an iNaturalist place (municipality, province, country)"),
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
            bbox=bbox, place_id=place_id, taxa=groups, year_from=year_from, year_to=year_to, limit=limit, taxon_id=taxon_id
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
    """The guided stream check. This is the product; everything else supports it."""
    return FileResponse(STATIC_DIR / "check.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/map", include_in_schema=False)
def map_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "map.html")


@app.get("/classify", include_in_schema=False)
def classify_page() -> FileResponse:
    """The inherited single-organism classifier, kept working (see README, lineage)."""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
