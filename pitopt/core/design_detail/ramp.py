"""
The haul road, laid on the bench stack.

The road climbs from the floor to the crest at one fixed grade, so every
bench of height H takes exactly H / grade metres of road measured along the
plan. That is the constraint the whole construction is built on, and it is
built in rather than hoped for: each climb is solved for the plan distance
it needs, and the grade is then measured back from the finished polyline
so a fault in the construction shows up as a wrong number, not a hidden one.

Where the road runs. Between two benches sits a flat: the inner edge is the
crest of the lower bench, the outer edge the toe of the upper. The road
takes that flat, its centreline half a width outside the lower crest. Going
up one bench it drifts outward from the ring of one flat to the ring of the
next while it advances round the pit, in polar terms about the floor's
centre. Each bench's climb is therefore a short spiral, and the spiral is
what a bench polyline is split by and replaced with (PRD F-DES-6).

Limits stated plainly, because a design tool that hides them is not
defensible: the pit's rings are read as a radius at each azimuth from the
floor's centre, so a ring that a ray leaves and re-enters (a strongly
concave pit) is followed along its outermost edge and is warned about; a ring
that splits into parts, or a bench too steep to climb at the grade in the
plan distance available, breaks the road there and the design says which
bench.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from .config import RampConfig
from .offset import offset
from .stack import BenchStack

AZIMUTHS = np.arange(0.0, 360.0, 0.5)         # the bearings every ring is read at
STEPS = 48                                    # plan points per bench climb
_BISECT = 80


@dataclass(frozen=True)
class RampSizing:
    """The road's width and grade, and how the width was decided."""

    width_m: float
    required_width_m: float | None       # what the fleet needs, when a truck was given
    grade_pct: float
    source: str                          # "truck" | "manual"
    grade_min_pct: float
    grade_max_pct: float

    @property
    def width_ok(self) -> bool:
        return self.required_width_m is None or self.width_m >= self.required_width_m - 1e-9

    @property
    def grade_ok(self) -> bool:
        return self.grade_min_pct <= self.grade_pct <= self.grade_max_pct


def size_ramp(config: RampConfig) -> RampSizing:
    """Width from the truck calculator, or as stated."""
    required = None
    if config.truck_width_m is not None:
        required = config.truck_width_m * (1.5 * config.lanes + 0.5) + config.safety_berm_m + config.drain_m
    if config.width_m is not None:
        width, source = config.width_m, "manual"
    else:
        width, source = required, "truck"
    return RampSizing(width, required, config.grade_pct, source, config.grade_min_pct, config.grade_max_pct)


@dataclass
class RingTable:
    """A ring's outermost radius at every azimuth about a centre."""

    radius: np.ndarray
    parts: int
    holes: int
    branched: int                        # azimuths where the ray crosses the outer edge more than once

    def at(self, azimuth) -> np.ndarray:
        return np.interp(np.asarray(azimuth, dtype=float) % 360.0, AZIMUTHS, self.radius, period=360.0)

    @property
    def defined(self) -> bool:
        return self.parts == 1 and bool(np.isfinite(self.radius).all())


def ring_table(geometry: BaseGeometry, centre: tuple[float, float]) -> RingTable:
    """Read a ring as radius against bearing (compass: north 0, east 90)."""
    undefined = RingTable(np.full(len(AZIMUTHS), np.nan), 0, 0, 0)
    if geometry.is_empty:
        return undefined
    polygons = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    outer = shapely.union_all([p.exterior for p in polygons])
    minx, miny, maxx, maxy = geometry.bounds
    reach = 2.0 * math.hypot(maxx - minx, maxy - miny) + 10.0
    rad = np.radians(AZIMUTHS)
    ends = np.column_stack([centre[0] + reach * np.sin(rad), centre[1] + reach * np.cos(rad)])
    rays = shapely.linestrings(np.stack([np.tile(centre, (len(ends), 1)), ends], axis=1))
    hits = shapely.intersection(rays, outer)

    radius = np.full(len(AZIMUTHS), np.nan)
    branched = 0
    for i, hit in enumerate(hits):
        if hit.is_empty:
            continue
        xy = shapely.get_coordinates(hit)
        distance = np.hypot(xy[:, 0] - centre[0], xy[:, 1] - centre[1])
        radius[i] = distance.max()
        branched += int(len(np.unique(np.round(distance, 6))) > 1)
    return RingTable(radius, len(polygons), sum(len(p.interiors) for p in polygons), branched)


