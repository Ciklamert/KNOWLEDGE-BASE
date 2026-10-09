# 06 - REST API reference

Base URL: `http(s)://<server>:<BRAIN_PORT>` (default port 8765). All bodies and responses are JSON unless stated
otherwise. An interactive list of the routes (OpenAPI) is at `/api/docs-ui` after login.

## Authentication
Every route needs one of the following, except `/`, `/healthz`, `/api/login`, `/api/logout`, `/ui/*` and
`/webhooks/*` (webhooks carry their own secrets, see [09-WEBHOOKS.md](09-WEBHOOKS.md)):
- `Authorization: Bearer <BRAIN_API_TOKEN>` (agents, scripts, CI);
- `Authorization: Basic base64(<BRAIN_UI_USER>:<BRAIN_UI_PASSWORD>)` (for example `curl -u user:pass`);
- the `brain_session` cookie set by `/api/login` (the browser). Requests with this cookie that change something
  (`POST`, `PUT`, `DELETE`) must also send the header `X-Brain-UI: 1`.

Errors are JSON `{"detail": "..."}`:

| Status | Meaning |
|---|---|
| 400 | bad input (missing field, invalid setting value, invalid format) |
| 401 | not authenticated |
| 403 | cookie request without `X-Brain-UI: 1` |
| 404 | unknown repository, set, document, job, node or file |
| 413 | upload larger than `BRAIN_MAX_UPLOAD_MB` |
| 429 | five failed logins from this address in the last minute |
| 500 | engine error; the message names the engine and the reason |

## Session

| Method and path | Body / query | Returns |
|---|---|---|
| `GET /healthz` | | `{"ok": true}` without authentication (for load balancers and monitoring) |
| `POST /api/login` | `{"username", "password"}` | sets the `brain_session` cookie (HttpOnly, SameSite=Strict, `Secure` with TLS) |
| `POST /api/logout` | | clears the cookie |
| `GET /api/me` | | `{"user", "public_url"}` |

## Status, jobs, logs

| Method and path | Body / query | Returns |
|---|---|---|
| `GET /api/status` | | `ready`; `engines.code` and `engines.docs` (`state`, `detail`, log tail on error); `llm` (probe result and real embedding size); `pipeline` (LightRAG ingestion); `models` (`default`, `ask`, `enhance`, `srs`, `lightrag`, `embedding`, `vision`); `running` jobs; `uptime` |
| `GET /api/jobs` | `kind` (`startup`, `sync`, `upload`, `ask`, `enhance`, `srs`, `branch`, `restart`), `limit` (50) | recent jobs, newest first |
| `GET /api/jobs/{job_id}` | | one job with `state` (running, done, error), `step`, `progress`, `steps` (last 100), `result`, `error`, `seconds` |
| `GET /api/logs/{name}` | `name` = `server`, `lightrag`, `code`; `lines` (200, at most 2000) | the last log lines |

## Search, ask, enhance, analysis, drift

Scope fields, accepted by every request below: `target` = `set:<name>` or `repo:<name>` (the UI combobox
value); or `set` (a set name) and `repos` (a list, or a comma-separated string). Default: every repository.
`branch` uses a branch overlay when one exists. `model` overrides the configured chat model for this request.

