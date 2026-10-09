# 18 - Code engine comparison: codebase-memory-mcp, graphify and others

AI-BRAIN needs a code engine that:
1. builds a structural code graph (symbols, calls, inheritance, imports, routes);
2. offers semantic (vector) search over code;
3. supports any programming language;
4. updates incrementally after every merge;
5. runs fully offline on Windows and Linux.

The decision is recorded in [ADR-001](decisions/ADR-001-code-graph-engine.md) and
[ADR-020](decisions/ADR-020-semantic-code-search.md).

## 1. codebase-memory-mcp and graphify side by side

| Criterion | codebase-memory-mcp 0.11 (used) | graphify 0.9.x |
|---|---|---|
| What it is | one native binary (C): MCP server and CLI | Python package and assistant skill with a CLI |
| Parsing | tree-sitter, **150+ languages**, LSP-style type resolution for Java, Kotlin, C#, Python, TypeScript/JavaScript, Go, Rust, C/C++, PHP | tree-sitter, **37 languages** |
| Graph model | persistent SQLite graph per project: functions, methods, classes, routes, files; CALLS, INHERITS, IMPLEMENTS, OVERRIDE, IMPORTS, HTTP_CALLS, ASYNC_CALLS, DATA_FLOWS, TESTS and more | `graph.json`: symbols, imports, inheritance; Leiden community clusters; edges marked extracted or inferred |
| **Vector (semantic) search** | **yes**: a bundled code-embedding model, `semantic_query`, no API calls | **no**: its README states it is not a vector index and has no embeddings or vector store |
| Lexical search | BM25 (SQLite FTS5) over names, qualified names, paths and bodies; graph-ranked text and regex search | query, path and explain over the JSON graph |
| Deep queries | Cypher-like `query_graph`, `trace_path` (inbound, outbound, data flow), change detection, architecture overview, file outline | `query`, `path`, `explain` |
| Incremental updates | content hash per file, git-aware; a one-file change re-indexes in seconds | per-file cache, `--update`, `--watch` |
| Documents, PDFs, images | not its job (AI-BRAIN uses LightRAG) | extraction with an LLM provider |
| Network | none (the model is bundled) | none for code; an LLM provider for documents |
| Scale | the Linux kernel (28 million lines) in about 3 minutes (published); a 4,862-file Java repository in 69 s and a one-file change in about 5 s (measured) | no published numbers for large repositories |
| Licence | MIT | MIT |
| In AI-BRAIN | `brain/providers/codebase_memory.py` | would need a new provider and would have no vectors to offer |

## 2. Decision
**codebase-memory-mcp.** graphify is a good tool for exploring one repository, but it has no vector search (the
main need), covers far fewer languages and has no stronger code graph. Using it would remove semantic code search
instead of adding it.

## 3. The multilingual gap and how AI-BRAIN closes it
The engine's bundled code model is English- and code-oriented, so a Turkish question ("müşteriye iade nasıl
yapılır") does not reach `refund_payment` by meaning. AI-BRAIN therefore also keeps a **multilingual code vector
index** built with the corporate embedding model (`brain/codevec.py`): every function, method, class and route is
embedded once and then only when it changes. Every search uses three sources:

| Source | Engine | What it contributes |
|---|---|---|
| Code graph | codebase-memory-mcp | keyword (BM25) matches, callers, callees and parents of the best hits, relations, signatures |
| Code vectors | codebase-memory-mcp (local model) and `codevec` (corporate multilingual model) | code that means the same as the question, in any human language |
| Document graph | LightRAG | business entities, rules and passages; their names are also used to search code |

## 4. Other engines considered

| Engine | Why not |
|---|---|
| GitNexus | needs a Node runtime and LadybugDB; heavier to run air-gapped on Windows |
| CodeGraphContext, code-graph-rag | need an external graph database (Neo4j, Kuzu, Memgraph); fewer languages |
| Sourcegraph / Zoekt | search only, no call graph; a server farm |
| A custom tree-sitter indexer in Python | slow at scale, few grammars, and one corporate-API embedding call per symbol |
| LightRAG for code | one or two model calls per chunk, and a semantic rather than structural graph |

Every engine plugs in through the `CodeGraph` interface ([08-PLUGINS.md](08-PLUGINS.md)), so the choice can be
revisited without touching search, agents, MCP or the UI.

## 5. Sources
- graphify: github.com/Graphify-Labs/graphify (README: "Not a vector index. No embeddings, no vector store");
  reviews by Better Stack and wavect.
- codebase-memory-mcp: github.com/DeusData/codebase-memory-mcp; arXiv:2603.27277 (published benchmark).
- The 4,862-file Java measurement was taken on an enterprise repository during the engine evaluation.
