"""Prompt analysis - the first step of search, ask and enhance (no LLM call, a few milliseconds).

For every prompt AI-BRAIN first:
  1. tokenises it (Unicode: Turkish, English, code identifiers, file paths, `quoted` or "quoted" phrases);
  2. separates the STOP-WORDS (English + Turkish lists, plus BRAIN_STOPWORDS_EXTRA) from the content words;
  3. scores every content word by how much it is likely to identify something specific:
        identifier (chargeCustomer, tax_rate, Invoice.create, HTTP_503) +3   file path / extension +3
        quoted phrase +4      acronym (KDV, VAT, API) +2      repeated in the prompt +0.5 each
        longer words slightly higher; generic programming words (code, function, dosya, sınıf ...) x0.5
  4. adds search variants: Turkish case/plural suffixes stripped (Müşteriden -> Müşteri, faturaları -> fatura),
     English plurals (refunds -> refund), identifier parts (chargeCustomer -> charge, customer);
  5. builds CONCEPTS: runs of adjacent important words (e.g. "partial refund", "fatura KDV hesaplama").

The result drives everything after it:
  * code search: BM25 query = ranked key terms + variants; semantic query = ranked key terms;
  * document search: keywords = key terms + variants, concepts = multi-word themes (matched against concept names);
  * ask / enhance: the model is told the language, the key terms (most important first) and what was ignored.
"""
from __future__ import annotations

import re
from collections import Counter

from . import settings as cfg

STOP_EN = set("""
a about above after again against all also am an and any are aren't as at be because been before being below between
both but by can cannot could couldn't did didn't do does doesn't doing don't down during each else even ever every
few for from further get gets got had hadn't has hasn't have haven't having he her here hers herself him himself his
how however i i'd i'll i'm i've if in into is isn't it it's its itself just let's like me more most much must my
myself need needs no nor not now of off on once only or other ought our ours ourselves out over own please
same shall she should shouldn't so some such than that that's the their theirs them themselves then there there's
these they this those through to too under until up upon us very via was wasn't we were weren't what what's when
where which while who whom why will with within without won't would wouldn't you your yours yourself yourselves
make makes made use used using want wants wanted show tell give explain describe let thing things something way
new add adds added fix fixes change changes update implement implementation create help know see look find work
works done do does
""".split())
STOP_TR = set("""
acaba ama ancak artık aslında az bana bazen bazı bazıları belki ben beni benim beri bile bir birçok biri birkaç
birşey biz bize bizi bizim bu buna bunda bundan bunlar bunları bunların bunu bunun burada böyle böylece çok çünkü
da daha dahi de defa değil diğer diye dolayı en fakat gibi göre hala hangi hangisi hani hatta hem henüz hep hepsi
her herhangi herkes hiç hiçbir için ile ilgili ise işte itibaren kadar karşın kendi kendine kez ki kim kimden kime
kimi kimse lütfen mı mi mu mü nasıl ne neden nedir nerde nerede nereye niçin niye o olan olarak oldu olduğu olduğunu
olmak olmaz olsa olsun olup ona ondan onlar onları onların onu onun orada öyle oysa pek rağmen sadece sanki şey
şeyler şimdi şöyle şu şuna şunda şundan şunu tarafından tüm üzere var vardı ve veya ya yani yap yapar yapmak
yapılır yapın yapınız yok yine zaten icin nasil neler midir misin musun mısın yapabilir eder eden etmek ediyor
olur olabilir istiyorum ister lazım gerek gerekiyor şekilde zaman sonra önce göster anlat açıkla ekle düzelt
içinde içindeki içine içinden üzerinde altında arasında güncelle oluştur kaldır sil değiştir yaz bul getir incele
""".split())
TR_VERB = re.compile(r"(?:[ıiuü]?yor(?:um|sun|uz|lar|du|muş)?|[ıiuüae]rken|ken|mak|mek|abilir|ebilir|acak|ecek|malı|meli)$")
GENERIC = set("""
code codes function functions method methods class classes file files module modules variable variables value values
system data project repo repository error errors issue bug problem service services logic feature part
kod kodu kodda fonksiyon fonksiyonu metot metod metodu sınıf sınıfı dosya dosyası dosyada modül değişken değer
sistem veri proje hata hatası sorun özellik servis kısım
""".split())
TR_SUFFIXES = sorted("""
lerinden larından lerinde larında lerine larına lerini larını lerin ların leri ları ler lar
ndan nden ndaki ndeki daki deki taki teki dan den tan ten nın nin nun nün ın in un ün
yla yle ya ye yı yi yu yü da de ta te sı si su sü
""".split(), key=len, reverse=True)
TOKEN = re.compile(r"`[^`]{2,80}`|\"[^\"]{2,80}\"|“[^”]{2,80}”|[^\W_][\w./:\\-]*[\w]|[^\W_]", re.UNICODE)


def _stopwords() -> set[str]:
    extra = {w.strip().casefold() for w in cfg.get("BRAIN_STOPWORDS_EXTRA").split(",") if w.strip()}
    return {w.casefold() for w in STOP_EN | STOP_TR} | extra


def _kind(tok: str) -> str:
    if re.search(r"[/\\]|\.[A-Za-z]{1,5}$", tok) and not tok.endswith("."):
        return "path"
    if "_" in tok or "." in tok or "::" in tok or re.search(r"[a-zçğıöşü][A-ZÇĞİÖŞÜ]", tok) \
            or re.search(r"[A-Za-z]\d|\d[A-Za-z]", tok):
        return "identifier"
    if re.fullmatch(r"[A-ZÇĞİÖŞÜ]{2,6}s?", tok):
        return "acronym"
    if tok.isdigit():
        return "number"
    return "word"


