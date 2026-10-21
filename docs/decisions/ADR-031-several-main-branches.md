# ADR-031 - Several main branches per repository

**Status:** accepted · **Requirement:** R50

## Context
Many teams keep more than one long-lived branch: `main` for production, `develop` for integration, `release/x` for
versions in maintenance. Feature branches are cut from any of them. With one tracked branch per repository, a
`develop` overlay expired after `BRAIN_BRANCH_TTL_DAYS`, was updated only when someone pushed to it, and every drift
check measured a feature branch against `main`, although it was cut from `develop`.

## Decision
- A repository keeps its main branch (`branch`, the repository's own project) and lists its **other main branches**
  (`mains`; `BRAIN_OTHER_MAIN_BRANCHES` as the default). Each is a branch overlay marked `main`: indexed at every
  update of the repository when its head moved (one `git ls-remote`), updated at once by a push or merge webhook,
  never expired.
- A feature branch is compared with **the main it derives from**: the main for which
  `git rev-list --count origin/<main>..origin/<branch>` is smallest. The overlay stores it as `base`; drift checks,
  `brain drift` and the UI use it; `base` (REST) or `--main` (CLI) overrides it.
- Vectors cost nothing extra: the vector cache ([ADR-030](ADR-030-api-economy-branches-pictures.md)) shares every
  unchanged symbol between all main branches.

## Alternatives
- **One repository entry per main branch** (`billing-develop`): works today, but duplicates the clone, the webhook
  and the settings, and feature branches still cannot tell which entry they belong to.
- **The merge-base date** to pick the base: a main merged into another (main → develop) makes the dates ambiguous;
  the count of unshared commits is exact and one git call per main.

## Consequences
Teams with GitFlow or release branches see each main branch fully indexed and current, search it with
`branch=develop`, and get drift advice against the branch they actually cut from. The cost is one worktree and one
code graph per extra main branch, built on the local CPU.
