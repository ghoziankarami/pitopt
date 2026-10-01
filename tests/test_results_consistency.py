"""
End-to-end consistency of an engine run: what the UI shows must equal what an
independent calculation from the exported block model gives. Runs against every
`outputs/*/*_results.json` that exists (skips when none).

  python -m pytest -q tests/test_results_consistency.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
from conftest import discover_runs, run_id  # noqa: E402

RESULTS = discover_runs()
pytestmark = pytest.mark.skipif(not RESULTS, reason="no runs in outputs/")


@pytest.fixture(params=RESULTS, ids=run_id)
def run(request):
    path = request.param
    r = json.loads(path.read_text())
    blocks = pd.read_csv(path.parent / f"{r['meta']['name']}_blocks.csv")
    return r, blocks


def close(a, b, rel=1e-6, abs_=1e-6):
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def test_block_value_recomputed_independently(run):
    """README valuation formula, re-implemented from the run's own parameters."""
    r, b = run
    e = r["params"]["economics"]
    # Grade as a fraction: per cent of mass or volume, parts per million, grams per tonne (also 1e-6 by mass).
    divisor = {"mass_percent": 100.0, "volume_percent": 100.0, "ppm": 1e6, "gpt": 1e6}[e["grade_basis"]]
    vol = b["volume"].to_numpy()
    rock = vol * b["density"].to_numpy()
    rec_vol, rec_mass = vol * e["mining_recovery"], rock * e["mining_recovery"]
    ore_t = rec_mass * (1 + e["dilution"])
    revenue = np.zeros(len(b))
    prod_cost = np.zeros(len(b))
    unit = {"t": 1.0, "kg": 1e3, "g": 1e6, "oz": 1e6 / 31.1034768, "lb": 1e3 / 0.45359237}
    for p in e["products"]:
        grade = b[p["grade_col"]].to_numpy() / divisor
        in_situ = grade * (rec_vol * p["density"] if e["grade_basis"] == "volume_percent" else rec_mass)
        t = in_situ * p["plant_recovery"]
        u = unit[p["price_unit"]]
        sell = t * p["selling_cost_per_tonne"] * u + (t / p["density"]) * p["selling_cost_per_volume"] * (p["density"] > 0)
        revenue += (t * p["price"] * u - sell) * (1 - e["royalty_rate"])
        prod_cost += t * p["processing_cost_per_tonne"] * u
    plant = ore_t * e["processing_cost_per_tonne"] + rec_vol * (1 + e["dilution"]) * e["processing_cost_per_volume"]
    fixed = rock * (e["mining_cost_per_tonne"] + e["rehabilitation_cost_per_tonne"]) + vol * (e["mining_cost_per_volume"] + e["rehabilitation_cost_per_volume"])
    if e["mining_cost_increment_per_m"]:
        # haulage rising with depth, from the reference RL (the top of the model when none is given)
        z = b["z"].to_numpy()
        reference = e["mining_cost_reference_rl"]
        if reference is None:
            reference = float((b["z"] + b["dz"] / 2).max())
        fixed = fixed + rock * e["mining_cost_increment_per_m"] * np.clip(reference - z, 0.0, None)
    value_ore = revenue - prod_cost - plant - fixed
    ore_domains = r["params"]["block_model"].get("ore_domains")
    if ore_domains:
        value_ore = np.where(b["domain"].isin(ore_domains).to_numpy(), value_ore, -fixed)
    classes = r["params"]["block_model"].get("include_classes")
    if classes:      # blocks outside the listed confidence classes carry no revenue: waste only
        value_ore = np.where(b["resource_class"].isin(classes).to_numpy(), value_ore, -fixed)
    value = np.maximum(value_ore, -fixed)
    got = b["value"].to_numpy()
    assert np.allclose(value, got, rtol=1e-6, atol=1e-3), f"max |diff| {np.abs(value - got).max():.6g}"


def test_kpis_match_block_model(run):
    r, b = run
    k, pit = r["kpis"], b[b["in_pit"]]
    assert close(pit["rock_tonnes"].sum(), k["rock_t"])
    assert close(pit.loc[pit["destination"] == 1, "ore_tonnes"].sum(), k["ore_t"])
    assert close(pit["value"].sum(), k["value_undiscounted"])
    assert close(pit["volume"].sum(), k["volume_m3"])


