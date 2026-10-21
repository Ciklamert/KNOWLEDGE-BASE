"""AI-BRAIN - one command for everything (run through brain.cmd on Windows, ./brain.sh on Linux).

  brain serve                       start UI + REST API + MCP + webhooks; starts both graph engines and agents
  brain doctor                      check Python, settings, corporate API, engines, repositories
  brain sync [REPO]                 update + re-index one repository (or all) on the running server
  brain search "text" [--scope all|code|semantic|docs] [--set S]   search (no LLM)
  brain ask "question" [--set S]    ask the AI-BRAIN ask agent (grounded answer with sources)
  brain enhance "prompt" [--set S]  print an implementation-ready prompt for an AI coding agent
  brain guide ["topic"] [--set S]   write a project guide for newcomers
  brain drift [PATH] [--repo R]     compare your branch in PATH (default: .) with the indexed main
  brain hook [PATH] [--repo R] [--remove]   in a checkout: every `git pull` of main updates AI-BRAIN
  brain connect [claude|opencode|pi|all]   print the configuration for an AI agent
  brain version
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if sys.version_info[:2] != (3, 13):
    sys.exit(f"AI-BRAIN requires Python 3.13 (this is {sys.version.split()[0]}). Run setup.ps1 / setup.sh.")
from brain import settings as cfg  # noqa: E402

VERSION = "1.0.0"


def base_url() -> str:
    url = os.environ.get("BRAIN_URL") or cfg.get("BRAIN_PUBLIC_URL")
    if url:
        return url.rstrip("/")
    host = cfg.get("BRAIN_HOST")
    return f"{'https' if cfg.get('BRAIN_TLS_CERT') else 'http'}://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{cfg.get('BRAIN_PORT')}"


def api(method: str, path: str, body: dict | None = None, timeout: float = 900):
    import httpx
    headers = {}
    token = os.environ.get("BRAIN_API_TOKEN") or cfg.get("BRAIN_API_TOKEN")
    auth = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        auth = (cfg.get("BRAIN_UI_USER"), cfg.get("BRAIN_UI_PASSWORD"))
    try:
        r = httpx.request(method, base_url() + path, json=body, headers=headers, auth=auth, timeout=timeout,
                          trust_env=False, verify=False)
    except httpx.HTTPError as exc:
        sys.exit(f"cannot reach the knowledge base at {base_url()} ({exc}). Is `brain serve` running?")
    if r.status_code >= 400:
        sys.exit(f"HTTP {r.status_code}: {r.text[:500]}")
    return r.json()


def cmd_serve(_):
    from brain import server
    server.main()


def cmd_sync(a):
    print(json.dumps(api("POST", f"/api/repos/{a.repo}/sync" if a.repo else "/api/repos/sync"), indent=2))
    print("running in the background; progress: UI > Overview / Repositories")


def cmd_search(a):
    r = api("POST", "/api/search", {"query": " ".join(a.query), "scope": a.scope, "set": a.set, "branch": a.branch,
                                    "detail": a.detail})
    print(r["markdown"] or "no matches")
    if r["errors"]:
        print("\nerrors: " + "; ".join(r["errors"]), file=sys.stderr)


def cmd_ask(a):
    r = api("POST", "/api/ask", {"question": " ".join(a.question), "set": a.set, "branch": a.branch})
    print(r["answer"])
    print(f"\n-- {r['ms']} ms, tools: {[s['tool'] for s in r['steps']]}, notes: {r['errors']}", file=sys.stderr)


def _git(path: Path, *args) -> str:
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip() if r.returncode == 0 else ""


def local_git_facts(path: Path, main: str | None = None, candidates: list[str] | None = None) -> dict:
    """What the server needs to judge drift, computed in the developer's own checkout. Without `main`, the main
    branch HEAD derives from is the candidate with the fewest commits HEAD does not share."""
    if not main:
        best = (float("inf"), "main")
        for m in candidates or ["main"]:
            _git(path, "fetch", "--quiet", "origin", m)
            n = _git(path, "rev-list", "--count", f"origin/{m}..HEAD")
            if n.isdigit() and int(n) < best[0]:
                best = (int(n), m)
        main = best[1]
    _git(path, "fetch", "--quiet", "origin", main)
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    base = _git(path, "merge-base", "HEAD", f"origin/{main}")
    changed = set(_git(path, "diff", "--name-only", f"origin/{main}...HEAD").splitlines())
    changed |= {ln[3:].split(" -> ")[-1] for ln in _git(path, "status", "--porcelain").splitlines() if len(ln) > 3}
    url = _git(path, "remote", "get-url", "origin")
    return {"branch": branch, "base_commit": base or None, "head_commit": _git(path, "rev-parse", "HEAD"),
            "changed_files": sorted(x for x in changed if x), "remote": url, "main": main}


def _guess_repo(remote: str, path: Path) -> str:
    repos = api("GET", "/api/repos")["repos"]
    tail = remote.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1].lower() if remote else path.name.lower()
    for r in repos:
        url = (r.get("remote") or r["url"] or "").rstrip("/").removesuffix(".git").lower()
        if r["name"].lower() == tail or (url and url.endswith("/" + tail)):
            return r["name"]
    sys.exit(f"cannot tell which configured repository {path} is; pass --repo NAME")


def repo_facts(path: Path, repo: str | None, main: str | None = None) -> tuple[dict, str]:
    """The local git facts of a checkout and its configured repository; without --main, the base is the nearest of
    the repository's main branches."""
    if not _git(path, "rev-parse", "--abbrev-ref", "HEAD"):
        sys.exit(f"{path} is not a git checkout")
    repo = repo or _guess_repo(_git(path, "remote", "get-url", "origin"), path)
    info = next((r for r in api("GET", "/api/repos")["repos"] if r["name"] == repo), {})
    return local_git_facts(path, main, [info.get("branch") or "main", *info.get("mains", [])]), repo


