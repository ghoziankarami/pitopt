"""
The optimiser shell as an outline, and the simplification that makes it
diggable.

A maximum_closure shell is a set of whole blocks. Its outline at one level is
the union of those blocks' squares — a staircase that steps by a block at
a time. Offsetting the staircase as it is would reproduce every step as a
notch in every bench, so the outline is simplified first. That is a
judgement, not a standard, and it is the stage that most decides how the
result looks; so what it did — how far it allowed a point to move, how much
area it gained or lost, what it dropped — comes back as a record beside
the geometry rather than being folded into it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from .config import SmoothingConfig


@dataclass
class SmoothingRecord:
    """What the smoothing did to the outline. Reported in the design so
    that a tonnage difference can be traced to it."""

    applied: bool
    tolerance_m: float
    closing_m: float
    area_before_m2: float
    area_after_m2: float
    dropped_parts: int = 0
    dropped_area_m2: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def area_change_m2(self) -> float:
        return self.area_after_m2 - self.area_before_m2


def shell_level_areas(blocks: pd.DataFrame, mask: np.ndarray) -> dict[float, float]:
    """Footprint area (block count times block area) at every elevation the shell occupies.

    Cheap on purpose — a block count per level, not a union of squares — because this is read to characterise
    the shell's overall shape (is it a single cone that narrows to one floor, or something else) before any
    geometry is built from it, not to draw anything."""
    dx, dy = float(blocks["dx"].iloc[0]), float(blocks["dy"].iloc[0])
    z = np.round(blocks["z"].to_numpy()[mask], 6)
    levels, counts = np.unique(z, return_counts=True)
    return dict(zip(levels.tolist(), (counts * dx * dy).tolist()))


@dataclass
class ShellFit:
    """How closely the built design tracks the true shell, at the bench and side (toe or crest) where they
    agree the least."""

    ratio: float                          # design polygon area / true shell area at the matching elevation, worst over the stack
    bench: int
    side: str                             # "toe" | "crest"
    rl: float
    design_area_m2: float
    shell_area_m2: float


def worst_shell_fit(stack, shell_areas: dict[float, float], dz: float) -> ShellFit | None:
    """The offset construction (build_bench_stack) grows every bench's wall outward from the last by a fixed,
    formula-derived distance; nothing about it looks at the shell again once the anchor outline is taken. That
    is exactly right for a shell that is one cone widening steadily from its floor to its crest, and it can be
    badly wrong otherwise: a shell whose footprint balloons at a middle elevation and pinches at both ends (a
    wide, shallow, undulating deposit — mineral sands, a stratiform seam) leaves the design far short of the
    true width partway up the wall, with no parameter that fixes it, because the fault is the shape and not a
    number. Comparing each bench's own crest and toe area against the shell's true footprint at that elevation
    catches this directly, at the bench and side where it is worst, rather than inferring it indirectly from
    how far off the final reconciliation ends up.

    None when the shell has no measurable area at any bench elevation (nothing to compare against)."""
    if not shell_areas:
        return None
    levels = np.array(sorted(shell_areas))
    worst: ShellFit | None = None
    for bench in stack.benches:
        for side, rl, polygon in (("toe", bench.toe_rl, bench.toe), ("crest", bench.crest_rl, bench.crest)):
            shell_area = shell_areas[float(levels[np.argmin(np.abs(levels - (rl - dz / 2.0)))])]
            if shell_area <= 0:
                continue
            ratio = polygon.area / shell_area
            if worst is None or ratio < worst.ratio:
                worst = ShellFit(ratio, bench.index, side, rl, polygon.area, shell_area)
    return worst


def level_footprint(blocks: pd.DataFrame, mask: np.ndarray, z: float) -> BaseGeometry:
    """Outline of the masked blocks whose centre is at elevation z.

    Boxes are built in one vectorised call and merged in one union, which
    stays fast at the block counts a real model has."""
    at_level = mask & np.isclose(blocks["z"].to_numpy(), z)
    if not at_level.any():
        return Polygon()
    x, y = blocks["x"].to_numpy()[at_level], blocks["y"].to_numpy()[at_level]
    hx, hy = blocks["dx"].to_numpy()[at_level] / 2.0, blocks["dy"].to_numpy()[at_level] / 2.0
    return shapely.union_all(shapely.box(x - hx, y - hy, x + hx, y + hy))


def smooth_outline(outline: BaseGeometry, config: SmoothingConfig, block_diagonal_m: float) -> tuple[BaseGeometry, SmoothingRecord]:
    """Close single-block notches, simplify, drop unmineable fragments.

    The simplification band defaults to one block diagonal — the finest
    detail the shell actually carries, so nothing real is smoothed away and
    only the staircase is. Topology is preserved: a hole stays a hole and
    two parts never merge."""
    before = float(outline.area)
    tolerance = config.tolerance_m if config.tolerance_m is not None else block_diagonal_m
    closing = config.closing_m or 0.0
    if not config.enabled or outline.is_empty:
        return outline, SmoothingRecord(False, 0.0, 0.0, before, before)

    result = outline
    if closing > 0:
        result = result.buffer(closing, quad_segs=8).buffer(-closing, quad_segs=8)
    if tolerance > 0:
        result = result.simplify(tolerance, preserve_topology=True)

    dropped, dropped_area, notes = 0, 0.0, []
    if config.min_area_m2:
        parts = list(result.geoms) if hasattr(result, "geoms") else [result]
        kept = [p for p in parts if p.area >= config.min_area_m2]
        dropped = len(parts) - len(kept)
        dropped_area = float(sum(p.area for p in parts if p.area < config.min_area_m2))
        result = shapely.union_all(kept) if kept else Polygon()
        if dropped:
            notes.append(f"{dropped} fragment(s) under {config.min_area_m2:g} m2 dropped ({dropped_area:,.0f} m2)")

    return result, SmoothingRecord(True, tolerance, closing, before, float(result.area), dropped, dropped_area, notes)


def block_diagonal(blocks: pd.DataFrame) -> float:
    return math.hypot(float(blocks["dx"].iloc[0]), float(blocks["dy"].iloc[0]))


def working_width(outline: BaseGeometry, tolerance: float = 0.01) -> float:
    """How wide the floor is where it is widest: the diameter of the largest circle that fits inside, which is
    what an excavator turning on it needs. Zero for an empty outline."""
    if outline.is_empty:
        return 0.0
    return float(2.0 * shapely.maximum_inscribed_circle(outline, tolerance=tolerance).length)


def widen_to_min_width(outline: BaseGeometry, min_width: float) -> tuple[BaseGeometry, bool]:
    """Widen every part of a floor that is narrower than the minimum mining width, evenly all round, until its
    largest inscribed circle is exactly that wide. A part already wide enough is untouched. Returns the outline
    and whether anything was widened.

    Even widening is the smallest change that makes the part workable and the one that adds the least waste; the
    material it adds is what the reconciliation reports as minimum-width dilution."""
    parts = list(outline.geoms) if hasattr(outline, "geoms") else [outline]
    widened, changed = [], False
    for part in parts:
        width = working_width(part)
        if 0.0 < width < min_width - 1e-6:
            part = part.buffer((min_width - width) / 2.0, quad_segs=16)
            changed = True
        widened.append(part)
    return (shapely.union_all(widened) if changed else outline), changed
