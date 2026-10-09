"""AI-BRAIN - one command for everything (run through brain.cmd on Windows, ./brain.sh on Linux).

  brain serve                       start UI + REST API + MCP + webhooks; starts both graph engines and agents
  brain doctor                      check Python, settings, corporate API, engines, repositories
  brain sync [REPO]                 update + re-index one repository (or all) on the running server
  brain search "text" [--scope all|code|semantic|docs] [--set S]   search (no LLM)
  brain ask "question" [--set S]    ask the AI-BRAIN ask agent (grounded answer with sources)
  brain enhance "prompt" [--set S]  print an implementation-ready prompt for an AI coding agent
  brain drift [PATH] [--repo R]     compare your branch in PATH (default: .) with the indexed main
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
    r = api("POST", "/api/search", {"query": " ".join(a.query), "scope": a.scope, "set": a.set, "branch": a.branch})
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


def local_git_facts(path: Path, main: str = "main") -> dict:
    """What the server needs to judge drift, computed in the developer's own checkout."""
    _git(path, "fetch", "--quiet", "origin", main)
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    base = _git(path, "merge-base", "HEAD", f"origin/{main}")
    changed = set(_git(path, "diff", "--name-only", f"origin/{main}...HEAD").splitlines())
    changed |= {ln[3:].split(" -> ")[-1] for ln in _git(path, "status", "--porcelain").splitlines() if len(ln) > 3}
    url = _git(path, "remote", "get-url", "origin")
    return {"branch": branch, "base_commit": base or None, "head_commit": _git(path, "rev-parse", "HEAD"),
            "changed_files": sorted(x for x in changed if x), "remote": url}


def _guess_repo(remote: str, path: Path) -> str:
    repos = api("GET", "/api/repos")["repos"]
    tail = remote.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1].lower() if remote else path.name.lower()
    for r in repos:
        url = (r.get("remote") or r["url"] or "").rstrip("/").removesuffix(".git").lower()
        if r["name"].lower() == tail or (url and url.endswith("/" + tail)):
            return r["name"]
    sys.exit(f"cannot tell which configured repository {path} is; pass --repo NAME")


def cmd_enhance(a):
    body = {"prompt": " ".join(a.prompt), "set": a.set, "branch": a.branch}
    if a.path:
        facts = local_git_facts(Path(a.path).resolve())
        body.update(repo=a.repo or _guess_repo(facts["remote"], Path(a.path).resolve()), branch=facts["branch"],
                    base_commit=facts["base_commit"], changed_files=facts["changed_files"])
    r = api("POST", "/api/enhance", body)
    print(r["enhanced"])
    print(f"\n-- {r['ms']} ms, llm: {r['llm']}, tools: {[s['tool'] for s in r['steps']]}, notes: {r['errors']}",
          file=sys.stderr)


def cmd_drift(a):
    path = Path(a.path).resolve()
    facts = local_git_facts(path, a.main)
    if not facts["branch"]:
        sys.exit(f"{path} is not a git checkout")
    repo = a.repo or _guess_repo(facts["remote"], path)
    r = api("POST", "/api/drift", {"repo": repo, **{k: facts[k] for k in ("branch", "base_commit", "head_commit",
                                                                          "changed_files")}})
    print(r["markdown"])


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
    from brain.providers import codebase_memory, lightrag
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
    row("lightrag-server installed", bool(lightrag.server_exe()), lightrag.server_exe() or "re-run setup")
    for mod in ("fastapi", "uvicorn", "httpx", "pdfplumber", "pypdfium2", "pptx", "openpyxl"):
        try:
            __import__(mod)
            row(f"python package {mod}", True)
        except ImportError:
            row(f"python package {mod}", False, "re-run setup")
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
        if name == "enhance":
            p.add_argument("--path", help="your checkout: adds branch-drift notes")
            p.add_argument("--repo")
        p.set_defaults(f=fn)
    p = sub.add_parser("drift")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--repo")
    p.add_argument("--main", default="main")
    p.set_defaults(f=cmd_drift)
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
