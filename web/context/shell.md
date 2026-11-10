# Shell

## Several projects: a switcher on every screen, and the cross-project inbox as the landing page

**Id:** b8378331-be5c-4349-96ab-ed44a8563c4e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's multi-project requirement, relayed by the coordinator, 2026-10-21; the dashboard's implementation, 2026-10-21; re-checked when the tabs became the browser's own (card tsk-p6aye59z0k7g), 2026-11-06
**Revisit when:** a human asks to land on one project
**See:** inbox.md#the-inbox-is-the-first-screen-board-agents-organisation-and-chat-follow-in-that-order — a8f4ac34-b7be-47f0-aaec-dc494e6c2080 — as of 2026-10-21
**See:** shell.md#the-project-tabs-are-the-browsers-own-moved-by-dragging-by-altshiftarrow-or-from-the-tabs-menu — cd4fe2ba-aaa7-47fd-aa04-43e97207d5d6 — as of 2026-11-06

One account holds many projects. The header of every screen carries a
project switcher: each project this browser has open as a tab, with its
state and the number of open requests waiting for this human, plus "All
projects" with the total. A switcher row too long is answered by closing
tabs (cd4fe2ba). The
cross-project view (`/all`) is the inbox across every project, each
entry labelled with its project and that project's state, answered in
place. Opening the dashboard without a route lands there when the human
belongs to more than one project, and on that project's inbox when there
is only one. Everything else lives under `/<owner>/<slug>/...`.

**Reason:** the requirement is that the human sees from anywhere that a
project needs them; a count beside every project name does that on every
screen, and a landing page across all projects keeps "the inbox is the
first screen" true when there is more than one inbox.

**Rejected alternative:** landing on the last project used — it needs
remembered state, and it hides what waits elsewhere behind the switcher
on exactly the screen opened first. A project chooser as the landing
page — one click more before the first answer, and it shows counts but
not the requests themselves.

## The project tabs are the browser's own, moved by dragging, by Alt+Shift+Arrow or from the tabs menu

**Id:** cd4fe2ba-aaa7-47fd-aa04-43e97207d5d6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decision of 2026-11-06 on request req-6zp8zjwabmds, relayed on card tsk-p6aye59z0k7g; the dashboard's implementation, 2026-11-06
**Revisit when:** the account keeps the open tabs too, or the tab row gets groups or pinned tabs
**See:** https://github.com/oliver-zehentleitner/maity — 6e21a45a-26a7-46a0-b7c4-f7213718225b — as of 2026-11-06

Which projects the header shows as tabs, and in which order, is kept in
this browser per viewer (`js/tabs.js`); without storage it holds for the
visit. A browser with nothing kept starts from the account's
`start_tabs`, or with every project when that is `null`. A project the
browser has not seen yet opens as the last tab; one opened by its
address gets its tab back. A tab moves by dragging, by Alt+Shift+Arrow
on the focused tab, or by Move this tab left/right in the tabs menu
beside the row, which also opens and closes each project (switches that
keep the menu open) and keeps the current row as the start set. Each
move is announced with the new place. A project's start-set switch also
sits in its own settings (Mine). The cross-project inbox can be filtered
to projects with an open tab; personal requests always stay.

