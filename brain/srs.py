"""Requirements writer: a Software Requirements Specification (SRS) that any person can read, following an editable
FORMAT (template), in one of two modes:
  * existing (default): describe what the system does and what the documents say, from the codebases (code graph)
    and the documents (document graph);
  * new: specify a capability that does not exist yet, from the request. The knowledge base is used as context
    (current behaviour, terms, rules, systems to connect to, what the change affects), not as the source of the
    requirements; nothing new is claimed to exist.

Formats (data/srs/templates/*.md, editable in the UI) are plain Markdown:
  * `#` line          the document title; {{title}}, {{date}}, {{scope}}, {{language}} are filled in;
  * `##` sections     written in order; the `>` lines right under a heading are the instructions for that
                      section (they are not copied to the output); text without `>` is kept as written;
  * `[per capability]` in a section's instructions: that section is written once PER CAPABILITY (feature area)
                      with a `###` heading each, e.g. the functional requirements;
  * <!-- comments --> are notes for the format author and are removed.

Engine (one background job, progress visible):
  1. evidence: relevance-pipeline search for the topic, an architecture overview of every repository in scope,
     document passages and domain entities;
  2. plan: the model lists the capabilities (feature areas, in business words) with search queries for each;
  3. per capability: targeted search + a grounded writing call (tools allowed) -> requirements in EARS form;
  4. every other section: one grounded call with the section instructions, the plan and the capability texts;
  5. assemble: IDs numbered (FR-001, BR-001, NFR-001 ...), traceability appendix with the code and document
     sources for the technical team (the body stays free of technical detail), saved to data/srs/output/.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path

from . import agents, llm, query as qa, search
from . import settings as cfg

SRS_SYSTEM = f"""You are the AI-BRAIN requirements writer: a senior business analyst who writes Software Requirements
Specifications that business people, testers and managers understand without technical knowledge. You derive
requirements from evidence: what the current system's code DOES and what the organisation's documents SAY.

{agents.GROUNDING}

<writing_rules>
- Plain language for non-technical readers. Do NOT mention class, function, file, table, endpoint or library names,
  programming languages or frameworks in the text. Translate technical facts into business behaviour
  (e.g. "retries the bank request three times" instead of "PaymentGateway.charge loops 3 times").
- Each requirement is ONE testable statement in EARS form, using "shall":
    Ubiquitous:  The <system> shall <response>.
    Event:       When <trigger>, the <system> shall <response>.
    State:       While <state>, the <system> shall <response>.
    Unwanted:    If <unwanted condition>, then the <system> shall <response>.
    Optional:    Where <feature is included>, the <system> shall <response>.
- Quality (ISO/IEC/IEEE 29148): necessary, unambiguous (no "fast", "user-friendly", "etc.", "and/or"), complete,
  singular (one behaviour per requirement), feasible, verifiable (measurable values where the evidence gives them),
  consistent with the other requirements.
- Requirement IDs: write FR-? for functional, BR-? for business rules, NFR-? for quality requirements; they are
  numbered automatically afterwards.
- Under each functional requirement: **Why:** one sentence (business reason); **Acceptance criteria:** 1-3 bullets
  in Given / When / Then form; **Status:** Implemented | Partly implemented | Documented only (in documents, not
  found in code) | Implemented, not documented.
- Never invent behaviour, numbers or rules. If something important is unknown, put it under open issues.
- Output Markdown only, no preamble.
</writing_rules>"""

PLAN_SYSTEM = """You plan a Software Requirements Specification. From the evidence, identify the CAPABILITIES (feature
areas a business user would recognise, e.g. "Customer invoicing", "Refunds", "User sign-in") within the requested
topic and scope. Return ONLY JSON:
{"system_name": "<plain name of the system>", "summary": "<2-3 plain sentences>",
 "capabilities": [{"name": "<business name>", "description": "<one plain sentence>",
                   "queries": ["<search query>", "<search query in English code terms>"]}],
 "glossary": [{"term": "<business term>", "definition": "<plain definition>"}]}
