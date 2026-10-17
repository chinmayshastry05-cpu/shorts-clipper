"""Low-level helpers: subprocess, ffprobe, time & URL parsing."""

import re
import subprocess
from pathlib import Path

from .logutil import get_logger

log = get_logger("util")

_URL_RE = re.compile(r"^https?://", re.I)
_YT_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/|live/))([A-Za-z0-9_-]{11})"
)


def is_url(s):
    return bool(_URL_RE.match(str(s)))


def youtube_id(url):
    """Extract the 11-char YouTube video id, or None."""
    m = _YT_ID_RE.search(str(url))
    return m.group(1) if m else None


def source_key(source):
    """A stable id for either a URL or a local file (for cache keys)."""
    if is_url(source):
        vid = youtube_id(source)
        if vid:
            return vid
        return re.sub(r"[^A-Za-z0-9]+", "_", str(source))[-40:]
    p = Path(source)
    try:
        return f"{p.stem}_{p.stat().st_size}"
    except OSError:
        return re.sub(r"[^A-Za-z0-9]+", "_", p.stem)


def run(cmd, **kw):
    """Run a subprocess, raising RuntimeError with captured stderr tail on failure."""
    kw.setdefault("stdout", subprocess.PIPE)
    kw.setdefault("stderr", subprocess.PIPE)
    kw.setdefault("text", True)
    log.debug("run: %s", " ".join(map(str, cmd)))
    proc = subprocess.run(cmd, **kw)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-1500:]
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(map(str, cmd))}\n{tail}")
    return proc


def ffprobe_duration(path):
    proc = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return float(proc.stdout.strip())


def ffprobe_dims(path):
    proc = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0", str(path)])
    w, h = proc.stdout.strip().split("x")
    return int(w), int(h)


def has_audio(path):
    proc = run(["ffprobe", "-v", "error", "-select_streams", "a",
                "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)])
    return bool(proc.stdout.strip())


def slugify(text, maxlen=60):
    s = re.sub(r"[^\w\s-]", "", str(text)).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:maxlen].strip("-") or "clip"


def extract_wav16k(video_path, wav_path):
    """Extract 16kHz mono wav (what faster-whisper expects)."""
    run(["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000",
         "-f", "wav", str(wav_path)])
    return wav_path


def extract_frame(video_path, at_seconds, out_path, width=270):
    """Extract one frame (scaled to `width`, keeping aspect) for the preview."""
    run(["ffmpeg", "-y", "-ss", f"{at_seconds:.2f}", "-i", str(video_path),
         "-vframes", "1", "-vf", f"scale={width}:-2", str(out_path)])
    return out_path
