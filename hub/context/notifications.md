# Notifications

How the hub derives a human's notifications. What they are and why they exist in three
stages is in the root `context/notifications.md`.

## Items are derived on every read from 30 days of the human's projects, with the relations as they are now

**Id:** e29065f2-c5d3-43dd-9209-f7f30b67269a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §18.1, §18.2; the implementation of tsk-32jx98jzne6z, part N1, 2026-10-23
**Revisit when:** `GET /me/notifications` or its long-poll gets slow for a human with many busy projects, or several hub replicas serve long-polls
**See:** https://github.com/oliver-zehentleitner/maity — d2d3356f-7a73-4e77-ac7c-3e04b07c2517 — as of 2026-10-23

`maity_hub.notifications.items.derive` reads, for each project the human
is an active member of, the events of the last 30 days since the
membership began, of the kinds that can make an item. Since the
maintainer's narrowing of 2026-10-26 (root context, notifications.md)
those are only messages, `mentioned` and the request events. It
classifies them (`inbox` over `mention` over `chat`), checks each
against what the human may read now, and adds the human's account
records. Counts, filters, the cursor and positions all work on that
list in Python. A request's relation to the human (addressee, holder,
asker) is the request's as it is when the bell is read. The only stored
state is the read marks (`notification_read`, the chats' own marks,
`read_at` on records). A held long-poll looks every 0.5 seconds, one per
session, and checks the session again at every look; which long-poll is
current is kept in the process, so a second replica would need it
shared.

**Reason:** §18.1 asks that an item never shows more than the human may
read at the moment it is read or mailed. A view computed when read
meets that by construction. Stored notifications would need every
membership end, redaction and permission change to find and withdraw
them. Thirty days of a few projects are small for V1, and the scan has
one place to optimise later.

**Rejected alternatives:**
- A notification row written per human and event at emit time: faster
  reads, but every later change of what the human may read would have to
  chase the rows.
- Relations frozen at the time of the event: a request forwarded away
  would keep producing items for a human who no longer holds it.

## Positions are sealed under a key derived from the instance key, else a random key the hub stores

