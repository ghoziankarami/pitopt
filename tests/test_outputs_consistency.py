# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Orebit (Ghozian Islam Karami)
"""
The files a user hands on (Excel, PDF, DXF, CSV) must carry the same numbers as the run's
results.json, which is what the UI shows. Runs against every `outputs/*/*_results.json`.
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
from conftest import discover_runs, run_id  # noqa: E402

RESULTS = discover_runs()
skip_no_runs = pytest.mark.skipif(not RESULTS, reason="no runs in outputs/")


@pytest.fixture(params=RESULTS, ids=run_id)
def run(request):
    path = request.param
    r = json.loads(path.read_text())
    return r, path.parent, r["meta"]["name"]


def close(a, b, rel=1e-6, abs_=1e-6):
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def num(text: str) -> float:
    return float(re.sub(r"[^0-9.\-]", "", text))


@skip_no_runs
def test_pit_by_pit_csv_and_excel_equal_results(run):
    r, folder, name = run
    csv = pd.read_csv(folder / f"{name}_pit_by_pit.csv")
    sheet = pd.read_excel(folder / f"{name}_report.xlsx", sheet_name="Pit by Pit (RAF)")
    for table in (csv, sheet):
        assert len(table) == len(r["pit_by_pit"])
        for got, want in zip(table.itertuples(index=False), r["pit_by_pit"]):
            row = got._asdict()
            assert close(row["revenue_factor"], want["rf"])
            assert int(row["blocks"]) == want["blocks"]
            assert close(row["rock_tonnes"], want["rock_t"])
            assert close(row["value"], want["value"], rel=1e-9, abs_=1e-3)
            if "npv_average" in row and want["npv_avg"] is not None and not pd.isna(row["npv_average"]):
                assert close(row["npv_average"], want["npv_avg"], rel=1e-6, abs_=1.0)


@skip_no_runs
def test_excel_schedule_pushbacks_and_summary_equal_results(run):
    r, folder, name = run
    book = folder / f"{name}_report.xlsx"
    k = r["kpis"]
    summary = pd.read_excel(book, sheet_name="Summary").set_index("Item")["Value"].astype(str)
    assert f"RF {k['final_rf']:.2f}" in summary["Final pit"] and f"shell {k['final_shell']}" in summary["Final pit"]
    assert close(num(summary["Undiscounted value"]), k["value_undiscounted"], rel=1e-6, abs_=1.0)
    assert close(num(summary["Crest RL"]), k["crest_rl"], abs_=0.06) and close(num(summary["Toe RL"]), k["toe_rl"], abs_=0.06)

    for sheet, key in (("Schedule", "plan"), ("Schedule (best case)", "best"), ("Schedule (worst case)", "worst")):
        want = r["schedule"][key]
        if not want:
            continue
        got = pd.read_excel(book, sheet_name=sheet)
        assert len(got) == len(want)
        assert np.allclose(got["cash_flow"], [w["cash_flow"] for w in want], rtol=1e-9, atol=1e-3), sheet
        assert np.allclose(got["rock_tonnes"], [w["rock_tonnes"] for w in want], rtol=1e-9, atol=1e-3), sheet
    if r["pushbacks"]["rows"]:
        got = pd.read_excel(book, sheet_name="Pushbacks")
        assert np.allclose(got["value"], [p["value"] for p in r["pushbacks"]["rows"]], rtol=1e-9, atol=1e-3)
        assert list(got["blocks"]) == [p["blocks"] for p in r["pushbacks"]["rows"]]

    bench = pd.read_excel(book, sheet_name="Bench Summary")
    assert int(bench["blocks"].sum()) == r["pit_by_pit"][[x["shell"] for x in r["pit_by_pit"]].index(k["final_shell"])]["blocks"]
    assert close(bench["value"].sum(), k["value_undiscounted"], rel=1e-6, abs_=1.0)


@skip_no_runs
def test_pdf_reports_the_same_headline_numbers(run):
    import pypdfium2 as pdfium

    r, folder, name = run
    pdf = pdfium.PdfDocument(str(folder / f"{name}_report.pdf"))
    text = "\n".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
    k = r["kpis"]
    assert f"RF {k['final_rf']:.2f}" in text
    assert f"{k['value_undiscounted']:,.0f}" in text
    if r["schedule"]["plan"]:
        assert f"{k['npv_plan']:,.0f}" in text
        assert f"{k['npv_best']:,.0f}" in text and f"{k['npv_worst']:,.0f}" in text
    assert "()" not in text, "a label placeholder was left empty"
    assert "None" not in text and "nan" not in text.lower().replace("finance", "")


def _faces(path):
    import ezdxf

    msp = ezdxf.readfile(str(path)).modelspace()
    pts = []
    for f in msp.query("3DFACE"):
        pts.extend(tuple(v) for v in (f.dxf.vtx0, f.dxf.vtx1, f.dxf.vtx2, f.dxf.vtx3))
    return np.array(pts), len(msp.query("3DFACE"))


@skip_no_runs
@pytest.mark.parametrize("stem,layer", [("pit_face_position", "face"), ("pit_shell", "bowl")])
def test_dxf_surfaces_are_the_stored_surfaces(run, stem, layer):
    """Every DXF vertex sits on a node of the surface grid the UI draws, at that node's elevation."""
    r, folder, name = run
    dxf = folder / f"{name}_{stem}.dxf"
    if not dxf.exists():
        pytest.skip(f"{stem} not written")
    npz = np.load(folder / f"{name}_surfaces.npz")
    xs, ys, z = npz["xs"], npz["ys"], npz[layer]
    pts, n = _faces(dxf)
    assert n > 0
    ix = np.abs(pts[:, 0][:, None] - xs[None, :]).argmin(axis=1)
    iy = np.abs(pts[:, 1][:, None] - ys[None, :]).argmin(axis=1)
    step = float(xs[1] - xs[0])
    assert np.all(np.abs(pts[:, 0] - xs[ix]) < 1e-3) and np.all(np.abs(pts[:, 1] - ys[iy]) < 1e-3), "vertices are off-grid"
    expected = z[ix, iy]
    ok = np.isfinite(expected)
    assert ok.mean() > 0.95
    assert np.abs(pts[ok, 2] - expected[ok]).max() < 0.02 + 1e-3 * step, f"max |dz| {np.abs(pts[ok, 2] - expected[ok]).max():.4f}"


