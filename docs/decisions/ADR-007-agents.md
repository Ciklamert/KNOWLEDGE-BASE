# ADR-007 - Ask and enhance agents: one tool-calling loop with graceful degradation

**Status:** accepted · **Requirements:** R11, R12, R17, R9, R3

## Decision
One loop (`brain/agents.py` `run_agent`) serves ask, enhance and the requirements writer; they differ in system
prompt (ADR-022) and limits:
1. the conversation is seeded with the full search (ADR-006, ADR-017), so even a one-shot answer is grounded;
2. the model may call read-only tools (`search`, `semantic`, `docs`, `symbol`, `trace`, `snippet`, `read`, `grep`,
   `files`, `overview`) through OpenAI tool calling: at most `*_MAX_STEPS` rounds, 4 calls per round, 8,000
   characters per result, within `*_TIMEOUT`;
3. a final answer without tools is forced when the steps or the time run out.

Degradation: a gateway that rejects tool calling (HTTP 400, 404, 422, 501) switches the loop to one grounded call
(`BRAIN_AGENT_TOOL_CALLING=auto`); an unreachable model returns the search results (ask) or a deterministic prompt
(enhance). Each role has its own model, timeout, step limit, token limit and temperature, and every request may
choose a model from the list the corporate API offers (`GET /api/models`, the UI comboboxes).

## Alternatives
An agent framework (LangChain, LangGraph): more dependencies and indirection for a loop of about 60 lines. A fixed
pipeline without tools: it cannot follow call chains or look up a rule it did not retrieve first.

## Consequences
Works with any OpenAI-compatible gateway, with or without tool calling. Answers follow the user's language
(Turkish in, Turkish out). Every response carries the tool calls (`steps`) and the search it was based on
(`evidence`), so people can check it.
