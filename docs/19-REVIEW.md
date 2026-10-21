# 19 - Review and rating

An assessment of AI-BRAIN from three angles: what an AI agent pays and gets when it uses AI-BRAIN over MCP, how
well it replaces search, grep, glob and read, and how well people can explore a project and research while coding.
It ends with the known limits, a rating and the recommended next steps.

## 1. What has been verified
- Every module, the REST and MCP surface, the installers and this documentation were reviewed against each other;
  the static test enforces that every setting, route and MCP tool is documented and that every link works.
- The end-to-end test runs on Windows 11 with Python 3.13.16 from an empty data folder against the mock gateway, and
  all 101 checks pass ([15-TESTING.md](15-TESTING.md)).
- The answer sizes below were measured on the test repository through MCP (≈ 4 characters per token).

## 2. AI agents over MCP: tokens

| What the agent pays for | Size |
|---|---|
| tool list (18 tools, sent with every turn) | ≈ 1,500 tokens |
| `search`, 8 hits: `brief` / `normal` / `full` | ≈ 470 / 1,060 / 1,660 tokens |
| `symbol` (a short method with source, signature, calls) | ≈ 120 tokens |
| `outline` of a file | ≈ 100 tokens |
| `grep mode=files` / `grep` with matches | ≈ 25 / 95 tokens |

How it stays small: terse tool schemas with the scope arguments explained once; exact tools for exact questions;
search detail levels; answers capped by `BRAIN_TOOL_MAX_TOKENS`; the code engine's paging and timing fields removed;
repositories without matches left out; named symbols ranked first so the agent does not page; server-side agents
(`ask`, `enhance_prompt`, `write_requirements`) return only their result. Inside those agents, repeated identical
tool calls are answered with a note, and every run reports its model calls and tokens. See
[ADR-024](decisions/ADR-024-token-economy.md).

## 3. AI agents: search, grep, glob and read

| Local tool | AI-BRAIN | Assessment |
|---|---|---|
| grep / rg | `grep` (files / matches / full, folder and file filters), `search` | better: graph-ranked, across all repositories of a set; `search` adds meaning, Turkish questions and documents |
| glob | `files` | equal for listing; works without a checkout and across a set; says when results are cut |
| read | `outline` + `read`, `symbol` | better for understanding: a file's structure first, then only the needed lines; a function with its callers and callees in one answer; `read` finds the repository by itself |
| "where is X?" | `search` with the identifier | the named symbol is ranked first, with its location and signature |

What local tools still do better: they see uncommitted changes and branches that were never indexed. AI-BRAIN
answers from the indexed `main` (or a branch overlay) and says so; `check_branch` tells the agent which files to read
locally.

## 4. People: exploring a project and research while coding
- **Learn a project**: the structure of every repository of a scope without a model call, and a written guide for
  newcomers with cited main flows and a reading order ([ADR-025](decisions/ADR-025-learning-a-project.md)).
- **Search** shows three sources side by side, with the reason each hit was found and its callers and callees; every
  agent answer shows its evidence, its tool calls and its token use.
- **Code graph** and **Document graph** pages for browsing; *Ask about this* turns any symbol into a question about
  what it does, who calls it and which business rules apply.
- **Enhance prompt** and the **Requirements writer** turn research into a task for a coding agent or a specification
  for business readers.

## 5. Documents
The document engine indexes without a model: a document is converted, split along its headings and pages, and is
searchable by keywords, concepts and rules as soon as the upload returns. Vectors follow in batches (`BRAIN_EMBED_BATCH`
passages per call, `BRAIN_EMBED_PARALLEL` calls at once), each picture costs one vision call, and each concept name is
embedded once. A 100-page document with 300 passages and 400 concepts therefore costs about 12 embedding calls instead
of hundreds of chat calls, so a slow gateway delays only the meaning-based part, never the document itself
([ADR-002](decisions/ADR-002-document-graph.md)).

