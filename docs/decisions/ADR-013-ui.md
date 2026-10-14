# ADR-013 - UI: plain JavaScript, vendored force-graph, live updates over server-sent events

**Status:** accepted · **Requirements:** R23, R35

## Decision
One static page (`brain/ui/index.html`, `app.js`, `style.css`) with no build step and one vendored library,
force-graph (MIT; canvas rendering that stays fluid with thousands of nodes). Light and dark themes follow the
operating system; the layout works on narrow screens. The menu is grouped by purpose (Use, Explore, Manage), and one
result renderer is shared by Search, Ask, Enhance, Learn and Requirements (ADR-023).

**Live updates**: every visible change on the server (a job step, a document indexed, vectors or pictures completed,
repositories or settings saved, a webhook delivery) increases one counter. The page keeps one server-sent-events
connection to `/api/events` and, on each change, refreshes the status and the page being shown (Overview, Documents,
Repositories, Requirements list, Logs), at most about three times a second. Pages with something being typed or a
graph being explored are not redrawn. The connection reconnects by itself after a server restart.

## Alternatives
| Option | Why not |
|---|---|
| React or Vue with a bundler | a Node toolchain to keep offline for about 750 lines of UI logic |
| polling every few seconds | late updates, needless requests; the page still looks stale right after an operation |
| websockets | two-way messaging is not needed; server-sent events are plain HTTP, work through proxies and reconnect by themselves |

## Consequences
The UI works offline, loads at once, can be changed with a text editor, and shows the result of every operation as
soon as the server has it. Graph views show the architecture level (classes, modules, routes with lifted edges) and
neighbourhoods on demand, so large repositories stay readable.
