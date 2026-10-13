# Architecture decision records

Each record states the context, the decision, the alternatives considered and the consequences. Requirement numbers
(R1-R33) refer to [00-REQUIREMENTS.md](../00-REQUIREMENTS.md).

| ADR | Decision |
|---|---|
| [ADR-001](ADR-001-code-graph-engine.md) | Code graph and code vectors: codebase-memory-mcp |
| [ADR-002](ADR-002-document-graph-lightrag.md) | Document graph: LightRAG server as a managed child process |
| [ADR-003](ADR-003-single-process-server.md) | One process, one port: FastAPI for UI, REST, MCP and webhooks |
| [ADR-004](ADR-004-configuration.md) | One settings schema, one `.env` file edited by the UI, `repos.json` for repositories |
| [ADR-005](ADR-005-plugin-providers.md) | Plug-in provider interfaces for both engines |
| [ADR-006](ADR-006-search-without-llm.md) | Search without LLM calls |
| [ADR-007](ADR-007-agents.md) | Ask and enhance agents: one tool-calling loop with graceful degradation |
| [ADR-008](ADR-008-authentication.md) | Authentication: one user from configuration, signed cookie, bearer token for agents |
| [ADR-009](ADR-009-webhooks-and-sync.md) | Updates on every merge and every pull of the tracked branch |
| [ADR-010](ADR-010-branch-drift.md) | Branch drift: analysis with recommendations plus optional branch overlays |
| [ADR-011](ADR-011-python-version.md) | Python 3.13 only |
| [ADR-012](ADR-012-mcp-transport.md) | MCP over Streamable HTTP with JSON responses, implemented in the server |
| [ADR-013](ADR-013-ui.md) | UI: plain JavaScript, vendored force-graph, polled jobs |
| [ADR-014](ADR-014-offline-packaging.md) | Offline packaging: everything inside the folder |
| [ADR-015](ADR-015-rich-documents.md) | Rich documents: model-free conversion for LightRAG's native multimodal pipeline |
| [ADR-016](ADR-016-prompt-analysis.md) | Prompt analysis before search, ask and enhance |
| [ADR-017](ADR-017-relevance-pipeline.md) | Relevance pipeline: expansion, document bridge, graph expansion, re-ranking |
| [ADR-018](ADR-018-repositories-webhooks-sets.md) | One webhook per repository; sets as repository groups; one scope combobox |
| [ADR-019](ADR-019-everything-to-markdown.md) | Every document is converted to Markdown before LightRAG, the MarkItDown way |
| [ADR-020](ADR-020-semantic-code-search.md) | Semantic code search: codebase-memory-mcp plus a multilingual code vector index |
| [ADR-021](ADR-021-requirements-writer.md) | Requirements writer: format-driven, evidence-first SRS generation |
| [ADR-022](ADR-022-prompt-design.md) | System prompt design for ask, enhance and the requirements writer |
| [ADR-023](ADR-023-three-sources-ai-first.md) | Three sources in every result; results designed for AI agents first |
| [ADR-024](ADR-024-token-economy.md) | Token economy for AI agents over MCP |
| [ADR-025](ADR-025-learning-a-project.md) | Learning a project: structure without a model, a guide written from evidence |
| [ADR-026](ADR-026-requirements-for-something-new.md) | Requirements for something new |
| [ADR-027](ADR-027-daily-refresh.md) | Every repository is updated at least every 24 hours |
