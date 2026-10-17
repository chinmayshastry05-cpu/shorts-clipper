"""Reframe a segment to vertical 9:16, anchored on the speaker's face.

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


def vertical_filters(segment_path, vertical=True, face_x=None):
    """Return (out_w, out_h, [vf strings]) for a 9:16 frame cropped around
    the face (or centered when face_x is None). Source is returned untouched
    when vertical is False."""
    src_w, src_h = ffprobe_dims(segment_path)
    if not vertical:
        return src_w, src_h, []
    x, y, cw, ch = crop_box(src_w, src_h, face_x)
    anchor = f"face x={face_x:.3f}" if face_x is not None else "center"
    log.info("%s crop %dx%d at (%d,%d) from %dx%d", anchor, cw, ch, x, y, src_w, src_h)
    return (config.OUT_W, config.OUT_H,
            [f"crop={cw}:{ch}:{x}:{y}", f"scale={config.OUT_W}:{config.OUT_H}"])
