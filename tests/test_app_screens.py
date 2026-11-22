# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Orebit (Ghozian Islam Karami)
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
from pathlib import Path

import pytest
import yaml

sync_api = pytest.importorskip("playwright.sync_api")

from pitopt.ui.server import App, UIServer, make_handler  # noqa: E402

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
    server = UIServer(("127.0.0.1", 0), make_handler(App(root)))
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


def test_quick_pit_estimation_one_screen_flow(browser, tmp_path):
    """1-screen Quick Pit Estimation: sample/CSV -> instant pre-validation & RAM -> run -> KPI & 3D preview."""
    src = ROOT / "projects" / "example_tin"
    if not src.exists():
        pytest.skip("example_tin project missing")
    shutil.copytree(src, tmp_path / "projects" / "example_tin", ignore=shutil.ignore_patterns("outputs", "out"))
    server = UIServer(("127.0.0.1", 0), make_handler(App(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    pg = open_project(browser, url, "example_tin")
    try:
        pg.click("nav.side a[data-go='unggah']")
        pg.wait_for_url("**/#/unggah")
        pg.wait_for_timeout(300)
        pg.wait_for_selector("main h1")
        assert "Estimasi Pit Cepat" in pg.inner_text("main h1")

        # 1. Load sample dataset -> instant pre-validation & RAM estimate
        pg.select_option("#q-sample", "example_tin")
        pg.click("button[data-act='qUseSample']")
        pg.wait_for_selector("button[data-act='qRun']:not([disabled])", timeout=15000)
        pre_text = pg.inner_text("main")
        assert "Estimasi RAM solver" in pre_text
        assert "Kisi reguler" in pre_text

        # 2. Adjust slope angle -> RAM estimate recalculates cleanly
        slope_input = pg.locator("input[data-path='slope_angle']")
        slope_input.fill("42")
        slope_input.dispatch_event("change")
        pg.wait_for_timeout(300)

        # 3. Run optimization on the same 1-screen view -> KPI summary & 3D preview
        pg.click("button[data-act='qRun']")
        pg.wait_for_selector("#quick-plot3d", timeout=90000)
        pg.wait_for_selector(".kpi", timeout=15000)
        assert "#/unggah" in pg.url or pg.evaluate("location.hash") == "#/unggah"

        kpi_text = pg.inner_text("main").lower()
        for label in ("NPV rencana", "Nilai tak terdiskonto", "Rock", "Umpan (ore)", "Waste", "Kedalaman maks"):
            assert label.lower() in kpi_text, f"Missing KPI card: {label}"

        # 4. Full Setup tab remains accessible
        pg.click("button[data-act='wMode'][data-v='full']")
        pg.wait_for_selector("main h1")
        assert "Proyek baru" in pg.inner_text("main h1")

        assert not pg.problems, pg.problems
    finally:
        pg.close()
        server.shutdown()


def test_all_23_screens_switch_id_en_cleanly_without_leaked_strings(browser, site):
    """Every one of the 23 views translates cleanly in EN, switches ID <-> EN live, and leaves zero missing keys."""
    url, _ = site
    all_23 = [
        "data", "qa", "parameter", "jalankan", "ringkasan", "pit-by-pit", "pit-final", "pushback",
        "rencana", "desain", "blok", "sensitivitas", "d-sumber", "d-sektor", "d-ramp", "d-generate",
        "d-validasi", "d-penampang", "d-ekspor", "3d", "bandingkan", "ekspor", "unggah",
    ]
    leaked_id = re.compile(
        r"\b(?:belum|dan|dari|untuk|dengan|hasil|sudah|tidak|bisa|satu|proyek|skenario|ringkasan|desain|"
        r"rencana|parameter|sektor|blok|dipakai|dipilih|muncul|permukaan|terbaca|sintetis|bawah|sebagai|pada|"
        r"setiap|kosong|lebar|tinggi|sudut|pilih|diisi|otomatis|secara|berdasarkan|tambang|laporan|perlu|ubah|hapus|"
        r"selisih|jarak|ukuran|jumlah|nilai|kadar|umpan|batuan|bijih|dinding|kemiringan|garis|penampang|irisan|"
        r"warna|putar|berhenti|tujuan|dalam|luar|tanpa|atau|yang|akan|jika|bila|hanya|lain|baru|lama|"
        r"jalankan|simpan|batal|kembali|lanjut|buka|lihat|unduh|paket|berkas|jenis|tabel|grafik|peta|skala|"
        r"masalah|peringatan|asumsi|dokumen|galian|tertinggal|dilusi|tercuram|terukur|terdiskonto|rata|"
        r"jalur|tepi|tingkat|seragam|praktis|dampak|ambang|penjumlahan|sisa|hitung|kelola|berjalan|selesai|"
        r"gagal|muat|unggah|contoh|sumber|langkah|tahap|wajib|opsional|catatan)\b",
        re.IGNORECASE,
    )
    leaked_en = re.compile(
        r"\b(?:summary|parameters|validation|reconciliation|sensitivity|compare|export|upload|block model|"
        r"run optimisation|generate design|cancel|manage|scenario|project|not run yet)\b",
        re.IGNORECASE,
    )

    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(45000)
    pg.problems = []
    pg.on("pageerror", lambda e: pg.problems.append(f"pageerror: {e}"))
    pg.on("console", lambda m: pg.problems.append(f"console: {m.text}") if m.type == "error" else None)
    pg.add_init_script("localStorage.setItem('pitopt-scenario-v2','example_tin/project'); localStorage.setItem('pitopt-lang','en')")
    pg.goto(url)
    pg.wait_for_selector("nav.side")
    try:
        # Generate detailed design so d-generate, d-validasi, d-penampang, d-ekspor, d-ramp render full content.
        pg.evaluate("location.hash = '#/d-generate'")
        pg.wait_for_selector(".pagehead button[data-act='dGenerate']")
        pg.click(".pagehead button[data-act='dGenerate']")
        pg.wait_for_selector("#d3d.js-plotly-plot canvas", timeout=60000)
        pg.wait_for_timeout(400)

        for screen in all_23:
            pg.evaluate(f"location.hash = '#/{screen}'")
            pg.wait_for_selector("main h1")
            pg.wait_for_timeout(400)
            if screen == "d-generate":
                pg.click("main button[data-act='dTab'][data-k='val']")
                pg.wait_for_timeout(200)
            if screen == "d-ekspor":
                pg.click("button[data-act='dExport']")
                pg.wait_for_timeout(500)
            # Strip <pre> blocks (raw engine logs / JSON provenance) before checking UI copy.
            visible = pg.evaluate("""(() => {
                const clone = document.body.cloneNode(true);
                clone.querySelectorAll('pre').forEach(el => el.remove());
                return clone.innerText;
            })()""")
            assert not leaked_id.search(visible), f"Leaked Indonesian text on {screen}: {leaked_id.findall(visible)}"
            missing = pg.evaluate("""(() => {
                const titles = new Set((window.__pitopt.S.projects || []).map(p => p.title));
                return [...window.__pitopt.i18n.missing].filter(k => !titles.has(k.split(" · ")[0]));
            })()""")
            assert not missing, f"Missing i18n keys on {screen}: {missing}"
            pg.evaluate("window.__pitopt.i18n.missing.clear()")

        # Live ID <-> EN switching across representative views.
        for screen, en_title, id_title in (
            ("ringkasan", "Results summary", "Ringkasan hasil"),
            ("desain", "Design", "Desain"),
            ("d-validasi", "Validation & Reconciliation", "Validasi & Rekonsiliasi"),
            ("unggah", "Quick Pit Estimation", "Estimasi Pit Cepat"),
        ):
            pg.evaluate(f"location.hash = '#/{screen}'")
            pg.wait_for_selector("main h1")
            assert pg.inner_text("main h1").strip() == en_title
            pg.click("button[data-act='lang'][data-v='id']")
            pg.wait_for_timeout(250)
            assert pg.inner_text("main h1").strip() == id_title
            id_text = pg.evaluate("""(() => {
                const clone = document.body.cloneNode(true);
                clone.querySelectorAll('pre, select, .num, .tagc').forEach(el => el.remove());
                return clone.innerText;
            })()""")
            assert not leaked_en.search(id_text), f"Leaked English text on {screen} in ID mode: {leaked_en.findall(id_text)}"
            pg.click("button[data-act='lang'][data-v='en']")
            pg.wait_for_timeout(250)
            assert pg.inner_text("main h1").strip() == en_title

        # Multi-commodity EN check (gold_oz, ree_ppm, sands_vol)
        for project in ("gold_oz", "ree_ppm", "sands_vol"):
            pg.select_option("#proyek", project)
            pg.wait_for_timeout(400)
            for screen in ("ringkasan", "pit-by-pit", "pushback", "qa", "data"):
                pg.evaluate(f"location.hash = '#/{screen}'")
                pg.wait_for_selector("main h1")
                pg.wait_for_timeout(300)
                visible = pg.evaluate("""(() => {
                    const clone = document.body.cloneNode(true);
                    clone.querySelectorAll('pre').forEach(el => el.remove());
                    return clone.innerText;
                })()""")
                assert not leaked_id.search(visible), f"Leaked Indonesian text on {project}/{screen}: {leaked_id.findall(visible)}"
                missing = pg.evaluate("""(() => {
                    const titles = new Set((window.__pitopt.S.projects || []).map(p => p.title));
                    return [...window.__pitopt.i18n.missing].filter(k => !titles.has(k.split(" · ")[0]));
                })()""")
                assert not missing, f"Missing i18n keys on {project}/{screen}: {missing}"
                pg.evaluate("window.__pitopt.i18n.missing.clear()")

        assert not pg.problems, pg.problems
    finally:
        pg.close()


ALL_23_SCREENS = [
    "data", "qa", "parameter", "jalankan", "ringkasan", "pit-by-pit", "pit-final", "pushback",
    "rencana", "desain", "blok", "sensitivitas", "d-sumber", "d-sektor", "d-ramp", "d-generate",
    "d-validasi", "d-penampang", "d-ekspor", "3d", "bandingkan", "ekspor", "unggah",
]


@pytest.mark.parametrize("width,height", [(375, 812), (768, 1024), (1440, 900)])
def test_responsive_viewports_no_horizontal_overflow(browser, site, width, height):
    """Every screen renders without horizontal page/nav/header/table/canvas overflow at 375px, 768px, and 1440px."""
    url, _ = site
    pg = browser.new_page(viewport={"width": width, "height": height})
    pg.set_default_timeout(45000)
    pg.problems = []
    pg.on("pageerror", lambda e: pg.problems.append(f"pageerror: {e}"))
    pg.on("console", lambda m: pg.problems.append(f"console: {m.text}") if m.type == "error" else None)
    pg.add_init_script("localStorage.setItem('pitopt-scenario-v2','example_tin/project'); localStorage.setItem('pitopt-lang','en')")
    pg.goto(url)
    pg.wait_for_selector("nav.side")
    try:
        # Ensure detailed design exists so d-generate, d-validasi, d-penampang, d-ekspor, d-ramp render full tables/canvases.
        pg.evaluate("location.hash = '#/d-generate'")
        pg.wait_for_selector(".pagehead button[data-act='dGenerate']")
        pg.click(".pagehead button[data-act='dGenerate']")
        pg.wait_for_selector("#d3d.js-plotly-plot canvas", timeout=60000)
        pg.wait_for_timeout(400)

        for screen in ALL_23_SCREENS:
            pg.evaluate(f"location.hash = '#/{screen}'")
            pg.wait_for_selector("main h1")
            pg.wait_for_timeout(450)
            metrics = pg.evaluate("""() => {
                const doc = document.documentElement;
                const hdr = document.querySelector('header.top');
                const nav = document.querySelector('nav.side');
                const hRect = hdr ? hdr.getBoundingClientRect() : null;
                const nRect = nav ? nav.getBoundingClientRect() : null;
                const badTables = [...document.querySelectorAll('table.t')].filter(t => {
                    const p = t.parentElement;
                    const pStyle = p ? getComputedStyle(p) : null;
                    const scrollable = pStyle && (pStyle.overflowX === 'auto' || pStyle.overflowX === 'scroll' || pStyle.overflow === 'auto' || pStyle.overflow === 'scroll');
                    const r = (scrollable ? p : t).getBoundingClientRect();
                    return r.right > doc.clientWidth + 1;
                }).map(t => t.innerText.slice(0, 40));
                const badCanvases = [...document.querySelectorAll('canvas')].filter(c => {
                    const p = c.parentElement;
                    const pStyle = p ? getComputedStyle(p) : null;
                    const scrollable = pStyle && (pStyle.overflowX === 'auto' || pStyle.overflowX === 'scroll' || pStyle.overflow === 'auto' || pStyle.overflow === 'scroll');
                    const r = (scrollable ? p : c).getBoundingClientRect();
                    return r.width > 0 && r.right > doc.clientWidth + 1;
                }).map(c => c.id || c.className);
                return {
                    scrollWidth: doc.scrollWidth,
                    clientWidth: doc.clientWidth,
                    headerRight: hRect ? hRect.right : 0,
                    navRight: nRect ? nRect.right : 0,
                    navWidth: nRect ? nRect.width : 0,
                    badTables,
                    badCanvases,
                };
            }""")
            assert metrics["scrollWidth"] <= metrics["clientWidth"], (
                f"{width}x{height} {screen}: horizontal overflow scrollWidth={metrics['scrollWidth']} > clientWidth={metrics['clientWidth']}"
            )
            assert metrics["headerRight"] <= metrics["clientWidth"] + 1, (
                f"{width}x{height} {screen}: header overflows ({metrics['headerRight']} > {metrics['clientWidth']})"
            )
            assert metrics["navRight"] <= metrics["clientWidth"] + 1, (
                f"{width}x{height} {screen}: nav overflows ({metrics['navRight']} > {metrics['clientWidth']})"
            )
            assert not metrics["badTables"], f"{width}x{height} {screen}: unwrapped overflowing tables {metrics['badTables']}"
            assert not metrics["badCanvases"], f"{width}x{height} {screen}: overflowing canvases {metrics['badCanvases']}"

            if width == 1440 and screen == "d-sektor":
                cols = pg.evaluate("getComputedStyle(document.querySelector('.dd-cols3')).gridTemplateColumns.split(' ').length")
                assert cols == 3, f"Desktop 1440 d-sektor should keep 3-panel layout, got {cols} columns"
                assert metrics["navWidth"] < 70, f"Desktop 1440 d-sektor rail should stay < 70px, got {metrics['navWidth']}"

        assert not pg.problems, pg.problems
    finally:
        pg.close()


def test_wcag_accessibility_aria_focus_and_contrast(browser, site):
    """ARIA roles/labels, keyboard :focus-visible navigation, and WCAG 2.2 AA (>=4.5:1) contrast in light & dark themes."""
    url, _ = site
    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(45000)
    pg.problems = []
    pg.on("pageerror", lambda e: pg.problems.append(f"pageerror: {e}"))
    pg.on("console", lambda m: pg.problems.append(f"console: {m.text}") if m.type == "error" else None)
    pg.add_init_script("localStorage.setItem('pitopt-scenario-v2','example_tin/project'); localStorage.setItem('pitopt-lang','en'); localStorage.removeItem('pitopt-theme')")
    pg.goto(url)
    pg.wait_for_selector("nav.side")
    try:
        # 1. Contrast checks in both light and dark themes on multiple screens
        for theme in ("light", "dark"):
            pg.evaluate(f"document.documentElement.dataset.theme = '{'dark' if theme == 'dark' else ''}'")
            pg.evaluate("location.hash = '#/pit-by-pit'")
            pg.wait_for_selector("table.t")
            pg.wait_for_timeout(300)

            contrast_failures = pg.evaluate("""() => {
                const parse = (c) => {
                    const m = c.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/);
                    return m ? [Number(m[1]), Number(m[2]), Number(m[3]), m[4] === undefined ? 1 : Number(m[4])] : null;
                };
                const blend = (fg, bg) => {
                    const a = fg[3];
                    return [fg[0]*a + bg[0]*(1-a), fg[1]*a + bg[1]*(1-a), fg[2]*a + bg[2]*(1-a)];
                };
                const lum = ([r, g, b]) => {
                    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
                    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
                };
                const ratio = (c1, c2) => {
                    const l1 = lum(c1), l2 = lum(c2);
                    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
                };
                const bgOf = (el) => {
                    let cur = el;
                    while (cur) {
                        const c = parse(getComputedStyle(cur).backgroundColor);
                        if (c && c[3] > 0.05) return c.slice(0, 3);
                        cur = cur.parentElement;
                    }
                    return parse(getComputedStyle(document.body).backgroundColor).slice(0, 3);
                };
                const selectors = [
                    'body', 'main h1', '.muted', '.faint', '.navh', '.nav .no',
                    '.nav.active', '.btn.primary', '.tabs button.on',
                    '.pill.ok', '.pill.warn', '.pill.bad', '.pill.mute',
                    'table.t tr.dim td', '.tagc.info', '.tagc.asumsi',
                ];
                const fails = [];
                for (const sel of selectors) {
                    for (const el of document.querySelectorAll(sel)) {
                        const st = getComputedStyle(el);
                        if (st.display === 'none' || st.visibility === 'hidden' || el.offsetParent === null) continue;
                        if (!el.innerText.trim()) continue;
                        const fg = parse(st.color);
                        const bg = bgOf(el);
                        if (!fg || !bg) continue;
                        const eff = fg[3] < 1 ? blend(fg, bg) : fg.slice(0, 3);
                        const r = ratio(eff, bg);
                        if (r < 4.5) fails.push({ sel, text: el.innerText.trim().slice(0, 25), ratio: Number(r.toFixed(2)), fg: st.color, bg });
                    }
                }
                return fails;
            }""")
            assert not contrast_failures, f"{theme} theme WCAG AA contrast failures (<4.5:1): {contrast_failures}"

        # 2. Check .ve.one & .badge contrast on 3d / d-sumber in dark mode as well
        pg.evaluate("document.documentElement.dataset.theme = 'dark'; location.hash = '#/3d'")
        pg.wait_for_selector("main h1")
        pg.click(".pagehead .tabs button[data-v='1']")
        pg.wait_for_timeout(250)
        ve_contrast = pg.evaluate("""() => {
            const el = document.querySelector('.ve.one');
            if (!el) return 99;
            const parse = (c) => c.match(/\\d+/g).slice(0, 3).map(Number);
            const lum = ([r, g, b]) => {
                const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
                return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
            };
            const st = getComputedStyle(el);
            const l1 = lum(parse(st.color)), l2 = lum(parse(st.backgroundColor));
            return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
        }""")
        assert ve_contrast >= 4.5, f".ve.one contrast in dark mode {ve_contrast:.2f} < 4.5"

        # 3. ARIA roles, labels, and keyboard focusability across interactive screens
        for screen in ("pushback", "blok", "sensitivitas", "unggah", "d-sektor", "d-generate"):
            pg.evaluate(f"location.hash = '#/{screen}'")
            pg.wait_for_selector("main h1")
            pg.wait_for_timeout(300)
            a11y = pg.evaluate("""() => {
                const nav = document.querySelector('nav.side');
                const navActive = document.querySelector('nav.side a.active[aria-current="page"]');
                const navNoHref = [...document.querySelectorAll('nav.side a[data-go]')].filter(a => !a.getAttribute('href'));
                const tabsMissingRole = [...document.querySelectorAll('.tabs:not(.lang)')].filter(t => t.getAttribute('role') !== 'tablist');
                const tabBtnsBad = [...document.querySelectorAll('.tabs:not(.lang) button')].filter(b => b.getAttribute('role') !== 'tab' || !['true', 'false'].includes(b.getAttribute('aria-selected')));
                const unnamedBtns = [...document.querySelectorAll('button')].filter(b => {
                    if (b.offsetParent === null) return false;
                    const name = (b.getAttribute('aria-label') || b.innerText || b.getAttribute('title') || '').trim();
                    return !name;
                });
                const unlabeledRange = [...document.querySelectorAll('input[type=range]')].filter(r => !r.getAttribute('aria-label'));
                return {
                    navLabel: Boolean(nav && nav.getAttribute('aria-label')),
                    hasCurrentPage: Boolean(navActive),
                    navNoHref: navNoHref.length,
                    tabsMissingRole: tabsMissingRole.length,
                    tabBtnsBad: tabBtnsBad.length,
                    unnamedBtns: unnamedBtns.length,
                    unlabeledRange: unlabeledRange.length,
                };
            }""")
            assert a11y["navLabel"], f"{screen}: nav.side missing aria-label"
            assert a11y["hasCurrentPage"], f"{screen}: active nav link missing aria-current='page'"
            assert a11y["navNoHref"] == 0, f"{screen}: nav links missing href for keyboard Tab focus"
            assert a11y["tabsMissingRole"] == 0, f"{screen}: .tabs missing role='tablist'"
            assert a11y["tabBtnsBad"] == 0, f"{screen}: tab buttons missing role='tab' / aria-selected"
            assert a11y["unnamedBtns"] == 0, f"{screen}: buttons without accessible name"
            assert a11y["unlabeledRange"] == 0, f"{screen}: range inputs missing aria-label"

        # 4. Keyboard :focus-visible outline and modal Escape handling
        pg.evaluate("location.hash = '#/ringkasan'")
        pg.wait_for_selector("main h1")
        pg.focus("button[data-act='theme']")
        # Trigger keyboard Tab so :focus-visible matches
        pg.keyboard.press("Tab")
        focus_info = pg.evaluate("""() => {
            const el = document.activeElement;
            if (!el || el === document.body) return null;
            const st = getComputedStyle(el);
            return { tag: el.tagName, outlineStyle: st.outlineStyle, outlineWidth: parseFloat(st.outlineWidth) };
        }""")
        assert focus_info and focus_info["outlineStyle"] != "none" and focus_info["outlineWidth"] >= 2, (
            f"Keyboard focus lacks visible >=2px outline: {focus_info}"
        )

        pg.click("button[data-act='manage']")
        pg.wait_for_selector("#modal")
        assert pg.get_attribute("#modal", "role") == "dialog"
        assert pg.get_attribute("#modal", "aria-modal") == "true"
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(150)
        assert pg.locator("#modal").count() == 0, "Escape key should close modal dialog"

        assert not pg.problems, pg.problems
    finally:
        pg.close()

