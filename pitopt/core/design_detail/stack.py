"""
The bench stack: crest and toe outline of every bench, built from one
anchor outline by repeated offsetting.

Bench k counted from the anchor has its crest at

    crest_offset(k) = k * run + floor(k / N) * berm

from the anchor outline and its toe one face run further in (PRD F-DES-6).
With `anchor: floor` the anchor is the floor outline and the walls are
offset outward as the stack climbs; with `anchor: crest` it is the crest and
the stack steps inward as it descends. The offset distance depends on the
sector the wall faces, mixed across boundaries, so the same routine builds a
uniform pit and a sectored one.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from ..cancel import CancelToken
from .config import DesignDetailConfig
from .offset import azimuth_profile, offset
from .parameters import SectorGeometry

MAX_BENCHES = 200         # a guard against a mistyped bench height, not a design limit


@dataclass
class Bench:
    """One bench. `index` counts from the top: 1 is the highest bench."""

    index: int
    crest_rl: float
    toe_rl: float
    crest: BaseGeometry
    toe: BaseGeometry
    crest_offsets: dict[str, float]      # per sector: distance of the crest ring from the anchor outline
    toe_offsets: dict[str, float]

    @property
    def height(self) -> float:
        return self.crest_rl - self.toe_rl


@dataclass
class BenchStack:
    benches: list[Bench]                 # top to bottom
    anchor: str
    anchor_rl: float
    sectors: list[SectorGeometry]
    warnings: list[str] = field(default_factory=list)
    collapsed_at: int | None = None      # bench, counted from the crest, that has no area left (crest anchor only)
    anchor_outline: BaseGeometry | None = None
    config: DesignDetailConfig | None = None

    def bench_at(self, rl: float) -> Bench | None:
        """The bench whose face spans this elevation; None above the crest or below the floor."""
        for bench in self.benches:
            if bench.toe_rl - 1e-9 <= rl <= bench.crest_rl + 1e-9:
                return bench
        return None

    def section_at(self, rl: float) -> BaseGeometry:
        """The excavation as cut by a horizontal plane at this elevation: the ring at the matching point up
        the face, between the bench's toe and its crest. Empty outside the built stack."""
        bench = self.bench_at(rl)
        if bench is None:
            return Polygon()
        fraction = (rl - bench.toe_rl) / bench.height
        offsets = [bench.toe_offsets[s.name] + fraction * (bench.crest_offsets[s.name] - bench.toe_offsets[s.name])
                   for s in self.sectors]
        return ring_outline(self.anchor_outline, self.sectors, offsets, self.config, grow=self.anchor == "floor")[0]


def bench_count(top_rl: float, bottom_rl: float, bench_height: float) -> int:
    """Whole benches between two elevations; a partial one at the top counts
    as a bench, since the wall still has to reach the crest."""
    n = math.ceil((top_rl - bottom_rl) / bench_height - 1e-9)
    if n < 1:
        raise ValueError(f"crest {top_rl:g} is not above the floor {bottom_rl:g}")
    if n > MAX_BENCHES:
        raise ValueError(f"{n} benches of {bench_height:g} m between {bottom_rl:g} and {top_rl:g}: check the bench height")
    return n


def _distance(config: DesignDetailConfig, sectors: list[SectorGeometry], offsets: list[float]):
    """A number when every sector asks for the same distance, else a
    bearing-dependent function. The number path is shapely's own buffer,
    the one that supports a mitre join."""
    if max(offsets) - min(offsets) < 1e-9:
        return offsets[0], False
    return azimuth_profile(sectors, offsets, config.blend_deg), True


def ring_outline(anchor_outline: BaseGeometry, sectors: list[SectorGeometry], offsets: list[float],
                 config: DesignDetailConfig, *, grow: bool) -> tuple[BaseGeometry, bool]:
    """The anchor outline moved out (or in) by each sector's distance. The second value says whether the
    distance varied by sector, which is when a mitre join gives way to a round one."""
    distance, variable = _distance(config, sectors, offsets)
    style = "round" if variable else config.join_style
    return offset(anchor_outline, distance, grow=grow, join_style=style, miter_limit=config.miter_limit), variable


def build_bench_stack(anchor_outline: BaseGeometry, anchor_rl: float, n_benches: int, sectors: list[SectorGeometry],
                      config: DesignDetailConfig, on_bench: Callable[[Bench, int], None] | None = None,
                      cancel: CancelToken | None = None) -> BenchStack:
    """Build `n_benches` benches from an anchor outline.

    `on_bench(bench, n_done)` is called as each bench is finished, in the order they are built, so a viewer can
    draw the pit while it is still being computed; `cancel` is checked before each one.

    Floor anchor: benches are numbered upward internally and reported from
    the top, so a bench keeps the same index whichever way it was built."""
    heights = {s.bench_height for s in sectors}
    if len(heights) != 1:
        raise ValueError("sectors with different bench heights are not supported: benches must share elevations")
    height = heights.pop()
    grow = config.anchor == "floor"
    stack = BenchStack([], config.anchor, anchor_rl, sectors, anchor_outline=anchor_outline, config=config)
    mitre_dropped = False

    def ring(k: int, far: bool) -> tuple[BaseGeometry, dict[str, float], bool]:
        """The ring of bench k nearer the anchor (`far=False`) or a face run further from it."""
        offsets = [s.toe_offset(k) if far else s.crest_offset(k) for s in sectors]
        outline, variable = ring_outline(anchor_outline, sectors, offsets, config, grow=grow)
        return outline, {s.name: o for s, o in zip(sectors, offsets)}, variable

    if anchor_outline.is_empty:
        raise ValueError("the anchor outline is empty: nothing to build a pit from")

    built: list[Bench] = []
    for k in range(n_benches):
        if cancel is not None:
            cancel.check()
        near, near_off, v_near = ring(k, far=False)
        far, far_off, v_far = ring(k, far=True)
        mitre_dropped |= (v_near or v_far) and config.join_style == "mitre"
        if grow:       # k counts upward from the floor: the near ring is the toe, the far ring the crest
            crest, toe, crest_off, toe_off = far, near, far_off, near_off
            crest_rl, toe_rl = anchor_rl + (k + 1) * height, anchor_rl + k * height
        else:          # k counts downward from the crest: the near ring is the crest
            crest, toe, crest_off, toe_off = near, far, near_off, far_off
            crest_rl, toe_rl = anchor_rl - k * height, anchor_rl - (k + 1) * height
        if crest.is_empty or toe.is_empty:
            stack.collapsed_at = k + 1
            stack.warnings.append(
                f"bench {k + 1} from the crest has no area left at RL {toe_rl:g}: the pit closes above its floor"
            )
            break
        bench = Bench(n_benches - k if grow else k + 1, crest_rl, toe_rl, crest, toe, crest_off, toe_off)
        built.append(bench)
        if on_bench is not None:
            on_bench(bench, len(built))

    ordered = sorted(built, key=lambda b: -b.crest_rl)
    for i, bench in enumerate(ordered, start=1):
        bench.index = i
    stack.benches = ordered
    if mitre_dropped:
        stack.warnings.append("mitre join needs one distance all round; the sector boundaries use round joins instead")
    return stack
