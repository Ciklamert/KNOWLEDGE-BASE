# 01 - Architecture

## 1. The whole system on one page

```
 people (browser) ─login─┐   AI agents ─MCP /mcp─┐ ─REST /api/*─┐   GitLab / TFS ─webhooks─┐
                         ▼                       ▼              ▼                          ▼
┌────────────────────────── brain serve  (brain/server.py: FastAPI + uvicorn, one port) ─────────────────────────┐
│ auth.py      session cookie / bearer token / basic auth; webhooks carry their own secrets                    │
│ settings.py  one schema of every setting; .env (the UI edits it in place); repos.json (repositories, sets)    │
│ jobs.py      background jobs with step, progress and error; a change counter streamed to the UI (/api/events) │
│                                                                                                               │
│ query.py     prompt analysis (stop-words, ranked key terms, variants, concepts) - first step of everything    │
│ search.py    three-source search, no chat call ───────────┐                                                   │
│ agents.py    ask, enhance, project guide, tool loop ──────┤                                                   │
│ srs.py       requirements writer ─────────────────────────┤  all read-only queries                            │
│ drift.py     branch vs. main analysis ────────────────────┤                                                   │
│ mcp.py       MCP tools ───────────────────────────────────┤                                                   │
│ codevec.py   multilingual code vector index ──────────────┤                                                   │
│ repos.py     pull, index, sets, overlays, local-pull watch, daily update ◄── webhooks.py, git hooks          │
│                                                           ▼                                                   │
│ providers/__init__.py      CodeGraph interface                      DocGraph interface                        │
│ providers/codebase_memory.py ─────┐                    providers/docgraph.py + convert.py                    │
│                                   │                      · documents → Markdown → passages (headings, pages)  │
│                                   │                      · keywords (SQLite FTS5), vectors, concepts, links  │
│                                   │                      · data/docs/docs.db + assets/, no LLM per chunk     │
└───────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┘
                                    ▼
      codebase-memory-mcp (native binary): one warm MCP stdio process for queries, one CLI process per index run,
      data/cbm/<project>.db (SQLite), no network
```

The corporate API is called only by `brain/llm.py`: chat (agents, query expansion, requirements, picture
descriptions), embeddings (document passages, code vectors, the question of a search) and the model list. Nothing else leaves the
server except git traffic to the configured git servers.

## 2. Components

| Component | File | Responsibility |
|---|---|---|
| CLI | `brain.py` | `serve`, `doctor`, `sync`, `search`, `ask`, `enhance`, `guide`, `drift`, `hook`, `connect`, `version` |
| Server | `brain/server.py` | routes for UI, REST, MCP, webhooks and live events; start-up sequence; authentication middleware |
| Settings | `brain/settings.py` | schema of all settings, `.env` reading and writing, `repos.json`, data paths |
| Jobs | `brain/jobs.py` | background work with progress; the change counter behind live UI updates |
| Corporate API client | `brain/llm.py` | chat (with tool calling and pictures), embeddings, model list, health probe, token meter |
| Authentication | `brain/auth.py` | signed session cookie, bearer token, basic auth, login lock-out |
| Plug-in contracts | `brain/providers/__init__.py` | `CodeGraph`, `DocGraph`, provider loading by name |
| Code engine provider | `brain/providers/codebase_memory.py` | indexing, hybrid search, exact names, graph expansion, annotations, `symbol`/`outline`/`read`/`grep`/`files`, impact of a change, UI graphs |
| Document engine | `brain/providers/docgraph.py` | passages, keyword index, vectors, concepts (word forms, aliases), business rules, links, picture descriptions, search, UI graph |
| Document converter | `brain/providers/convert.py` | every document format → Markdown + pictures (the MarkItDown idea) |
| Prompt analysis | `brain/query.py` | stop-words, ranked key terms, variants, concepts, language |
| Code vectors | `brain/codevec.py` | multilingual code vector index with the corporate embedding model |
| Search | `brain/search.py` | three-source search, relevance pipeline, Markdown rendering, evidence |
| Agents | `brain/agents.py` | ask, enhance (any request: bug fix, new feature, refactor ...), project guide, query expansion, the shared tool loop and its tools (also used by MCP and REST) |
| Requirements writer | `brain/srs.py` | software requirements in the user's own format from system requirements, a new idea or a topic, checked against the code and documents |
| Repositories | `brain/repos.py` | registry, sets, git, sync, local-pull watch, daily update, git hooks, branch overlays, index state |
| Branch drift | `brain/drift.py` | branch vs. `main` analysis with recommendations and the tests to run |
| Decision memory | `brain/memory.py` | typed, dated decisions, rules, gotchas and conventions; searchable; marked stale when their code is gone |
| Webhooks | `brain/webhooks.py` | per-repository and group-level GitLab and TFS hooks |
| MCP | `brain/mcp.py` | MCP tool definitions and JSON-RPC handling |
| UI | `brain/ui/` | one static page: `index.html`, `app.js`, `style.css`, vendored force-graph |

