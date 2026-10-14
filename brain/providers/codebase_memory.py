"""Code graph provider: codebase-memory-mcp (CBM, MIT, single native binary, built and ready to use).

CBM parses 150+ languages with vendored tree-sitter grammars (+ LSP-style type resolution for the big ones),
stores a knowledge graph per project in one SQLite file (functions, classes, routes; CALLS, INHERITS,
IMPLEMENTS, IMPORTS, HTTP_CALLS, ...), keeps a BM25 index and embeds functions with a BUNDLED code model:
indexing and searching make zero network calls.

How this provider uses it:
  queries   one persistent MCP stdio process (warm, ~0.1-1 s per call), serialized by a lock
  indexing  `codebase-memory-mcp cli index_repository` in a separate process, so a long index never blocks
            queries; incremental by content hash
  UI        read-only SQL on the project database (graph overview, neighbourhoods, node details)
"""
from __future__ import annotations

import json
import os
import platform
import queue
import re
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

from .. import settings as cfg
from . import CodeGraph

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
UNIT_LABELS = ("Class", "Interface", "Enum", "Struct", "Trait", "Type", "Module", "Route", "Record", "Object")
LIFT_EDGES = ("CALLS", "INHERITS", "IMPLEMENTS", "HTTP_CALLS", "ASYNC_CALLS", "IMPORTS", "USAGE", "OVERRIDE")
REL_EDGES = ("CALLS", "INHERITS", "IMPLEMENTS", "OVERRIDE", "HTTP_CALLS", "ASYNC_CALLS", "IMPORTS", "TESTS",
             "EMITS", "LISTENS_ON", "DATA_FLOWS", "THROWS")
SKIP_LABELS = ("Folder", "Project", "Branch", "Variable", "Field", "Section", "File")
TESTY = re.compile(r"(^|/)(tests?|__tests__|spec|testing)(/|$)|Tests?\.|_test\.|\.spec\.|\.test\.", re.I)
TOOLS = {"trace": "trace_path", "architecture": "get_architecture"}   # deep tools -> engine tool names


NOISE = re.compile(r"^\s*(?:total\w*|\w*offset|limit|returned|\w+_returned|raw_\w+|directories_\w+|elapsed_ms|"
                   r"dedup_ratio|\w+_ms|file_path)\s*:\s*\S*\s*$|^\s*(?:\w*has_more|truncated)\s*:\s*false\s*$")


def tidy(text: str) -> str:
    """Drop the engine's paging and timing fields (they cost agent tokens and say nothing); keep has_more: true."""
    return "\n".join(line for line in text.splitlines() if not NOISE.match(line)).strip()


def binary() -> Path:
    if cfg.get("CBM_BIN"):
        return Path(cfg.get("CBM_BIN")).expanduser()
    osname = {"Windows": "windows", "Darwin": "darwin"}.get(platform.system(), "linux")
    return cfg.ROOT / "bin" / osname / ("codebase-memory-mcp.exe" if osname == "windows" else "codebase-memory-mcp")


def short(qn: str) -> str:
    parts = (qn or "").split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else qn


