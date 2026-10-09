# 07 - MCP and AI agents (Claude Code, opencode, pi and others)

AI-BRAIN is an MCP server at **`<BRAIN_PUBLIC_URL>/mcp`**: Streamable HTTP transport with JSON responses,
protocol versions 2025-06-18, 2025-03-26 and 2024-11-05. Authentication: `Authorization: Bearer <BRAIN_API_TOKEN>`.
Nothing is installed on developer machines. `brain connect` prints every snippet below with the real URL and token;
the UI Overview page shows them too.

## 1. Tools

Scope arguments, available on most tools: `set` (a set name; the request then covers all its repositories),
`repos` (a list of repository names), `branch` (uses a branch overlay when one exists).

| Tool | Arguments | Purpose |
|---|---|---|
| `search` | `query`, `scope` (`all`, `code`, `semantic`, `docs`), `k`, scope | first stop for research: code graph, code vectors and documents, no model call; each hit with location, signature, callers, callees and why it matched |
| `ask` | `question`, `model`, scope | a grounded answer with citations (uses the model) |
| `enhance_prompt` | `prompt`, `repo`, `base_commit`, `changed_files`, `model`, scope | an implementation-ready prompt; with branch facts also branch-drift warnings |
| `write_requirements` | `topic`, `template`, `language`, `model`, `set`, `repos` | a Software Requirements Specification in plain language (slow: several model calls) |
| `check_branch` | `repo`, `branch`, `base_commit`, `head_commit`, `changed_files` | branch drift report with recommendations |
| `symbol` | `name`, scope | definition, source, callers and callees |
| `trace` | `function_name`, `repo`, `direction` (`inbound`, `outbound`, `both`), `depth` (3), scope | call chains for impact analysis |
| `snippet` | `qualified_name`, `repo`, scope | full source of a symbol |
| `read` | `repo`, `path`, `start`, `end` | numbered lines of any indexed file (at most 400); use instead of reading files locally |
| `grep` | `pattern`, `regex`, `file_pattern`, scope | exact text or regex over the indexed code, ranked by the graph; use instead of grep / rg |
| `files` | `pattern` (glob), scope | indexed file paths; use instead of glob |
| `list_repos` | | repositories, sets, indexed commits, branch overlays (without secrets) |
| `list_documents` | | documents and their processing status |
| `add_note` | `name`, `text` | store a finding or decision as a new document |
| `sync_repo` | `repo` (empty = all) | update and re-index in the background |

The server's `initialize` answer carries a short instruction for the agent: call `search` before grep, glob or
read; `enhance_prompt` to plan a task; `check_branch` when not on `main`.

## 2. Why agents should use AI-BRAIN instead of read, grep and glob

| Local habit | AI-BRAIN tool | What the agent gains |
|---|---|---|
| `grep` / `rg` to find code | `search`, `grep` | results from the code graph, the code vectors and the documents, ranked by meaning; each hit has location, signature, callers, callees and the reason it matched; works across all repositories of a set and in Turkish or English |
| `glob` | `files` | the file list of one repository or a whole set, without a checkout |
| `read` | `snippet`, `read` | exactly the symbol or line range needed, with the file's total length |
| reading many files to follow a flow | `trace`, `symbol` | the call chain, callers and callees in one call |
| asking the user about business rules | `search` with `scope=docs`, `ask` | rules, decisions and facts from the documents, with their sources |
| planning a change | `enhance_prompt` | task, context, impact, plan, acceptance criteria, out of scope |

One `search` usually replaces several rounds of grep and read; the agent opens local files only to edit them,
after checking AI-BRAIN's locations in its working copy.

## 3. Claude Code
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

## 4. opencode
In `~/.config/opencode/opencode.json` (or the project's `opencode.json`):
```json
{"mcp": {"brain": {"type": "remote", "url": "http://brain.corp.local:8765/mcp", "enabled": true, "oauth": false,
                "headers": {"Authorization": "Bearer <BRAIN_API_TOKEN>"}}}}
```
The tools appear as `brain_search`, `brain_enhance_prompt` and so on. Append `integrations/AGENTS.brain.md` to
`AGENTS.md`. In an air-gapped network also set `OPENCODE_DISABLE_MODELS_FETCH=1`.

## 5. pi, scripts and other agents without MCP
They use the REST API ([06-API.md](06-API.md)) with the same token. Put `integrations/AGENTS.brain.md` into the
project's `AGENTS.md` and export `BRAIN_URL` and `BRAIN_API_TOKEN` in the shell that runs the agent; the file
contains ready `curl` commands for search, files, read and enhance. The same works in CI jobs.

## 6. Other MCP clients
Cursor, Continue, VS Code / Copilot, Windsurf, Zed, Goose and others: add a remote (HTTP) MCP server with the URL
and the `Authorization` header. A client that supports only stdio can use a generic stdio-to-HTTP bridge from the
internal package mirror; the server needs nothing extra.

## 7. Recommended agent workflow
1. A task arrives → `enhance_prompt` (with branch facts when not on `main`).
2. Research → `search`, then `symbol`, `trace`, `snippet`, `read`, `grep`, `files` for details.
3. Not on `main` → `check_branch` and follow its recommendations.
4. Learned something lasting → `add_note`.

## 8. Checking a connection by hand
```bash
curl -s -H "Authorization: Bearer $BRAIN_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' http://brain.corp.local:8765/mcp | jq '.result.tools[].name'
```