Order capabilities by importance. Use the language requested for names, descriptions and glossary."""

NEW_GROUNDING = """<grounding_rules>
- Facts about the CURRENT system (what exists, how it works, its rules) come ONLY from <knowledge_base> and your tool
  results; never invent them. The NEW capability is proposed from the request.
- When the material says nothing about something the new capability needs, propose sensible behaviour and mark it
  "to be confirmed"; do not present it as existing.
- Code shows what the system DOES; documents show what it SHOULD do. Report conflicts that affect the new capability.
- When the scope is a set of repositories, consider EVERY repository in the set.
- Write in the SAME LANGUAGE as the request.
</grounding_rules>"""

NEW_RULES = """<new_feature_rules>
This specification is for something NEW that the request asks for: it is not implemented yet and may not be
mentioned in any document. The knowledge base is CONTEXT, not the source of the requirements:
- Derive the requirements from the request. Choose sensible, testable behaviour for what the request leaves open,
  and list every choice you made under the open issues as "to be confirmed".
- Use the knowledge base for the current behaviour, business terms, rules that the new capability must respect,
  data it reuses, systems it connects to, and the existing capabilities it changes. Use the organisation's own terms.
- Never claim that the new behaviour already exists. If the evidence shows that part of it exists, say so.
- Status of each functional requirement: New | Changes existing behaviour | Partly implemented.
</new_feature_rules>"""

SRS_NEW_SYSTEM = SRS_SYSTEM.replace(agents.GROUNDING, NEW_GROUNDING).replace(
    "You derive\nrequirements from evidence: what the current system's code DOES and what the organisation's documents SAY.",
    "You specify NEW\ncapabilities from a request, consistent with what the current system does and what the documents say.") \
    .replace("**Status:** Implemented | Partly implemented | Documented only (in documents, not\n  found in code) | "
             "Implemented, not documented.", "**Status:** New | Changes existing behaviour | Partly implemented.") \
    .replace("- Never invent behaviour, numbers or rules. If something important is unknown, put it under open issues.",
             "- Never invent facts about the CURRENT system; new behaviour is proposed, and every assumption goes under "
             "open issues as \"to be confirmed\".") + "\n\n" + NEW_RULES

PLAN_NEW_SYSTEM = """You plan a Software Requirements Specification for a NEW capability that the request asks for (it does
not exist yet). Identify the CAPABILITIES the new feature needs, from the REQUEST (use the evidence only to name
things the way the organisation does and to see which existing capabilities are affected). Return ONLY JSON:
{"system_name": "<plain name of the new capability>", "summary": "<2-3 plain sentences: what is new and why>",
 "capabilities": [{"name": "<business name>", "description": "<one plain sentence>",
                   "queries": ["<search query for related existing code or rules>", "<the same in English code terms>"]}],
 "glossary": [{"term": "<business term>", "definition": "<plain definition>"}]}
Order capabilities by importance. Use the language requested for names, descriptions and glossary."""

DEFAULT_TEMPLATE = """# Software Requirements Specification - {{title}}
<!-- FORMAT GUIDE (this comment is removed from the output)
     - "## " starts a section; the "> " lines under it are the instructions the writer follows.
     - Put [per capability] in a section's instructions to write that section once per capability.
     - Placeholders: {{title}} {{date}} {{scope}} {{language}}. Text without "> " is copied as it is. -->

| | |
|---|---|
| Version | Draft generated by AI-BRAIN on {{date}} |
| Scope | {{scope}} |

## 1. Introduction
> In plain words: what this system (or feature) is for, who this document is for, and what is in and out of
> scope. Two or three short paragraphs.

## 2. Users and stakeholders
> A table "User group | What they need from the system", only for groups supported by the evidence.

## 3. System overview
> A short story of how people use the system from start to finish, then a bulleted list of the capabilities
> (one line each, business words only).

## 4. Functional requirements
> [per capability] One sentence about the purpose of the capability, then its requirements FR-? in EARS form,
> each with Why, Acceptance criteria (Given/When/Then) and Status.

## 5. Business rules
> Numbered rules BR-? (calculations, limits, approvals, validations, time limits) in plain language, each naming
> the capability it belongs to.

