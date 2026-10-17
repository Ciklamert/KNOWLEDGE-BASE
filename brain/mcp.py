"""MCP server (Streamable HTTP transport, JSON responses) at POST /mcp, for any MCP client:
Claude Code, opencode, Cursor, Continue, Copilot ... Register it under the name "brain"; tools then show up as
brain_search / mcp__brain__search etc. Authentication: `Authorization: Bearer <BRAIN_API_TOKEN>`.

Token economy: an agent pays for the tool list on every turn and for every answer it reads. So the tool list is
short and terse, answers are bounded (BRAIN_SEARCH_DETAIL, BRAIN_TOOL_MAX_TOKENS), and the tools are ordered from
cheap to expensive: symbol / outline / read / grep / files answer exact questions in a few hundred tokens; search
gives ranked evidence from all sources; ask / enhance_prompt / write_requirements spend model calls on the server.
"""
from __future__ import annotations

from . import agents, drift, memory, providers, repos, search, srs

VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = ("Organisation knowledge base: code graph + code vectors + documents of every configured repository. "
                "Use it instead of grep/glob/read: `symbol` for one symbol, `outline` then `read` for a file, `grep` "
                "for exact text, `files` for paths, `search` for anything by meaning (detail=brief to scan). "
                "`impact` before and after editing (what breaks, tests to run); `recall` at the start of a task and `remember` what you learned that the next session needs (decisions, gotchas); `enhance_prompt` plans a task; `check_branch` when not on main. Verify locations in your working "
                "copy before editing. Scope: `repo` = one repository, `set` = a repository set (default: all "
                "repositories); `branch` uses a branch overlay when one is indexed.")
_S, _I, _B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
SCOPE = {"repo": _S, "set": _S}   # explained once in INSTRUCTIONS, not in every schema
BRANCH = {"branch": _S}


def _tool(name: str, desc: str, props: dict, required: list[str], scope: bool = True) -> dict:
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": {**props, **(SCOPE if scope else {})}, "required": required}}


TOOLS = [
    _tool("search", "Ranked code (graph + vectors) and documents, any language, no LLM. Hits: location, signature, "
                    "callers, callees, why. detail: brief, normal, full.",
          {"query": _S, "scope": {"type": "string", "enum": ["all", "code", "semantic", "docs"]},
           "detail": {"type": "string", "enum": ["brief", "normal", "full"]}, "k": _I, **BRANCH}, ["query"]),
    _tool("symbol", "A symbol: location, signature, source, callers, callees.",
          {"name": _S, "source": {"type": "string", "enum": ["auto", "full", "none"]}, **BRANCH}, ["name"]),
    _tool("outline", "Declarations of a file with line ranges; read it before the file.",
          {"path": _S}, ["path"]),
    _tool("read", "Numbered lines of a file (max 400); repo optional.",
          {"path": _S, "start": _I, "end": _I}, ["path"]),
    _tool("grep", "Exact text or regex, ranked by the code graph. mode: files, matches, full.",
          {"pattern": _S, "regex": _B, "mode": {"type": "string", "enum": ["files", "matches", "full"]},
           "file_pattern": _S, "path": _S},
          ["pattern"]),
    _tool("files", "Indexed file paths matching a glob, e.g. **/*.sql.", {"pattern": _S}, ["pattern"]),
    _tool("trace", "Call chain of a function.",
          {"function_name": _S, "direction": {"type": "string", "enum": ["inbound", "outbound", "both"]},
           "depth": _I}, ["function_name"]),
    _tool("impact", "What changing files or symbols reaches (no LLM): dependants, routes, tests, rules.",
          {"files": {"type": "array", "items": _S}, "symbols": {"type": "array", "items": _S}, "depth": _I,
           **BRANCH}, []),
    _tool("overview", "Repository structure: packages, entry points, routes, hotspots, tree.",
          {"repo": _S, "path": {"type": "string", "description": "folder"},
           "aspects": {"type": "array", "items": {"type": "string", "enum": [
               "overview", "structure", "routes", "hotspots", "entry_points", "dependencies", "layers", "file_tree"]}}},
          ["repo"], scope=False),
    _tool("ask", "A cited answer researched by a server-side agent (LLM).",
          {"question": _S, "model": _S, **BRANCH}, ["question"]),
    _tool("enhance_prompt", "Any request (bug, feature, refactor ...) as an implementation-ready prompt; "
                            "base_commit/changed_files add branch warnings.",
          {"prompt": _S, "base_commit": _S,
           "changed_files": {"type": "array", "items": _S}, "model": _S, **BRANCH}, ["prompt"]),
    _tool("write_requirements", "Software requirements in a saved format, checked against code and documents (slow). "
                                "topic: system requirements, an idea or a topic.",
          {"topic": _S, "template": _S, "language": _S,
           "model": _S}, ["topic"]),
    _tool("check_branch", "Branch vs indexed main: behind, conflict-risk files, tests, what to do. "
                          "base_commit: git merge-base HEAD origin/main; changed_files: git diff --name-only "
                          "origin/main...HEAD + uncommitted.",
          {"repo": _S, "branch": _S, "base_commit": _S, "head_commit": _S, "changed_files": {"type": "array", "items": _S}},
          ["repo"], scope=False),
    _tool("list_repos", "Repositories, sets, indexed commits, branch overlays.", {}, [], scope=False),
    _tool("doc", "Documents as trees, no LLM. q: unit (Madde 5 (2), 3.1, REQ-004), term (define) or actor (obligations).",
          {"mode": {"type": "string", "enum": ["list", "outline", "unit", "refs", "define", "obligations", "impact"]},
           "document": _S, "q": _S}, ["mode"], scope=False),
    _tool("remember", "Keep a decision, rule, gotcha or convention for later sessions; same type+title replaces.",
          {"type": {"type": "string", "enum": list(memory.TYPES)}, "title": _S, "text": _S, "repo": _S,
           "paths": {"type": "array", "items": _S}}, ["type", "title", "text"], scope=False),
    _tool("recall", "Facts kept with remember, newest or by query.",
          {"query": _S, "repo": _S, "type": _S}, [], scope=False),
    _tool("sync_repo", "Update and re-index a repository (or all).", {"repo": _S}, [], scope=False),
]
CODE_TOOLS = ("symbol", "outline", "read", "grep", "files", "trace", "overview")


