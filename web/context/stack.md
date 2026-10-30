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
**See:** stack.md#a-real-browser-end-to-end-test-runs-in-ci-with-playwright-for-python-next-to-the-smoke-test — fb1daf22-fe54-4073-b89e-9e099a5a389e — as of 2026-10-22

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

## A real-browser end-to-end test runs in CI with Playwright for Python, next to the smoke test

**Id:** fb1daf22-fe54-4073-b89e-9e099a5a389e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's request for real-browser end-to-end tests before the maintainer's first browser test, 2026-10-22; the VM's missing Chromium libraries (`ldd`), 2026-10-22
**Revisit when:** the dashboard gets a Node toolchain for another reason, or the CI job outgrows its time budget
**See:** stack.md#the-behaviour-smoke-test-runs-on-a-bare-node-binary-in-ci-make-check-stays-on-python-alone — ad2319c8-9158-483e-b180-ee88691c6b87 — as of 2026-10-22

`tools/e2e.py` starts a real hub on a free loopback port with a
throwaway SQLite file, serving this checkout's `web/`, and drives the
dashboard in headless Chromium through Playwright for Python, while the
agent side is the `maity` CLI in scratch clones: sign-in, create a
project, the join line, an agent joining, claiming a card, asking,
the answer in the inbox waking the agent's `maity wait`, a second
project, the switcher and the cross-project view. It takes a screenshot
of every step and fails on any console error, page error or failed API
call. CI runs it in its own job, `web-e2e`, and uploads the screenshots
also when a step fails. The smoke test stays: it is the fast check of
every view and branch the browser test does not walk.

**Reason:** the smoke test's DOM shim has no layout, focus, real timers,
CSP or browser `fetch`, and the shim's gaps had already hidden bugs. The
earlier entry rejected a headless browser because it brings a package
manager into the repository; Playwright for Python does not: it is one
more `pip install` next to the hub and the CLI, which the test needs
anyway, so `web/` still has no `package.json`, no `node_modules` and no
build step, and the browser download happens on the runner only. Python
also drives the hub's and CLI's processes directly. It runs in CI and
not only as a documented script because the shared VM's Chromium lacks
system libraries (`libnss3`, `libnspr4`, `libasound2`) and they cannot
be installed without root there, while the CI runner has them (the job
checks with `ldd` and installs a fixed minimal list only when one is
missing, since 2026-10-22; `--with-deps` before took 52 s to 5 min).

**Rejected alternative:** Playwright for Node — a `package.json` and a
lockfile in `web/`, the Node toolchain the stack excludes. Selenium —
a separate driver to match to the browser, and no waiting on the page's
state built in, which the feed's 5-second interval needs. Only a
documented local script — on this VM it could not run, so nobody would
have seen the dashboard in a browser before the maintainer.

## The browser test checks accessibility with axe-core from the npm tarball, pinned by its sha512 and read without npm

**Id:** fedb8f92-42ff-4918-9840-5bfcc6c7c6cb
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's request for an automated accessibility pass in the browser test, 2026-10-22
**Revisit when:** axe-core stops shipping `axe.min.js` in its npm package, or the dashboard gets a Node toolchain
**See:** stack.md#a-real-browser-end-to-end-test-runs-in-ci-with-playwright-for-python-next-to-the-smoke-test — fb1daf22-fe54-4073-b89e-9e099a5a389e — as of 2026-10-22

`tools/e2e.py` runs axe-core on each view as the scenario reaches it:
at 1280 and 390 px in the light scheme, and at 1280 px dark. A serious or
critical violation fails the run after the last step; every finding goes
to `a11y.json` and `a11y.txt` in the artifacts. The engine is the npm
package's tarball at a fixed version. The script fetches it from the
registry once, checks it against the registry's sha512 integrity on every
run, and reads `package/axe.min.js` from it in memory, without npm and
without extracting anything. It is evaluated into the page through the
DevTools protocol, so the hub's `default-src 'self'` CSP stays as served.

**Reason:** axe-core is the engine the usual accessibility tools build on,
and its npm package is its own release, signed and with provenance. The
sha512 pins exactly that file, the way a lock pins a Python dependency. No
`package.json`, no `node_modules` and no build step come into `web/`, which
the stack entries exclude.

