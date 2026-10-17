# 07 - MCP and AI agents (Claude Code, opencode, pi and others)

AI-BRAIN is an MCP server at **`<BRAIN_PUBLIC_URL>/mcp`**: Streamable HTTP transport with JSON responses,
protocol versions 2025-06-18, 2025-03-26 and 2024-11-05. Authentication: `Authorization: Bearer <BRAIN_API_TOKEN>`.
Nothing is installed on developer machines. `brain connect` prints every snippet below with the real URL and token;
the UI Overview page shows them too.

## 1. Tools

Scope arguments are explained once, in the server's instructions, instead of in every tool schema: `repo` = one
repository, `set` = a repository set (default: all repositories), `branch` = use a branch overlay when one is
indexed (on `search`, `symbol`, `ask`, `enhance_prompt`).

| Tool | Arguments | Purpose | Typical answer size |
|---|---|---|---|
| `symbol` | `name` (short or qualified), `source` (`auto`, `full`, `none`) | location, signature, docstring, source (whole when 60 lines or less, else the first 40), callers, callees, parents, tests, other symbols with the same name | 100-600 tokens |
| `outline` | `path` | declarations of one file with their line ranges: read this before reading a file | 100-500 tokens |
| `read` | `path`, `start`, `end` | numbered lines (at most 400); without `repo` the first repository that has the file is used | as many lines as asked |
| `grep` | `pattern`, `regex`, `mode` (`files`, `matches`, `full`), `file_pattern`, `path` (folder) | exact text or regex, ranked by the code graph; `mode=files` only locates | 50-600 tokens |
| `files` | `pattern` (glob such as `**/*.sql`) | indexed file paths (at most 300; says when more match) | small |
| `trace` | `function_name`, `direction` (`inbound`, `outbound`, `both`), `depth` (3) | call chains for impact analysis | at most `BRAIN_TOOL_MAX_TOKENS` |
| `impact` | `files` and/or `symbols`, `depth` (3), `branch` | what a change reaches, no model call: the changed symbols, the code that depends on them (callers, subclasses, overrides), entry points (routes), the tests to run and the business rules that name the code | small |
| `overview` | `repo`, `path` (folder), `aspects` (`overview`, `structure`, `routes`, `hotspots`, `entry_points`, `dependencies`, `layers`, `file_tree`) | a repository's structure | at most `BRAIN_TOOL_MAX_TOKENS` |
| `search` | `query`, `scope` (`all`, `code`, `semantic`, `docs`), `detail` (`brief`, `normal`, `full`), `k` | ranked results from the code graph, the code vectors and the documents, no model call; each hit with location, signature, callers, callees and why it matched | brief ≈ 500, normal ≈ 1,000, full ≈ 1,700 tokens |
| `ask` | `question`, `model` | a grounded answer with citations, researched by a server-side agent | the answer only |
| `enhance_prompt` | `prompt` (any kind: bug fix, new feature, refactor ...), `base_commit`, `changed_files`, `model` | an implementation-ready prompt; with branch facts also branch-drift warnings | the prompt only |
| `write_requirements` | `topic` (system requirements, a new idea or a topic of the current system), `template` (one of the user's formats), `language`, `model` | a Software Requirements Specification in plain language in the user's format (slow) | a document |
| `check_branch` | `repo`, `branch`, `base_commit`, `head_commit`, `changed_files` | branch drift report with recommendations | small |
| `list_repos` | | one line per repository: provider, branch, sets, indexed commit, symbols, overlays, errors | small |
| `doc` | `mode` (`list`, `outline`, `unit`, `refs`, `define`, `obligations`, `impact`), `document`, `q` (a unit such as "Madde 5 (2)", "3.1", "REQ-004"; a term; an actor) | documents as trees, no model call: the documents with versions; a document's outline; one unit's text with what it refers to and what refers to it; a term's definition and where it is used; an actor's obligations, prohibitions and permissions with conditions and limits; what depends on a unit | small |
| `remember` | `type` (`decision`, `rule`, `gotcha`, `convention`), `title`, `text`, `repo`, `paths` | keep a lasting fact for every later session; searchable like a document; the same type and title replaces the older one | one line |
| `recall` | `query`, `repo`, `type` | the facts recorded earlier, newest first or ranked for the query; stale ones are marked | small |
| `sync_repo` | `repo` (empty = all) | update and re-index in the background | small |

## 2. Token economy
An agent pays tokens twice: for the tool list, which is sent with every turn, and for every answer it reads.
AI-BRAIN keeps both small:
- **A short tool list.** Terse descriptions, scope arguments explained once in the instructions: the list is about
  about 6,000 characters (≈ 1,500 tokens) for 18 tools.
- **Exact tools first.** `symbol`, `outline`, `read`, `grep` and `files` answer exact questions in a few hundred
  tokens. `ask`, `enhance_prompt` and `write_requirements` run their model calls on the server, so the agent reads
  only the result, not the research.
- **Search detail levels.** `detail=brief` lists locations, signatures, callers, callees and the reason each hit
  matched, without source; `normal` (the default, `BRAIN_SEARCH_DETAIL`) adds the source of the 3 best hits;
  `full` adds the source of every hit.
- **Bounded answers.** `trace`, `grep`, `overview`, `outline` and `symbol` are cut at `BRAIN_TOOL_MAX_TOKENS`
  (default 2,500) with a note saying how to get the rest; the code engine's paging and timing fields are removed;
  repositories without matches are left out of `grep`.
- **Named things first.** An identifier or file path written in a search (`apply_vat`, `src/billing/tax.py`) finds
  that symbol directly and ranks it first, so the agent does not page through results.

## 3. Why agents should use AI-BRAIN instead of read, grep and glob

| Local habit | AI-BRAIN tool | What the agent gains |
|---|---|---|
| `grep` / `rg` to find code | `grep`, `search` | graph-ranked matches across every repository of a set; `search` also finds code by meaning (in Turkish or English) and the business documents |
| `glob` | `files` | the file list of one repository or a set, without a checkout |
| `read` of a whole file | `outline`, then `read` of a line range | only the lines needed |
| reading files to understand a function | `symbol` | source, callers, callees and parents in one answer |
| reading many files to follow a flow | `trace` | the call chain in one answer |
| exploring an unknown repository | `overview` | languages, packages, entry points, routes, hotspots, file tree |
| asking the user about business rules | `search` with `scope=docs`, `ask` | rules, decisions and facts from the documents, with their sources |

The agent opens local files only to edit them, after checking AI-BRAIN's locations in its working copy.

## 4. Recommended agent workflow
1. A task arrives → `recall` (what earlier sessions learned), then `enhance_prompt` (with branch facts when not
   on `main`).
2. Research → `search` (`detail=brief` to scan), then `symbol`, `outline` + `read`, `grep`, `trace` for details.
3. Before and after editing → `impact` with the files or symbols you touch: what depends on them and which tests
   to run.
4. Not on `main` → `check_branch` and follow its recommendations (it also lists the tests to run).
5. Learned something the next session needs (a decision and why, a gotcha, a convention) → `remember`.

## 5. Claude Code
```bash
claude mcp add --transport http --scope user brain http://brain.corp.local:8765/mcp \
       --header "Authorization: Bearer <BRAIN_API_TOKEN>"
claude mcp list            # brain: connected
```
Per project instead, in `.mcp.json`:
```json
{"mcpServers": {"brain": {"type": "http", "url": "http://brain.corp.local:8765/mcp",
                       "headers": {"Authorization": "Bearer ${BRAIN_API_TOKEN}"}}}}
```
Optional:
- copy `integrations/claude-code/brain-enhance.md` to `~/.claude/commands/` (or `.claude/commands/` of a project)
  to get the command `/brain-enhance <request>`;
- append `integrations/AGENTS.brain.md` to `CLAUDE.md`, so Claude uses AI-BRAIN before grep, glob and read.

## 6. opencode
In `~/.config/opencode/opencode.json` (or the project's `opencode.json`):
```json
{"mcp": {"brain": {"type": "remote", "url": "http://brain.corp.local:8765/mcp", "enabled": true, "oauth": false,
                "headers": {"Authorization": "Bearer <BRAIN_API_TOKEN>"}}}}
```
The tools appear as `brain_search`, `brain_symbol` and so on. Append `integrations/AGENTS.brain.md` to `AGENTS.md`.
In an air-gapped network also set `OPENCODE_DISABLE_MODELS_FETCH=1`.

## 7. pi, scripts and other agents without MCP
They use the REST API ([06-API.md](06-API.md)) with the same token: `/api/search`, `/api/code/symbol`,
`/api/code/outline`, `/api/code/read`, `/api/code/grep`, `/api/code/files`, `/api/code/overview`. Put
`integrations/AGENTS.brain.md` into the project's `AGENTS.md` and export `BRAIN_URL` and `BRAIN_API_TOKEN` in the
shell that runs the agent; the file contains ready `curl` commands. The same works in CI jobs.

## 8. Other MCP clients
Cursor, Continue, VS Code / Copilot, Windsurf, Zed, Goose and others: add a remote (HTTP) MCP server with the URL
and the `Authorization` header. A client that supports only stdio can use a generic stdio-to-HTTP bridge from the
internal package mirror; the server needs nothing extra.

## 9. Checking a connection by hand
```bash
curl -s -H "Authorization: Bearer $BRAIN_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' http://brain.corp.local:8765/mcp | jq '.result.tools[].name'
```
