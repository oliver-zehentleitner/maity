# Authentication

## A call's side effects commit before the endpoint runs, in their own transaction

**Id:** d9800cc1-6d12-481a-a039-f389d758b11b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the authentication slice)

Resolving the caller (`maity_hub.auth.caller.authenticate`) and the side
effects every authenticated call has (`docs/api.md` §2.4) — `last_seen_at`
on the human, the membership, the session and the credential, the
renewal of the caller's leases, the move of its claims to the live
session — run in one transaction that commits before the endpoint's own
transaction starts.

**Reason:** presence and leases say that the caller is alive and working,
which is true whether or not the call itself succeeds: an agent whose
claim attempt answers `already_claimed`, or whose report is refused, has
still been heard from. In the endpoint's transaction an error would roll
the renewal back, and an agent that keeps hitting errors would lose its
leases while it works.

**Rejected alternative:** one transaction per request, side effects
included — one commit fewer per call, but a failed call would then erase
the evidence that the caller is alive.

## A runner caller is confined in one place, before any route runs

**Id:** 1d62b2f2-abdb-4470-91dd-8de0517f21b9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner design review with the coordinating agent, 2026-10-22

A runner credential (`docs/api.md` §15.1) authenticates like an agent's,
and right after authentication `deps._resolve` decides whether the path is
one a runner may call at all: `/runner/*` passes, a `/projects/*` path
answers `not_found`, everything else `forbidden`. `access.membership`
answers `not_found` for a runner as a second line, so a project route
never finds a membership for one.

**Reason:** about seventeen places branch on `caller.kind` as if there
were two kinds (`principal_id`, `access.membership`, the members,
requests and conversations routes): "not human" means agent, "not agent"
means human. A runner reaching any of them would be taken for the other
kind. Excluding it before the route runs makes those branches
unreachable for a runner, instead of correct only where someone
remembered to add a third case. Raising inside the authentication
transaction also undoes the call's last-use update, as the agent's
other-project refusal does.

**Rejected alternative:** a third case in every branch on `caller.kind`.
Each route would have to be right on its own, and a route added later
without the case would serve a runner as an agent or a human.

## An admin agent's members:admin is a path of its own, not the scope

**Id:** 1a2db596-5fb3-48b0-baa9-2cac8372cc3d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** contract #139 (`docs/api.md` §2.3 ᵃ) and the plan agreed with the contract owner, 2026-10-23

`members:admin` stays human-only in the scope table (`scopes.HUMAN_ONLY`),
so every `require("members:admin")` and `may("members:admin")` in the hub
still refuses an agent. `PATCH` and `DELETE …/members/<built-in function id>` take an
explicit path for an agent with the `admin` role (`maity_hub.admin_agents`).
It decides per target and field, and files a `member_change` proposal where
the owner's go is needed. Only the scope list in the resume packet shows
the limited scope (`scopes.listed_scopes`). The human-only refusals answer
`details.reason: humans_only` and are checked before the scope, so the
answer is the same for an agent of any role.

**Reason:** `members:admin` guards joins, runners, attachments,
placements, the member details and `spawn_consent_by`, more than twenty
checks. Granting the scope and narrowing it everywhere would open each
check that is missed; keeping it closed and opening two endpoints fails
closed.

**Rejected alternative:** granting `members:admin` to admin agents in the
scope table and adding a `kind == "agent"` refusal at every other use. The
table would then say more than the hub allows, and each new use of the
scope would have to remember the exception.

## A session shows a public id, named browser and system, and keeps no address once it ends

**Id:** 3a06ee98-93d4-470d-a749-4ec0d5cf5039
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.6.5; the hub owner's notes on the session list (`maity say`, card tsk-bjmkt2akq5dn), 2026-10-23; the implementation, 2026-10-23
**Revisit when:** the hub needs a sign-in history beyond the 90-day account records, or a reverse proxy setup where `net.resolve` cannot tell the client address

`human_session` carries a public id from `ids.new_id` (`hss-…`), never
derived from the cookie's value, which is stored only as its hash. The
browser and the operating system are names from a fixed list, matched
against the `User-Agent` at the sign-in and capped at 64 characters
(`auth.sessions.describe`); the header itself is not stored. `ip` is the
address of the latest call as the trusted-proxy resolution gives it,
and it and `source` (the start address) are set to NULL when the
session ends: by a write for a logout, a revocation, `end-others`, a
password change or a new login in the same browser; for sessions that
expired, one statement clears them all whenever anyone signs in or
reads a session list. The backfill keeps no address for a session that
had already ended. The list shows no `ip` for an
ended session. Existing sessions were backfilled with method `password`
and a fresh public id.

**Reason:** the hub owner asked for the public id, the parsed names and
the end of the addresses (confirmed); the reasons below are this
entry's reading of that. An address is personal data, and a table that kept the
address of every session ever made would be an address history of each
human that nothing needs. While a session is live the address helps its
human tell sessions apart. A name from a list cannot carry a header's
text into the dashboard.

**Rejected alternatives:**
- Keeping the raw `User-Agent`: more detail, but unbounded text from
  the client, and personal data beyond what the list shows.
- Keeping the addresses of ended sessions for the 30 days the list shows
  them: the sign-in record of §2.6.5 keeps where a session started, so
  a second copy is not needed.

## Until the other sign-in methods exist, every session is in good standing and the mail link reports `not_implemented`

**Id:** a6967e81-d77f-45dd-b5ab-dbd5628d7c8a
**Type:** workaround
**Status:** superseded
**Superseded by:** 36284c53-8139-4c41-99c0-9123e9e2c4f2
**Evidence:** inferred
**Source:** docs/api.md §2.6.5, §2.6.6; the implementation of tsk-bjmkt2akq5dn, 2026-10-23
**Revisit when:** the device code (§2.6.2) or the sign-in link (§2.6.3) lands, or account records (§18.1) exist

