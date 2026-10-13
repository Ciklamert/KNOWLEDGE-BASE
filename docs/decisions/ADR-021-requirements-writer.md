# ADR-021 - Requirements writer: format-driven, evidence-first SRS generation

**Status:** accepted · **Requirement:** R13

## Decision
- **Formats are Markdown files** (`data/srs/templates/`): `##` sections, `>` instructions, `[per capability]` for
  repeated sections, placeholders. Anyone can adapt the company template without code. The built-in `default` follows
  the ISO/IEC/IEEE 29148 SRS outline, simplified for non-technical readers.
- **Evidence first, then plan, then write**: search, an architecture overview of every repository and the documents
  → the model plans the capabilities (business feature areas) → each capability is written with its own search (tools
  allowed) → the remaining sections are written from the plan and the capability texts. Each call stays small and
  grounded, and progress is visible.
- **Plain language with traceability**: EARS sentences; Why, Acceptance criteria and Status per requirement; code and
  document references only in an appendix. *Status* shows the gaps between the documents and the running system.
- The result is saved (`data/srs/output/`), downloadable, and can be published into the document graph.
- Two modes: what exists (this record) and something new (ADR-026).

## Alternatives
| Option | Why not |
|---|---|
| one large prompt with everything | exceeds the context on real systems, ungrounded, no progress |
| a fixed template in code | every company has its own SRS layout |
| a technical specification generated from code | the need is human-readable requirements |

## Consequences
Specifications are readable by non-technical people and checkable by the technical team. Cost grows with the number
of capabilities (about 20-30 model calls for 8 capabilities); the run is bounded by `BRAIN_SRS_TIMEOUT`.
