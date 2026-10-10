# 01 - Architecture

## 1. The whole system on one page

```
 people (browser) ─login─┐   AI agents ─MCP /mcp─┐ ─REST /api/*─┐   GitLab / TFS ─webhooks─┐
                         ▼                       ▼              ▼                          ▼
┌────────────────────────── brain serve  (brain/server.py: FastAPI + uvicorn, one port) ─────────────────────────┐
│ auth.py      session cookie / bearer token / basic auth; webhooks carry their own secrets                    │
│ settings.py  one schema of every setting; .env (the UI edits it in place); repos.json (repositories, sets)    │
│ jobs.py      background jobs with step, progress and error, polled by the UI                                  │
│                                                                                                               │
│ query.py     prompt analysis (stop-words, ranked key terms, variants, concepts) - first step of everything    │
│ search.py    three-source search, no chat call ───────────┐                                                   │
│ agents.py    ask, enhance, shared tool loop ──────────────┤                                                   │
│ srs.py       requirements writer ─────────────────────────┤  all read-only queries                            │
│ drift.py     branch vs. main analysis ────────────────────┤                                                   │
│ mcp.py       MCP tools ───────────────────────────────────┤                                                   │
│ codevec.py   multilingual code vector index ──────────────┤                                                   │
│ repos.py     clone/fetch, index, sets, overlays, debounced sync ◄── webhooks.py (GitLab, TFS)               │
│                                                           ▼                                                   │
│ providers/__init__.py      CodeGraph interface                      DocGraph interface                        │
│ providers/codebase_memory.py ─────┐                    providers/lightrag.py + convert.py ─┐                │
└───────────────────────────────────┼────────────────────────────────────────────────────────┼────────────────┘
                                    ▼                                                        ▼
      codebase-memory-mcp (native binary)                         lightrag-server (child process, 127.0.0.1:9631)
       · one warm MCP stdio process for queries                    · entity/relation extraction (chat model)
       · one CLI process per index run                             · chunk, entity and relation vectors (embeddings)
       · data/cbm/<project>.db (SQLite), no network                · data/lightrag/ (graphml, JSON, nano-vectordb)
```

The corporate API is called by `brain/llm.py` (chat, embeddings, model list) and by LightRAG. Nothing else leaves
the server except git traffic to the configured git servers.

## 2. Components

| Component | File | Responsibility |
|---|---|---|
| CLI | `brain.py` | `serve`, `doctor`, `sync`, `search`, `ask`, `enhance`, `drift`, `connect`, `version` |
| Server | `brain/server.py` | routes for UI, REST, MCP and webhooks; start-up sequence; authentication middleware |
| Settings | `brain/settings.py` | schema of all settings, `.env` reading and writing, `repos.json`, data paths |
| Jobs | `brain/jobs.py` | background work with progress |
| Corporate API client | `brain/llm.py` | chat (with tool calling), embeddings, model list, health probe |
| Authentication | `brain/auth.py` | signed session cookie, bearer token, basic auth, login lock-out |
| Plug-in contracts | `brain/providers/__init__.py` | `CodeGraph`, `DocGraph`, provider loading by name |
| Code engine provider | `brain/providers/codebase_memory.py` | indexing, hybrid search, graph expansion, annotations, `read`/`grep`/`files`, UI graphs |
| Document engine provider | `brain/providers/lightrag.py` | LightRAG child process, documents, retrieval without chat calls, UI graph |
| Document converter | `brain/providers/convert.py` | every document format → Markdown (or `.textpack` = Markdown + images) |
| Prompt analysis | `brain/query.py` | stop-words, ranked key terms, variants, concepts, language |
| Code vectors | `brain/codevec.py` | multilingual code vector index with the corporate embedding model |
| Search | `brain/search.py` | three-source search, relevance pipeline, Markdown rendering, evidence |
| Agents | `brain/agents.py` | ask, enhance, project guide, query expansion, the shared tool loop and its tools (also used by MCP and REST) |
| Requirements writer | `brain/srs.py` | SRS generation from editable formats |
| Repositories | `brain/repos.py` | registry, sets, git, sync, branch overlays, index state |
| Branch drift | `brain/drift.py` | branch vs. `main` analysis with recommendations |
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
   code model), **Start document graph engine** (spawns `lightrag-server` and waits for `/health`) and **Check
   corporate API** (one chat call and one embedding call; reports the real embedding size).
4. When the code engine is ready and `BRAIN_SYNC_ON_START=true`, every repository is cloned or updated and
   indexed (incrementally), and its multilingual code vectors are updated.
5. `/api/status` reports `ready: true` when both engines and the corporate API are ready, and the log prints
   `READY`. The UI answers from the first second and shows every job with its progress and errors.
6. If `BRAIN_SYNC_INTERVAL_MINUTES` is above 0, all repositories are updated again at that interval.

### 3.2 Search (no chat call)
1. Prompt analysis: stop-words out, key terms ranked, variants and concepts built (`brain/query.py`).
2. In parallel for the repositories in scope: code engine search (BM25 + its local code vectors, fused by
   reciprocal rank), the multilingual code vector index, and LightRAG `/query/data` with the key terms and
   concepts supplied as keywords (so LightRAG makes no chat call).
