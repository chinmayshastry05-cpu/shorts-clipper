"""Central configuration: paths, defaults, constants.

Linux-first: caches live under the user's XDG cache dir (never inside the
repo or the AppImage), transcription runs on CPU, captions use DejaVu Sans
(ships with every Linux desktop). No Ollama, no GPU, no cloud.
"""

import os
from pathlib import Path

# Project root = the folder containing the `shortscut` package.
ROOT = Path(__file__).resolve().parent.parent

# Cache layout (never re-download / re-transcribe what we already have).
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "shortscut"
TRANSCRIPT_CACHE = CACHE_DIR / "transcripts"      # transcript_<id>.json
SEGMENT_CACHE = CACHE_DIR / "segments"            # <id>_<start>-<end>.mp4
SEGWORDS_CACHE = CACHE_DIR / "segwords"           # <id>_<start>-<end>.json

DEFAULT_OUTPUT = Path.home() / "Downloads"

# Whisper (faster-whisper, CPU). "tiny" is ~75 MB on first run and fast
# enough on a 2-core VM; bump to "base"/"small" for better accuracy.
DEFAULT_WHISPER = "tiny"

# Output video
OUT_W, OUT_H = 1080, 1920           # 9:16
SEGMENT_MAX_HEIGHT = 720            # download at most 720p (plenty for vertical)

# Clip lengths offered in the UI (seconds).
DURATIONS = (30, 45, 60)

# Caption position: fraction from the TOP of the phone preview (0.0 = top,
# 1.0 = bottom). 0.72 sits near the bottom, clear of the middle of frame.
DEFAULT_CAPTION_Y = 0.72

# Caption look
DEFAULT_CAPTION_STYLE = "cinematic"
DEFAULT_CAPTION_SCRIPT = "native"
CAPTION_FONT = "DejaVu Sans"


def ensure_dirs():
    for d in (CACHE_DIR, TRANSCRIPT_CACHE, SEGMENT_CACHE, SEGWORDS_CACHE):
        d.mkdir(parents=True, exist_ok=True)
