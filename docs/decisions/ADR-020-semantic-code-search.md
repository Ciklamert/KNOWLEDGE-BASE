# ADR-020 - Semantic code search: codebase-memory-mcp plus a multilingual code vector index

**Status:** accepted · **Requirement:** R7

## Context
Code must be searchable by meaning, also when the question is Turkish and the code is English. Two engines were
compared ([18-ENGINE-COMPARISON.md](../18-ENGINE-COMPARISON.md)):

| | codebase-memory-mcp 0.11 | graphify 0.9.x |
|---|---|---|
| Parsing | tree-sitter, 150+ languages, LSP-style type resolution | tree-sitter, 37 languages |
| Graph | SQLite graph: calls, inheritance, imports, routes, HTTP calls, data flow, tests | JSON graph, Leiden clusters |
| **Vector search** | **yes**: bundled code-embedding model, no API calls | **no** |
| Lexical search | BM25 (FTS5) | queries over the JSON graph |
| Updates | incremental by content hash | incremental (`--update`, `--watch`) |

## Decision
1. **Keep codebase-memory-mcp**: graphify has no vector search, fewer languages and no stronger graph.
2. **Add a multilingual code vector index** (`brain/codevec.py`, `BRAIN_CODE_VECTORS=both`, the default): after each
   sync every function, method, class and route (label, name, path, signature, docstring, first 25 lines) is embedded
   with the corporate multilingual embedding model, only for new and changed symbols, and stored as int8 vectors in
   `data/codevec/<repo>.npz`. Search is a NumPy dot product. A different embedding model or dimension rebuilds the
   index.
3. Search fuses BM25, the engine's local code vectors and the multilingual vectors by reciprocal rank, then
   re-ranks (ADR-017). A **Semantic code** scope (UI, API `scope=semantic`, agent tool `semantic`) searches code by
   meaning only.

## Consequences
A Turkish question ("müşteriye iade nasıl yapılır") reaches `refund_payment`. The first sync costs one embedding pass
over all symbols (batched and parallel: `BRAIN_CODE_VECTORS_BATCH`, `BRAIN_CODE_VECTORS_PARALLEL`); later syncs embed
only changed symbols. `BRAIN_CODE_VECTORS=local` turns the multilingual index off (no API cost, and no code text sent to
the API).
