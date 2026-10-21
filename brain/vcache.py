"""Persistent embedding cache: one vector per (embedding model, text), shared by document passages, concept names,
code symbols and questions. Every embedding goes through llm.embed, which asks this cache first, so re-indexing,
re-uploads, new document versions and branch overlays (whose symbols mostly equal the tracked branch's) only send
the texts that really changed to the slow API.

Storage: data/vectors.db (SQLite), key = SHA-1 of model + text, value = the L2-normalised vector as int8 (1 byte per
dimension, the precision every index here stores anyway), day = last day it was used. Entries not used for
BRAIN_VECTOR_CACHE_DAYS are removed by prune() (called once a day by the scheduler). Deleting the file is safe.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time

import numpy as np

from . import settings as cfg

_lock = threading.Lock()
_db: dict = {}


def enabled() -> bool:
    return cfg.get("BRAIN_VECTOR_CACHE")


def _file():
    return cfg.data_dir() / "vectors.db"


def _conn() -> sqlite3.Connection:
    f = _file()
    c = _db.get("conn")
    if c is None or _db.get("file") != f:
        f.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(f, check_same_thread=False, timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE IF NOT EXISTS v (k BLOB PRIMARY KEY, vec BLOB NOT NULL, day INTEGER NOT NULL) WITHOUT ROWID")
        _db.update(conn=c, file=f)
    return c


def _today() -> int:
    return int(time.time() // 86400)


def _key(model: str, text: str) -> bytes:
    return hashlib.sha1(f"{model}\0{text}".encode("utf-8", "replace")).digest()


def get(model: str, texts: list[str]) -> dict[int, list[float]]:
    """The cached vectors of these texts, {position: vector}."""
    keys = [_key(model, t) for t in texts]
    out, today = {}, _today()
    with _lock:
        c = _conn()
        for i in range(0, len(keys), 500):
            part = keys[i:i + 500]
            rows = c.execute(f"SELECT k, vec FROM v WHERE k IN ({','.join('?' * len(part))})", part).fetchall()
            found = {k: v for k, v in rows}
            for j, k in enumerate(part, i):
                if k in found:
                    out[j] = (np.frombuffer(found[k], dtype=np.int8).astype(np.float32) / 127.0).tolist()
        if out:
            c.executemany("UPDATE v SET day = ? WHERE k = ? AND day < ?", [(today, keys[i], today) for i in out])
            c.commit()
    return out


def put(model: str, texts: list[str], vectors: list[list[float]]) -> None:
    if not vectors:
        return
    m = np.asarray(vectors, dtype=np.float32)
    m = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
    q = np.clip(np.round(m * 127), -127, 127).astype(np.int8)
    today = _today()
    with _lock:
        c = _conn()
        c.executemany("INSERT OR REPLACE INTO v VALUES (?, ?, ?)",
                      [(_key(model, t), v.tobytes(), today) for t, v in zip(texts, q)])
        c.commit()


def prune() -> int:
    """Remove the vectors not used for BRAIN_VECTOR_CACHE_DAYS days (0 = keep forever). Returns how many."""
    days = cfg.get("BRAIN_VECTOR_CACHE_DAYS")
    if days <= 0 or not _file().exists():
        return 0
    with _lock:
        c = _conn()
        n = c.execute("DELETE FROM v WHERE day < ?", (_today() - days,)).rowcount
        c.commit()
    return n


def stats() -> dict:
    f = _file()
    if not f.exists():
        return {"vectors": 0, "mb": 0.0}
    with _lock:
        n = _conn().execute("SELECT count(*) FROM v").fetchone()[0]
    return {"vectors": n, "mb": round(f.stat().st_size / 1e6, 1)}
