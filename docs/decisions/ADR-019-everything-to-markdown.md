# ADR-019 - Every document is converted to Markdown before LightRAG

**Status:** accepted · **Requirement:** R8

## Decision
`brain/providers/convert.py` `to_markdown()` converts **every** upload: Word, PDF, PowerPoint and Excel (ADR-015),
HTML (a dependency-free converter), CSV and TSV (tables), source code and configuration files (fenced code blocks),
text files (UTF-8, then the Turkish Windows code page, then Latin-1) and Markdown (as is). A document without pictures
goes to LightRAG as `<file>.md`; with pictures as `<file>.textpack` (Markdown + image files) so the vision model reads
them. The Markdown is kept in `data/converted/` and can be opened from the Documents page (*Markdown*) and from every
document passage in a result.

## Why
LightRAG's native engine chunks Markdown along headings and analyses HTML tables, so one consistent input format gives
better chunks, entities and relations than a mix of binary formats, and people can see exactly what was indexed.

## Consequences
Unknown binary formats are rejected with the list of supported formats instead of being indexed as noise. The
document graph sees the same structure (headings, tables, code blocks) whatever the original format was.