What it understands without a model: sections and pages; Turkish word forms of a concept as one concept; requirement
sentences typed obligation, prohibition, recommendation or limit, with their amounts and durations; table rows with
numbers; synonyms and Turkish/English translations as aliases (by meaning); and the code that implements a concept
(by meaning). What it does not understand: rules phrased without a modal word or a number, relations other than
"named together", and every Turkish word form (one suffix is removed, so "onayı" and "onayları" stay apart). Alias and
concept → code quality depends on the embedding model's similarity scale and has only been tested with a mock.

## 6. Updates
A merge (webhook) or a pull of the tracked branch (watched local checkouts, `brain hook` in any other checkout)
updates the repository's graph; every update pulls at once, and requests during an update make it run once more.
Every page that shows state (overview, documents, repositories, requirements, logs) is refreshed by the server's
event stream as soon as something changes, without reloading.

## 7. Known limits and risks
- Tested against a **mock** corporate API. Retrieval and tool behaviour are verified; answer quality, guide quality
  and real multilingual ranking depend on the organisation's models and must be checked with the real gateway.
- **Linux**: the installer is syntax-checked but has not been run on a Linux machine. GitLab and TFS were simulated
  with their webhook payloads.
- **One shared login**: no per-user roles or audit trail; put an SSO reverse proxy in front if needed.
- **Token counts** come from the gateway's `usage` field; a gateway that does not send it shows only the call count.
- **Code vectors cost**: the first sync embeds every symbol once; on a slow gateway set `BRAIN_CODE_VECTORS=local`.
- **Documents**: borderless tables and complex multi-column PDF layouts convert less well; scanned PDFs without a
  text layer are understood through the vision model's page descriptions, or, without it, through local OCR, which
  loses Turkish accents (search folds them anyway) and misses some lines on poor scans.
- **One document graph** for all sets; separate document spaces need a second instance.

## 8. Rating
Two numbers, because they answer different questions. **Fit for the situation** (air-gapped, slow corporate API,
code and documents together): weighted for those needs and compared with the alternatives in
[18-ENGINE-COMPARISON.md](18-ENGINE-COMPARISON.md). **Absolute**: as a product, including how proven it is.

| Area | Score (of 10) | Why |
|---|---|---|
| Air-gap fit | 10 | 42 wheels, no download, no cloud, one URL and key |
| Slow-API tolerance | 9 | no chat call while indexing; at most one embedding call per search, never waited for longer than 3 s; agent answers still wait on the model |
| Coverage: code, meaning, documents, many repositories | 9 | three sources fused; documents with rules, word forms, aliases and links to code |
| For autonomous agents | 8 | exact tools, impact with tests, decision memory; about 1,500 tokens of tool list per turn |
| For developers | 7.5 | search, ask, enhance, requirements, learn, live pages; one shared login, no editor plug-in |
| Document understanding | 6 | patterns plus embeddings: rules, limits, aliases; shallower than per-chunk LLM extraction by design |
| Simplicity | 7.5 | one process, SQLite, about 7,000 lines of Python and a UI: small, but all of it maintained by one team |
| Maturity | 3 | tested with a mock model, a small test repository and Windows only; no real users yet |
| **Fit for the situation** | **8.2** | first among the systems compared; no other covers code, meaning and documents offline without a model call per chunk |
| **Absolute** | **7** | a well-built, well-tested prototype; a pilot with the real API, real repositories and real questions is what is missing |

## 9. Recommended next steps
1. Pilot with the real corporate API and two or three real repositories; tune `BRAIN_SEARCH_DETAIL`,
   `BRAIN_RERANK_WEIGHT` and `BRAIN_SEARCH_TOP_K`.
2. Upload a representative set of real documents and check the concepts on the Document graph page; add
   organisation-specific stop-words with `BRAIN_STOPWORDS_EXTRA` if generic words show up as concepts.
3. Keep 20 real questions in Turkish and English, with the expected files and documents, as a regression set, and
   compare the tokens an agent spends with and without AI-BRAIN on the same tasks.
4. Run setup once on a Linux server and add the result to [15-TESTING.md](15-TESTING.md).
5. Connect one real GitLab project and one TFS repository through their own webhooks.
