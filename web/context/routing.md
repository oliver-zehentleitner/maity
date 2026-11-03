# Routing

How the dashboard reads and changes its address. The decision to address
it by paths is the family's: [`context/routing.md`](../../context/routing.md)
(e34ae588) and docs/api.md §16.11.

## The address is read and changed in one helper, `M.route`; only fixture mode carries the path in the fragment

**Id:** 5159639a-f639-4ee7-8a5b-b750c96c074b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §16.11 (the dashboard routes with the History API; how `file://` fixture mode finds its files is the web owner's); the coordinator's approval of the proposal on the routing card (tsk-vaxw9ye9yvm5), 2026-10-29
**Revisit when:** fixture mode is served by a development server, or the dashboard gets a router library

`js/route.js` is the one place that knows how the address bar holds a
route. Over http(s) it reads `location.pathname` and `location.search`,
changes them with `pushState` and `replaceState`, and draws the view on
`popstate`; a click on a link of the dashboard (a path, not a hub path
such as `/api/`, `/assets/`, `/join/`) stays in the page, while a
modified click, another target or a download is the browser's. Going to
the address one is at changes nothing, as a link to the same fragment
did. In fixture mode, a page opened from `file://`, the same path
travels in the fragment (`index.html#/new`), since such an address
cannot carry a path and `pushState` to another one is refused there.
Every view writes paths: `M.dom.h` turns an `href` that is a route into
what the address bar needs. `M.route.isRoute` is also the security
boundary for those links and for a sign-in's `next`: no `//`, no
backslash (which a browser reads as a slash, so `/\x` would leave the
origin), no control character, no hub path. `tools/check.py` fails on a `#/`, on
`location.hash` or on the History API anywhere in `web/js/` but
`js/route.js`. The device code reads from the fragment over https
(`/sign-in/code#c=…`) and is removed from the address once read; in
fixture mode it is the route's query.

**Reason:** a path is the address a forge has and the one public pages
share (§16.11); keeping the knowledge in one file lets fixture mode stay
a page opened from disk, which `context/fixtures.md` rests on, without
any view knowing the difference.

**Rejected alternative:** a development server for fixture mode, so it
could use paths too: fixture mode is defined as the page opened from
`file://`, and a served page never reads fixtures. Each view building
its own `#/` or path by mode: every call site would carry the
distinction, and one forgotten would break only in one of the two modes.

## The legal pages are the one kind of hub path the dashboard links to, by a fixed list

**Id:** d4878714-49e9-4aba-81ea-5d91e9b3bdd4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.7.1, §16.11 (the hub serves `/impressum`, `/privacy`, `/terms` and their versions itself); web/js/route.js `isHubPage`, web/js/dom.js; the landing editor (#632); the review of #632, 2026-10-30
**Revisit when:** the hub serves another page a person should reach from the dashboard, or the legal pages move under a path of the dashboard

`M.route.isHubPage` accepts exactly `/impressum`, `/privacy` and
`/terms`, each optionally with one version segment, and only where
`isRoute` refuses them as hub paths; `h()` writes such an `href` as it
is, a plain page load, never through `M.route.href`. The legal links
on the login and registration pages and the editor's "Served at" links
are the only users.

**Reason:** the legal pages are the hub's static HTML (§16.7.1), so a
link to them leaves the app, as it must; every other hub path (`/api`,
`/assets`, `/join`, `/mail`, `/badge`, `/r`) is no page for a person and
stays refused by `h()`, the boundary the entry above keeps.

**Rejected alternative:** letting `h()` link any hub path as a plain
page load: one rule wider than needed would make a link to `/api/…` or
`/mail/…` from data possible again. Building the legal links outside
`h()`, as raw elements: the one place that checks every `href` would
have an exception nobody sees.

## The repository's `index.html` names its files relatively; the hub serves the shell with `<base href="/assets/">`

**Id:** bc798b68-fce9-41a6-a145-b4e25149b726
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §16.11 ("The app shell": its files under `/assets/`, a `<base>` or a development server for `file://` the web owner's to settle); the coordinator's approval and the hub's implementation in the hub's routing PR (#613), 2026-10-29
**Revisit when:** the dashboard gets a build step that writes the paths, or fixture mode stops being a page opened from disk

`web/index.html` loads `js/…`, `css/…` and `brand/…` relatively. The hub
inserts `<base href="/assets/">` right after `<head>` when it serves the
shell, so the files load at any depth of the address, and fixture mode
opens the same file from disk without a base. Under that base an anchor
(`#x`) or a bare query (`?x`) would lead into `/assets/`, so `M.dom.h`
takes neither as a local link; every link of the dashboard is an
absolute path, every API call starts with `/api/v1/`.

**Reason:** one file serves both: the hub's shell and the page opened
from disk.

**Rejected alternative:** absolute `/assets/…` paths in `index.html`:
fixture mode would ask `file:///assets/…` and load nothing. An inline
script choosing the base by protocol: the shell's
`Content-Security-Policy: default-src 'self'` forbids inline scripts.

## A project's swarm is its public page for anyone who is not a member, and at `?as=public`

**Id:** b3982ae9-18ec-4e1a-b383-c8d68d817a71
**Type:** decision
**Status:** superseded
**Superseded by:** 8a528eb5-8dd6-4fec-996e-79c5b57abb51
**Evidence:** confirmed
**Source:** docs/api.md §6.22 (the dashboard draws the public page at `/<owner>/<slug>/swarm` for visitors without a session, for anyone who is not a member and at `?as=public`; a member gets the Swarm tab with a link to the public view), §16.11; the card tsk-ejtazwt37dhp for the reduced body
**Revisit when:** the hub serves the public swarm as a static page of its own (§16.9), or pictures may be shown to visitors

`/<owner>/<slug>/swarm` draws the public page before any session is
asked when the address carries `?as=public`, for a visitor without a
session, and for a signed-in human who is not a member of the project;
a member gets the Swarm tab, which links to the public view. The public
page is drawn from the hub's reduced body only (`GET
/swarm/{owner}/{slug}`): agents with two-letter initials, a held card as
a count. Off, closed or unknown is one friendly "no public swarm here"
with a sign-in link that comes back to the page.

**Reason:** one canonical address for the public and the members' page
(§16.11); a member still checks what they publish with `?as=public`. The
hub already strips what the world may not see, and one message for off,
closed and unknown matches its uniform `not_found`.

**Rejected alternative:** the public page at an address of its own
(the earlier `#/s/<slug>`, shown to everyone there, members included):
§16.11 removes it, and `?as=public` gives members the same view at the
one address.

## A place on a page is a route and one checked anchor, written by `M.route` alone; in fixture mode it follows the route after a second `#`

**Id:** e5a0c394-947a-4c7c-b830-09c655befa44
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.8 ("The whole contract": `/<owner>/<slug>/contract#s-6.8` opens a section, a contract card's section links there), §16.11; web/js/route.js `isAnchored`, `anchoredHref`, `jump`; the card tsk-6jz07t0080rk
**Revisit when:** a second view needs places on its page, or fixture mode stops carrying the route in the fragment

`M.route.isAnchored` accepts a route followed by one `#` and an anchor
of a letter and then letters, digits, `.`, `_` or `-`, at most 100
characters; `h()` writes it through `M.route.anchoredHref`, so in
fixture mode it becomes `#/<owner>/<slug>/contract#s-6.8` and
`M.route.current()` gives back the path and that `fragment`. `isRoute`
itself still refuses every `#`, so a sign-in's `next` never carries one.
A click on such a link to the page one is on only scrolls (`jump`) and,
over http(s), names the place in the address with `replaceState`;
nothing is drawn or read again. To another page it is a new history
entry, and that view jumps once its text is drawn.

**Reason:** §6.8 links sections by a fragment, and under the shell's
`<base href="/assets/">` a bare `#anchor` leads into `/assets/` (the
`index.html` entry above), so a place has to be written as its route
plus the anchor. The anchor's characters are the hub's (`s-<number>`,
`h-<n>`), so the check stays narrow.

**Rejected alternative:** a query (`contract?section=6.8`): the
contract names the fragment, and a query is part of the route, so each
jump in the table of contents would be a new address the view draws
again, re-reading a file of up to 4 MiB. Letting `isRoute` take a
fragment: it is also the boundary for a sign-in's `next`, which the
hub's own check refuses with a `#`.
