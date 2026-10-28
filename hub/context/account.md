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
actor, the account row marked first. What changed is the old payloads:
`views.shape_deleted` rewrites, at read time, every person object of a
deleted account in stored JSON — a member view (`id` with `kind: human`),
or an object with a human's `member_id` and a name or handle (`asked_by`,
`on_behalf_of`, mentions, history and chat participants) — into the
deleted shape, keeping ids, types and free text. It runs once over all
payloads of a page in `event_views`, the message listings and a request's
`needs_in_session`, with one query for the deleted accounts among them.

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
**Status:** active
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
