"""
The detailed design's geometry against answers worked out by hand.

A pit design that only agrees with itself proves nothing, so each check
here compares the engine with something computed another way: a closed
formula, the Steiner formula for the area of an offset convex shape, or the
existing raster design. Circles and ellipses are used because their offset
is known exactly.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from shapely import affinity
from shapely.geometry import Point, Polygon

from pitopt.config import BermConfig, DesignConfig, DesignDetailConfig, ProjectConfig, RampConfig, SectorConfig
from pitopt.core.design import bench_geometry
from pitopt.core.design_detail.footprint import level_footprint, smooth_outline
from pitopt.core.design_detail.offset import azimuth_profile, offset
from pitopt.core.design_detail.parameters import (
    BLOCKED,
    OK,
    WARNING,
    angle_status,
    berm_width,
    inter_ramp_angle_deg,
    resolve_sectors,
)
from pitopt.core.design_detail.stack import bench_count, build_bench_stack

ROOT_PROJECT = "projects/example_tin/project.yaml"


def circle(radius: float) -> Polygon:
    return Point(0, 0).buffer(radius, quad_segs=256)


def detail(**kw) -> DesignConfig:
    berm = kw.pop("berm", BermConfig())
    sectors = kw.pop("sectors", [])
    return DesignConfig(bench_height=kw.pop("H", 10.0), bench_face_angle_deg=kw.pop("face", 70.0),
                        detail=DesignDetailConfig(enabled=True, berm=berm, sectors=sectors, **kw))


# ── berm and angle formulas, by hand ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("height, expected", [(10.0, 6.5), (15.0, 7.5), (30.0, 10.5)])
def test_ritchie_berm_is_point_two_h_plus_four_and_a_half(height, expected):
    width, note = berm_width(BermConfig(method="ritchie"), height, 70.0, 1, 40.0)
    assert width == pytest.approx(expected)
    assert note is None


def test_ritchie_beyond_its_fitted_range_is_flagged_not_silent():
    width, note = berm_width(BermConfig(method="ritchie"), 40.0, 70.0, 1, 40.0)
    assert width == pytest.approx(12.5)
    assert note and "extrapolation" in note


def test_manual_and_ryan_use_what_they_are_given():
    assert berm_width(BermConfig(method="manual", width=9.0), 10.0, 70.0, 1, 40.0)[0] == 9.0
    assert berm_width(BermConfig(method="ryan", ryan_a=0.3, ryan_b=3.0), 10.0, 70.0, 1, 40.0)[0] == pytest.approx(6.0)


def test_inter_ramp_angle_for_15m_benches_at_70_degrees():
    # run = 15 / tan 70 = 5.4595 m; berm 7.5 m; IRA = atan(15 / (5.4595 + 7.5)) = 49.17 deg
    assert inter_ramp_angle_deg(15.0, 70.0, 7.5, 1) == pytest.approx(49.17, abs=0.01)
    # two benches between berms: atan(30 / (10.919 + 7.5)) = atan(1.6287) = 58.45 deg
    assert inter_ramp_angle_deg(15.0, 70.0, 7.5, 2) == pytest.approx(58.45, abs=0.01)


def test_ira_is_always_flatter_than_the_face_and_falls_as_the_berm_widens():
    face = 65.0
    angles = [inter_ramp_angle_deg(10.0, face, w, 1) for w in (0.0, 3.0, 6.0, 12.0)]
    assert angles[0] == pytest.approx(face)             # no berm: the wall is the face
    assert all(a > b for a, b in zip(angles, angles[1:]))


def test_slope_berm_reproduces_the_existing_design_engine():
    """Cross-check against the raster design, which sizes its berm the same way."""
    legacy = bench_geometry(overall_angle_deg=40.0, bench_height=10.0, face_angle_deg=65.0, berm_width=None)
    width, _ = berm_width(BermConfig(method="slope"), 10.0, 65.0, 1, 40.0)
    assert width == pytest.approx(legacy.berm_width)
    assert inter_ramp_angle_deg(10.0, 65.0, width, 1) == pytest.approx(40.0)


def test_slope_berm_refuses_a_face_flatter_than_the_overall_angle():
    with pytest.raises(ValueError, match="flatter"):
        berm_width(BermConfig(method="slope"), 10.0, 35.0, 1, 40.0)


def test_status_against_a_limit_is_ok_warning_or_blocked():
    assert angle_status(40.0, 41.0, 0.5) == OK
    assert angle_status(40.6, 41.0, 0.5) == WARNING          # 0.4 deg of margin, under the 0.5 threshold
    assert angle_status(41.0, 41.0, 0.5) == WARNING          # exactly at the limit still passes, with no margin
    assert angle_status(42.1, 41.0, 0.5) == BLOCKED          # the east-sector example from the design brief
    assert angle_status(99.0, None, 0.5) == OK               # no limit, nothing to fail


def test_bench_offsets_follow_the_prd_formula():
    d = detail(H=10.0, face=70.0, berm=BermConfig(method="manual", width=6.0), berm_every_n_benches=2)
    (s,), _ = resolve_sectors(d, 40.0)
    run = 10.0 / math.tan(math.radians(70.0))
    for k in range(7):
        assert s.crest_offset(k) == pytest.approx(k * run + (k // 2) * 6.0)
        assert s.toe_offset(k) == pytest.approx(k * run + (k // 2) * 6.0 + run)


# ── the offset itself ───────────────────────────────────────────────────────────────────────────────────────────
def test_a_uniform_distance_matches_the_steiner_area_of_a_convex_shape():
    """Growing a convex shape by d adds  perimeter * d + pi d^2  exactly."""
    shape = affinity.scale(circle(100.0), 1.0, 0.5)                 # an ellipse 200 x 100
    d = 12.0
    expected = shape.area + shape.length * d + math.pi * d * d
    assert offset(shape, d, grow=True).area == pytest.approx(expected, rel=1e-3)


def test_a_bearing_dependent_offset_reduces_to_the_buffer_when_the_distance_is_constant():
    shape = affinity.scale(circle(100.0), 1.0, 0.5)
    swept = offset(shape, lambda bearing: np.full_like(bearing, 12.0), grow=True)
    assert swept.area == pytest.approx(shape.buffer(12.0).area, rel=2e-3)
    assert swept.is_valid


def test_shrinking_a_circle_gives_the_smaller_circle():
    inner = offset(circle(100.0), 30.0, grow=False)
    assert inner.area == pytest.approx(math.pi * 70.0**2, rel=1e-3)
    swept = offset(circle(100.0), lambda b: np.full_like(b, 30.0), grow=False)
    assert swept.area == pytest.approx(math.pi * 70.0**2, rel=3e-3)


def test_a_shrinking_pit_that_closes_returns_nothing_rather_than_a_sliver():
    assert offset(circle(20.0), 25.0, grow=False).is_empty


def test_a_dumbbell_splits_in_two_when_shrunk():
    left, right = Point(-60, 0).buffer(40, quad_segs=64), Point(60, 0).buffer(40, quad_segs=64)
    neck = Polygon([(-60, -6), (60, -6), (60, 6), (-60, 6)])
    dumbbell = left.union(right).union(neck)
    assert dumbbell.geom_type == "Polygon"
    for distance in (10.0, lambda b: np.full_like(b, 10.0)):
        parts = offset(dumbbell, distance, grow=False)
        assert parts.geom_type == "MultiPolygon" and len(parts.geoms) == 2
        assert parts.is_valid


def test_an_island_shrinks_and_disappears_as_the_pit_grows_around_it():
    ring = circle(100.0).difference(circle(20.0))
    grown = offset(ring, 30.0, grow=True)
    assert grown.geom_type == "Polygon" and not list(grown.interiors)       # the hole closed
    assert grown.is_valid
    partly = offset(ring, 10.0, grow=True)
    assert len(list(partly.interiors)) == 1
    assert Polygon(partly.interiors[0]).area == pytest.approx(math.pi * 10.0**2, rel=2e-2)


def test_a_concave_corner_offset_is_valid_and_not_self_intersecting():
    l_shape = Polygon([(0, 0), (100, 0), (100, 40), (40, 40), (40, 100), (0, 100)])
    for distance in (15.0, lambda b: np.full_like(b, 15.0)):
        for grow in (True, False):
            out = offset(l_shape, distance, grow=grow)
            assert out.is_valid and not out.is_empty


# ── azimuth blending ────────────────────────────────────────────────────────────────────────────────────────────
def four_sectors():
    d = detail(sectors=[
        SectorConfig(name="U", azimuth_from=315, azimuth_to=45),
        SectorConfig(name="T", azimuth_from=45, azimuth_to=135),
        SectorConfig(name="S", azimuth_from=135, azimuth_to=225),
        SectorConfig(name="B", azimuth_from=225, azimuth_to=315),
    ])
    return resolve_sectors(d, 40.0)[0]


def test_sector_values_hold_across_the_arc_and_blend_linearly_over_the_boundary():
    profile = azimuth_profile(four_sectors(), [20.0, 30.0, 40.0, 50.0], blend_deg=12.0)
    at = lambda a: float(profile(np.array([a]))[0])               # noqa: E731
    assert at(0) == pytest.approx(20.0)             # centre of the north sector, which wraps through 0
    assert at(33) == pytest.approx(20.0)            # 12 deg before the 45 boundary: still pure north
    assert at(45) == pytest.approx(25.0)            # on the boundary: halfway between north and east
    assert at(51) == pytest.approx(27.5)
    assert at(57) == pytest.approx(30.0)            # 12 deg past: pure east
    assert at(90) == pytest.approx(30.0)
    assert at(315) == pytest.approx(35.0)           # the west/north boundary, across the wrap
    assert at(359.9) == pytest.approx(at(0.1), abs=0.5)


def test_with_no_blend_the_value_steps_at_the_boundary():
    profile = azimuth_profile(four_sectors(), [20.0, 30.0, 40.0, 50.0], blend_deg=0.0)
    assert float(profile(np.array([44.0]))[0]) == pytest.approx(20.0)
    assert float(profile(np.array([46.0]))[0]) == pytest.approx(30.0)


# ── the stack ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_floor_anchor_circle_rings_match_the_hand_computed_radii():
    """R = 100 m floor, 10 m benches at 70 deg, manual berm 6.5 m, berm every bench.
    run = 10 / tan 70 = 3.6397 m, so the toe of bench b is b * (3.6397 + 6.5) out from the floor and its crest
    a run further; the crest of bench 3 is 2 * 10.1397 + 3.6397 = 23.919 m out."""
    d = detail(H=10.0, face=70.0, berm=BermConfig(method="manual", width=6.5))
    sectors, _ = resolve_sectors(d, 40.0)
    stack = build_bench_stack(circle(100.0), 1000.0, 5, sectors, d.detail)
    run = 10.0 / math.tan(math.radians(70.0))
    assert [b.index for b in stack.benches] == [1, 2, 3, 4, 5]
    assert stack.benches[-1].toe_rl == 1000.0 and stack.benches[0].crest_rl == 1050.0
    for bench in stack.benches:
        b = 5 - bench.index                                    # 0 = the bench on the floor
        toe_r, crest_r = 100.0 + b * (run + 6.5), 100.0 + b * (run + 6.5) + run
        assert bench.toe.area == pytest.approx(math.pi * toe_r**2, rel=2e-3)
        assert bench.crest.area == pytest.approx(math.pi * crest_r**2, rel=2e-3)
    assert stack.benches[2].crest_offsets["Semua"] == pytest.approx(23.919, abs=1e-3)


def test_crest_anchor_circle_steps_inward_by_the_same_offsets():
    d = detail(H=10.0, face=70.0, berm=BermConfig(method="manual", width=6.5), anchor="crest")
    sectors, _ = resolve_sectors(d, 40.0)
    stack = build_bench_stack(circle(200.0), 1100.0, 4, sectors, d.detail)
    run = 10.0 / math.tan(math.radians(70.0))
    assert stack.benches[0].crest_rl == 1100.0 and stack.benches[-1].toe_rl == 1060.0
    for bench in stack.benches:
        k = bench.index - 1
        crest_r = 200.0 - k * (run + 6.5)
        assert bench.crest.area == pytest.approx(math.pi * crest_r**2, rel=2e-3)
        assert bench.toe.area == pytest.approx(math.pi * (crest_r - run) ** 2, rel=2e-3)


def test_the_two_anchors_agree_on_the_wall_between_the_same_two_outlines():
    """Build up from a floor, then down from the crest it produced: the same wall comes back."""
    kw = dict(H=10.0, face=70.0, berm=BermConfig(method="manual", width=6.5))
    up = detail(**kw)
    down = detail(anchor="crest", **kw)
    floor = circle(60.0)
    built = build_bench_stack(floor, 1000.0, 4, resolve_sectors(up, 40.0)[0], up.detail)
    crest_ring = built.benches[0].crest
    back = build_bench_stack(crest_ring, 1040.0, 4, resolve_sectors(down, 40.0)[0], down.detail)
    # the crest ring is a crest, and the top bench's toe sits a face run in: the first bench's toes must agree
    assert back.benches[0].toe.area == pytest.approx(built.benches[0].toe.area, rel=5e-3)


def test_a_wall_that_closes_above_the_floor_stops_and_says_so():
    d = detail(H=10.0, face=70.0, berm=BermConfig(method="manual", width=6.5), anchor="crest")
    sectors, _ = resolve_sectors(d, 40.0)
    stack = build_bench_stack(circle(30.0), 1100.0, 10, sectors, d.detail)
    assert stack.collapsed_at is not None and len(stack.benches) < 10
    assert any("closes" in w for w in stack.warnings)


def test_sectors_with_different_face_angles_reach_different_distances():
    d = detail(H=10.0, face=70.0, berm=BermConfig(method="manual", width=6.0), sectors=[
        SectorConfig(name="N", azimuth_from=270, azimuth_to=90, face_angle_deg=80.0),
        SectorConfig(name="S", azimuth_from=90, azimuth_to=270, face_angle_deg=55.0),
    ])
    sectors, _ = resolve_sectors(d, 40.0)
    stack = build_bench_stack(circle(100.0), 1000.0, 3, sectors, d.detail)
    crest = stack.benches[0].crest                       # top bench: three benches of climb
    north = max(y for _, y in crest.exterior.coords)     # bearing 0
    south = -min(y for _, y in crest.exterior.coords)    # bearing 180
    steep, shallow = sectors[0], sectors[1]
    assert north == pytest.approx(100.0 + steep.toe_offset(2), abs=0.5)
    assert south == pytest.approx(100.0 + shallow.toe_offset(2), abs=0.5)
    assert south > north                                  # the flatter face needs more room
    assert stack.benches[0].crest.is_valid


def test_bench_count_counts_a_partial_top_bench():
    assert bench_count(1180.0, 1000.0, 12.0) == 15
    assert bench_count(1005.0, 1000.0, 10.0) == 1
    with pytest.raises(ValueError, match="not above"):
        bench_count(1000.0, 1000.0, 10.0)


# ── footprint and smoothing ─────────────────────────────────────────────────────────────────────────────────────
def grid_blocks(nx: int, ny: int, size: float = 10.0, z: float = 1000.0) -> pd.DataFrame:
    xs, ys = np.meshgrid(np.arange(nx) * size + size / 2, np.arange(ny) * size + size / 2, indexing="ij")
    n = nx * ny
    return pd.DataFrame({"x": xs.ravel(), "y": ys.ravel(), "z": np.full(n, z), "dx": size, "dy": size, "dz": 5.0})


def test_level_footprint_area_is_the_block_count_times_the_block_area():
    blocks = grid_blocks(6, 4)
    mask = np.ones(len(blocks), dtype=bool)
    assert level_footprint(blocks, mask, 1000.0).area == pytest.approx(24 * 100.0)
    assert level_footprint(blocks, mask, 1005.0).is_empty
    mask[:] = False
    assert level_footprint(blocks, mask, 1000.0).is_empty


def test_smoothing_removes_the_block_staircase_and_reports_what_it_did():
    from pitopt.config import SmoothingConfig

    r = 80.0
    x, y = np.meshgrid(np.arange(-r, r, 10.0) + 5, np.arange(-r, r, 10.0) + 5, indexing="ij")
    inside = x**2 + y**2 <= r * r
    blocks = pd.DataFrame({"x": x[inside], "y": y[inside], "z": 1000.0, "dx": 10.0, "dy": 10.0, "dz": 5.0})
    outline = level_footprint(blocks, np.ones(len(blocks), dtype=bool), 1000.0)
    smooth, record = smooth_outline(outline, SmoothingConfig(), block_diagonal_m=math.hypot(10, 10))
    assert len(smooth.exterior.coords) < len(outline.exterior.coords) / 3          # far fewer vertices
    assert smooth.hausdorff_distance(outline) <= record.tolerance_m + 1e-6         # nothing moved past the band
    assert record.applied and record.area_after_m2 == pytest.approx(smooth.area)
    assert record.area_change_m2 == pytest.approx(smooth.area - outline.area)
    assert smooth.is_valid


def test_smoothing_can_be_switched_off_and_then_changes_nothing():
    from pitopt.config import SmoothingConfig

    outline = Polygon([(0, 0), (10, 0), (10, 10), (20, 10), (20, 20), (0, 20)])
    same, record = smooth_outline(outline, SmoothingConfig(enabled=False), 14.0)
    assert same.equals(outline) and not record.applied and record.area_change_m2 == 0.0


def test_fragments_below_the_minimum_area_are_dropped_and_counted():
    from pitopt.config import SmoothingConfig

    parts = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]).union(Polygon([(300, 0), (304, 0), (304, 4), (300, 4)]))
    out, record = smooth_outline(parts, SmoothingConfig(tolerance_m=0.0, min_area_m2=100.0), 14.0)
    assert out.geom_type == "Polygon" and record.dropped_parts == 1 and record.dropped_area_m2 == pytest.approx(16.0)


# ── configuration ───────────────────────────────────────────────────────────────────────────────────────────────
def _config(**detail_kw):
    cfg = ProjectConfig.from_yaml(ROOT_PROJECT)
    detail_kw.setdefault("ramp", RampConfig(width_m=25.0))         # the ramp needs a width or a truck; not the subject here
    cfg.design.detail = DesignDetailConfig(enabled=True, **detail_kw)
    return cfg


@pytest.mark.parametrize("kw, message", [
    (dict(anchor="side"), "anchor"),
    (dict(source="pushback"), "not implemented"),
    (dict(berm=BermConfig(method="ryan")), "geotechnical report"),
    (dict(berm=BermConfig(method="manual")), "needs width"),
    (dict(sectors=[SectorConfig(name="a", azimuth_from=0, azimuth_to=90)]), "not covered"),
    (dict(sectors=[SectorConfig(name="a", azimuth_from=0, azimuth_to=200), SectorConfig(name="b", azimuth_from=180, azimuth_to=360)]),
     "overlaps"),
    (dict(sectors=[SectorConfig(name="a", azimuth_from=0, azimuth_to=180, bench_height=7.0),
                   SectorConfig(name="b", azimuth_from=180, azimuth_to=360)]), "cannot have its own height"),
    (dict(sectors=[SectorConfig(name="a", azimuth_from=0, azimuth_to=20), SectorConfig(name="b", azimuth_from=20, azimuth_to=360)]),
     "blend zones"),
])
def test_invalid_design_detail_configuration_is_refused_with_the_reason(kw, message):
    with pytest.raises(ValueError, match=message):
        _config(**kw).validate()


def test_a_valid_four_sector_configuration_passes():
    _config(sectors=[
        SectorConfig(name="U", azimuth_from=315, azimuth_to=45),
        SectorConfig(name="T", azimuth_from=45, azimuth_to=135),
        SectorConfig(name="S", azimuth_from=135, azimuth_to=225),
        SectorConfig(name="B", azimuth_from=225, azimuth_to=315),
    ]).validate()


def test_a_project_with_detail_off_is_not_validated_against_it():
    cfg = ProjectConfig.from_yaml(ROOT_PROJECT)
    cfg.design.detail = DesignDetailConfig(enabled=False, anchor="nonsense")
    cfg.validate()


# ── on a real shell ─────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def example_shell():
    """The bundled example's optimiser shell, as the pipeline wrote it."""
    from pathlib import Path

    runs = sorted(Path(__file__).resolve().parents[1].glob(".pytest_runs/example_tin/example_tin_blocks.csv"))
    if not runs:
        pytest.skip("no generated example run")
    blocks = pd.read_csv(runs[0])
    return blocks, blocks["in_pit"].to_numpy().astype(bool)


