"""Pipeline orchestration for ONE short: transcript -> auto-cut window ->
segment -> word captions -> 9:16 crop -> render.

No LLM, no GPU, no cloud. One call makes one short of the requested length.
The GUI calls `prepare()` (transcript + window + segment + words, for the
phone preview) and then `render_short()` (ASS + export, with the dragged
caption position). The CLI calls `make_short()` which does both in one go.
"""

import tempfile
from pathlib import Path

from . import captions, config, download, editing, export, selection, transcript, whisper_engine
from .logutil import get_logger
from .util import extract_frame, ffprobe_duration, slugify, source_key

log = get_logger("pipeline")


def prepare(source, duration, whisper_model=config.DEFAULT_WHISPER, progress=None,
            face_track=True):
    """Transcript + window + segment + words + face anchor. Returns a dict the
    GUI previews.

    progress: optional callable(msg) for status updates.
    """
    config.ensure_dirs()
    if progress:
        progress("Getting transcript…")
    segments, language, method = transcript.get_transcript(source, whisper_model)
    log.info("transcript via %s | %d segs | lang=%s", method, len(segments), language)

    if progress:
        progress("Picking the best window…")
    start, end, nwords = selection.pick_window(segments, duration)
    log.info("window %.1f-%.1fs (%d words) for %ds short", start, end, nwords, duration)

    if progress:
        progress("Fetching that segment…")
    try:
        seg = download.get_segment(source, start, end)
    except Exception:
        # Ranged fetch failed (flaky CDN) — download the full video once and slice.
        log.warning("ranged fetch failed — falling back to full-video download")
        if progress:
            progress("Ranged fetch failed — downloading full video once…")
        full = download.get_full_video(source)
        seg = download.slice_from_local(full, source, start, end)

    if face_track:
        if progress:
            progress("Finding the speaker…")
        face_runs, two_shot = editing.detect_face_track(seg)
        if face_runs:
            # Preview anchor: duration-weighted median of the run anchors.
            face_x = sorted(r[2] for r in face_runs)[len(face_runs) // 2]
        else:
            face_x = editing.detect_face_center_x(seg)
        log.info("face anchor: %s (%d run(s), two_shot=%s)",
                 f"{face_x:.3f}" if face_x is not None else "none — center crop",
                 len(face_runs), two_shot)
        if two_shot:
            msg = ("Two-shot scene detected — the crop follows the dominant "
                   "speaker; the other person may be cropped out.")
            log.warning(msg)
            if progress:
                progress(msg)
    else:
        face_runs, two_shot, face_x = [], False, None

    if progress:
        progress("Timing captions…")
    # Fallback for the caption pass: the transcript's phrase segments in this
    # window, in case the segment's own transcription yields no words.
    fallback = [s for s in segments if s["end"] > start and s["start"] < end]
    words = captions.segment_words(seg, source, start, end, whisper_model,
                                   fallback_segments=fallback)
    whisper_engine.free_model()

    # Preview frame: middle of the segment.
    frame = Path(tempfile.mkdtemp(prefix="shortsclipper_preview_")) / "frame.jpg"
    extract_frame(seg, (end - start) / 2.0, frame)
    return {
        "source": source, "key": source_key(source), "language": language,
        "method": method, "start": start, "end": end, "words": words,
        "nwords": nwords, "segment": str(seg), "frame": str(frame),
        "duration": end - start, "face_x": face_x,
        "face_runs": face_runs, "two_shot": two_shot,
    }


def render_short(prep, caption_y=config.DEFAULT_CAPTION_Y,
                 caption_style=config.DEFAULT_CAPTION_STYLE,
                 caption_script=config.DEFAULT_CAPTION_SCRIPT,
                 output_path=None, force=False, progress=None, keep_ass=False):
    """Render a prepared short with the given caption position. Returns metadata."""
    out = Path(output_path) if output_path else None
    if out is None:
        out = config.DEFAULT_OUTPUT / f"shortsclipper_{prep['key']}_{int(prep['start'])}-{int(prep['end'])}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not force:
        log.info("output already exists (%s) — reusing", out.name)
    else:
        if progress:
            progress("Burning captions + rendering…")
        seg_dur = ffprobe_duration(prep["segment"])
        out_w, out_h, vf = editing.vertical_filters(
            prep["segment"], vertical=True, face_x=prep.get("face_x"))
        ass_path = out.with_suffix(".ass")
        n_events = captions.write_ass(prep["words"], seg_dur, out_w, out_h,
                                      ass_path, caption_style, caption_script,
                                      caption_y=caption_y)
        face_runs = prep.get("face_runs") or []
        if len(face_runs) > 1:
            # Cut-heavy / two-shot segment: re-anchor the crop per run
            # instead of holding one static anchor for the whole clip.
            export.render_tracked(prep["segment"], out.parent, out.name,
                                  face_runs, ass_path.name)
        else:
            export.render(prep["segment"], out.parent, out.name, vf, ass_path.name)
        if not keep_ass:
            ass_path.unlink(missing_ok=True)
    return {
        "output": str(out), "window": [prep["start"], prep["end"]],
        "duration": round(ffprobe_duration(out), 2) if out.exists() else None,
        "width": config.OUT_W, "height": config.OUT_H,
        "caption_events": None, "caption_y": caption_y,
        "source": prep["source"], "two_shot": prep.get("two_shot", False),
    }


def make_short(source, duration=30, caption_y=config.DEFAULT_CAPTION_Y,
               caption_style=config.DEFAULT_CAPTION_STYLE,
               caption_script=config.DEFAULT_CAPTION_SCRIPT,
               output_path=None, whisper_model=config.DEFAULT_WHISPER,
               force=False, progress=None, keep_ass=False, face_track=True):
    """One-shot: prepare + render. Returns the render metadata dict."""
    prep = prepare(source, duration, whisper_model, progress, face_track=face_track)
    meta = render_short(prep, caption_y, caption_style, caption_script,
                        output_path, force, progress, keep_ass=keep_ass)
    meta["caption_events"] = None  # counted at write time; see log
    meta["nwords"] = prep["nwords"]
    meta["method"] = prep["method"]
    meta["language"] = prep["language"]
    log.info("=== done | %s | %.1f-%.1fs ===", meta["output"],
             prep["start"], prep["end"])
    return meta
