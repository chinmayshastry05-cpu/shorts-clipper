"""Tests: URL / video-id / cache-key helpers."""

from shortsclipper.util import is_url, source_key, youtube_id


def test_youtube_id():
    assert youtube_id("https://www.youtube.com/watch?v=aqz-KE-bpKQ") == "aqz-KE-bpKQ"
    assert youtube_id("https://youtu.be/aqz-KE-bpKQ") == "aqz-KE-bpKQ"
    assert youtube_id("https://www.youtube.com/shorts/aqz-KE-bpKQ") == "aqz-KE-bpKQ"
    assert youtube_id("https://upload.wikimedia.org/x/y.webm") is None


def test_is_url():
    assert is_url("https://example.com/v.mp4")
    assert not is_url("/home/user/video.mp4")


def test_source_key_youtube_is_video_id():
    assert source_key("https://www.youtube.com/watch?v=aqz-KE-bpKQ&t=5s") == "aqz-KE-bpKQ"


def test_source_key_local_uses_stem_and_size(tmp_path):
    f = tmp_path / "talk.mp4"
    f.write_bytes(b"x" * 100)
    assert source_key(str(f)) == f"talk_{100}"
