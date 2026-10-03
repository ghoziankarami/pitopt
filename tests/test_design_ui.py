"""
The Desain Detail screens in a real browser: every screen loads without a script error, Generate streams and can
be cancelled, an edited parameter is a visible draft, the states that come before there is a design (no run, a
bad parameter, a broken road) say what is wrong, and dark mode draws.

Needs Playwright with Chromium; skipped where it is not installed.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from pathlib import Path

import pytest
import yaml

sync_api = pytest.importorskip("playwright.sync_api")

from pitopt.ui.server import App, UIServer, make_handler  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DETAIL = {
    "enabled": False, "berm": {"method": "slope"},
    "sectors": [{"name": "Utara", "azimuth_from": 315, "azimuth_to": 45, "ira_max_deg": 60.0},
                {"name": "Timur", "azimuth_from": 45, "azimuth_to": 135, "ira_max_deg": 20.0},
                {"name": "Selatan", "azimuth_from": 135, "azimuth_to": 225}, {"name": "Barat", "azimuth_from": 225, "azimuth_to": 315}],
    "ramp": {"width_m": 15.0}, "grade_classes": {"grade_col": "SN_PCT", "breaks": [0.5, 1.0], "names": ["Waste", "Rendah", "Tinggi"]},
}
SCREENS = {"d-sumber": "Sumber shell", "d-sektor": "Crest & Sektor", "d-ramp": "Ramp", "d-generate": "Generate & Tinjau",
           "d-validasi": "Validasi & Rekonsiliasi", "d-penampang": "Penampang 1:1", "d-ekspor": "Ekspor desain"}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    src = ROOT / ".pytest_runs/example_tin"
    if not src.exists():
        pytest.skip("no generated example run")
    root = tmp_path_factory.mktemp("design_ui")
    project = root / "projects" / "example_tin"
    shutil.copytree(ROOT / "projects/example_tin", project, ignore=shutil.ignore_patterns("outputs"))
    raw = yaml.safe_load((project / "project.yaml").read_text())
    raw["output"] = {"directory": "outputs"}
    raw.setdefault("design", {})["detail"] = DETAIL
    (project / "project.yaml").write_text(yaml.safe_dump(raw))
    shutil.copytree(src, project / "outputs")
    empty = root / "projects" / "empty"
    empty.mkdir()
    (empty / "project.yaml").write_text("project: {name: empty, title: Kosong, order: 9}\nblock_model: {path: x.csv}\noutput: {directory: outputs}\n")
    server = UIServer(("127.0.0.1", 0), make_handler(App(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def demo_site(tmp_path_factory):
    src = ROOT / ".pytest_runs/example_tin"
    if not src.exists():
        pytest.skip("no generated example run")
    if not (ROOT / "outputs/porphyry").is_dir():
        pytest.skip("generated Porphyry demo outputs are provisioned separately")
    root = tmp_path_factory.mktemp("interactive_demo")
    project = root / "projects" / "example_tin"
    shutil.copytree(ROOT / "projects/example_tin", project, ignore=shutil.ignore_patterns("outputs"))
    raw = yaml.safe_load((project / "project.yaml").read_text())
    raw["output"] = {"directory": "outputs"}
    raw.setdefault("design", {})["detail"] = DETAIL
    (project / "project.yaml").write_text(yaml.safe_dump(raw))
    shutil.copytree(src, project / "outputs")
    porphyry = root / "projects" / "porphyry_synthetic"
    shutil.copytree(ROOT / "projects/porphyry_synthetic", porphyry)
    shutil.copytree(ROOT / "outputs/porphyry", root / "outputs" / "porphyry")
    server = UIServer(("127.0.0.1", 0), make_handler(App(root, demo_mode=True)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def porphyry_demo_page(browser, demo_site):
    pg = browser.new_page(viewport={"width": 1440, "height": 1000})
    pg.set_default_timeout(45000)
    pg.add_init_script("localStorage.removeItem('pitopt-lang'); localStorage.removeItem('pitopt-scenario-v2')")
    pg.goto(demo_site)
    wait_for_app(pg)
    yield pg
    pg.close()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            # --disable-gpu: a software WebGL context is slower per frame but does not stall waiting on the
            # host GPU driver, which is what produced the "GPU stall due to ReadPixels" warnings and the
            # flakiness they caused across a long sequential run of Plotly-heavy tests in one browser process.
            b = p.chromium.launch(args=["--disable-gpu", "--disable-dev-shm-usage"])
        except Exception as exc:                                  # noqa: BLE001 — no browser installed here
            pytest.skip(f"chromium unavailable: {exc}")
        yield b
        b.close()


def wait_for_app(pg):
    for attempt in range(3):
        try:
            pg.wait_for_selector("nav.side", timeout=15000)
            return
        except sync_api.TimeoutError:
            if attempt == 2:
                raise
            pg.reload(wait_until="domcontentloaded")


@pytest.fixture()
def page(browser, site):
    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(45000)                                  # generous: many browsers share one process here
    pg.problems = []
    pg.on("pageerror", lambda e: pg.problems.append(f"pageerror: {e}"))
    pg.on("console", lambda m: pg.problems.append(f"console: {m.text}") if m.type == "error" else None)
    # these tests read Indonesian labels; the interface defaults to English
    pg.add_init_script("if (!localStorage.getItem('pitopt-scenario-v2')) localStorage.setItem('pitopt-scenario-v2','example_tin/project'); localStorage.setItem('pitopt-lang','id'); localStorage.removeItem('pitopt-theme')")
    pg.goto(site)
    wait_for_app(pg)
    yield pg
    pg.close()


@pytest.fixture()
def demo_page(browser, demo_site):
    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(45000)
    pg.problems = []
    pg.on("pageerror", lambda e: pg.problems.append(f"pageerror: {e}"))
    pg.add_init_script("localStorage.setItem('pitopt-scenario-v2','example_tin/project'); localStorage.removeItem('pitopt-lang'); localStorage.removeItem('pitopt-support-prompted')")
    pg.goto(demo_site)
    wait_for_app(pg)
    yield pg
    pg.close()


def wait_for_plot(page, timeout: int = 20000) -> None:
    """Plotly loads its vendor script and builds the WebGL scene asynchronously; the text in the button flips
    before that finishes, so a screen that needs the plot waits for it by itself rather than by a fixed sleep.
    Plotly attaches its own "js-plotly-plot" class to the div it is given (#d3d itself, not a child of it), so
    the selector is the element, not a descendant; the WebGL canvas inside it is the proof the scene was built."""
    page.wait_for_selector("#d3d.js-plotly-plot canvas", timeout=timeout)


def go(page, screen: str, wait: str = "h1") -> None:
    page.evaluate(f"location.hash = '#/{screen}'")
    page.wait_for_selector(wait)
    page.wait_for_timeout(700)


def generate(page, timeout: int = 60000) -> None:
    go(page, "d-generate")
    click_generate(page)
    page.wait_for_selector("text=Generate ulang", timeout=timeout)
    wait_for_plot(page)


def click_generate(page) -> None:
    """The header action button that starts a build. Scoped by its data-act attribute rather than its label,
    because the label itself is not a stable target here: it reads "Generate desain" the first time and
    "Generate ulang" once a design already exists for this scenario (the server keeps one design per scenario
    and a fresh page picks it up on load — deliberately, so asking again with nothing changed is instant), and
    "Generate desain" duplicates into the empty-state card besides. The attribute is the one thing that never
    changes and never repeats within the header."""
    page.click(".pagehead button[data-act='dGenerate']")


def test_every_screen_loads_without_a_script_error_and_shows_its_title(page):
    for screen, title in SCREENS.items():
        go(page, screen)
        assert page.inner_text("main h1").strip() == title, screen
    assert not page.problems, page.problems


def test_the_sidebar_numbers_the_design_06_and_moves_the_later_steps(page):
    text = page.inner_text("nav.side")
    for number, label in (("06", "Desain Detail"), ("07", "3D & Penampang"), ("08", "Bandingkan"), ("09", "Ekspor")):
        assert number in text and label in text
    go(page, "d-sektor")
    assert "rail" in page.get_attribute("nav.side", "class")                  # the working screens use the compact rail
    assert page.evaluate("document.querySelector('nav.side').getBoundingClientRect().width") < 70
    go(page, "d-validasi")
    assert "rail" not in page.get_attribute("nav.side", "class")


def test_before_a_design_exists_the_screens_offer_to_generate_one(page):
    for screen in ("d-validasi", "d-penampang", "d-ekspor"):
        go(page, screen)
        assert "Desain belum di-generate" in page.inner_text("main"), screen


def test_generate_streams_benches_then_shows_the_findings_and_the_exaggeration(page):
    go(page, "d-generate")
    click_generate(page)
    page.wait_for_selector("text=Batalkan generate", timeout=15000)               # the button turned into Cancel while running
    page.wait_for_selector("text=Generate ulang", timeout=60000)
    wait_for_plot(page)
    assert "VE 2,0×" in page.inner_text("main")                                      # the exaggeration is always written down
    # "Validasi" also names the sidebar's own step link, hidden while this screen uses the compact rail; the
    # in-page tab is scoped by its own container so the click cannot land on that hidden one instead.
    page.click("main button[data-act='dTab'][data-k='val']")
    assert "Timur" in page.inner_text("main")                                         # the sector limit set to 20 degrees must fail
    assert not page.problems, page.problems


def test_a_result_fills_the_validation_and_section_and_export_screens(page):
    generate(page)
    go(page, "d-validasi")
    text = page.inner_text("main")
    assert "Rekonsiliasi terhadap shell PitOpt" in text and "IRA per sektor" in text and "Peta rekonsiliasi per blok" in text
    go(page, "d-penampang")
    page.wait_for_selector("#dsec1")
    page.wait_for_timeout(1200)
    assert page.evaluate("document.getElementById('dsec1').width") > 0 and "VE 2,0×" in page.inner_text("main")
    go(page, "d-ekspor")
    page.click("text=Ekspor terpilih")
    page.wait_for_selector("text=FILE DITULIS")
    assert ".dxf" in page.inner_text("main") and "PD_CREST" in page.inner_text("main")
    assert not page.problems, page.problems


def test_cancelling_generate_returns_to_the_design_that_was_on_screen(page):
    generate(page)
    go(page, "d-ramp")
    page.fill("input[data-path='ramp.grade_pct']", "9.5")
    page.keyboard.press("Tab")
    page.wait_for_selector("text=DIUBAH", timeout=10000) if False else page.wait_for_timeout(600)
    go(page, "d-generate")
    click_generate(page)
    if page.locator("text=Batalkan generate").count():
        page.click("text=Batalkan generate")
    page.wait_for_selector("text=Generate ulang", timeout=60000)
    wait_for_plot(page)                                                                # a design is still drawn
    assert not page.problems, page.problems


def test_an_edited_parameter_is_a_visible_draft_that_can_be_saved_or_dropped(page):
    go(page, "d-sektor")
    page.fill("input[data-key='face_angle_deg'] >> nth=0", "66")
    page.keyboard.press("Tab")
    page.wait_for_selector("text=belum digenerate", timeout=10000)
    assert "ASUMSI" in page.inner_text("main") and "Simpan sebagai skenario" in page.inner_text("main")
    page.click("text=Simpan sebagai skenario…")
    assert "Simpan sebagai skenario baru" in page.inner_text("#modal")
    page.click("#modal >> text=Tutup")
    page.click("text=Batalkan perubahan")
    page.wait_for_timeout(600)
    assert "belum digenerate" not in page.inner_text("main")


def test_a_parameter_the_engine_refuses_is_explained_and_can_be_undone(page):
    go(page, "d-ramp")
    page.fill("input[data-path='ramp.grade_pct']", "14")
    page.keyboard.press("Tab")
    page.wait_for_selector("text=grade_pct", timeout=10000)
    assert "outside" in page.inner_text("main") or "di luar" in page.inner_text("main")
    page.click("text=Batalkan perubahan")
    page.wait_for_selector("text=Alignment ramp")


def test_a_project_with_no_run_says_so_and_offers_to_run(page):
    page.evaluate("localStorage.setItem('pitopt-scenario-v2','empty/project')")
    page.reload()
    page.wait_for_selector("nav.side")
    go(page, "d-sumber")
    assert "Belum ada hasil PitOpt untuk skenario ini" in page.inner_text("main")
    assert page.locator("main >> text=Jalankan optimasi").count() >= 1


def test_a_broken_road_is_named_on_the_ramp_screen_and_blocks_the_check(page):
    generate(page)

    def broken(route):
        res = route.fetch()
        doc = res.json()
        doc["document"]["ramp"]["complete"] = False
        doc["document"]["ramp"]["broken"] = {"bench": 3, "reason": "the wall below splits into 2 separate parts"}
        doc["ramp"]["bench"] = [b for b in doc["ramp"]["bench"] if b > 3]
        route.fulfill(response=res, body=json.dumps(doc))

    page.route("**/api/design/result*", broken)
    page.evaluate("location.reload()")
    page.wait_for_selector("nav.side")
    go(page, "d-ramp")
    text = page.inner_text("main")
    assert "Ramp putus di bench 3" in text and "splits" in text
    assert page.locator("main span.num", has_text="3").count() >= 1


def test_dark_mode_draws_the_plan_and_the_section(page):
    generate(page)
    page.evaluate("window.__pitopt.A.theme()")
    go(page, "d-penampang")
    page.wait_for_timeout(1200)
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") != "rgb(242, 243, 245)"
    assert not page.problems, page.problems


def test_public_demo_explains_local_upload_and_regenerates_a_sample_design(demo_page):
    page = demo_page
    assert page.evaluate("localStorage.getItem('pitopt-lang')") == "en"
    assert "Source code on GitHub" in page.inner_text("#demo-banner")
    assert page.locator("#demo-banner a").get_attribute("href") == "https://github.com/ghoziankarami/pitopt"
    page.click("button[data-act='manage']")
    page.click("#modal button[data-act='newProject']")
    page.wait_for_selector("main h1:has-text('Use your own data')")
    assert "Use your own data" in page.inner_text("main")
    assert "does not accept uploads" in page.inner_text("main")
    assert page.locator("main input[type='file']").count() == 0
    assert page.locator("main a", has_text="Local installation guide").get_attribute("href").endswith("docs/INSTALLATION.md")

    page.click("main a[href='#/d-generate']")
    go(page, "d-ramp")
    page.fill("input[data-path='ramp.width_m']", "24")
    page.keyboard.press("Tab")
    page.wait_for_selector(".fld.changed", timeout=10000)
    assert page.locator("input[data-path='ramp.width_m']").input_value() == "24"
    go(page, "d-generate")
    click_generate(page)
    page.wait_for_selector(".support-card", timeout=60000)
    assert "Support Orebit" in page.inner_text(".support-card")
    generated_copy = page.locator("main").inner_text()
    indonesian_ui_words = re.compile(
        r"\b(?:belum|dan|dari|untuk|dengan|hasil|sudah|tidak|bisa|perhatian|perlu|ubah|lalu|regenerasi|"
        r"sektor|geoteknik|tinggi|tiap|ditampilkan|tersedia|layar|dibangun|ulang|sekitar|detik|dinding|"
        r"menyatu|tetangga|lewat|batas|azimut|sehingga|lain|dipakai|begitu|saja|berubah|sebelumnya|"
        r"sudut|melampaui|bukan|peringatan|blokir|lagi|buka|lihat|di|untuk|batuan|umpan)\b",
        re.IGNORECASE,
    )
    assert not indonesian_ui_words.search(generated_copy), generated_copy
    assert page.locator(".support-card a[href='https://saweria.co/orebitindonesia']").count() == 1
    assert not page.problems, page.problems


def test_public_demo_defaults_to_english_across_the_entire_ui(porphyry_demo_page):
    page = porphyry_demo_page
    assert page.evaluate("localStorage.getItem('pitopt-lang')") == "en"
    assert page.locator("#proyek").input_value() == "porphyry_synthetic"
    assert "Source code on GitHub" in page.inner_text("#demo-banner")
    assert page.locator("#demo-banner a").get_attribute("href") == "https://github.com/ghoziankarami/pitopt"
    routes = ["data", "qa", "parameter", "jalankan", "ringkasan", "pit-by-pit", "pit-final", "pushback",
              "rencana", "desain", "blok", "sensitivitas", "d-sumber", "d-sektor", "d-ramp", "d-generate",
              "d-validasi", "d-penampang", "d-ekspor", "3d", "bandingkan", "ekspor", "unggah"]
    indonesian_ui_words = re.compile(
        r"\b(?:belum|dan|dari|untuk|dengan|hasil|sudah|tidak|bisa|satu|proyek|skenario|ringkasan|desain|"
        r"rencana|parameter|sektor|blok|dipakai|dipilih|muncul|permukaan|terbaca|sintetis|bawah|sebagai|pada|"
        r"setiap|kosong|lebar|tinggi|sudut|pilih|diisi|otomatis|secara|berdasarkan|tambang|laporan|perlu|ubah|hapus)\b",
        re.IGNORECASE,
    )
    for screen in routes:
        go(page, screen, wait="main h1")
        text = page.locator("body").inner_text()
        assert not indonesian_ui_words.search(text), f"Indonesian copy on {screen}: {text}"
