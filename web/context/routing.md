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

## A public project's Overview addresses show its public overview to anyone; its swarm tab stays the members'

**Id:** 66f1d8b8-8308-4dd7-ae48-803a99d8d2bf
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-11-01 (a public project looks to a visitor as to a member, read-only); the lead's approval on the card tsk-n2ymkzczcya5; docs/api.md §16.9, §16.11, §6.20; web/js/visitor.js `canBePublic`, `storedPath`; the visitor cases in web/tools/smoke.js
**Revisit when:** the swarm tab gets a public page of its own, or the badge links elsewhere than `/overview`

`/<owner>/<slug>/overview` and `…/overview/project` are public addresses:
`M.visitor.page` reads the project's own stored page (`kind` `project`)
for them and draws it read-only, for a visitor and for a signed-in
non-member alike, at the address they opened. `…/overview/swarm` has no
stored page: a visitor keeps the login, which goes on there after the
sign-in, and a signed-in non-member is taken to `…/overview` with the
address replaced, so that Back does not return to a dead end. That
happens only once the hub answers the project's page: an earlier
address of a project (a rename, a transfer) has none, so a member who
follows an old swarm link is led on to the current one, the tab kept.

**Reason:** the badge (§6.20) links to `/overview`, and before this the
link ended on the login for a visitor and on `not_member` for a
signed-in non-member, while the project's own address showed the same
overview. The Overview is the member view of exactly that page.

**Rejected alternative:** keeping `/overview` a members' address like
the other dashboard views: the badge link, the one place a stranger is
sent into a project, would end on the login. Mapping the swarm tab to
the overview for a visitor too: the login there is what lets a member
who follows a mail link go on to the swarm after signing in.

## `/` is the hub's start page: a click on a link to it is a page load, never a route change

