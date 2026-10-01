"""
What the practical design mines against what the optimiser shell holds.

Every block is classified by its centre, one bench at a time: inside the
shell and the design, only in the design (material the design takes that the
optimiser did not pay for: dilution), or only in the shell (material the
optimiser wanted that the design leaves behind). The tonnage table is the sum
of that classification and nothing else, so the table and the per-block map
cannot disagree.

Dilution is split by why the design reaches beyond the shell, because the
remedies differ. Three designs are cut at every bench, each containing the
last:

    batter    the walls at the geometry the sectors call for
    min width the floor widened to the minimum mining width
    ramp      the road cut

A block the design takes and the shell does not is assigned to the first of
these that contains it: walls, then floor width, then ramp. Nothing is
counted twice.

The road cut. Above the road the material within its width is mined out, and
the wall rises from the road's outer edge at the sector's face angle. The
ordinary wall leans outward faster than that, because its benches carry
berms, so the cut sticks out of the ordinary wall by

    (road width - berm) - h * berm / H

at a height h above the road: the widening the overall angle pays for at each
crossing, shrinking to nothing a few benches higher. At any elevation the cut
is therefore every stretch of road below it, widened by that lean.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from .angles import sector_mask
from .config import DesignLimitsConfig
from .parameters import BLOCKED, OK, WARNING, SectorGeometry
from .ramp import Ramp
from .stack import BenchStack

CAUSES = ("batter", "min_width", "ramp")


@dataclass
class Tally:
    """Blocks, ore and waste counts, tonnes and value of a set of blocks."""

    blocks: int = 0
    ore_blocks: int = 0
    waste_blocks: int = 0
    rock_tonnes: float = 0.0
    ore_tonnes: float = 0.0
    value: float = 0.0

    @classmethod
    def of(cls, blocks: pd.DataFrame, mask: np.ndarray) -> Tally:
        ore = (blocks["destination"].to_numpy() == 1) & mask
        return cls(
            blocks=int(mask.sum()), ore_blocks=int(ore.sum()), waste_blocks=int(mask.sum() - ore.sum()),
            rock_tonnes=float(blocks["rock_tonnes"].to_numpy()[mask].sum()),
            ore_tonnes=float(blocks["ore_tonnes"].to_numpy()[ore].sum()),
            value=float(blocks["value"].to_numpy()[mask].sum()),
        )


@dataclass
class Reconciliation:
    shell: Tally                          # every block inside the optimiser shell
    design: Tally                         # every block inside the practical design
    gained: dict[str, Tally]              # in the design, not the shell, by cause
    left_behind: Tally                    # in the shell, not the design
    per_bench: pd.DataFrame               # one row per bench, category and cause
    raster: dict | None = None            # the uniform raster design's totals, when it was run
    warn_pct: float = 5.0
    block_pct: float = 10.0
    in_design: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool), repr=False)
    cause: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=object), repr=False)

    @property
    def gained_total(self) -> Tally:
        return _sum(self.gained.values())

    def change_pct(self, metric: str) -> float:
        """Practical design against the shell, per cent; nan when the shell has none of it."""
        base = getattr(self.shell, metric)
        return 100.0 * (getattr(self.design, metric) - base) / base if base else float("nan")

    def status(self, metric: str) -> str:
        change = abs(self.change_pct(metric))
        if np.isnan(change) or change <= self.warn_pct:
            return OK
        return WARNING if change <= self.block_pct else BLOCKED

    def residual(self) -> dict[str, float]:
        """design - (shell + gained - left behind), per figure. Zero to rounding: it is the same classification
        counted two ways, so anything else is a bug."""
        gained = self.gained_total
        return {f: getattr(self.design, f) - (getattr(self.shell, f) + getattr(gained, f) - getattr(self.left_behind, f))
                for f in ("blocks", "ore_blocks", "waste_blocks", "rock_tonnes", "ore_tonnes", "value")}


def _sum(tallies) -> Tally:
    total = Tally()
    for t in tallies:
        for f in total.__dataclass_fields__:
            setattr(total, f, getattr(total, f) + getattr(t, f))
    return total


def _levels(blocks: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Distinct block-centre elevations, and each block's index into them."""
    return np.unique(np.round(blocks["z"].to_numpy(), 6), return_inverse=True)


def _road_cut(ramp: Ramp, sectors: list[SectorGeometry]):
    """The road as short straight pieces, each with the elevation it sits at, and how fast the wall cut above it
    leans outward per metre of height (the cotangent of the face angle of the sector the piece lies in)."""
    a = np.column_stack([ramp.x[:-1], ramp.y[:-1]])
    b = np.column_stack([ramp.x[1:], ramp.y[1:]])
    mid = (a + b) / 2.0
    bearing = np.degrees(np.arctan2(mid[:, 0] - ramp.centre[0], mid[:, 1] - ramp.centre[1])) % 360.0
    lean = np.zeros(len(mid))
    assigned = np.zeros(len(mid), dtype=bool)
    for sector in sectors:
        hit = sector_mask(sector, bearing) & ~assigned
        lean[hit] = 1.0 / math.tan(math.radians(sector.face_angle_deg))
        assigned |= hit
    pieces = shapely.linestrings(np.stack([a, b], axis=1))
    return pieces, (ramp.z[:-1] + ramp.z[1:]) / 2.0, lean


