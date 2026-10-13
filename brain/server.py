"""One process, one port: web UI + REST API + MCP endpoint + webhooks.

Start-up (all in background jobs, visible in the UI): start the code-graph engine, start the document-graph
engine, probe the corporate API, then clone/update and index every repository. The UI and API answer
immediately and report readiness at /api/status; `brain serve` also prints when everything is ready.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import agents, auth, drift, jobs, llm, mcp, providers, query, repos, search, srs, webhooks
from . import settings as cfg

UI = Path(__file__).parent / "ui"
log = logging.getLogger("brain")
STARTUP: dict = {"llm": {"state": "starting"}, "started": time.time()}


# ---------------------------------------------------------------- start-up
def _start_engine(kind: str, job: jobs.Job) -> dict:
    eng = providers.get(kind)
    job.log(f"starting {eng.name}")
    eng.start()
    if eng.state != "ready":
        raise RuntimeError(eng.detail)
    return eng.health()


def _check_llm(job: jobs.Job) -> dict:
    job.log("calling chat and embedding endpoints")
    res = llm.check()
    STARTUP["llm"] = {"state": "ready" if res["chat"] and res["embedding"] else "error", **res}
    if res["errors"]:
        raise RuntimeError("; ".join(res["errors"]))
    return res


def _ensure_webhook_secrets() -> None:
    """Repositories added by editing repos.json by hand get their webhook secret at start-up."""
    try:
        if any(not r["webhook_secret"] for r in repos.all_repos()):
            cfg.save_repos(repos.all_repos(), cfg.load_sets())
            log.info("generated webhook secrets for repositories that had none")
    except Exception as exc:
        log.warning("could not generate webhook secrets: %s", exc)


def boot() -> None:
    _ensure_webhook_secrets()
    code_job = jobs.start("startup", "Start code graph engine", lambda j: _start_engine("code", j))
    jobs.start("startup", "Start document graph engine (LightRAG)", lambda j: _start_engine("docs", j))
    jobs.start("startup", "Check corporate API (chat + embeddings)", _check_llm)

    def initial_sync():
        while code_job.state == "running":
            time.sleep(0.5)
        if cfg.get("BRAIN_SYNC_ON_START") and repos.all_repos() and code_job.state == "done":
            repos.request_sync(None, "start-up")
        repos.refresh_stale()   # every repository at least every BRAIN_SYNC_INTERVAL_MINUTES (24 h)
    threading.Thread(target=initial_sync, daemon=True).start()
    threading.Thread(target=repos.watch_local, daemon=True, name="watch-local").start()


@asynccontextmanager
async def lifespan(_app):
    boot()
    yield
    for kind in ("docs", "code"):
        try:
            providers.get(kind).stop()
        except Exception:
            pass


app = FastAPI(title="AI-BRAIN", version="1.0.0", docs_url="/api/docs-ui", redoc_url=None, lifespan=lifespan)
app.mount("/ui", StaticFiles(directory=UI), name="ui")
PUBLIC = ("/", "/healthz", "/api/login", "/api/logout", "/webhooks/", "/ui/", "/favicon.ico")


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC or path.startswith(("/webhooks/", "/ui/")):
        return await call_next(request)
    ip = request.client.host if request.client else "?"
    user, method = auth.identify({k.lower(): v for k, v in request.headers.items()}, request.cookies, ip)
    if not user:
        return JSONResponse({"detail": "authentication required"}, status_code=401,
                            headers={} if path.startswith("/api/") and request.headers.get("x-brain-ui")
                            else {"WWW-Authenticate": 'Basic realm="ai-brain"'})
    if method == "cookie" and request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-brain-ui") != "1":
        return JSONResponse({"detail": "missing X-Brain-UI header"}, status_code=403)
    request.state.user = user
    return await call_next(request)


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(404, str(exc.args[0] if exc.args else exc))
    if isinstance(exc, ValueError):
        return HTTPException(400, str(exc))
    return HTTPException(500, f"{type(exc).__name__}: {exc}")


async def _run(fn, *a, **kw):
    try:
        return await run_in_threadpool(fn, *a, **kw)
    except HTTPException:
        raise
    except Exception as exc:
        raise _err(exc) from None


# ---------------------------------------------------------------- pages, session
@app.get("/")
def index():
    return FileResponse(UI / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/login")
def login(request: Request, body: dict = Body(...)):
    ip = request.client.host if request.client else "?"
    if auth.locked(ip):
        raise HTTPException(429, "too many failed logins; wait a minute")
    if not auth.check_password(str(body.get("username", "")), str(body.get("password", "")), ip):
        raise HTTPException(401, "wrong user name or password")
    r = JSONResponse({"user": body["username"]})
    r.set_cookie(auth.COOKIE, auth.make_session(body["username"]), httponly=True, samesite="strict",
                 secure=bool(cfg.get("BRAIN_TLS_CERT")), max_age=int(cfg.get("BRAIN_SESSION_HOURS") * 3600))
    return r


@app.post("/api/logout")
def logout():
    r = JSONResponse({"ok": True})
    r.delete_cookie(auth.COOKIE)
    return r


@app.get("/api/me")
def me(request: Request):
    return {"user": request.state.user, "public_url": cfg.get("BRAIN_PUBLIC_URL") or str(request.base_url).rstrip("/")}


# ---------------------------------------------------------------- status & jobs
@app.get("/api/status")
def status():
    eng = {}
    for kind in ("code", "docs"):
        try:
            eng[kind] = providers.get(kind).health()
        except Exception as exc:
            eng[kind] = {"state": "error", "detail": f"provider failed to load: {exc}"}
    ready = all(eng[k]["state"] == "ready" for k in eng) and STARTUP["llm"].get("state") == "ready"
    try:
        pipe = providers.docs().pipeline() if eng["docs"]["state"] == "ready" else {}
    except Exception:
        pipe = {}
    return {"ready": ready, "engines": eng, "llm": STARTUP["llm"], "pipeline": pipe,
            "models": {"default": cfg.get("BRAIN_LLM_MODEL"), "ask": cfg.model("ask"), "enhance": cfg.model("enhance"),
                       "srs": cfg.model("srs"), "guide": cfg.model("guide"), "lightrag": cfg.model("lightrag"), "embedding": cfg.get("BRAIN_EMBEDDING_MODEL"),
                       "vision": cfg.get("BRAIN_VLM_MODEL") or None},
            "running": [j for j in jobs.recent(50) if j["state"] == "running"],
            "uptime": round(time.time() - STARTUP["started"])}


@app.get("/api/jobs")
def job_list(kind: str | None = None, limit: int = 50):
    return jobs.recent(limit, kind)


@app.get("/api/jobs/{job_id}")
def job_get(job_id: int):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "unknown job")
    return j.view(full=True)


@app.get("/api/logs/{name}")
def logs(name: str, lines: int = 200):
    f = {"lightrag": "lightrag.log", "code": "codebase-memory.log", "server": "server.log"}.get(name)
    if not f:
        raise HTTPException(404, "logs: lightrag | code | server")
    p = cfg.data_dir() / "logs" / f
    text = p.read_text(encoding="utf-8", errors="replace").splitlines()[-min(lines, 2000):] if p.exists() else []
    return {"name": name, "lines": text}


# ---------------------------------------------------------------- search / ask / enhance / drift
def _scope(b: dict) -> tuple:
    """(set, repos, branch). `target` is the UI combobox value: "set:<name>" or "repo:<name>"."""
    rn = b.get("repos")
    if isinstance(rn, str):
        rn = [x for x in rn.split(",") if x]
    set_name = b.get("set") or None
    kind, _, value = str(b.get("target") or "").partition(":")
    if kind == "repo" and value:
        rn, set_name = [value], None
    elif kind == "set" and value:
        set_name = value
    return set_name, rn or None, b.get("branch") or None


@app.get("/api/models")
def api_models():
    """Chat models offered by the corporate API (GET /models), for the model comboboxes; falls back to the
    configured ones when the gateway does not list models."""
    configured = [m for m in dict.fromkeys([cfg.get("BRAIN_LLM_MODEL"), cfg.model("ask"), cfg.model("enhance"),
                                            cfg.model("srs"), cfg.model("guide")]) if m]
    try:
        listed = llm.models()
        error = None
    except llm.LLMError as exc:
        listed, error = [], str(exc)
    embed = cfg.get("BRAIN_EMBEDDING_MODEL")
    models = [m for m in dict.fromkeys(configured + listed) if m and m != embed]
    return {"models": models, "listed": bool(listed), "error": error,
            "defaults": {"ask": cfg.model("ask"), "enhance": cfg.model("enhance"), "srs": cfg.model("srs"),
                         "guide": cfg.model("guide")}}


@app.post("/api/analyze")
def api_analyze(body: dict = Body(...)):
    """Prompt analysis only (stop-words, ranked key terms, variants, concepts); also the first step of the others."""
    a = query.analyze(str(body.get("text") or body.get("query") or body.get("prompt") or body.get("question") or ""))
    return {**a, "summary": query.summary(a)}


@app.post("/api/search")
async def api_search(body: dict = Body(...)):
    if not str(body.get("query", "")).strip():
        raise HTTPException(400, "query is required")
    r = await _run(search.search, body["query"], body.get("scope", "all"), *_scope(body), k=body.get("k"))
    return {**r, "markdown": search.render(r, 60000, body.get("detail"))}


def _agent(kind: str, body: dict, fn):
    if body.get("async"):
        job = jobs.start(kind, f"{kind}: {str(body.get('question') or body.get('prompt'))[:80]}",
                         lambda j: fn(log=j.log))
        return {"job": job.id}
    return fn()


@app.post("/api/ask")
async def api_ask(body: dict = Body(...)):
    q = str(body.get("question", "")).strip()
    if not q:
        raise HTTPException(400, "question is required")
    return await _run(_agent, "ask", body, lambda log=lambda *a, **k: None: agents.ask(
        q, *_scope(body), model=body.get("model") or None, log=log))


@app.post("/api/enhance")
async def api_enhance(body: dict = Body(...)):
    p = str(body.get("prompt", "")).strip()
    if not p:
        raise HTTPException(400, "prompt is required")
    return await _run(_agent, "enhance", body, lambda log=lambda *a, **k: None: agents.enhance(
        p, *_scope(body), repo=body.get("repo"), base_commit=body.get("base_commit"),
        changed_files=body.get("changed_files"), model=body.get("model") or None, log=log))


@app.post("/api/guide")
async def api_guide(body: dict = Body(...)):
    """A project guide for newcomers (background job unless "async": false)."""
    set_name, rn, _ = _scope(body)

    def fn(log=lambda *a, **k: None):
        return agents.guide(str(body.get("topic") or ""), set_name, rn, model=body.get("model") or None, log=log)
    if body.get("async", True):
        return {"job": jobs.start("guide", f"Project guide: {body.get('target') or 'all'}", lambda j: fn(log=j.log)).id}
    return await _run(fn)


@app.post("/api/drift")
async def api_drift(body: dict = Body(...)):
    if not body.get("repo"):
        raise HTTPException(400, "repo is required")
    rep = await _run(drift.check, body["repo"], body.get("branch"), body.get("base_commit"),
                     body.get("changed_files"), body.get("head_commit"))
    return {**rep, "markdown": drift.render(rep)}


# ---------------------------------------------------------------- repositories & sets
def _base(request: Request) -> str:
    return cfg.get("BRAIN_PUBLIC_URL") or str(request.base_url).rstrip("/")


@app.get("/api/repos")
async def repo_list(request: Request):
    """Repositories with state and their own webhook, plus the repository sets."""
    return {"repos": await _run(repos.overview, _base(request)), "sets": repos.sets(), "file": str(cfg.repos_file())}


@app.put("/api/repos")
async def repo_save(body: dict = Body(...)):
    """Save repositories and sets: {"repos": [...], "sets": {"name": ["repo", ...]}}."""
    return await _run(cfg.save_repos, body.get("repos", []), body.get("sets"))


@app.post("/api/repos/sync")
def repo_sync_all():
    job = repos.request_sync(None, "manual")
    return {"job": job.id if job else None}


@app.post("/api/repos/{name}/sync")
def repo_sync(name: str):
    try:
        repos.repo(name)
    except KeyError as exc:
        raise _err(exc) from None
    job = repos.request_sync(name, "manual")
    return {"job": job.id if job else None, "queued": job is None}


@app.post("/api/repos/{name}/branches")
def repo_branch(name: str, body: dict = Body(...)):
    branch = str(body.get("branch", "")).strip()
    if not branch:
        raise HTTPException(400, "branch is required")
    job = jobs.start("branch", f"Index branch {name}@{branch}", lambda j: repos.index_branch(name, branch, j))
    return {"job": job.id}


@app.delete("/api/repos/{name}/branches/{branch:path}")
async def repo_branch_delete(name: str, branch: str):
    await _run(repos.remove_branch, name, branch)
    return {"removed": f"{name}@{branch}"}


# ---------------------------------------------------------------- code graph (UI)
@app.get("/api/code/projects")
async def code_projects():
    return await _run(providers.code().projects)


@app.get("/api/code/graph")
async def code_graph(project: str, limit: int = 1200):
    return await _run(providers.code().graph, project, min(limit, 5000))


@app.get("/api/code/ego/{node_id}")
async def code_ego(node_id: int, project: str, depth: int = 1):
    return await _run(providers.code().ego, project, node_id, depth)


@app.get("/api/code/node/{node_id}")
async def code_node(node_id: int, project: str):
    d = await _run(providers.code().node, project, node_id)
    if not d:
        raise HTTPException(404, "node not found")
    return d


@app.get("/api/code/find")
async def code_find(q: str, project: str | None = None):
    projects = [project] if project else [p["name"] for p in providers.code().projects()]
    return await _run(providers.code().find, q, projects, 25)


def _code_ctx(target: str = "", repo: str = "") -> "agents.Context":
    return agents.Context(*_scope({"target": target, "repos": repo}))


@app.get("/api/code/symbol")
async def code_symbol(name: str, target: str = "", repo: str = "", source: str = "auto"):
    """A symbol by name: location, signature, source, callers, callees (Markdown)."""
    return {"text": await _run(lambda: _code_ctx(target, repo).run_tool("symbol", {"name": name, "source": source}))}


@app.get("/api/code/outline")
async def code_outline(path: str, target: str = "", repo: str = ""):
    """Declarations of one file with line ranges (Markdown)."""
    return {"text": await _run(lambda: _code_ctx(target, repo).run_tool("outline", {"path": path}))}


@app.get("/api/code/overview")
async def code_overview(repo: str, path: str = "", aspects: str = "overview"):
    """A repository's structure (Markdown); aspects: comma list of overview, structure, routes, hotspots,
    entry_points, dependencies, layers, file_tree."""
    a = {"repo": repo, "path": path or None, "aspects": [x for x in aspects.split(",") if x]}
    return {"text": await _run(lambda: _code_ctx("", repo).run_tool("overview", a))}


@app.get("/api/code/read")
async def code_read(path: str, repo: str = "", target: str = "", start: int = 1, end: int | None = None):
    """Numbered lines of a file in an indexed repository (max 400): the knowledge-base replacement for `read`.
    Without `repo`, the first repository of the scope that has the file is used."""
    def run():
        ctx = _code_ctx(target, repo)
        return ctx._first(repo or None, lambda p: providers.code().read(p, path, start, end))
    return await _run(run)


@app.get("/api/code/files")
async def code_files(pattern: str = "*", target: str = "", repo: str = ""):
    """Indexed file paths matching a glob in one repository or a set: the replacement for `glob`."""
    def run():
        ctx = _code_ctx(target, repo)
        return [f"{p}/{f}" for p in ctx.projects for f in providers.code().files(p, pattern)]
    return {"files": await _run(run)}


@app.post("/api/code/grep")
async def code_grep(body: dict = Body(...)):
    """Exact text / regex search over the indexed code, ranked by the code graph: the replacement for `grep`."""
    if not str(body.get("pattern", "")).strip():
        raise HTTPException(400, "pattern is required")
    args = {k: body.get(k) for k in ("pattern", "regex", "file_pattern", "mode", "path")}
    return {"text": await _run(lambda: agents.Context(*_scope(body)).run_tool("grep", args))}


# ---------------------------------------------------------------- documents
@app.get("/api/docs")
async def doc_list():
    d = providers.docs()
    return {"documents": await _run(d.documents), "pipeline": await _run(d.pipeline)}


@app.post("/api/docs/upload")
async def doc_upload(files: list[UploadFile] = File(...)):
    limit = cfg.get("BRAIN_MAX_UPLOAD_MB") * 1024 * 1024
    batch = []
    for f in files:
        data = await f.read()
        if len(data) > limit:
            raise HTTPException(413, f"{f.filename}: larger than BRAIN_MAX_UPLOAD_MB={cfg.get('BRAIN_MAX_UPLOAD_MB')}")
        batch.append((f.filename or "document", data))

    def work(job):
        out = []
        for i, (name, data) in enumerate(batch):
            job.log(f"converting and uploading {name}", i / len(batch))
            try:
                out.append(providers.docs().upload(name, data))
            except Exception as exc:
                out.append({"file": name, "status": "failure", "message": str(exc)})
                job.log(f"{name} failed: {exc}")
        if all(o.get("status") == "failure" for o in out):
            raise RuntimeError("; ".join(f"{o['file']}: {o.get('message')}" for o in out))
        return out
    job = jobs.start("upload", f"Upload {len(batch)} document(s)", work)
    return {"job": job.id}


@app.post("/api/docs/text")
async def doc_text(body: dict = Body(...)):
    if not body.get("text"):
        raise HTTPException(400, "text is required")
    return await _run(providers.docs().add_text, body.get("name") or "note.md", body["text"])


@app.delete("/api/docs/{doc_id}")
async def doc_delete(doc_id: str):
    return await _run(providers.docs().delete, [doc_id])


@app.get("/api/docs/graph")
async def doc_graph(label: str = "*", max_nodes: int = 600, depth: int = 3):
    return await _run(providers.docs().graph, label, min(max_nodes, 3000), min(depth, 6))


@app.get("/api/docs/labels")
async def doc_labels(q: str = ""):
    return await _run(providers.docs().labels, q)


@app.get("/api/docs/markdown")
async def doc_markdown(name: str):
    """The Markdown a document was converted to before it went to the document graph."""
    return {"name": name, "markdown": await _run(providers.docs().markdown, name)}


# ---------------------------------------------------------------- requirements writer (SRS)
@app.get("/api/srs/templates")
def srs_templates():
    return {"templates": srs.templates()}


@app.get("/api/srs/templates/{name}")
async def srs_template_get(name: str):
    return {"name": name, "text": await _run(srs.get_template, name)}


@app.put("/api/srs/templates/{name}")
async def srs_template_put(name: str, body: dict = Body(...)):
    return {"saved": await _run(srs.save_template, name, str(body.get("text") or ""))}


@app.delete("/api/srs/templates/{name}")
async def srs_template_delete(name: str):
    await _run(srs.delete_template, name)
    return {"deleted": name}


@app.post("/api/srs")
async def srs_write(body: dict = Body(...)):
    """Write a specification (background job unless "async": false). mode: existing (describe what the code and
    documents contain) | new (specify something new from the request, with the knowledge base as context)."""
    topic = str(body.get("topic", "")).strip()
    if not topic:
        raise HTTPException(400, "topic is required")
    set_name, rn, _ = _scope(body)

    def fn(log=lambda *a, **k: None):
        return srs.write(topic, set_name, rn, body.get("template") or None, body.get("language") or None,
                         body.get("model") or None, body.get("title") or None, mode=body.get("mode") or "existing", log=log)
    if body.get("async", True):
        return {"job": jobs.start("srs", f"Requirements: {topic[:80]}", lambda j: fn(log=j.log)).id}
    return await _run(fn)


@app.get("/api/srs/documents")
def srs_documents():
    return {"documents": srs.documents()}


@app.get("/api/srs/documents/{name}")
async def srs_document(name: str):
    return {"name": name, "markdown": await _run(srs.read, name)}


@app.delete("/api/srs/documents/{name}")
async def srs_document_delete(name: str):
    await _run(srs.delete, name)
    return {"deleted": name}


@app.post("/api/srs/documents/{name}/publish")
async def srs_publish(name: str):
    """Add a specification to the document graph, so search/ask/enhance can use it."""
    md = await _run(srs.read, name)
    return await _run(providers.docs().add_text, f"SRS-{name}.md", md)


# ---------------------------------------------------------------- settings
@app.get("/api/settings")
def settings_get():
    return {"settings": cfg.public_view(), "file": str(cfg.config_file())}


@app.put("/api/settings")
def settings_put(body: dict = Body(...)):
    changes = {k: ("" if v is None else str(v)) for k, v in (body.get("changes") or {}).items()}
    try:
        scopes = cfg.update(changes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    started = []
    for kind in ("code", "docs"):
        if kind in scopes:
            started.append(jobs.start("restart", f"Restart {kind} engine (settings changed)",
                                      lambda j, k=kind: providers.reload(k).health()).id)
    if any(k.startswith("BRAIN_LLM") or k.startswith("BRAIN_EMBEDDING") for k in changes):
        started.append(jobs.start("startup", "Check corporate API (chat + embeddings)", _check_llm).id)
    return {"saved": sorted(changes), "jobs": started,
            "restart_server": "server" in scopes,
            "message": "saved" + ("; restart the server for host/port/TLS/data-dir changes" if "server" in scopes else "")}


@app.post("/api/restart/{kind}")
def restart(kind: str):
    if kind not in ("code", "docs"):
        raise HTTPException(404, "kind: code | docs")
    return {"job": jobs.start("restart", f"Restart {kind} engine", lambda j: providers.reload(kind).health()).id}


# ---------------------------------------------------------------- webhooks
async def _payload(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        raise HTTPException(400, "JSON body expected") from None


@app.post("/webhooks/gitlab")
async def hook_gitlab(request: Request):
    code, body = await run_in_threadpool(webhooks.gitlab, {k.lower(): v for k, v in request.headers.items()},
                                         await _payload(request))
    return JSONResponse(body, status_code=code)


@app.post("/webhooks/repo/{name}")
async def hook_repo(name: str, request: Request):
    """A repository's own webhook (GitLab or TFS, recognised from the request; secret per repository)."""
    code, body = await run_in_threadpool(webhooks.repo_hook, name, {k.lower(): v for k, v in request.headers.items()},
                                         await _payload(request))
    return JSONResponse(body, status_code=code)