Every file is described in [16-CODEBASE.md](16-CODEBASE.md).

## 3. Main flows

### 3.1 Start-up (`brain serve`)
1. Settings are read from `.env`. The server refuses to listen on a non-loopback address while
   `BRAIN_UI_PASSWORD` is empty.
2. Repositories in `repos.json` without a webhook secret get one.
3. Three jobs start in parallel: **Start code graph engine** (starts the warm MCP process, which loads the bundled
   code model), **Start document graph engine** (opens `data/docs/docs.db`; then, in the background, embeds passages
   without a vector and describes pictures not described yet) and **Check corporate API** (one chat call and one
   embedding call; reports the real embedding size).
4. When the code engine is ready and `BRAIN_SYNC_ON_START=true`, every repository is cloned or updated and
   indexed (incrementally), and its multilingual code vectors are updated.
5. `/api/status` reports `ready: true` when both engines and the corporate API are ready, and the log prints
   `READY`. The UI answers from the first second and shows every job with its progress and errors.
6. Background loops: local checkouts are watched for pulls of their tracked branch (`BRAIN_WATCH_LOCAL_SECONDS`), and
   every repository is updated at least every `BRAIN_SYNC_INTERVAL_MINUTES` (default 24 hours).

### 3.2 Search (no chat call)
1. Prompt analysis: stop-words out, key terms ranked, variants and concepts built (`brain/query.py`).
2. In parallel: the code engine (BM25 + its local code vectors, fused by reciprocal rank) for the repositories in
   scope, the multilingual code vector index, and the document engine (keywords + passage vectors + concept graph).
3. Exact names: identifiers and file paths written in the question find their symbols directly.
4. Document-to-code bridge: concept names from the document results become extra code-search terms.
5. Code-graph expansion: callers, callees and parents of the best hits join the candidates.
6. Re-ranking of the code candidates by meaning with the corporate embedding model.
7. Named symbols first, repository balance, source lines, and graph annotations (signature, callers, callees,
   parents) per hit; rendered for agents at a detail level (brief, normal, full).

Details: [05-SEARCH-ASK-ENHANCE.md](05-SEARCH-ASK-ENHANCE.md).

### 3.3 Ask, enhance and the project guide
Prompt analysis → one short model call for extra search terms → the search above seeds the conversation → the
model may call read-only tools for at most `MAX_STEPS` rounds within `TIMEOUT` → final answer, enhanced prompt (for any
kind of request) or project guide. Enhance also runs a branch-drift check when a branch is given; the
guide adds the architecture overview of every repository in scope. Fallbacks: a gateway without tool calling gets
one grounded call; an unreachable model returns the search results or a deterministic prompt.

### 3.4 Requirements writer
The request (a topic to describe, or system requirements / a new idea) and the user's format → evidence (search +
architecture overview of every repository + documents) → the model plans the capabilities and picks the format
sections to write per capability → each capability is written with its own search → the other sections follow the
format → IDs numbered, appendix added, saved under `data/srs/output/`. Details:
[17-REQUIREMENTS-WRITER.md](17-REQUIREMENTS-WRITER.md).

### 3.5 Repository update
A webhook, a git hook after a pull, a pull noticed in a local checkout, a button, the CLI, MCP `sync_repo`, start-up
or the daily schedule calls `repos.request_sync`, which starts the update at once; a request that arrives while the
same repository is being updated makes that update run once more when it finishes. The job brings the checkout to
the tracked branch (server-managed clone: `fetch` + `checkout -B` + `reset --hard`; local checkout: `pull --ff-only`
only when clean and on the tracked branch), runs the code engine's incremental index, updates the multilingual code
vectors of changed symbols, and records the indexed commit in `data/state.json`.

