# ADR-027 - Every repository is updated at least every 24 hours

**Status:** accepted · **Requirement:** R33

## Context
Webhooks, pull hooks and the local-checkout watch update a repository when something happens. A missed webhook, a
server that was down during a merge, or a checkout nobody pulls would leave a repository behind indefinitely.

## Decision
Once a minute the server checks every repository; one whose last update (successful or failed, from
`data/state.json`) is older than `BRAIN_SYNC_INTERVAL_MINUTES` (default 1440 = 24 hours) gets an update. Every other
update resets its clock, so an active repository is not updated twice; a repository already being updated is skipped.
`0` turns it off.

## Alternatives
A fixed daily time for all repositories (every repository at once, a load peak, and a restart at that time skips a
day); updating all repositories every N minutes regardless of activity (repeats work the webhooks already did).

## Consequences
No repository is ever more than a day behind, even without webhooks, and after a restart the overdue repositories
are caught up within a minute.