`auth.sessions.good_standing` is true for a session made by password and
false for every other method; with only the password built, every
session is in good standing. The rules for sessions that are not
(`not_in_good_standing`, `session_too_new`, `end-others` ending only the
others that are not either, the approval chain on `DELETE`) are written
and tested on rows of the other methods already. The marking of a
`session_created` item that grants good standing to those, and the
`created` record in the list (null for now), come with account records.
`GET /admin/settings/sign-in` lists `not_implemented` in `missing`, so
`email_link_available` stays false until the hub serves the link.

**Reason:** the web's session view calls these routes now, so the list
had to come before the methods that make sessions out of good standing.
Saying `not_implemented` is the honest answer while the switch is on and
the mail settings are complete but nothing would send the link.

**Rejected alternatives:**
- Answering `email_link_available` from the setting and the mail
  settings alone, as §2.6.6 reads: it would report a method the hub
  cannot perform.

## A device code's long-poll looks at its row every quarter second, and the device cookie holds one value per human

**Id:** c84e1ec4-84b4-4f1b-a72f-ce33c7939014
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.6.2, §2.6.4, §2.6.5; the implementation of tsk-03ak6rjn2mfd, 2026-10-23
**Revisit when:** device codes get many concurrent waiters, or the hub runs more than one replica

`GET /auth/device-codes/{id}?wait` and `GET /auth/device-login?wait`
read the code's row again every 0.25 seconds until its status changes
or the wait ends. A second long-poll of the same session or pending
cookie takes the key over and the first answers with `superseded:
true`, as §8.3 does for events. The device cookie `maity_device` holds
up to four dot-separated random values, one per human who signed in on
that browser, each stored as `sha256` with its human. A new sign-in adds
a value only when none of them belongs to that human. Codes that die
with their session or with the method switched off become `denied`.

**Reason:** a code lives five minutes, has at most two waiters, and
changes state three times. Reading one row by primary key a few times a
second costs less than a wake path from the committing thread into each
waiter's loop, the way events have one, and a status written by any
thread or a second replica is seen without it. One cookie with a value
per human is what §2.6.5 asks of a shared browser. A single value would
make every second human's browser look new.

**Rejected alternatives:**
- Waking device-code waiters through the events notifier: the codes are
  no events and belong to no project.
- One cookie per human (`maity_device_<id>`): it would put the human's
  id in a cookie name that every request to the hub carries.

## A pending account is confined in one place, and registration waits for the operator's account

**Id:** 3018018e-1537-40d7-afef-661e68fdad90
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of §2.7.5 and §16.4 (docs/api.md), 2026-10-25; review of #381, 2026-10-25

An account that waits for approval is confined in `deps._resolve`, in
the same transaction as authentication and before any route runs, the
way a runner caller is. Only the calls §2.7.5 lists pass (`PENDING_MAY`);
everything else is `account_pending`. The refusal also rolls back the
call's presence side effects.

**Rejected alternative:** a check in each route, or in `human_caller`
alone. Every route added later would need to remember it, and a route
that takes `AnyCaller` would let a pending account through. One place
that sees every human call cannot be forgotten.

Completion refuses with `closed` while no human exists. The instance
admin is still the earliest human (§16), so the first registered account
would otherwise become the instance admin, with `approval: automatic`
at once. With `approval: operator` it would wait for a decision nobody
can make.

**Reason:** the confinement follows the runner's precedent in the same
module. Refusing before the operator exists follows from how
`instance_admin_id` is defined today; it was required in review and is
not stated in the contract itself (inferred). The `account_registration`
row of a deleted account keeps the decision and a rejection's reason,
not the address or the source.

## The login page is offered registration only where someone could finish it

**Id:** 01d0f6ab-e4f6-48c8-9a28-4e89f0b43c35
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's ruling on an empty allowlist, 2026-10-29 (follow-up to #652, card tsk-46vft0764kve); docs/api.md §2.7 "What the login page learns", §16.4; the review of #657
**See:** https://github.com/oliver-zehentleitner/maity — 48c34360-b586-4e82-b21a-737b922f1734 — as of 2026-10-29
**Revisit when:** registration gains a way in that needs no list entry (an invitation is already one, §3.4), or `missing` gains a reason that also makes registration impossible

`GET /auth/methods` answers `registration: true` only when
`effective_mode` is `allowlist` or `open` and `missing` does not name
`allowlist`. So an allowlist with both lists empty answers `false`;
the instance admin sees the gap in `GET /admin/settings/registration`
as `missing: ["allowlist"]`. `POST /auth/register` is unchanged: it
answers `202` and drops the request, as for any address not on the list.

**Reason:** under an empty allowlist every visitor would get the form
and then the silence of a dropped request, a dead end for everyone.
Telling an anonymous visitor that the allowlist is empty reveals no
entry and no account.

**Rejected alternative:** `registration: true` under an empty
allowlist, as the contract first said (the dead end above). Refusing a
`PATCH` that leaves the allowlist empty: §16.4 calls it valid, and an
admin may set the mode before the entries.

## Two-factor sign-in: whether a session must enrol is worked out per call, and the second step re-keys the session in place

**Id:** ff8b8099-8384-4d68-906a-1b4d7b17bc47
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-25 (card tsk-rnchtdn1ffhe; contract `docs/api.md` §2.8)
**Revisit when:** the hub runs more than one replica (the wrong-code counts are in the process), or a role change gains a hook every path goes through

Three choices of the implementation that the contract leaves open:

