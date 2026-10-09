# ADR-017 - Relevance pipeline: expansion, document bridge, graph expansion, re-ranking

**Status:** accepted · **Requirement:** R15

## Context
The prompt analysis (ADR-016) finds the important words, but words alone leave four gaps:
1. **Language**: a Turkish question ("banka yeniden deneme kuralı") shares no words with English code
   (`PaymentGateway.charge`, `retry`), and the code engine's bundled model is English- and code-oriented.
2. **Vocabulary**: documents and code name the same thing differently ("Payment Gateway" and `PaymentGateway`,
   "iade" and `refund_payment`).
3. **Structure**: the code that matters is often wired to a match (its caller or callee) without sharing its words.
4. **Ranking**: a lexical rank orders by shared words, not by meaning, so the best answer is often far down.

## Decision
After recall, these stages run, each with its own setting (all on by default):

| Stage | What it does | Cost | Setting |
|---|---|---|---|
| Query expansion (agents only) | one short model call returns up to 10 extra terms: likely English identifiers, translations, synonyms | one small chat call, at most `BRAIN_QUERY_EXPANSION_TIMEOUT` (20 s), skipped on error | `BRAIN_QUERY_EXPANSION` |
| Document → code bridge | entity names from the document results ("Payment Gateway") become extra code-search terms (`Payment`, `Gateway`, `PaymentGateway`), merged by reciprocal rank at half weight | one extra local code query | `BRAIN_DOC_BRIDGE` |
| Code-graph expansion | callers, callees, parents and implementations of the best hits join the candidates at half weight | one local SQL query per repository | `BRAIN_GRAPH_EXPAND`, `BRAIN_GRAPH_EXPAND_TOP` |
| Re-ranking by meaning | the prompt, the code candidates and the document passages are embedded with the corporate multilingual model; final order = `BRAIN_RERANK_WEIGHT` × similarity + the rest × lexical rank | one batched embedding call, cached in memory | `BRAIN_RERANK`, `BRAIN_RERANK_CANDIDATES` |

Search itself still makes no chat call: expansion is used only by the agents, which call the model anyway.

## Alternatives
| Option | Why not |
|---|---|
| a cross-encoder reranker (bge-reranker) | needs a model server or a local ML runtime; corporate gateways rarely offer `/rerank` |
| re-ranking with a chat model | a chat call per search; slow |
| translation dictionaries | maintenance; the embedding model and the chat model already cover both languages |

## Consequences
Cross-language and cross-vocabulary questions find the implementing code, connected code is found through the graph,
and the most meaningful results come first. Every response shows the stages that ran (`pipeline`), the expanded and
bridged terms, and per hit `matched` and `similarity`, so each stage's effect is visible and each can be switched off.
