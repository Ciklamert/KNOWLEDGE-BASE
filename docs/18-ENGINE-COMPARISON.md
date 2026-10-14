# 18 - Engine comparison: the code engine and the document engine

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
| Documents, PDFs, images | not its job (AI-BRAIN has its own document engine) | extraction with an LLM provider |
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
| Document graph | the built-in document engine | passages with section and page, concepts with definitions, facts; concept names are also used to search code |

## 4. Other engines considered

| Engine | Why not |
|---|---|
| GitNexus | needs a Node runtime and LadybugDB; heavier to run air-gapped on Windows |
| CodeGraphContext, code-graph-rag | need an external graph database (Neo4j, Kuzu, Memgraph); fewer languages |
| Sourcegraph / Zoekt | search only, no call graph; a server farm |
| A custom tree-sitter indexer in Python | slow at scale, few grammars, and one corporate-API embedding call per symbol |
| an LLM-extracted knowledge graph (LightRAG, GraphRAG) for code | one or two model calls per chunk, and a semantic rather than structural graph |

Every engine plugs in through the `CodeGraph` interface ([08-PLUGINS.md](08-PLUGINS.md)), so the choice can be
revisited without touching search, agents, MCP or the UI.

## 6. The document engine compared with open-source engines
Compared in October 2026 against what AI-BRAIN needs from a document engine: Word, PowerPoint, Excel, PDF with tables
and pictures, HTML and more; no model call per chunk; the corporate embedding model (no model files to download);
Python 3.13 wheels only, no second service; a graph of concepts and links, not only passages.

| Engine | What it is | Formats | Model at indexing | Fit |
|---|---|---|---|---|
| **AI-BRAIN docgraph** (used) | ~600 lines in the server, one SQLite file: passages by heading and page, FTS5 BM25, int8 vectors, concepts and document links, RRF | everything the converter takes (PDF tables and pictures, Office, HTML, e-mail, zip, ...) | none; one batched embedding pass, one vision call per picture | all needs, no extra package |
| [knowledge-rag](https://github.com/lyonzin/knowledge-rag) | Python MCP server: ChromaDB + optional SQLite FTS5, FastEmbed, cross-encoder rerank | about 35 extensions incl. DOCX, XLSX, PPTX; PDF text only, no OCR, tables and pictures not handled | none, but a local ONNX model (~200 MB) and a re-ranker must be downloaded | the closest; adds ChromaDB and ONNX, no concept graph, PyMuPDF (AGPL) for PDF |
| [DocuGraph MCP](https://github.com/yoiberdev/docugraph-mcp) | Rust binary: PDF structure graph, BM25, n-gram "semantic" sketch | PDF only | none | PDF only; early (published accuracy limits); no Office formats, no real vectors |
| [kb-index](https://github.com/ZhengchenTao/kb-index), [kb-mcp](https://github.com/jblenman/kb-mcp) | SQLite FTS5 (+ vectors) over Markdown, served over MCP | Markdown and text | none | same core idea as docgraph, but no conversion, tables, pictures or concepts |
| [Microsoft GraphRAG](https://github.com/microsoft/graphrag), `--method fast` | noun-phrase graph with NLTK/spaCy and co-occurrence | text | LLM community reports still needed | large dependency set (spaCy models, pandas, LanceDB) and model calls at indexing |
| [Tencent WeKnora](https://github.com/Tencent/WeKnora) | full RAG platform with MCP endpoints, optional Neo4j | PDF, Word, Excel, images and more | LLM-driven (Q&A, wiki, optional graph) | a platform with its own services and databases, not an embeddable engine |
| [LightRAG](https://github.com/HKUDS/LightRAG) | LLM entity and relation extraction | via its own parsers | one or more chat calls per chunk | the reason for the change (ADR-002) |

**Result:** none of them is simpler and covers more. The closest, knowledge-rag, would add ChromaDB, an ONNX runtime
and downloaded models, handle PDF tables and pictures worse, and drop the concept graph. The built-in engine stays.
Two ideas were checked and are already in it: reciprocal-rank fusion of BM25 and vectors, and passages that keep their
heading path and page.

## 7. Sources
- graphify: github.com/Graphify-Labs/graphify (README: "Not a vector index. No embeddings, no vector store");
  reviews by Better Stack and wavect.
- codebase-memory-mcp: github.com/DeusData/codebase-memory-mcp; arXiv:2603.27277 (published benchmark).
- The 4,862-file Java measurement was taken on an enterprise repository during the engine evaluation.
- Document engines: the project pages linked in section 6 (read in October 2026).
