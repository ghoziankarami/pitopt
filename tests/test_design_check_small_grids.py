# SPDX-License-Identifier: MIT
"""Existing finite comparisons remain measured; absent spans stay unavailable."""
import math

import numpy as np
import pytest

from pitopt.core.verify import design_check


@pytest.mark.parametrize('shape', [(1, 1), (1, 2), (2, 1), (2, 2), (3, 8)])
def test_three_bench_angle_is_unavailable_when_no_pair_spans_three_benches(shape):
    result = design_check(np.zeros(shape), cell=1, face_angle_deg=65, overall_angle_deg=45, bench_run=20)
    assert math.isnan(result['steepest_over_3_benches_deg'])
    assert result['three_bench_span_m'] == 60
    if shape == (1, 1):
        assert math.isnan(result['steepest_local_face_deg'])
    else:
        assert result['steepest_local_face_deg'] == 0


@pytest.mark.parametrize('transpose', [False, True])
def test_thin_grid_retains_the_measurable_axis_without_fake_diagonal_pairs(transpose):
    face = np.arange(6, dtype=float).reshape(1, 6) * 2
    if transpose:
        face = face.T
    result = design_check(face, cell=1, face_angle_deg=65, overall_angle_deg=45, bench_run=1)
    expected = math.degrees(math.atan(2))
    assert result['steepest_local_face_deg'] == pytest.approx(expected)
    assert result['steepest_over_3_benches_deg'] == pytest.approx(expected)


def test_unknown_surface_does_not_report_zero_degree_measurements():
    result = design_check(np.full((2, 3), np.nan), cell=1, face_angle_deg=65, overall_angle_deg=45, bench_run=1)
    assert math.isnan(result['steepest_local_face_deg'])
    assert math.isnan(result['steepest_over_3_benches_deg'])


def test_actual_oversteep_face_is_not_hidden_by_the_extent_guard():
    face = np.array([[0., 100.], [0., 100.]])
    result = design_check(face, cell=1, face_angle_deg=65, overall_angle_deg=45, bench_run=.1)
    assert result['steepest_local_face_deg'] == pytest.approx(math.degrees(math.atan(100)))
    assert result['steepest_local_face_deg'] > result['design_face_angle_deg']
