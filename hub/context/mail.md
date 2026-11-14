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

## The test send counts against no budget, defaults to the admin’s verified address, and `last_test` is cleared only by a real change

**Id:** 30b4ad58-6913-49fd-b6a4-ed0a20bbee4e
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.2, §16.3, §18.4; the implementation of tsk-gwft8fzazd6w, 2026-10-23
**Revisit when:** the notification address states or the test-send recipient contract change

`POST /admin/settings/mail/test` writes `last_test` and nothing to
`mail_delivery`, so it moves none of the counters. Without `to` it uses
only the calling admin's address with status `verified` from the notification
settings (§18.4), never a pending replacement or a disabled address. Without
that address it is `invalid` (`to: no_verified_address`). An explicit `to`
still wins. The former missing-address-store constraint is resolved now that
the notification settings exist. A `PATCH` clears `last_test` only when a connection
field (`host`, `port`, `tls`, `username`, `password`, `from`) has a
different effective value afterwards, not whenever one is in the body.

**Reason:** a test is none of the three kinds of mail whose budgets the
counters show, and counting it would make `failed_last_hour` report the
admin's experiments as delivery failures. Reading the caller's notification
settings implements §16.3's default without trusting a pending replacement;
refusing remains what §16.3 says for "no `to` and no verified address". A dashboard
that sends its whole form on every save would otherwise wipe the last test with an unchanged value.

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
back out of `pending_registration`: a leaked copy of that table gives no valid link. The mail's
own row in `mail_outbox` does hold the link until the mail is out, and loses its text then (the
outbox entry above). Doing it in the same transaction
as the pending row means a row that rolls back leaves no mail and a mail never names a row that
is not there. A budget of its own keeps an unauthenticated caller who can trigger these mails
from using up the security or notification budgets.

**Rejected alternatives:**
- Storing the nonce: a read of the table would then be enough to complete someone's
  registration, given the password hash is not.
- The registration mail on the sign-in budget: the two are triggered by different requests with
  different limits (§2.7.3 against §2.6.4); one flood would silence the other.

## The registration's link page is a router of its own, and answers each refusal with the status of what refused

**Id:** 5c1d7e0a-2b64-4f0e-9a38-71d0b6f4c2e9
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.7.1 steps 5 and 6, §2.7.2, §2.7.3, §18.6; the implementation of tsk-sbxts7s5990v, part 5b, 2026-10-28
**Revisit when:** the sign-in link page (§2.6.3) lands and the two form cookies want one helper, or the dashboard takes over the form

`routes/register_page.py` serves `GET` and `POST /mail/register/{token}`; `routes/mail_links.py`
stays the pages that set and read no cookie. The `GET` sets only `maity_form` (a random value,
`Path=/mail/register`, `HttpOnly`, `SameSite=Strict`, ten minutes) and puts the same value in a
hidden field; the `POST` needs both to match and a `Sec-Fetch-Site` of exactly `same-origin`, so a
request that does not say where it comes from is refused as well (the rule of §2.6.3's sign-in
page). The terms version the person saw travels in a hidden field the hub signs with the
registration's nonce, so a version from another registration, or a forged one, counts as none
seen and asks for a fresh confirmation. The completion itself is `registration_accounts.complete`
unchanged; the page maps its result to a status: a form error or wrong password `400`,
terms that changed `409`, registration closed since the mail `403`, the hourly cap `503`, a link
that no longer works `404` and one page for every reason. Every `POST` counts against the login
limit of its source address (§2.7.3 shares them). The pages carry `Referrer-Policy: no-referrer`
and `Cache-Control: no-store`, the request log masks the token, and the cookies are set only on
success, the way the login sets them, with the form cookie removed. The completion is a sign-in
like the login: the browser's earlier session ends (§2.6.5), the new session is made by
`sessions.create` (its account record, `last_login_at`, the password given as `password_at`), and
the device cookie is set; `method: "register"` counts as signed in by password for the good
standing, since the password was given at the completion. The terms version is asked first, so
terms set or changed while the page was open say so before any other error.

**Reason:** a page that sets a cookie and reads a form is not the page of a link that must set and
read none, so mixing them would loosen the contract of §18.6 for the unsubscribe and verify
pages. Binding the terms version to the nonce makes the signed field useless on another
registration. Statuses that tell a browser, a proxy and a test what happened cost nothing here:
the person sees the same words either way, and only a person who proved the mailbox and the
password sees an error that depends on an account (a taken handle).

