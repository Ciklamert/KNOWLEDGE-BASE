"""Option (b) the prompt-enhancer agent, option (c) the ask agent, and the shared agent loop the requirements
writer (brain/srs.py) also uses.

Every agent run:
  1. prompt analysis + (optional) model query expansion -> the relevance pipeline (brain/search.py) seeds the
     conversation with grounded context (saves round trips, works even without tool calling);
  2. the model may call read-only AI-BRAIN tools (search, semantic, docs, symbol, trace, snippet, read,
     grep, files, overview) for at most MAX_STEPS rounds, within the role's total TIMEOUT;
  3. the model writes the final output in the user's language.
Prompt design follows current guidance for grounded (RAG) agents: role and goal first; retrieved material in
clearly tagged blocks BEFORE the request (long-context ordering); answer only from the material, cite every
claim, say what is missing instead of guessing; explicit output structure; handle conflicts between code and
documents; cover every repository of a set. Models are chosen per request (UI combobox / API "model").
If the gateway does not support tool calling, the loop degrades to one grounded call (BRAIN_AGENT_TOOL_CALLING).
If the model is unreachable, the caller still gets the search results / a deterministic enhanced prompt.
"""
from __future__ import annotations

import json
import re
import time

from . import drift, llm, providers, query as qa, repos, search
from . import settings as cfg

GROUNDING = """<grounding_rules>
- Use ONLY the material inside <knowledge_base> and the results of your tool calls. Do not use general knowledge
  to fill gaps about THIS organisation's systems; never invent files, symbols, endpoints, numbers or business rules.
- If the material is insufficient, say exactly what is missing and which repository/document would contain it,
  then give the best partial answer that the material supports. "Not found in the knowledge base" is a valid answer.
- Code shows what the system DOES; documents show what it SHOULD do or why. When they disagree, report the
  disagreement explicitly (it is valuable) instead of picking one silently.
- When the scope is a set of repositories, consider EVERY repository in the set; say which repository each
  finding comes from, and check the others with tools (repo=...) before concluding something does not exist.
- Cite inline: code as `repo/path:line-line`, documents as [document name].
- Write in the SAME LANGUAGE as the user's request (Turkish request -> Turkish output). Keep identifiers, file
  names and code unchanged.
</grounding_rules>"""

TOOL_GUIDE = """<tool_use>
The knowledge base already combined three sources for you: the code graph (symbols, calls, inheritance), the code
vector indexes (code by meaning) and the document graph (business entities, rules, passages). Each code hit shows
where it is, why it matched, its signature and its callers/callees. Check whether this answers the request; if
not, call tools: `search` (all three sources; scope=code|docs|semantic, repo=... for one repository), `semantic`
(code by meaning, for concepts with unknown names), `docs` (documents only), `symbol` (definition, callers,
callees), `trace` (call chains for impact), `snippet` (full source of a symbol), `read` (lines of any file),
`grep` (exact text / regex), `files` (file paths matching a glob), `overview` (architecture of one repository).
Prefer a few precise calls; stop calling tools as soon as you can answer well.
</tool_use>"""

ASK_SYSTEM = f"""You are the AI-BRAIN ask agent: a senior engineer and domain analyst who knows this organisation's
codebases (code graph) and business documents (document graph: specifications, rules, decisions, procedures).
Your goal: a correct, verifiable answer that a developer or analyst can act on.

{GROUNDING}

{TOOL_GUIDE}

<answer_format>
1. **Answer** - the direct answer in 1-4 sentences (yes/no first when the question is yes/no).
2. **Details** - how it works / why, as short bullets or numbered steps, each with its citation. For flows,
   follow the call chain in order (entry point -> ... -> result). Include the relevant business rules.
3. **Where to look** - the 2-6 most useful code locations and documents.
4. **Gaps and conflicts** - only if something is missing, uncertain or contradictory.
Use Markdown. No preamble, no repetition of the question, no generic advice.
</answer_format>"""