| Method and path | Body | Returns |
|---|---|---|
| `POST /api/analyze` | `{"text"}` (also `query`, `prompt` or `question`) | the prompt analysis only: `language`, `terms[{term, kind, score}]`, `keywords`, `variants`, `identifiers`, `concepts`, `stop_words`, `tokens`, `summary` |
| `GET /api/models` | | `models` (chat models the corporate API lists at `GET /models`, plus the configured ones, without the embedding model), `listed`, `error`, `defaults` (`ask`, `enhance`, `srs`) |
| `POST /api/search` | `{"query", "scope": "all"\|"code"\|"semantic"\|"docs", "target", "set", "repos", "branch", "k"}` | `analysis` (with `expanded`, `bridged` when used), `pipeline`, `sources` (hits per source), `code[]` (`project`, `id`, `qn`, `name`, `label`, `path`, `line1`, `line2`, `code`, `matched`, `signature`, `callers`, `callees`, `parents`, `similarity`, `rerank`), `relations[]`, `docs` (`chunks`, `entities`, `relations`), `projects`, `errors`, `ms`, `markdown` |
| `POST /api/ask` | `{"question", "target", "set", "repos", "branch", "model", "async": false}` | `answer`, `model`, `llm`, `analysis`, `sources`, `evidence` (the search the answer is based on), `steps` (tool calls), `errors`, `ms`; with `"async": true` only `{"job"}` |
| `POST /api/enhance` | `{"prompt", "target", "set", "repos", "branch", "model", "repo", "base_commit", "changed_files": [..], "async": false}` | `enhanced`, `model`, `llm`, `analysis`, `sources`, `evidence`, `steps`, `drift`, `errors`, `ms`; or `{"job"}` |
| `POST /api/drift` | `{"repo", "branch", "base_commit", "head_commit", "changed_files": [..]}` (`repo` required) | `tracked_branch`, `indexed_commit`, `main_head`, `base_commit`, `behind`, `main_files`, `branch_files`, `risk_files`, `facts`, `recommendations[{action, why, how, files}]`, `markdown` |

Example:
```bash
curl -s -H "Authorization: Bearer $BRAIN_API_TOKEN" -H "Content-Type: application/json" \
     -d '{"query":"fatura KDV hesaplama","target":"set:payments"}' http://brain:8765/api/search | jq -r .markdown
```

## Repositories and sets

| Method and path | Body | Returns |
|---|---|---|
| `GET /api/repos` | | `repos[]` (configuration without tokens, `token_set`, `remote`, `managed`, `checkout`, `sets`, own `webhook` {`url`, `secret`, `provider`, `how`}, `indexed`, `nodes`, `commit`, `indexed_at`, `error`, `vectors`, `branches`), `sets`, `file` |
| `PUT /api/repos` | `{"repos": [{name, provider, url, path, branch, user, token, aliases}], "sets": {"<set>": ["<repo>", ...]}}` | the validated, saved `repos.json` (`repos`, `sets`); webhook secrets are generated; an empty token keeps the stored one |
| `POST /api/repos/sync` | | `{"job"}`: update and index all repositories |
| `POST /api/repos/{name}/sync` | | `{"job", "debounced"}`; `job` is null when an update was requested within the debounce window |
| `POST /api/repos/{name}/branches` | `{"branch"}` | `{"job"}`: index a pushed branch as an overlay |
| `DELETE /api/repos/{name}/branches/{branch}` | | removes the overlay; the branch may contain `/` |

## Code (used by the UI, and the read / grep / glob replacements for agents)

| Method and path | Query / body | Returns |
|---|---|---|
| `GET /api/code/projects` | | `[{name, root, indexed_at, nodes, edges}]` for every repository and overlay |
| `GET /api/code/graph` | `project`, `limit` (1200, at most 5000) | architecture graph: classes, modules, routes, with method edges lifted to their classes |
| `GET /api/code/ego/{node_id}` | `project`, `depth` (1 or 2) | the neighbourhood of a node |
| `GET /api/code/node/{node_id}` | `project` | node details, source, incoming and outgoing relations |
| `GET /api/code/find` | `q`, `project` (optional) | up to 25 symbols by name |
| `GET /api/code/read` | `repo`, `path`, `start` (1), `end` | `{project, path, start, end, total_lines, text}`: numbered lines, at most 400 (default 200) |
| `GET /api/code/files` | `pattern` (glob, default `*`), `target` or `repo` | `{"files": ["repo/path", ...]}`, at most 300 per repository |
| `POST /api/code/grep` | `{"pattern", "regex": false, "file_pattern", "target", "set", "repos"}` | `{"text"}`: matches per repository, ranked by the code graph |

## Documents

