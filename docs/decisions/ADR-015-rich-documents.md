# ADR-015 - Rich documents: model-free conversion that keeps tables, pages and pictures

**Status:** accepted · **Requirements:** R6, R8, R9

## Decision
PDF, PowerPoint, Excel, Word and images are converted locally with small, permissively licensed libraries
(pdfplumber, pypdfium2, python-docx, python-pptx, openpyxl, Pillow) and no ML models:
- PDF: text in reading order, headings from font sizes, ruled tables as Markdown tables, embedded pictures cropped,
  pages without a text layer and pages with drawn charts rendered whole, page headers and footers removed, and a page
  marker (`<!-- page N -->`) so every passage knows its page;
- PowerPoint: titles, bullets, tables, chart data, pictures, speaker notes;
- Excel: each sheet as one Markdown table (the document engine splits long tables by rows, header repeated);
- Word: headings, lists, emphasis, tables, pictures.

Pictures are kept as image files next to the Markdown. The document engine (ADR-002) indexes the text at once and
then has the vision model (`BRAIN_VLM_MODEL`) describe each picture: visible text transcribed, charts and diagrams
explained with their values. A scanned page is a picture, so the vision model is also its OCR. The original file is
kept in `data/originals/`.

## Alternatives
| Option | Why not |
|---|---|
| plain text extraction | tables flattened, pictures lost, no pages |
| Docling or MinerU | best layout quality, but torch and model weights or a GPU, and another service |
| a local OCR engine (Tesseract, RapidOCR) | another binary or an ONNX runtime with models to bundle; it reads text but cannot explain a chart; the vision model does both |
| Marker or PyMuPDF4LLM | GPL and AGPL licences |

## Consequences
Tables keep rows and columns and every row stays searchable; pictures and scans become searchable text once the
vision model has described them; nothing heavy is installed. Without a vision model, pictures are searchable only by
their caption and alt text. Borderless tables and complex multi-column layouts are the known weak spot.
