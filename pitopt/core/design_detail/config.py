"""
Configuration of the detailed pit design (design.detail, PRD F-DES-6): sectors, berm criteria, crest
smoothing, the geotechnical limits, the haul road and the grade classes — and the checks that refuse a
parameter the design cannot defend.

Kept with the design engine rather than in pitopt/config.py so the detailed design is one self-contained
package: pitopt.config composes these into ProjectConfig and re-exports them, and nothing here imports
anything from the optimiser.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BermConfig:
    """
    How the catch berm width is decided.

    A berm is not a free parameter: it is the bench width needed to catch
    rockfall from the face above it, so it follows from the bench height
    and the face angle by a published criterion. Letting a user type all
    three invites a combination that is geometrically inconsistent.

      ritchie   the modified Ritchie criterion, W = 0.2 H + 4.5 m — the
                catch-bench rule most Western codes and feasibility
                studies quote. Derived for benches up to about 30 m; above
                that it is extrapolation and the design warns.
      ryan      Ryan & Pryor's criterion, W = a H + b. There is no
                industry-agreed pair of coefficients, so there is no
                default: supply them from the geotechnical report or the
                design refuses to run rather than invent a berm.
      slope     the width that makes the inter-ramp angle equal
                slope.overall_angle_deg, so the design and the optimiser
                agree on the wall. Reproduces the behaviour of a blank
                design.berm_width.
      manual    `width` exactly as given, for a berm dictated by a study.
    """
    method: str = "ritchie"
    width: float | None = None          # manual only
    ryan_a: float | None = None         # ryan only — from the geotechnical report
    ryan_b: float | None = None


@dataclass
class SectorConfig:
    """
    One azimuth sector of the pit wall, with its own geotechnical
    geometry. Walls fail by structure, and structure has an orientation,
    so a real design varies around the pit rather than applying one angle
    to the whole rim.

    Every geometry field left unset inherits the corresponding value from
    the parent `design:` block, so a sector can differ in one parameter
    without restating the rest. `azimuth_from`/`azimuth_to` are compass
    bearings in degrees and may wrap through north (315 -> 45).
    """
    name: str = ""
    azimuth_from: float = 0.0
    azimuth_to: float = 360.0
    bench_height: float | None = None
    face_angle_deg: float | None = None
    berm_every_n_benches: int | None = None
    berm: BermConfig | None = None
    ira_max_deg: float | None = None
    osa_max_deg: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.berm, dict):
            self.berm = BermConfig(**self.berm)


@dataclass
class SmoothingConfig:
    """
    Crest simplification applied before the walls are offset.

    A maximum_closure shell is a staircase of whole blocks: its rim steps in
    and out by a block at a time. Offsetting that staircase directly
    reproduces every step as a notch in all fifteen benches, which no
    survey crew could peg and no excavator could dig. Simplifying the rim
    first is what turns an optimisation result into a diggable shape, and
    it is the single stage with the most influence on the answer — so it
    is a visible, recorded parameter, never a hidden clean-up.

    `tolerance_m` is the Douglas-Peucker band: no simplified point moves
    further than this from the original rim. Unset means one block
    diagonal, the resolution the shell actually carries. `closing_m` fills
    single-block notches before simplifying. `min_area_m2` drops fragments
    too small to mine, and is reported rather than silently discarded.
    """
    enabled: bool = True
    tolerance_m: float | None = None
    closing_m: float | None = None
    min_area_m2: float | None = None


@dataclass
class DesignLimitsConfig:
    """
    The geotechnical envelope the design is checked against, and the
    minimum geometry a mine can actually work in.

    These are limits, not inputs: the design is built from bench geometry
    and then measured against them. `warn_margin_deg` is how close to a
    limit counts as a warning rather than a pass — a wall designed 0.1
    degrees inside its limit has no tolerance left for survey error.
    """
    ira_max_deg: float | None = None
    osa_max_deg: float | None = None
    warn_margin_deg: float = 0.5
    min_mining_width_m: float = 30.0
    # A floor narrower than the minimum mining width cannot be worked. With a
    # floor anchor it is widened to the minimum, and the extra material is
    # reported as its own line of dilution; a crest anchor cannot widen the
    # floor and reports the conflict instead.
    widen_floor_to_min_width: bool = True
    # Tonnage, ore and value of the practical design against the optimiser
    # shell: within warn is OK, within block a warning, beyond it blocked.
    recon_warn_pct: float = 5.0
    recon_block_pct: float = 10.0
    # Difference below which two coordinates are the same point. 1 mm: far
    # finer than any survey, coarse enough that GEOS predicates stay robust.
    tolerance_m: float = 0.001


@dataclass
class RampConfig:
    """
    The haul road. Its width comes from the largest truck, its grade from
    what that truck can pull loaded, and both are equipment facts rather
    than design preferences.

    Given `truck_width_m`, the running surface is the width the fleet needs
    to pass safely: each lane one truck wide, half a truck of clearance at
    both edges and between lanes, so 1.5 * lanes + 0.5 truck widths (3.5
    for the usual two lanes), plus the safety berm and the drain. A
    `width_m` given as well is used as stated and checked against that
    requirement; a road narrower than the fleet needs is reported, not
    quietly widened. With neither the design refuses, rather than assume
    a fleet.

    `direction` is the way the road climbs round the pit, seen from above.
    `entry_azimuth_deg` is the bearing at which it leaves the floor; unset,
    the design picks the bearing where the wall is widest and says so.
    A switchback reverses `switchbacks` times, and each hairpin needs a
    platform the truck can turn on: `hairpin_radius_m` comes from the
    truck's turning circle and has no default.
    """
    enabled: bool = True
    pattern: str = "spiral"             # spiral | switchback
    width_m: float | None = None
    truck_width_m: float | None = None
    lanes: int = 2
    safety_berm_m: float = 0.0
    drain_m: float = 0.0
    grade_pct: float = 9.0
    grade_min_pct: float = 8.0
    grade_max_pct: float = 10.0
    direction: str = "clockwise"        # clockwise | anticlockwise
    entry_azimuth_deg: float | None = None
    switchbacks: int | None = None      # switchback only: how many times the road reverses
    hairpin_radius_m: float | None = None


@dataclass
class GradeClassConfig:
    """
    Grade classes for the plan, the sections and the block reconciliation.

    Commodity-neutral by construction: the column is named and the breaks
    are the project's own numbers in that column's own units, so the same
    code serves a copper porphyry in per cent and a gold deposit in grams
    per tonne. `breaks` are the boundaries between classes, so there is
    always one more name than break.
    """
    grade_col: str | None = None        # unset: the first product's grade column
    breaks: list = field(default_factory=list)
    names: list = field(default_factory=list)


@dataclass
class DesignDetailConfig:
    """
    Detailed pit design: bench polygons, sector geometry, a ramp and the
    validations that say whether the result is buildable (F-DES-6).

    Off by default. With `enabled: false` nothing here runs and the design
    surfaces are exactly the uniform benched bowl of `design:` above, so
    an existing project keeps the answer it had.

    `anchor` decides which ring of the optimiser shell the design honours,
    and it is the one choice that changes what the design means:

      floor   the design floor holds the shell's floor and the walls are
              offset outward and upward from it. The ore the optimiser
              paid for stays inside the design, the crest lands where the
              geometry puts it, and the reconciliation measures the waste
              the practical wall adds. This is the usual way to turn an
              optimisation shell into a pit, and it is what `design:`
              already does — so the two agree.
      crest   the crest is held and the benches are offset inward and
              downward from it. Use it when the rim is fixed by something
              outside the optimisation — a lease boundary, a river, plant
              infrastructure — and accept that the floor, and the ore in
              it, is what gives way.

    `blend_deg` is the azimuth band either side of a sector boundary over
    which the two sectors' offsets are mixed linearly, so a change of
    geotechnical domain does not appear as a step in the wall.
    """
    enabled: bool = False
    anchor: str = "floor"               # floor | crest
    source: str = "final_shell"         # final_shell | pushback
    berm_every_n_benches: int = 1
    join_style: str = "round"           # round | mitre
    miter_limit: float = 2.0
    blend_deg: float = 12.0
    berm: BermConfig = field(default_factory=BermConfig)
    sectors: list = field(default_factory=list)
    smoothing: SmoothingConfig = field(default_factory=SmoothingConfig)
    limits: DesignLimitsConfig = field(default_factory=DesignLimitsConfig)
    ramp: RampConfig = field(default_factory=RampConfig)
    grade_classes: GradeClassConfig = field(default_factory=GradeClassConfig)

    def __post_init__(self) -> None:
        if isinstance(self.berm, dict):
            self.berm = BermConfig(**self.berm)
        if isinstance(self.smoothing, dict):
            self.smoothing = SmoothingConfig(**self.smoothing)
        if isinstance(self.limits, dict):
            self.limits = DesignLimitsConfig(**self.limits)
        if isinstance(self.ramp, dict):
            self.ramp = RampConfig(**self.ramp)
        if isinstance(self.grade_classes, dict):
            self.grade_classes = GradeClassConfig(**self.grade_classes)
        self.sectors = [SectorConfig(**s) if isinstance(s, dict) else s for s in self.sectors]


def validate_detail(t: DesignDetailConfig, bench_height: float) -> None:
    """Everything the detailed design needs before it draws a bench.

    A parameter it cannot defend is refused here rather than
    substituted, because a berm invented from a missing coefficient
    looks exactly like a berm from the geotechnical report once it is
    in a drawing."""
    if t.anchor not in ("floor", "crest"):
        raise ValueError("design.detail.anchor must be 'floor' or 'crest'")
    if t.source == "pushback":
        raise ValueError("design.detail.source 'pushback' is not implemented yet; use 'final_shell'")
    if t.source != "final_shell":
        raise ValueError("design.detail.source must be 'final_shell'")
    if t.join_style not in ("round", "mitre"):
        raise ValueError("design.detail.join_style must be 'round' or 'mitre'")
    if t.miter_limit <= 0:
        raise ValueError("design.detail.miter_limit must be > 0")
    if t.berm_every_n_benches < 1:
        raise ValueError("design.detail.berm_every_n_benches must be >= 1")
    if not 0 <= t.blend_deg < 90:
        raise ValueError("design.detail.blend_deg must be in [0, 90)")

    _validate_berm(t.berm, "design.detail.berm")
    for index, s in enumerate(t.sectors):
        where = f"design.detail.sectors[{index}]" + (f" ({s.name})" if s.name else "")
        if s.bench_height is not None and s.bench_height <= 0:
            raise ValueError(f"{where}: bench_height must be > 0")
        if s.bench_height is not None and s.bench_height != bench_height:
            raise ValueError(
                f"{where}: bench_height {s.bench_height:g} differs from design.bench_height {bench_height:g}. "
                "Benches share elevations all round the pit, so a sector cannot have its own height yet"
            )
        arc = (s.azimuth_to - s.azimuth_from) % 360.0 or 360.0
        if len(t.sectors) > 1 and arc < 2 * t.blend_deg:
            raise ValueError(
                f"{where}: spans {arc:g} deg, less than the two blend zones ({2 * t.blend_deg:g} deg) "
                "at its edges; narrow design.detail.blend_deg or widen the sector"
            )
        if s.face_angle_deg is not None and not 0 < s.face_angle_deg < 90:
            raise ValueError(f"{where}: face_angle_deg must be in (0, 90)")
        if s.berm_every_n_benches is not None and s.berm_every_n_benches < 1:
            raise ValueError(f"{where}: berm_every_n_benches must be >= 1")
        for name in ("ira_max_deg", "osa_max_deg"):
            value = getattr(s, name)
            if value is not None and not 0 < value < 90:
                raise ValueError(f"{where}: {name} must be in (0, 90)")
        if s.berm is not None:
            _validate_berm(s.berm, f"{where}.berm")
    for problem in _azimuth_coverage(t.sectors):
        raise ValueError(f"design.detail.sectors: {problem}")

    m = t.smoothing
    for name in ("tolerance_m", "closing_m", "min_area_m2"):
        value = getattr(m, name)
        if value is not None and value < 0:
            raise ValueError(f"design.detail.smoothing.{name} must be >= 0")

    limits = t.limits
    for name in ("ira_max_deg", "osa_max_deg"):
        value = getattr(limits, name)
        if value is not None and not 0 < value < 90:
            raise ValueError(f"design.detail.limits.{name} must be in (0, 90)")
    if limits.warn_margin_deg < 0:
        raise ValueError("design.detail.limits.warn_margin_deg must be >= 0")
    if limits.min_mining_width_m <= 0 or limits.tolerance_m <= 0:
        raise ValueError("design.detail.limits: min_mining_width_m and tolerance_m must be > 0")
    if not 0 < limits.recon_warn_pct <= limits.recon_block_pct:
        raise ValueError("design.detail.limits: 0 < recon_warn_pct <= recon_block_pct")

    r = t.ramp
    if r.enabled:
        if r.pattern not in ("spiral", "switchback"):
            raise ValueError("design.detail.ramp.pattern must be 'spiral' or 'switchback'")
        if r.width_m is None and r.truck_width_m is None:
            raise ValueError(
                "design.detail.ramp needs width_m, or truck_width_m to size it from the fleet"
            )
        if r.width_m is not None and r.width_m <= 0:
            raise ValueError("design.detail.ramp.width_m must be > 0")
        if r.truck_width_m is not None and r.truck_width_m <= 0:
            raise ValueError("design.detail.ramp.truck_width_m must be > 0")
        if r.lanes < 1:
            raise ValueError("design.detail.ramp.lanes must be >= 1")
        if r.safety_berm_m < 0 or r.drain_m < 0:
            raise ValueError("design.detail.ramp: safety_berm_m and drain_m must be >= 0")
        if not 0 < r.grade_min_pct <= r.grade_max_pct:
            raise ValueError("design.detail.ramp: 0 < grade_min_pct <= grade_max_pct")
        if not r.grade_min_pct <= r.grade_pct <= r.grade_max_pct:
            raise ValueError(
                f"design.detail.ramp.grade_pct {r.grade_pct:g}% is outside "
                f"[{r.grade_min_pct:g}%, {r.grade_max_pct:g}%]"
            )
        if r.direction not in ("clockwise", "anticlockwise"):
            raise ValueError("design.detail.ramp.direction must be 'clockwise' or 'anticlockwise'")
        if r.entry_azimuth_deg is not None and not 0 <= r.entry_azimuth_deg < 360:
            raise ValueError("design.detail.ramp.entry_azimuth_deg must be in [0, 360)")
        if r.pattern == "switchback":
            if r.switchbacks is None or r.switchbacks < 1:
                raise ValueError("design.detail.ramp: a switchback needs switchbacks >= 1 (how many times it reverses)")
            if r.hairpin_radius_m is None or r.hairpin_radius_m <= 0:
                raise ValueError(
                    "design.detail.ramp: a switchback needs hairpin_radius_m from the truck's turning circle; "
                    "there is no default to assume"
                )

    g = t.grade_classes
    if g.breaks or g.names:
        if len(g.names) != len(g.breaks) + 1:
            raise ValueError(
                f"design.detail.grade_classes: {len(g.breaks)} breaks need {len(g.breaks) + 1} names, "
                f"got {len(g.names)}"
            )
        if any(b >= a for b, a in zip(g.breaks, g.breaks[1:])):
            raise ValueError("design.detail.grade_classes.breaks must increase")


def _validate_berm(berm: BermConfig, where: str) -> None:
    if berm.method not in ("ritchie", "ryan", "slope", "manual"):
        raise ValueError(f"{where}.method must be ritchie, ryan, slope or manual")
    if berm.method == "manual" and (berm.width is None or berm.width < 0):
        raise ValueError(f"{where}.method 'manual' needs width >= 0")
    if berm.method == "ryan" and (berm.ryan_a is None or berm.ryan_b is None):
        raise ValueError(
            f"{where}.method 'ryan' needs ryan_a and ryan_b from the geotechnical report — "
            "there is no industry-agreed default and the design will not invent one"
        )


def _azimuth_coverage(sectors: list) -> list[str]:
    """Sectors must tile the full 360 degrees exactly once.

    A gap leaves part of the rim with no geometry and an overlap leaves it
    with two, and either way some of the wall in the drawing was never
    designed. Cheap to check here, invisible once it is a DXF."""
    if not sectors:
        return []
    spans: list[tuple[float, float, str]] = []
    for index, s in enumerate(sectors):
        label = s.name or f"[{index}]"
        start = s.azimuth_from % 360.0
        length = (s.azimuth_to - s.azimuth_from) % 360.0
        if length == 0:
            length = 360.0 if len(sectors) == 1 else 0.0
        if length <= 0:
            return [f"sector {label} spans no azimuth ({s.azimuth_from:g} to {s.azimuth_to:g})"]
        if start + length <= 360.0:
            spans.append((start, start + length, label))
        else:                                       # wraps through north: two pieces
            spans.append((start, 360.0, label))
            spans.append((0.0, start + length - 360.0, label))

    spans.sort()
    problems, cursor = [], 0.0
    for start, end, label in spans:
        if start > cursor + 1e-6:
            problems.append(f"azimuth {cursor:g} to {start:g} deg is not covered by any sector")
        elif start < cursor - 1e-6:
            problems.append(f"sector {label} overlaps another between {start:g} and {cursor:g} deg")
        cursor = max(cursor, end)
    if cursor < 360.0 - 1e-6:
        problems.append(f"azimuth {cursor:g} to 360 deg is not covered by any sector")
    return problems
