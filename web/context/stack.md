# Stack

## No framework and no build step: static HTML, vanilla JavaScript as classic scripts, CSS

**Id:** bbf733b2-9b82-4c60-9857-4ee23849683b
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** the coordinator's task brief, 2026-10-21; the dashboard's first implementation, 2026-10-21
**Revisit when:** a view needs client-side state that hand-written DOM code cannot keep correct, or a dependency has to be vendored

The dashboard is a directory of static files the hub serves at `/`:
one `index.html`, plain JavaScript files, one stylesheet. No framework,
no bundler, no Node toolchain, no package manager; anything external
would be vendored into `web/` as a file. The scripts are classic
`<script defer>` files sharing one `window.Maity` namespace, not ES
modules, and the page opens from the file system as well as from the
hub. `make check` runs on Python's standard library alone.

**Reason:** no framework, no build step and no Node toolchain are set by
the brief; why is not recorded there. The inferred reason: the hub is a
Python service that must start with nothing else installed (root
`context/architecture.md`), and a dashboard that needs `npm install` and a
build before the hub can serve it would add a second toolchain to every
install path and to CI. Classic scripts instead of ES modules follow from
the file-system requirement, which is confirmed: browsers refuse module
scripts loaded from `file://` (opaque origin), so modules would force a
local web server for development.

**Rejected alternative:** a component framework (React, Vue, Svelte) with
a build step — excluded by the brief. ES modules without a bundler —
rejected for the `file://` reason above; the cost accepted is a load
order in `index.html` and one global namespace instead of imports.
