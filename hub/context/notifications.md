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

## One account per address: a unique normalized column, claimed under a row of `address_lock`

**Id:** ea46fd15-c3f9-49a6-bece-44f472471aed
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §18.4 and §2.7.1; the implementation of tsk-32jx98jzne6z, part 3 of the re-cut of #280, 2026-10-27
**Revisit when:** the hub runs more than one replica on an engine whose row lock differs from the three the tests run on

`notification_settings.address_normalized` holds the verified address trimmed and
lower-cased, under a unique constraint. Verifying an address first locks the address's row
in `address_lock` (inserted if absent, then `SELECT ... FOR UPDATE`), checks that no other
account holds it, and writes it. A link for an address another account claimed meanwhile is
the dead-link page and changes nothing. Removing the address clears the column, which frees
the address. Setting a pending address claims nothing. A registration's completion claims
its address the same way (`preferences.claim_verified`, called by
`registration_accounts.claim_address`), under the same lock; the loser makes no account.

**Reason:** the contract asks for a unique constraint as the guard and a lock that
verification, address change and registration share. A lock row per address serializes
exactly the contenders for one address, and the constraint still catches anything that
skips the lock. Until this claim existed, no registration could complete (the stand-in
answered `False` and failed closed).

**Rejected alternatives:**
- The unique constraint alone, catching the violation: it works, but the contract names the
  shared lock, and registration needs it to void the other pending registrations in the same
  transaction.
- A lock on the human's row: it would not serialize two accounts racing for one address.

## Notification mail is planned per human once a minute from the derived items, each item mailed once; a human whose notifications did not move is not derived again

**Id:** de75f59b-21f5-4a26-8ab4-9819c23c6228
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §18.4, §18.5, §2.6.5; the implementation of tsk-32jx98jzne6z, part 4 of the re-cut of #280, 2026-10-27; the incident of 2026-10-26 (a per-call cost that grew with history)
**Revisit when:** many humans make one pass longer than a minute, or the bell gets a cheaper way to say that nothing moved than `listing.stamp`

