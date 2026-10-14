"""Document graph provider: AI-BRAIN's own document engine, the document counterpart of codebase-memory-mcp.

It builds the graph WITHOUT a language-model call per chunk, so indexing is as fast as the conversion and one batched
embedding pass, even on a slow corporate API:
  * structure  every document becomes Markdown (convert.py) and is split along its headings into passages: text,
               table (split by rows, header repeated) and picture passages, each with its heading path and page;
  * keywords   SQLite FTS5 (BM25) over the passages, with Turkish/English diacritics folded (ş=s, ı=i, ü=u ...);
  * vectors    one embedding per passage with the corporate embedding model, in batches (int8, in the same file);
  * concepts   the idea of Microsoft's LazyGraphRAG: concepts come from classical text analysis, not from an LLM:
               multi-word names in capitals ("Payment Gateway"), acronyms (KDV), code identifiers, quoted terms,
               glossary entries ("Term: definition", two-column glossary tables) and phrases repeated in a document
               ("iade onayı"); in Turkish documents word forms are reduced to their stem (iadeler, iadesi -> iade);
               passages MENTION concepts, concepts that appear in the same passage are related, and documents that
               name each other are linked;
  * rules      requirement sentences in Turkish and English ("-malıdır", "zorunludur", "yasaktır", "must", "shall")
               with their limits ("5.000 TL üzeri", "3 gün içinde") and table rows with numbers become typed facts:
               obligation, prohibition, recommendation, limit or value;
  * meaning    every concept name is embedded once (batched, after the passages): concepts that mean the same
               (synonyms, Turkish/English translations) become aliases, a question reaches a concept by meaning, and
               search links a concept to the code that implements it through the stored code vectors;
  * pictures   embedded images, scanned pages and drawn charts are described by the vision model (BRAIN_VLM_MODEL)
               AFTER the text is searchable: one call per picture, never one per chunk.
Search (no chat call): BM25 + vectors + concept graph, fused by reciprocal rank; the answer carries the passages with
their document, section and page, the business rules in them, the concepts with their definitions and aliases, and
facts (sentences that join two concepts).
Everything lives in one SQLite file, data/docs/docs.db, plus the pictures in data/docs/assets/.
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import sqlite3
import threading
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .. import jobs, llm, query as qa
from .. import settings as cfg
from . import DocGraph, convert

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS docs(id TEXT PRIMARY KEY, name TEXT UNIQUE, status TEXT, error TEXT, chunks INT DEFAULT 0,
  pictures INT DEFAULT 0, described INT DEFAULT 0, chars INT DEFAULT 0, updated REAL);
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, doc TEXT, ord INT, kind TEXT, path TEXT, page INT,
  text TEXT, asset TEXT, vec BLOB);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(body, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS concepts(id INTEGER PRIMARY KEY, key TEXT UNIQUE, name TEXT, kind TEXT, definition TEXT);
CREATE TABLE IF NOT EXISTS mentions(concept INT, chunk INT, PRIMARY KEY(concept, chunk)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS mentions_chunk ON mentions(chunk);
CREATE TABLE IF NOT EXISTS links(doc TEXT, target TEXT, PRIMARY KEY(doc, target)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, chunk INT, kind TEXT, modality TEXT, text TEXT, limits TEXT);
CREATE INDEX IF NOT EXISTS rules_chunk ON rules(chunk);
CREATE TABLE IF NOT EXISTS aliases(a INT, b INT, sim REAL, PRIMARY KEY(a, b)) WITHOUT ROWID;
"""
ANALYSIS = "2"   # version of the concept and rule analysis; a stored index of another version is re-analysed
CAPS = r"[A-ZÇĞİÖŞÜ]"
TITLE_PHRASE = re.compile(rf"\b{CAPS}[\w'’-]+(?:\s+(?:of|for|and|ve|ile|de|da)?\s*{CAPS}[\w'’-]+){{1,3}}")
ACRONYM = re.compile(rf"\b{CAPS}{{2,6}}s?\b")
IDENT = re.compile(r"\b[A-Za-z]+(?:[A-Z][a-z0-9]+)+\b|\b[a-z]+(?:_[a-z0-9]+)+\b")
QUOTED = re.compile(r"[\"“«]([^\"”»\n]{3,40})[\"”»]")
DEFINITION = re.compile(r"^\s*[-*]?\s*\**([^\s:*][^:*\n]{1,40}?)\**\s*[:–—]\s+(.{15,})$")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
GLOSSARY_HEAD = re.compile(r"term|terim|kavram|name|ad|kısaltma|abbreviation", re.I)
PROHIBIT = re.compile(r"\b(?:must|shall|may|should)\s+not\b|\b(?:cannot|can\s?not|not\s+(?:be\s+)?(?:allowed|permitted))\b|"
                      r"\b(?:prohibited|forbidden)\b|yasak|izin\s+verilmez|\w+m[ae]m[ae]l[ıi]\w*|\w+[ae]m[ae]z\b|"
                      r"\w+(?:[ıiuü]l|[ıiuü]n)m[ae]z\b", re.I)
OBLIGE = re.compile(r"\b(?:must|shall|required|requires|mandatory|has\s+to|have\s+to|needs?|only\s+if)\b|"
                    r"\w+(?:mal[ıi]|mel[ıi])(?:d[ıi]r|d[ıi]rlar)?\b|zorunlu|gerek(?:ir|li|ir\.|mektedir)|şart(?:t[ıi]r)?\b", re.I)
ADVISE = re.compile(r"\b(?:should|recommended)\b|önerilir|tavsiye", re.I)
NUMBER = r"(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?"
UNIT = (r"(?:TL|TRY|₺|USD|EUR|€|\$|%|yüzde|iş\s+günü|gün|saat|dakika|saniye|hafta|ay|yıl|adet|kez|defa|"
        r"business\s+days?|days?|hours?|minutes?|seconds?|weeks?|months?|years?|times|items?)")
