# 05 - Search, ask and enhance

Search, Ask, Enhance prompt, the Project guide and the Requirements writer all run on the same search. This document
explains it from the first step to the agents' output. The Requirements writer is described in
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
first eight key terms; the document engine matches the key terms + variants in its keyword index and the concepts
against its concept names; the agents receive the analysis ("key terms, most important first; ignored stop-words") before the
retrieved material, and every search they make with their tools is analysed the same way.

## 3. The search pipeline

`brain/search.py` `search()`. Every stage after recall can be switched off in **Settings → Relevance**.

| # | Stage | What it does | Setting |
|---|---|---|---|
| 1 | **Query expansion** (agents only) | Ask, enhance and the requirements writer first make one short model call that returns up to 10 extra search terms: likely English code identifiers, translations (Turkish ↔ English) and synonyms. They are added after the user's own key terms and shown as "expanded". On error or timeout the search continues without them. | `BRAIN_QUERY_EXPANSION`, `BRAIN_QUERY_EXPANSION_TIMEOUT` |
| 2 | **Recall, in parallel** | (a) Code engine, per repository: BM25 over names, qualified names, paths and bodies plus a vector search with its bundled code model, fused by reciprocal rank (`1/(60+rank)`). (b) The multilingual code vector index (`brain/codevec.py`), when `BRAIN_CODE_VECTORS=both`. (c) The document engine: BM25 over the passages, the passage vectors and the concept graph, fused by reciprocal rank (no chat call; section 4). The code candidate pool is `BRAIN_RERANK_CANDIDATES` (default 30). | `BRAIN_CODE_VECTORS`, `BRAIN_SEARCH_DOC_CHUNKS` |
| 2b | **Exact names** | Identifiers and file paths written in the question (`apply_vat`, `InvoiceService.create_invoice`, `src/billing/tax.py`) are looked up directly: symbols with that name or qualified-name tail, and the main symbols of that file. They are tagged "exact name" or "file path" and always ranked first, because the user is pointing at them. | always on |
| 3 | **Document → code bridge** | Concept names from the document results ("Payment Gateway", "Retry Policy") become extra code-search terms (`Payment`, `Gateway`, `PaymentGateway`). The extra hits are merged at half weight and tagged "document terms". | `BRAIN_DOC_BRIDGE` |
| 4 | **Code-graph expansion** | Callers, callees, parents and implementations of the best `BRAIN_GRAPH_EXPAND_TOP` (default 5) hits join the candidates at half weight, tagged for example "code graph: called by charge". This finds code wired to the matches even when it shares no words with the question. | `BRAIN_GRAPH_EXPAND`, `BRAIN_GRAPH_EXPAND_TOP` |
| 5 | **Re-ranking by meaning** | Each code candidate is compared with the question through the multilingual code vector stored for it at indexing (`brain/codevec.py`), so re-ranking costs no API call; a candidate without a stored vector gets the average similarity (document passages are already ranked by meaning in the document engine). Final order = `BRAIN_RERANK_WEIGHT` (default 0.6) × similarity + the rest × lexical rank. Needs `BRAIN_CODE_VECTORS=both`. | `BRAIN_RERANK`, `BRAIN_RERANK_WEIGHT` |
| 6 | **Final result** | Exact names first, repository balance (every repository with hits keeps one or two places), the best `BRAIN_SEARCH_TOP_K` (default 8) code hits with up to 40 source lines each, annotations from the graph (signature, up to 6 callers and callees, up to 4 parents), relations between the hits, and the best `BRAIN_SEARCH_DOC_CHUNKS` (default 6) passages. | `BRAIN_SEARCH_TOP_K`, `BRAIN_SEARCH_DOC_CHUNKS` |

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
3. **Document graph** (the document engine): passages, concepts and facts.

### How the document engine answers
1. **Keywords**: the key terms, variants and multi-word concepts, folded the way the index is (lower case, ş = s,
   ı = i), and their stems are searched in the SQLite FTS5 index (BM25) over every passage, its section path and its
   document name. The index has two columns: the exact folded text, and the same text stemmed, so "onaylar" finds
   "onayı" and "onayının" (Turkish: own suffix rules, measured on 112 forms of official-document nouns with no form
   split apart; English: Snowball / Porter 2).