| Method and path | Body / query | Returns |
|---|---|---|
| `GET /api/docs` | | `documents[]` (`id`, `name`, `status`, `chunks`, `updated_at`, `error`, `summary`), `pipeline` (`busy`, `job`, `message`, `batch`, `batches`, `docs`, `history`) |
| `POST /api/docs/upload` | multipart field `files` (one or more) | `{"job"}`; the job result lists each file (`file`, `stored_as`, `converted`, `markdown_chars`, `status`, `message`) |
| `POST /api/docs/text` | `{"name", "text"}` | adds a note as a document |
| `GET /api/docs/markdown` | `name` | `{name, markdown}`: what the document was converted to before it went to LightRAG |
| `DELETE /api/docs/{doc_id}` | | removes the document with its chunks, entities, relations and cached extraction results |
| `GET /api/docs/graph` | `label` (`*` = whole graph), `max_nodes` (600, at most 3000), `depth` (3, at most 6) | `{nodes, links, truncated}` |
| `GET /api/docs/labels` | `q` | entity names; the most connected ones when `q` is empty |

## Requirements writer
See [17-REQUIREMENTS-WRITER.md](17-REQUIREMENTS-WRITER.md).

| Method and path | Body | Returns |
|---|---|---|
| `POST /api/srs` | `{"topic", "target", "set", "repos", "template": "default", "language": "auto", "model", "title", "async": true}` | `{"job"}`; the job result (or, with `"async": false`, the response) is `{name, markdown, title, topic, scope, template, language, model, capabilities, errors, seconds, evidence, analysis}` |
| `GET /api/srs/templates` | | `{"templates": [names]}` |
| `GET /api/srs/templates/{name}` | | `{name, text}` |
| `PUT /api/srs/templates/{name}` | `{"text"}` | saves a format; it must contain at least one `##` section |
| `DELETE /api/srs/templates/{name}` | | deletes a format (`default` cannot be deleted) |
| `GET /api/srs/documents` | | written specifications with their metadata |
| `GET /api/srs/documents/{name}` | | `{name, markdown}` |
| `DELETE /api/srs/documents/{name}` | | deletes a specification |
| `POST /api/srs/documents/{name}/publish` | | adds the specification to the document graph as `SRS-<name>.md` |

## Settings and engines

| Method and path | Body | Returns |
|---|---|---|
| `GET /api/settings` | | `settings[]` (`key`, `group`, `page`, `help`, `kind`, `choices`, `restart`, `default`, `value`, `is_set`; secrets have an empty `value`), `file` |
| `PUT /api/settings` | `{"changes": {"KEY": "value"}}` | `saved`, `jobs` (engine restarts and API checks started), `restart_server`, `message` |
| `POST /api/restart/{kind}` | `kind` = `code` or `docs` | `{"job"}`: restart that engine |

## Webhooks

| Method and path | Authentication | Returns |
|---|---|---|
| `POST /webhooks/repo/{name}` | the repository's own secret: GitLab `X-Gitlab-Token`, or TFS basic-auth password | 202 accepted (with `job`, `debounced`), 200 ignored (with the reason), 400 not a GitLab or TFS payload, 401 wrong secret, 404 unknown repository, 503 no secret yet |
| `POST /webhooks/gitlab` | `X-Gitlab-Token` = `BRAIN_GITLAB_WEBHOOK_SECRET` | 202, 200 ignored, 401, 404 repository not in `repos.json`, 503 secret not configured |
| `POST /webhooks/tfs` | basic auth = `BRAIN_TFS_WEBHOOK_USER` / `BRAIN_TFS_WEBHOOK_PASSWORD` | same as GitLab |
| `GET /api/webhooks` | login | group-hook URLs, whether they are configured, `events`, the last 50 `deliveries` |

## MCP
`POST /mcp` (JSON-RPC 2.0, Streamable HTTP transport, JSON responses; a batch array is accepted), `GET /mcp` →
405, `DELETE /mcp` → 200. Tools and client setup: [07-MCP-AND-AGENTS.md](07-MCP-AND-AGENTS.md).
