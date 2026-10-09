# 05 - Search, ask and enhance

Search, Ask, Enhance prompt and the Requirements writer all run on the same search. This document explains it
from the first step to the agents' output. The Requirements writer is described in
[17-REQUIREMENTS-WRITER.md](17-REQUIREMENTS-WRITER.md).

## 1. Common inputs

| Input | UI | API | Meaning |
|---|---|---|---|
| scope | *Scope* combobox | `target` = `repo:<name>` or `set:<name>`; also `set`, `repos` | one repository, or a set (default `set:all`); for a set every repository is examined |
| branch | *Branch* field | `branch` | if a branch overlay exists for that branch, it replaces the repository's `main` index ([10](10-BRANCH-DRIFT.md)) |
| model | *Model* combobox (Ask, Enhance, Requirements) | `model` | a chat model from `GET /api/models`; empty = the configured default for that role |
| search kind | *All / Code / Semantic code / Documents* (Search) | `scope` = `all`, `code`, `semantic`, `docs` | which sources are searched; `semantic` = code by meaning only |

## 2. Step 0 - prompt analysis

`brain/query.py`, also available alone as `POST /api/analyze`. It runs before everything else, takes a few
milliseconds and makes no model call. The UI shows it live under every input box while you type, and every
response returns it as `analysis`.

1. **Tokens**: Unicode words, code identifiers, file paths, and phrases in quotes or backticks.
2. **Stop-words** are taken out: built-in English and Turkish lists (question words, fillers, "please",
   "add/fix/update", "nasıl/nerede/lütfen/güncelle" …) plus the company's own list `BRAIN_STOPWORDS_EXTRA`.
   Words shorter than three characters are dropped as well.
3. **Key terms**: every remaining word gets a score; the best `BRAIN_QUERY_MAX_TERMS` (default 12) are kept,
   most important first.

   | Kind | Example | Score |
   |---|---|---|
   | phrase in quotes or backticks | `"partial refunds"`, `` `apply_vat` `` | 1 + 4 + length bonus |
   | identifier | `chargeCustomer`, `tax_rate`, `Invoice.create`, `HTTP_503` | 1 + 3 + length bonus |
   | file path | `src/billing/tax.py` | 1 + 3 + length bonus |
   | acronym | `KDV`, `VAT`, `API` | 1 + 2 + length bonus |
   | ordinary word | `fatura`, `refund` | 1 + length bonus |
   | generic programming word, Turkish verb form | `fonksiyonunu`, `code`, `uygulanıyor` | the above × 0.5 |
   | each repetition in the prompt | | + 0.5 |

   The length bonus is `min(length, 12) / 12`, so longer words rank slightly higher.
4. **Variants** for exact matching: one Turkish case, plural or possessive suffix removed (`Müşteriden` →
   `Müşteri`, `faturaları` → `fatura`), English plurals (`refunds` → `refund`, `policies` → `policy`) and
   identifier parts (`chargeCustomer` → `charge`, `Customer`).
5. **Concepts**: runs of up to three adjacent important words (`partial refunds`, `Müşteriden ödeme alınırken`),
   the best four.
6. **Language**: `tr`, `en`, `mixed` or `unknown`, from the stop-words and Turkish letters found.

How the analysis is used: the code engine's keyword (BM25) query is key terms + variants; its vector query is the
first eight key terms; LightRAG gets the concepts as high-level keywords and key terms + variants as low-level
keywords; the agents receive the analysis ("key terms, most important first; ignored stop-words") before the
retrieved material, and every search they make with their tools is analysed the same way.

## 3. The search pipeline

`brain/search.py` `search()`. Every stage after recall can be switched off in **Settings → Relevance**.