def _scope(a: dict) -> tuple:
    return a.get("set"), ([a["repo"]] if a.get("repo") else a.get("repos")), a.get("branch")


def call_tool(name: str, a: dict) -> str:
    if name == "search":
        r = search.search(a["query"], a.get("scope", "all"), *_scope(a), k=a.get("k"))
        return (search.render(r, 30000, a.get("detail")) or "No AI-BRAIN matches.") + \
            (f"\n\n(errors: {'; '.join(r['errors'])})" if r["errors"] else "")
    if name in CODE_TOOLS:
        ctx = agents.Context(*_scope(a)) if name != "overview" else agents.Context(None, [a["repo"]])
        return ctx.run_tool(name, a)
    if name == "impact":
        return agents.impact(a.get("files"), a.get("symbols"), *_scope(a), int(a.get("depth") or 3))["markdown"]
    if name == "ask":
        r = agents.ask(a["question"], *_scope(a), model=a.get("model"))
        return r["answer"] + (f"\n\n(notes: {'; '.join(r['errors'])})" if r["errors"] else "")
    if name == "enhance_prompt":
        r = agents.enhance(a["prompt"], *_scope(a), repo=a.get("repo"), base_commit=a.get("base_commit"),
                           changed_files=a.get("changed_files"), model=a.get("model"),)
        return r["enhanced"]
    if name == "write_requirements":
        r = srs.write(a["topic"], *_scope(a)[:2], a.get("template"), a.get("language"), a.get("model"))
        return r["markdown"] + (f"\n\n(notes: {'; '.join(r['errors'])})" if r["errors"] else "")
    if name == "check_branch":
        return drift.render(drift.check(a["repo"], a.get("branch"), a.get("base_commit"), a.get("changed_files"),
                                        a.get("head_commit")))
    if name == "list_repos":
        return "\n".join(f"{r['name']} ({r['provider']}, {r['branch']}) sets: {', '.join(r['sets']) or '-'}; "
                         f"indexed: {(r['commit'] or 'not yet')[:10]}; symbols: {r['nodes'] or 0}"
                         + (f"; overlays: {', '.join(b['branch'] for b in r['branches'])}" if r["branches"] else "")
                         + (f"; error: {r['error']}" if r["error"] else "")
                         for r in repos.overview()) or "No repositories configured."
    if name == "doc":
        query = getattr(providers.docs(), "doc_query", None)
        if not query:
            return "this document engine has no document tree"
        q = a.get("q")
        return query(a.get("mode") or "list", a.get("document"), unit=q, term=q, actor=q)["text"]
    if name == "remember":
        m = memory.remember(a["type"], a["title"], a["text"], a.get("repo"), a.get("paths"), "agent")
        return f"{'replaced' if m['replaced'] else 'recorded'}: [{m['type']}] {m['title']}"
    if name == "recall":
        return memory.render(memory.recall(a.get("query"), a.get("repo"), a.get("type")))
    if name == "sync_repo":
        job = repos.request_sync(a.get("repo"), "mcp")
        return f"sync started (job {job.id})" if job else "a sync for this repository was just requested; skipped"
    raise ValueError(f"unknown tool {name}")


def handle(msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method", "")
    if mid is None or method.startswith("notifications/"):
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion")
        return ok({"protocolVersion": want if want in VERSIONS else VERSIONS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "ai-brain", "version": "1.1.0"}, "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        p = msg.get("params") or {}
        try:
            text, err = call_tool(p.get("name", ""), p.get("arguments") or {}), False
        except Exception as exc:
            text, err = f"{type(exc).__name__}: {exc}", True
        return ok({"content": [{"type": "text", "text": text}], "isError": err})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
