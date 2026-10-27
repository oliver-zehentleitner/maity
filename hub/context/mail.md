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
queue is deleted after seven days, so the outbox keeps no lasting record
of who got what.

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
**Source:** the coordinator's agreement on making the mail workers safe for a second process (`maity say`, seq 3405), 2026-10-25; the implementation of tsk-s7rktpfc3ejh, folded into the outbox when it was re-cut, 2026-10-27
**Revisit when:** a second hub replica runs for good and mail volume makes the unused places of a lost race matter, or a mail is found sent twice after a crash mid-send
**See:** kubernetes.md — 5e42eb26-9883-49e2-89c0-9fe4e6517c62 — as of 2026-10-25

A process takes a row with one conditional UPDATE, from `waiting` (or a
lapsed `sending`) to `sending`, with `not_before` set to now plus
`CLAIM_FOR` (two minutes). Only the process whose UPDATE changed the row
sends it; a process that dies mid-send leaves a claim that lapses, and
the row is taken again. A retry puts the row back to `waiting`.

The budget of the row's kind is decided after the claim, in a transaction of its
own: what was sent in the last hour plus the claims of that kind still in flight
that were taken earlier (by their deadline, then by id; the id of a row says
nothing about when it was claimed, since a retry falls due late). Over it, a security mail is released (`waiting`, five minutes
on) and a sign-in answer dropped. The settings are read again before every
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
- Checking the budget before the claim, as the first version did: two workers
  could each see room for the last place while the first was still in the SMTP
  conversation and both send (found in review, #478). The earliest claim in
  flight wins instead; a worker that drops out leaves a place unused until the
  next pass, which is the safe side of a budget.

## A registration's link is a signed token whose nonce is kept only as a hash, in the mail's own transaction

**Id:** a8f3a73c-7af9-4276-841e-3f84b056dedf
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.7.1 (the mail, the token); the implementation of tsk-32jx98jzne6z, part 5a, 2026-10-27
**Revisit when:** the link page (`/mail/register/{token}`) needs more than the pending id and the nonce, or a pending registration may be mailed twice

`registration_mail.send` runs in the transaction that writes the pending registration. For a
confirmation link it draws a nonce, stores `sha256(nonce)` in `pending_registration.nonce_hash`
and puts the nonce itself only in the token (`{i: pending id, p: "register", n: nonce,
x: expiry}`, signed like every link of §18.6) and so only in the mail. It goes to the outbox
as `registration` mail on the budget of that name (default 30 an hour; over it the mail is
dropped, a late link is useless) and carries when, and from which browser, system and address,
the request came, and nothing else of the person. The note to an address that has an account
has no token and no link that signs anyone in. Both are in the language of the request's
`Accept-Language` when the hub has it, else English, and have no unsubscribe part.

**Reason:** the link must prove the mailbox, so it carries a secret the hub itself cannot read
back out of its database: a leaked table gives no valid link. Doing it in the same transaction
as the pending row means a row that rolls back leaves no mail and a mail never names a row that
is not there. A budget of its own keeps an unauthenticated caller who can trigger these mails
from using up the security or notification budgets.

**Rejected alternatives:**
- Storing the nonce: a read of the table would then be enough to complete someone's
  registration, given the password hash is not.
- The registration mail on the sign-in budget: the two are triggered by different requests with
  different limits (§2.7.3 against §2.6.4); one flood would silence the other.

