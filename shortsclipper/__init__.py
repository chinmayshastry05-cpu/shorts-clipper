"""Shorts Clipper — original Linux desktop app for auto-cutting vertical shorts.

Paste a video URL or drop a local video, pick 30/45/60 seconds, drag the
caption on a phone preview, download the finished 9:16 short. Everything
runs locally (ffmpeg + faster-whisper + yt-dlp); no cloud APIs.
"""

import os
from pathlib import Path

# --- Environment fixes (run on ANY `import shortsclipper...`, before anything
# that touches the network). They only make TLS/proxy handling match the
# machine's own system configuration; verification is never disabled. ---

# httpx (used by huggingface_hub for the Whisper model download) crashes on
# bracketed IPv6 entries in NO_PROXY / no_proxy (e.g. "[::1]") with
# `InvalidURL: Invalid port: ':1]'`. Strip bracketed entries — the plain
# `localhost` / `127.0.0.1` entries cover loopback; this does not disable
# any proxy, it only drops entries httpx cannot parse.
for _var in ("NO_PROXY", "no_proxy"):
    _val = os.environ.get(_var)
    if _val and "[" in _val:
        os.environ[_var] = ",".join(p for p in _val.split(",") if "[" not in p)

# If the machine has a system CA bundle and the process does not already
# point TLS at a specific store, prefer the system store. This is what makes
# TLS verification work on machines whose proxy / corporate CA lives in the
# system store (yt-dlp is told separately to prefer system certs).
_SYSTEM_CA = Path("/etc/ssl/certs/ca-certificates.crt")
if _SYSTEM_CA.exists():
    os.environ.setdefault("SSL_CERT_FILE", str(_SYSTEM_CA))
    os.environ.setdefault("REQUESTS_CA_BUNDLE", str(_SYSTEM_CA))

__version__ = "0.3.0"
