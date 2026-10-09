"""MCP server (Streamable HTTP transport, JSON responses) at POST /mcp, for any MCP client:
Claude Code, opencode, Cursor, Continue, Copilot ... Register it under the name "brain"; tools then show up as
brain_search / mcp__brain__search etc. Authentication: `Authorization: Bearer <BRAIN_API_TOKEN>`.
"""
from __future__ import annotations

import json

from . import agents, drift, providers, repos, search, srs

VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SCOPE = {"set": {"type": "string", "description": "Repository set: the request covers ALL its repositories (default: all)."},
         "repos": {"type": "array", "items": {"type": "string"}, "description": "Limit to these repositories (e.g. one)."},
         "branch": {"type": "string", "description": "Your current git branch (uses a branch overlay if one exists)."}}


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": {**props, **SCOPE}, "required": required}


TOOLS = [
    {"name": "search",
     "description": "FIRST STOP for research. Searches the organisation's code graph (all languages: symbols, call "
                    "graph), code vectors (code by meaning, Turkish or English) AND document graph (specs, rules, "
                    "decisions) without any LLM call. Returns code locations with signature, callers, callees, why "
                    "each matched and source, plus relationships, document passages and domain facts.",
     "inputSchema": _schema({"query": {"type": "string"},
                             "scope": {"type": "string", "enum": ["all", "code", "semantic", "docs"], "default": "all",
                                       "description": "semantic = code by meaning only"},
                             "k": {"type": "integer", "default": 8}}, ["query"])},
    {"name": "ask",
     "description": "Ask a question; an AI-BRAIN agent researches code + documents and returns a grounded "
                    "answer with sources. Slower than search (uses the LLM).",
     "inputSchema": _schema({"question": {"type": "string"},
                             "model": {"type": "string", "description": "chat model (default: configured)"}}, ["question"])},
    {"name": "enhance_prompt",
     "description": "Turn a short development request into a precise, implementation-ready prompt (task, relevant "
                    "code, business rules, impact, plan, acceptance criteria). Pass repo/branch/base_commit/"
                    "changed_files to also get branch-drift warnings.",
     "inputSchema": _schema({"prompt": {"type": "string"}, "repo": {"type": "string"},
                             "base_commit": {"type": "string"},
                             "changed_files": {"type": "array", "items": {"type": "string"}},
                             "model": {"type": "string", "description": "chat model (default: configured)"}}, ["prompt"])},
    {"name": "write_requirements",
     "description": "Write a Software Requirements Specification in plain language (for non-technical readers) "
                    "from the code and documents, following a format (template). Slow: several model calls.",
     "inputSchema": _schema({"topic": {"type": "string", "description": "system, module or feature to specify"},
                             "template": {"type": "string", "default": "default"},
                             "language": {"type": "string", "description": "auto, English, Turkish ..."},
                             "model": {"type": "string"}}, ["topic"])},
    {"name": "check_branch",
     "description": "The knowledge base follows main. Call this when working on another branch: it reports how far "
                    "your branch is behind main, files changed on both sides (conflict risk), and what to do. Run "
                    "locally first: `git rev-parse --abbrev-ref HEAD`, `git merge-base HEAD origin/main`, "
                    "`git diff --name-only origin/main...HEAD` and `git status --porcelain`, and pass the results.",
     "inputSchema": {"type": "object", "properties": {
         "repo": {"type": "string"}, "branch": {"type": "string"}, "base_commit": {"type": "string"},
         "head_commit": {"type": "string"}, "changed_files": {"type": "array", "items": {"type": "string"}}},
         "required": ["repo"]}},
    {"name": "symbol", "description": "Definition, source, callers, callees of a class/function/method by name.",
     "inputSchema": _schema({"name": {"type": "string"}}, ["name"])},
    {"name": "trace", "description": "Call chain (inbound callers / outbound callees) of a function, for impact analysis.",
     "inputSchema": _schema({"function_name": {"type": "string"}, "repo": {"type": "string"},
                             "direction": {"type": "string", "enum": ["inbound", "outbound", "both"]},
                             "depth": {"type": "integer", "default": 3}}, ["function_name"])},
    {"name": "snippet", "description": "Full source of a symbol by qualified or short name.",
     "inputSchema": _schema({"qualified_name": {"type": "string"}, "repo": {"type": "string"}}, ["qualified_name"])},
    {"name": "read", "description": "Read lines of a file in an indexed repository (numbered, max 400 lines). "
                                     "Use instead of reading files locally when the repository is not on your machine.",
     "inputSchema": {"type": "object", "properties": {"repo": {"type": "string"}, "path": {"type": "string"},
                     "start": {"type": "integer", "default": 1}, "end": {"type": "integer"}}, "required": ["repo", "path"]}},
    {"name": "grep", "description": "Exact text or regex search over the indexed code of one repository or a set, "
                                     "ranked by the code graph. Use instead of grep/rg.",
     "inputSchema": _schema({"pattern": {"type": "string"}, "regex": {"type": "boolean", "default": False},
                             "file_pattern": {"type": "string", "description": "e.g. *.java"}}, ["pattern"])},
    {"name": "files", "description": "List indexed file paths matching a glob (e.g. **/*.sql, src/billing/*). Use instead of glob.",
     "inputSchema": _schema({"pattern": {"type": "string", "default": "*"}}, ["pattern"])},
    {"name": "list_repos", "description": "Configured repositories, their sets, indexed commit and branch overlays.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_documents", "description": "Documents in the document graph with processing status.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "add_note", "description": "Store a note/decision/finding as a new document in the document graph.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "text": {"type": "string"}},
                     "required": ["name", "text"]}},
    {"name": "sync_repo", "description": "Update and re-index one repository (or all) in the background.",
     "inputSchema": {"type": "object", "properties": {"repo": {"type": "string"}}}},
]


