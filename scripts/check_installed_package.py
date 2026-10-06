"""Smoke-test an installed wheel, outside the source checkout.

CI invokes this with the clean venv's Python and -I. Only standard-library
test helpers are used; the installed application provides its dependencies.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    import pitopt
    from pitopt.ui.server import STATIC, App, UIServer, make_handler

    installed = Path(pitopt.__file__).resolve()
    if source == installed or source in installed.parents:
        raise AssertionError("Smoke test imported the checkout instead of the installed wheel")
    expected = {p.relative_to(source / "pitopt/ui/static").as_posix(): p.read_bytes()
                for p in (source / "pitopt/ui/static").rglob("*") if p.is_file()}
    actual = {p.relative_to(STATIC).as_posix(): p.read_bytes() for p in STATIC.rglob("*") if p.is_file()}
    if actual != expected:
        raise AssertionError("Installed UI differs from source: missing, changed or extra assets")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        shutil.copytree(source / "projects/example_tin", root / "projects/example_tin")
        for command in (["--help"], ["validate", "--config", str(root / "projects/example_tin/project.yaml")]):
            subprocess.run([sys.executable, "-I", "-m", "pitopt", *command], cwd=root, check=True)
        server = UIServer(("127.0.0.1", 0), make_handler(App(root)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            for name, data in actual.items():
                route = "/" if name == "index.html" else "/static/" + name
                with urllib.request.urlopen(base + route, timeout=10) as response:
                    if response.read() != data:
                        raise AssertionError("Installed server changed asset: " + name)
            with urllib.request.urlopen(base + "/static/vendor/plotly.min.js", timeout=10) as response:
                if len(response.read()) < 100_000:
                    raise AssertionError("Installed Plotly bundle is missing")
            try:
                urllib.request.urlopen(urllib.request.Request(base + "/", headers={"Host": "external.example"}), timeout=10)
            except urllib.error.HTTPError as error:
                if error.code != 403:
                    raise
            else:
                raise AssertionError("Installed local server accepted an unrelated Host")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    print(json.dumps({"installed_from": str(installed), "ui_files": len(actual),
                      "index_sha256": hashlib.sha256(actual["index.html"]).hexdigest()}))
    print("PASS: installed wheel, CLI, tin input validation, every UI asset, Plotly and local Host guard")


if __name__ == "__main__":
    main()
