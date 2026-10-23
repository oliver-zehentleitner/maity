# Ticker

## A ticker item is an event, its dedupe key a row of its own, and it is shaped per reader where every event view is made

**Id:** 746b5971-1a29-458f-90da-a8243a4f2848
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §17 (items, audience, subscriptions, dedupe, listing, shaping per reader); the coordinator's card for the hub side (tsk-0wtpcjkdhgq8) and its agreed split into three pull requests, 2026-10-23; the implementation of the first, 2026-10-23
**Revisit when:** a second read path returns events without `views.event_views`, or a project's ticker grows so long that the listing's `for=me`, `area` and `since` filters and the resume packet's counts, which scan its ticker events, are slow
**See:** events.md#the-long-poll-waits-on-an-asyncio-event-never-on-the-database — 6310ef59-6010-4fa5-95d5-30f20bc00117 — as of 2026-10-23

An item is an event of kind `ticker` (`maity_hub.ticker.write`). Its
audience is computed once, when it is written, and the members' follow
and mute are applied then. Its dedupe key goes into `ticker_dedupe`
under a unique (project, key), checked under the project lock that
`events.emit` takes anyway. The shaping per reader happens in
`views.event_views`, which every read path already goes through:
`detail` added, `reasons` and `audience` reduced for everyone but human
owners and admins. A decision the reader may not read now is dropped in
`events.readable_by`, from a set computed once per batch beside the
humans-only tombstones (`hidden_redactions`); a decision is found by its
subject, which its tombstone keeps, so a redacted one is withheld too.
The tombstone of an item is shaped like the item. Its `event_redacted`
keeps the item's audience (§8.5), is shaped like it, is withheld with a
withheld decision, and never wakes: the long-poll skips a notice whose
subject is a ticker item. Waking for `ticker` goes by the reader's
`reasons` entry, never by `all`; humans get `wake: false` but keep their
`member:` token, which names them for their notifications (§18.1). The read side
lives in `ticker_read`, which imports neither `events` nor `views`, so
both use it without a cycle. The listing and the packet read the same
events through the same functions; their filters work on the stored row
and only a page becomes views, but `for=me`, `area`, `since` and the
packet's counts still scan the project's ticker events. A member's
subscription is read and written under the project lock.

**Reason:** §17.1 makes an item an event and §17.5 requires the same
shaping on every path. Putting it where the event view is built covers
`GET /events`, the long-poll, the resume packet and the listing without a
second implementation that could drift. The dedupe key needs a unique
constraint (§17.7) that a JSON field in the event row cannot carry. The
decision check needs the request as it is now, so it is read per batch,
the way the redaction check already works. The notice keeps §8.5's
audience so that whoever received the item is told it is gone; its `all`
would wake every session, so waking is decided by the subject's kind.

**Rejected alternative:** a table of ticker items beside the event log:
it would hold the same facts twice and need its own read paths for the
shaping. Filtering decisions after reading, in each route: easy to miss on
one path, which would show a decision to a member who may not read its
request. Storing `detail` with the item: §17.5 adds it at read time, so a
renamed request title shows as it is now.
