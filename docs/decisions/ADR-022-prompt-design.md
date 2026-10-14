# ADR-022 - System prompt design for ask, enhance and the requirements writer

**Status:** accepted · **Requirements:** R11, R12, R13

## Basis
Current practice for grounded (retrieval-augmented) agents and for requirements writing: role and goal first;
retrieved material in clearly tagged blocks placed before the request (long-context ordering); answer only from the
material, with citations; explicit permission and instruction to say what is missing instead of guessing; an explicit
output structure; EARS (Mavin et al., IEEE RE 2009) for requirement sentences; the ISO/IEC/IEEE 29148 requirement
quality characteristics.

## Decision
- **Shared grounding rules** (`agents.GROUNDING`) for every agent: only the material; never invent identifiers,
  numbers or rules; a partial answer with an explicit "missing" note; code shows what the system does and documents
  what it should do, and conflicts are reported; every repository of a set is considered; inline citations; the
  user's language.
- **Shared tool guide** (`agents.TOOL_GUIDE`): what the three sources already contain, when to call which tool, few
  precise calls, stop as soon as the answer is supported.
- **Message layout**: `<scope>`, `<prompt_analysis>`, `<knowledge_base>`, extra blocks, then the request in its own
  tag last.
- **Ask**: Answer (one to four sentences) → Details (flows in call order, rules, each cited) → Where to look → Gaps and
  conflicts.
- **Enhance**: one prompt for every request. Classify it (bug fix, new feature, change, refactor, performance,
  security, tests, migration, configuration, investigation, documentation, question; two classes if needed); look
  for what the class needs (the failing path and root cause for a bug; where it plugs in and what to imitate for a
  new feature; callers and invariants for a refactor); the minimal change; explicit assumptions and open questions;
  sections Task [class], What exists today, Analysis (class-specific), Business rules and constraints, Impact,
  Implementation plan, Acceptance criteria, Out of scope, Open questions and assumptions, Notes for the agent.
- **Requirements writer**: plain language, EARS sentences, ISO 29148 quality, no technical names in the body; the
  fields and sections are the user's format, never built in (ADR-021).
- **Expansion**: returns only a JSON array of terms (identifiers, translations, synonyms).

## Consequences
Answers are short, cited and honest about gaps; enhanced prompts carry what a coding agent needs and what it must not
touch; requirements are testable and readable by non-technical people.
