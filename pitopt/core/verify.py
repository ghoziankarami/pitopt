"""
Independent geometric checks on a solved pit.

None of these reuse the solver's own precedence arcs or its cone template,
so a fault in the template cannot hide behind itself:

  walls      every pair of mined columns on the block-stepped pit surface,
             against the design angle
  cone       every in-pit block against its true slope cone
  schedule   every scheduled block against the blocks in its cone
  design     the benched face position: no local face steeper than the
             bench face angle, no wall over several benches steeper than
             the overall angle

Each returns plain numbers; a result of 0 violations is the pass condition.
The pipeline runs all of them on every run and stores the result, so a pit
that fails is visible in the summary rather than discovered later.
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np
import pandas as pd

from ..config import ProjectConfig
from .pitsurface import pit_surface_grid


def _angle_groups(cfg: ProjectConfig, blocks: pd.DataFrame) -> list[tuple[np.ndarray, float]]:
    """(row mask, slope angle) per geotechnical domain — the block's own
    domain decides the angle applied to it, the same convention the solver
    uses. Blocks in no listed domain take the overall angle."""
    overall = float(cfg.slope.overall_angle_deg)
    angles = cfg.slope.domain_angles or {}
    if not angles or "domain" not in blocks.columns:
        return [(np.ones(len(blocks), dtype=bool), overall)]
    dom = blocks["domain"].to_numpy()
    groups, covered = [], np.zeros(len(blocks), dtype=bool)
    for name, angle in angles.items():
        mask = dom == name
        groups.append((mask, float(angle)))
        covered |= mask
    if (~covered).any():
        groups.append((~covered, overall))
    return groups


def wall_check(cfg: ProjectConfig, blocks: pd.DataFrame, elevation: Callable | None, radius_m: float = 120.0) -> dict:
    in_pit = blocks["in_pit"].to_numpy()
    _xs, _ys, surface = pit_surface_grid(blocks, in_pit, elevation)
    dx = float(blocks["dx"].iloc[0])
    dz = float(blocks["dz"].iloc[0])
    # a surface wall may be as steep as the steepest domain allows; the cone check is the per-domain test
    tan = math.tan(math.radians(max(a for _m, a in _angle_groups(cfg, blocks))))

    mined = np.zeros(surface.shape, dtype=bool)
    pit = blocks[in_pit]
    mined[pit["gi"].to_numpy() - blocks["gi"].min(), pit["gj"].to_numpy() - blocks["gj"].min()] = True

    cells = int(radius_m // dx)
    worst, count, pairs = 0.0, 0, 0
    steepest = []
    for di in range(-cells, cells + 1):
        for dj in range(-cells, cells + 1):
            d = math.hypot(di, dj) * dx
            if d == 0 or d > radius_m:
                continue
            a = surface[max(0, -di): surface.shape[0] - max(0, di), max(0, -dj): surface.shape[1] - max(0, dj)]
            b = surface[max(0, di): surface.shape[0] - max(0, -di) or None, max(0, dj): surface.shape[1] - max(0, -dj) or None]
            m = mined[max(0, -di): mined.shape[0] - max(0, di), max(0, -dj): mined.shape[1] - max(0, dj)]
            rise = b - a
            valid = m & np.isfinite(rise)
            allowed = d * tan + dz + dx * tan
            excess = np.where(valid, rise - allowed, -np.inf)
            pairs += int(valid.sum())
            bad = excess > 0
            count += int(bad.sum())
            if bad.any():
                worst = max(worst, float(excess[bad].max()))
            if d >= 30 and valid.any():
                steepest.append(float(np.degrees(np.arctan(np.nanmax(np.where(valid, rise, np.nan)) / d))))
    return {
        "pairs_checked": pairs,
        "violations": count,
        "worst_excess_m": worst,
        "steepest_wall_deg_over_30m": max(steepest) if steepest else float("nan"),
    }


def _grid(blocks: pd.DataFrame, values: np.ndarray, fill: int) -> tuple[np.ndarray, tuple]:
    b0, i0, j0 = blocks["bench"].min(), blocks["gi"].min(), blocks["gj"].min()
    shape = (blocks["bench"].max() - b0 + 1, blocks["gi"].max() - i0 + 1, blocks["gj"].max() - j0 + 1)
    grid = np.full(shape, fill, dtype=np.int32)
    grid[blocks["bench"].to_numpy() - b0, blocks["gi"].to_numpy() - i0, blocks["gj"].to_numpy() - j0] = values
    return grid, shape


def _cone_pairs(shape: tuple, dx: float, dz: float, tan: float, levels: int, slack_m: float):
    """(level, di, dj) for every cell inside the true cone, shrunk by
    `slack_m` so one block of grid discretisation is not flagged."""
    for level in range(1, min(levels, shape[0]) + 1):
        r = level * dz / tan - slack_m
        if r < 0:
            continue
        rc = int(r // dx)
        for di in range(-rc, rc + 1):
            for dj in range(-rc, rc + 1):
                if math.hypot(di, dj) * dx <= r:
                    yield level, di, dj


def _shifted(grid: np.ndarray, k, i, j, level, di, dj):
    nb, ni, nj = grid.shape
    kk, ii, jj = k + level, i + di, j + dj
    ok = (kk < nb) & (ii >= 0) & (ii < ni) & (jj >= 0) & (jj < nj)
    return ok, grid[kk[ok], ii[ok], jj[ok]]


def cone_check(cfg: ProjectConfig, blocks: pd.DataFrame, levels: int = 40) -> dict:
    """Every block in the pit must have every block of its true cone in the
    pit too. Uses each block's own domain angle directly, not the solver's template."""
    dx, dz = float(blocks["dx"].iloc[0]), float(blocks["dz"].iloc[0])
    state, shape = _grid(blocks, blocks["in_pit"].to_numpy().astype(int), -1)
    grid_row = _grid(blocks, np.arange(len(blocks)), -1)[0]
    k, i, j = np.nonzero(state == 1)
    row = grid_row[k, i, j]
    bad = np.zeros(len(k), dtype=bool)
    for mask, angle in _angle_groups(cfg, blocks):
        sel = np.flatnonzero(mask[row])
        if not len(sel):
            continue
        ks, is_, js = k[sel], i[sel], j[sel]
        tan = math.tan(math.radians(angle))
        for level, di, dj in _cone_pairs(shape, dx, dz, tan, levels, slack_m=dx):
            ok, above = _shifted(state, ks, is_, js, level, di, dj)
            hit = np.zeros(len(ks), dtype=bool)
            hit[np.flatnonzero(ok)[above == 0]] = True
            bad[sel] |= hit
    return {"in_pit_blocks_with_unmined_block_inside_cone": int(bad.sum())}


def schedule_check(cfg: ProjectConfig, blocks: pd.DataFrame, levels: int = 40) -> dict:
    """No block may be mined in an earlier period than a block in its cone."""
    dx, dz = float(blocks["dx"].iloc[0]), float(blocks["dz"].iloc[0])
    period, shape = _grid(blocks, blocks["period"].to_numpy().astype(int), 0)
    grid_row = _grid(blocks, np.arange(len(blocks)), -1)[0]
    k, i, j = np.nonzero(period > 0)
    p = period[k, i, j]
    row = grid_row[k, i, j]
    bad = np.zeros(len(k), dtype=bool)
    for mask, angle in _angle_groups(cfg, blocks):
        sel = np.flatnonzero(mask[row])
        if not len(sel):
            continue
        tan = math.tan(math.radians(angle))
        for level, di, dj in _cone_pairs(shape, dx, dz, tan, levels, slack_m=dx):
            ok, above = _shifted(period, k[sel], i[sel], j[sel], level, di, dj)
            hit = np.zeros(len(sel), dtype=bool)
            hit[np.flatnonzero(ok)[above > p[sel][ok]]] = True
            bad[sel] |= hit
    return {"blocks_mined_before_a_block_in_their_cone": int(bad.sum()), "periods": int(p.max())}


def design_check(face: np.ndarray, cell: float, face_angle_deg: float, overall_angle_deg: float, bench_run: float) -> dict:
    """Steepest local face and steepest wall over three benches on the
    designed face position."""

    def steepest(offset_cells: int) -> float:
        worst = 0.0
        for di, dj in ((offset_cells, 0), (0, offset_cells), (offset_cells, offset_cells), (offset_cells, -offset_cells)):
            a = face[max(0, -di): face.shape[0] - max(0, di), max(0, -dj): face.shape[1] - max(0, dj)]
            b = face[max(0, di): face.shape[0] - max(0, -di) or None, max(0, dj): face.shape[1] - max(0, -dj) or None]
            rise = np.abs(b - a)
            run = math.hypot(di, dj) * cell
            if np.isfinite(rise).any():
                worst = max(worst, float(np.degrees(np.arctan(np.nanmax(rise) / run))))
        return worst

    span = int(math.ceil(3 * bench_run / cell))
    return {
        "design_face_angle_deg": face_angle_deg,
        "steepest_local_face_deg": steepest(1),
        "design_overall_angle_deg": round(overall_angle_deg, 2),
        "steepest_over_3_benches_deg": steepest(span),
        "three_bench_span_m": span * cell,
    }


def run_all(
    cfg: ProjectConfig,
    blocks: pd.DataFrame,
    elevation: Callable | None,
    face: np.ndarray | None = None,
    cell: float | None = None,
    geometry=None,
) -> dict:
    """Every check, as one dictionary. The three numbers shown in the header
    of the UI are walls / cone / schedule violations."""
    out: dict = {}
    out["walls"] = wall_check(cfg, blocks, elevation)
    out["cone"] = cone_check(cfg, blocks)
    if "period" in blocks.columns and (blocks["period"] > 0).any():
        out["schedule"] = schedule_check(cfg, blocks)
    if face is not None and cell and geometry is not None:
        out["design"] = design_check(face, cell, geometry.face_angle_deg, geometry.overall_angle_deg, geometry.bench_run)
    out["violations"] = (
        out["walls"]["violations"],
        out["cone"]["in_pit_blocks_with_unmined_block_inside_cone"],
        out.get("schedule", {}).get("blocks_mined_before_a_block_in_their_cone", 0),
    )
    return out