### 3.6 Document upload
UI or REST upload → the original is kept in `data/originals/` → the file is converted to Markdown with its pictures
(`data/converted/<file>.md` keeps the Markdown) → split along headings into passages (text, tables by rows,
pictures), with section path and page → keyword index, concepts, document links: the document is **searchable at
once, without any model call** → in the background: one batched embedding pass for the passage vectors, then the
vision model describes each picture (when `BRAIN_VLM_MODEL` is set). The **Documents** page shows passages, vectors
and described pictures per document, updated live.

### 3.7 Live UI
Every job step, document change, repository or settings change, and webhook delivery increases one change counter
(`jobs.tick()`). The browser keeps one server-sent-events connection to `/api/events`; on each change it refreshes the
status and the visible page (at most about three times a second), so results of an operation appear without
reloading.

## 4. Storage

Everything lives under `BRAIN_DATA_DIR` (default `data/` in the install folder).

| Path | Contents | Safe to delete? |
|---|---|---|
| `cbm/<project>.db` | code graph, BM25 index and local code vectors per repository or branch overlay | yes: rebuilt by the next sync |
| `codevec/<project>.npz` | multilingual code vectors (int8) per repository or overlay | yes: rebuilt by the next sync (one embedding pass) |
| `repos/<name>/` | server-managed clones | yes: cloned again |
| `worktrees/<repo>--<branch>/` | branch overlay checkouts | remove overlays in the UI first |
| `docs/docs.db` | the document engine: passages, keyword index, vectors, concepts, links | yes, if `originals/` is kept: **Re-index all** rebuilds it |
| `docs/assets/` | the pictures of each document | with `docs.db` |
| `originals/` | uploaded files exactly as received | **keep**: the source for re-indexing |
| `converted/` | the Markdown each document was converted to | yes (re-created by re-indexing) |
| `srs/templates/`, `srs/output/` | the user's requirements formats and written specifications | keep |
| `state.json` | indexed commit per repository, branch overlays | yes |
| `logs/` | `server.log`, `codebase-memory.log` | yes |
| `.secret_key` | cookie signing key when `BRAIN_SECRET_KEY` is empty | yes (everyone is logged out) |

A backup is a copy of `data/`, `.env` and `repos.json`.

## 5. Folder layout
```
brain.py  brain.cmd  brain.sh        CLI and launchers (the launchers use .venv)
setup.ps1  setup.sh                  offline installers
requirements.txt  .env.example  repos.example.json
README.md  INSTALL.html
wheels/                              every Python package for Python 3.13, Windows x64 and Linux x86-64 (41 files)
bin/                                 codebase-memory-mcp archives + SHA256SUMS (setup unpacks bin/windows or bin/linux)
brain/                               the server
  providers/                         codebase_memory.py, docgraph.py, convert.py
  ui/                                index.html, app.js, style.css, vendor/force-graph.min.js
integrations/                        AGENTS.brain.md, claude-code/brain-enhance.md
tests/                               mock_openai.py, smoke_test.py, test_static.py
tools/                               gen_config.py (generates .env.example and docs/03-CONFIGURATION.md)
docs/                                this documentation and decisions/
```
Created at run time: `.venv/`, `.env`, `repos.json`, `data/`.

## 6. Design principles
1. **No model call where text analysis is enough.** Code and documents are indexed with parsers, keyword indexes,
   graph statistics and one batched embedding pass; models are used at question time, and for pictures.
2. **One of everything.** One process, one port, one settings schema, one configuration file, one job mechanism,
   one search used by every function, one tool implementation behind MCP, REST and the agents.
3. **Degrade, never block.** Every model step has a fallback; every long step is a background job with visible
   progress and errors; a failed embedding or picture step is finished later.
4. **Interfaces at the seams.** Engine-specific code lives only in `brain/providers/`.
5. **Local state only.** SQLite and plain files; a backup is a folder copy.
6. **Evidence first.** Every answer, prompt and specification is built from search results that are shown with it.
7. **Small.** About 6,350 lines of Python and a 750-line UI script, 11 direct Python dependencies.
