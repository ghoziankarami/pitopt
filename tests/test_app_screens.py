"""
Every screen of the app, in a real browser, on every commodity the suite runs: tin (per cent by mass), gold
(g/t, per ounce), rare earths (ppm, per kilogram, classes and domains) and mineral sands (volume per cent,
strips). Each screen must load without a script error, and the numbers the summary shows must be the numbers
the engine wrote — read back off the page and parsed, not assumed from the template.

Needs Playwright with Chromium; skipped where it is not installed.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

sync_api = pytest.importorskip("playwright.sync_api")

from pitopt.ui.server import App, make_handler  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".pytest_runs"
PROJECTS = ["example_tin", "gold_oz", "ree_ppm", "sands_vol"]
SCREENS = ["ringkasan", "pit-by-pit", "pit-final", "pushback", "rencana", "desain", "blok", "sensitivitas", "3d",
           "parameter", "data", "qa", "jalankan", "bandingkan", "ekspor", "unggah"]


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    if not all((RUNS / p).exists() for p in PROJECTS):
        pytest.skip("generated runs missing")
    root = tmp_path_factory.mktemp("app")
    for name in PROJECTS:
        target = root / "projects" / name
        source = ROOT / "projects/example_tin" if name == "example_tin" else RUNS / "_src" / name
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("outputs", "out"))
        yml = target / "project.yaml"
        raw = yaml.safe_load(yml.read_text())
        raw.setdefault("output", {})["directory"] = "out"
        yml.write_text(yaml.safe_dump(raw))
        shutil.copytree(RUNS / name, target / "out")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", root
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(args=["--disable-gpu", "--disable-dev-shm-usage"])
        except Exception as exc:                                  # noqa: BLE001 — no browser installed here
            pytest.skip(f"chromium unavailable: {exc}")
        yield b
        b.close()


def open_project(browser, url: str, project: str):
    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(45000)
    pg.problems = []
    pg.on("pageerror", lambda e: pg.problems.append(f"pageerror: {e}"))
    pg.on("console", lambda m: pg.problems.append(f"console: {m.text}") if m.type == "error" else None)
    pg.add_init_script(f"localStorage.setItem('pitopt-scenario-v2','{project}/project'); localStorage.setItem('pitopt-lang','id')")
    pg.goto(url)
    pg.wait_for_selector("nav.side")
    return pg


def number(text: str) -> float:
    """An Indonesian-formatted number off the page: '1.234,56' -> 1234.56, '−3,5' -> -3.5."""
    t = text.strip().replace("−", "-").replace(".", "").replace(",", ".")
    return float(re.search(r"-?\d+(?:\.\d+)?", t).group())


@pytest.mark.parametrize("project", PROJECTS)
def test_every_screen_loads_without_a_script_error(browser, site, project):
    url, _ = site
    pg = open_project(browser, url, project)
    try:
        for screen in SCREENS:
            pg.evaluate(f"location.hash = '#/{screen}'")
            pg.wait_for_selector("main h1")
            pg.wait_for_timeout(500)
            assert pg.inner_text("main h1").strip(), f"{project}/{screen} has no title"
            assert "Gagal" not in pg.inner_text("main h1"), f"{project}/{screen}"
        assert not pg.problems, f"{project}: {pg.problems}"
    finally:
        pg.close()


@pytest.mark.parametrize("project", PROJECTS)
def test_the_summary_shows_exactly_what_the_engine_computed(browser, site, project):
    url, root = site
    doc = json.loads(next((root / "projects" / project / "out").glob("*_results.json")).read_text())
    k = doc["kpis"]
    pg = open_project(browser, url, project)
    try:
        pg.evaluate("location.hash = '#/ringkasan'")
        pg.wait_for_selector(".kpi")
        cards = pg.evaluate("""[...document.querySelectorAll('.kpi')].map(c => ({
            k: c.querySelector('.k').textContent.trim(),
            v: [...c.querySelector('.v').childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim()}))""")
        shown = {c["k"]: c["v"] for c in cards}
        expected = {"Nilai tak terdiskonto": k["value_undiscounted"] / 1e6, "NPV rencana": k["npv_plan"] / 1e6,
                    "NPV best case": k["npv_best"] / 1e6, "NPV worst case": k["npv_worst"] / 1e6,
                    "Rock": k["rock_t"] / 1e6, "Umpan (ore)": k["ore_t"] / 1e6, "Waste": k["waste_t"] / 1e6,
                    "Kedalaman maks": k["max_depth_m"]}
        for label, value in expected.items():
            assert label in shown, f"{project}: no '{label}' card"
            decimals = 0 if label == "Kedalaman maks" else 2
            assert number(shown[label]) == pytest.approx(round(value, decimals), abs=10 ** -decimals / 2 + 1e-9), \
                f"{project} {label}: page {shown[label]!r} vs engine {value}"
        for name, product in k["products"].items():
            if name in shown:
                assert number(shown[name]) == pytest.approx(round(product["tonnes"]), abs=0.5), f"{project} {name}"
        assert not pg.problems, pg.problems
    finally:
        pg.close()


@pytest.mark.parametrize("project", PROJECTS)
def test_the_pit_by_pit_table_lists_every_shell(browser, site, project):
    url, root = site
    doc = json.loads(next((root / "projects" / project / "out").glob("*_results.json")).read_text())
    pg = open_project(browser, url, project)
    try:
        pg.evaluate("location.hash = '#/pit-by-pit'")
        pg.wait_for_selector("table.t")
        pg.wait_for_timeout(400)
        text = pg.inner_text("main")
        for row in doc["pit_by_pit"]:
            assert f"{row['rf']:.2f}".replace(".", ",") in text, f"{project}: RF {row['rf']} missing"
        assert not pg.problems, pg.problems
    finally:
        pg.close()