**Rejected alternatives:**
- `axe-playwright-python` from PyPI: a third-party wrapper that bundles a
  copy of axe of its own choosing, so it adds a second party to trust for
  the same file.
- Vendoring `axe.min.js` into the repository: 650 KB of minified
  third-party code in every diff and review.
- Loading axe from a CDN in the page: the hub's CSP refuses it, and
  relaxing the CSP for the test would test a different page.
- `bypass_csp` in the browser context, to inject a script tag: the same
  objection, a page the hub does not serve.

## The QR code of a device-code URL is made by the dashboard's own encoder, checked against an independent one

**Id:** 0cbdffd3-1a72-4c65-af3a-cf3cbc2ddb0e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.6.7 ("made in the dashboard's own code, no third-party script", §1.1); the maintainer's wish for mobile sign-in by QR, 2026-10-23 (tsk-4nce5jy2axzp); the dashboard's implementation and its check against segno 1.6.6, 2026-10-25
**Revisit when:** the dashboard needs QR codes in another mode than bytes, or at another error correction level

`js/qr.js` encodes byte mode at error correction level M, every version
from 1 to 40 (up to 2331 bytes, so any public URL a hub may have fits),
with the eight masks scored by the four penalty rules of ISO/IEC
18004, and draws one SVG path of dark modules on a white ground in a
four-module quiet zone, dark on light in either theme. It was checked
module for module against segno, an independent encoder, for 117
symbols: five texts, versions picked and forced (7 and 10 carry version
information), each mask, and the mask chosen automatically. segno pads
an already byte-aligned stream with eight more zero bits, which the
standard does not ask for; with that one step set to the standard, every
symbol matched. A second run covered every version from 1 to 40, forced
with two masks each, and long texts up to the 2331-byte limit with the
mask chosen: 85 symbols, all equal. A smoke check keeps one symbol as a
fixed hash, so a change to the encoder shows. A URL no QR can hold leaves
the code and Cancel on the page without the QR.

**Reason:** the contract rules out a third-party script, and a sign-in
URL needs only a small part of QR: bytes and one error correction
level. All forty versions cost two tables, and a public host may have a
long name. The bit-exact comparison is what makes a
hand-written encoder trustworthy without a scanner in CI.

**Rejected alternative:** a QR library vendored into `web/`: third-party
code in the page the contract keeps it out of. A QR image made by the
hub: a server-side dependency and a second request for what the page can
draw. Only the code, no QR: the maintainer asked for sign-in on the phone
by scanning.

## The browser test moves the hub's clock as the page sees it whenever it moves the browser's

**Id:** 8c119e9f-9bc8-464f-8fae-54770977af9a
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-ekyd6skhtyp0 (the join-expiry step red on main a4f214a and on #560, green on other heads with no related change), 2026-10-30; web/js/api.js (every answer's `Maity-Server-Time` sets how far the browser is off the hub, `M.api.now()`); web/js/join.js (expiry judged by `M.api.now()` every 10 seconds); the step in web/tools/e2e.py
**Revisit when:** the hub gets a clock a test can move from outside, or the page stops judging expiry by the hub's clock

`join_expiry_step` moved only the browser's clock (`clock.fast_forward`)
past a join's 15 minutes. The page judges expiry by the hub's clock, and
every answer of the hub sets the browser's offset from it again: until
the next answer the page reckoned with the moved time and drew the join
as expired; after it, with the hub's real time, and the 10-second
re-judge drew the join as open again. Whether the check saw "expired"
depended on which came first. The step now routes the second tab's
calls to the hub and moves each answer's `Maity-Server-Time` by the same
16 minutes as the browser's clock, so both clocks the page reads agree
and nothing waits for real time.

**Reason:** the page is right to follow the hub's clock, so the test has
to move that clock too; a browser-only clock change contradicts every
next answer.

**Rejected alternative:** a join with the shortest TTL (60 seconds) and a
wait for it: a minute of real time per run, and still a race at the
edge. A clock the e2e hub takes from outside (an environment variable):
a way to set the hub's time in a running hub, for a test, which the hub
does not offer and should not need. Changing the page to keep its first
offset: the offset follows the hub on purpose, across a long session.

