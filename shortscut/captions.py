"""Caption authoring: get word-level timings for a SHORT downloaded segment (fast),
then write an animated .ass. Because we transcribe the segment itself, its words are
already 0-based — no offset math, and we never word-transcribe the full video.

The caption's vertical position comes from `caption_y` (fraction from the top
of the frame, 0.0 = top, 1.0 = bottom) — the same value the GUI preview drag
sets. It is applied as the ASS bottom margin, so the burned position matches
the preview exactly.
"""

import json
import re
import tempfile
from pathlib import Path

from . import config, whisper_engine
from .logutil import get_logger
from .util import extract_wav16k, source_key

log = get_logger("captions")


# ---- per-segment word timings (cached) -----------------------------------

def _words_from_segments(segments, start, end):
    """Fallback: turn phrase-level transcript segments (absolute time) into
    word entries (0-based) by splitting each phrase's text and distributing
    its words evenly across the phrase's span. Used when the segment's own
    word-level transcription returns nothing (Whisper is unreliable on some
    non-English / noisy audio — it can return zero segments for a clip whose
    full-audio transcript found speech). The captions are then phrase-timed
    instead of word-timed, but they exist."""
    out = []
    for seg in segments:
        s0 = max(0.0, seg["start"] - start)
        e0 = min(end - start, seg["end"] - start)
        if e0 <= s0:
            continue
        tokens = (seg.get("text") or "").split()
        if not tokens:
            continue
        step = (e0 - s0) / len(tokens)
        for i, tok in enumerate(tokens):
            out.append({"word": tok, "start": s0 + i * step, "end": s0 + (i + 1) * step})
    return out


def segment_words(segment_path, source, start, end,
                  whisper_model=config.DEFAULT_WHISPER, fallback_segments=None):
    """Word-level timings for one segment (0-based). Cached by source+range.

    fallback_segments: phrase-level transcript segments (absolute time) for
    this window, used only when the segment's own transcription yields no
    words (see _words_from_segments).
    """
    key = f"{source_key(source)}_{start:07.2f}-{end:07.2f}"
    cache = config.SEGWORDS_CACHE / f"{key}.json"
    if cache.exists():
        log.info("cache HIT — segment words (%s)", cache.name)
        return json.loads(cache.read_text(encoding="utf-8"))

    workdir = Path(tempfile.mkdtemp(prefix="shortscut_segw_"))
    try:
        wav = extract_wav16k(segment_path, workdir / "seg.wav")
        _, words, _ = whisper_engine.transcribe(wav, whisper_model, word_timestamps=True)
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)

    if not words and fallback_segments:
        words = _words_from_segments(fallback_segments, start, end)
        log.warning("segment transcription empty — fell back to %d phrase-timed words "
                    "from the full transcript", len(words))

    config.SEGWORDS_CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    log.info("segment words ready (%d words) -> cached", len(words))
    return words


# ---- .ass authoring ------------------------------------------------------

def _ass_time(t):
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _ass_escape(text):
    return (text.replace("\\", "\\\\").replace("{", "(")
            .replace("}", ")").replace("\n", " ").strip())


def _group_words(words, max_words, max_gap):
    lines, cur = [], []
    for w in words:
        if not (w["word"] or "").strip():
            continue
        if cur and (len(cur) >= max_words or w["start"] - cur[-1]["end"] > max_gap):
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


_IAST_HINGLISH = [("ā", "aa"), ("ī", "i"), ("ū", "u"), ("ṃ", "n"), ("ṁ", "n"),
                  ("ṅ", "ng"), ("ñ", "ny"), ("ṇ", "n"), ("ṭh", "th"), ("ṭ", "t"),
                  ("ḍh", "dh"), ("ḍ", "d"), ("ṛ", "r"), ("ś", "sh"), ("ṣ", "sh"),
                  ("ḥ", ""), ("ē", "e"), ("ō", "o")]
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def to_hinglish(word):
    """Romanize a Devanagari word to readable Hinglish. Latin words pass through."""
    if not _DEVANAGARI.search(word):
        return word
    try:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate
    except Exception:
        return word
    s = transliterate(word, sanscript.DEVANAGARI, sanscript.IAST)
    for a, b in _IAST_HINGLISH:
        s = s.replace(a, b)
    s = s.replace("~", "n")
    s = re.sub(r"[^\x00-\x7fA-Za-z']", "", s).lower()
    s = re.sub(r"([bcdfghjklmnpqrstvwxyz])a$", r"\1", s)
    return s or word


def write_ass(words, seg_duration, play_w, play_h, path,
              style=config.DEFAULT_CAPTION_STYLE, script=config.DEFAULT_CAPTION_SCRIPT,
              caption_y=config.DEFAULT_CAPTION_Y):
    """Write an animated word-by-word .ass for a 0-based segment.

    style: 'cinematic' (big bold uppercase, gold pop) or 'karaoke'.
    script: 'native' keeps original glyphs, 'hinglish' romanizes Devanagari.
    caption_y: fraction from the top of the frame (0.0-1.0) — the GUI drag
    value. Applied as the ASS bottom margin: margin_v = (1 - caption_y) * height.
    """
    caption_y = min(1.0, max(0.0, float(caption_y)))
    local = []
    for w in words:
        s, e = max(0.0, w["start"]), min(seg_duration, w["end"])
        if e <= 0 or s >= seg_duration:
            continue
        tok = (w["word"] or "").strip()
        if not any(ch.isalnum() for ch in tok):
            continue
        disp = to_hinglish(tok) if script == "hinglish" else tok
        if not disp.strip():
            continue
        local.append({"word": disp, "start": s, "end": e})

    cinematic = style == "cinematic"
    font = config.CAPTION_FONT
    if cinematic:
        fs = int(play_h * 0.062)
        outline, shadow = 6, 4
        lines = _group_words(local, max_words=3, max_gap=0.7)
        active = r"{\c&H2FE8FF&\b1\fscx112\fscy112}"
        idle = r"{\c&HFFFFFF&\b1\fscx100\fscy100}"
    else:
        fs = max(48, int(play_h * 0.05))
        outline, shadow = 5, 3
        lines = _group_words(local, max_words=5, max_gap=0.8)
        active = r"{\c&H00E6FF&\b1}"
        idle = r"{\c&HFFFFFF&\b0}"

    margin_v = int((1.0 - caption_y) * play_h)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 1
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Base,{font},{fs},&H00FFFFFF,&H000000FF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for line in lines:
        for i, w in enumerate(line):
            parts = []
            for j, ww in enumerate(line):
                tok = _ass_escape(ww["word"]).strip()
                if not tok:
                    continue
                if cinematic:
                    tok = tok.upper()
                parts.append((active if j == i else idle) + tok)
            text = " ".join(parts)
            if cinematic:
                text = r"{\fad(60,60)}" + text
            events.append(
                f"Dialogue: 0,{_ass_time(w['start'])},{_ass_time(w['end'])},Base,,0,0,0,,{text}")
    Path(path).write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    log.info("wrote %s (%d caption events, style=%s, script=%s, caption_y=%.2f, margin_v=%d)",
             Path(path).name, len(events), style, script, caption_y, margin_v)
    return len(events)