ENHANCE_SYSTEM = f"""You are the AI-BRAIN prompt enhancer: a staff engineer who prepares work for an AI coding agent
(Claude Code, opencode, pi, Copilot ...). Turn the developer's short request into a precise, self-contained,
implementation-ready prompt grounded in this organisation's code graph and document graph, so the coding agent
can start working without exploring blindly.

{GROUNDING}

{TOOL_GUIDE}

<method>
1. Classify the intent: feature, bug fix, refactor, test, investigation, documentation or question.
2. Locate the exact code: entry points (routes, handlers, jobs), the symbols to change, their callers (impact),
   data models, configuration, existing tests to extend, and similar existing code to imitate.
3. Collect the business rules and constraints from documents that the change must respect.
4. Keep the plan minimal: the smallest change that satisfies the request; no unrequested refactors.
5. If the request is ambiguous, do not guess silently: choose the most likely interpretation, state it as an
   assumption, and list the open question.
</method>

<output_format>
Output ONLY the enhanced prompt, in Markdown, with exactly these sections (omit a section only if empty):
## Task
What to achieve and why, in 1-3 sentences (intent type in brackets, e.g. [bug fix]).
## Context
Bullets: `repo/path:line` - symbol - what it does and why it matters (change / read / imitate).
## Business rules and constraints
Bullets with [document name]; conventions visible in the code (error handling, logging, naming).
## Impact
Callers and dependants that may break; interfaces, APIs, database schemas and contracts to keep compatible.
## Implementation plan
Numbered, concrete steps in order, each naming the file/symbol to touch.
## Acceptance criteria
Checkable bullets; tests to add or update (unit/integration), including edge cases and error paths.
## Out of scope
What the agent must NOT change.
## Open questions and assumptions
Only if any.
## Notes for the agent
Branch/freshness warnings if given; "verify the listed files in your working copy before editing".
</output_format>"""

EXPAND_SYSTEM = """You turn a developer's or analyst's request into search terms for a code + document knowledge base.
Return ONLY a JSON array of at most 10 short strings, most useful first:
- likely code identifiers in English (class, function, field, endpoint names in camelCase / snake_case / PascalCase),
- English translations of non-English domain words, and the Turkish word when the request is in English,
- close synonyms used in business documents.
Do not repeat the words already given as key terms. No explanations."""

