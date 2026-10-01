"""
DXF surface I/O — the interchange format survey and mine design actually
use, so topography comes in as DXF and the pit shell goes back out as DXF.

Reading is deliberately permissive about entity type. A "surface" DXF in
practice is any of: a triangulated mesh (3DFACE / polyface POLYLINE /
MESH), contour or breakline strings (3D POLYLINE, 2D POLYLINE whose one
elevation sits in its header, LWPOLYLINE with elevation, LINE, SPLINE),
or a bare point cloud (POINT) — in model space or wrapped in a block
reference, as survey often delivers it. All of them reduce to XYZ points,
which is all the optimiser needs — it only ever asks "is this block
centroid above or below ground?". tests/test_dxf_topography.py writes
each form from one known surface and checks it reads back.

Writing produces 3DFACE triangles, which every mine-planning and CAD
package reads without negotiation.
"""
from __future__ import annotations

from typing import Callable

import ezdxf
import numpy as np
from scipy.interpolate import griddata

SURFACE_TYPES = ("3DFACE", "MESH", "POLYLINE", "LWPOLYLINE", "POINT", "LINE", "SPLINE")


def _entities(layout, depth: int = 0):
    """Every entity in a layout, with block references (INSERT) expanded in place and their transform applied —
    survey topography is often delivered inside a block. Nested blocks are followed a few levels deep."""
    for entity in layout:
        if entity.dxftype() == "INSERT" and depth < 8:
            yield from _entities(entity.virtual_entities(), depth + 1)
        else:
            yield entity


def _points_of(entity) -> list[tuple[float, float, float]]:
    kind = entity.dxftype()
    if kind == "3DFACE":
        return [tuple(getattr(entity.dxf, a))[:3] for a in ("vtx0", "vtx1", "vtx2", "vtx3")]
    if kind == "MESH":
        return [(v[0], v[1], v[2]) for v in entity.vertices]
    if kind == "POLYLINE":
        if entity.is_2d_polyline:
            # a 2D polyline carries one elevation for the whole string (a contour): the vertices are flat at 0
            z = entity.dxf.elevation.z if entity.dxf.hasattr("elevation") else 0.0
            return [(v.dxf.location.x, v.dxf.location.y, z) for v in entity.vertices]
        # a polyface mesh mixes real vertices with face records (index lists stored at 0,0,0); keep the vertices
        return [tuple(v.dxf.location) for v in entity.vertices if not v.is_face_record]
    if kind == "LWPOLYLINE":
        return [(p[0], p[1], entity.dxf.elevation) for p in entity.get_points()]
    if kind == "POINT":
        return [tuple(entity.dxf.location)]
    if kind == "LINE":
        return [tuple(entity.dxf.start), tuple(entity.dxf.end)]
    if kind == "SPLINE":
        return [tuple(p) for p in entity.flattening(0.5)]
    return []


def read_surface_points(path: str) -> np.ndarray:
    """Collect every XYZ point from a DXF, whatever entities carry it: a triangulated mesh (3DFACE, polyface,
    MESH), contour or breakline strings (POLYLINE, LWPOLYLINE, LINE, SPLINE), or a point cloud (POINT), in model
    space or inside block references. Returns an (n, 3) array."""
    doc = ezdxf.readfile(path)
    points: list[tuple[float, float, float]] = []
    for entity in _entities(doc.modelspace()):
        if entity.dxftype() in SURFACE_TYPES:
            points.extend(_points_of(entity))

    if not points:
        raise ValueError(
            f"No usable geometry found in {path}. Expected {', '.join(SURFACE_TYPES)} entities carrying elevations "
            "(in model space or inside a block)."
        )

    unique = np.unique(np.asarray(points, dtype=float), axis=0)
    return unique[np.isfinite(unique).all(axis=1)]


def elevation_from_points(points: np.ndarray) -> Callable[[np.ndarray, np.ndarray], np.ndarray]:
    """Linear interpolation of a surface, nearest-neighbour outside the
    convex hull so blocks near the model edge still get an answer."""
    xy, z = points[:, :2], points[:, 2]

    def elevation(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        z_linear = griddata(xy, z, (x, y), method="linear")
        missing = np.isnan(z_linear)
        if missing.any():
            z_linear = z_linear.copy()
            z_linear[missing] = griddata(xy, z, (x[missing], y[missing]), method="nearest")
        return z_linear

    return elevation


def read_surface(path: str) -> Callable[[np.ndarray, np.ndarray], np.ndarray]:
    return elevation_from_points(read_surface_points(path))


def write_surface(path: str, xs: np.ndarray, ys: np.ndarray, grid_z: np.ndarray, layer: str = "PIT_SURFACE") -> int:
    """
    Write a gridded surface as 3DFACE triangles (two per grid cell).

    xs, ys: 1-D node coordinates. grid_z: (len(xs), len(ys)) elevations,
    NaN for nodes with no surface. Returns the number of faces written.
    """
    doc = ezdxf.new("R2010")
    doc.layers.add(layer)
    msp = doc.modelspace()
    faces = 0

    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            corners = [
                (xs[i], ys[j], grid_z[i, j]),
                (xs[i + 1], ys[j], grid_z[i + 1, j]),
                (xs[i + 1], ys[j + 1], grid_z[i + 1, j + 1]),
                (xs[i], ys[j + 1], grid_z[i, j + 1]),
            ]
            if any(not np.isfinite(c[2]) for c in corners):
                continue
            msp.add_3dface([corners[0], corners[1], corners[2], corners[2]], dxfattribs={"layer": layer})
            msp.add_3dface([corners[0], corners[2], corners[3], corners[3]], dxfattribs={"layer": layer})
            faces += 2

    doc.saveas(path)
    return faces
