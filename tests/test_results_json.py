"""Unavailable diagnostics remain explicit nulls in strict JSON output."""
import json
from pathlib import Path

from pitopt.config import ProjectConfig
from pitopt.io.results import _derived, _json_safe


def test_unavailable_wall_measurement_does_not_abort_result_export():
    raw = {'walls': {'steepest_wall_deg_over_30m': float('nan')}, 'violations': [0, 0, 0]}
    got = _json_safe(raw)
    assert got['walls']['steepest_wall_deg_over_30m'] is None
    assert got['violations'] == [0, 0, 0]
    json.dumps(got, allow_nan=False)


def test_unprofitable_product_has_unavailable_cutoff_in_strict_json():
    root = Path(__file__).resolve().parents[1]
    cfg = ProjectConfig.from_yaml(str(root / 'projects/example_tin/project.yaml'))
    product = cfg.economics.products[0]
    product.processing_cost_per_tonne = product.price * 2
    got = _derived(cfg)
    assert got['cutoffs'][product.name] is None
    assert got['margins'][product.name] < 0
    json.dumps(got, allow_nan=False)
