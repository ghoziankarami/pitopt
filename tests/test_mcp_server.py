# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ghozi Ankarami and PitOpt contributors
"""Contract tests for pitopt.mcp_server and PitOptCommands without external MCP clients."""
from __future__ import annotations

import builtins
import importlib
import shutil
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

from pitopt import mcp_server
from pitopt.mcp_server import PitOptCommands, Session

ROOT = Path(__file__).resolve().parents[1]


def _copy_example_tin(tmp_path: Path) -> Path:
    project_dir = tmp_path / "example_tin"
    shutil.copytree(ROOT / "projects/example_tin", project_dir)
    yaml_path = project_dir / "project.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    out_dir = (tmp_path / "out").as_posix()
    text = text.replace("directory: outputs", f"directory: {out_dir}")
    yaml_path.write_text(text, encoding="utf-8")
    return yaml_path


@pytest.fixture(autouse=True)
def _reset_module_session():
    mcp_server.commands.session.config = None
    mcp_server.commands.session.result = None
    yield
    mcp_server.commands.session.config = None
    mcp_server.commands.session.result = None


def test_tools_before_load_return_helpful_message():
    cmds = PitOptCommands()
    assert "load_project" in cmds.set_product_price("SN", 25.0)
    assert "load_project" in cmds.set_costs(mining_cost_per_volume=3.0)
    assert "load_project" in cmds.set_slope(45.0)
    assert "load_project" in cmds.set_revenue_factors([1.0])
    assert "load_project" in cmds.validate_loaded_project()
    assert "load_project" in cmds.run_pit_optimization()
    assert "load_project" in cmds.build_detail_design()
    assert "load_project" in cmds.audit_provenance()
    assert "run_pit_optimization" in cmds.get_pit_report()
    assert "run_pit_optimization" in cmds.get_bench_summary()


def test_atomic_staging_rollback_on_validation_failure(tmp_path):
    yaml_path = _copy_example_tin(tmp_path)
    cmds = PitOptCommands()
    loaded = cmds.load_project(str(yaml_path))
    assert "Project 'example_tin'" in loaded

    orig_slope = cmds.session.config.slope.overall_angle_deg
    orig_price = cmds.session.config.economics.products[0].price
    orig_mining = cmds.session.config.economics.mining_cost_per_volume
    orig_rfs = list(cmds.session.config.shells.revenue_factors)

    with pytest.raises(ValueError):
        cmds.set_slope(-10.0)
    assert cmds.session.config.slope.overall_angle_deg == orig_slope

    with pytest.raises(ValueError):
        cmds.set_product_price("SN", -5.0)
    assert cmds.session.config.economics.products[0].price == orig_price

    with pytest.raises(ValueError):
        cmds.set_costs(mining_cost_per_volume=float("nan"))
    assert cmds.session.config.economics.mining_cost_per_volume == orig_mining

    with pytest.raises(ValueError):
        cmds.set_revenue_factors([])
    assert cmds.session.config.shells.revenue_factors == orig_rfs


def test_full_mcp_workflow_via_module_tools(tmp_path):
    yaml_path = _copy_example_tin(tmp_path)

    load_out = mcp_server.load_project(str(yaml_path))
    assert "example_tin" in load_out

    assert "->" in mcp_server.set_product_price("SN", 32000.0)
    assert mcp_server.session.config.economics.products[0].price == pytest.approx(32000.0)
    assert "Unknown" not in mcp_server.set_product_price("NONEXISTENT", 10.0)
    assert "Available:" in mcp_server.set_product_price("NONEXISTENT", 10.0)

    assert "Costs updated" in mcp_server.set_costs(mining_cost_per_volume=3.5)
    assert mcp_server.session.config.economics.mining_cost_per_volume == pytest.approx(3.5)

    assert "42.0 deg" in mcp_server.set_slope(42.0)
    assert mcp_server.session.config.slope.overall_angle_deg == pytest.approx(42.0)

    assert "[0.8, 1.0]" in mcp_server.set_revenue_factors([0.8, 1.0])
    assert mcp_server.session.config.shells.revenue_factors == [0.8, 1.0]

    val_out = mcp_server.validate_loaded_project()
    assert "Validated 'example_tin'" in val_out

    run_out = mcp_server.run_pit_optimization()
    assert "Outputs:" in run_out
    assert mcp_server.session.result is not None

    report_out = mcp_server.get_pit_report()
    assert "RF" in report_out or "1.00" in report_out

    bench_out = mcp_server.get_bench_summary()
    assert "ore_tonnes" in bench_out and "waste_tonnes" in bench_out


