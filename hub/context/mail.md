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
content) over the last hour; `security_queued` counts the security rows
still `queued`, however old. The SMTP conversation is `smtplib`, driven
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
**Source:** docs/api.md §16.2, §18.4, §18.5, §18.7; the implementation of tsk-32jx98jzne6z, part N2, 2026-10-23
**Revisit when:** the hub runs more than one replica (two workers would send the same row), or mail volume needs more than one mail at a time

A verification mail, the notice to an old address and, later,
notification and sign-in mail are rows in `mail_outbox`, written in the
same transaction as the change that causes them. `maity_hub.mail.outbox.Worker`
looks every five seconds, sends what is due one mail at a time with the
settings in effect, and records each outcome in `mail_delivery` under
the mail's budget kind. A security mail over `security_max_per_hour`
gets a later `not_before` and waits, never dropped. `enabled: false`
holds every row. A failure at `resolve`, `connect`, `tls`, `auth` or
`timeout` is the instance's and is retried with backoff for 24 hours. A
permanent `5xx` at `RCPT TO` or `DATA` fails the row and, when the mail
went to the human's verified address, counts a hard failure; the third
in a row disables the address and writes `mail_disabled` (§18.7), and a
delivery resets the count. Sign-in mail over its budget is dropped, not
delayed. A row that left the queue is deleted after seven days, so the
outbox keeps no lasting record of who got what.

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

## An outbox row is claimed before it is sent; the claim lapses after two minutes

**Id:** 92cf47a5-5206-4552-a493-2255cb3a1e48
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the coordinator's agreement on making the mail workers safe for a second process (`maity say`, seq 3405), 2026-10-25; the implementation of tsk-s7rktpfc3ejh
**Revisit when:** a second hub replica runs for good (then the instance budget needs a reservation across processes), or a mail is found sent twice after a crash mid-send
**See:** https://github.com/oliver-zehentleitner/maity — 5e42eb26-9883-49e2-89c0-9fe4e6517c62 — as of 2026-10-25

A process takes a row with one conditional UPDATE, from `waiting` (or a
lapsed `sending`) to `sending`, with `not_before` set to now plus
`CLAIM_FOR` (two minutes). Only the process whose UPDATE changed the row
sends it; a process that dies mid-send leaves a claim that lapses, and
the row is taken again. A retry puts the row back to `waiting`. The
notification mailer needs no claim of its own: a human's pass holds the
human's settings row `FOR UPDATE` until it commits, and what it mailed
is in `mail_item_sent` before a second pass can look.

**Reason:** the chart keeps one pod with Recreate, but an overlap, a
manual second process or a future replica must not send mail twice. A
conditional UPDATE is the claim every engine does the same way, and
reusing `not_before` as the deadline needs no migration. Two minutes
outlasts the 20-second SMTP conversation by a wide margin.

**Rejected alternatives:**
- `SELECT … FOR UPDATE SKIP LOCKED`: not on every engine the hub
  supports in the same form, and the lock would be held across the SMTP
  conversation.
- Exactly-once delivery: not possible across a crash between the
  server's `250` and the commit; the claim makes it at-least-once and
  one-at-a-time.
