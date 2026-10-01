"""UI server: read endpoints, path safety, override application."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from pitopt.ui.server import App, make_handler

ROOT = Path(__file__).resolve().parents[1]


def test_apply_overrides_by_product_name():
    raw = {"economics": {"products": [{"name": "SN", "price": 1.0}]}, "slope": {"overall_angle_deg": 45}}
    out = App._apply(raw, {"economics.products.SN.price": 2.0, "slope.overall_angle_deg": 30})
    assert out["economics"]["products"][0]["price"] == 2.0 and out["slope"]["overall_angle_deg"] == 30
    assert raw["economics"]["products"][0]["price"] == 1.0          # original untouched
    with pytest.raises(ValueError):
        App._apply(raw, {"economics.products.NOPE.price": 1})


def test_inside_rejects_outside_paths():
    app = App(ROOT)
    with pytest.raises(PermissionError):
        app._inside(Path("/etc/passwd"))


def test_projects_endpoint():
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/projects"))
        assert any(p["id"] == "example_tin" for p in data)
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/download?project=example_tin&scenario=project&file=../../etc/passwd")
    finally:
        server.shutdown()


def _mini_root(tmp_path):
    for name, out in (("a", "../../outputs/shared"), ("b", "../../outputs/shared"), ("c", "../../outputs/own_c")):
        folder = tmp_path / "projects" / name
        folder.mkdir(parents=True)
        (folder / "project.yaml").write_text(
            f"project: {{name: {name}, title: T{name}, scenario: S}}\nblock_model: {{path: x.csv}}\noutput: {{directory: {out}}}\n")
        (tmp_path / out.replace("../../", "")).mkdir(parents=True, exist_ok=True)
        (tmp_path / out.replace("../../", "") / f"{name}_results.json").write_text("{}")
    return App(tmp_path)


def test_rename_changes_title_only(tmp_path):
    app = _mini_root(tmp_path)
    app.rename("a", None, "Baru")
    assert next(p for p in app.list_projects() if p["id"] == "a")["title"] == "Baru"
    assert (tmp_path / "projects" / "a").exists()
    with pytest.raises(ValueError):
        app.rename("a", None, "  ")


def test_delete_needs_exact_confirmation(tmp_path):
    app = _mini_root(tmp_path)
    with pytest.raises(ValueError):
        app.delete("c", None, "nope")
    assert (tmp_path / "projects" / "c").exists()


def test_delete_project_removes_its_outputs_but_not_shared_ones(tmp_path):
    app = _mini_root(tmp_path)
    app.delete("c", None, "c")
    assert not (tmp_path / "projects" / "c").exists() and not (tmp_path / "outputs" / "own_c").exists()
    app.delete("a", None, "a")                       # outputs/shared is still used by project b
    assert not (tmp_path / "projects" / "a").exists() and (tmp_path / "outputs" / "shared").exists()
    assert (tmp_path / "projects" / "b").exists()


def test_delete_refuses_while_running(tmp_path):
    from pitopt.ui.server import Job

    app = _mini_root(tmp_path)
    app.running = Job("c", "project")
    with pytest.raises(ValueError):
        app.delete("c", None, "c")


# ---- the server has no login: other websites must not be able to drive it ----

def _serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def _request(port, path, method="GET", headers=None, body=None):
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    r = conn.getresponse()
    r.read()
    conn.close()
    return r.status


def test_foreign_host_header_is_refused():
    server, port = _serve()
    try:
        assert _request(port, "/api/projects") == 200
        assert _request(port, "/api/projects", headers={"Host": f"evil.example:{port}"}) == 403   # DNS rebinding
    finally:
        server.shutdown()


def test_cross_site_and_headerless_posts_are_refused():
    server, port = _serve()
    try:
        body = json.dumps({"project": "example_tin", "name": "x"})
        own = {"Content-Type": "application/json", "X-PitOpt": "1"}
        assert _request(port, "/api/rename", "POST", {"Content-Type": "text/plain"}, body) == 403          # a form / simple request
        assert _request(port, "/api/rename", "POST", {**own, "Origin": "http://evil.example"}, body) == 403
        assert _request(port, "/api/rename", "POST", {**own, "Sec-Fetch-Site": "cross-site"}, body) == 403
        # our own pages pass the guard (the empty name is then rejected by validation, not by the guard)
        assert _request(port, "/api/rename", "POST", {**own, "Origin": f"http://127.0.0.1:{port}"}, json.dumps({"project": "example_tin", "name": " "})) == 400
    finally:
        server.shutdown()
