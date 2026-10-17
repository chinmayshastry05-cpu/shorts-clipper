"""Tests: auto-cut window selection (speech-density sliding window)."""

from shortscut.selection import pick_window


def _segs(spec):
    # spec: list of (start, end, nwords) -> segments with that many words
    return [{"start": s, "end": e, "text": " ".join(["w"] * n)}
            for s, e, n in spec]


def test_picks_densest_window():
    # 0-30s has 10 words, 30-60s has 50 words -> the 30s window lands at 30s.
    segs = _segs([(0, 10, 3), (10, 20, 3), (20, 30, 4), (30, 40, 20),
                  (40, 50, 15), (50, 60, 15)])
    start, end, words = pick_window(segs, 30)
    assert (start, end) == (30, 60)
    assert words == 50


def test_short_video_returns_whole_span():
    segs = _segs([(2, 8, 5), (8, 14, 7)])
    start, end, words = pick_window(segs, 60)
    assert (start, end) == (2, 14)
    assert words == 12


def test_tie_breaks_earliest():
    segs = _segs([(0, 10, 10), (10, 20, 10), (20, 30, 10)])
    start, end, _ = pick_window(segs, 20)
    assert (start, end) == (0, 20)