TOOLS = [
    {"type": "function", "function": {"name": "search", "description": "Search code AND documents (relevance pipeline).",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"},
                    "scope": {"type": "string", "enum": ["all", "code", "semantic", "docs"]},
                    "repo": {"type": "string", "description": "limit to one repository of the scope"}},
                    "required": ["query"]}}},
    {"type": "function", "function": {"name": "semantic", "description": "Find code by meaning (concepts whose names you do not know).",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "repo": {"type": "string"}},
                    "required": ["query"]}}},
    {"type": "function", "function": {"name": "docs", "description": "Search only the documents (rules, specs, decisions).",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "symbol",
     "description": "Definition, source, callers and callees of a class/function/method by name.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "trace", "description": "Call chain of a function (who calls it / what it calls).",
     "parameters": {"type": "object", "properties": {"function_name": {"type": "string"},
                    "direction": {"type": "string", "enum": ["inbound", "outbound", "both"]},
                    "repo": {"type": "string"}}, "required": ["function_name"]}}},
    {"type": "function", "function": {"name": "snippet", "description": "Full source of a symbol (qualified or short name).",
     "parameters": {"type": "object", "properties": {"qualified_name": {"type": "string"}, "repo": {"type": "string"}},
                    "required": ["qualified_name"]}}},
    {"type": "function", "function": {"name": "read", "description": "Numbered lines of a file in a repository (max 400).",
     "parameters": {"type": "object", "properties": {"repo": {"type": "string"}, "path": {"type": "string"},
                    "start": {"type": "integer"}, "end": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "grep", "description": "Exact text or regex search over the code, ranked by the graph.",
     "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "regex": {"type": "boolean"},
                    "file_pattern": {"type": "string"}, "repo": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "files", "description": "File paths matching a glob, e.g. **/*.sql or src/billing/*.",
     "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "repo": {"type": "string"}},
                    "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "overview",
     "description": "Architecture of one repository: languages, packages, entry points, routes, hotspots.",
     "parameters": {"type": "object", "properties": {"repo": {"type": "string"}}, "required": ["repo"]}}},
]
LIMITS = {   # role -> setting keys (timeout, max steps, max tokens, temperature)
    "ask": ("BRAIN_ASK_TIMEOUT", "BRAIN_ASK_MAX_STEPS", "BRAIN_ASK_MAX_TOKENS", "BRAIN_ASK_TEMPERATURE"),
    "enhance": ("BRAIN_ENHANCE_TIMEOUT", "BRAIN_ENHANCE_MAX_STEPS", "BRAIN_ENHANCE_MAX_TOKENS", "BRAIN_ENHANCE_TEMPERATURE"),
}
_native = {"ok": True}   # flips to False once the gateway rejects `tools` (auto mode)


def expand(prompt: str, analysis: dict, role: str, model: str | None = None) -> list[str]:
    """One short model call: extra search terms (identifiers, translations, synonyms). Never blocks: [] on error."""
    if not cfg.get("BRAIN_QUERY_EXPANSION"):
        return []
    try:
        msg = llm.chat([{"role": "system", "content": EXPAND_SYSTEM},
                        {"role": "user", "content": f"Request: {prompt[:2000]}\nKey terms already used: "
                                                    + ", ".join(analysis["keywords"])}],
                       model or cfg.model(role), timeout=cfg.get("BRAIN_QUERY_EXPANSION_TIMEOUT"), max_tokens=200,
                       temperature=0)
    except llm.LLMError:
        return []
    m = re.search(r"\[.*?\]", msg["content"], flags=re.S)
    try:
        terms = json.loads(m.group(0)) if m else []
    except ValueError:
        terms = []
    return [str(t).strip() for t in terms if isinstance(t, (str, int)) and 1 < len(str(t).strip()) <= 60][:10]


class Context:
    """The scope a request runs in (repository set / repositories / branch)."""

    def __init__(self, set_name=None, repo_names=None, branch=None):
        self.set_name, self.repo_names, self.branch = set_name, repo_names, branch
        self.projects = repos.resolve_scope(set_name, repo_names, branch)

    def describe(self) -> str:
        names = ", ".join(p.split("--")[0] for p in self.projects) or "none indexed"
        if self.repo_names and len(self.repo_names) == 1:
            return f"<scope>One repository: {names}.</scope>"
        label = f"set '{self.set_name}'" if self.set_name and self.set_name != "all" else "all repositories"
        return (f"<scope>{label} = {len(self.projects)} repositories: {names}. The request is about ALL of them: "
                f"look at every repository, not only the first one.</scope>")

    def project(self, repo: str | None) -> str:
        if repo:
            for p in self.projects:
                if p == repo or p.startswith(repo + "--"):
                    return p
            return repo
        if not self.projects:
            raise ValueError("no indexed repository in scope")
        return self.projects[0]

    def run_tool(self, name: str, a: dict) -> str:
        code = providers.code()
        repo_only = [a["repo"]] if a.get("repo") else self.repo_names
        if name in ("search", "docs", "semantic"):
            scope = "docs" if name == "docs" else "semantic" if name == "semantic" else a.get("scope") or "all"
            r = search.search(a.get("query", ""), scope, None if a.get("repo") else self.set_name, repo_only, self.branch)
            return search.render(r, 9000) or "no results"
        if name == "symbol":
            return code.symbol(a.get("name", ""), self.projects)
        if name == "trace":
            return code.tool("trace", {"function_name": a["function_name"], "project": self.project(a.get("repo")),
                                       "direction": a.get("direction") or "both", "depth": 3})
        if name == "snippet":
            return code.tool("snippet", {"qualified_name": a["qualified_name"], "project": self.project(a.get("repo"))})
        if name == "overview":
            return code.tool("architecture", {"project": self.project(a.get("repo")), "aspects": ["overview"]})
        if name == "read":
            r = code.read(self.project(a.get("repo")), a["path"], a.get("start") or 1, a.get("end"))
            return f"{r['project']}/{r['path']} lines {r['start']}-{r['end']} of {r['total_lines']}\n{r['text']}"
        targets = [self.project(a["repo"])] if a.get("repo") else self.projects
        if name == "grep":
            return "\n\n".join(f"## {p}\n" + code.grep(p, a["pattern"], bool(a.get("regex")), a.get("file_pattern"))
                               for p in targets) or "no indexed repository"
        if name == "files":
            return "\n".join(f"{p}/{f}" for p in targets for f in code.files(p, a.get("pattern") or "*")) or "no files"
        raise ValueError(f"unknown tool {name}")


def run_agent(role: str, system: str, user: str, ctx: Context, seed: dict | None, extra: str = "",
              model: str | None = None, limits: tuple | None = None, tools: bool = True) -> dict:
    """Shared agent loop. Material first (tagged), request last. Returns {output, steps, llm, errors}."""
    timeout, max_steps, max_tokens, temperature = (cfg.get(k) if isinstance(k, str) else k
                                                   for k in (limits or LIMITS[role]))
    model = model or cfg.model(role)
    mode = cfg.get("BRAIN_AGENT_TOOL_CALLING")
    deadline = time.time() + timeout
    parts = [ctx.describe()]
    if seed is not None:
        parts.append("<prompt_analysis>" + qa.summary(seed["analysis"])
                     + " Focus on the key terms, in this order of importance.</prompt_analysis>")
        parts.append("<knowledge_base>\n" + (search.render(seed) or "(the automatic search returned nothing)")
                     + "\n</knowledge_base>")
    if extra:
        parts.append(extra)
    parts.append(user)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]
    steps, errors = [], list((seed or {}).get("errors", []))
    use_tools = tools and (mode == "native" or (mode == "auto" and _native["ok"]))
    for step in range(max_steps + 1):
        remaining = deadline - time.time()
        final = step == max_steps or remaining < 15 or not use_tools
        if remaining <= 2:
            errors.append(f"{role}: total timeout ({timeout:.0f}s) reached")
            break
        try:
            msg = llm.chat(msgs, model, timeout=min(remaining, cfg.get("BRAIN_LLM_TIMEOUT")), max_tokens=max_tokens,
                           temperature=temperature, tools=None if final else TOOLS)
        except llm.LLMError as exc:
            if not final and mode == "auto" and exc.status in (400, 404, 422, 501):
                _native["ok"], use_tools = False, False      # gateway without tool calling: degrade, retry once
                errors.append("tool calling not supported by the gateway; answering from the automatic search")
                continue
            errors.append(f"{role}: {exc}")
            break
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"output": msg["content"], "steps": steps, "llm": True, "errors": errors, "model": model}
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls[:4]:
            fn = c.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
                result = ctx.run_tool(fn.get("name", ""), args)
            except Exception as exc:
                args, result = {}, f"tool error: {exc}"
            steps.append({"tool": fn.get("name"), "args": args, "chars": len(result)})
            msgs.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": result[:8000]})
        for c in calls[4:]:
            msgs.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": "skipped: max 4 tools per round"})
    return {"output": "", "steps": steps, "llm": False, "errors": errors, "model": model}