3. Exact names: identifiers and file paths written in the question find their symbols directly.
4. Document-to-code bridge: entity names from the document results become extra code-search terms.
5. Code-graph expansion: callers, callees and parents of the best hits join the candidates.
6. Re-ranking by meaning with the corporate embedding model.
7. Named symbols first, repository balance, source lines, and graph annotations (signature, callers, callees,
   parents) per hit; rendered for agents at a detail level (brief, normal, full).

Details: [05-SEARCH-ASK-ENHANCE.md](05-SEARCH-ASK-ENHANCE.md).

### 3.3 Ask and enhance
Prompt analysis → one short model call for extra search terms → the search above seeds the conversation → the
model may call read-only tools for at most `MAX_STEPS` rounds within `TIMEOUT` → final answer or enhanced prompt.
Enhance also runs a branch-drift check when a branch is given. Fallbacks: a gateway without tool calling gets one
grounded call; an unreachable model returns the search results (ask) or a deterministic prompt (enhance).

The project guide (Learn page) is the same loop with the architecture overview of every repository in scope added
to the material.

### 3.4 Requirements writer
Evidence (search + architecture overview of every repository + documents) → the model plans the capabilities →
each capability is written with its own search → the other sections are written from the plan → IDs numbered,
traceability appendix added, saved under `data/srs/output/`. Details: [17-REQUIREMENTS-WRITER.md](17-REQUIREMENTS-WRITER.md).

### 3.5 Repository update
A webhook, a button, the CLI, MCP `sync_repo`, start-up or the interval calls `repos.request_sync`, which merges
requests for the same repository within `BRAIN_WEBHOOK_DEBOUNCE_SECONDS` into one job. The job brings the
checkout to the tracked branch (server-managed clone: `fetch` + `checkout -B` + `reset --hard`; local checkout:
`pull --ff-only` only when clean and on the tracked branch), runs the code engine's incremental index, updates
the multilingual code vectors of changed symbols, and records the indexed commit in `data/state.json`.

### 3.6 Document upload
UI or REST multipart upload → the original is kept in `data/originals/` → the file is converted to Markdown
(`data/converted/<file>.md` keeps a copy) → sent to LightRAG as `<file>.md`, or as `<file>.textpack` when it has
pictures → LightRAG chunks it along headings, extracts entities and relations with the chat model, describes
pictures with the vision model and embeds everything → status on the **Documents** page moves from *pending* to
*processing* to *processed* (or *failed* with the reason).

## 4. Storage

Everything lives under `BRAIN_DATA_DIR` (default `data/` in the install folder).

| Path | Contents | Safe to delete? |
|---|---|---|
| `cbm/<project>.db` | code graph, BM25 index and local code vectors per repository or branch overlay | yes: rebuilt by the next sync |
| `codevec/<project>.npz` | multilingual code vectors (int8) per repository or overlay | yes: rebuilt by the next sync (one embedding pass) |
| `repos/<name>/` | server-managed clones | yes: cloned again |
| `worktrees/<repo>--<branch>/` | branch overlay checkouts | remove overlays in the UI first |
| `lightrag/` | document graph, vectors, key-value stores, LightRAG's LLM cache | **no**: documents would have to be uploaded again |
| `documents/` | LightRAG's input files | no |
| `originals/` | uploaded files exactly as received | keep: needed to rebuild the document graph |
| `converted/` | the Markdown each document was converted to | yes (the *Markdown* preview disappears) |
| `srs/templates/`, `srs/output/` | requirements formats and written specifications | keep |
| `state.json` | indexed commit per repository, branch overlays | yes |
| `logs/` | `server.log`, `lightrag.log`, `codebase-memory.log` | yes |
| `.secret_key` | cookie signing key when `BRAIN_SECRET_KEY` is empty | yes (everyone is logged out) |

A backup is a copy of `data/`, `.env` and `repos.json`.

## 5. Folder layout
```
brain.py  brain.cmd  brain.sh        CLI and launchers (the launchers use .venv)
setup.ps1  setup.sh                  offline installers
requirements.txt  .env.example  repos.example.json
README.md  INSTALL.html
wheels/                              every Python package for Python 3.13, Windows x64 and Linux x86-64
bin/                                 codebase-memory-mcp archives + SHA256SUMS (setup unpacks bin/windows or bin/linux)
vendor/tiktoken_cache/               tokenizer files LightRAG needs offline
brain/                               the server
  providers/                         codebase_memory.py, lightrag.py, convert.py
  ui/                                index.html, app.js, style.css, vendor/force-graph.min.js
integrations/                        AGENTS.brain.md, claude-code/brain-enhance.md
tests/                               mock_openai.py, smoke_test.py, test_static.py
tools/                               gen_config.py (generates .env.example and docs/03-CONFIGURATION.md)
docs/                                this documentation and decisions/
```
Created at run time: `.venv/`, `.env`, `repos.json`, `data/`.

## 6. Design principles
1. **Reuse ready engines.** codebase-memory-mcp and LightRAG do the heavy work; AI-BRAIN is about 5,300 lines of
   Python plus a 670-line UI script that connect them, rank results and present them.
2. **One of everything.** One process, one port, one settings schema, one configuration file, one job mechanism,
   one search used by every function.
3. **Degrade, never block.** Every model step has a fallback; every long step is a background job with visible
   progress and errors; engines are supervised and can be restarted from the UI.
4. **Interfaces at the seams.** Engine-specific code lives only in `brain/providers/`.
5. **Local state only.** SQLite and plain files; a backup is a folder copy.
6. **Evidence first.** Every answer, prompt and specification is built from search results that are shown with it.
