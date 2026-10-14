# ADR-005 - Plug-in provider interfaces for both engines

**Status:** accepted · **Requirement:** R25

## Decision
Two abstract classes in `brain/providers/__init__.py`, `CodeGraph` and `DocGraph`, define everything the rest of the
system may ask of an engine: life cycle, indexing or ingestion, search without model calls, relations, graph
expansion and annotations, file access, deep tools and UI graphs. `BRAIN_CODE_PROVIDER` and `BRAIN_DOC_PROVIDER`
select the implementation by module name or `package.module:Class`. `providers.reload(kind)` swaps an engine at run
time when the setting changes. Optional methods have safe defaults, so a minimal provider implements four (code) or
five (documents) methods.

## Alternatives
Entry-point plug-in discovery (every plug-in would need packaging); a generic "engine over HTTP" protocol (an extra
service per engine).

## Consequences
Engine-specific code (SQL on the code engine's schema, the document engine's index, document conversion) is confined to
`brain/providers/`. Search, agents, the requirements writer, MCP, REST, UI and webhooks never import an engine
directly. Guide: [08-PLUGINS.md](../08-PLUGINS.md).
