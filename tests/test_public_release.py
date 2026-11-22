"""Release regressions: closure edge cases, margins, and bounded demo requests."""
import http.client
import json
import shutil
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
import yaml

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


def get(port, route):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", route)
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


def test_demo_blocks_user_uploads_and_project_creation(demo):
    project = "upload_probe_codex"
    status, body = post(demo, "sample-data", route=f"/api/upload?project={project}&name=blocks.csv")
    assert status == 403 and "demo publik" in body["error"]
    assert not (Path(__file__).resolve().parents[1] / "projects" / project).exists()
    assert post(demo, "{}", route="/api/create-project")[0] == 403


@pytest.fixture
def interactive_demo(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    source_run = repo / ".pytest_runs/example_tin"
    if not source_run.exists():
        pytest.skip("generated synthetic sample run is unavailable")
    root = tmp_path
    project = root / "projects" / "example_tin"
    shutil.copytree(repo / "projects/example_tin", project, ignore=shutil.ignore_patterns("outputs"))
    config_path = project / "project.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["output"] = {"directory": "outputs"}
    config_path.write_text(yaml.safe_dump(config))
    shutil.copytree(source_run, project / "outputs")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(root, demo_mode=True)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], config_path, project / "outputs"
    server.shutdown()
    server.server_close()


def test_demo_allows_sample_design_parameter_changes_in_memory(interactive_demo):
    port, config_path, outputs = interactive_demo
    config_before = config_path.read_bytes()
    outputs_before = sorted(p.name for p in outputs.iterdir())
    payload = {"project": "example_tin", "scenario": "project", "params": {"ramp.width_m": 24.0}}
    status, state = post(port, json.dumps(payload))
    assert status == 200
    assert state["params"]["detail"]["ramp"]["width_m"] == 24.0

    status, body = post(port, json.dumps(payload), route="/api/design/run")
    assert status == 200
    job_id = body["job"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status, job = get(port, f"/api/design/job?id={job_id}")
        assert status == 200
        if job["status"] != "running":
            break
        time.sleep(0.1)
    assert job["status"] == "done", job
    status, result = get(port, "/api/design/result?project=example_tin&scenario=project")
    assert status == 200
    assert result["ramp"]["width"] == 24.0
    assert config_path.read_bytes() == config_before
    assert sorted(p.name for p in outputs.iterdir()) == outputs_before


def test_json_body_limits(demo):
    assert post(demo, "[]")[0] == 400
    assert post(demo, "{}", {"Content-Length": str(256 * 1024 + 1)})[0] == 400


def test_public_release_guard_scripts_present():
    repo = Path(__file__).resolve().parents[1]
    assert (repo / "scripts/check_installed_package.py").is_file()
    assert (repo / ".github/scripts/check_repository_hygiene.py").is_file()



def test_public_root_serves_landing_and_demo_serves_workspace(demo):
    conn = http.client.HTTPConnection("127.0.0.1", demo, timeout=10)
    conn.request("GET", "/")
    landing = conn.getresponse().read().decode()
    conn.request("GET", "/demo")
    workspace = conn.getresponse().read().decode()
    conn.close()
    assert 'href="/demo"' in landing and "PitOpt" in landing
    assert "<script src=" not in landing and "<link rel=\"stylesheet\" href=\"http" not in landing
    assert "/static/js/app.js" in workspace


def test_export_public_release_excludes_internal_agent_files(tmp_path):
    import importlib.util
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("export_public_release", repo / "scripts/export_public_release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for internal in ("AGENTS.md", "CLAUDE.md", "STANDARDS.md", "ops/scripts/agents/wp.py",
                     "docs/PLAN-pitopt.md", "docs/archive/TASKS-done.md", "docs/handover/HANDOVER-pitopt.md"):
        assert mod.is_excluded(internal), internal
    assert not mod.is_excluded("README.md") and not mod.is_excluded("docs/INSTALLATION.md")
    assert not mod.is_excluded("pitopt/ui/static/landing.html")


def test_project_listing_ignores_macos_appledouble_files(tmp_path):
    """A stray `._project.yaml` (tar from macOS) must not break /api/projects."""
    src = Path(__file__).resolve().parents[1] / "projects" / "example_tin"
    dest = tmp_path / "projects" / "example_tin"
    shutil.copytree(src, dest)
    (dest / "._project.yaml").write_bytes(b"\x00\x05\x16\x07" + b"\xa3" * 60)
    projects = App(tmp_path, demo_mode=True).list_projects()
    assert [p["id"] for p in projects] == ["example_tin"]


def test_grids3d_endpoint_is_whole_metres_and_results_omit_grids(tmp_path):
    shutil.copytree(Path(__file__).resolve().parents[1] / "projects", tmp_path / "projects")
    shutil.copytree(Path(__file__).resolve().parents[1] / "outputs", tmp_path / "outputs")
    app = App(tmp_path, demo_mode=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        def get(path):
            c = http.client.HTTPConnection("127.0.0.1", httpd.server_port); c.request("GET", path)
            return json.loads(c.getresponse().read())
        q = "project=example_tin&scenario=project"
        results = get(f"/api/results?{q}")
        assert "grids3d" not in results and results["has_grids3d"] is True
        g = get(f"/api/grids3d?{q}")
        assert all(v is None or isinstance(v, int) for row in g["topo"] for v in row)
    finally:
        httpd.shutdown()