def _scope(a: dict) -> tuple:
    return a.get("set"), a.get("repos"), a.get("branch")


def call_tool(name: str, a: dict) -> str:
    if name == "search":
        r = search.search(a["query"], a.get("scope", "all"), *_scope(a), k=a.get("k"))
        return (search.render(r, 30000) or "No AI-BRAIN matches.") + \
            (f"\n\n(errors: {'; '.join(r['errors'])})" if r["errors"] else "")
    if name == "ask":
        r = agents.ask(a["question"], *_scope(a), model=a.get("model"))
        return r["answer"] + (f"\n\n(notes: {'; '.join(r['errors'])})" if r["errors"] else "")
    if name == "enhance_prompt":
        r = agents.enhance(a["prompt"], *_scope(a), repo=a.get("repo"), base_commit=a.get("base_commit"),
                           changed_files=a.get("changed_files"), model=a.get("model"))
        return r["enhanced"]
    if name == "write_requirements":
        r = srs.write(a["topic"], a.get("set"), a.get("repos"), a.get("template") or "default", a.get("language"),
                      a.get("model"))
        return r["markdown"] + (f"\n\n(notes: {'; '.join(r['errors'])})" if r["errors"] else "")
    if name == "check_branch":
        return drift.render(drift.check(a["repo"], a.get("branch"), a.get("base_commit"), a.get("changed_files"),
                                        a.get("head_commit")))
    ctx = agents.Context(*_scope(a)) if name in ("symbol", "trace", "snippet", "grep", "files") else None
    if name == "read":
        return agents.Context(None, [a["repo"]]).run_tool("read", a)
    if name in ("grep", "files"):
        return ctx.run_tool(name, a)
    if name == "symbol":
        return ctx.run_tool("symbol", a)
    if name == "trace":
        return providers.code().tool("trace", {"function_name": a["function_name"], "project": ctx.project(a.get("repo")),
                                               "direction": a.get("direction") or "both", "depth": int(a.get("depth") or 3)})
    if name == "snippet":
        return ctx.run_tool("snippet", a)
    if name == "list_repos":
        return json.dumps([{k: v for k, v in r.items() if k not in ("webhook", "webhook_secret")}
                           for r in repos.overview()], indent=1, default=str)
    if name == "list_documents":
        return "\n".join(f"{d['id']}  {d['status']:<10} {d['name']}" for d in providers.docs().documents()) or "No documents."
    if name == "add_note":
        return json.dumps(providers.docs().add_text(a["name"], a["text"]), ensure_ascii=False)
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
                   "serverInfo": {"name": "ai-brain", "version": "1.0.0"},
                   "instructions": "Organisation knowledge base (code graph + document graph). Call `search` before "
                                   "grep/glob/read; `enhance_prompt` to plan a task; `check_branch` when not on main."})
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
