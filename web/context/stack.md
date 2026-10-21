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

## The behaviour smoke test runs on a bare node binary in CI; make check stays on Python alone

**Id:** ad2319c8-9158-483e-b180-ee88691c6b87
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's review of the dashboard pull request, 2026-10-21
**Revisit when:** CI can run a real browser without adding a package manager to the repository, or the shim starts to need browser behaviour it does not have
**See:** stack.md#no-framework-and-no-build-step-static-html-vanilla-javascript-as-classic-scripts-css — bbf733b2-9b82-4c60-9857-4ee23849683b — as of 2026-10-21

`tools/smoke.js` runs the page's scripts against a minimal DOM shim in
Node and walks every view, in fixture mode and against a fake hub
(`make smoke`). It uses Node's built-in modules only: no `package.json`,
no `npm install`, no dependency. CI runs it in the `web` job next to
`make check`, which stays on the Python standard library. Neither is a
browser test; what a change looks like in a browser is stated in its
pull request.

**Reason:** the structure checks cannot see behaviour (the inbox moving
to the next entry, a reply id turning into a class, fixture mode being
reachable), and the dashboard's scripts are JavaScript, so a JavaScript
runtime is the cheapest way to execute them. A node binary is on every
CI runner and on most developer machines; the toolchain the stack
decision excludes is the package ecosystem, not the runtime.

**Rejected alternative:** a headless browser (Playwright, Puppeteer) — it
brings a package manager and a browser download into the repository and
CI. Emulating the DOM in Python — no standard-library DOM, and a second
copy of the page's behaviour to keep in step. Keeping the test outside
the repository — nobody else could run it, and CI would not.
