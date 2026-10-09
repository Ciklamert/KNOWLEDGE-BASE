# ADR-002 - Document graph: LightRAG server as a managed child process

**Status:** accepted · **Requirements:** R6, R4, R3

## Context
The document graph is built with LightRAG. It must use the corporate OpenAI-compatible API, be configurable from
`.env` and the UI, start with the system and survive crashes.

## Decision
Run the upstream, unmodified **`lightrag-server`** (lightrag-hku 1.5.7, pinned) as a child process bound to
`127.0.0.1:LIGHTRAG_PORT`. Its environment is built from AI-BRAIN's settings (`BRAIN_LLM_*`, `BRAIN_EMBEDDING_*`,
`BRAIN_VLM_MODEL`, `LIGHTRAG_*`) plus raw `LIGHTRAG__*` pass-through variables. The provider waits for `/health`
at start-up, supervises the process (up to 5 restarts) and shows its log tail in the UI on errors. All calls use
LightRAG's REST API.

## Alternatives
| Option | Why not |
|---|---|
| embed the LightRAG library in the server process | couples the server's event loop and dependencies to LightRAG's internals; its server already has the upload pipeline, status tracking, graph API and safe concurrency |
| expose LightRAG's own server and UI | a second port and login, no code graph, no combined search |

## Consequences
- Upgrading LightRAG means changing one pin, as long as its REST API and variable names stay compatible.
- Behaviours handled in the provider: a placeholder `.env` in its working directory prevents an interactive
  question that otherwise stops start-up on Windows; LightRAG's own reranker is disabled (`RERANK_BINDING=null`,
  AI-BRAIN re-ranks itself); remote image downloads are off; `NO_PROXY` covers 127.0.0.1.
- Storage is LightRAG's default file storage (graphml, JSON key-value, nano-vectordb) under `data/lightrag/`.
  Larger installations can move it to PostgreSQL or Neo4j with `LIGHTRAG__*` variables, without code changes.
