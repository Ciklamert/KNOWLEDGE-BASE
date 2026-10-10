"""The ask agent, the prompt enhancer, the project guide, and the shared agent loop the requirements writer
(brain/srs.py) also uses.

Every agent run:
  1. prompt analysis + (optional) model query expansion -> the relevance pipeline (brain/search.py) seeds the
     conversation with grounded context (saves round trips, works even without tool calling);
  2. the model may call read-only AI-BRAIN tools (search, semantic, docs, symbol, trace, outline, read, grep,
     files, overview) for at most MAX_STEPS rounds, within the role's total TIMEOUT; a repeated identical call is
     answered with a short note instead of the same result;
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
where it is, why it matched, its signature and its callers/callees. If that answers the request, do not call tools.
Otherwise pick the cheapest tool that answers the next question:
- one symbol's source, callers and callees: `symbol`; call chains for impact: `trace`;
- a file: `outline` first (declarations with line ranges), then `read` only the lines you need;
- exact text or regex: `grep` (mode=files to only locate); file paths by glob: `files`;
- new concepts: `search` (detail=brief to scan widely), `semantic` (code by meaning), `docs` (documents only);
- a repository's structure: `overview`.
Use repo=... to target one repository. Stop calling tools as soon as you can answer well.
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

def _fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


_S, _I, _B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
TOOLS = [
    _fn("search", "Search code (graph + vectors) and documents.",
        {"query": _S, "scope": {"type": "string", "enum": ["all", "code", "semantic", "docs"]},
         "detail": {"type": "string", "enum": ["brief", "normal", "full"]}, "repo": _S}, ["query"]),
    _fn("semantic", "Find code by meaning (concepts whose names you do not know).", {"query": _S, "repo": _S}, ["query"]),
    _fn("docs", "Search only the documents (rules, specs, decisions).", {"query": _S}, ["query"]),
    _fn("symbol", "A symbol by name: location, signature, source, callers, callees.",
        {"name": _S, "source": {"type": "string", "enum": ["auto", "full", "none"]}, "repo": _S}, ["name"]),
    _fn("trace", "Call chain of a function (who calls it / what it calls).",
        {"function_name": _S, "direction": {"type": "string", "enum": ["inbound", "outbound", "both"]}, "repo": _S},
        ["function_name"]),
    _fn("outline", "Declarations of one file with line ranges.", {"path": _S, "repo": _S}, ["path"]),
    _fn("read", "Numbered lines of a file (max 400).", {"path": _S, "start": _I, "end": _I, "repo": _S}, ["path"]),
    _fn("grep", "Exact text or regex in the code; mode=files lists only the files.",
        {"pattern": _S, "regex": _B, "mode": {"type": "string", "enum": ["files", "matches", "full"]},
         "file_pattern": _S, "path": _S, "repo": _S}, ["pattern"]),
    _fn("files", "File paths matching a glob, e.g. **/*.sql.", {"pattern": _S, "repo": _S}, ["pattern"]),
    _fn("overview", "A repository's structure: languages, packages, entry points, routes, hotspots, file tree.",
        {"repo": _S, "path": _S, "aspects": {"type": "array", "items": {"type": "string", "enum": [
            "overview", "structure", "routes", "hotspots", "entry_points", "dependencies", "layers", "file_tree"]}}},
        ["repo"]),
]


def cap(text: str, hint: str = "narrow the request") -> str:
    """Keep one tool answer within BRAIN_TOOL_MAX_TOKENS (about 4 characters per token)."""
    limit = cfg.get("BRAIN_TOOL_MAX_TOKENS") * 4
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    return text[:cut if cut > limit // 2 else limit] + f"\n… (cut at about {limit // 4} tokens; {hint})"


LIMITS = {   # role -> setting keys (timeout, max steps, max tokens, temperature)
    "ask": ("BRAIN_ASK_TIMEOUT", "BRAIN_ASK_MAX_STEPS", "BRAIN_ASK_MAX_TOKENS", "BRAIN_ASK_TEMPERATURE"),
    "enhance": ("BRAIN_ENHANCE_TIMEOUT", "BRAIN_ENHANCE_MAX_STEPS", "BRAIN_ENHANCE_MAX_TOKENS", "BRAIN_ENHANCE_TEMPERATURE"),
    "guide": ("BRAIN_GUIDE_TIMEOUT", "BRAIN_GUIDE_MAX_STEPS", "BRAIN_GUIDE_MAX_TOKENS", "BRAIN_GUIDE_TEMPERATURE"),
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

    def targets(self, repo: str | None) -> list[str]:
        return [self.project(repo)] if repo else self.projects

    def _first(self, repo: str | None, fn):
        """Run fn(project) on the named repository, or on the first repository of the scope where it works."""
        errors = []
        for p in self.targets(repo):
            try:
                return fn(p)
            except (KeyError, RuntimeError, ValueError) as exc:
                errors.append(f"{p}: {exc}")
        raise KeyError("; ".join(errors) or "no indexed repository in scope")

    def run_tool(self, name: str, a: dict) -> str:
        code = providers.code()
        repo = a.get("repo") or None
        if name in ("search", "docs", "semantic"):
            scope = "docs" if name == "docs" else "semantic" if name == "semantic" else a.get("scope") or "all"
            r = search.search(a.get("query", ""), scope, None if repo else self.set_name,
                              [repo] if repo else self.repo_names, self.branch)
            return search.render(r, 9000, a.get("detail")) or "no results"
        if name == "symbol":
            return cap(code.symbol(a.get("name", ""), self.targets(repo), a.get("source") or "auto"),
                       "use read(repo, path, start, end) for the rest")
        if name == "trace":
            return code.tool("trace", {"function_name": a["function_name"], "project": self.project(repo),
                                       "direction": a.get("direction") or "both", "depth": int(a.get("depth") or 3)})
        if name == "snippet":   # kept for callers of the engine's own snippet tool
            return code.tool("snippet", {"qualified_name": a["qualified_name"], "project": self.project(repo)})
        if name == "overview":
            args = {"project": self.project(repo), "aspects": a.get("aspects") or ["overview"]}
            if a.get("path"):
                args["path"] = a["path"]
            return cap(code.tool("architecture", args), "pass path=<folder> or fewer aspects")
        if name == "outline":
            return cap(self._first(repo, lambda p: f"{p}/{a['path']}\n" + code.outline(p, a["path"])),
                       "read the line ranges you need")
        if name == "read":
            r = self._first(repo, lambda p: code.read(p, a["path"], a.get("start") or 1, a.get("end")))
            return cap(f"{r['project']}/{r['path']} lines {r['start']}-{r['end']} of {r['total_lines']}\n{r['text']}",
                       "read a smaller range")
        if name == "grep":
            found = [(p, code.grep(p, a["pattern"], bool(a.get("regex")), a.get("file_pattern"),
                                   mode=a.get("mode") or "matches", path=a.get("path"))) for p in self.targets(repo)]
            return cap("\n\n".join(f"## {p}\n{t}" for p, t in found if t) or "no matches",
                       "use mode=files, file_pattern= or path=")
        if name == "files":
            rows = [f"{p}/{f}" for p in self.targets(repo) for f in code.files(p, a.get("pattern") or "*", 301)]
            note = "\n… more than 300 files match: narrow the pattern" if len(rows) > 300 else ""
            return ("\n".join(rows[:300]) + note) if rows else "no files match"
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
    steps, errors, seen = [], list((seed or {}).get("errors", [])), {}
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
                key = (fn.get("name"), json.dumps(args, sort_keys=True))
                if key in seen:
                    result = f"(same call as step {seen[key]}: its result is above)"
                else:
                    seen[key] = len(steps) + 1
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
    llm.start_meter()
    ctx = Context(set_name, repo_names, branch)
    seed = _seed(question, "ask", ctx, model, log)
    log("asking the model", 0.4)
    res = run_agent("ask", ASK_SYSTEM, f"<question>\n{question}\n</question>", ctx, seed, model=model)
    answer = res["output"] or ("The language model did not answer (" + "; ".join(res["errors"][-2:]) +
                               "). These are the most relevant AI-BRAIN results:\n\n" + search.render(seed))
    return {"answer": answer, "llm": res["llm"], "model": res["model"], "steps": res["steps"],
            "sources": search.sources(seed), "evidence": search.evidence(seed), "analysis": seed["analysis"],
            "errors": res["errors"], "usage": llm.read_meter(), "ms": int((time.time() - t0) * 1000)}


def enhance(prompt: str, set_name=None, repo_names=None, branch=None, repo: str | None = None,
            base_commit: str | None = None, changed_files: list[str] | None = None, model: str | None = None,
            log=lambda *a, **k: None) -> dict:
    t0 = time.time()
    llm.start_meter()
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
            "drift": drift_report, "errors": res["errors"], "usage": llm.read_meter(),
            "ms": int((time.time() - t0) * 1000)}


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


GUIDE_SYSTEM = f"""You are the AI-BRAIN project guide: a senior engineer who helps a newcomer understand a codebase
quickly, from its code graph, its architecture overview and the organisation's documents. Write the guide a new
team member would want on day one: what the project is for, how it is built, how its main flows work, and where to
start reading.

