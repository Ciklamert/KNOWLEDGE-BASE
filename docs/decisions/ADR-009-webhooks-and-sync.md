# ADR-009 - Updates on every merge and every pull of the tracked branch

**Status:** accepted · **Requirements:** R20, R19

## Decision
- A repository with a git `url` is cloned by the server into `data/repos/<name>` and owned by it: an update is
  `fetch` + `checkout -B <branch> origin/<branch>` + `reset --hard origin/<branch>`, so the clone always equals the
  remote branch. A repository given as a local `path` is only fast-forwarded when it is clean and on its tracked
  branch.
- GitLab and TFS / Azure DevOps webhooks start an update when something is merged into (or pushed to) the tracked
  branch; events for other branches are ignored; `BRAIN_WEBHOOK_EVENTS` selects merge and/or push events. Each
  repository has its own webhook (ADR-018); group-level hooks match repositories by URL, path, name or alias.
- Every pull of the tracked branch updates AI-BRAIN too: local-path checkouts are watched (the branch head is
  compared with the indexed commit every `BRAIN_WATCH_LOCAL_SECONDS`), and `brain hook` installs git hooks
  (`post-merge`, `post-rewrite`) in any checkout that ask the server to update after a `git pull` of that branch.
- An update starts at once and pulls immediately. A request that arrives while the same repository is being updated
  makes that update run once more when it finishes, so nothing is missed and nothing runs twice in parallel. The
  code engine re-indexes by content hash; the multilingual code vectors are updated for changed symbols only.
- Other triggers: server start, an update of every repository at least every 24 hours (ADR-027), the UI buttons, the
  CLI and MCP.
- The corporate GitLab and TFS addresses are settings (`BRAIN_GITLAB_URL`, `BRAIN_TFS_URL`) with their own read
  tokens. Repositories refer to them as `gitlab:group/project` and `tfs:Project/repo`, expanded at use time, so
  moving a server is one setting change. Credentials are chosen by URL prefix, with `BRAIN_GIT_USER` /
  `BRAIN_GIT_TOKEN` as the fallback and a per-repository token taking precedence.
- The indexed commit of each repository is stored in `data/state.json`; the drift check uses it.

## Alternatives
Git hooks on developer machines as the only trigger: every developer would have to install them; they are offered
as an addition (`brain hook`), not a requirement. A fixed waiting window to merge events: it delays every update and
can still miss a commit written after the window; the run-once-more rule has neither problem. Polling the remote
only: slower and wasteful; kept as an optional fallback.

## Consequences
The graph reflects `main` seconds after a merge or a pull, with no developer action. Unknown repositories answer 404, so a
misconfigured hook is visible in the git server's delivery log and in the UI.