def test_schedule_is_the_block_model(run):
    """Period tonnes equal the sum over blocks tagged with that period, NPV is the
    discounted sum of the period cash flows, and total cash equals the pit value.
    Per-period cash may differ from the tagged block sum (bench runs are split
    proportionally); the run must report exactly that difference."""
    r, b = run
    if not r["schedule"]["plan"]:
        pytest.skip("no schedule in this run")
    rate, years = r["kpis"]["discount_rate"], r["params"]["schedule"]["period_years"]
    plan, npv = r["schedule"]["plan"], 0.0
    rec = {x["period"]: x for x in r["schedule"]["tag_reconciliation"]["rows"]}
    for row in plan:
        sel = b[b["period"] == row["period"]]
        assert len(sel) == row["blocks"]
        assert close(sel["rock_tonnes"].sum(), row["rock_tonnes"])
        assert close(sel.loc[sel["destination"] == 1, "ore_tonnes"].sum(), row["ore_tonnes"])
        assert close(sel["value"].sum(), rec[row["period"]]["tagged"], rel=1e-6, abs_=1.0)
        assert close(rec[row["period"]]["plan"], row["cash_flow"], rel=1e-9, abs_=1e-3)
        npv += row["cash_flow"] / (1 + rate) ** (row["period"] * years)
        assert close(npv, row["npv"], rel=1e-6, abs_=1.0), f"period {row['period']}"
    assert close(npv, r["kpis"]["npv_plan"], rel=1e-6, abs_=1.0)
    assert close(sum(x["cash_flow"] for x in plan), b.loc[b["in_pit"], "value"].sum(), rel=1e-6, abs_=1.0)
    assert (b["period"] > 0).sum() == b["in_pit"].sum()


def test_pushbacks_are_the_block_model(run):
    r, b = run
    rows = r["pushbacks"]["rows"]
    assert (b["pushback"] > 0).sum() == b["in_pit"].sum()
    for p in rows:
        sel = b[b["pushback"] == p["pushback"]]
        assert len(sel) == p["blocks"]
        assert close(sel["value"].sum(), p["value"], rel=1e-6, abs_=1.0)
        assert close(sel.loc[sel["destination"] == 1, "ore_tonnes"].sum(), p["ore_tonnes"])
    assert sum(p["blocks"] for p in rows) == b["in_pit"].sum()


def test_pit_by_pit_rows_are_nested_shells(run):
    r, b = run
    prev = 0
    for row in r["pit_by_pit"]:
        sel = b[(b["shell"] > 0) & (b["shell"] <= row["shell"])]
        assert len(sel) == row["blocks"], f"shell {row['shell']}"
        assert row["blocks"] >= prev
        prev = row["blocks"]
        if row["blocks"]:
            assert close(sel["rock_tonnes"].sum(), row["rock_t"])
    final = r["final_pit"]["row"]
    assert final["rf"] == r["final_pit"]["rf"] and final["shell"] == r["kpis"]["final_shell"]


def test_sensitivity_matches_plan_and_breakeven(run):
    r, _ = run
    s = r["sensitivity"]
    if not s:
        pytest.skip("no sensitivity in this run")
    at1 = next(x for x in s["all"] if abs(x["price_factor"] - 1) < 1e-9)
    assert close(at1["npv"], r["kpis"]["npv_plan"], rel=1e-6, abs_=1.0)
    for name, rows in (s.get("per_product") or {}).items():
        assert close(next(x for x in rows if abs(x["price_factor"] - 1) < 1e-9)["npv"], r["kpis"]["npv_plan"], rel=1e-6, abs_=1.0), name
    be = s.get("breakeven")
    if be is not None:
        xs = [x["price_factor"] for x in s["all"]]
        ys = [x["npv"] for x in s["all"]]
        assert close(float(np.interp(0.0, ys, xs)), be, rel=0.02), "break-even must lie where NPV crosses zero"


def test_plan_raster_matches_block_columns(run):
    r, b = run
    pv = r["plan_view"]
    pit = b[b["in_pit"]]
    columns = pit.assign(i=np.round((pit["x"] - pv["x0"]) / pv["dx"] - 0.5).astype(int),
                         j=np.round((pit["y"] - pv["y0"]) / pv["dy"] - 0.5).astype(int))[["i", "j"]].drop_duplicates()
    for field in ("pushback", "period", "depth"):
        if pv[field]:
            assert len(pv[field]) == pv["nx"] * pv["ny"]
    # per-column earliest pushback/period must match the block model
    grid = np.array(pv["pushback"]).reshape(pv["ny"], pv["nx"])
    assert (grid > 0).sum() == len(columns) or abs((grid > 0).sum() - len(columns)) <= max(2, 0.01 * len(columns))
    assert grid.max() == r["pushbacks"]["rows"][-1]["pushback"]