{GROUNDING}

{TOOL_GUIDE}

<output_format>
Markdown, with exactly these sections (omit a section only if the material has nothing for it):
## What it is
Purpose, users and main capabilities in 3-6 sentences, in business words.
## How it is built
Languages, main modules or services and what each is responsible for; for a set, the role of each repository and how
they talk to each other (calls, HTTP routes, shared libraries). A short component list, each with its location.
## Main flows
The 2-4 most important flows, each as numbered steps from the entry point (route, handler, job) to the result, every
step cited `repo/path:line`.
## Where to start reading
5-10 files or symbols in a good reading order, one line each saying why.
## Key concepts
A table "Term | Meaning | Where in the code" for the domain terms.
## Business rules
The rules from documents that the code enforces (or should), each cited; note conflicts between code and documents.
## Good to know
Conventions, configuration, tests and anything surprising, only when the material shows it.
</output_format>"""


def guide(topic: str = "", set_name=None, repo_names=None, model: str | None = None, log=lambda *a, **k: None) -> dict:
    """A project guide for newcomers: architecture overview of every repository in scope + a grounded agent run."""
    t0 = time.time()
    llm.start_meter()
    ctx = Context(set_name, repo_names)
    log("reading the architecture of each repository", 0.05)
    arch, errors = [], []
    for p in ctx.projects[:6]:
        try:
            arch.append(f"### {p}\n" + cap(ctx.run_tool("overview", {"repo": p, "aspects": ["overview", "routes", "hotspots"]}),
                                            "the overview tool gives more")[:6000])
        except Exception as exc:
            errors.append(f"overview {p}: {exc}")
    question = topic.strip() or "the purpose, main entry points, core business logic and main flows of the system"
    seed = _seed(question, "guide", ctx, model, log)
    seed["errors"] = errors + seed["errors"]
    log("writing the guide", 0.4)
    res = run_agent("guide", GUIDE_SYSTEM, f"<request>Write the project guide{': focus on ' + topic if topic.strip() else ''}."
                                           "</request>", ctx, seed,
                    "<architecture>\n" + "\n\n".join(arch) + "\n</architecture>" if arch else "", model=model)
    text = res["output"] or ("The language model did not answer (" + "; ".join(res["errors"][-2:]) + "). "
                             "Architecture and the most relevant results:\n\n" + "\n\n".join(arch) + "\n\n" + search.render(seed))
    return {"guide": text, "llm": res["llm"], "model": res["model"], "steps": res["steps"],
            "sources": search.sources(seed), "evidence": search.evidence(seed), "analysis": seed["analysis"],
            "architecture": arch, "errors": res["errors"], "usage": llm.read_meter(), "ms": int((time.time() - t0) * 1000)}
