"""
The design as the UI drives it: state, Generate with progress, Cancel, the
finished geometry, a block slice, a section and the export, all over HTTP.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from pitopt.ui.server import App, make_handler

ROOT = Path(__file__).resolve().parents[1]
PROJECT, SCENARIO = "example_tin", "project"
PARAMS = {"berm.method": "slope", "ramp.width_m": 15.0}


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    """A server over a temporary project root holding the example and a finished run of it."""
    src = ROOT / ".pytest_runs/example_tin"
    if not src.exists():
        pytest.skip("no generated example run")
    root = tmp_path_factory.mktemp("design_api")
    project = root / "projects" / PROJECT
    shutil.copytree(ROOT / "projects/example_tin", project, ignore=shutil.ignore_patterns("outputs"))
    raw = yaml.safe_load((project / "project.yaml").read_text())
    raw["output"] = {"directory": "outputs"}
    (project / "project.yaml").write_text(yaml.safe_dump(raw))
    shutil.copytree(src, project / "outputs")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path: str, body: dict | None = None, expect: int = 200):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json", "X-PitOpt": "1", "Origin": base})
        try:
            with urllib.request.urlopen(req) as res:
                return json.load(res)
        except urllib.error.HTTPError as err:
            assert err.code == expect, f"{path}: {err.code} {err.read()[:200]}"
            return json.load(err) if err.headers.get("Content-Type", "").startswith("application/json") else None

    call.root, call.outputs = root, project / "outputs"
    yield call
    server.shutdown()


def wait_done(api, job_id: str, timeout: float = 60.0) -> dict:
    end, events = time.time() + timeout, []
    while time.time() < end:
        snap = api(f"/api/design/job?id={job_id}&since={len(events)}")
        events += snap["events"]
        if snap["status"] != "running":
            return {**snap, "all_events": events}
        time.sleep(0.05)
    raise AssertionError("design job did not finish")


def generate(api, params=PARAMS) -> dict:
    job = api("/api/design/run", {"project": PROJECT, "scenario": SCENARIO, "params": params})["job"]
    return wait_done(api, job)


def test_state_before_any_design_describes_the_scenario_and_says_there_is_no_design(api):
    s = api("/api/design/state", {"project": PROJECT, "scenario": SCENARIO, "params": PARAMS})
    assert s["has_results"] and s["blocks_ready"] and s["session"] is None
    assert s["final_pit"]["shell"] > 0 and s["slope_deg"] > 0
    assert s["sectors"][0]["berm_width"] > 0 and s["params"]["detail"]["ramp"]["width_m"] == 15.0
    assert api("/api/design/result?project=example_tin&scenario=project", expect=404)["error"]


def test_a_scenario_without_results_says_so_instead_of_failing(api):
    (api.root / "projects" / "empty").mkdir()
    (api.root / "projects" / "empty" / "project.yaml").write_text(
        "project: {name: empty, title: E}\nblock_model: {path: x.csv}\noutput: {directory: outputs}\n")
    assert api("/api/design/state", {"project": "empty", "scenario": "project"}) == {"has_results": False}


def test_a_bad_parameter_is_refused_readably_before_any_work_starts(api):
    err = api("/api/design/run", {"project": PROJECT, "scenario": SCENARIO, "params": {"anchor": "sideways"}}, expect=400)
    assert "anchor" in err["error"]
    err = api("/api/design/run", {"project": PROJECT, "scenario": SCENARIO, "params": {"berm.method": "ryan"}}, expect=400)
    assert "geotechnical report" in err["error"]


def test_generate_streams_each_bench_as_it_finishes_and_then_the_stages(api):
    snap = generate(api)
    assert snap["status"] == "done" and snap["fraction"] == 1.0
    events = snap["all_events"]
    benches = [e for e in events if e["type"] == "bench_done"]
    assert len(benches) == benches[0]["total"] and [e["done"] for e in benches] == list(range(1, len(benches) + 1))
    assert all(e["crest"] and e["toe"] and e["crest"][0]["o"] for e in benches)
    stages = [e["stage"] for e in events if e["type"] == "stage"]
    assert stages == ["anchor", "benches", "ramp", "reconcile", "validate"]
    order = [events.index(next(e for e in events if e.get("stage") == s)) for s in ("benches", "ramp")]
    assert order == sorted(order) and events.index(benches[-1]) < events.index(next(e for e in events if e.get("stage") == "ramp"))


def test_asking_again_with_nothing_changed_returns_the_design_at_once(api):
    generate(api)
    snap = generate(api)
    assert snap["status"] == "done" and [e["type"] for e in snap["all_events"]] == ["cached"]
    changed = generate(api, {**PARAMS, "ramp.width_m": 20.0})
    assert any(e["type"] == "bench_done" for e in changed["all_events"])            # a changed parameter rebuilds


def test_the_finished_design_carries_geometry_the_screens_draw(api):
    generate(api)
    r = api("/api/design/result?project=example_tin&scenario=project")
    n = len(r["benches"])
    assert n > 0 and r["ramp"]["x"] and len(r["ramp"]["edges"]["left"]) == len(r["ramp"]["x"])
    assert r["document"]["provenance"]["signedByCP"] is False and r["document"]["reconciliation"]["residual"]
    assert r["sector_lines"] and r["centre"] and r["classes"]["configured"] is False
    state = api("/api/design/state", {"project": PROJECT, "scenario": SCENARIO, "params": PARAMS})
    assert state["session"]["current"] is True and set(state["session"]["status"]) >= {"ira", "osa", "ramp"}
    stale = api("/api/design/state", {"project": PROJECT, "scenario": SCENARIO, "params": {**PARAMS, "ramp.width_m": 30.0}})
    assert stale["session"]["current"] is False                                     # edited parameters no longer match the design


def test_a_plan_slice_classifies_every_block_against_the_shell_and_the_design(api):
    generate(api)
    plan = api("/api/design/plan?project=example_tin&scenario=project&rl=-7.5")
    n = len(plan["x"])
    assert n > 0 and all(len(plan[k]) == n for k in ("y", "grade", "cls", "ore", "in_shell", "in_design", "value", "cause"))
    assert plan["shell"] and plan["design"] and plan["levels"] == sorted(plan["levels"])
    assert set(plan["cause"]) <= {"batter", "min_width", "ramp", ""}
    assert sum(plan["in_shell"]) > 0 and sum(plan["in_design"]) > 0


def test_a_section_gives_the_walls_the_blocks_and_where_the_road_crosses(api):
    generate(api)
    plan = api("/api/design/plan?project=example_tin&scenario=project&rl=-7.5")
    xs, ys = plan["x"], plan["y"]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    sec = api(f"/api/design/section?project=example_tin&scenario=project&x1={cx - 150}&y1={cy}&x2={cx + 150}&y2={cy}")
    assert sec["length"] == pytest.approx(300.0) and sec["rings"] and sec["blocks"]["d"] and sec["shell"]
    crest = [r for r in sec["rings"] if r["kind"] == "crest" and r["spans"]]
    assert crest and all(0 <= a < b <= 300 for r in crest for a, b in r["spans"])
    assert len(sec["blocks"]["d"]) == len(sec["blocks"]["mined"]) == len(sec["blocks"]["rl"])


def test_export_writes_what_was_asked_and_always_the_json_with_the_provenance(api):
    generate(api)
    files = api("/api/design/export", {"project": PROJECT, "scenario": SCENARIO, "kinds": ["sectors"]})["files"]
    kinds = {f["kind"] for f in files}
    assert kinds == {"design_sectors_dxf", "design_detail_json"} and all(f["bytes"] > 0 for f in files)
    everything = api("/api/design/export", {"project": PROJECT, "scenario": SCENARIO})["files"]
    assert {"design_benches_dxf", "design_ramp_dxf", "design_reconciliation_xlsx"} <= {f["kind"] for f in everything}
    assert all((api.outputs / f["name"]).exists() for f in everything)


def test_cancelling_a_generate_keeps_the_design_already_on_screen(api):
    generate(api)
    before = api("/api/design/result?project=example_tin&scenario=project")["key"]
    job = api("/api/design/run", {"project": PROJECT, "scenario": SCENARIO, "params": {**PARAMS, "ramp.width_m": 22.0}})["job"]
    api("/api/design/cancel", {"id": job})
    snap = wait_done(api, job)
    assert snap["status"] in ("cancelled", "done")                                  # it may have finished before the cancel landed
    after = api("/api/design/result?project=example_tin&scenario=project")["key"]
    assert after == before if snap["status"] == "cancelled" else after != before


def test_a_new_generate_cancels_the_one_still_running(api):
    first = api("/api/design/run", {"project": PROJECT, "scenario": SCENARIO, "params": {**PARAMS, "ramp.width_m": 17.0}})["job"]
    second = api("/api/design/run", {"project": PROJECT, "scenario": SCENARIO, "params": {**PARAMS, "ramp.width_m": 18.0}})["job"]
    assert wait_done(api, second)["status"] == "done"
    assert wait_done(api, first)["status"] in ("cancelled", "done")