@skip_no_runs
def test_surface_grid_is_registered_to_the_block_footprints(run):
    """Surface nodes are cell centres laid from the model's true lower-left block edge — not shifted by
    the model origin — and the grid covers the whole block footprint."""
    r, folder, name = run
    blocks = pd.read_csv(folder / f"{name}_blocks.csv", usecols=["x", "y", "dx", "dy"])
    npz = np.load(folder / f"{name}_surfaces.npz")
    for axis, col, step in (("xs", "x", blocks["dx"].iloc[0]), ("ys", "y", blocks["dy"].iloc[0])):
        nodes = npz[axis]
        cell = float(nodes[1] - nodes[0])
        assert abs(nodes[0] - (blocks[col].min() - step / 2 + cell / 2)) < 1e-6, f"{axis} does not start at the true block edge"
        assert nodes[-1] >= blocks[col].max() + step / 2 - cell - 1e-6, f"{axis} stops short of the model"


@skip_no_runs
def test_dxf_face_position_never_above_topography_and_reaches_the_toe(run):
    r, folder, name = run
    dxf = folder / f"{name}_pit_face_position.dxf"
    if not dxf.exists():
        pytest.skip("no face position")
    npz = np.load(folder / f"{name}_surfaces.npz")
    xs, ys, topo = npz["xs"], npz["ys"], npz["topo"]
    pts, _ = _faces(dxf)
    ix = np.abs(pts[:, 0][:, None] - xs[None, :]).argmin(axis=1)
    iy = np.abs(pts[:, 1][:, None] - ys[None, :]).argmin(axis=1)
    above = pts[:, 2] - topo[ix, iy]
    assert np.nanmax(above) < 0.05, "face position rises above the topography"
    assert pts[:, 2].min() <= r["kpis"]["toe_rl"] + 0.5, "the deepest face does not reach the reported toe RL"


@skip_no_runs
def test_stage_dxf_files_match_plan(run):
    r, folder, name = run
    npz = np.load(folder / f"{name}_surfaces.npz")
    out = r["params"]["output"]
    for kind, count in (("pushback", len(r["pushbacks"]["rows"])), ("period", len(r["schedule"]["plan"]))):
        files = sorted(folder.glob(f"{name}_{kind}_*_end.dxf"))
        wanted = out["write_dxf"] and out[f"dxf_surface_{kind}s"]      # the user can switch the stage DXFs off
        assert len(files) == (count if wanted else 0), kind
        layers = [k for k in npz.files if k.startswith(f"{kind}_")]     # the UI's own copy is always written
        assert len(layers) == count
    # end-of-period surfaces never rise: each is at or below the previous one everywhere
    layers = [npz[f"period_{i}"] for i in range(1, len(r["schedule"]["plan"]) + 1)]
    for a, b in zip(layers, layers[1:]):
        assert np.nanmax(b - a) < 1e-6, "an end-of-period surface is higher than the period before it"