**Reason:** the split between browser and account is the maintainer's
(the contract entry above). The rest is inferred from the dashboard's
existing rules: nothing is drag-only (the board's Move and Place menus),
so a single pointer or a keyboard reaches every move a drag makes; and
a filter that hides personal requests would hide requests with no tab
to open them from.

**Rejected alternatives:** unknown beyond the contract entry's.

## The dashboard asks the hub no capability question; a route it calls that is missing is an error

**Id:** e1699490-402f-45ac-9461-d85189411559
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's alpha rule (no compatibility layers before launch, 2026-10-29); the coordinator's rulings on tsk-wgg2t8ngx9xg (the notifications fallback and the "not on this hub" mechanism removed, `hubHas` and `hubBody` with them, and the field-presence checks in the same PR), 2026-10-30; hub/src/maity_hub/app.py (every router mounted unconditionally); hub/src/maity_hub/views.py and policy.py (the fields every project and member view carries)
**Revisit when:** Maity leaves alpha and a dashboard must run against an older hub (§1.6), or the hub mounts a route only under a setting

The page no longer reads `GET /openapi.json`: there is no `M.api.hubHas`,
`M.api.hubBody`, `M.api.missingRoute`, `M.api.absent` or
`M.dom.notOnHub`. Every control is offered by the page's own rules
(role, trust, project state), and every route it calls is called; a
404 or 405 from one is an error and is said as one. Nor does the page
test whether the hub sends a field it always sends (`"signing" in
policy`, `"logo" in project`, a card's `parent`): only fields the hub
sends to some readers or under a condition are tested, such as a
member's `owner_preferences` or `keep_the_why_unconfirmed`.
The notifications' counts are read like any other call: until they are read the switcher
counts the open requests from `/me`, and a failed read is said.
Settings a hub really may have off stay explicit in its answers, such as
`409 attachments_not_configured` or a sign-in method's `method_disabled`.

**Reason:** the dashboard and the hub ship together from one
repository, and the hub mounts every router without a condition, so a
route "not on this hub" only happens with an older hub, which nobody
runs in the alpha. The machinery cost a request per page, a muted text
per feature and a branch per view, and it hid a broken deploy behind a
quiet line.

**Rejected alternative:** keeping the machine-form checks for the
controls only: the same dead branches in each view, for the same hub
that does not exist. Keeping the quiet line for a 404: a missing route
now means something is broken, and that should read as broken.

## A control for a route a hub may lack is offered only when the hub's machine form lists it; an unreadable one keeps the control

**Id:** 51dab38e-abd9-4848-91ed-a066eea39e9f
**Type:** decision
**Status:** superseded
**Superseded by:** e1699490-402f-45ac-9461-d85189411559
**Evidence:** confirmed
**Source:** the coordinator's web-vs-live audit and its card (tsk-x995qwddkrk2), 2026-10-23: on maity.team "New group chat" and "Attach files" were offered while the hub served neither; the dashboard's implementation, 2026-10-23
**Revisit when:** every hub the dashboard serves has group chats and attachments, or the hub answers a capability list of its own

`M.api.hubHas(method, path)` reads `GET /openapi.json` once per page and
says whether the hub serves a route, the `/api/v1` prefix and the
parameters' names not compared. New group chat, the form at
`/<owner>/<slug>/chat/new`, the blind removal in Project settings and reading
along from outside a project need `POST /projects/{slug}/conversations`;
without it the chat list says "This hub has no group chats yet." instead
of looking empty. Attach files needs `POST /projects/{slug}/attachments`
and is hidden, too, once the hub answered 404 to the pending list. The
Ticker asks the same way. A machine form that cannot be read counts as
"served": the controls stay, and a failure says itself where it happens.

**Reason:** the hub has no capability list, and its machine form is the
one place that says which routes it serves; the routes in question could
not be probed without side effects (a POST would create) or tell apart
(`GET …/conversations` exists on hubs without group chats, and a 404
may be a mistyped project). Offering a control whose every use fails
tells the human nothing until they have typed a message or picked a
file.

**Rejected alternative:** hiding the controls when the machine form
cannot be read: a passing network failure would silently take working
features off the page for the rest of its life. Each view reading
`openapi.json` on its own, as the Ticker did: the same read and the same
two key forms in several places.

## A project's unread mentions are a link beside its tabs, to /notifications filtered to the project

**Id:** 0906c3fe-ffe3-4baf-94c1-c093de6fee54
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-xb7bf1x0h3cy (the owner's report: the Maity pill showed 2, the Inbox and Chat tabs nothing), the plan agreed with the lead on the card, 2026-11-03; docs/api.md §18.2 (`kind`, `project`), §18.3 (`up_to` with `kind` and `project`), §18.8 "Per-project badges"; the maintainer's decision to drop the line on the Chat tab, card tsk-sesdq48m9ewk, 2026-11-10 (chats 102080 and 103539)
**See:** inbox.md#the-inbox-is-the-requests-alone-activity-is-on-the-bell-the-chat-button-and-notifications — 2ff6afe9-ed47-4ffd-b12d-947cfb7774ca — as of 2026-11-03

A project's pill counts its open requests, unread chats and unread mentions (§18.2 `by_project`),
but only Inbox and Chat have a tab count. While the project has unread mentions, a line beside its
tabs ("1 unread mention") links to `/notifications?kind=mention&project=<owner>/<slug>`. That page
reads both filters from its address and asks the hub with them (§18.2). Its heading names them
("Mentions in Maity"), a link leads back to all notifications, and Mark all read sends the same
`kind` and `project` with `up_to` (§18.3), so it marks nothing outside the filter. The line is
filled again with every count read, so it follows the pill.

The line is left out on the Chat tab, on its list and in an open chat: the maintainer asked for it
gone there, since the chat list shows a chat with an unread mention as an @, visible at once
(tsk-sesdq48m9ewk, 2026-11-10, chat 102080). The @ covers chat mentions only: the line also counts
mentions in project messages and on cards (§18.1), which the Chat tab does not show. Asked about
those, the maintainer kept the removal because they stay in the bell and on the line of every other
tab, as on the pill and /notifications (chat 103539).

**Reason:** a count on a project should lead to what it counts in one step, and mentions have no
place in the project: the inbox is the requests alone (see 2ff6afe9). The hub already filters
by kind and project for reading and for marking, so the dashboard needs no new call.

**Rejected alternatives:**
- Leaving mentions out of the pill: §18.8 builds the per-project badge from `by_project`, whose
  total counts them, and the all-projects pill would no longer add up.
- A Mentions tab: the tabs are the project's own views; this one would only lead out to
  `/notifications`.
- The pill leading to the mentions when they are all it counts: the pill always opens the
  project, and a target that changes with the count is surprising.
- The line in the inbox only: it would show on one tab, and the inbox does not redraw when only
  the counts change.

## A route the hub does not serve is said quietly, and the page does not ask it again

**Id:** aa3669b7-71e6-4e87-9376-5759824653d3
**Type:** decision
**Status:** superseded
**Superseded by:** e1699490-402f-45ac-9461-d85189411559
**Evidence:** confirmed
**Source:** the coordinator's card from H's audit of every route the web calls against the hub on main (tsk-yht5tzadgv83, tsk-056gjh5jpfq7), 2026-10-23: 19 of 83 not served, some red, the notifications read every 15 s regardless; the dashboard's implementation, 2026-10-23
**Revisit when:** the hub answers a capability list, or every route the web calls is served on every supported hub

A 404 or 405 means "not on this hub" only when the hub's machine form
does not list that method for that path (`M.api.missingRoute`); a 404 on
a listed route is the resource's (a project left, a card gone) and stays
an error, as does one while the machine form cannot be read. A view that
needs a missing route shows a muted line in its place (`M.dom.notOnHub`)
and notes the route (`M.api.absent`, method and path without the query,
until the next navigation, so a deploy meanwhile is found): the notifications' count read on the `/me` round, the browser
notifications' long-poll, the overview's re-reads and the sessions list
ask no more. A 5xx, a network failure, 401 or 403 is still shown as an
error.

**Reason:** an older hub without a feature is the normal case while the
hub grows, not a failure of the reader's; a red line for it reads as
something broken, and a timer that keeps asking costs a request every
15 seconds for nothing.

**Rejected alternative:** a check of the machine form before every call,
as for the controls (views.md: controls only for routes the hub lists):
the answer of the call itself already says it, and these reads happen
whether or not a control is drawn. Caching every 404 by its full path: a
card or a request that is gone answers 404 too, and must not be taken for
a missing feature.

## At phone width the header's text beside the logo is hidden from sight, not from screen readers

**Id:** d88c7687-5b55-45c7-92e8-6689e2181e06
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's instruction of 2026-10-25, from a phone screenshot of the cross-project inbox; the dashboard's implementation, 2026-10-25; the project's mark added after his phone screenshots of 2026-10-28 (inside a project the buttons wrapped to a second row)
**Revisit when:** the switcher stops naming the current scope, or the header gets a second line on phones

Below 600 px the span beside the logo (the project's name, "Everything
waiting for you", "Your account", …) is clipped to one pixel by CSS,
the usual visually hidden pattern; on wider screens it stays as it was.
The project's mark beside it is not shown there either (`display:
none`): it is decoration, already hidden from screen readers. The
buttons beside the logo are spaced tighter there (gaps, inner padding,
the counts' padding; the same height), so that with their counts they
stay in the logo's row at 360 px. Only two counts of three characters
("99+") at 360 px still wrap, into the two rows it had before.

**Reason:** on a phone the text crowded the menus, and the switcher's
current tab already names the scope. Inside a project the mark and the
buttons' spacing pushed the buttons into a second row, which moved the
whole page down; the tab shows the same mark. Clipped rather than removed, a
screen reader still reads where the page is.

**Rejected alternative:** `display: none`: it takes the name from
screen readers too, and the page title alone is read only on load.
Shortening the text: the project names are the operators', of any
length.

## The header gets a "+" menu to bring someone in; invitations get their own page; Runners lose their tab

**Id:** 3f6eadd3-d1d5-4389-bb65-626e9cdbc1dc
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's card tsk-05meme59sq1x, 2026-10-31 (bell between the gear and the profile, a bold "+" right of the Lead button with Agent and User, `/invite` for invitations, Invite user and Join agent on Members, the old invitation form on Members gone) and his word the same day to take the Runners tab out of the project tabs, linked from Project settings instead; docs/api.md §16.11 (`/invite`, contract #919); the dashboard's implementation, 2026-10-31
**Revisit when:** the agents page gets its join at the top (the same card's next part), a project gets more ways to bring someone in, or an endpoint gives the invitations of all one's projects at once (then `/invite` no longer reads them one project at a time)
**See:** shell.md#the-row-of-tabs-has-no-new-project-tab-the-tabs-menu-follows-the-tabs-a-dragged-tabs-place-is-a-line — 4ff40142-df78-4c11-8f0c-c0024adecd79 — as of 2026-11-09

The signed-in header reads Lead, Chat (the maintainer's order, tsk-td5c6z21xg5s, 2026-11-01), "+", the gear, the bell, the
profile. "+" is a menu like the gear's with Agent (the agents page) and
User (`/invite`), for humans only; Runner and Project were added later
(4ff40142). `/invite` lists the projects where the
human adds members. The one chosen (`?project=`, as Members' Invite user
links it) shows the invitation form and its list. The other projects
show their lists without a form. Members has two blue buttons at the top,
Invite user and Join agent; its own invitation form is gone. The project
view `runners` keeps its route and its Settings tab mark, but has no tab:
the project's Settings links it. `/invite` reads the projects one after
the other and draws again when another project is chosen. A counter
drops an older pass still reading, as `renderSeq` does in the router;
without it, two passes append their lists twice.

**Reason:** the layout is the maintainer's (confirmed); why is read
from the card, not stated by him: bringing someone in is one act whether
it is an agent or a person, so it gets one place in the header, and an
owner of several projects finds all their invitations on one page. Why
the Runners tab goes was not given (unknown).

**Rejected alternative:** the header first and `/invite` in a later
pull request, which would have shipped a User item leading to no page.
Reading all projects at once with `Promise.all` and no counter: a choice
made mid-read would still append twice.

## The header with the lockup is in the page itself; loading and failure stand centred under it

**Id:** d48f94c1-fbdf-4f81-b16d-896fe74535ce
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's feedback relayed by the coordinator (tsk-vb0dgwhrkvsn), 2026-10-27: on a phone, while the app loads or cannot load, the page was a blank strip with "Loading…" top-left; wanted the header with the logo at once and kept on failure, the loader centred, the same for the failure, static so it shows before JavaScript runs; the designer's pass on #433, 2026-10-27 (no red alarm box: a calm block, plain words, the reason folded, Try again primary at the edge; the loader after 300 ms); the dashboard's implementation, 2026-10-27
**Revisit when:** the header's first row changes, or the page gets a shell that renders on the server

`web/index.html` holds the header's first row as `brandTitle()` draws
it (the lockup, one file per theme), so it is on screen before any
script or hub call; every view redraws the header as before. The loader
(`p.page-loading`, 48 px with "Loading Maity…" under it, shown after
300 ms so a fast load never flashes it) and a page that could not load
(`div.page-failed`: the mark at 50 %, a title in plain words, what to
do, the reason under Details, a primary **Try again** that shows the
loader and loads again, and **Sign in again** on a 401) are centred in
what the header leaves of the screen: `body:has(> main >
…)` becomes a column of the screen's height and `main` takes the rest.
A browser without `:has` shows them at the top, as before.

Since 2026-10-30 the lockup is a link home (the maintainer's wish, the
card tsk-vqn9m1qt4rtt): signed in to everything waiting (`/all`),
without a session to the instance's start page (`/`), the static
header's link `/` as no session is known yet. The link carries the
accessible name ("Maity: everything waiting for you", "Maity: home");
the two pictures have empty `alt`, since only one of them shows and the
name would otherwise be read twice or be the bare word.

**Reason:** the first thing a person sees should say where they are, and
a failure should not look like a broken page; plain HTML and CSS show
before the scripts load, which on a slow phone is the longest wait. A
selector on what `main` holds needs no class to set and none to forget
to remove when the first view arrives.

**Rejected alternative:** drawing the header from JavaScript first: it
waits for every deferred script. A class on `main` that the router
removes: one more step every path to a view must remember. The error box
as the failure: red in an empty screen reads as a crash, and a file path
as its title is the system talking to itself.

## On a phone the project's links are one row that scrolls; the state stands beside it

**Id:** df210b31-e55a-47c9-93da-2d139e9ded89
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's card tsk-m9ew7v609fq0, 2026-11-03 (on a phone the project's links wrapped into two rows; one row that scrolls sideways, the state always in sight); review on #1271 (with Review, Released and an absence the first version squeezed the row to 0 px and scrolled the page sideways)
**Revisit when:** a project gets so many state parts that they leave no usable row beside them on a phone, or the header gives the links a row of their own
**See:** settings.md#a-projects-own-links-stand-beside-the-repository-which-reads-repository-whatever-the-forge-the-form-sends-only-what-changed — 10a77061-c980-4990-b44b-cb7f518cd4eb — as of 2026-11-03

At phone width (≤ 600 px) the repository, Pull Requests, the project's own links and Why are one
row of their own (`.project-links`) that scrolls sideways, with the fade cue of the tab rows.
The state, the released mark and the absence stand beside it, outside the row, so a scroll
never moves them away. The row keeps about one link's width (9rem); the state parts that do not
fit beside it wrap under it.

**Reason:** two rows of links took the room above the tabs, and the state is the part the
maintainer asked to keep in sight. A row allowed to shrink to nothing hid the links and pushed
the page sideways once an absence stood beside the state.

**Rejected alternative:** the links wrapping as before (two rows or more on a phone), which the
card asked to end. The state parts never wrapping: with an absence they need more than a phone's
width.

## The dashboard keys a project by its full name, everywhere

**Id:** 242091d4-23c3-446e-ae63-6bb67057640e
**Type:** decision
**Status:** needs-review
**Evidence:** confirmed
**Source:** docs/api.md §6.25 (projects in their owner's namespace; a client keeps `full_name` or the pair, never the slug alone), the card tsk-dbbcw9ccabfk and the hub's PR #483, 2026-10-27
**Revisit when:** organisations become namespace owners, or the hub serves the one-segment routes again

A project's address in the dashboard is `/<owner>/<slug>/…` (§16.11), and every
key the dashboard keeps for a project is its `full_name`: the API base,
the switcher, the inbox's grouping and filter, the counts, the global
chat, the read-along page, the lead button, the runners' configuration.
A full name that is no project of one's own is asked of the hub once,
which answers an alias with the current name. The address before
namespaces (`/p/<slug>`, rewritten through `legacy_slug`) is gone since
2026-10-29 with the other old addresses (§16.11): no redirect. The fixture
hub maps a full name to its fixture directory and refuses an old path
with 410, as the hub does.

**Reason:** a slug is unique only within its owner's namespace; a key or
a link built from the slug alone could reach another owner's project of
the same slug, and an old link could lead somewhere new.

**Rejected alternative:** changing only the API paths and keeping the
slug as the dashboard's key: two projects named `shop` would share
counts, drafts and links. Rewriting the old `/p/<slug>` by the current
slug: §6.25 forbade it, since another project may carry that slug by now.

## The project banner is shown at 2:1, the shape of a forge's social preview

**Id:** c2e9d1e8-f7b5-46fd-8c93-9ea04ff52042
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish on the card tsk-4jhn5xeypjjb (the banner had the wrong height; GitHub asks for at least 640×320, ideally 1280×640) and his follow-up (never crop: the Keep the Why banner's text was cut); the coordinator's cap at 960 pixels, 2026-10-28
**Revisit when:** the 960-pixel cap is too small or too large for the inbox below, or a forge's preview has another shape

The banner on the project's inbox, and its preview in Project settings,
are as wide as their column, at most 960 pixels (the banner centred),
and half as high (`aspect-ratio: 2 / 1`).
The image is never cropped (`object-fit: contain`): one of another shape
is shown whole, with margins in the surface colour. There is no fixed
height; the cap keeps the inbox below in sight on a wide screen, where
the full width made the banner the whole first screenful.

**Reason:** a project's banner is mostly the repository's social preview,
which GitHub defines at 2:1. The same shape shows it whole at every
width. A preview often carries text, such as the Keep the Why banner, and
cropping makes that unreadable, so margins are preferred.

**Rejected alternative:** the fixed 180-pixel strip it had: at desktop
width it cut a 2:1 preview to about 6.5:1, showing only a stripe of it.
Filling the 2:1 box by cropping (`object-fit: cover`): a banner of
another shape lost the text at its edges.

## The view being left is inert until the next one is drawn

**Id:** 1d888f69-9233-40b4-b9f3-cd679825ef82
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the runner flake of web-e2e (tsk-q1xrpaahtah0, runs 40718638353 and 40721945466) and the reviewer's reproduction with ordinary clicks and Back on PR #551, 2026-10-28
**Revisit when:** views are mounted before their data is read, or a view is kept across navigations

A navigation renders the next view off screen and mounts it when its
data is read; until then the view being left stays shown. From the start
of the render it is `inert`: no click, key or focus reaches it.

**Reason:** an action in the old view (a Revoke) was answered into that
view, which then disappeared, while the new view showed what it had read
before the action, as if nothing had happened. The page alone was wrong,
the hub had revoked. Inert keeps the old view as a visual placeholder
without letting it start anything.

**Rejected alternative:** waiting in the end-to-end test only: it hid a
real case (a click during a slow navigation). Clearing the old view at
once: a blank page on every navigation, and a jump. Making every view's
initial read consistent with actions in other instances: one rule per
view, for a race the inert placeholder removes for all of them.

## The project's repository and Keep the Why dashboard are links beside its state, from what the project view already holds

**Id:** bdb4632c-1047-4a88-9249-f09f8c50d1e8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request on the card tsk-n161gf6h8feb (two buttons top right beside the state, the repository with its forge's icon, the Keep the Why dashboard, both in a new tab), 2026-10-29; the coordinator's note that the project view already carries `repository` and `keep_the_why_export.members[]` with the root at `path: ""` and its `dashboard_url`, so no contract change, 2026-10-30
**Revisit when:** a project needs a dashboard address other than its export's, or the hub derives more forges

In a project the header shows, after the state, the absence and the
released mark, a link to the repository (`repository.url`, labelled by
`repository.forge`: GitHub and GitLab with their marks, Gitea by its
name with a branch mark, any other as "Repository" with a branch mark) and **Why**, the dashboard of the Keep
the Why family's root member. Either is left out where the project has
none or its address is not plain `https`; both open in a tab of their
own and are named for a screen reader with where they go.

**Reason:** these are the two places one leaves the dashboard for most
often; the data is in the project view already, so the links cost no
request and no new setting.

**Rejected alternative:** a new project field for the dashboard's
address, as the card first proposed: the export already names it, and a
second address could drift from the one the family publishes. Only the
Overview's Project panel, where both links already are: one click
further, on one view only.

## The row of tabs has no New project tab; the tabs menu follows the tabs, a dragged tab's place is a line

**Id:** 4ff40142-df78-4c11-8f0c-c0024adecd79
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-hp9gq9rmrdq2 (the owner, 2026-11-08: no "+ New project" tab, the "…" menu right at the end of the tabs); his word the same day, relayed by lotse#wtwy (seq 94519), that dragging works and he wants to see where a dragged tab lands, a line before or after the tab under it, by the drop's own half, the keyboard move unchanged; card tsk-45fhe2yrwzb7 (the owner, 2026-11-09: the "+" menu gets Runner, in the order Agents, People, Runner, Projects); card tsk-2a56j80p3p9h (the owner, 2026-11-09: on a phone the "…" stays at the right end of the tabs' row, never on a line of its own)
**Revisit when:** the row of tabs gets groups or pinned tabs, the "+" menu gets more than four items, or a drop learns a right-to-left order
**See:** shell.md#the-project-tabs-are-the-browsers-own-moved-by-dragging-by-altshiftarrow-or-from-the-tabs-menu — cd4fe2ba-aaa7-47fd-aa04-43e97207d5d6 — as of 2026-11-08

The row of project tabs ends with the last tab; the tabs menu ("…") stands right after it. The tabs take their own width (`flex: 0 1 auto`), and a project's state keeps the far end of the row (`margin-inline-start: auto`). On a phone (600 px) the row wraps by the tabs' full width, which put the menu on a line of its own; there the tabs fill the room the menu leaves (`flex: 1 1 0`) and scroll, the menu keeps the row's right end, and the project's state takes the next row. New project is in the header's "+" menu, its last item since 2026-11-09 (Agent, User, Runner, then Project; Runner leads to `/runners` and its pairing form, tsk-45fhe2yrwzb7), which is named "Add an agent, a person, a runner or a project". The empty state's Create a project stays.

While a tab is dragged, a 3 px upright line in the accent colour stands in the gap beside the tab under the pointer: before it when the pointer is on its first half, after it on its second. The drop puts the tab exactly there; both read the same half (`dragTab.pastMiddle`). Only one tab carries the line at a time, never the dragged tab itself. The line goes on `dragleave`, on the drop and on `dragend`, wherever the drag ends. It is a `::before` or `::after` of the tab, placed absolutely 5 px outside it, so nothing in the row moves; the row keeps 6 px after its last tab, so the line after that tab is not cut off.

**Reason:** the owner's layout. A tab for one action among the projects read as one more project and kept the menu far from the tabs it manages. A line drawn by the drop's own rule is the place the drop takes, so what the eye sees is what happens. A border or a margin would shift the tabs under the pointer and so change the half it is on.

**Rejected alternatives:**
- New project as an item of the tabs menu: that menu is about the tabs, not about creating.
- The line as an element between two tabs: it would widen the row while dragging and move the tab under the pointer.
- An inset `box-shadow` on the tab: on the round tab it follows the curve and reads as a second border, not as a place between two tabs.

## All projects has two pages, Inbox and Chats, as a project has its views

**Id:** c72e8c45-838f-4304-bf9f-9e1d3a7693a7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-gw59z3w3fenf (the maintainer, 2026-10-31: the existing chats page as a second page under All projects, beside the Inbox, with unread counts); the row of pages is the implementer's
**Revisit when:** All projects gets a third page, or the Chat button and the Chats page part ways

Under the header, where a project shows its views, All projects shows
its two pages: **Inbox** (`/all`, the requests across projects) and
**Chats** (`/chats`, every chat across them), each with the hub's
count for it (`counts.inbox`, `counts.chat`, §18.2), refreshed with
the other counts. On either page **All projects** stays current in the
project row and the header names it as on the Inbox; the Chat button
leads to the same page. A chat notification already leads into its
chat. Rejected: Chats as a scope of its own outside All projects, as it
was: the reader found the chats only through the Chat button, not
where the requests across projects are. A tab inside the inbox view:
the inbox and the chat list are views of their own, and a page address
for each keeps the back button and links working.

## Jour fixe and Why across projects: one read per project

**Id:** c095fb26-7aa5-4529-a42a-08896de2d032
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's cards tsk-qnsmjbpdkm1t and tsk-jpe6vzyq39mg, which name reading per project as the way without a read across projects and forbid widening who sees what; the coordinator's agreement, 2026-11-01; docs/api.md §11.3, §20.9
**Revisit when:** the hub gets a read across projects for either, a reader's projects make the reads slow, or the contract lists rounds for an agent's owner outside the project

`/all/jour-fixe` and `/all/why` read `GET …/jour-fixe` and
`GET …/keep-the-why` once for each project in the reader's list. Each
section fills when its own answer comes, and a failure stays in its section.
The Why page never sends `max_age=0`: it takes the hub's cache. Both paths
are under `/all`, a word already reserved (§16.11).

**Reason:** the hub filters each answer by that project's rules, so nothing
becomes visible that the project page does not show. Two limits are known:
N requests per view, and an owner outside a project whose agent takes part in
a round (§20.7) sees that round nowhere here, since no listing is open to them.

A series without a topic, an owner's series an admin may not read (§20.1), is
"A private series." here, never its ID. The project page also names the owner;
this page reads no member list, so `handle` would print the raw member ID.

**Rejected alternatives:**
- Falling back to the series ID, or naming the owner by that raw member ID: an
  ID is no name.
- A new `GET /me/jour-fixe` or a read across projects for Why: a contract
  change the current number of projects does not need.
- First-level `/jour-fixe` and `/why`: each would reserve another word that
  handles may no longer take.
- Waiting for every project before drawing: the slowest export would hold up
  the page.


## The frame's stylesheets are switched on only where the sign-in or registration stands signed out, its header and footer beside the app's

**Id:** e9ddc07e-71c0-47c7-bd12-6a7e4d2c35f0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-74rvy49kbv6s and the designer's approved draft (`public-pages.css`, 2026-11-02); the agreement with the hub's side that the dashboard links the hub's two stylesheets rather than copying them (2026-11-02); `web/js/site-chrome.js`, 2026-11-03; lotse#wtwy's decision on #1287 (message seq 65368, 2026-11-03)
**See:** https://github.com/oliver-zehentleitner/maity — 41837936-d085-4592-88d7-b1708a8b4b3a — as of 2026-11-03
**Revisit when:** `landing.css` scopes its rules to the frame, or the dashboard gets a second page in the frame (the form pages of mail links)

Signed out, the sign-in and `/register` draw their form into gj6k's door layout, then ask
`GET /site/chrome` with the address's `?lang=` (or the last one this page saw, `M.i18n.frameAddress`),
and take the frame's language from its answer. While the page stands, the hub's
`/assets/landing/landing.css` and `public-pages.css` are linked (without `?v`, so the hub answers
the current file with an ETag), and `html` carries `public-frame`. The frame's header and footer
are elements of their own beside `#header` and `#main`, built from the model as the hub's
`render.py` builds them; the app's bar is hidden meanwhile and comes back where the read fails.
The sign-in stands in the frame wherever it is drawn without a session: `/login`, the root after a
sign-out, an address of the app opened without a session and without a stored public page, and
the sign-in drawn when a session ends. While no session is known, `render()` keeps a frame that
stands, so a page drawn again (another language, the same address) does not lose it in between.
Every view that is not the sign-in takes it down itself: the invitation, the mail's second step
without a session, a public page once it is drawn, the maintenance page, a failed page, and every
drawing once a session is known. The scope is confirmed: lotse#wtwy decided it on 2026-11-03 (on
#1287, after the review found the frame at those addresses). It was chosen over drawing the
frame at `/login` and `/register` alone; why it lost is inferred, not stated: that choice would show
the same form in two designs depending on the address.

**Reason:** `landing.css` sets `:root`'s tokens, `body`, headings and links for the whole
document, so it may not stay on under the app. Once a session is known, `render()` takes the
frame down in one place before any view draws; without one, it stays standing while the view is
decided, and each view that is not the sign-in or registration leaves it itself. The app's `#header` rules (sticky, its own
background and padding) would beat `.site-header` by specificity, so the frame does not reuse
that element.

**Rejected alternatives:** copying the landing's rules into `app.css`, scoped to the frame: a
second copy of the design that drifts from the hub's, which the agreement ruled out. Drawing the
frame's header into `#header`: the specificity fight above, and an override per rule. Watching
`#main` with a MutationObserver and leaving the frame when its page is gone: it needs no rule in
`render()`, but the smoke test's DOM has no observer, so it would ship untested. Waiting with the
form until the frame is read: sign-in may never depend on that call (§16.7.4).

The frame's footer stands in place of the dashboard's product line (§16.13). `render()` hands
its wish to `M.siteChrome.line()`. A drawing without a known session holds the line back, and so does every read `enter()` starts, also one a page starts without `render()` (the
login's language picker), until that read decides. The line stays away while a frame stands. It comes back only
where the frame is left (`leave()`) or not drawn (a failed read, a model without header or
footer, which both run `drop()`). The choice itself is confirmed: the maintainer's decision
req-5k1gvfsmcg9k (2026-11-03), against keeping the product line under the landing footer. His
reason is not recorded. Inferred: two footers on one page would both name the product.
**Rejected:** showing the line in `render()` and hiding it in `enter()` once the read answers. That
showed it under the landing footer for one round trip on every drawing in the frame, and under the
form on the way in (#1287 review, `b5142212`). Also rejected: a route check in `product-line.js`,
which does not know whether the frame stands or its read failed.
**Known gap:** `M.api.get` has no timeout. A `GET /site/chrome` that never answers leaves the
page without the frame and without the line, as §16.13 says for a read that waits. A timeout was
not added: it would put a second clock beside the API's own error handling, and a hub that does
not answer leaves the sign-in itself unusable anyway (review of #1287 by
maity-review-team-grok#dzse).
**Known gap:** a session that ended on the hub without the page being told (signed out in
another tab, expired) stays in `M.api.session()`. A 401 on `GET /auth/session` is a public call
and does not clear it (`js/api.js`; only `endSession` does), so `render()` takes the frame down
and lets the product line go on each such drawing: the app's bar and the line show for one round
trip of `/auth/session` before the sign-in enters the frame again. The stale session itself is
older than #1287 (`js/api.js` answered that 401 the same way before it); the flash is #1287's,
since only #1287 leaves the frame and holds the line by the session. Found in the review of #1287
by maity-review-team-grok#spq4. Recording it rather
than clearing the session on that 401 here was lotse#wtwy's decision (message seq 66307,
2026-11-04); the reason is inferred, not stated: the case is rare, the page recovers after one
round trip, and a change to the session's lifetime belongs in a change of its own. Workaround:
reload the page, or sign out and in again.

The frame's mark (`home()` in `js/site-chrome.js`) is the hub's SVG without its style attributes;
it keeps the class `mark`, and its colours come from `public-pages.css` (`.site-header .mark
rect`, …), because the dashboard's policy is `default-src 'self'` with no inline style. **Rejected:** the
style attributes as the hub inlines them (web-e2e failed on them at `cc402ec1`), classes in
`app.css` (a second copy of the hub's design, reverted in `7b63d015`), and an `<img>` (it cannot
take the header's theme tokens). Source: the author's notes on #1287, round 2 (card
tsk-gsk31zvpfv02).

The footer's languages (`language()`) are this page's own path and query with `lang` set,
written through `M.route.href`, and a click chooses the language (as the page's picker does) and
draws the page again at that address. **Rejected:** a bare `?lang=`, which under the shell's
`<base href="/assets/">` resolves to `/assets/` (a 404) and loses a sign-in's `next`; a page load
to `/?lang=`, which leaves the sign-in. Source: the same notes on #1287.

Under 960 px, a pitch panel that has none of the pitch's parts (subline, points, note) is hidden
(`hub/src/maity_hub/landing_assets/public-pages.css`, the narrow-screen rule), so a phone gets no
empty dark band. Every key of §16.7.4 is optional, so a panel with only a note or only points
stays. The title is the form's heading, not a part of the panel. A new part that `pitch()` draws
must be added to that rule. **Rejected:** hiding on subline and points only (it hid a note-only
pitch, the ChatGPT reviewer's P2 on #1287); a class set by the script (a second source of truth);
keeping the empty band. **Known gap:** the smoke case renders only a note-only panel, so dropping
one of the rule's `:has()` parts, or a new part not named in it, stays green. Source: the author's
notes on #1287, round 3 (card tsk-gsk31zvpfv02).

## The boot reads the window and the session together; /me still after the session

**Id:** 63c48583-5f47-4beb-93be-d4426d45f57b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-y8gkq1kvt63c (item 4 of the plan on tsk-fxjtwmkc4md5); lotse's choice of option 2 (message seq 94765, 2026-11-08) after the full e2e found the early /me failing by design; web/js/app.js `render` (`early`); the boot case in web/tools/smoke.js
**Revisit when:** the hub answers /auth/session and /me in one read, or a session that owes the second factor may read /me

`render()` starts `GET /auth/session` together with the window's read (`M.maintenance.fresh()`)
instead of after it, and handles the answers in the old order: the window first, then the session.
`GET /me` still waits for the session's answer. The invitation and registration pages read the
session themselves, so the drawing starts no early read for them, and only the newest session read
sets the language: an older answer, a 401 above all, that came back after it switched a newer
session's language back (review of #1524).

**Reason:** two round trips in a row before the session was known. The answers stay in their order
because each one decides whether the next matters (a running window, no session, a session that
owes the second factor). The window is cached for a minute, so later drawings mostly save nothing;
the first load saves one round trip.

**Rejected alternatives:** /me early as well (the card's first plan), gated by the hub's readable
session cookie and quiet towards the page. It fails by design for a session that still owes the
second factor (403) and for a cookie that outlived its session (401), which e2e's check for failed
answers reported; allowing those would have meant a harness exception that could hide a real
failing /me. Without the cookie gate it was worse: a visitor's 401 drew "your session has ended",
and an enrolment 403 redrew the setup in an endless loop. Asking /me with a fetch of its own,
outside `M.api`: a second client with its own error handling.

## A handle field's hint is a sentence of fixed words, with no handle or address filled in

**Id:** e9c2136d-efa9-4222-b013-6042a56ec86c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-srzrkf2parzt (the owner's decision req-3wdzdcvcbf7s: every field that asks for a handle explains the word); the ChatGPT reviewer's P2 in the review of #1488 (seq 91149) and the Grok reviewer's P3 (seq 91705); web/js/handles.js `explain`; e2e `handle_hints_step`
**Revisit when:** a hint has to name the reader's own handle or address, or the phone widths the e2e step measures change

Under every field that asks for a handle, `M.handles.explain(kind, input)`
adds one sentence of fixed words for its kind (your own, an agent's, an
organisation's, the person invited), which the field names in its
`aria-describedby`. Nothing is filled in: no handle, no host, no example
address. e2e `handle_hints_step` measures all seven kinds of field at 390
and 360 px, light and dark: at most two lines, no overflow.

**Reason:** the first version filled in the instance's host and the
reader's handle as an example (`maity.team/<handle>`). On the English
Account page that took three lines at 360 px, and a 31-character handle
three lines at 390 px, against the card's two lines on a phone. Fixed
words keep every hint's length known whatever the handle or the host.

**Rejected alternatives:** a filled-in example cut to a length, which
still varies with the host and reads oddly when cut; a filled-in example
only on wide screens, which gives two texts to keep true. The example
`agent-e` or `oz-team` as a fixed word was dropped too: it read as a fact
about the reader's own agent or organisation.
