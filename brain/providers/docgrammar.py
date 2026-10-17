"""Document grammar: the tree-sitter idea for official documents, without a model.

Natural sentences have no formal grammar, but official and technical documents follow drafting conventions that are
almost one. This module parses those conventions in Turkish and English:

  * units        the document tree: parts and chapters (BİRİNCİ BÖLÜM, Chapter 2), articles (MADDE 5 –, Article 5),
                 numbered sections (4.2 Title, from headings or numbered lines), paragraphs ((1), (2)), items (a), (b),
                 sub-items (1), (i)), annexes (EK-1, Annex A) and requirements (REQ-001, FR-12, NFR-3, US-4 ...: a line
                 or a table row that starts with an ID);
  * references   to units of the same document ("5 inci maddenin (2) numaralı fıkrası", "birinci fıkranın (a) bendi",
                 "Section 4.2(a)", "clause 3", "paragraph (2)"), to requirements anywhere (REQ-001), to laws and
                 standards ("6698 sayılı Kanun", ISO/IEC 27001, RFC 2119, KVKK, GDPR) and to other documents;
  * definitions  "Bu Yönetmelikte geçen; a) Banka: ...", "(bundan sonra 'Banka' olarak anılacaktır)", "'Bank' means ...",
                 "hereinafter 'Bank'", glossary and abbreviation tables;
  * amendments   "değiştirilmiştir", "yürürlükten kaldırılmıştır", "eklenmiştir", "is amended", "is repealed",
                 "replaces", "supersedes", "obsoletes", "deprecated";
  * statements   normative sentences split into modality (obligation, prohibition, recommendation, permission, limit;
                 RFC 2119 keywords included), actor, action, object, condition, exception and limits; user stories
                 ("As a ..., I want ... so that ...", "Bir ... olarak ... istiyorum") and acceptance criteria
                 (Given / When / Then). Each statement carries a confidence: high, medium or low.

The structure layers (units, references, definitions, amendments) follow fixed markers and are reliable; the statement
layer is best effort and says so through its confidence.
"""
from __future__ import annotations

import re
import unicodedata

TR_ORD = {w: i + 1 for i, w in enumerate(
    "birinci ikinci üçüncü dördüncü beşinci altıncı yedinci sekizinci dokuzuncu onuncu on birinci on ikinci on üçüncü "
    "on dördüncü on beşinci".replace("on ", "on_").split())}
TR_ORD = {k.replace("_", " "): v for k, v in TR_ORD.items()}
EN_ORD = {w: i + 1 for i, w in enumerate("first second third fourth fifth sixth seventh eighth ninth tenth".split())}
ROMAN = {r: i + 1 for i, r in enumerate("i ii iii iv v vi vii viii ix x xi xii".split())}
SUFFIX = r"(?:'?\s*(?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü|ıncı|\.))?"
ORDWORDS = "|".join(sorted(TR_ORD, key=len, reverse=True))

PART = re.compile(rf"^\s*(?:(?P<ord>{ORDWORDS})\s+(?P<kind>kısım|bölüm|kisim|bolum)|(?P<kind2>kısım|bölüm|part|chapter|kisim|bolum)"
                  r"\s+(?P<num>\d+|[ivx]+))\b[\s:.–-]*(?P<title>.*)$", re.I)
ARTICLE = re.compile(r"^\s*\**\s*(?P<pre>geçici\s+|gecici\s+|ek\s+)?(?:madde|article)\s+(?P<num>\d+[a-z]?)\s*\**\s*[–—:.-]*\s*\**(?P<title>.*)$",
                     re.I)
