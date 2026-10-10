"""Plug-in contracts. The rest of the system talks ONLY to these two interfaces, so the code-graph engine and
the document-graph engine can be swapped by changing BRAIN_CODE_PROVIDER / BRAIN_DOC_PROVIDER:

    BRAIN_CODE_PROVIDER=codebase_memory          -> brain/providers/codebase_memory.py : Provider
    BRAIN_DOC_PROVIDER=lightrag                  -> brain/providers/lightrag.py        : Provider
    BRAIN_DOC_PROVIDER=mycompany.brain_ext:MyDocs   -> any importable class implementing DocGraph

A new provider implements the abstract methods below; everything optional has a safe default.
See docs/08-PLUGINS.md for a step-by-step guide.
"""
from __future__ import annotations

import importlib
import threading
from abc import ABC, abstractmethod

from .. import settings as cfg


class Engine(ABC):
    """Common life cycle. state: stopped | starting | ready | error."""
    name = "engine"

    def __init__(self):
        self.state, self.detail = "stopped", ""

    def start(self) -> None:          # make the engine ready (may block; called in a background job)
        self.state = "ready"

    def stop(self) -> None:
        self.state = "stopped"

    def health(self) -> dict:
        return {"provider": self.name, "state": self.state, "detail": self.detail}


class CodeGraph(Engine):
    """A code knowledge graph with search. One 'project' per indexed tree (repository or repository@branch)."""

    @abstractmethod
    def index(self, project: str, path: str, log=lambda msg, progress=None: None) -> dict:
        """(Re)index the source tree at `path` as `project` (incremental where possible). Returns stats."""

    @abstractmethod
    def remove(self, project: str) -> None: ...

    @abstractmethod
    def projects(self) -> list[dict]:
        """[{name, root, indexed_at, nodes, edges}]"""

    @abstractmethod
    def search(self, query: str, keywords: list[str], projects: list[str], k: int, mode: str = "hybrid") -> list[dict]:
        """No-LLM search; mode = hybrid | semantic | lexical. `keywords` come from the prompt analysis: ranked key terms first,
        then search variants (stems, identifier parts). Hits: {project, id, qn, name, label, path, line1, line2,
        score, code}."""

    def relations(self, hits: list[dict], limit: int = 30) -> list[dict]:
        """[{type, a, b}] edges around the hits."""
        return []

    def symbols(self, project: str, limit: int = 200000) -> list[dict]:
        """[{qn, text}] for every function/class/route: what the corporate code vector index embeds.
        Return [] if the engine cannot list symbols (the index is then simply not built)."""
        return []

    def hits_for(self, project: str, scored: dict[str, float]) -> list[dict]:
        """{qualified name: score} -> hit dicts in the shape search() returns (used by the vector index)."""
        return []

    def with_code(self, hits: list[dict]) -> list[dict]:
        """Attach source lines (`code`) to hits."""
        return hits

    def neighbors(self, hits: list[dict], limit: int = 20) -> list[dict]:
        """Graph expansion: hits wired to the given hits (callers, callees, parents); `matched` says how."""
        return []

    def annotate(self, hits: list[dict]) -> list[dict]:
        """Add `signature`, `callers`, `callees`, `parents` to hits where the engine knows them."""
        return hits

    def files(self, project: str, pattern: str = "*", limit: int = 300) -> list[str]:
        """Indexed file paths matching a glob (the knowledge-base replacement for `glob`)."""
        return []

    def read(self, project: str, path: str, start: int = 1, end: int | None = None) -> dict:
        """Numbered lines of an indexed file (the replacement for `read`)."""
        raise ValueError("reading files is not supported by this code provider")

    def grep(self, project: str, pattern: str, regex: bool = False, file_pattern: str | None = None, limit: int = 30,
             mode: str = "matches", path: str | None = None) -> str:
        """Text / regex search over the indexed source (the replacement for `grep`)."""
        raise ValueError("text search is not supported by this code provider")

    def symbol(self, name: str, projects: list[str], source: str = "auto") -> str:
        """Markdown: location, signature, source (auto | full | none), callers, callees of a symbol."""
        return "symbol lookup is not supported by this code provider"

    def exact(self, terms: list[str], projects: list[str], limit: int = 10) -> list[dict]:
        """Hits whose name equals an identifier, or that live in a file path, named in the question."""
        return []

    def outline(self, project: str, path: str) -> str:
        """Declarations of one file with line ranges (read it before reading lines)."""
        raise ValueError("file outlines are not supported by this code provider")

    def tool(self, name: str, args: dict) -> str:
        """Engine-specific deep tools: trace, snippet, architecture (overview), query_graph, file_outline."""
        raise ValueError(f"tool {name} is not supported by this code provider")

    def graph(self, project: str, limit: int = 1200) -> dict:
        """UI overview: {nodes:[{id,name,kind,...}], links:[{source,target,type}]}"""
        return {"nodes": [], "links": []}

    def ego(self, project: str, node_id: int, depth: int = 1) -> dict:
        return {"nodes": [], "links": []}

    def node(self, project: str, node_id: int) -> dict | None:
        return None

    def find(self, q: str, projects: list[str], limit: int = 25) -> list[dict]:
        return []


