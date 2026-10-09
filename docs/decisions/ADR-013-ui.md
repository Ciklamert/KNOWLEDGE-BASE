# ADR-013 - UI: plain JavaScript, vendored force-graph, polled jobs

**Status:** accepted · **Requirement:** R23

## Decision
One static page (`brain/ui/index.html`, `app.js`, `style.css`) with no build step and one vendored library,
force-graph (MIT; canvas rendering that stays fluid with thousands of nodes). Progress and errors come from the job
registry, polled every 1-4 seconds. Light and dark themes follow the operating system; the layout works on narrow
screens. The menu is grouped by purpose (Use, Explore, Manage), and one result renderer is shared by Search, Ask,
Enhance and Requirements (ADR-023).

## Alternatives
React or Vue with a bundler (a Node toolchain to keep offline for about 670 lines of UI logic); server-sent events or
websockets for progress (more moving parts than polling small JSON).

## Consequences
The UI works offline, loads at once, and can be changed with a text editor. Graph views show the architecture level
(classes, modules, routes with lifted edges) and neighbourhoods on demand, so large repositories stay readable.