| # | Stage | What it does | Setting |
|---|---|---|---|
| 1 | **Query expansion** (agents only) | Ask, enhance and the requirements writer first make one short model call that returns up to 10 extra search terms: likely English code identifiers, translations (Turkish ↔ English) and synonyms. They are added after the user's own key terms and shown as "expanded". On error or timeout the search continues without them. | `BRAIN_QUERY_EXPANSION`, `BRAIN_QUERY_EXPANSION_TIMEOUT` |
| 2 | **Recall, in parallel** | (a) Code engine, per repository: BM25 over names, qualified names, paths and bodies plus a vector search with its bundled code model, fused by reciprocal rank (`1/(60+rank)`). (b) The multilingual code vector index (`brain/codevec.py`), when `BRAIN_CODE_VECTORS=both`. (c) LightRAG `/query/data` in `LIGHTRAG_QUERY_MODE` (default `mix`: entities, relations and chunk vectors) with the keywords supplied, so LightRAG makes **no chat call**. The candidate pool is `BRAIN_RERANK_CANDIDATES` (default 30). | `BRAIN_CODE_VECTORS`, `LIGHTRAG_TOP_K` |
| 3 | **Document → code bridge** | Entity names from the document results ("Payment Gateway", "Retry Policy") become extra code-search terms (`Payment`, `Gateway`, `PaymentGateway`). The extra hits are merged at half weight and tagged "document terms". | `BRAIN_DOC_BRIDGE` |
| 4 | **Code-graph expansion** | Callers, callees, parents and implementations of the best `BRAIN_GRAPH_EXPAND_TOP` (default 5) hits join the candidates at half weight, tagged for example "code graph: called by charge". This finds code wired to the matches even when it shares no words with the question. | `BRAIN_GRAPH_EXPAND`, `BRAIN_GRAPH_EXPAND_TOP` |
| 5 | **Re-ranking by meaning** | The prompt, every code candidate (kind, name, path and source) and every document passage are embedded with the corporate multilingual embedding model. Final order = `BRAIN_RERANK_WEIGHT` (default 0.6) × similarity + the rest × lexical rank. Embeddings are cached in memory (20,000 texts). | `BRAIN_RERANK`, `BRAIN_RERANK_WEIGHT` |
| 6 | **Final result** | Repository balance (every repository with hits keeps one or two places), the best `BRAIN_SEARCH_TOP_K` (default 8) code hits with up to 40 source lines each, annotations from the graph (signature, up to 6 callers and callees, up to 4 parents), relations between the hits, and the best `BRAIN_SEARCH_DOC_CHUNKS` (default 6) passages. | `BRAIN_SEARCH_TOP_K`, `BRAIN_SEARCH_DOC_CHUNKS` |

Ranking details inside the code engine: test files count half (×0.5), symbols of one or two lines count ×0.6, and
built-in or external symbols without a file are skipped. Each part of the search is bounded by
`BRAIN_SEARCH_TIMEOUT` (default 60 s); a part that fails is reported in `errors` and the rest is still returned.
The *Semantic code* scope uses only the two vector indexes (no BM25, bridge or expansion).

**Why these stages**: a Turkish question shares no words with English code, and documents name things
differently from code. Expansion and the bridge add the missing words, the graph adds the code connected to the
matches, and re-ranking orders everything by meaning, so the most related result comes first.

## 4. Three sources in every result

Every result combines:
1. **Code graph** (codebase-memory-mcp): keyword matches, graph expansion, relations, signatures, callers,
   callees, parents;
2. **Code vectors**: the code engine's local code embeddings and the multilingual code vector index;
3. **Document graph** (LightRAG): passages, entities and facts (relations).

Each code hit carries `matched`, the list of what found it: `keywords`, `code vectors`, `multilingual code
vectors`, `document terms`, `code graph: …`. The response carries `sources`, the number of hits per source, and
`pipeline`, the stages that ran. The Markdown rendering (`render()`) gives every code hit its location
`repo/path:line-line`, kind, name, qualified name, signature, callers, callees, parents, "found by" and source, then
the code relations, document passages, domain entities and domain facts, and ends with next-step hints for agents
(`snippet`, `trace`, `read`, `grep`, `files`). Sections are dropped whole when the size budget is reached, the most
important first; the budget is `BRAIN_CONTEXT_MAX_CHARS` (default 16,000) for the agents' seed, 9,000 per agent tool
call, 30,000 for MCP `search` and 60,000 for REST `markdown`.

## 5. Search (no chat call)

`POST /api/search`, MCP `search`, `brain search`, UI **Search**.

Response: `query`, `scope`, `analysis`, `pipeline`, `sources`, `code[]` (each with `project`, `qn`, `name`,
`label`, `path`, `line1`, `line2`, `code`, `matched`, `signature`, `callers`, `callees`, `parents`, `similarity`,
`rerank`), `relations[]`, `docs` (`chunks`, `entities`, `relations`), `projects`, `errors`, `ms` and `markdown`.

"No chat call" means no chat-completion call. Search makes embedding calls: one for the query in LightRAG, one
for the multilingual code vectors and one batched call for re-ranking (cached).

## 6. Enhance prompt

`brain/agents.py` `enhance()`; `POST /api/enhance`, MCP `enhance_prompt`, `brain enhance`, UI **Enhance prompt**,
Claude Code command `integrations/claude-code/brain-enhance.md`.

Input: the developer's short request in any language, the scope, the model, and optionally branch facts (`repo`,
`branch`, `base_commit`, `changed_files`).

1. Prompt analysis and query expansion.
2. Seed search (section 3) for the request.
3. If a branch is given (and one repository is in scope or `repo` is set): a branch-drift check
   ([10](10-BRANCH-DRIFT.md)); its findings go into *Notes for the agent*.
4. The model (`BRAIN_ENHANCE_MODEL`, else `BRAIN_LLM_MODEL`) runs with the enhancer system prompt and the
   read-only tools for at most `BRAIN_ENHANCE_MAX_STEPS` (default 4) rounds within `BRAIN_ENHANCE_TIMEOUT`
   (default 120 s), `BRAIN_ENHANCE_MAX_TOKENS` (1800) and `BRAIN_ENHANCE_TEMPERATURE` (0.2).
