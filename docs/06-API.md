# 06 - REST API reference

For a task-oriented introduction with examples, start with [20-REST-API-GUIDE.md](20-REST-API-GUIDE.md).

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
| `GET /api/status` | | `ready`; `engines.code` and `engines.docs` (`state`, `detail`, log tail on error); `llm` (probe result and real embedding size); `pipeline` (document engine activity: `busy`, `message`); `models` (`default`, `ask`, `enhance`, `srs`, `guide`, `embedding`, `vision`); `running` jobs; `uptime` |
| `GET /api/jobs` | `kind` (`startup`, `sync`, `upload`, `ask`, `enhance`, `guide`, `srs`, `branch`, `restart`), `limit` (50) | recent jobs, newest first |
| `GET /api/jobs/{job_id}` | | one job with `state` (running, done, error), `step`, `progress`, `steps` (last 100), `result`, `error`, `seconds` |
| `GET /api/logs/{name}` | `name` = `server` or `code`; `lines` (200, at most 2000) | the last log lines |
| `GET /api/events` | | server-sent events: `data: <n>` whenever something visible changes (job steps, documents, repositories, settings, webhook deliveries), and a keep-alive comment about every 20 s; the UI refreshes on each message |

## Search, ask, enhance, analysis, drift

Scope fields, accepted by every request below: `target` = `set:<name>` or `repo:<name>` (the UI combobox
value); or `set` (a set name) and `repos` (a list, or a comma-separated string). Default: every repository.
`branch` uses a branch overlay when one exists. `model` overrides the configured chat model for this request.

| Method and path | Body | Returns |
|---|---|---|
| `POST /api/analyze` | `{"text"}` (also `query`, `prompt` or `question`) | the prompt analysis only: `language`, `terms[{term, kind, score}]`, `keywords`, `variants`, `identifiers`, `concepts`, `stop_words`, `tokens`, `summary` |
| `GET /api/models` | | `models` (chat models the corporate API lists at `GET /models`, plus the configured ones, without the embedding model), `listed`, `error`, `defaults` (`ask`, `enhance`, `srs`, `guide`) |
| `POST /api/search` | `{"query", "scope": "all"\|"code"\|"semantic"\|"docs", "target", "set", "repos", "branch", "k", "detail": "brief"\|"normal"\|"full"}` | `analysis` (with `expanded`, `bridged` when used), `pipeline`, `sources` (hits per source), `code[]` (`project`, `id`, `qn`, `name`, `label`, `path`, `line1`, `line2`, `code`, `matched`, `signature`, `callers`, `callees`, `parents`, `similarity`, `rerank`), `relations[]`, `docs` (`chunks`: passages with `source` (document › section, page), `doc`, `content`, `kind`, `matched`, `similarity`; `entities`: concepts with `name`, `type`, `description`, `aliases`, `implemented_by`; `relations`: facts `a`, `b`, `description`; `rules`: `text`, `modality` (obligation, prohibition, recommendation, permission, limit, value), `kind` (rule, story, acceptance, table row), `limits`, `actor`, `action`, `condition`, `unit` (the unit path, e.g. "Bölüm 2 › Madde 5 › (1)"), `confidence`, `source`; `documents`: the cards of the documents shown (`name`, `summary`, `effective`, `version`, `superseded_by`); a passage of an older version has `note`), `projects`, `errors`, `ms`, `markdown` (at the requested `detail`, default `BRAIN_SEARCH_DETAIL`) |
| `POST /api/ask` | `{"question", "target", "set", "repos", "branch", "model", "async": false}` | `answer`, `model`, `llm`, `analysis`, `sources`, `evidence` (the search the answer is based on), `steps` (tool calls), `errors`, `usage` (`calls`, `prompt_tokens`, `completion_tokens`), `ms`; with `"async": true` only `{"job"}` |
| `POST /api/enhance` | `{"prompt", "target", "set", "repos", "branch", "model", "repo", "base_commit", "changed_files": [..], "async": false}`; any kind of request (bug fix, new feature, refactor ...) | `enhanced`, `model`, `llm`, `analysis`, `sources`, `evidence`, `steps`, `drift`, `errors`, `usage`, `ms`; or `{"job"}` |
| `POST /api/guide` | `{"topic", "target", "set", "repos", "model", "async": true}` | `{"job"}`; the job result (or, with `"async": false`, the response) is `{guide, model, llm, architecture, analysis, sources, evidence, steps, errors, usage, ms}` |
| `POST /api/drift` | `{"repo", "branch", "base_commit", "head_commit", "changed_files": [..]}` (`repo` required) | `tracked_branch`, `indexed_commit`, `main_head`, `base_commit`, `behind`, `main_files`, `branch_files`, `risk_files`, `facts`, `recommendations[{action, why, how, files}]`, `markdown` |
| `POST /api/impact` | `{"files": [..], "symbols": [..], "depth": 3}` plus the scope fields; at least files or symbols | `repos[]` (per repository: `project`, `changed`, `affected` (`symbol`, `path`, `line`, `depth`, `via`), `entry_points` (`routes`, `top_callers`), `tests`, `test_files`), `rules` (document passages that name the changed code), `errors`, `markdown`; no model call |

