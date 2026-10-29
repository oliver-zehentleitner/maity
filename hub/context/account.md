# Account

## A deletion request is a row of its own, and its link a signed token bound to that row

**Id:** 25f6666e-7c2d-45b4-98ff-9ef2081abb2c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-28 (account deletion, contract #545, migration 0076)
**Revisit when:** a second kind of request a human confirms by mail needs the same lifecycle

`POST /me/deletion` (docs/api.md §2.9) writes a row of `account_deletion`:
`id` is the sha256 of a random nonce, `live` is true while the request may
be confirmed and NULL once it is withdrawn, replaced or used, with a unique
constraint on `(human_id, live)`. The mailed link is a token of
`notifications.tokens` (purpose `account_deletion`) that carries the nonce;
the page looks the row up by the nonce's hash and the human, and every
withdrawal (`DELETE /me/deletion`, a newer request, `POST /auth/password`,
a change or removal of the verified address) only clears `live`.

**Reason:** the link has to be single use, expire, and die with the request
it belongs to; a row with the at-most-one marker the hub uses elsewhere
gives all three on every engine, and a copy of the database opens no link
(only the hash is stored). The withdrawals become one conditional update
each, in the transaction of the call that causes them.

**Rejected alternatives:**
- A signed token alone, as the unsubscribe link: nothing to withdraw it
  with short of moving an epoch that other links share.
- Columns on `human` or in `notification_settings`: the settings row is
  deleted with the account and is absent for a human who never changed a
  setting, and the account row would carry a request's history.

## The deletion reuses the removals on one connection, and marks the account first

**Id:** 8983161c-2c93-416b-aa98-8b8fd9a65102
**Type:** decision
**Status:** superseded
**Superseded by:** 33449ea0-6edd-4265-9817-b3c2c29d86e0
**Evidence:** confirmed
**Source:** implementation session, 2026-10-28 (account deletion, contract #545)
**Revisit when:** a removal it reuses starts its own transaction, or event payloads become rewritable beyond redaction

The link's `POST` runs `account_deletion.delete_account` inside one
`events.transaction`: runners through `routes.runners.remove` (the body of
`DELETE /runners/{id}`, extracted), profiles through
`routes.agents.delete_profile` (the body of `DELETE /agents/{id}` with
`cascade`, extracted), memberships through `members.apply_remove`,
invitations through `invitations.void`, requests through `close_request`
and a new `return_to_pool`. Each takes the caller's connection and none
commits, so a failure anywhere rolls all of it back and no event is
announced (`events.transaction` announces only after the commit). The
events these write name no actor (the hub's change); the runner removal
keeps its owner as `by`, as its own route does. The human row gets
`deleted_at` and the name "Deleted account" before anything else.

**Reason:** "exactly as a removal does" is only true if it is the removal's
code; a second implementation of each effect would drift. Marking the row
first makes every member view written into the removal events already show
the deleted shape instead of the name and handle.

**Known limit:** events written before the deletion keep the payload they
were written with (the log is append-only, §8.1); a member view in an old
`member_joined` still carries the old handle. Views computed at read time
(member views, `asked_by`, an event's human actor, history and chat
participants) show the deleted shape.

**Rejected alternative:** a background job that deletes step by step: a
crash in the middle would leave an account half deleted, which §2.9 rules
out.

## The deletion reuses the removals in one transaction; a deleted person in stored JSON is shaped at read time

**Id:** 33449ea0-6edd-4265-9817-b3c2c29d86e0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-28; review of #561 (the coordinator's ruling that old payloads must not show the person)
**Revisit when:** a removal it reuses starts its own transaction, or a new reader shows stored event JSON without `views.event_views`
**See:** account.md#the-deletion-reuses-the-removals-on-one-connection-and-marks-the-account-first — 8983161c-2c93-416b-aa98-8b8fd9a65102 — as of 2026-10-28

The deletion itself is unchanged from the superseded entry: one
`events.transaction`, the existing removals on its connection, the hub as
actor. (The account row is no longer marked first but written last, for the
lock order of 2cecbd85-ba32-43db-905f-11efddb97f3d; with read-time shaping
nothing depends on it.) What changed is the old payloads:
`views.shape_deleted` rewrites, at read time, every person object of a
deleted account in stored JSON — a member view (`id` with `kind: human`),
or an object with a human's `member_id` and a name or handle (`asked_by`,
`on_behalf_of`, mentions, history and chat participants) — into the
deleted shape, keeping ids, types and free text. It runs once over all
payloads of a page in `event_views` and the message listings, and over
the stored JSON of the direct views: a request (its mentions, answer and
`needs_in_session`; single and lists), a card (single, lists, board), a
note and a history entry, with one query for the deleted accounts among
them.

**Reason:** §2.9 says a payload shows a deleted account as one; the
append-only log constrains what is stored, not what is delivered. Shaping
in the read path keeps the log untouched and covers every old event at
once.

**Rejected alternatives:**
- Leave old payloads as written (the superseded entry's known limit):
  refused in review, the person stays identifiable to every member.
- Rewrite the stored payloads at deletion, like a redaction: touches every
  event of every project the person was in, and breaks the rule that only
  a redaction changes a stored payload.

## No write of a deleted account commits: the check is at the commit

**Id:** a96c2553-eac1-4ee1-b1d7-573c45e581a9
**Type:** decision
**Status:** superseded
**Superseded by:** 2cecbd85-ba32-43db-905f-11efddb97f3d
**Evidence:** confirmed
**Source:** review of #561 (a write held between authentication and its transaction committed after the deletion)
**Revisit when:** a human caller writes through a path that is not this engine, or the deletion stops locking the account row first

`write_guard` hooks the engine: once a request's human caller is
authenticated (`deps._resolve` binds its id in a context variable), every
transaction of that request that wrote re-reads the human row with a
shared lock right before it commits, and refuses with `unauthenticated`
when the account is deleted. The deletion locks the row `FOR UPDATE`
first, so a write either commits before it (and is removed with the rest)
or waits and is refused.

**Reason:** a call authenticates in its own transaction and writes in
later ones; a check per route, or in `idempotency.run` alone, leaves every
route that opens its own transaction open to the race. The commit is the
one place every write passes, whichever route or helper made it.

**Rejected alternatives:**
- A check in `idempotency.run`: many writes (`engine.begin()` in routes,
  the address, sessions) do not pass through it.
- Also refusing when the calling session ended: a logout ends its own
  session in the transaction being checked; the deletion sets `deleted_at`
  in the same transaction that ends every session, so the account decides.

## One lock order against a deletion: the account lock before any other

**Id:** 2cecbd85-ba32-43db-905f-11efddb97f3d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** re-review of #561 (the commit-time check inverted the lock order: a profile delete holding the profile lock waited for the human row the deletion held, while the deletion waited for the profile)
**Revisit when:** something besides `write_guard` and the deletion locks `account_lock`, or a human caller works through a path outside the engine
**See:** account.md#no-write-of-a-deleted-account-commits-the-check-is-at-the-commit — a96c2553-eac1-4ee1-b1d7-573c45e581a9 — as of 2026-10-28

`write_guard` still binds the authenticated human caller per request, but
checks at the start instead of the commit: before a transaction's first
locking statement (a write or a locking read) it takes the human's row in
`account_lock` (one row per human, made by 0076 and on first need) with a
shared lock and refuses a deleted account. The deletion takes that row
exclusively as its first lock (`account_deletion.lock_account`), takes no
lock on the human row before its object locks, and writes the human row
last. An address's confirmation link, which changes the account without a
caller, takes the shared lock too. The link's `POST` runs under
`db.retrying`, so a deadlock with unrelated work never leaves the deletion
failed or half done.

**Reason:** with one first lock that only these take, a human's own work
and the deletion cannot wait for each other while holding something the
other wants. Its own row rather than the human row: the human row is
locked `FOR UPDATE` by ordinary work — account records (`records.write`),
a slug claim (`namespace.taken`), the preferences, the avatar, and the
deletion request — often after project locks, so a shared lock on it held
from a transaction's start would deadlock against those. Read-only
transactions take nothing: a plain read under READ COMMITTED holds nothing
the deletion waits for.

**Rejected alternatives:**
- The human row `FOR SHARE` at the start of every human transaction: two
  writers of one human that both later lock the row `FOR UPDATE` (a record
  each) deadlock on the upgrade, and a third party's record for the human
  after a project lock forms a cycle with the human's own work.
- PostgreSQL's `FOR KEY SHARE` against `FOR NO KEY UPDATE`: no such modes
  on MariaDB.
- The check at the commit (the superseded entry): it took the human row
  after object locks, the opposite of the deletion's order.

## The operator's counter is derived from `deleted_at`, nothing is stored

**Id:** 0a3d8286-a7e9-4c01-9851-704e751c1e53
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-28 (account deletion, contract #545)
**Revisit when:** accounts can be deleted in a way that removes the row

`GET /admin/statistics` counts `totals.humans_deleted` from
`human.deleted_at`; deleted accounts are in no other total, not in
`returning`, and `GET /admin/users` does not list them.

**Reason:** §16.6 stores nothing of its own, and the row stays for good
(§2.9), so the count is exact without a counter table that could drift.

**Rejected alternative:** a stored counter: one more thing a failed
transaction or a restore could leave out of step.

## Every table that names a human is checked against the deletion and the export

**Id:** b60df323-1007-4d28-bde6-a0df241f53c7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the review of #586, where forge links (#567) and mail sign-in links (#550) had landed after the deletion and were not removed by it; the coordinator's card for a schema check; the review of #607 (columns without a foreign key, the delegated removals, `project`)
**Revisit when:** a column names a person under a name the pattern does not catch, a table behind `membership` or `agent_profile` holds a person's data that their removal does not reach, or the deletion or export moves its statements out of the modules the test reads

`tests/test_per_human_tables.py` walks the schema. A table names a human
through a foreign key to `human`, a column called `human_id`, or a column
marked in `NAMES_A_HUMAN`: one without a foreign key that holds a
human's id (often a `hum-…`/`agt-…` principal id) or an address. Every
column without a foreign key whose name looks like a person's (`*human*`,
`*_by`, `owner_id`, `caller`, `address*`) must be decided there, `True`
or `False` (a reason, a deadline, a mode), so a new one fails until
someone decides.

Every table that names a human must then be named (`t.<table>`) in
`account_deletion.py`, handed to the module that removes such a row
anywhere (`DELETION_THROUGH`: `members.apply_remove`,
`agents.delete_profile`, `runners.remove`, as §2.9 says the deletion
removes them "as a removal does"), or listed in `DELETION_KEEPS` with a
reason; and the same for `export.py`, `EXPORT_THROUGH` and
`EXPORT_LEAVES_OUT`. A list entry for a column or table that is gone, no
longer names a human, or that the code handles after all, fails as
stale. `project` is kept on purpose, not covered because the deletion
happens to read it: it is the one keep the deletion module also names
(it reads projects to find what the human owns, for `namespace_owner`,
but never deletes or blanks the row), so the stale check exempts exactly
`project` by name (`KEPT_THOUGH_READ`) rather than dropping the "handled
after all" check, and any other table the deletion starts to handle
still fails while it sits in `DELETION_KEEPS`. "Named" means `t.<table>` as a whole name in the
module's code, comments and docstrings left out: `t.email_sign_in` is
not named by `t.email_sign_in_day`.

The walk is one hop. Tables that reach a person only through
`membership` (`card_watch`, `member_briefing`, `conversation_read`,
`presence_minute`, …) or through `agent_profile` are not checked: they
are the removal's (§6.2) and the profile deletion's (§6.3), which the
deletion hands them to.

The test checks that a table is decided, not that the decision is right:
whether a statement covers the right column stays the reviewer's to see.
Two entries were open at first: `address_lock` and `registration_lock`
kept a row per address after the deletion, while §2.9 says the addresses
are deleted. They are settled: the rows are keyed by the address's HMAC
and the deletion removes the account's (`notifications.md`, "A lock row
holds the address's HMAC, never the address", 25f27b8d), so neither
table names a person any more.

**Reason:** a feature that adds a table about a person is built without
the deletion in view, and nothing failed when it was left out; the gap
showed only in a later review. A failing test makes the author decide at
the time the table is added.

**Rejected alternatives:**
- A marker on each column in `tables.py` (`info={"names_a_human": ...}`),
  as the review proposed: the same enforcement, but about 45 column
  definitions touched for it, against one registry next to the test that
  reads it.
- Dropping the "handled after all" check for every keep, to let
  `project` pass: a handled table could then hide in `DELETION_KEEPS`
  unnoticed.
- Counting only foreign keys and `human_id`: principal ids in plain
  strings (`paused_by`, `caller`, `actor_human_id`) and addresses passed
  through unseen.