class DocGraph(Engine):
    """A document knowledge graph with search."""

    @abstractmethod
    def upload(self, filename: str, data: bytes) -> dict: ...

    @abstractmethod
    def add_text(self, name: str, text: str) -> dict: ...

    @abstractmethod
    def delete(self, doc_ids: list[str]) -> dict: ...

    @abstractmethod
    def documents(self) -> list[dict]:
        """[{id, name, status, chunks, updated_at, error}]"""

    @abstractmethod
    def search(self, query: str, keywords: list[str], chunks: int, top_k: int,
               concepts: list[str] | None = None) -> dict:
        """No-chat-call retrieval. `keywords` = ranked key terms + variants, `concepts` = multi-word themes, both
        from the prompt analysis. Returns {chunks:[{source, content}], entities:[{name,type,description}],
        relations:[...]}"""

    def pipeline(self) -> dict:
        """Ingestion progress: {busy, job, message, batch, batches, docs, history}"""
        return {}

    def graph(self, label: str = "*", max_nodes: int = 600, depth: int = 3) -> dict:
        """UI graph: {nodes:[{id,name,kind,description}], links:[{source,target,type,description}], truncated}"""
        return {"nodes": [], "links": [], "truncated": False}

    def markdown(self, name: str) -> str:
        """The Markdown a document was converted to before ingestion (UI preview)."""
        raise KeyError(f"no converted Markdown for {name}")

    def labels(self, q: str = "") -> list[str]:
        return []


_lock = threading.Lock()
_loaded: dict[str, Engine] = {}


def _load(kind: str) -> Engine:
    spec = cfg.get("BRAIN_CODE_PROVIDER" if kind == "code" else "BRAIN_DOC_PROVIDER")
    mod, _, cls = spec.partition(":")
    module = importlib.import_module(mod if "." in mod else f"{__name__}.{mod}")
    engine = getattr(module, cls or "Provider")()
    base = CodeGraph if kind == "code" else DocGraph
    if not isinstance(engine, base):
        raise TypeError(f"{spec} must implement {base.__name__}")
    return engine


def get(kind: str) -> Engine:
    """The active provider for 'code' or 'docs' (created on first use)."""
    with _lock:
        if kind not in _loaded:
            _loaded[kind] = _load(kind)
        return _loaded[kind]


def code() -> CodeGraph:
    return get("code")  # type: ignore[return-value]


def docs() -> DocGraph:
    return get("docs")  # type: ignore[return-value]


def reload(kind: str) -> Engine:
    """Stop and re-create a provider (after its settings changed or the plug-in was switched), then start it."""
    with _lock:
        old = _loaded.pop(kind, None)
    if old is not None:
        old.stop()
    engine = get(kind)
    engine.start()
    return engine