Example:
```bash
curl -s -H "Authorization: Bearer $BRAIN_API_TOKEN" -H "Content-Type: application/json" \
     -d '{"query":"fatura KDV hesaplama","target":"set:payments"}' http://brain:8765/api/search | jq -r .markdown
```

## Repositories and sets

| Method and path | Body | Returns |
|---|---|---|
| `GET /api/repos` | | `repos[]` (configuration without tokens, `token_set`, `remote`, `managed`, `checkout`, `sets`, own `webhook` {`url`, `secret`, `provider`, `how`}, `indexed`, `nodes`, `commit`, `indexed_at`, `error`, `vectors`, `branches`), `sets`, `file` |
| `PUT /api/repos` | `{"repos": [{name, provider, url, path, branch, user, token, aliases}], "sets": {"<set>": ["<repo>", ...]}}` | the validated, saved `repos.json` (`repos`, `sets`), plus `indexing` (repositories that are new or whose URL, path or branch changed: they are indexed at once on their branch) and `job` (that update, or null); webhook secrets are generated; an empty token keeps the stored one |
| `POST /api/repos/sync` | | `{"job"}`: update and index all repositories |
| `POST /api/repos/{name}/sync` | | `{"job", "queued"}`; starts at once; when the repository is already being updated, `job` is null, `queued` is true and that update runs once more |
| `POST /api/repos/{name}/branches` | `{"branch"}` | `{"job"}`: index a pushed branch as an overlay |
| `DELETE /api/repos/{name}/branches/{branch}` | | removes the overlay; the branch may contain `/` |

## Code (used by the UI, and the read / grep / glob replacements for agents without MCP)

`target` (`set:<name>` or `repo:<name>`) or `repo` choose the scope; without them every repository is used.

| Method and path | Query / body | Returns |
|---|---|---|
| `GET /api/code/projects` | | `[{name, root, indexed_at, nodes, edges}]` for every repository and overlay |
| `GET /api/code/graph` | `project`, `limit` (1200, at most 5000) | architecture graph: classes, modules, routes, with method edges lifted to their classes |
| `GET /api/code/ego/{node_id}` | `project`, `depth` (1 or 2) | the neighbourhood of a node |
| `GET /api/code/node/{node_id}` | `project` | node details, source, incoming and outgoing relations |
| `GET /api/code/find` | `q`, `project` (optional) | up to 25 symbols by name |
| `GET /api/code/symbol` | `name` (short or qualified), `source` (`auto`, `full`, `none`), `target` or `repo` | `{"text"}`: location, signature, source, callers, callees, parents, other matches |
| `GET /api/code/outline` | `path`, `target` or `repo` | `{"text"}`: declarations of the file with line ranges |
| `GET /api/code/overview` | `repo`, `path` (folder), `aspects` (comma list: `overview`, `structure`, `routes`, `hotspots`, `entry_points`, `dependencies`, `layers`, `file_tree`) | `{"text"}`: the repository's structure |
| `GET /api/code/read` | `path`, `start` (1), `end`, `repo` or `target` | `{project, path, start, end, total_lines, text}`: numbered lines, at most 400 (default 200); without `repo` the first repository that has the file |
| `GET /api/code/files` | `pattern` (glob, default `*`), `target` or `repo` | `{"files": ["repo/path", ...]}`, at most 300 per repository |
| `POST /api/code/grep` | `{"pattern", "regex": false, "mode": "files"\|"matches"\|"full", "file_pattern", "path", "target", "set", "repos"}` | `{"text"}`: matches per repository with matches, ranked by the code graph |

## Documents

