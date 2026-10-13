# 19 - Review and rating

An assessment of AI-BRAIN from three angles: what an AI agent pays and gets when it uses AI-BRAIN over MCP, how
well it replaces search, grep, glob and read, and how well people can explore a project and research while coding.
It ends with the known limits, a rating and the recommended next steps.

## 1. What has been verified
- Every module, the REST and MCP surface, the installers and this documentation were reviewed against each other;
  the static test enforces that every setting, route and MCP tool is documented and that every link works.
- The end-to-end test runs on Windows 11 with Python 3.13.16 from an empty data folder against the mock gateway, and
  all 76 checks pass ([15-TESTING.md](15-TESTING.md)).
- The answer sizes below were measured on the test repository through MCP (≈ 4 characters per token).

## 2. AI agents over MCP: tokens

| What the agent pays for | Size |
|---|---|
| tool list (16 tools, sent with every turn) | ≈ 1,340 tokens |
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

## 5. Updates
A merge (webhook) or a pull of the tracked branch (watched local checkouts, `brain hook` in any other checkout)
updates the repository's graph; every update pulls at once, and requests during an update make it run once more.

## 6. Known limits and risks
- Tested against a **mock** corporate API. Retrieval and tool behaviour are verified; answer quality, guide quality
  and real multilingual ranking depend on the organisation's models and must be checked with the real gateway.
- **Linux**: the installer is syntax-checked but has not been run on a Linux machine. GitLab and TFS were simulated
  with their webhook payloads.
- **One shared login**: no per-user roles or audit trail; put an SSO reverse proxy in front if needed.
- **Token counts** come from the gateway's `usage` field; a gateway that does not send it shows only the call count.
- **Code vectors cost**: the first sync embeds every symbol once; on a slow gateway set `BRAIN_CODE_VECTORS=local`.
- **Documents**: borderless tables and complex multi-column PDF layouts convert less well.
- **One document graph** for all sets; separate document spaces need a second instance.

## 7. Rating

| Area | Score (of 10) | Why |
|---|---|---|
| Token economy for AI agents | 9 | compact tool list, exact tools of a few hundred tokens, detail levels, capped and cleaned answers, usage reported |
| Search, grep, glob, read for agents | 9 | graph-ranked grep with modes, outline before read, compact symbol, named symbols first, three-source search |
| Exploring and learning for people | 8.5 | structure view, cited project guide, evidence everywhere, ask from the graph; one shared account |
| Architecture and simplicity | 9 | a small core around two ready engines; one tool implementation behind MCP, REST and the agents |
| Requirements coverage | 9 | all 33 requirements traced to code and tests ([00](00-REQUIREMENTS.md)) |
| Code quality | 8 | consistent, documented modules; a few long functions (search pipeline, requirements writer) |
| Testing | 7.5 | static and 76 end-to-end checks; no real-API, Linux or load tests yet |
| Documentation | 9 | step-by-step guides, 27 decision records, a generated configuration reference |
| **Overall** | **8.7** | ready for a pilot; the next step is the real gateway, real repositories and real questions |

## 8. Recommended next steps
1. Pilot with the real corporate API and two or three real repositories; tune `BRAIN_SEARCH_DETAIL`,
   `BRAIN_RERANK_WEIGHT` and `BRAIN_SEARCH_TOP_K`.
2. Keep 20 real questions in Turkish and English, with the expected files and documents, as a regression set, and
   compare the tokens an agent spends with and without AI-BRAIN on the same tasks.
3. Run setup once on a Linux server and add the result to [15-TESTING.md](15-TESTING.md).
4. Connect one real GitLab project and one TFS repository through their own webhooks.