def cmd_enhance(a):
    body = {"prompt": " ".join(a.prompt), "set": a.set, "branch": a.branch}
    if a.path:
        facts, repo = repo_facts(Path(a.path).resolve(), a.repo)
        body.update(repo=repo, branch=facts["branch"], base_commit=facts["base_commit"],
                    changed_files=facts["changed_files"])
    r = api("POST", "/api/enhance", body)
    print(r["enhanced"])
    print(f"\n-- {r['ms']} ms, llm: {r['llm']}, tools: {[s['tool'] for s in r['steps']]}, notes: {r['errors']}",
          file=sys.stderr)


def cmd_guide(a):
    r = api("POST", "/api/guide", {"topic": " ".join(a.topic), "set": a.set, "repos": [a.repo] if a.repo else None,
                                   "async": False}, timeout=1800)
    print(r["guide"])
    print(f"\n-- {r['ms']} ms, usage: {r.get('usage')}, notes: {r['errors']}", file=sys.stderr)


HOOKS = ("post-merge", "post-rewrite")


def cmd_hook(a):
    """Install (or remove) git hooks in a checkout so that every pull of the tracked branch updates AI-BRAIN."""
    path = Path(a.path).resolve()
    hooks = Path(_git(path, "rev-parse", "--git-path", "hooks") or "")
    if not str(hooks):
        sys.exit(f"{path} is not a git checkout")
    hooks = hooks if hooks.is_absolute() else path / hooks
    if a.remove:
        for h in HOOKS:
            f = hooks / h
            if f.exists() and "ai-brain:" in f.read_text(encoding="utf-8", errors="replace"):
                f.unlink()
                print(f"removed {f}")
        return
    repo = a.repo or _guess_repo(_git(path, "remote", "get-url", "origin"), path)
    branch = next((r["branch"] for r in api("GET", "/api/repos")["repos"] if r["name"] == repo), "main")
    from brain import repos
    text = repos.hook_script(repo, branch, Path(sys.executable).as_posix(), (ROOT / "brain.py").as_posix())
    hooks.mkdir(parents=True, exist_ok=True)
    for h in HOOKS:
        f = hooks / h
        if f.exists() and "ai-brain:" not in f.read_text(encoding="utf-8", errors="replace"):
            sys.exit(f"{f} already exists and is not AI-BRAIN's: add this line to it instead:\n"
                     f"  \"{Path(sys.executable).as_posix()}\" \"{(ROOT / 'brain.py').as_posix()}\" sync {repo} &")
        f.write_text(text, encoding="utf-8", newline="\n")
        f.chmod(0o755)
        print(f"installed {f}")
    print(f"every `git pull` of {branch} in {path} now updates repository '{repo}' on {base_url()}")


