"""Document graph provider: LightRAG (HKU, MIT), the upstream `lightrag-server`, unmodified, as a private child
process on 127.0.0.1. LightRAG extracts entities and relations with the corporate chat model, embeds chunks
with the corporate embedding model, and stores graph + vectors + key-value data as local files.

Every LightRAG variable is derived from this system's settings (BRAIN_LLM_*, LIGHTRAG_*) and can be extended
with raw pass-through variables (LIGHTRAG__NAME=value). Every document is first converted to Markdown
(convert.py): `<file>.md`, or `<file>.textpack` (Markdown + images) when it has pictures, so tables keep their
structure and images are described by the vision model (BRAIN_VLM_MODEL) inside LightRAG's native pipeline.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from .. import settings as cfg
from . import DocGraph, convert

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def server_exe() -> str | None:
    bindir = Path(sys.executable).parent
    for name in ("lightrag-server.exe", "lightrag-server"):
        if (bindir / name).exists():
            return str(bindir / name)
    return shutil.which("lightrag-server")


def _display_name(file_path: str) -> str:
    """'report.docx.md' / 'deck.pptx.textpack' -> the name the user uploaded."""
    name = Path(file_path.split("<SEP>")[0]).name
    for suffix in (".textpack", ".md"):
        if name.endswith(suffix) and Path(name[: -len(suffix)]).suffix:
            return name[: -len(suffix)]
    return name


class Provider(DocGraph):
    name = "lightrag"

    def __init__(self):
        super().__init__()
        self.port = cfg.get("LIGHTRAG_PORT")
        self.url = f"http://127.0.0.1:{self.port}"
        self.work, self.inputs, self.originals = cfg.path("lightrag"), cfg.path("documents"), cfg.path("originals")
        self.log_file = cfg.path("logs") / "lightrag.log"
        self.proc: subprocess.Popen | None = None
        self.restarts, self._stopping = 0, False

    # ---------------------------------------------------------------- child process
    def parser_rule(self) -> str:
        if cfg.get("LIGHTRAG_PARSER"):
            return cfg.get("LIGHTRAG_PARSER")
        # everything arrives as .md or .textpack (convert.py) and is read by the structure-aware native engine;
        # legacy (plain text) is only the catch-all
        return "*:native-iteP,*:legacy-R" if cfg.get("BRAIN_VLM_MODEL") else "*:native-teP,*:legacy-R"

    def child_env(self) -> dict:
        llm_url, llm_key = cfg.get("BRAIN_LLM_BASE_URL"), cfg.get("BRAIN_LLM_API_KEY")
        env = {**os.environ,
               "HOST": "127.0.0.1", "PORT": str(self.port), "WORKING_DIR": str(self.work), "INPUT_DIR": str(self.inputs),
               "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
               "LLM_BINDING": "openai", "LLM_MODEL": cfg.model("lightrag"),
               "LLM_BINDING_HOST": llm_url, "LLM_BINDING_API_KEY": llm_key,
               "EMBEDDING_BINDING": "openai", "EMBEDDING_MODEL": cfg.get("BRAIN_EMBEDDING_MODEL"),
               "EMBEDDING_DIM": str(cfg.get("BRAIN_EMBEDDING_DIM")),
               "EMBEDDING_BINDING_HOST": cfg.get("BRAIN_EMBEDDING_BASE_URL") or llm_url,
               "EMBEDDING_BINDING_API_KEY": cfg.get("BRAIN_EMBEDDING_API_KEY") or llm_key,
               "TIMEOUT": str(cfg.get("LIGHTRAG_TIMEOUT")), "LLM_TIMEOUT": str(cfg.get("LIGHTRAG_LLM_TIMEOUT")),
               "EMBEDDING_TIMEOUT": str(cfg.get("LIGHTRAG_EMBEDDING_TIMEOUT")),
               "MAX_ASYNC": str(cfg.get("LIGHTRAG_MAX_ASYNC")), "RERANK_BINDING": "null",
               "MAX_PARALLEL_INSERT": str(cfg.get("LIGHTRAG_MAX_PARALLEL_INSERT")),
               "SUMMARY_LANGUAGE": cfg.get("LIGHTRAG_SUMMARY_LANGUAGE"),
               "CHUNK_SIZE": str(cfg.get("LIGHTRAG_CHUNK_SIZE")),
               "CHUNK_OVERLAP_SIZE": str(cfg.get("LIGHTRAG_CHUNK_OVERLAP")),
               "LIGHTRAG_PARSER": self.parser_rule(),
               "VLM_PROCESS_ENABLE": "true" if cfg.get("BRAIN_VLM_MODEL") else "false",
               "NATIVE_MD_IMAGE_DOWNLOAD_ENABLED": "false",   # air-gapped: never fetch remote images
               "WEBUI_TITLE": "AI-BRAIN documents"}
        if cfg.get("BRAIN_VLM_MODEL"):
            env["VLM_LLM_MODEL"] = cfg.get("BRAIN_VLM_MODEL")
        if cfg.get("BRAIN_CA_BUNDLE"):
            env["SSL_CERT_FILE"] = env["REQUESTS_CA_BUNDLE"] = cfg.get("BRAIN_CA_BUNDLE")
        for k in ("NO_PROXY", "no_proxy"):  # its localhost traffic must never go through a corporate proxy
            env[k] = ",".join(x for x in (env.get(k, ""), "127.0.0.1,localhost") if x)
        env.update(cfg.passthrough("LIGHTRAG__"))
        return env

    def _spawn(self) -> None:
        exe = server_exe()
        if not exe:
            raise RuntimeError("lightrag-server is not installed in this Python environment (run setup)")
        log = open(self.log_file, "a", encoding="utf-8")
        log.write(f"\n===== {time.ctime()} starting {exe} on {self.url} (parser {self.parser_rule()}) =====\n")
        log.flush()
        # lightrag-server asks "continue? (yes/NO)" when its working directory has no .env and stdin looks like a
        # terminal (on Windows even NUL does). A placeholder .env avoids the question; all real values come from
        # the environment below, which LightRAG's load_dotenv(override=False) never overrides.
        marker = self.work / ".env"
        if not marker.exists():
            marker.write_text("# Managed by the knowledge base: settings come from its own .env via environment.\n",
                              encoding="utf-8")
        self.proc = subprocess.Popen([exe], env=self.child_env(), cwd=str(self.work), stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)

    def start(self) -> None:
        self._stopping = False
        self.state, self.detail = "starting", "starting LightRAG"
        if not cfg.get("BRAIN_LLM_BASE_URL") or not cfg.get("BRAIN_EMBEDDING_MODEL"):
            self.state, self.detail = "error", "set BRAIN_LLM_BASE_URL, BRAIN_LLM_MODEL and BRAIN_EMBEDDING_MODEL first"
            return
        try:
            if not self.healthy():
                self._spawn()
            end = time.time() + cfg.get("LIGHTRAG_STARTUP_TIMEOUT")
            while time.time() < end:
                if self.healthy():
                    self.state, self.detail = "ready", f"LightRAG on {self.url}"
                    break
                if self.proc is not None and self.proc.poll() is not None:
                    raise RuntimeError(f"LightRAG exited with code {self.proc.returncode}:\n{self.log_tail(12)}")
                time.sleep(1)
            else:
                raise RuntimeError(f"LightRAG not healthy after {cfg.get('LIGHTRAG_STARTUP_TIMEOUT')}s:\n{self.log_tail(12)}")
        except Exception as exc:
            self.state, self.detail = "error", str(exc)
            return
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _watchdog(self) -> None:
        proc = self.proc
        while not self._stopping and proc is self.proc:
            time.sleep(5)
            if proc is not None and proc.poll() is not None and not self._stopping:
                self.state, self.detail = "error", f"LightRAG exited ({proc.returncode}); restarting\n{self.log_tail(8)}"
                if self.restarts >= 5:
                    self.detail = "LightRAG keeps crashing; see the log below and fix the settings\n" + self.log_tail(12)
                    return
                self.restarts += 1
                self.start()
                return

    def stop(self) -> None:
        self._stopping = True
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.state = "stopped"

    def healthy(self) -> bool:
        try:
            return httpx.get(self.url + "/health", timeout=3, trust_env=False).status_code == 200
        except httpx.HTTPError:
            return False

    def health(self) -> dict:
        h = super().health()
        h.update(url=self.url, parser=self.parser_rule(), vision=bool(cfg.get("BRAIN_VLM_MODEL")))
        if self.state == "error":
            h["log"] = self.log_tail(15)
        return h

    def log_tail(self, n: int = 30) -> str:
        try:
            return "\n".join(self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
        except OSError:
            return ""

    # ---------------------------------------------------------------- REST helpers
    def _req(self, method: str, path: str, timeout: float | None = None, **kw):
        if self.state != "ready" and not self.healthy():
            raise RuntimeError(f"document engine is {self.state}: {self.detail[:300]}")
        try:
            r = httpx.request(method, self.url + path, timeout=timeout or cfg.get("LIGHTRAG_REQUEST_TIMEOUT"),
                              trust_env=False, **kw)
        except httpx.TimeoutException:
            raise RuntimeError(f"LightRAG {path}: timeout") from None
        if r.status_code >= 400:
            raise RuntimeError(f"LightRAG {path}: HTTP {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    # ---------------------------------------------------------------- documents
    def upload(self, filename: str, data: bytes) -> dict:
        safe = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", Path(filename).name).strip() or "document"
        (self.originals / safe).write_bytes(data)
        name, payload, md = convert.to_markdown(safe, data)   # every document goes in as Markdown
        (cfg.path("converted") / f"{safe}.md").write_text(md, encoding="utf-8")
        res = self._req("POST", "/documents/upload", files={"file": (name, payload)})
        return {"file": safe, "stored_as": name, "converted": name != safe, "markdown_chars": len(md),
                "status": res.get("status"), "message": res.get("message"), "track_id": res.get("track_id")}

    def markdown(self, name: str) -> str:
        """The Markdown a document was converted to (kept in data/converted/)."""
        f = cfg.path("converted") / f"{Path(name).name}.md"
        if not f.exists():
            raise KeyError(f"no converted Markdown for {name}")
        return f.read_text(encoding="utf-8")

    def add_text(self, name: str, text: str) -> dict:
        return self._req("POST", "/documents/text", json={"text": text, "file_source": name})

    def delete(self, doc_ids: list[str]) -> dict:
        return self._req("DELETE", "/documents/delete_document",
                         json={"doc_ids": doc_ids, "delete_file": True, "delete_llm_cache": True})

    def documents(self) -> list[dict]:
        docs, page = [], 1
        while page < 500:
            res = self._req("POST", "/documents/paginated", json={"page": page, "page_size": 200,
                                                                   "sort_field": "updated_at", "sort_direction": "desc"})
            for d in res.get("documents", []):
                docs.append({"id": d.get("id"), "name": _display_name(str(d.get("file_path", ""))),
                             "status": d.get("status"), "chunks": d.get("chunks_count"),
                             "updated_at": d.get("updated_at"), "error": d.get("error_msg") or d.get("error"),
                             "summary": (d.get("content_summary") or "")[:200]})
            if not res.get("pagination", {}).get("has_next"):
                break
            page += 1
        return docs

    def pipeline(self) -> dict:
        try:
            p = self._req("GET", "/documents/pipeline_status", timeout=10)
        except Exception as exc:
            return {"error": str(exc)}
        return {"busy": p.get("busy"), "job": p.get("job_name"), "message": p.get("latest_message"),
                "batch": p.get("cur_batch"), "batches": p.get("batchs"), "docs": p.get("docs"),
                "history": (p.get("history_messages") or [])[-8:]}

    # ---------------------------------------------------------------- retrieval (no chat calls)
    def search(self, query: str, keywords: list[str], chunks: int, top_k: int,
               concepts: list[str] | None = None) -> dict:
        """Supplying hl/ll keywords makes LightRAG skip its LLM keyword-extraction step, so this path makes
        embedding calls only and no chat-completion call. High-level keywords = the prompt's concepts (themes,
        matched against relations), low-level keywords = its key terms (matched against entities)."""
        res = self._req("POST", "/query/data", timeout=cfg.get("BRAIN_SEARCH_TIMEOUT"), json={
            "query": query[:2000], "mode": cfg.get("LIGHTRAG_QUERY_MODE"), "top_k": top_k, "chunk_top_k": chunks,
            "hl_keywords": concepts or [query[:300]], "ll_keywords": keywords or [query[:200]]})
        d = res.get("data", res) or {}

        def src(x):
            return _display_name(str(x.get("file_path", "?")))
        return {"chunks": [{"source": src(c), "content": str(c.get("content", ""))} for c in d.get("chunks", [])][:chunks],
                "entities": [{"name": e.get("entity_name"), "type": e.get("entity_type"),
                              "description": str(e.get("description", "")).split("<SEP>")[0], "source": src(e)}
                             for e in d.get("entities", [])][:top_k],
                "relations": [{"a": r.get("src_id"), "b": r.get("tgt_id"),
                               "description": str(r.get("description", "")).split("<SEP>")[0], "source": src(r)}
                              for r in d.get("relationships", [])][:top_k]}

    # ---------------------------------------------------------------- UI graph
    def graph(self, label: str = "*", max_nodes: int = 600, depth: int = 3) -> dict:
        g = self._req("GET", "/graphs", params={"label": label or "*", "max_depth": depth, "max_nodes": max_nodes})
        nodes = [{"id": n.get("id"), "name": n.get("id"), "kind": (n.get("properties") or {}).get("entity_type", "?"),
                  "description": str((n.get("properties") or {}).get("description", "")).split("<SEP>")[0][:400]}
                 for n in g.get("nodes", [])]
        links = [{"source": e.get("source"), "target": e.get("target"),
                  "type": str((e.get("properties") or {}).get("keywords", ""))[:60],
                  "description": str((e.get("properties") or {}).get("description", "")).split("<SEP>")[0][:300]}
                 for e in g.get("edges", [])]
        return {"nodes": nodes, "links": links, "truncated": g.get("is_truncated", False)}

    def labels(self, q: str = "") -> list[str]:
        if q:
            return self._req("GET", "/graph/label/search", params={"q": q, "limit": 50})
        return self._req("GET", "/graph/label/popular", params={"limit": 50})
