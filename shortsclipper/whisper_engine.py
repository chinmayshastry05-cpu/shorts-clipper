"""Shared faster-whisper model — loaded once, reused across transcript passes.

CPU-only on purpose: the app must run on any Linux laptop / VM, with or
without a GPU. The tiny model (~75 MB, downloaded once to the Hugging Face
cache on first use) is fast enough for short-form cutting.
"""

import gc

from .logutil import get_logger

log = get_logger("whisper")

_model = None
_model_size = None


def get_model(size):
    """Return the shared WhisperModel, (re)loading if the requested size changed."""
    global _model, _model_size
    if _model is not None and _model_size == size:
        return _model
    if _model is not None:
        free_model()
    from faster_whisper import WhisperModel
    log.info("loading faster-whisper '%s' on cpu (int8)...", size)
    _model = WhisperModel(size, device="cpu", compute_type="int8")
    _model_size = size
    return _model


def transcribe(wav_path, size, word_timestamps, language=None):
    """Transcribe a wav. Returns (segments, words, language).

    segments: [{start,end,text}]; words: [{start,end,word}] (empty if not requested).
    language: BCP-47 code to force (e.g. "hi"); None = autodetect. Short
    clips SHOULD pass the language detected on the full audio — on a 30 s
    Hinglish segment autodetect alone can land on the wrong language (Urdu
    instead of Hindi) and produce wrong-script captions.
    """
    model = get_model(size)
    seg_iter, info = model.transcribe(
        str(wav_path), word_timestamps=word_timestamps, vad_filter=True,
        language=language)
    segments, words = [], []
    for s in seg_iter:  # generator — iterate to actually run inference
        segments.append({"start": s.start, "end": s.end, "text": (s.text or "").strip()})
        if word_timestamps and s.words:
            for w in s.words:
                words.append({"start": w.start, "end": w.end, "word": w.word})
    log.info("transcribed %d segments, %d words (lang=%s)",
             len(segments), len(words), info.language)
    return segments, words, info.language


def free_model():
    """Release the model (call when a run is finished)."""
    global _model, _model_size
    if _model is None:
        return
    del _model
    _model = None
    _model_size = None
    gc.collect()
    log.debug("whisper model freed")