@pytest.mark.parametrize("anchor", ["floor", "crest"])
def test_design_on_a_real_shell_is_valid_nested_and_honours_its_anchor(example_shell, anchor):
    from pitopt.core.design_detail.builder import build_design

    blocks, in_pit = example_shell
    cfg = ProjectConfig.from_yaml(ROOT_PROJECT)
    cfg.design.detail = DesignDetailConfig(enabled=True, anchor=anchor, ramp=RampConfig(width_m=15.0),
                                           berm=BermConfig(method="slope"))
    design = build_design(blocks, in_pit, cfg)
    benches = design.stack.benches

    assert benches and all(b.crest.is_valid and b.toe.is_valid and not b.crest.is_empty for b in benches)
    assert design.stack.collapsed_at is None or anchor == "crest"
    for above, below in zip(benches, benches[1:]):
        # a wall never overhangs, whichever way it was built: the bench below sits inside the bench above,
        # separated by its berm
        assert above.toe.buffer(1e-6).contains(below.crest)
    for bench in benches:
        assert bench.crest.buffer(1e-6).contains(bench.toe)     # the crest ring encloses its toe ring

    if anchor == "floor":            # the floor of the design holds the floor of the optimiser shell
        lowest = benches[-1]
        floor = smooth_outline(level_footprint(blocks, in_pit, blocks.loc[in_pit, "z"].min()),
                               cfg.design.detail.smoothing, math.hypot(blocks["dx"].iloc[0], blocks["dy"].iloc[0]))[0]
        assert lowest.toe.buffer(1e-6).contains(floor)
        assert benches[0].crest.area > lowest.toe.area          # the pit widens upward

    assert design.smoothing.applied and design.smoothing.area_before_m2 > 0
    assert {a.status for a in design.angles} <= {OK, WARNING, BLOCKED}


def test_the_slope_criterion_makes_the_ira_equal_the_optimiser_angle(example_shell):
    from pitopt.core.design_detail.builder import build_design

    blocks, in_pit = example_shell
    cfg = ProjectConfig.from_yaml(ROOT_PROJECT)
    cfg.design.detail = DesignDetailConfig(enabled=True, berm=BermConfig(method="slope"), ramp=RampConfig(width_m=15.0))
    design = build_design(blocks, in_pit, cfg)
    assert design.angles[0].ira_deg == pytest.approx(cfg.slope.overall_angle_deg, abs=1e-9)
