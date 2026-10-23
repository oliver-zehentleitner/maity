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

## Merges are read by the probe from the moment the ticker is switched on, and contract sections come from the diff against the file at the merge

**Id:** 66053e8f-9e9b-447b-896d-be37f8007724
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §17.3 (contract sections, linked cards, the 300-file cap) and §17.4 (the probe, every 2 minutes, nothing older than the switch); the agreed second part of the hub card (tsk-0wtpcjkdhgq8), 2026-10-23; the implementation, 2026-10-23
**Revisit when:** the webhook (part 3) makes the probe look sooner, or a forge other than GitHub is observed
**See:** ticker.md#a-ticker-item-is-an-event-its-dedupe-key-a-row-of-its-own-and-it-is-shaped-per-reader-where-every-event-view-is-made — 746b5971-1a29-458f-90da-a8243a4f2848 — as of 2026-10-23

`ticker_source.merges_since` holds the moment `settings.ticker.enabled`
was switched on. The probe worker runs a merge round every 2 minutes,
beside its 5-minute sweep: for each project with a source row and an
observable repository, it reads the pull requests closed against the
default branch, keeps those merged after `merges_since` that have no
`merge:<n>` key yet, reads each one's files (at most 300), and for a
contract file among them that file at the merge commit and at the base.
The sections come from the unified diff: added lines are looked up in the
file at the merge commit, deleted lines in the file at the base. Each
item is written in a short transaction of its own, under the project
lock, after the ticker is checked again. Without a patch, or for a file
over 1 MiB, the sections are unknown and every implementer applies.

**Reason:** §17.4 announces nothing older than the switch, so the moment
has to be stored; the dedupe key alone would announce the whole history
the first time. Reading the forge with no connection held is the probe's
rule (§11). The diff names exactly the changed lines, and the two files
give the heading above each of them, as §17.3 defines a section. A
separate cadence keeps the reports' and releases' sweep at its interval.

**Rejected alternative:** a cursor of the last announced merge instead of
the switch time: merges can be reported out of order by the forge's
"updated" sort, and the dedupe key already makes a second look harmless.
Reading only the files' names and taking every section of a touched
contract file: it would wake every implementer for a one-line change.