CLAUSE = re.compile(r"^\s*(?:section|§|clause|kısım)\s*(?P<num>\d{1,2}(?:\.\d{1,3}){1,4})\.?\s+(?P<title>\S.*)$", re.I)
LETTER_HEAD = re.compile(r"^\s*(?P<num>[A-Z]|[IVX]{1,4})\.\s+(?P<title>[A-ZÇĞİÖŞÜ][^.]{1,80})$")
SECTION = re.compile(r"^\s*(?:§\s*|section\s+|bölüm\s+)?(?P<num>\d{1,2}(?:\.\d{1,3}){0,4})\.?\s+(?P<title>[A-ZÇĞİÖŞÜ][^|]{1,140})$")
PARAGRAPH = re.compile(r"^\s*\((?P<num>\d{1,2})\)\s+(?P<text>\S.*)$")
ITEM = re.compile(r"^\s*(?:\((?P<a>[a-zçğıöşü])\)|(?P<b>[a-zçğıöşü])\))\s+(?P<text>\S.*)$")
SUBITEM = re.compile(r"^\s*(?:(?P<n>\d{1,2})\)|\((?P<r>i{1,3}|iv|v|vi{0,3}|ix|x)\))\s+(?P<text>\S.*)$")
ANNEX = re.compile(r"^\s*(?:#+\s*)?(?P<kind>ek|annex|appendix|ekler)[\s.-]*(?P<num>[0-9]{1,2}|[A-Z])\b[\s:.–-]*(?P<title>.*)$", re.I)
REQ_ID = r"(?:[A-Z]{1,6}-){0,2}[A-Z]{1,6}-\d{1,5}(?:\.\d{1,3})?"
REQUIREMENT = re.compile(rf"^\s*(?:[-*]\s*)?\**\[?(?P<id>{REQ_ID})\]?\**\s*[:.)–—-]?\s+(?P<text>\S.*)$")
REQ_ROW = re.compile(rf"^\s*\|\s*\**(?P<id>{REQ_ID})\**\s*\|(?P<text>.*)\|\s*$")
LEVEL = {"part": 0, "chapter": 1, "annex": 1, "article": 2, "section": 2, "requirement": 9, "paragraph": 10, "item": 11,
         "subitem": 12}

# references --------------------------------------------------------------------------------------------------------
TR_ART_REF = re.compile(rf"(?P<art>\d+)\s*{SUFFIX}\s*madde(?:si(?:nin|nde|ne|ni)?|nin|nde|de|ye|yi|deki|sindeki)?"
                        rf"(?:\s*(?:nin|ının|inin)?\s*\(?(?P<par>\d+)\)?\s*numaralı\s+fıkra\w*)?"
                        rf"(?:\s*(?:nın|nin)?\s*\(?(?P<item>[a-zçğıöşü])\)?\s*bend\w*)?", re.I)
TR_GECICI_REF = re.compile(rf"geçici\s+(?P<art>\d+)\s*{SUFFIX}\s*madde\w*", re.I)
TR_PAR_REF = re.compile(rf"(?:\(?(?P<num>\d+)\)?\s*numaralı|(?P<ord>{ORDWORDS}))\s+fıkra\w*"
                        rf"(?:\s*(?:nın|nin)?\s*\(?(?P<item>[a-zçğıöşü])\)?\s*bend\w*)?", re.I)
TR_ITEM_REF = re.compile(r"\((?P<item>[a-zçğıöşü])\)\s*bend\w*", re.I)
TR_SEC_REF = re.compile(r"(?P<num>\d{1,2}(?:\.\d{1,3}){1,4})\.?\s*(?:numaralı\s+)?(?:bölüm|kısım|madde|başlık)\w*", re.I)
EN_REF = re.compile(r"\b(?P<kind>section|sections|§|clause|article|art\.|paragraph|para\.)\s*(?P<num>\d{1,3}(?:\.\d{1,3}){0,4})"
                    r"(?P<sub>(?:\s*\((?:[a-z]|\d{1,2}|[ivx]{1,4})\))*)", re.I)
EN_PAR_REF = re.compile(r"\b(?:paragraph|subsection)\s*\((?P<num>\d{1,2})\)", re.I)
EN_ITEM_REF = re.compile(r"\b(?:item|point|subparagraph|clause)\s*\((?P<item>[a-z])\)", re.I)
ANNEX_REF = re.compile(r"\b(?:ek|annex|appendix)[\s.-]*(?P<num>\d{1,2}|[A-Z])\b(?!-\d)", re.I)
REQ_REF = re.compile(rf"\b(?P<id>{REQ_ID})\b")
LAW_REF = re.compile(r"(?P<num>\d{3,5})\s*sayılı\s+(?P<name>(?:[A-ZÇĞİÖŞÜ][\w'’-]*\s+){0,8}?(?:Kanun|Kanunu|Kanunun|Yönetmelik|"
                     r"Yönetmeliği|Tebliğ|Tebliği|Genelge|Genelgesi|Karar|Kararı|Cumhurbaşkanlığı Kararnamesi))")
STANDARD = re.compile(r"\b(?:ISO(?:/IEC)?\s*\d{4,5}(?:-\d{1,2})?(?::\d{4})?|IEC\s*\d{4,5}|RFC\s*\d{3,4}|KVKK|GDPR|PCI[\s-]?DSS|"
                      r"SOC\s*2|ITIL(?:\s*v?\d)?|COBIT|NIST\s*(?:SP\s*)?\d{3}-\d{2,3}|OWASP(?:\s+Top\s+10)?|HIPAA|SOX|BDDK|SPK|TCMB)\b")

