"""
The haul road and the overall slope angle, against hand calculations.

The pit used throughout is a circular floor of 100 m radius under ten 10 m
benches at 70 degrees with a 6.5 m berm, so every ring is a circle whose
radius can be written down: the road's plan length, its turns round the
pit and the angle of the wall with and without it all follow from a few
lines of arithmetic done independently of the code under test.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from shapely.geometry import Point, Polygon

from pitopt.config import BermConfig, DesignConfig, DesignDetailConfig, ProjectConfig, RampConfig, SectorConfig
from pitopt.core.design_detail.angles import crossings, sector_osa
from pitopt.core.design_detail.builder import floor_width
from pitopt.core.design_detail.parameters import BLOCKED, OK, WARNING, resolve_sectors
from pitopt.core.design_detail.ramp import (
    AZIMUTHS,
    build_ramp,
    default_entry_azimuth,
    footprint,
    ring_table,
    size_ramp,
    wall_tables,
)
from pitopt.core.design_detail.stack import build_bench_stack

H, FACE, BERM, N_BENCHES, FLOOR_R, WIDTH, GRADE = 10.0, 70.0, 6.5, 10, 100.0, 25.0, 9.0
RUN = H / math.tan(math.radians(FACE))


def circle(radius: float, centre=(0.0, 0.0)) -> Polygon:
    return Point(*centre).buffer(radius, quad_segs=64)      # 256 edges: radius error under 1 cm at 100 m


def pit(ramp: RampConfig | None = None, sectors=None, floor=None, benches=N_BENCHES, **detail_kw):
    ramp = ramp or RampConfig(width_m=WIDTH, grade_pct=GRADE)
    design = DesignConfig(bench_height=H, bench_face_angle_deg=FACE, detail=DesignDetailConfig(
        enabled=True, berm=BermConfig(method="manual", width=BERM), ramp=ramp, sectors=sectors or [], **detail_kw))
    resolved, _ = resolve_sectors(design, 40.0)
    stack = build_bench_stack(floor if floor is not None else circle(FLOOR_R), 1000.0, benches, resolved, design.detail)
    return design, stack


def built(**kw):
    design, stack = pit(**kw)
    sizing = size_ramp(design.detail.ramp)
    return stack, sizing, build_ramp(stack, sizing, design.detail.ramp)


# ── sizing: the truck calculator ────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("lanes, truck, expected", [
    (2, 6.5, 3.5 * 6.5),            # the usual two-lane road: 3.5 truck widths
    (1, 6.5, 2.0 * 6.5),            # one lane: one truck plus half a truck of clearance each side
    (3, 6.0, 5.0 * 6.0),
])
def test_ramp_width_is_the_fleet_clearance_rule(lanes, truck, expected):
    sizing = size_ramp(RampConfig(truck_width_m=truck, lanes=lanes))
    assert sizing.width_m == pytest.approx(expected) and sizing.source == "truck"


def test_safety_berm_and_drain_are_added_to_the_running_surface():
    sizing = size_ramp(RampConfig(truck_width_m=6.0, lanes=2, safety_berm_m=2.0, drain_m=1.0))
    assert sizing.width_m == pytest.approx(3.5 * 6.0 + 3.0)


def test_a_road_narrower_than_the_fleet_needs_is_kept_as_given_and_flagged():
    sizing = size_ramp(RampConfig(truck_width_m=7.0, width_m=20.0))
    assert sizing.width_m == 20.0 and sizing.required_width_m == pytest.approx(24.5) and not sizing.width_ok
    assert size_ramp(RampConfig(truck_width_m=7.0, width_m=25.0)).width_ok


# ── reading a ring as radius against bearing ────────────────────────────────────────────────────────────────────
def test_a_circle_reads_as_a_constant_radius_and_an_ellipse_as_its_semi_axes():
    table = ring_table(circle(80.0), (0.0, 0.0))
    assert table.defined and np.allclose(table.radius, 80.0, atol=0.05)
    ellipse = Polygon([(120 * math.cos(t), 50 * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 2000, endpoint=False)])
    table = ring_table(ellipse, (0.0, 0.0))
    assert table.at(90.0) == pytest.approx(120.0, abs=0.1)         # east is the long axis
    assert table.at(0.0) == pytest.approx(50.0, abs=0.1)           # north the short one


def test_a_ring_that_splits_is_reported_as_two_parts():
    two = Point(-100, 0).buffer(20).union(Point(100, 0).buffer(20))
    table = ring_table(two, (0.0, 0.0))
    assert table.parts == 2 and not table.defined


# ── the spiral ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_road_rises_at_exactly_the_requested_grade_on_every_bench():
    _, _, ramp = built()
    assert ramp.complete
    grades = ramp.grade_by_bench()
    assert sorted(grades) == list(range(1, N_BENCHES + 1))
    assert all(g == pytest.approx(GRADE, abs=1e-6) for g in grades.values())


def test_the_road_runs_from_the_floor_to_the_crest_and_never_descends():
    stack, _, ramp = built()
    assert ramp.z[0] == pytest.approx(stack.benches[-1].toe_rl) and ramp.z[-1] == pytest.approx(stack.benches[0].crest_rl)
    assert (np.diff(ramp.z) > 0).all()


def test_the_total_plan_length_is_the_depth_over_the_grade():
    """100 m of climb at 9% is 1111.1 m of road, whatever the pit looks like."""
    stack, _, ramp = built()
    assert ramp.horizontal_length_m == pytest.approx(100.0 / 0.09, rel=1e-6)


def test_the_road_follows_the_wall_at_the_radius_worked_out_by_hand():
    """A flat's inner edge is the crest of the bench below; the centreline is half a road width beyond it.
    The floor node sits at 100 + 12.5, and the node at the top at the top crest ring + 12.5."""
    _, _, ramp = built()
    radius = np.hypot(ramp.x - ramp.centre[0], ramp.y - ramp.centre[1])
    assert radius[0] == pytest.approx(FLOOR_R + WIDTH / 2, abs=0.2)
    top_crest = FLOOR_R + (N_BENCHES - 1) * (RUN + BERM) + RUN
    assert radius[-1] == pytest.approx(top_crest + WIDTH / 2, abs=0.3)
    assert radius[-1] > radius[0]                                  # the road moves outward as it climbs


def test_the_number_of_turns_matches_an_independent_estimate():
    """Each bench is H/grade = 111.1 m of road at a mean radius of its two nodes; the azimuth it sweeps is
    the length over that radius (the outward drift of about 10 m adds well under 1% to the length)."""
    _, _, ramp = built()
    per_bench = H / (GRADE / 100.0)

    def flat_radius(k: int) -> float:
        """Ring of the k-th flat above the floor: the floor itself, then the crest of each bench in turn."""
        return FLOOR_R + (0.0 if k == 0 else (k - 1) * (RUN + BERM) + RUN) + WIDTH / 2

    expected = sum(math.degrees(per_bench / ((flat_radius(k - 1) + flat_radius(k)) / 2)) for k in range(1, N_BENCHES + 1))
    assert ramp.turns == pytest.approx(expected / 360.0, rel=0.01)


def test_direction_sets_which_way_the_bearing_runs():
    _, _, cw = built(ramp=RampConfig(width_m=WIDTH, grade_pct=GRADE, direction="clockwise"))
    _, _, ccw = built(ramp=RampConfig(width_m=WIDTH, grade_pct=GRADE, direction="anticlockwise"))
    assert cw.azimuth[-1] > cw.azimuth[0] and ccw.azimuth[-1] < ccw.azimuth[0]
    assert cw.turns == pytest.approx(ccw.turns, rel=1e-6)


def test_the_road_starts_at_the_requested_bearing():
    _, _, ramp = built(ramp=RampConfig(width_m=WIDTH, grade_pct=GRADE, entry_azimuth_deg=225.0))
    assert not ramp.entry_defaulted and ramp.azimuth[0] == pytest.approx(225.0)
    start = math.degrees(math.atan2(ramp.x[0] - ramp.centre[0], ramp.y[0] - ramp.centre[1])) % 360.0
    assert start == pytest.approx(225.0, abs=0.01)


def test_with_no_entry_given_the_road_starts_where_the_wall_is_widest_and_says_so():
    ellipse = Polygon([(150 * math.cos(t), 60 * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 1500, endpoint=False)])
    stack, _, ramp = built(floor=ellipse, ramp=RampConfig(width_m=WIDTH, grade_pct=GRADE))
    _, top, floor = wall_tables(stack)
    assert ramp.entry_defaulted
    widths = top.radius - floor.radius
    assert widths[np.argmin(np.abs(AZIMUTHS - ramp.entry_azimuth_deg))] == pytest.approx(np.nanmax(widths), abs=1e-9)
    assert default_entry_azimuth(top, floor) == ramp.entry_azimuth_deg


def test_each_bench_gets_a_strip_as_wide_as_the_road():
    _, _, ramp = built()
    assert sorted(ramp.strips) == list(range(1, N_BENCHES + 1))
    assert footprint(ramp).area > 0
    for strip in ramp.strips.values():
        assert strip.is_valid and strip.area > 0


# ── when the road cannot be built ───────────────────────────────────────────────────────────────────────────────
def test_a_wall_that_splits_breaks_the_road_and_names_the_bench():
    """Two floors joined by a neck: the lowest benches are two separate rings, so no road can run along them."""
    dumbbell = Point(-70, 0).buffer(30, quad_segs=64).union(Point(70, 0).buffer(30, quad_segs=64)).union(
        Polygon([(-70, -4), (70, -4), (70, 4), (-70, 4)]))
    assert dumbbell.geom_type == "Polygon"
    shrinking = DesignConfig(bench_height=H, bench_face_angle_deg=FACE, detail=DesignDetailConfig(
        enabled=True, anchor="crest", berm=BermConfig(method="manual", width=BERM), ramp=RampConfig(width_m=WIDTH)))
    resolved, _ = resolve_sectors(shrinking, 40.0)
    stack = build_bench_stack(dumbbell.buffer(45), 1100.0, 6, resolved, shrinking.detail)     # neck 49 m half-width, lobes 75 m
    ramp = build_ramp(stack, size_ramp(shrinking.detail.ramp), shrinking.detail.ramp)
    assert not ramp.complete
    assert "splits" in ramp.broken.reason or "does not surround" in ramp.broken.reason
    assert 1 <= ramp.broken.bench <= len(stack.benches)


def test_a_grade_too_shallow_to_absorb_the_outward_drift_breaks_the_road():
    """A bench that steps out 60 m cannot be climbed in the 11 m of road a 100% grade gives it."""
    cfg = RampConfig(width_m=WIDTH, grade_pct=9.0)
    design, stack = pit(ramp=cfg, benches=4)
    steep = build_ramp(stack, size_ramp(RampConfig(width_m=WIDTH, grade_pct=99.0)), cfg)
    assert not steep.complete and "shifts outward" in steep.broken.reason


# ── the switchback ──────────────────────────────────────────────────────────────────────────────────────────────
def test_a_switchback_reverses_the_stated_number_of_times_at_the_same_grade():
    cfg = RampConfig(width_m=WIDTH, grade_pct=GRADE, pattern="switchback", switchbacks=3, hairpin_radius_m=15.0)
    _, _, ramp = built(ramp=cfg)
    assert ramp.complete and len(ramp.reversals) == 3
    assert all(g == pytest.approx(GRADE, abs=1e-6) for g in ramp.grade_by_bench().values())
    heading = np.sign(np.diff(ramp.azimuth))
    turns_of_direction = int((np.diff(heading[heading != 0]) != 0).sum())
    assert turns_of_direction == 3
    assert any("hairpin" in w for w in ramp.warnings)             # the platform is assumed, and says so


def test_a_switchback_winds_far_less_than_a_spiral_over_the_same_climb():
    _, _, spiral = built()
    _, _, zigzag = built(ramp=RampConfig(width_m=WIDTH, grade_pct=GRADE, pattern="switchback", switchbacks=3,
                                         hairpin_radius_m=15.0))
    net = abs(zigzag.azimuth[-1] - zigzag.azimuth[0])
    assert net < abs(spiral.azimuth[-1] - spiral.azimuth[0])
    assert zigzag.horizontal_length_m == pytest.approx(spiral.horizontal_length_m, rel=1e-6)   # same climb, same road


# ── the overall slope angle ─────────────────────────────────────────────────────────────────────────────────────
def test_the_overall_angle_without_the_road_is_the_depth_over_the_wall_width():
    """100 m of depth over a wall 9 * (3.640 + 6.5) + 3.640 = 94.9 m wide: atan(100 / 94.9) = 46.5 degrees."""
    design, stack = pit()
    _, top, floor = wall_tables(stack)
    (osa,) = sector_osa(stack, None, top, floor, design.detail.limits)
    wall = N_BENCHES * RUN + (N_BENCHES - 1) * BERM
    assert wall == pytest.approx(94.9, abs=0.01)
    assert osa.osa_no_ramp_deg == pytest.approx(math.degrees(math.atan2(100.0, wall)), abs=0.05)
    assert osa.osa_no_ramp_deg == pytest.approx(46.5, abs=0.05)
    assert osa.analytic_gap_deg == pytest.approx(0.0, abs=0.05)         # measured and closed form agree on a regular pit


def test_the_road_flattens_the_wall_by_crossings_times_its_excess_over_the_berm():
    """Each crossing adds (25 - 6.5) = 18.5 m of width. With one crossing: atan(100 / 113.4) = 41.4 degrees."""
    design, stack = pit()
    _, top, floor = wall_tables(stack)
    ramp = build_ramp(stack, size_ramp(design.detail.ramp), design.detail.ramp, (wall_tables(stack)))
    (osa,) = sector_osa(stack, ramp, top, floor, design.detail.limits)
    wall = N_BENCHES * RUN + (N_BENCHES - 1) * BERM
    assert osa.osa_deg < osa.osa_no_ramp_deg                              # the road always flattens
    at_worst = math.degrees(math.atan2(100.0, wall + (WIDTH - BERM) * 1))
    assert at_worst == pytest.approx(41.4, abs=0.1)
    # the worst bearing is one crossed the fewest times, so it is the one road-free of a second pass
    assert osa.osa_deg >= math.degrees(math.atan2(100.0, wall + (WIDTH - BERM) * osa.crossings_max)) - 0.05


def test_the_mean_number_of_crossings_over_all_bearings_is_the_turns_of_the_road():
    """A bearing is crossed once per turn: averaged round the whole pit, that is exactly the turns."""
    _, _, ramp = built()
    count = crossings(ramp, AZIMUTHS)
    assert count.mean() == pytest.approx(ramp.turns, rel=2e-3)
    assert set(np.unique(count)) <= {math.floor(ramp.turns), math.ceil(ramp.turns)}


def test_the_sector_status_follows_its_limit_and_the_worst_bearing():
    sectors = [SectorConfig(name="U", azimuth_from=270, azimuth_to=90, osa_max_deg=50.0),
               SectorConfig(name="S", azimuth_from=90, azimuth_to=270, osa_max_deg=40.0)]
    design, stack = pit(sectors=sectors)
    cfg = design.detail.ramp
    _, top, floor = wall_tables(stack)
    ramp = build_ramp(stack, size_ramp(cfg), cfg, (wall_tables(stack)))
    north, south = sector_osa(stack, ramp, top, floor, design.detail.limits)
    assert north.status in (OK, WARNING) and north.osa_deg <= 50.0
    assert south.status == BLOCKED and south.osa_deg > 40.0            # 41+ degrees against a 40 degree limit
    assert south.margin_deg < 0 < north.margin_deg


# ── the floor ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_floor_width_is_the_diameter_of_the_largest_circle_that_fits():
    _, stack = pit()
    assert floor_width(stack) == pytest.approx(2 * FLOOR_R, rel=1e-3)
    _, narrow = pit(floor=Polygon([(-150, -15), (150, -15), (150, 15), (-150, 15)]))
    assert floor_width(narrow) == pytest.approx(30.0, abs=0.1)         # a long slot is only as wide as it is wide


# ── configuration ───────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ramp, message", [
    (RampConfig(width_m=25.0, grade_pct=12.0), "outside"),
    (RampConfig(width_m=25.0, direction="up"), "direction"),
    (RampConfig(width_m=25.0, pattern="switchback", hairpin_radius_m=15.0), "switchbacks"),
    (RampConfig(width_m=25.0, pattern="switchback", switchbacks=2), "hairpin_radius_m"),
    (RampConfig(), "width_m, or truck_width_m"),
])
def test_an_unbuildable_ramp_configuration_is_refused_with_the_reason(ramp, message):
    cfg = ProjectConfig.from_yaml("projects/example_tin/project.yaml")
    cfg.design.detail = DesignDetailConfig(enabled=True, ramp=ramp)
    with pytest.raises(ValueError, match=message):
        cfg.validate()


# ── on a real shell ─────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("anchor", ["floor", "crest"])
def test_a_road_on_the_bundled_examples_real_shell_is_complete_and_at_grade(anchor):
    from pathlib import Path

    import pandas as pd

    from pitopt.core.design_detail.builder import build_design

    path = Path(__file__).resolve().parents[1] / ".pytest_runs/example_tin/example_tin_blocks.csv"
    if not path.exists():
        pytest.skip("no generated example run")
    blocks = pd.read_csv(path)
    in_pit = blocks["in_pit"].to_numpy().astype(bool)

    cfg = ProjectConfig.from_yaml("projects/example_tin/project.yaml")
    cfg.design.detail = DesignDetailConfig(enabled=True, anchor=anchor, berm=BermConfig(method="slope"),
                                           ramp=RampConfig(width_m=15.0, grade_pct=9.0))
    design = build_design(blocks, in_pit, cfg)
    ramp, stack = design.ramp, design.stack

    depth = stack.benches[0].crest_rl - stack.benches[-1].toe_rl
    assert ramp.complete and ramp.turns > 0
    assert ramp.z[0] == pytest.approx(stack.benches[-1].toe_rl) and ramp.z[-1] == pytest.approx(stack.benches[0].crest_rl)
    assert ramp.horizontal_length_m == pytest.approx(depth / 0.09, rel=1e-6)
    assert all(g == pytest.approx(9.0, abs=1e-6) for g in ramp.grade_by_bench().values())
    assert sorted(ramp.strips) == list(range(1, len(stack.benches) + 1))
    for sector in design.osa:
        assert sector.osa_deg < sector.osa_no_ramp_deg                    # the road flattens the wall
        assert sector.crossings_max >= 1
    assert design.floor_width_m > 0
