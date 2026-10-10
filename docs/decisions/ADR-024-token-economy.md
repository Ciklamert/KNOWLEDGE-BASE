# ADR-024 - Token economy for AI agents over MCP

**Status:** accepted · **Requirements:** R28, R18

## Context
An agent that uses AI-BRAIN through MCP pays tokens twice: for the tool list, which is part of every turn, and for
every answer it reads. Search results with the source of every hit, raw engine output with paging fields and a long
tool list would make each question expensive, and an agent should not need several calls to read one function or
one file.

## Decision
1. **A short tool list.** Terse descriptions; the scope arguments (`repo`, `set`, `branch`) are explained once in
   the server instructions instead of in every schema; `symbol` also returns the source, so no separate snippet
   tool is needed. 16 tools in about 5,400 characters (≈ 1,340 tokens).
2. **Exact tools for exact questions.** `symbol` (location, signature, source when short, callers, callees,
   parents), `outline` (a file's declarations with line ranges), `read` (a line range; the repository is found when
   not given), `grep` (`mode=files` to only locate, `path` to limit to a folder), `files`, `overview`.
3. **Detail levels for search** (`BRAIN_SEARCH_DETAIL`, `detail` per request): `brief` (no source), `normal` (the
   source of the 3 best hits), `full`.
4. **Bounded, clean answers.** Tool answers are cut at `BRAIN_TOOL_MAX_TOKENS` with a note on how to get the rest;
   the code engine's paging and timing fields are removed; repositories without matches are left out.
5. **Named things first.** Identifiers and file paths written in the question find their symbols directly and are
   ranked first.
6. **Agents on the server** do not repeat themselves: an identical tool call in the same run returns a short note;
   every run reports its model calls and tokens.
7. One implementation: MCP, REST and the server-side agents all call `agents.Context.run_tool`.

## Alternatives
| Option | Why not |
|---|---|
| fewer, larger tools (one `code` tool with a mode) | a vaguer schema the model must read every turn, and more wrong calls |
| always return full source | simple, but most of it is never used by the agent |
| summarise results with a model | a chat call per search; slow; the summary can lose the exact location |

## Consequences
Typical answers: `symbol` ≈ 100-600 tokens, `outline` ≈ 100-500, `grep mode=files` ≈ 50-200, `search` ≈ 500
(brief) / 1,000 (normal) / 1,700 (full) for eight hits. Agents read whole files only to edit them.