# definitions ---------------------------------------------------------------------------------------------------------
HEREAFTER = re.compile(r"\(?\s*(?:bundan\s+(?:böyle|sonra)|kısaca|aşağıda|hereinafter(?:\s+referred\s+to\s+as)?|the\s+)?\s*[\"“'‘](?P<term>[^\"”'’]{2,40})[\"”'’]"
                       r"\s*(?:olarak\s+(?:anılacaktır|adlandırılacaktır|ifade\s+edilecektir)|\)|means|shall\s+mean|refers\s+to|is\s+defined\s+as)", re.I)
TERM_LINE = re.compile(r"^\s*(?:[-*]|\(?[a-zçğıöşü]\)|\d+\))?\s*\**(?P<term>[^:*\n]{2,50}?)\**\s*:\s+(?P<def>.{10,})$")
DEF_CONTEXT = re.compile(r"tanım|kısaltma|terim|geçen;|definition|glossary|abbreviation|terms", re.I)

# amendments ----------------------------------------------------------------------------------------------------------
AMEND = [("repeals", re.compile(r"yürürlükten\s+kaldırıl|mülga|is\s+repealed|are\s+repealed|is\s+revoked|is\s+withdrawn|obsoletes", re.I)),
         ("amends", re.compile(r"değiştirilmiştir|şeklinde\s+değiştir|is\s+amended|are\s+amended|is\s+replaced\s+by|replaces|supersedes|"
                               r"yerine\s+geçer|updates", re.I)),
         ("adds", re.compile(r"eklenmiştir|is\s+added|are\s+added|is\s+inserted", re.I)),
         ("deprecates", re.compile(r"deprecated|kullanımdan\s+kaldırıl", re.I))]

# statements ----------------------------------------------------------------------------------------------------------
RFC = [("prohibition", re.compile(r"\b(?:MUST NOT|SHALL NOT)\b")), ("obligation", re.compile(r"\b(?:MUST|SHALL|REQUIRED)\b")),
       ("recommendation", re.compile(r"\b(?:SHOULD NOT|SHOULD|RECOMMENDED|NOT RECOMMENDED)\b")),
       ("permission", re.compile(r"\b(?:MAY|OPTIONAL)\b"))]
EN_MODAL = re.compile(r"\b(?P<m>must\s+not|shall\s+not|should\s+not|may\s+not|cannot|can\s+not|is\s+not\s+allowed\s+to|"
                      r"are\s+not\s+allowed\s+to|must|shall|should|may|is\s+required\s+to|are\s+required\s+to|needs?\s+to|"
                      r"has\s+to|have\s+to|is\s+responsible\s+for|are\s+responsible\s+for|will)\b", re.I)
EN_COND = re.compile(r"\b(?:if|when|whenever|where|unless|provided\s+that|in\s+case\s+of|in\s+the\s+event\s+(?:of|that)|"
                     r"before|after|once)\b", re.I)
EN_EXC = re.compile(r"\b(?:except(?:\s+(?:for|when|where|that))?|other\s+than|with\s+the\s+exception\s+of)\b", re.I)
TR_COND = re.compile(r"\b\w+(?:sa|se|ması\s+halinde|mesi\s+halinde|ması\s+durumunda|mesi\s+durumunda|dığında|diğinde|duğunda|"
                     r"düğünde|tığında|tiğinde|tuğunda|tüğünde|ken)\b|\b(?:halinde|hâlinde|durumunda|takdirde|ise)\b", re.I)
TR_EXC = re.compile(r"\b(?:ancak|hariç|dışında|istisna(?:sı|en)?|bununla\s+birlikte)\b", re.I)
TR_MODAL_SUFFIX = re.compile(r"(?:mamalıdır|memelidir|mamalı|memeli|malıdır|melidir|malı|meli|maz|mez|amaz|emez|abilir|ebilir|"
                             r"maktadır|mektedir|acaktır|ecektir|ır|ir|ur|ür|ar|er|dır|dir|dur|dür|tır|tir|tur|tür|r)$")
PREDICATES = {"zorunlu", "gerekli", "şart", "yasak", "mecburi", "esas", "yetkili", "sorumlu"}
TR_LIGHT = re.compile(r"^(?:edil|et|yapıl|yap|veril|ver|ol|sağlan|sağla|bulun|tutul|tut|alın|al|geçiril|geçir|getiril|getir|tutul)", re.I)
STORY_EN = re.compile(r"^\s*as\s+an?\s+(?P<actor>[^,]{2,60}),\s*i\s+(?:want|need|would\s+like)\s+(?:to\s+)?(?P<action>.+?)"
                      r"(?:,?\s*so\s+(?:that\s+)?(?P<goal>.+))?\s*$", re.I)