@dataclass
class RampBreak:
    bench: int                           # bench, counted from the top, the road could not climb
    reason: str


@dataclass
class Ramp:
    """The finished road: a 3D centreline, a strip per bench, and what went wrong if anything."""

    pattern: str
    sizing: RampSizing
    direction: str
    entry_azimuth_deg: float
    entry_defaulted: bool
    centre: tuple[float, float]
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    azimuth: np.ndarray                  # unwrapped bearing: keeps counting past 360 as the road goes round
    bench_of_point: np.ndarray           # bench (from the top) each point climbs; the floor point is the lowest
    strips: dict[int, BaseGeometry]
    reversals: list[int] = field(default_factory=list)
    broken: RampBreak | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.broken is None

    @property
    def horizontal_length_m(self) -> float:
        return float(np.hypot(np.diff(self.x), np.diff(self.y)).sum()) if len(self.x) > 1 else 0.0

    @property
    def turns(self) -> float:
        return float(abs(self.azimuth[-1] - self.azimuth[0]) / 360.0) if len(self.azimuth) > 1 else 0.0

    def grade_by_bench(self) -> dict[int, float]:
        """Grade in per cent, measured from the polyline: rise over plan length, bench by bench."""
        grades = {}
        for bench in sorted(set(self.bench_of_point.tolist())):
            members = np.flatnonzero(self.bench_of_point == bench)
            # a climb starts on the node the previous climb ended on, which that climb owns
            idx = np.arange(max(members[0] - 1, 0), members[-1] + 1)
            run = float(np.hypot(np.diff(self.x[idx]), np.diff(self.y[idx])).sum())
            rise = float(self.z[idx[-1]] - self.z[idx[0]])
            if run > 0:
                grades[int(bench)] = 100.0 * rise / run
        return grades


def wall_tables(stack: BenchStack) -> tuple[tuple[float, float], RingTable, RingTable]:
    """The floor's centre, and the crest ring and the floor ring read about it."""
    floor = stack.benches[-1].toe
    centre_point = floor.centroid if floor.contains(floor.centroid) else floor.representative_point()
    centre = (float(centre_point.x), float(centre_point.y))
    return centre, ring_table(stack.benches[0].crest, centre), ring_table(floor, centre)


def _interfaces(stack: BenchStack) -> list[tuple[float, BaseGeometry]]:
    """The flat between each pair of benches, top to bottom: its elevation and its inner ring.
    Index 0 is the crest and index n the floor."""
    b = stack.benches
    flats = [(b[0].crest_rl, b[0].crest)]
    flats += [(b[j].crest_rl, b[j].crest) for j in range(1, len(b))]
    flats.append((b[-1].toe_rl, b[-1].toe))
    return flats


def _plan(centre, phi0, sign, delta, r_from: RingTable, r_to: RingTable):
    t = np.linspace(0.0, 1.0, STEPS + 1)
    phi = phi0 + sign * delta * t
    r = (1.0 - t) * r_from.at(phi) + t * r_to.at(phi)
    xy = np.column_stack([centre[0] + r * np.sin(np.radians(phi)), centre[1] + r * np.cos(np.radians(phi))])
    return phi, xy, float(np.hypot(*np.diff(xy, axis=0).T).sum())


def _solve_climb(centre, phi0, sign, r_from, r_to, target):
    """The azimuth the road must travel so that this climb is `target` metres long in plan.
    None when the ring shift alone is already longer than the road allowed at the grade."""
    if _plan(centre, phi0, sign, 0.0, r_from, r_to)[2] > target:
        return None
    hi = 1.0
    while _plan(centre, phi0, sign, hi, r_from, r_to)[2] < target:
        hi *= 2.0
        if hi > 720.0:
            return None
    lo = 0.0
    for _ in range(_BISECT):
        mid = 0.5 * (lo + hi)
        if _plan(centre, phi0, sign, mid, r_from, r_to)[2] < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def default_entry_azimuth(top: RingTable, floor: RingTable) -> float:
    """The bearing at which the wall is widest, so the road has the most room."""
    width = top.radius - floor.radius
    if not np.isfinite(width).any():
        return 0.0
    return float(AZIMUTHS[int(np.nanargmax(width))])


