"""Requirements writer: a Software Requirements Specification (SRS) in plain language, in YOUR format.

Formats are entirely the user's: there is no built-in one. A format is any Markdown document (typed in the UI, or a
Word/PDF template converted with /api/convert): its headings are the sections to write, in order, and the text under
each heading says what belongs there (or is example text to replace). The writer follows the format's sections,
numbering, requirement IDs and fields exactly; {{title}}, {{date}}, {{scope}} and {{language}} are filled in when used.

One request field, no modes. The request is whatever the user gives, of any length (pasted, or converted from a
document): a topic of the current system ("refunds"), system requirements, a new idea, or a mix. The writer checks it
against the current code (code graph) and documents (document graph) and gives every requirement a status: what
already exists, what must change, what is new. Nothing new is claimed to exist.

Engine (one background job, progress visible):
  1. evidence: a search for the request, an architecture overview of every repository in scope, documents;
  2. plan: the model lists the capabilities (feature areas in business words) with search queries and the part
     of the request each one comes from, and picks the format sections to write once per capability;
  3. per capability: a targeted search + a grounded writing call (tools allowed);
  4. every other section: one grounded call with the section's guidance, the plan and the capability texts;
  5. assemble: placeholders filled, IDs like "FR-?" numbered per prefix, an appendix for the technical team with the
     code and documents behind each capability; saved to data/srs/output/.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path

from . import agents, llm, query as qa, search
from . import settings as cfg

WRITING_RULES = """<writing_rules>
- Follow the FORMAT exactly: its sections, headings, numbering, requirement ID style, fields and conventions. The text
  under a format heading tells you what to write there; replace example text, keep fixed text.
