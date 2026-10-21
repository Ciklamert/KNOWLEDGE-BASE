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
               AFTER the text is searchable: one call per picture, never one per chunk, at most BRAIN_VLM_MAX_PER_HOUR,
               oldest first. A picture seen before (same bytes, any document) reuses its description; tiny or
               one-colour pictures are skipped. Local OCR (ocr.py) reads the text of a picture at once when there is
               no vision model, when the vision call fails or times out, or when the hourly budget is used up; the
               vision model adds its description later.
Search (no chat call): BM25 + vectors + concept graph, fused by reciprocal rank; the answer carries the passages with
their document, section and page, the business rules in them, the concepts with their definitions and aliases, and
facts (sentences that join two concepts).
Everything lives in one SQLite file, data/docs/docs.db, plus the pictures in data/docs/assets/.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import sqlite3
import threading
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .. import jobs, llm, ocr as _ocr, query as qa
from .. import settings as cfg
from . import DocGraph, convert, docgrammar as dgr

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS docs(id TEXT PRIMARY KEY, name TEXT UNIQUE, status TEXT, error TEXT, chunks INT DEFAULT 0,
  pictures INT DEFAULT 0, described INT DEFAULT 0, chars INT DEFAULT 0, updated REAL);
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, doc TEXT, ord INT, kind TEXT, path TEXT, page INT,
  text TEXT, asset TEXT, vec BLOB);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(body, stem, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS cards(doc TEXT PRIMARY KEY, language TEXT, summary TEXT, dates TEXT, versions TEXT,
  numbers TEXT, effective TEXT, sig BLOB, near TEXT);
CREATE TABLE IF NOT EXISTS concepts(id INTEGER PRIMARY KEY, key TEXT UNIQUE, name TEXT, kind TEXT, definition TEXT);
CREATE TABLE IF NOT EXISTS mentions(concept INT, chunk INT, PRIMARY KEY(concept, chunk)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS mentions_chunk ON mentions(chunk);
CREATE TABLE IF NOT EXISTS links(doc TEXT, target TEXT, PRIMARY KEY(doc, target)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, chunk INT, kind TEXT, modality TEXT, text TEXT, limits TEXT);
CREATE INDEX IF NOT EXISTS rules_chunk ON rules(chunk);
CREATE TABLE IF NOT EXISTS aliases(a INT, b INT, sim REAL, PRIMARY KEY(a, b)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS units(id INTEGER PRIMARY KEY, doc TEXT, ord INT, parent INT, kind TEXT, key TEXT, label TEXT,
  title TEXT, path TEXT, page INT, text TEXT, chunk INT);
CREATE INDEX IF NOT EXISTS units_doc ON units(doc, key);
CREATE INDEX IF NOT EXISTS units_key ON units(key);
CREATE TABLE IF NOT EXISTS refs(id INTEGER PRIMARY KEY, doc TEXT, unit INT, kind TEXT, key TEXT, raw TEXT, target INT, amend TEXT);
CREATE INDEX IF NOT EXISTS refs_unit ON refs(unit);
CREATE INDEX IF NOT EXISTS refs_target ON refs(target);
CREATE INDEX IF NOT EXISTS refs_key ON refs(key);
CREATE TABLE IF NOT EXISTS defs(id INTEGER PRIMARY KEY, doc TEXT, unit INT, term TEXT, key TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS defs_key ON defs(key);
CREATE TABLE IF NOT EXISTS seen(sha TEXT PRIMARY KEY, text TEXT, by TEXT, at REAL) WITHOUT ROWID;
"""
RULE_SLOTS = ("actor", "action", "object", "condition", "exception", "unit", "confidence")
ANALYSIS = "3"   # version of the concept and rule analysis; a stored index of another version is re-analysed
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
PERMIT = re.compile(r"\b(?:may|MAY|OPTIONAL|is\s+permitted\s+to|are\s+permitted\s+to|is\s+allowed\s+to|are\s+allowed\s+to)\b|"
                    r"\w+[ae]bilir(?:ler)?\b|izin\s+verilir|yetkilidir", re.I)
# Turkish official texts state duties in the passive aorist at the end of the sentence: "olay kaydı açılır", "kayıtlar
# saklanır", "erişim hakları kaldırılır" (= shall be opened / kept / removed)
TR_NORMATIVE = re.compile(r"\b\w+(?:[ıiuü]l|[ıiuü]n|l|n)[ıiuü]r$")
NUMBER = r"(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?"
UNIT = (r"(?:TL|TRY|₺|USD|EUR|€|\$|%|yüzde|iş\s+günü|gün|saat|dakika|saniye|hafta|ay|yıl|adet|kez|defa|"
        r"business\s+days?|days?|hours?|minutes?|seconds?|weeks?|months?|years?|times|items?)")
LIMIT = re.compile(rf"(?:(?:en\s+az|en\s+fazla|en\s+geç|at\s+least|at\s+most|up\s+to|no\s+later\s+than|more\s+than|"
                   rf"less\s+than|over|above|below|under|within|maximum|minimum)\s+)?(?:(?:%|yüzde)\s*{NUMBER}|{NUMBER}\s*{UNIT}"
                   rf"(?:['’]?[a-zçğıöşü]{{0,4}})?)(?:\s+(?:üzeri\w*|üstü\w*|altı\w*|içinde\w*|içerisinde|sonra\w*|önce\w*|"
                   rf"fazla\w*|az\w*|kadar|aşan|geçen|geçmeyen|or\s+more|or\s+less))?", re.I)
OCR_LABEL = "Text in the picture (OCR):"
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


TR_SUFFIXES = sorted({fold(x) for x in qa.TR_SUFFIXES} | {"na", "ne", "ya", "ye", "nin", "nun", "ndan", "nde", "nda"},
                     key=len, reverse=True)
_english = threading.local()


def stem(word: str, turkish: bool = True) -> str:
    """The stem of a folded word, the same for every inflected form.
    Turkish: one case, plural or possessive suffix (at least four letters stay), then one final vowel (a case or
    possessive vowel, or the word's own) and consonant softening undone: onay, onayı, onaya, onayının -> onay;
    müşteri, müşteriler -> muster; talep, talebi -> talep. Measured on 112 forms of official-document nouns: no form
    split apart, no two words joined; Snowball's Turkish stemmer split 22 of them.
    English: Snowball (Porter 2): refunds, refunded -> refund; approval, approved -> approv."""
    if not turkish:
        if not hasattr(_english, "s"):
            import snowballstemmer
            _english.s = snowballstemmer.stemmer("english")
        return _english.s.stemWord(word)
    for suf in TR_SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            word = word[: -len(suf)]
            break
    if len(word) >= 5 and word[-1] in "aeiou":
        word = word[:-1]
    if len(word) >= 3 and word[-1] in "bdg":
        word = word[:-1] + {"b": "p", "d": "t", "g": "k"}[word[-1]]
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
                        else "recommendation" if ADVISE.search(sentence) else "permission" if PERMIT.search(sentence)
                        else "obligation" if TR_NORMATIVE.search(sentence.rstrip(" .")) else "limit" if limits else "")
            if modality:
                out.append({"kind": "rule", "modality": modality, "text": sentence, "limits": limits[:4]})
    return out


def _turkish(text: str) -> bool:
    return qa.analyze(text[:4000])["language"] in ("tr", "mixed")


# ---------------------------------------------------------------- document cards (no model)
MONTHS = {m: i + 1 for i, names in enumerate(
    ["ocak january jan", "şubat subat february feb", "mart march mar", "nisan april apr", "mayıs mayis may", "haziran june jun",
     "temmuz july jul", "ağustos agustos august aug", "eylül eylul september sep sept", "ekim october oct",
     "kasım kasim november nov", "aralık aralik december dec"]) for m in names.split()}
DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b|"
                  r"\b(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{4})\b|\b([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\b")
EFFECTIVE = re.compile(r"yürürlük|geçerlilik|geçerli|yayım|onay tarihi|revizyon tarihi|effective|valid from|issued|"
                       r"approved on|revision date", re.I)
VERSION = re.compile(r"\b(?:versiyon|sürüm|revizyon|rev\.?|version|v)\s*(?:no\.?|:)?\s*(\d+(?:\.\d+){0,2})\b", re.I)
DOC_NUMBER = re.compile(r"\b(?:doküman|döküman|belge|doc(?:ument)?|form|prosedür|procedure)\s*(?:no|numarası|number|kodu|code)"
                        r"\s*[:.]?\s*([A-Z0-9][A-Z0-9./-]{2,20})|\b([A-Z]{2,5}-\d{2,5}(?:-\d{1,3})?)\b", re.I)


def doc_facts(md: str) -> dict:
    """Dates (ISO), the effective date (the date next to "yürürlük", "effective" ...), version numbers and document
    numbers found in a document."""
    dates, effective = [], None
    for m in DATE.finditer(md):
        g = m.groups()
        try:
            if g[0]:
                d, mo, y = int(g[0]), int(g[1]), int(g[2])
            elif g[3]:
                y, mo, d = int(g[3]), int(g[4]), int(g[5])
            elif g[6]:
                d, mo, y = int(g[6]), MONTHS.get(lower(g[7]), 0), int(g[8])
            else:
                mo, d, y = MONTHS.get(lower(g[9]), 0), int(g[10]), int(g[11])
        except ValueError:
            continue
        if not (1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100):
            continue
        iso = f"{y:04d}-{mo:02d}-{d:02d}"
        dates.append(iso)
        if effective is None and EFFECTIVE.search(md[max(0, m.start() - 60):m.start()]):
            effective = iso
    numbers = [a or b for a, b in DOC_NUMBER.findall(md)]
    return {"dates": sorted(set(dates))[-12:], "effective": effective, "versions": list(dict.fromkeys(VERSION.findall(md)))[:6],
            "numbers": list(dict.fromkeys(n.strip(".-/") for n in numbers if n))[:6]}


def central_sentences(text: str, turkish: bool, n: int = 4) -> list[str]:
    """The n most central sentences of a document, in document order (LexRank over TF-IDF of stemmed words): an
    extractive summary without a model."""
    sents = [s.strip() for line in text.splitlines() if not line.lstrip().startswith(("|", "#", "!", "<!--"))
             for s in SENTENCE.split(line) if 40 <= len(s.strip()) <= 400][:300]
    if len(sents) <= n:
        return sents
    bags = [Counter(stemmed(s, turkish).split()) for s in sents]
    df = Counter(w for b in bags for w in b)
    idf = {w: np.log(len(sents) / c) for w, c in df.items()}
    vocab = {w: i for i, w in enumerate(idf)}
    m = np.zeros((len(sents), len(vocab)), dtype=np.float32)
    for i, b in enumerate(bags):
        for w, c in b.items():
            m[i, vocab[w]] = c * idf[w]
    m /= np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
    sim = (m @ m.T > 0.1).astype(np.float32)
    sim /= np.maximum(sim.sum(axis=1, keepdims=True), 1)
    p = np.full(len(sents), 1.0 / len(sents))
    for _ in range(30):
        p = 0.15 / len(sents) + 0.85 * sim.T @ p
    return [sents[i] for i in sorted(np.argsort(-p)[:n])]


def minhash(text: str, k: int = 64) -> np.ndarray:
    """A 64-number MinHash signature of the document's 5-word shingles: near-identical documents (versions of the
    same procedure) have mostly equal numbers."""
    words = re.findall(r"\w+", fold(text))
    shingles = {" ".join(words[i:i + 5]) for i in range(max(1, len(words) - 4))}
    h = np.asarray([int(hashlib.blake2b(s.encode(), digest_size=8).hexdigest(), 16) for s in shingles], dtype=np.uint64)
    rng = np.random.default_rng(42)
    a = rng.integers(1, 2**61 - 1, size=k, dtype=np.uint64) | np.uint64(1)
    b = rng.integers(0, 2**61 - 1, size=k, dtype=np.uint64)
    return np.min((h[:, None] * a[None, :] + b[None, :]), axis=0)


def _version_key(card: dict) -> tuple:
    v = max(([int(x) for x in s.split(".")] for s in card.get("versions") or []), default=[])
    return (v, card.get("effective") or max(card.get("dates") or [""], default=""))


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
        self._graph: tuple | None = None   # (version, passage-concept graph as arrays) for Personalized PageRank
        self._themes: tuple | None = None   # (version, themes)
        self._cards: tuple | None = None    # (version, document cards)
        self.version = 0
        self._completing = threading.Lock()

    # ---------------------------------------------------------------- life cycle
    def start(self) -> None:
        with self.lock:
            self.db = sqlite3.connect(self.dir / "docs.db", check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.executescript(SCHEMA)
            if "stem" not in [d[0] for d in self.db.execute("SELECT * FROM fts LIMIT 0").description]:
                self.db.execute("DROP TABLE fts")   # an index without the stemmed column: rebuilt by reanalyse()
                self.db.executescript(SCHEMA)
                self.db.execute("DELETE FROM meta WHERE key = 'analysis'")
            have = [r[1] for r in self.db.execute("PRAGMA table_info(rules)")]
            for col in RULE_SLOTS:
                if col not in have:
                    self.db.execute(f"ALTER TABLE rules ADD COLUMN {col} {'INT' if col == 'unit' else 'TEXT'}")
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
        threading.Thread(target=self._every, daemon=True, name="docgraph-complete").start()

    def _every(self) -> None:
        """complete() at start, then every 10 minutes: finishes what waited for the API (a failed or slow call, the
        hourly vision budget) without a new upload."""
        while self.db is not None:
            try:
                self.complete()
            except Exception as exc:   # stopped meanwhile, or a bug: try again at the next round
                self._say(f"completion failed: {exc}", busy=False)
            time.sleep(600)

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
            rows, turkish = [], _turkish(md)
            for n, p in enumerate(parts):
                cur = db.execute("INSERT INTO chunks(doc, ord, kind, path, page, text, asset) VALUES (?,?,?,?,?,?,?)",
                                 (doc, n, p["kind"], p["path"], p["page"], p["text"], p["asset"]))
                body = f"{name} {p['path']} {p['text']}"
                db.execute("INSERT INTO fts(rowid, body, stem) VALUES (?, ?, ?)", (cur.lastrowid, fold(body), stemmed(body, turkish)))
                rows.append((cur.lastrowid, p["kind"], p["text"]))
            self._analyse(db, rows, md)
            self._grammar(db, doc, name, md, rows)
            self._card(db, doc, md)
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
        turkish = _turkish(md)
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
            db.executescript("DELETE FROM mentions; DELETE FROM concepts; DELETE FROM rules; DELETE FROM aliases; "
                             "DELETE FROM fts; DELETE FROM cards; DELETE FROM units; DELETE FROM refs; DELETE FROM defs;")
            for doc, name in db.execute("SELECT id, name FROM docs").fetchall():
                rows = db.execute("SELECT id, kind, text, path FROM chunks WHERE doc = ? ORDER BY ord", (doc,)).fetchall()
                md = "\n\n".join(r[2] for r in rows)
                turkish = _turkish(md)
                db.executemany("INSERT INTO fts(rowid, body, stem) VALUES (?, ?, ?)",
                               [(r[0], fold(f"{name} {r[3]} {r[2]}"), stemmed(f"{name} {r[3]} {r[2]}", turkish)) for r in rows])
                self._analyse(db, [tuple(r[:3]) for r in rows], md)
                conv = cfg.path("converted") / f"{name}.md"   # the converted Markdown keeps headings and page markers
                self._grammar(db, doc, name, conv.read_text(encoding="utf-8") if conv.exists() else md, [tuple(r[:3]) for r in rows])
                self._card(db, doc, md)
            db.execute("INSERT OR REPLACE INTO meta VALUES ('analysis', ?)", (ANALYSIS,))
            db.commit()
            self.version += 1
        jobs.tick()

    # ---------------------------------------------------------------- document grammar (no model)
    def _grammar(self, db: sqlite3.Connection, doc: str, name: str, md: str, rows: list[tuple[int, str, str]]) -> None:
        """Units, references, definitions and statement slots of one document (brain/providers/docgrammar.py)."""
        lines, turkish = dgr.normalize_lines(md), _turkish(md)
        units = dgr.parse_units(md)
        chunks = [(cid, fold(text)) for cid, _, text in rows]

        def chunk_of(text: str) -> int | None:
            probe = fold(" ".join(text.split()[:12]))[:80]
            return next((cid for cid, t in chunks if probe and probe in " ".join(t.split())), None)
        ids: dict[int, int] = {}
        by_key: dict[str, int] = {}
        for u in units:
            body = "\n".join(lines[u["start"]:u["end"]])[:20000]
            first = next((l for l in lines[u["start"]:u["end"]] if l.strip() and not l.startswith("<!--")), "")
            cur = db.execute("INSERT INTO units(doc, ord, parent, kind, key, label, title, path, page, text, chunk) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (doc, u["i"], ids.get(u["parent"]), u["kind"], u["key"], u["label"], u["title"], u["path"], u["page"],
                              body, chunk_of(first) or chunk_of(" ".join(body.split()[3:20]))))
            ids[u["i"]] = cur.lastrowid
            by_key.setdefault(u["key"], cur.lastrowid)

        def resolve(key: str) -> int | None:
            while key:
                if key in by_key:
                    return by_key[key]
                key = key.rpartition("/")[0]
            return None
        children = {}
        for u in units:
            children.setdefault(u["parent"], []).append(u)
        defs_ctx = set()
        for u in units:
            own_end = min([c["start"] for c in children.get(u["i"], [])] + [u["end"]])
            own = "\n".join(lines[u["start"]:own_end])
            anc, p = [], u
            while p is not None:
                anc.append(p)
                p = units[p["parent"]] if p["parent"] is not None else None
            ctx = {"article": next((a["key"] for a in anc if a["kind"] in ("article", "section")), None),
                   "paragraph": next((a["key"] for a in anc if a["kind"] == "paragraph"), None)}
            in_defs = any(dgr.DEF_CONTEXT.search(a["title"] or "") or dgr.DEF_CONTEXT.search(
                "\n".join(lines[a["start"]:a["start"] + 2])) for a in anc)
            if in_defs:
                defs_ctx.add(u["i"])
            sentences = [x for line in own.splitlines() for x in dgr.SENT.split(line)]
            for sent in sentences:
                kind = dgr.amendment(sent)
                for r in dgr.find_refs(sent, ctx):
                    if r["key"] == u["key"]:
                        continue
                    target = resolve(r["key"]) if r["kind"] == "unit" else by_key.get(r["key"]) if r["kind"] == "requirement" else None
                    db.execute("INSERT INTO refs(doc, unit, kind, key, raw, target, amend) VALUES (?,?,?,?,?,?,?)",
                               (doc, ids[u["i"]], r["kind"], r["key"], r["raw"][:200], target, kind))
            for term, text in dgr.find_definitions(own, in_defs):
                db.execute("INSERT INTO defs(doc, unit, term, key, text) VALUES (?,?,?,?,?)",
                           (doc, ids[u["i"]], term, concept_key(term, turkish), text[:600]))
        # statements: slots for the rules found in the passages, user stories, acceptance criteria
        spans = sorted(((u["start"], u["end"], ids[u["i"]], u["lvl"]) for u in units), key=lambda x: -x[3])
        folded_lines = [fold(l) for l in lines]

        def unit_of(text: str) -> int | None:
            probe = fold(dgr.core(text))[:50]
            hit = next((n for n, l in enumerate(folded_lines) if probe and probe in l), None)
            if hit is None:
                return None
            return next((uid for a, b, uid, _ in spans if a <= hit < b), None)
        q = ",".join("?" * len(rows)) or "NULL"
        for rid, text, modality in db.execute(f"SELECT id, text, modality FROM rules WHERE chunk IN ({q}) AND kind = 'rule'",
                                              tuple(r[0] for r in rows)).fetchall():
            st = dgr.parse_statement(text, turkish, modality)
            db.execute("UPDATE rules SET actor=?, action=?, object=?, condition=?, exception=?, unit=?, confidence=?, kind=?, "
                       "modality=COALESCE(?, modality) WHERE id = ?",
                       (st["actor"], st["action"], st["object"], st["condition"], st["exception"], unit_of(text),
                        st["confidence"], st["kind"], st["modality"], rid))
        extra = [dgr.parse_statement(l, turkish) | {"text": l.strip(" -*")} for l in lines
                 if dgr.STORY_EN.match(l.strip(" -*")) or dgr.STORY_TR.match(l.strip(" -*"))] + dgr.gherkin(lines)
        for st in extra:
            db.execute("INSERT INTO rules(chunk, kind, modality, text, limits, actor, action, object, condition, exception, unit, confidence) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (chunk_of(st["text"]), st["kind"], st["modality"], st["text"][:500], "", st["actor"], st["action"], st["object"],
                        st["condition"], st["exception"], unit_of(st["text"]), st["confidence"]))
        # references become graph links: a "reference" concept joins the referring passage and the referred one, so
        # Personalized PageRank follows "5 inci madde", "Section 3.1" and "REQ-004" like any shared concept
        for src_chunk, tgt_chunk, label in db.execute("""SELECT s.chunk, t.chunk, t.label FROM refs r JOIN units s ON s.id = r.unit
                JOIN units t ON t.id = r.target WHERE r.doc = ? AND s.chunk IS NOT NULL AND t.chunk IS NOT NULL
                AND s.chunk != t.chunk""", (doc,)).fetchall():
            key = f"ref:{doc}:{label}"
            db.execute("INSERT OR IGNORE INTO concepts(key, name, kind) VALUES (?,?,?)", (key, f"{label} ({name})", "reference"))
            for c in (src_chunk, tgt_chunk):
                db.execute("INSERT OR IGNORE INTO mentions SELECT id, ? FROM concepts WHERE key = ?", (c, key))

    def _find_units(self, document: str | None, unit: str) -> list[sqlite3.Row]:
        keys = dgr.unit_keys(unit)
        if not keys:
            return []
        q = ",".join("?" * len(keys))
        rows = self._q(f"""SELECT u.*, d.name AS docname FROM units u JOIN docs d ON d.id = u.doc WHERE u.key IN ({q})
                           {"AND d.name = ?" if document else ""} ORDER BY length(u.key) DESC""",
                       (*keys, *([document] if document else [])))
        return rows

    def doc_query(self, mode: str, document: str | None = None, unit: str | None = None, term: str | None = None,
                  actor: str | None = None, query: str | None = None, limit: int = 30) -> dict:
        """The `doc` tool: outline | unit | refs | define | obligations | impact | list. Returns {text, data}."""
        mode = (mode or "list").lower()
        if mode == "list":
            docs = self.documents()
            lines = [f"{d['name']}: {d['chunks']} passages, {d.get('rules', 0)} rules"
                     + (f", v{d['versions'][0]}" if d.get("versions") else "") + (f", effective {d['effective']}" if d.get("effective") else "")
                     + (f" (older version; newer: {d['superseded_by']})" if d.get("superseded_by") else "") for d in docs]
            return {"text": "\n".join(lines) or "No documents.", "data": docs}
        if mode == "outline":
            doc = self._q("SELECT id, name FROM docs WHERE name = ?", (document or "",))
            if not doc:
                return {"text": f"No document named {document!r}. Use mode=list.", "data": []}
            rows = self._q("""SELECT u.id, u.kind, u.label, u.title, u.page, u.parent,
                (SELECT count(*) FROM refs r WHERE r.target = u.id) refs_in, (SELECT count(*) FROM rules x WHERE x.unit = u.id) rules
                FROM units u WHERE u.doc = ? ORDER BY u.ord""", (doc[0]["id"],))
            depth = {}
            out = []
            for r in rows:
                depth[r["id"]] = depth.get(r["parent"], -1) + 1
                extra = ", ".join(x for x in (f"{r['rules']} rules" if r["rules"] else "", f"referred to {r['refs_in']}x" if r["refs_in"] else "",
                                              f"p. {r['page']}" if r["page"] else "") if x)
                out.append("  " * depth[r["id"]] + f"- {r['label']}" + (f" {r['title']}" if r["title"] and r["kind"] != "section" or (r["kind"] == "section" and r["title"] != r["label"]) else "")
                           [:150] + (f" ({extra})" if extra else ""))
            return {"text": "\n".join(out[:400]) or "No structure found (the document has no numbered units or headings).",
                    "data": [dict(r) for r in rows]}
        if mode in ("unit", "refs", "impact"):
            found = self._find_units(document, unit or "")
            if not found:
                return {"text": f"No unit {unit!r}" + (f" in {document}" if document else "") + ". Use mode=outline.", "data": []}
            u = found[0]
            out_refs = self._q("""SELECT r.kind, r.key, r.raw, r.amend, t.label, d.name FROM refs r LEFT JOIN units t ON t.id = r.target
                LEFT JOIN docs d ON d.id = t.doc WHERE r.unit = ?""", (u["id"],))
            in_refs = self._q("""SELECT s.label, s.path, d.name, r.raw, r.amend FROM refs r JOIN units s ON s.id = r.unit JOIN docs d ON d.id = s.doc
                WHERE r.target = ? OR (r.kind = 'requirement' AND r.key = ? AND r.unit != ?)""", (u["id"], u["key"], u["id"]))
            lines = [f"### {u['path']} — {u['docname']}" + (f", p. {u['page']}" if u["page"] else "")]
            if mode == "unit":
                lines.append(u["text"][:4000])
            if out_refs:
                lines.append("refers to: " + "; ".join(f"{r['label'] or r['raw']}" + (f" ({r['name']})" if r["name"] and r["name"] != u["docname"] else "")
                                                       + (f" [{r['amend']}]" if r["amend"] else "") for r in out_refs[:limit]))
            if in_refs:
                lines.append("referred to by: " + "; ".join(f"{r['path']}" + (f" ({r['name']})" if r["name"] != u["docname"] else "")
                                                           + (f" [{r['amend']}]" if r["amend"] else "") for r in in_refs[:limit]))
            if mode in ("unit", "impact"):
                sts = self._q("SELECT modality, actor, action, object, condition, text FROM rules WHERE unit = ?", (u["id"],))
                if sts:
                    lines.append("statements:\n" + "\n".join(f"- [{s['modality']}] {s['text'][:200]}" for s in sts[:limit]))
            if mode == "impact":
                inside = [r[0] for r in self._q("SELECT id FROM units WHERE doc = ? AND (id = ? OR path LIKE ?)",
                                                (u["doc"], u["id"], u["path"] + " › %"))]
                q = ",".join("?" * len(inside))
                deeper = self._q(f"""SELECT DISTINCT s.path, d.name FROM refs r JOIN units s ON s.id = r.unit JOIN docs d ON d.id = s.doc
                    WHERE r.target IN ({q}) AND r.target != ?""", (*inside, u["id"]))
                if deeper:
                    lines.append("its parts are referred to by: " + "; ".join(f"{r['path']} ({r['name']})" for r in deeper[:limit]))
                terms = self._q(f"SELECT key, term FROM defs WHERE unit IN ({q})", tuple(inside))
                for t in terms:
                    users = self._q("""SELECT DISTINCT d.name FROM concepts k JOIN mentions m ON m.concept = k.id JOIN chunks c ON c.id = m.chunk
                        JOIN docs d ON d.id = c.doc WHERE k.key = ?""", (t["key"],))
                    if users:
                        lines.append(f"defined term '{t['term']}' used in: " + ", ".join(x[0] for x in users[:limit]))
                second = self._q(f"""SELECT DISTINCT s.path, d.name FROM refs r JOIN units s ON s.id = r.unit JOIN docs d ON d.id = s.doc
                    WHERE r.target IN (SELECT r2.unit FROM refs r2 WHERE r2.target = ?)""", (u["id"],))
                if second:
                    lines.append("indirectly (2 hops): " + "; ".join(f"{r['path']} ({r['name']})" for r in second[:limit]))
            return {"text": "\n".join(lines), "data": {"unit": dict(u), "refers_to": [dict(r) for r in out_refs],
                                                       "referred_by": [dict(r) for r in in_refs]}}
        if mode == "define":
            key = concept_key(term or "", True)
            rows = self._q("""SELECT x.term, x.text, u.path, d.name FROM defs x LEFT JOIN units u ON u.id = x.unit JOIN docs d ON d.id = x.doc
                WHERE x.key IN (?, ?) OR lower(x.term) = lower(?)""", (key, concept_key(term or "", False), term or ""))
            con = self._q("SELECT name, definition FROM concepts WHERE key IN (?, ?) AND definition IS NOT NULL",
                          (key, concept_key(term or "", False)))
            uses = self._q("""SELECT d.name, c.path, c.page FROM concepts k JOIN mentions m ON m.concept = k.id JOIN chunks c ON c.id = m.chunk
                JOIN docs d ON d.id = c.doc WHERE k.key IN (?, ?) LIMIT ?""", (key, concept_key(term or "", False), limit))
            lines = [f"- **{r['term']}** ({r['name']}" + (f" › {r['path']}" if r["path"] else "") + f"): {r['text']}" for r in rows]
            lines += [f"- **{c['name']}** (glossary): {c['definition']}" for c in con]
            if uses:
                lines.append("used in: " + "; ".join(f"{u['name']}" + (f" › {u['path']}" if u["path"] else "") for u in uses))
            return {"text": "\n".join(lines) or f"No definition of {term!r} found.", "data": {"definitions": [dict(r) for r in rows],
                                                                                          "uses": [dict(u) for u in uses]}}
        if mode == "obligations":
            where, args = ["x.modality IS NOT NULL", "x.kind != 'table row'"], []
            if document:
                where.append("d.name = ?")
                args.append(document)
            rows = self._q(f"""SELECT x.kind, x.modality, x.actor, x.action, x.object, x.condition, x.exception, x.limits, x.text,
                x.confidence, u.path, d.name FROM rules x JOIN chunks c ON c.id = x.chunk JOIN docs d ON d.id = c.doc
                LEFT JOIN units u ON u.id = x.unit WHERE {' AND '.join(where)}""", tuple(args))
            if actor:
                ak = {stem(w, tr) for w in re.findall(r"\w+", fold(actor)) for tr in (True, False)}
                rows = [r for r in rows if ak & {stem(w, tr) for w in re.findall(r"\w+", fold(f"{r['actor'] or ''} {r['object'] or ''} {r['text']}"))
                                                 for tr in (True, False)}]
            if query:
                qk = {stem(w, tr) for w in re.findall(r"\w{3,}", fold(query)) for tr in (True, False)}
                rows = sorted((r for r in rows if qk & set(stemmed(r["text"], True).split() + stemmed(r["text"], False).split())),
                              key=lambda r: -len(qk & set(stemmed(r["text"], True).split())))
            lines = [f"- [{r['modality']}] " + (f"**{r['actor']}** → " if r["actor"] else "") + f"{r['action'] or ''}"
                     + (f" {r['object']}" if r["object"] else "") + (f" · if {r['condition']}" if r["condition"] else "")
                     + (f" · {r['exception']}" if r["exception"] else "") + (f" · limits: {r['limits']}" if r["limits"] else "")
                     + f" ({r['name']}" + (f" › {r['path']}" if r["path"] else "") + ")" for r in rows[:limit]]
            return {"text": "\n".join(lines) or "No matching statements.", "data": [dict(r) for r in rows[:limit]]}
        return {"text": f"unknown mode {mode}; use list, outline, unit, refs, define, obligations or impact", "data": []}

    def _card(self, db: sqlite3.Connection, doc: str, md: str) -> None:
        """The document card: central sentences, dates, effective date, versions, document numbers, and the documents
        that are near-identical to it (MinHash of 5-word shingles, at least half equal: other versions)."""
        facts, sig = doc_facts(md), minhash(md)
        near = []
        for other, osig, onear in db.execute("SELECT doc, sig, near FROM cards WHERE doc != ?", (doc,)).fetchall():
            sim = float(np.mean(np.frombuffer(osig, dtype=np.uint64) == sig)) if osig else 0.0
            if sim >= 0.5:
                near.append({"doc": other, "similarity": round(sim, 2)})
                theirs = [x for x in json.loads(onear or "[]") if x["doc"] != doc] + [{"doc": doc, "similarity": round(sim, 2)}]
                db.execute("UPDATE cards SET near = ? WHERE doc = ?", (json.dumps(theirs), other))
        db.execute("INSERT OR REPLACE INTO cards VALUES (?,?,?,?,?,?,?,?,?)",
                   (doc, "tr" if _turkish(md) else "en", json.dumps(central_sentences(md, _turkish(md)), ensure_ascii=False),
                    json.dumps(facts["dates"]), json.dumps(facts["versions"]), json.dumps(facts["numbers"], ensure_ascii=False),
                    facts["effective"], sig.tobytes(), json.dumps(near)))

    def cards(self, doc_ids: list[str] | None = None) -> dict[str, dict]:
        """{doc id: card}, with `superseded_by` (a near-identical document with a higher version or later date) and
        `versions_of` (all near-identical documents). Cached until the index changes."""
        if self._cards is not None and self._cards[0] == self.version:
            return {d: c for d, c in self._cards[1].items() if doc_ids is None or d in doc_ids}
        names = {r[0]: r[1] for r in self._q("SELECT id, name FROM docs")}
        rows = self._q("SELECT * FROM cards")
        raw = {r["doc"]: {"name": names.get(r["doc"], r["doc"]), "language": r["language"],
                          "summary": json.loads(r["summary"] or "[]"), "dates": json.loads(r["dates"] or "[]"),
                          "versions": json.loads(r["versions"] or "[]"), "numbers": json.loads(r["numbers"] or "[]"),
                          "effective": r["effective"], "near": [x for x in json.loads(r["near"] or "[]") if x["doc"] in names]}
               for r in rows if r["doc"] in names}
        for doc, c in raw.items():
            c["versions_of"] = [raw[x["doc"]]["name"] for x in c["near"] if x["doc"] in raw]
            newer = [raw[x["doc"]] for x in c["near"] if x["doc"] in raw and _version_key(raw[x["doc"]]) > _version_key(c)]
            c["superseded_by"] = max(newer, key=_version_key)["name"] if newer else None
        self._cards = (self.version, raw)
        return {d: c for d, c in raw.items() if doc_ids is None or d in doc_ids}

    def themes(self, limit: int = 20) -> list[dict]:
        """Themes across the library without a model: communities of the concept graph (label propagation over
        concepts named together), each named by its most mentioned concepts, with the documents that discuss it."""
        if self._themes is not None and self._themes[0] == self.version:
            return self._themes[1][:limit]
        pairs = self._q("""SELECT m1.concept a, m2.concept b, count(*) n FROM mentions m1 JOIN mentions m2
            ON m1.chunk = m2.chunk AND m1.concept < m2.concept
            WHERE m1.concept IN (SELECT id FROM concepts WHERE kind != 'reference')
              AND m2.concept IN (SELECT id FROM concepts WHERE kind != 'reference')
            GROUP BY a, b HAVING n >= 1 ORDER BY n DESC LIMIT 20000""")
        nbr: dict[int, dict[int, int]] = {}
        for r in pairs:
            nbr.setdefault(r["a"], {})[r["b"]] = r["n"]
            nbr.setdefault(r["b"], {})[r["a"]] = r["n"]
        label = {c: c for c in nbr}
        order = sorted(nbr, key=lambda c: -len(nbr[c]))
        for _ in range(10):   # label propagation: each concept takes the label most of its weighted neighbours carry
            moved = 0
            for c in order:
                votes: Counter = Counter()
                for o, w in nbr[c].items():
                    votes[label[o]] += w
                best = max(votes.items(), key=lambda kv: (kv[1], -kv[0]))[0] if votes else label[c]
                if best != label[c]:
                    label[c], moved = best, moved + 1
            if not moved:
                break
        groups: dict[int, list[int]] = {}
        for c, l in label.items():
            groups.setdefault(l, []).append(c)
        counts = {r[0]: r[1] for r in self._q("SELECT concept, count(*) FROM mentions GROUP BY concept")}
        cname = {r[0]: r[1] for r in self._q("SELECT id, name FROM concepts")}
        out = []
        for members in sorted(groups.values(), key=lambda m: -sum(counts.get(c, 0) for c in m)):
            if len(members) < 2:
                continue
            top = sorted(members, key=lambda c: -counts.get(c, 0))
            q = ",".join("?" * len(members))
            docs = [r[0] for r in self._q(f"""SELECT d.name FROM mentions m JOIN chunks c ON c.id = m.chunk JOIN docs d
                ON d.id = c.doc WHERE m.concept IN ({q}) GROUP BY d.id ORDER BY count(*) DESC LIMIT 8""", tuple(members))]
            out.append({"label": ", ".join(cname.get(c, "?") for c in top[:3]), "concepts": [cname.get(c, "?") for c in top[:12]],
                        "size": len(members), "documents": docs})
        self._themes = (self.version, out)
        return out[:limit]

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
                pictures = self._describe_pictures()
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
        """Gives every picture a text, oldest first; returns how many changed (-1 when the vision call failed).
        Kinds: picture (waiting) -> figure (vision description, final) | ocr (OCR text, upgraded by the vision model
        later) | decor (tiny or one colour, skipped). Descriptions are cached by the picture's SHA-1 (table seen)."""
        vision = bool(cfg.get("BRAIN_VLM_MODEL") and cfg.get("BRAIN_LLM_BASE_URL"))
        ocr_ok = _ocr.available()
        kinds = "('picture', 'ocr')" if vision else "('picture')"
        rows = self._q(f"""SELECT c.id, c.doc, c.asset, c.path, c.text, c.kind, d.name FROM chunks c JOIN docs d
                           ON d.id = c.doc WHERE c.kind IN {kinds} AND c.asset IS NOT NULL
                           ORDER BY c.kind = 'ocr', c.id""")
        done, failed = 0, False
        for n, r in enumerate(rows, 1):
            f = self.assets / r["doc"] / r["asset"]
            if not f.exists():
                continue
            data = f.read_bytes()
            sha = hashlib.sha1(data).hexdigest()
            hit = {x["by"]: x["text"] for x in self._q("SELECT by, text FROM seen WHERE sha = ?", (sha,))}
            if "vision" in hit:
                done += self._picture_text(r, hit["vision"], "figure")
                continue
            if r["kind"] == "picture" and ("decor" in hit or _decorative(data)):
                self._seen(sha, "", "decor")
                done += self._picture_text(r, "", "decor")
                continue
            if vision and not failed and _vision_budget():
                self._say(f"describing pictures {n}/{len(rows)} ({r['name']})")
                try:
                    text = llm.chat([{"role": "user", "content": [
                        {"type": "text", "text": VISION_PROMPT.format(doc=r["name"], path=r["path"] or "-")},
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + _small_jpeg(data)}}]}],
                        cfg.get("BRAIN_VLM_MODEL"), timeout=cfg.get("BRAIN_VLM_TIMEOUT"), max_tokens=700,
                        temperature=0)["content"]
                    self._seen(sha, text, "vision")
                    done += self._picture_text(r, text, "figure")
                    continue
                except llm.LLMError as exc:   # timeout, gateway error, model without vision: OCR now, vision later
                    self._say(f"picture descriptions postponed: {exc}")
                    failed = True
            if r["kind"] != "picture" or not ocr_ok:
                continue
            if "ocr" not in hit:
                self._say(f"reading pictures with OCR {n}/{len(rows)} ({r['name']})")
                try:
                    hit["ocr"] = _ocr.read(data)
                except Exception as exc:
                    self._say(f"OCR failed on {r['asset']}: {exc}")
                    continue
                self._seen(sha, hit["ocr"], "ocr")
            done += self._picture_text(r, f"{OCR_LABEL}\n{hit['ocr']}" if hit["ocr"] else "", "ocr")
        return -1 if failed and not done else done

    def _seen(self, sha: str, text: str, by: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO seen VALUES (?,?,?,?)", (sha, text, by, time.time()))
            self.db.commit()

    def _picture_text(self, r, text: str, kind: str) -> int:
        """Sets a picture passage's text (its alt text and caption, then `text`) and kind, and re-derives its keyword
        index, concepts and rules; the vector is embedded again by the next pass."""
        caption = r["text"].split(OCR_LABEL, 1)[0].strip()
        body = f"{caption}\n{text}".strip()
        with self.lock:
            self.db.execute("UPDATE chunks SET text = ?, kind = ?, vec = NULL WHERE id = ?", (body, kind, r["id"]))
            full = f"{r['name']} {r['path']} {body}"
            self.db.execute("UPDATE fts SET body = ?, stem = ? WHERE rowid = ?",
                            (fold(full), stemmed(full, _turkish(body)), r["id"]))
            if r["kind"] == "picture":
                self.db.execute("UPDATE docs SET described = described + 1 WHERE id = ?", (r["doc"],))
            self.db.execute("DELETE FROM rules WHERE chunk = ?", (r["id"],))
            if text:
                turkish = qa.analyze(body[:2000])["language"] in ("tr", "mixed")
                for _, (cname, ckind) in list(concepts_in(text, _stop()).items())[:20]:
                    key = concept_key(cname, turkish, ckind)
                    self.db.execute("INSERT OR IGNORE INTO concepts(key, name, kind) VALUES (?,?,?)", (key, cname, ckind))
                    self.db.execute("INSERT OR IGNORE INTO mentions SELECT id, ? FROM concepts WHERE key = ?", (r["id"], key))
                for rule in rules_in("figure", body):
                    self.db.execute("INSERT INTO rules(chunk, kind, modality, text, limits) VALUES (?,?,?,?,?)",
                                    (r["id"], rule["kind"], rule["modality"], rule["text"], "; ".join(rule["limits"])))
            self.db.commit()
            self.version += 1
        jobs.tick()
        return 1

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
                self.db.execute("DELETE FROM cards WHERE doc = ?", (doc,))
                for table in ("units", "refs", "defs"):
                    self.db.execute(f"DELETE FROM {table} WHERE doc = ?", (doc,))
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
        cards = self.cards()
        return [{"id": r["id"], "name": r["name"], "status": r["status"], "chunks": r["chunks"], "error": r["error"],
                 "vectors": vec.get(r["id"], 0), "rules": rules.get(r["id"], 0), "pictures": r["pictures"], "described": r["described"],
                 **{k: cards.get(r["id"], {}).get(k) for k in ("versions", "effective", "superseded_by", "versions_of")},
                 "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(r["updated"] or 0))}
                for r in self._q("SELECT * FROM docs ORDER BY updated DESC")]

    def pipeline(self) -> dict:
        return dict(self.activity)

    def markdown(self, name: str) -> str:
        f = cfg.path("converted") / f"{Path(name).name}.md"
        if not f.exists():
            raise KeyError(f"no converted Markdown for {name}")
        return f.read_text(encoding="utf-8")

    def _mentions(self) -> tuple[dict, dict, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """The passage-concept graph as arrays (cached until the index changes)."""
        if self._graph is None or self._graph[0] != self.version:
            rows = self._q("SELECT concept, chunk FROM mentions")
            cpos = {c: i for i, c in enumerate(dict.fromkeys(r[0] for r in rows))}
            hpos = {h: i for i, h in enumerate(dict.fromkeys(r[1] for r in rows))}
            ci = np.asarray([cpos[r[0]] for r in rows], dtype=np.int64)
            hi = np.asarray([hpos[r[1]] for r in rows], dtype=np.int64)
            self._graph = (self.version, cpos, hpos, ci, hi, np.bincount(ci, minlength=len(cpos)).astype(np.float64),
                           np.bincount(hi, minlength=len(hpos)).astype(np.float64))
        return self._graph[1:]

    def _ppr(self, concepts: list[int], passages: list[int], steps: int = 12, damping: float = 0.5) -> list[int]:
        """Personalized PageRank over the passage-concept graph (the retrieval of HippoRAG, LinearRAG and SPRIG): mass
        starts at the question's concepts (rare ones weigh more) and the best keyword and vector passages, and flows
        passage -> concept -> passage, so passages linked through a shared concept are found even when they share no
        word with the question. A concept named everywhere passes on little (its mass is split over its passages).
        Returns passage ids, best first."""
        cpos, hpos, ci, hi, cdeg, hdeg = self._mentions()
        if not len(ci):
            return []
        sc, sh = np.zeros(len(cpos)), np.zeros(len(hpos))
        for c in concepts:
            if c in cpos:
                sc[cpos[c]] += 1.0 / np.log(2.0 + cdeg[cpos[c]])
        for h in passages:
            if h in hpos:
                sh[hpos[h]] += 0.5
        total = sc.sum() + sh.sum()
        if not total:
            return []
        sc, sh = sc / total, sh / total
        c, h = sc.copy(), sh.copy()
        for _ in range(steps):
            h_next = np.bincount(hi, weights=(c / np.maximum(cdeg, 1))[ci], minlength=len(hpos))
            c_next = np.bincount(ci, weights=(h / np.maximum(hdeg, 1))[hi], minlength=len(cpos))
            c, h = (1 - damping) * sc + damping * c_next, (1 - damping) * sh + damping * h_next
        ids = np.fromiter(hpos.keys(), dtype=np.int64, count=len(hpos))
        top = [i for i in np.argsort(-h)[:60] if h[i] > 0]
        return [int(ids[i]) for i in top]

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
        forms = terms + phrases + [stem(t, tr) for t in terms if " " not in t for tr in (True, False)]   # stems hit the stem column
        match = " OR ".join('"' + re.sub(r'["]', " ", t) + '"' for t in dict.fromkeys(forms) if t.strip())
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
        seeds = [c for ranked, _, _ in lists for c in ranked[:5]]   # the best keyword and vector passages
        if hit or seeds:
            ranked = self._ppr(hit, seeds)
            if ranked:
                lists.append((ranked, 1.0 if hit else 0.5, "concept graph"))
        score: dict[int, float] = {}
        how: dict[int, list[str]] = {}
        for ranked, weight, label in lists:
            for rank, cid in enumerate(ranked):
                score[cid] = score.get(cid, 0) + weight / (60 + rank)
                how.setdefault(cid, []).append(label)
        old = {d for d, c in self.cards().items() if c["superseded_by"]}
        if old and score:   # a passage of an older version counts half: the current version comes first
            cand = sorted(score, key=lambda c: -score[c])[:chunks * 4]
            q = ",".join("?" * len(cand))
            for cid, doc in self._q(f"SELECT id, doc FROM chunks WHERE id IN ({q})", tuple(cand)):
                if doc in old:
                    score[cid] *= 0.5
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
                           WHERE m.chunk IN ({q}) AND k.kind != 'reference' GROUP BY k.id ORDER BY (k.key IN ({','.join('?' * len(keys)) or "''"})) DESC,
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
        found = self._q(f"""SELECT x.chunk, x.kind, x.modality, x.text, x.limits, x.actor, x.action, x.condition, x.confidence,
            u.path AS unit, d.name, c.path, c.page FROM rules x JOIN chunks c ON c.id = x.chunk JOIN docs d ON d.id = c.doc
            LEFT JOIN units u ON u.id = x.unit WHERE x.chunk IN ({q}) AND x.modality IS NOT NULL""", tuple(best))
        ranked = sorted(found, key=lambda r: (-sum(w in stemmed(r["text"]) for w in words), order[r["chunk"]]))
        rules = [{"text": r["text"], "modality": r["modality"], "kind": r["kind"],
                  "limits": [x for x in (r["limits"] or "").split("; ") if x], "actor": r["actor"], "action": r["action"],
                  "condition": r["condition"], "unit": r["unit"], "confidence": r["confidence"],
                  "source": " › ".join(x for x in (r["name"], r["path"]) if x) + (f", p. {r['page']}" if r["page"] else "")}
                 for r in ranked[:max(top_k, 8)]]
        shown = list(dict.fromkeys(c["doc"] for c in out_chunks))
        cards = {c["name"]: c for c in self.cards().values() if c["name"] in shown}
        documents = [{"name": n, "summary": cards[n]["summary"][:2], "effective": cards[n]["effective"],
                      "version": (cards[n]["versions"] or [None])[0], "superseded_by": cards[n]["superseded_by"]}
                     for n in shown if n in cards]
        for c in out_chunks:   # a passage from an older version says so
            newer = cards.get(c["doc"], {}).get("superseded_by")
            if newer:
                c["note"] = f"older version; newer: {newer}"
        return {"chunks": out_chunks, "entities": entities, "relations": facts[:top_k], "rules": rules, "documents": documents}

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


_vlm_calls: list[float] = []   # times of the vision calls in the last hour


def _vision_budget() -> bool:
    """True (and counted) when one more vision call fits in BRAIN_VLM_MAX_PER_HOUR (0 = no limit)."""
    cap, now = cfg.get("BRAIN_VLM_MAX_PER_HOUR"), time.time()
    _vlm_calls[:] = [t for t in _vlm_calls if now - t < 3600]
    if cap > 0 and len(_vlm_calls) >= cap:
        return False
    _vlm_calls.append(now)
    return True


def _decorative(data: bytes) -> bool:
    """A picture not worth a description: smaller than BRAIN_PICTURE_MIN_PX on a side, or nearly one colour
    (spacers, rules, plain backgrounds)."""
    from PIL import Image, ImageStat
    try:
        img = Image.open(io.BytesIO(data))
        if min(img.size) < cfg.get("BRAIN_PICTURE_MIN_PX"):
            return True
        img.thumbnail((128, 128))
        return ImageStat.Stat(img.convert("L")).stddev[0] < 4
    except Exception:
        return False


def _small_jpeg(data: bytes, edge: int = 1600) -> str:
    """The picture as base64 JPEG, at most `edge` pixels on its long side (fewer tokens for the vision model)."""
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    img.thumbnail((edge, edge))
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=85)
    return base64.b64encode(out.getvalue()).decode()