- **Enrolment is a derived state.** A session stores `full`,
  `second_factor` or `enrolment`, but whether a full session must enrol
  (`required_admins` for an admin or owner, or, once the reset lands, after a reset) is
  computed on every call in the gate (`auth.second_factor.gate`, run in
  `deps._resolve` before any route). So a session the human held when
  the policy was switched on, or when they became an owner, is held at
  enrolment from its next call without anything writing to it, and is
  released the moment the reason goes away — except an enrolment session
  whose human enrolled elsewhere meanwhile, which ends rather than
  becoming full without ever giving a code. The gate refuses inside the
  authentication transaction, as the other-project check does, so a
  refused call leaves no presence behind; for the same reason the gate
  cannot write: a session it has to end is ended by `deps` in a
  transaction of its own before the 401, or the end would be rolled
  back and the session revive.
- **The second step re-keys the row.** Completing a sign-in replaces the
  session's `id_hash` and CSRF token in a conditional update (the row
  must still owe the step), instead of making a new row. The fresh
  cookie value is what the fixation rule asks for; the public id, the
  `approved_by` lineage and `created_at` stay, which the session list,
  "End this session" and the age rules of §2.6.5 read. The conditional
  update is also what makes one of two concurrent verifies win.
- **A code counts only for the factor it was checked against.** The
  check locks the factor's row first (as a confirmation, a reset and new
  recovery codes do, so they wait for one another in one order: factor,
  then recovery codes), and the step is consumed by an update that also
  names the factor's generation and sealed secret. The lock alone would
  serialize on a server database; the condition keeps a code of a factor
  replaced between read and consume from counting even where no lock is
  taken.
- **Wrong codes are counted in the process**, per second-factor session
  (five end it) and per human (ten in 15 minutes lock the checks), like
  every other limit of the hub in V1 (`ratelimit.Limiter`). A restart
  forgets the counts. With several worker processes the limits multiply,
  so the hub runs one worker per process.
- **The admin's reset of someone's factor (§2.8.3) is a decision of its own**
  (the entry below); the step-up of address changes and held approvals is
  in `notifications.md`.

**Rejected alternatives:**
- Writing the enrolment state when the policy or a role changes: every
  path that makes someone an owner or an admin, or flips the policy,
  would have to find and rewrite the human's sessions; a missed path
  would leave a session unrestricted.
- A new session row at the second step: it would lose the lineage and
  the age the standing rules read, or have to copy them.
- Counting wrong codes in the database: one replica is the V1 limit for
  every limiter; a durable count only for this one would buy little
  while the per-address and per-human limits elsewhere stay in memory.

## A reset of a second factor takes effect when the human presses the button; the factor's generation is what kills the other links

**Id:** 7d2b4c9e-3a15-4c6f-8e07-b9a1d5f06c42
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.8.3, §18.6; the implementation of #380, part 2, 2026-10-28
**Revisit when:** the instance audit log exists (a request should be written there, §2.8.3), or the notification mail of `second_factor_changed` is derived and the effect's own mail is checked against it

