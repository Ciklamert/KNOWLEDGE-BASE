"""GitLab and TFS / Azure DevOps Server webhooks: a merge into a repository's tracked branch (main) updates
that repository's code graph at once (pull + incremental index); an event that arrives while the repository is
being updated makes that update run once more.

Every repository has its OWN webhook: POST /webhooks/repo/<name> with its own secret (repos.json
"webhook_secret", generated when the repository is saved; shown on the Repositories page). GitLab or TFS is
recognised from the request. The group-level endpoints below remain for one hook covering many repositories:

GitLab   POST /webhooks/gitlab   header X-Gitlab-Token == BRAIN_GITLAB_WEBHOOK_SECRET
         events: "Merge Request Hook" (action=merge, target_branch=<tracked>), "Push Hook" (ref=refs/heads/<tracked>)
TFS/ADO  POST /webhooks/tfs      Basic auth == BRAIN_TFS_WEBHOOK_USER / BRAIN_TFS_WEBHOOK_PASSWORD
         events: git.pullrequest.merged / git.pullrequest.updated (status=completed, targetRefName=refs/heads/<tracked>),
                 git.push (refUpdates[].name = refs/heads/<tracked>)
"""
from __future__ import annotations

import base64
import hmac
import re
import time
from collections import deque

from . import jobs, repos
from . import settings as cfg

LOG: deque = deque(maxlen=50)   # recent deliveries, shown in the UI


def _norm(url: str) -> str:
    """https://user:pw@host/group/proj.git, git@host:group/proj.git -> host/group/proj"""
    u = (url or "").strip().lower()
    u = re.sub(r"^[a-z+]+://", "", u)
    u = re.sub(r"^[^@/]+@", "", u)
    u = u.replace(":", "/").rstrip("/")
    u = re.sub(r"\.git$", "", u)
    u = u.replace("/_git/", "/")          # TFS: host/collection/project/_git/repo
    return u


def _remote(r: dict) -> str:
    try:
        return repos.remote(r)
    except ValueError:   # shorthand without its base URL configured
        return ""


def match_repo(candidates: list[str]) -> dict | None:
    """Find the configured repository for the URLs / names a webhook carries."""
    cands = [c for c in candidates if c]
    keys = {_norm(c) for c in cands} | {c.lower() for c in cands}
    for r in repos.all_repos():
        mine = {r["name"].lower(), *(a.lower() for a in r["aliases"])}
        url = _remote(r)
        if url:
            mine.add(_norm(url))
        if keys & mine:
            return r
    # tolerate different hosts (ssh vs http alias, IP vs DNS): compare the path tail
    tails = {"/".join(k.split("/")[-2:]) for k in keys if "/" in k}
    for r in repos.all_repos():
        if _remote(r) and "/".join(_norm(_remote(r)).split("/")[-2:]) in tails:
            return r
    return None


def _events() -> set[str]:
    return {e.strip() for e in cfg.get("BRAIN_WEBHOOK_EVENTS").split(",") if e.strip()}


def _result(source: str, status: int, body: dict) -> tuple[int, dict]:
    LOG.appendleft({"time": time.time(), "source": source, "status": status, **body})
    jobs.tick()
    return status, body


def _accept(source: str, r: dict, event: str, ref: str) -> tuple[int, dict]:
    if ref.removeprefix("refs/heads/") != r["branch"]:
        return _result(source, 200, {"ignored": f"{event} on {ref}, tracked branch is {r['branch']}", "repo": r["name"]})
    job = repos.request_sync(r["name"], reason=f"webhook {source} {event}")
    return _result(source, 202, {"accepted": True, "repo": r["name"], "event": event,
                                 "job": job.id if job else None, "queued": job is None})


def _gitlab_event(r: dict, headers: dict, payload: dict, source: str) -> tuple[int, dict]:
    kind = payload.get("object_kind") or headers.get("x-gitlab-event", "")
    if kind in ("merge_request", "Merge Request Hook"):
        a = payload.get("object_attributes") or {}
        if "merge" not in _events():
            return _result(source, 200, {"ignored": "merge events disabled (BRAIN_WEBHOOK_EVENTS)", "repo": r["name"]})
        if a.get("action") != "merge" and a.get("state") != "merged":
            return _result(source, 200, {"ignored": f"merge request {a.get('action') or a.get('state')}", "repo": r["name"]})
        return _accept(source, r, "merge", a.get("target_branch", ""))
    if kind in ("push", "Push Hook"):
        if "push" not in _events():
            return _result(source, 200, {"ignored": "push events disabled (BRAIN_WEBHOOK_EVENTS)", "repo": r["name"]})
        return _accept(source, r, "push", payload.get("ref", ""))
    return _result(source, 200, {"ignored": f"event {kind}", "repo": r["name"]})


