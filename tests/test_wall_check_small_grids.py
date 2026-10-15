# SPDX-License-Identifier: MIT
"""Analytic grid pairs exercise the actual independent wall verifier."""
from types import SimpleNamespace

import pandas as pd
import pytest

from pitopt.config import SlopeConfig
from pitopt.core.precedence import add_grid_indices
from pitopt.core.verify import wall_check


def model(nx, ny, nz=2):
    rows = [dict(x=5+i*10, y=5+j*10, z=5+k*10, dx=10, dy=10, dz=10)
            for i in range(nx) for j in range(ny) for k in range(nz)]
    blocks = add_grid_indices(pd.DataFrame(rows))
    blocks['in_pit'] = True
    return blocks


def config():
    return SimpleNamespace(slope=SlopeConfig(overall_angle_deg=45))


@pytest.mark.parametrize('nx,ny', [(1, 1), (1, 2), (2, 1), (2, 2), (2, 3), (3, 2)])
def test_small_flat_grid_checks_every_actual_ordered_column_pair(nx, ny):
    result = wall_check(config(), model(nx, ny), None, radius_m=120)
    columns = nx * ny
    assert result['pairs_checked'] == columns * (columns - 1)
    assert result['violations'] == 0
    assert result['worst_excess_m'] == 0


@pytest.mark.parametrize('axis', ['x', 'y'])
def test_thin_grid_still_detects_a_real_excessively_steep_wall(axis):
    blocks = model(2, 1, 6) if axis == 'x' else model(1, 2, 6)
    blocks['in_pit'] = (blocks[axis] < 10) | (blocks['z'] > 50)
    result = wall_check(config(), blocks, None, radius_m=120)
    # Two mined floors at0m and50m,10m apart. Existing stepped-wall
    # allowance is10*tan45 +10 +10*tan45 =30m; actual excess is20m.
    assert result['pairs_checked'] == 2
    assert result['violations'] == 1
    assert result['worst_excess_m'] == pytest.approx(20)


@pytest.mark.parametrize('radius,pairs', [(5, 0), (10, 8), (15, 12)])
def test_radius_boundary_keeps_axis_pairs_and_excludes_diagonals(radius, pairs):
    result = wall_check(config(), model(2, 2), None, radius_m=radius)
    assert result['pairs_checked'] == pairs
    assert result['violations'] == 0