def _seed(text: str, role: str, ctx: Context, model: str | None, log) -> dict:
    log("analysing the request", 0.05)
    terms = expand(text, qa.analyze(text), role, model)
    if terms:
        log("model-expanded search terms: " + ", ".join(terms), 0.08)
    log("searching code and documents", 0.1)
    seed = search.search(text, "all", ctx.set_name, ctx.repo_names, ctx.branch, extra_terms=terms)
    log("key terms: " + ", ".join(seed["analysis"]["keywords"][:8]), 0.2)
    log(f"found {len(seed['code'])} code hits in {len({h['project'] for h in seed['code']})} repositories, "
        f"{len((seed.get('docs') or {}).get('chunks', []))} passages", 0.3)
    return seed


def ask(question: str, set_name=None, repo_names=None, branch=None, model: str | None = None,
        log=lambda *a, **k: None) -> dict:
    t0 = time.time()
    ctx = Context(set_name, repo_names, branch)
    seed = _seed(question, "ask", ctx, model, log)
    log("asking the model", 0.4)
    res = run_agent("ask", ASK_SYSTEM, f"<question>\n{question}\n</question>", ctx, seed, model=model)
    answer = res["output"] or ("The language model did not answer (" + "; ".join(res["errors"][-2:]) +
                               "). These are the most relevant AI-BRAIN results:\n\n" + search.render(seed))
    return {"answer": answer, "llm": res["llm"], "model": res["model"], "steps": res["steps"],
            "sources": search.sources(seed), "evidence": search.evidence(seed), "analysis": seed["analysis"],
            "errors": res["errors"],
            "ms": int((time.time() - t0) * 1000)}


