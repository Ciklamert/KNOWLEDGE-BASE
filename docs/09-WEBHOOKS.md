# 09 - Webhooks: GitLab and TFS / Azure DevOps Server

Goal: when a merge request (GitLab) or pull request (TFS / Azure DevOps Server) is merged into a repository's
tracked branch (`main` by default), that repository's code graph is updated within seconds: fetch, incremental
index, code vectors of changed symbols.

## 1. Two kinds of webhook

| Kind | URL | Secret | Matches the repository by |
|---|---|---|---|
| **Per repository** (recommended) | `/webhooks/repo/<name>` | the repository's own `webhook_secret` (generated, shown on the Repositories page) | its name in the URL |
| Group-level GitLab | `/webhooks/gitlab` | `BRAIN_GITLAB_WEBHOOK_SECRET` | the clone URL, namespace path, name or `aliases` in the payload |
| Group-level TFS | `/webhooks/tfs` | `BRAIN_TFS_WEBHOOK_USER` / `BRAIN_TFS_WEBHOOK_PASSWORD` | the remote URL or name in the payload |

The per-repository webhook needs no URL matching, so mirrors, renamed projects and different host names cannot
break it. A group-level hook covers many repositories with one configuration. Both can be used at the same time.

## 2. How a delivery is handled
1. The git server POSTs the event.
2. The secret is checked with a constant-time comparison. Wrong or missing → 401. Not configured → 503.
3. The repository is found (per-repository: by name; group-level: by normalised clone URL, http or ssh, with or
   without credentials and `.git`, TFS `/_git/` paths, namespace path, name or alias, and finally by the last two
   path parts). Unknown → 404, which the git server shows in its delivery log.
4. Only events for the repository's `branch` count; anything else → 200 `{"ignored": "<reason>"}`.
5. `BRAIN_WEBHOOK_EVENTS` (default `merge,push`) selects which kinds trigger an update: `merge` = merged MR/PR,
   `push` = any push to the tracked branch.
6. An update starts at once → 202 with the job id. If the repository is already being updated, the answer says
   `"queued": true` and that update runs once more when it finishes (a merge usually fires a merge and a push event).
7. The job pulls immediately (fetch, reset the server-managed clone to the branch) and re-indexes
   ([04-REPOSITORIES-AND-SETS.md](04-REPOSITORIES-AND-SETS.md) §4). Progress is on **Overview** and
   **Repositories**; the last 50 deliveries are listed under **Repositories → Webhook deliveries**.

Events handled:
- GitLab: `object_kind: merge_request` with `action: merge` (or `state: merged`) and `target_branch` = tracked
  branch; `object_kind: push` with `ref` = `refs/heads/<tracked branch>`. The `X-Gitlab-Event` header is also
  understood.
- TFS: `git.pullrequest.merged` and `git.pullrequest.updated` with `resource.status = completed`,
  `mergeStatus = succeeded` and `targetRefName` = `refs/heads/<tracked branch>`; `git.push` with a `refUpdates`
  entry for the tracked branch.

For `/webhooks/repo/<name>` GitLab and TFS are recognised from the request: an `X-Gitlab-Token` or
`X-Gitlab-Event` header or an `object_kind` field means GitLab (secret = `X-Gitlab-Token`), an `eventType` field
means TFS (secret = basic-auth password, any user name). Anything else → 400.

## 3. GitLab, per repository
1. AI-BRAIN: **Repositories** → the repository's row → *Copy URL* and *Copy secret*.
2. GitLab → project → **Settings → Webhooks → Add new webhook**:
   - URL: the copied URL (`http(s)://<server>:8765/webhooks/repo/<name>`);
   - Secret token: the copied secret;
   - Trigger: **Merge request events** and **Push events** (branch filter: the tracked branch);
   - SSL verification: as fits your certificate.
3. **Test → Push events**. Expected: 202 (accepted) or 200 (ignored, for example a test push on another branch).
4. Self-managed GitLab blocks webhooks to private addresses by default: *Admin → Settings → Network → Outbound
   requests → Allow requests to the local network from webhooks and integrations*.

## 4. TFS / Azure DevOps Server, per repository
1. AI-BRAIN: **Repositories** → the repository's row → *Copy URL* and *Copy secret*.
2. TFS → project → **Project settings → Service hooks → + → Web Hooks**:
   - Trigger: **Pull request merge attempted** (repository = yours, target branch = the tracked branch); add a
     second hook **Code pushed** if `push` events are wanted;
   - URL: the copied URL;
   - Basic authentication: any user name, password = the copied secret;
   - Resource details to send: **All**.
3. **Test**. Expected: 200 or 202.

## 5. Group-level hooks
- GitLab: set `BRAIN_GITLAB_WEBHOOK_SECRET` (a long random string) on the Repositories page or in `.env`; add a
  group webhook (GitLab Premium) or a project webhook with URL `http(s)://<server>:8765/webhooks/gitlab`, the same
  secret, and the same triggers as above. A 404 means the project's URL does not match any repository: add
  `"aliases": ["group/project"]` to the repository.
- TFS: set `BRAIN_TFS_WEBHOOK_USER` and `BRAIN_TFS_WEBHOOK_PASSWORD`; add service hooks with URL
  `http(s)://<server>:8765/webhooks/tfs` and those basic-auth values.

## 6. Without webhooks
- Local-path repositories are re-indexed after every pull of their tracked branch, without any webhook
  ([04-REPOSITORIES-AND-SETS.md](04-REPOSITORIES-AND-SETS.md) §4).
- `brain hook` in a developer checkout updates AI-BRAIN after every `git pull` of the tracked branch.
Every repository is updated at least every 24 hours anyway (`BRAIN_SYNC_INTERVAL_MINUTES`, default 1440); set it
lower (for example 10) to update more often when webhooks are not possible. An
unchanged repository costs one fetch and a hash check.

## 7. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| 401 | the secret (or basic-auth values) differs; copy it again on both sides |
| 404 `unknown repository` / `repository not configured` | the name in the URL is wrong, or (group hook) add the repository or an `aliases` entry |
| 503 | the secret is not configured on the AI-BRAIN side (group hook), or the repository has not been saved yet (per-repository hook) |
| 400 `not a GitLab or TFS webhook payload` | the hook sends another format; use the GitLab or TFS hook types above |
| 202 but nothing changes | the sync job failed: see its error on Overview (credentials, network, TLS) |
| GitLab "Invalid url given" | allow local network requests for webhooks (section 3, step 4) |
| A local-path repository shows no webhook | correct: the server does not own that checkout; update it with *Update* or the interval |
