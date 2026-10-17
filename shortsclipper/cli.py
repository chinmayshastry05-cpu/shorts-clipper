#!/usr/bin/env python3
"""Shorts Clipper — headless CLI (used for testing + scripting).

The GUI is the primary interface (`python -m shortsclipper`). This CLI runs the
same pipeline without a display: transcript -> auto-cut -> captions -> render.
"""

import argparse
import json
import shutil
import sys

from . import config, pipeline
from .logutil import get_logger, set_verbose

log = get_logger("cli")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="shortsclipper",
        description="Shorts Clipper — auto-cut a 30/45/60s vertical short with captions")
    ap.add_argument("--input", required=True, help="Video URL or local video path")
    ap.add_argument("--duration", type=int, choices=config.DURATIONS, default=30,
                    help="short length in seconds (default 30)")
    ap.add_argument("--caption-y", type=float, default=config.DEFAULT_CAPTION_Y,
                    help="caption position, fraction from top 0.0-1.0 (default 0.72)")
    ap.add_argument("--caption-style", choices=["cinematic", "karaoke"],
                    default=config.DEFAULT_CAPTION_STYLE)
    ap.add_argument("--caption-script", choices=["native", "hinglish"],
                    default=config.DEFAULT_CAPTION_SCRIPT)
    ap.add_argument("--whisper-model", default=config.DEFAULT_WHISPER)
    ap.add_argument("--output", default=None, help="output mp4 path (default ~/Downloads)")
    ap.add_argument("--force", action="store_true", help="re-render even if output exists")
    ap.add_argument("--keep-ass", action="store_true",
                    help="keep the generated .ass caption file next to the output")
    ap.add_argument("--no-face-track", action="store_true",
                    help="disable the face-anchored crop (plain center crop)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    set_verbose(args.verbose)
    if not 0.0 <= args.caption_y <= 1.0:
        log.error("--caption-y must be between 0.0 and 1.0")
        return 2
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            log.error("%s not found on PATH", tool)
            return 1

    try:
        meta = pipeline.make_short(
            source=args.input, duration=args.duration, caption_y=args.caption_y,
            caption_style=args.caption_style, caption_script=args.caption_script,
            output_path=args.output, whisper_model=args.whisper_model,
            force=args.force, progress=lambda m: log.info("%s", m),
            keep_ass=args.keep_ass, face_track=not args.no_face_track,
        )
    except (RuntimeError, KeyboardInterrupt) as e:
        log.error("%s", e)
        return 1
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
