"""Tests: caption position (drag value) lands in the ASS bottom margin,
and the ASS file carries the word events."""

import pytest

from shortscut.captions import write_ass

WORDS = [{"word": "hello", "start": 0.0, "end": 0.5},
         {"word": "world", "start": 0.6, "end": 1.0}]


def _margin_v(path):
    """MarginV (index 21) of the ASS Style line, parsed by splitting on commas."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Style: Base,"):
            fields = line.split(",")
            assert len(fields) == 23, f"unexpected Style field count: {len(fields)}"
            return int(fields[21])
    raise AssertionError("ASS style line not found")


def test_caption_y_top_gives_large_bottom_margin(tmp_path):
    p = tmp_path / "top.ass"
    write_ass(WORDS, 30.0, 1080, 1920, p, caption_y=0.10)
    assert _margin_v(p) == int((1.0 - 0.10) * 1920)


def test_caption_y_bottom_gives_small_bottom_margin(tmp_path):
    p = tmp_path / "bottom.ass"
    write_ass(WORDS, 30.0, 1080, 1920, p, caption_y=0.90)
    assert _margin_v(p) == int((1.0 - 0.90) * 1920)


def test_caption_y_moves_margin_monotonically(tmp_path):
    margins = []
    for y in (0.2, 0.5, 0.8):
        p = tmp_path / f"m{y}.ass"
        write_ass(WORDS, 30.0, 1080, 1920, p, caption_y=y)
        margins.append(_margin_v(p))
    assert margins[0] > margins[1] > margins[2]


def test_events_present(tmp_path):
    p = tmp_path / "events.ass"
    n = write_ass(WORDS, 30.0, 1080, 1920, p)
    assert n > 0
    assert p.read_text(encoding="utf-8").count("Dialogue:") == n


def test_words_from_segments_fallback():
    """Phrase segments -> evenly-timed words, shifted to 0-based."""
    from shortscut.captions import _words_from_segments
    segs = [{"start": 10.0, "end": 14.0, "text": "one two three four"},
            {"start": 20.0, "end": 21.0, "text": "five"}]
    words = _words_from_segments(segs, start=10.0, end=70.0)
    assert len(words) == 5
    assert words[0] == {"word": "one", "start": 0.0, "end": 1.0}
    assert words[3]["word"] == "four" and words[3]["end"] == 4.0
    # Second phrase is at 10-11s 0-based (20-10 .. 21-10).
    assert words[4] == {"word": "five", "start": 10.0, "end": 11.0}


def test_words_from_segments_clips_to_window():
    from shortscut.captions import _words_from_segments
    segs = [{"start": 0.0, "end": 100.0, "text": "a b"}]
    words = _words_from_segments(segs, start=10.0, end=30.0)
    assert words[0]["start"] == 0.0 and words[-1]["end"] == 20.0