def _road_cut_at(rl: float, road, half_width: float, window: float) -> BaseGeometry:
    """The road cut at one elevation: every stretch of road at or below it, widened by the lean of the wall
    above it. `window` drops road so far below that the ordinary wall has already moved past it."""
    pieces, z, lean = road
    below = (z <= rl) & (rl - z <= window)
    if not below.any():
        return Polygon()
    return shapely.union_all(shapely.buffer(pieces[below], half_width + (rl - z[below]) * lean[below], quad_segs=8))


def reconcile(blocks: pd.DataFrame, in_pit: np.ndarray, plain: BenchStack, stack: BenchStack, ramp: Ramp | None,
              limits: DesignLimitsConfig, raster: dict | None = None) -> Reconciliation:
    """Classify every block against the shell and the three nested designs.

    `plain` is the stack with the floor as the optimiser has it and `stack` the one with the floor widened; they
    are the same object when nothing was widened."""
    x, y = blocks["x"].to_numpy(), blocks["y"].to_numpy()
    levels, level_of = _levels(blocks)
    in_batter, in_width, in_design = (np.zeros(len(blocks), dtype=bool) for _ in range(3))
    road = window = None
    if ramp is not None and len(ramp.x) > 1:
        road = _road_cut(ramp, stack.sectors)
        window = _cut_window(ramp, stack)

    for i, level in enumerate(levels):
        bench = stack.bench_at(level)
        if bench is None:
            continue
        idx = np.flatnonzero(level_of == i)
        section = plain.section_at(level)
        in_batter[idx] = shapely.contains_xy(section, x[idx], y[idx])
        widened = section if stack is plain else stack.section_at(level)
        in_width[idx] = shapely.contains_xy(widened, x[idx], y[idx]) if widened is not section else in_batter[idx]
        cut = _road_cut_at(level, road, ramp.sizing.width_m / 2.0, window) if road is not None else None
        full = widened if cut is None or cut.is_empty else widened.union(cut)
        in_design[idx] = shapely.contains_xy(full, x[idx], y[idx]) if full is not widened else in_width[idx]

    cause = np.where(in_batter, "batter", np.where(in_width, "min_width", np.where(in_design, "ramp", "")))
    new = in_design & ~in_pit
    gained = {c: Tally.of(blocks, new & (cause == c)) for c in CAUSES}
    return Reconciliation(
        Tally.of(blocks, in_pit), Tally.of(blocks, in_design), gained, Tally.of(blocks, in_pit & ~in_design),
        _per_bench(blocks, in_pit, in_design, cause, level_of, levels), raster,
        limits.recon_warn_pct, limits.recon_block_pct, in_design, cause,
    )


def _cut_window(ramp: Ramp, stack: BenchStack) -> float:
    """How far above a stretch of road its cut can still stick out of the ordinary wall: where the excess
    (road width - berm) - h * berm / H reaches zero, in the sector with the least berm."""
    height = stack.benches[0].crest_rl - stack.benches[-1].toe_rl
    windows = [(ramp.sizing.width_m - s.berm_width) * s.bench_height / s.berm_width if s.berm_width > 0 else height
               for s in stack.sectors]
    return min(height, max(windows) + stack.sectors[0].bench_height)


def _per_bench(blocks, in_pit, in_design, cause, level_of, levels) -> pd.DataFrame:
    """One row per elevation, category and cause: the map of screen 5 as a table."""
    category = np.where(in_pit & in_design, "both", np.where(in_design, "design_only", np.where(in_pit, "shell_only", "")))
    ore = blocks["destination"].to_numpy() == 1
    frame = pd.DataFrame({
        "rl": levels[level_of], "category": category, "cause": np.where(category == "design_only", cause, ""),
        "blocks": 1, "ore_blocks": ore.astype(int), "waste_blocks": (~ore).astype(int),
        "rock_tonnes": blocks["rock_tonnes"].to_numpy(),
        "ore_tonnes": np.where(ore, blocks["ore_tonnes"].to_numpy(), 0.0), "value": blocks["value"].to_numpy(),
    })
    frame = frame[frame["category"] != ""]
    return frame.groupby(["rl", "category", "cause"], as_index=False).sum().sort_values(
        ["rl", "category", "cause"], ascending=[False, True, True]).reset_index(drop=True)
