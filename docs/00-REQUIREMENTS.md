# 00 - Requirements and traceability

This document lists every requirement AI-BRAIN is built to, where each one is implemented and how it is verified.
"End-to-end test" means `tests/smoke_test.py` against a running server; "static test" means `tests/test_static.py`
(both described in [15-TESTING.md](15-TESTING.md)).

## Goal

The simplest, cleanest and smallest knowledge base that gives people and AI agents the code, the code's meaning and
the business documents of an organisation together, in an **air-gapped corporate network** whose only AI service is
an **OpenAI-compatible API reached with a key and a URL**.

## Requirements

### Environment

| # | Requirement | Where it is met | Verified by |
|---|---|---|---|
| R1 | Fully offline. The only AI service is an OpenAI-compatible corporate API (key + URL). | `BRAIN_LLM_BASE_URL`, `BRAIN_LLM_API_KEY` ([03](03-CONFIGURATION.md)). `brain/llm.py` is the server's only AI client and LightRAG receives the same values. The code engine makes no network calls. Packages, engine binaries and tokenizer files ship in the folder ([14](14-OFFLINE-PACKAGING.md)). | end-to-end test against a local mock gateway; `brain doctor` |
| R2 | Installation without internet; one Python version: 3.13; no preparation step. | `wheels/` holds every package for Python 3.13 on Windows and Linux; setup installs with `pip --no-index`; `brain.py` and setup refuse other versions. [ADR-011](decisions/ADR-011-python-version.md), [ADR-014](decisions/ADR-014-offline-packaging.md) | offline install on Windows 11 with Python 3.13.16; static test "wheels are for Python 3.13 only" |
| R3 | When the server starts, the code graph, the document graph and the agents are ready without manual steps. | `brain/server.py` `boot()`: starts both engines, probes the corporate API, syncs every repository; `/api/status` reports `ready`; the log prints `READY`. | end-to-end test "system is ready" |
| R4 | Every value (timeouts, models, GitLab/TFS addresses and tokens, LightRAG `LLM_TIMEOUT`, engine variables) is adjustable from the UI and from `.env`. | One schema in `brain/settings.py`; the UI edits the same `.env`; `LIGHTRAG__NAME` / `CBM__NAME` pass any engine variable through; another file via `BRAIN_CONFIG_FILE`. [ADR-004](decisions/ADR-004-configuration.md) | static tests (generated reference up to date, validation, pass-through, LightRAG timeouts); end-to-end settings round trip |

### Knowledge

| # | Requirement | Where it is met | Verified by |
|---|---|---|---|
| R5 | A code graph from a ready-made engine, including code vectors. | codebase-memory-mcp 0.11 (native binary: tree-sitter graph, BM25, bundled code embeddings), `brain/providers/codebase_memory.py`. [ADR-001](decisions/ADR-001-code-graph-engine.md) | end-to-end test "search finds code" |
| R6 | A document graph built with LightRAG. | lightrag-hku 1.5.7 server as a managed child process, `brain/providers/lightrag.py`. [ADR-002](decisions/ADR-002-document-graph-lightrag.md) | end-to-end test "document processed by LightRAG" |
| R7 | Semantic search over code (a vector index of code) that also works across Turkish and English; the choice of engine compared with graphify. | engine's local code vectors + multilingual code vector index (`brain/codevec.py`); *Semantic code* scope. [ADR-020](decisions/ADR-020-semantic-code-search.md), [18](18-ENGINE-COMPARISON.md) | end-to-end test "semantic scope", "code vectors built" |
| R8 | Every document is converted to Markdown before it goes to LightRAG. | `brain/providers/convert.py` `to_markdown()`, `data/converted/`, *Markdown* preview. [ADR-015](decisions/ADR-015-rich-documents.md), [ADR-019](decisions/ADR-019-everything-to-markdown.md) | static tests (Word, HTML, CSV, code, binary rejected); end-to-end preview |
| R9 | Any human language (at least Turkish and English) and any programming language. | Unicode prompt analysis with Turkish and English stop-words and suffix variants; agents answer in the question's language; multilingual embeddings; `LIGHTRAG_SUMMARY_LANGUAGE`; 150+ programming languages in the code engine. | end-to-end test "Turkish document search"; static prompt-analysis tests |

### Use

