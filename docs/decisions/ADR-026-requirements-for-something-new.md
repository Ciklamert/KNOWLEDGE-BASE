# ADR-026 - Requirements for something new

**Status:** accepted · **Requirement:** R31

## Context
The requirements writer describes what exists: every requirement comes from the code or the documents. Teams also
need to specify a capability that does not exist yet and is not mentioned anywhere, written in the organisation's
terms and consistent with the current system.

## Decision
- A **mode** on the requirements writer: `existing` (default) or `new` (UI *What exists* / *Something new*; API and
  MCP `mode`).
- In `new` mode the same pipeline runs with different instructions:
  - the **plan** takes the capabilities from the request, not from the evidence;
  - the **searches** look for the related existing code, rules and documents;
  - the **writer** follows its own grounding rules: facts about the current system only from the evidence; the new
    behaviour proposed from the request; every choice the request leaves open marked "to be confirmed"; never a
    claim that the new behaviour exists;
  - **Status** values are *New*, *Changes existing behaviour* and *Partly implemented*.
- A built-in **`new-feature`** format with the sections a proposal needs: current situation, proposed solution,
  functional and quality requirements, impact on the current system, rollout and migration, assumptions and open
  questions. Any other format can be used too.
- The appendix lists the **related existing system** (code and documents each new capability touches) instead of
  traceability.

## Alternatives
A separate "proposal writer" (a second pipeline and UI for the same job); writing new requirements with Ask (no
format, no EARS, no numbering); asking the model without the knowledge base (requirements in foreign terms that
ignore existing rules and the systems they affect).

## Consequences
A proposal for a new capability comes out in the same quality and format as a description of the current system,
and shows what it changes and what the business still has to decide.