LIMIT = re.compile(rf"(?:(?:en\s+az|en\s+fazla|en\s+geç|at\s+least|at\s+most|up\s+to|no\s+later\s+than|more\s+than|"
                   rf"less\s+than|over|above|below|under|within|maximum|minimum)\s+)?(?:(?:%|yüzde)\s*{NUMBER}|{NUMBER}\s*{UNIT}"
                   rf"(?:['’]?[a-zçğıöşü]{{0,4}})?)(?:\s+(?:üzeri\w*|üstü\w*|altı\w*|içinde\w*|içerisinde|sonra\w*|önce\w*|"
                   rf"fazla\w*|az\w*|kadar|aşan|geçen|geçmeyen|or\s+more|or\s+less))?", re.I)
VISION_PROMPT = ("This picture is from the document \"{doc}\" (section: {path}). For search, write in plain text: all "
                 "visible text exactly as written; what the chart, diagram, table or photo shows, with its labels and "
                 "values. Use the document's language. No preamble.")


def fold(text: str) -> str:
    """Comparison form: lower case, Turkish dotless/dotted i unified, accents removed (Müşteri -> musteri)."""
    text = unicodedata.normalize("NFKD", text.casefold().replace("ı", "i"))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def lower(text: str) -> str:
    """Lower case that keeps Turkish letters whole (İ -> i, not i + a combining dot)."""
    return text.replace("İ", "i").casefold()


TR_SUFFIXES = sorted({fold(x) for x in qa.TR_SUFFIXES}, key=len, reverse=True)


def stem(word: str, turkish: bool = True) -> str:
    """A folded word without one Turkish case/plural/possessive suffix (iadeler, iadesi, iadenin -> iade) and without
    an English plural s (refunds -> refund); at least four letters stay."""
    if turkish:
        for suf in TR_SUFFIXES:
            if word.endswith(suf) and len(word) - len(suf) >= 4:
                return word[: -len(suf)]
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def concept_key(name: str, turkish: bool = True, kind: str = "") -> str:
    """The identity of a concept: folded, a suffix after an apostrophe removed (KDV'nin -> kdv), each word stemmed.
    Identifiers and acronyms keep their exact form."""
    words = [re.sub(r"['’].*$", "", w) for w in fold(name).split()]
    if kind in ("identifier", "acronym"):
        return " ".join(w for w in words if w)
    return " ".join(stem(w, turkish) for w in words if w)


def stemmed(text: str, turkish: bool = True) -> str:
    return " ".join(stem(w, turkish) for w in re.findall(r"\w+", fold(text)))


def rules_in(kind: str, text: str) -> list[dict]:
    """Typed facts without a model: requirement sentences (obligation, prohibition, recommendation, limit) with the
    limits they state, and table rows that hold numbers (value), each row written with its column names."""
    out = []
    if kind == "table":
        rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in text.splitlines()
                if r.startswith("|") and not re.match(r"\|\s*:?-{3}", r)]
        if len(rows) < 2 or (len(rows[0]) == 2 and GLOSSARY_HEAD.search(rows[0][0])):
            return out
        head = rows[0]
        for cells in rows[1:101]:
            if not any(re.search(r"\d", c) for c in cells):
                continue
            line = "; ".join(f"{h}: {c}" if h else c for h, c in zip(head, cells) if c)
            out.append({"kind": "table row", "modality": "value", "text": line[:400],
                        "limits": [m.group(0).strip() for m in LIMIT.finditer(line)][:4]})
        return out
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line).replace("**", "").strip()
        for sentence in SENTENCE.split(line):
            sentence = sentence.strip()
            if not 15 < len(sentence) < 500:
                continue
            limits = [m.group(0).strip() for m in LIMIT.finditer(sentence)]
            modality = ("prohibition" if PROHIBIT.search(sentence) else "obligation" if OBLIGE.search(sentence)
                        else "recommendation" if ADVISE.search(sentence) else "limit" if limits else "")
            if modality:
                out.append({"kind": "rule", "modality": modality, "text": sentence, "limits": limits[:4]})
    return out


def title_key(name: str) -> str:
    """How a document's name appears in text: "odeme-kurallari.pdf" -> "odeme kurallari"."""
    return " ".join(re.sub(r"[-_.]+", " ", fold(Path(name).stem)).split())


def _quantise(m: np.ndarray) -> np.ndarray:
    m = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
    return np.clip(np.round(m * 127), -127, 127).astype(np.int8)


# ---------------------------------------------------------------- structure: Markdown -> passages
def passages(md: str, limit: int) -> list[dict]:
    """Split converted Markdown along headings into passages {kind, path, page, text, asset}: text passages up to
    `limit` characters (paragraphs kept whole), tables split into pieces of 40 rows with the header repeated,
    one passage per picture (its alt text and the nearest caption until the vision model describes it)."""
    out: list[dict] = []
    path: list[str] = []
    page, buf, size = None, [], 0
    lines = md.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]   # the document title; every passage already carries the document name

    def emit(kind, text, asset=None):
        text = text.strip()
        if text or asset:
            out.append({"kind": kind, "path": " › ".join(path), "page": page, "text": text, "asset": asset})

    def flush():
        nonlocal buf, size
        emit("text", "\n".join(buf))
        buf, size = [], 0
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"<!-- page (\d+) -->", line)
        if m:
            if size >= limit // 3:
                flush()
            page = int(m.group(1))
        elif re.match(r"#{1,6}\s", line):
            flush()
            level = len(line) - len(line.lstrip("#"))
            path = path[:max(0, level - 2)] + [line.lstrip("#").strip()]
        elif line.startswith("|"):
            flush()
            table = []
            while i < len(lines) and lines[i].startswith("|"):
                table.append(lines[i])
                i += 1
            head, body = table[:2], table[2:]
            for k in range(0, max(1, len(body)), 40):
                emit("table", "\n".join(head + body[k:k + 40]))
            continue
        elif re.match(r"!\[[^\]]*\]\(assets/", line):
            flush()
            alt, asset = re.match(r"!\[([^\]]*)\]\((assets/[^)]+)\)", line).groups()
            caption = ""
            for j in (i + 1, i + 2):   # the caption belongs to the picture, not to the next text passage
                if j < len(lines) and re.match(r"(figure|fig\.|şekil|resim|grafik|chart)\b", lines[j], re.I):
                    caption = lines.pop(j)
                    break
            emit("picture", f"{alt}\n{caption}".strip(), asset)
        elif line.startswith("```"):
            block = [line]
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            block.append("```")
            if size and size + sum(map(len, block)) > limit:
                flush()
            buf += block
            size += sum(map(len, block))
        elif not line.strip():
            if size >= limit:
                flush()
            elif buf and buf[-1]:
                buf.append("")
        else:
            if size and size + len(line) > limit * 1.3:
                flush()
            buf.append(line)
            size += len(line)
        i += 1
    flush()
    return out