`POST /admin/users/{id}/second-factor/reset` (`auth/second_factor_reset.py`) writes one row of
`second_factor_reset` and mails the human's verified address a link; nothing about the human
changes. The row's id is the hash of the link's nonce, so the table holds nothing that opens a
link. The page `/mail/second-factor-reset/{token}` (`routes/mail_links.py`, no cookie, like the other
link pages) shows the account, the admin and the reason as quoted text; its `POST` is the effect:
under the factor's row it claims the link with a conditional update of `used_at`, checks that the
link's generation is still the factor's, and then removes the enrolment and the recovery codes
with `reset_required`, moves the generation, ends every session of the human
(`second_factor_reset`) and writes `second_factor_changed {change: reset, by: <admin handle>}`.
The operator's `maity-hub second-factor reset --handle` runs the same effect at once with `by:
operator`. A link is dead when it was used, expired, or the generation moved: a recovery code
that was used, a new enrolment, turning the factor off and another reset all move it, so no list
of links has to be voided. The request is limited to three an hour per human (in process, like
the other limiters) and needs the admin's own step-up; the admin's own account is refused
(`own_account`), a human without a verified address `address_unverified`, an instance
without mail `mail_not_configured`.

**Reason:** the mail proves the mailbox, not the person, so the admin alone must never strip a
factor: the human's button is the second party. Tying the link to the generation reuses what
every change of the factor already does, instead of a second bookkeeping that could miss a path.
Storing only the hash of the nonce keeps a leaked table from holding a link that works. The
effect and the operator's command share one function so that the record, the session end and
`reset_required` cannot drift apart.

**Rejected alternatives:**
- The reset taking effect at the request: the contract forbids it, and a stolen admin session
  would then remove every factor it names.
- Marking the other links of the human as used when one takes effect: the generation already does
  it, in the same transaction, for every way the factor can change.
- Resetting a human who has no factor: nothing would change and a mail would go out for nothing;
  it is a conflict.

## A forgotten password is reset by mail, also where the mail is the second factor

**Id:** 2caa97c3-3a24-401b-a29f-02579a503559
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision on req-s113f1gsd892 (seq 109195, 109226, confirmed in seq 109283, 2026-11-11), docs/api.md §2.10, tsk-pk755085ctff
**Revisit when:** an account is taken over through its mailbox; or passkeys (§2.8) give humans without TOTP another factor to require at a reset

A reset link to the verified address sets a new password (§2.10). With TOTP enrolled the reset
also needs a TOTP or recovery code. Without TOTP the mailbox is enough, and that includes
`second_factor: email`, where the next sign-in's mail factor is the same mailbox again. For those
humans the hub says so and pushes toward an authenticator app: a dashboard banner, a sentence in
the reset mail and one on the reset page. A per-human switch (`email.password_reset`) and an
instance switch (`password_reset`), both on by default, turn it off.

**Reason:** a team instance needs a way back in without an admin for every forgotten password. Under
mail as the second factor the sign-in link is already off (§2.8.8), so without the reset such a
human had no self-service way at all. The maintainer chose the mailbox as enough and a strong
nudge toward TOTP over a gate.

**Rejected alternatives:**
- Under mail as the second factor, no self-service: an instance admin sends the reset mail after
  checking with the person by another channel (as the second-factor reset, §2.8.3). An admin for
  every forgotten password.
- A 24-hour hold, announced in every live session with "Cancel": a human who forgot the password
  usually has no live session, so it mostly delays the honest one.
- No reset at all under mail as the second factor, only the operator: too hard for a team
  instance.
- One switch for the sign-in link and the reset together: the reset is the stronger way in, and
  a human may want the link off and the reset on.
- Reset mails from the sign-in budget (`sign_in_max_per_hour`): the mail factor's mails come from
  it too, so anonymous reset requests could stop them for an hour, and with them the sign-in of
  every human without TOTP. Reset mails got `password_reset_max_per_hour` instead (review of the
  contract PR).
- Wrong TOTP codes at a reset counted only in the per-human limit: whoever holds the mailbox could
  keep guessing with fresh links unreported. Nor per link: four wrong codes on each of several
  links never reach a fifth on any one. The fifth wrong code at resets of one human in 24 hours,
  across links, voids every open reset link and writes `second_factor_failed`, as the sign-in
  step does (reviews of the contract PR). A code under a dead token is neither compared nor
  counted, so a former reader of an old mailbox cannot void the human's new links, and every
  further wrong code in the window alarms again rather than restarting the count. Nor are coded
  resets refused for the rest of the day after the fifth: whoever reads the mailbox could then
  lock the honest human out of the reset for 24 hours with five wrong codes, while voiding and
  alarming keeps a right code working (review of the contract PR).
- Under the instance's `second_factor: off`, a reset that follows the sign-in and asks for no
  TOTP code: the mailbox alone would then set the password of a human who enrolled an
  authenticator app. `off` turns the sign-in step off, not the enrolment the human made, and a
  password outlives a link session. An enrolled human who lost the app gets out through the
  admin's second-factor reset or the operator, since their own removal is refused under `off`
  (review of the contract PR).

## The reset's request limits are buckets of their own, and an empty code is no guess

**Id:** 0e98bef7-6601-4f00-b10c-6c1a4c19222e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.6.4 ("as `POST /auth/email-link`"), §2.10; tsk-tadt2vw7589n; `hub/src/maity_hub/auth/password_resets.py` `RequestLimits`, `hub/src/maity_hub/routes/password_reset.py` `_code_right`
**See:** auth.md#a-forgotten-password-is-reset-by-mail-also-where-the-mail-is-the-second-factor — 2caa97c3-3a24-401b-a29f-02579a503559 — as of 2026-11-12

`POST /auth/password-reset` has the numbers of the sign-in link's request (10 per hour per
source address, 3 per 15 minutes and 10 per day per address and source), counted in limiters
of its own. At `complete`, an enrolled human's call without a TOTP or recovery code is refused
like a wrong code, but neither compared nor counted.

**Reason:** the reset has its own mail budget so that anonymous reset requests stop nothing but
reset mails (2caa97c3); one set of request buckets shared with the sign-in link would undo that
one step earlier, since reset requests from an address would then refuse its sign-in links. A
call without a code is no guess at the factor: counting it would let a client that has not yet
asked for the code, or a mailbox reader who never tries one, spend the human's five wrong codes
of the day and raise the alarm for nothing.

**Rejected alternatives:**
- The sign-in link's own limiters, shared: one kind of request would refuse the other.
- An empty code counted as a wrong one: alarms that say nothing about the factor.

## A human's cookie call renews the leases of the memberships that hold an open claim, and reads no others

**Id:** 659d15cb-6c9b-4e06-8fec-164368951df4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.5; tsk-dfatkddmt565; `hub/tests/test_human_lease.py` and the cost found while measuring `GET /me/conversations` (tsk-45vs1hdzswjs)
**Revisit when:** a human's lease is to be renewed for something other than a claimed card, or a hold (`availability.hold_cap`) is to cover a membership with no claim
**See:** availability.md#a-limit-only-ever-lengthens-a-lease — 98ea3f6d-dbc2-4163-92e2-e2717c794b9b — as of 2026-10-29
**See:** auth.md#a-calls-side-effects-commit-before-the-endpoint-runs-in-their-own-transaction — d9800cc1-6d12-481a-a039-f389d758b11b — as of 2026-10-29

`auth.caller._cookie` renewed, on every request of a human with a session, the leases of all the
human's active memberships: per membership three reads in `availability.hold_cap` (the
membership, the human, the project) and an `UPDATE` of the claimed cards, so four statements
for each project the human is in, whether or not a card was held. A human holds a claim rarely.
Measured with 1 and with 7 projects and no claim: 11 and 35 statements for the sign-in alone;
now 11 and 11. The membership query got an `EXISTS` on open cards whose `claim_holder` is the
membership, and the loop runs over those memberships only, with the same `renewed_lease`, hold
and 24-hour cap as before, so a claim that exists is renewed exactly as it was.
The `EXISTS` and the `UPDATE` must keep the same predicate (the holder and an open status): if
one gains a condition, such as an instance, the other needs it too, or a claim is skipped or a
membership is read for nothing.

**Reason:** the cost was linear in the human's projects on every dashboard poll and bought
nothing, because a renewal with no card to update changes no row. Narrowing the set where it is
chosen keeps §6.5 untouched; nothing the contract says depends on the renewal of a membership
without a claim.

**Rejected alternatives:**
- Renewing at most once a minute per session: it would shorten the visible renewal of a held
  claim and change what §6.5 says an ordinary call does.
- One `UPDATE` for all memberships: the lease length and the hold are per membership
  (`hold_cap` reads the human's and the project's limit and absence), so the reads would stay.
- Caching the memberships of a session: the answer is a function of rows another request can
  change (a claim taken, a membership ended), and a stale set would skip a renewal.

## The mail factor is a second-factor session like TOTP's, with its link and code bound to that session's row

**Id:** 3c5c1c16-9ed6-4c48-8b08-6346159398a5
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §2.8.8 (#925, #930); the card tsk-qawqnetfhn6m and the maintainer's five rules of 2026-10-31 (every new session, TOTP before mail, no sign-in link as first factor, step-up by mail, no silent fallback); the implementation of `auth/mail_factor.py`
**See:** auth.md#two-factor-sign-in-whether-a-session-must-enrol-is-worked-out-per-call-and-the-second-step-re-keys-the-session-in-place — ff8b8099-8384-4d68-906a-1b4d7b17bc47 — as of 2026-10-31
**Revisit when:** a second mailed factor (a passkey recovery by mail, say) needs the same storage, or the mail must be sent from a worker instead of the sign-in's transaction, or code rollbacks without a database downgrade become a supported path, since the limit named below then matters

Under `second_factor: email` the hub does not add a new kind of session: a human without TOTP gets the same `second_factor` session an enrolled human gets, with `via: email` read from the account (`second_factor.via`: TOTP before mail), and a life of 15 minutes instead of 5. The mail goes out in the transaction that makes the session (`second_factor.begin`), through the outbox, so it is sent only if the sign-in commits. The token and the code are stored as HMAC-SHA-256 under `MAITY_MAIL_SIGNING_KEY` on that session's own row (`mail_token_mac`, `mail_code_mac`), not in a table of their own: they are valid only while the session lives, single use by one conditional update that clears both, and a new mail overwrites them, so the earlier link and code die with no further step. `mail_sent` counts the mails of the session (three), taken in the update itself (`mail_sent < 3` in its `WHERE`), so two sends at once cannot both take the third; the human's ten an hour are a limiter. A human who never had a verified address enrols (`must_enrol`); one whose address was verified and is lost (`address_ever_verified`) stops at the second step, where a send answers `409 address_unverified` and an account record `second_factor_failed` `email_unavailable` is written after the commit. Switching the policy away from `email` ends an open mail session at its next call, as switching to `off` does.

**Reason:** a mail factor that lived beside the session would need its own expiry, its own single-use rule and its own cleanup, and every one of them is already the session's. Keeping the secret material on the session row means nothing outlives the sign-in it was for.

**Rejected alternatives:**
- A table of mail challenges: a second life to keep in step with the session's, and a place a code could outlive it.
- Sending the mail after the response, as the sign-in link does: that mail answers an anonymous request and must not reveal whether an account exists; this one goes to a human who already proved the first factor, so it belongs in the transaction.
- The sign-in link's own code and token tables: the same mailbox twice would be one factor, which is why §2.8.8 switches the link off under `email` (not yet built here, see below).

The mail gives no standing of its own (§2.8.2): `sessions.good_standing` counts TOTP and a recovery code as the second factor that confers it, not `email`, which proved the mailbox only. Under `email` a reset does not send a human with a verified address to enrolment (`must_enrol` is false for them whatever the reset flag says): the reset went through that mailbox, and an enrolment on the password alone would let its holder install their own app; the operator's reset sends only an account without a verified address there. An enrolment session that the policy now asks a second factor of ends instead of becoming full (`state` asks `asks`, not only `enrolled`). A mailed code lives 15 minutes from `mail_sent_at`, in a full session that steps up as in a second-factor one, and the wrong codes of a session are counted over the longest session life, 15 minutes.

The session's three mails count for a second-factor session only; a full session that steps up is held by the hour's ten alone. The hour's ten are counted after the update that stores the mail, so the loser of a race for the third mail spends none of them; two sends at once may pass the check together and go one over, which the session's three still bound.

**Turning it on:** the code that confirms `email` lies on the admin's session row like a step-up's, under a MAC domain of its own, so neither code does the other's work; a nonce in the instance setting `sign_in.second_factor_pending` is part of the MAC, so a newer `PATCH` by any admin voids every open confirmation. A confirmation table was rejected: it would need a migration for what the session's row and one setting already hold.

**No way to lock yourself out:** the confirmation checks the mail settings and the admin's verified address again, since both can change in its 15 minutes. Under `email` removing the verified address is refused without TOTP, also when a held removal is approved, and turning TOTP off is refused without a verified address: either step alone looks harmless, and together they leave the human at a second step nothing can complete.

**Downgrade:** the `downgrade()` of `20261031191500_mail_factor` refuses while `sign_in.second_factor` is stored as `email`, so the operator switches first and rule 5's silent drop cannot come from a database downgrade. **Known limit:** a rollback of the code alone, with the database left as it is, cannot be refused, since old builds cannot be changed: a build below #943 reads the value as unknown and falls back to the environment's policy, and a build from #943 up to this change keeps `email` with the sign-in link on, which breaks rule 3. Switch away from `email` before such a rollback.

## A request run again after a deadlock is still the first user of its nonce

**Id:** 05c462cb-0a99-41e7-98d3-c226c085a697
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-q18vgx41yr5f, from a note of the #92 review; checked on 2026-11-01 by injecting a transient failure after the nonce is spent
**Revisit when:** the process's nonce window goes away, or SQLite and MariaDB keep their nonces in the database as PostgreSQL does

`NonceWindow` remembers which request spent a nonce (`RequestFacts.request`, one object per request),
and the same request counts as the first again. On PostgreSQL nothing changes: the nonce is a row in
the transaction, and a retry's rollback takes it back.

**Reason:** `retrying` runs the whole authentication again, and the nonce is spent before it ends. The
process's window is not part of the transaction, so on SQLite and MariaDB a deadlock in the
authentication's side effects answered `401 nonce_reused` to a request that had done nothing wrong,
which defeated the retry on signed requests. Only the object is compared and only the object is kept, so
the window holds nothing of the request.

**Rejected alternatives:**
- Giving the nonce back when the attempt fails: between the failure and the repeat a replay of the same
  request would count as the first, and every path out of the transaction would have to do it.
- Spending the nonce after the commit: two copies of a request could both authenticate before either
  spends it.
- Moving the nonces into the database on every engine: a table and a write per signed request on the
  engines that run one replica, for what one comparison solves.


## A sign-in's confirmation is stored on its session, carried over from the read marks once

**Id:** f5611a2e-9219-4e5e-a816-5700da32a47c
**Type:** decision
**Status:** active
**Evidence:** confirmed

"This was me" (`POST /auth/sessions/{id}/confirm`, §2.6.5) writes `confirmed_at` and
`confirmed_by` on the confirmed session's `human_session` row. `sessions.good_standing` reads
the row alone: password or registration, a TOTP or recovery-code second factor, or
`confirmed_at`. Since tsk-0baaez2895sb a new sign-in is no bell item at all (§2.6.5, root
`context/notifications.md` feb34f93): the confirm marks nothing read, and no read mark of a
`session_created` record is written any more. The migration
`20261103100000_session_confirmed` carries over every `session_created` record that a session
marked read (`read_by` set) as a confirmation at that read's time by that session. Before, only
an allowed session could mark one, so each such mark was a confirmation. A record read without
`read_by` confirms nothing. The carry-over is one `UPDATE … FROM account_record`, joined on the
record's `session_id`, because the column change holds an exclusive lock on `human_session`
until the migration commits.

The confirm checks run in one transaction. A target not yet in good standing is confirmed by a
conditional `UPDATE` on `ended_at IS NULL`; then every target, in good standing or not, is read
again with a row lock (`SELECT … FOR UPDATE`), and if it ended meanwhile the call is
`not_found` with nothing confirmed. A concurrent `DELETE` therefore either waits and
ends a confirmed session, or leaves the confirm `not_found`. A target already in good standing
keeps its standing as it is; only its liveness is held.

Who may mark a security item read is `listing.refusal`. Only `email_address_changed` is
guarded; every other security kind may be marked from any session (§18.3). `not_earlier` is
checked before `not_in_good_standing`, in the confirm's order, and each skipped item is answered
in `skipped`.

The bell leaves new sign-ins out where it reads its records: `records.SECURITY` no longer holds
`session_created`, so the list, the counts and the pinned block never read one, and records
written before the change, read or not, drop out the same way without a migration. The mailer
alone asks for them (`items.derive(sign_ins=True)`), for the sign-in mail of the `security`
mode, which stays. `sessions_rev` (§18.2) is `acr-<n>` of the newest live `session_created` or
`session_ended` record (`records.sessions_rev`), the number the session list already gives as
`created.record`; a held long-poll also answers when it moves, though it lists no item; a
session record already past `after` when the request comes answers at once, as an item past
`after` does, so a sign-in between two answers is not seen only after the full wait. A confirm
writes no record and so moves nothing: another tab's banner of that sign-in goes at its next
read of the sessions, not at once.

The pinned block (`items.pinned`) reads the unread security records alone, newest first, up to
50. Security items come only from account records, so it reads no project's events. The 50 are
taken in SQL, so the records that give no item (a forge access that went, §18.1) are left out
in SQL too (`items.records_without_item`): counted against the limit, 50 newer ones would hide
an older alert that `counts.security` still counts. A session
moved into enrolment (§2.8.5) keeps `GET /me/notifications`, `POST /me/notifications/read` and
the confirm only while its sign-in was complete and it is in good standing; a fresh enrolment
sign-in keeps none of them.

**Reason:** with the confirmation derived from the record's read flag, any change to how items
are read changed who is in good standing, and an expired record silently took the standing
away. A column on the session makes standing one row's fact, readable where the session is read,
and lets the bell mark alerts read without touching it.

**Rejected alternatives:**
- Keeping the derivation from `account_record.read_at` and adding a separate "read only" flag:
  two flags on the record for one decision, and the standing still depends on a record that
  expires after 90 days.
- Carrying the old read marks over as `confirmed_at: null` with good standing kept another way:
  the session list could not say when or by whom such a session was confirmed, although the
  record holds both.
- Carrying the read marks over one `UPDATE` per record: every sign-in waits on the exclusive
  lock for N round trips (measured on PostgreSQL: 50 000 marks, 9.9 s).
- Holding only the target that still needs confirming: a target in good standing then had no
  liveness check, and a concurrent `DELETE` and the confirm both answered 200 with the alert
  marked read on an ended session (shown on PostgreSQL in review).
- Refusing to mark the alert of a session whose row is gone (the old behaviour): such an alert
  could then never be cleared until its record expired, the very thing the bell change set out to
  end. Moot since card tsk-0baaez2895sb: a sign-in is no bell item, so there is no such
  alert to mark.

## A password attempt takes its place in the count before the compare; the known sources' fingerprints are keyed from the lock's first-use pepper

**Id:** d12ec062-8d9e-4357-916a-a2f1a1bc3bd1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.1 and §2.8.6 (count before compare, keyed fingerprint), root `context/sign-in.md` 01029c7f; the review of the contract PR, which pointed at the lock entry below for the pepper
**See:** notifications.md — 25f27b8d-6405-400f-b2f0-c561a4dce360 — as of 2026-11-05

Every bucket of wrong passwords (`auth/password_limits.py`) records the attempt first, the
compare runs, and a right answer gives its place back. The password change, the
re-authentication, the address change and the second-factor check do it through
`ratelimit.Attempt` (`place`, then `release`); the login's two buckets, per account and per
account and source, use `place` and `release` directly in `LoginAttempt`, because a refusal there
depends on the source. `LoginAttempt` places in both login buckets and refuses with `email_link` or `password_paused` when the account's bucket is full and the
source is not a known one or has spent its own five. An address of no account counts in a bucket
keyed by its fingerprint, never the address or a plain hash.

`known_source` holds an HMAC-SHA-256 of the source address per human. Its key is derived by HKDF
(purpose `sign_in.known_source`) from `MAITY_SECRET_KEY`, or without one from the per-address
lock's pepper `address.lock_pepper`, which `addresses.prepare` makes at first use; the login
runs `prepare` before its transaction. Until the pepper exists, no source is remembered or known.
`sessions._signed_in` remembers the source, so every completed sign-in counts, whatever its
method.

**Reason:** checked first and counted after a wrong compare, as before, parallel attempts all
pass the check and the limit is a suggestion: five in the window must mean five. The pepper is
the lock's because a row a migration makes is gone after the table is emptied and nothing makes
it again (the lock entry's reason), and the first-use pepper already exists on every hub that
has locked an address; a derived key per purpose keeps the two uses apart. One class for every
kind of attempt does not fit the login, which places in two buckets and refuses on their
combination.

**Rejected alternatives:**
- A pepper of its own made by the migration of `known_source`: written first, it failed the
  lock entry's reason; the contract review caught it before the hub PR.
- A pepper of its own made at first use: a second `prepare` before the transaction of every way
  of signing in, for a value one HKDF step gives from the existing pepper.
- A plain SHA-256 of an unknown address as its bucket key: guessable, as the lock entry says of
  lock rows.

## A known source's fingerprint is deleted by a sweep at 30 days, not only when someone signs in

**Id:** 4c40c003-542f-4884-8975-08fa04925ec0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.1 ("A fingerprint goes 30 days after its last sign-in and with the account"), the review of the hub PR of the sign-in hardening
**See:** auth.md — d12ec062-8d9e-4357-916a-a2f1a1bc3bd1 — as of 2026-11-06

A row of `known_source` is deleted 30 days after its last sign-in by `known_sources.Worker`,
which runs `forget_old` every hour on its own (one pod per pass, `worker_runs`), and
`known_sources.remember` still deletes the old rows when a sign-in completes. `known_sources.known`
already ignores a row past 30 days, but ignoring is not deleting.

**Reason:** the contract promises the fingerprint goes after 30 days. A delete that runs only
inside a sign-in leaves a source's pseudonym in the table for as long as nobody signs in, which
on a quiet hub, such as one person's, is for ever; the check in `known` hides the row, it does not
remove it.

**Rejected alternatives:**
- Deleting only inside `remember`, the first form of the PR: the retention above.
- Relying on `known` to ignore old rows: the same retention, and a copy of the database shows the
  pseudonyms.


## The session sweep `forget_expired_addresses` gets no index until prod numbers show its cost

**Id:** 87cd9a5c-af3b-4a06-a007-6898feadc9f0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the measurement on tsk-6srccd2r1h62 (step 1, local PostgreSQL), the lead's decision on its PR 4
**See:** events.md — 483be046-dbf5-4c2f-a9d4-cc18dfb09469 — as of 2026-11-09
**Revisit when:** the `maity_hub.timing` line of a prod password login or session list shows a `db_ms` worth a look; the line is the request's total over all its statements, so the sweep's share needs a statement-level measurement on prod data (EXPLAIN ANALYZE of the sweep) before an index is built

`auth/sessions.forget_expired_addresses` is one UPDATE over the sessions of every human on the
instance: `ended_at IS NULL`, past `expires_at` or idle past `SESSION_IDLE`, with an address or a
source still set. It runs on every password login (`POST /auth/login`, `routes/auth.py`) and
every session list (`sessions.listing`); the device-code and mail sign-ins do not call it. It has no `human_id` filter, so no index on the human serves it. Run
through EXPLAIN with `enable_seqscan=off` on local PostgreSQL, it was the one statement of the four
measured routes with no index path: a scan that grows with all sessions on the instance. No index
was added.

**Reason:** the one index that would serve the sweep's filter without also covering the ended
sessions is partial, and a partial index is not portable to MariaDB: the hub has none (no
`postgresql_where` in `tables.py` or the migrations). A PostgreSQL-only index would split the
schema by dialect and leave MariaDB and SQLite on the scan. A plain index over `ended_at` and the
two times is portable, but locally the whole session list spends about 2 ms in the database over
its 17 statements, the sweep included, and only prod has the session counts that could make the
sweep matter. So it is built when prod numbers show the cost, not
before.

**Rejected alternatives:**
- A partial index on open sessions (PostgreSQL): the dialect split above.
- A plain index now, without numbers: a migration and a write cost on every session row, for a
  cost not shown.

## Presence and a session's address are written at most once a minute, not on every call

**Id:** dea949c1-d5ec-4781-b618-884abfd151d0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions on req-79cbqd7dcpps (seq 109161, 2026-11-11) and on req-xkwfa78akg93 (2026-11-11, "never early"), docs/api.md §2.4, §2.6.5 and §5.3, `seen.SEEN_EVERY`, `seen.latest_call`
**Revisit when:** presence (§5.3) reads against a window shorter than 120 s, a reader needs a `last_seen_at` or session `ip` fresher than a minute, or a new reader turns `last_seen_at` into a state without `seen.latest_call`

Every authenticated call used to write `last_seen_at` on the session and on the member or human,
and a human session's `ip`: two or three UPDATEs, with their row locks, on every request. The hub
now writes them only when the stored `last_seen_at` is at least `SEEN_EVERY` (60 s) old; the
condition sits in the UPDATE's WHERE, so two calls racing in the same minute write once. An agent's
claim leases still renew on every call, since a lease is not presence. A human cookie call that
wrote nothing still checks that the session is open and alive, so a session ended within the
minute is refused. A completed sign-in writes the human's `last_seen_at` as a call does.

The latest call then lies anywhere from the stored time to a minute after it, so no reading of the
stored time is exact. Every reader that turns it into a state reads it from `seen.latest_call`, a
minute after it: membership presence (`views`), the landing's people online, a session's idle
end (`session_alive`, the cookie update, the address sweep) and the digest's stalled holder.
`online`, `away`, the stalled holder's threshold and the idle end come up to a minute late after
the last call, never early (§2.4, §5.3). The jour fixe's minutes online and its instance choice
read an instance's latest call from its credential's `last_used_at` instead, which every call
writes, as the instances' presence always has.

**Reason:** the writes were most of the per-request database work on the auth path. With them
gone, a reader must err one way: a caller shown away, expired or stalled while it still calls, or
a state that holds up to a minute longer after the last call. The maintainer chose the second, so
that a member that calls is never shown away.

**Rejected alternatives:**
- Writing on every call: the per-request UPDATEs and row locks above.
- Reading the stored time as the latest call: a member that called 62 s ago showed `away` (a
  write at T, a call at T + 59 that wrote nothing, a read at T + 121), and a session in use could
  expire up to a minute early.
- Other options of the first request: unknown.

## The credential filter has no boundary in front, and reads a JSON body's decoded strings too

**Id:** d539d36c-45e7-4178-8428-835e67549e0f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-bg5f4cv0894w (credential filter hardening), 2026-11-13
**Revisit when:** a body arrives in an encoding other than JSON that can escape characters, or the filter's matches start revoking credentials nobody leaked

`credentials.PATTERN` (§2.2) matches `mty1.<id>.<secret>` whatever
character stands right before it, and `find_all` scans a JSON body twice:
the raw bytes, and every key and string value it decodes to. The CLI's
check before sending (`sign.CREDENTIAL_IN_TEXT_RE`, `hub._guard_payload`)
does the same, so it refuses what the hub would refuse.

**Reason:** with a word boundary in front, a credential right after a
letter, a digit or `_` did not match, and in a JSON body that includes
every escape that ends in a letter: the `n` of `\n`, the `t` of `\t`.
Dropping the boundary costs nothing in safety: a match is refused, and
only a credential whose secret verifies is revoked, so a false match
only refuses a request. Escapes such as `\u006d` change the bytes of
the credential itself, which no pattern over the raw bytes can see.
Reading the decoded strings catches them. The body is decoded as the
app's JSON parser decodes it (`json.detect_encoding`: a UTF-8 byte
order mark, UTF-16 and UTF-32), since a body the app reads as JSON
but the scan does not would carry an escaped credential past it.

**Rejected alternatives:**
- Keeping the boundary and scanning only the decoded strings: a
  credential right after a letter in plain text, or in a body that is
  no JSON, would still pass.
- Scanning only the decoded strings: the raw scan is what covers a
  body that is not JSON, or JSON that does not decode, and the query.

## Anonymous mail requests are capped per recipient, and limits per source address count an IPv6 client by its /64

**Id:** ad4dc104-7b44-4049-a9e4-ebcf7aef9dd2
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.5, §2.6.4, §2.7.3; tsk-q4zynccy5t0b; `hub/src/maity_hub/net.py` `Origin.limit_key`, `hub/src/maity_hub/auth/email_links.py` `recipient_over`
**See:** auth.md#the-resets-request-limits-are-buckets-of-their-own-and-an-empty-code-is-no-guess — 0e98bef7-6601-4f00-b10c-6c1a4c19222e — as of 2026-11-13

`POST /auth/email-link`, `POST /auth/password-reset` and `POST /auth/register` each keep, beside the pair limits, a silent limit per recipient keyed on a digest of the normalised address alone: 5 mails per hour and 20 per day, in buckets of each path's own (registration's day limit of 20 was already there, now under a digest key). A request counts there only once its pair limit let it through. Every limit keyed on the caller's address takes `Origin.limit_key`: an IPv4 address as it is, an IPv6 address as its /64, an IPv4-mapped address as its IPv4; the session's address, a mail's text and the known sources keep the whole address.

**Reason:** the pair limits bound one source, not the mails one address receives from many. Counting only what the pair limit passed keeps a single source from spending the address's own budget. One bucket per path keeps the reset and the sign-in link apart as before (0e98bef7). A /64 is what one IPv6 client is usually given, so a limit per full IPv6 address would count one client as many.

**Rejected alternatives:**
- One recipient bucket shared by the three paths: requests of one kind would refuse the mails of another.
- Counting every request against the recipient, refused by the pair limit or not: one source alone could then stop the address's mails.
- /56 or /48: wider prefixes put unrelated customers of one provider into one count; /64 is the smallest prefix a client is commonly handed whole.

## The in-process limiter keeps its keys in order of their newest attempt and forgets idle ones from the front

**Id:** 6112b6e6-f3b7-481b-911e-d6bab311242d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** tsk-q4zynccy5t0b; `hub/src/maity_hub/ratelimit.py` `Limiter._prune`

`Limiter._hits` is an `OrderedDict`; an attempt moves its key to the end, and every take first drops keys from the front while their newest attempt is outside the window. Each attempt costs the keys it forgets and one look more. A key whose newest attempt was given back (`release`) may stay behind a live key a little longer.

**Reason:** a pass over every key once more than 1024 were live cost each attempt time in the number of keys, exactly when many keys are live.

**Rejected alternatives:**
- Prune at most once per N calls or per part of the window: bounded on average, but memory still grows between passes and the pass itself stays a scan of all keys.

