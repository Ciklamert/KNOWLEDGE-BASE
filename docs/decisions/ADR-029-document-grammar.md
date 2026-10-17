# ADR-029 - A grammar for official and technical documents (the tree-sitter idea)

**Status:** accepted · **Requirements:** R44, R45

## Context
LightRAG understands documents because a model reads every passage, which the slow corporate API cannot afford.
codebase-memory-mcp understands code without a model because code has a formal grammar. Free text has none, but
official and technical documents follow drafting conventions that are almost formal: numbered articles, paragraphs
and items (BÖLÜM, MADDE 5 –, (1), a)), numbered sections (4.2), requirement IDs (REQ-004), defined terms, cross-references
("5 inci maddenin (2) numaralı fıkrası", "Section 3.1"), amendment formulas ("yürürlükten kaldırılmıştır",
"supersedes") and normative sentences built from a few modal patterns ("-malıdır", "zorunludur", MUST / SHALL).
Rule-based extraction is reported as cheap and efficient for documents with a formal structure; meaning extraction from
free sentences by rules remains weak.

## Decision
`brain/providers/docgrammar.py` parses these conventions in Turkish and English, without a model:
- **units** (the tree), **references** (resolved to units in the same document; requirement IDs across documents; laws
  and standards as named targets), **definitions** and **amendments**: the structural layer;
- **statements**: modality (RFC 2119 included), actor, action, object, condition, exception and limits, plus user
  stories and Given / When / Then acceptance criteria, each with a confidence; the best-effort layer.
The engine stores units, references, definitions and statement slots, adds a "reference" concept for every resolved
reference (so Personalized PageRank follows references), and answers the MCP and REST tool `doc` (list, outline,
unit, refs, define, obligations, impact). Documents without these conventions keep the previous behaviour.

## Alternatives
A model per passage (LightRAG): too slow on the gateway. A trained NER model (GLiNER): typed entities, but no structure,
references or statements, and 350 MB to ship. A full syntactic parser for Turkish (Zemberek, spaCy models): Java or
models that do not run on Python 3.13.

## Consequences
On the evaluation corpus (tests/eval, [15-TESTING.md](../15-TESTING.md)): every unit, reference and definition found;
statement slots right in 21 of 22 sampled sentences; the doc tool answered 17 of 17 questions. The corpus was written
by the same author as the grammar, so real documents will score lower until the patterns are tuned on them; free
prose gains nothing from this layer.
