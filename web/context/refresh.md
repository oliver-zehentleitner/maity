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
feed carries.

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
**Status:** active
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

The `/me` round (`/me`, the notification counts and, while a sign-in
alert is unread, the banner's session list) runs every 60 seconds, not
15. A tab whose `document.visibilityState` is `hidden` skips it, along
with the project's events and the chat lists (every 30 seconds, a
project's and `/chats`). The project's events are read every 15 seconds
instead of 5. A tab shown again after a skipped `/me` round or event read
reads it within 5 seconds, once; the events from the cursor. Its chat
lists catch up at the next 30-second round. Actions and events still
re-read `/me` at once. `/chats`, which has no project feed, reads the
notification counts (`/me/notifications?limit=0`, not `/me`) every 15
seconds while it is shown: a reply in the open chat comes in by them.

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
