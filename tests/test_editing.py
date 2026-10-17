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


# ---- face tracking over time (v0.2.1) ------------------------------------

from shortsclipper.editing import (_is_two_shot, _runs_to_ranges,
                                   _split_anchor_runs)


def test_split_anchor_runs_on_cut():
    # Speaker on the left for the first half, on the right after the cut.
    samples = [(i * 30 / 16 + 30 / 32, 0.25 if i < 8 else 0.75)
               for i in range(16)]
    runs = _split_anchor_runs(samples)
    assert len(runs) == 2
    ranges = _runs_to_ranges(runs, 30.0)
    assert len(ranges) == 2
    assert ranges[0][0] == 0.0 and ranges[1][1] == 30.0
    assert ranges[0][2] == 0.25 and ranges[1][2] == 0.75
    assert ranges[0][1] == ranges[1][0]  # contiguous coverage


def test_stable_speaker_single_run():
    samples = [(i * 2.0, 0.5 + (0.01 if i % 2 else -0.01)) for i in range(15)]
    ranges = _runs_to_ranges(_split_anchor_runs(samples), 30.0)
    assert len(ranges) == 1
    t0, t1, x = ranges[0]
    assert (t0, t1) == (0.0, 30.0) and abs(x - 0.5) < 0.02


def test_short_run_merges_into_neighbor():
    # A 1-sample glance at x=0.9 inside a stable 0.3 track must not split
    # the render into a sub-second run.
    samples = [(i * 0.5, 0.3) for i in range(16)] + [(8.25, 0.9)] + \
              [(i * 0.5, 0.3) for i in range(17, 40)]
    ranges = _runs_to_ranges(_split_anchor_runs(samples), 20.0, min_run=1.5)
    assert len(ranges) == 1
    assert ranges[0] == (0.0, 20.0, 0.3)


def test_two_shot_detection():
    # Two comparable faces, far apart horizontally -> two-shot.
    faces = [(100, 100, 200, 200), (1500, 120, 180, 180)]
    assert _is_two_shot(faces, 1920)
    # One dominant face + a small background face -> not two-shot.
    assert not _is_two_shot([(100, 100, 200, 200), (1500, 120, 60, 60)], 1920)
    # Two faces but nearly overlapping (same person double-detect) -> no.
    assert not _is_two_shot([(100, 100, 200, 200), (150, 110, 190, 190)], 1920)
