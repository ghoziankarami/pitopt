"""
Acceptance: the detailed design on the shapes that break naive pit design.

Three pits, chosen because each defeats a different simple method: a regular
ellipse (the case every method gets right), an irregular concave pit (a bay
and a lobe, so the wall turns both ways) and a pit with an island or a saddle
(the outline gains a hole, or the floor nearly pinches).

Each shell is built the way an optimiser's is: the outline shrinks by one
bench's worth of wall per level, at the design's own inter-ramp angle. A shell
steeper than the design allows would show a large dilution that is the shell's
doing and not the engine's, so the wall is matched on purpose.

For each pit the design must have: no self-intersection, a road that is one
continuous path at the grade asked for, a reconciliation that closes exactly,
and a difference to the shell that is recorded and inside the blocked
threshold. A pit whose floor splits in two cannot have one road, and the
design has to say so and name the bench rather than draw something.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import shapely
from shapely import affinity
from shapely.geometry import Point, Polygon

from pitopt.config import BermConfig, DesignDetailConfig, ProjectConfig, RampConfig
from pitopt.core.design_detail.builder import build_design
from pitopt.core.design_detail.parameters import BLOCKED, OK

H, FACE, BERM_STEP = 10.0, 65.0, 11.16     # atan(10 / 11.16) = 41.9 degrees: what a 65 degree face with a 6.5 m berm gives


def ellipse(a: float, b: float) -> Polygon:
    return affinity.scale(Point(0, 0).buffer(1, quad_segs=64), a, b)


SHAPES = {
    "ellipse": ellipse(260, 170),
    "concave": ellipse(270, 175).difference(Point(-60, 170).buffer(90, quad_segs=48)).union(Point(200, -30).buffer(80, quad_segs=48)),
    "island": ellipse(300, 200).difference(Point(0, 0).buffer(15, quad_segs=48)),
    "saddle": Point(-140, 0).buffer(170, quad_segs=48).union(Point(140, 0).buffer(170, quad_segs=48)).union(
        Polygon([(-140, -90), (140, -90), (140, 90), (-140, 90)])),
}
SPLIT_FLOOR = Point(-150, 0).buffer(120, quad_segs=48).union(Point(150, 0).buffer(120, quad_segs=48)).union(
    Polygon([(-150, -55), (150, -55), (150, 55), (-150, 55)]))


def shell(crest: Polygon, levels: int = 8, size: float = 10.0):
    minx, miny, maxx, maxy = crest.buffer(20).bounds
    xs = np.arange(minx // size * size, maxx + size, size) + size / 2
    ys = np.arange(miny // size * size, maxy + size, size) + size / 2
    gx, gy = (a.ravel() for a in np.meshgrid(xs, ys, indexing="ij"))
    frames = []
    for k in range(levels):
        outline = crest.buffer(-k * BERM_STEP) if k else crest
        inside = shapely.contains_xy(outline, gx, gy) if not outline.is_empty else np.zeros(len(gx), dtype=bool)
        frames.append(pd.DataFrame({"x": gx, "y": gy, "z": 1000.0 + H / 2 + (levels - 1 - k) * H, "in": inside}))
    df = pd.concat(frames, ignore_index=True)
    ore = ((np.floor(df.x / 50) + np.floor(df.y / 50) + df.z // 10) % 3 == 0).to_numpy()
    tonnes = 2700 * size * size * H / 1000
    blocks = pd.DataFrame({"x": df.x, "y": df.y, "z": df.z, "dx": size, "dy": size, "dz": H,
                           "destination": ore.astype(int), "rock_tonnes": tonnes,
                           "ore_tonnes": np.where(ore, tonnes, 0.0), "value": np.where(ore, 4000.0, -900.0)})
    return blocks, df["in"].to_numpy()


def design(blocks, in_pit):
    cfg = ProjectConfig.from_yaml("projects/example_tin/project.yaml")
    cfg.design.bench_height, cfg.design.bench_face_angle_deg = H, FACE
    cfg.design.detail = DesignDetailConfig(enabled=True, berm=BermConfig(method="ritchie"),
                                           ramp=RampConfig(width_m=25.0, grade_pct=9.0))
    return build_design(blocks, in_pit, cfg)


@pytest.mark.parametrize("name", SHAPES)
def test_the_design_is_buildable_and_its_difference_to_the_shell_is_recorded(name):
    blocks, in_pit = shell(SHAPES[name])
    d = design(blocks, in_pit)
    v = d.validation

    assert v.status("self_intersection") == OK
    assert v.status("min_width") == OK
    assert d.ramp.complete, d.ramp.broken
    assert all(g == pytest.approx(9.0, abs=1e-6) for g in d.ramp.grade_by_bench().values())
    assert d.ramp.z[0] == pytest.approx(d.floor_rl) and d.ramp.z[-1] == pytest.approx(d.crest_rl)

    r = d.reconciliation
    assert all(abs(x) < 1e-6 for x in r.residual().values())                  # the table is the sum of the blocks
    for metric in ("rock_tonnes", "ore_tonnes", "value"):
        assert abs(r.change_pct(metric)) < r.block_pct, f"{metric} {r.change_pct(metric):+.1f}% is blocked"
    assert v.status("reconciliation") != BLOCKED


def test_the_difference_to_the_shell_is_a_few_per_cent_when_the_wall_matches_the_design():
    """Not a tuned target: with the shell's wall at the design's own angle, what is left is the road and the
    rounding of the staircase. Ellipse, bay-and-lobe, island and saddle all land in the same few per cent."""
    changes = {}
    for name, crest in SHAPES.items():
        blocks, in_pit = shell(crest)
        changes[name] = design(blocks, in_pit).reconciliation.change_pct("rock_tonnes")
    assert all(0.0 < c < 10.0 for c in changes.values()), changes
    assert max(changes.values()) - min(changes.values()) < 3.0, changes         # the shapes agree with one another


def test_a_floor_that_splits_in_two_blocks_the_ramp_and_names_the_bench():
    blocks, in_pit = shell(SPLIT_FLOOR)
    d = design(blocks, in_pit)
    assert not d.ramp.complete and d.validation.status("ramp") == BLOCKED
    assert d.ramp.broken.bench == len(d.stack.benches) and "splits" in d.ramp.broken.reason
    assert any(f.check == "ramp" and f.scope == f"bench {d.ramp.broken.bench}" for f in d.validation.problems())
    assert d.validation.status("self_intersection") == OK                      # the walls are still good
    assert all(abs(x) < 1e-6 for x in d.reconciliation.residual().values())
