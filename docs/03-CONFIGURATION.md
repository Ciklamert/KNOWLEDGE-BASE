# 03 - Configuration reference

> Generated from `brain/settings.py` by `python tools/gen_config.py`. Do not edit by hand.

## Where values come from

1. **The configuration file** `.env` in the install folder (another file: set the environment variable `BRAIN_CONFIG_FILE=/path/brain.env`). The web UI *Settings* page edits this same file in place.
2. **Process environment variables** - used only for keys that are *not* in the file.
3. **Defaults** listed below.

Repositories and repository sets live in `repos.json` (another file: `BRAIN_REPOS_FILE`). See [04-REPOSITORIES-AND-SETS.md](04-REPOSITORIES-AND-SETS.md).

**Restart column:** *live* = applied on the next request; *docs*/*code* = that engine restarts automatically when you save in the UI (from the CLI: restart the server); *server* = restart `brain serve` yourself.

**Pass-through:** any `LIGHTRAG__NAME=value` line is passed to LightRAG as `NAME=value` (e.g. `LIGHTRAG__ENTITY_TYPES`, `LIGHTRAG__MAX_GLEANING`); any `CBM__NAME=value` is passed to codebase-memory-mcp. So every engine variable is adjustable without code changes.

## Server

| Key | Default | Restart | Meaning |
|---|---|---|---|
| `BRAIN_HOST` | `0.0.0.0` | server | Bind address. 0.0.0.0 = reachable from any IP (login required). |
| `BRAIN_PORT` | `8765` | server | Port for UI, REST API, MCP and webhooks. |
| `BRAIN_PUBLIC_URL` | (empty) | live | Address users and agents use, e.g. http://10.0.0.5:8765 (shown in the UI). |
| `BRAIN_UI_USER` | `admin` | live | Login user name for the web UI and API (Basic auth). |
| `BRAIN_UI_PASSWORD` | (empty) | live | **required** Login password (UI + API). The server refuses to listen on a network address without it. Secret: never shown by the UI. |
| `BRAIN_API_TOKEN` | (empty) | live | Bearer token for AI agents (REST + MCP). Empty = only user/password. Secret: never shown by the UI. |
| `BRAIN_SECRET_KEY` | (empty) | live | Signs login cookies. Empty = generated once and stored in the data folder. Secret: never shown by the UI. |
| `BRAIN_SESSION_HOURS` | `12` | live | How long a UI login stays valid. |
| `BRAIN_TLS_CERT` | (empty) | server | PEM certificate file to serve HTTPS (optional). |
| `BRAIN_TLS_KEY` | (empty) | server | PEM private key file for HTTPS (optional). |
| `BRAIN_DATA_DIR` | `data` | server | Where all state lives (graphs, documents, clones). Relative = inside the install. |
| `BRAIN_MAX_UPLOAD_MB` | `200` | live | Largest accepted document upload. |

## Corporate API

| Key | Default | Restart | Meaning |
|---|---|---|---|
| `BRAIN_LLM_BASE_URL` | (empty) | docs | **required** OpenAI-compatible base URL, ending in /v1. |
| `BRAIN_LLM_API_KEY` | (empty) | docs | **required** API key for the base URL. Secret: never shown by the UI. |
| `BRAIN_LLM_MODEL` | (empty) | docs | **required** Default chat model (used by every role that has no own model). |
| `BRAIN_EMBEDDING_MODEL` | (empty) | docs | **required** Embedding model (multilingual, e.g. bge-m3): documents, the multilingual code vectors and re-ranking. |
| `BRAIN_EMBEDDING_DIM` | `1024` | docs | **required** Embedding vector size. Changing it (or the model) requires re-ingesting documents; code vectors rebuild by themselves. |
| `BRAIN_EMBEDDING_BASE_URL` | (empty) | docs | Only if embeddings live on a different URL. |
| `BRAIN_EMBEDDING_API_KEY` | (empty) | docs | Only if embeddings need a different key. Secret: never shown by the UI. |
| `BRAIN_VLM_MODEL` | (empty) | docs | Vision model for images and scanned pages in documents (optional). |
| `BRAIN_CA_BUNDLE` | (empty) | docs | Corporate CA certificate (PEM) for TLS interception. |
| `BRAIN_VERIFY_TLS` | `true` | docs | Verify TLS certificates of the corporate API. |
| `BRAIN_LLM_TIMEOUT` | `120` | live | Default seconds for one chat/embedding HTTP call. |
| `BRAIN_AGENT_TOOL_CALLING` | `auto` | live | auto = use native tool calling, fall back if the gateway rejects it; native; off = one-shot with context. One of: `auto`, `native`, `off`. |

## Relevance

| Key | Default | Restart | Meaning |
|---|---|---|---|
| `BRAIN_QUERY_MAX_TERMS` | `12` | live | How many key terms are extracted from a prompt (most important first). |
| `BRAIN_STOPWORDS_EXTRA` | (empty) | live | Extra stop-words to ignore, comma separated (company jargon, e.g. proje, ekip, ticket). Built-in: English + Turkish. |
| `BRAIN_RERANK` | `true` | live | Re-rank code and document results by meaning with the corporate embedding model (multilingual). |
| `BRAIN_RERANK_CANDIDATES` | `30` | live | How many code candidates are re-ranked (more = better recall, slower). |
| `BRAIN_RERANK_WEIGHT` | `0.6` | live | Share of meaning vs. lexical rank in the final order (0-1). |
| `BRAIN_DOC_BRIDGE` | `true` | live | Use the domain entities found in documents as extra code-search terms (business words -> code). |
| `BRAIN_GRAPH_EXPAND` | `true` | live | Add callers, callees and parents of the best code hits as candidates (code graph expansion). |
| `BRAIN_GRAPH_EXPAND_TOP` | `5` | live | How many of the best code hits are expanded through the code graph. |
| `BRAIN_QUERY_EXPANSION` | `true` | live | Ask/enhance only: one short model call turns the prompt into extra search terms (English identifiers, synonyms, translations). |
| `BRAIN_QUERY_EXPANSION_TIMEOUT` | `20` | live | Seconds for the expansion call; on timeout the search continues without it. |

## Search

| Key | Default | Restart | Meaning |
|---|---|---|---|
| `BRAIN_SEARCH_TOP_K` | `8` | live | Code hits returned per search. |
| `BRAIN_SEARCH_DOC_CHUNKS` | `6` | live | Document passages returned per search. |
| `BRAIN_SEARCH_TIMEOUT` | `60` | live | Seconds before a search part (code or docs) is abandoned. |
| `BRAIN_CONTEXT_MAX_CHARS` | `16000` | live | Size budget of rendered search context given to agents. |
| `BRAIN_SEARCH_DETAIL` | `normal` | live | How much of each code hit search writes for AI agents, MCP and the CLI (less = fewer tokens): brief = location, signature, callers, callees and why it matched; normal = also the source of the 3 best hits; full = the source of every hit. A request can choose another level. One of: `brief`, `normal`, `full`. |
| `BRAIN_TOOL_MAX_TOKENS` | `2500` | live | Approximate token limit of one code-tool answer for agents (trace, grep, overview); longer answers are cut and say how to get the rest. |

## Ask agent

| Key | Default | Restart | Meaning |
|---|---|---|---|
| `BRAIN_ASK_MODEL` | (empty) | live | Chat model for the ask agent (empty = BRAIN_LLM_MODEL). |
| `BRAIN_ASK_TIMEOUT` | `180` | live | Total seconds for one question (all steps). |
| `BRAIN_ASK_MAX_STEPS` | `6` | live | Maximum tool-calling rounds before answering. |
| `BRAIN_ASK_MAX_TOKENS` | `1500` | live | Maximum tokens of the answer. |
| `BRAIN_ASK_TEMPERATURE` | `0.1` | live | Sampling temperature. |

## Enhance agent

| Key | Default | Restart | Meaning |
|---|---|---|---|
| `BRAIN_ENHANCE_MODEL` | (empty) | live | Chat model for the prompt enhancer (empty = BRAIN_LLM_MODEL). |
| `BRAIN_ENHANCE_TIMEOUT` | `120` | live | Total seconds for one enhancement (all steps). |
| `BRAIN_ENHANCE_MAX_STEPS` | `4` | live | Maximum tool-calling rounds before writing the prompt. |
| `BRAIN_ENHANCE_MAX_TOKENS` | `1800` | live | Maximum tokens of the enhanced prompt. |
| `BRAIN_ENHANCE_TEMPERATURE` | `0.2` | live | Sampling temperature. |

## Project guide

| Key | Default | Restart | Meaning |
|---|---|---|---|
| `BRAIN_GUIDE_MODEL` | (empty) | live | Chat model for the project guide (empty = BRAIN_LLM_MODEL). |
| `BRAIN_GUIDE_TIMEOUT` | `300` | live | Total seconds for one project guide (all steps). |
| `BRAIN_GUIDE_MAX_STEPS` | `5` | live | Maximum tool-calling rounds before writing the guide. |
| `BRAIN_GUIDE_MAX_TOKENS` | `3000` | live | Maximum tokens of the guide. |
| `BRAIN_GUIDE_TEMPERATURE` | `0.2` | live | Sampling temperature. |

## Code graph

| Key | Default | Restart | Meaning |
|---|---|---|---|
| `BRAIN_CODE_PROVIDER` | `codebase_memory` | code | Code graph plug-in: a name in brain/providers or 'package.module:Class'. |
| `CBM_BIN` | (empty) | code | Path to codebase-memory-mcp (empty = bin/<os>/ of this install). |
| `CBM_INDEX_MODE` | `full` | live | full = all files + semantic vectors; moderate; fast = no vectors. One of: `full`, `moderate`, `fast`. |
| `CBM_INDEX_TIMEOUT` | `7200` | live | Seconds one repository index may take. |
| `CBM_QUERY_TIMEOUT` | `120` | live | Seconds one code-graph query may take. |
| `BRAIN_CODE_VECTORS` | `both` | live | Semantic code search: local = only the code engine's bundled code embeddings (offline, English-oriented); both = also a code vector index built with the corporate multilingual embedding model (Turkish questions find English code by meaning; costs one embedding pass per changed symbol after each sync). One of: `local`, `both`. |
| `BRAIN_CODE_VECTORS_BATCH` | `64` | live | Symbols per embedding request when building the corporate code vectors. |
| `BRAIN_CODE_VECTORS_PARALLEL` | `4` | live | Parallel embedding requests when building the corporate code vectors. |
| `BRAIN_CODE_VECTORS_MAX` | `200000` | live | Largest number of symbols embedded per repository. |

## Updates & webhooks

| Key | Default | Restart | Meaning |
|---|---|---|---|
| `BRAIN_SYNC_ON_START` | `true` | live | Clone/update and index all repositories when the server starts. |
| `BRAIN_SYNC_INTERVAL_MINUTES` | `0` | live | Also fetch+index every N minutes (0 = webhooks only). |
| `BRAIN_DEFAULT_BRANCH` | `main` | live | Branch the code graph follows when a repository does not name one. |
| `BRAIN_WEBHOOK_EVENTS` | `merge,push` | live | Events that trigger an update of the tracked branch: merge (MR/PR merged), push (any push to it). |
| `BRAIN_WEBHOOK_DEBOUNCE_SECONDS` | `15` | live | Webhooks for the same repo within this window run one update. |
| `BRAIN_GITLAB_WEBHOOK_SECRET` | (empty) | live | Group-level GitLab webhook secret (/webhooks/gitlab). Each repository also has its own webhook and secret. Secret: never shown by the UI. |
| `BRAIN_TFS_WEBHOOK_USER` | (empty) | live | Group-level TFS service-hook user (/webhooks/tfs). |
| `BRAIN_TFS_WEBHOOK_PASSWORD` | (empty) | live | Group-level TFS service-hook password (/webhooks/tfs). Each repository also has its own webhook and secret. Secret: never shown by the UI. |

## Git servers

| Key | Default | Restart | Meaning |
|---|---|---|---|
| `BRAIN_GIT_TIMEOUT` | `900` | live | Seconds for one git clone/fetch. |
| `BRAIN_GITLAB_URL` | (empty) | live | Corporate GitLab base URL, e.g. https://gitlab.corp.local. Repositories can then be written as gitlab:group/project. |
| `BRAIN_GITLAB_USER` | (empty) | live | User for HTTPS clone/fetch from BRAIN_GITLAB_URL (any name works with a token). |
| `BRAIN_GITLAB_TOKEN` | (empty) | live | GitLab personal/project access token with read_repository. Secret: never shown by the UI. |
| `BRAIN_TFS_URL` | (empty) | live | Corporate TFS / Azure DevOps Server collection URL, e.g. https://tfs.corp.local/tfs/DefaultCollection. Repositories can then be written as tfs:Project/repo. |
| `BRAIN_TFS_USER` | (empty) | live | User for HTTPS clone/fetch from BRAIN_TFS_URL. |
| `BRAIN_TFS_TOKEN` | (empty) | live | TFS / Azure DevOps personal access token with Code (read). Secret: never shown by the UI. |
| `BRAIN_GIT_USER` | (empty) | live | User for HTTPS git on any other server (fallback credentials). |
| `BRAIN_GIT_TOKEN` | (empty) | live | Token for HTTPS git on any other server (fallback credentials). Secret: never shown by the UI. |
| `BRAIN_GIT_CA_BUNDLE` | (empty) | live | Corporate CA certificate (PEM) for the git servers' HTTPS. |
| `BRAIN_GIT_SSL_VERIFY` | `true` | live | Verify TLS for git (false only for broken internal CAs). |

## Requirements writer

| Key | Default | Restart | Meaning |
|---|---|---|---|
| `BRAIN_SRS_MODEL` | (empty) | live | Chat model for the requirements writer (empty = BRAIN_LLM_MODEL). |
| `BRAIN_SRS_TIMEOUT` | `1800` | live | Total seconds for one specification (all sections). |
| `BRAIN_SRS_MAX_CAPABILITIES` | `12` | live | Most capabilities (feature areas) described in one specification. |
| `BRAIN_SRS_MAX_TOKENS` | `3000` | live | Maximum tokens per written section. |
| `BRAIN_SRS_TEMPERATURE` | `0.2` | live | Sampling temperature. |
| `BRAIN_SRS_LANGUAGE` | `auto` | live | Language of the specification: auto (same as the request), English, Turkish ... |

## Document graph

| Key | Default | Restart | Meaning |
|---|---|---|---|
| `BRAIN_DOC_PROVIDER` | `lightrag` | docs | Document graph plug-in: a name in brain/providers or 'package.module:Class'. |
| `LIGHTRAG_PORT` | `9631` | docs | Internal LightRAG port (127.0.0.1 only). |
| `LIGHTRAG_LLM_MODEL` | (empty) | docs | Chat model for entity extraction (empty = BRAIN_LLM_MODEL). |
| `LIGHTRAG_LLM_TIMEOUT` | `240` | docs | LightRAG LLM_TIMEOUT: seconds for one chat call during entity/relation extraction and summaries. |
| `LIGHTRAG_EMBEDDING_TIMEOUT` | `60` | docs | LightRAG EMBEDDING_TIMEOUT: seconds for one embedding call. |
| `LIGHTRAG_TIMEOUT` | `300` | docs | LightRAG TIMEOUT: seconds the LightRAG server allows for one HTTP request. |
| `LIGHTRAG_STARTUP_TIMEOUT` | `180` | live | Seconds to wait for LightRAG to become healthy. |
| `LIGHTRAG_REQUEST_TIMEOUT` | `600` | live | Seconds for one request from this server to LightRAG. |
| `LIGHTRAG_MAX_ASYNC` | `4` | docs | Concurrent LLM calls during ingestion. |
| `LIGHTRAG_MAX_PARALLEL_INSERT` | `2` | docs | Documents processed in parallel. |
| `LIGHTRAG_SUMMARY_LANGUAGE` | `English` | docs | Language of extracted entity descriptions (English, Turkish ...). |
| `LIGHTRAG_CHUNK_SIZE` | `1200` | docs | Tokens per chunk. |
| `LIGHTRAG_CHUNK_OVERLAP` | `100` | docs | Token overlap between chunks. |
| `LIGHTRAG_QUERY_MODE` | `mix` | live | Retrieval mode: mix (graph+vectors), hybrid, local, global, naive. One of: `mix`, `hybrid`, `local`, `global`, `naive`. |
| `LIGHTRAG_TOP_K` | `20` | live | Entities/relations retrieved per query. |
| `LIGHTRAG_PARSER` | (empty) | docs | Override LightRAG's parser routing (empty = automatic). |
