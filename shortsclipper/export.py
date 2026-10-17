"""Export: render one already-downloaded segment into the final short.

Applies the 9:16 crop/scale and burns the .ass captions. The segment is
0-based, so no seeking is needed and the 0-based .ass track lines up exactly.
"""

from pathlib import Path

from . import config
from .logutil import get_logger
from .util import has_audio, run

log = get_logger("export")


def render(segment_path, outdir, out_name, vf_parts, ass_name=None):
    """Render segment_path -> outdir/out_name. Returns the output Path.
    vf_parts: video-filter chain (crop/scale); ass_name: bare .ass filename in outdir."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    vchain = list(vf_parts)
    if ass_name:
        vchain.append(f"ass={ass_name}")     # bare name; we run with cwd=outdir
    seg_has_audio = has_audio(segment_path)

    cmd = ["ffmpeg", "-y", "-i", str(segment_path)]
    if vchain:
        cmd += ["-vf", ",".join(vchain)]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if seg_has_audio:
        cmd += ["-c:a", "aac", "-b:a", "160k"]
    else:
        cmd += ["-an"]
    cmd.append(out_name)
    log.info("rendering -> %s", out_name)
    run(cmd, cwd=str(outdir))
    out = outdir / out_name
    log.info("done %s (%.1f MB)", out_name, out.stat().st_size / 1e6)
    return out
