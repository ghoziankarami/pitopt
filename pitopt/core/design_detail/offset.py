"""
Moving a pit outline sideways by a distance that depends on which way the
wall faces.

The polygon problem the design engine rests on. A wall that varies by
sector needs a *variable-distance* offset, and the textbook trick of
shifting every vertex along its normal is exactly the naive version that
fails: at a convex corner the shifted edges cross and leave a loop, at a
concave one they pull apart, and a narrow neck can pinch the outline in
two. All of that is a property of the offset, not a bug to patch.

So the offset is defined by what it means instead of by vertex surgery.
Growing an outline by d(direction) is the union of the outline with a disk
swept along each edge, radius d at that edge's own facing; shrinking it is
removing those sweeps. Both are set operations, so the geometry engine —
not this module — decides what happens at corners, pinches and vanishing
islands, and the result is valid by construction. Round joins fall out of
the disks; a uniform distance reduces to shapely's own buffer and matches
it.
"""
from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient

from .parameters import SectorGeometry

# Segments per quarter circle when a disk is approximated. 16 keeps the
# rim within 0.5% of the true radius; the exported geometry is checked
# against exact circles in the tests.
QUAD_SEGS = 16
# No single sweep is longer than this, so the facing it samples is local.
MAX_SEGMENT_M = 10.0


def azimuth_profile(sectors: list[SectorGeometry], values: list[float], blend_deg: float) -> Callable[[np.ndarray], np.ndarray]:
    """value(azimuth): each sector's own value across its arc, mixed
    linearly through +/- blend_deg either side of a boundary so a change of
    geotechnical domain is a ramp in the wall and not a step.

    Azimuths are compass bearings, clockwise from north, and periodic."""
    nodes_x, nodes_y = [], []
    for sector, value in zip(sectors, values):
        start = sector.azimuth_from % 360.0
        length = (sector.azimuth_to - sector.azimuth_from) % 360.0 or 360.0
        # A hair of inset even with no blend: two nodes at the same azimuth make the interpolation ambiguous.
        inset = max(min(blend_deg, length / 2.0), 1e-6)
        nodes_x += [(start + inset) % 360.0, (start + length - inset) % 360.0]
        nodes_y += [value, value]
    if len(sectors) == 1:                       # one sector all the way round is a constant
        return lambda azimuth: np.full_like(np.asarray(azimuth, dtype=float), values[0])
    order = np.argsort(nodes_x)
    xs, ys = np.asarray(nodes_x)[order], np.asarray(nodes_y)[order]
    return lambda azimuth: np.interp(np.asarray(azimuth, dtype=float) % 360.0, xs, ys, period=360.0)


def _segments(polygon: Polygon) -> tuple[list[LineString], np.ndarray]:
    """The outline cut into short edges, each with the compass bearing of
    its outward normal (away from the material, into a hole for an island)."""
    lines: list[LineString] = []
    bearings: list[float] = []
    oriented = orient(polygon, sign=1.0)        # material always on the left of travel, holes included
    for ring in [oriented.exterior, *oriented.interiors]:
        ring = shapely.segmentize(ring, MAX_SEGMENT_M)
        xy = np.asarray(ring.coords)
        for a, b in zip(xy[:-1], xy[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            if math.hypot(dx, dy) < 1e-9:
                continue
            lines.append(LineString([a, b]))
            bearings.append(math.degrees(math.atan2(dy, -dx)) % 360.0)       # normal (dy, -dx): east = 90, north = 0
    return lines, np.asarray(bearings)


def offset(geometry: BaseGeometry, distance: float | Callable[[np.ndarray], np.ndarray], *, grow: bool,
           join_style: str = "round", miter_limit: float = 2.0) -> BaseGeometry:
    """Grow (or shrink) a polygon or multipolygon.

    `distance` is a number, or a function of the outward-normal bearing.
    Anything that is not a Polygon (an emptied result, a lone line left by a
    pinch) is dropped: only area is a pit."""
    if geometry.is_empty:
        return geometry
    if not callable(distance):
        style = {"round": "round", "mitre": "mitre"}[join_style]
        return _areal(geometry.buffer(distance if grow else -distance, quad_segs=QUAD_SEGS, join_style=style,
                                      mitre_limit=miter_limit))

    polygons = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    sweeps: list[BaseGeometry] = []
    for polygon in polygons:
        lines, bearings = _segments(polygon)
        if not lines:
            continue
        radii = np.asarray(distance(bearings), dtype=float)
        keep = radii > 0
        sweeps.append(shapely.union_all(shapely.buffer(np.asarray(lines, dtype=object)[keep], radii[keep],
                                                       quad_segs=QUAD_SEGS)))
    swept = shapely.union_all(sweeps) if sweeps else Polygon()
    return _areal(geometry.union(swept) if grow else geometry.difference(swept))


def _areal(geometry: BaseGeometry) -> BaseGeometry:
    """Keep only the area: polygons and multipolygons, nothing degenerate."""
    if geometry.is_empty or geometry.geom_type in ("Polygon", "MultiPolygon"):
        return geometry
    parts = [g for g in getattr(geometry, "geoms", []) if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty]
    return shapely.union_all(parts) if parts else Polygon()
