"""Independent whole-block capacity and cash timing examples."""
import numpy as np
import pandas as pd
import pytest

from pitopt.core.schedule import schedule_production


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
