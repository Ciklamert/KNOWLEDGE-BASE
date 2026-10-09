"""Option (a): search the code graph, the code vector indexes and the document graph together, without any chat call.

Pipeline (each stage can be switched off in Settings; see docs/05-SEARCH-ASK-ENHANCE.md):
  0. prompt analysis (brain/query.py): stop-words out, key terms ranked, variants and concepts built;
  1. recall, in parallel: code = BM25 over key terms + variants and semantic search over key terms inside the code
     engine (no network) + the corporate multilingual code vector index (brain/codevec.py, BRAIN_CODE_VECTORS);
     documents = LightRAG graph + vector retrieval with concepts as high-level and key terms as low-level keywords
     (embedding call only); scope "semantic" = code by meaning only (both vector indexes, no BM25);
  2. document -> code bridge (BRAIN_DOC_BRIDGE): the domain entities the documents returned (e.g. "Payment
     Gateway", "Retry Policy") become extra code-search terms, so business words in Turkish or English reach the
     code that implements them;
  3. code-graph expansion (BRAIN_GRAPH_EXPAND): callers, callees and parents of the best hits join the
     candidates, so code wired to the matches is found even when it shares no words with the question;
  4. re-ranking (BRAIN_RERANK): the full prompt and every candidate (code snippet / document passage) are embedded
     with the corporate MULTILINGUAL embedding model and ordered by meaning, blended with the lexical rank.
     A Turkish question therefore ranks English code by what it means, not only by shared words;
  5. repository balance: when several repositories are searched (a set), every repository with relevant code
     keeps a place in the result, so a set answer looks at all of its codebases; every hit is annotated from the
     graph (signature, callers, callees, parents) and says which source found it (field "matched").
Every result therefore combines the three sources: code graph, code vector indexes and document graph.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from . import codevec, llm, providers, query as qa, repos
from . import settings as cfg

_pool = ThreadPoolExecutor(8, thread_name_prefix="search")
_cache: "OrderedDict[str, list[float]]" = OrderedDict()   # text hash -> embedding (re-ranking)
_cache_lock = threading.Lock()


def _embed(texts: list[str]) -> list[list[float]]:
    keys = [hashlib.sha1(t.encode("utf-8", "replace")).hexdigest() for t in texts]
    with _cache_lock:
        missing = [i for i, k in enumerate(keys) if k not in _cache]
    if missing:
        vecs = llm.embed([texts[i] for i in missing], timeout=cfg.get("BRAIN_SEARCH_TIMEOUT"))
        with _cache_lock:
            for i, v in zip(missing, vecs):
                _cache[keys[i]] = v
            while len(_cache) > 20000:
                _cache.popitem(last=False)
    with _cache_lock:
        return [_cache[k] for k in keys]


def _cos(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def rerank(query: str, items: list[dict], text, keep: int, weight: float | None = None) -> list[dict]:
    """Order items by blend = w * semantic similarity (corporate embeddings) + (1 - w) * lexical rank score."""
    if len(items) < 2:
        return items[:keep]
    w = cfg.get("BRAIN_RERANK_WEIGHT") if weight is None else weight
    vecs = _embed([query[:2000]] + [text(it)[:2000] for it in items])
    qv, n = vecs[0], len(items)
    for i, (it, v) in enumerate(zip(items, vecs[1:])):
        it["similarity"] = round(_cos(qv, v), 4)
        it["rerank"] = round(w * it["similarity"] + (1 - w) * (1 - i / n), 4)
    return sorted(items, key=lambda it: -it["rerank"])[:keep]


def _code_text(h: dict) -> str:
    return f"{h['label']} {h['name']} {h['qn']} {h['path']}\n{h.get('code') or ''}"


def _bridge_terms(docs: dict, known: list[str]) -> list[str]:
    """Domain entity names from the document results, as extra code-search terms."""
    seen = {k.casefold() for k in known}
    stop = qa._stopwords()
    out: list[str] = []
    for e in (docs.get("entities") or [])[:8]:
        name = str(e.get("name") or "")
        for w in re.findall(r"[^\W_][\w.-]{2,}", name):
            if w.casefold() not in seen and w.casefold() not in stop:
                seen.add(w.casefold())
                out.append(w)
        compact = re.sub(r"\W+", "", name)   # "Payment Gateway" -> PaymentGateway (identifier style)
        if " " in name.strip() and len(compact) > 5 and compact.casefold() not in seen:
            seen.add(compact.casefold())
            out.append(compact)
    return out[:12]


def _diversify(hits: list[dict], k: int) -> list[dict]:
    """Keep the order, but guarantee every repository that has hits at least one of the first k places
    (two when there is room), so a question about a set sees all its codebases."""
    projects = list(dict.fromkeys(h["project"] for h in hits))
    if len(projects) < 2:
        return hits[:k]
    per = 2 if k >= 2 * len(projects) else 1
    chosen = []
    for p in projects:
        chosen += [h for h in hits if h["project"] == p][:per]
    chosen = sorted(chosen, key=hits.index)[:k]
    rest = [h for h in hits if h not in chosen]
    return sorted(chosen + rest[:max(0, k - len(chosen))], key=hits.index)


def _merge(primary: list[dict], extra: list[dict], weight: float = 0.5) -> list[dict]:
    """Reciprocal-rank merge of two hit lists (the second list counts `weight`); `matched` reasons are united."""
    score: dict[tuple, float] = {}
    hits: dict[tuple, dict] = {}
    for lst, wgt in ((primary, 1.0), (extra, weight)):
        for rank, h in enumerate(lst):
            key = (h["project"], h["qn"])
            score[key] = score.get(key, 0) + wgt / (60 + rank)
            if key in hits:
                hits[key]["matched"] = list(dict.fromkeys(hits[key].get("matched", []) + h.get("matched", [])))
                if "similarity" in h and "similarity" not in hits[key]:
                    hits[key]["similarity"] = h["similarity"]
            else:
                hits[key] = h
    return [hits[key] for key in sorted(score, key=lambda x: -score[x])]


def _tag(hits: list[dict], reason: str) -> list[dict]:
    for h in hits:
        h["matched"] = list(dict.fromkeys(h.get("matched", []) + [reason]))
    return hits


def search(query: str, scope: str = "all", set_name: str | None = None, repo_names: list[str] | None = None,
           branch: str | None = None, k: int | None = None, extra_terms: list[str] | None = None) -> dict:
    """scope: all (code + documents) | code | semantic (code by meaning only) | docs."""
    t0 = time.time()
    k = int(k or cfg.get("BRAIN_SEARCH_TOP_K"))
    chunks = cfg.get("BRAIN_SEARCH_DOC_CHUNKS")
    use_rerank = cfg.get("BRAIN_RERANK")
    pool_k = max(k, cfg.get("BRAIN_RERANK_CANDIDATES")) if use_rerank else k
    analysis = qa.analyze(query)
    if extra_terms:   # model-expanded terms (ask / enhance / requirements), after the user's own key terms
        known = {x.casefold() for x in analysis["keywords"] + analysis["variants"]}
        analysis["expanded"] = [t for t in extra_terms if t.casefold() not in known][:12]
    kw = analysis["keywords"] + analysis["variants"] + analysis.get("expanded", [])
    out = {"query": query, "scope": scope, "analysis": analysis, "code": [], "relations": [], "docs": {},
           "projects": [], "pipeline": ["prompt analysis"], "errors": []}
    f_code = f_docs = f_vec = None
    projects: list[str] = []
    code = providers.code()
    # 1. recall from the three sources in parallel
    if scope in ("all", "code", "semantic"):
        try:
            projects = repos.resolve_scope(set_name, repo_names, branch)
            out["projects"] = projects
            if projects:
                f_code = _pool.submit(code.search, query, kw, projects, pool_k,
                                      "semantic" if scope == "semantic" else "hybrid")
                if codevec.enabled():
                    f_vec = _pool.submit(lambda: codevec.search(_embed([query[:2000]])[0], projects, pool_k))
            else:
                out["errors"].append("code: no indexed repository in this scope yet")
        except KeyError as exc:
            out["errors"].append(f"code: {exc.args[0]}")
    if scope in ("all", "docs"):
        f_docs = _pool.submit(providers.docs().search, query, kw, chunks * 2 if use_rerank else chunks,
                              cfg.get("LIGHTRAG_TOP_K"), analysis["concepts"])
    timeout = cfg.get("BRAIN_SEARCH_TIMEOUT")
    code_hits: list[dict] = []
    if f_code:
        try:
            code_hits = f_code.result(timeout=timeout)
            out["pipeline"].append("code graph search (keywords + local code vectors)" if scope != "semantic"
                                   else "local code vectors")
        except Exception as exc:
            out["errors"].append(f"code: {exc or 'timeout'}")
    if f_vec:
        try:
            vec_hits = _tag(f_vec.result(timeout=timeout), "multilingual code vectors")
            if vec_hits:
                code_hits = _merge(code_hits, vec_hits, 1.0)
                out["pipeline"].append("multilingual code vector index")
        except Exception as exc:
            out["errors"].append(f"code vectors: {exc or 'timeout'}")
    if f_docs:
        try:
            out["docs"] = f_docs.result(timeout=timeout)
            out["pipeline"].append("document graph (entities, relations, passages)")
        except Exception as exc:
            out["errors"].append(f"docs: {exc or 'timeout'}")
    # 2. document -> code bridge: business terms from the document graph become code-search terms
    if projects and scope != "semantic" and cfg.get("BRAIN_DOC_BRIDGE") and out["docs"]:
        terms = _bridge_terms(out["docs"], kw)
        if terms:
            try:
                extra = _tag(code.search(" ".join(terms), terms, projects, pool_k), "document terms")
                code_hits = _merge(code_hits, extra)
                analysis["bridged"] = terms
                out["pipeline"].append(f"document -> code bridge ({len(terms)} terms)")
            except Exception as exc:
                out["errors"].append(f"bridge: {exc}")
    # 3. code-graph expansion: callers / callees / parents of the best hits
    if projects and scope != "semantic" and cfg.get("BRAIN_GRAPH_EXPAND") and code_hits:
        try:
            near = code.neighbors(code_hits[:cfg.get("BRAIN_GRAPH_EXPAND_TOP")], pool_k)
            if near:
                code_hits = _merge(code_hits, near, 0.5)
                out["pipeline"].append(f"code graph expansion ({len(near)} neighbours)")
        except Exception as exc:
            out["errors"].append(f"graph expansion: {exc}")
    code_hits = code_hits[:pool_k * 2]   # bound the re-ranking cost
    # 4. semantic re-ranking with the corporate embedding model
    if use_rerank and (len(code_hits) > 1 or len(out["docs"].get("chunks") or []) > 1):
        try:
            if code_hits:
                code_hits = rerank(query, code.with_code(code_hits), _code_text, len(code_hits))
            if out["docs"].get("chunks"):
                out["docs"]["chunks"] = rerank(query, out["docs"]["chunks"], lambda c: c["content"], chunks)
            out["pipeline"].append("semantic re-rank")
        except Exception as exc:
            out["errors"].append(f"re-rank skipped: {exc}")
    # 5. final: repository balance, source lines, graph context (signature, callers, callees)
    out["code"] = code.annotate(code.with_code(_diversify(code_hits, k)))
    if out["docs"].get("chunks"):
        out["docs"]["chunks"] = out["docs"]["chunks"][:chunks]
    if out["code"]:
        try:
            out["relations"] = code.relations(out["code"][:6], 30)
        except Exception as exc:
            out["errors"].append(f"relations: {exc}")
    m = [x for h in out["code"] for x in h.get("matched", [])]
    d = out["docs"] or {}
    out["sources"] = {"code graph": sum(1 for x in m if x == "keywords" or x.startswith("code graph") or x == "document terms"),
                      "code vectors": sum(1 for x in m if "vectors" in x),
                      "document passages": len(d.get("chunks") or []), "document entities": len(d.get("entities") or []),
                      "document facts": len(d.get("relations") or []), "code relations": len(out["relations"])}
    out["ms"] = int((time.time() - t0) * 1000)
    return out


def _lang(path: str) -> str:
    ext = (path or "").rsplit(".", 1)[-1].lower()
    return {"py": "python", "ts": "typescript", "js": "javascript", "kt": "kotlin", "rs": "rust", "cs": "csharp",
            "h": "c", "hpp": "cpp", "yml": "yaml"}.get(ext, ext)


def render(r: dict, max_chars: int | None = None, snippet_lines: int = 30) -> str:
    """Markdown for people and for AI agents: every code hit says where it is, why it matched, its signature and its
    callers/callees, so an agent can work from it instead of grep/glob/read. Sections are dropped whole when the
    budget is reached (the most important come first)."""
    max_chars = max_chars or cfg.get("BRAIN_CONTEXT_MAX_CHARS")
    items: list[str] = []
    a = r.get("analysis")
    if a and a["keywords"]:
        items.append("_Key terms:_ " + ", ".join(f"`{t}`" for t in a["keywords"])
                     + (f" · _expanded:_ {', '.join(a['expanded'])}" if a.get("expanded") else "")
                     + (f" · _from documents:_ {', '.join(a['bridged'])}" if a.get("bridged") else "")
                     + (f" · _ignored stop-words:_ {', '.join(a['stop_words'])}" if a["stop_words"] else ""))
    if r.get("sources"):
        items.append("_Sources:_ " + ", ".join(f"{k} {v}" for k, v in r["sources"].items() if v)
                     + (f" · _repositories:_ {', '.join(r['projects'])}" if r.get("projects") else ""))
    if r["code"]:
        items.append("## Code (code graph + code vectors, re-ranked by meaning)")
        for i, h in enumerate(r["code"], 1):
            lines = (h.get("code") or "").splitlines()
            snip = "\n".join(lines[:snippet_lines]) + ("\n…" if len(lines) > snippet_lines else "")
            meta = []
            if h.get("signature"):
                meta.append(f"signature `{h['signature']}`")
            if h.get("callers"):
                meta.append("called by " + ", ".join(f"`{x}`" for x in h["callers"]))
            if h.get("callees"):
                meta.append("calls " + ", ".join(f"`{x}`" for x in h["callees"]))
            if h.get("parents"):
                meta.append("extends/implements " + ", ".join(f"`{x}`" for x in h["parents"]))
            if h.get("matched"):
                meta.append("found by " + ", ".join(h["matched"]))
            loc = f"{h['project']}/{h['path']}:{h['line1']}-{h['line2']}" if h.get("path") else f"{h['project']} (no file: {h['label'].lower()})"
            items.append(f"{i}. `{loc}` {h['label']} `{h['name']}`"
                         + (f" (qualified: `{h['qn']}`)" if h.get("qn") else "")
                         + ("\n   " + " · ".join(meta) if meta else "")
                         + (f"\n```{_lang(h['path'])}\n{snip}\n```" if snip.strip() else ""))
    rel = list(dict.fromkeys(f"- `{e['a']}` —{e['type']}→ `{e['b']}`" for e in r["relations"]))
    if rel:
        items.append("## Code relationships (code graph)\n" + "\n".join(rel[:25]))
    d = r.get("docs") or {}
    if d.get("chunks"):
        items.append("## Document passages (document graph)")
        for c in d["chunks"]:
            items.append(f"> **{c['source']}**: " + " ".join(c["content"].split())[:1000])
    if d.get("entities"):
        items.append("## Domain entities (document graph)\n" + "\n".join(
            f"- **{e['name']}** ({e['type']}): {e['description'][:240]}" for e in d["entities"][:12]))
    if d.get("relations"):
        items.append("## Domain facts (document graph)\n" + "\n".join(
            f"- {e['a']} → {e['b']}: {e['description'][:220]}" for e in d["relations"][:10]))
    if r["code"]:
        items.append("_Next steps:_ `snippet` (qualified name) for full source · `trace` for call chains · "
                     "`read` (repo, path, lines) for any file · `grep` for exact text · `files` to list paths.")
    out, total = [], 0
    for p in items:
        if total + len(p) > max_chars:
            continue
        out.append(p)
        total += len(p) + 2
    return "\n\n".join(out)


def sources(r: dict) -> list[dict]:
    src = [{"kind": "code", "ref": f"{h['project']}/{h['path']}:{h['line1']}-{h['line2']}" if h.get("path") else f"{h['project']}: {h['name']}",
            "name": h["name"]}
           for h in r["code"]]
    src += [{"kind": "doc", "ref": c["source"]} for c in (r.get("docs") or {}).get("chunks", [])]
    return src


def evidence(r: dict, lines: int = 15) -> dict:
    """A compact copy of a search result for the UI's evidence panel (ask, enhance, requirements)."""
    code = [{**{k: v for k, v in h.items() if k != "code"}, "code": "\n".join((h.get("code") or "").splitlines()[:lines])}
            for h in r["code"]]
    return {"code": code, "docs": r.get("docs") or {}, "relations": r.get("relations", []),
            "pipeline": r.get("pipeline", []), "sources": r.get("sources", {}), "projects": r.get("projects", [])}
