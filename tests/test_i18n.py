# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Orebit (Ghozian Islam Karami)
"""English dictionary and UI i18n contract tests."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "pitopt/ui/static"
DICT = json.loads((STATIC / "i18n/en.json").read_text())

ALL_23_ROUTES = (
    "data", "qa", "parameter", "jalankan", "ringkasan", "pit-by-pit", "pit-final",
    "pushback", "rencana", "desain", "blok", "sensitivitas", "d-sumber", "d-sektor",
    "d-ramp", "d-generate", "d-validasi", "d-penampang", "d-ekspor", "3d",
    "bandingkan", "ekspor", "unggah",
)


def test_placeholders_match_between_languages():
    bad = [(k, v) for k, v in DICT.items() if k.count("{#}") != v.count("{#}")]
    assert not bad, bad[:5]


def test_no_empty_or_untranslated_copies_of_indonesian_sentences():
    assert all(v.strip() for v in DICT.values())
    # a long sentence mapped to itself is a forgotten translation
    english_like = ("RL", "rock +", "bench {#}", "signedByCP")
    same = [k for k, v in DICT.items() if k == v and len(k.split()) > 5 and not any(w in k for w in english_like)]
    assert not same, same[:5]


def test_language_toggle_and_dictionary_are_wired():
    app = (STATIC / "js/app.js").read_text()
    assert 'data-act="lang"' in app and "loadDictionary" in app and "tx(shell())" in app


def test_default_language_is_consistent_across_html_and_i18n():
    html = (STATIC / "index.html").read_text()
    i18n_js = (STATIC / "js/i18n.js").read_text()
    assert '<html lang="en">' in html
    assert 'localStorage.getItem("pitopt-lang") || "en"' in i18n_js
    assert 'if (lang !== "en" && lang !== "id") lang = "en"' in i18n_js
    assert "decodeEnt" in i18n_js and "encodeEnt" in i18n_js


def test_all_23_views_and_canvas_strings_are_localized():
    app = (STATIC / "js/app.js").read_text()
    for route in ALL_23_ROUTES:
        assert re.search(rf'(?:^|[\s,])"?{re.escape(route)}"?\s*:', app), f"Route {route!r} missing from app.js VIEWS"

    # Every screen title used in pageHead / empty / gate must have an English dictionary entry
    # (or be an international single-word term identical in ID/EN like Data / Ramp).
    screen_titles = [
        "QA Data", "Parameter", "Jalankan", "Ringkasan hasil", "Pit by Pit", "Pit Final",
        "Pushback & Rencana Periode", "Desain", "Model Blok", "Sensitivitas",
        "Sumber shell", "Crest & Sektor", "Generate & Tinjau",
        "Validasi & Rekonsiliasi", "Penampang {#}:{#}", "Ekspor desain",
        "{#}D & Penampang", "Bandingkan", "Ekspor", "Estimasi Pit Cepat",
        "Proyek baru dari data Anda", "Gunakan data Anda sendiri",
    ]
    missing_titles = [title for title in screen_titles if title not in DICT]
    assert not missing_titles, f"Missing screen titles in en.json: {missing_titles}"

    # Canvas, Plotly, validation error, and locale calls must not bypass i18n.
    assert 'locale()' in (STATIC / "js/views/design_sumber.js").read_text()
    assert 'toLocaleString("id-ID"' not in (STATIC / "js/views/design_sumber.js").read_text()
    assert 'lang === "en" ? "N" : "U"' in (STATIC / "js/design/plan.js").read_text()
    assert 't("jarak sepanjang A–A′ (m)")' in (STATIC / "js/design/section.js").read_text()
    assert 't("jarak sepanjang centerline (m)")' in (STATIC / "js/views/design_ramp.js").read_text()
    assert 't("Nama wajib diisi.")' in (STATIC / "js/views/params.js").read_text()
    assert 't("Nama skenario wajib diisi.")' in (STATIC / "js/design/ui.js").read_text()
    assert "t(" in (STATIC / "js/views/view3d.js").read_text()
    assert "t(" in (STATIC / "js/design/three.js").read_text()
