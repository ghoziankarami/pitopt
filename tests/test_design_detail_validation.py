"""
Reconciliation, the five validations and the exports.

The reconciliation is checked on a block model small enough to count by
hand: a square pit of blocks under one bench, so the ring of blocks the
practical wall reaches is a number that can be written down. The exports are
read back with the same libraries a CAD package would use.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import ezdxf
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import Point, Polygon, box

from pitopt.config import BermConfig, DesignConfig, DesignDetailConfig, DesignLimitsConfig, ProjectConfig, RampConfig, SectorConfig
from pitopt.core.design_detail.builder import build_design
from pitopt.core.design_detail.footprint import widen_to_min_width, working_width
from pitopt.core.design_detail.parameters import BLOCKED, OK, WARNING, resolve_sectors
from pitopt.core.design_detail.ramp import build_ramp, size_ramp
from pitopt.core.design_detail.reconcile import Reconciliation, Tally, reconcile
from pitopt.core.design_detail.stack import Bench, build_bench_stack
from pitopt.core.design_detail.validate import validate

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".pytest_runs/example_tin/example_tin_blocks.csv"


def block_pit(nx: int, ny: int, size: float = 10.0, z: float = 5.0, pad: int = 3, ore_every: int = 2) -> tuple[pd.DataFrame, np.ndarray]:
    """A rectangle of blocks (`nx` x `ny`) in the middle of a larger model, one block tall, with the shell
    being the middle rectangle. Every `ore_every`-th block is ore."""
    gx, gy = np.meshgrid(np.arange(nx + 2 * pad), np.arange(ny + 2 * pad), indexing="ij")
    x, y = (gx.ravel() + 0.5) * size, (gy.ravel() + 0.5) * size
    n = len(x)
    ore = (np.arange(n) % ore_every == 0)
    blocks = pd.DataFrame({
        "x": x, "y": y, "z": z, "dx": size, "dy": size, "dz": 10.0,
        "destination": ore.astype(int), "rock_tonnes": 1000.0, "ore_tonnes": np.where(ore, 400.0, 0.0),
        "value": np.where(ore, 5000.0, -700.0),
    })
    in_pit = ((gx.ravel() >= pad) & (gx.ravel() < pad + nx) & (gy.ravel() >= pad) & (gy.ravel() < pad + ny))
    return blocks, in_pit


def design_for(face: float, ramp: RampConfig | None = None, berm: float = 0.0, **kw) -> DesignConfig:
    return DesignConfig(bench_height=10.0, bench_face_angle_deg=face, detail=DesignDetailConfig(
        enabled=True, berm=BermConfig(method="manual", width=berm), ramp=ramp or RampConfig(enabled=False), **kw))


def stack_of(blocks: pd.DataFrame, in_pit: np.ndarray, design: DesignConfig, n: int = 1):
    outline = box(*(blocks.loc[in_pit, "x"].min() - 5, blocks.loc[in_pit, "y"].min() - 5,
                    blocks.loc[in_pit, "x"].max() + 5, blocks.loc[in_pit, "y"].max() + 5))
    sectors, _ = resolve_sectors(design, 30.0)
    return build_bench_stack(outline, 0.0, n, sectors, design.detail)


# ── reconciliation, counted by hand ─────────────────────────────────────────────────────────────────────────────
def test_the_ring_of_blocks_a_flat_wall_reaches_is_counted_exactly():
    """10 x 10 blocks of 10 m under one 10 m bench at 30 degrees. The face runs 17.3 m; the plane through the
    block centres cuts it half way, 8.66 m out. Blocks beside the edge have their centre 5 m out and are taken;
    the corner blocks are 7.07 m from the corner and are taken; the next ring is 15 m out and is not.
    So the design is 12 x 12 = 144 blocks: 44 gained, none left behind."""
    blocks, in_pit = block_pit(10, 10)
    design = design_for(30.0)
    stack = stack_of(blocks, in_pit, design)
    r = reconcile(blocks, in_pit, stack, stack, None, design.detail.limits)

    assert r.shell.blocks == 100 and r.design.blocks == 144
    assert r.gained_total.blocks == 44 and r.gained["batter"].blocks == 44
    assert r.gained["min_width"].blocks == 0 and r.gained["ramp"].blocks == 0
    assert r.left_behind.blocks == 0


def test_tonnes_and_value_follow_the_blocks():
    blocks, in_pit = block_pit(10, 10)
    design = design_for(30.0)
    stack = stack_of(blocks, in_pit, design)
    r = reconcile(blocks, in_pit, stack, stack, None, design.detail.limits)
    assert r.design.rock_tonnes == pytest.approx(144 * 1000.0)
    assert r.change_pct("rock_tonnes") == pytest.approx(100.0 * 44 / 100)
    ore_design = int(((blocks["destination"] == 1) & r.in_design).sum())
    assert r.design.ore_blocks == ore_design and r.design.ore_tonnes == pytest.approx(ore_design * 400.0)
    assert r.design.value == pytest.approx(ore_design * 5000.0 - (144 - ore_design) * 700.0)


def test_the_tonnage_table_is_the_sum_of_the_per_block_classification():
    """design = shell + gained - left behind, for every figure, and the per-bench map sums to the same."""
    blocks, in_pit = block_pit(10, 10)
    design = design_for(30.0)
    stack = stack_of(blocks, in_pit, design)
    r = reconcile(blocks, in_pit, stack, stack, None, design.detail.limits)
    assert all(abs(v) < 1e-6 for v in r.residual().values())
    by = r.per_bench.groupby("category")[["blocks", "rock_tonnes", "ore_tonnes", "value"]].sum()
    assert by.loc["design_only", "blocks"] == r.gained_total.blocks
    assert by.loc["both", "blocks"] + by.loc["design_only", "blocks"] == r.design.blocks
    assert by.loc["both", "rock_tonnes"] + by.loc["design_only", "rock_tonnes"] == pytest.approx(r.design.rock_tonnes)
    assert by.loc["both", "value"] + by.loc["design_only", "value"] == pytest.approx(r.design.value)


def test_a_crest_anchored_wall_leaves_the_shells_edge_behind():
    """Anchored at the crest the wall steps inward and the shell's outer ring is only partly inside it: the
    blocks left behind are the blocks the optimiser wanted at the edge."""
    blocks, in_pit = block_pit(10, 10)
    design = design_for(30.0, anchor="crest")
    stack = stack_of(blocks, in_pit, design)
    r = reconcile(blocks, in_pit, stack, stack, None, design.detail.limits)
    assert r.left_behind.blocks > 0 and r.design.blocks < r.shell.blocks
    assert r.gained_total.blocks == 0


def test_thresholds_come_from_the_limits_and_grade_the_change():
    tally = Tally(blocks=100, rock_tonnes=1000.0, ore_tonnes=1000.0, value=1000.0)

    def status(change_pct: float, warn: float = 5.0, block: float = 10.0) -> str:
        design = Tally(blocks=100, rock_tonnes=1000.0 * (1 + change_pct / 100), ore_tonnes=1000.0, value=1000.0)
        return Reconciliation(tally, design, {}, Tally(), pd.DataFrame(), None, warn, block).status("rock_tonnes")

    assert status(4.9) == OK and status(-5.0) == OK
    assert status(5.1) == WARNING and status(-9.9) == WARNING
    assert status(10.1) == BLOCKED and status(-10.1) == BLOCKED
    assert status(8.0, warn=10.0, block=20.0) == OK                  # the limits are parameters, not constants
    assert Reconciliation(Tally(), Tally(), {}, Tally(), pd.DataFrame()).status("rock_tonnes") == OK   # nothing to compare


# ── minimum mining width ────────────────────────────────────────────────────────────────────────────────────────
def test_a_narrow_floor_is_widened_to_exactly_the_minimum_and_a_wide_one_is_left_alone():
    slot = box(-150, -10, 150, 10)                                   # 20 m wide
    wide, changed = widen_to_min_width(slot, 40.0)
    assert changed and working_width(wide) == pytest.approx(40.0, abs=0.1)
    assert wide.contains(slot)
    same, changed = widen_to_min_width(box(-150, -30, 150, 30), 40.0)
    assert not changed and same.area == pytest.approx(300 * 60)


def test_each_part_of_a_split_floor_is_widened_on_its_own():
    parts = box(-100, -10, -40, 10).union(box(40, -25, 100, 25))     # 20 m wide and 50 m wide
    wide, changed = widen_to_min_width(parts, 40.0)
    assert changed and len(wide.geoms) == 2
    widths = sorted(working_width(p) for p in wide.geoms)
    assert widths[0] == pytest.approx(40.0, abs=0.1) and widths[1] == pytest.approx(50.0, abs=0.1)


def test_widening_the_floor_is_reported_as_its_own_dilution_and_never_double_counted():
    """A 3-block-wide pit (30 m) under a 60 m minimum: the batter takes what the wall needs, the widening takes
    more, and every block is in exactly one of the two."""
    blocks, in_pit = block_pit(3, 12, pad=6)
    limits = DesignLimitsConfig(min_mining_width_m=60.0)
    design = design_for(30.0, limits=limits)
    plain = stack_of(blocks, in_pit, design)
    wide_outline, changed = widen_to_min_width(plain.anchor_outline, 60.0)
    assert changed
    sectors, _ = resolve_sectors(design, 30.0)
    wide = build_bench_stack(wide_outline, 0.0, 1, sectors, design.detail)
    r = reconcile(blocks, in_pit, plain, wide, None, limits)
    assert r.gained["min_width"].blocks > 0 and r.gained["batter"].blocks > 0
    assert all(abs(v) < 1e-6 for v in r.residual().values())
    only_plain = reconcile(blocks, in_pit, plain, plain, None, limits)
    assert r.design.blocks > only_plain.design.blocks
    assert r.gained["batter"].blocks == only_plain.gained["batter"].blocks    # the walls take the same either way


# ── the five validations ────────────────────────────────────────────────────────────────────────────────────────
def test_the_east_and_west_examples_from_the_brief_fail_their_own_checks():
    """East over its inter-ramp limit, west over its overall limit: blocked, and every other sector passes."""
    sectors = [SectorConfig(name="Utara", azimuth_from=315, azimuth_to=45, ira_max_deg=60.0, osa_max_deg=60.0),
               SectorConfig(name="Timur", azimuth_from=45, azimuth_to=135, ira_max_deg=30.0, osa_max_deg=60.0),
               SectorConfig(name="Selatan", azimuth_from=135, azimuth_to=225, ira_max_deg=60.0, osa_max_deg=60.0),
               SectorConfig(name="Barat", azimuth_from=225, azimuth_to=315, ira_max_deg=60.0, osa_max_deg=30.0)]
    if not EXAMPLE.exists():
        pytest.skip("no generated example run")
    blocks = pd.read_csv(EXAMPLE)
    in_pit = blocks["in_pit"].to_numpy().astype(bool)
    cfg = ProjectConfig.from_yaml("projects/example_tin/project.yaml")
    cfg.design.detail = DesignDetailConfig(enabled=True, sectors=sectors, berm=BermConfig(method="slope"),
                                           ramp=RampConfig(width_m=15.0))
    v = build_design(blocks, in_pit, cfg).validation
    failed = {(f.check, f.scope) for f in v.findings if f.status == BLOCKED}
    assert ("ira", "Timur") in failed and ("osa", "Barat") in failed
    assert not {s for c, s in failed if c in ("ira", "osa")} - {"Timur", "Barat"}
    assert v.status("ira") == BLOCKED and v.status("osa") == BLOCKED


def test_a_bowtie_outline_is_blocked_as_a_self_intersection():
    blocks, in_pit = block_pit(10, 10)
    design = design_for(30.0)
    stack = stack_of(blocks, in_pit, design, n=2)
    bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])
    assert not bowtie.is_valid
    stack.benches[0] = Bench(1, stack.benches[0].crest_rl, stack.benches[0].toe_rl, bowtie, bowtie, {}, {})
    v = validate(stack, [], [], None, 100.0, None, design.detail.limits)
    assert v.status("self_intersection") == BLOCKED
    assert any("valid polygon" in f.message for f in v.findings)


def test_a_wall_that_overhangs_is_blocked():
    blocks, in_pit = block_pit(10, 10)
    design = design_for(30.0)
    stack = stack_of(blocks, in_pit, design, n=2)
    upper, lower = stack.benches
    stack.benches[0], stack.benches[1] = (Bench(1, upper.crest_rl, upper.toe_rl, upper.crest, lower.crest, {}, {}),
                                          Bench(2, lower.crest_rl, lower.toe_rl, upper.crest.buffer(50), lower.toe, {}, {}))
    v = validate(stack, [], [], None, 100.0, None, design.detail.limits)
    assert v.status("self_intersection") == BLOCKED and any("overhangs" in f.message for f in v.findings)


def test_a_clean_stack_passes_the_self_intersection_check():
    blocks, in_pit = block_pit(10, 10)
    design = design_for(30.0)
    stack = stack_of(blocks, in_pit, design, n=3)
    assert validate(stack, [], [], None, 100.0, None, design.detail.limits).status("self_intersection") == OK


def test_a_broken_ramp_blocks_and_names_the_bench_and_a_narrow_road_warns():
    ring = Point(0, 0).buffer(30, quad_segs=32)
    design = design_for(70.0, ramp=RampConfig(width_m=20.0, truck_width_m=7.0), berm=6.5)   # 10.1 m of drift a bench
    sectors, _ = resolve_sectors(design, 30.0)
    stack = build_bench_stack(ring, 0.0, 4, sectors, design.detail)
    cfg = design.detail.ramp
    ramp = build_ramp(stack, size_ramp(cfg), cfg)
    v = validate(stack, [], [], ramp, 60.0, None, design.detail.limits)
    assert any(f.check == "ramp" and f.status == WARNING and "narrower" in f.message for f in v.findings)   # 20 m < 24.5 m
    steep = build_ramp(stack, size_ramp(RampConfig(width_m=25.0, grade_pct=99.0)), cfg)
    v = validate(stack, [], [], steep, 60.0, None, design.detail.limits)
    assert v.status("ramp") == BLOCKED and any(f.scope.startswith("bench") for f in v.findings if f.check == "ramp")


def test_the_floor_under_the_minimum_mining_width_is_blocked():
    blocks, in_pit = block_pit(10, 10)
    design = design_for(30.0)
    stack = stack_of(blocks, in_pit, design)
    assert validate(stack, [], [], None, 20.0, None, design.detail.limits).status("min_width") == BLOCKED
    assert validate(stack, [], [], None, 35.0, None, design.detail.limits).status("min_width") == OK


def test_the_worst_finding_decides_a_checks_status():
    blocks, in_pit = block_pit(10, 10)
    design = design_for(30.0)
    stack = stack_of(blocks, in_pit, design)
    v = validate(stack, [], [], None, 100.0, None, design.detail.limits)
    assert v.status() == OK and set(v.by_check()) == {"shape_fit", "ira", "osa", "reconciliation", "ramp", "self_intersection", "min_width"}


# ── the exports, read back the way a CAD package would ──────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    if not EXAMPLE.exists():
        pytest.skip("no generated example run")
    from pitopt.io.design_export import write_all

    blocks = pd.read_csv(EXAMPLE)
    in_pit = blocks["in_pit"].to_numpy().astype(bool)
    cfg = ProjectConfig.from_yaml("projects/example_tin/project.yaml")
    cfg.output.design_shell_reference = True
    cfg.provenance = {"design.detail.ramp.grade_pct": {"source": "asumsi", "note": "typical for the fleet"},
                      "design.detail.ramp.width_m": {"source": "dokumen", "ref": "Haul study T2"}}
    cfg.design.detail = DesignDetailConfig(enabled=True, berm=BermConfig(method="slope"), ramp=RampConfig(width_m=15.0))
    detail = build_design(blocks, in_pit, cfg)
    out = tmp_path_factory.mktemp("design_export")
    written = write_all(detail, cfg, out, "ex", {"final_shell": 7, "final_rf": 0.96}, blocks, in_pit)
    return detail, cfg, out, written


def test_every_output_is_written_and_not_empty(exported):
    _, _, _, written = exported
    assert set(written) >= {"design_benches_dxf", "design_ramp_dxf", "design_sectors_dxf", "design_detail_json",
                            "design_reconciliation_csv", "design_by_bench_csv", "design_reconciliation_xlsx"}
    assert all(Path(p).stat().st_size > 0 for p in written.values())


def test_the_dxf_is_ac1024_with_a_layer_per_elevation_and_the_bench_polylines(exported):
    detail, _, out, _ = exported
    doc = ezdxf.readfile(out / "ex_design_benches.dxf")
    assert doc.dxfversion == "AC1024"
    layers = {layer.dxf.name for layer in doc.layers}
    n = len(detail.stack.benches)
    assert len([n_ for n_ in layers if n_.startswith("PD_CREST_")]) == n
    assert len([n_ for n_ in layers if n_.startswith("PD_TOE_")]) == n and "PD_SHELL_REF" in layers
    for bench in detail.stack.benches:
        layer = f"PD_CREST_{bench.crest_rl:g}".replace(".", "_")
        lines = [e for e in doc.modelspace().query("POLYLINE") if e.dxf.layer == layer]
        assert lines and lines[0].is_closed
        assert {round(v.dxf.location.z, 6) for v in lines[0].vertices} == {round(bench.crest_rl, 6)}
    assert all(" " not in name and "." not in name for name in layers)


def test_the_ramp_dxf_carries_the_real_elevations_and_both_edges(exported):
    detail, _, out, _ = exported
    doc = ezdxf.readfile(out / "ex_design_ramp.dxf")
    centre = [e for e in doc.modelspace().query("POLYLINE") if e.dxf.layer == "PD_RAMP_CL"]
    edges = [e for e in doc.modelspace().query("POLYLINE") if e.dxf.layer == "PD_RAMP_EDGE"]
    assert len(centre) == 1 and len(edges) == 2
    z = [v.dxf.location.z for v in centre[0].vertices]
    assert z[0] == pytest.approx(detail.ramp.z[0]) and z[-1] == pytest.approx(detail.ramp.z[-1])
    left, right = ([(v.dxf.location.x, v.dxf.location.y) for v in e.vertices] for e in edges)
    gap = np.hypot(*(np.array(left) - np.array(right)).T)
    assert gap.mean() == pytest.approx(15.0, rel=0.02)              # the edges are one road width apart


def test_the_provenance_travels_in_the_dxf_header_and_the_json(exported):
    detail, _, out, _ = exported
    header = dict(ezdxf.readfile(out / "ex_design_benches.dxf").header.custom_vars.properties)
    assert header["PD_SHELL_SHA256"] == detail.shell_sha256 and header["PD_SIGNED_BY_CP"] == "false"
    assert header["PD_VALIDATION_RECONCILIATION"] == detail.validation.by_check()["reconciliation"]
    doc = json.loads((out / "ex_design_detail.json").read_text())
    prov = doc["provenance"]
    assert prov["signedByCP"] is False and prov["sourceShell"]["final_rf"] == 0.96
    assert prov["sourceShell"]["sha256"] == detail.shell_sha256 and len(detail.shell_sha256) == 64
    assert set(prov["validation"]) == {"shapeFit", "ira", "osa", "reconciliation", "ramp", "selfIntersection", "minWidth"}
    sources = {p["id"]: p for p in prov["parameters"]}
    assert sources["ramp.grade_pct"]["source"] == "ASUMSI" and sources["ramp.grade_pct"]["note"]
    assert sources["ramp.width_m"]["source"] == "DOKUMEN" and sources["ramp.width_m"]["ref"] == "Haul study T2"
    assert sources["anchor"]["source"] == "DEFAULT"                # nothing recorded means the engine's own value


def test_the_json_reconciliation_closes_and_matches_the_csv(exported):
    _, _, out, _ = exported
    doc = json.loads((out / "ex_design_detail.json").read_text())
    r = doc["reconciliation"]
    assert all(abs(v) < 1e-6 for v in r["residual"].values())
    gained = sum(g["rock_tonnes"] for g in r["gained"].values())
    assert r["practical_design"]["rock_tonnes"] == pytest.approx(r["shell"]["rock_tonnes"] + gained - r["left_behind"]["rock_tonnes"])
    csv = pd.read_csv(out / "ex_design_reconciliation.csv").set_index("line")
    assert csv.loc["practical_design", "rock_tonnes"] == pytest.approx(r["practical_design"]["rock_tonnes"])
    assert csv.loc["residual (must be 0)", "rock_tonnes"] == pytest.approx(0.0, abs=1e-6)
    by_bench = pd.read_csv(out / "ex_design_by_bench.csv")
    assert by_bench.loc[by_bench["category"] != "shell_only", "rock_tonnes"].sum() == pytest.approx(r["practical_design"]["rock_tonnes"])


def test_the_json_is_strict_json_with_no_nan(exported):
    _, _, out, _ = exported
    text = (out / "ex_design_detail.json").read_text()
    json.loads(text, parse_constant=lambda c: pytest.fail(f"non-finite number {c} in the JSON"))
    assert "NaN" not in text and "Infinity" not in text


def test_the_workbook_has_the_sheets_a_report_reads(exported):
    _, _, out, _ = exported
    sheets = pd.read_excel(out / "ex_design_reconciliation.xlsx", sheet_name=None)
    assert list(sheets) == ["Reconciliation", "By bench", "Validation", "Sectors", "Parameters"]
    assert len(sheets["Validation"]) > 0 and len(sheets["Sectors"]) == 1


# ── the whole pipeline: switching it on must not move anything that was there ───────────────────────────────────
def test_switching_the_detailed_design_on_leaves_every_existing_result_untouched(tmp_path):
    """Run the example twice, detail off and detail on. Every value in the results document that existed before
    is identical; the only additions are the design_detail block and the new parameters and files."""
    from test_regression_gate import digest

    from pitopt.pipeline import run

    off = sorted((ROOT / ".pytest_runs/example_tin").glob("*_results.json"))
    if not off:
        pytest.skip("no generated example run")
    cfg = ProjectConfig.from_yaml(str(ROOT / "projects/example_tin/project.yaml"))
    cfg.output.directory = str(tmp_path)
    cfg.design.detail = DesignDetailConfig(enabled=True, berm=BermConfig(method="slope"), ramp=RampConfig(width_m=15.0))
    run(cfg, verbose=False, context={"project": "example_tin", "scenario": "project"})

    before = digest(json.loads(off[0].read_text()))
    after_doc = json.loads(next(tmp_path.glob("*_results.json")).read_text())
    after = digest(after_doc)

    changed = [k for k in before if k in after and before[k] != after[k] and not k.startswith("params.design.detail")]
    assert not changed, f"detail-on moved existing results: {changed[:8]}"
    assert not [k for k in before if k not in after and not k.startswith("params.design.detail")]
    assert "design_detail" in after_doc and after_doc["design_detail"]["reconciliation"]["raster_design"]
    assert {"ex" for f in tmp_path.glob("*_design_detail.json")} and list(tmp_path.glob("*_design_benches.dxf"))
    assert any(f["name"].endswith("_design_reconciliation.xlsx") for f in after_doc["outputs"])


# ── the road cut ────────────────────────────────────────────────────────────────────────────────────────────────
def _road_pit(berm: float = 6.5, benches: int = 6):
    design = design_for(70.0, ramp=RampConfig(width_m=25.0), berm=berm)
    sectors, _ = resolve_sectors(design, 30.0)
    stack = build_bench_stack(Point(0, 0).buffer(100, quad_segs=64), 0.0, benches, sectors, design.detail)
    return design, stack, build_ramp(stack, size_ramp(design.detail.ramp), design.detail.ramp)


def test_the_cut_above_the_road_leans_outward_at_the_face_angle():
    """h metres above a stretch of road the cut reaches W/2 + h / tan(face) from its centreline: 12.5 + 5 * 0.364."""
    from pitopt.core.design_detail.reconcile import _road_cut, _road_cut_at

    _, stack, ramp = _road_pit()
    road = _road_cut(ramp, stack.sectors)
    i, h = len(ramp.x) // 4, 5.0
    mid = np.array([(ramp.x[i] + ramp.x[i + 1]) / 2, (ramp.y[i] + ramp.y[i + 1]) / 2])
    outward = (mid - ramp.centre) / np.hypot(*(mid - ramp.centre))
    reach = 12.5 + h / math.tan(math.radians(70.0))
    cut = _road_cut_at(float((ramp.z[i] + ramp.z[i + 1]) / 2 + h), road, 12.5, window=1e9)
    inside, outside = Point(*(mid + (reach - 0.3) * outward)), Point(*(mid + (reach + 0.3) * outward))
    assert cut.contains(inside) and not cut.contains(outside)


def test_road_below_a_level_is_cut_and_road_above_it_is_not():
    from pitopt.core.design_detail.reconcile import _road_cut, _road_cut_at

    _, stack, ramp = _road_pit()
    road = _road_cut(ramp, stack.sectors)
    assert _road_cut_at(ramp.z[0] - 1.0, road, 12.5, 1e9).is_empty              # below the whole road: nothing yet
    low = _road_cut_at(ramp.z[len(ramp.z) // 3], road, 12.5, 1e9)
    high = _road_cut_at(ramp.z[-1], road, 12.5, 1e9)
    assert 0 < low.area < high.area                                              # the cut only grows as the road climbs


def test_the_cut_window_is_where_the_excess_over_the_wall_reaches_zero():
    """Excess = (W - berm) - h * berm / H: for W = 25, berm 6.5, H 10 it is gone at h = 18.5 * 10 / 6.5 = 28.5 m.
    With no berm the wall never catches up, so the window is the whole depth."""
    from pitopt.core.design_detail.reconcile import _cut_window

    _, stack, ramp = _road_pit()
    assert _cut_window(ramp, stack) == pytest.approx(min(60.0, 18.5 * 10.0 / 6.5 + 10.0))
    _, stack, ramp = _road_pit(berm=0.0)
    assert _cut_window(ramp, stack) == pytest.approx(60.0)


def test_adding_the_road_only_ever_adds_material():
    if not EXAMPLE.exists():
        pytest.skip("no generated example run")
    blocks = pd.read_csv(EXAMPLE)
    in_pit = blocks["in_pit"].to_numpy().astype(bool)
    cfg = ProjectConfig.from_yaml("projects/example_tin/project.yaml")
    cfg.design.detail = DesignDetailConfig(enabled=True, berm=BermConfig(method="slope"), ramp=RampConfig(width_m=15.0))
    with_road = build_design(blocks, in_pit, cfg).reconciliation
    cfg.design.detail = DesignDetailConfig(enabled=True, berm=BermConfig(method="slope"), ramp=RampConfig(enabled=False))
    without = build_design(blocks, in_pit, cfg).reconciliation
    assert (with_road.in_design | ~without.in_design).all()                      # nothing the walls took is given back
    assert with_road.gained["ramp"].blocks > 0 and without.gained["ramp"].blocks == 0
    assert with_road.gained["batter"].blocks == without.gained["batter"].blocks   # the walls take the same either way


# ── shape_fit: does the shell fit a single-cone offset at all ──────────────────────────────────────────────────
def test_worst_shell_fit_finds_the_exact_bench_and_ratio_by_hand():
    """Two benches on a 10 m-radius circular floor (pi*100 = 314.16 m2). Feed a shell_areas table that matches
    the design exactly at the floor and gives the crest an area ten times its own: the worst point must be
    exactly that bench's crest, at a ratio computable by hand."""
    from pitopt.core.design_detail.footprint import worst_shell_fit

    design = design_for(30.0, berm=6.5)
    sectors, _ = resolve_sectors(design, 30.0)
    stack = build_bench_stack(Point(0, 0).buffer(10, quad_segs=64), 0.0, 2, sectors, design.detail)
    areas = {}
    for bench in stack.benches:
        areas[bench.toe_rl - 5.0] = bench.toe.area           # dz/2 = 5.0 (bench_height 10) below the RL: the block-centre z
        areas[bench.crest_rl - 5.0] = bench.crest.area
    top = stack.benches[0]
    inflated = top.crest.area * 10.0
    areas[top.crest_rl - 5.0] = inflated

    fit = worst_shell_fit(stack, areas, dz=10.0)
    assert fit.bench == top.index and fit.side == "crest" and fit.rl == pytest.approx(top.crest_rl)
    assert fit.ratio == pytest.approx(top.crest.area / inflated) and fit.ratio == pytest.approx(0.1, abs=1e-9)
    assert fit.shell_area_m2 == pytest.approx(inflated)


