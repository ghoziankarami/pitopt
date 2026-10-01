"""Release regressions: closure edge cases, margins, and bounded demo requests."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from pitopt.config import EconomicsConfig, ProductConfig
from pitopt.core.economics import product_margin
from pitopt.core.solver import solve_max_closure
from pitopt.ui.server import App, make_handler


@pytest.mark.parametrize("values,arcs,expected", [
    ([], [], 0), ([3, 2], [], 5), ([-3, -2], [], 0),
    ([0, 0], [], 0), ([5, -3], [[0, 1]], 2), ([2, -3], [[0, 1]], 0),
    ([3, -3], [[0, 1]], 0), ([8, -2], [[0, 1], [1, 0]], 6),
])
def test_closure_edge_cases(values, arcs, expected):
    values = np.array(values, dtype=float)
    chosen = solve_max_closure(values, np.array(arcs, dtype=int))
    assert values[chosen].sum() == expected
    assert all(not chosen[b] or chosen[p] for b, p in arcs)


def test_closure_rejects_nonfinite_values():
    with pytest.raises(ValueError, match="finite"):
        solve_max_closure(np.array([np.nan]), np.empty((0, 2), dtype=int))


def test_margin_charges_product_processing_after_royalty():
    product = ProductConfig(name="CU", grade_col="CU", price=1000, processing_cost_per_tonne=200)
    econ = EconomicsConfig(royalty_rate=0.2, products=[product])
    assert product_margin(econ, product) == 600


@pytest.fixture
def demo():
    root = Path(__file__).resolve().parents[1]
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(root, demo_mode=True)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def post(port, payload, extra_headers=None, route="/api/design/state"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"X-PitOpt": "1", "Content-Type": "application/json", **(extra_headers or {})}
    conn.request("POST", route, payload, headers)
    response = conn.getresponse()
    status, body = response.status, json.loads(response.read())
    conn.close()
    return status, body


def test_demo_refuses_solver_and_nonfinite_parameters(demo):
    assert post(demo, "{}", route="/api/run")[0] == 403
    assert post(demo, '{"project":"example_tin","scenario":"project","params":{"blend_deg":NaN}}')[0] == 400
    assert post(demo, '{"project":"example_tin","scenario":"project","params":{"sectors":[{}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}]}}')[0] == 400
    assert post(demo, '{"project":"example_tin","scenario":"project","params":{"sectors.0.face_angle_deg":0.00001}}')[0] == 400


def test_demo_rejects_unapproved_project_reads(demo):
    conn = http.client.HTTPConnection("127.0.0.1", demo, timeout=10)
    conn.request("GET", "/api/inspect?project=unlisted_project&file=private_blocks.csv")
    response = conn.getresponse()
    assert response.status == 404
    response.read()
    conn.close()


def test_json_body_limits(demo):
    assert post(demo, "[]")[0] == 400
    assert post(demo, "{}", {"Content-Length": str(256 * 1024 + 1)})[0] == 400
