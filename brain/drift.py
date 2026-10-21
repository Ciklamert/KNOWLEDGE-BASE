"""Branch drift: the code graph follows `main`, but a developer works on a feature branch.

Two things can be out of date:
  * the developer's branch is BEHIND main (main moved on since the branch was cut) -> merge/rebase risk;
  * the knowledge base describes main, so for every file the developer changed, AI-BRAIN answers show main's
    version, not the branch's.
check() compares the developer's branch with the indexed main and ALWAYS returns concrete recommendations,
including what to do when the system itself cannot fix the situation. No LLM call is involved.

Information sources, best first:
  1. the branch is pushed: the server fetches it and computes everything itself;
  2. not pushed: the caller (CLI `brain drift`, or an AI agent running git locally) passes base_commit
     (= `git merge-base HEAD origin/main`) and changed_files (= `git diff --name-only origin/main...HEAD`
     plus uncommitted files).
"""
from __future__ import annotations

from . import repos


def _files(root, a: str, b: str) -> list[str]:
    out = repos.git(root, "diff", "--name-only", f"{a}..{b}", timeout=120)
    return [x for x in out.splitlines() if x.strip()]


def check(repo_name: str, branch: str | None = None, base_commit: str | None = None,
          changed_files: list[str] | None = None, head_commit: str | None = None, base: str | None = None) -> dict:
    """`base` = the main branch the branch derives from; when empty: the branch itself if it is a main branch, the
    main recorded in its overlay, or the nearest main (repos.base_of) for a pushed branch."""
    r = repos.repo(repo_name)
    root = repos.checkout(r)
    st = repos.state()
    url = repos.remote(r) if r["url"] else ""
    all_mains = repos.mains(r)
    overlay = st["branches"].get(f"{r['name']}@{branch}") if branch else None
    main = base if base in all_mains else branch if branch in all_mains else (overlay or {}).get("base") or ""
    if not main and branch and len(all_mains) > 1:
        try:
            main = repos.base_of(r, branch, root, url or repos.git(root, "remote", "get-url", "origin", timeout=30))
        except RuntimeError:
            pass
    main = main or r["branch"]
    indexed = (st["repos"].get(r["name"], {}) if main == r["branch"] else
               st["branches"].get(f"{r['name']}@{main}", {})).get("commit")
    rep: dict = {"repo": r["name"], "tracked_branch": main, "mains": all_mains, "branch": branch, "indexed_commit": indexed,
                 "facts": [], "risk_files": [], "branch_files": [], "main_files": [], "recommendations": []}
    rec, facts = rep["recommendations"], rep["facts"]
    try:
        url = url or repos.git(root, "remote", "get-url", "origin", timeout=30)
        repos.git(root, "fetch", "origin", f"+refs/heads/{main}:refs/remotes/origin/{main}", url=url, repo=r)
        main_head = repos.head(root, f"origin/{main}")
    except RuntimeError as exc:
        main_head = indexed
        facts.append(f"could not fetch {main} from the remote ({exc}); using the indexed commit")
    rep["main_head"] = main_head

    # 1) is the knowledge base itself behind main?
    if indexed and main_head and indexed != main_head:
        try:
            n = int(repos.git(root, "rev-list", "--count", f"{indexed}..{main_head}", timeout=60))
        except RuntimeError:
            n = -1
        facts.append(f"the knowledge base indexed {main} at {indexed[:10]}, {main} is now at {main_head[:10]}"
                     + (f" ({n} commits newer)" if n > 0 else ""))
        rec.append({"action": "sync_brain", "why": f"the knowledge base is behind {main}",
                    "how": f"POST /api/repos/{r['name']}/sync (or the Update button / MCP tool `sync_repo`), which also "
                           "updates the other main branches. Webhooks normally do this within seconds; if this "
                           "repeats, check the webhook."})

    # 2) where did the branch start, and what changed on each side?
    branch_head = head_commit
    if branch and branch != main:
        try:
            repos.git(root, "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", url=url, repo=r)
            remote_head = repos.head(root, f"origin/{branch}")
            branch_head = branch_head or remote_head
            if head_commit and head_commit != remote_head:
                facts.append(f"your local {branch} ({head_commit[:10]}) differs from origin/{branch} "
                             f"({remote_head[:10]}): unpushed or unpulled commits")
            base_commit = base_commit or repos.git(root, "merge-base", f"origin/{main}", f"origin/{branch}", timeout=60)
            changed_files = sorted(set(changed_files or []) | set(_files(root, base_commit, remote_head)))
        except RuntimeError:
            facts.append(f"branch {branch} is not on the remote (not pushed yet); using what the caller sent")
    if not base_commit and head_commit and (not branch or branch == main):
        base_commit = head_commit   # on the tracked branch itself: compare your HEAD with the remote main
    if not base_commit:
        rec.append({"action": "send_git_facts",
                    "why": "without the branch's merge-base the server cannot measure drift",
                    "how": "push the branch, or pass base_commit = `git merge-base HEAD origin/main` and "
                           "changed_files = `git diff --name-only origin/main...HEAD` (+ `git status --porcelain`). "
                           "`brain drift` in your checkout does this for you."})
        return rep
    rep["base_commit"] = base_commit
    try:
        behind = int(repos.git(root, "rev-list", "--count", f"{base_commit}..{main_head}", timeout=60))
        rep["main_files"] = _files(root, base_commit, main_head)
    except RuntimeError:
        behind = -1
        facts.append(f"base commit {base_commit[:10]} is unknown on the server (fetch your main, or rebase first)")
    rep["behind"] = behind
    rep["branch_files"] = sorted(set(changed_files or []))
    risk = sorted(set(rep["branch_files"]) & set(rep["main_files"]))
    rep["risk_files"] = risk

    # 3) recommendations: always concrete, ordered by what to do first
    if behind > 0:
        facts.append(f"your branch is {behind} commit(s) behind {main}; {len(rep['main_files'])} file(s) changed on {main} "
                     f"since you branched, {len(risk)} of them also changed by you")
        if risk:
            rec.append({"action": "rebase_now", "why": f"{len(risk)} file(s) changed on both sides: likely conflicts",
                        "files": risk[:50],
                        "how": f"git fetch origin && git rebase origin/{main}  (or: git merge origin/{main}). "
                               "Resolve these files first; re-run your tests. Rebasing early keeps conflicts small."})
        else:
            rec.append({"action": "rebase_safe", "why": f"no overlapping files: rebasing onto {main} should be clean",
                        "how": f"git fetch origin && git rebase origin/{main}"})
    elif behind == 0:
        facts.append(f"your branch contains the latest {main}: no merge drift")
    if rep["branch_files"]:
        rec.append({"action": "trust_local_files",
                    "why": "the knowledge base shows main's version of the files you changed",
                    "files": rep["branch_files"][:50],
                    "how": "for these files read your working copy instead of AI-BRAIN snippets; use AI-BRAIN for everything "
                           "else (callers, docs, other modules)."})
        try:
            from . import providers
            imp = providers.code().impact(r["name"], rep["branch_files"])
            rep["tests_to_run"] = [f"{t['path']}::{t['symbol'].rsplit('.', 1)[-1]}" for t in imp["tests"]]
            if imp["tests"]:
                rec.append({"action": "run_tests", "why": f"{len(imp['tests'])} test(s) cover code you changed or its "
                            f"callers", "files": imp["test_files"][:50],
                            "how": "run these tests before pushing; `impact` (MCP) or POST /api/impact lists the "
                                   "callers and routes as well."})
        except Exception:
            pass   # an older index or another code engine: the rest of the check still stands
        if len(rep["branch_files"]) >= 10 and branch and branch != main:
            rec.append({"action": "index_branch",
                        "why": "many files differ from main: a branch overlay makes search and agents see your code",
                        "how": f"push the branch, then POST /api/repos/{r['name']}/branches {{\"branch\": \"{branch}\"}} "
                               "(or 'Index a branch…' on the Repositories page). Search/ask/enhance with branch="
                               f"{branch} then use it. Remove it after merging."})
    if overlay and branch_head and overlay.get("commit") != branch_head:
        rec.append({"action": "refresh_overlay", "why": "the branch overlay is older than your branch head",
                    "how": f"re-run POST /api/repos/{r['name']}/branches {{\"branch\": \"{branch}\"}}"})
    if not rec:
        rec.append({"action": "none", "why": "branch and knowledge base are in step", "how": "nothing to do"})
    return rep


def render(rep: dict) -> str:
    lines = [f"### Branch check: {rep['repo']} ({rep.get('branch') or 'unknown branch'} vs {rep['tracked_branch']})"]
    lines += [f"- {f}" for f in rep["facts"]]
    lines.append("**Recommendations**")
    for i, r in enumerate(rep["recommendations"], 1):
        lines.append(f"{i}. **{r['action']}**: {r['why']}. {r['how']}")
        if r.get("files"):
            lines.append("   files: " + ", ".join(f"`{f}`" for f in r["files"][:20]))
    return "\n".join(lines)
