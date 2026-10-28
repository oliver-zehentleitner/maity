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
**Status:** active
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
