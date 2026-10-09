"""Code vector index built with the corporate MULTILINGUAL embedding model (BRAIN_CODE_VECTORS=both).

Why a second code vector index: the code engine already keeps one (bundled code-embedding model, local, free),
but that model is English/code oriented, so "müşteriye iade nasıl yapılır" does not find `refund_payment`. The
corporate embedding model (e.g. bge-m3) is multilingual, so this index lets a Turkish question find English code
by meaning. Both are fused in search (reciprocal rank).

Storage: data/codevec/<project>.npz with the embedding model name, qualified names, content hashes and int8-quantised, L2-normalised
vectors (1 byte per dimension; ~75 MB for 75k symbols at 1024 dims). Updates are incremental: after every sync only
symbols whose text changed are embedded again; a different embedding model or dimension rebuilds the whole
index. Search is a NumPy dot product (milliseconds for 100k symbols).
"""
from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import llm, providers
from . import settings as cfg

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def enabled() -> bool:
    return cfg.get("BRAIN_CODE_VECTORS") == "both" and bool(cfg.get("BRAIN_EMBEDDING_MODEL"))


def _file(project: str) -> Path:
    return cfg.path("codevec") / f"{project}.npz"


def _load(project: str) -> dict | None:
    f = _file(project)
    if not f.exists():
        return None
    mtime = f.stat().st_mtime
    with _lock:
        hit = _cache.get(project)
        if hit and hit[0] == mtime:
            return hit[1]
    z = np.load(f, allow_pickle=False)
    data = {"qn": z["qn"].tolist(), "hash": z["hash"].tolist(), "vec": z["vec"],
            "model": str(z["model"]) if "model" in z.files else ""}
    with _lock:
        _cache[project] = (mtime, data)
    return data


def _quantise(m: np.ndarray) -> np.ndarray:
    m = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
    return np.clip(np.round(m * 127), -127, 127).astype(np.int8)


def update(project: str, log=lambda msg, progress=None: None) -> dict:
    """Embed new/changed symbols of a project; reuse the rest. Returns {symbols, embedded}."""
    if not enabled():
        return {"skipped": "BRAIN_CODE_VECTORS=local"}
    syms = providers.code().symbols(project, cfg.get("BRAIN_CODE_VECTORS_MAX"))
    if not syms:
        return {"symbols": 0, "embedded": 0}
    hashes = [hashlib.sha1(s["text"].encode("utf-8", "replace")).hexdigest()[:16] for s in syms]
    old = _load(project)
    if old is not None and (old["vec"].shape[1] != cfg.get("BRAIN_EMBEDDING_DIM")
                            or old["model"] != cfg.get("BRAIN_EMBEDDING_MODEL")):
        old = None   # the embedding model or dimension changed: vectors are not comparable, embed everything again
    reuse = {}
    if old:
        idx = {(q, h): i for i, (q, h) in enumerate(zip(old["qn"], old["hash"]))}
        reuse = {i: idx[(s["qn"], h)] for i, (s, h) in enumerate(zip(syms, hashes)) if (s["qn"], h) in idx}
    todo = [i for i in range(len(syms)) if i not in reuse]
    dim = None
    vec = None
    if old and reuse:
        dim = old["vec"].shape[1]
    batch = max(1, cfg.get("BRAIN_CODE_VECTORS_BATCH"))
    chunks = [todo[i:i + batch] for i in range(0, len(todo), batch)]
    done = [0]
    results: dict[int, list[float]] = {}

    def work(chunk):
        vs = llm.embed([syms[i]["text"] for i in chunk])
        for i, v in zip(chunk, vs):
            results[i] = v
        done[0] += len(chunk)
        log(f"{project}: code vectors {done[0]}/{len(todo)}", done[0] / max(1, len(todo)))
    if chunks:
        log(f"{project}: embedding {len(todo)} changed symbols ({len(reuse)} reused)")
        with ThreadPoolExecutor(max(1, cfg.get("BRAIN_CODE_VECTORS_PARALLEL"))) as pool:
            list(pool.map(work, chunks))
    if results:
        dim = len(next(iter(results.values())))
    if dim is None:
        return {"symbols": len(syms), "embedded": 0}
    vec = np.zeros((len(syms), dim), dtype=np.int8)
    if results:
        order = sorted(results)
        vec[order] = _quantise(np.asarray([results[i] for i in order], dtype=np.float32))
    if old is not None and old["vec"].shape[1] == dim:
        for i, j in reuse.items():
            vec[i] = old["vec"][j]
    f = _file(project)
    tmp = f.with_name(f.stem + ".tmp.npz")
    np.savez(tmp, qn=np.asarray([s["qn"] for s in syms]), hash=np.asarray(hashes), vec=vec,
             model=np.asarray(cfg.get("BRAIN_EMBEDDING_MODEL")))
    tmp.replace(f)
    return {"symbols": len(syms), "embedded": len(results)}


def search(query_vector: list[float], projects: list[str], k: int) -> list[dict]:
    """Nearest symbols to an (already embedded) query, as hit dicts with a `similarity`."""
    q = np.asarray(query_vector, dtype=np.float32)
    q = q / max(float(np.linalg.norm(q)), 1e-9)
    hits = []
    for proj in projects:
        data = _load(proj)
        if not data or data["vec"].shape[1] != q.shape[0]:
            continue
        sims = (data["vec"].astype(np.float32) @ q) / 127.0
        top = np.argsort(-sims)[:k]
        scored = {data["qn"][i]: float(sims[i]) for i in top}
        for h in providers.code().hits_for(proj, scored):
            h["similarity"] = round(scored[h["qn"]], 4)
            hits.append(h)
    hits.sort(key=lambda h: -h["similarity"])
    return providers.code().with_code(hits[:k])


def remove(project: str) -> None:
    _file(project).unlink(missing_ok=True)
    with _lock:
        _cache.pop(project, None)