| Method and path | Body / query | Returns |
|---|---|---|
| `GET /api/docs` | | `documents[]` (`id`, `name`, `status`, `chunks` (passages), `rules`, `versions`, `effective`, `superseded_by`, `versions_of`, `vectors`, `pictures`, `described`, `updated_at`, `error`), `pipeline` (`busy`, `message`) |
| `POST /api/docs/upload` | multipart field `files` (one or more) | `{"job"}`; the job result lists each file (`file`, `status`, `passages`, `pictures`, `markdown_chars`, `message`); each file is searchable when its entry appears; vectors and picture descriptions follow in the background |
| `POST /api/docs/text` | `{"name", "text"}` | adds a note as a document (Markdown) and returns its upload result |
| `GET /api/docs/markdown` | `name` | `{name, markdown}`: what the document was converted to before it was indexed |
| `DELETE /api/docs/{doc_id}` | | `{"deleted": [names]}`: removes the document with its passages, vectors, concepts, links, pictures, original and Markdown |
| `POST /api/docs/reindex` | | `{"job"}`: converts and indexes every original again (after a converter or passage-size change) |
| `GET /api/docs/graph` | `label` (`*` = the most connected concepts, or a concept name), `max_nodes` (600, at most 3000), `depth` (3, at most 6) | `{nodes, links, truncated}`: concepts and documents; links `mentions`, `related`, `same as` (aliases), `refers to` |
| `GET /api/docs/themes` | `limit` (20) | `themes[]`: `label` (the most mentioned concepts), `concepts`, `size`, `documents`; communities of the concept graph, no model call |
| `GET /api/docs/doc` | `mode` (`list`, `outline`, `unit`, `refs`, `define`, `obligations`, `impact`), `document`, `unit`, `term`, `actor`, `q` | `{text, data}`: the document grammar (units, references, definitions, statements), no model call; the same as the MCP tool `doc` |
| `GET /api/docs/card` | `name` | the document card: `summary` (central sentences), `dates`, `effective`, `versions`, `numbers`, `language`, `versions_of`, `superseded_by` |
| `GET /api/docs/labels` | `q` | concept names; the most mentioned ones when `q` is empty |
| `POST /api/convert` | multipart field `file` | `{name, markdown}`: any supported document converted to Markdown without indexing it (system requirements and formats for the requirements writer) |

## Decision memory

| Method and path | Body / query | Returns |
|---|---|---|
| `GET /api/memory` | `q` (ranks by relevance), `repo`, `type` | `memories[]` (`name`, `type`, `title`, `text`, `repo`, `paths`, `source`, `created`, `stale` (code paths that no longer exist), `history`), `types` |
| `POST /api/memory` | `{"type": "decision"\|"rule"\|"gotcha"\|"convention", "title", "text", "repo", "paths": [..], "source"}` | the memory with `replaced` (true when one with the same type and title existed); it is also a document named `memory-<type>-<title>.md` |
| `DELETE /api/memory/{name}` | | `{"deleted"}`: the memory and its document |

## Requirements writer
See [17-REQUIREMENTS-WRITER.md](17-REQUIREMENTS-WRITER.md).

| Method and path | Body | Returns |
|---|---|---|
| `POST /api/srs` | `{"topic", "target", "set", "repos", "template", "language": "auto", "model", "title", "async": true}`; `topic` is the request, any length: system requirements, a new idea or a topic of the current system; `template` is one of the user's formats (default: the first) | `{"job"}`; the job result (or, with `"async": false`, the response) is `{name, markdown, title, topic, scope, template, language, model, capabilities, errors, usage, seconds, evidence, analysis}`; 400 when no format exists yet |
| `GET /api/srs/templates` | | `{"templates": [names]}`: the user's formats (none at first) |
| `GET /api/srs/templates/{name}` | | `{name, text}` |
| `PUT /api/srs/templates/{name}` | `{"text"}` | saves a format; it must have headings (each is a section) |
| `DELETE /api/srs/templates/{name}` | | deletes a format |
| `GET /api/srs/documents` | | written specifications with their metadata (`title`, `scope`, `template`, `model`, `created`) |
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
| `POST /webhooks/repo/{name}` | the repository's own secret: GitLab `X-Gitlab-Token`, or TFS basic-auth password | 202 accepted (with `job`, `queued`), 200 ignored (with the reason), 400 not a GitLab or TFS payload, 401 wrong secret, 404 unknown repository, 503 no secret yet |
| `POST /webhooks/gitlab` | `X-Gitlab-Token` = `BRAIN_GITLAB_WEBHOOK_SECRET` | 202, 200 ignored, 401, 404 repository not in `repos.json`, 503 secret not configured |
| `POST /webhooks/tfs` | basic auth = `BRAIN_TFS_WEBHOOK_USER` / `BRAIN_TFS_WEBHOOK_PASSWORD` | same as GitLab |
| `GET /api/webhooks` | login | group-hook URLs, whether they are configured, `events`, the last 50 `deliveries` |

## MCP
`POST /mcp` (JSON-RPC 2.0, Streamable HTTP transport, JSON responses; a batch array is accepted), `GET /mcp` →
405, `DELETE /mcp` → 200. Tools and client setup: [07-MCP-AND-AGENTS.md](07-MCP-AND-AGENTS.md).