STORY_TR = re.compile(r"^\s*bir\s+(?P<actor>.{2,60}?)\s+olarak,?\s*(?P<action>.+?)\s+istiyorum(?:[,;]?\s*(?:böylece|ki|bu\s+sayede)\s+(?P<goal>.+))?\s*[.]?$",
                      re.I)
GHERKIN = re.compile(r"^\s*[-*]?\s*\**(?P<k>given|when|then|and|but|diyelim\s+ki|eğer|olduğunda|o\s+zaman|ve|ama)\**\b\s*(?P<text>.+)$",
                     re.I)
SENT = re.compile(r"(?<=[.!?;])\s+(?=[A-ZÇĞİÖŞÜ(\"“])")
DET = re.compile(r"^(?:the|a|an|all|each|every|any)\s+", re.I)


def tr_lower(text: str) -> str:
    """Lower case that keeps Turkish letters and the length (İ -> i, I -> ı), so match positions stay valid."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.replace("İ", "i").casefold().replace("ı", "i"))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _num(word: str) -> int | None:
    w = norm(word)
    if w.isdigit():
        return int(w)
    return TR_ORD.get(word.lower()) or EN_ORD.get(w) or ROMAN.get(w)


# ---------------------------------------------------------------- units
INLINE_ARTICLE = re.compile(r"(?<=\S)(?<!GEÇİCİ)(?<!EK)\s+(?=(?:GEÇİCİ\s+|EK\s+)?MADDE\s+\d+[a-z]?\s*[–—-])")
INLINE_PARAGRAPH = re.compile(r"(?<=\S)\s+(?=\(\d{1,2}\)\s+[A-ZÇĞİÖŞÜ0-9\"“])")
INLINE_ITEM = re.compile(r"(?<=[;:,])\s+(?=[a-zçğıöşü]\)\s+[A-ZÇĞİÖŞÜ])")


def normalize_lines(md: str) -> list[str]:
    """The lines the grammar reads: PDF text often arrives with an article, its paragraphs and items on one line
    ("MADDE 5 – Erişim (1) Sistem sahibi ... (2) Ayrıcalıklı ..."), so inline article, paragraph and item markers start
    a new line. Tables and headings stay as they are."""
    out = []
    for line in md.splitlines():
        if line.startswith(("|", "#", "<!--")) or len(line) < 40:
            out.append(line)
            continue
        line = INLINE_ARTICLE.sub("\n", line)
        line = INLINE_PARAGRAPH.sub("\n", line)
        out += INLINE_ITEM.sub("\n", line).split("\n")
    return out


def parse_units(md: str) -> list[dict]:
    """The unit tree of converted Markdown: [{i, parent, kind, num, key, label, title, path, page, start, end}], in
    document order; `start`/`end` are indexes into normalize_lines(md) (end exclusive)."""
    lines = normalize_lines(md)
    units: list[dict] = []
    stack: list[dict] = []
    page = None
    for n, raw in enumerate(lines):
        m = re.match(r"<!-- page (\d+) -->", raw)
        if m:
            page = int(m.group(1))
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", raw)
        line = heading.group(2).strip() if heading else raw.strip()
        if not line or (n == 0 and heading and heading.group(1) == "#"):
            continue
        unit = _match_unit(line, bool(heading), stack)
        if unit is None and heading:   # an unnumbered heading is a section named by its title
            unit = {"kind": "section", "num": None, "title": line[:160], "depth": len(heading.group(1))}
        if unit is None:
            continue
        lvl = LEVEL[unit["kind"]] + (unit.get("depth", 1) - 1) * 0.1
        while stack and stack[-1]["lvl"] >= lvl:
            stack.pop()["end"] = n
        unit.update(i=len(units), parent=stack[-1]["i"] if stack else None, lvl=lvl, page=page, start=n, end=len(lines))
        unit["key"], unit["label"] = _key(unit, stack)
        unit["path"] = " › ".join([s["label"] for s in stack] + [unit["label"]])
        units.append(unit)
        stack.append(unit)
    for u in units:   # a requirement is its line or paragraph: it ends at the next blank line
        if u["kind"] == "requirement":
            blank = next((k for k in range(u["start"] + 1, u["end"]) if not lines[k].strip()), u["end"])
            u["end"] = min(u["end"], blank)
    return units


def _match_unit(line: str, heading: bool, stack: list[dict]) -> dict | None:
    line = re.sub(r"^[*_]+|[*_]+$", "", line).strip()   # numbers typed in bold or italics in Word: **1. Amaç**
    low = tr_lower(line)
    in_article = any(s["kind"] in ("article", "section") for s in stack)
    if (m := REQUIREMENT.match(line)) or (m := REQ_ROW.match(line)):
        if not re.match(r"(?:ISO|IEC|RFC|NIST|SOC|PCI)-", m.group("id")):
            return {"kind": "requirement", "num": m.group("id").upper(), "title": m.group("text").strip(" |")[:160]}
    if (m := ARTICLE.match(low)) and (heading or len(line) < 200):
        pre = norm(m.group("pre") or "").strip()
        return {"kind": "article", "num": (pre + " " if pre else "") + m.group("num"), "word": "article" if norm(low).lstrip(" *").startswith("article") else "madde",
                "title": line[m.start("title"):].strip(" –-:*")[:160]}
    if (m := PART.match(low)) and (heading or len(line) < 80):
        kind = norm(m.group("kind") or m.group("kind2"))
        num = _num(m.group("ord") or m.group("num") or "")
        if num:
            return {"kind": "part" if kind in ("kisim", "part") else "chapter", "num": str(num), "word": kind,
                    "title": line[m.start("title"):].strip()[:160]}
    if (m := ANNEX.match(low)) and (heading or len(line) < 80) and not re.match(r"ek\s+madde", low):
        return {"kind": "annex", "num": m.group("num").upper(), "title": line[m.start("title"):].strip()[:160]}
    if m := CLAUSE.match(line):   # "Section 2.01 The Provider shall ...": a numbered clause, even when it is a sentence
        return {"kind": "section", "num": m.group("num"), "title": m.group("title").strip()[:160], "depth": m.group("num").count(".") + 1}
    if (m := LETTER_HEAD.match(line)) and len(line) < 90:   # "A. Purpose", "II. Scope"
        return {"kind": "section", "num": m.group("num"), "title": m.group("title").strip()[:160], "depth": 1}
    if (m := SECTION.match(line)) and (heading or len(line) < 120) and not line.rstrip().endswith((".", ",", ";")):
        return {"kind": "section", "num": m.group("num"), "title": m.group("title").strip()[:160], "depth": m.group("num").count(".") + 1}
    if in_article and (m := PARAGRAPH.match(line)):
        return {"kind": "paragraph", "num": m.group("num"), "title": m.group("text")[:160]}
    if stack and (m := ITEM.match(line)):
        return {"kind": "item", "num": (m.group("a") or m.group("b")).lower(), "title": m.group("text")[:160]}
    if stack and stack[-1]["kind"] in ("item", "subitem") and (m := SUBITEM.match(line)):
        return {"kind": "subitem", "num": m.group("n") or m.group("r"), "title": m.group("text")[:160]}
    return None


def _key(unit: dict, stack: list[dict]) -> tuple[str, str]:
    kind, num = unit["kind"], unit["num"]
    if kind == "article":
        key = "art:" + norm(num).replace(" ", "")
        pre, _, n = num.rpartition(" ")
        default = "Article " if unit.get("word") == "article" else "Madde "
        return key, {"gecici": "Geçici Madde ", "ek": "Ek Madde "}.get(pre, default) + n
    if kind == "section":
        return (f"sec:{num}", num) if num else (f"head:{norm(unit['title'])[:60]}", unit["title"][:60])
    if kind == "requirement":
        return f"req:{num}", num
    if kind in ("part", "chapter"):
        word = {"kisim": "Kısım", "bolum": "Bölüm", "part": "Part", "chapter": "Chapter"}.get(unit.get("word", kind), "Chapter")
        return f"{kind}:{num}", f"{word} {num}"
    if kind == "annex":
        return f"annex:{norm(num)}", f"Annex {num}"
    parent = next((s for s in reversed(stack) if LEVEL[s["kind"]] < LEVEL[kind]), None)
    base = parent["key"] + "/" if parent else ""
    label = {"paragraph": f"({num})", "item": f"{num})", "subitem": f"{num})"}[kind]
    return f"{base}{kind[:3]}:{num}", label


def unit_keys(query: str) -> list[str]:
    """Candidate unit keys for what a person types: "Madde 5", "madde 5 (2) b", "Geçici Madde 1", "Article 12(2)(b)",
    "Section 3.1", "3.1", "Bölüm 2", "Chapter 2", "REQ-004", "Ek-1", "Annex A", or a heading's title."""
    q = query.strip()
    low = norm(q)
    if m := re.search(rf"\b({REQ_ID})\b", q.upper()):
        return [f"req:{m.group(1)}"]
    if m := re.match(r"(?:(gecici|ek)\s+)?(?:madde|article|art\.?)\s*(\d+[a-z]?)\s*(?:\(?(\d+)\)?)?\s*(?:\(?([a-z])\)?)?", low):
        key = f"art:{m.group(1) or ''}{m.group(2)}"
        keys = [key]
        if m.group(3):
            keys.insert(0, key := f"{key}/par:{m.group(3)}")
        if m.group(4):
            keys.insert(0, f"{key}/ite:{m.group(4)}")
        return keys
    if m := re.match(r"(?:section|bolum|kisim|§)?\s*(\d{1,2}(?:\.\d{1,3}){0,4})\.?$", low):
        return [f"sec:{m.group(1)}", f"art:{m.group(1)}"]
    if m := re.match(r"(?:bolum|chapter|kisim|part)\s+(\d+|[ivx]+)$", low):
        n = _num(m.group(1))
        return [f"chapter:{n}", f"part:{n}"]
    if m := re.match(r"(?:ek|annex|appendix)[\s.-]*(\w)$", low):
        return [f"annex:{m.group(1)}"]
    return [f"head:{low[:60]}"]