5. Output in the developer's language with these sections: **Task** (with the intent type, for example [bug fix]),
   **Context** (`repo/path:line` - symbol - why it matters), **Business rules and constraints**, **Impact**,
   **Implementation plan**, **Acceptance criteria**, **Out of scope**, **Open questions and assumptions**, **Notes
   for the agent**.

Fallback: if the model cannot be reached, a deterministic prompt is built from the search (task, key terms,
relevant code, knowledge-base context, branch notes), so a coding agent still gets a grounded prompt.

Response: `enhanced`, `model`, `llm` (whether the model wrote it), `analysis`, `sources`, `evidence`, `steps`,
`drift`, `errors`, `ms`.

## 7. Ask

`brain/agents.py` `ask()`; `POST /api/ask`, MCP `ask`, `brain ask`, UI **Ask**.

The same loop with the ask system prompt and its own limits: `BRAIN_ASK_MODEL`, `BRAIN_ASK_MAX_STEPS` (6),
`BRAIN_ASK_TIMEOUT` (180 s), `BRAIN_ASK_MAX_TOKENS` (1500), `BRAIN_ASK_TEMPERATURE` (0.1). The answer has
**Answer** (one to four sentences), **Details** (each point cited, flows in call order), **Where to look** and,
when needed, **Gaps and conflicts**. Code is cited as `repo/path:line-line`, documents as `[document name]`.

Fallback: without a model the answer explains why and contains the most relevant search results.

Response: `answer`, `model`, `llm`, `analysis`, `sources`, `evidence`, `steps`, `errors`, `ms`.

## 8. The agent loop and its tools

One loop (`run_agent`) serves ask, enhance and the requirements writer:
1. The message is built material first and request last: `<scope>` (which repositories, and for a set the
   instruction to look at every one), `<prompt_analysis>`, `<knowledge_base>` (the rendered seed search), extra
   blocks (branch freshness), then the request in its own tag.
2. The model may call tools, at most 4 per round; each tool result is cut at 8,000 characters.
3. When the step limit is reached or less than 15 seconds remain, the model is asked for the final answer
   without tools. Each model call is also bounded by `BRAIN_LLM_TIMEOUT`.

Read-only tools (OpenAI function calling):

| Tool | Does |
|---|---|
| `search(query, scope, repo)` | the full search of section 3 (`scope`: all, code, semantic, docs) |
| `semantic(query, repo)` | code by meaning only |
| `docs(query)` | documents only |
| `symbol(name)` | definition, source, callers and callees of a class, function or method |
| `trace(function_name, direction, repo)` | call chain, inbound, outbound or both (depth 3) |
| `snippet(qualified_name, repo)` | full source of a symbol |
| `read(repo, path, start, end)` | numbered lines of any indexed file (at most 400) |
| `grep(pattern, regex, file_pattern, repo)` | exact text or regex over the indexed code, ranked by the graph, per repository |
| `files(pattern, repo)` | indexed file paths matching a glob such as `**/*.sql` |
| `overview(repo)` | architecture of one repository: languages, packages, entry points, routes, hotspots |

Without `repo`, `grep` and `files` run over every repository in scope.

### Gateways without tool calling
`BRAIN_AGENT_TOOL_CALLING`:
- `auto` (default): tools are sent; if the gateway answers 400, 404, 422 or 501 to a request with tools, the
  server remembers it and from then on answers every request with one grounded call on the seed search;
- `native`: tools are always sent and errors are reported;
- `off`: never send tools (one grounded call per request; fastest, least thorough).

## 9. Cost and latency per request

| Function | Chat calls | Embedding calls | Typical time |
|---|---|---|---|
| search | 0 | 1 (documents) + 1 (code vectors) + 1 batched (re-ranking, cached) | 0.5-3 s |
| ask | 1 expansion + 1 to 1 + `BRAIN_ASK_MAX_STEPS` | as search, plus one search per `search`/`semantic`/`docs` tool call | 5-60 s, at most `BRAIN_ASK_TIMEOUT` |
| enhance | 1 expansion + 1 to 1 + `BRAIN_ENHANCE_MAX_STEPS` | as ask | 5-45 s, at most `BRAIN_ENHANCE_TIMEOUT` |
| requirements | about 2 + capabilities + sections, each with up to 3 tool rounds | one search per capability | minutes, at most `BRAIN_SRS_TIMEOUT` |

## 10. Synchronous and background use
Agents and scripts call the endpoints synchronously and wait for the result. The UI sends `"async": true`,
receives a job id, and polls `/api/jobs/{id}` to show each step ("analysing the request", "model-expanded search
terms", "searching code and documents", "found N code hits in M repositories", "asking the model" …). The
requirements writer runs as a background job by default.