| # | Requirement | Where it is met | Verified by |
|---|---|---|---|
| R10 | **Search** over code and documents without any LLM call. | `brain/search.py` (`POST /api/search`, MCP `search`, `brain search`). [ADR-006](decisions/ADR-006-search-without-llm.md) | end-to-end tests "search finds code / documents" |
| R11 | **Enhance prompt**: an agent with its own system prompt that prepares a prompt for any AI coding agent. | `brain/agents.py` `ENHANCE_SYSTEM`, `enhance()` (`POST /api/enhance`, MCP `enhance_prompt`). [ADR-007](decisions/ADR-007-agents.md), [ADR-022](decisions/ADR-022-prompt-design.md) | end-to-end test "enhance agent returns a prompt" |
| R12 | **Ask**: an agent that searches the knowledge base and returns an answer. | `brain/agents.py` `ASK_SYSTEM`, `ask()` (`POST /api/ask`, MCP `ask`). [ADR-007](decisions/ADR-007-agents.md), [ADR-022](decisions/ADR-022-prompt-design.md) | end-to-end tests "ask answers", "ask used tools" |
| R13 | **Requirements writer**: a page that writes a Software Requirements Specification from code and documents, in plain language, following an editable format. | `brain/srs.py`, UI *Requirements*, `/api/srs*`, MCP `write_requirements`. [17](17-REQUIREMENTS-WRITER.md), [ADR-021](decisions/ADR-021-requirements-writer.md) | static tests (format parsing, numbering); end-to-end "specification written" |
| R14 | Before search, ask and enhance run, the stop-words and the most important words of the prompt are extracted and drive the process. | `brain/query.py`; used by search and every agent; `POST /api/analyze`; live chips in the UI. [ADR-016](decisions/ADR-016-prompt-analysis.md) | static tests (stop-words, ranking, variants, language) |
| R15 | Search, ask and enhance return the most related results. | Relevance pipeline: model query expansion (agents), document-to-code bridge, code-graph expansion, semantic re-ranking with the multilingual embedding model. [ADR-017](decisions/ADR-017-relevance-pipeline.md) | end-to-end tests (pipeline stages, graph expansion, Turkish search) |
| R16 | Search, ask, enhance and the requirements writer use the code graph, the code vectors and the document graph together. | One search with three sources; per-hit `matched`, per-source `sources` counts. [ADR-023](decisions/ADR-023-three-sources-ai-first.md), [05](05-SEARCH-ASK-ENHANCE.md) | end-to-end tests "sources counted", "graph expansion" |
| R17 | The chat model can be chosen per request from the models the API offers (combobox in Ask, Enhance and Requirements). | `GET /api/models`, model comboboxes, `model` in REST and MCP. | end-to-end tests "models listed", "answer names the chosen model" |
| R18 | Everything is usable by any AI agent (Claude Code, opencode, pi and others) over REST and MCP, and agents can use AI-BRAIN instead of read / grep / glob. | `brain/server.py` (REST), `brain/mcp.py` (MCP), tools `symbol`, `outline`, `read`, `grep`, `files`, `trace`, `overview`; self-explaining results; `brain connect`; `integrations/`. [07](07-MCP-AND-AGENTS.md), [ADR-012](decisions/ADR-012-mcp-transport.md) | end-to-end MCP tests (initialize, tools/list, search, symbol, read, grep, files) |
| R28 | AI agents using MCP spend as few tokens as possible, and get better search, grep, glob and read than their local tools. | Short tool list; exact tools `symbol`, `outline`, `read`, `grep` (files / matches / full), `files`, `overview`; search detail levels; answers bounded by `BRAIN_TOOL_MAX_TOKENS` and stripped of engine paging fields; identifiers and file paths in a question ranked first; repeated agent tool calls answered with a note; token usage reported per run. [07](07-MCP-AND-AGENTS.md) §2, [ADR-024](decisions/ADR-024-token-economy.md) | end-to-end tests (compact tool list, outline, read without repo, grep mode=files, qualified symbol, brief smaller than full, identifier ranked first) |
| R29 | People can explore a project, learn what it does, and use AI-BRAIN for research while coding. | UI *Learn a project* (structure without a model, a written project guide), `POST /api/guide`, `brain guide`, *Ask about this* in the code graph. [05](05-SEARCH-ASK-ENHANCE.md) §7b, [11](11-UI.md), [ADR-025](decisions/ADR-025-learning-a-project.md) | end-to-end tests (overview, project guide with token usage) |

### Repositories

