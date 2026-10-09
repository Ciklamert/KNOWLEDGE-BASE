# AI-BRAIN

AI-BRAIN is a knowledge base for software teams in an air-gapped corporate network. It keeps three indexes:

- a **code graph** of every configured repository (symbols, calls, inheritance, routes, imports),
- **code vectors** that find code by meaning, also when the question is in Turkish and the code is in English,
- a **document graph** of the business documents (rules, specifications, decisions, procedures).

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
 │  ask agent ──────────────┤   multilingual code vectors  ─► data/codevec (corporate embeddings)│
 │  enhance-prompt agent ───┤                                                                  │
 │  requirements writer ────┴─► document graph ─────────────► LightRAG (child on 127.0.0.1)     │
 │  branch drift check · branch overlays · webhook-driven updates of the tracked branch         │
 └───────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                             ▼
                       corporate OpenAI-compatible API (chat, embeddings, optional vision)
```

## What it does

| Function | What happens | Model calls |
|---|---|---|
| **Search** | Analyses the prompt (stop-words out, key terms ranked), searches the code graph, both code vector indexes and the document graph, connects business terms from documents to code, adds callers and callees of the best hits, and re-ranks everything by meaning. | none (embedding calls only) |
| **Ask** | An agent researches with read-only tools and answers in the question's language, citing code (`repo/path:line`) and documents. | expansion + a few |
| **Enhance prompt** | An agent turns a short request into an implementation-ready prompt for a coding agent: task, context, business rules, impact, plan, acceptance criteria, out of scope, open questions, branch warnings. | expansion + a few |
| **Requirements writer** | Writes a Software Requirements Specification in plain language from code and documents, following an editable Markdown format. | several per capability |
| **Code tools for agents** | `read`, `grep`, `files`, `symbol`, `trace`, `snippet`: agents work across all repositories without a local checkout. | none |
| **Branch drift** | Compares a developer's branch with the indexed `main` and recommends what to do (rebase, trust local files, index the branch). | none |

Every function is available in the **web UI**, the **REST API** and **MCP**. The UI also shows both graphs, uploads
and removes documents, manages repositories, sets and webhooks, edits every setting, and shows the state,
progress and errors of every background job. A merge into a repository's tracked branch on **GitLab** or
**TFS / Azure DevOps Server** updates its code graph through a webhook.

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
| `brain doctor` | check Python, configuration, corporate API, code engine, LightRAG, packages, git and repositories |
| `brain sync [REPO]` | update and re-index one repository, or all of them |
| `brain search "…" [--scope all\|code\|semantic\|docs] [--set S] [--branch B]` | search from a terminal |
| `brain ask "…" [--set S] [--branch B]` | ask a question |
| `brain enhance "…" [--set S] [--path .] [--repo R]` | enhance a prompt; `--path` adds branch-drift notes from a local checkout |
| `brain drift [PATH] [--repo R] [--main main]` | compare the branch checked out in PATH with the indexed `main` |
| `brain connect [claude\|opencode\|pi\|all]` | print ready-to-paste agent configuration |
| `brain version` | print the version |

## Requirements at a glance

- Windows 10/11 or Windows Server 2019+ (x64), or Linux x86-64 with glibc 2.17+.
- Python 3.13 and git. All Python packages are bundled in `wheels/`.
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
| [docs/18-ENGINE-COMPARISON.md](docs/18-ENGINE-COMPARISON.md) | codebase-memory-mcp compared with graphify and other engines |
| [docs/19-REVIEW.md](docs/19-REVIEW.md) | review of the whole system, known limits and rating |
| [docs/decisions/](docs/decisions/README.md) | architecture decision records ADR-001 to ADR-023 |
