# ADR-012 - MCP over Streamable HTTP with JSON responses, implemented in the server

**Status:** accepted · **Requirement:** R18

## Decision
Serve MCP at `POST /mcp` with the Streamable HTTP transport in JSON-response mode; server-sent events are not needed
because every tool returns one result. Supported methods: `initialize` (version negotiation between 2025-06-18,
2025-03-26 and 2024-11-05, with short usage instructions), `ping`, `tools/list`, `tools/call`; notifications get HTTP
202; batches are accepted. About 60 lines in `brain/mcp.py`. Authentication is the same bearer token as the REST API.

## Alternatives
The official MCP Python SDK: an extra dependency tree for a small JSON-RPC dispatcher. The stdio transport: it would
require installing something on every developer machine.

## Consequences
Claude Code (`--transport http`), opencode (`type: remote`), Cursor, Continue, VS Code and others connect with a URL
and a header; nothing is installed on developer machines. Agents without MCP use the identical REST API.