**Id:** 4f5c757a-98f6-44d1-adad-08fbe61b3d33
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §16.7 (the root shows the landing page to a visitor without a session while it is enabled, the shell otherwise), §16.7.5 (the frame's mark and section links); hub/src/maity_hub/routes/pages.py `root`; web/js/route.js `listen`; web/js/app.js `logout`; the card tsk-fmdn6vb2zs19 (the logo on the sign-in page showed the sign-in form at `/`) and the lead's approval of the plan, 2026-11-04; the review of #1340 (the same form after signing out)
**Revisit when:** the dashboard draws a view of its own at `/`, or the hub stops deciding per request what `/` shows

The click handler of `M.route.listen` leaves every link whose path is
`/` to the browser, with or without a query or a fragment
(`/`, `/?lang=de`, `/?lang=de#s3`): the browser loads the page, and
the hub answers it. Signing out leaves the same way: `logout`
(`web/js/app.js`) ends with `M.route.load`, a page load that replaces
the current entry, unless it has a dashboard path to return to (the
invitation's "Not you?"). `M.route.go("/")` stays a route change where
the session exists: after the sign-in (`renderStep`, and the second
factor's own address once the sign-in is complete) and after a device sign-in (`web/js/device-sign-in.js`), where the hub's
answer to `/` is the shell anyway.

**Reason:** what `/` shows is the hub's decision, taken per request
from the session cookie and `?as=public`: the landing page while it is
enabled, for a visitor without a session or anyone asking `?as=public`,
the shell otherwise, where the dashboard draws the sign-in for a
visitor (a running maintenance window answers with its refusal page in
place of the landing page). The dashboard cannot draw the landing page;
it is the hub's own HTML. A route change to `/` kept the dashboard and
drew its own view for a visitor, which is the sign-in form, while the
address bar named the landing page. The frame's logo, its section
links, the app's own logo signed out and the way out of a sign-out all
led there. Fixture mode has no click handler and no hub, so only a
served page showed it; the e2e step `start_page_step` covers the links
and the sign-out.

**Rejected alternative:** a marker on each link that must be a page
load (`data-…` set by `js/site-chrome.js`): every link to `/` would have
to remember it, and the app's own logo already lacked one. A dashboard
view at `/` that reloads the page: two loads, and the hub's rule
written a second time in the dashboard. `M.route.go` itself loading
every start-page target: a full reload after each sign-in that ends on
`/` (the second factor's step, a device sign-in without another `next`,
a password sign-in with a `next` of `/`, which `render` routes to),
where the hub answers the shell anyway.

## An address that shows nothing says "not found" in words that never tell whether a name exists; the status stays the hub's 200

**Id:** 51873531-fa92-4281-b935-066b6e73944f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-h1e5zmq1wnhj (an unknown address showed the sign-in form) and the lead's approval of the plan, 2026-11-07; docs/api.md §16.11; web/js/not-found.js; web/js/app.js `showsVisitorNothing`; the not-found cases in web/tools/smoke.js
**See:** https://github.com/oliver-zehentleitner/maity — e34ae588-4dbc-423c-8da8-29fc62436cb5 — as of 2026-11-07
**Revisit when:** the hub answers an address that can never be a page with a status of its own, or the dashboard learns, without asking the hub, whether a name exists

Without a session, an address the dashboard has no page for draws
`M.notFound.page`. That covers a handle without a stored public page,
and a project address whose view word is none of `NAV`'s. The page
stands in the frame of the sign-in and reads "This page does not exist,
or it is not public." It links to the sign-in (with `next` back to this
address), the start page and `/explore`. Signed in, `M.notFound.view`
takes the place of "No such view" inside the app. An address under one
of the dashboard's own first words (`/inbox`, `/requests/<id>`,
`/sign-in/code`) and every known project view keep the sign-in, even
where the word names no view: there the sign-in leads on.

**Reason:** the hub answers all of these with the shell, 200 and
`noindex`, so that the answer never tells whether a project or a person
exists (e34ae588). A private profile and a missing one give the
dashboard the same 404 from `/public/pages/…`, so the dashboard cannot
tell them apart either. A page that says only "does not exist" would
claim more than it knows. The sign-in form at a mistyped address read
as if the page were the sign-in. `noindex` already keeps the address out
of search engines, so the card's concern about crawlers needed no new
status.

**Rejected alternatives:**
- A 404 from the hub for names that do not exist: it tells a stranger
  which names exist, against e34ae588.
- A 404 from the hub for addresses that can never be a page (an unknown
  own word, more segments than any route): leaks nothing, but it is a
  contract change to §16.11 and an update of e34ae588. The lead keeps it
  as a separate question for the maintainer, outside this change.
- "Not found" for every address the dashboard does not know, own first
  words included: `/sign-in/code`, `/requests/<id>` from a mail and
  `/inbox` reach `parseRoute` as `unknown`, and a visitor there needs
  the sign-in that leads on (the smoke test's device-code case caught it).

The page's link to `/explore` is a page load, as every link there is
(`M.route.listen`, entry b8377791 below).

## An event's page opens the event where it lives, the place's address with `#seq-<n>`; a 404 says "not visible"

**Id:** 25f39a28-47e6-4562-94bd-414f1da5a14e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-6g2h8dag2fkg (step 3: the link opens the message where it lives, scrolls to it and highlights it, and without access shows "not visible"); docs/api.md §8.9 "The answer" (where an event lives) and "The dashboard's links", §16.11 (`events/<seq>`); the rule that opening a chat costs a known number of requests (tsk-r1adgwp0a5dr); the dashboard's implementation (PR 3 of the card), 2026-11-11; its review (a chat's tombstone without a conversation, an answer after the page was left), 2026-11-11; its second review (a removed project message belonged in Messages per §8.9 then: the listing told it from a chat's tombstone, fmzu 108227, vuur 108230; its audience stays and tells most but not all of them apart, spq4 108278, vuur 108281), 2026-11-11; its third review (the seq compared exactly only up to 2⁵³, a removed message about a card or request opening that, spq4 108392, vuur 108395), 2026-11-11; the owner's decision that a project message about a card opens in Messages at its seq, the card linked beside it (req-cxyyb2w01s8m, option o2, seq 109453, card tsk-hpzs907e3xvx), and the owner's confirmation that a removed message never opens in Messages (req-5zfznap3s3bj, option o1, seq 110013), with §8.9 as changed for both by PR #1644, 2026-11-11
**See:** https://github.com/oliver-zehentleitner/maity — a96ea52b-30a4-4761-84ea-7423f3fca0b6 — as of 2026-11-11
**Revisit when:** the hub serves a chat's messages around a given `seq` (then a chat can open at it in one read), the card panel lists the messages about a card (the owner's decision then may be put to the owner again), a project message can be about something other than a card, or readers report links that stop short of an old message

`/<owner>/<slug>/events/<seq>` (`js/event.js`, no tab) reads
`GET …/events/{seq}` once and replaces the address, with no history
entry of its own, by where the event lives (§8.9), in that order: its chat
(`chat/<conversation_id>`, direct or group) when the hub names a
conversation for this reader, else Messages for a message that is not
removed and whose `payload.type` names a type and not `chat`, one about a
card included (Messages names the card beside it, a link), else its
subject's card (`tasks/<id>`) or request (`inbox/<id>`), else the event's
own page. A removed message never opens in Messages: a removed project
message about a card opens its card (its `subject`, kept through the
redaction, §8.5), one without a card is drawn on the event's page, as
removed. A chat's tombstone that a former participant still reads but can
no longer open in its chat comes, like a removed project message's, with
`conversation_id: null` and a payload without a type; it is placed the
same way, at its subject, else on the page. The page therefore never
needs to tell the two tombstones apart, and every event is placed from
its one read. `#seq-<n>` follows the place's address (a place on the
page, `M.route.seqTarget()`). An event with none of these places is drawn
on the page itself. An answer that arrives after the reader left the page
(another link, back) changes nothing: the view checks after the read,
before it redirects or draws, that it is still the page shown, as the
app's own check of a render comes only after the view returns. The place
marks the message (`.seq-target`) and scrolls to it. A direct or group
chat reads older pages one at a time, as Show earlier does, only while
the message could still be in them, and at most ten (`REVEAL_PAGES`,
`js/chat.js` `reveal`). Messages does the same with its listing's cursor.
Past the bound the place says it did not reach the message, and Show
earlier goes on from there. A card or a request opens as its own link
opens it. The card panel has no list of the messages about a card to mark
one in.

