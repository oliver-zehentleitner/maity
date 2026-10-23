# Mail

## Mail settings as one row per admin-set field, the counters from a delivery table, the conversation on the standard library

**Id:** 2b0a92f1-f958-4945-b49f-58f0e294a7b6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.2, §16.3; the hub card for mail settings and the test send (tsk-gwft8fzazd6w), 2026-10-23; its implementation, 2026-10-23
**Revisit when:** the hub runs more than one replica and sends mail from each, or a field of §16.2 needs a value the JSON column cannot hold
**See:** https://github.com/oliver-zehentleitner/maity — d2d3356f-7a73-4e77-ac7c-3e04b07c2517 — as of 2026-10-23

`mail_setting` holds one row per field the instance admin set through
`PATCH /admin/settings/mail`, keyed by the field's API name, the value
as JSON; `null` in a `PATCH` deletes the row, and a missing row means
the environment's value or the default. The answer's `source` is read
off that: environment first, then a row, then the default. The SMTP
password's row holds only the sealed value (`maity_hub.secretbox`,
field `mail.smtp_password`), and `last_test` lives in the same table
under its own key. The counters
of §16.2 count rows of `mail_delivery` (budget kind, outcome, time; no
address and no content) over the last hour; `security_queued` counts
the security rows still `queued`, however old. The SMTP conversation is
`smtplib`, driven step by step (`maity_hub.mail.smtp`) so that each
stage of §16.3 is its own exchange, inside one 20-second deadline.

**Reason:** a row per field makes `source: "admin"` a fact of the
database instead of a second flag beside each value, and a new field of
§16.2 needs no migration. Counters in the database survive a restart,
which the hourly budgets must, and stay right if a second replica ever
sends; the sending itself (notifications, sign-in mail) writes the rows,
so this table is created with the settings that read it. `smtplib`
gives every command and its reply separately, which the stage names
need, and the routes are synchronous already.

**Rejected alternatives:**
- One settings row with a column per field: each field of §16.2 becomes
  a column and a migration, and "set by the admin" would need a flag per
  column to tell a stored default from no value.
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
`invalid` (`to: required`): the contract's default, the admin's own
verified address, does not exist in the hub until the notification
settings are built. A `PATCH` clears `last_test` only when a connection
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
