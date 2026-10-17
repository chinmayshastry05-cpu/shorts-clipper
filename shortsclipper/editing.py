"""Reframe a segment to vertical 9:16, anchored on the speaker's face.

v0.2.1: the face anchor is tracked OVER TIME. One static anchor breaks on
videos that cut between shots (two-shot interviews): the speaker jumps to
the other side and the fixed crop cuts them off. detect_face_track() splits
the segment into anchor runs (one per shot), the renderer crops each run
around its own anchor, and a persistent two-shot layout logs a warning that
the second speaker may be cropped.

v0.2: face-anchored crop. The pipeline detects the speaker's face center
(OpenCV Haar cascade over sampled frames, median wins) and anchors the 9:16
crop on it. When no face is found - or OpenCV is not installed - the crop
falls back to the v0.1 center crop. The phone preview shows exactly the
crop that gets exported.
"""

from . import config
from .logutil import get_logger
from .util import ffprobe_dims

log = get_logger("editing")

# Minimum sampled frames that must contain a face before we trust the anchor.
MIN_FACE_SAMPLES = 2

# Tracking (v0.2.1): a new anchor run starts when the face center jumps more
# than this fraction of the frame width between consecutive samples.
MAX_ANCHOR_JUMP = 0.15
# Runs shorter than this (seconds) are merged into a neighbor — avoids
# flicker on brief glances away / cutaway shots.
MIN_RUN_SECONDS = 1.5
# Two-shot: a sample counts as two-shot when it holds >=2 faces at least this
# wide relative to the largest face, separated by at least this fraction of
# the frame width. Persistent two-shot frames trigger the warning.
TWO_SHOT_MIN_REL_SIZE = 0.5
TWO_SHOT_MIN_SEPARATION = 0.20


def _crop_size(src_w, src_h):
    """The 9:16 crop rectangle size (even ints) for a given source."""
    target = config.OUT_W / config.OUT_H
    if src_w / src_h > target:
        cw, ch = int(round(src_h * target)), src_h
    else:
        cw, ch = src_w, int(round(src_w / target))
    return (min(cw, src_w) & ~1), (min(ch, src_h) & ~1)


def _place(cx, cy, cw, ch, src_w, src_h):
    """Clamp a crop of size cw x ch centered at (cx, cy) into the frame."""
    x = max(0, min(int(round(cx - cw / 2.0)), src_w - cw)) & ~1
    y = max(0, min(int(round(cy - ch / 2.0)), src_h - ch)) & ~1
    return x, y


def crop_box(src_w, src_h, face_x=None):
    """The 9:16 crop box (x, y, w, h) for a source frame. Public so the
    GUI preview can show exactly the crop that gets exported.

    face_x: face center as a fraction of frame width (0.0-1.0), or None for
    the plain center crop.
    """
    cw, ch = _crop_size(src_w, src_h)
    cx = (face_x if face_x is not None else 0.5) * src_w
    x, y = _place(cx, src_h / 2.0, cw, ch, src_w, src_h)
    return x, y, cw, ch