**Rejected alternatives:**
- One `POST` that answers JSON for the dashboard to render: §2.7.1 puts the page outside the API
  and the link must work from a mail on any device, with no script.
- Accepting a `POST` without `Sec-Fetch-Site`: an older browser could then be made to submit the
  form from another site; the cookie alone is a second guard, not a reason to drop the first.

## The registration's link page wears the legal pages' shell, not the dashboard's app

**Id:** f63430e9-d5ca-430e-afef-d44ec980bd35
**Type:** decision
**Status:** superseded
**Superseded by:** e3267520-bfef-40e3-aa6f-17cecd17147c
**Evidence:** inferred
**Source:** the card tsk-7sw2a2bd5srp from the coordinator, 2026-10-31: the maintainer, testing the registration live, found the page bare HTML (no stylesheet) and asked for the legal pages' shell; docs/api.md §2.7.1 and §16.7.1. Why not the app and not the landing assets is this entry's reading
**Revisit when:** the dashboard takes over the form, or the legal pages move to the landing page's stylesheet and fonts

`render.form_document` gives the page the legal pages' head (the Maity mark), their colours in light
and dark, one centred panel and a footer with the legal links the instance serves; its style is the
legal pages' `STYLE` plus a few rules for fields, errors and the button, all inline. Each field's
error stands under it, tied to the field (`aria-invalid`, `aria-describedby`). The answers carry
the legal pages' policy, `default-src 'none'; style-src 'unsafe-inline'`, with `form-action 'self'`,
`base-uri 'none'` and `frame-ancestors 'none'` for a page that posts a password.

**Reason:** the page is the first a new person sees after the mail, so it should look like Maity,
and it has to keep what §2.7.1 asks of it: the token is in the address, so nothing may be loaded
from elsewhere, and no script runs before there is an account.

**Rejected alternatives:**
- The dashboard's single-page app: a script before the account exists, and an app that would
  read the token from the address.
- The landing page's stylesheet and self-hosted fonts (the card named them): the legal pages
  this shell copies use the system fonts and one inline style, so the page would look unlike
  the pages it links, and it would need its policy widened for the hub's own fonts and sheet.

## The account mails of registration and the invitation's mail are queued only while mail is ready, in English, tied to an account only where one holds the address