# ---------------------------------------------------------------- concepts: classical text analysis, no LLM
def concepts_in(text: str, stop: set[str]) -> dict[str, tuple[str, str]]:
    """{key: (name, kind)} for the concepts a passage names."""
    found: dict[str, tuple[str, str]] = {}

    def add(name, kind):
        name = " ".join(name.split()).strip(" .,;:()[]*`'\"")
        key = fold(name)
        if len(key) >= 3 and key not in stop and not key.isdigit():
            found.setdefault(key, (name, kind))
    plain = re.sub(r"[*`#>]", " ", re.sub(r"\|", " . ", text))   # table cells never join into one name
    for m in TITLE_PHRASE.finditer(plain):
        words = m.group(0).split()
        while words and fold(words[0]) in stop:   # "The Payment Gateway" -> "Payment Gateway"
            words.pop(0)
        if len(words) >= 2:
            add(" ".join(words), "name")
    for m in ACRONYM.finditer(plain):
        add(m.group(0), "acronym")
    for m in IDENT.finditer(text):
        add(m.group(0), "identifier")
    for m in QUOTED.finditer(text):
        add(m.group(1), "term")
    return found


def repeated_phrases(text: str, stop: set[str], turkish: bool = True) -> dict[str, str]:
    """Two-word phrases (no stop-words) used at least twice in a document, in any word form: its domain vocabulary
    ("iade onayı", "iade onayının") -> {key: the first form seen}."""
    words = re.findall(r"[^\W\d_]{3,}", lower(text))
    pairs: Counter = Counter()
    shown: dict[str, str] = {}
    for a, b in zip(words, words[1:]):
        if fold(a) in stop or fold(b) in stop:
            continue
        key = f"{stem(fold(a), turkish)} {stem(fold(b), turkish)}"
        pairs[key] += 1
        shown.setdefault(key, f"{a} {b}")
    return {k: shown[k] for k, n in pairs.items() if n >= 2}


def definitions_in(kind: str, text: str) -> dict[str, tuple[str, str]]:
    """{key: (term, definition)} from "Term: definition" lines and two-column glossary tables."""
    out = {}
    if kind == "table":
        rows = [[c.strip() for c in r.strip("|").split("|")] for r in text.splitlines() if not r.startswith("|---")]
        if rows and len(rows[0]) == 2 and GLOSSARY_HEAD.search(rows[0][0]):
            for term, meaning in rows[1:]:
                if term and len(meaning) > 5:
                    out[fold(term)] = (term, meaning)
        return out
    for line in text.splitlines():
        m = DEFINITION.match(line)
        if m and len(m.group(1).split()) <= 5:
            out[fold(m.group(1))] = (m.group(1).strip(), SENTENCE.split(m.group(2).strip())[0])
    return out


