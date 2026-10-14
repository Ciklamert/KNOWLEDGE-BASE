# ADR-026 - One requirements writer for system requirements and for the current system

**Status:** accepted · **Requirements:** R31, R34

## Context
Teams receive system requirements (or a new idea) and must turn them into software requirements that fit the current
system: what already exists, what must change, what is new, which rules apply and which systems are affected. They
also need to describe what a system does today. Both are the same job with a different request, and choosing a mode
first is one more thing to get wrong.

## Decision
- **One request field, no mode.** The request is system requirements, a new idea, a topic of the current system, or a
  mix; any length, pasted or loaded from a Word, PDF or other file through `POST /api/convert`.
- One pipeline and one set of instructions:
  - the **plan** takes the capabilities from the request when it asks for something (every part of it must belong to
    one) and from the evidence when it names a topic, and records the part of the request each capability comes from;
  - the **searches** look for the related existing code, rules and documents;
  - the **writer** takes facts about the current system only from the evidence, proposes behaviour the request leaves
    open and marks it "to be confirmed", and never claims that new behaviour exists;
  - each requirement gets a **status**: *Implemented*, *Partly implemented*, *Changes existing behaviour*, *New*,
    *Documented only* or *Implemented, not documented*, in the format's status field or as "(Status: …)".
- The appendix lists, per capability, the code and documents the requirements were checked against.

## Alternatives
Two modes (describe / from system requirements): the same pipeline behind a switch people must set correctly, and a
request that mixes both fits neither. A separate proposal writer; writing requirements with Ask (no format, no
numbering); asking the model without the knowledge base (requirements in foreign terms that ignore existing rules and
the systems they affect).

## Consequences
Whatever the user gives, the result is software requirements in the organisation's own format, with a clear
statement of what the current system already does and what has to be built or changed.
