# ADR-028 - What autonomous agents need: one-call search, impact and decision memory

**Status:** accepted · **Requirements:** R39, R40, R41

## Context
A comparison with other code and document memory systems (codebase-memory-mcp, GitNexus, Serena, claude-context,
Augment, DeepWiki, Mem0, Zep, Letta, Cognee, LightRAG) and with the published findings on agents showed three gaps
that matter most on a slow corporate API:
1. a search embedded the question and re-ranked up to 30 code candidates by embedding their text at query time:
   seconds per search on a slow gateway, up to the search timeout when it struggles;
2. "a static edge is not proof that a change is safe": agents need what a change reaches *and the tests to run*,
   not only one symbol's callers;
3. agents lose the *why* between sessions; long instruction files help little, while retrieved, current facts do.

## Decision
- **One API call per search.** The question's embedding is fetched once, shared by the code vectors, the document
  passages and the re-ranking, cached, and waited for at most `BRAIN_EMBED_BUDGET` seconds. Re-ranking uses the
  multilingual code vectors stored at indexing. On a slow gateway the search answers from keywords, the graph and
  concepts and says that meaning was skipped; the late embedding serves the next search.
- **`impact`** (MCP, REST, CLI): from the code graph alone, the changed symbols (from files or names), the code that
  depends on them up to three hops, the routes and top callers that reach them, the tests (TESTS edges and test code
  among the dependants) and the document passages that name the changed code. The branch check adds the tests to
  run for the branch's files.
- **Decision memory** (`brain/memory.py`): `remember` / `recall` store short typed facts (decision, rule, gotcha,
  convention) with repository, code paths, source and date. Each is also a small document, so search, ask and
  enhance find it. Type + title is the identity: a newer memory replaces the older (the old text stays in its
  history). After every repository update, memories whose code paths no longer exist are marked stale. `add_note`
  is replaced by `remember`.

## Alternatives
- A project wiki written by the model in the background (DeepWiki style): useful, but the most API time of all
  options on a slow gateway; not adopted.
- Agent memory platforms (Mem0, Zep/Graphiti, Letta, Cognee): built for conversation memory, with LLM extraction or a
  graph database; the needed part is a few typed facts tied to code.
- Embedding every candidate at query time (the previous design): one batched API call per search, slow on the
  corporate gateway, and it sent code text even with `BRAIN_CODE_VECTORS=local`.

## Consequences
A search costs at most one embedding call and never waits long; with `BRAIN_CODE_VECTORS=local` no code text leaves
the server at query time (re-ranking is then off). Agents get blast radius and tests in a few hundred tokens, and the
reasons behind the code survive between sessions, marked when the code they describe is gone.
