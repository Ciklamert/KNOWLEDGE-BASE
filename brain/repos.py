"""Repositories, repository sets, git operations and code-graph synchronisation.

A repository (repos.json) is either
  * server-managed: it has a git `url`; the server clones it into data/repos/<name>, follows its tracked
    branch (default `main`) with `fetch` + `reset --hard`, and nobody edits that clone; or
  * local: it has a `path` to an existing checkout; the server only fast-forwards it when it is clean and on
    the tracked branch, and otherwise indexes it as it is.
Repositories belong to any number of named sets; every search/ask/enhance can be limited to one set.
The code-graph project of a repository is named after the repository. Branch overlays (see drift.py) are
extra projects named <repo>--<branch> built from a git worktree of that branch.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import codevec, jobs, providers
from . import settings as cfg

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_state_lock = threading.Lock()
_sync_lock = threading.Lock()
_pending: dict[str, float] = {}        # repo name -> time an update was requested (debounce)


# ---------------------------------------------------------------- state (what is indexed at which commit)
def _state_file() -> Path:
    return cfg.data_dir() / "state.json"


def state() -> dict:
    with _state_lock:
        f = _state_file()
        data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        data.setdefault("repos", {})
        data.setdefault("branches", {})
        return data


def _save_state(mutate) -> None:
    with _state_lock:
        f = _state_file()
        data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        data.setdefault("repos", {})
        data.setdefault("branches", {})
        mutate(data)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(f)


# ---------------------------------------------------------------- registry
def all_repos() -> list[dict]:
    return cfg.load_repos()


def repo(name: str) -> dict:
    for r in all_repos():
        if r["name"] == name or name in r["aliases"]:
            return r
    raise KeyError(f"unknown repository: {name}")


def managed(r: dict) -> bool:
    return bool(r["url"]) and not r["path"]


def remote(r: dict) -> str:
    """The repository's clone URL with gitlab:/tfs: shorthands expanded (see settings.resolve_url)."""
    return cfg.resolve_url(r["url"])


def checkout(r: dict) -> Path:
    return Path(r["path"]).expanduser().resolve() if r["path"] else cfg.path("repos") / r["name"]


def sets() -> dict[str, list[str]]:
    """Repository sets (repos.json "sets") plus the implicit set "all"."""
    return {"all": [r["name"] for r in all_repos()], **cfg.load_sets()}


def resolve_scope(set_name: str | None = None, repo_names: list[str] | None = None,
                  branch: str | None = None) -> list[str]:
    """Code-graph projects to search for a request. A branch overlay replaces its repository when present."""
    names = list(repo_names or []) or sets().get(set_name or "all")
    if names is None:
        raise KeyError(f"unknown repository set: {set_name} (known: {', '.join(sets())})")
    indexed = {p["name"] for p in providers.code().projects()}
    st = state()["branches"]
    out = []
    for n in names:
        overlay = st.get(f"{n}@{branch}") if branch else None
        if overlay and overlay.get("project") in indexed:
            out.append(overlay["project"])
        elif n in indexed:
            out.append(n)
    return out


# ---------------------------------------------------------------- git
def _auth_args(url: str, repo: dict | None = None) -> list[str]:
    args = []
    if not cfg.get("BRAIN_GIT_SSL_VERIFY"):
        args += ["-c", "http.sslVerify=false"]
    if cfg.get("BRAIN_GIT_CA_BUNDLE"):
        args += ["-c", f"http.sslCAInfo={cfg.get('BRAIN_GIT_CA_BUNDLE')}"]
    user, token = cfg.git_credentials(url, repo)
    if token and url.startswith("http"):
        cred = base64.b64encode(f"{user}:{token}".encode()).decode()
        args += ["-c", f"http.extraHeader=Authorization: Basic {cred}"]
    return args


def git(root: Path | None, *args: str, url: str = "", timeout: float | None = None, repo: dict | None = None) -> str:
    cmd = ["git", *_auth_args(url, repo)] + (["-C", str(root)] if root else []) + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout or cfg.get("BRAIN_GIT_TIMEOUT"), creationflags=NO_WINDOW,
                           env={**__import__("os").environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"git {' '.join(args[:2])} timed out after {timeout or cfg.get('BRAIN_GIT_TIMEOUT')}s") from None
    except FileNotFoundError:
        raise RuntimeError("git is not installed or not on PATH") from None
    if r.returncode != 0:
        msg = re.sub(r"Authorization: Basic \S+", "Authorization: ***", (r.stderr or r.stdout).strip())
        raise RuntimeError(f"git {' '.join(args[:2])}: {msg[-500:]}")
    return r.stdout.strip()


