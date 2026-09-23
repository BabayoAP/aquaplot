"""Area viewer (docs/AREA-VIEWER.md). No test here touches the network."""

import pytest
from fastapi.testclient import TestClient

from riffle.app import app
from riffle.area import AreaError, AreaQuery, AreaService, BBox, match_listed

OC_BBOX = BBox(south=33.38, west=-118.13, north=33.95, east=-117.41)


def obs(id_, name, common, lon, lat, iconic="Plantae", photo=True):
    return {
        "id": id_, "uri": f"https://www.inaturalist.org/observations/{id_}", "observed_on": "2026-09-14",
        "geojson": {"type": "Point", "coordinates": [lon, lat]}, "place_guess": "Irvine, CA",
        "taxon": {"id": id_ * 10, "name": name, "preferred_common_name": common, "rank": "species", "iconic_taxon_name": iconic},
        "photos": [{"url": "https://static.inaturalist.org/photos/1/square.jpg"}] if photo else [],
    }


CANNED = {
    "/observations": {
        "total_results": 3,
        "results": [
            obs(1, "Arundo donax", "Giant Reed", -117.8, 33.7),
            obs(2, "Solanum elaeagnifolium", "Silverleaf Nightshade", -117.9, 33.9, photo=False),
            {"id": 3, "geojson": None, "taxon": {"name": "Hidden"}},  # obscured location
        ],
    },
    "/observations/species_counts": {
        "results": [
            {"count": 40, "taxon": {"id": 10, "name": "Arundo donax", "preferred_common_name": "Giant Reed", "iconic_taxon_name": "Plantae", "default_photo": {"square_url": "x.jpg"}}},
            {"count": 7, "taxon": {"id": 20, "name": "Zosterops simplex", "preferred_common_name": "Swinhoe's White-eye", "iconic_taxon_name": "Aves"}},
        ]
    },
    "/observations/histogram": {"results": {"year": {"2023-01-01": 10, "2024-01-01": 20, "2025-01-01": 30}}},
}


class FakeFetch:
    def __init__(self):
        self.calls = []

    async def __call__(self, path, params):
        self.calls.append((path, dict(params)))
        if path == "/observations/histogram":
            scale = {"introduced": 1, "native": 3, "threatened": 0}[next(s for s in ("introduced", "native", "threatened") if s in params)]
            return {"results": {"year": {k: v * scale for k, v in CANNED[path]["results"]["year"].items()}}}
        return CANNED[path]


@pytest.fixture
def fake():
    return FakeFetch()


@pytest.fixture
def service(fake):
    return AreaService(fetch=fake)


@pytest.fixture
def client(service):
    app.state.area = service
    return TestClient(app)


# ---- query building -------------------------------------------------------


def test_bbox_rejects_inverted_or_out_of_range():
    with pytest.raises(ValueError):
        BBox(south=34, west=-118, north=33, east=-117)
    with pytest.raises(ValueError):
        BBox(south=33, west=-190, north=34, east=-117)


def test_query_needs_a_scope_and_known_taxa():
    with pytest.raises(ValueError, match="bounding box"):
        AreaQuery()
    with pytest.raises(ValueError, match="unknown taxa"):
        AreaQuery(bbox=OC_BBOX, taxa=("Dragons",))
    with pytest.raises(ValueError, match="year_from"):
        AreaQuery(bbox=OC_BBOX, year_from=2025, year_to=2020)


def test_params_carry_status_scope_taxa_and_years():
    q = AreaQuery(bbox=OC_BBOX, orange_county_only=True, taxa=("Insecta", "Plantae"), year_from=2020, year_to=2024)
    p = q.params("introduced")
    assert p["introduced"] == "true" and "native" not in p
    assert p["place_id"] == 2738 and p["swlat"] == 33.38 and p["nelng"] == -117.41
    assert p["iconic_taxa"] == "Insecta,Plantae"
    assert p["d1"] == "2020-01-01" and p["d2"] == "2024-12-31"
    assert p["quality_grade"] == "research"  # FR-A2: research-grade only


# ---- listed-invasive matching ---------------------------------------------


def test_listed_match_is_exact_or_subspecies(service):
    assert match_listed("Arundo donax", service.listed).rating == "High"
    assert match_listed("Trachemys scripta elegans", service.listed).source.startswith("USGS")
    assert match_listed("Arundo donaxii", service.listed) is None
    assert match_listed(None, service.listed) is None


def test_listed_match_accepts_synonyms(service):
    # iNaturalist's name for fountain grass and the Cal-IPC name must hit the same entry.
    entry = match_listed("Cenchrus setaceus", service.listed)
    assert entry is not None and match_listed("Pennisetum setaceum", service.listed) is entry
    assert match_listed("Rana catesbeiana", service.listed).common_name == "American Bullfrog"


def test_seed_is_well_formed(service):
    names = [e.scientific_name for e in service.listed]
    assert len(names) == len(set(names))
    for e in service.listed:
        assert e.rating in {"High", "Moderate", "Limited", "Listed"} and e.source and e.group
        assert len(e.scientific_name.split()) >= 2  # binomials only; genus-level entries would over-match


# ---- service ---------------------------------------------------------------


