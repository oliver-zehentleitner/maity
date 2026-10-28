# Mail

## The mail counters from a delivery table, the conversation on the standard library

**Id:** 2b0a92f1-f958-4945-b49f-58f0e294a7b6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.2, §16.3; the hub card for mail settings and the test send (tsk-gwft8fzazd6w), 2026-10-23; its implementation, 2026-10-23
**Revisit when:** the hub runs more than one replica and sends mail from each
**See:** https://github.com/oliver-zehentleitner/maity — d2d3356f-7a73-4e77-ac7c-3e04b07c2517 — as of 2026-10-23
**See:** persistence.md#admin-set-instance-settings-in-one-table-with-a-registry-in-code-admin-set-secrets-sealed-in-a-table-of-their-own — e689f915-bca1-41c1-97d5-bdc125cbd9b3 — as of 2026-10-23

The admin-set mail values are `mail.*` names in `instance_setting`, the
sealed SMTP password `mail.smtp_password` in `instance_secret`, and the
last test `mail.last_test` (persistence.md). The counters of §16.2 count
rows of `mail_delivery` (budget kind, outcome, time; no address and no
content) over the last hour; `security_queued` counts the security mail
still waiting in `mail_outbox`, however old. The SMTP conversation is `smtplib`, driven
step by step (`maity_hub.mail.smtp`) so that each stage of §16.3 is its
own exchange, inside one 20-second deadline. `tls: none` with a host
that is not loopback stops the hub at startup and is refused at stage
`tls` before any connection, whichever source each of the two comes
from.

**Reason:** counters in the database survive a restart, which the
hourly budgets must, and stay right if a second replica ever sends; the
sending itself (notifications, sign-in mail) writes the rows, so this
table is created with the settings that read it. `smtplib` gives every
command and its reply separately, which the stage names need, and the
routes are synchronous already. A pair checked only per source let an
admin's `tls: none` meet a later environment host and send in clear
(found in review).

**Rejected alternatives:**
- Counters in process, like `ratelimit.Limiter`: a restart would reset
  the budgets, and two replicas would each count half.
- An SMTP library as a new dependency (aiosmtplib): an async client in
  synchronous routes, for what the standard library already does.

## The test send counts against no budget, needs `to` until addresses exist, and `last_test` is cleared only by a real change

**Id:** 30b4ad58-6913-49fd-b6a4-ed0a20bbee4e
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.2, §16.3, §18.4; the implementation of tsk-gwft8fzazd6w, 2026-10-23
**Revisit when:** `/me/notification-settings` stores a verified address (§18.4), so that `to` may default to the admin's own

`POST /admin/settings/mail/test` writes `last_test` and nothing to
`mail_delivery`, so it moves none of the counters. Without `to` it is
`invalid` (`to: no_verified_address`): the contract's default, the
admin's own verified address, does not exist in the hub until the
notification settings are built. A `PATCH` clears `last_test` only when a connection
field (`host`, `port`, `tls`, `username`, `password`, `from`) has a
different effective value afterwards, not whenever one is in the body.

**Reason:** a test is none of the three kinds of mail whose budgets the
counters show, and counting it would make `failed_last_hour` report the
admin's experiments as delivery failures. The `to` default needs an
address the hub does not hold yet; refusing is what §16.3 says for "no
`to` and no verified address". A dashboard that sends its whole form on
every save would otherwise wipe the last test with an unchanged value.

**Rejected alternatives:**
- Counting a failed test in `failed_last_hour`: the counters would mix
  the settings check with real deliveries.
- Clearing `last_test` whenever a connection field is in the body:
  simpler, but every full-form save would drop a still valid result.

## Mail goes through an outbox written in the deciding transaction and sent by a worker thread

**Id:** c77fd991-dc7d-4c37-9971-8f500a91ccf8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.2, §18.5, §18.7; the implementation of tsk-32jx98jzne6z, 2026-10-23, re-cut as the first of four pull requests, 2026-10-27
**Revisit when:** the hub runs more than one replica for good (the budgets are read per pass, not reserved), or mail volume needs more than one mail at a time

