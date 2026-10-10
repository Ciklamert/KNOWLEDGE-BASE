# ADR-025 - Learning a project: structure without a model, a guide written from evidence

**Status:** accepted · **Requirement:** R29

## Context
People who are new to a repository, or who research while coding, need to know what it does, how it is built,
which flows matter and where to start reading. The code graph already knows the structure; the documents know
the business; neither was presented as an introduction.

## Decision
- **Learn a project** page in the UI. *Show structure* displays, per repository of the chosen scope, the code
  engine's architecture overview: languages, packages, entry points, routes and the most-connected code (no model
  call, instant). *Write project guide* runs the shared agent loop (ADR-007) with a guide prompt, seeded with those
  overviews and a search, and writes: What it is, How it is built, Main flows (numbered, cited steps), Where to start
  reading, Key concepts, Business rules, Good to know.
- The guide can be copied, downloaded, or added to the document graph so later searches find it.
- The same guide is available as `POST /api/guide` and `brain guide`; it is not an MCP tool, because coding agents
  get the same knowledge more cheaply from `overview`, `symbol` and `search`.
- **Ask about this** in the code graph opens Ask with a question about the selected symbol: what it does, who
  calls it and which business rules apply.

## Alternatives
A static generated documentation site (stale after every merge, no business rules); a separate wiki (maintained by
hand); a guide per repository generated at every sync (model cost for guides nobody reads).

## Consequences
A newcomer gets a cited introduction in about a minute, always built from the current `main`, and can follow every
claim to the code or the document it came from.