def cmd_drift(a):
    facts, repo = repo_facts(Path(a.path).resolve(), a.repo, a.main)
    r = api("POST", "/api/drift", {"repo": repo, "base": facts["main"], **{k: facts[k] for k in (
        "branch", "base_commit", "head_commit", "changed_files")}})
    print(r["markdown"])


def cmd_impact(a):
    """What a change reaches and which tests to run: the files given, or the local branch's changes (for CI)."""
    path = Path(a.path).resolve()
    files = a.files
    repo = a.repo
    if not files:
        facts, repo = repo_facts(path, repo, a.main)
        files = facts["changed_files"]
    if not files:
        sys.exit("no changed files")
    print(api("POST", "/api/impact", {"files": files, "repos": [repo] if repo else None})["markdown"])


def cmd_connect(a):
    url, token = base_url(), cfg.get("BRAIN_API_TOKEN") or "<BRAIN_API_TOKEN>"
    which = {"claude", "opencode", "pi"} if a.agent == "all" else {a.agent}
    if "claude" in which:
        print("# Claude Code - run once (user scope), or put the JSON in .mcp.json of a project:")
        print(f'claude mcp add --transport http --scope user brain {url}/mcp --header "Authorization: Bearer {token}"')
        print(json.dumps({"mcpServers": {"brain": {"type": "http", "url": f"{url}/mcp",
                                                "headers": {"Authorization": f"Bearer {token}"}}}}, indent=2))
        print()
    if "opencode" in which:
        print("# opencode - add to ~/.config/opencode/opencode.json (or the project's opencode.json):")
        print(json.dumps({"mcp": {"brain": {"type": "remote", "url": f"{url}/mcp", "enabled": True, "oauth": False,
                                         "headers": {"Authorization": f"Bearer {token}"}}}}, indent=2))
        print()
    if "pi" in which or "claude" in which or "opencode" in which:
        print("# Any agent (pi, scripts, CI) - plain REST; add integrations/AGENTS.brain.md to your AGENTS.md:")
        print(f'curl -s -H "Authorization: Bearer {token}" -H "Content-Type: application/json" '
              f'-d \'{{"query":"where is VAT applied"}}\' {url}/api/search')


