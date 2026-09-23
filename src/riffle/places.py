"""Region resolution against the real Orange County boundary (PRD §7, FR-6).

``inputs.py`` answers "is this in Orange County" with a bounding box, which is
all v1 strictly needs, but the box also covers Long Beach, Whittier, Corona and
the northern edge of Camp Pendleton, none of which are Orange County. Now that
M2 status resolution is county-relative, a wrong answer at the edge changes the
label's certainty and the wording the model is given, so the pipeline refines
the box answer with the county polygon iNaturalist publishes for place 2738.

The polygon is fetched once per cache lifetime through the shared ``InatClient``
and tested with an even-odd ray cast, so no geometry dependency is added. If the
fetch fails the bounding-box answer stands (PRD §5.2, degrade gracefully): the
refinement can only make the region more accurate, never block a classification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .inat import ORANGE_COUNTY_PLACE_ID, InatClient, InatError
from .schema import Region

Ring = list[tuple[float, float]]  # (lon, lat)


def point_in_ring(lon: float, lat: float, ring: Ring) -> bool:
    """Even-odd rule. A point on the boundary may fall either way, which is fine at county scale."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x_at = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_at:
                inside = not inside
    return inside


def point_in_geojson(lon: float, lat: float, geometry: dict[str, Any]) -> bool:
    """Polygon or MultiPolygon, outer ring minus holes."""
    kind = geometry.get("type")
    polygons = [geometry["coordinates"]] if kind == "Polygon" else geometry["coordinates"] if kind == "MultiPolygon" else []
    for rings in polygons:
        if not rings:
            continue
        outer, *holes = rings
        if point_in_ring(lon, lat, [(float(x), float(y)) for x, y in outer]) and not any(
            point_in_ring(lon, lat, [(float(x), float(y)) for x, y in h]) for h in holes
        ):
            return True
    return False


@dataclass
class OrangeCountyPlace:
    inat: InatClient

    async def geometry(self) -> dict[str, Any] | None:
        raw = await self.inat.get(f"/places/{ORANGE_COUNTY_PLACE_ID}", {})
        results = raw.get("results") or []
        return (results[0].get("geometry_geojson") or None) if results else None

    async def refine(self, region: Region) -> Region:
        """Replace the bounding-box answer with the polygon answer when both coordinates are known."""
        if region.lat is None or region.lon is None:
            return region
        try:
            geometry = await self.geometry()
        except InatError:
            return region
        if not geometry:
            return region
        return region.model_copy(update={"in_orange_county": point_in_geojson(region.lon, region.lat, geometry)})