- Plain language for business people, testers and managers. Do NOT mention class, function, file, table, endpoint or
  library names, programming languages or frameworks; describe business behaviour ("retries the bank request three
  times", not "PaymentGateway.charge loops 3 times").
- One testable statement per requirement, with "shall", unless the format prescribes another sentence style.
- Quality (ISO/IEC/IEEE 29148): necessary, unambiguous (no "fast", "user-friendly", "etc."), complete, singular,
  feasible, verifiable (measurable values where known), consistent.
- Requirement IDs: use the format's style with "?" for the number (e.g. FR-?, SRS-?); they are numbered afterwards.
- Output Markdown only, no preamble.
</writing_rules>"""

RULES = """<grounding_rules>
- The REQUEST is the source of the requirements. It is either a topic of the current system (then describe what the
  system does and what the documents say about it), or system requirements / a new idea (then cover every part of
  it), or a mix of both.
- Facts about the CURRENT system come ONLY from <knowledge_base> and your tool results; never invent behaviour,
  numbers or rules. Use them to say what already exists, what must change, which rules apply and which systems and
  data are affected.
- Where the request asks for something the system does not do and is silent on details, propose sensible, testable
  behaviour and mark it "to be confirmed". Unknowns about the current system go to the open issues.
- Code shows what the system DOES; documents what it SHOULD do. Report conflicts that matter for the request.
- When the scope is a set of repositories, consider EVERY repository in the set.
- Write in the SAME LANGUAGE as the request.
</grounding_rules>

<status_rules>
Where the format has a status field use it, otherwise add "(Status: …)" to each requirement: Implemented |
Partly implemented | Changes existing behaviour | New | Documented only (in documents, not in code) | Implemented, not
documented. Never claim that new behaviour already exists.
</status_rules>"""

ROLE = """You are the AI-BRAIN requirements writer: a senior business analyst who writes Software Requirements
Specifications that people without technical knowledge understand."""

PLAN = """You plan a Software Requirements Specification. Identify the CAPABILITIES (feature areas a business user
recognises, e.g. "Customer invoicing", "Refunds"): for a topic of the current system, the ones the evidence shows within
it; for system requirements or a new idea, the ones it asks for (every part of the request must belong to a
capability), named the way the organisation does. Return ONLY JSON:
{"system_name": "<plain name>", "summary": "<2-3 plain sentences>",
 "capabilities": [{"name": "<business name>", "description": "<one plain sentence>",
                   "excerpt": "<the words of the request this capability comes from>",
                   "queries": ["<search query for related code or rules>", "<the same in English code terms>"]}],
 "per_capability_sections": [<numbers of the format sections that must be written once per capability, e.g. the
                              functional requirements; [] if none>],
 "glossary": [{"term": "<business term>", "definition": "<plain definition>"}]}
Order capabilities by importance. Use the language requested for names, descriptions and glossary."""

# ---------------------------------------------------------------- formats (the user's own)
def _tdir() -> Path:
    return cfg.path("srs", "templates")


def _safe(name: str) -> str:
    n = re.sub(r"[^\w .-]+", "-", Path(str(name)).stem).strip(" .-")
    if not n:
        raise ValueError("format name required")
    return n


def templates() -> list[str]:
    return sorted(p.stem for p in _tdir().glob("*.md"))


def get_template(name: str) -> str:
    f = _tdir() / f"{_safe(name)}.md"
    if not f.exists():
        raise KeyError(f"unknown format {name}")
    return f.read_text(encoding="utf-8")


def save_template(name: str, text: str) -> str:
    if not parse(text)[1]:
        raise ValueError("a format needs headings: each heading is a section to write")
    (_tdir() / f"{_safe(name)}.md").write_text(text, encoding="utf-8")
    return _safe(name)


def delete_template(name: str) -> None:
    (_tdir() / f"{_safe(name)}.md").unlink(missing_ok=True)


def parse(text: str) -> tuple[str, list[dict]]:
    """-> (text before the first section, [{heading, guidance}]). The sections are the headings of the most used
    level that occurs at least twice (## in most formats, # in a converted Word template); deeper headings stay inside
    their section as structure to follow."""
    text = re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)
    lines = text.splitlines()
    levels = [len(m.group(1)) for line in lines if (m := re.match(r"(#{1,4})\s+\S", line))]
    level = next((lv for lv in (2, 1, 3, 4) if levels.count(lv) >= 2), min(levels, default=0))
    if not level:
        return text.strip(), []
    header, sections = [], []
    for line in lines:
        m = re.match(r"(#{1,4})\s+(.*)", line)
        if m and len(m.group(1)) == level:
            sections.append({"heading": m.group(2).strip(), "guidance": []})
        elif sections:
            sections[-1]["guidance"].append(line)
        else:
            header.append(line)
    for s in sections:
        s["guidance"] = "\n".join(s["guidance"]).strip()
    return "\n".join(header).strip(), sections


# ---------------------------------------------------------------- outputs
def _odir() -> Path:
    return cfg.path("srs", "output")


def documents() -> list[dict]:
    out = []
    for f in sorted(_odir().glob("*.md"), key=lambda p: -p.stat().st_mtime):
        meta = f.with_suffix(".json")
        m = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        out.append({"name": f.stem, "title": m.get("title", f.stem), "created": f.stat().st_mtime,
                    "scope": m.get("scope"), "template": m.get("template"), "model": m.get("model"),
                    "chars": f.stat().st_size})
    return out


def read(name: str) -> str:
    f = _odir() / f"{_safe(name)}.md"
    if not f.exists():
        raise KeyError(f"unknown specification {name}")
    return f.read_text(encoding="utf-8")


def delete(name: str) -> None:
    for suffix in (".md", ".json"):
        (_odir() / f"{_safe(name)}{suffix}").unlink(missing_ok=True)


# ---------------------------------------------------------------- engine
def _language(topic: str, language: str | None) -> str:
    lang = (language or cfg.get("BRAIN_SRS_LANGUAGE") or "auto").strip()
    if lang.lower() != "auto":
        return lang
    return {"tr": "Turkish", "en": "English"}.get(qa.analyze(topic[:4000])["language"], "English")


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, flags=re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def _number(md: str) -> str:
    """FR-? FR-? BR-? -> FR-001 FR-002 BR-001: every prefix the format uses is numbered on its own."""
    counters: dict[str, int] = {}

    def nxt(m):
        counters[m.group(1)] = counters.get(m.group(1), 0) + 1
        return f"{m.group(1)}-{counters[m.group(1)]:03d}"
    return re.sub(r"\b([A-Z]{1,6})-(?:\?|X+|\{\w*\})", nxt, md)


def write(topic: str, set_name: str | None = None, repo_names: list[str] | None = None, template: str | None = None,
          language: str | None = None, model: str | None = None, title: str | None = None,
          log=lambda *a, **k: None) -> dict:
    """topic: the request, any length: a topic of the current system, system requirements, a new idea, or a mix."""
    names = templates()
    if not names:
        raise ValueError("there is no format yet: add your organisation's format under Requirements > Formats "
                         "(type it, or load a Word/PDF template)")
    template = template or names[0]
    header, sections = parse(get_template(template))
    system = f"{ROLE}\n\n{RULES}\n\n{WRITING_RULES}"
    t0 = time.time()
    llm.start_meter()
    deadline = t0 + cfg.get("BRAIN_SRS_TIMEOUT")
    model = model or cfg.model("srs")
    lang = _language(topic, language)
    ctx = agents.Context(set_name, repo_names)
    scope_text = ", ".join(p.split("--")[0] for p in ctx.projects) or "documents only"
    errors: list[str] = []
    sources: dict[str, set] = {}
    request = topic.strip()[:40000]

    def remaining() -> float:
        return deadline - time.time()

    def limits(tokens=None):
        return (max(30.0, remaining()), 3, tokens or cfg.get("BRAIN_SRS_MAX_TOKENS"), cfg.get("BRAIN_SRS_TEMPERATURE"))

    def note_sources(cap: str, r: dict):
        s = sources.setdefault(cap, set())
        s.update(f"`{h['project']}/{h['path']}:{h['line1']}`" for h in r["code"][:6])
        s.update(f"[{c['source']}]" for c in (r.get("docs") or {}).get("chunks", [])[:4])

    # 1. evidence
    log("collecting evidence: search, architecture of each repository, documents", 0.03)
    seed = search.search(request[:4000], "all", set_name, repo_names,
                         extra_terms=agents.expand(request[:2000], qa.analyze(request[:4000]), "srs", model))
    note_sources("(overall)", seed)
    arch = []
    for p in ctx.projects[:8]:
        try:
            arch.append(f"### {p.split('--')[0]}\n" + ctx.run_tool("overview", {"repo": p})[:2500])
        except Exception as exc:
            errors.append(f"overview {p}: {exc}")
    evidence = "<architecture>\n" + "\n".join(arch) + "\n</architecture>" if arch else ""
    outline = "\n".join(f"{i + 1}. {s['heading']}: {' '.join(s['guidance'].split())[:200]}" for i, s in enumerate(sections))

    # 2. plan
    log("planning the capabilities", 0.1)
    plan = {}
    try:
        msg = llm.chat([{"role": "system", "content": PLAN},
                        {"role": "user", "content": f"{ctx.describe()}\n{evidence}\n<knowledge_base>\n{search.render(seed, 12000)}\n"
                                                    f"</knowledge_base>\n<format_sections>\n{outline}\n</format_sections>\n"
                                                    f"<request>\n{request[:30000]}\n</request>\nLanguage: {lang}. At most "
                                                    f"{cfg.get('BRAIN_SRS_MAX_CAPABILITIES')} capabilities."}],
                       model, timeout=min(remaining(), cfg.get("BRAIN_LLM_TIMEOUT")), max_tokens=3000, temperature=0.1)
        plan = _json(msg["content"])
    except llm.LLMError as exc:
        errors.append(f"plan: {exc}")
    caps = [c for c in plan.get("capabilities", []) if isinstance(c, dict) and c.get("name")]
    caps = caps[: cfg.get("BRAIN_SRS_MAX_CAPABILITIES")] or [{"name": request[:80], "description": request[:300],
                                                             "queries": [request[:300]], "excerpt": request[:3000]}]
    per_cap = {int(n) - 1 for n in plan.get("per_capability_sections") or [] if str(n).isdigit() and 0 < int(n) <= len(sections)}
    system_name = plan.get("system_name") or request[:80]
    plan_text = (f"System: {system_name}\nSummary: {plan.get('summary', '')}\nCapabilities:\n"
                 + "\n".join(f"- {c['name']}: {c.get('description', '')}" for c in caps))
    log(f"{len(caps)} capabilities: " + ", ".join(c["name"] for c in caps), 0.15)

    # 3. the per-capability sections
    cap_texts: dict[str, str] = {}
    guidance = "\n\n".join(f"### {sections[i]['heading']}\n{sections[i]['guidance']}" for i in sorted(per_cap))
    if per_cap:
        for i, cap in enumerate(caps):
            if remaining() < 60:
                errors.append("time budget (BRAIN_SRS_TIMEOUT) reached; remaining capabilities skipped")
                break
            log(f"writing capability {i + 1}/{len(caps)}: {cap['name']}", 0.15 + 0.6 * i / len(caps))
            q = " ".join([cap["name"], cap.get("description", "")] + list(cap.get("queries") or [])[:3])[:600]
            r = search.search(q, "all", set_name, repo_names)
            note_sources(cap["name"], r)
            part = f"\n<request_part>\n{cap.get('excerpt') or ''}\n</request_part>" if cap.get("excerpt") else ""
            res = agents.run_agent("srs", system,
                                   f"<plan>\n{plan_text}\n</plan>{part}\n<format_guidance>\n{guidance}\n</format_guidance>\n"
                                   f"<task>Write the part for the capability \"{cap['name']}\" ({cap.get('description', '')}) "
                                   f"following the format guidance. Start with a line '### {cap['name']}'. "
                                   f"Language: {lang}.</task>", ctx, r, model=model, limits=limits())
            errors += [e for e in res["errors"] if e not in errors]
            cap_texts[cap["name"]] = res["output"] or f"### {cap['name']}\n\n_(not written: {'; '.join(res['errors'][-1:])})_"
    written = "\n\n".join(cap_texts.values())

    # 4. the other sections
    body: list[str] = []
    others = [i for i in range(len(sections)) if i not in per_cap]
    for i, s in enumerate(sections):
        if i in per_cap:
            body.append(f"## {s['heading']}\n\n" + written)
            continue
        if remaining() < 30:
            body.append(f"## {s['heading']}\n\n_(not written: time budget reached)_")
            continue
        log(f"writing section: {s['heading']}", 0.75 + 0.2 * others.index(i) / max(1, len(others)))
        req = f"<request>\n{request[:20000]}\n</request>\n"
        res = agents.run_agent("srs", system,
                               f"<plan>\n{plan_text}\n</plan>\n{req}<capability_requirements>\n{written[:14000]}\n"
                               f"</capability_requirements>\n<glossary_candidates>{json.dumps(plan.get('glossary', []), ensure_ascii=False)}"
                               f"</glossary_candidates>\n<format_section heading=\"{s['heading']}\">\n{s['guidance']}\n"
                               f"</format_section>\n<task>Write ONLY the body of the section \"{s['heading']}\" (no heading "
                               f"line), following the format section's guidance and staying consistent with the capability "
                               f"requirements. Language: {lang}.</task>",
                               ctx, seed, evidence, model=model, limits=limits(), tools=False)
        errors += [e for e in res["errors"] if e not in errors]
        body.append(f"## {s['heading']}\n\n" + (res["output"] or "_(not written)_"))

    # 5. assemble
    title = title or system_name
    fill = {"title": title, "date": dt.date.today().isoformat(), "scope": scope_text, "language": lang}
    head = re.sub(r"\{\{(\w+)\}\}", lambda m: fill.get(m.group(1), m.group(0)), header) or f"# {title}"
    trace = ["## Appendix - Where it comes from (for the technical team)",
             "The code and documents behind each capability: the current situation the requirements were checked against."]
    for cap, refs in sources.items():
        if refs:
            trace.append(f"- **{cap}**: " + ", ".join(sorted(refs)[:12]))
    md = _number("\n\n".join([head] + body + ["\n".join(trace)]))
    md = re.sub(r"\{\{(\w+)\}\}", lambda m: fill.get(m.group(1), m.group(0)), md)
    name = f"{dt.datetime.now():%Y%m%d-%H%M}-" + (re.sub(r"[^\w]+", "-", title.lower()).strip("-")[:50] or "srs")
    (_odir() / f"{name}.md").write_text(md, encoding="utf-8")
    meta = {"title": title, "topic": request[:500], "scope": scope_text, "template": template,
            "language": lang, "model": model, "capabilities": [c["name"] for c in caps], "errors": errors,
            "usage": llm.read_meter(), "seconds": round(time.time() - t0, 1)}
    (_odir() / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log("done", 1.0)
    return {"name": name, "markdown": md, "evidence": search.evidence(seed), "analysis": seed["analysis"], **meta}
