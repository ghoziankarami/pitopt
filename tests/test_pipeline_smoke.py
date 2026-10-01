"""
End-to-end smoke test on synthetic data. Run this before pointing the
pipeline at a real resource — it confirms the local environment
(maximum_closure, networkx, scipy, ezdxf) is wired up and that the result has
the properties any correct pit must have.

The checks are deliberately about pit *behaviour*, not fixed numbers:
a wrong sign or a reversed cut convention produces an inverted pit with
no error message, and the only thing that catches it is asserting the
shape and the economics come out the right way round.

Run with:  pytest -q tests/test_pipeline_smoke.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from pitopt.config import EconomicsConfig, ProductConfig
from pitopt.core.economics import ORE, WASTE, marginal_cutoff_grades, product_margin, value_blocks
from pitopt.core.planning import pit_by_pit_npv, pushback_labels, select_final_pit, select_pushbacks
from pitopt.core.precedence import add_grid_indices, build_precedence, cone_offsets
from pitopt.core.schedule import specified_sequence, strip_sequence
from pitopt.core.shells import run_nested_shells

ROOT = Path(__file__).resolve().parent.parent

ECONOMICS = EconomicsConfig(
    grade_basis="mass_percent",
    mining_recovery=0.95,
    dilution=0.05,
    royalty_rate=0.03,
    mining_cost_per_tonne=2.50,
    processing_cost_per_tonne=9.50,
    products=[
        ProductConfig(
            name="SN",
            grade_col="SN_PCT",
            price=30_000.0,
            plant_recovery=0.85,
            selling_cost_per_tonne=1_500.0,
        )
    ],
)

# Two products with very different values, for the multi-product checks.
SANDS = EconomicsConfig(
    grade_basis="volume_percent",
    mining_recovery=0.97,
    dilution=0.03,
    mining_cost_per_volume=1.5,
    rehabilitation_cost_per_volume=20.0,
    products=[
        ProductConfig(name="ZIRCON", grade_col="ZR", price=1400.0, density=1.6,
                      plant_recovery=0.9025, processing_cost_per_tonne=900.0,
                      selling_cost_per_volume=250.0),
        ProductConfig(name="ILMENITE", grade_col="IL", price=280.0, density=1.6,
                      plant_recovery=0.9025, selling_cost_per_volume=250.0),
    ],
)


def make_toy_block_model(n_xy: int = 21, n_z: int = 10, dx=10.0, dy=10.0, dz=5.0) -> pd.DataFrame:
    """Rich core decaying outward, flat topography at z=0."""
    xs, ys = np.arange(n_xy) * dx, np.arange(n_xy) * dy
    zs = -np.arange(n_z) * dz
    cx, cy = xs.mean(), ys.mean()

    grid_x, grid_y, grid_z = np.meshgrid(xs, ys, zs, indexing="ij")
    radius = np.hypot(grid_x - cx, grid_y - cy)
    grade = np.clip(0.8 - 0.01 * radius + np.random.normal(0, 0.03, radius.shape), 0.0, None)

    df = pd.DataFrame(
        {
            "x": grid_x.ravel(), "y": grid_y.ravel(), "z": grid_z.ravel(),
            "SN_PCT": grade.ravel(),
            "dx": dx, "dy": dy, "dz": dz, "density": 1.8,
        }
    )
    return add_grid_indices(df)


def test_cone_template_reduction() -> None:
    full = cone_offsets(45.0, 10.0, 10.0, 10.0, max_levels=8, reduce_template=False)
    reduced = cone_offsets(45.0, 10.0, 10.0, 10.0, max_levels=8, reduce_template=True)
    assert len(reduced) < len(full), "reduced template should be smaller than the full cone"
    print(f"  cone template: {len(full)} offsets -> {len(reduced)} after reduction")


def test_destination_and_cutoff() -> None:
    cutoff = marginal_cutoff_grades(ECONOMICS, 1.0, rock_density=1.8)["SN"]
    df = pd.DataFrame(
        {
            "x": [0.0, 10.0], "y": [0.0, 0.0], "z": [0.0, 0.0],
            "SN_PCT": [cutoff * 2.0, cutoff * 0.5],
            "dx": 10.0, "dy": 10.0, "dz": 5.0, "density": 1.8,
        }
    )
    valued = value_blocks(df, ECONOMICS)
    assert valued.loc[0, "destination"] == ORE, "a block well above cutoff must go to the mill"
    assert valued.loc[1, "destination"] == WASTE, "a block well below cutoff must be treated as waste"
    assert valued.loc[1, "value"] == valued.loc[1, "value_waste"], "waste blocks must not carry processing cost"
    print(f"  marginal cutoff {cutoff:.4f}% — destinations assigned correctly")


def test_product_margin_nets_off_product_processing() -> None:
    """A product's own processing cost comes off its price, not out of the
    grade: charging it as an ore cost invents a cutoff that is not there."""
    zircon, ilmenite = SANDS.products
    assert product_margin(SANDS, zircon) == 1400.0 - 250.0 / 1.6 - 900.0
    assert product_margin(SANDS, ilmenite) == 280.0 - 250.0 / 1.6
    assert marginal_cutoff_grades(SANDS, 1.0)["ZIRCON"] == 0.0, (
        "with no ore-level processing cost there is no cutoff grade"
    )
    print(f"  product margins: zircon {product_margin(SANDS, zircon):,.2f}/t, "
          f"ilmenite {product_margin(SANDS, ilmenite):,.2f}/t")


def test_cheap_product_not_priced_as_dear_one() -> None:
    """The whole point of separate products: a block of ilmenite must not
    be worth the same as a block of zircon."""
    df = pd.DataFrame(
        {
            "x": [0.0, 10.0], "y": [0.0, 0.0], "z": [0.0, 0.0],
            "ZR": [5.0, 0.0], "IL": [0.0, 5.0],
            "dx": 10.0, "dy": 10.0, "dz": 1.0, "density": 1.6,
        }
    )
    valued = value_blocks(df, SANDS)
    zircon_block, ilmenite_block = valued.loc[0, "value"], valued.loc[1, "value"]
    assert zircon_block > ilmenite_block, "zircon at 1,400/t must outvalue ilmenite at 280/t"
    print(f"  equal-grade blocks value differently: zircon {zircon_block:,.0f} vs ilmenite {ilmenite_block:,.0f}")


def test_price_units_are_equivalent() -> None:
    """A gold price per troy ounce must value a block exactly as the same
    price expressed per tonne."""
    base = dict(grade_basis="gpt", mining_cost_per_tonne=3.0, processing_cost_per_tonne=15.0)
    per_oz = EconomicsConfig(**base, products=[ProductConfig(name="AU", grade_col="AU", price=2300.0, price_unit="oz",
                                                             plant_recovery=0.9, selling_cost_per_tonne=5.0)])
    per_t = EconomicsConfig(**base, products=[ProductConfig(name="AU", grade_col="AU", price=2300.0 * 32_150.7466,
                                                            plant_recovery=0.9, selling_cost_per_tonne=5.0 * 32_150.7466)])
    df = pd.DataFrame({"x": [0.0], "y": [0.0], "z": [0.0], "AU": [1.2], "dx": 10.0, "dy": 10.0, "dz": 5.0, "density": 2.7})
    a, b = value_blocks(df, per_oz)["value"].iloc[0], value_blocks(df, per_t)["value"].iloc[0]
    assert np.isclose(a, b), (a, b)
    print(f"  gold priced per oz and per t value a 1.2 g/t block identically: {a:,.0f}")


def test_pit_shape_and_nesting() -> None:
    np.random.seed(0)
    blocks = make_toy_block_model()
    arcs = build_precedence(blocks, slope_angle_deg=38.0, max_levels=8)
    factors = [0.5, 0.8, 1.0]
    solved, report, violations = run_nested_shells(blocks, arcs, ECONOMICS, factors)

    in_pit = solved["in_pit"].to_numpy()
    assert in_pit.any(), "expected at least some blocks in the pit"
    assert violations == 0, f"shells must be nested, got {violations} violations"

    top = solved[(solved.bench == solved.bench.max()) & in_pit]
    bottom = solved[(solved.bench == solved.bench.min()) & in_pit]
    assert len(top) >= len(bottom), (
        "pit must be wider at surface than at depth — if this fails, check the precedence cone"
    )

    assert report["blocks"].is_monotonic_increasing, "shell size must grow with revenue factor"
    assert report["strip_ratio"].is_monotonic_increasing, "strip ratio must grow with revenue factor"
    best = report.loc[report["value"].idxmax(), "revenue_factor"]
    assert best == 1.0, f"value at planning price must peak at RF 1.0, peaked at {best}"

    print(f"  {in_pit.sum():,}/{len(solved):,} blocks in pit, {len(top)} wide at surface vs {len(bottom)} at depth")
    print(f"  shells nested across {factors}, value peaks at RF 1.0")


def _assert_feasible(order: np.ndarray, arcs: np.ndarray, in_pit: np.ndarray, label: str) -> None:
    """Every slope predecessor of a mined block must come earlier in the order."""
    position = np.full(len(in_pit), -1)
    position[order] = np.arange(len(order))
    inside = in_pit[arcs[:, 0]]
    block, pred = arcs[inside, 0], arcs[inside, 1]
    assert (position[pred] >= 0).all(), f"{label}: a predecessor of a mined block is not mined"
    assert (position[pred] < position[block]).all(), f"{label}: a block is mined before its predecessor"


def test_standard_planning_workflow() -> None:
    """Nested shells -> discounted pit by pit -> final pit -> pushbacks ->
    specified schedule, with every sequence precedence-feasible."""
    np.random.seed(0)
    blocks = make_toy_block_model()
    arcs = build_precedence(blocks, slope_angle_deg=38.0)
    factors = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    solved, report, _ = run_nested_shells(blocks, arcs, ECONOMICS, factors)

    capacity = 250_000.0
    table = pit_by_pit_npv(solved, report, capacity, None, 0.10, "tonnes")
    assert (table["npv_best"] >= table["npv_worst"] - 1e-6).all(), "best case must never trail worst case"
    final, reason = select_final_pit(table, "average", 0.01)
    assert table["revenue_factor"].iloc[final - 1] <= 1.0, "final pit cannot exceed the RF 1.0 shell"

    shell = solved["shell"].to_numpy()
    in_pit = (shell > 0) & (shell <= final)
    boundaries, candidates = select_pushbacks(solved, final, capacity, None, 0.10, "tonnes", max_pushbacks=3, lag_benches=2)
    assert boundaries[-1] == final and candidates["selected"].sum() == 1
    pushback = pushback_labels(boundaries, shell)

    _assert_feasible(specified_sequence(solved, in_pit, pushback, 2), arcs, in_pit, "specified case")

    # The plan must not depend on the row order of the input file.
    from pitopt.core.schedule import schedule_production, schedule_summary
    planned = solved.assign(pushback=pushback)
    npv = schedule_summary(schedule_production(
        planned, in_pit, capacity, None, 0.10, order=specified_sequence(planned, in_pit, pushback, 2)))["npv"]
    shuffled = planned.sample(frac=1.0, random_state=3)
    mask = shuffled.index.isin(planned.index[in_pit])
    order = specified_sequence(shuffled, mask, shuffled["pushback"].to_numpy(), 2)
    npv_shuffled = schedule_summary(schedule_production(shuffled, mask, capacity, None, 0.10, order=order))["npv"]
    assert np.isclose(npv, npv_shuffled), f"NPV depends on row order: {npv} vs {npv_shuffled}"
    order, _, _ = strip_sequence(solved, in_pit, width=30.0, face_angle_deg=38.0)
    _assert_feasible(order, arcs, in_pit, "strip sequence")
    print(f"  final pit RF {table['revenue_factor'].iloc[final - 1]:.2f} ({reason}); "
          f"{len(boundaries)} pushbacks; specified and strip sequences feasible")


def main() -> None:
    print("Running pitopt smoke tests...")
    test_cone_template_reduction()
    test_destination_and_cutoff()
    test_product_margin_nets_off_product_processing()
    test_cheap_product_not_priced_as_dear_one()
    test_price_units_are_equivalent()
    test_pit_shape_and_nesting()
    test_standard_planning_workflow()
    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()


def test_grid_indices_are_exact_for_any_origin() -> None:
    """Centres at half-block offsets from zero, and centres off the zero lattice, must index one-to-one
    and map back to their true coordinates (this used to merge neighbouring columns / shift the surface)."""
    from pitopt.core.pitsurface import pit_surface_grid

    for x0, y0, z0 in ((1010.0, 5010.0, 195.0), (650227.9, 9698150.0, 11.77), (0.0, 0.0, 0.0)):
        dx, dy, dz = 20.0, 20.0, 10.0
        gx, gy, gz = np.meshgrid(x0 + dx * np.arange(7), y0 + dy * np.arange(6), z0 + dz * np.arange(4), indexing="ij")
        df = add_grid_indices(pd.DataFrame({"x": gx.ravel(), "y": gy.ravel(), "z": gz.ravel(), "dx": dx, "dy": dy, "dz": dz}))
        assert df["gi"].nunique() == 7 and df["gj"].nunique() == 6 and df["bench"].nunique() == 4
        assert np.array_equal(np.diff(np.sort(df["gi"].unique())), np.ones(6))
        xs, ys, _ = pit_surface_grid(df, np.zeros(len(df), dtype=bool), None)
        assert np.allclose(xs, x0 + dx * np.arange(7)) and np.allclose(ys, y0 + dy * np.arange(6))


def test_model_too_large_is_refused_before_it_runs(monkeypatch) -> None:
    import pytest

    from pitopt.core import limits
    from pitopt.core.limits import ModelTooLarge, check_solver_memory, estimate_solver_bytes

    assert estimate_solver_bytes(1_000, 20_000) > 20_000 * 500
    check_solver_memory(10_000, 200_000, available=16 * 2**30)                    # fits
    with pytest.raises(ModelTooLarge, match="reblock"):
        check_solver_memory(3_600_000, 3_600_000 * 45, available=9 * 2**30)       # the 3.6 M-block case on a 9 GB machine
    # calibration: the 230,164-block run peaked at 9.5 GB; the estimate must not fall below what was measured
    assert estimate_solver_bytes(230_164, 15_106_074) / 1e9 >= 9.4
    monkeypatch.setattr(limits, "available_memory_bytes", lambda: None)
    assert check_solver_memory(3_600_000, 3_600_000 * 45)["need_gb"] > 100          # memory unknown: estimate only
