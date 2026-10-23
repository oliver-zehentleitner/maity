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
default branch, most recently updated first, page by page until a page
reaches back before what has been read already (`scanned_until`, or the
switch-on), since a merge updates its pull request and nothing older can
follow. A round reads at most 20 pages; when that cuts it, the next round
goes on from the next page (`resume_page`), and once an interval has been
read to its end `scanned_until` moves to the moment that scan began, so
later rounds stop there. It keeps those updated after that bound and
merged after `merges_since` that have no `merge:<n>` key yet: a pull
request merged before the bound but updated after it (a comment while a
cut scan was under way moves it to page 1, past the pages still to be
read) is read again rather than lost, and the key keeps it to one item.
The bound is floored to its second for both the admission and the
early stop, since the forge's `updated_at` has whole seconds: an update
in the bound's own second is read again, never lost. It
reads each one's files (at most 300; a rename counts
for its old and its new path, and a renamed contract file is a contract
change), and for a contract file that file at the merge commit and at the
base. The sections come from the unified diff: added lines are looked up
in the file at the merge commit, deleted lines in the file at the base.
Each item is written in a short transaction of its own, under the
project lock, only if the ticker is still on, `merges_since` is the one
the round started from, and the repository and branch are the same;
otherwise the round ends. Without a patch, or for a file over 1 MiB, the
sections are unknown and every implementer applies. A project that had
the ticker on before this part arrived gets the upgrade's moment, from
the migration and again from the next PATCH that switches it on.

**Reason:** §17.4 announces nothing older than the switch, so the moment
has to be stored; the dedupe key alone would announce the whole history
the first time. Reading the forge with no connection held is the probe's
rule (§11). The diff names exactly the changed lines, and the two files
give the heading above each of them, as §17.3 defines a section. A
separate cadence keeps the reports' and releases' sweep at its interval.

**Rejected alternative:** a cursor of the last announced merge instead of
the scan's own start: merges come back in the forge's "updated" order,
not in merge order, so the last one announced says nothing about what is
still behind. Reading the whole backlog in one round: unbounded on a busy
repository. Stopping at a page bound and only logging the cut: the
merges behind it would never be announced. Admitting by the merge time
after the bound: a merge that moved up the list while a cut scan read
on would fall between its pages and the next interval for good.
Reading only the files' names and taking every section of a touched
contract file: it would wake every implementer for a one-line change.

## The forge webhook is answered in the middleware, limited and checked before its body is read, and only ever triggers the probe

**Id:** e0fc2208-24e8-40f9-9042-293637043187
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §17.4 (signature, limits before the body, refusals alike, the body a trigger never a fact); the third part of the hub card (tsk-0wtpcjkdhgq8), 2026-10-23; the implementation, 2026-10-23; the review of PR #235 and the contract owner's ruling on the buckets and, in the second round, on the held-back body, 2026-10-23
**Revisit when:** a forge other than GitHub signs deliveries, or the hub runs more than one replica (the limits are in-process)
**See:** packaging.md#cryptography-for-the-secrets-the-hub-stores-held-to-one-major-release — 2ea5c41e-7128-4205-91dc-04ff6110b338 — as of 2026-10-23

`POST /api/v1/projects/{slug}/forge/webhook` never reaches the API's
routes: `maity_hub.forge_webhook.handle` answers it from the middleware,
before the middleware would read the body. A missing, repeated or
over-1-MiB `Content-Length` is `payload_too_large` for every slug. Then
it looks up the project, its webhook and the opened secret; without one
of them (or without `MAITY_SECRET_KEY`, or with a secret the key does
not open) it takes a place in the per-address bucket, reads the declared
body all the same and answers `webhook_signature`, so a body held back
hangs for every slug alike. For a known slug it takes a place in the
per-project-and-address bucket before reading at most 1 MiB, so at most 60 bodies per project and address are
read at once, and gives the place back when the HMAC-SHA256 (exactly
one signature header, compared in constant time) verifies; then it
charges the project's bucket of verified deliveries. Every request that
does not verify, known slug or not, also counts against one bucket per
source address and is answered `rate_limited` once that is full. A
verified delivery is never checked against that bucket.

A verified delivery only queues work on the probe worker: a closed pull
request makes it look for merges now, a deployment status makes it read
that deployment. A body that is not a JSON object is `invalid`. The
delivery id is kept as `origin.delivery` only in the shape
`[A-Za-z0-9-]{1,64}`, and only on the merge the delivery named; the
other merges the same scan finds are the probe's own. A sealed secret
is bound to its field and project and never reads as empty when the key
cannot open it: the view shows `configured: false`, each delivery logs
an error, and the hub logs at startup how many stored secrets it cannot
open.

What remains apart, accepted: a known slug's request also opens the
secret and computes the HMAC, a few microseconds; a known slug's request
past the per-address limit is answered `rate_limited` only after its
body; and with 60 of its own requests held open at once against one
known slug, the 61st is refused before its body while an unknown slug's
is still read. None of these tells one request from another; the held
body did, as a one-request answer, and is read for every slug now. There
is no replay protection, since GitHub signs no timestamp; a replayed
delivery only makes the probe read again, and the probe announces only
what it observes.

**Reason:** §17.4 wants the limits and the existence check before any
body is read, but the middleware reads every body first to scan it for
credentials, so the route layer comes too late. A trigger that only
queues a read keeps the forge's claims out of the item: the hub
announces what its own read observed. Answering every refusal the same
way, before the body, is what keeps the path from telling whether a
project exists.

**Rejected alternative:** a FastAPI route with a dependency for the
limits: the body would already have been read by then. Writing the item
from the delivery's body: a forged or replayed body could announce a
merge that never happened, which §17.4 rules out. Taking a place in
the per-address bucket for every request before its body: forges
deliver from shared address pools, so one project's failing deliveries
would refuse another project's verified ones from the same address,
which §17.4 rules out; counting the failures there after verification
keeps the answers alike without that.

**Condition:** the credential scan of the middleware does not run on this
path. That holds only while the delivery body is never stored, echoed or
logged: it is parsed for the deployment id and dropped, and only the
forge's delivery id from the header is kept (`origin.delivery`). Should
any part of the body ever be stored (in an event, a log line, an
idempotency record), the scan has to run on it first, or that part is
not stored.
