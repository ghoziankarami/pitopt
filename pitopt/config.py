"""
Project configuration: typed parameter sets loaded from a YAML file.

Defaults are conventional first-pass values. They are deliberately
generic — replace every one of them with your own study's numbers before
the result means anything.

Economics is expressed as a list of *products*. A single-metal deposit is
one product; a mineral sands or polymetallic deposit is several, each
with its own price, recovery and processing cost. That matters whenever
products differ in value: combining zircon at 1,400/t and ilmenite at
280/t into one "grade" would price five tonnes of ilmenite as if it were
a tonne of zircon.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# The detailed design's own parameters live with its engine; they are re-exported here so ProjectConfig stays the
# one place a project is described, and existing `from pitopt.config import RampConfig` keeps working.
from .core.design_detail.config import (  # noqa: F401 — re-exported
    BermConfig,
    DesignDetailConfig,
    DesignLimitsConfig,
    GradeClassConfig,
    RampConfig,
    SectorConfig,
    SmoothingConfig,
    _azimuth_coverage,
    validate_detail,
)

# Divisor converting a reported grade into a fraction.
GRADE_DIVISOR = {"mass_percent": 100.0, "volume_percent": 100.0, "ppm": 1_000_000.0, "gpt": 1_000_000.0}

# Grade bases measured against block volume rather than block mass.
VOLUME_BASES = {"volume_percent"}

# Sales units per tonne of product, for products priced in ounces or pounds.
UNITS_PER_TONNE = {"t": 1.0, "kg": 1_000.0, "g": 1_000_000.0, "oz": 32_150.7466, "lb": 2_204.62262}


@dataclass
class BlockModelConfig:
    path: str
    x_col: str = "X"
    y_col: str = "Y"
    z_col: str = "Z"
    grade_col: str | None = None     # convenience for a single-product model
    density_col: str | None = None
    dx_col: str | None = None
    dy_col: str | None = None
    dz_col: str | None = None
    domain_col: str | None = None
    class_col: str | None = None
    # Actual material volume per block, where a reblocked model carries
    # partly-filled cells at the topographic and lateral edges. The grid
    # stays regular for precedence; only the volume valued is reduced.
    volume_col: str | None = None
    dx: float = 10.0
    dy: float = 10.0
    dz: float = 10.0
    density: float = 2.7
    include_classes: list = field(default_factory=list)   # empty = keep all
    ore_domains: list = field(default_factory=list)       # empty = any domain may be ore


@dataclass
class SurfaceConfig:
    """Topography. DXF is the industry interchange format; CSV XYZ is
    accepted as a fallback for DEM/point-cloud dumps."""
    path: str | None = None
    format: str = "dxf"
    x_col: str = "X"
    y_col: str = "Y"
    z_col: str = "Z"


@dataclass
class ProductConfig:
    """
    One saleable product.

    processing_cost_per_tonne is charged per tonne of *this* product, not
    per tonne of ore — the right basis for a mineral separation plant, and
    the way a by-product that costs nothing extra to recover is expressed
    (leave it at zero).

    `density` is only used when grades are volume-based: it converts the
    product's volume fraction into tonnes.

    `price_unit` is the unit the price and the per-unit costs are quoted in:
    t, kg, g, oz (troy) or lb — gold at 2,300 per oz, copper at 4.1 per lb.
    Quantities are still carried in tonnes internally.
    """
    name: str
    grade_col: str
    price: float
    price_unit: str = "t"
    plant_recovery: float = 1.0
    density: float = 1.0
    processing_cost_per_tonne: float = 0.0
    selling_cost_per_tonne: float = 0.0
    selling_cost_per_volume: float = 0.0

    @property
    def per_tonne(self) -> float:
        """Factor turning a per-price_unit figure into a per-tonne one."""
        return UNITS_PER_TONNE[self.price_unit]


@dataclass
class EconomicsConfig:
    """
    Costs are split by what they are charged on.

    Mining and rehabilitation apply to every block taken out of the pit,
    ore or waste — they are the price of removing material at all, and
    they are what a waste block's negative value is made of. Processing
    costs apply only to material routed to the plant.

    Both per-tonne and per-volume forms exist because the industry quotes
    both: hard rock works in dollars per tonne, alluvial and dredging
    operations in dollars per cubic metre. They are summed, so use
    whichever your study uses and leave the other at zero.
    """
    grade_basis: str = "mass_percent"
    mining_recovery: float = 1.0
    dilution: float = 0.0
    royalty_rate: float = 0.0

    mining_cost_per_tonne: float = 0.0
    mining_cost_per_volume: float = 0.0
    # Haulage grows with depth: extra mining cost per tonne for every metre
    # below the reference RL (default: top of the model). The usual
    # depth-based mining cost adjustment for deep pits.
    mining_cost_increment_per_m: float = 0.0
    mining_cost_reference_rl: float | None = None
    rehabilitation_cost_per_tonne: float = 0.0
    rehabilitation_cost_per_volume: float = 0.0

    processing_cost_per_tonne: float = 0.0
    processing_cost_per_volume: float = 0.0

    products: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.products = [ProductConfig(**p) if isinstance(p, dict) else p for p in self.products]


@dataclass
class SlopeConfig:
    """
    Overall slope angle driving the precedence cone. `max_bench_levels`
    caps how many benches up the cone template reaches. Leave it unset:
    it is then sized from the block shape so the cone reaches three blocks
    out, which keeps diagonal walls within a few degrees of the design
    angle. A fixed small value is only safe for roughly cubic blocks — on
    10 x 10 x 1 m blocks, 8 levels let diagonal walls stand at 40 degrees
    against a 30 degree design. `pitopt validate` prints the effective
    angle in both directions.

    `domain_angles` maps a value in the block model's domain column to
    its own angle, for models with distinct geotechnical domains.
    """
    overall_angle_deg: float = 45.0
    max_bench_levels: int | None = None
    domain_angles: dict = field(default_factory=dict)


@dataclass
class DesignConfig:
    """
    Geotechnical bench geometry for the pit design surfaces.

    bench_height, bench_face_angle_deg and berm_width define the wall;
    together they give the overall slope. Leave berm_width unset and it is
    sized so the benches honour slope.overall_angle_deg — the optimiser and
    the design then agree on the slope. `cell` is the design grid spacing:
    it must be finer than the berm for benches to show.

    `detail` adds bench polygons, azimuth sectors and a ramp on top of
    this geometry. It is off by default and inherits the bench height and
    face angle from here, so the two never disagree about the wall.
    """
    enabled: bool = True
    bench_height: float = 10.0
    bench_face_angle_deg: float = 65.0
    berm_width: float | None = None
    cell: float = 2.5
    detail: DesignDetailConfig = field(default_factory=DesignDetailConfig)

    def __post_init__(self) -> None:
        if isinstance(self.detail, dict):
            self.detail = DesignDetailConfig(**self.detail)


@dataclass
class ShellsConfig:
    """Revenue factors for the nested pit shells (Whittle
    parameterisation, also written RAF — revenue adjustment factor): the
    price is scaled by each factor and the pit re-solved, giving the
    family of shells used for pushback choice and price sensitivity.
    RF 1.0 is the ultimate pit."""
    revenue_factors: list = field(
        default_factory=lambda: [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]
    )


@dataclass
class ScheduleConfig:
    """
    Production scheduling over the shells.

    `ore_capacity` is throughput per period on plant feed; `total_capacity`
    optionally caps all material moved, which is what binds when stripping
    rather than milling is the constraint. `basis` picks whether those
    limits are read as tonnes or cubic metres — alluvial operations are
    normally planned by volume.

    Set either `ore_capacity` (the plant rate is given, mine life follows)
    or `periods` (mine life is given, plant rate follows).
    """
    enabled: bool = False
    ore_capacity: float = 0.0
    # Alternative to ore_capacity: the number of periods the final pit
    # should be mined over. The plant rate then follows from the pit
    # (final pit feed / periods) — the "size the plant for an N-year life"
    # case. When both are set, periods wins.
    periods: int | None = None
    period_years: float = 1.0       # length of one period, for discounting
    total_capacity: float | None = None
    basis: str = "tonnes"          # tonnes | volume
    discount_rate: float = 0.10
    max_periods: int = 100
    include_worst_case: bool = True


@dataclass
class FinalPitConfig:
    """
    How the final pit is chosen from the shells, once they have been
    scheduled and discounted (the pit-by-pit analysis).

    criterion       NPV to maximise: best | worst | average (of best and
                    worst — the usual proxy for a schedule not yet built)
    tolerance       take the smallest shell within this fraction of the
                    maximum; the NPV curve is flat at the top, and the
                    smaller pit carries less capital and price risk
    revenue_factor  fix the final pit to one shell instead
    """
    criterion: str = "average"
    tolerance: float = 0.01
    revenue_factor: float | None = None


@dataclass
class PushbackConfig:
    """
    How the final pit is split into mining stages.

    Pushbacks are stages, not periods: one pushback is usually mined over
    one to two years and consecutive pushbacks overlap in time. Setting the
    duration to one period gives one pushback per period if that is wanted.

    shells  a few of the nested shells become pushback boundaries, chosen
            for the best specified-case NPV among the splits that are
            practical: every pushback at least `min_tonnes` of material
            (default: one period of plant feed) and no more than
            `max_narrow` of its area narrower than `min_width`. Mined in
            order with a lag of `bench_lag_m` between pushbacks.
    strips  panels `strip_width` wide advancing along the deposit with a
            face sloping back at the wall angle — the practice for shallow
            elongated deposits (mineral sands, alluvials). `strip_axis`
            auto takes the long axis; `strip_direction` auto keeps the
            direction with the higher NPV. The strips are the working
            panels; consecutive strips are grouped into the pushbacks, cut
            where each pushback carries an equal share of the plant feed.
    """
    method: str = "shells"          # shells | strips
    # How many pushbacks — three ways, first one set wins:
    #   count           fixed number (manual)
    #   duration_years  fixed duration per pushback (manual); count = life / duration
    #   "auto"          duration from practice: target_duration_years
    #                   (1-2 years is normal), lengthened if the pit is too
    #                   deep to sink through in that time at
    #                   max_vertical_advance_m per year
    count: int | None = None
    duration_years: object = "auto"
    target_duration_years: float = 1.5
    max_vertical_advance_m: float = 80.0
    max_pushbacks: int = 6
    min_tonnes: float | None = None
    min_width: float = 50.0
    max_narrow: float = 0.30
    bench_lag_m: float = 10.0
    strip_width: float = 50.0
    strip_axis: str = "auto"        # auto | x | y
    strip_direction: str = "auto"   # auto | forward | reverse


@dataclass
class SensitivityConfig:
    """Price factors applied to a FIXED pit — distinct from the revenue
    factors, which re-optimise the pit outline at each price."""
    enabled: bool = False
    price_factors: list = field(
        default_factory=lambda: [0.7, 0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2, 1.3]
    )
    per_product: bool = True       # also flex each product on its own


@dataclass
class OutputConfig:
    directory: str = "outputs"
    write_dxf: bool = True
    dxf_cell: float | None = None   # DXF facet size, m; None = the bench face run (max 5 m), never coarser than the design grid
    write_results: bool = True      # results.json + surfaces.npz, read by the UI
    verify: bool = True             # independent geometric checks on every run
    write_plot: bool = True
    write_excel: bool = True
    write_pdf: bool = True
    write_3d: bool = True          # interactive HTML viewer (plotly)
    dxf_surface_all_shells: bool = False
    dxf_surface_periods: bool = True     # end-of-period pit surfaces: the period mine plan
    dxf_surface_pushbacks: bool = True   # end-of-pushback surfaces
    # Detailed design (design.detail): bench, ramp and sector DXF, session JSON, reconciliation CSV/XLSX.
    write_design_detail: bool = True
    design_shell_reference: bool = False  # also draw the optimiser shell outline beside the design, for overlay in CAD


@dataclass
class ProjectConfig:
    name: str
    block_model: BlockModelConfig
    surface: SurfaceConfig
    economics: EconomicsConfig
    slope: SlopeConfig
    design: DesignConfig
    shells: ShellsConfig
    final_pit: FinalPitConfig
    pushbacks: PushbackConfig
    schedule: ScheduleConfig
    sensitivity: SensitivityConfig
    output: OutputConfig
    # Where each parameter came from: {"economics.mining_cost_per_volume":
    # {"source": "dokumen", "ref": "Parameter!C21"}, ...}. source is one of
    # dokumen | asumsi | default; asumsi entries carry a mandatory note.
    provenance: dict = field(default_factory=dict)
    source: str | None = None

    @classmethod
    def from_yaml(cls, path: str) -> ProjectConfig:
        with open(path) as f:
            raw = yaml.safe_load(f)

        base = Path(path).resolve().parent

        def resolve(p: str | None) -> str | None:
            if not p:
                return p
            return str((base / p).resolve()) if not Path(p).is_absolute() else p

        bm = BlockModelConfig(**raw["block_model"])
        bm.path = resolve(bm.path)

        surf = SurfaceConfig(**raw.get("surface", {}))
        surf.path = resolve(surf.path)

        out = OutputConfig(**raw.get("output", {}))
        out.directory = resolve(out.directory)

        cfg = cls(
            name=raw.get("project", {}).get("name", "pit"),
            block_model=bm,
            surface=surf,
            economics=EconomicsConfig(**raw.get("economics", {})),
            slope=SlopeConfig(**raw.get("slope", {})),
            design=DesignConfig(**raw.get("design", {})),
            shells=ShellsConfig(**raw.get("shells", {})),
            final_pit=FinalPitConfig(**raw.get("final_pit", {})),
            pushbacks=PushbackConfig(**raw.get("pushbacks", {})),
            schedule=ScheduleConfig(**raw.get("schedule", {})),
            sensitivity=SensitivityConfig(**raw.get("sensitivity", {})),
            output=out,
            provenance=raw.get("provenance", {}) or {},
            source=str(Path(path).resolve()),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        e = self.economics
        if e.grade_basis not in GRADE_DIVISOR:
            raise ValueError(f"economics.grade_basis must be one of {list(GRADE_DIVISOR)}, got {e.grade_basis!r}")
        if not e.products:
            raise ValueError("economics.products must list at least one product")
        if not 0 < e.mining_recovery <= 1:
            raise ValueError("economics.mining_recovery must be in (0, 1]")
        if not 0 <= e.dilution < 1:
            raise ValueError("economics.dilution must be in [0, 1)")
        if not 0 <= e.royalty_rate < 1:
            raise ValueError("economics.royalty_rate must be in [0, 1)")

        for p in e.products:
            if p.price_unit not in UNITS_PER_TONNE:
                raise ValueError(f"product {p.name}: price_unit must be one of {list(UNITS_PER_TONNE)}")
            if not 0 < p.plant_recovery <= 1:
                raise ValueError(f"product {p.name}: plant_recovery must be in (0, 1]")
            if p.price <= 0:
                raise ValueError(f"product {p.name}: price must be > 0")
            if e.grade_basis in VOLUME_BASES and p.density <= 0:
                raise ValueError(f"product {p.name}: density must be > 0 for a volume-basis grade")

        if not 0 < self.slope.overall_angle_deg < 90:
            raise ValueError("slope.overall_angle_deg must be in (0, 90)")
        if self.slope.max_bench_levels is not None and self.slope.max_bench_levels < 1:
            raise ValueError("slope.max_bench_levels must be >= 1")
        if not self.shells.revenue_factors:
            raise ValueError("shells.revenue_factors must not be empty")
        if any(rf <= 0 for rf in self.shells.revenue_factors):
            raise ValueError("shells.revenue_factors must all be > 0")

        if self.schedule.enabled:
            if self.schedule.ore_capacity <= 0 and not self.schedule.periods:
                raise ValueError("schedule needs ore_capacity > 0 or periods >= 1")
            if self.schedule.periods is not None and self.schedule.periods < 1:
                raise ValueError("schedule.periods must be >= 1")
            if self.schedule.period_years <= 0:
                raise ValueError("schedule.period_years must be > 0")
            if self.schedule.basis not in ("tonnes", "volume"):
                raise ValueError("schedule.basis must be 'tonnes' or 'volume'")
            if not 0 <= self.schedule.discount_rate < 1:
                raise ValueError("schedule.discount_rate must be in [0, 1)")
        d = self.design
        if d.enabled:
            if d.bench_height <= 0 or d.cell <= 0 or not 0 < d.bench_face_angle_deg < 90:
                raise ValueError("design: bench_height and cell must be > 0, bench_face_angle_deg in (0, 90)")
            if d.bench_face_angle_deg < self.slope.overall_angle_deg:
                raise ValueError("design.bench_face_angle_deg cannot be flatter than slope.overall_angle_deg")
            if d.berm_width is not None and d.berm_width < 0:
                raise ValueError("design.berm_width must be >= 0")
            if d.detail.enabled:
                validate_detail(d.detail, d.bench_height)
        if self.final_pit.criterion not in ("best", "worst", "average"):
            raise ValueError("final_pit.criterion must be best, worst or average")
        if not 0 <= self.final_pit.tolerance < 0.5:
            raise ValueError("final_pit.tolerance must be in [0, 0.5)")
        pb = self.pushbacks
        if pb.method not in ("shells", "strips"):
            raise ValueError("pushbacks.method must be 'shells' or 'strips'")
        if pb.count is not None and pb.count < 1:
            raise ValueError("pushbacks.count must be >= 1")
        if pb.duration_years != "auto" and (pb.duration_years is None or float(pb.duration_years) <= 0):
            raise ValueError("pushbacks.duration_years must be 'auto' or a number > 0")
        if pb.target_duration_years <= 0 or pb.max_vertical_advance_m <= 0:
            raise ValueError("pushbacks.target_duration_years and max_vertical_advance_m must be > 0")
        if pb.max_pushbacks < 1 or pb.strip_width <= 0 or pb.min_width < 0 or pb.bench_lag_m < 0:
            raise ValueError("pushbacks: max_pushbacks >= 1, strip_width > 0, min_width and bench_lag_m >= 0")
        if pb.strip_axis not in ("auto", "x", "y") or pb.strip_direction not in ("auto", "forward", "reverse"):
            raise ValueError("pushbacks.strip_axis must be auto|x|y and strip_direction auto|forward|reverse")
        if self.sensitivity.enabled and not self.sensitivity.price_factors:
            raise ValueError("sensitivity.price_factors must not be empty when sensitivity is enabled")
