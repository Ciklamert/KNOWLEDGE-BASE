# ADR-019 - Every document is converted to Markdown first, the MarkItDown way

**Status:** accepted · **Requirements:** R8, R32

## Decision
`brain/providers/convert.py` converts **every** upload to Markdown, built on the idea of Microsoft's MarkItDown:
- **One entry point, a registry of small converters.** Each converter names the file extensions and the content kinds
  it accepts. A new format is one function and one registry line.
- **The content decides, not only the name.** `sniff()` reads magic numbers, the files inside a zip and the shape of
  text, so a Word file without an extension, a PDF named `.bin` or an RSS feed named `.xml` is read correctly.
- **Fallbacks.** Converters are tried in order (extension and content agree, then a specific content kind, then the
  extension, then a generic content kind); if one fails the next is tried; plain text is the last resort.
- **Structure for language models, few tokens.** Headings, lists, links, emphasis, code blocks, Markdown pipe tables
  and page markers are kept; page furniture (navigation, scripts, side bars, footers), PDF page headers and footers,
  repeated logos and blank runs are dropped.
- **Containers are opened.** A zip archive, an e-book or an e-mail is converted file by file, attachment by
  attachment, each under its own heading.
- Formats: PDF, Word, PowerPoint, Excel, HTML, CSV/TSV, JSON, XML, RSS/Atom, Jupyter notebooks, EPUB, e-mail, zip,
  images, source code, configuration and text files (ADR-015 describes the rich-document converters).

The Markdown is kept in `data/converted/` and can be opened from the Documents page (*Markdown*) and from every
document passage in a result; the pictures go to the document engine, which has them described by the vision model.
The same conversion is offered without indexing (`POST /api/convert`), for example to load system requirements or a
requirements format from a Word or PDF file.

## Differences from MarkItDown, on purpose
| MarkItDown | AI-BRAIN | Why |
|---|---|---|
| pictures described during conversion by an LLM | pictures kept as files, described after the text is searchable | the document is searchable at once; the vision step can be retried and never blocks |
| many optional dependencies (and a Python package to install) | only packages already bundled, no ML models | the installation is offline and Python 3.13 only |
| audio transcription, YouTube, Outlook `.msg`, `.xls` | not supported | no bundled library and no network; such files are rejected with the list of supported formats |

## Why
One consistent input format lets the document engine split every document the same way (headings, tables, pages,
pictures), people can see exactly what was indexed, and fewer tokens per document means cheaper answers.

## Consequences
Unknown binary content is rejected with the list of supported formats instead of being indexed as noise. The
document graph sees the same structure whatever the original format was.
