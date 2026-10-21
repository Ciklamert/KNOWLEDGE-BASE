# ADR-030 - Never pay the slow API twice; branch overlays that clean themselves up; pictures with an OCR fallback

**Status:** accepted · **Requirements:** R46, R47, R48, R49

## Context
The corporate API is the slow and scarce part: one OpenAI-compatible URL and key in an air-gapped network. Three
things spent it without need:
- **The same text was embedded again** after *Re-index all*, a re-upload or a new document version, and a branch
  overlay re-embedded every symbol of its repository although only a few files changed.
- **The same picture was described again** for the same reasons; nothing limited the vision calls, and a scanned
  page had no text at all when there was no vision model or it failed.
- **Branch overlays lived for ever**: removal was manual, and webhooks ignored other branches.

## Decision
1. **One vector cache for every embedding.** `llm.embed` asks `data/vectors.db` (SQLite) first: key = SHA-1 of the
   model name and the text, value = the unit vector as int8 (the precision every index here stores), plus the day
   of last use. Passages, concept names, code symbols and questions all benefit without their own code. Entries not
   used for `BRAIN_VECTOR_CACHE_DAYS` (180) are removed daily. `BRAIN_VECTOR_CACHE=false` turns it off.
2. **Branch overlays reuse the main branch by content, not by copying.** The overlay's graph is still built from the
   full worktree on the CPU (correct calls between changed and unchanged files); its vectors come from the cache,
   so only symbols changed on the branch reach the API. Because the cache is keyed by text, it works whichever
   branch is "main": each repository chooses it (*Main branch* column, `BRAIN_DEFAULT_BRANCH` by default).
3. **Overlays leave with their branch**, three layers: the webhook's branch deletion (git's all-zero new commit:
   GitLab `after`, TFS `refUpdates[].newObjectId`; a GitLab merge with *Delete source branch*); a reconcile with
   `git ls-remote --heads` after every update of the repository; and expiry after `BRAIN_BRANCH_TTL_DAYS` (30)
   without an index or a search. A push to a branch with an overlay updates it (`BRAIN_BRANCH_UPDATE_ON_PUSH`).
4. **Pictures:** a description cache by the picture's SHA-1 (table `seen`), shared by all documents; pictures under
   `BRAIN_PICTURE_MIN_PX` (120) or of nearly one colour skipped; at most `BRAIN_VLM_MAX_PER_HOUR` (60) vision calls,
   oldest first, `BRAIN_VLM_TIMEOUT` (90 s) each; the document engine resumes every 10 minutes by itself.
5. **OCR as a fallback, not a stage.** RapidOCR 1.2.3 (ONNX Runtime on the CPU, models inside the wheel, about
   2 s per picture) reads a picture's text at once when there is no vision model, when the vision call fails or
   times out, or when the hourly budget is used up. The vision model replaces that text with its description later.
   It is an optional pack (`wheels/ocr/`, about 150 MB); without it nothing changes. `BRAIN_OCR=off` disables it.

## Alternatives
- **Seed overlay vectors from the main branch's npz file** by symbol and hash: covers only the overlay case and
  needs its own code; the text cache covers it and every other re-embedding.
- **Index only the changed files of a branch** (fast, but calls between changed and unchanged files go missing), or
  **copy main's engine database** (depends on codebase-memory-mcp internals). Rejected: the graph is cheap, the API
  is not.
- **Only webhooks, or only a nightly check**, for deleted branches: a webhook can be missed, a nightly check alone is
  slow. Both, plus expiry, cost one git call per update.
- **OCR on every picture first, vision only on demand:** cheaper, but OCR reads only text, not what a chart or
  diagram shows. **Image embeddings** (CLIP, ColPali): no image-embedding endpoint on the gateway, and local models
  need torch. **Tesseract:** a system install with Turkish data files, not a pip wheel. **RapidOCR 3.x:** downloads
  models at run time.

## Consequences
- Re-indexing, re-uploading, new versions and branch overlays cost API calls only for what really changed.
- A deleted branch's overlay disappears at once with a webhook, at the next update without one, and an abandoned one
  after 30 days. The Repositories page shows each overlay's age and expiry.
- A 300-page scan no longer floods the gateway: it is read by OCR in minutes and described by the vision model at
  60 pages an hour in the background.
- OCR drops Turkish accents (search folds them anyway) and misses some lines on poor scans; it is a floor, not a
  replacement for the vision model.
