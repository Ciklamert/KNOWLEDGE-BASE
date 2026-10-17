# ADR-002 - Document graph: a built-in engine that indexes without an LLM call per chunk

**Status:** accepted · **Requirements:** R6, R8, R9, R1

## Context
The document graph must take Word, PowerPoint, Excel, PDF (with tables and pictures), HTML and other formats, and
be searchable soon after an upload, also on a slow corporate API. Engines that extract entities and relations with
a language model (LightRAG, Microsoft GraphRAG and similar) make one or more model calls per chunk: on a slow
gateway a few hundred pages take hours, and every re-index repeats the cost. The code side shows the alternative:
codebase-memory-mcp builds its graph with parsers and statistics, not with a model.

Research behind the decision:
- Microsoft's **LazyGraphRAG** builds its concept graph with classical NLP (noun-phrase extraction and
  co-occurrence statistics) instead of an LLM, at the indexing cost of plain vector RAG, and defers model use to
  query time ([Microsoft Research](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)).
- **PageIndex** shows that a document's own structure (its table of contents: chapters, sections, pages) is a
  strong retrieval index with traceable page references ([VectifyAI PageIndex](https://gittrend.io/repo/VectifyAI/PageIndex));
  AI-BRAIN keeps that structure without PageIndex's model-written summaries.
- Hybrid lexical + vector retrieval fused by reciprocal rank (Cormack, Clarke and Buettcher, SIGIR 2009) is the
  approach the code side already uses.

## Decision
A small document engine inside the server (`brain/providers/docgraph.py`), the document counterpart of
codebase-memory-mcp:
1. **Structure**: every document becomes Markdown with its pictures (ADR-019) and is split along its headings into
   passages: text (paragraphs kept whole), tables (40 rows per passage, header repeated) and pictures, each with its
   section path and page number.
2. **Keywords**: SQLite FTS5 (BM25) over the passages, with Turkish and English diacritics folded (ş = s, ı = i), in
   two columns: exact and stemmed. Turkish stems come from own suffix rules; measured on 112 forms of official-document
   nouns they split none apart, while Snowball's Turkish stemmer split 22 (it is used for English only).
3. **Vectors**: one embedding per passage with the corporate embedding model, in batches, stored as int8.
4. **Concepts** (the LazyGraphRAG idea): multi-word names in capitals, acronyms, code identifiers, quoted terms,
   glossary entries ("Term: definition", two-column glossary tables) and phrases repeated in a document, in any
   Turkish word form (iadeler, iadesi -> iade). Passages mention concepts; concepts named in the same passage are
   related; documents that name each other are linked.
4b. **Rules**: requirement sentences in Turkish and English, typed obligation, prohibition, recommendation or
   limit, with the limits they state (amounts, durations, percentages), and table rows with numbers, all found by
   patterns at indexing.
4c. **Meaning**: each concept name is embedded once (batched). Concepts that mean the same become aliases (synonyms,
   translations), a question reaches a concept by meaning, and search links concepts to the code that implements
   them through the stored code vectors. No chat call.
5. **Pictures**: embedded images, scanned pages and drawn charts are described by the vision model
   (`BRAIN_VLM_MODEL`) after the text is searchable: one call per picture, never one per chunk.
6. **Search** without a chat call: BM25 + passage vectors + concept graph, fused by reciprocal rank. The concept
   graph is searched with Personalized PageRank (HippoRAG, LinearRAG, SPRIG): mass starts at the question's concepts
   and the best keyword and vector passages and flows passage → concept → passage, so passages linked through a
   shared concept are found even when they share no word with the question; the result has
   the passages with document, section and page, the rules in them, the concepts with their definitions, aliases and
   implementing code, and facts (sentences that join two concepts).
6b. **Document cards**: per document its central sentences (LexRank), dates, effective date, versions and document
   numbers; near-identical documents (MinHash) are versions of each other, and older versions are flagged and rank
   lower. **Themes**: communities of the concept graph (label propagation), named by their top concepts.
7. Everything is one SQLite file (`data/docs/docs.db`) plus `data/docs/assets/`. No child process, no port, no
   extra Python package.

## Alternatives
| Option | Why not |
|---|---|
| LightRAG (LLM entity extraction per chunk) | hours of model calls per document on a slow gateway; a child process, a port and 137 more wheels (225 MB instead of 80 MB) |
| Microsoft GraphRAG | the same per-chunk extraction plus community summaries; heavier still |
| PageIndex | model-written summaries at indexing and model-guided search at query time: slow on the same gateway |
| Docling / MinerU for conversion | best layout quality but torch, model weights or a GPU, and another service |
| a vector store only (no structure, no concepts) | loses sections, pages, tables and the links between documents and terms |
| knowledge-rag (ChromaDB + FastEmbed MCP server) | the closest open-source engine; adds ChromaDB, an ONNX runtime and downloaded models, no concept graph, PDF without tables or pictures |
| DocuGraph MCP, kb-index, kb-mcp | PDF only or Markdown only; no Office conversion, tables or pictures |
| txtai + kb-mcp-server | a similarity graph with topics instead of concepts and rules; torch or LiteLLM and downloaded models |
| LinearRAG as is | English spaCy transformer NER and local embeddings (torch); its retrieval idea is adopted instead |

The full comparison is in [18-ENGINE-COMPARISON.md](../18-ENGINE-COMPARISON.md) section 6.

## Consequences
- A document is searchable as soon as it is converted (seconds); vectors follow in one batched pass; picture
  descriptions follow when a vision model is configured. A slow or failing API never blocks indexing: missing
  vectors and descriptions are completed later.
- Concepts and rules come from patterns, not from understanding: a rule phrased without a modal word or a number
  is missed, Turkish stems cover suffixes but not every form (onayı and onayları stay apart), and aliases and
  concept → code links depend on the embedding model's similarity scale (`BRAIN_CONCEPT_SIM`,
  `BRAIN_CONCEPT_CODE_SIM`), which must be checked on real documents.
- A different embedding model or dimension is detected at start and the vectors are rebuilt.
- Replaceable through the `DocGraph` interface (ADR-005).
