"""Turn EVERY document into Markdown before it goes to LightRAG (``to_markdown``).

Word, PDF, PowerPoint, Excel, HTML, CSV, text, code and images all become Markdown with real headings, lists and
HTML tables; documents with pictures become a ``.textpack`` (Markdown + image files) so the vision model can read
the pictures. The converted Markdown is also kept in data/converted/ and can be previewed in the UI.


Why: LightRAG's own *native* engine reads .textpack locally (no external service). It turns every
image into a ``drawings.json`` item (analysed by the vision model, VLM role), every HTML table into
a ``tables.json`` item (analysed by the text model), and splits by headings for the ``P`` chunker.
LightRAG's default PDF path (``legacy``) extracts plain text only: tables lose structure, images vanish.

Model-free and permissively licensed: pdfplumber (MIT) for words, fonts and tables, pypdfium2
(Apache-2.0/BSD) for rendering image regions and scanned pages. A page with no text layer is
rendered whole, so the vision model reads it (OCR + description in one step).
"""
import hashlib
import html
import io
import re
import zipfile
from collections import Counter
from pathlib import Path

MIN_IMG_PX = 64          # LightRAG skips smaller images anyway (VLM_MIN_IMAGE_PIXEL)
MAX_SHEET_ROWS = 2000
MAX_SHEET_COLS = 40


