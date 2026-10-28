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
- **The admin's reset of someone's factor (§2.8.3) is not in this change.**
  The table and column for it exist; part 2 of #380 adds the route, the
  confirmation mail and `maity-hub second-factor reset`. Step-up for
  address changes and held approvals is wired when those routes exist
  (card tsk-9z1m4tcz1e98).

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
