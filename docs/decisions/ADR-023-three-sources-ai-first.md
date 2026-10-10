# ADR-023 - Three sources in every result; results designed for AI agents first

**Status:** accepted · **Requirements:** R16, R18, R23

## Decision
- One search serves search, ask, enhance and the requirements writer, and always combines the **code graph** (BM25,
  graph expansion through callers, callees and parents, relations), the **code vectors** (local and multilingual) and
  the **document graph** (passages, entities, facts; their names also search the code).
- Every code hit **explains itself**: location, qualified name, signature, callers, callees, parents, which sources
  found it (`matched`), similarity and source lines. The response counts hits per source (`sources`).
- **AI agents get what they would otherwise collect with read, grep and glob**: `read` (line ranges), `grep`
  (graph-ranked text and regex), `files` (glob over the index), plus `symbol`, `outline`, `trace` and `overview`
  (ADR-024 keeps their answers small).
  Rendered results end with next-step hints. Agents need no local checkout and can work across every repository of a
  set.
- **People see the same evidence**: one result layout everywhere, and an *Evidence used* panel under every agent
  output.

## Alternatives
Separate code-search and document-search pages (people would have to combine them); returning only locations (agents
would still open every file); exposing the raw engine tools only (no fusion, no ranking).

## Consequences
Answers can be checked against their evidence; agents need far fewer tool calls and tokens; the graph contributes code
that shares no words with the question.
