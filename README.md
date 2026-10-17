# AI-BRAIN

AI-BRAIN is a knowledge base for software teams in an air-gapped corporate network. It keeps three indexes:

- a **code graph** of every configured repository (symbols, calls, inheritance, routes, imports),
- **code vectors** that find code by meaning, also when the question is in Turkish and the code is in English,
- a **document graph** of the business documents (rules, specifications, decisions, procedures), built like the
  code graph: from the documents' structure, keywords, vectors and concepts, without a model call per chunk, so it
  is fast even on a slow corporate API.

People use it through a web UI. AI coding agents (Claude Code, opencode, pi, Cursor and others) use it through
MCP or a REST API. The only outbound connection is to the organisation's **OpenAI-compatible API**
(`/chat/completions`, `/embeddings`, `/models`) and to its git servers.

```
  AI agents (Claude Code, opencode, pi …)      browsers (login)        GitLab / TFS
        │ MCP /mcp        │ REST /api/*              │ /                  │ /webhooks/*
        ▼                 ▼                          ▼                    ▼
 ┌──────────────────── brain serve: one process, one port (default 8765) ─────────────────────┐
 │ login and tokens · background jobs with progress · settings (.env) · repositories (repos.json)│
 │                                                                                             │
 │  search (no model call) ─┬─► code graph + code vectors ─► codebase-memory-mcp (native binary)│
 │  ask agent, guide ───────┤   multilingual code vectors  ─► data/codevec (corporate embeddings)│
 │  enhance-prompt agent ───┤                                                                  │
 │  requirements writer ────┴─► document graph ─────────────► built-in engine (SQLite, no LLM)  │
 │  branch drift · overlays · updates on merge, on pull and every 24 h · live UI updates         │
 └───────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                             ▼
                       corporate OpenAI-compatible API (chat, embeddings, optional vision)
```

## What it does

| Function | What happens | Model calls |
|---|---|---|
| **Search** | Analyses the prompt (stop-words out, key terms ranked), searches the code graph, both code vector indexes and the document graph, connects business terms from documents to code, adds callers and callees of the best hits, and re-ranks everything by meaning. | none (embedding calls only) |
| **Ask** | An agent researches with read-only tools and answers in the question's language, citing code (`repo/path:line`) and documents. | expansion + a few |
| **Enhance prompt** | An agent turns any request (a bug to fix, a new feature, a change, a refactor, an investigation) into an implementation-ready prompt for a coding agent. It recognises the kind of request itself: for a bug it traces the failing path and the likely root cause, for a new feature it shows what exists today, where it fits and what to imitate. Task, what exists, analysis, business rules, impact, plan, acceptance criteria, out of scope, open questions, branch warnings. | expansion + a few |
| **Impact** | What a change reaches before and after editing: the code that depends on the changed files or symbols, the routes that lead there, the tests to run and the business rules that name the code (MCP `impact`, `POST /api/impact`, `brain impact` in CI). | none |
| **Decision memory** | Decisions, rules, gotchas and conventions that people and agents should not relearn: typed, dated, searchable like documents, replaced by topic, marked stale when their code is gone (MCP `remember` / `recall`, Documents → *Memory*). | none |
| **Document tree** | Official and technical documents parsed like code: chapters, articles, paragraphs, numbered sections and requirement IDs; cross-references, definitions, amendments; who must do what, with conditions and limits (MCP and REST `doc`, Documents → *Outline*). | none |
| **Requirements writer** | Turns system requirements, a new idea or a topic of the current system (pasted or loaded from a file) into software requirements checked against the current code and documents, with one request field and no modes; always in your organisation's own format (typed, or loaded from a Word/PDF template). | several per capability |
| **Documents** | Every upload becomes Markdown first, the MarkItDown way (PDF with tables and pictures, Word, PowerPoint, Excel, HTML, CSV, JSON, XML, RSS, notebooks, EPUB, e-mails with attachments, zip archives, images, code and text, recognised by content), is split into passages along headings and pages, and is searchable at once: keywords, concepts and links between documents. | one batched embedding pass; one vision call per picture |
| **Code tools for agents** | `symbol`, `outline`, `read`, `grep`, `files`, `trace`, `overview`: exact answers in a few hundred tokens, across all repositories, without a local checkout. | none |
| **Learn a project** | The structure of a repository (languages, packages, entry points, routes, most-connected code) and a written guide for newcomers: what it does, how it is built, main flows, where to start reading. | none / a few |
| **Branch drift** | Compares a developer's branch with the indexed `main` and recommends what to do (rebase, trust local files, index the branch). | none |

Every function is available in the **web UI**, the **REST API** and **MCP**. The UI also shows both graphs, uploads
and removes documents, manages repositories, sets and webhooks, edits every setting, and shows the state,
progress and errors of every background job, updated live. A merge into a repository's tracked branch on **GitLab** or
**TFS / Azure DevOps Server** updates its code graph through a webhook, and so does every pull of that branch (local
checkouts are watched; `brain hook` covers any other checkout). Every update pulls immediately, and every repository
is updated at least every 24 hours.

## Quick start

