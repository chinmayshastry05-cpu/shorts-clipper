"""Local web UI (v0.3.0): `python -m shortsclipper` starts a localhost server
and opens the app in the default browser.

Why web instead of Tkinter: the standalone Python shipped in the AppImage
builds its Tk without Xft, so Tkinter text renders as bitmap fonts on every
Linux desktop — a modern UI is impossible there. The browser gives real
fonts, real rounded corners and the Magic UI look, with zero extra
dependencies (stdlib http.server only). The clipping pipeline is untouched:
this module calls the same pipeline.prepare/render_short the old GUI did.
"""

import io
import json
import re
import threading
import time
import uuid
import webbrowser
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, captions as captions_mod
from . import config, pipeline
from .editing import crop_box
from .logutil import get_logger

log = get_logger("webui")

INDEX = Path(__file__).resolve().parent / "webassets" / "index.html"
PREVIEW_W, PREVIEW_H = 540, 960  # 2x the 270x480 display size (retina)

_jobs = {}          # id -> dict(kind, status, progress[], result, error)
_preps = {}         # (source, duration) -> job id of a finished prepare
_jobs_lock = threading.Lock()
_busy = threading.Lock()   # one pipeline job at a time, like the old GUI
_last_beat = {"t": None}
_shutdown = threading.Event()


def _first_caption_line(words, style):
    grouped = captions_mod._group_words(
        [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in words],
        max_words=3 if style == "cinematic" else 5,
        max_gap=0.7 if style == "cinematic" else 0.8)
    if not grouped:
        return "No speech in this window"
    text = " ".join(w["word"] for w in grouped[0])
    return text.upper() if style == "cinematic" else text


def _new_job(kind):
    job = {"id": uuid.uuid4().hex[:12], "kind": kind, "status": "running",
           "progress": [], "result": None, "error": None}
    with _jobs_lock:
        _jobs[job["id"]] = job
    return job


def _get_job(job_id):
    with _jobs_lock:
        return _jobs.get(job_id)


def _run(job, fn):
    def target():
        with _busy:
            try:
                job["result"] = fn(lambda m: job["progress"].append(m))
                job["status"] = "done"
            except Exception as e:  # noqa: BLE001 - surfaced in the UI
                log.exception("job failed")
                job["error"] = str(e)
                job["status"] = "error"
    threading.Thread(target=target, daemon=True).start()


def _start_prepare(source, duration):
    key = (source, duration)
    with _jobs_lock:
        old = _preps.get(key)
    if old:
        old_job = _get_job(old)
        if old_job and old_job["status"] == "done":
            return old_job
    job = _new_job("prepare")

    def work(progress):
        prep = pipeline.prepare(source, duration, progress=progress)
        job["prep"] = prep
        with _jobs_lock:
            _preps[key] = job["id"]
        return {
            "start": prep["start"], "end": prep["end"],
            "duration": prep["duration"], "nwords": prep["nwords"],
            "method": prep["method"], "face_x": prep.get("face_x"),
            "lines": {
                "cinematic": _first_caption_line(prep["words"], "cinematic"),
                "karaoke": _first_caption_line(prep["words"], "karaoke"),
            },
        }
    _run(job, work)
    return job


def _start_render(source, duration, caption_y, style, script):
    job = _new_job("render")

    def work(progress):
        with _jobs_lock:
            prep_id = _preps.get((source, duration))
        prep_job = _get_job(prep_id) if prep_id else None
        if prep_job and prep_job["status"] == "done":
            prep = prep_job["prep"]
        else:
            prep = pipeline.prepare(source, duration, progress=progress)
        out = config.CACHE_DIR / "renders" / f"shortsclipper_{duration}s_{job['id']}.mp4"
        meta = pipeline.render_short(
            prep, caption_y=caption_y, caption_style=style,
            caption_script=script, output_path=out, force=True, progress=progress)
        return {"name": f"shortsclipper_{duration}s.mp4", "output": meta["output"]}
    _run(job, work)
    return job


def _preview_jpeg(job):
    from PIL import Image
    prep = job.get("prep")
    if not prep:
        return None
    img = Image.open(prep["frame"]).convert("RGB")
    w, h = img.size
    x, y, cw, ch = crop_box(w, h, face_x=prep.get("face_x"))
    img = img.crop((x, y, x + cw, y + ch)).resize((PREVIEW_W, PREVIEW_H))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


_BOUNDARY_RE = re.compile(rb"content-disposition: form-data; name=\"[^\"]*\"; filename=\"([^\"]*)\"", re.I)


