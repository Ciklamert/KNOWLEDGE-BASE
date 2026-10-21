"""Local OCR, the fallback for pictures and scanned pages when the vision model is missing, slow or failing.

RapidOCR (ONNX Runtime, CPU, models bundled in the wheel, no download at run time) is an optional install:
setup installs it from wheels/ocr/ when that folder is shipped. Without it, this module reports itself unavailable
and pictures wait for the vision model as before. About 1-2 seconds per picture on one CPU core. Turkish letters
lose their accents (search folds them anyway); the vision model, when it answers later, adds the full description.
"""
from __future__ import annotations

import threading

from . import settings as cfg

_lock = threading.Lock()
_engine: dict = {}


def available() -> bool:
    if cfg.get("BRAIN_OCR") == "off":
        return False
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:   # not installed, or onnxruntime cannot load on this machine
        return False


def read(data: bytes) -> str:
    """The text in a picture, line by line (lines below BRAIN_OCR_MIN_SCORE confidence left out); "" if none."""
    with _lock:   # one picture at a time: the engine is not thread-safe and uses every core anyway
        if "e" not in _engine:
            from rapidocr_onnxruntime import RapidOCR
            _engine["e"] = RapidOCR()
        result, _ = _engine["e"](data)
    floor = cfg.get("BRAIN_OCR_MIN_SCORE")
    return "\n".join(str(text) for _box, text, score in (result or []) if float(score) >= floor and str(text).strip())