2. **Vectors**: the query embedding (shared with the code search) is compared with every passage vector.
3. **Concepts**: concepts whose name equals a key term or concept of the question (in any word form: iadeler,
   iadesi and iade are one concept), the concepts nearest to the question by meaning (`BRAIN_CONCEPT_SIM`), and
   their aliases (concepts that mean the same, such as "iade onayı" and "Refund Approval") are the seeds of a
   Personalized PageRank over the passage-concept graph, together with the best keyword and vector passages. Mass
   flows passage → concept → passage (12 steps, damping 0.5), and a concept named everywhere passes on little. The
   passages it ranks highest form the third list, so a passage linked to the question through a shared concept is
   found even when it shares no word with it (multi-hop).
4. The three lists are fused by reciprocal rank. Each passage carries its document, section path and page
   (`source`, for example `contract.pdf › 4 Payments › 4.2 Refunds, p. 12`), its kind (text, table, picture, figure),
   what found it (`matched`) and its similarity.
5. **Concepts** (`entities`): the concepts named in these passages, the ones the question names first, each with its
   definition when a glossary or "Term: definition" line gives one.
6. **Facts** (`relations`): sentences of these passages that name two of those concepts.
7. **Documents** (`documents`): the card of each document shown: its most central sentences (LexRank over the
   stemmed words), version, effective date, and the newer version when one exists. Near-identical documents (MinHash
   of 5-word shingles, at least half equal) are versions of each other; the one with the higher version number or
   later date is current. Passages of an older version count half in the ranking and carry `note` ("older version;
   newer: …").
8. **Rules** (`rules`): the requirement sentences of these passages, typed `obligation` ("-malıdır", "zorunludur",
   "gerekir", "must", "shall", "need"), `prohibition` ("yasaktır", "edilemez", "-mamalıdır", "must not", "cannot"),
   `recommendation` ("should", "önerilir") or `limit`, each with the limits it states ("5.000 TL üzeri", "en geç 3
   iş günü içinde", "over 1,000 EUR"), and table rows with numbers written with their column names (`value`). The
   rules that contain the question's words come first. Found when the document is indexed, without a model.

Concept → code: after the documents answer, each returned concept's stored vector is compared with the stored
multilingual code vectors; code at `BRAIN_CONCEPT_CODE_SIM` or above joins the code hits (tagged "implements
concept: …") and the concept lists it as `implemented_by`. No API call is made. The similarity scale depends on
the embedding model, so check the links on real questions and tune the setting.

Each code hit carries `matched`, the list of what found it: `exact name`, `file path`, `keywords`, `code vectors`,
`multilingual code vectors`, `document terms`, `code graph: …`. The response carries `sources`, the number of hits
per source, and `pipeline`, the stages that ran.

The Markdown rendering (`render()`, used for agents, MCP and the CLI) gives every code hit its location
`repo/path:line-line`, kind, qualified name, signature, callers, callees, parents and "found by", then document
passages, business rules, concepts (with aliases and the code that implements them) and facts, and ends with next-step hints (`symbol`, `outline`, `read`, `trace`). The
**detail level** (`BRAIN_SEARCH_DETAIL`, or `detail` per request) decides how much is written:

| Detail | Source code | Relations | Passage length | Typical size (8 hits) |
|---|---|---|---|---|
| `brief` | none | none | 300 characters | ≈ 500 tokens |
| `normal` (default) | the 3 best hits, 15 lines each | 10 | 600 characters | ≈ 1,000 tokens |
| `full` | every hit, 30 lines each | 25 | 1,000 characters | ≈ 1,700 tokens |

Sections are dropped whole when the size budget is reached, the most important first; the budget is
`BRAIN_CONTEXT_MAX_CHARS` (default 16,000) for the agents' seed, 9,000 per agent tool call, 30,000 for MCP `search`
and 60,000 for REST `markdown`. The UI always receives the full JSON.

## 5. Search (no chat call)

`POST /api/search`, MCP `search`, `brain search`, UI **Search**.

Response: `query`, `scope`, `analysis`, `pipeline`, `sources`, `code[]` (each with `project`, `qn`, `name`,
`label`, `path`, `line1`, `line2`, `code`, `matched`, `signature`, `callers`, `callees`, `parents`, `similarity`,
`rerank`), `relations[]`, `docs` (`chunks`, `entities`, `relations`), `projects`, `errors`, `ms` and `markdown`
(rendered at the requested `detail`).

"No chat call" means no chat-completion call. Search makes at most **one** call to the corporate API: the embedding
of the question, shared by the multilingual code vectors, the document passages and the re-ranking, and cached
(20,000 texts). It waits for it at most `BRAIN_EMBED_BUDGET` seconds (default 3). On a slow gateway the search then
answers from keywords, the code graph and the concepts, and says so in `pipeline` ("meaning skipped"); the embedding
still arrives in the background and is used by the next search with the same question.

## 6. Enhance prompt

`brain/agents.py` `enhance()`; `POST /api/enhance`, MCP `enhance_prompt`, `brain enhance`, UI **Enhance prompt**,
Claude Code command `integrations/claude-code/brain-enhance.md`.

Input: the developer's request in any language and of any kind, the scope, the model, and optionally branch facts
(`repo`, `branch`, `base_commit`, `changed_files`). There is no mode to choose: one enhancer handles every class of
request. It first classifies the request and then looks for what that class needs:

| Class | The agent looks for |
|---|---|
| bug fix | the failing path from its entry point to the faulty code, the likely root cause with evidence, how to reproduce it, the tests that should have caught it |
| new feature | not the feature (it does not exist), but where it plugs in: entry points to extend, modules and data it uses, the most similar existing feature to imitate |
| change, refactor, performance, security, migration | the symbols to change, their callers (impact), the behaviour that must stay the same, how to verify or measure the result |
| tests, configuration, investigation, documentation, question | what is to be found out, written or covered, and where the answer lives |

A request can have two classes (a new feature that also fixes a bug); the agent names both. For every class it also
collects the business rules from documents and the conventions from the code.

1. Prompt analysis and query expansion.
2. Seed search (section 3) for the request.
3. If a branch is given (and one repository is in scope or `repo` is set): a branch-drift check
   ([10](10-BRANCH-DRIFT.md)); its findings go into *Notes for the agent*.
4. The model (`BRAIN_ENHANCE_MODEL`, else `BRAIN_LLM_MODEL`) runs with the enhancer system prompt and the
   read-only tools for at most `BRAIN_ENHANCE_MAX_STEPS` (default 4) rounds within `BRAIN_ENHANCE_TIMEOUT`
   (default 120 s), `BRAIN_ENHANCE_MAX_TOKENS` (1800) and `BRAIN_ENHANCE_TEMPERATURE` (0.2).
5. Output in the developer's language with these sections (empty ones left out): **Task** (with the request class, for example [bug fix] or [new feature]), **What exists today**
   (`repo/path:line` - symbol - change / read / imitate / extend), **Analysis** (only what the class needs: for a bug
   the symptom, reproduction and likely root cause; for a new feature where it fits, files to create, data and
   interfaces; for a refactor the target shape and the behaviour to keep; for performance the hot path and how to
   measure it), **Business rules and constraints**, **Impact**, **Implementation plan**, **Acceptance criteria**
   (for a bug, a test that fails before the fix), **Out of scope**, **Open questions and assumptions**, **Notes for
   the agent**.

Fallback: if the model cannot be reached, a deterministic prompt is built from the search (task, key terms,
relevant code, knowledge-base context, branch notes), so a coding agent still gets a grounded prompt.

Response: `enhanced`, `model`, `llm` (whether the model wrote it), `analysis`, `sources`, `evidence`,
`steps`, `drift`, `errors`, `usage`, `ms`.

## 7. Ask

`brain/agents.py` `ask()`; `POST /api/ask`, MCP `ask`, `brain ask`, UI **Ask**.

The same loop with the ask system prompt and its own limits: `BRAIN_ASK_MODEL`, `BRAIN_ASK_MAX_STEPS` (6),
`BRAIN_ASK_TIMEOUT` (180 s), `BRAIN_ASK_MAX_TOKENS` (1500), `BRAIN_ASK_TEMPERATURE` (0.1). The answer has
**Answer** (one to four sentences), **Details** (each point cited, flows in call order), **Where to look** and,
when needed, **Gaps and conflicts**. Code is cited as `repo/path:line-line`, documents as `[document name]`.

Fallback: without a model the answer explains why and contains the most relevant search results.

Response: `answer`, `model`, `llm`, `analysis`, `sources`, `evidence`, `steps`, `errors`, `usage`, `ms`.

## 7b. Project guide

`brain/agents.py` `guide()`; `POST /api/guide`, `brain guide`, UI **Learn a project**.

An introduction for newcomers to one repository or a set, optionally focused on a topic:
1. the architecture overview of every repository in scope (at most 6): languages, packages, entry points, routes,
   hotspots;
2. a seed search for the topic, or for "purpose, main entry points, core business logic and main flows";
3. the agent loop with the guide prompt and limits `BRAIN_GUIDE_MODEL`, `BRAIN_GUIDE_MAX_STEPS` (5),
   `BRAIN_GUIDE_TIMEOUT` (300 s), `BRAIN_GUIDE_MAX_TOKENS` (3000), `BRAIN_GUIDE_TEMPERATURE` (0.2);
4. output sections: **What it is**, **How it is built**, **Main flows** (numbered steps from the entry point, each
   cited), **Where to start reading** (5-10 files or symbols in reading order), **Key concepts** (term, meaning,
   where in the code), **Business rules**, **Good to know**.

Without a model the response contains the architecture overviews and the search results. The UI can copy, download
or add the guide to the document graph, so later searches find it.

Response: `guide`, `model`, `llm`, `architecture`, `analysis`, `sources`, `evidence`, `steps`, `errors`, `usage`, `ms`.

## 8. The agent loop and its tools

One loop (`run_agent`) serves ask, enhance, the project guide and the requirements writer:
1. The message is built material first and request last: `<scope>` (which repositories, and for a set the
   instruction to look at every one), `<prompt_analysis>`, `<knowledge_base>` (the rendered seed search), extra
   blocks (branch freshness), then the request in its own tag.
2. The model may call tools, at most 4 per round; each tool result is cut at 8,000 characters. A call identical to
   an earlier one in the same run is answered with "(same call as step N: its result is above)" instead of the same
   text again.
3. When the step limit is reached or less than 15 seconds remain, the model is asked for the final answer
   without tools. Each model call is also bounded by `BRAIN_LLM_TIMEOUT`.

Read-only tools (OpenAI function calling):

| Tool | Does |
|---|---|
| `search(query, scope, detail, repo)` | the full search of section 3 (`scope`: all, code, semantic, docs) |
| `semantic(query, repo)` | code by meaning only |
| `docs(query)` | documents only |
| `symbol(name, source, repo)` | location, signature, source (`auto`: whole when 60 lines or less, else 40 lines), callers, callees, parents, other matches |
| `trace(function_name, direction, repo)` | call chain, inbound, outbound or both (depth 3) |
| `outline(path, repo)` | declarations of one file with line ranges |
| `read(path, start, end, repo)` | numbered lines of any indexed file (at most 400) |
| `grep(pattern, regex, mode, file_pattern, path, repo)` | exact text or regex, ranked by the graph; `mode=files` only locates |
| `files(pattern, repo)` | indexed file paths matching a glob such as `**/*.sql` |
| `overview(repo, path, aspects)` | a repository's structure: languages, packages, entry points, routes, hotspots, file tree |

Without `repo`, `grep` and `files` run over every repository in scope, and `read` and `outline` use the first
repository that has the file. `symbol`, `outline`, `read`, `grep`, `trace` and `overview` answers are cut at
`BRAIN_TOOL_MAX_TOKENS` (≈ 4 characters per token) with a note saying how to get the rest, and the code engine's paging
and timing fields are removed from them.

Every run counts its model calls and tokens (`usage`: `calls`, `prompt_tokens`, `completion_tokens`, as reported by
the gateway); the UI shows them under each answer.

### Gateways without tool calling
`BRAIN_AGENT_TOOL_CALLING`:
- `auto` (default): tools are sent; if the gateway answers 400, 404, 422 or 501 to a request with tools, the
  server remembers it and from then on answers every request with one grounded call on the seed search;
- `native`: tools are always sent and errors are reported;
- `off`: never send tools (one grounded call per request; fastest, least thorough).

## 9. Cost and latency per request

| Function | Chat calls | Embedding calls | Typical time |
|---|---|---|---|
| search | 0 | at most 1 (the question; cached; waits at most `BRAIN_EMBED_BUDGET`) | 0.2-3 s |
| ask | 1 expansion + 1 to 1 + `BRAIN_ASK_MAX_STEPS` | as search, plus one search per `search`/`semantic`/`docs` tool call | 5-60 s, at most `BRAIN_ASK_TIMEOUT` |
| enhance | 1 expansion + 1 to 1 + `BRAIN_ENHANCE_MAX_STEPS` | as ask | 5-45 s, at most `BRAIN_ENHANCE_TIMEOUT` |
| project guide | 1 expansion + 1 to 1 + `BRAIN_GUIDE_MAX_STEPS` | as ask | 10-120 s, at most `BRAIN_GUIDE_TIMEOUT` |
| requirements | about 2 + capabilities + sections, each with up to 3 tool rounds | one search per capability | minutes, at most `BRAIN_SRS_TIMEOUT` |

## 10. Synchronous and background use
Agents and scripts call the endpoints synchronously and wait for the result. The UI sends `"async": true`,
receives a job id, and polls `/api/jobs/{id}` to show each step ("analysing the request", "model-expanded search
terms", "searching code and documents", "found N code hits in M repositories", "asking the model" …). The
requirements writer and the project guide run as background jobs by default.