## 6. Quality requirements
> NFR-? for performance, availability, security and privacy, usability, auditability and compliance, only where
> the evidence supports them; missing ones go to section 9 as "to be decided".

## 7. Information the system keeps
> The main kinds of information the system stores, in plain words, and who may see or change them.

## 8. Connections to other systems
> Other systems or organisations the system exchanges information with (e.g. a bank, e-mail), in plain words.

## 9. Assumptions, conflicts and open issues
> Assumptions made, conflicts between documents and the current system, and questions the business must answer.

## 10. Glossary
> A table "Term | Meaning" for the business terms used in this document.
"""


NEW_TEMPLATE = """# Software Requirements Specification - {{title}} (new)
<!-- FORMAT GUIDE: the format for "something new". Same rules as the default format. -->

| | |
|---|---|
| Version | Proposal drafted by AI-BRAIN on {{date}} |
| Scope | {{scope}} |
| Status | Proposed: not implemented yet |

## 1. Introduction
> In plain words: what is requested, why it is needed, who this document is for, and what is in and out of scope.

## 2. Current situation
> How the related part of the system works today and which business rules already apply, from the evidence only.
> Say clearly if nothing related exists yet.

## 3. Users and stakeholders
> A table "User group | What they need from the new capability".

## 4. Proposed solution overview
> A short story of how people will use the new capability from start to finish, then a bulleted list of its
> capabilities (one line each, business words only).

## 5. Functional requirements
> [per capability] One sentence about the purpose of the capability, then its requirements FR-? in EARS form,
> each with Why, Acceptance criteria (Given/When/Then) and Status (New, Changes existing behaviour, Partly implemented).

## 6. Business rules
> Numbered rules BR-? the new capability introduces or must respect (existing rules: say so).

## 7. Quality requirements
> NFR-? for performance, availability, security and privacy, usability, auditability and compliance; values the
> request does not give are proposed and marked "to be confirmed".

## 8. Impact on the current system
> Existing capabilities, information and connections to other systems that change, in plain words, and what users of
> those capabilities will notice.

## 9. Rollout and migration
> How the new capability can be introduced: existing data to convert, switch-over, training, only if relevant.

## 10. Assumptions and open questions
> Every choice made where the request was silent, as "to be confirmed", and the questions the business must answer.

