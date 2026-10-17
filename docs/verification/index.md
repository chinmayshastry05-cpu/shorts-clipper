# Verification — ShortCut Linux v0.1.0

How each claim in the README was checked. Logs are the raw command output
(paths sanitized). A check is PASS only if the output file was verified
(duration, dimensions, captions, position) — not just "the command exited 0".

## Unit tests

| Check | Result |
|---|---|
| `pytest tests/ -q` (selection, captions, util, fallback) | PASS — 13 passed |

## End-to-end (real videos, CC-licensed, Wikimedia Commons)

### (a) URL input — PASS (first run)

- Source: `https://upload.wikimedia.org/wikipedia/commons/d/de/Wikipedians_speak_-_Konkani_Wikipedian_Frania_Pereira.webm`
  (101 s, speech, CC-licensed). Direct video URL — see note on YouTube below.
- Command: pipeline with `--duration 30 --caption-y 0.72`.
- Output: `url-30s.mp4`, 22.3 MB, **30.00 s**, **1080×1920** H.264, audio present.
- Window picked: 59.71–89.71 s (speech-dense), 90 words, method `audio-whisper`, lang `en`.
- Captions: **91 ASS events**, MarginV 537 = (1 − 0.72) × 1920 — the dragged
  position lands exactly.
- Log: `e2e-url-30s.log`.

### (b) Local-file input — FAIL then FIXED

- Source: `WikipediansSpeak-Soubhagyavathi.webm` (156 s, Kannada speech),
  downloaded to disk, passed as a local path.
- Command: pipeline with `--duration 60 --caption-y 0.35`.
- First run: output **60.03 s**, **1080×1920**, audio present, MarginV 1248 =
  (1 − 0.35) × 1920 — but **0 caption events**. FAIL.
- Root cause: Whisper (tiny AND base) returns zero segments for this 60 s
  Kannada clip when transcribed standalone, even with VAD off and language
  forced — while the full-audio transcript finds speech. The segment
  transcription is unreliable on this audio; the pipeline had no fallback.
- Fix: segment captioning falls back to the full transcript's phrase
  segments for the window (words split evenly across each phrase) when the
  segment transcription yields nothing.
- **Re-run — PASS.** Output `local-60s.mp4`, 32.8 MB, **60.03 s**, **1080×1920**,
  audio present, MarginV 1248 = expected, **95 caption events** (was 0),
  lang `kn`, 95 words. Frame check (mid-event, 17.25 s): caption
  "KI **HALLI** KELUAN" — white with black outline, active word in gold,
  wrapped to 2 lines inside the frame, sitting at 35% from top. (The
  fixed-time t=3 s frame caught a 60 ms fade and looks faint — expected;
  the mid-event frame is the real check.)
- Log (first run): `e2e-local-60s.log` — note: this log ends at the
  assertion; the output file itself was verified (60.03 s, 1080×1920, audio).

### (c) Caption wrapping — BUG found by visual inspection, FIXED

- The first URL-test output's captions overflowed the frame edge
  ("THE DIFFERENT CAS…" cut off both sides) — libass did not wrap the line.
- Isolated: a minimal ASS with the same header rendered by this ffmpeg
  build does not wrap at `WrapStyle: 2`, but wraps correctly at
  `WrapStyle: 1` (verified with `wraptest*.ass` renders).
- Fix: ASS header now uses `WrapStyle: 1`. The GUI preview also wraps its
  caption line to the phone width.
- **Re-run — PASS.** URL test re-run (30 s, caption-y 0.72): **30.00 s**,
  **1080×1920**, audio present, MarginV 537 = expected, **91 events**.
  Frame check: "THE DIFFERENT / CAST," — wraps to two lines inside the
  frame, active word "CAST," in gold, sitting at 72% from top.

## Re-runs — DONE

- URL test (30 s, caption-y 0.72) re-run with `WrapStyle: 1` — PASS (see §a + §c).
- Local test (60 s, caption-y 0.35) re-run with the phrase fallback — PASS (see §b).

