# ADR-003 - One process, one port: FastAPI for UI, REST, MCP and webhooks

**Status:** accepted · **Requirements:** R18, R20, R23, R24, R27

## Decision
`brain serve` runs one FastAPI application under uvicorn. It serves the static UI, the REST API, the MCP endpoint and
the webhooks on `BRAIN_HOST:BRAIN_PORT`. The code engine is a child process it owns; the document engine runs inside it
(ADR-002). Long work runs in background
threads tracked as jobs (`brain/jobs.py`).

## Why
FastAPI and uvicorn are small and need no other service. One port means one firewall rule,
one TLS certificate, one login and one URL for people, agents and git servers.

## Alternatives
Separate services (UI server, API server, MCP server, a worker queue with Redis or Celery): more processes, ports
and failure modes for no gain at this scale; requests are I/O-bound and the heavy work happens inside the engines.

## Consequences
Horizontal scaling is not a goal: one server serves a department. The engines are serialised where they must be:
one code index at a time, and code queries through one warm process (about 0.1-1 s each).