| # | Requirement | Where it is met | Verified by |
|---|---|---|---|
| R19 | Single repository and multiple repositories; repositories grouped in sets; every request targets one repository or a set, and a set covers all of its codebases. | `repos.json` with `sets`; scope combobox (`target=repo:<name>` / `set:<name>`); repository balance in results; agents told to cover every repository. [04](04-REPOSITORIES-AND-SETS.md), [ADR-018](decisions/ADR-018-repositories-webhooks-sets.md) | end-to-end tests (set scope, single-repository scope, balance, unknown set reported) |
| R20 | GitLab and TFS webhooks update the code graph when something is merged into the tracked branch (`main`); the GitLab and TFS servers have configurable corporate URLs. | `brain/webhooks.py`, `brain/repos.py`; `BRAIN_GITLAB_URL`, `BRAIN_TFS_URL` and `gitlab:` / `tfs:` shorthands. [09](09-WEBHOOKS.md), [ADR-009](decisions/ADR-009-webhooks-and-sync.md) | end-to-end webhook tests (merge accepted, merged code searchable, other branch ignored, wrong secret rejected); static shorthand and credential tests |
| R21 | Each repository has its own webhook; repository-related settings are on the Repositories page. | `POST /webhooks/repo/<name>` with a per-repository secret; Repositories page. [ADR-018](decisions/ADR-018-repositories-webhooks-sets.md) | end-to-end tests (own GitLab and TFS hooks); static tests (secret generated and kept) |
| R22 | Developers work on branches while the graph follows `main`: the system detects the drift and recommends a solution, also where it cannot fix the situation itself. | `brain/drift.py` (`POST /api/drift`, MCP `check_branch`, `brain drift`), branch overlays, enhance adds branch notes. [10](10-BRANCH-DRIFT.md), [ADR-010](decisions/ADR-010-branch-drift.md) | end-to-end tests (behind count, conflict-risk file, recommendations, unpushed branch, overlay index/search/remove) |
| R30 | Every pull of the tracked branch updates the repository's graph automatically, and every update pulls the repository immediately. | `repos.watch_local()` (local checkouts, `BRAIN_WATCH_LOCAL_SECONDS`), `brain hook` (git hooks after `git pull`), `repos.request_sync()` (starts at once; a request during an update makes it run once more). [04](04-REPOSITORIES-AND-SETS.md) §4, [ADR-009](decisions/ADR-009-webhooks-and-sync.md) | end-to-end test "a pull of the tracked branch in a local checkout is indexed automatically"; hook tried with a real `git pull` |

### UI and access

| # | Requirement | Where it is met | Verified by |
|---|---|---|---|
| R23 | A user-friendly UI with both graphs, search, ask, enhance and requirements, document upload and removal, statuses, progress and errors; related things together and as much detail as possible. | `brain/ui/` ([11](11-UI.md)); grouped menu; one result layout with source chips, graph context and evidence panels; every long action is a job with progress (`brain/jobs.py`). [ADR-013](decisions/ADR-013-ui.md) | browser check; job endpoints in the end-to-end test |
| R24 | The UI is reachable from any IP address with a user name and password taken from the configuration. | `BRAIN_HOST=0.0.0.0`, `BRAIN_UI_USER`, `BRAIN_UI_PASSWORD`, `brain/auth.py`, optional HTTPS. [ADR-008](decisions/ADR-008-authentication.md) | end-to-end authentication tests |

### Engineering

| # | Requirement | Where it is met | Verified by |
|---|---|---|---|
| R25 | Plug-and-play engines: the code graph engine and LightRAG can be replaced. | `brain/providers/__init__.py` interfaces, `BRAIN_CODE_PROVIDER`, `BRAIN_DOC_PROVIDER`. [08](08-PLUGINS.md), [ADR-005](decisions/ADR-005-plugin-providers.md) | static test "providers load via registry" |
| R26 | A Markdown document for every decision, fact and important detail; README.md; INSTALL.html for Windows and Linux; everything done by executable scripts. | `docs/`, `docs/decisions/`, `README.md`, `INSTALL.html`, `setup.ps1`, `setup.sh`, `brain.cmd`, `brain.sh`, `brain.py`. | static tests (every setting, route and MCP tool documented; README links resolve; decision records present) |
| R27 | The simplest, smallest and cleanest solution. | Two ready-made engines, one process, one port, one settings schema, no database server, no frontend build. [01](01-ARCHITECTURE.md) §6 | review in [19](19-REVIEW.md) |

## Constraints that follow from the goal

- **No internet at run time.** No package or model downloads; LightRAG never downloads remote images from
  documents (`NATIVE_MD_IMAGE_DOWNLOAD_ENABLED=false`); tokenizer files ship in `vendor/tiktoken_cache`.
- **No database server.** Graphs, vectors and state are files under `data/`.
- **One process and one port** for people, agents and git servers; LightRAG listens on 127.0.0.1 only.
- **Few dependencies.** `lightrag-hku[api]` brings what the server needs (FastAPI, uvicorn, httpx, NumPy,
  python-docx). `requirements.txt` adds the document converters pdfplumber and pypdfium2 and names python-pptx
  and openpyxl explicitly. No ML runtime is installed.