def test_worst_shell_fit_is_none_with_no_shell_area_to_compare():
    from pitopt.core.design_detail.footprint import worst_shell_fit

    design = design_for(30.0, berm=6.5)
    sectors, _ = resolve_sectors(design, 30.0)
    stack = build_bench_stack(Point(0, 0).buffer(10, quad_segs=64), 0.0, 1, sectors, design.detail)
    assert worst_shell_fit(stack, {}, dz=10.0) is None


@pytest.mark.parametrize("ratio, status", [(0.9, OK), (0.55, WARNING), (0.1, BLOCKED)])
def test_shape_fit_status_follows_the_ratio_thresholds(ratio, status):
    from pitopt.core.design_detail.footprint import ShellFit
    from pitopt.core.design_detail.validate import _shape_fit_finding

    f = _shape_fit_finding(ShellFit(ratio, bench=3, side="toe", rl=100.0, design_area_m2=ratio * 1000, shell_area_m2=1000))
    assert f.status == status and f.check == "shape_fit" and "bench 3" in f.message


def test_a_shell_that_balloons_at_mid_height_and_pinches_at_both_ends_is_flagged():
    """The shape shape_fit exists for: floor and crest are small, a middle elevation is far wider than either —
    the pattern found in a real mineral-sands shell, reproduced here synthetically so the test needs no
    external data. A single-cone offset from the floor cannot reach the middle width in a few benches."""
    H, levels = 5.0, 6
    small = Point(0, 0).buffer(15, quad_segs=48)
    huge = Point(0, 0).buffer(120, quad_segs=48)
    blocks_list, size, z0 = [], 5.0, 0.0
    for k in range(levels):
        shape = huge if levels // 3 <= k <= 2 * levels // 3 else small       # wide in the middle third, narrow elsewhere
        minx, miny, maxx, maxy = shape.bounds
        xs = np.arange(minx, maxx, size) + size / 2
        ys = np.arange(miny, maxy, size) + size / 2
        gx, gy = np.meshgrid(xs, ys, indexing="ij")
        inside = shapely.contains_xy(shape, gx.ravel(), gy.ravel())
        blocks_list.append(pd.DataFrame({"x": gx.ravel()[inside], "y": gy.ravel()[inside], "z": z0 + H / 2 + k * H,
                                         "dx": size, "dy": size, "dz": H, "destination": 1,
                                         "rock_tonnes": 1.0, "ore_tonnes": 1.0, "value": 1.0}))
    blocks = pd.concat(blocks_list, ignore_index=True)
    in_pit = np.ones(len(blocks), dtype=bool)

    cfg = ProjectConfig.from_yaml("projects/example_tin/project.yaml")
    cfg.design.bench_height = H
    cfg.design.detail = DesignDetailConfig(enabled=True, berm=BermConfig(method="manual", width=2.0), ramp=RampConfig(enabled=False))
    d = build_design(blocks, in_pit, cfg)
    fit = next(f for f in d.validation.findings if f.check == "shape_fit")
    assert fit.status in (WARNING, BLOCKED) and fit.value < 1.0
    assert d.reconciliation.change_pct("rock_tonnes") < -30.0                    # the design misses most of the middle bulge