async def test_observations_become_geojson_and_drop_unplaceable(service):
    fc = await service.observations(AreaQuery(bbox=OC_BBOX), "introduced")
    assert fc["type"] == "FeatureCollection" and fc["total"] == 3
    assert len(fc["features"]) == 2  # obscured one dropped
    first = fc["features"][0]
    assert first["geometry"]["coordinates"] == [-117.8, 33.7]
    assert first["properties"]["listed"] == "High" and first["properties"]["listed_source"] == "Cal-IPC Inventory"
    assert first["properties"]["photo"].endswith("medium.jpg")
    assert fc["features"][1]["properties"]["listed"] is None
    assert fc["features"][1]["properties"]["photo"] is None


async def test_species_counts_are_tagged(service):
    rows = await service.species(AreaQuery(bbox=OC_BBOX), "introduced")
    assert rows[0]["count"] == 40 and rows[0]["listed"] == "High"
    assert rows[1]["listed"] is None and rows[1]["group"] == "Aves"


async def test_trend_aligns_years_and_computes_share(service, fake):
    t = await service.trend(AreaQuery(bbox=OC_BBOX, year_from=2024))
    assert t["years"] == ["2024", "2025"]
    assert t["introduced"] == [20, 30] and t["native"] == [60, 90] and t["threatened"] == [0, 0]
    assert t["introduced_share_pct"] == [25.0, 25.0]
    statuses = sorted(next(s for s in ("introduced", "native", "threatened") if s in p) for path, p in fake.calls if path.endswith("histogram"))
    assert statuses == ["introduced", "native", "threatened"]


async def test_trend_defaults_to_recent_window():
    async def old_records(path, params):
        return {"results": {"year": {f"{y}-01-01": 1 for y in range(1962, 2027)}}}

    svc = AreaService(fetch=old_records)
    t = await svc.trend(AreaQuery(bbox=OC_BBOX))
    assert t["years"] == [str(y) for y in range(2015, 2027)]
    t = await svc.trend(AreaQuery(bbox=OC_BBOX, year_from=1990, year_to=1992))
    assert t["years"] == ["1990", "1991", "1992"]  # an explicit range is honoured as given


async def test_trend_window_is_by_calendar_year_with_gaps_filled():
    async def sparse(path, params):
        return {"results": {"year": {"1982-01-01": 1, "2020-01-01": 5, "2026-01-01": 9}}}

    t = await AreaService(fetch=sparse).trend(AreaQuery(bbox=OC_BBOX))
    assert t["years"][0] == "2015" and t["years"][-1] == "2026" and len(t["years"]) == 12
    assert t["introduced"] == [0, 0, 0, 0, 0, 5, 0, 0, 0, 0, 0, 9]


async def test_trend_with_no_data_is_empty():
    async def nothing(path, params):
        return {"results": {"year": {}}}

    t = await AreaService(fetch=nothing).trend(AreaQuery(bbox=OC_BBOX))
    assert t["years"] == [] and t["introduced_share_pct"] == []


async def test_cache_serves_repeat_queries_until_ttl(fake):
    now = [0.0]
    svc = AreaService(fetch=fake, ttl=100, clock=lambda: now[0])
    q = AreaQuery(bbox=OC_BBOX)
    await svc.observations(q, "introduced")
    await svc.observations(q, "introduced")
    assert len(fake.calls) == 1
    await svc.observations(q, "native")  # different status is a different key
    assert len(fake.calls) == 2
    now[0] = 101
    await svc.observations(q, "introduced")
    assert len(fake.calls) == 3


async def test_upstream_failure_is_area_error():
    async def boom(path, params):
        raise AreaError("iNaturalist request failed: 503")

    svc = AreaService(fetch=boom)
    with pytest.raises(AreaError):
        await svc.observations(AreaQuery(bbox=OC_BBOX), "introduced")


# ---- HTTP ------------------------------------------------------------------


def test_map_page_serves(client):
    res = client.get("/map")
    assert res.status_code == 200
    assert "Area viewer" in res.text and "globalforestwatch" in res.text


def test_observations_endpoint(client):
    res = client.get("/api/area/observations", params={"south": 33.4, "west": -118, "north": 33.9, "east": -117.5, "status": "introduced", "taxa": "Plantae"})
    assert res.status_code == 200
    assert res.json()["features"][0]["properties"]["status"] == "introduced"


def test_orange_county_scope_without_bbox(client, fake):
    res = client.get("/api/area/species", params={"oc": "true", "status": "native"})
    assert res.status_code == 200
    assert fake.calls[-1][1]["place_id"] == 2738 and "swlat" not in fake.calls[-1][1]


def test_bad_inputs_are_422(client):
    assert client.get("/api/area/observations").status_code == 422  # no scope
    assert client.get("/api/area/observations", params={"south": 33, "west": -118, "north": 34}).status_code == 422  # partial bbox
    assert client.get("/api/area/observations", params={"oc": "true", "taxa": "Dragons"}).status_code == 422
    assert client.get("/api/area/observations", params={"oc": "true", "status": "alien"}).status_code == 422


def test_upstream_failure_is_502(client):
    async def boom(path, params):
        raise AreaError("iNaturalist request failed: 503")

    app.state.area = AreaService(fetch=boom)
    res = client.get("/api/area/trend", params={"oc": "true"})
    assert res.status_code == 502 and "iNaturalist" in res.json()["detail"]


def test_listed_endpoint_exposes_seed(client):
    body = client.get("/api/area/listed").json()
    assert body["version"].startswith("seed-")
    assert any(e["scientific_name"] == "Arundo donax" for e in body["entries"])