@app.post("/webhooks/tfs")
async def hook_tfs(request: Request):
    code, body = await run_in_threadpool(webhooks.tfs, {k.lower(): v for k, v in request.headers.items()},
                                         await _payload(request))
    return JSONResponse(body, status_code=code)


@app.get("/api/webhooks")
def hook_log(request: Request):
    base = cfg.get("BRAIN_PUBLIC_URL") or str(request.base_url).rstrip("/")
    return {"gitlab_url": base + "/webhooks/gitlab", "tfs_url": base + "/webhooks/tfs",
            "gitlab_configured": bool(cfg.get("BRAIN_GITLAB_WEBHOOK_SECRET")),
            "tfs_configured": bool(cfg.get("BRAIN_TFS_WEBHOOK_PASSWORD")), "events": cfg.get("BRAIN_WEBHOOK_EVENTS"),
            "deliveries": list(webhooks.LOG)}


# ---------------------------------------------------------------- MCP (Streamable HTTP, JSON mode)
@app.post("/mcp")
async def mcp_post(request: Request):
    payload = await _payload(request)
    msgs = payload if isinstance(payload, list) else [payload]
    replies = await run_in_threadpool(lambda: [r for r in (mcp.handle(m) for m in msgs) if r is not None])
    if not replies:
        return Response(status_code=202)
    return JSONResponse(replies if isinstance(payload, list) else replies[0])