## 11. Glossary
> A table "Term | Meaning" for the business terms used in this document.
"""
BUILT_IN = {"default": DEFAULT_TEMPLATE, "new-feature": NEW_TEMPLATE}
MODES = ("existing", "new")


# ---------------------------------------------------------------- formats (templates)
def _tdir() -> Path:
    d = cfg.path("srs", "templates")
    for name, text in BUILT_IN.items():
        if not (d / f"{name}.md").exists():
            (d / f"{name}.md").write_text(text, encoding="utf-8")
    return d


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
    sections = parse(text)[1]
    if not sections:
        raise ValueError("a format needs at least one '## ' section")
    (_tdir() / f"{_safe(name)}.md").write_text(text, encoding="utf-8")
    return _safe(name)


def delete_template(name: str) -> None:
    if _safe(name) in BUILT_IN:
        raise ValueError(f"the built-in format '{_safe(name)}' cannot be deleted (edit it instead)")
    (_tdir() / f"{_safe(name)}.md").unlink(missing_ok=True)


def parse(text: str) -> tuple[str, list[dict]]:
    """-> (header text before the first section, [{heading, instructions, body, per_capability}])"""
    text = re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)
    header, sections, cur = [], [], None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = {"heading": line[3:].strip(), "instructions": [], "body": []}
            sections.append(cur)
        elif cur is None:
            header.append(line)
        elif line.startswith(">") and not cur["body"]:
            cur["instructions"].append(line.lstrip("> ").rstrip())
        else:
            cur["body"].append(line)
    for s in sections:
        s["instructions"] = " ".join(x for x in s["instructions"] if x)
        s["per_capability"] = "[per capability]" in s["instructions"].lower()
        s["instructions"] = re.sub(r"\[per capability\]\s*", "", s["instructions"], flags=re.I)
        s["body"] = "\n".join(s["body"]).strip()
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
                    "mode": m.get("mode", "existing"),
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
    return {"tr": "Turkish", "en": "English"}.get(qa.analyze(topic)["language"], "English")


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, flags=re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def _number(md: str) -> str:
    for prefix in ("FR", "BR", "NFR"):
        counter = iter(range(1, 10000))
        md = re.sub(rf"\b{prefix}-(?:\?|[0-9X]+|\{{\w*\}})", lambda m: f"{prefix}-{next(counter):03d}", md)
    return md


def write(topic: str, set_name: str | None = None, repo_names: list[str] | None = None, template: str | None = None,
          language: str | None = None, model: str | None = None, title: str | None = None, mode: str = "existing",
          log=lambda *a, **k: None) -> dict:
    """mode: existing = describe what the code does and the documents say; new = specify something new from the
    request, with the knowledge base as context."""
    mode = mode if mode in MODES else "existing"
    template = template or ("new-feature" if mode == "new" else "default")
    system = SRS_NEW_SYSTEM if mode == "new" else SRS_SYSTEM
    t0 = time.time()
    llm.start_meter()
    deadline = t0 + cfg.get("BRAIN_SRS_TIMEOUT")
    model = model or cfg.model("srs")
    lang = _language(topic, language)
    header, sections = parse(get_template(template))
    ctx = agents.Context(set_name, repo_names)
    scope_text = ", ".join(p.split("--")[0] for p in ctx.projects) or "documents only"
    errors: list[str] = []
    sources: dict[str, set] = {}

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
    seed = search.search(topic, "all", set_name, repo_names, extra_terms=agents.expand(topic, qa.analyze(topic), "srs", model))
    note_sources("(overall)", seed)
    arch = []
    for p in ctx.projects[:8]:
        try:
            arch.append(f"### {p.split('--')[0]}\n" + ctx.run_tool("overview", {"repo": p})[:2500])
        except Exception as exc:
            errors.append(f"overview {p}: {exc}")
    evidence = "<architecture>\n" + "\n".join(arch) + "\n</architecture>" if arch else ""

    # 2. plan
    log("planning the capabilities", 0.1)
    plan = {}
    try:
        msg = llm.chat([{"role": "system", "content": PLAN_NEW_SYSTEM if mode == "new" else PLAN_SYSTEM},
                        {"role": "user", "content": f"{ctx.describe()}\n{evidence}\n<knowledge_base>\n{search.render(seed, 12000)}\n"
                                                    f"</knowledge_base>\n<request>{'New capability requested' if mode == 'new' else 'Topic'}: {topic}\nLanguage: {lang}\n"
                                                    f"At most {cfg.get('BRAIN_SRS_MAX_CAPABILITIES')} capabilities.</request>"}],
                       model, timeout=min(remaining(), cfg.get("BRAIN_LLM_TIMEOUT")), max_tokens=2000, temperature=0.1)
        plan = _json(msg["content"])
    except llm.LLMError as exc:
        errors.append(f"plan: {exc}")
    caps = [c for c in plan.get("capabilities", []) if isinstance(c, dict) and c.get("name")]
    caps = caps[: cfg.get("BRAIN_SRS_MAX_CAPABILITIES")] or [{"name": topic, "description": topic, "queries": [topic]}]
    system_name = plan.get("system_name") or topic
    plan_text = (f"System: {system_name}\nSummary: {plan.get('summary', '')}\nCapabilities:\n"
                 + "\n".join(f"- {c['name']}: {c.get('description', '')}" for c in caps))
    log(f"{len(caps)} capabilities: " + ", ".join(c["name"] for c in caps), 0.15)

    # 3. per-capability sections
    cap_texts: dict[str, str] = {}
    per_cap = [s for s in sections if s["per_capability"]]
    for i, cap in enumerate(caps):
        if remaining() < 60:
            errors.append("time budget (BRAIN_SRS_TIMEOUT) reached; remaining capabilities skipped")
            break
        log(f"writing capability {i + 1}/{len(caps)}: {cap['name']}", 0.15 + 0.6 * i / len(caps))
        q = " ".join([cap["name"], cap.get("description", "")] + list(cap.get("queries") or [])[:3])[:600]
        r = search.search(q, "all", set_name, repo_names)
        note_sources(cap["name"], r)
        instr = " ".join(s["instructions"] for s in per_cap) or "Functional requirements for this capability."
        res = agents.run_agent("srs", system,
                               f"<plan>\n{plan_text}\n</plan>\n<task>Write the part for the capability "
                               f"\"{cap['name']}\" ({cap.get('description', '')}). Section instructions: {instr}\n"
                               f"Start with a line '### {cap['name']}'. Language: {lang}.</task>",
                               ctx, r, model=model, limits=limits())
        errors += [e for e in res["errors"] if e not in errors]
        cap_texts[cap["name"]] = res["output"] or f"### {cap['name']}\n\n_(not written: {'; '.join(res['errors'][-1:])})_"

    # 4. other sections
    written = "\n\n".join(cap_texts.values())
    body: list[str] = []
    others = [s for s in sections if not s["per_capability"]]
    for s in sections:
        if s["per_capability"]:
            body.append(f"## {s['heading']}\n\n" + (s["body"] + "\n\n" if s["body"] else "") + written)
            continue
        if not s["instructions"]:
            body.append(f"## {s['heading']}\n\n{s['body']}")
            continue
        if remaining() < 30:
            body.append(f"## {s['heading']}\n\n_(not written: time budget reached)_")
            continue
        log(f"writing section: {s['heading']}", 0.75 + 0.2 * others.index(s) / max(1, len(others)))
        res = agents.run_agent("srs", system,
                               f"<plan>\n{plan_text}\n</plan>\n<capability_requirements>\n{written[:14000]}\n"
                               f"</capability_requirements>\n<glossary_candidates>{json.dumps(plan.get('glossary', []), ensure_ascii=False)}"
                               f"</glossary_candidates>\n<task>Write ONLY the body of the section \"{s['heading']}\" "
                               f"(no heading line). Instructions: {s['instructions']}\nStay consistent with the capability "
                               f"requirements. Language: {lang}.</task>",
                               ctx, seed, evidence, model=model, limits=limits(), tools=False)
        errors += [e for e in res["errors"] if e not in errors]
        body.append(f"## {s['heading']}\n\n" + (s["body"] + "\n\n" if s["body"] else "")
                    + (res["output"] or "_(not written)_"))

    # 5. assemble
    title = title or system_name
    fill = {"title": title, "date": dt.date.today().isoformat(), "scope": scope_text, "language": lang}
    head = re.sub(r"\{\{(\w+)\}\}", lambda m: fill.get(m.group(1), m.group(0)), header)
    trace = (["## Appendix - Related existing system (for the technical team)",
              "The existing code and documents each new capability touches or must stay consistent with. The body "
              "of the document is written for non-technical readers."] if mode == "new" else
             ["## Appendix - Traceability (for the technical team)",
              "Where the requirements of each capability were found. The body of the document is written for "
              "non-technical readers; these references let developers and testers verify it."])
    for cap, refs in sources.items():
        if refs:
            trace.append(f"- **{cap}**: " + ", ".join(sorted(refs)[:12]))
    md = _number("\n\n".join([head] + body + ["\n".join(trace)]))
    md = re.sub(r"\{\{(\w+)\}\}", lambda m: fill.get(m.group(1), m.group(0)), md)
    name = f"{dt.datetime.now():%Y%m%d-%H%M}-" + (re.sub(r"[^\w]+", "-", title.lower()).strip("-")[:50] or "srs")
    (_odir() / f"{name}.md").write_text(md, encoding="utf-8")
    meta = {"title": title, "topic": topic, "mode": mode, "scope": scope_text, "template": template, "language": lang,
            "model": model, "capabilities": [c["name"] for c in caps], "errors": errors,
            "usage": llm.read_meter(), "seconds": round(time.time() - t0, 1)}
    (_odir() / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log("done", 1.0)
    return {"name": name, "markdown": md, "evidence": search.evidence(seed), "analysis": seed["analysis"], **meta}
