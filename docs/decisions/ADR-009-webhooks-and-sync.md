# ADR-009 - Webhook-driven, debounced updates of server-managed clones

**Status:** accepted · **Requirements:** R20, R19

## Decision
- A repository with a git `url` is cloned by the server into `data/repos/<name>` and owned by it: an update is
  `fetch` + `checkout -B <branch> origin/<branch>` + `reset --hard origin/<branch>`, so the clone always equals the
  remote branch. A repository given as a local `path` is only fast-forwarded when it is clean and on its tracked
  branch.
- GitLab and TFS / Azure DevOps webhooks start an update when something is merged into (or pushed to) the tracked
  branch; events for other branches are ignored; `BRAIN_WEBHOOK_EVENTS` selects merge and/or push events. Each
  repository has its own webhook (ADR-018); group-level hooks match repositories by URL, path, name or alias.
- Requests for one repository within `BRAIN_WEBHOOK_DEBOUNCE_SECONDS` become one job (a merge fires a merge and a push
  event). The code engine re-indexes by content hash; the multilingual code vectors are updated for changed
  symbols only.
- Other triggers: server start, a periodic interval (`BRAIN_SYNC_INTERVAL_MINUTES`), the UI buttons, the CLI and MCP.
- The corporate GitLab and TFS addresses are settings (`BRAIN_GITLAB_URL`, `BRAIN_TFS_URL`) with their own read
  tokens. Repositories refer to them as `gitlab:group/project` and `tfs:Project/repo`, expanded at use time, so
  moving a server is one setting change. Credentials are chosen by URL prefix, with `BRAIN_GIT_USER` /
  `BRAIN_GIT_TOKEN` as the fallback and a per-repository token taking precedence.
- The indexed commit of each repository is stored in `data/state.json`; the drift check uses it.

## Alternatives
Git hooks on developer machines: every developer would have to install them, and their machines would need to reach
the server. Polling only: slower and wasteful; kept as an optional fallback.

## Consequences
The graph reflects `main` seconds after a merge, with no developer action. Unknown repositories answer 404, so a
misconfigured hook is visible in the git server's delivery log and in the UI.
