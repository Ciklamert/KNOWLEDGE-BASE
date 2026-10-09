# ADR-015 - Rich documents: model-free conversion for LightRAG's native multimodal pipeline

**Status:** accepted · **Requirements:** R6, R8, R9

## Decision
PDF, PowerPoint, Excel, Word and images are converted locally with small, permissively licensed libraries
(pdfplumber, pypdfium2, python-pptx, openpyxl, python-docx) and no ML models:
- PDF: text in reading order, headings from font sizes, ruled tables as HTML, embedded pictures cropped, pages
  without a text layer and pages with drawn charts rendered whole;
- PowerPoint: titles, bullets, tables, chart data, pictures, speaker notes;
- Excel: sheets as HTML tables in blocks of 200 rows;
- Word: headings, lists, emphasis, tables, pictures.

A document with pictures becomes a `.textpack` (Markdown plus image files). LightRAG's native engine then chunks along
headings, has the text model analyse the HTML tables and, when `BRAIN_VLM_MODEL` is set, the vision model describe
pictures and scanned pages. The original file is kept in `data/originals/`. The rule that every other format also
becomes Markdown is ADR-019.

## Alternatives
| Option | Why not |
|---|---|
| LightRAG's plain PDF path | tables flattened, pictures lost |
| Docling or MinerU | best layout quality, but torch and model weights or a GPU, and another service; still possible through LightRAG's `DOCLING_ENDPOINT` and `LIGHTRAG_PARSER` |
| Marker or PyMuPDF4LLM | GPL and AGPL licences |

## Consequences
Tables keep rows and columns; pictures and scans become searchable text through the corporate vision model; nothing
heavy is installed. Borderless tables and complex multi-column layouts are the known weak spot (Docling can be added
if they matter).
