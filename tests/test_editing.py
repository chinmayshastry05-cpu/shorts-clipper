"""Tests: 9:16 crop geometry (center + face-anchored) and the face-detection
fallback. Geometry tests are pure math; the detection test needs a real
(no-face) video so it exercises the OpenCV path end to end."""

import subprocess

import pytest

from shortsclipper.editing import (_crop_size, _place, crop_box,
                                   detect_face_center_x, vertical_filters)


def test_crop_size_landscape():
    assert _crop_size(1920, 1080) == (608, 1080)


def test_crop_size_tall_source():
    # A source already taller than 9:16 crops top/bottom instead.
    assert _crop_size(720, 1600) == (720, 1280)


def test_place_clamps_into_frame():
    assert _place(0, 540, 608, 1080, 1920, 1080) == (0, 0)
    assert _place(1920, 540, 608, 1080, 1920, 1080) == (1920 - 608, 0)


def test_crop_box_center_matches_v01():
    # face_x=None and face_x=0.5 both reproduce the v0.1 center crop exactly.
    assert crop_box(1920, 1080) == (656, 0, 608, 1080)
    assert crop_box(1920, 1080, face_x=None) == (656, 0, 608, 1080)
    assert crop_box(1920, 1080, face_x=0.5) == (656, 0, 608, 1080)


def test_crop_box_anchors_on_face():
    x, y, cw, ch = crop_box(1920, 1080, face_x=0.25)
    assert (y, cw, ch) == (0, 608, 1080)
    # the face center lands at the middle of the crop window
    assert x + cw / 2 == pytest.approx(0.25 * 1920, abs=1)


def test_crop_box_clamps_at_edges():
    assert crop_box(1920, 1080, face_x=0.02)[0] == 0
    assert crop_box(1920, 1080, face_x=0.98)[0] == 1920 - 608


def _tiny_video(path, size="320x240", seconds=1):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=size={size}:duration={seconds}:rate=10",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_vertical_filters_face_anchor_moves_window(tmp_path):
    src = _tiny_video(tmp_path / "tiny.mp4")
    out_w, out_h, vf = vertical_filters(str(src), face_x=0.25)
    assert (out_w, out_h) == (1080, 1920)
    x, y, cw, ch = crop_box(320, 240, face_x=0.25)
    assert vf == [f"crop={cw}:{ch}:{x}:{y}", "scale=1080:1920"]
    # the anchor really does move the window left of the center crop
    xc = crop_box(320, 240)[0]
    assert x < xc


def test_vertical_filters_no_face_is_center(tmp_path):
    src = _tiny_video(tmp_path / "tiny.mp4")
    _, _, vf = vertical_filters(str(src))
    x, y, cw, ch = crop_box(320, 240)
    assert vf == [f"crop={cw}:{ch}:{x}:{y}", "scale=1080:1920"]


def test_detect_face_returns_none_without_faces(tmp_path):
    pytest.importorskip("cv2")
    src = _tiny_video(tmp_path / "noface.mp4", seconds=2)
    assert detect_face_center_x(src) is None


def test_detect_face_unopenable_returns_none(tmp_path):
    pytest.importorskip("cv2")
    assert detect_face_center_x(tmp_path / "does-not-exist.mp4") is None