**Id:** bb74a85e-1bd2-40ee-8c13-5a9ab7eaa74f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §18.2 (the opaque position, #257); the implementation of tsk-32jx98jzne6z, part N1, 2026-10-23
**Revisit when:** the contract's position rules change, or positions need to survive a change of `MAITY_SECRET_KEY`

A position is JSON `{v, p: {project id: seq}, a: record}` sealed with
AES-256-GCM, a random nonce in front, the human's id and
`notifications.position` as associated data, base64url without padding.
The key is HKDF-SHA256 of `MAITY_SECRET_KEY` with that purpose as info.
Without an instance key, the hub makes a random 32-byte key at first use
and keeps it as `notifications.position_key` in `instance_secret`. That
value is not sealed, since there is nothing to seal it with. Past 4096
characters the vector is stored in `notification_position` and the
position is a sealed `{v, h: handle}`, which looks like any other
position.

**Reason:** the contract makes positions independent of whether an
instance key is set. A stored key protects what the seal is for, a
forged or borrowed position, since whoever reads the database reads the
notifications anyway. Putting both forms under the same seal keeps the
form invisible to the client.

**Rejected alternatives:**
- A plaintext position with an HMAC: it would show the client the
  project ids and numbers, which the contract keeps from the holder.
- The random key in a new table of its own: `instance_secret` already
  is the place for values no setting may serve.

## A held long-poll compares a stamp before it derives again, and full answers run a few at a time

**Id:** 06563fc8-cd5c-4820-b089-9d233f3d44b8
**Type:** decision
**Type:** incident
**Status:** active
**Evidence:** inferred
**Source:** production incident 2026-10-26 (hub not ready, connection pool timeouts), analysis from the code and the incident log
**See:** notifications.md#items-are-derived-on-every-read-from-30-days-of-the-humans-projects-with-the-relations-as-they-are-now — e29065f2-c5d3-43dd-9209-f7f30b67269a — as of 2026-10-26
**Revisit when:** derive no longer runs per-row queries, or the long-poll waits on commits instead of looking

The hub was not ready for about a quarter of an hour. The pool ran out at a low request
rate. The likely cause was that every held notifications long-poll ran the full answer every
half second. The full answer derives every item of 30 days with several queries per event,
so each open long-poll occupied a connection and a share of the one Python core, and enough
of them took the pool from every other call, the health probe included.

**Decision:** between two looks, a held long-poll reads `listing.stamp`. That is a few
aggregates: the memberships, each project's highest event, the account records and their
reads, the event items' read marks and the chat marks; the project heads count only
the event kinds that can make an item, so a card's churn wakes no held long-poll. That
filter needs its own index, `(project_id, kind, seq)`: with only `(project_id, seq)`
the head reads every event row of the project on every look. The
full answer runs only when the
stamp differs; a read mark counts as movement. Full answers and marks pass a semaphore of
four per process. The marks are
written at READ COMMITTED in one statement that skips existing rows. A REPEATABLE READ
snapshot's insert failed on the key when a second mark of the same items raced it, and
would raise a serialization failure even with an on-conflict clause.

**Rejected alternatives:**
- A larger pool by default only moves the load to the database. It is now configurable
  instead.
- Capping the request threads at pool size plus overflow, so a full pool would queue
  requests in the hub. Tried in the same change and dropped: with 15 threads instead of
  40, waiters blocked on a slow read take every thread and starve unrelated requests.
  The guarding test is `test_waiters_on_a_slow_family_do_not_starve_the_request_threadpool`.
  How threads and pool should be sized is left to a separate decision.
- Waking on commits like the events long-poll, and removing the per-row queries in
  `derive`, are the full fix. They are larger and follow separately; the stamp and the
  semaphore stop the overload on their own.

**Reason:** the smallest change that makes an idle long-poll cheap and bounds what a busy
one can take. Evidence is inferred: the cost per event was measured locally; the incident
log showed pool timeouts at a low request rate, with no lock wait found on these paths.

## Deriving items reads each kind of lookup once per batch, not once per event

**Id:** b4a7c2f0-e8c8-4e9d-a093-95f07b4eb411
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** incident follow-up 2026-10-26 (the hub slow after the stamp check, the stamp moving with every agent action); measured on a local fixture before and after
**See:** notifications.md#a-held-long-poll-compares-a-stamp-before-it-derives-again-and-full-answers-run-a-few-at-a-time — 06563fc8-cd5c-4820-b089-9d233f3d44b8 — as of 2026-10-26
**Revisit when:** the classification reads something new per event, or the long-poll waits on commits instead of looking

With agents at work, the stamp moves on almost every look, so a held long-poll still
derives often. The cost was the per-event lookups in `_classify`: the card, the watch,
twice the owner of an agent membership, and the names. That is about three queries for
every foreign event of thirty days.

**Decision:** `items.Lookup` loads per project batch, each in one query: the requests
the rows name, the memberships behind the actors, and the profiles and humans behind
them (with the narrowing of 2026-10-26 the cards and watches left it). Its answers equal
the single lookups. An id the batch did not name falls back to the single lookup, so a
missed case costs a query instead of giving a different answer. The read marks are read by
the batch's seq range instead of a list of every seq. Measured on a local fixture of 450
card events and 150 chat messages: 1059 queries and ~110 ms became 13 queries and ~20 ms,
with the same 601 items. A test keeps the count flat as events grow.

**Rejected alternatives:**
- Caching the derived items per human between answers. Every read rule (§18.1) is applied
  as things are now, so a cache would need invalidation on every relation the
  classification reads: more state, for what one batch of queries already makes cheap.
- Rewriting the classification as SQL. It would duplicate §18.1's rules in a second form
  that has to agree with the Python one.

**Reason:** the smallest change that removes the per-event cost while keeping the rules in
one place. Evidence is inferred: measured locally, production to confirm.

## Notification settings store only what the human changed; the defaults fill the rest on read

**Id:** 3e9a6b69-7715-4ce3-8c9d-a9194fbf9500
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §18.4; the implementation of tsk-32jx98jzne6z, part 2a of the re-cut of #280, 2026-10-27
**Revisit when:** a default changes in a way existing humans must not receive, or the settings need a field the merge cannot express (a list)

`notification_settings.preferences` holds the browser and mail preferences as one JSON
value with only the keys the human set; `preferences._merged` lays it over the defaults
key by key on every read. A human who never changed anything has no row: a `GET` shows
the defaults and writes nothing, the first `PATCH` makes the row. A kind removed on
2026-10-26 (§18.1) is skipped when the value is read, and `PATCH` rewrites the stored
value without it, as §18.4 says.

**Reason:** a default that changes later (a new kind, another `daily_at`) reaches every
human who did not choose otherwise, and a human's choice never has to be told apart from
a copy of an old default. Dropping removed kinds on read needs no migration over the
rows, and the contract wants them deleted with the next write anyway.

**Rejected alternatives:**
- Storing the full value at the first read: later defaults would reach nobody who had
  opened the settings once, and a `GET` would write.
- Deleting the removed kinds from every row in a migration: a data migration over every
  human's row for settings that already govern nothing, and §18.4 asks for the next
  `PATCH`.
<<<<<<< HEAD

## A link in a mail is a signed token the hub stores nothing for; a page for a token that is not ours says nothing about anyone

**Id:** aaf1d325-deae-4409-9014-4927505d414e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §18.6; the implementation of tsk-32jx98jzne6z, part 2b of the re-cut of #280, 2026-10-27
**Revisit when:** a link must be used once only (the unsubscribe token has no nonce, so a mail can be replayed until the address changes), or the signing key is rotated

A token is the base64url of a JSON object with sorted keys and an HMAC-SHA-256 over it with
the instance's `MAITY_MAIL_SIGNING_KEY` (`notifications.tokens`); it is read only when
the key exists, the length is under 1024, the MAC matches in constant time and the payload is
an object. The unsubscribe token carries `{human, purpose, kind, epoch}` and nothing is stored
for it: it works until the human's `epoch` moves. The pages (`routes/mail_links.py`) answer
`not_found` with one text for every reason, and take the human's language only from a token
the hub signed itself, else English.

**Reason:** nothing to store or clean up for a link that may sit in a mailbox for years, and
the page of a forged token must not tell a stranger which handle or language an id has.
A repeated unsubscribe is harmless (the kind is off already), so a nonce would buy no
safety here, while a verify or reset link, which change things once, carry one (§18.6).

**Rejected alternatives:**
- A stored unsubscribe token per mail: a table that only grows, for a link whose second use
  does nothing.
- Telling the reason a link is dead ("expired", "already used"): it separates a guessed token
  from a real one, which §18.6 forbids.

=======
>>>>>>> agent-f/hub-notification-prefs
