# ADR-016 - Prompt analysis before search, ask and enhance

**Status:** accepted · **Requirements:** R14, R10, R9

## Decision
Every prompt first goes through `brain/query.py` (no model call, a few milliseconds):
1. tokenise: Unicode words, code identifiers, file paths, quoted phrases;
2. take out the stop-words: built-in English and Turkish lists plus `BRAIN_STOPWORDS_EXTRA`;
3. score the remaining words: quoted phrase +4, identifier or file path +3, acronym +2, each repetition +0.5,
   longer words slightly higher, generic programming words and Turkish verb forms halved; keep the best
   `BRAIN_QUERY_MAX_TERMS`;
4. add search variants: one Turkish case, plural or possessive suffix removed (`Müşteriden` → `Müşteri`), English
   plurals (`refunds` → `refund`), identifier parts (`chargeCustomer` → `charge`, `Customer`);
5. build concepts: runs of adjacent important words (`partial refunds`, `Müşteriden ödeme alınırken`);
6. guess the language: `tr`, `en`, `mixed` or `unknown`.

The analysis drives everything after it: the code engine's BM25 query is key terms + variants, its vector query the
key terms, LightRAG's high-level keywords the concepts and its low-level keywords the key terms + variants; the agents
receive the analysis before the retrieved material. It is returned in every response, available alone at
`POST /api/analyze`, and shown live in the UI while typing.

## Alternatives
| Option | Why not |
|---|---|
| let LightRAG's model extract keywords | a chat call per search; search must not call a model |
| full NLP (spaCy, Zemberek, stemmers) | models and packages for two languages; the heuristics cover the identifiers and nouns that matter for code and business documents |
| a flat keyword list (the first N non-stop words) | no ranking: verbs and filler words crowd out identifiers; Turkish inflected forms miss exact matches |

## Consequences
Searches focus on the words that identify things (symbols, files, domain terms), Turkish inflected nouns match their
base forms, and graph retrieval uses themes instead of the raw sentence. People see how their prompt was understood
before running it. Company jargon that should not count is one setting away (`BRAIN_STOPWORDS_EXTRA`).
