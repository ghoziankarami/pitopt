# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Orebit (Ghozian Islam Karami)
"""Independent whole-block capacity and cash timing examples."""
import numpy as np
import pandas as pd
import pytest

from pitopt.core.schedule import schedule_design, schedule_production, schedule_summary


def model():
    return pd.DataFrame({'x': [0, 1, 2], 'y': [0, 0, 0], 'bench': [0, 0, 0], 'shell': [1, 1, 1],
                         'destination': [0, 1, 1], 'ore_tonnes': [0, 6, 6], 'rock_tonnes': [8, 6, 6],
                         'volume': [8, 6, 6], 'value': [-8, 60, 60]})


@pytest.mark.parametrize('basis', ['tonnes', 'volume'])
def test_waste_then_ore_obeys_both_capacities_and_actual_cash(basis):
    report = schedule_production(model(), np.ones(3, dtype=bool), 10, total_capacity=10, capacity_basis=basis)
    assert report.period.tolist() == [1, 2, 3]
    assert report.rock_tonnes.tolist() == [8, 6, 6]
    assert report.ore_tonnes.tolist() == [0, 6, 6]
    assert report.cash_flow.tolist() == [-8, 60, 60]
    assert report.attrs['block_period'].tolist() == [1, 2, 3]
    assert report.discounted_cash_flow.sum() == pytest.approx(-8 / 1.1 + 60 / 1.1**2 + 60 / 1.1**3)


def test_plant_capacity_is_not_allowed_one_block_over():
    report = schedule_production(model(), np.ones(3, dtype=bool), 10)
    assert report.ore_tonnes.tolist() == [6, 6]
    assert report.cash_flow.tolist() == [52, 60]


@pytest.mark.parametrize('options', [{'ore_capacity': 5}, {'total_capacity': 7}, {'max_periods': 1},
                                   {'ore_capacity': float('nan')}, {'total_capacity': 0}])
def test_infeasible_schedule_fails_instead_of_reporting_overload(options):
    kwargs = {'ore_capacity': 10, 'total_capacity': 10}
    kwargs.update(options)
    with pytest.raises(ValueError):
        schedule_production(model(), np.ones(3, dtype=bool), **kwargs)


def test_schedule_design_conserves_tonnage_and_respects_precedence():
    """schedule_design schedules in_design blocks (including shell==0 expansion),
    conserving rock/ore/waste/cash and respecting bench-downward precedence."""
    blocks = pd.DataFrame({
        "x": [0.0, 10.0, 0.0, 10.0],
        "y": [0.0, 0.0, 0.0, 0.0],
        "z": [10.0, 10.0, 0.0, 0.0],
        "bench": [1, 1, 0, 0],
        "shell": [1, 0, 1, 0],
        "pushback": [1, 0, 1, 0],
        "destination": [0, 1, 1, 0],
        "ore_tonnes": [0.0, 5.0, 8.0, 0.0],
        "rock_tonnes": [10.0, 5.0, 8.0, 10.0],
        "volume": [4.0, 2.0, 3.2, 4.0],
        "value": [-10.0, 40.0, 80.0, -10.0],
    })
    in_design = np.array([True, True, True, True])
    report = schedule_design(blocks, in_design, ore_capacity=10.0, total_capacity=15.0, discount_rate=0.10)
    summary = schedule_summary(report)

    assert summary["ore_tonnes"] == pytest.approx(13.0)
    assert summary["waste_tonnes"] == pytest.approx(20.0)
    assert summary["volume"] == pytest.approx(13.2)
    assert summary["total_cash_flow"] == pytest.approx(100.0)
    assert summary["npv"] == pytest.approx(report["discounted_cash_flow"].sum())

    bp = report.attrs["block_period"]
    assert len(bp) == 4
    # Bench 0 (lower) must not be mined in an earlier period than bench 1 (upper) at same (x, y)
    assert bp.loc[2] >= bp.loc[0]
    assert bp.loc[3] >= bp.loc[1]


def test_schedule_design_empty_mask_raises():
    with pytest.raises(ValueError):
        schedule_design(model(), np.zeros(3, dtype=bool), ore_capacity=10.0)
