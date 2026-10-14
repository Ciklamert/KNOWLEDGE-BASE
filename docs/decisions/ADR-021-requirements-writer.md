# ADR-021 - Requirements writer: the user's format, evidence first

**Status:** accepted · **Requirements:** R13, R34

## Decision
- **The format is entirely the user's.** There is no built-in format. A format is any Markdown document, typed in
  the UI or converted from the organisation's Word or PDF template: its headings are the sections to write (the
  most used heading level that occurs at least twice), and the text under each heading says what belongs there.
  The writer follows the format's sections, numbering, requirement ID style (`FR-?`, `REQ-?` …, numbered afterwards
  per prefix) and fields. `{{title}}`, `{{date}}`, `{{scope}}` and `{{language}}` are filled in when the format uses
  them.
- **Evidence first, then plan, then write**: search, an architecture overview of every repository and the documents
  → the model plans the capabilities (business feature areas) and picks the format sections to write once per
  capability → each capability is written with its own search (tools allowed) → the other sections follow the format
  from the plan and the capability texts. Each call stays small and grounded, and progress is visible.
- **One request, no modes** (ADR-026): system requirements, a new idea or a topic of the current system, always
  checked against the current code and documents.
- **Plain language with traceability**: one testable statement per requirement unless the format says otherwise;
  a status per requirement; code and document references only in an appendix for the technical team.
- The result is saved (`data/srs/output/`), downloadable, and can be published into the document graph.

## Alternatives
| Option | Why not |
|---|---|
| a built-in format | every organisation has its own SRS layout; a built-in one is either ignored or forced on people |
| a fixed format syntax (special markers for instructions and repeated sections) | Word templates converted to Markdown do not carry such markers; the planner decides which sections repeat per capability |
| one large prompt with everything | exceeds the context on real systems, ungrounded, no progress |

## Consequences
Any company template works, also one loaded from a Word or PDF file. Writing needs a saved format; without one the
writer says how to add it. Cost grows with the number of capabilities (about 20-30 model calls for 8 capabilities);
the run is bounded by `BRAIN_SRS_TIMEOUT`.
