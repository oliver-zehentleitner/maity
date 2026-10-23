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
data) and then reads `after=<cursor>&wait=0` every 5 seconds, page by
page. An event from someone else of a kind the view shows offers a
reload instead of replacing the view; a request event re-reads `/me` at
once; a chat event of the open conversation fetches its new messages.
Presence emits no event, so the Agents view re-reads it every 30 seconds
and updates it in place; the chat's list of conversations re-reads
`/conversations` on every chat event in the feed and, together with
`/members` for presence, every 30 seconds, one read at a time (a refresh
asked for during a read runs once more after it). `/me` is still read every 15 seconds for the
counts of every project, which no single project's feed carries.

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
`GET /me/notifications?limit=0`, made with the existing 15-second `/me`
read and after every answer: the counts, `by_project` for the switcher
and the tabs, and the position the browser's long-poll starts from. The
bell reads its latest 20 only when it opens.
An item's link is built from its `target`, never from its `url`. A hub
that answers 404 leaves the page as it was, with no bell. Any other
failure is said in the notice and stops nothing.

Browser notifications run only when the account wants them and the
browser allows them. They use the long-poll `?after=<position>&wait=55`,
each answer's `next_after` passed back unchanged as the next start,
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
