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
and updates it in place. `/me` is still read every 15 seconds for the
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