def head(root: Path, ref: str = "HEAD") -> str:
    return git(root, "rev-parse", ref, timeout=60)


def update_checkout(r: dict, log) -> Path:
    """Bring the checkout to the latest commit of the tracked branch."""
    root, branch = checkout(r), r["branch"]
    if managed(r):
        if not (root / ".git").exists():
            log(f"cloning {r['name']} ({branch})")
            if root.exists():
                shutil.rmtree(root)
            git(None, "clone", "--branch", branch, "--single-branch", "--no-tags", remote(r), str(root), url=remote(r), repo=r)
        else:
            log(f"fetching {r['name']} ({branch})")
            git(root, "remote", "set-url", "origin", remote(r), timeout=60)
            git(root, "fetch", "--prune", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", url=remote(r), repo=r)
            git(root, "checkout", "-B", branch, f"origin/{branch}", timeout=120)
            git(root, "reset", "--hard", f"origin/{branch}", timeout=120)
        return root
    if not root.is_dir():
        raise RuntimeError(f"{r['name']}: path not found: {root}")
    if (root / ".git").exists():
        try:
            current = git(root, "rev-parse", "--abbrev-ref", "HEAD", timeout=30)
            remotes = git(root, "remote", timeout=30)
            dirty = git(root, "status", "--porcelain", "--untracked-files=no", timeout=60)
            if remotes and current == branch and not dirty:
                log(f"fast-forwarding {r['name']} ({branch})")
                git(root, "pull", "--ff-only", "origin", branch, url=git(root, "remote", "get-url", "origin", timeout=30), repo=r)
            elif current != branch:
                log(f"{r['name']}: local checkout is on '{current}', not '{branch}'; indexing it as it is")
        except RuntimeError as exc:
            log(f"{r['name']}: git update skipped: {exc}")
    return root


# ---------------------------------------------------------------- sync (update + index)
def sync_repo(name: str, job: jobs.Job | None = None) -> dict:
    r = repo(name)
    log = (lambda m, p=None: job.log(m, p)) if job else (lambda m, p=None: None)
    t0 = time.time()
    try:
        root = update_checkout(r, log)
        commit = head(root) if (root / ".git").exists() else ""
        res = providers.code().index(r["name"], str(root), log)
        info = {"commit": commit, "indexed_at": time.time(), "seconds": round(time.time() - t0, 1),
                "project": res.get("project", r["name"]), "nodes": res.get("nodes"), "edges": res.get("edges"),
                "error": None}
        info["vectors"] = _vectors(info["project"], log)
    except Exception as exc:
        _save_state(lambda d: d["repos"].setdefault(name, {}).update(error=str(exc), failed_at=time.time()))
        raise
    _save_state(lambda d: d["repos"].__setitem__(name, info))
    return info


def _vectors(project: str, log) -> dict | None:
    """Corporate multilingual code vectors for a freshly indexed project. Never fails the sync."""
    if not codevec.enabled():
        return None
    try:
        return codevec.update(project, log)
    except Exception as exc:
        log(f"{project}: code vectors not updated: {exc}")
        return {"error": str(exc)}


def sync_all(job: jobs.Job, names: list[str] | None = None) -> dict:
    names = names or [r["name"] for r in all_repos()]
    out, errors = {}, {}
    with _sync_lock:
        for i, n in enumerate(names):
            job.log(f"[{i + 1}/{len(names)}] {n}", i / max(1, len(names)))
            try:
                out[n] = sync_repo(n, job)
            except Exception as exc:
                errors[n] = str(exc)
                job.log(f"{n} failed: {exc}")
    if errors and not out:
        raise RuntimeError("; ".join(f"{k}: {v}" for k, v in errors.items()))
    return {"synced": out, "errors": errors}


def request_sync(name: str | None = None, reason: str = "manual") -> jobs.Job | None:
    """Queue an update+index in the background. Requests for the same repo within the debounce window are
    merged into one job (a merge on GitLab typically fires both a merge and a push webhook)."""
    names = [name] if name else [r["name"] for r in all_repos()]
    now = time.time()
    window = cfg.get("BRAIN_WEBHOOK_DEBOUNCE_SECONDS")
    fresh = [n for n in names if now - _pending.get(n, 0) > window]
    if not fresh:
        return None
    for n in fresh:
        _pending[n] = now

    def work(job):
        if reason.startswith("webhook"):
            time.sleep(min(window, 5))   # let the git server finish writing the merge commit
        return sync_all(job, fresh)
    return jobs.start("sync", f"Update code graph: {', '.join(fresh)} ({reason})", work)


# ---------------------------------------------------------------- branch overlays
def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-") or "branch"


def index_branch(name: str, branch: str, job: jobs.Job) -> dict:
    """Index a branch as an extra project (<repo>--<branch>) from a git worktree, so work on a branch can be
    searched with that branch's code instead of main's."""
    r = repo(name)
    root = update_checkout(r, job.log) if managed(r) else checkout(r)
    url = remote(r) or git(root, "remote", "get-url", "origin", timeout=30)
    job.log(f"fetching branch {branch}")
    git(root, "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", url=url, repo=r)
    wt = cfg.path("worktrees") / f"{r['name']}--{slug(branch)}"
    if wt.exists():
        git(root, "worktree", "remove", "--force", str(wt), timeout=120)
    git(root, "worktree", "prune", timeout=60)
    git(root, "worktree", "add", "--detach", "--force", str(wt), f"origin/{branch}", timeout=600)
    res = providers.code().index(f"{r['name']}--{slug(branch)}", str(wt), job.log)
    _vectors(res.get("project"), job.log)
    info = {"repo": r["name"], "branch": branch, "project": res.get("project"), "commit": head(wt),
            "path": str(wt), "indexed_at": time.time()}
    _save_state(lambda d: d["branches"].__setitem__(f"{r['name']}@{branch}", info))
    return info


def remove_branch(name: str, branch: str) -> None:
    key = f"{name}@{branch}"
    info = state()["branches"].get(key)
    if not info:
        raise KeyError(f"no branch overlay {key}")
    try:
        providers.code().remove(info["project"])
        codevec.remove(info["project"])
    finally:
        r = repo(name)
        try:
            git(checkout(r), "worktree", "remove", "--force", info["path"], timeout=120)
        except RuntimeError:
            shutil.rmtree(info["path"], ignore_errors=True)
        _save_state(lambda d: d["branches"].pop(key, None))


def webhook_info(r: dict, base: str) -> dict:
    """The repository's own webhook: URL, secret and where to enter them on GitLab / TFS."""
    url = f"{base}/webhooks/repo/{r['name']}"
    if r["provider"] == "tfs":
        how = ("TFS / Azure DevOps: Project settings > Service hooks > Web Hooks; triggers 'Pull request merge "
               f"attempted' (target branch {r['branch']}) and optionally 'Code pushed'; URL above; basic "
               "authentication: any user name, password = the secret.")
    else:
        how = ("GitLab: project > Settings > Webhooks; URL above; Secret token = the secret; triggers 'Merge request "
               f"events' and 'Push events' (branch filter {r['branch']}).")
    return {"url": url, "secret": r["webhook_secret"], "provider": r["provider"], "how": how}


def overview(base: str = "") -> list[dict]:
    st = state()
    indexed = {p["name"]: p for p in providers.code().projects()}
    member = {}
    for sname, names in cfg.load_sets().items():
        for n in names:
            member.setdefault(n, []).append(sname)
    out = []
    for r in all_repos():
        s = st["repos"].get(r["name"], {})
        try:
            resolved = remote(r)
        except ValueError as exc:
            resolved = f"(error: {exc})"
        out.append({**{k: v for k, v in r.items() if k != "token"}, "token_set": bool(r["token"]),
                    "remote": resolved, "managed": managed(r), "checkout": str(checkout(r)),
                    "sets": member.get(r["name"], []), "webhook": webhook_info(r, base),
                    "indexed": r["name"] in indexed, "nodes": indexed.get(r["name"], {}).get("nodes"),
                    "commit": s.get("commit"), "indexed_at": s.get("indexed_at"), "error": s.get("error"),
                    "vectors": s.get("vectors"),
                    "branches": [b for b in st["branches"].values() if b["repo"] == r["name"]]})
    return out