@app.get("/mcp")
def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})


@app.delete("/mcp")
def mcp_delete():
    return Response(status_code=200)


# ---------------------------------------------------------------- entry point
def _loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def main() -> None:
    import uvicorn
    logs_dir = cfg.path("logs")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(logs_dir / "server.log", encoding="utf-8")])
    host, port = cfg.get("BRAIN_HOST"), cfg.get("BRAIN_PORT")
    if not cfg.get("BRAIN_UI_PASSWORD") and not _loopback(host):
        sys.exit("BRAIN_UI_PASSWORD is empty: refusing to listen on a non-loopback address. Set it in .env.")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # avoid Proactor bind races
    scheme = "https" if cfg.get("BRAIN_TLS_CERT") else "http"
    log.info("UI + REST + MCP (/mcp) + webhooks on %s://%s:%s", scheme, host, port)

    def announce():
        t0 = time.time()
        while time.time() - t0 < 900:
            time.sleep(2)
            st = status()
            if st["ready"]:
                log.info("READY: code graph, document graph and the agents (ask, enhance, guide, requirements) are up (%.0fs)", time.time() - t0)
                return
        log.warning("not fully ready after 15 min; open the UI Overview page for details")
    threading.Thread(target=announce, daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="warning",
                ssl_certfile=cfg.get("BRAIN_TLS_CERT") or None, ssl_keyfile=cfg.get("BRAIN_TLS_KEY") or None)