def build_ramp(stack: BenchStack, sizing: RampSizing, config: RampConfig,
               tables: tuple[tuple[float, float], RingTable, RingTable] | None = None) -> Ramp:
    """Lay the road from the floor to the crest. `tables` is `wall_tables(stack)` when the caller
    already has it."""
    n = len(stack.benches)
    centre, top, floor = tables or wall_tables(stack)
    flats = _interfaces(stack)
    half = sizing.width_m / 2.0
    tables = [ring_table(offset(ring, half, grow=True), centre) for _, ring in flats]
    warnings = list(_ring_warnings(tables, top, floor))

    defaulted = config.entry_azimuth_deg is None
    phi = default_entry_azimuth(top, floor) if defaulted else float(config.entry_azimuth_deg)
    entry = phi
    sign = 1.0 if config.direction == "clockwise" else -1.0
    per_leg = max(1, math.ceil(n / (config.switchbacks + 1))) if config.pattern == "switchback" else n

    xs, ys, zs, az, bench_of = [], [], [], [], []
    strips: dict[int, BaseGeometry] = {}
    reversals: list[int] = []
    broken = None
    grade = sizing.grade_pct / 100.0

    for step, bench in enumerate(range(n, 0, -1)):            # climb bench n first, the one on the floor
        lower, upper = tables[bench], tables[bench - 1]
        if bench < n and step % per_leg == 0:
            sign, _ = -sign, reversals.append(bench)
        if not (lower.defined and upper.defined):
            broken = RampBreak(bench, _why(lower, upper))
            break
        z_from, z_to = flats[bench][0], flats[bench - 1][0]
        target = (z_to - z_from) / grade
        delta = _solve_climb(centre, phi, sign, lower, upper, target)
        if delta is None:
            drift = float(np.nanmax(np.abs(upper.radius - lower.radius)))
            broken = RampBreak(bench, f"the road shifts outward by up to {drift:.1f} m over one bench, more than the "
                                      f"{target:.1f} m of road the {sizing.grade_pct:g}% grade allows")
            break
        phis, xy, length = _plan(centre, phi, sign, delta, lower, upper)
        start = 0 if not xs else 1                                 # the node the last climb ended on is not repeated
        cumulative = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
        xs += xy[start:, 0].tolist()
        ys += xy[start:, 1].tolist()
        zs += (z_from + (z_to - z_from) * cumulative[start:] / length).tolist()
        az += phis[start:].tolist()
        bench_of += [bench] * (len(xy) - start)
        strips[bench] = LineString(xy).buffer(half, cap_style="flat")
        phi = float(phis[-1])

    if config.pattern == "switchback":
        warnings.append(
            f"hairpin platforms of {config.hairpin_radius_m:g} m radius are assumed to fit at the {len(reversals)} "
            "reversal(s); their geometry is not drawn or checked"
        )
    return Ramp(config.pattern, sizing, config.direction, entry, defaulted, centre, np.asarray(xs), np.asarray(ys),
                np.asarray(zs), np.asarray(az), np.asarray(bench_of), strips, reversals, broken, warnings)


def _why(lower: RingTable, upper: RingTable) -> str:
    for table, where in ((lower, "below"), (upper, "above")):
        if table.parts > 1:
            return f"the wall {where} splits into {table.parts} separate parts, so there is no single ring to run the road along"
        if not np.isfinite(table.radius).all():
            return f"the wall {where} is missing or does not surround the floor's centre at every bearing"
    return "the wall could not be read"


def _ring_warnings(tables: list[RingTable], top: RingTable, floor: RingTable):
    if any(t.holes for t in tables) or floor.holes:
        yield "an island inside the pit is ignored: the road follows the outer wall only"
    if any(t.branched for t in tables) or top.branched or floor.branched:
        yield ("part of the wall is concave enough that a ray from the floor's centre leaves and re-enters it; "
               "the road follows the outermost edge there, so check the road against the plan")


def footprint(ramp: Ramp) -> Polygon:
    """All road strips together, for drawing and for checking against the wall."""
    return shapely.union_all(list(ramp.strips.values())) if ramp.strips else Polygon()