Windows (PowerShell, in the AI-BRAIN folder):
```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
.\brain.cmd serve
```
Linux:
```bash
./setup.sh
./brain.sh serve
```
Setup installs everything from the folder without internet access, creates `.env` and opens it so you can fill in
the six required values. Then open `http://<server>:8765`, log in, add repositories under **Repositories**, upload
documents under **Documents** and connect your agents (`brain connect`). The full guide for Windows and Linux is
**[INSTALL.html](INSTALL.html)** (same content: [docs/02-INSTALLATION.md](docs/02-INSTALLATION.md)).

## Commands

`brain` means `brain.cmd` on Windows and `./brain.sh` on Linux.

| Command | Purpose |
|---|---|
| `brain serve` | start the server: UI, REST API, MCP, webhooks, both engines and the agents |
| `brain doctor` | check Python, configuration, corporate API, code engine, SQLite full-text search, packages, git and repositories |
| `brain sync [REPO]` | update and re-index one repository, or all of them |
| `brain search "…" [--scope all\|code\|semantic\|docs] [--detail brief\|normal\|full] [--set S] [--branch B]` | search from a terminal |
| `brain ask "…" [--set S] [--branch B]` | ask a question |
| `brain enhance "…" [--set S] [--path .] [--repo R]` | enhance a prompt of any kind; `--path` adds branch-drift notes from a local checkout |
| `brain guide ["focus"] [--set S] [--repo R]` | write a project guide for newcomers |
| `brain hook [PATH] [--repo R] [--remove]` | in a checkout: every `git pull` of the tracked branch updates AI-BRAIN |
| `brain drift [PATH] [--repo R] [--main main]` | compare the branch checked out in PATH with the indexed `main` |
| `brain impact [files…] [--repo R] [--path .]` | what a change reaches and which tests to run; without files, the local branch's changed files (for CI) |
| `brain connect [claude\|opencode\|pi\|all]` | print ready-to-paste agent configuration |
| `brain version` | print the version |

## Requirements at a glance

- Windows 10/11 or Windows Server 2019+ (x64), or Linux x86-64 with glibc 2.17+.
- Python 3.13 and git. All Python packages are bundled in `wheels/` (42 wheels, about 80 MB).
- 4 CPU cores, 8 GB RAM (16 GB for large monorepos), 10 GB disk plus three times the size of the source code.
- An OpenAI-compatible chat model and embedding model reachable from the server; a vision model is optional.

## Documentation

| Document | Contents |
|---|---|
| [docs/00-REQUIREMENTS.md](docs/00-REQUIREMENTS.md) | every requirement, where it is met and how it is verified |
| [docs/01-ARCHITECTURE.md](docs/01-ARCHITECTURE.md) | components, flows, storage, folder layout, design principles |
| [docs/02-INSTALLATION.md](docs/02-INSTALLATION.md) | installation on Windows and Linux, step by step |
| [docs/03-CONFIGURATION.md](docs/03-CONFIGURATION.md) | every setting with default and meaning (generated from the code) |
| [docs/04-REPOSITORIES-AND-SETS.md](docs/04-REPOSITORIES-AND-SETS.md) | repositories, git servers, credentials, sets, updates |
| [docs/05-SEARCH-ASK-ENHANCE.md](docs/05-SEARCH-ASK-ENHANCE.md) | prompt analysis, the search pipeline, the agents and their tools |
| [docs/20-REST-API-GUIDE.md](docs/20-REST-API-GUIDE.md) | using AI-BRAIN through its REST API: authentication, jobs, recipes |
| [docs/06-API.md](docs/06-API.md) | REST API reference |
| [docs/07-MCP-AND-AGENTS.md](docs/07-MCP-AND-AGENTS.md) | MCP tools and connecting Claude Code, opencode, pi and others |
| [docs/08-PLUGINS.md](docs/08-PLUGINS.md) | replacing the code engine or the document engine |
| [docs/09-WEBHOOKS.md](docs/09-WEBHOOKS.md) | GitLab and TFS webhooks |
| [docs/10-BRANCH-DRIFT.md](docs/10-BRANCH-DRIFT.md) | working on a branch while the graph follows `main` |
| [docs/11-UI.md](docs/11-UI.md) | the web UI page by page |
| [docs/12-SECURITY.md](docs/12-SECURITY.md) | network, authentication, secrets, data |
| [docs/13-OPERATIONS.md](docs/13-OPERATIONS.md) | running, monitoring, backup, upgrade, troubleshooting |
| [docs/14-OFFLINE-PACKAGING.md](docs/14-OFFLINE-PACKAGING.md) | what the folder contains for an offline installation |
| [docs/15-TESTING.md](docs/15-TESTING.md) | static checks, end-to-end test, mock gateway, test record |
| [docs/16-CODEBASE.md](docs/16-CODEBASE.md) | every file and module with its important facts |
| [docs/17-REQUIREMENTS-WRITER.md](docs/17-REQUIREMENTS-WRITER.md) | the requirements writer and its formats |
| [docs/18-ENGINE-COMPARISON.md](docs/18-ENGINE-COMPARISON.md) | the code engine and the document engine compared with open-source alternatives |
| [docs/19-REVIEW.md](docs/19-REVIEW.md) | review of the whole system, known limits and rating |
| [docs/decisions/](docs/decisions/README.md) | architecture decision records ADR-001 to ADR-029 |