def detect_face_center_x(video_path, samples=8):
    """Median face-center across sampled frames, as a fraction of width.

    Uses OpenCV's bundled Haar cascade; the largest face in each sampled
    frame votes. Returns None when OpenCV is missing, the video cannot be
    opened, or fewer than MIN_FACE_SAMPLES frames contain a face - the
    caller then falls back to the center crop.
    """
    try:
        import cv2
    except ImportError:
        log.info("opencv not installed - using center crop")
        return None
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log.warning("cannot open %s for face detection - center crop", video_path)
        return None
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total <= 0:
            return None
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            log.warning("face cascade failed to load - center crop")
            return None
        xs = []
        for i in range(samples):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / samples))
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.2, 5, minSize=(48, 48))
            if len(faces):
                fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                xs.append((fx + fw / 2.0) / frame.shape[1])
        if len(xs) < MIN_FACE_SAMPLES:
            log.info("face found in %d/%d samples - center crop", len(xs), samples)
            return None
        xs.sort()
        return xs[len(xs) // 2]
    finally:
        cap.release()


def crop_filters(src_w, src_h, face_x=None):
    """[crop, scale] vf strings for a 9:16 frame anchored on face_x."""
    x, y, cw, ch = crop_box(src_w, src_h, face_x)
    return [f"crop={cw}:{ch}:{x}:{y}", f"scale={config.OUT_W}:{config.OUT_H}"]


def vertical_filters(segment_path, vertical=True, face_x=None):
    """Return (out_w, out_h, [vf strings]) for a 9:16 frame cropped around
    the face (or centered when face_x is None). Source is returned untouched
    when vertical is False."""
    src_w, src_h = ffprobe_dims(segment_path)
    if not vertical:
        return src_w, src_h, []
    anchor = f"face x={face_x:.3f}" if face_x is not None else "center"
    log.info("%s crop from %dx%d", anchor, src_w, src_h)
    return config.OUT_W, config.OUT_H, crop_filters(src_w, src_h, face_x)


# ---- face tracking over time (v0.2.1) ------------------------------------

def _split_anchor_runs(samples, max_jump=MAX_ANCHOR_JUMP):
    """Split [(t, x)] face samples into runs of stable anchor position.

    A new run starts when the face center jumps more than max_jump (fraction
    of frame width) from the running median — that is a cut to a different
    shot / a speaker on the other side. Pure logic, unit-tested directly.
    """
    runs = []  # each: {"times": [...], "xs": [...]}
    for t, x in samples:
        if runs:
            xs = runs[-1]["xs"]
            med = sorted(xs)[len(xs) // 2]
            if abs(x - med) <= max_jump:
                runs[-1]["times"].append(t)
                runs[-1]["xs"].append(x)
                continue
        runs.append({"times": [t], "xs": [x]})
    return runs


def _runs_to_ranges(runs, duration, min_run=MIN_RUN_SECONDS):
    """Turn sample runs into [(t0, t1, face_x)] covering [0, duration].

    Boundaries fall at midpoints between neighboring runs' nearest samples;
    runs shorter than min_run merge into the longer neighbor. face_x is the
    run's median anchor (fraction of width).
    """
    if not runs:
        return []
    spans = []
    for i, run in enumerate(runs):
        t0 = 0.0 if i == 0 else (runs[i - 1]["times"][-1] + run["times"][0]) / 2.0
        t1 = duration if i == len(runs) - 1 else (run["times"][-1] + runs[i + 1]["times"][0]) / 2.0
        xs = sorted(run["xs"])
        spans.append([t0, t1, xs[len(xs) // 2]])
    # Merge sub-min_run spans into the longer neighbor (repeat until stable).
    changed = True
    while changed and len(spans) > 1:
        changed = False
        for i, (t0, t1, _) in enumerate(spans):
            if t1 - t0 < min_run:
                left = spans[i - 1][1] - spans[i - 1][0] if i > 0 else -1
                right = spans[i + 1][1] - spans[i + 1][0] if i < len(spans) - 1 else -1
                j = i - 1 if left >= right else i + 1
                spans[j][0] = min(spans[j][0], t0)
                spans[j][1] = max(spans[j][1], t1)
                del spans[i]
                changed = True
                break
    # Coalesce adjacent runs that ended up with the same anchor (e.g. after
    # a short-run merge) — one crop window should not be re-cut needlessly.
    merged = []
    for span in spans:
        if merged and abs(span[2] - merged[-1][2]) <= MAX_ANCHOR_JUMP:
            merged[-1][1] = span[1]
        else:
            merged.append(list(span))
    return [(round(t0, 3), round(t1, 3), x) for t0, t1, x in merged]


def _is_two_shot(faces, frame_w):
    """Two comparable faces side by side (interview / debate layout)."""
    if len(faces) < 2:
        return False
    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
    (x1, _, w1, _), (x2, _, w2, _) = faces[0], faces[1]
    if w2 < w1 * TWO_SHOT_MIN_REL_SIZE:
        return False
    sep = abs((x1 + w1 / 2.0) - (x2 + w2 / 2.0)) / frame_w
    return sep >= TWO_SHOT_MIN_SEPARATION


def detect_face_track(video_path, samples=16):
    """Track the face anchor over the segment. Returns (ranges, two_shot).

    ranges: [(t0, t1, face_x)] covering the segment; empty when no usable
    face track (caller falls back to the single-anchor / center crop).
    two_shot: True when a persistent two-person layout was seen — the crop
    anchors on the dominant face and the second speaker may be cropped out.
    """
    try:
        import cv2
    except ImportError:
        log.info("opencv not installed - using center crop")
        return [], False
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log.warning("cannot open %s for face detection - center crop", video_path)
        return [], False
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        if total <= 0 or fps <= 0:
            return [], False
        duration = total / fps
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            log.warning("face cascade failed to load - center crop")
            return [], False
        found = []        # [(t, face_x)]
        two_shot_hits = 0
        prev_x = None
        for i in range(samples):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / samples))
            ok, frame = cap.read()
            if not ok:
                continue
            t = (i + 0.5) / samples * duration
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.2, 5, minSize=(48, 48))
            if not len(faces):
                continue
            if _is_two_shot(faces, frame.shape[1]):
                two_shot_hits += 1
            # Anchor face: nearest to the previous anchor (continuity), else largest.
            if prev_x is not None:
                face = min(faces, key=lambda f: abs((f[0] + f[2] / 2.0) / frame.shape[1] - prev_x))
            else:
                face = max(faces, key=lambda f: f[2] * f[3])
            prev_x = (face[0] + face[2] / 2.0) / frame.shape[1]
            found.append((t, prev_x))
        two_shot = two_shot_hits >= max(2, len(found) // 3)
        if len(found) < MIN_FACE_SAMPLES:
            log.info("face found in %d/%d samples - center crop", len(found), samples)
            return [], two_shot
        ranges = _runs_to_ranges(_split_anchor_runs(found), duration)
        if len(ranges) > 1:
            log.info("face track: %d anchor runs (%s)", len(ranges),
                     ", ".join(f"{a:.1f}-{b:.1f}s@x={x:.2f}" for a, b, x in ranges))
        if two_shot:
            log.warning("two-shot layout detected in %d/%d sampled frames — "
                        "cropping anchors on the dominant face; the second "
                        "speaker may be cropped out", two_shot_hits, len(found))
        return ranges, two_shot
    finally:
        cap.release()
