"""
The one entry point: optimiser shell in, detailed design out.

    blocks + in-pit mask -> anchor outline -> smoothing -> (floor widened)
        -> bench stack -> ramp -> angles -> reconciliation -> validation

Nothing here writes a file or touches the raster design; the caller decides
what to do with the result. Kept short on purpose: each step is its own
module with its own hand-checked tests, and this only wires them in order.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ...config import ProjectConfig
from ..cancel import CancelToken
from .angles import SectorOSA, sector_osa
from .footprint import (
    SmoothingRecord,
    block_diagonal,
    level_footprint,
    shell_level_areas,
    smooth_outline,
    widen_to_min_width,
    working_width,
    worst_shell_fit,
)
from .parameters import SectorGeometry, angle_status, resolve_sectors
from .ramp import Ramp, build_ramp, size_ramp, wall_tables
from .reconcile import Reconciliation, reconcile
from .stack import BenchStack, bench_count, build_bench_stack
from .validate import Validation, validate


@dataclass
class SectorAngle:
    """A sector's inter-ramp angle against its allowable value."""

    name: str
    ira_deg: float
    ira_max_deg: float | None
    status: str

    @property
    def margin_deg(self) -> float | None:
        return None if self.ira_max_deg is None else self.ira_max_deg - self.ira_deg


@dataclass
class DesignDetail:
    stack: BenchStack
    sectors: list[SectorGeometry]
    smoothing: SmoothingRecord
    angles: list[SectorAngle]
    floor_rl: float
    crest_rl: float
    osa: list[SectorOSA] = field(default_factory=list)
    ramp: Ramp | None = None
    floor_width_m: float = 0.0
    floor_widened: bool = False
    reconciliation: Reconciliation | None = None
    validation: Validation | None = None
    shell_sha256: str = ""
    warnings: list[str] = field(default_factory=list)


def shell_fingerprint(blocks: pd.DataFrame, in_pit: np.ndarray) -> str:
    """A hash of which blocks make up the shell the design was built from: the coordinates of every in-pit
    block, in a fixed order. Two designs with the same fingerprint came from the same shell."""
    shell = blocks.loc[in_pit, ["x", "y", "z"]].round(6).sort_values(["z", "y", "x"])
    return hashlib.sha256(shell.to_numpy(dtype="<f8").tobytes()).hexdigest()


def floor_width(stack: BenchStack) -> float:
    return working_width(stack.benches[-1].toe)


def build_design(blocks: pd.DataFrame, in_pit: np.ndarray, cfg: ProjectConfig, raster: dict | None = None,
                 progress: Callable[[str, dict], None] | None = None, cancel: CancelToken | None = None) -> DesignDetail:
    """Design the pit whose shell is `blocks[in_pit]`. `raster` is the uniform raster design's reconciliation
    when it was run, carried into the result so both designs can be read side by side.

    `progress(stage, info)` is told as each stage starts and, for the bench stack, as each bench finishes, so a
    viewer can draw the pit while the rest is computed; `cancel` is checked between stages and between benches."""
    def tell(stage: str, **info) -> None:
        if cancel is not None:
            cancel.check()
        if progress is not None:
            progress(stage, info)

    design, detail = cfg.design, cfg.design.detail
    if not in_pit.any():
        raise ValueError("there is no pit to design: no block is inside the shell")

    dz = float(blocks["dz"].iloc[0])
    levels = blocks.loc[in_pit, "z"]
    floor_level, crest_level = float(levels.min()), float(levels.max())
    floor_rl, crest_rl = floor_level - dz / 2.0, crest_level + dz / 2.0
    limits = detail.limits

    sectors, warnings = resolve_sectors(design, cfg.slope.overall_angle_deg)
    anchor_level, anchor_rl = (floor_level, floor_rl) if detail.anchor == "floor" else (crest_level, crest_rl)
    tell("anchor", anchor=detail.anchor, floor_rl=floor_rl, crest_rl=crest_rl)
    outline, smoothing = smooth_outline(level_footprint(blocks, in_pit, anchor_level), detail.smoothing,
                                        block_diagonal(blocks))
    warnings += smoothing.notes

    n = bench_count(crest_rl, floor_rl, sectors[0].bench_height)
    tell("benches", total=n)

    def bench_done(bench, done):
        if progress is not None:
            progress("bench_done", {"bench": bench, "done": done, "total": n})

    plain = build_bench_stack(outline, anchor_rl, n, sectors, detail, on_bench=bench_done, cancel=cancel)
    stack, widened = plain, False
    if detail.anchor == "floor" and limits.widen_floor_to_min_width:
        wide, widened = widen_to_min_width(outline, limits.min_mining_width_m)
        if widened:
            stack = build_bench_stack(wide, anchor_rl, n, sectors, detail, cancel=cancel)
            warnings.append(f"the floor was widened to the {limits.min_mining_width_m:g} m minimum mining width")
    warnings += stack.warnings

    angles = [SectorAngle(s.name, s.ira_deg, s.ira_max_deg, angle_status(s.ira_deg, s.ira_max_deg, limits.warn_margin_deg))
              for s in sectors]

    tables = wall_tables(stack)
    ramp = None
    if detail.ramp.enabled:
        tell("ramp")
        sizing = size_ramp(detail.ramp)
        ramp = build_ramp(stack, sizing, detail.ramp, tables)
        warnings += ramp.warnings
    osa = sector_osa(stack, ramp, tables[1], tables[2], limits)

    width = floor_width(stack)
    tell("reconcile")
    recon = reconcile(blocks, in_pit, plain, stack, ramp, limits, raster)
    tell("validate")
    # See validate.py's module docstring (SHAPE_WARN_RATIO / SHAPE_BLOCK_RATIO) for why this is checked at all:
    # the offset construction assumes a shell that is one cone, and a shape that is not one produces a design
    # far smaller than the shell with no parameter that fixes it.
    fit = worst_shell_fit(stack, shell_level_areas(blocks, in_pit), dz)
    checked = validate(stack, angles, osa, ramp, width, recon, limits, fit)
    warnings += [f.message for f in checked.problems()]
    return DesignDetail(stack, sectors, smoothing, angles, floor_rl, crest_rl, osa, ramp, width, widened, recon, checked,
                        shell_fingerprint(blocks, in_pit), warnings)