def _tfs_event(r: dict, payload: dict, source: str) -> tuple[int, dict]:
    event = payload.get("eventType", "")
    res = payload.get("resource") or {}
    if event.startswith("git.pullrequest"):
        if "merge" not in _events():
            return _result(source, 200, {"ignored": "merge events disabled (BRAIN_WEBHOOK_EVENTS)", "repo": r["name"]})
        if res.get("status") != "completed" or res.get("mergeStatus") not in (None, "succeeded"):
            return _result(source, 200, {"ignored": f"pull request {res.get('status')}", "repo": r["name"]})
        return _accept(source, r, "merge", res.get("targetRefName", ""))
    if event == "git.push":
        if "push" not in _events():
            return _result(source, 200, {"ignored": "push events disabled (BRAIN_WEBHOOK_EVENTS)", "repo": r["name"]})
        refs = [u.get("name", "") for u in res.get("refUpdates") or []]
        tracked = f"refs/heads/{r['branch']}"
        return _accept(source, r, "push", tracked if tracked in refs else (refs[0] if refs else ""))
    return _result(source, 200, {"ignored": f"event {event}", "repo": r["name"]})


def _basic(headers: dict) -> tuple[str, str]:
    auth = headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        return "", ""
    try:
        u, _, p = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
    except ValueError:
        return "", ""
    return u, p


def repo_hook(name: str, headers: dict, payload: dict) -> tuple[int, dict]:
    """The repository's own webhook, /webhooks/repo/<name>: GitLab or TFS, recognised from the request.
    Secret: GitLab sends it as X-Gitlab-Token, TFS as the basic-auth password (any user name)."""
    source = f"repo:{name}"
    try:
        r = repos.repo(name)
    except KeyError:
        return _result(source, 404, {"error": f"unknown repository {name}"})
    secret = r["webhook_secret"]
    if not secret:
        return _result(source, 503, {"error": "this repository has no webhook secret yet: save it on the Repositories page"})
    if "x-gitlab-token" in headers or "x-gitlab-event" in headers or "object_kind" in payload:
        if not hmac.compare_digest(headers.get("x-gitlab-token", ""), secret):
            return _result(source, 401, {"error": "invalid X-Gitlab-Token", "repo": name})
        return _gitlab_event(r, headers, payload, source)
    if "eventType" in payload:
        if not hmac.compare_digest(_basic(headers)[1], secret):
            return _result(source, 401, {"error": "invalid basic-auth password", "repo": name})
        return _tfs_event(r, payload, source)
    return _result(source, 400, {"error": "not a GitLab or TFS webhook payload", "repo": name})


def gitlab(headers: dict, payload: dict) -> tuple[int, dict]:
    """Group-level GitLab webhook: one hook for many projects, matched to repositories by URL / path."""
    secret = cfg.get("BRAIN_GITLAB_WEBHOOK_SECRET")
    if not secret:
        return _result("gitlab", 503, {"error": "BRAIN_GITLAB_WEBHOOK_SECRET is not configured"})
    if not hmac.compare_digest(headers.get("x-gitlab-token", ""), secret):
        return _result("gitlab", 401, {"error": "invalid X-Gitlab-Token"})
    p = payload.get("project") or {}
    rep = payload.get("repository") or {}
    r = match_repo([p.get("git_http_url"), p.get("git_ssh_url"), p.get("web_url"), p.get("path_with_namespace"),
                    p.get("name"), rep.get("git_http_url"), rep.get("url"), rep.get("homepage"), rep.get("name")])
    if r is None:
        return _result("gitlab", 404, {"error": "repository not configured in repos.json",
                                       "project": p.get("path_with_namespace") or p.get("name")})
    return _gitlab_event(r, headers, payload, "gitlab")


def tfs(headers: dict, payload: dict) -> tuple[int, dict]:
    """Group-level TFS / Azure DevOps service hook, matched to repositories by remote URL / name."""
    if not cfg.get("BRAIN_TFS_WEBHOOK_PASSWORD"):
        return _result("tfs", 503, {"error": "BRAIN_TFS_WEBHOOK_USER / BRAIN_TFS_WEBHOOK_PASSWORD are not configured"})
    u, pw = _basic(headers)
    if not (hmac.compare_digest(u, cfg.get("BRAIN_TFS_WEBHOOK_USER")) and hmac.compare_digest(pw, cfg.get("BRAIN_TFS_WEBHOOK_PASSWORD"))):
        return _result("tfs", 401, {"error": "invalid basic-auth credentials"})
    rep = (payload.get("resource") or {}).get("repository") or {}
    r = match_repo([rep.get("remoteUrl"), rep.get("url"), rep.get("name"), (rep.get("project") or {}).get("name")
                    and f"{(rep.get('project') or {}).get('name')}/{rep.get('name')}"])
    if r is None:
        return _result("tfs", 404, {"error": "repository not configured in repos.json", "repository": rep.get("name")})
    return _tfs_event(r, payload, "tfs")