**Id:** 158a003c-a0d6-4ac3-a2b7-eb407292b247
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §2.7.5, §3.4, §16.2, §18.5; implementation of the `TODO(#280)` mails (tsk-pb3vs6d65800) and its review (#776), 2026-10-30
**Revisit when:** the registration keeps the person's language past the confirmation, or the security budget is counted per recipient

The approval, rejection and expiry mails of registration (`registration_accounts._mail`) and the
invitation's mail (`invitation_mail.send`) are queued only when mail is complete and enabled
(`registration.mail_ready`), as the security mail of the outbox otherwise is not: without mail a
decision queues nothing. Each is queued in the deciding transaction on the `security` budget, which
is counted per instance and kind (`mail_budget`), not per recipient; "the recipient's security
budget" of §3.4 is that budget. A rejection's or an expiry's mail has no `human_id`: the account and
everything it made are deleted in the same transaction, and the address was read before. The
invitation's mail is tied to an account only where one holds the address as verified (or disabled),
so a disabled address stops it as it stops that account's other mail (§18.7); most often nobody
holds it yet. The texts are English: at the decision the hub no longer knows the person's language,
which only the pending registration kept. What the hub did not write (the operator's reason, the
inviter's and the project's names, the note) goes through `mailer.defang` and `mailer.quoted`, so
the only links are the hub's own (§18.5).

**Reason:** a mail held while mail is off would go out when someone switches mail on, possibly
weeks after the decision, about an account that may be gone. The contract says that without mail
the inviter passes the link on; the account mails follow the same rule so the two never differ.

**Rejected alternatives:**
- Queue them whatever the mail setting says, as the outbox holds every mail while mail is off:
  delivers stale news once mail comes back.
- Mail in the registration's language: the account registration does not keep it; keeping it would
  need a column and a migration for four mails the card asked to have in English.

## The registration's link page stands in the frame of the pages without a session, like the sign-in link's page

**Id:** e3267520-bfef-40e3-aa6f-17cecd17147c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-tp97v64vpy5z, PR 4, as lotse#wtwy split it (2026-11-13): the registration link page and the maintenance page go into the door frame; `routes/register_page.py`, `render.door_document`. The reasons are this entry's reading of the sign-in link page's entry (email-links.md, 89e8318d)
**Revisit when:** the dashboard takes the form over, the page needs a script, or the dashboard's `/login` gets the product line back

`GET /mail/register/{token}`, its refusals and its dead-link page are drawn by
`render.door_document`, as the sign-in link's page is: the landing page's header and footer around
the door of `public-pages.css`, the form in the form's column. The form keeps its fields, its
errors under each field (`aria-invalid`, `aria-describedby`), its signed terms version and its
statuses; the legal links that stood under it are the frame footer's Legal column now, so the page
has no links of its own and no words for them (`register_page.legal_*` are gone). The answers carry
`render.DOOR_CSP` and `Referrer-Policy: no-referrer`, with `Cache-Control: no-store` as before.
`render.form_document` and its inline style are removed; nothing else used them.

**Reason:** the page is the step after the mail on the way into the dashboard, and every other page
a person reaches without a session (`/login`, `/register`, the sign-in link, §18.6) already stands in
this frame. The old shell looked like the legal pages as they were before they took the landing
stylesheets (landing.md, dde46a41), so it had become the one page unlike its neighbours.

**Rejected alternatives:**
- Keep the legal pages' old shell (mail.md, f63430e9): unlike every page around it.
- The product line under the frame's footer: the framed pages end with the frame's footer
  (email-links.md, 89e8318d).


## The mail factor's mails have a budget of their own, `second_factor_max_per_hour`

**Id:** 443bdca8-64b0-4a07-9ea5-daf368945d35
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.8.8, §16.2; tsk-q4zynccy5t0b; `hub/src/maity_hub/mail/outbox.py` `BUDGETS`, `hub/src/maity_hub/auth/mail_factor.py`
**See:** auth.md#a-forgotten-password-is-reset-by-mail-also-where-the-mail-is-the-second-factor — 2caa97c3-3a24-401b-a29f-02579a503559 — as of 2026-11-13

The mail factor's links and codes, and the confirmation code that turns `email` on, go into the outbox as kind `second_factor`, counted against `second_factor_max_per_hour` (default 60, `MAITY_MAIL_SECOND_FACTOR_MAX_PER_HOUR`) with `second_factor_sent_last_hour` and `second_factor_dropped_last_hour` beside the other counters. Over it a mail is dropped, never held, as for the other kinds that answer a request: a late code is useless. `mail_outbox.kind` and `mail_budget.kind` are free `String(16)` columns without a check, so the kind needed no migration.

**Reason:** each kind of mail is counted on its own so that no kind's volume stops another (§16.2), and a human without TOTP cannot finish a sign-in without this mail. The reset's budget was split off for the same reason (2caa97c3); this finishes the split.

**Rejected alternatives:**
- Keep the factor's mails on `sign_in_max_per_hour`: the sign-in link's mails and the factor's would share one hour.
- Held over budget like security mail: a code that arrives after its 15 minutes helps nobody.

## Mails anyone can send to an address have budgets of their own and wait over them: verification and invitation

**Id:** d3113259-e9eb-4321-8a8a-70080feaf52b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §16.2, §3.4, §18.4; tsk-q4zynccy5t0b and the lead's ruling on it, 2026-11-14; `hub/src/maity_hub/mail/outbox.py` `BUDGETS`, `DROPPED_OVER_BUDGET`
**See:** mail.md#the-mail-factors-mails-have-a-budget-of-their-own-second_factor_max_per_hour — 443bdca8-64b0-4a07-9ea5-daf368945d35 — as of 2026-11-14

An address verification mail is kind `verification` (`verification_max_per_hour`) and an address-bound invitation's mail kind `invitation` (`invitation_max_per_hour`), both default 60, each with its `…_sent_last_hour` and `…_queued` counters. Over its budget such a mail waits for the next hour, as security mail does; it is never dropped. The security budget is left to mail about the account's own security.

**Reason:** any account can ask for verification mails and any project's admins can send invitations, to any address and from as many projects as they hold; on the security budget they could hold real security alerts back for hours. Unlike a sign-in code, a verification link and an invitation stay useful for a day, so waiting beats dropping.

**Rejected alternatives:**
- Leave both on the security budget with only the per-project and per-human limits: those bound one source, not the sum over many projects or accounts that fills the budget.
- Drop them over budget like the anonymous kinds: the invitee or the human would get nothing, with no sign why, for a link that would still have worked hours later.
- One shared budget for the two: invitations sent in bulk would stop a human's own address confirmation.
