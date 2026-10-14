"""Decision memory: what people and agents learn once and should not relearn every session.

A memory is a short, typed and dated fact: a decision (and why), a business rule, a gotcha, or a convention, with the
repository and code paths it concerns and where it came from. Each one is also a small Markdown document in the
document graph, so search, ask and enhance find it like any business rule; no model call is involved.

The topic is the identity: a new memory with the same type and title replaces the older one (the older text is kept
in `history`). After every repository update, memories whose code paths no longer exist are marked stale, because a
memory is only as good as the code it describes.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from . import jobs, providers
from . import settings as cfg

TYPES = ("decision", "rule", "gotcha", "convention")
_lock = threading.Lock()


def _file() -> Path:
    return cfg.path("memory") / "memories.json"


def _load() -> dict[str, dict]:
    f = _file()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _save(data: dict[str, dict]) -> None:
    f = _file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)
    jobs.tick()


def _name(kind: str, title: str) -> str:
    slug = re.sub(r"[^\w]+", "-", title.casefold()).strip("-")[:60] or "note"
    return f"memory-{kind}-{slug}"


def _markdown(m: dict) -> str:
    lines = [f"# {m['type'].capitalize()}: {m['title']}", "", m["text"].strip(), ""]
    if m.get("repo"):
        lines.append(f"- Repository: {m['repo']}")
    if m.get("paths"):
        lines.append("- Code: " + ", ".join(f"`{p}`" for p in m["paths"]))
    if m.get("source"):
        lines.append(f"- Source: {m['source']}")
    lines.append(f"- Recorded: {time.strftime('%Y-%m-%d', time.localtime(m['created']))}")
    return "\n".join(lines) + "\n"


def remember(kind: str, title: str, text: str, repo: str | None = None, paths: list[str] | None = None,
             source: str | None = None) -> dict:
    kind = (kind or "").strip().lower()
    if kind not in TYPES:
        raise ValueError(f"type must be one of {', '.join(TYPES)}")
    title, text = (title or "").strip(), (text or "").strip()
    if not title or not text:
        raise ValueError("title and text are required")
    name = _name(kind, title)
    with _lock:
        data = _load()
        old = data.get(name)
        m = {"name": name, "type": kind, "title": title[:200], "text": text[:4000], "repo": (repo or "").strip() or None,
             "paths": [p.replace("\\", "/") for p in (paths or []) if p][:20], "source": (source or "").strip() or None,
             "created": time.time(), "stale": [],
             "history": ((old or {}).get("history", []) + [{"text": old["text"], "created": old["created"]}])[-5:] if old else []}
        providers.docs().add_text(f"{name}.md", _markdown(m))
        data[name] = m
        _save(data)
    return {**m, "replaced": bool(old)}


def recall(query: str | None = None, repo: str | None = None, kind: str | None = None, limit: int = 20) -> list[dict]:
    """Memories, newest first; with a query, the ones the document search ranks for it first."""
    items = [m for m in _load().values() if (not repo or m.get("repo") in (None, repo)) and (not kind or m["type"] == kind)]
    items.sort(key=lambda m: -m["created"])
    if query and items:
        order: list[str] = []
        try:
            from . import query as qa
            a = qa.analyze(query)
            for c in providers.docs().search(query, a["keywords"] + a["variants"], 30, 4, a["concepts"]).get("chunks", []):
                n = str(c.get("doc", "")).removesuffix(".md")
                if n.startswith("memory-") and n not in order:
                    order.append(n)
        except Exception:
            pass
        words = [w for w in re.findall(r"\w{3,}", query.casefold())]
        literal = [m["name"] for m in items if any(w in (m["title"] + " " + m["text"]).casefold() for w in words)]
        rank = {n: i for i, n in enumerate(dict.fromkeys(order + literal))}
        items = sorted((m for m in items if m["name"] in rank), key=lambda m: rank[m["name"]])
    return items[:limit]


def forget(name: str) -> None:
    with _lock:
        data = _load()
        if data.pop(name, None) is None:
            raise KeyError(f"unknown memory {name}")
        docs = providers.docs()
        ids = [d["id"] for d in docs.documents() if d["name"] == f"{name}.md"]
        if ids:
            docs.delete(ids)
        _save(data)


def check_stale(repo: str, root: Path) -> int:
    """After a repository update: mark memories whose code paths no longer exist. Returns how many are stale."""
    with _lock:
        data = _load()
        changed = 0
        for m in data.values():
            if m.get("repo") != repo or not m.get("paths"):
                continue
            stale = [p for p in m["paths"] if not (root / p).exists()]
            if stale != m.get("stale"):
                m["stale"], changed = stale, changed + 1
        if changed:
            _save(data)
        return sum(1 for m in data.values() if m.get("repo") == repo and m.get("stale"))


def render(items: list[dict]) -> str:
    if not items:
        return "No memories yet. Record one with remember (type, title, text, repo, paths)."
    out = []
    for m in items:
        when = time.strftime("%Y-%m-%d", time.localtime(m["created"]))
        where = " · ".join(x for x in (m.get("repo") or "", ", ".join(m.get("paths") or [])) if x)
        stale = f" · STALE: {', '.join(m['stale'])} no longer exist" if m.get("stale") else ""
        out.append(f"- **[{m['type']}] {m['title']}** ({when}{' · ' + where if where else ''}{stale}): {m['text']}")
    return "\n".join(out)