def _variants(tok: str, kind: str, language: str) -> list[str]:
    out = []
    if kind == "identifier":
        parts = [p for p in re.split(r"[_.:\-/]+|(?<=[a-zçğıöşü0-9])(?=[A-ZÇĞİÖŞÜ])", tok) if len(p) > 2]
        out += parts if len(parts) > 1 else []
    elif kind == "word":
        low = tok.casefold()
        turkish = language in ("tr", "mixed") or re.search(r"[çğıöşü]", low)
        for suf in TR_SUFFIXES if turkish else ():   # Turkish: drop one case/plural/possessive suffix
            if low.endswith(suf) and len(low) - len(suf) >= 4:
                out.append(tok[: len(tok) - len(suf)])
                break
        if language != "tr" and re.fullmatch(r"[a-z]+", low) and len(low) > 4:   # English plurals
            if low.endswith("ies"):
                out.append(tok[:-3] + "y")
            elif low.endswith(("sses", "xes", "ches", "shes")):
                out.append(tok[:-2])
            elif low.endswith("s") and not low.endswith("ss"):
                out.append(tok[:-1])
    return out


def analyze(text: str, max_terms: int | None = None) -> dict:
    max_terms = max_terms or cfg.get("BRAIN_QUERY_MAX_TERMS")
    stop = _stopwords()
    raw = TOKEN.findall(text or "")
    seq, stops, scores, kinds = [], [], Counter(), {}
    for t in raw:
        quoted = t[0] in "`\"“"
        tok = t.strip("`\"“” ").strip(".-:")
        if not tok:
            continue
        low = tok.casefold()
        if not quoted and low in stop:
            stops.append(low)
            seq.append(None)          # phrase boundary
            continue
        kind = "phrase" if quoted else _kind(tok)
        if kind == "word" and len(tok) < 3 or kind == "number" and len(tok) < 3:
            seq.append(None)
            continue
        key = next((k for k in kinds if k.casefold() == low), tok)
        kinds.setdefault(key, kind)
        bonus = {"phrase": 4, "identifier": 3, "path": 3, "acronym": 2, "number": 0.5}.get(kind, 0)
        base = 1 + bonus + min(len(tok), 12) / 12
        if kind == "word" and any(low == g or (len(g) >= 4 and low.startswith(g)) for g in GENERIC):
            base *= 0.5           # generic programming words: kod, fonksiyonunu, file, method ...
        elif kind == "word" and len(low) > 5 and TR_VERB.search(low):
            base *= 0.5           # Turkish verb forms: uygulanıyor, oluşturuyor, alınırken ...
        scores[key] = scores[key] + 0.5 if key in scores else base
        seq.append(key)
    ranked = [k for k, _ in sorted(scores.items(), key=lambda kv: (-kv[1], list(scores).index(kv[0])))][:max_terms]
    tr = sum(1 for s in stops if s in {w.casefold() for w in STOP_TR}) + len(re.findall(r"[çğıöşüÇĞİÖŞÜ]", text or ""))
    en = sum(1 for s in stops if s in STOP_EN)
    language = "tr" if tr > en else "en" if en > tr else ("unknown" if not stops else "mixed")
    variants = []
    for k in ranked:
        for v in _variants(k, kinds[k], language):
            if v.casefold() not in stop and v.casefold() not in {x.casefold() for x in ranked + variants}:
                variants.append(v)
    # concepts: runs of adjacent content words, ranked by their summed score
    runs, cur = [], []
    for k in seq + [None]:
        if k is None or kinds.get(k) == "phrase":
            if k is not None:
                runs.append([k])
            if cur:
                runs.append(cur)
            cur = []
        else:
            cur.append(k)
    chunks = []
    for r in runs:
        for i in range(0, len(r), 3):
            c = r[i:i + 3]
            chunks.append((" ".join(c), sum(scores[x] for x in c)))
    concepts = list(dict.fromkeys(c for c, _ in sorted(chunks, key=lambda x: -x[1])))[:4]
    return {
        "language": language,
        "terms": [{"term": k, "kind": kinds[k], "score": round(scores[k], 2)} for k in ranked],
        "keywords": ranked,                                  # most important first
        "variants": variants,                                # stems / identifier parts, for lexical search
        "identifiers": [k for k in ranked if kinds[k] in ("identifier", "path")],
        "concepts": concepts or ranked[:3],                  # multi-word themes, for graph (high-level) retrieval
        "stop_words": list(dict.fromkeys(stops)),
        "tokens": len(raw),
    }


def summary(a: dict) -> str:
    """One paragraph for language models and people."""
    return (f"Prompt analysis (language: {a['language']}). Key terms, most important first: "
            + ", ".join(f"{t['term']} ({t['kind']})" for t in a["terms"])
            + (f". Concepts: {'; '.join(a['concepts'])}" if a["concepts"] else "")
            + (f". Search variants: {', '.join(a['variants'])}" if a["variants"] else "")
            + (f". Model-expanded terms: {', '.join(a['expanded'])}" if a.get("expanded") else "")
            + (f". Terms found via documents: {', '.join(a['bridged'])}" if a.get("bridged") else "")
            + (f". Ignored stop-words: {', '.join(a['stop_words'])}." if a["stop_words"] else "."))