`maity_hub.notifications.mailer` runs once a minute. For each human with a verified address
it first reads `listing.stamp` (a few aggregates, the one the bell's long-poll compares).
If it equals the stamp of the last pass, no item was left waiting for its hour or day
(`notification_mail_state.waiting`) and the human is not held over the budget, the pass
ends there. Otherwise it derives the unread items as the bell does and keeps those not yet
in `mail_item_sent` and not older than the address's `verified_at`; the open matters
`registration_pending` and `mail_disabled` are never mailed (§18.5). A new sign-in goes out
at once as a security mail. Outside quiet hours, `immediate` items go out together once the
oldest is two minutes old, unless ten notification mails left in the past hour; then they
join the hour's digest. `hourly` and `daily` digests go out when the full hour or `daily_at`
(in the human's time zone) has passed since the last one, recorded in
`notification_mail_state`. A human's first pass only starts those two clocks. When the
notification mail of the past hour, sent or waiting, reaches the instance's `max_per_hour`,
nothing is queued for the human; their items stay pending and the first pass with room again
sends everything due in one mail (§18.5, "merged into each human's next mail"). A kind set
to `off` leaves nothing waiting, so it never keeps a human's passes deriving. The text of a
`chat` or `mention` message, where the human asked for it, is read from the event, never
from a redacted one.

**Reason:** deriving from the same items as the bell keeps a mail from ever saying more than
the human may read at the moment it is built (§18.5, freshness). A row per mailed item is the
simplest guard against sending twice across passes and restarts. Starting from `verified_at`
keeps a newly confirmed address from receiving a month of backlog. The stamp is what the
bell already trusts to say that an answer cannot have changed; reusing it means a pass for a
human who did nothing costs a few aggregate reads and not thirty days of every project, which
the incident of 2026-10-26 showed does not scale.

**Rejected alternatives:**
- Mailing from event hooks at write time: the readability check would be the event's, not
  the mail's, and quiet hours and digests would need a queue anyway.
- Deriving every verified human on every pass, as the first version did: simple, but a cost
  per minute that grows with the humans' histories, the shape the incident was about.
- Letting mails over the instance budget wait in the outbox: simpler, but it can mean two
  mails where §18.5 asks for one (the first version, changed before review).

## A page of the bell is cut from items derived only as far as the page reaches; no cache

**Id:** 24ca001c-ff28-4df3-8af1-ba6ef6d567b6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** tsk-svhatnxrtqn8; Traefik access log of 2026-10-28 17:51-18:21 UTC (`GET /me/notifications` p50 1.0 s, p95 1.9 s, n=482); the local measurement in `hub/scripts/measure_notifications.py`
**Revisit when:** a listing needs the number of all matching items or a total over chat items, or `derive_page` and `derive` diverge in a test

`GET /me/notifications` derived every item of 30 days on every call, and every message an
agent sends its owner in a direct chat is one. The cost was linear in those messages (about
80 ms per 1,000 items, 1.2 s at 30,000), not in the projects or the queries; the counts, the
position and the twenty views together took under 100 ms. A page needs `limit` items and to
know whether one more follows, and the counts read no chat item (`chat` comes from the chats'
own marks). So `items.derive_page` derives everything that is not a plain chat message (requests,
mentions, account records: few, and they feed the counts), and of the plain chat messages
only the first `limit + 1` per project that the filters, the cursor or `after` accept, read
from the database in the order the listing uses (`at`, then `seq`), in chunks that grow
while a filter such as `unread` rejects them. A message whose payload text has a `member_id`
and the human's id is derived with the rest, since it may mention them; the text test only
selects, `_classify` decides. `scope` and the unread-chat count read their rows in one query
each instead of one per membership and per agent, and a page reads each project and actor once.
Measured on SQLite with 10 projects and 30,000 chat items: 1.16 s before, 0.1 s after.

**Reason:** the answer is a function of the page, so the work should be too; a cache would
answer from the past (a read mark, a claimed request or a rename that the stamp does not
see) and only helps while nothing moves, which on a busy team is rarely. `tests/test_notifications_page.py`
keeps the two honest: for every filter, page size and the cursor through items of one
timestamp, and for `after` chains, the bounded pages equal the pages cut from `derive`.

**Rejected alternatives:**
- A cache of the derived items keyed by `listing.stamp`: the stamp does not see a request
  claimed by another admin, a rename or the sliding 30-day window, and it misses on every new
  message, which is when the bell is polled most.
- Cheaper work per item (fewer JSON decodes, fewer lookups): at best a factor of two on a cost
  that stays linear in the history.
- Filtering chat messages by the human in SQL: a chat message names its addressee in `to`,
  so every message of the human's own chats matches and nothing is saved.

**Known limit:** a filter that rejects almost every chat (`unread` after everything was read)
still reads all of a project's chat rows in the window, in chunks, as the old derivation did.

## Changing or removing the verified address, and approving a held change, take the step-up the caller gives in

**Id:** b4c0e7a3-61d8-4f29-9a5e-0d83f7b1c2e6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.8.4; the card tsk-9z1m4tcz1e98 (the follow-up of the review of #471), 2026-10-28
**Revisit when:** another operation on the address becomes sensitive, or the held change moves to a place where `second_factor.require_step_up` cannot be given as a callable

`preferences.patch` and `preferences.decide_held` take a `step_up` callable that the routes fill
with `second_factor.require_step_up(conn, hub, caller)`. It is called where the change is known to
move a verified address (`_change_address`: the address is verified, or disabled, and the wanted one
differs, a removal included), and for the approval of a held change, first, so a refusal changes
nothing and counts no wrong password. Rejecting a held change asks for nothing: it only
withholds a change and §2.8.4 names the approval. Setting the first address, sending the same one
again and every other setting are not sensitive. A human who is not enrolled is never asked (that
is `require_step_up`'s own rule). The parameter has no default, so a caller that forgets it does not
compile in the type check.

**Reason:** the address is what a mailed reset and a mailed link are proved by, so whoever can move
it with a stolen session can take the account's mail; the second factor is the one thing that
session does not hold. The check lives where the change is decided rather than at the route because
only there is it known that the address moves (a request with the same address does not). The
callable keeps `preferences` free of the caller and the hub settings.

**Rejected alternatives:**
- A step-up on every `PATCH /me/notification-settings`: it would ask for the factor to switch a
  mail mode, which §2.8.4 does not list.
- Asking only on approval of the held change and on the removal: a change with the password from a
  full session is the main way an address moves, and it is the first thing §2.8.4 lists.

## A change of the second factor and wrong second-factor codes are security items, each mailed on its own

**Id:** 3e9a6f12-8c47-4b05-a1d3-52c7e0b9f8a6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.8.1, §18.1 (the `security` row), §18.5; the implementation of #380, part 3, 2026-10-28
**Revisit when:** a third kind of security record needs a mail (the list in `mailer.SECURITY_MAIL` and the titles in `items._two_factor_title` are the places), or the security mail of a sign-in and of these records should share one builder

The account records `second_factor_changed` and `second_factor_failed` (`records.SECURITY`)
become `security` items with the titles of §18.1 (`items._two_factor_title`; a `change` this
hub does not know reads "Two-factor sign-in changed", never a guess), and the mail pass sends each
of them as a security mail of its own, as it does a new sign-in: not batched, not held by quiet
hours, one mail per item (`mail_item_sent`), only while the human's `security` mode is
`immediate`, with the subject `[Maity] <title>`, the time, the link to Profile → Security and the
unsubscribe line of the `security` kind. The bell confirms them like the other security items
(`listing._may_mark`: from a session in good standing that is older than the item). The mail
carries no code, no secret and no link that changes anything.

**Reason:** the contract says every change of the factor "sends the security mail of §18.5" and
that security mail is never batched, so the digest path (`_send`) is the wrong one; the sign-in
alert already has the shape (one item, one mail, its own budget), and the two-factor mail reuses
it with a different body. Keeping the title as the subject and the body's first line means a
reader sees what happened without opening the dashboard, which is what these mails are for.

**Rejected alternatives:**
- Putting these items in the digest like `inbox` items: a change a human did not make would then
  wait for an hour or a day to be told.
- One generic security-mail builder for the sign-in and these records: the sign-in's body
  carries method, browser, system and address and the others do not, so a shared builder would be
  a switch inside; two short functions are clearer.

## The browser switch defaults to off and the mail time zone to UTC; both are the contract's "the human decides" made concrete

**Id:** 4847d0cc-4ed4-4b92-9efd-c3c98bade6a1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §18.4 (`browser`, `timezone`); `preferences.DEFAULTS`; a review note on the settings card (tsk-32jx98jzne6z), 2026-10-29
**Revisit when:** the dashboard asks for the browser's permission before the first `GET` of the settings, or an instance wants another default zone

`DEFAULTS["browser"]["enabled"]` is `False` and `DEFAULTS["email"]["timezone"]` is `"UTC"`. The
contract names neither value: §18.4 calls `enabled` "the account's wish", which the dashboard
sets only when the human turns it on and the browser has said yes, and says only that the dashboard
proposes the browser's zone. Why these two values won is read from that text, not recorded by
whoever first wrote them.

**Reason:** a `true` default would claim a wish nobody expressed and a permission the browser
never gave, and the hub cannot know either; `false` is the one value that is never wrong, and the
dashboard switches it on after the browser's answer. The hub knows no zone for a human who has not
said one, and every mail time (`daily_at`, `quiet_hours`) needs one; `UTC` is the zone that needs
no guess and shows in the settings, where the dashboard's proposal replaces it.

**Rejected alternatives:** a `browser.enabled` default of `true`, as the §18.4 example shows (the
example illustrates a human who already turned it on; as a default it would be a claim without a
permission); no default for `timezone` (every read would need a "not set" case and the mail pass a
fallback of its own). Whether either was weighed when the code was written is unknown.

## A second first write of the same human's settings finds the row the first made

**Id:** 7caa2c14-307e-461c-95c8-34aedab837c8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** a review note on the settings card (tsk-32jx98jzne6z) and the review of #581, 2026-10-29; `tests/test_settings_race.py`
**Revisit when:** a settings write runs at `REPEATABLE READ`, or the row is made at account creation

`preferences.row_of(lock=True)` reads the row `FOR UPDATE` first; when there is none it inserts it
in a savepoint, and on an `IntegrityError` (another first write committed in between) it reads and
locks the row that now exists. Two first `PATCH`es of one human therefore end one after the other,
instead of the later one answering 500 on the primary key. The deadlock retry of
`persistence.md` ("Concurrent writes") does not cover the duplicate key itself, so the route also
runs the whole `PATCH` in `db.retrying`: three first writes at once on MariaDB can end in a
duplicate-key deadlock (1213), which that retry does cover; a refused change (an error raised) is
not retried.

**Reason:** the row is made by the first write only (a read of a human with no row sees the
defaults and writes nothing), so two first writes are an ordinary case; select first because the
row is almost always there and the common write should not start with a failing insert. The hub's
server engines run at `READ COMMITTED` (`db.py`), where a `FOR UPDATE` on a missing key takes no
gap lock; the race test on PostgreSQL and MariaDB in CI is what shows it.

**Rejected alternatives:** insert first, then lock, as `landing.lock` does (safe at any isolation
level, but every `PATCH` would run a failing insert in a savepoint for a row that nearly always
exists; kept as the move if the CI race test shows a deadlock on MariaDB); making the row at
account creation (a write and a migration over every human for a row the defaults make
unnecessary, and it would end "a read writes nothing" only in name).

## A group chat notifies its participants from their current stay; one who left gets nothing from it, what came before included

**Id:** ccc4332d-30be-4bd0-9ccf-26d59194471f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §9.2, §18.1, §18.2; the implementation of #556 (`Lookup.inside`, `listing._unread_groups`) and its review, 2026-10-29
**Revisit when:** a former participant may read the chat they left, or an observer should be told about a chat

A message in a group chat becomes a `chat` item (or a `mention` item) for a participant whose
stay in the chat is current (`here`) and whose stay began before the message (`seq > window_after`);
never for the writer, never for an observer, who reads along and is not addressed (§9.2). Someone
who has left gets nothing from the chat, what was said while they were in it included, and a
rejoin does not bring back what was said while they were away. `counts.chat` adds the group chats
to the direct ones (`listing._unread_groups`, per stay: the others' messages after both the stay
began and the read mark, tombstones included), the number the chat list shows; a test compares
the two. The count costs two queries per group chat, which the bell's counts will take from the
chat list's batched `unread` instead (#560).

**Reason:** §18.1 names the participants as recipients. A former participant no longer reads the
chat (`…/messages` answers `not_found`, the list does not show it, §9.2), so an item for an
earlier message would link to a chat it cannot open, and `counts.chat` must equal the list's
`unread`, which drops the chat too. The stay's `window_after` bounds the items the way it bounds
the chat's own window.

**Rejected alternatives:**
- Keeping the earlier items until their 30 days run out: they would point at `not_found` and
  disagree with the count.
- Notifying the owner who reads along as an observer: §9.2 makes an observer a reader, not an
  addressee.
- Reusing the chat list's batched `conversation_list._unread` for the count right here: it would
  make the number the list's by construction, but the bell's counts are being moved onto the
  list's `unread_chats` in #560, so a second change to the same lines would only conflict.
