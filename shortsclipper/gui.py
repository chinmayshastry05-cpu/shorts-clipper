"""Desktop GUI: paste a URL or drop a local video, auto-cut, drag the caption
on a phone preview, download the short.

Tkinter (stdlib) + tkinterdnd2 for file drops (optional — the Browse button
always works). All heavy work runs in daemon threads so the UI stays alive.
"""

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import captions as captions_mod
from . import config, pipeline
from .editing import crop_box
from .logutil import get_logger

log = get_logger("gui")

PREVIEW_W, PREVIEW_H = 270, 480
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")


def _first_caption_line(words, style):
    """First caption line of the segment, as the preview shows it."""
    grouped = captions_mod._group_words(
        [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in words],
        max_words=3 if style == "cinematic" else 5,
        max_gap=0.7 if style == "cinematic" else 0.8)
    if not grouped:
        return "No speech in this window"
    text = " ".join(w["word"] for w in grouped[0])
    return text.upper() if style == "cinematic" else text


class App:
    def __init__(self, root):
        self.root = root
        root.title("Shorts Clipper — vertical shorts, offline")
        root.geometry("880x700")
        root.resizable(False, False)

        self.source = tk.StringVar()
        self.duration = tk.IntVar(value=30)
        self.style = tk.StringVar(value=config.DEFAULT_CAPTION_STYLE)
        self.script = tk.StringVar(value=config.DEFAULT_CAPTION_SCRIPT)
        self.caption_y = config.DEFAULT_CAPTION_Y
        self.prep = None
        self.busy = False
        self._jobs = queue.Queue()
        self._photo = None  # keep a ref or Tkinter garbage-collects it
        self._drag_start = None

        self._build()
        self._poll_jobs()

    # ---- layout ------------------------------------------------------

    def _build(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))
        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.Y)

        # Source
        ttk.Label(left, text="1. Video source", font=("", 11, "bold")).pack(anchor=tk.W)
        ttk.Label(left, text="Paste a video URL:").pack(anchor=tk.W, pady=(6, 0))
        url_row = ttk.Frame(left)
        url_row.pack(fill=tk.X, pady=2)
        ttk.Entry(url_row, textvariable=self.source, width=42).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(url_row, text="Load", command=self.on_preview).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(left, text="or drop a local video file onto the window,").pack(
            anchor=tk.W, pady=(10, 0))
        drop_row = ttk.Frame(left)
        drop_row.pack(fill=tk.X, pady=2)
        ttk.Button(drop_row, text="Browse…", command=self.on_browse).pack(side=tk.LEFT)
        ttk.Label(drop_row, text="mp4 / mov / mkv / webm").pack(side=tk.LEFT, padx=(6, 0))

        # Duration
        ttk.Label(left, text="2. Short length", font=("", 11, "bold")).pack(anchor=tk.W, pady=(16, 4))
        dur_row = ttk.Frame(left)
        dur_row.pack(anchor=tk.W)
        for d in config.DURATIONS:
            ttk.Radiobutton(dur_row, text=f"{d}s", variable=self.duration, value=d,
                            command=self._on_duration_change).pack(side=tk.LEFT, padx=(0, 12))

        # Caption style
        ttk.Label(left, text="3. Captions", font=("", 11, "bold")).pack(anchor=tk.W, pady=(16, 4))
        ttk.Label(left, text="Style:").pack(anchor=tk.W)
        ttk.Combobox(left, textvariable=self.style, values=["cinematic", "karaoke"],
                     state="readonly", width=16).pack(anchor=tk.W, pady=2)
        ttk.Label(left, text="Script:").pack(anchor=tk.W, pady=(6, 0))
        ttk.Combobox(left, textvariable=self.script, values=["native", "hinglish"],
                     state="readonly", width=16).pack(anchor=tk.W, pady=2)

        # Actions
        ttk.Label(left, text="4. Export", font=("", 11, "bold")).pack(anchor=tk.W, pady=(16, 4))
        btn_row = ttk.Frame(left)
        btn_row.pack(anchor=tk.W)
        self.preview_btn = ttk.Button(btn_row, text="Preview", command=self.on_preview)
        self.preview_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.download_btn = ttk.Button(btn_row, text="Download short", command=self.on_download)
        self.download_btn.pack(side=tk.LEFT)

        # Status + log
        self.status = ttk.Label(left, text="Ready — paste a URL or drop a video.",
                                 wraplength=380)
        self.status.pack(anchor=tk.W, pady=(14, 2))
        self.caption_label = ttk.Label(
            left, text=f"Caption: {int(self.caption_y * 100)}% from top — drag it on the phone.",
            wraplength=380)
        self.caption_label.pack(anchor=tk.W, pady=(0, 6))
        self.log_text = tk.Text(left, height=9, width=52, state=tk.DISABLED)
        self.log_text.pack(anchor=tk.W, pady=2)

        # Phone preview
        ttk.Label(right, text="Phone preview", font=("", 11, "bold")).pack(anchor=tk.W)
        ttk.Label(right, text="Drag the caption to move it.").pack(anchor=tk.W, pady=(0, 6))
        self.canvas = tk.Canvas(right, width=PREVIEW_W, height=PREVIEW_H,
                                bg="#111111", highlightthickness=1,
                                highlightbackground="#444444")
        self.canvas.pack()
        self.canvas.create_text(PREVIEW_W // 2, PREVIEW_H // 2,
                                text="Your video\npreview appears here",
                                fill="#888888", justify=tk.CENTER, tags=("placeholder",))
        self.canvas.tag_bind("caption", "<ButtonPress-1>", self._drag_start)
        self.canvas.tag_bind("caption", "<B1-Motion>", self._drag_move)
        self.canvas.tag_bind("caption", "<ButtonRelease-1>", self._drag_end)

    # ---- actions ------------------------------------------------------

    def on_browse(self):
        path = filedialog.askopenfilename(
            title="Choose a video",
            filetypes=[("Video files", " ".join(f"*{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")])
        if path:
            self.source.set(path)
            self.on_preview()

    def on_preview(self):
        src = self.source.get().strip()
        if not src:
            messagebox.showwarning("No source", "Paste a video URL or pick a local file first.")
            return
        self._run_thread(lambda: self._do_prepare(src), self._after_prepare)

    def on_download(self):
        src = self.source.get().strip()
        if not src:
            messagebox.showwarning("No source", "Paste a video URL or pick a local file first.")
            return
        out = filedialog.asksaveasfilename(
            title="Save short as",
            defaultextension=".mp4",
            initialdir=str(config.DEFAULT_OUTPUT),
            initialfile=f"shortsclipper_{self.duration.get()}s.mp4",
            filetypes=[("MP4 video", "*.mp4")])
        if not out:
            return
        self._run_thread(lambda: self._do_export(src, out), self._after_export)

    def _on_duration_change(self):
        # A new length means a new window — the preview refreshes on next Preview.
        self.prep = None

    # ---- background work ----------------------------------------------

    def _run_thread(self, fn, on_done):
        if self.busy:
            return
        self.busy = True
        self.preview_btn.config(state=tk.DISABLED)
        self.download_btn.config(state=tk.DISABLED)

        def target():
            try:
                result = fn()
                self._jobs.put(("done", on_done, result))
            except Exception as e:  # noqa: BLE001 - surfaced in the UI
                self._jobs.put(("error", on_done, e))

        threading.Thread(target=target, daemon=True).start()

    def _poll_jobs(self):
        try:
            while True:
                kind, on_done, payload = self._jobs.get_nowait()
                self.busy = False
                self.preview_btn.config(state=tk.NORMAL)
                self.download_btn.config(state=tk.NORMAL)
                if kind == "error":
                    self._set_status(f"Error: {payload}")
                    self._log(f"ERROR: {payload}")
                    log.error("%s", payload)
                else:
                    on_done(payload)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_jobs)

    def _do_prepare(self, src):
        self._set_status_async("Getting transcript…")
        return pipeline.prepare(src, self.duration.get(),
                                progress=self._set_status_async)

    def _do_export(self, src, out):
        if self.prep is None or self.prep["source"] != src:
            prep = pipeline.prepare(src, self.duration.get(),
                                    progress=self._set_status_async)
        else:
            prep = self.prep
        meta = pipeline.render_short(
            prep, caption_y=self.caption_y, caption_style=self.style.get(),
            caption_script=self.script.get(), output_path=out, force=True,
            progress=self._set_status_async)
        return meta

    def _after_prepare(self, prep):
        self.prep = prep
        self._draw_preview(prep)
        self._set_status(
            f"Ready — {prep['duration']:.0f}s window at "
            f"{prep['start']:.1f}-{prep['end']:.1f}s ({prep['nwords']} words). "
            "Drag the caption, then Download short.")
        self._log(f"window {prep['start']:.1f}-{prep['end']:.1f}s, "
                  f"{prep['nwords']} words, via {prep['method']}")
        fx = prep.get("face_x")
        if fx is not None:
            self._log(f"speaker found at {fx * 100:.0f}% of frame width — crop anchored on them")

    def _after_export(self, meta):
        self._set_status(f"Saved: {meta['output']}")
        self._log(f"saved {meta['output']}")
        messagebox.showinfo("Short saved", f"Saved to:\n{meta['output']}")

    # ---- preview + caption drag -----------------------------------------

    def _draw_preview(self, prep):
        from PIL import Image, ImageTk
        img = Image.open(prep["frame"]).convert("RGB")
        w, h = img.size
        x, y, cw, ch = crop_box(w, h, face_x=prep.get("face_x"))
        img = img.crop((x, y, x + cw, y + ch)).resize((PREVIEW_W, PREVIEW_H))
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor=tk.NW, tags=("frame",))
        self._draw_caption(prep)

    def _draw_caption(self, prep):
        self.canvas.delete("caption")
        text = _first_caption_line(prep["words"], self.style.get())
        cy = int(self.caption_y * PREVIEW_H)
        # Dark pill behind the text so it reads over any frame. width= wraps
        # the preview line like the exporter's WrapStyle 1 does.
        tmp = self.canvas.create_text(PREVIEW_W // 2, cy, text=text,
                                      font=("", 15, "bold"), fill="white",
                                      width=PREVIEW_W - 20, tags=("caption",))
        x0, y0, x1, y1 = self.canvas.bbox(tmp)
        self.canvas.delete(tmp)
        pad_x, pad_y = 10, 5
        self.canvas.create_rectangle(x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y,
                                     fill="black", outline="", tags=("caption",))
        self.canvas.create_text(PREVIEW_W // 2, cy, text=text,
                                font=("", 15, "bold"), fill="white",
                                width=PREVIEW_W - 20, tags=("caption",))
        self.canvas.tag_raise("caption")

    def _drag_start(self, event):
        self._drag_start = (event.x, event.y)

    def _drag_move(self, event):
        if self._drag_start is None or self.prep is None:
            return
        dy = event.y - self._drag_start[1]
        self.canvas.move("caption", 0, dy)
        self._drag_start = (event.x, event.y)

    def _drag_end(self, event):
        if self.prep is None:
            return
        # Caption vertical center after the drag -> new caption_y.
        bbox = self.canvas.bbox("caption")
        if not bbox:
            return
        cy = (bbox[1] + bbox[3]) / 2.0
        self.caption_y = min(0.95, max(0.05, cy / PREVIEW_H))
        self.caption_label.config(
            text=f"Caption: {int(self.caption_y * 100)}% from top — drag it on the phone.")
        self._log(f"caption moved to {int(self.caption_y * 100)}% from top")

    # ---- status / log ---------------------------------------------------

    def _set_status(self, msg):
        self.status.config(text=msg)

    def _set_status_async(self, msg):
        # Called from worker threads — marshal onto the UI thread.
        self.root.after(0, lambda: self._set_status(msg))

    def _log(self, msg):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)


def main():
    import sys
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
        root = TkinterDnD.Tk()
        has_dnd = True
    except Exception:
        root = tk.Tk()
        has_dnd = False
    app = App(root)
    if has_dnd:
        def on_drop(event):
            paths = root.tk.splitlist(event.data)
            if paths:
                app.source.set(paths[0])
                app.on_preview()
        root.drop_target_register(DND_FILES)
        root.dnd_bind("<<Drop>>", on_drop)
    # "Open with" / AppImage argv: a file path or URL as the first argument.
    if len(sys.argv) > 1 and sys.argv[1] != "--cli":
        app.source.set(sys.argv[1])
        root.after(200, app.on_preview)
    log.info("GUI started (drag-and-drop: %s)", "on" if has_dnd else "off")
    root.mainloop()
