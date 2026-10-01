"""English dictionary for the UI: every entry keeps its numeric placeholders, in the same number."""
import json
from pathlib import Path

DICT = json.loads((Path(__file__).resolve().parents[1] / "pitopt/ui/static/i18n/en.json").read_text())


def test_placeholders_match_between_languages():
    bad = [(k, v) for k, v in DICT.items() if k.count("{#}") != v.count("{#}")]
    assert not bad, bad[:5]


def test_no_empty_or_untranslated_copies_of_indonesian_sentences():
    assert all(v.strip() for v in DICT.values())
    # a long sentence mapped to itself is a forgotten translation
    english_like = ("RL", "rock +", "bench {#}")     # engine/format strings that read the same in both languages
    same = [k for k, v in DICT.items() if k == v and len(k.split()) > 5 and not any(w in k for w in english_like)]
    assert not same, same[:5]


def test_language_toggle_and_dictionary_are_wired():
    root = Path(__file__).resolve().parents[1] / "pitopt/ui/static/js"
    app = (root / "app.js").read_text()
    assert 'data-act="lang"' in app and "loadDictionary" in app and "tx(shell())" in app