def enhance(prompt: str, set_name=None, repo_names=None, branch=None, repo: str | None = None,
            base_commit: str | None = None, changed_files: list[str] | None = None, model: str | None = None,
            log=lambda *a, **k: None) -> dict:
    t0 = time.time()
    ctx = Context(set_name, repo_names, branch)
    seed = _seed(prompt, "enhance", ctx, model, log)
    extra, drift_report = "", None
    if branch and (repo or len(ctx.projects) == 1):
        try:
            log("checking branch drift", 0.35)
            drift_report = drift.check(repo or ctx.projects[0].split("--")[0], branch, base_commit, changed_files)
            extra = "<branch_freshness>(include in 'Notes for the agent')\n" + drift.render(drift_report) + "\n</branch_freshness>"
        except Exception as exc:
            seed["errors"].append(f"branch check: {exc}")
    log("writing the enhanced prompt", 0.4)
    res = run_agent("enhance", ENHANCE_SYSTEM, f"<developer_request>\n{prompt}\n</developer_request>", ctx, seed, extra,
                    model=model)
    enhanced = res["output"] or fallback_prompt(prompt, seed, drift_report)
    return {"enhanced": enhanced, "llm": res["llm"], "model": res["model"], "steps": res["steps"],
            "sources": search.sources(seed), "evidence": search.evidence(seed), "analysis": seed["analysis"],
            "drift": drift_report,
            "errors": res["errors"], "ms": int((time.time() - t0) * 1000)}


def fallback_prompt(prompt: str, seed: dict, drift_report: dict | None) -> str:
    """Deterministic enhanced prompt when the model is unavailable: the request plus grounded context."""
    files = list(dict.fromkeys(f"`{h['project']}/{h['path']}:{h['line1']}` — {h['label']} `{h['name']}`"
                               for h in seed["code"]))
    out = ["## Task", prompt.strip(), "", "Key terms: " + ", ".join(seed["analysis"]["keywords"]), "",
           "## Relevant code"] + [f"- {f}" for f in files[:10]]
    ctx = search.render(seed, 9000)
    if ctx:
        out += ["", "## Knowledge-base context", ctx]
    if drift_report:
        out += ["", "## Notes for the agent", drift.render(drift_report)]
    out += ["", "Verify the listed files in your working copy before editing."]
    return "\n".join(out)
