# 20 - Using AI-BRAIN through its REST API

This guide is for developers who connect another system to AI-BRAIN: a portal, a chat bot, a CI pipeline, a script.
It explains how to authenticate, how the calls fit together and how to do each common task, with `curl` and Python
examples. The complete list of routes and fields is the reference in [06-API.md](06-API.md); coding agents can use
the MCP endpoint instead ([07-MCP-AND-AGENTS.md](07-MCP-AND-AGENTS.md)).

## 1. What you can do

| Task | Route | Model calls |
|---|---|---|
| Search code and documents together | `POST /api/search` | none |
| Ask a question and get a cited answer | `POST /api/ask` | a few |
| Turn a request (bug, new feature, change ...) into a prompt for a coding agent | `POST /api/enhance` | a few |
| Write software requirements in your organisation's format | `POST /api/srs` | many (background job) |
| Learn a project: structure and a newcomer's guide | `GET /api/code/overview`, `POST /api/guide` | none / a few |
| Read code: a symbol, a file outline, lines, grep, glob | `GET /api/code/symbol`, `/outline`, `/read`, `/files`, `POST /api/code/grep` | none |
| Add, list and remove documents | `POST /api/docs/upload`, `GET /api/docs`, `DELETE /api/docs/{id}` | embeddings; one vision call per picture |
| Add repositories and start updates | `PUT /api/repos`, `POST /api/repos/{name}/sync` | embeddings for changed code |
| Check whether a branch is behind | `POST /api/drift` | none |
| What a change reaches and which tests to run | `POST /api/impact` | none |
| Keep decisions, rules, gotchas and conventions | `GET`/`POST /api/memory` | none |

## 2. Connecting

**Base URL**: `http(s)://<server>:<BRAIN_PORT>` (default port 8765), for example `http://brain.corp:8765`.

**Authentication**: send the API token on every request. The administrator finds it as `BRAIN_API_TOKEN` in `.env`
(setup generates it) or on the *Settings* page.
```
Authorization: Bearer <BRAIN_API_TOKEN>
```
HTTP basic authentication with the UI user and password also works (`curl -u user:password`). Do not use the
browser cookie from a program: cookie requests that change something need an extra header and expire.

**Check the connection**:
```bash
export BRAIN=http://brain.corp:8765
export H="Authorization: Bearer $BRAIN_API_TOKEN"
curl -s $BRAIN/healthz                       # {"ok": true}, no token needed
curl -s -H "$H" $BRAIN/api/status | jq '{ready, engines, llm}'
```
`ready` is `true` when both engines run. `llm` shows whether the corporate API answers.

**Python**: the examples use `httpx` (bundled with AI-BRAIN); `requests` works the same way.
```python
import httpx
brain = httpx.Client(base_url="http://brain.corp:8765", timeout=600,
                     headers={"Authorization": "Bearer <BRAIN_API_TOKEN>"})
print(brain.get("/api/status").json()["ready"])
```

## 3. Conventions

**JSON in, JSON out.** Send `Content-Type: application/json` with every body. Uploads are `multipart/form-data`.

**Errors** come back as `{"detail": "..."}` with a status code: 400 bad input, 401 missing or wrong token, 404
unknown repository, document, job or format, 413 upload too large, 500 an engine failed (the message names it). A
program should show `detail` to its user; it is written to be read.

**Scope**: which codebases a request looks at. Every search, ask, enhance, guide and requirements request accepts:

| Field | Example | Meaning |
|---|---|---|
| `target` | `"set:payments"` or `"repo:billing"` | one set or one repository |
| `set` | `"payments"` | a set by name |
| `repos` | `["billing", "web"]` or `"billing,web"` | a list of repositories |
| (none) | | every repository |

Documents are always searched as a whole. `GET /api/repos` lists the repositories and sets.

**Branch**: `branch` (for example `"feature/discount"`) searches a branch overlay when one has been indexed; otherwise
the tracked branch is used.

**Model**: `model` picks one of the chat models from `GET /api/models` for this request; leave it out for the
configured default.

**Long-running work runs as a job.** Ask, enhance and guide answer directly unless you send `"async": true`; the
requirements writer, uploads, re-indexing and repository updates always return `{"job": "<id>"}` at once. Poll the
job until its `state` is no longer `running`:
```bash
curl -s -H "$H" $BRAIN/api/jobs/$JOB | jq '{state, step, progress, error}'
```
```python
import time

def wait(job_id, every=2):
    while True:
        j = brain.get(f"/api/jobs/{job_id}").json()
        if j["state"] != "running":
            if j["state"] == "error":
                raise RuntimeError(j["error"])
            return j["result"]
        print(f"{j['progress']:.0%} {j['step']}")
        time.sleep(every)
```
`state` is `running`, `done` or `error`; `step` and `progress` (0 to 1) describe what is happening; `steps` holds the
last 100 progress lines; `result` is the same object the synchronous call would return.

