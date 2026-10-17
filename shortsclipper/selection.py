"""Auto-cut: pick the single best window of the requested length.

No LLM, no cloud. The transcript's phrase segments carry a word count each;
the best window is the one with the most spoken words inside it (speech
density). Ties break toward the earliest window, so output is deterministic.
"""

import bisect


def _words(text):
    return len((text or "").split())


def pick_window(segments, duration):
    """Return (start, end, word_count) for the best `duration`-second window.

    segments: [{start, end, text}] from the transcript. If the spoken content
    is shorter than `duration`, the whole spoken span is returned.
    """
    if not segments:
        raise RuntimeError("cannot pick a window from an empty transcript")
    span_start = min(s["start"] for s in segments)
    span_end = max(s["end"] for s in segments)
    span = span_end - span_start
    if span <= duration:
        total = sum(_words(s["text"]) for s in segments)
        return span_start, span_end, total

    # Candidate starts: every segment start (a window starting mid-phrase is
    # never better than one starting at a phrase boundary with the same words).
    starts = sorted({s["start"] for s in segments})
    # Prefix sums over segments sorted by start, for fast window word counts.
    ordered = sorted(segments, key=lambda s: s["start"])
    seg_starts = [s["start"] for s in ordered]
    prefix = [0]
    for s in ordered:
        prefix.append(prefix[-1] + _words(s["text"]))

    def words_in(lo, hi):
        # Segments that overlap [lo, hi] — count a segment if its start is inside.
        i = bisect.bisect_left(seg_starts, lo)
        j = bisect.bisect_left(seg_starts, hi)
        return prefix[j] - prefix[i]

    best_start, best_words = starts[0], -1
    for cand in starts:
        hi = cand + duration
        if hi > span_end + 1e-9:
            break
        w = words_in(cand, hi)
        if w > best_words:
            best_words, best_start = w, cand
    # If every candidate window ran past the end (sparse tail), fall back to
    # the last full window.
    if best_words < 0:
        best_start = max(span_start, span_end - duration)
        best_words = words_in(best_start, best_start + duration)
    return best_start, best_start + duration, best_words