## AppImage — PASS

- Build: `./build-appimage.sh` (standalone Python 3.12 + pip deps + static
  ffmpeg/ffprobe + DejaVu Sans Bold + fontconfig). Output:
  `ShortCut-Linux-x86_64.AppImage`, 210,631,160 bytes.
- Build fixes landed during this run (all in the script, reproducible):
  - `av` pinned to exactly `14.0.0` — 14.4.0 has no usable wheel for the
    standalone Python (pip fell back to a source build needing libav
    headers); `--only-binary :all:` so a missing wheel fails loudly.
  - Build scratch moved from `/tmp` to `~/workspace/tmp` (this VM's `/tmp`
    is ephemeral and a restart wipes it).
  - `tar --no-same-owner` for the static ffmpeg tarball (sandbox can't chown).
  - AppRun writes its fontconfig file to `~/.cache/shortscut/fonts.conf`,
    not `/tmp` (a full `/tmp` killed the first GUI launch).
- Verify:
  - (1) GUI: the extracted `AppRun` under `xvfb-run` launched and stayed up
    (Tkinter mainloop running, killed by the tester). NOTE: the
    `--appimage-extract-and-run` path was NOT used for the GUI check in this
    VM — it extracts ~690 MB into `/tmp`, which here is a 512 MB tmpfs, so
    extraction itself fails. That is a limit of this VM's `/tmp`, not of the
    AppImage; on a normal machine the AppImage mounts via FUSE (no
    extraction) or extracts to a disk-backed `/tmp`.
  - (2) `--cli` render inside the AppImage (extracted AppRun, same code):
    `appimage-30s.mp4`, **30.03 s**, **1080×1920** h264 + AAC, method
    `audio-whisper`, lang `kn`. Frame check: "KANA **DAL** MESHE" — white
    with black outline, active word in gold, wrapped to 2 lines, sitting at
    72% from top. Bundled Python, deps, ffmpeg, and DejaVu font all work.
  - (3) Two `/tmp`-full failures during this verification were the VM's
    512 MB tmpfs filling with `--appimage-extract-and-run` leftovers
    (my own test artifacts, removed); the second `--cli` run then passed.
    The app itself writes temp WAVs to `/tmp` (via `tempfile`) — small
    (~1 MB per segment), fine on a normal machine.

## What was NOT tested

- **YouTube (youtube.com) download.** This VM's datacenter IP gets YouTube's
  "Sign in to confirm you're not a bot" wall from yt-dlp, so the YouTube
  extractor path could not run here. The URL path was tested with a direct
  video URL (same yt-dlp download code). On a normal home connection the
  YouTube path uses the same code; YouTube may still bot-check datacenter/VPN
  IPs (documented in the README).
- **GUI drag interaction.** The caption drag is implemented (Tkinter canvas,
  moves the caption + updates the position label) but was not driven by a
  simulated mouse in this run — the position value it sets is the same
  `caption_y` the CLI/export path verifies. The preview frame + caption text
  render was verified by code inspection, not by a GUI screenshot test.
- **Face-tracked reframe.** v0.1 uses a center crop (documented). Not tested
  because it does not exist.
- **Cloud engines / Ollama.** The app has none; transcription is local Whisper.
- **Windows / macOS.** Linux-only (AppImage, x86_64).

## Notes on the test environment

- The VM's proxy MITMs TLS: yt-dlp is told to prefer the system CA store
  (`--compat-options no-certifi`), and the app strips bracketed-IPv6 entries
  from `NO_PROXY`/`no_proxy` (httpx crashes on them). Both are in the app
  code, not test-only workarounds.
- `faster-whisper` needs `av==14.0.0` (pinned exact): av 14.4.0 has no usable
  wheel for the AppImage's standalone Python (pip falls back to a source
  build that fails without libav headers), and av 15+/19 removed the
  `metadata_errors` parameter faster-whisper passes.
