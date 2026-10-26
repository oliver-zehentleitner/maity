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
membership began, of the kinds that can make an item. It classifies
them (`inbox` over `mention` over `card` and `chat`), checks each
against what the human may read now, and adds the human's account
records. Counts, filters, the cursor and positions all work on that
list in Python. A card's relation to the human (creator, holder,
watcher, …) is the card's as it is when the bell is read: an item from
a watch drops out once the watch ends. The only stored state is the
read marks (`notification_read`, the chats' own marks, `read_at` on
records). The long-poll answers again every 0.5 seconds until an item
lies past `after`, one per session, and checks the session again
at every look; which long-poll is current is kept in the process, so a
second replica would need it shared.

**Reason:** §18.1 asks that an item never shows more than the human may
read at the moment it is read or mailed. A view computed when read
meets that by construction. Stored notifications would need every
membership end, redaction and permission change to find and withdraw
them. Thirty days of a few projects are small for V1, and the scan has
one place to optimise later.

**Rejected alternatives:**
- A notification row written per human and event at emit time: faster
  reads, but every later change of what the human may read would have to
  chase the rows, and a watch would sit in a table readers of events
  could join.
- Relations frozen at the time of the event: an ended watch or a lost
  holder would keep producing items for a card that is no longer the
  human's.

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
reads, the event items' read marks, the chat marks and the watched cards (a watch
writes no event). The full answer runs only when the
stamp differs; a read mark counts as movement. Full answers and marks pass a semaphore of
four per process. Request threads are capped at pool size plus overflow, so a full pool
queues requests in the hub instead of failing them after the pool timeout. The marks are
written at READ COMMITTED in one statement that skips existing rows. A REPEATABLE READ
snapshot's insert failed on the key when a second mark of the same items raced it, and
would raise a serialization failure even with an on-conflict clause.

**Rejected alternatives:**
- A larger pool by default only moves the load to the database. It is now configurable
  instead.
- Waking on commits like the events long-poll, and removing the per-row queries in
  `derive`, are the full fix. They are larger and follow separately; the stamp and the
  semaphore stop the overload on their own.

**Reason:** the smallest change that makes an idle long-poll cheap and bounds what a busy
one can take. Evidence is inferred: the cost per event was measured locally; the incident
log showed pool timeouts at a low request rate, with no lock wait found on these paths.