**Live notifications** (optional): `GET /api/events` is a server-sent event stream that sends `data: <n>` whenever
a job, a document, a repository or a setting changes. Use it to refresh a dashboard instead of polling every job.

## 4. Recipes

### 4.1 Search code and documents
No model call: fast and free, also good as a building block for your own assistant.
```bash
curl -s -H "$H" -H "Content-Type: application/json" $BRAIN/api/search \
     -d '{"query": "fatura KDV hesaplama", "target": "set:payments", "detail": "normal"}' | jq -r .markdown
```
- `scope`: `all` (default), `code`, `semantic` (code by meaning only) or `docs`.
- `k`: how many hits (default `BRAIN_SEARCH_TOP_K`).
- `detail`: `brief`, `normal` or `full` controls the size of `markdown`, a ready-to-read summary.
- Structured results: `code[]` (repository, path, lines, signature, callers, callees), `docs.chunks[]` (document,
  section and page, passage text), `docs.rules[]` (business rules typed obligation, prohibition, recommendation,
  limit or value, with their limits), `docs.entities[]` (concepts with definitions, aliases and `implemented_by`),
  `docs.relations[]` (facts),
  `analysis` (how the query was understood) and `sources` (hits per source).

### 4.2 Ask a question
```bash
curl -s -H "$H" -H "Content-Type: application/json" $BRAIN/api/ask \
     -d '{"question": "Müşteriye iade nasıl yapılır?", "target": "set:payments"}' | jq -r .answer
```
`answer` is Markdown with citations (`repo/path:line`, `[document › section, p. N]`). `evidence` is the search the
answer is based on, `steps` the tool calls the model made, `usage` the model calls and tokens. For a chat bot, send
`"async": true` and show the job's `step` while the user waits.

### 4.3 Turn a request into a prompt for a coding agent
One call for every kind of request: a bug to fix, a new feature, a change, a refactor, an investigation. The enhancer
recognises the kind itself.
```bash
curl -s -H "$H" -H "Content-Type: application/json" $BRAIN/api/enhance \
     -d '{"prompt": "1000 TL üzeri iadeler zaman aşımına uğruyor", "target": "repo:billing"}' | jq -r .enhanced
```
`enhanced` is the prompt (Task with the request class, What exists today, Analysis, Business rules, Impact,
Implementation plan, Acceptance criteria, Out of scope, Open questions, Notes for the agent). To add warnings about the
developer's branch, also send `branch`, `repo`, `base_commit` (`git merge-base HEAD origin/main`) and
`changed_files`; the drift check is then in `drift` and in the prompt's notes.

### 4.4 Write software requirements
The requirements writer always uses one of your organisation's formats; there is none at first.

1. Save a format once (Markdown: each heading is a section, the text under it says what to write; IDs like `FR-?`
   are numbered). A Word or PDF template can be converted first:
   ```bash
   curl -s -H "$H" -F "file=@SRS-template.docx" $BRAIN/api/convert | jq -r .markdown > format.md
   jq -Rs '{text: .}' format.md | curl -s -H "$H" -H "Content-Type: application/json" -X PUT \
        $BRAIN/api/srs/templates/company -d @-
   ```
2. Start the writer with the request: system requirements, a new idea or a topic of the current system, of any
   length. Every requirement is checked against the current code and documents and gets a status (Implemented,
   Changes existing behaviour, New, ...):
   ```python
   sysreq = open("system-requirements.md", encoding="utf-8").read()   # or /api/convert for a Word/PDF file
   job = brain.post("/api/srs", json={"topic": sysreq, "target": "set:payments", "template": "company"}).json()["job"]
   spec = wait(job)
   open(spec["name"] + ".md", "w", encoding="utf-8").write(spec["markdown"])
   ```
   Optional fields: `language` (`auto`, `English`, `Turkish`), `title`, `model`. The result also has `capabilities`,
   `errors` (parts that could not be written) and `usage`.
3. Written specifications stay on the server: `GET /api/srs/documents`, `GET /api/srs/documents/{name}`, and
   `POST /api/srs/documents/{name}/publish` adds one to the document graph.

### 4.5 Add documents
```bash
curl -s -H "$H" -F "files=@Iade-Proseduru.pdf" -F "files=@Tarifeler.xlsx" $BRAIN/api/docs/upload   # {"job": "..."}
```
When the job is done, each file is searchable; its result lists `passages` and `pictures` per file. Vectors and
picture descriptions follow in the background (`GET /api/docs` shows `vectors` and `described`). Supported: PDF
(tables, pictures, scanned pages), Word, PowerPoint, Excel, HTML, CSV, JSON, XML, e-mails, zip archives, EPUB,
notebooks, Markdown, text, code and images. Uploading a file with the same name replaces it.
- A short text as a document: `POST /api/docs/text` with `{"name": "decision-42.md", "text": "..."}`.
- What a document was converted to: `GET /api/docs/markdown?name=Iade-Proseduru.pdf`.
- Remove: `DELETE /api/docs/{id}` with the `id` from `GET /api/docs`.