# ---------------------------------------------------------------- the provider
class Provider(DocGraph):
    name = "docgraph"

    def __init__(self):
        super().__init__()
        self.dir = cfg.path("docs")
        self.assets = cfg.path("docs", "assets")
        self.lock = threading.RLock()
        self.db: sqlite3.Connection | None = None
        self.activity = {"busy": False, "message": "idle"}
        self._matrix: tuple[int, np.ndarray, np.ndarray] | None = None   # (version, chunk ids, int8 vectors)
        self.version = 0
        self._completing = threading.Lock()

    # ---------------------------------------------------------------- life cycle
    def start(self) -> None:
        with self.lock:
            self.db = sqlite3.connect(self.dir / "docs.db", check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.executescript(SCHEMA)
            if "vec" not in [r[1] for r in self.db.execute("PRAGMA table_info(concepts)")]:
                self.db.execute("ALTER TABLE concepts ADD COLUMN vec BLOB")
            model = f"{cfg.get('BRAIN_EMBEDDING_MODEL')}|{cfg.get('BRAIN_EMBEDDING_DIM')}"
            if self._meta("embedding") != model:   # vectors of another model are not comparable: embed again
                self.db.execute("UPDATE chunks SET vec = NULL")
                self.db.execute("UPDATE concepts SET vec = NULL")
                self.db.execute("DELETE FROM aliases")
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('embedding', ?)", (model,))
            self.db.commit()
            n = self.db.execute("SELECT count(*) FROM docs").fetchone()[0]
            stale = n and self._meta("analysis") != ANALYSIS
        self.state, self.detail = "ready", f"{n} document(s)"
        if stale:
            self.reanalyse()   # concepts and rules from the stored passages; text and vectors are kept
        threading.Thread(target=self.complete, daemon=True, name="docgraph-complete").start()

    def stop(self) -> None:
        with self.lock:
            if self.db is not None:
                self.db.close()
                self.db = None
        self.state = "stopped"

    def health(self) -> dict:
        h = super().health()
        with self.lock:
            if self.db is not None:
                h.update(documents=self.db.execute("SELECT count(*) FROM docs").fetchone()[0],
                         passages=self.db.execute("SELECT count(*) FROM chunks").fetchone()[0],
                         concepts=self.db.execute("SELECT count(*) FROM concepts").fetchone()[0],
                         vision=bool(cfg.get("BRAIN_VLM_MODEL")))
        return h

    def _meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _q(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self.lock:
            if self.db is None:
                raise RuntimeError("document engine is not started")
            return self.db.execute(sql, args).fetchall()

    def _say(self, message: str, busy: bool = True) -> None:
        self.activity = {"busy": busy, "message": message}
        jobs.tick()

    # ---------------------------------------------------------------- ingestion
    def upload(self, filename: str, data: bytes) -> dict:
        name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", Path(filename).name).strip() or "document"
        (cfg.path("originals") / name).write_bytes(data)
        pack = convert.convert(name, data)
        md = pack.text
        (cfg.path("converted") / f"{name}.md").write_text(md, encoding="utf-8")
        doc = "doc-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
        self.delete([doc], keep_files=True)
        folder = self.assets / doc
        for rel, blob in pack.assets.items():
            (folder / Path(rel).parent.name).mkdir(parents=True, exist_ok=True)
            (folder / rel).write_bytes(blob)
        parts = passages(md, cfg.get("BRAIN_DOC_CHUNK_CHARS"))
        self._say(f"{name}: {len(parts)} passages")
        self._index(doc, name, md, parts)
        threading.Thread(target=self.complete, daemon=True).start()   # vectors and pictures; the text is searchable now
        return {"file": name, "status": "success", "passages": len(parts), "pictures": len(pack.assets),
                "markdown_chars": len(md), "message": f"{len(parts)} passages, {len(pack.assets)} pictures"}

    def add_text(self, name: str, text: str) -> dict:
        return self.upload(name if Path(name).suffix else f"{name}.md", text.encode("utf-8"))

    def _index(self, doc: str, name: str, md: str, parts: list[dict]) -> None:
        others = {title_key(r["name"]): r["id"] for r in self._q("SELECT id, name FROM docs")}
        with self.lock:
            db = self.db
            db.execute("INSERT INTO docs(id, name, status, chunks, pictures, chars, updated) VALUES (?,?,?,?,?,?,?)",
                       (doc, name, "processing", len(parts), sum(p["kind"] == "picture" for p in parts), len(md), time.time()))
            rows = []
            for n, p in enumerate(parts):
                cur = db.execute("INSERT INTO chunks(doc, ord, kind, path, page, text, asset) VALUES (?,?,?,?,?,?,?)",
                                 (doc, n, p["kind"], p["path"], p["page"], p["text"], p["asset"]))
                db.execute("INSERT INTO fts(rowid, body) VALUES (?, ?)", (cur.lastrowid, fold(f"{name} {p['path']} {p['text']}")))
                rows.append((cur.lastrowid, p["kind"], p["text"]))
            self._analyse(db, rows, md)
            folded_doc = " ".join(re.sub(r"[-_]+", " ", fold(md)).split())
            for title, other in others.items():   # this document names an earlier one
                if len(title) >= 6 and title in folded_doc:
                    db.execute("INSERT OR IGNORE INTO links VALUES (?, ?)", (doc, other))
            if len(title_key(name)) >= 6:          # earlier documents that name this one
                for (other,) in db.execute("""SELECT DISTINCT c.doc FROM fts JOIN chunks c ON c.id = fts.rowid
                                              WHERE fts MATCH ? AND c.doc != ?""", (f'"{title_key(name)}"', doc)):
                    db.execute("INSERT OR IGNORE INTO links VALUES (?, ?)", (other, doc))
            db.execute("UPDATE docs SET status = 'processed' WHERE id = ?", (doc,))
            db.execute("INSERT OR REPLACE INTO meta VALUES ('analysis', ?)", (ANALYSIS,))
            db.commit()
            self.version += 1
            jobs.tick()

    def _analyse(self, db: sqlite3.Connection, rows: list[tuple[int, str, str]], md: str) -> None:
        """Concepts, definitions, mentions and rules of one document's passages (no model call)."""
        stop = _stop()
        turkish = qa.analyze(md[:4000])["language"] in ("tr", "mixed")
        phrases = repeated_phrases(md, stop, turkish)
        for cid, kind, text in rows:
            found = {}
            for _, (cname, ckind) in concepts_in(text, stop).items():
                key = concept_key(cname, turkish, ckind)
                if len(key) >= 3 and key not in stop:
                    found.setdefault(key, (cname, ckind))
            words = f" {stemmed(text, turkish)} "
            found.update({k: (v, "phrase") for k, v in phrases.items() if f" {k} " in words})
            defs = {concept_key(term, turkish): (term, meaning) for _, (term, meaning) in definitions_in(kind, text).items()}
            found.update({k: (term, "term") for k, (term, _) in defs.items()})
            for key, (cname, ckind) in list(found.items())[:40]:
                db.execute("INSERT OR IGNORE INTO concepts(key, name, kind) VALUES (?,?,?)", (key, cname, ckind))
                if key in defs:
                    db.execute("UPDATE concepts SET definition = ? WHERE key = ? AND definition IS NULL", (defs[key][1], key))
                db.execute("INSERT OR IGNORE INTO mentions SELECT id, ? FROM concepts WHERE key = ?", (cid, key))
            for r in rules_in(kind, text):
                db.execute("INSERT INTO rules(chunk, kind, modality, text, limits) VALUES (?,?,?,?,?)",
                           (cid, r["kind"], r["modality"], r["text"], "; ".join(r["limits"])))

    def reanalyse(self) -> None:
        """Rebuild concepts, mentions, rules and aliases from the stored passages after the analysis changed; the
        passages, their vectors and the pictures stay (no conversion, no embedding of passages)."""
        with self.lock:
            db = self.db
            db.executescript("DELETE FROM mentions; DELETE FROM concepts; DELETE FROM rules; DELETE FROM aliases;")
            for (doc,) in db.execute("SELECT id FROM docs").fetchall():
                rows = db.execute("SELECT id, kind, text FROM chunks WHERE doc = ? ORDER BY ord", (doc,)).fetchall()
                self._analyse(db, [tuple(r) for r in rows], "\n\n".join(r[2] for r in rows))
            db.execute("INSERT OR REPLACE INTO meta VALUES ('analysis', ?)", (ANALYSIS,))
            db.commit()
            self.version += 1
        jobs.tick()

    def complete(self) -> None:
        """Embed the passages that have no vector yet and describe the pictures that have no description yet.
        Runs after every upload and at start-up, so a failed or interrupted step is finished later."""
        if not self._completing.acquire(blocking=False):
            return   # already running; it loops until nothing is left, so this upload is covered too
        try:
            th = str(cfg.get("BRAIN_CONCEPT_SIM"))
            if self._meta("alias_sim") != th:   # the threshold changed: recompute every alias (local, no API call)
                with self.lock:
                    self.db.execute("DELETE FROM aliases")
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES ('alias_sim', ?)", (th,))
                    self.db.commit()
                self._alias([int(c) for c in self._concept_matrix()[0]])
            while True:
                api = bool(cfg.get("BRAIN_EMBEDDING_MODEL") and cfg.get("BRAIN_LLM_BASE_URL"))
                vectors = self._embed_missing() if api else 0
                pictures = self._describe_pictures() if cfg.get("BRAIN_VLM_MODEL") else 0
                concepts = self._embed_concepts() if api else 0
                if vectors <= 0 and pictures <= 0 and concepts <= 0:
                    break
        finally:
            self._completing.release()
            self._say("idle", busy=False)

    def _embed_missing(self) -> int:
        """Embeds the passages without a vector; returns how many (-1 when the API failed: tried again later)."""
        rows = self._q("""SELECT c.id, c.text, c.path, d.name FROM chunks c JOIN docs d ON d.id = c.doc
                          WHERE c.vec IS NULL AND c.text != ''""")
        batch = max(1, cfg.get("BRAIN_EMBED_BATCH"))
        groups = [rows[i:i + batch] for i in range(0, len(rows), batch)]
        done, failed = [0], []

        def work(group):
            try:
                vecs = llm.embed([f"{r['name']} › {r['path']}\n{r['text']}"[:2000] for r in group])
            except llm.LLMError as exc:
                self._say(f"vectors postponed: {exc}")
                failed.append(exc)
                return
            q = _quantise(np.asarray(vecs, dtype=np.float32))
            with self.lock:
                self.db.executemany("UPDATE chunks SET vec = ? WHERE id = ?", [(v.tobytes(), r["id"]) for v, r in zip(q, group)])
                self.db.commit()
                self.version += 1
                jobs.tick()
            jobs.tick()
            done[0] += len(group)
            self._say(f"vectors {done[0]}/{len(rows)}")
        if groups:
            with ThreadPoolExecutor(max(1, cfg.get("BRAIN_EMBED_PARALLEL"))) as pool:
                list(pool.map(work, groups))
        return -1 if failed else done[0]

    def _embed_concepts(self) -> int:
        """Embeds concept names without a vector (batched), then records as aliases the concepts that mean the same
        (synonyms, translations) at BRAIN_CONCEPT_SIM. Returns how many (-1 when the API failed: tried again later)."""
        rows = self._q("SELECT id, name, key FROM concepts WHERE vec IS NULL")
        if not rows:
            return 0
        batch = max(1, cfg.get("BRAIN_EMBED_BATCH"))
        new: list[int] = []
        for i in range(0, len(rows), batch):
            group = rows[i:i + batch]
            try:
                vecs = llm.embed([r["name"] for r in group])
            except llm.LLMError as exc:
                self._say(f"concept vectors postponed: {exc}")
                return -1
            q = _quantise(np.asarray(vecs, dtype=np.float32))
            with self.lock:
                self.db.executemany("UPDATE concepts SET vec = ? WHERE id = ?", [(v.tobytes(), r["id"]) for v, r in zip(q, group)])
                self.db.commit()
            new += [r["id"] for r in group]
            self._say(f"concept vectors {min(i + batch, len(rows))}/{len(rows)}")
        self._alias(new)
        return len(rows)

    def _alias(self, new: list[int]) -> None:
        """Aliases between the new concepts and all others: similar meaning, and neither name contains the other."""
        ids, mat, keys = self._concept_matrix()
        if not len(ids) or not new:
            return
        pos = {int(c): i for i, c in enumerate(ids)}
        rows = [pos[c] for c in new if c in pos]
        sims = (mat[rows].astype(np.float32) @ mat.astype(np.float32).T) / (127.0 * 127.0)
        th = cfg.get("BRAIN_CONCEPT_SIM")
        pairs = []
        for r, row in zip(rows, sims):
            for j in np.nonzero(row >= th)[0][:20]:
                a, b = int(ids[r]), int(ids[j])
                ka, kb = keys[r], keys[j]
                if a != b and ka not in kb and kb not in ka:
                    pairs += [(a, b, float(row[j])), (b, a, float(row[j]))]
        if pairs:
            with self.lock:
                self.db.executemany("INSERT OR REPLACE INTO aliases VALUES (?,?,?)", pairs)
                self.db.commit()
                self.version += 1

    def _concept_matrix(self) -> tuple[np.ndarray, np.ndarray, list[str]]:
        rows = self._q("SELECT id, key, vec FROM concepts WHERE vec IS NOT NULL")
        if not rows:
            return np.zeros(0, np.int64), np.zeros((0, 1), np.int8), []
        return (np.asarray([r[0] for r in rows], dtype=np.int64),
                np.stack([np.frombuffer(r[2], dtype=np.int8) for r in rows]), [r[1] for r in rows])

    def concept_vectors(self, names: list[str]) -> dict[str, np.ndarray]:
        """Stored vectors of concepts by name (unit length), for linking concepts to code."""
        if not names:
            return {}
        q = ",".join("?" * len(names))
        return {r["name"]: np.frombuffer(r["vec"], dtype=np.int8).astype(np.float32) / 127.0
                for r in self._q(f"SELECT name, vec FROM concepts WHERE name IN ({q}) AND vec IS NOT NULL", tuple(names))}

    def _describe_pictures(self) -> int:
        """Describes the pictures not described yet (kind picture -> figure); returns how many (-1 on API failure)."""
        rows = self._q("""SELECT c.id, c.doc, c.asset, c.path, c.text, d.name FROM chunks c JOIN docs d ON d.id = c.doc
                          WHERE c.kind = 'picture' AND c.asset IS NOT NULL""")
        for n, r in enumerate(rows, 1):
            f = self.assets / r["doc"] / r["asset"]
            if not f.exists():
                continue
            self._say(f"describing pictures {n}/{len(rows)} ({r['name']})")
            try:
                text = llm.chat([{"role": "user", "content": [
                    {"type": "text", "text": VISION_PROMPT.format(doc=r["name"], path=r["path"] or "-")},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + _small_jpeg(f.read_bytes())}}]}],
                    cfg.get("BRAIN_VLM_MODEL"), max_tokens=700, temperature=0)["content"]
            except llm.LLMError as exc:
                self._say(f"picture descriptions postponed: {exc}")
                return -1
            body = f"{r['text']}\n{text}".strip()
            with self.lock:
                self.db.execute("UPDATE chunks SET text = ?, kind = 'figure', vec = NULL WHERE id = ?", (body, r["id"]))
                self.db.execute("UPDATE fts SET body = ? WHERE rowid = ?", (fold(f"{r['name']} {r['path']} {body}"), r["id"]))
                self.db.execute("UPDATE docs SET described = described + 1 WHERE id = ?", (r["doc"],))
                turkish = qa.analyze(text[:2000])["language"] in ("tr", "mixed")
                for _, (cname, kind) in list(concepts_in(text, _stop()).items())[:20]:
                    key = concept_key(cname, turkish, kind)
                    self.db.execute("INSERT OR IGNORE INTO concepts(key, name, kind) VALUES (?,?,?)", (key, cname, kind))
                    self.db.execute("INSERT OR IGNORE INTO mentions SELECT id, ? FROM concepts WHERE key = ?", (r["id"], key))
                for rule in rules_in("figure", text):
                    self.db.execute("INSERT INTO rules(chunk, kind, modality, text, limits) VALUES (?,?,?,?,?)",
                                    (r["id"], rule["kind"], rule["modality"], rule["text"], "; ".join(rule["limits"])))
                self.db.commit()
                self.version += 1
                jobs.tick()
            jobs.tick()
        return len(rows)

    def delete(self, doc_ids: list[str], keep_files: bool = False) -> dict:
        removed = []
        for doc in doc_ids:
            rows = self._q("SELECT name FROM docs WHERE id = ?", (doc,))
            with self.lock:
                ids = [r[0] for r in self.db.execute("SELECT id FROM chunks WHERE doc = ?", (doc,))]
                self.db.executemany("DELETE FROM fts WHERE rowid = ?", [(i,) for i in ids])
                self.db.executemany("DELETE FROM mentions WHERE chunk = ?", [(i,) for i in ids])
                self.db.executemany("DELETE FROM rules WHERE chunk = ?", [(i,) for i in ids])
                self.db.execute("DELETE FROM chunks WHERE doc = ?", (doc,))
                self.db.execute("DELETE FROM links WHERE doc = ? OR target = ?", (doc, doc))
                self.db.execute("DELETE FROM docs WHERE id = ?", (doc,))
                self.db.execute("DELETE FROM concepts WHERE id NOT IN (SELECT concept FROM mentions)")
                self.db.execute("DELETE FROM aliases WHERE a NOT IN (SELECT id FROM concepts) OR b NOT IN (SELECT id FROM concepts)")
                self.db.commit()
                self.version += 1
                jobs.tick()
            jobs.tick()
            for f in sorted((self.assets / doc).glob("**/*"), reverse=True) if (self.assets / doc).exists() else []:
                f.unlink() if f.is_file() else f.rmdir()
            if (self.assets / doc).exists():
                (self.assets / doc).rmdir()
            if rows and not keep_files:
                for f in (cfg.path("originals") / rows[0]["name"], cfg.path("converted") / f"{rows[0]['name']}.md"):
                    f.unlink(missing_ok=True)
            if rows:
                removed.append(rows[0]["name"])
        return {"deleted": removed}

    def reindex(self, log=lambda *a, **k: None) -> dict:
        """Convert and index every original again (after a converter or passage-size change)."""
        files = sorted(p for p in cfg.path("originals").iterdir() if p.is_file())
        for n, f in enumerate(files):
            log(f"re-indexing {f.name}", n / max(1, len(files)))
            self.upload(f.name, f.read_bytes())
        return {"documents": len(files)}

    # ---------------------------------------------------------------- reading
    def documents(self) -> list[dict]:
        vec = {r[0]: r[1] for r in self._q("SELECT doc, count(vec) FROM chunks GROUP BY doc")}
        rules = {r[0]: r[1] for r in self._q("SELECT c.doc, count(*) FROM rules x JOIN chunks c ON c.id = x.chunk GROUP BY c.doc")}
        return [{"id": r["id"], "name": r["name"], "status": r["status"], "chunks": r["chunks"], "error": r["error"],
                 "vectors": vec.get(r["id"], 0), "rules": rules.get(r["id"], 0), "pictures": r["pictures"], "described": r["described"],
                 "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(r["updated"] or 0))}
                for r in self._q("SELECT * FROM docs ORDER BY updated DESC")]

    def pipeline(self) -> dict:
        return dict(self.activity)

    def markdown(self, name: str) -> str:
        f = cfg.path("converted") / f"{Path(name).name}.md"
        if not f.exists():
            raise KeyError(f"no converted Markdown for {name}")
        return f.read_text(encoding="utf-8")

    def _vectors(self) -> tuple[np.ndarray, np.ndarray]:
        if self._matrix is None or self._matrix[0] != self.version:
            rows = self._q("SELECT id, vec FROM chunks WHERE vec IS NOT NULL")
            ids = np.asarray([r[0] for r in rows], dtype=np.int64)
            mat = np.stack([np.frombuffer(r[1], dtype=np.int8) for r in rows]) if rows else np.zeros((0, 1), np.int8)
            self._matrix = (self.version, ids, mat)
        return self._matrix[1], self._matrix[2]

    # ---------------------------------------------------------------- search (no chat call)
    def search(self, query: str, keywords: list[str], chunks: int, top_k: int, concepts: list[str] | None = None) -> dict:
        terms = [fold(t) for t in (keywords or query.split()) if t.strip()][:24]
        phrases = [fold(c) for c in (concepts or []) if " " in c]
        qv = None
        lists: list[tuple[list[int], float, str]] = []
        match = " OR ".join('"' + re.sub(r'["]', " ", t) + '"' for t in terms + phrases if t.strip())
        if match:
            lists.append(([r[0] for r in self._q("SELECT rowid FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT 60",
                                                 (match,))], 1.0, "keywords"))
        sims: dict[int, float] = {}
        ids, mat = self._vectors()
        if len(ids):
            try:
                from .. import search as _search   # the question's one embedding, shared and budgeted
                v = _search.query_vector(query)
                qv = np.asarray(v, dtype=np.float32) / max(float(np.linalg.norm(v)), 1e-9) if v else None
                if qv is not None and qv.shape[0] == mat.shape[1]:
                    scores = (mat.astype(np.float32) @ qv) / 127.0
                    top = np.argsort(-scores)[:60]
                    sims = {int(ids[i]): round(float(scores[i]), 4) for i in top}
                    lists.append((list(sims), 1.0, "vectors"))
            except Exception:
                pass   # keyword and concept search still work without the embedding API
        keys = {k for t in terms + phrases for k in (t, concept_key(t, True), concept_key(t, False))}
        hit = [r["id"] for r in self._q(f"SELECT id FROM concepts WHERE key IN ({','.join('?' * len(keys))})", tuple(keys))] if keys else []
        if qv is not None:   # concepts the question means, in other words or the other language
            cids, cmat, _ = self._concept_matrix()
            if len(cids) and cmat.shape[1] == qv.shape[0]:
                cs = (cmat.astype(np.float32) @ qv) / 127.0
                hit += [int(cids[i]) for i in np.argsort(-cs)[:5] if cs[i] >= cfg.get("BRAIN_CONCEPT_SIM")]
        if hit:   # and the concepts that mean the same (aliases)
            hit += [r[0] for r in self._q(f"SELECT b FROM aliases WHERE a IN ({','.join('?' * len(hit))})", tuple(hit))]
            hit = list(dict.fromkeys(hit))
        if hit:
            lists.append(([r[0] for r in self._q(f"""SELECT chunk FROM mentions WHERE concept IN ({','.join('?' * len(hit))})
                GROUP BY chunk ORDER BY count(*) DESC LIMIT 60""", tuple(hit))], 0.5, "concepts"))
        score: dict[int, float] = {}
        how: dict[int, list[str]] = {}
        for ranked, weight, label in lists:
            for rank, cid in enumerate(ranked):
                score[cid] = score.get(cid, 0) + weight / (60 + rank)
                how.setdefault(cid, []).append(label)
        best = sorted(score, key=lambda c: -score[c])[:chunks]
        if not best:
            return {"chunks": [], "entities": [], "relations": [], "rules": []}
        q = ",".join("?" * len(best))
        rows = {r["id"]: r for r in self._q(f"""SELECT c.id, c.kind, c.path, c.page, c.text, d.name FROM chunks c
                                                JOIN docs d ON d.id = c.doc WHERE c.id IN ({q})""", tuple(best))}
        out_chunks = []
        for cid in best:
            r = rows.get(cid)
            if r is None:
                continue
            where = " › ".join(x for x in (r["name"], r["path"]) if x) + (f", p. {r['page']}" if r["page"] else "")
            out_chunks.append({"source": where, "doc": r["name"], "content": r["text"], "kind": r["kind"],
                               "matched": how[cid], **({"similarity": sims[cid]} if cid in sims else {})})
        cons = self._q(f"""SELECT k.id, k.name, k.kind, k.definition, k.key, count(*) n FROM mentions m JOIN concepts k ON k.id = m.concept
                           WHERE m.chunk IN ({q}) GROUP BY k.id ORDER BY (k.key IN ({','.join('?' * len(keys)) or "''"})) DESC,
                           n DESC, k.definition IS NULL LIMIT ?""", (*best, *keys, top_k))
        also = {}
        if cons:
            for r in self._q(f"""SELECT x.a, k.name FROM aliases x JOIN concepts k ON k.id = x.b
                                 WHERE x.a IN ({','.join('?' * len(cons))}) ORDER BY x.sim DESC""", tuple(c["id"] for c in cons)):
                also.setdefault(r[0], []).append(r[1])
        entities = [{"name": c["name"], "type": c["kind"], "description": c["definition"] or f"named in {c['n']} of these passages",
                     **({"aliases": also[c["id"]][:4]} if c["id"] in also else {})} for c in cons]
        names = [(c["name"], fold(c["name"])) for c in cons[:12]]
        facts, seen = [], set()
        for cid in best:
            r = rows.get(cid)
            for sentence in SENTENCE.split((r["text"] if r else "").replace("\n", " ")):
                fs = fold(sentence)
                inside = [n for n, f in names if f in fs]
                if len(inside) >= 2 and 20 < len(sentence) < 400 and (inside[0], inside[1]) not in seen:
                    seen.add((inside[0], inside[1]))
                    facts.append({"a": inside[0], "b": inside[1], "description": sentence.strip(), "source": r["name"]})
        order = {cid: i for i, cid in enumerate(best)}
        words = {stem(t) for t in terms} | set(terms)
        found = self._q(f"""SELECT x.chunk, x.kind, x.modality, x.text, x.limits, d.name, c.path, c.page FROM rules x
            JOIN chunks c ON c.id = x.chunk JOIN docs d ON d.id = c.doc WHERE x.chunk IN ({q})""", tuple(best))
        ranked = sorted(found, key=lambda r: (-sum(w in stemmed(r["text"]) for w in words), order[r["chunk"]]))
        rules = [{"text": r["text"], "modality": r["modality"], "kind": r["kind"],
                  "limits": [x for x in (r["limits"] or "").split("; ") if x],
                  "source": " › ".join(x for x in (r["name"], r["path"]) if x) + (f", p. {r['page']}" if r["page"] else "")}
                 for r in ranked[:max(top_k, 8)]]
        return {"chunks": out_chunks, "entities": entities, "relations": facts[:top_k], "rules": rules}

    # ---------------------------------------------------------------- graph for the UI
    def graph(self, label: str = "*", max_nodes: int = 600, depth: int = 3) -> dict:
        if label and label != "*":
            root = self._q("SELECT id FROM concepts WHERE key = ?", (fold(label),))
            if not root:
                return {"nodes": [], "links": [], "truncated": False}
            seeds, keep = {root[0]["id"]}, {root[0]["id"]}
            for _ in range(max(1, min(depth, 2))):
                q = ",".join("?" * len(seeds))
                near = self._q(f"""SELECT m2.concept c, count(*) n FROM mentions m1 JOIN mentions m2 ON m1.chunk = m2.chunk
                    WHERE m1.concept IN ({q}) AND m2.concept NOT IN ({q}) GROUP BY m2.concept ORDER BY n DESC LIMIT 40""",
                                   (*seeds, *seeds))
                seeds = {r["c"] for r in near} - keep
                keep |= seeds
                if len(keep) >= max_nodes or not seeds:
                    break
            concept_ids = list(keep)[:max_nodes]
        else:
            for least in (2, 1):   # concepts named in at least two passages; in a small library, all of them
                concept_ids = [r["concept"] for r in self._q("""SELECT concept, count(*) n FROM mentions GROUP BY concept
                    HAVING n >= ? ORDER BY n DESC LIMIT ?""", (least, int(max_nodes * 0.8)))]
                if len(concept_ids) >= 10:
                    break
        if not concept_ids:
            return {"nodes": [], "links": [], "truncated": False}
        q = ",".join("?" * len(concept_ids))
        cons = self._q(f"SELECT id, name, kind, definition FROM concepts WHERE id IN ({q})", tuple(concept_ids))
        docs = self._q(f"""SELECT d.id, d.name, k.concept, count(*) n FROM mentions k JOIN chunks c ON c.id = k.chunk
            JOIN docs d ON d.id = c.doc WHERE k.concept IN ({q}) GROUP BY d.id, k.concept""", tuple(concept_ids))
        pairs = self._q(f"""SELECT m1.concept a, m2.concept b, count(*) n FROM mentions m1 JOIN mentions m2
            ON m1.chunk = m2.chunk AND m1.concept < m2.concept WHERE m1.concept IN ({q}) AND m2.concept IN ({q})
            GROUP BY a, b HAVING n >= 2 ORDER BY n DESC LIMIT ?""", (*concept_ids, *concept_ids, max_nodes * 3))
        nodes = [{"id": f"c{c['id']}", "name": c["name"], "kind": c["kind"], "description": c["definition"] or ""} for c in cons]
        nodes += [{"id": d, "name": n, "kind": "document", "description": ""} for d, n in {(r["id"], r["name"]) for r in docs}]
        links = [{"source": r["id"], "target": f"c{r['concept']}", "type": "mentions", "description": f"{r['n']} passages"} for r in docs]
        links += [{"source": f"c{r['a']}", "target": f"c{r['b']}", "type": "related",
                   "description": f"named together in {r['n']} passages"} for r in pairs]
        links += [{"source": f"c{r['a']}", "target": f"c{r['b']}", "type": "same as", "description": f"similar meaning {r['sim']:.2f}"}
                  for r in self._q(f"SELECT a, b, sim FROM aliases WHERE a < b AND a IN ({q}) AND b IN ({q})",
                                   (*concept_ids, *concept_ids))]
        links += [{"source": r["doc"], "target": r["target"], "type": "refers to", "description": ""}
                  for r in self._q("SELECT doc, target FROM links")
                  if any(n["id"] == r["doc"] for n in nodes) and any(n["id"] == r["target"] for n in nodes)]
        return {"nodes": nodes, "links": links, "truncated": len(concept_ids) >= max_nodes * 0.8}

    def labels(self, q: str = "") -> list[str]:
        if q:
            return [r[0] for r in self._q("SELECT name FROM concepts WHERE key LIKE ? LIMIT 50", (f"%{fold(q)}%",))]
        return [r[0] for r in self._q("""SELECT k.name FROM concepts k JOIN mentions m ON m.concept = k.id
            GROUP BY k.id ORDER BY count(*) DESC LIMIT 50""")]


def _stop() -> set[str]:
    return {fold(w) for w in qa._stopwords()}


def _small_jpeg(data: bytes, edge: int = 1600) -> str:
    """The picture as base64 JPEG, at most `edge` pixels on its long side (fewer tokens for the vision model)."""
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    img.thumbnail((edge, edge))
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=85)
    return base64.b64encode(out.getvalue()).decode()
