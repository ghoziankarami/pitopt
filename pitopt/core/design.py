"""
Pit design geometry: from the optimiser's floor to a benched pit.

The optimiser returns a block-stepped shell. A pit is built to
geotechnical geometry instead — bench height, bench face angle and berm
width — whose overall effect is the overall slope angle:

    overall = atan( H / (H / tan(face) + berm) )

Two surfaces come out of that geometry, and they answer different
questions:

  pit shell       the excavation itself: the floor, with benched walls
                  rising from it. Where the walls would climb above
                  ground they are simply not cut off, so the shape is the
                  full bowl regardless of topography. This is the pit as a
                  design object.

  face position   the same bowl clipped by topography — the ground surface
                  that actually exists once the pit (or a period, or a
                  pushback) has been mined. This is what survey measures
                  and what goes into a mine plan.

Both are computed on a fine grid by a benched-cone dilation of the floor,
evaluated exactly with one distance transform per floor level:

    shell(x) = min over mined floor points p of  floor(p) + g(|x - p|)

where g is the benched wall profile — rising one bench height over the
face run, flat across the berm, repeated. Every point on a wall therefore
sits exactly on the design profile from the nearest part of the floor, so
the walls are benched and never steeper than the design slope.

Designing the walls moves material relative to the optimiser shell (the
block steps are replaced by a continuous benched wall), so the design is
reconciled against the shell: tonnes, value and the difference between
them. A design within a few percent of its shell is the usual target.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from scipy import ndimage


@dataclass
class BenchGeometry:
    bench_height: float
    face_angle_deg: float
    berm_width: float

    @property
    def face_run(self) -> float:
        return self.bench_height / math.tan(math.radians(self.face_angle_deg))

    @property
    def bench_run(self) -> float:
        return self.face_run + self.berm_width

    @property
    def overall_angle_deg(self) -> float:
        return math.degrees(math.atan2(self.bench_height, self.bench_run))

    def rise(self, distance: np.ndarray) -> np.ndarray:
        """Height of the benched wall at horizontal distance from its toe."""
        n = np.floor(distance / self.bench_run)
        remainder = distance - n * self.bench_run
        tan_face = math.tan(math.radians(self.face_angle_deg))
        return n * self.bench_height + np.minimum(self.bench_height, remainder * tan_face)


def bench_geometry(overall_angle_deg: float, bench_height: float, face_angle_deg: float, berm_width: float | None) -> BenchGeometry:
    """Bench geometry from its parts. With no berm given, the berm is the
    width that makes the benches honour the overall slope angle."""
    if berm_width is None:
        run = bench_height / math.tan(math.radians(overall_angle_deg))
        face = bench_height / math.tan(math.radians(face_angle_deg))
        if run < face:
            raise ValueError(
                f"bench face angle {face_angle_deg} deg is flatter than the overall slope {overall_angle_deg} deg"
            )
        berm_width = run - face
    return BenchGeometry(bench_height, face_angle_deg, berm_width)


@dataclass
class DesignGrid:
    xs: np.ndarray
    ys: np.ndarray
    topo: np.ndarray
    cell_i: np.ndarray    # block grid column (gi) of every fine node, -1 outside
    cell_j: np.ndarray


def design_grid(blocks: pd.DataFrame, elevation: Callable | None, cell: float) -> DesignGrid:
    dx, dy, dz = (float(blocks[c].iloc[0]) for c in ("dx", "dy", "dz"))
    x0, y0 = float(blocks["x"].min()), float(blocks["y"].min())
    gi0, gj0 = int(blocks["gi"].min()), int(blocks["gj"].min())
    xs = np.arange(x0 - dx / 2 + cell / 2, float(blocks["x"].max()) + dx / 2, cell)
    ys = np.arange(y0 - dy / 2 + cell / 2, float(blocks["y"].max()) + dy / 2, cell)

    ci = (np.round((xs - x0) / dx).astype(int) + gi0)
    cj = (np.round((ys - y0) / dy).astype(int) + gj0)

    if elevation is not None:
        mx, my = np.meshgrid(xs, ys, indexing="ij")
        topo = np.asarray(elevation(mx.ravel(), my.ravel()), dtype=float).reshape(mx.shape)
    else:
        tops = blocks.groupby(["gi", "gj"])["z"].max() + dz / 2.0
        lookup = np.full((blocks["gi"].max() - gi0 + 1, blocks["gj"].max() - gj0 + 1), np.nan)
        lookup[tops.index.get_level_values(0) - gi0, tops.index.get_level_values(1) - gj0] = tops.to_numpy()
        topo = lookup[np.clip(ci - gi0, 0, lookup.shape[0] - 1)][:, np.clip(cj - gj0, 0, lookup.shape[1] - 1)]
    return DesignGrid(xs, ys, topo, ci, cj)


def _floor_raster(blocks: pd.DataFrame, mined: np.ndarray, grid: DesignGrid) -> np.ndarray:
    """Floor elevation of the mined columns, painted onto the fine grid."""
    dz = float(blocks["dz"].iloc[0])
    gi0, gj0 = int(blocks["gi"].min()), int(blocks["gj"].min())
    floors = blocks[mined].groupby(["gi", "gj"])["z"].min() - dz / 2.0
    lookup = np.full((blocks["gi"].max() - gi0 + 1, blocks["gj"].max() - gj0 + 1), np.inf)
    lookup[floors.index.get_level_values(0) - gi0, floors.index.get_level_values(1) - gj0] = floors.to_numpy()
    ii = np.clip(grid.cell_i - gi0, 0, lookup.shape[0] - 1)
    jj = np.clip(grid.cell_j - gj0, 0, lookup.shape[1] - 1)
    raster = lookup[ii][:, jj]
    outside_i = (grid.cell_i < gi0) | (grid.cell_i - gi0 >= lookup.shape[0])
    outside_j = (grid.cell_j < gj0) | (grid.cell_j - gj0 >= lookup.shape[1])
    raster[outside_i, :] = np.inf
    raster[:, outside_j] = np.inf
    return raster


def pit_shell(blocks: pd.DataFrame, mined: np.ndarray, grid: DesignGrid, geometry: BenchGeometry) -> np.ndarray:
    """The benched bowl. Walls rise from the edge of the optimised floor —
    the toe sits on the shell's floor boundary, the usual design
    convention — so the design always contains the floor of the shell,
    and the wall material the block steps left behind is reported in the
    reconciliation. Growing walls from column centres instead would leave
    a cliff at every cell edge where two floors meet. Infinite where no
    mined column is within reach."""
    floor = _floor_raster(blocks, mined, grid)
    if not np.isfinite(floor).any():
        return floor
    source = floor
    cell = float(grid.xs[1] - grid.xs[0]) if len(grid.xs) > 1 else 1.0

    # The bench profile only rises with distance, so among all floor
    # columns at one elevation L the lowest wall at x comes from the
    # nearest of them: L + g(distance to the nearest). One Euclidean
    # distance transform per floor level gives that exactly, instead of
    # dilating by every offset in the cone.
    shell = floor.copy()
    for level in np.unique(source[np.isfinite(source)]):
        distance = ndimage.distance_transform_edt(source != level, sampling=cell)
        np.minimum(shell, level + geometry.rise(distance), out=shell)
    return shell


def face_position(shell: np.ndarray, grid: DesignGrid) -> np.ndarray:
    """The bowl clipped by topography: the ground after mining."""
    return np.fmin(grid.topo, shell)


def shell_for_display(shell: np.ndarray, grid: DesignGrid, geometry: BenchGeometry) -> np.ndarray:
    """The bowl up to one bench above the highest ground, NaN beyond — the
    walls stop where there is nothing left to cut."""
    ceiling = float(np.nanmax(grid.topo)) + geometry.bench_height
    return np.where(shell <= ceiling, shell, np.nan)


def design_fraction(blocks: pd.DataFrame, face: np.ndarray, grid: DesignGrid) -> np.ndarray:
    """Share of each block's volume that the design mines: the part of the block between the designed face
    position and the topography, sampled over the block footprint on the design grid.

    The share is of the block's full extent, capped by the topography, so it reproduces the integral of
    (topography - face) over the design grid; the earlier tempting "share of the material below the topography"
    overcounted a block that sits half above ground by a factor of two (+16% instead of +5% on the tin example).

    Testing only the block centre against the surface (the earlier rule) is a one-point sample of a surface
    that steps by whole benches; on a small pit it moved the design volume by 13% either way against the
    integral of the very surface written to DXF. Sampling the footprint reproduces that integral."""
    cell = float(grid.xs[1] - grid.xs[0]) if len(grid.xs) > 1 else 1.0
    dx, dy, dz = (float(blocks[c].iloc[0]) for c in ("dx", "dy", "dz"))
    nx, ny = max(1, int(round(dx / cell))), max(1, int(round(dy / cell)))
    x, y, z = blocks["x"].to_numpy(), blocks["y"].to_numpy(), blocks["z"].to_numpy()
    top, bottom = z + dz / 2, z - dz / 2
    total = np.zeros(len(blocks))
    for a in (np.arange(nx) + 0.5) / nx - 0.5:
        for b in (np.arange(ny) + 0.5) / ny - 0.5:
            ix = np.clip(np.round((x + a * dx - grid.xs[0]) / cell).astype(int), 0, len(grid.xs) - 1)
            iy = np.clip(np.round((y + b * dy - grid.ys[0]) / cell).astype(int), 0, len(grid.ys) - 1)
            upper = np.minimum(top, grid.topo[ix, iy])          # nothing is mined above the topography
            lower = np.maximum(bottom, face[ix, iy])
            total += np.clip((upper - lower) / dz, 0.0, 1.0)
    return np.nan_to_num(total / (nx * ny))


def reconcile(blocks: pd.DataFrame, optimised: np.ndarray, face: np.ndarray, grid: DesignGrid) -> tuple[np.ndarray, dict]:
    """What the design mines against the optimiser shell. Returns (fraction of each block mined, summary);
    design totals are the block totals weighted by that fraction, shell totals count whole blocks."""
    fraction = design_fraction(blocks, face, grid)

    def totals(weight: np.ndarray) -> dict:
        ore = (blocks["destination"] == 1).to_numpy()
        return {
            "blocks": int(round(float(weight.sum()))),
            "rock_tonnes": float((blocks["rock_tonnes"].to_numpy() * weight).sum()),
            "ore_tonnes": float((blocks["ore_tonnes"].to_numpy() * weight * ore).sum()),
            "value": float((blocks["value"].to_numpy() * weight).sum()),
        }

    shell_totals, design_totals = totals(optimised.astype(float)), totals(fraction)
    summary = {"shell": shell_totals, "design": design_totals}
    for key in ("rock_tonnes", "ore_tonnes", "value"):
        base = shell_totals[key]
        summary[f"{key}_change"] = (design_totals[key] - base) / base if base else float("nan")
    return fraction, summary
