"""Reframe a segment to vertical 9:16 with a center crop.

v0.1 scope: a fixed center crop. It is deterministic, dependency-free (no
OpenCV), and the phone preview shows exactly the crop that gets exported.
Face-anchored / saliency crops are a possible later addition, not a v0.1 need.
"""

from . import config
from .logutil import get_logger
from .util import ffprobe_dims

log = get_logger("editing")


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


def crop_box(src_w, src_h):
    """The 9:16 center-crop box (x, y, w, h) for a source frame. Public so the
    GUI preview can show exactly the crop that gets exported."""
    cw, ch = _crop_size(src_w, src_h)
    x, y = _place(src_w / 2.0, src_h / 2.0, cw, ch, src_w, src_h)
    return x, y, cw, ch


def vertical_filters(segment_path, vertical=True):
    """Return (out_w, out_h, [vf strings]) for a center-cropped 9:16 frame.
    Source is returned untouched when vertical is False."""
    src_w, src_h = ffprobe_dims(segment_path)
    if not vertical:
        return src_w, src_h, []
    cw, ch = _crop_size(src_w, src_h)
    x, y = _place(src_w / 2.0, src_h / 2.0, cw, ch, src_w, src_h)
    log.info("center crop %dx%d at (%d,%d) from %dx%d", cw, ch, x, y, src_w, src_h)
    return (config.OUT_W, config.OUT_H,
            [f"crop={cw}:{ch}:{x}:{y}", f"scale={config.OUT_W}:{config.OUT_H}"])
