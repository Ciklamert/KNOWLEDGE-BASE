# ADR-019 - Every document is converted to Markdown before LightRAG, the MarkItDown way

**Status:** accepted · **Requirements:** R8, R32

## Decision
`brain/providers/convert.py` converts **every** upload to Markdown, built on the idea of Microsoft's MarkItDown:
- **One entry point, a registry of small converters.** Each converter names the file extensions and the content
  kinds it accepts. New formats are one function and one registry line.
- **The content decides, not only the name.** `sniff()` reads magic numbers, the files inside a zip and the shape of
  text, so a Word file without an extension, a PDF named `.bin` or an RSS feed named `.xml` is read correctly.
- **Fallbacks.** Converters are tried in order (extension and content agree, then a specific content kind, then the
  extension, then a generic content kind); if one fails the next is tried; plain text is the last resort.
- **Structure for language models, few tokens.** Headings, lists, links, emphasis, code blocks and tables are kept;
  page furniture (navigation, scripts, side bars, footers), PDF page headers and footers, repeated logos and blank
  runs are dropped.
- **Containers are opened.** A zip archive, an e-book or an e-mail is converted file by file, attachment by
  attachment, each under its own heading.
- Formats: PDF, Word, PowerPoint, Excel, HTML, CSV/TSV, JSON, XML, RSS/Atom, Jupyter notebooks, EPUB, e-mail, zip,
  images, source code, configuration and text files (ADR-015 describes the rich-document converters).

Documents without pictures go to LightRAG as `<file>.md`; with pictures as `<file>.textpack` (Markdown + image
files) so the vision model reads them. The Markdown is kept in `data/converted/` and can be opened from the Documents
page (*Markdown*) and from every document passage in a result.

## Differences from MarkItDown, on purpose
| MarkItDown | AI-BRAIN | Why |
|---|---|---|
| Markdown pipe tables | HTML tables inside the Markdown | LightRAG's native engine analyses HTML tables as tables (rows, columns, merged headers) |
| pictures described during conversion by an LLM | pictures kept as files in a `.textpack` | LightRAG's vision step describes them once, in context, with the corporate vision model |
| many optional dependencies (and a Python package to install) | only packages already bundled, no ML models | the installation is offline and Python 3.13 only |
| audio transcription, YouTube, Outlook `.msg`, `.xls` | not supported | no bundled library and no network; such files are rejected with the list of supported formats |

## Why
LightRAG's native engine chunks Markdown along headings and analyses HTML tables, so one consistent input format gives
better chunks, entities and relations than a mix of binary formats; people can see exactly what was indexed; and
fewer tokens per document means faster, cheaper extraction.

## Consequences
Unknown binary content is rejected with the list of supported formats instead of being indexed as noise. The
document graph sees the same structure whatever the original format was.
