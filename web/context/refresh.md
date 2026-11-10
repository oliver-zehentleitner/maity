# Refresh

## The dashboard reads the project's events with wait=0 on an interval, not with the long-poll

**Id:** 264c1452-2cc4-4518-b1fb-85e901a09aa2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §8.2 (readable and wake-relevant sets) and §8.3 (one long-poll per session), 2026-10-21
**Revisit when:** the hub offers a cookie session a stream of its readable set, or one long-poll per tab

A project view starts at the head (`GET /projects/{slug}/events?after=latest&wait=0`,
read together with the project and its members, before the view's own
data) and then reads `after=<cursor>&wait=0` every 5 seconds (15 since
6cb02c3d-063d-473b-b86b-8f8324c11f14), page by
page. An event from someone else of a kind the view shows offers a
reload instead of replacing the view; a request event re-reads `/me` at
once; a chat event of the open conversation fetches its new messages.
Presence emits no event, so the Agents view re-reads it every 30 seconds
and updates it in place; the chat's list of conversations re-reads
`/conversations` on every chat event in the feed and, together with
`/members` for presence, every 30 seconds, one read at a time (a refresh
asked for during a read runs once more after it). `/me` is still read every 60 seconds (15 until
2026-10-28, see 6cb02c3d-063d-473b-b86b-8f8324c11f14) for the counts of every project, which no single project's
feed carries. A panel that offers members (the join panel's instances
and the team's limit) reads them again when it opens, and a view that
reads the members again sets the list, the index by id and the names
together (`M.withMembers`): an instance limit raised in the rulebook was
offered only after a reload (the maintainer's report, tsk-pj6n7sxertx5).

**Reason:** `wait=0` returns the readable set, which for an owner or
admin is every event of the project; the long-poll returns the
wake-relevant set only, which leaves out the admin's see-all, so the
owner's board would never hear of a card an agent claimed that was not
addressed to them. A session holds one long-poll, so a second tab, or
the cross-project view next to a project view, would end the first with
`superseded`. The contract offers a cookie session polling "with `wait=0`
every few seconds"; five is the value chosen here.

**Rejected alternative:** one long-poll per cookie session, for its
lower latency and fewer calls — the two gaps above. Polling each
resource of the open view (the chat's messages, the board's tasks) on
its own interval, as before — one call per view and interval instead of
one feed, and nothing for the views that have no cheap "after" query.

## Notification counts ride on the 15-second /me read; browser notifications long-poll their own endpoint, and only after the human turned them on

**Id:** e849f49d-bbdf-462c-972d-a67e7f6740e6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the notifications contract (docs/api.md §18, PR #160) and the coordinator's card for the dashboard's part (tsk-vxz496gfw81s), 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** the hub offers a push channel without an open tab, or personal requests get a view of their own
**See:** refresh.md#the-dashboard-reads-the-projects-events-with-wait0-on-an-interval-not-with-the-long-poll — 264c1452-2cc4-4518-b1fb-85e901a09aa2 — as of 2026-10-22
**See:** https://github.com/oliver-zehentleitner/maity — d2d3356f-7a73-4e77-ac7c-3e04b07c2517 — as of 2026-10-22

The badges and the tab title come from one read of
`GET /me/notifications?limit=0`, made with the existing interval `/me`
read (60 seconds since 6cb02c3d-063d-473b-b86b-8f8324c11f14) and after every answer: the counts and `by_project` for the switcher
and the tabs. The bell reads its latest 20 only when it opens.
An item's link is built from its `target`, never from its `url`. A hub
that answers 404 leaves the page as it was, with no bell. Any other
failure is said in the notice and stops nothing.

The read a page starts when it is drawn does not hold that page up
(tsk-hyfqc0sp2bvc). It runs beside the page's own reads. The page
draws with the counts read so far, or /me's open requests before the
first read. The header (the switcher, Chat, the bell, the tabs, the
title) follows when it answers. Awaiting it with the page's own reads
was the way before: on prod it took about 2 s, and every page waited
that long. The inbox (All projects' and a project's) still reads its
list only after that read answered; its header does not wait. Its
inbox count starts from those counts, and a later difference is a
change. Counts that answer after the list was read would start it at
requests the list does not show, which then are neither drawn nor
offered; counts from an earlier page, or /me's `open_requests`, would
offer a change that is none (§18.2's inbox also counts personal
requests). Where that read fails, the count starts from what was read
before, as it did when every page waited. A failure that comes late is
said in the same notice.

Browser notifications run only when the account wants them and the
browser allows them. They use the long-poll `?after=<position>&wait=55`,
starting from a `limit=0` head read when the loop starts (on, after a
setting changed, after another tab had the slot), so nothing from before
pops up at once, and each answer's `next_after` passed back unchanged as
the next start,
which §18.2 gives a session beside its events long-poll. A `superseded`
answer means another tab took that slot, so this tab waits five
minutes; the item id as tag stops a second display. A quick empty
answer gets a 30-second pause. The browser's permission is asked only
in the change handler of the switch.

**Reason:** a separate interval for counts would be a second clock
beside `/me`, and the inbox already reads `/me` for the same numbers. The
events decision above (`wait=0` instead of the long-poll) holds because
the events long-poll leaves out the admin's see-all. The notifications
long-poll does not have that gap: it carries exactly what notifies this
human, so its lower latency costs nothing. Building links from `target`
keeps the dashboard's routes in the dashboard: a `url` names the hub's
public address, which a page opened elsewhere may not share. Asking the
browser on a click is the only time a browser reliably shows the
prompt, and it is the human's own decision to be asked.

**Rejected alternative:** counting the per-project badges from the
newest 50 items, as this page did against the contract's first round:
the numbers were too low whenever more than 50 were unread, and the hub
now counts per project itself (`by_project`). Reading the bell's items
on every poll: they are shown only when the bell is open. Showing
browser notifications from the 15-second poll: fifteen seconds late,
and every open tab would show them. Asking for permission when the
page loads: browsers block or suppress prompts without a click, and a
prompt nobody asked for is what people learn to deny.

## A sign-in or address alert is never marked read by opening it or by Mark all read

**Id:** 4c95abfb-95af-4c4d-85e0-6fb1cddfd79f
**Type:** decision
**Status:** superseded
**Superseded by:** 643600cd-dd61-4291-85d7-025e322f4c81
**Evidence:** confirmed
**Source:** docs/api.md §2.6.5 and §18.3 (marking a `session_created` item read gives the reported session good standing); the coordinator's ruling on the review of the dashboard's notifications (PR #194), 2026-10-23
**Revisit when:** the hub lets the bell confirm a sign-in itself, or §2.6.5 changes who may mark a security item
**See:** views.md#sessions-say-what-this-session-may-not-do-before-it-is-tried-and-this-was-me-is-the-only-way-a-sign-in-is-confirmed — 561b77f6-2a12-4352-aa50-36a8aa773fbe — as of 2026-10-23
**See:** refresh.md#notification-counts-ride-on-the-15-second-me-read-browser-notifications-long-poll-their-own-endpoint-and-only-after-the-human-turned-them-on — e849f49d-bbdf-462c-972d-a67e7f6740e6 — as of 2026-10-23

In the bell, opening an item marks it read, except an item of kind
`security`: a new sign-in or an address change. It stays unread and
links to the account's sessions, where **This was me** confirms it.
**Mark all read** leaves it too, as the hub does for `up_to`, and is not
offered when such alerts are all that is unread; the panel says where
they are confirmed. Re-checked when the sessions view came (2026-10-23):
the rule stands, the bell only links to it.

**Reason:** marking a sign-in alert read from an allowed session is what
gives the reported session good standing (§2.6.5): it may then end the
human's other sessions and approve address changes. A click to see what
the alert is about is not a confirmation; it would let a session signed
in by someone with access to the human's mail confirm itself through the
human's curiosity.

**Rejected alternative:** marking every opened item read, security ones
included, as the bell did at first: one click on the alert would confirm
the sign-in.


## The restricted-access set's notice is a project's setting, read by a read mark, though its target says `settings`

**Id:** aefe70f5-509b-47ea-9768-02623c68016a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.4 ("When the set changes without the setting": the notice links to the project's restricted-access setting), §18.1 and §19 (the notice goes to the humans in the set); the review of #1448 (2026-11-07), which found that such a member was led to a page without the setting; the hub's notification item for `restricted_changed` (`hub/src/maity_hub/notifications/items.py`, target `{type: "settings", id: "restricted_access"}`); card tsk-g8ts5vxhj1md, 2026-11-06
**Revisit when:** the hub gives the set's notice a target type of its own, or another notice points at a project's setting

The bell treats a target `{type: "settings"}` as one's own notification
settings: it links to `/account/notifications` and never reads as read by
opening or Mark all read, because the hub's `mail_disabled` notice there
is an open matter. The restricted-access set's notice carries the same
type with `id: "restricted_access"`, and is an ordinary notice about a
project: the bell links it to that project's settings and lets a read mark
read it, as any notice. `notify.js` tells the two apart by the id.

The notice also reaches members in the set who may not change the setting
(§19). The project's settings send such a member to `settings/mine`, and
that page shows them the setting to read (`js/app.js`): its mode, that they
are in the set, and the set and the count, which the hub serves to every
member in the set (§6.1 "Reading the setting"). One link then works for both
kinds of reader, and only a human with `project:admin` changes the setting.

**Reason:** read as one's own settings, the set's notice would open the
wrong page and stay unread for 30 days, since no matter of the human's
closes it. The contract says what the notice links to, not which target
type it carries, and the hub already ships that target.

**Rejected alternatives:**
- A target type of its own from the hub (for example `project_settings`):
  cleaner, but a hub change for one notice whose meaning the id already
  carries, and the dashboard would still need this rule until a deploy.
- A link of its own for members who may not administer the project (a
  route only for the read-only setting): a second address for the same
  setting, and the bell would have to know the reader's rights. The
  existing redirect to `settings/mine` already sends exactly those members
  there.


## The bell pins the unread security alerts, and Mark all read takes them only after asking

**Id:** 643600cd-dd61-4291-85d7-025e322f4c81
**Type:** decision
**Status:** superseded
**Superseded by:** 09f74f56-7c6c-4d94-a499-ef804b022f3a
**Evidence:** inferred
**Source:** docs/api.md §2.6.5 ("This was me" its own call), §18.2 (`pinned`), §18.3 (`include_security`, `skipped`) and §18.8 (the dashboard's part), contract PR #1230; the bell card tsk-0kz8v1ff5sgf, 2026-11-03
**Revisit when:** the hub confirms a sign-in by anything but its own call, or `pinned` changes what it holds
**See:** refresh.md#a-sign-in-or-address-alert-is-never-marked-read-by-opening-it-or-by-mark-all-read — 4c95abfb-95af-4c4d-85e0-6fb1cddfd79f — as of 2026-11-03
**See:** views.md#sessions-say-what-this-session-may-not-do-and-a-sign-in-is-confirmed-by-its-own-call — 0d50b2d4-2841-4510-a204-90d3aa574927 — as of 2026-11-03

The bell shows the hub's `pinned` block above the latest items: every unread
security alert, each once, with **This was me** for a sign-in this session may
confirm (`POST /auth/sessions/{id}/confirm`) and **Mark read** for the rest it may
mark. The list below leaves the pinned ids out. Opening a security alert still marks
nothing. **Mark all read** is offered whenever anything is unread; with alerts pinned
it first asks, listing them and saying that reading confirms nothing, and then sends
`include_security: true`. What the hub leaves in `skipped` is named with its reason,
and the panel stays open. A filter button reads the unread ones alone (`unread=true`).

**Reason:** since the confirmation is its own call, reading an alert no longer gives a
session good standing, so the bell may clear security alerts. A sign-in alert is still
the one item that must not be missed, so it stands on top whatever the page, and
clearing it in bulk is a choice the human makes knowingly.

**Revisit triggered (2026-11-04):** contract PR #1331 takes `session_created` out of the bell, so
`pinned` no longer holds sign-ins and the pinned block has no This was me; a sign-in shows in the
"Current sessions" box of the Notifications page instead (docs/api.md §18.8, root
`context/notifications.md`, entry feb34f93-e450-4c29-abc2-b525f20e7bb7). The Mark read and
Mark all read part for `email_address_changed` stays. The dashboard PR of card tsk-0baaez2895sb
resolves this entry.

**Rejected alternatives:** keeping security alerts out of Mark all read, as before: they
could only be cleared one by one, and the bell stayed lit. Marking them without asking:
one click would clear a sign-in alert nobody looked at. Showing pinned alerts in the list
as well: the same alert twice in a panel of twenty.

## The bell pins security alerts but no sign-in; the Notifications page lists the current sessions, read again when sessions_rev moves

**Id:** 09f74f56-7c6c-4d94-a499-ef804b022f3a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.6.5 ("A sign-in is no notification"), §18.2 (`sessions_rev`) and §18.8, contract PR #1331; card tsk-0baaez2895sb, 2026-11-04
**Revisit when:** the hub pins a sign-in again, or `sessions_rev` stops moving on a session record
**See:** refresh.md#the-bell-pins-the-unread-security-alerts-and-mark-all-read-takes-them-only-after-asking — 643600cd-dd61-4291-85d7-025e322f4c81 — as of 2026-11-04
**See:** views.md#sessions-say-what-this-session-may-not-do-and-a-sign-in-is-confirmed-by-its-own-call — 0d50b2d4-2841-4510-a204-90d3aa574927 — as of 2026-11-04

What the earlier entry says about the pinned block and Mark all read stands for the
security alerts the hub still pins: an address change, a second factor, forge access.
Each gets **Mark read** where this session may mark it, and Mark all read asks first and
sends `include_security: true`. A sign-in is in none of it: the pinned block has no
**This was me**, and nothing in the bell links to a session. The Notifications page shows
a small "Current sessions" box instead: the active sessions, newest first, five and a
count of the rest, this session and the unconfirmed ones marked, a link to Profile →
Sessions, no buttons. It reads `GET /auth/sessions` when the page opens and again only
when the `sessions_rev` the bell knows (from a counts answer or the long-poll) differs from
the value it last read with; a failed read is tried again on the bell's next change. The
mail sign-in banner is built again on the same change, at once, not only in the 60-second
counts round.

**Reason:** the contract makes a sign-in no notification, so a pinned sign-in with a
confirm button would show something the hub no longer sends. `sessions_rev` is the one
signal the counts already carry that a session began or ended; reading the session list
on every counts round would cost a request each 60 seconds per tab for an answer that
rarely changes.

**Rejected alternatives:** reading the sessions on every counts round: it works without
`sessions_rev`, at one more request per round per tab. Keeping **This was me** in the
box: the maintainer asked for a small field that shows, not one that acts; confirming
stays in Profile → Sessions and on the banner.

## A device code is followed with wait=0 every 2 seconds on both devices, not with its long-poll

**Id:** e977fe7b-e4f3-4214-a498-8117180a8265
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.6.2 (`GET /auth/device-codes/{id}` and `GET /auth/device-login`, `?wait=0–55`); the dashboard's implementation, 2026-10-25
**Revisit when:** a code's 5 minutes need a quicker answer than 2 seconds, or the hub limits how often these are read

The signed-in device reads `GET /auth/device-codes/{id}?wait=0` and the
new device `GET /auth/device-login?wait=0` every 2 seconds, one read at a
time, on the page's own timers; a countdown by the hub's clock runs
beside them. The reads stop at a terminal state, and the timers end with
the page, the login page's included.

**Reason:** a held request would outlive the page that made it: leaving
Sign in another device, or signing in, would leave a 55-second request
open with nothing to receive it, while the dashboard's timers already
stop on every navigation. Two seconds is within what a human notices
while looking from one device to the other, and a code lives 5 minutes.

**Rejected alternative:** the contract's `wait=55`, for the quickest
answer and fewer reads: it needs cancelling held requests on navigation,
which the dashboard does nowhere else. The 5-second interval of the event
feed: noticeably slow while someone holds a phone waiting.

## Successful replies of an ended session are obsolete too

**Id:** 81f718f0-eab0-4ec1-8a26-80ac142c2e06
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Revisit when:** the client gains a shared request lifecycle or session renewal

Ending the session invalidates its outstanding authenticated replies and
blocks further authenticated calls locally. A successful session check
after sign-in opens the gate again; public sign-in and invitation routes
remain available throughout.

**Reason:** stopping timers and ignoring late 401s does not stop a held
successful list page from asking for its next page after sign-out. The
coordinator confirmed this follow-up after the held-page reproduction.

**Rejected alternative:** relying on timer disposal and the late-401
guard alone: neither prevents a successful old reply from continuing
work, including after another session has signed in.

## A hidden tab reads nothing on its intervals; /me every 60 seconds, events every 15

**Id:** 6cb02c3d-063d-473b-b86b-8f8324c11f14
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the load finding of 2026-10-28 on the card tsk-yek3wssk08dq (three hours at the proxy: `/me` 2657 and `/auth/sessions` 2606 requests, roughly every 4 seconds over the open tabs, on a hub with one vCPU); the dashboard's implementation, 2026-10-28
**Revisit when:** the hub offers the counts as a stream a cookie session can hold, or the counts' latency is reported as too slow
**See:** refresh.md#the-dashboard-reads-the-projects-events-with-wait0-on-an-interval-not-with-the-long-poll — 264c1452-2cc4-4518-b1fb-85e901a09aa2 — as of 2026-10-28

The `/me` round (`/me`, the notification counts and, while the banner
stands or `sessions_rev` moved, the banner's session list) runs every 60 seconds, not
15. A tab whose `document.visibilityState` is `hidden` skips it, along
with the project's events and the chat lists (every 30 seconds, a
project's and `/chats`). The project's events are read every 15 seconds
instead of 5. A tab shown again after a skipped `/me` round or event read
reads it within 5 seconds, once; the events from the cursor. Its chat
lists catch up at the next 30-second round. Actions and events still
re-read `/me` at once. `/chats`, which has no project feed, reads the
notification counts (`/me/notifications?limit=0`, not `/me`) every 15
seconds while it is shown. Those counts bring a reply in the open chat
at once only where they move: a message from someone else to a party or
participant. A group chat read along as an agent's owner moves no count
(§9.3), so while one is open, each counts read refreshes it anyway;
one's own message from another tab moves none either and comes with the
30-second round.

**Reason:** the 15-second round in every open tab was a large share of
the hub's load: each round with an unread sign-in alert also read the
session list. A hidden tab shows nothing that the round would update, so
its reads were pure cost. Since the round runs only in tabs that are
shown, a browser in practice asks once, not once per tab. Sixty seconds
is the bound the finding asked for. The event read with `wait=0` every
5 seconds in each open project page was the largest share. It stays
`wait=0` for the reasons of 264c1452 (a long-poll returns only the
wake-relevant set, one long-poll per session), now every 15 seconds: a
change made by someone else shows up to 15 seconds late, and one's own
changes show at once from the answer. Counts that matter at once (a
request answered, a request event in the open project) are re-read by
the event, not by the interval.

**Rejected alternative:** one read per browser through a
`BroadcastChannel` between tabs. It is more code and a shared state
between tabs, for the case of several tabs shown at once, which the
visibility check does not cover. Re-reading the banner's sessions only
when the count of unread alerts changes: the banner must go when its
session ends elsewhere with the count unchanged, which only a read finds.

## A page switch draws from the session, /me and project it kept, and reads them again behind the view

**Id:** f71932e2-191d-492b-aef9-02a274a8855c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-hn2wa8a7e2eq (measured waterfalls of a page switch) and the owner's choice of what to build from that report, 2026-11-06
**Revisit when:** the hub offers a session, /me and the project in one read, or the dashboard gains a shared request cache
**See:** refresh.md#the-dashboard-reads-the-projects-events-with-wait0-on-an-interval-not-with-the-long-poll — 264c1452-2cc4-4518-b1fb-85e901a09aa2 — as of 2026-11-06
**See:** views.md#the-view-being-left-is-inert-until-the-next-one-is-drawn — 1d888f69-9233-40b4-b9f3-cd679825ef82 — as of 2026-11-06

A change of the address inside the dashboard draws the next view from
`/auth/session`, `/me` and, inside the same project, its project and
members as the last drawing read them, for at most 60 seconds. The
project's event head is read again every time, before the view's data.
Behind the drawn view the same four reads are made again. A change in
who is signed in, the second step, the memberships with their trust and
role, a maintenance window or one's own limit draws the view again from
what was read; a 401 of the session check draws the page afresh. Counts,
members and the project only refresh what is kept for the next switch,
and only the read behind the drawing that stands does, whether it
answers or fails: an older one answering or failing first would leave
the current one nothing to compare. A project entered from outside is
kept as that drawing read it, so the next switch inside it waits for
neither. Any
write of the tab (a POST, PATCH, PUT or DELETE through `M.api`), a
sign-out, an ended session, a refresh and a maintenance change drop what
is kept. While the next view loads, the view being left is also
`aria-busy` and dimmed, and a bar above it, in the page's top padding,
shows the click was taken.

**Reason:** every switch read the session, then /me, then the project's
reads, then the view's data, one after another: four round trips before
anything showed (694 ms for the board at 150 ms latency, more on prod).
Keeping the first three leaves two. That the owner chose this is
confirmed; the 60 seconds, the fields that draw again and dropping on
writes are this implementation's reading of what must stay as fresh as
before, not yet confirmed by review.

**Rejected alternative:** reusing the previous view's event cursor as
well, for one round trip: events between that cursor and the new view's
read would be offered as a reload of what the view already shows.
Redrawing on any difference in /me or the members: the counts and
presence move all the time, so nearly every switch would be drawn twice.
Keeping until the next read without a time limit: a membership changed
by someone else would stand until something else read /me.