Until 2026-11-11 the order was different twice over. The subject came
before Messages, so a link to a notice about a card opened the card,
whose panel lists no messages: the reader never saw the text clicked,
and the owner chose Messages with the card beside it (req-cxyyb2w01s8m,
o2). And a removed project message belonged in Messages while a chat's
tombstone did not, so for a message with no type, no conversation and no
card or request it is about, the page read the Messages listing once
(`…/messages?after=<seq − 1>&limit=1`, §8.8), which holds the project's
tombstone and never a chat's: listed, it opened in Messages; not listed,
or the read failed, it was drawn on the page. A tombstone with a
conversation or a subject was placed at its chat or its subject without
that read. §8.9 now
keeps every removed message out of Messages (req-5zfznap3s3bj, o1;
context/messages.md, See above), so that read is gone.

A `404` and a path that is no `seq` (`068216`, sent to the hub never)
both show "not visible" in one sentence, the same for an event the
reader may not see and one that does not exist, as the hub's answers are
the same.

**Reason:** the card asks for the message where it lives, and §8.9 says
where that is. Opening it there gives its context (the chat around it,
the card), which a copy on a page of its own would not. Replacing the
address makes back leave the place, not land on a page that only
forwards. Bounding the search keeps a link's cost known, as the rule for
opening a chat does (no request whose cost grows with history). Ten pages
of fifty are the last 500 messages of a chat, which is where a cited
`seq` almost always is. A removed message has no text to show in
Messages, and its tombstone there has no `task_id` (§8.8), so Messages
would show neither the message nor its card; placing a tombstone by its
subject, else on the page, spares the second read that a link to one
with no conversation and no subject cost. One sentence for
404 keeps the page as silent as the route about whether the event
exists.

