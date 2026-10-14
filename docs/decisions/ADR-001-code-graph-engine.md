# ADR-001 - Code graph and code vectors: codebase-memory-mcp

**Status:** accepted · **Requirements:** R5, R9, R1

## Context
The code graph must come from a ready-made engine, handle any programming language, run air-gapped on Windows and
Linux, scale to enterprise repositories (thousands of files) and update incrementally after every merge. It should
also offer vector search over code without calling a remote service.

## Decision
Use **codebase-memory-mcp 0.11** (MIT, DeusData): one native binary per operating system with 150+ vendored
tree-sitter grammars, LSP-style type resolution for the major languages, one SQLite knowledge graph per project
(functions, classes, routes; CALLS, INHERITS, IMPLEMENTS, IMPORTS, HTTP_CALLS, DATA_FLOWS, TESTS …), an FTS5 BM25
index and a **bundled code-embedding model** (no API calls).

How AI-BRAIN uses it:
- queries go to one warm MCP stdio process, serialised by a lock;
- indexing runs as a separate CLI process, one at a time, so a long index never blocks queries;
- the UI graphs, graph expansion, annotations and file listing read the SQLite file read-only.

## Alternatives
| Option | Why not |
|---|---|
| a custom tree-sitter indexer in Python | slow at scale, few grammars, one corporate-API embedding call per symbol |
| GitNexus | needs a Node runtime and LadybugDB; heavier to run air-gapped on Windows |
| CodeGraphContext, code-graph-rag | need an external graph database (Neo4j, Kuzu, Memgraph); fewer languages |
| an LLM-extracted knowledge graph (LightRAG, GraphRAG) | one or two model calls per chunk, and a semantic rather than structural graph |
| Sourcegraph / Zoekt | search only, no call graph; a server farm |
| graphify | no vector search, 37 languages ([18](../18-ENGINE-COMPARISON.md)) |

## Consequences
- Indexing makes **no network calls**. Measured: a 4,862-file Java repository in 69 s, a one-file change in about 5 s.
- The binary is about 300 MB because it contains the model. Antivirus products have flagged it as a false
  positive; setup verifies the official SHA-256 so IT can allow-list it.
- The bundled model is English- and code-oriented; ADR-020 adds a multilingual code vector index for that reason.
- Engine behaviours handled in the provider: the cache directory must not be world-writable (it lives in
  `data/cbm`); the engine normalises project names (the returned name is stored); `delete_project` answers
  `not_found` for caches under non-ASCII paths, so the provider deletes the database files itself.
- Replaceable through the `CodeGraph` interface (ADR-005).
