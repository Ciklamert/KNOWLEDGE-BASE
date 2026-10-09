# 19 - Review and rating

An assessment of the whole system: what has been verified, its strengths, its known limits, a rating and the
recommended next steps.

## 1. What has been verified
- Every module (`brain/*.py`, the providers, the UI), the REST and MCP surface, the installers and this
  documentation were reviewed against each other: every setting, route and MCP tool is documented, and the static
  test enforces it.
- The end-to-end test runs on Windows 11 with Python 3.13.16 from an empty data folder against the mock gateway, and
  all its checks pass ([15-TESTING.md](15-TESTING.md)).
- The offline installation was run with `pip --no-index` from `wheels/`.

## 2. Strengths
- **Small and offline.** One process, one port, local files only, two ready-made engines, and an installation that
  needs no internet (all Python 3.13 wheels bundled).
- **Three sources in every answer.** Code graph (keywords, graph expansion, relations), code vectors (local and
  multilingual) and document graph, joined by prompt analysis, query expansion, the document-to-code bridge and
  re-ranking by meaning. Every hit says what found it and carries its signature, callers and callees.
- **Built for AI agents.** MCP and REST tools that replace grep, glob and read across all repositories of a set;
  grounded agents that cite and name what is missing; a prompt enhancer and a requirements writer on the same
  evidence.
- **Built for people.** A grouped UI where results look the same everywhere, evidence panels under every answer,
  and every long action visible as a job.
- **Operations.** A webhook per repository, debounced incremental updates, branch drift checks with overlays,
  supervised engines, one settings schema shown in the UI and written to `.env`.
- **Documentation.** Requirements traceability, 23 decision records, a configuration reference generated from the
  code.

## 3. Known limits and risks
- Tested against a **mock** corporate API. The retrieval plumbing is verified, but answer quality, requirements
  quality and real multilingual ranking depend on the organisation's models and must be checked with the real
  gateway.
- **Linux**: the installer is syntax-checked but has not been run on a Linux machine. GitLab and TFS were simulated
  with their webhook payloads.
- **One shared login**: no per-user roles or audit trail; put an SSO reverse proxy in front if needed.
- **Code vectors cost**: the first sync embeds every symbol once; on a slow gateway set `BRAIN_CODE_VECTORS=local`
  or raise `BRAIN_CODE_VECTORS_PARALLEL`. The vectors of one repository are held in memory while searching (about
  1 KB per symbol at 1024 dimensions).
- **Documents**: borderless tables and complex multi-column PDF layouts convert less well; Docling can be added
  through LightRAG's own settings if they matter ([ADR-015](decisions/ADR-015-rich-documents.md)).
- **One document graph** for all sets; separate document spaces need a second instance.

## 4. Rating

| Area | Score (of 10) | Why |
|---|---|---|
| Architecture and simplicity | 9 | a small core around two ready engines, clear plug-in seams, one process |
| Requirements coverage | 9 | all 27 requirements traced to code and tests ([00](00-REQUIREMENTS.md)) |
| Retrieval design | 8.5 | three sources, analysis, expansion, bridge, graph expansion, re-ranking; not yet measured on real models |
| Usefulness for AI agents | 9 | self-explaining hits, read/grep/files, grounded agents, enhancer, branch checks |
| UI for people | 8 | grouped, detailed, evidence everywhere; one shared account, no per-user features |
| Code quality | 8 | consistent, documented modules; a few long functions (search pipeline, requirements writer) |
| Testing | 7.5 | static and end-to-end tests; no real-API, Linux or load tests yet |
| Documentation | 9 | step-by-step guides, decision records, generated configuration reference |
| **Overall** | **8.5** | ready for a pilot; the next step is a pilot with the real gateway and real repositories |

## 5. Recommended next steps
1. Pilot with the real corporate API and two or three real repositories; tune `BRAIN_RERANK_WEIGHT` and
   `BRAIN_SEARCH_TOP_K`.
2. Ask 20 real questions in Turkish and English and keep them, with the expected files and documents, as a
   regression set.
3. Run setup once on a Linux server and add the result to [15-TESTING.md](15-TESTING.md).
4. Connect one real GitLab project and one TFS repository through their own webhooks.
