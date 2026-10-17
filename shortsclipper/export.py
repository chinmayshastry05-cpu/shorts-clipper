"""Export: render one already-downloaded segment into the final short.

Applies the 9:16 crop/scale and burns the .ass captions. The segment is
0-based, so no seeking is needed and the 0-based .ass track lines up exactly.
"""

from pathlib import Path

from . import config
from .logutil import get_logger
from .util import ffprobe_dims, has_audio, run

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


def tracked_filtergraph(src_w, src_h, runs, ass_name=None, audio=True):
    """Build the -filter_complex for a multi-anchor render.

    runs: [(t0, t1, face_x|None)] covering the segment. Each run is trimmed,
    cropped around its own face anchor (center when None), scaled to 9:16,
    then everything is concatenated and the captions burned on top. Audio
    gets matching atrim slices when present. Returns (graph, vout, aout).
    Pure string-building — unit-tested without ffmpeg.
    """
    from .editing import crop_filters
    vpieces, apieces = [], []
    for i, (t0, t1, face_x) in enumerate(runs):
        crop = ",".join(crop_filters(src_w, src_h, face_x))
        vpieces.append(f"[0:v]trim=start={t0}:end={t1},setpts=PTS-STARTPTS,{crop}[v{i}]")
        if audio:
            apieces.append(f"[0:a]atrim=start={t0}:end={t1},asetpts=PTS-STARTPTS[a{i}]")
    cat_in = "".join(f"[v{i}]" for i in range(len(runs)))
    graph = vpieces + apieces
    graph.append(f"{cat_in}concat=n={len(runs)}:v=1:a=0[vcat]")
    if audio:
        graph.append("".join(f"[a{i}]" for i in range(len(runs)))
                     + f"concat=n={len(runs)}:v=0:a=1[acat]")
    vout = "vcat"
    if ass_name:
        graph.append(f"[vcat]ass={ass_name}[vout]")
        vout = "vout"
    return ";".join(graph), vout, ("acat" if audio else None)


def render_tracked(segment_path, outdir, out_name, runs, ass_name=None):
    """Render with a per-run face anchor (two-shot / cut-heavy segments).

    Runs are trimmed from the source, each cropped on its own anchor,
    concatenated back, and captions burned in one ffmpeg pass. Returns the
    output Path.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    src_w, src_h = ffprobe_dims(segment_path)
    seg_has_audio = has_audio(segment_path)
    graph, vout, aout = tracked_filtergraph(src_w, src_h, runs, ass_name,
                                            audio=seg_has_audio)
    cmd = ["ffmpeg", "-y", "-i", str(segment_path),
           "-filter_complex", graph, "-map", f"[{vout}]"]
    if aout:
        cmd += ["-map", f"[{aout}]"]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if aout:
        cmd += ["-c:a", "aac", "-b:a", "160k"]
    else:
        cmd += ["-an"]
    cmd.append(out_name)
    log.info("tracked render (%d anchor runs) -> %s", len(runs), out_name)
    run(cmd, cwd=str(outdir))
    out = outdir / out_name
    log.info("done %s (%.1f MB)", out_name, out.stat().st_size / 1e6)
    return out