class _Stdio:
    """Persistent MCP stdio connection (JSON-RPC lines). Restarts itself once on failure."""

    def __init__(self, env: dict, log: Path):
        self.env, self.log = env, log
        self.proc, self.q, self.mid = None, None, 0
        self.lock = threading.Lock()

    def _start(self):
        err = open(self.log, "a", encoding="utf-8")
        self.proc = subprocess.Popen([str(binary())], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                     env=self.env, text=True, encoding="utf-8", bufsize=1, creationflags=NO_WINDOW)
        self.q = queue.Queue()

        def pump(p=self.proc, q=self.q):
            for line in p.stdout:
                if line.strip():
                    q.put(line)
            q.put(None)
        threading.Thread(target=pump, daemon=True).start()
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "ai-brain", "version": "1.0"}}, 180)
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.proc.stdin.flush()

    def _rpc(self, method, params, timeout):
        self.mid += 1
        mid = self.mid
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        end = time.time() + timeout
        while True:
            line = self.q.get(timeout=max(0.1, end - time.time()))
            if line is None:
                raise RuntimeError(f"codebase-memory-mcp exited (see {self.log})")
            msg = json.loads(line)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", str(msg["error"])))
                return msg.get("result", {})

    def call(self, name: str, args: dict, timeout: float) -> tuple[str, dict]:
        with self.lock:
            for attempt in (1, 2):
                try:
                    if self.proc is None or self.proc.poll() is not None:
                        self._start()
                    res = self._rpc("tools/call", {"name": name, "arguments": args}, timeout)
                    break
                except (queue.Empty, OSError, RuntimeError, ValueError) as exc:
                    self.kill()
                    if attempt == 2:
                        raise RuntimeError(f"code graph query failed: {exc or 'timeout'}") from None
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise RuntimeError(text[:500])
        return text, res.get("structuredContent") or {}

    def kill(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
        self.proc = None


class Provider(CodeGraph):
    name = "codebase_memory"

    def __init__(self):
        super().__init__()
        self.cache_dir = cfg.path("cbm")
        self.env = {**os.environ, "CBM_CACHE_DIR": str(self.cache_dir), **cfg.passthrough("CBM__")}
        self.mcp = _Stdio(self.env, cfg.data_dir() / "logs" / "codebase-memory.log")
        cfg.path("logs")
        self._index_lock = threading.Lock()
        self._cache: dict = {}

    # ---------------------------------------------------------------- life cycle
    def start(self) -> None:
        self.state, self.detail = "starting", "loading the code engine"
        if not binary().exists():
            self.state, self.detail = "error", f"binary not found: {binary()} (run setup)"
            return
        try:
            self.call("list_projects", {})  # warms the process and loads the bundled code-embedding model
            self.state, self.detail = "ready", f"{len(self.projects())} project(s) indexed"
        except Exception as exc:
            self.state, self.detail = "error", str(exc)

    def stop(self) -> None:
        self.mcp.kill()
        self.state = "stopped"

    def health(self) -> dict:
        h = super().health()
        h["binary"] = str(binary())
        return h

    def call(self, tool: str, args: dict, timeout: float | None = None) -> dict:
        text, structured = self.mcp.call(tool, args, timeout or cfg.get("CBM_QUERY_TIMEOUT"))
        if structured:
            return structured
        try:
            return json.loads(text)
        except ValueError:
            return {"text": text}

    # ---------------------------------------------------------------- indexing
    def index(self, project: str, path: str, log=lambda msg, progress=None: None) -> dict:
        args = {"repo_path": str(Path(path).resolve()), "name": project, "mode": cfg.get("CBM_INDEX_MODE")}
        with self._index_lock:  # one index at a time keeps memory bounded on big monorepos
            log(f"indexing {project} ({args['mode']})")
            p = subprocess.Popen([str(binary()), "cli", "--progress", "--json", "index_repository"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=self.env, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
            tail: list[str] = []

            def read_progress():
                for line in p.stderr:
                    line = line.strip()
                    if line and not line.startswith("level="):
                        tail.append(line)
                        del tail[:-20]
                        log(f"{project}: {line[:160]}")
            reader = threading.Thread(target=read_progress, daemon=True)
            reader.start()
            try:
                out, _ = p.communicate(json.dumps(args), timeout=cfg.get("CBM_INDEX_TIMEOUT"))
            except subprocess.TimeoutExpired:
                p.kill()
                raise RuntimeError(f"indexing {project} exceeded CBM_INDEX_TIMEOUT={cfg.get('CBM_INDEX_TIMEOUT')}s")
            reader.join(5)
        try:
            res = json.loads(out)
        except json.JSONDecodeError:
            raise RuntimeError(("\n".join(tail) or out or "index failed")[-600:]) from None
        if res.get("isError"):
            raise RuntimeError("".join(c.get("text", "") for c in res.get("content", []))[:600])
        s = res.get("structuredContent") or {}
        self._cache.clear()
        self.detail = f"{len(self.projects())} project(s) indexed"
        return {"project": s.get("project", project), "nodes": s.get("nodes"), "edges": s.get("edges"),
                "skipped_files": s.get("not_indexed_files_count"), "status": s.get("status")}

    def remove(self, project: str) -> None:
        try:
            self.call("delete_project", {"project": project})
        except RuntimeError:
            pass   # v0.11 reports not_found for some cache paths (e.g. non-ASCII); remove the files directly
        with self.mcp.lock:   # release SQLite handles (Windows cannot delete open files); restarts on next query
            self.mcp.kill()
            for suffix in ("", "-wal", "-shm"):
                (self.cache_dir / f"{project}.db{suffix}").unlink(missing_ok=True)
        self._cache.clear()
        # warm the query process again now, so the next search does not pay the model-loading time
        threading.Thread(target=lambda: self.call("list_projects", {}), daemon=True).start()

    # ---------------------------------------------------------------- read-only SQL
    def _db(self, project: str) -> sqlite3.Connection:
        db = self.cache_dir / f"{project}.db"
        if not db.exists():
            raise KeyError(f"code project not indexed: {project}")
        con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=15, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def projects(self) -> list[dict]:
        out = []
        for db in sorted(self.cache_dir.glob("*.db")):
            if db.name.startswith("_"):
                continue
            try:
                con = self._db(db.stem)
                for r in con.execute("SELECT name, indexed_at, root_path FROM projects"):
                    if r["name"] == db.stem:
                        nodes = con.execute("SELECT count(*) FROM nodes").fetchone()[0]
                        edges = con.execute("SELECT count(*) FROM edges").fetchone()[0]
                        out.append({"name": r["name"], "root": r["root_path"], "indexed_at": r["indexed_at"],
                                    "nodes": nodes, "edges": edges})
                con.close()
            except (sqlite3.Error, KeyError):
                continue
        return out

    def _root(self, project: str) -> Path | None:
        try:
            con = self._db(project)
            r = con.execute("SELECT root_path FROM projects WHERE name=?", (project,)).fetchone()
            con.close()
            return Path(r[0]) if r else None
        except (sqlite3.Error, KeyError):
            return None

    def read_lines(self, project: str, rel: str, a: int, b: int) -> str:
        root = self._root(project)
        if not root or not rel or rel.startswith("<"):
            return ""
        fp = (root / rel).resolve()
        if root.resolve() not in fp.parents:  # never read outside the indexed tree
            return ""
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                return "\n".join(f.read().splitlines()[max(0, a - 1):b])
        except OSError:
            return ""

    # ---------------------------------------------------------------- search
    @staticmethod
    def _rows(res: dict, key: str | None = None) -> list[dict]:
        block = res.get(key) if key else res
        if not isinstance(block, dict) or "cols" not in block:
            return []
        return [dict(zip(block["cols"], r)) for r in block.get("rows", [])]

    def search(self, query: str, keywords: list[str], projects: list[str], k: int, mode: str = "hybrid") -> list[dict]:
        """hybrid = BM25 (identifiers + bodies) + semantic (bundled code embeddings), fused by reciprocal rank;
        semantic = embeddings only; lexical = BM25 only."""
        hits = []
        for proj in projects:
            fused: dict[str, float] = {}
            how: dict[str, list[str]] = {}
            if mode in ("hybrid", "lexical"):
                for rank, r in enumerate(self._rows(self.call("search_graph", {
                        "project": proj, "query": " ".join(keywords) or query, "limit": 25, "format": "json"}))):
                    fused[r["qn"]] = fused.get(r["qn"], 0) + 1 / (60 + rank)
                    how.setdefault(r["qn"], []).append("keywords")
            if mode in ("hybrid", "semantic"):
                res = self.call("search_graph", {"project": proj, "semantic_query": (keywords or query.split())[:8],
                                                 "semantic_limit": 25, "format": "json"})
                for rank, r in enumerate(self._rows(res, "semantic")):
                    fused[r["qn"]] = fused.get(r["qn"], 0) + 1 / (60 + rank)
                    how.setdefault(r["qn"], []).append("code vectors")
            for h in self.hits_for(proj, fused):
                h["matched"] = how.get(h["qn"], [])
                hits.append(h)
        hits.sort(key=lambda h: -h["score"])
        return self.with_code(hits[:k])

    def hits_for(self, project: str, scored: dict[str, float]) -> list[dict]:
        """{qualified name: score} -> hit dicts (tests and one-liners down-weighted; builtins skipped)."""
        if not scored:
            return []
        out = []
        con = self._db(project)
        for qn, score in scored.items():
            n = con.execute("SELECT id, label, name, file_path, start_line, end_line FROM nodes "
                            "WHERE qualified_name=?", (qn,)).fetchone()
            if n is None or n["label"] in SKIP_LABELS or (n["file_path"] or "").startswith("<"):
                continue
            if TESTY.search(n["file_path"] or ""):
                score *= 0.5           # tests explain usage but are rarely the answer
            if (n["end_line"] or 0) - (n["start_line"] or 0) < 3:
                score *= 0.6           # trivial getters / one-liners
            out.append({"project": project, "id": n["id"], "qn": qn, "name": n["name"], "label": n["label"],
                        "path": n["file_path"], "line1": n["start_line"], "line2": n["end_line"],
                        "score": round(score, 5)})
        con.close()
        return out

    def with_code(self, hits: list[dict]) -> list[dict]:
        for h in hits:
            if "code" not in h:
                h["code"] = self.read_lines(h["project"], h["path"], h["line1"], min(h["line2"], h["line1"] + 40))
        return hits

    def symbols(self, project: str, limit: int = 200000) -> list[dict]:
        """Every function / method / class / route of a project, with a short text for embedding."""
        con = self._db(project)
        rows = con.execute(f"""SELECT qualified_name qn, label, name, file_path, start_line, end_line, properties
            FROM nodes WHERE label IN ('Function','Method','Class','Interface','Enum','Struct','Trait','Type','Route',
            'Record','Object') AND file_path NOT LIKE '<%' AND file_path != '' ORDER BY file_path, start_line LIMIT ?""",
                           (limit,)).fetchall()
        con.close()
        root = self._root(project)
        files: dict[str, list[str]] = {}
        out = []
        for r in rows:
            if root and r["file_path"] not in files:
                try:
                    files[r["file_path"]] = (root / r["file_path"]).read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    files[r["file_path"]] = []
            lines = files.get(r["file_path"], [])
            props = json.loads(r["properties"] or "{}")
            head = "\n".join(lines[max(0, (r["start_line"] or 1) - 1):min(r["end_line"] or 0, (r["start_line"] or 1) + 24)])
            text = (f"{r['label']} {short(r['qn'])} in {r['file_path']}\n"
                    + (f"{props.get('signature')}\n" if props.get("signature") else "")
                    + (f"{props.get('docstring')}\n" if props.get("docstring") else "") + head)
            out.append({"qn": r["qn"], "text": text[:2000]})
        return out

    GRAPH_EDGES = ("CALLS", "INHERITS", "IMPLEMENTS", "OVERRIDE", "HTTP_CALLS", "ASYNC_CALLS", "DATA_FLOWS")

    def neighbors(self, hits: list[dict], limit: int = 20) -> list[dict]:
        """Code-graph expansion: callers, callees, parents and implementations of the given hits, as new hits
        (matched = "code graph: calls X" / "called by X" ...). Lets search reach code that shares no words with
        the question but is wired to code that does."""
        out: list[dict] = []
        by_proj: dict[str, list[dict]] = {}
        for h in hits:
            by_proj.setdefault(h["project"], []).append(h)
        t = ",".join("?" * len(self.GRAPH_EDGES))
        for proj, hs in by_proj.items():
            ids = {h["id"]: h["name"] for h in hs}
            q = ",".join("?" * len(ids))
            con = self._db(proj)
            rows = con.execute(f"""SELECT e.type, e.source_id s, e.target_id t, a.qualified_name aq, b.qualified_name bq
                FROM edges e JOIN nodes a ON a.id=e.source_id JOIN nodes b ON b.id=e.target_id
                WHERE (e.source_id IN ({q}) OR e.target_id IN ({q})) AND e.type IN ({t})
                  AND a.file_path NOT LIKE '<%' AND b.file_path NOT LIKE '<%' LIMIT 400""",
                               (*ids, *ids, *self.GRAPH_EDGES)).fetchall()
            con.close()
            scored, how = {}, {}
            for rank, r in enumerate(rows):
                if r["s"] in ids and r["t"] not in ids:
                    other, why = r["bq"], f"code graph: {ids[r['s']]} {r['type'].lower()} it"
                elif r["t"] in ids and r["s"] not in ids:
                    other, why = r["aq"], f"code graph: {r['type'].lower()} {ids[r['t']]}"
                else:
                    continue
                scored[other] = scored.get(other, 0) + 1 / (60 + rank)
                how.setdefault(other, why)
            for h in self.hits_for(proj, scored):
                h["matched"] = [how[h["qn"]]]
                out.append(h)
        out.sort(key=lambda h: -h["score"])
        return out[:limit]

    def annotate(self, hits: list[dict]) -> list[dict]:
        """Add signature, callers and callees (from the graph) to each hit, for people and AI agents."""
        for h in hits:
            try:
                con = self._db(h["project"])
            except KeyError:
                continue
            props = con.execute("SELECT properties FROM nodes WHERE id=?", (h["id"],)).fetchone()
            p = json.loads((props[0] if props else None) or "{}")
            if p.get("signature"):
                h["signature"] = str(p["signature"])[:200]
            rows = con.execute("""SELECT e.type, e.source_id s, a.name an, b.name bn FROM edges e
                JOIN nodes a ON a.id=e.source_id JOIN nodes b ON b.id=e.target_id
                WHERE (e.source_id=? OR e.target_id=?) AND e.type IN ('CALLS','HTTP_CALLS','ASYNC_CALLS','INHERITS','IMPLEMENTS')
                  AND a.file_path NOT LIKE '<%' AND b.file_path NOT LIKE '<%' LIMIT 60""", (h["id"], h["id"])).fetchall()
            con.close()
            h["callees"] = list(dict.fromkeys(r["bn"] for r in rows if r["s"] == h["id"] and r["type"].endswith("CALLS")))[:6]
            h["callers"] = list(dict.fromkeys(r["an"] for r in rows if r["s"] != h["id"] and r["type"].endswith("CALLS")))[:6]
            h["parents"] = list(dict.fromkeys(r["bn"] for r in rows if r["s"] == h["id"] and r["type"] in ("INHERITS", "IMPLEMENTS")))[:4]
        return hits

    def files(self, project: str, pattern: str = "*", limit: int = 300) -> list[str]:
        """Indexed file paths matching a glob (e.g. **/*.py, src/billing/*)."""
        import fnmatch
        con = self._db(project)
        paths = [r[0] for r in con.execute("SELECT rel_path FROM file_hashes WHERE project=? ORDER BY rel_path", (project,))]
        con.close()
        pat = pattern or "*"
        return [p for p in paths if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, pat.replace("**/", ""))][:limit]

    def read(self, project: str, path: str, start: int = 1, end: int | None = None) -> dict:
        """Lines of an indexed file (max 400 per call), with the total line count."""
        root = self._root(project)
        if not root:
            raise KeyError(f"code project not indexed: {project}")
        fp = (root / path).resolve()
        if root.resolve() not in fp.parents or not fp.is_file():
            raise KeyError(f"no file {path} in {project}")
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start or 1))
        end = min(len(lines), int(end or start + 199), start + 399)
        return {"project": project, "path": path, "start": start, "end": end, "total_lines": len(lines),
                "text": "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(start, end + 1))}

    def grep(self, project: str, pattern: str, regex: bool = False, file_pattern: str | None = None, limit: int = 30,
             mode: str = "matches", path: str | None = None) -> str:
        """Graph-ranked text / regex search over the indexed source (the code engine's search_code).
        mode: files (paths only, cheapest) | matches (symbols with matching lines) | full (bounded source)."""
        args = {"pattern": pattern, "project": project, "regex": bool(regex), "limit": limit,
                "mode": {"files": "files", "full": "full"}.get(mode, "compact"),
                "max_output_tokens": cfg.get("BRAIN_TOOL_MAX_TOKENS")}
        if file_pattern:
            args["file_pattern"] = file_pattern
        if path:
            args["path_filter"] = path
        text = tidy(self.mcp.call("search_code", args, cfg.get("CBM_QUERY_TIMEOUT"))[0])
        return "" if re.search(r"^(?:results|files): 0\b", text, flags=re.M) else text

    def relations(self, hits: list[dict], limit: int = 30) -> list[dict]:
        out, by_proj = [], {}
        for h in hits:
            by_proj.setdefault(h["project"], []).append(h["id"])
        for proj, ids in by_proj.items():
            con = self._db(proj)
            q, t = ",".join("?" * len(ids)), ",".join("?" * len(REL_EDGES))
            rows = con.execute(f"""SELECT e.type, a.qualified_name aq, b.qualified_name bq FROM edges e
                JOIN nodes a ON a.id=e.source_id JOIN nodes b ON b.id=e.target_id
                WHERE (e.source_id IN ({q}) OR e.target_id IN ({q})) AND e.type IN ({t})
                  AND b.file_path NOT LIKE '<%' LIMIT ?""", (*ids, *ids, *REL_EDGES, limit)).fetchall()
            out += [{"project": proj, "type": r["type"], "a": short(r["aq"]), "b": short(r["bq"])} for r in rows]
            con.close()
        return out

    def find(self, q: str, projects: list[str], limit: int = 25) -> list[dict]:
        out = []
        for proj in projects:
            try:
                con = self._db(proj)
            except KeyError:
                continue
            rows = con.execute(f"""SELECT id, label, name, qualified_name, file_path, start_line, end_line FROM nodes
                WHERE label NOT IN ({','.join('?' * len(SKIP_LABELS))}) AND file_path NOT LIKE '<%'
                  AND (name = ? OR name LIKE ?) ORDER BY (name = ?) DESC, length(name) LIMIT ?""",
                               (*SKIP_LABELS, q, f"%{q}%", q, limit)).fetchall()
            out += [{"project": proj, **dict(r)} for r in rows]
            con.close()
        return out[:limit]

    def symbol(self, name: str, projects: list[str], source: str = "auto") -> str:
        """One symbol, compactly: location, signature, source (auto = whole when short, else the first 40 lines),
        callers, callees, parents; other symbols with the same name as one line each."""
        last = name.rsplit(".", 1)[-1]
        found = self.find(last, projects, 8)
        found = sorted(found, key=lambda f: (f["qualified_name"] != name and not f["qualified_name"].endswith("." + name),
                                             f["name"] != last))
        if not found:
            return f"No symbol named '{name}'. Use search (by meaning) or grep (exact text)."
        best = found[0]
        d = self.node(best["project"], best["id"])
        if not d:
            return f"No symbol named '{name}'."
        lines = (d["end_line"] or 0) - (d["start_line"] or 0) + 1
        out = [f"### {d['label']} `{short(d['qualified_name'])}` - {best['project']}/{d['file_path']}:{d['start_line']}-{d['end_line']}"
               f" ({lines} lines; qualified: `{d['qualified_name']}`)"]
        if d["props"].get("signature"):
            out.append("signature: " + str(d["props"]["signature"]))
        if d["props"].get("docstring"):
            out.append("doc: " + " ".join(str(d["props"]["docstring"]).split())[:300])
        if source != "none":
            limit = 400 if source == "full" else (lines if lines <= 60 else 40)
            code = self.read_lines(best["project"], d["file_path"], d["start_line"], d["start_line"] + limit - 1)
            if code:
                more = lines - limit
                out.append(f"```\n{code}\n```" + (f"\n({more} more lines: symbol(source=full) or read(repo, path, start, end))"
                                                    if more > 0 else ""))
        groups = {"called by": [r for r in d["in"] if r["type"].endswith("CALLS")],
                  "calls": [r for r in d["out"] if r["type"].endswith("CALLS")],
                  "extends / implements": [r for r in d["out"] if r["type"] in ("INHERITS", "IMPLEMENTS")],
                  "extended / implemented by": [r for r in d["in"] if r["type"] in ("INHERITS", "IMPLEMENTS")],
                  "tested by": [r for r in d["in"] if r["type"] == "TESTS"]}
        for label, rows in groups.items():
            names = list(dict.fromkeys(short(r["qname"]) for r in rows))
            if names:
                out.append(f"{label} ({len(names)}): " + ", ".join(f"`{x}`" for x in names[:15])
                           + (" …" if len(names) > 15 else ""))
        others = [f for f in found[1:] if f["qualified_name"] != d["qualified_name"]][:5]
        if others:
            out.append("other matches: " + "; ".join(f"`{f['qualified_name']}` {f['project']}/{f['file_path']}:{f['start_line']}"
                                                     for f in others))
        return "\n".join(out)

    def exact(self, terms: list[str], projects: list[str], limit: int = 10) -> list[dict]:
        """Symbols whose name or qualified-name tail equals an identifier of the question, and the main symbols of
        a file path named in it. These are what the user is pointing at, so search ranks them first."""
        idents = [t for t in terms if "/" not in t and "\\" not in t]
        paths = [t.replace("\\", "/").lstrip("./") for t in terms if "/" in t or "\\" in t or "." in t.rsplit("/", 1)[-1]]
        out: list[dict] = []
        for proj in projects:
            try:
                con = self._db(proj)
            except KeyError:
                continue
            scored: dict[str, float] = {}
            how: dict[str, str] = {}
            skip = ",".join("?" * len(SKIP_LABELS))
            for i, t in enumerate(idents):
                for (qn,) in con.execute(f"""SELECT qualified_name FROM nodes WHERE label NOT IN ({skip})
                        AND file_path NOT LIKE '<%' AND (name = ? OR qualified_name LIKE ?) LIMIT 5""",
                                         (*SKIP_LABELS, t, "%." + t)):
                    scored.setdefault(qn, 2.0 - i * 0.01)
                    how.setdefault(qn, "exact name")
            for p in paths:
                for (qn,) in con.execute(f"""SELECT qualified_name FROM nodes WHERE label IN
                        ('Class','Interface','Enum','Struct','Trait','Type','Route','Function','Record','Object')
                        AND (file_path = ? OR file_path LIKE ?) ORDER BY start_line LIMIT 4""", (p, "%/" + p)):
                    scored.setdefault(qn, 1.0)
                    how.setdefault(qn, "file path")
            con.close()
            for h in self.hits_for(proj, scored):
                h["matched"] = [how[h["qn"]]]
                out.append(h)
        out.sort(key=lambda h: -h["score"])
        return out[:limit]

    SYMBOL_LABELS = ("Function", "Method", "Class", "Interface", "Enum", "Struct", "Trait", "Type", "Record",
                     "Object", "Module")
    DEPENDS = ("CALLS", "HTTP_CALLS", "ASYNC_CALLS", "INHERITS", "IMPLEMENTS", "OVERRIDE")

    def impact(self, project: str, files: list[str] | None = None, symbols: list[str] | None = None,
               depth: int = 3) -> dict:
        """What a change reaches, from the graph alone: the changed symbols (in `files`, or named in `symbols`), the
        code that depends on them up to `depth` hops (callers, subclasses, overrides), the entry points that lead
        there (routes and their handlers, or callers nothing else calls) and the tests to run (TESTS edges and test
        code among the dependants)."""
        con = self._db(project)
        lab = ",".join("?" * len(self.SYMBOL_LABELS))
        seeds: dict[int, sqlite3.Row] = {}
        for f in files or []:
            f = f.replace("\\", "/").removeprefix("./")
            for r in con.execute(f"""SELECT id, label, name, qualified_name, file_path, start_line FROM nodes
                    WHERE label IN ({lab}) AND (file_path = ? OR file_path LIKE ?) AND label != 'Module'""",
                                 (*self.SYMBOL_LABELS, f, "%/" + f)):
                seeds[r["id"]] = r
        for s in symbols or []:
            tail = s.rsplit(".", 1)[-1]
            for r in con.execute(f"""SELECT id, label, name, qualified_name, file_path, start_line FROM nodes
                    WHERE label IN ({lab}) AND name = ? AND file_path NOT LIKE '<%'""", (*self.SYMBOL_LABELS, tail)):
                if r["qualified_name"] == s or r["qualified_name"].endswith("." + s) or s == tail:
                    seeds[r["id"]] = r
        dep = ",".join("?" * len(self.DEPENDS))
        level = {i: 0 for i in seeds}
        info: dict[int, sqlite3.Row] = dict(seeds)
        via: dict[int, int] = {}
        frontier = list(seeds)
        for d in range(1, max(1, min(int(depth), 6)) + 1):
            if not frontier or len(level) > 2000:
                break
            q = ",".join("?" * len(frontier))
            nxt = []
            for r in con.execute(f"""SELECT e.target_id t, a.id, a.label, a.name, a.qualified_name, a.file_path,
                    a.start_line FROM edges e JOIN nodes a ON a.id = e.source_id
                    WHERE e.target_id IN ({q}) AND e.type IN ({dep}) AND a.file_path NOT LIKE '<%'""",
                                 (*frontier, *self.DEPENDS)):
                if r["id"] not in level:
                    level[r["id"]], info[r["id"]], via[r["id"]] = d, r, r["t"]
                    nxt.append(r["id"])
            frontier = nxt
        ids = list(level)
        q = ",".join("?" * len(ids)) or "NULL"
        tests: dict[int, sqlite3.Row] = {}
        for r in con.execute(f"""SELECT a.id, a.label, a.name, a.qualified_name, a.file_path, a.start_line FROM edges e
                JOIN nodes a ON a.id = e.source_id WHERE e.type = 'TESTS' AND e.target_id IN ({q})""", ids):
            tests[r["id"]] = r
        for i in ids:
            if TESTY.search(info[i]["file_path"] or ""):
                tests[i] = info[i]
        routes = [{"route": r["route"], "handler": short(r["hq"]), "path": r["fp"]} for r in con.execute(
            f"""SELECT b.name route, a.qualified_name hq, a.file_path fp FROM edges e JOIN nodes a ON a.id = e.source_id
                JOIN nodes b ON b.id = e.target_id WHERE e.type = 'HANDLES' AND e.source_id IN ({q})""", ids)]
        called = {r[0] for r in con.execute(f"""SELECT DISTINCT target_id FROM edges WHERE target_id IN ({q})
                AND type IN ({dep}) AND source_id IN (SELECT id FROM nodes WHERE file_path NOT LIKE '<%')""",
                                            (*ids, *self.DEPENDS))}
        con.close()

        def item(r, d=None):
            out = {"symbol": short(r["qualified_name"]), "label": r["label"], "path": r["file_path"],
                   "line": r["start_line"]}
            if d is not None:
                out["depth"] = d
                if r["id"] in via:
                    out["via"] = short(info[via[r["id"]]]["qualified_name"])
            return out
        affected = sorted((i for i in ids if i not in seeds and i not in tests), key=lambda i: (level[i], info[i]["file_path"]))
        tops = [i for i in affected if i not in called and info[i]["label"] != "Module"]
        return {"project": project, "changed": [item(r) for r in seeds.values()],
                "affected": [item(info[i], level[i]) for i in affected],
                "entry_points": {"routes": routes, "top_callers": [item(info[i], level[i]) for i in tops]},
                "tests": [item(r) for r in sorted(tests.values(), key=lambda r: (r["file_path"], r["start_line"]))],
                "test_files": sorted({r["file_path"] for r in tests.values()})}

    def outline(self, project: str, path: str) -> str:
        """Declarations of one file with their line ranges: read this before reading lines."""
        text = self.mcp.call("get_file_outline", {"project": project, "file_path": path.replace("\\", "/").lstrip("./"),
                                                  "limit": 200}, cfg.get("CBM_QUERY_TIMEOUT"))[0]
        return tidy(text)

    def tool(self, name: str, args: dict) -> str:
        if name not in TOOLS:
            raise ValueError(f"unknown code tool {name}; available: {', '.join(TOOLS)}")
        if name == "trace":
            args = {"max_output_tokens": cfg.get("BRAIN_TOOL_MAX_TOKENS"), **args}
        text, _ = self.mcp.call(TOOLS[name], args, cfg.get("CBM_QUERY_TIMEOUT"))
        return tidy(text)

    # ---------------------------------------------------------------- UI graphs
    def node(self, project: str, node_id: int) -> dict | None:
        con = self._db(project)
        r = con.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if r is None:
            con.close()
            return None
        d = dict(r)
        props = json.loads(d.pop("properties", None) or "{}")
        d["props"] = {k: v for k, v in props.items() if k in ("signature", "return_type", "complexity", "lines",
                                                               "is_entry_point", "is_test", "docstring")}
        d["code"] = self.read_lines(project, d["file_path"], d["start_line"], min(d["end_line"], d["start_line"] + 80))
        rel = con.execute("""SELECT e.type, e.source_id s, e.target_id t, a.qualified_name aq, a.label al,
                b.qualified_name bq, b.label bl FROM edges e JOIN nodes a ON a.id=e.source_id
                JOIN nodes b ON b.id=e.target_id WHERE (e.source_id=? OR e.target_id=?)
                AND e.type NOT IN ('CONTAINS_FOLDER') LIMIT 300""", (node_id, node_id)).fetchall()
        d["out"] = [{"type": x["type"], "id": x["t"], "qname": x["bq"], "label": x["bl"]} for x in rel if x["s"] == node_id]
        d["in"] = [{"type": x["type"], "id": x["s"], "qname": x["aq"], "label": x["al"]} for x in rel if x["t"] == node_id]
        d["project"] = project
        con.close()
        return d

    def graph(self, project: str, limit: int = 1200) -> dict:
        """Architecture view: classes/modules/routes, with method-level edges lifted to their owners."""
        db = self.cache_dir / f"{project}.db"
        key = ("graph", project, limit, db.stat().st_mtime if db.exists() else 0)
        if key in self._cache:
            return self._cache[key]
        con = self._db(project)
        nodes = {r["id"]: dict(r) for r in con.execute(
            f"SELECT id, label, name, qualified_name, file_path FROM nodes WHERE label IN "
            f"({','.join('?' * len(UNIT_LABELS))}) AND file_path NOT LIKE '<%'", UNIT_LABELS)}
        owner = {}
        for s, t in con.execute("SELECT source_id, target_id FROM edges WHERE type = 'DEFINES'"):
            owner[t] = s
        for s, t in con.execute("SELECT source_id, target_id FROM edges WHERE type = 'DEFINES_METHOD'"):
            owner[t] = s   # class -> method wins over file -> method

        def unit(n):
            for _ in range(4):
                if n in nodes or n is None:
                    return n
                n = owner.get(n)
            return n if n in nodes else None
        agg: dict = {}
        t = ",".join("?" * len(LIFT_EDGES))
        for s, d, typ in con.execute(f"SELECT source_id, target_id, type FROM edges WHERE type IN ({t})", LIFT_EDGES):
            a, b = unit(s), unit(d)
            if a is not None and b is not None and a != b:
                k2 = (a, b, "USES" if typ == "USAGE" else typ)
                agg[k2] = agg.get(k2, 0) + 1
        con.close()
        deg: dict = {}
        for (a, b, _), w in agg.items():
            deg[a] = deg.get(a, 0) + w
            deg[b] = deg.get(b, 0) + w
        keep = set(sorted(nodes, key=lambda n: -deg.get(n, 0))[:limit])
        res = {"project": project, "total_nodes": len(nodes),
               "nodes": [{"id": n, "kind": nodes[n]["label"], "name": nodes[n]["name"], "qname": nodes[n]["qualified_name"],
                          "path": nodes[n]["file_path"], "degree": deg.get(n, 0)} for n in keep],
               "links": [{"source": a, "target": b, "type": typ, "weight": w} for (a, b, typ), w in
                         sorted(((k3, w) for k3, w in agg.items() if k3[0] in keep and k3[1] in keep),
                                key=lambda x: -x[1])[:limit * 4]]}
        self._cache[key] = res
        return res

    def ego(self, project: str, node_id: int, depth: int = 1) -> dict:
        con = self._db(project)
        seen, frontier, links, limit = {node_id}, {node_id}, set(), 300
        for _ in range(max(1, min(depth, 2))):
            if not frontier:
                break
            q = ",".join("?" * len(frontier))
            rows = con.execute(f"""SELECT source_id, target_id, type FROM edges WHERE (source_id IN ({q})
                OR target_id IN ({q})) AND type NOT IN ('CONTAINS_FOLDER','CONTAINS_FILE','SIMILAR_TO','HAS_BRANCH')
                LIMIT 2000""", (*frontier, *frontier)).fetchall()
            nxt = set()
            for s, d, typ in rows:
                if len(seen) >= limit and (s not in seen or d not in seen):
                    continue
                links.add((s, d, typ))
                for x in (s, d):
                    if x not in seen:
                        seen.add(x)
                        nxt.add(x)
            frontier = nxt
        q = ",".join("?" * len(seen))
        nodes = [{"id": r["id"], "kind": r["label"], "name": r["name"], "qname": r["qualified_name"],
                  "path": r["file_path"]} for r in
                 con.execute(f"SELECT id, label, name, qualified_name, file_path FROM nodes WHERE id IN ({q})", tuple(seen))]
        con.close()
        return {"nodes": nodes, "links": [{"source": s, "target": d, "type": t} for s, d, t in links], "center": node_id}