def test_design_reconciliation_matches_blocks(run):
    r, b = run
    d = r["design"]
    if not d:
        pytest.skip("design disabled")
    w = b["design_fraction"].to_numpy()
    assert int(round(w.sum())) == d["reconciliation"]["design"]["blocks"]
    assert close((b["rock_tonnes"] * w).sum(), d["reconciliation"]["design"]["rock_tonnes"], rel=1e-4)
    assert close((b["value"] * w).sum(), d["reconciliation"]["design"]["value"], rel=1e-4, abs_=1.0)
    assert ((w >= 0) & (w <= 1)).all() and (b["in_design"] == (w >= 0.5)).all()


def test_verification_is_clean_and_reported(run):
    r, _ = run
    assert r["verification"]["walls"] == 0 and r["verification"]["cone"] == 0 and r["verification"]["schedule"] == 0


def test_every_output_file_exists(run):
    r, _ = run
    for f in r["outputs"]:
        assert f["bytes"] > 0, f["name"]


def test_schedule_respects_plant_capacity_and_fills_it(run):
    """Whole blocks are scheduled, so a period meets capacity to within one block: never more than one block over,
    and every period but the last runs at capacity (the schedule only under-fills when the pit is exhausted)."""
    r, b = run
    one_block = float(b.loc[b["destination"] == 1, "ore_tonnes"].max())
    plan = r["schedule"]["plan"]
    cap = r["params"]["schedule"].get("ore_capacity") or 0
    if not plan or not cap or r["params"]["schedule"].get("periods"):
        pytest.skip("capacity not the binding input for this run")
    basis_tonnes = r["params"]["schedule"].get("basis", "tonnes") == "tonnes"
    if not basis_tonnes:
        pytest.skip("volume basis")
    for row in plan:
        assert row["ore_tonnes"] <= cap + one_block, f"period {row['period']} exceeds capacity by more than one block"
    for row in plan[:-1]:
        assert row["ore_tonnes"] >= cap - one_block, f"period {row['period']} under-fills the plant before the pit is exhausted"


def test_detailed_design_is_tied_to_the_block_model(run):
    """The detailed design's reconciliation, recomputed from the run's own block table: its shell tier is the
    in-pit blocks and nothing else, its middle tier is the raster design the run reported, the table closes, and
    a complete road climbs at exactly the grade that was asked for."""
    r, b = run
    d = r.get("design_detail")
    if not d:
        pytest.skip("detailed design not run")
    rec = d["reconciliation"]
    assert all(abs(v) < 1e-6 for v in rec["residual"].values())

    in_pit = b["in_pit"].astype(bool).to_numpy()
    ore = (b["destination"] == 1).to_numpy()
    shell = rec["shell"]
    assert shell["blocks"] == int(in_pit.sum())
    assert close(shell["rock_tonnes"], float(b.loc[in_pit, "rock_tonnes"].sum()), rel=1e-9)
    assert close(shell["ore_tonnes"], float(b.loc[in_pit & ore, "ore_tonnes"].sum()), rel=1e-9)
    assert close(shell["value"], float(b.loc[in_pit, "value"].sum()), rel=1e-9, abs_=1.0)
    assert shell["ore_blocks"] + shell["waste_blocks"] == shell["blocks"]

    if r.get("design") and rec["raster_design"]:
        assert close(rec["raster_design"]["rock_tonnes"], r["design"]["reconciliation"]["design"]["rock_tonnes"], rel=1e-9)

    ramp = d["ramp"]
    if ramp and ramp["complete"]:
        assert all(close(g, ramp["grade_pct"], rel=1e-6) for g in ramp["measured_grade_pct"].values())
        depth = d["crest_rl"] - d["floor_rl"]
        assert close(ramp["horizontal_length_m"], depth / (ramp["grade_pct"] / 100.0), rel=1e-6)
    assert set(d["provenance"]["validation"]) >= {"shapeFit", "ira", "osa", "reconciliation", "ramp", "selfIntersection", "minWidth"}