def cmd_doctor(_):
    from brain import llm
    from brain.providers import codebase_memory
    ok = True

    def row(name, good, info=""):
        nonlocal ok
        ok &= good is not False
        print(f"{'PASS' if good else ('WARN' if good is None else 'FAIL')}  {name:<34} {info}")
    row("python 3.13", sys.version_info[:2] == cfg.PYTHON, sys.version.split()[0])
    row("config file", cfg.config_file().exists(), str(cfg.config_file()))
    for k in ("BRAIN_LLM_BASE_URL", "BRAIN_LLM_API_KEY", "BRAIN_LLM_MODEL", "BRAIN_EMBEDDING_MODEL"):
        row(k, bool(cfg.get(k)))
    local = cfg.get("BRAIN_HOST") in ("127.0.0.1", "localhost", "::1")
    row("BRAIN_UI_PASSWORD", bool(cfg.get("BRAIN_UI_PASSWORD")) or (None if local else False),
        "required: the server refuses to listen on BRAIN_HOST=" + cfg.get("BRAIN_HOST") + " without it")
    row("BRAIN_API_TOKEN", bool(cfg.get("BRAIN_API_TOKEN")) or None, "agents use it for REST/MCP")
    if cfg.get("BRAIN_LLM_BASE_URL"):
        res = llm.check()
        row("corporate chat endpoint", res["chat"], cfg.get("BRAIN_LLM_MODEL"))
        row("corporate embedding endpoint", res["embedding"], f"dim={res['dim']} (BRAIN_EMBEDDING_DIM={cfg.get('BRAIN_EMBEDDING_DIM')})")
        for e in res["errors"]:
            print("      " + e[:300])
    row("code engine binary", codebase_memory.binary().exists(), str(codebase_memory.binary()))
    if codebase_memory.binary().exists():
        r = subprocess.run([str(codebase_memory.binary()), "--version"], capture_output=True, text=True)
        row("code engine runs", r.returncode == 0, (r.stdout or r.stderr).strip()[:120]
            + ("" if r.returncode == 0 else "  (antivirus quarantine? see docs/13-OPERATIONS.md)"))
    import sqlite3
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        row("sqlite full-text search (FTS5)", True, sqlite3.sqlite_version)
    except sqlite3.Error as exc:
        row("sqlite full-text search (FTS5)", False, f"{exc}: the document engine needs it")
    for mod in ("fastapi", "uvicorn", "httpx", "multipart", "numpy", "pdfplumber", "pypdfium2", "docx", "pptx", "openpyxl", "PIL"):
        try:
            __import__(mod)
            row(f"python package {mod}", True)
        except ImportError:
            row(f"python package {mod}", False, "re-run setup")
    from brain import ocr, vcache
    row("OCR fallback (optional)", ocr.available() or None,
        "RapidOCR installed" if ocr.available() else
        ("BRAIN_OCR=off" if cfg.get("BRAIN_OCR") == "off" else "not installed: ship wheels/ocr and re-run setup"))
    if cfg.get("BRAIN_VECTOR_CACHE"):
        st = vcache.stats()
        row("embedding cache", True, f"{st['vectors']} vectors, {st['mb']} MB in data/vectors.db")
    row("git", bool(_git(ROOT, "--version") or subprocess.run(["git", "--version"], capture_output=True).returncode == 0))
    try:
        repos = cfg.load_repos()
        row("repos.json", bool(repos) or None, f"{len(repos)} repositories" if repos else "no repositories configured yet")
        for r in repos:
            if r["path"]:
                row(f"  repo {r['name']}", Path(r["path"]).is_dir(), r["path"])
            else:
                try:
                    row(f"  repo {r['name']}", None, f"cloned from {cfg.resolve_url(r['url']).split('@')[-1]} on first sync")
                except ValueError as exc:
                    row(f"  repo {r['name']}", False, str(exc))
    except Exception as exc:
        row("repos.json", False, str(exc))
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(prog="brain", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("serve").set_defaults(f=cmd_serve)
    sub.add_parser("doctor").set_defaults(f=cmd_doctor)
    sub.add_parser("version").set_defaults(f=lambda _: print(VERSION))
    p = sub.add_parser("sync")
    p.add_argument("repo", nargs="?")
    p.set_defaults(f=cmd_sync)
    for name, arg, fn in (("search", "query", cmd_search), ("ask", "question", cmd_ask), ("enhance", "prompt", cmd_enhance)):
        p = sub.add_parser(name)
        p.add_argument(arg, nargs="+")
        p.add_argument("--set")
        p.add_argument("--branch")
        if name == "search":
            p.add_argument("--scope", default="all", choices=["all", "code", "semantic", "docs"])
            p.add_argument("--detail", choices=["brief", "normal", "full"])
        if name == "enhance":
            p.add_argument("--path", help="your checkout: adds branch-drift notes")
            p.add_argument("--repo")
        p.set_defaults(f=fn)
    p = sub.add_parser("guide")
    p.add_argument("topic", nargs="*")
    p.add_argument("--set")
    p.add_argument("--repo")
    p.set_defaults(f=cmd_guide)
    p = sub.add_parser("drift")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--repo")
    p.add_argument("--main", help="the main branch you branched from (default: the nearest one)")
    p.set_defaults(f=cmd_drift)
    p = sub.add_parser("impact")
    p.add_argument("files", nargs="*")
    p.add_argument("--repo")
    p.add_argument("--path", default=".")
    p.add_argument("--main", help="the main branch you branched from (default: the nearest one)")
    p.set_defaults(f=cmd_impact)
    p = sub.add_parser("hook")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--repo")
    p.add_argument("--remove", action="store_true")
    p.set_defaults(f=cmd_hook)
    p = sub.add_parser("connect")
    p.add_argument("agent", nargs="?", default="all", choices=["claude", "opencode", "pi", "all"])
    p.set_defaults(f=cmd_connect)
    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        return
    a.f(a)


if __name__ == "__main__":
    main()