def test_detail_design_and_rollback(tmp_path):
    yaml_path = _copy_example_tin(tmp_path)
    cmds = PitOptCommands(Session())
    cmds.load_project(str(yaml_path))
    cmds.set_revenue_factors([1.0])
    cmds.run_pit_optimization()

    orig_bh = cmds.session.config.design.bench_height
    with pytest.raises(ValueError):
        cmds.build_detail_design(bench_height=-5.0)
    assert cmds.session.config.design.bench_height == orig_bh

    design_out = cmds.build_detail_design(bench_height=5.0, berm_width_m=4.0, bench_face_angle_deg=70.0)
    assert "Detailed design built" in design_out
    assert "Benches:" in design_out
    assert cmds.session.result.design_detail is not None


def test_reblock_model_tool(tmp_path):
    csv_path = tmp_path / "subcelled.csv"
    df = pd.DataFrame({
        "X": [2.5, 7.5, 2.5, 7.5],
        "Y": [2.5, 2.5, 7.5, 7.5],
        "Z": [2.5, 2.5, 2.5, 2.5],
        "DX": [5.0, 5.0, 5.0, 5.0],
        "DY": [5.0, 5.0, 5.0, 5.0],
        "DZ": [5.0, 5.0, 5.0, 5.0],
        "AU": [1.0, 2.0, 3.0, 4.0],
        "DENSITY": [2.5, 2.5, 2.5, 2.5],
        "CLASS": ["IND1", "IND2", "IND1", "INF1"],
    })
    df.to_csv(csv_path, index=False)

    out_dir = tmp_path / "reblocked"
    out = mcp_server.reblock_model(
        source=str(csv_path),
        target_dx=10.0,
        target_dy=10.0,
        target_dz=5.0,
        size_cols=["DX", "DY", "DZ"],
        grades=["AU"],
        categories=["CLASS"],
        density="DENSITY",
        out_dir=str(out_dir),
        name="sub",
    )
    assert "1 blocks" in out
    assert "500.0 m3" in out
    assert (out_dir / "sub_blocks.csv").exists()


def test_audit_provenance_tool(tmp_path):
    yaml_path = _copy_example_tin(tmp_path)
    cmds = PitOptCommands()
    cmds.load_project(str(yaml_path))
    cmds.session.config.provenance = {
        "slope.overall_angle_deg": {"source": "asumsi", "note": "Preliminary 45 deg"},
        "economics.products.SN.price": {"source": "input", "ref": "study_2026"},
    }
    audit = cmds.audit_provenance()
    assert "[asumsi]" in audit
    assert "Preliminary 45 deg" in audit
    assert "Fingerprint sha256:" in audit


def test_import_compatibility_v1_and_v2(monkeypatch):
    class FakeServer:
        def __init__(self, name: str):
            self.name = name

        def tool(self):
            return lambda fn: fn

        def run(self):
            return None

    # Simulate mcp v2 (mcp.server.mcpserver.MCPServer)
    mcp_pkg = types.ModuleType("mcp")
    mcp_server_pkg = types.ModuleType("mcp.server")
    mcp_v2 = types.ModuleType("mcp.server.mcpserver")
    mcp_v2.MCPServer = FakeServer

    monkeypatch.setitem(sys.modules, "mcp", mcp_pkg)
    monkeypatch.setitem(sys.modules, "mcp.server", mcp_server_pkg)
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", mcp_v2)
    reloaded = importlib.reload(mcp_server)
    assert isinstance(reloaded.mcp, FakeServer)

    # Simulate mcp v1 (mcp.server.fastmcp.FastMCP)
    monkeypatch.delitem(sys.modules, "mcp.server.mcpserver", raising=False)
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "mcp.server.mcpserver":
            raise ImportError("no v2")
        return real_import(name, globals, locals, fromlist, level)

    mcp_v1 = types.ModuleType("mcp.server.fastmcp")
    mcp_v1.FastMCP = FakeServer
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", mcp_v1)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    reloaded_v1 = importlib.reload(mcp_server)
    assert isinstance(reloaded_v1.mcp, FakeServer)
