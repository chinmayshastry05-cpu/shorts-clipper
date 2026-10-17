"""Tests: Hinglish romanization — the loanword lexicon, phonetic fallback,
and the loud failure when the transliteration dep is missing (v0.2.0 bug:
--caption-script hinglish silently no-opped in the AppImage)."""

import sys

import pytest

from shortsclipper import hinglish
from shortsclipper.captions import write_ass

pytest.importorskip("indic_transliteration")


def test_loanwords_return_english_spelling():
    assert hinglish.to_hinglish("टू") == "to"
    assert hinglish.to_hinglish("डू") == "do"
    assert hinglish.to_hinglish("हियर") == "here"
    assert hinglish.to_hinglish("इज़") == "is"
    assert hinglish.to_hinglish("करियर") == "career"
    assert hinglish.to_hinglish("एडवाइज़र") == "advisor"
    assert hinglish.to_hinglish("इंटरव्यू") == "interview"


def test_reported_v020_sentence():
    # The exact manglings reported from the Learn AI channel agent:
    # "to do here is" -> "tu du hiyar ij", "career advisor" -> "edavaaijara".
    src = "टू डू हियर इज़ करियर एडवाइज़र".split()
    assert [hinglish.to_hinglish(w) for w in src] == [
        "to", "do", "here", "is", "career", "advisor"]


def test_plural_suffix():
    assert hinglish.to_hinglish("जॉब्स") == "jobs"
    assert hinglish.to_hinglish("वीडियोस") == "videos"


def test_nukta_variant():
    assert hinglish.to_hinglish("एडवाइजर") == "advisor"  # no nukta


def test_phonetic_hindi_words():
    assert hinglish.to_hinglish("कैसे") == "kaise"
    assert hinglish.to_hinglish("बहुत") == "bahut"


def test_latin_passthrough():
    assert hinglish.to_hinglish("hello") == "hello"


def test_missing_dep_is_loud(monkeypatch, tmp_path):
    """No silent no-op: without indic-transliteration a Hinglish render must fail."""
    monkeypatch.setitem(sys.modules, "indic_transliteration", None)
    monkeypatch.setitem(sys.modules, "indic_transliteration.sanscript", None)
    with pytest.raises(hinglish.HinglishUnavailableError):
        hinglish.require_hinglish()
    with pytest.raises(hinglish.HinglishUnavailableError):
        hinglish.to_hinglish("कैसे")
    words = [{"word": "hello", "start": 0.0, "end": 0.5}]
    with pytest.raises(hinglish.HinglishUnavailableError):
        write_ass(words, 30.0, 1080, 1920, tmp_path / "x.ass", script="hinglish")


def test_native_script_never_needs_dep(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "indic_transliteration", None)
    monkeypatch.setitem(sys.modules, "indic_transliteration.sanscript", None)
    words = [{"word": "नमस्ते", "start": 0.0, "end": 0.5}]
    n = write_ass(words, 30.0, 1080, 1920, tmp_path / "x.ass", script="native")
    assert n == 1
    assert "नमस्ते" in (tmp_path / "x.ass").read_text(encoding="utf-8")


def test_write_ass_hinglish_output(tmp_path):
    words = [{"word": "करियर", "start": 0.0, "end": 0.5},
             {"word": "बहुत", "start": 0.6, "end": 1.0}]
    p = tmp_path / "h.ass"
    write_ass(words, 30.0, 1080, 1920, p, script="hinglish")
    text = p.read_text(encoding="utf-8")
    assert "CAREER" in text and "BAHUT" in text