### 4.6 Add a repository
```bash
curl -s -H "$H" $BRAIN/api/repos | jq '{repos: [.repos[] | {name, provider, url, path, branch}], sets}' > repos.json
# add {"name": "web", "url": "gitlab:portal/web", "branch": "develop"} to .repos, then:
curl -s -H "$H" -H "Content-Type: application/json" -X PUT $BRAIN/api/repos -d @repos.json | jq '{indexing, job}'
```
`PUT /api/repos` replaces the whole list, so send every repository you want to keep. A repository that is new, or
whose URL, path or branch changed, is indexed at once on its branch: `indexing` names them and `job` is the update
job. Later updates come from webhooks, local pulls and the 24-hour refresh; `POST /api/repos/{name}/sync` starts one
by hand. The response's `webhook` per repository (`GET /api/repos`) has the URL and secret to configure in GitLab
or TFS ([09-WEBHOOKS.md](09-WEBHOOKS.md)).

### 4.7 Read code without a checkout
```bash
curl -s -H "$H" "$BRAIN/api/code/symbol?name=refund_payment&repo=billing" | jq -r .text   # source, callers, callees
curl -s -H "$H" "$BRAIN/api/code/outline?path=src/billing/invoice.py&repo=billing" | jq -r .text
curl -s -H "$H" "$BRAIN/api/code/read?path=src/billing/invoice.py&start=10&end=40&repo=billing" | jq -r .text
curl -s -H "$H" "$BRAIN/api/code/files?pattern=*.py&repo=billing" | jq -r '.files[]'
curl -s -H "$H" -H "Content-Type: application/json" $BRAIN/api/code/grep \
     -d '{"pattern": "apply_vat", "mode": "matches", "target": "set:payments"}' | jq -r .text
```

### 4.8 Check a branch in CI
```bash
curl -s -H "$H" -H "Content-Type: application/json" $BRAIN/api/drift -d "{\"repo\": \"billing\",
  \"branch\": \"$CI_COMMIT_BRANCH\", \"base_commit\": \"$(git merge-base HEAD origin/main)\",
  \"changed_files\": $(git diff --name-only origin/main...HEAD | jq -Rsc 'split("\n") | map(select(length > 0))')}" \
  | jq -r .markdown
```
`behind`, `risk_files` (changed on both sides) and `recommendations` tell the pipeline whether to rebase first;
`tests_to_run` lists the tests that cover the changed code.

### 4.9 What a change reaches, and which tests to run
```bash
curl -s -H "$H" -H "Content-Type: application/json" $BRAIN/api/impact \
     -d '{"files": ["src/billing/tax.py"], "target": "repo:billing"}' | jq -r .markdown
```
Pass `files` (paths in the repository) and/or `symbols` (names such as `apply_vat` or `InvoiceService.create_invoice`).
Per repository the result has `changed`, `affected` (the code that depends on it, with `depth` and `via`),
`entry_points` (routes and top callers), `tests` and `test_files`; `rules` are the document passages that name the
changed code. No model call. In CI, `brain impact` does the same for the local branch's changed files.

### 4.10 Decision memory
```bash
curl -s -H "$H" -H "Content-Type: application/json" $BRAIN/api/memory -d '{"type": "decision",
  "title": "Refund retries", "text": "Retries stop after three attempts; the bank blocks a fourth.",
  "repo": "billing", "paths": ["src/billing/refund.py"], "source": "ticket PAY-142"}'
curl -s -H "$H" "$BRAIN/api/memory?q=refund%20retries" | jq '.memories[] | {type, title, text, stale}'
```
`type` is `decision`, `rule`, `gotcha` or `convention`. The same type and title replaces the older memory
(`replaced: true`). Every memory is also searchable as a document, so ask and enhance use it. `stale` lists code
paths that no longer exist after the last update. `DELETE /api/memory/{name}` forgets one.

## 5. Good practice
- Keep the token in a secret store; anyone with it can read the indexed code and documents. Use HTTPS in production
  ([12-SECURITY.md](12-SECURITY.md)).
- Use `/api/search` when you only need retrieval; it costs no chat call and at most one embedding call, and never
  waits longer than `BRAIN_EMBED_BUDGET` for it. Use ask, enhance and requirements when
  you need written output.
- Use `"async": true` and the job routes for anything a user waits on, and set a generous client timeout (the
  examples use 600 s) for synchronous calls.
- Read `errors` in every agent response: it lists engines or tools that failed while the answer was still produced.
- The interactive route list (OpenAPI) is at `/api/docs-ui` after logging in to the UI.
