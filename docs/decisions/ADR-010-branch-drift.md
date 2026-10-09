# ADR-010 - Branch drift: analysis with recommendations plus optional branch overlays

**Status:** accepted · **Requirement:** R22

## Context
The graph follows `main`; developers work on branches that fall behind `main` and differ from it.

## Decision
1. **Analysis without a model** (`brain/drift.py`): merge-base, commits behind, files changed on `main` since the
   branch point, files changed on the branch, their intersection (conflict risk), and whether AI-BRAIN itself lags
   `origin/main`. It works for pushed branches (computed on the server) and for unpushed ones (the caller sends
   `base_commit` and `changed_files`, which `brain drift` or the agent computes locally).
2. **Recommendations are always returned**, in order: update AI-BRAIN, rebase now (with the risky files) or rebase
   safely, trust local files for changed paths, build an overlay, refresh an overlay, or send git facts. The system
   recommends even where it cannot act: rebasing is the developer's job.
3. **Branch overlays**: a pushed branch can be indexed from a git worktree as an extra project; requests with
   `branch=` use it instead of `main` for that repository.
4. The enhancer puts the findings into its output, so the coding agent acts on them.

## Alternatives
Index every branch automatically (cost grows with the number of branches, and most branches differ little); ignore
the problem (agents would confidently edit against old signatures).

## Consequences
Developers and agents get a concrete, safe next step. An overlay costs one index per branch and should be removed
after merging.