class Handler(BaseHTTPRequestHandler):
    server_version = "ShortsClipper/0.3"

    # -- helpers -------------------------------------------------------
    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def log_message(self, fmt, *args):  # keep the terminal quiet
        log.debug(fmt, *args)

    # -- routes --------------------------------------------------------
    def do_GET(self):
        _last_beat["t"] = time.time()
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            html = INDEX.read_text(encoding="utf-8").replace("{{VERSION}}", __version__)
            self._send(200, html.encode(), "text/html; charset=utf-8")
            return
        if path == "/api/heartbeat":
            self._json({"ok": True})
            return
        m = re.fullmatch(r"/api/jobs/([0-9a-f]+)", path)
        if m:
            job = _get_job(m.group(1))
            if not job:
                self._json({"error": "unknown job"}, 404)
                return
            self._json({"status": job["status"], "progress": job["progress"],
                        "result": job["result"], "error": job["error"]})
            return
        m = re.fullmatch(r"/api/jobs/([0-9a-f]+)/frame\.jpg", path)
        if m:
            job = _get_job(m.group(1))
            data = _preview_jpeg(job) if job else None
            if data is None:
                self._json({"error": "no preview"}, 404)
            else:
                self._send(200, data, "image/jpeg")
            return
        m = re.fullmatch(r"/api/jobs/([0-9a-f]+)/download", path)
        if m:
            job = _get_job(m.group(1))
            if not job or job["status"] != "done" or job["kind"] != "render":
                self._json({"error": "not ready"}, 404)
                return
            out = Path(job["result"]["output"])
            if not out.exists():
                self._json({"error": "file gone"}, 404)
                return
            data = out.read_bytes()
            self._send(200, data, "video/mp4", {
                "Content-Disposition": f'attachment; filename="{job["result"]["name"]}"'})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        _last_beat["t"] = time.time()
        path = urlsplit(self.path).path
        if path == "/api/prepare":
            try:
                req = json.loads(self._body() or b"{}")
                source = str(req["source"]).strip()
                duration = int(req["duration"])
                assert source and duration in config.DURATIONS
            except Exception:
                self._json({"error": "bad request"}, 400)
                return
            job = _start_prepare(source, duration)
            self._json({"job": job["id"]})
            return
        if path == "/api/render":
            try:
                req = json.loads(self._body() or b"{}")
                source = str(req["source"]).strip()
                duration = int(req["duration"])
                caption_y = min(0.95, max(0.05, float(req["caption_y"])))
                style = req["style"] if req["style"] in ("cinematic", "karaoke") else config.DEFAULT_CAPTION_STYLE
                script = req["script"] if req["script"] in ("native", "hinglish") else config.DEFAULT_CAPTION_SCRIPT
                assert source and duration in config.DURATIONS
            except Exception:
                self._json({"error": "bad request"}, 400)
                return
            job = _start_render(source, duration, caption_y, style, script)
            self._json({"job": job["id"]})
            return
        if path == "/api/upload":
            ctype = self.headers.get("Content-Type", "")
            m = re.search(r"boundary=(.+)$", ctype)
            if not m:
                self._json({"error": "bad upload"}, 400)
                return
            boundary = m.group(1).strip().strip('"').encode()
            raw = self._body()
            filename, data = self._parse_multipart(raw, boundary)
            if filename is None:
                self._json({"error": "no file in upload"}, 400)
                return
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name) or "upload.mp4"
            up_dir = config.CACHE_DIR / "uploads"
            up_dir.mkdir(parents=True, exist_ok=True)
            dest = up_dir / f"{int(time.time())}_{safe}"
            dest.write_bytes(data)
            self._json({"source": str(dest)})
            return
        if path == "/api/shutdown":
            self._json({"ok": True})
            _shutdown.set()
            return
        self._json({"error": "not found"}, 404)

    @staticmethod
    def _parse_multipart(raw, boundary):
        for part in raw.split(b"--" + boundary):
            if b"\r\n\r\n" not in part:
                continue
            head, data = part.split(b"\r\n\r\n", 1)
            m = _BOUNDARY_RE.search(head)
            if not m:
                continue
            if data.endswith(b"\r\n"):
                data = data[:-2]
            if data.endswith(b"--"):
                data = data[:-2]
            return m.group(1).decode("utf-8", "replace"), data
        return None, None


def _watchdog():
    """Quit when the page is gone: once we've seen a heartbeat, 25 s without
    one means the tab was closed. Never while a pipeline job is running —
    a render must finish even if the user closed the tab."""
    while not _shutdown.wait(5):
        t = _last_beat["t"]
        if t is not None and time.time() - t > 25 and not _busy.locked():
            log.info("page closed — shutting down")
            _shutdown.set()


def main():
    config.ensure_dirs()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=_watchdog, daemon=True).start()

    def serve():
        while not _shutdown.is_set():
            server.handle_request()
    threading.Thread(target=serve, daemon=True).start()

    print(f"Shorts Clipper v{__version__} — running at {url}")
    print("Close the tab to quit (or Ctrl+C here).")
    import os
    if not os.environ.get("SHORTSCLIPPER_NO_OPEN"):
        try:
            webbrowser.open(url)
        except Exception:
            log.warning("could not open a browser; open %s manually", url)
    try:
        while not _shutdown.is_set():
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    server.server_close()


if __name__ == "__main__":
    main()