**Rejected alternative:** reading the chat around the `seq` instead of
from its newest page: the chat's reads mark what they return read, and
`before=` from the target would draw a chat whose newest messages are
missing, a second mode of the chat view for one link. Showing every
event on its own page: it loses the context the card asks for. An
unbounded search: a link to the first message of a long chat would read
the whole history. The subject before Messages, as §8.9 had it until
2026-11-11: a notice about a card opened the card, which shows no message,
and the owner chose Messages with the card beside it (req-cxyyb2w01s8m,
o2). A list of a card's messages in its panel, the cited one marked: a new
part of the card view for one link, not what the owner chose. A removed
project message in Messages, told from a chat's tombstone by one read of
the Messages listing, as the page did until 2026-11-11 for a typeless
message with no conversation and no card or request it is about: a
second read on every link to such a message, for a place that showed no
text and no card; §8.9 dropped that place (req-5zfznap3s3bj, o1).
Reading a missing type as a project message (the Messages listing's own
filter judges only unredacted events, which carry their type): a chat's tombstone without a
conversation went to Messages, which lists no chat message, and the event
the hub had just served ended as "not reached" (review of #1629).
Routing a typeless tombstone by its audience (one token that is not
`member:` or `instance:` sends it to Messages): a member-only project
message cannot be told apart from a chat by audience (spq4 108278, vuur
108281); with no tombstone in Messages the question no longer arises.
Parsing the listing with a BigInt-aware JSON reader for the seq above
2⁵³: the whole app reads seqs as numbers, and Messages could not mark
such a message anyway (spq4 108392).

## `/explore` and `/for/<slug>` are the hub's pages: a click on a link to them is a page load, and they stay routes

**Id:** b8377791-ca86-4ebe-82a3-dbf40b17daa2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-mg681fdn8p6m (header links to `/explore` drew the unknown-address view), found on tsk-h1e5zmq1wnhj, 2026-11-07; docs/api.md §16.11, §16.9, §16.7.2; web/js/route.js `hubDrawn`; the route cases in web/tools/smoke.js and `visitor_step` in web/tools/e2e.py
**See:** routing.md#-is-the-hubs-start-page-a-click-on-a-link-to-it-is-a-page-load-never-a-route-change — 4f5c757a-98f6-44d1-adad-08fbe61b3d33 — as of 2026-11-07
**Revisit when:** the hub draws another page of its own at an address the dashboard also answers, or the dashboard gets a view of its own at `/explore` or `/for/<slug>`

`M.route.listen` leaves a click on `/explore` or `/for/<slug>` to the
browser, with or without a query or a place, as it does for `/`. Both
stay routes (`M.route.isRoute`), and `HUB` stays the hub's own list of
hub paths. The not-found page's own click stop for `/explore` is gone.

**Reason:** the hub answers these addresses itself where it serves them:
the public projects while public pages are on (§16.9), and a landing
variant while the landing page is on and the variant exists (§16.7.2).
It answers the shell otherwise. A route change kept the dashboard, which
knows no view there and drew the unknown-address view, so the frame's
links to `/explore` never reached the hub's page.

**Rejected alternatives:**
- Adding `explore` and `for` to `HUB`, as the card first suggested:
  `HUB` mirrors the hub's `HUB_FIRST` (`hub/src/maity_hub/paths.py`),
  which also decides a sign-in's `next` and which hrefs the views may
  write. Neither page is a hub path in §16.11: both are the shell where
  they are off.
- A click stop on each link to them, as the not-found page had: every
  link would have to carry it, and the frame's header links did not.