def _assert_offline_3d_html(html: str) -> None:
    assert len(html) > 100_000, "local plotly.min.js bundle does not appear to be embedded"
    assert not re.search(r'<script[^>]+src\s*=\s*["\']https?://', html, re.IGNORECASE), "external script CDN found"
    assert '<script src="https://cdn.plot.ly' not in html
    assert "https://cdn.plot.ly/plotly" not in html


@skip_no_runs
def test_3d_viewer_html_is_offline_no_cdn(run):
    _r, folder, name = run
    viewer = folder / f"{name}_3d_viewer.html"
    if not viewer.exists():
        pytest.skip("3d_viewer.html not written")
    _assert_offline_3d_html(viewer.read_text(encoding="utf-8", errors="ignore"))


def test_write_3d_html_is_offline_no_cdn(tmp_path):
    from pitopt.io.viz import write_interactive_3d

    xs = np.linspace(500_000.0, 500_100.0, 11)
    ys = np.linspace(9_150_000.0, 9_150_100.0, 11)
    topo = np.full((11, 11), 100.0)
    pit = np.full((11, 11), 80.0)
    out = tmp_path / "demo_3d_viewer.html"
    write_interactive_3d(xs, ys, topo, pit, [], str(out), "Demo Pit")
    _assert_offline_3d_html(out.read_text(encoding="utf-8"))


def test_write_report_pdf_includes_crs_provenance_and_design_reconciliation(tmp_path):
    import pypdfium2 as pdfium

    from pitopt.io.pdf import write_report

    pdf_path = tmp_path / "demo_report.pdf"
    pit_by_pit = pd.DataFrame(
        [{"shell": 1, "revenue_factor": 1.0, "blocks": 100, "rock_tonnes": 1000.0, "ore_tonnes": 400.0,
          "waste_tonnes": 600.0, "strip_ratio": 1.5, "value": 50000.0, "npv_best": 45000.0, "npv_worst": 40000.0}]
    )
    schedule = pd.DataFrame(
        [{"period": 1, "blocks": 100, "rock_tonnes": 1000.0, "ore_tonnes": 400.0, "waste_tonnes": 600.0,
          "strip_ratio": 1.5, "cash_flow": 50000.0, "discount_factor": 0.909, "discounted_cash_flow": 45450.0, "npv": 45450.0}]
    )
    write_report(
        str(pdf_path),
        "Demo Project",
        headline=[("Final pit", "shell 1, RF 1.00"), ("Undiscounted value", "50,000")],
        parameters=[("Slope", "45 deg"), ("Mining cost", "2.50/t")],
        pit_by_pit=pit_by_pit,
        schedule=schedule,
        sensitivity=None,
        warnings=[],
        assumptions=["Constant planning price across mine life."],
        plan_label="best case",
        crs="EPSG:32748",
        vertical_datum="EGM2008",
        provenance={
            "block_model.file": {"source": "input", "note": "GeoSuite CSV export"},
            "slope.overall_angle_deg": {"source": "terukur", "note": "Geotech sector A"},
            "economics.royalty_rate": {"source": "asumsi", "note": "Default 4% royalty"},
        },
        design_reconciliation=[("Rock tonnes change", "+2.5%"), ("Design value", "48,750")],
    )
    doc = pdfium.PdfDocument(str(pdf_path))
    text = "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    assert "EPSG:32748" in text
    assert "EGM2008" in text
    assert "Practical Design Reconciliation" in text
    assert "48,750" in text
    assert "Parameter Provenance" in text
    assert "GeoSuite CSV export" in text
    assert "terukur" in text
    assert "asumsi" in text
    assert "()" not in text
    assert "None" not in text


def test_write_surface_dxf_embeds_crs_and_vertical_datum_metadata(tmp_path):
    import ezdxf

    from pitopt.io.dxf import read_surface_metadata, write_surface

    xs = np.array([500_000.0, 500_010.0, 500_020.0])
    ys = np.array([9_150_000.0, 9_150_010.0, 9_150_020.0])
    grid = np.full((3, 3), 120.0)
    dxf_path = tmp_path / "pit_shell.dxf"
    faces = write_surface(
        str(dxf_path),
        xs,
        ys,
        grid,
        layer="PIT_SHELL",
        project="demo_project",
        crs="EPSG:32748",
        vertical_datum="EGM2008",
    )
    assert faces == 8
    meta = read_surface_metadata(str(dxf_path))
    assert meta["PROJECT"] == "demo_project"
    assert meta["CRS"] == "EPSG:32748"
    assert meta["VERTICAL_DATUM"] == "EGM2008"
    doc = ezdxf.readfile(str(dxf_path))
    assert doc.units == ezdxf.units.M