# ---------------------------------------------------------------- references
def find_refs(text: str, ctx: dict | None = None) -> list[dict]:
    """References in a piece of text: [{kind, key, raw}]; `ctx` = {"article": "art:5", "paragraph": "art:5/par:2"} resolves
    relative references ("birinci fıkra", "paragraph (2)", "(a) bendi") inside the current article."""
    ctx = ctx or {}
    out, seen = [], set()

    def add(kind, key, raw):
        if key and (kind, key) not in seen:
            seen.add((kind, key))
            out.append({"kind": kind, "key": key, "raw": raw.strip()})
    spans = []
    for m in TR_GECICI_REF.finditer(text):
        add("unit", f"art:gecici{m.group('art')}", m.group(0))
        spans.append(m.span())
    for m in TR_ART_REF.finditer(text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        key = f"art:{m.group('art')}"
        if m.group("par"):
            key += f"/par:{m.group('par')}"
        if m.group("item"):
            key += f"/ite:{m.group('item').lower()}"
        add("unit", key, m.group(0))
        spans.append(m.span())
    for m in TR_PAR_REF.finditer(text):
        if any(a <= m.start() < b for a, b in spans) or not ctx.get("article"):
            continue
        num = m.group("num") or _num(m.group("ord") or "")
        key = f"{ctx['article']}/par:{num}" + (f"/ite:{m.group('item').lower()}" if m.group("item") else "")
        add("unit", key, m.group(0))
        spans.append(m.span())
    for m in TR_ITEM_REF.finditer(text):
        if not any(a <= m.start() < b for a, b in spans) and (ctx.get("paragraph") or ctx.get("article")):
            add("unit", f"{ctx.get('paragraph') or ctx['article']}/ite:{m.group('item').lower()}", m.group(0))
    for m in TR_SEC_REF.finditer(text):
        if not any(a <= m.start() < b for a, b in spans):
            add("unit", f"sec:{m.group('num')}", m.group(0))
    for m in EN_REF.finditer(text):
        kind = m.group("kind").lower().rstrip(".")
        base = f"art:{m.group('num')}" if kind in ("article", "art") else f"sec:{m.group('num')}"
        subs = re.findall(r"\(([^)]+)\)", m.group("sub") or "")
        for s in subs:
            base += f"/par:{s}" if s.isdigit() else (f"/sub:{s}" if s in ROMAN else f"/ite:{s}")
        add("unit", base, m.group(0))
    for m in EN_PAR_REF.finditer(text):
        if ctx.get("article"):
            add("unit", f"{ctx['article']}/par:{m.group('num')}", m.group(0))
    for m in EN_ITEM_REF.finditer(text):
        if ctx.get("paragraph") or ctx.get("article"):
            add("unit", f"{ctx.get('paragraph') or ctx['article']}/ite:{m.group('item')}", m.group(0))
    for m in ANNEX_REF.finditer(text):
        if not re.match(r"(?i)ek\s+madde", text[m.start():m.start() + 9]):
            add("unit", f"annex:{norm(m.group('num'))}", m.group(0))
    for m in REQ_REF.finditer(text):
        if not re.match(r"(?:ISO|IEC|RFC|NIST|SOC|PCI)-", m.group("id")):
            add("requirement", f"req:{m.group('id').upper()}", m.group(0))
    for m in LAW_REF.finditer(text):
        add("law", f"law:{m.group('num')}", f"{m.group('num')} sayılı {m.group('name')}")
    for m in STANDARD.finditer(text):
        add("standard", "std:" + re.sub(r"\s+", " ", m.group(0).upper()), m.group(0))
    return out


# ---------------------------------------------------------------- definitions, amendments
def find_definitions(text: str, in_definitions: bool = False) -> list[tuple[str, str]]:
    """[(term, definition)] from "(bundan sonra 'X' olarak anılacaktır)", "'X' means ...", and "Term: definition" lines
    inside a definitions unit ("Tanımlar", "Definitions", "Bu Yönetmelikte geçen;")."""
    out = []
    for m in HEREAFTER.finditer(text):
        a, b = text.rfind("\n", 0, m.start("term")) + 1, text.find("\n", m.end())
        line = text[a:b if b >= 0 else len(text)].strip()
        out.append((m.group("term").strip(), line[:400]))
    if in_definitions or DEF_CONTEXT.search(text[:200]):
        for line in text.splitlines():
            m = TERM_LINE.match(line)
            if m and len(m.group("term").split()) <= 6 and not m.group("term").strip().lower().startswith(("not", "note")):
                out.append((m.group("term").strip(" *"), m.group("def").strip()))
    return out


def amendment(sentence: str) -> str | None:
    return next((kind for kind, rx in AMEND if rx.search(sentence)), None)


# ---------------------------------------------------------------- statements
def core(sentence: str) -> str:
    """A sentence without its leading markers: requirement ID, article header with its title, paragraph or item
    number ("REQ-001: ...", "MADDE 5 – Erişim talepleri (1) ...", "(2) ...", "b) ...")."""
    s = " ".join(sentence.split()).strip(" -*")
    s = re.sub(rf"^\**\[?{REQ_ID}\]?\**\s*[:.)–—-]?\s*", "", s)
    s = re.sub(r"^(?i:section|§|clause)\s*\d{1,2}(?:\.\d{1,3}){1,4}\.?\s+", "", s)
    if re.match(r"(?i)(?:geçici\s+|gecici\s+|ek\s+)?(?:madde|article)\s+\d+", tr_lower(s)):
        m = re.search(r"\(\d{1,2}\)\s+(?=\S)", s[:120])
        s = s[m.end():] if m else re.sub(r"^\S+(?:\s+\S+)?\s+\d+[a-z]?\s*[–—:.-]+\s*", "", s)
    return re.sub(r"^(?:\(\d{1,2}\)|\(?[a-zçğıöşü]\)|\d{1,2}\))\s+", "", s)


def parse_statement(sentence: str, turkish: bool, modality: str | None = None) -> dict:
    """Slots of one normative sentence: {modality, actor, action, object, condition, exception, confidence}."""
    s = core(sentence)
    if re.search(r"RFC\s*2119|key\s*words?\s+[\"“]?MUST", s):        # RFC 2119's own boilerplate is not a rule
        return {"kind": "rule", "modality": None, "actor": None, "action": None, "object": None, "condition": None,
                "exception": None, "confidence": "low"}
    for kind, rx in RFC:
        if rx.search(s):
            modality = kind
            break
    if (m := STORY_EN.match(s)) or (m := STORY_TR.match(s)):
        return {"kind": "story", "modality": "requirement", "actor": m.group("actor").strip(), "action": m.group("action").strip(),
                "object": (m.group("goal") or "").strip(" .") or None, "condition": None, "exception": None, "confidence": "high"}
    exception = None
    rx_exc = TR_EXC if turkish else EN_EXC
    if (m := rx_exc.search(s)) and m.start() > 0:
        exception, s = s[m.start():].strip(" .,;"), s[:m.start()].strip(" ,;")
    slots = _tr_slots(s) if turkish and not EN_MODAL.search(s) else _en_slots(s)
    slots.update(kind="rule", modality=modality, exception=exception or slots.get("exception"))
    found = sum(bool(slots.get(k)) for k in ("actor", "action"))
    slots["confidence"] = "high" if found == 2 and modality and len(s.split()) <= 40 else "medium" if slots.get("action") else "low"
    return slots


def _en_slots(s: str) -> dict:
    condition = None
    lead = re.match(r"^(?P<c>(?:if|when|whenever|where|unless|provided\s+that|in\s+case\s+of|in\s+the\s+event\s+(?:of|that)|once)\b[^,]{3,160}),\s*(?P<rest>.+)$", s, re.I)
    if lead:
        condition, s = lead.group("c"), lead.group("rest")
    m = EN_MODAL.search(s)
    if not m:
        return {"actor": None, "action": None, "object": None, "condition": condition}
    actor = DET.sub("", s[:m.start()].strip(" ,")) or None
    if actor and len(actor.split()) > 10:
        actor = " ".join(actor.split()[-6:])
    rest = s[m.end():].strip()
    tail = EN_COND.search(rest)
    if tail and tail.start() > 0 and not condition:
        condition, rest = rest[tail.start():].strip(" .,;"), rest[:tail.start()].strip(" ,;")
    words = rest.split()
    neg = "not " if re.search(r"not|cannot", m.group("m"), re.I) else ""
    if words and words[0].lower() == "be" and len(words) > 1:
        action, obj = f"be {words[1]}", " ".join(words[2:])
    else:
        action, obj = (words[0] if words else None), " ".join(words[1:])
    return {"actor": actor, "action": (neg + action).strip(" .,;") if action else None, "object": obj.strip(" .,;") or None,
            "condition": condition}


def _tr_slots(s: str) -> dict:
    words = s.rstrip(" .!;").split()
    if not words:
        return {"actor": None, "action": None, "object": None, "condition": None}
    condition = None
    for m in TR_COND.finditer(s):
        if m.end() < len(s) * 0.85:
            condition_end = m.end()
            comma = s.find(",", condition_end - 1)
            cut = comma + 1 if 0 <= comma - condition_end < 25 else condition_end
            condition, s = s[:cut].strip(" ,"), s[cut:].strip(" ,")
            words = s.rstrip(" .!;").split()
            break
    if not words:
        return {"actor": None, "action": None, "object": None, "condition": condition}
    verb = words[-1]
    stem = TR_MODAL_SUFFIX.sub("", verb.lower()) or verb.lower()
    action_words = 1
    if TR_LIGHT.match(verb.lower()) and len(words) >= 2:   # "onay verilmelidir", "kayıt altına alınmalıdır"
        stem, action_words = f"{words[-2].lower()} {stem}", 2
    body = words[:-action_words]
    actor = None
    base = stem.split()[-1]
    passive = bool(re.search(r"(?:[ıiuü]l|[ıiuü]n|[aeıiouöü]n|[aeıiouöü]l)$", base)) and len(base) > 3   # açıl, saklan, geçiril
    predicate = base in PREDICATES                                                                    # zorunlu(dur), yasak(tır)
    if "tarafından" in body:
        k = body.index("tarafından")
        actor, body = " ".join(body[max(0, k - 5):k]), body[k + 1:]
    elif not passive and not predicate:
        lead = []
        for w in body:
            if re.search(r"[,;:]$", w) and not re.search(r"\d", w):   # "Sistem sahibi, erişim taleplerini ..." -> the subject
                lead.append(w.rstrip(",;:"))
                break
            if re.search(r"\d|[,;:]$", w) or (lead and re.search(r"(?:[ıiuü]|y[ıiuü]|n[ıiuü]|[ae]|y[ae]|n[ae]|d[ae]|t[ae]|d[ae]n|t[ae]n|nd[ae]n?)$", w.lower())):
                break
            lead.append(w)
            if len(lead) >= 4:
                break
        if lead and len(lead) < len(body):
            actor, body = " ".join(lead), body[len(lead):]
    return {"actor": actor, "action": stem or None, "object": " ".join(body[:14]).strip(" ,;") or None, "condition": condition}


def gherkin(lines: list[str]) -> list[dict]:
    """Acceptance criteria from Given / When / Then lines (and Turkish equivalents): one statement per Then, with the
    preceding Given and When lines as its condition."""
    out, cond, last = [], [], None
    for line in lines:
        m = GHERKIN.match(line)
        if not m:
            cond, last = [], None
            continue
        k = norm(m.group("k"))
        kind = {"given": "given", "diyelim ki": "given", "when": "when", "eger": "when", "oldugunda": "when", "then": "then",
                "o zaman": "then"}.get(k, last)
        if kind in ("given", "when"):
            cond.append(m.group("text").strip())
        elif kind == "then":
            out.append({"kind": "acceptance", "modality": "obligation", "actor": None, "action": m.group("text").strip(" ."),
                        "object": None, "condition": "; ".join(cond) or None, "exception": None, "confidence": "high",
                        "text": line.strip(" -*")})
        last = kind
    return out