class Pack:
    """Collects markdown + assets, writes a .textpack zip."""

    def __init__(self, title: str):
        self.md = [f"# {title}", ""]
        self.assets: dict[str, bytes] = {}
        self._seen: Counter = Counter()

    def add_image(self, data: bytes, ext: str, alt: str) -> None:
        h = hashlib.sha1(data).hexdigest()[:12]
        self._seen[h] += 1
        if self._seen[h] > 2:  # logos / headers repeated on every page: describe once or twice
            return
        name = f"assets/{h}.{ext}"
        self.assets[name] = data
        self.md += [f"![{alt}]({name})", ""]

    def build(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("text.md", "\n".join(self.md))
            for name, data in self.assets.items():
                z.writestr(name, data)
        return buf.getvalue()


def html_table(rows: list[list]) -> str:
    rows = [[("" if c is None else " ".join(str(c).split())) for c in r] for r in rows if r and any(c not in (None, "") for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    head = "".join(f"<th>{html.escape(c)}</th>" for c in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _png(img) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()


def _jpg(img) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=82)
    return out.getvalue()


# ---------------------------------------------------------------- PDF
def pdf(data: bytes, title: str) -> "Pack":
    import pdfplumber
    import pypdfium2

    pack = Pack(title)
    doc = pypdfium2.PdfDocument(data)
    with pdfplumber.open(io.BytesIO(data)) as pdfp:
        sizes = Counter()
        for page in pdfp.pages[:30]:
            sizes.update(round(c["size"]) for c in page.chars[:4000])
        body = sizes.most_common(1)[0][0] if sizes else 10
        heading_sizes = sorted({s for s in sizes if s >= body * 1.18}, reverse=True)[:3]

        for pno, page in enumerate(pdfp.pages):
            scale = 2.0
            rendered = None

            def render():
                nonlocal rendered
                if rendered is None:
                    rendered = doc[pno].render(scale=scale).to_pil()
                return rendered

            text_chars = [c for c in page.chars if c.get("text", "").strip()]
            if len(text_chars) < 20:  # scanned page / pure figure: let the vision model read it
                pack.md += [f"## Page {pno + 1}", ""]
                pack.add_image(_jpg(render()), "jpg", f"Page {pno + 1} of {title} (scanned or graphic page)")
                continue

            blocks = []  # (top, kind, payload)
            tables = page.find_tables()
            tboxes = [t.bbox for t in tables]
            for t in tables:
                h = html_table(t.extract())
                if h:
                    blocks.append((t.bbox[1], "table", h))

            for im in page.images:
                x0, top, x1, bottom = im["x0"], im["top"], im["x1"], im["bottom"]
                if (x1 - x0) * scale < MIN_IMG_PX or (bottom - top) * scale < MIN_IMG_PX:
                    continue
                box = (max(0, x0) * scale, max(0, top) * scale, min(page.width, x1) * scale,
                       min(page.height, bottom) * scale)
                if box[2] - box[0] < MIN_IMG_PX or box[3] - box[1] < MIN_IMG_PX:
                    continue
                blocks.append((top, "image", _png(render().crop(tuple(int(v) for v in box)))))

            def inside(obj):
                cx, cy = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
                return any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in tboxes)

            for line in page.extract_text_lines(return_chars=True, strip=True):
                if not line["text"].strip() or inside(line):
                    continue
                size = round(max((c["size"] for c in line["chars"]), default=body))
                blocks.append((line["top"], "line", (line["text"], size, line["bottom"])))

            # many vector strokes outside tables = chart/diagram drawn with paths -> page snapshot
            strokes = [o for o in page.curves + page.lines + page.rects if not inside(o)]
            if len(strokes) > 40:
                blocks.append((page.height, "image", _jpg(render())))

            blocks.sort(key=lambda b: b[0])
            para, last_bottom = [], None

            def flush():
                if para:
                    pack.md += [" ".join(para), ""]
                    para.clear()
            for top, kind, payload in blocks:
                if kind == "line":
                    text, size, bottom = payload
                    if size in heading_sizes and len(text) < 120:
                        flush()
                        pack.md += ["#" * (heading_sizes.index(size) + 2) + " " + text, ""]
                    else:
                        if last_bottom is not None and top - last_bottom > size * 0.9:
                            flush()
                        para.append(text)
                    last_bottom = bottom
                else:
                    flush()
                    last_bottom = None
                    if kind == "table":
                        pack.md += [payload, ""]
                    else:
                        pack.add_image(payload, "png" if payload[:4] == b"\x89PNG" else "jpg",
                                       f"Figure on page {pno + 1} of {title}")
            flush()
    doc.close()
    return pack


# ---------------------------------------------------------------- PowerPoint
def pptx(data: bytes, title: str) -> "Pack":
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    pack = Pack(title)
    prs = Presentation(io.BytesIO(data))

    def walk(shapes):
        for sh in shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from walk(sh.shapes)
            else:
                yield sh
    for n, slide in enumerate(prs.slides, 1):
        head = slide.shapes.title.text.strip() if slide.shapes.title is not None and slide.shapes.title.has_text_frame else ""
        pack.md += [f"## Slide {n}{': ' + head if head else ''}", ""]
        for sh in sorted(walk(slide.shapes), key=lambda s: (s.top or 0, s.left or 0)):
            if slide.shapes.title is not None and sh.shape_id == slide.shapes.title.shape_id:
                continue
            if sh.has_text_frame and sh.text_frame.text.strip():
                for p in sh.text_frame.paragraphs:
                    t = "".join(r.text for r in p.runs).strip()
                    if t:
                        pack.md.append(("  " * p.level) + "- " + t)
                pack.md.append("")
            elif getattr(sh, "has_table", False) and sh.has_table:
                pack.md += [html_table([[c.text for c in r.cells] for r in sh.table.rows]), ""]
            elif getattr(sh, "has_chart", False) and sh.has_chart:
                ch = sh.chart
                try:
                    cats = list(ch.plots[0].categories)
                    rows = [["series", *map(str, cats)]] + [[s.name, *s.values] for s in ch.plots[0].series]
                    pack.md += [f"Chart: {ch.chart_title.text_frame.text if ch.has_title else 'untitled'}", "",
                                html_table(rows), ""]
                except Exception:
                    pass
            elif sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    pack.add_image(sh.image.blob, sh.image.ext.replace("jpeg", "jpg"), f"Image on slide {n}")
                except Exception:
                    pass
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            pack.md += ["Speaker notes: " + slide.notes_slide.notes_text_frame.text.strip(), ""]
    return pack


# ---------------------------------------------------------------- Excel
def xlsx(data: bytes, title: str) -> "Pack":
    from openpyxl import load_workbook

    pack = Pack(title)
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = []
        for i, r in enumerate(ws.iter_rows(values_only=True)):
            if i >= MAX_SHEET_ROWS:
                break
            rows.append(list(r[:MAX_SHEET_COLS]))
        rows = [r for r in rows if any(c not in (None, "") for c in r)]
        if not rows:
            continue
        pack.md += [f"## Sheet: {ws.title}", ""]
        # split very long sheets into tables of 200 rows (header repeated) so each stays analysable
        header, rest = rows[0], rows[1:] or []
        for i in range(0, max(len(rest), 1), 200):
            pack.md += [html_table([header] + rest[i:i + 200]), ""]
        if ws.max_row and ws.max_row > MAX_SHEET_ROWS:
            pack.md += [f"(sheet truncated: first {MAX_SHEET_ROWS} of {ws.max_row} rows)", ""]
    return pack


def image(data: bytes, title: str, ext: str) -> "Pack":
    pack = Pack(title)
    pack.add_image(data, "jpg" if ext in (".jpg", ".jpeg") else ext.lstrip("."), title)
    return pack


# ---------------------------------------------------------------- Word
def docx(data: bytes, title: str) -> "Pack":
    """Headings (from Word styles), lists, bold/italic, tables (HTML) and pictures, in document order."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    pack = Pack(title)
    doc = Document(io.BytesIO(data))
    rels = doc.part.related_parts

    def runs_md(p) -> str:
        out = []
        for r in p.runs:
            t = r.text
            if not t:
                continue
            if r.bold and t.strip():
                t = f"**{t.strip()}** "
            elif r.italic and t.strip():
                t = f"*{t.strip()}* "
            out.append(t)
        return "".join(out).strip()
    def end_list():
        if pack.md and pack.md[-1].startswith("- "):
            pack.md.append("")
    for block in doc.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(block, doc)
            for blip in block.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip"):
                rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                part = rels.get(rid)
                if part is not None:
                    ext = (part.partname.ext or "png").lower().replace("jpeg", "jpg")
                    if ext in ("png", "jpg", "gif", "webp"):
                        pack.add_image(part.blob, ext, f"Image in {title}")
            text = runs_md(p)
            if not text:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            m = re.match(r"(heading|başlık)\s*(\d)", style)
            is_list = "list" in style or (p._p.pPr is not None and p._p.pPr.numPr is not None)
            if not is_list:
                end_list()
            if style == "title":
                pack.md += [f"# {text}", ""]
            elif m:
                pack.md += ["#" * min(6, int(m.group(2)) + 1) + " " + text, ""]
            elif is_list:
                pack.md.append(f"- {text}")
            else:
                pack.md += [text, ""]
        elif tag == "tbl":
            end_list()
            t = Table(block, doc)
            pack.md += [html_table([[c.text for c in row.cells] for row in t.rows]), ""]
    return pack


# ---------------------------------------------------------------- HTML
class _Html2Md:
    """Small, dependency-free HTML -> Markdown: headings, paragraphs, lists, links, code, tables (kept as HTML)."""

    def __init__(self):
        from html.parser import HTMLParser
        self.out: list[str] = []
        self.buf: list[str] = []
        self.table: list[list[str]] | None = None
        self.skip = 0
        outer = self

        class P(HTMLParser):
            def handle_starttag(self, tag, attrs):
                outer.start(tag, dict(attrs))

            def handle_endtag(self, tag):
                outer.end(tag)

            def handle_data(self, data):
                outer.data(data)
        self.parser = P(convert_charrefs=True)

    def flush(self, prefix=""):
        text = " ".join("".join(self.buf).split())
        self.buf = []
        if text:
            self.out += [prefix + text, ""]

    def start(self, tag, attrs):
        if tag in ("script", "style", "head", "nav", "noscript"):
            self.skip += 1
        elif tag == "table":
            self.flush()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.table.append([])
        elif tag in ("td", "th") and self.table is not None:
            self.buf = []
        elif tag in ("p", "div", "br", "section", "article") or re.fullmatch(r"h[1-6]", tag) or tag == "li":
            self.flush()
        elif tag == "code":
            self.buf.append("`")

    def end(self, tag):
        if tag in ("script", "style", "head", "nav", "noscript"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th") and self.table is not None:
            if self.table:
                self.table[-1].append(" ".join("".join(self.buf).split()))
            self.buf = []
        elif tag == "table" and self.table is not None:
            self.out += [html_table(self.table), ""]
            self.table = None
        elif re.fullmatch(r"h[1-6]", tag):
            self.flush("#" * int(tag[1]) + " ")
        elif tag == "li":
            self.flush("- ")
        elif tag in ("p", "div", "section", "article"):
            self.flush()
        elif tag == "code":
            self.buf.append("`")

    def data(self, d):
        if not self.skip:
            self.buf.append(d)

    def convert(self, html_text: str) -> str:
        self.parser.feed(html_text)
        self.flush()
        return "\n".join(self.out)


def html_md(data: bytes, title: str) -> "Pack":
    pack = Pack(title)
    pack.md += [_Html2Md().convert(_decode(data))]
    return pack


# ---------------------------------------------------------------- plain text, tables, code
CODE_EXT = {".py": "python", ".java": "java", ".js": "javascript", ".ts": "typescript", ".cs": "csharp", ".go": "go",
            ".rb": "ruby", ".php": "php", ".kt": "kotlin", ".swift": "swift", ".c": "c", ".h": "c", ".cpp": "cpp",
            ".hpp": "cpp", ".rs": "rust", ".scala": "scala", ".sql": "sql", ".sh": "bash", ".ps1": "powershell",
            ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".xml": "xml", ".toml": "toml", ".ini": "ini",
            ".properties": "properties", ".conf": "", ".cfg": "", ".gradle": "groovy", ".vb": "vbnet"}
TEXT_EXT = {".txt", ".text", ".log", ".rst", ".adoc", ".asciidoc", ".org", ".tex"}


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254", "latin-1"):   # UTF-8 first, then Turkish Windows, then anything
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def text_md(data: bytes, title: str) -> "Pack":
    pack = Pack(title)
    pack.md += [_decode(data).strip(), ""]
    return pack


def csv_md(data: bytes, title: str, delimiter: str) -> "Pack":
    import csv
    pack = Pack(title)
    rows = list(csv.reader(io.StringIO(_decode(data)), delimiter=delimiter))[:MAX_SHEET_ROWS]
    if rows:
        header, rest = rows[0], rows[1:]
        for i in range(0, max(len(rest), 1), 200):
            pack.md += [html_table([header] + rest[i:i + 200]), ""]
    return pack


def code_md(data: bytes, title: str, lang: str) -> "Pack":
    pack = Pack(title)
    pack.md += [f"```{lang}", _decode(data).rstrip(), "```", ""]
    return pack


# ---------------------------------------------------------------- entry point
SUPPORTED = sorted({".md", ".markdown", ".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".html", ".htm", ".csv", ".tsv",
                    ".png", ".jpg", ".jpeg", ".webp", ".gif"} | TEXT_EXT | set(CODE_EXT))


def to_markdown(filename: str, data: bytes) -> tuple[str, bytes, str]:
    """EVERY document becomes Markdown before it reaches LightRAG.
    Returns (stored file name, payload, markdown text): `<file>.md` when the document has no images, else
    `<file>.textpack` (Markdown + image files, read by LightRAG's native engine; images go to the vision model)."""
    ext = Path(filename).suffix.lower()
    title = re.sub(r"[_\-]+", " ", Path(filename).stem).strip() or filename
    if ext in (".md", ".markdown"):
        md = _decode(data)
        return (filename if ext == ".md" else f"{filename}.md"), md.encode("utf-8"), md
    if ext == ".pdf":
        pack = pdf(data, title)
    elif ext == ".docx":
        pack = docx(data, title)
    elif ext == ".pptx":
        pack = pptx(data, title)
    elif ext in (".xlsx", ".xlsm"):
        pack = xlsx(data, title)
    elif ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        pack = image(data, title, ext)
    elif ext in (".html", ".htm"):
        pack = html_md(data, title)
    elif ext in (".csv", ".tsv"):
        pack = csv_md(data, title, "\t" if ext == ".tsv" else ",")
    elif ext in CODE_EXT:
        pack = code_md(data, title, CODE_EXT[ext])
    elif ext in TEXT_EXT or b"\x00" not in data[:4096]:
        pack = text_md(data, title)
    else:
        raise ValueError(f"{filename}: unsupported format {ext or '(none)'}; supported: {', '.join(SUPPORTED)}")
    md = "\n".join(pack.md)
    if pack.assets:
        return f"{filename}.textpack", pack.build(), md
    return f"{filename}.md", md.encode("utf-8"), md
