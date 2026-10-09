# ADR-006 - Search without LLM calls

**Status:** accepted · **Requirement:** R10

## Decision
- **Code**: for each repository in scope, the code engine returns a BM25 ranking (FTS5 over names, qualified names,
  paths and bodies) and a vector ranking (its bundled code embeddings); they are fused by reciprocal rank
  (k = 60). Tests count half and one- or two-line symbols ×0.6; source lines and graph relations are attached.
- **Documents**: LightRAG `/query/data` in `mix` mode with `hl_keywords` and `ll_keywords` supplied by AI-BRAIN, which
  makes LightRAG skip its model-based keyword extraction.
- **Keywords** come from the prompt analysis (ADR-016).
- Every part runs in parallel and is bounded by `BRAIN_SEARCH_TIMEOUT`; a failing part is reported and the others are
  still returned.

## Why
Reciprocal rank fusion of lexical and dense retrieval is better than either alone (Cormack, Clarke and Buettcher,
SIGIR 2009): BM25 finds exact identifiers, embeddings find paraphrases ("bill a customer" → `chargeCustomer`), and
graph relations add the structure pure vector search misses.

## Consequences
Search is fast (typically under 3 s), free of chat tokens and deterministic. "No LLM call" means no chat-completion
call: embedding calls remain, because document vectors, the multilingual code vectors (ADR-020) and the re-ranking
(ADR-017) use the corporate embedding model.