Mail is a row in `mail_outbox`, written in the same transaction as the
change that causes it. `maity_hub.mail.outbox.Worker` looks every five
seconds, sends what is due one mail at a time with the settings in
effect, and records each outcome in `mail_delivery` under the mail's
budget kind. A security mail over `security_max_per_hour` gets a later
`not_before` and waits, never dropped. `enabled: false` holds every row.
A failure at `resolve`, `connect`, `tls`, `auth` or `timeout` is the
instance's and is retried with backoff for 24 hours; a permanent `5xx`
at `RCPT TO` or `DATA` fails the row and, when the mail went to the
human's verified address in use, counts a hard failure against it: the
third in a row disables the address and writes `mail_disabled` (§18.7), and
a delivery resets the count. A verification mail to a pending address
counts against no address. Once disabled, no further mail goes to that
address: each row is checked against the address as it stands just before its
delivery, so what was queued earlier and the rest of a batch stop too; only
the confirmation link of an address being set again passes (the outbox row is
marked `_purpose: verify`, a mark that is never sent as a header, and goes to
the pending address): it is the way back. Nothing else follows it while the
address stays disabled, the link used or not. Sign-in mail over its budget is
dropped, not delayed, since a late link is useless. A row that left the
queue loses its text at once, since the text carries the mail's links (a
confirmation, a sign-in, a registration link), and its headers (the signed
unsubscribe link is one), and keeps its recipient and subject; the row is
deleted after seven days, so the outbox keeps no lasting record of who got
what. A row that left before this change loses its text on the next sweep.
A row still waiting keeps its text for the seconds it takes to send; a mail
that keeps failing is dropped on the first failed attempt after 24 hours, so
the text of a row nobody retries can stay longer.

**Reason:** a mail decided in a transaction that rolls back must not
leave, and a request must not wait up to 20 seconds for an SMTP server.
The budgets need the order and the waiting that a queue gives. A thread
like the images worker needs no new process for one replica.

**Rejected alternatives:**
- Sending inside the request: a slow or failing server would hold the
  admin's or human's request, and a mail could leave for a change that
  then fails to commit.
- An in-memory queue: a restart would lose queued security mail, which
  §16.2 says is never dropped.
- Sealing the text with `MAITY_SECRET_KEY` while it waits: the window it
  would protect is the same one a link is valid for, it would make the
  outbox depend on a key that is optional, and a row that is out needs no
  text at all. Clearing the text when the row leaves the queue closes the
  long exposure (a backup taken a week later) without that dependency
  (card tsk-ayng0czsxp11, from the review of #489).

## An outbox row is claimed before it is sent; the claim lapses after two minutes

**Id:** 92cf47a5-5206-4552-a493-2255cb3a1e48
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the coordinator's agreement on making the mail workers safe for a second process (`maity say`, seq 3405), 2026-10-25; the implementation of tsk-s7rktpfc3ejh, folded into the outbox when it was re-cut, 2026-10-27
**Revisit when:** a mail is found sent twice after a crash mid-send, or the hour's window should slide instead of roll
**See:** kubernetes.md — 5e42eb26-9883-49e2-89c0-9fe4e6517c62 — as of 2026-10-25

A process takes a row with one conditional UPDATE, from `waiting` (or a
lapsed `sending`) to `sending`, with `not_before` set to now plus
`CLAIM_FOR` (two minutes). Only the process whose UPDATE changed the row
sends it; a process that dies mid-send leaves a claim that lapses, and
the row is taken again. A retry puts the row back to `waiting`.

The budget of the row's kind is decided in the same transaction as the claim, under a lock on
that kind's row in `mail_budget` (`kind`, `window_start`, `admitted`): the hour rolls when it
has passed, and `admitted` grows by one only below the budget. Over it, a security mail is
released (`waiting`, five minutes on) and a sign-in or registration mail dropped. A retry is
not admitted again (it was when it first went out); a claim that lapsed is, which errs on the
side of the budget. The settings are read again before every
delivery, so `enabled: false` stops the rest of a pass, and a delivery under way
runs to its end.

**Reason:** the chart keeps one pod with Recreate, but an overlap, a
manual second process or a future replica must not send mail twice. A
conditional UPDATE is the claim every engine does the same way, and
reusing `not_before` as the deadline needs no extra column. Two minutes
outlasts the 20-second SMTP conversation by a wide margin. The claim is
part of the outbox from its first version, not a later change on top.

**Rejected alternatives:**
- `SELECT ... FOR UPDATE SKIP LOCKED`: not on every engine the hub
  supports in the same form, and the lock would be held across the SMTP
  conversation.
- Exactly-once delivery: not possible across a crash between the
  server's `250` and the commit; the claim makes it at-least-once and
  one-at-a-time.
- Checking the budget before the claim, then after it by counting what was sent and what is in
  flight (the first two versions of #478): two workers could both see room for the last place,
  once by a commit the other had not yet made, once by ordering the claims by id and then by
  deadline, which a clock that jumps defeats. A counter that is locked, checked and raised in
  one transaction depends on no commit and no clock.
- Counting when a mail is sent: the place would be free again for a mail that fails for good;
  counting when it is admitted keeps a place used, the strict side of a budget against abuse.
