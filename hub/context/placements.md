# Placements

Why the hub's placements (`docs/api.md` §15.5–15.7) behave where the contract left a
choice. The rules themselves are in `maity_hub/placements.py` and the contract.

## A preset change keeps who may start agents and how many

**Id:** 8ed2416d-faf2-4523-99cd-2ac370694500
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation of placements, 2026-10-22; confirmed by the contract owner the same day, written into `docs/api.md` §6.1

Changing `policy.preset` refills the policy fields from the preset, except
`signing`, `spawn_requests` and `max_placements` (`policy.KEPT_ON_PRESET`).
Every preset fills `consent` and 8 when a project is created.

**Reason:** a preset is chosen for how cards and reviews work. Refilling
`spawn_requests` would quietly move a project from `off` to `consent`,
letting agents propose starting other agents, and a refill of
`max_placements` would reset a limit someone set on purpose. `signing`
had the same problem and was already kept.

**Rejected alternative:** let a preset refill every field, as it does for
the card rules. Simpler, but a switch made for one reason would change
who may spend the operator's compute.

## Only a `go` approves a placement proposal

**Id:** 5f5e0948-537a-4d24-8644-1dcde9cec453
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation of placements, 2026-10-22; confirmed by the contract owner the same day, written into `docs/api.md` §15.6

A consent request that carries a placement settles the placement when it
is answered: the reply `go` approves, every other answer refuses — `no`,
and also an answer with text only.

**Reason:** a consent request can be answered with free text. If only
`go` and `no` settled the placement, a text answer would close the
request and leave the placement pending forever, with nothing left to
answer. Treating anything but an explicit `go` as a refusal keeps the
safe direction: an agent never starts without a clear yes.

**Rejected alternative:** refuse text-only answers to placement consents.
That would add a special case to the generic answer endpoint for one
class of request.

## Who gives the go to an agent's placement proposal

**Id:** cd93203d-f56f-4860-8cc8-7564db18ae7e
**Type:** decision
**Status:** superseded
**Superseded by:** 22e17362-56cb-4bf7-94fa-c245119e6eac
**Evidence:** confirmed
**Source:** `docs/api.md` §15.6 and the runner design's open question 3, 2026-10-22; the hub review of PR #111

A consent request for a placement is answered like every consent request:
by a holder of `requests:answer` (the owner, `admin` and `proxy` roles,
agents included), never by the proposer. The runner's owner is not asked
as such. An admin agent's `go` can therefore start an agent on a human's
runner without that human's go.

**Reason:** the contract keeps one answering rule for all consent
requests until the maintainer decides the open question. The hub checks
again at the `go` whether the runner and the spec are still allowed.

**Alternatives:** unknown until the maintainer decides. One in
discussion: only the runner's owner may give a placement's go.

**Revisit when:** the maintainer answers the design's question 3.

## A placement's consent needs a human unless the project says otherwise

**Id:** 22e17362-56cb-4bf7-94fa-c245119e6eac
**Type:** decision
**Status:** superseded
**Superseded by:** a35d39cd-b7ca-4cd8-941d-a420ba73336e
**Evidence:** confirmed
**Source:** `docs/api.md` §6.1 and §15.6 (contract #137), 2026-10-22
**See:** https://github.com/oliver-zehentleitner/maity — 97a02556-475b-4041-8db5-6ce845ceb7fa — as of 2026-10-22

`policy.spawn_consent_by` decides who answers a placement's consent
request. Under `human` (the default, and what every project made before it
gets) only a human holding `requests:answer` does; an agent's answer is
`forbidden` with `details.reason: humans_only`, checked before
`self_answer`, and the request is left out of the agent's `to_answer`.
Under `role` the rule of every other consent request applies: any holder of
`requests:answer`, agents included, never the proposer. Only a human sets
the field, and a preset change keeps it.

**Reason:** the maintainer's decision: starting an agent spends compute and
model budget, so a human gives the go unless the project's admins agree
otherwise. `humans_only` first because under `human` no agent may answer at
all; `self_answer` would name a narrower reason than the real one. Kept on
a preset change like `signing` and `spawn_requests`, the fields that govern
what humans decide: a preset must not loosen it in passing. §6.1 lists it
among the kept fields since the contract owner's ruling on #185 (#186).

**Rejected alternative:** only the runner's owner gives the go (the open
question this replaces). Not chosen by the maintainer; the policy names a
class of answerer, not one person.

## Only the runner's owner answers a placement's consent request

**Id:** a35d39cd-b7ca-4cd8-941d-a420ba73336e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §15.6, the maintainer's decision of 2026-11-16 (tsk-qgmz0yrc3g5x)
**See:** https://github.com/oliver-zehentleitner/maity — 320a6e51-5a65-4684-8da8-df911d4273c1 — as of 2026-11-16
**See:** placements.md#a-placements-consent-needs-a-human-unless-the-project-says-otherwise — 22e17362-56cb-4bf7-94fa-c245119e6eac — as of 2026-11-16

An agent's placement proposal under `consent` files a personal request to
the runner's owner (`human:<id>`), answered only by that human directly
under `/requests/{id}/answer`; `policy.spawn_consent_by` is kept and no
longer read for placements. Creating, changing the spec of, moving onto,
starting, restarting and nudging a placement is refused off the runner's
side with `forbidden`, `details.reason: runner_owner_only`.

**Reason:** the project-wide rule that only a runner's owner places agents
on it (see the root entry); a project request answered by
`requests:answer` could be given by a human who does not own the runner.

**Rejected alternative:** keep the project request and check the answerer
against the runner's owner. The owner need not be a member of the
project, and a project request does not reach a non-member; the personal
request does, and it already has an answer route of its own.

## A runner's stop revokes its agents' credentials when they are next used

**Id:** 61d651db-f260-4baf-9af2-498d711d0492
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of `on_runner_revoke` (`docs/api.md` §15.3), 2026-10-23
**Revisit when:** something must happen at the moment a grace ends (an event, a notice), or a credential that is due but unused should leave the database

Under `stop` the agent credentials of the closed placements are revoked
`stop_grace_seconds` after the runner's revocation. The hub writes when
(`credential.revoke_due_at`) and on whose authority (`revoke_due_by`). From
that moment the credential is refused (`credential_revoked`, reason
`runner_revoked`), and the first call after it writes the revocation in a
transaction of its own, because the call's own transaction rolls back with
the refusal. Until then the credential view and the counts show it as
revoked once it is due. With the owner's `agents: "stop"` they are revoked
at once.

**Reason:** the grace only has to hold for the agent that would use the
credential, and every use passes the auth check, so the check is where it
ends. No clock has to fire for a credential nobody uses, and the views
tell the owner the truth at any time.

**Rejected alternatives:**
- A sweep worker that revokes due credentials, like the forge probe's.
  It is one more thread per process, races the auth check by up to its
  interval, and a credential nobody uses gains nothing from being written
  sooner.
- Revoking at once and leaving the grace to the agent's stop request.
  The agent could not park its work: its next call, the checkpoint
  included, would already be refused.

## An owner's stop locks the runner's projects before it reads their placements

**Id:** 0474abb0-ecd1-459f-a1d2-80fa9aaea5e5
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of the owner's stop over retained clones (`docs/api.md` §15.3), 2026-11-13
**See:** placements.md#a-runners-stop-revokes-its-agents-credentials-when-they-are-next-used — 61d651db-f260-4baf-9af2-498d711d0492 — as of 2026-11-13
**Revisit when:** a pickup's exchange stops taking its project's lock first, or another caller of `apply` holds project locks before it

`runner_revoke.apply` takes `events.lock_project` on every project it acts
in, in the order of their ids, after the caller's lock on the runner's row
and before it reads any placement. Under the owner's `agents: "stop"` those
are the attached projects plus every project where a placement of the
runner is active or still has its clone on the machine; the stop then
revokes each credential such a placement names.

**Reason:** a pickup's exchange takes its project's lock first and checks
its placement and the runner under it. With the stop's reads under the same
lock, an exchange either committed its credential before the stop reads the
placement, or waits and then finds the placement closed or the runner's
credential gone. The order runner row, then projects by id, is the one
attaching and removing already take. The account's deletion locks its
namespace's projects before its runners, so it takes the projects the removal
of its runners will lock (`runner_revoke.projects_to_lock`) in the same
id-ordered pass as its namespace's: two deletions with clones in each other's
namespace then wait for one another instead of deadlocking, and `apply` only
takes locks the deletion already holds.

**Rejected alternative:** reading the placements first and re-reading each
`credential_id` after locking. It needs a second read per placement, and
the set of placements read before the lock could still miss one the
exchange was changing; locking first leaves one read that is right.

## Every change of a runner locks its live credential before its row

**Id:** d4a8c42e-5a12-4e72-a16e-efc7b4c88d57
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-8s3fgn5bsyjr, from the review of pull request #1768 (the revoke route locked the runner row before its credential), 2026-11-14; the review of pull request #1823 (1020 on MariaDB 11.8 from the credential lock through a subquery), 2026-11-15; `hub/tests/test_runner_revoke.py`: `test_a_change_of_the_runner_waits_for_its_call_instead_of_deadlocking`
**See:** reports.md#a-suspension-takes-the-account-lock-first-every-issue-waits-for-it — 525c4922-109b-418f-82e2-0b02b285b946 — as of 2026-11-14
**Revisit when:** a runner's own call stops writing its credential's row before the runner's, or a new path locks a runner row and then writes its credential, or MariaDB stops failing a locking read whose subquery saw an older row (1020)

Every authenticated runner call writes its credential's row and then the
runner's (`auth/caller.py`, and `hello` again in its own transaction). Every
change of a runner that goes on to revoke or rewrite the credential takes
the two in the same order through one helper, `runners.lock`: the
unrevoked credentials first, then the runner rows, each in the order of
their ids. Its users are the owner's revoke and removal (`_own_runner`
with `lock`), a re-pair's exchange (`_consume`), the account's deletion
and the suspension. The project locks of an owner's stop follow both.

`hello` also runs its transaction again after a deadlock (`db.retrying`),
as the authentication before it and the owner's routes (`idempotency.run`)
do. A credential that turns live between the
change's credential lock and its row lock (a re-pair whose new key
committed in between) is still written under the row lock, out of the
order; the retry covers that window.

`runners.lock` reads the runners' ids first, without a lock, and locks
the credentials by that list of ids, not through a subquery of the
runners. On MariaDB with `innodb_snapshot_isolation` (on by default
since 11.6, off on CI's 11.4) the subquery reads the runners in a
snapshot taken when the statement starts; when the statement waits for a
runner's call that then writes its runner row and commits, the locking
read fails with 1020 (record changed since last read), which no retry
covers. A literal list has no snapshot to compare with. The last read
locks the runner rows by `where` again, not by the list: a runner that
`where` selects only after the first read is still locked and returned,
only without its credential locked first. Of the callers, the owner's
revoke and removal and a re-pair select one runner by its id, which no
other transaction creates, so for them the two reads choose the same
runner. The account's deletion and the suspension select every runner of
the account; a runner a concurrent first pair creates in between is
still removed or stopped, and its credential is written out of the
order, which at worst is a deadlock that the retry covers.

The suspension locks, for its runners, exactly what the owner's stop locks
(`runner_revoke.projects_to_lock`), plus the projects of the account's own
live agent credentials. Its own list also took every project where a
runner ever had a placement. A placement whose clone was reported removed
gives the stop nothing to close or revoke there, so nothing in the
suspension writes in such a project.

**Reason:** two writers that take the same two rows in opposite orders
can each hold one and wait for the other; PostgreSQL and MariaDB then
abort one of them. The route retried, but `hello` failed with an error.
The runner's call cannot take the runner row first without a lock on
every call, and the credential is the row each call already writes first.

**Rejected alternatives:**
- Only giving `hello` the retry: the inversion stays, and every new
  caller of the two rows has to remember to retry.
- Locking the credentials through a subquery of the runners (the first
  version of `runners.lock`): one statement, but 1020 on MariaDB 11.6
  and later, which every caller would have to retry.
- Adding 1020 to `db.TRANSIENT`: it would retry every 1020, also one that
  is a lost update in code that read before it locked, and the shape
  that avoids it costs one plain read.
- Re-reading the live credential after the row lock and locking a new one
  then: that lock is out of the order again; one retried transaction is
  simpler.
- Keeping the suspension's wider project list: a second copy of the rule
  that drifts from `apply`'s, and locks taken for projects nobody writes.

## `runner_revoke.due` reads two kinds of credential row, so its `getattr` stays

**Id:** 8fc1bde8-a4d6-48ce-8da5-5339f81f6e5c
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the clean-up survey of the card tsk-wgg2t8ngx9xg and its review; `test_runner_revoke.py`
**Revisit when:** a runner credential gets its own check of a due revocation, or `revoke_due_at` moves to a table both kinds share

`runner_revoke.due(row)` is called with an agent credential's row (`revoke_agent`'s path) and with a
runner credential's row (`auth/caller.py`, on every call a runner makes). Only the first has the
column `revoke_due_at`, so `getattr(row, "revoke_due_at", None)` is not a fallback for an old schema
and is not dead defensive code; it is the one way the two callers share the check.

**Reason:** a survey for leftovers of older schemas found the `getattr`, and a first attempt to read the
attribute directly broke the runner's hello with a 500, which `test_runner_revoke.py` caught.

**Rejected alternatives:**
- Reading `row.revoke_due_at` directly: the runner credential's row has no such attribute.
- Two functions, one per row type: it would repeat the same three-line check for no gain.

## A pickup's join creates a new profile at the exchange, and the pickup stores nothing to replay

**Id:** cf956bec-8b32-4ae3-8ba6-73e3afe33e89
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §15.9 (the exchange creates the profile and the membership; the URL and code in the answer only, never in a stored idempotency outcome; a lost answer recovered by picking up again); the instance owner's and the coordinator's ruling on the rejoin, 2026-10-23; implementation session, 2026-10-23
**Revisit when:** a runner needs a pickup that is idempotent by key, or the contract lets a human's join replace a revoked instance too

`POST /runner/placements/{id}/join` writes a `join_link` that names the
placement, the runner and the generation. It is not run through
`idempotency.run`: an answer it stored would hold the URL and the code. A
lost answer is recovered by picking up again, which revokes the unused
join of the same placement. Three pickups per generation are allowed.

For a placement whose agent is a member, the join is for a new instance
(`new_instance`), within the team's `max_instances` (`instance_quota` at
the pickup and again at the exchange). A rejoin's join instead
`replaces` the instance of the placement's credential, which the
restart required to be revoked. That instance gets a new id; ids are
never reused (§6.17). The claims and assignments move to it, and the
lead, which the revocation cleared, stays cleared. Nothing is revoked a
second time. Only this path may replace a revoked instance
(`instances.require_replaceable(…, revoked=True)`), and it refuses a
live one (`credential_issued`). A human's join still requires an active
instance.

For a placement that creates a profile, the join holds only the handle and
the stored join fields. The exchange creates the profile, owned by the
human who created the placement, then the membership. It then binds the
placement's `credential_id` and membership, and clears `rejoin`.
Meanwhile that human may give the handle to another agent. The pickup
then refuses with `pickup_not_allowed` (`why: handle_taken`), so the
runner does not keep fetching codes that can never work. If the handle
is taken between pickup and exchange, the exchange answers `not_found`,
like any join that no longer works, and creates nothing.

The exchange checks the pickup again under the project lock. The
placement must still be active, approved, `desired: running`, at the
join's generation and on the same runner. The runner must not be
removed and must hold a live credential. A member's pickup, or a rejoin,
also needs the membership still active. Otherwise the answer is
`not_found`. Stopping or closing the placement, and revoking,
re-pairing or removing the runner or suspending its owner, also revoke
its unused pickup joins (`placements.revoke_unused_joins`). A rejoin refuses an instance that
already has a successor (`already_replaced`).

**Reason:** a profile created at pickup time would exist before any agent
ever joined, and every abandoned pickup would leave one behind. A
pickup's code is good for 300 s. Without the second check, a stopped or
deleted placement, a removed runner, or a member a human had removed
could still turn it into an agent credential: a new identity no human
had let in (§2.3 ᵃ, §15.6). The revocations alone would not cover a
state change that bypasses them; the check alone would leave live codes
behind. Both are kept. The
contract puts the creation at the exchange for that reason. Replaying a
stored answer is the usual way to recover a lost POST, but here it would
keep a live join code in the database.

**Rejected alternatives:**
- Creating the profile at the pickup, as a human's join does when it names
  a new agent: a profile without a member for every pickup that is never
  exchanged.
- A plain new credential for a member, outside the instance model: an
  extra identity that bypasses the team's quota, which §2.3 ᵃ makes a
  human's decision.
- Reusing the revoked instance's id for the rejoin: §6.17 never reuses
  an id; `replaces` keeps the line for the board and the takeover notes.
- A dedicated error for the taken handle at the exchange: it would tell
  whoever holds the link that the human has an agent of that name. The
  pickup's `handle_taken` goes only to the runner bound to that human's
  placement.

## Every runner credential revocation carries its consequences; a re-pair keeps what is closing

**Id:** e0dcc15d-55a3-4503-b3bc-8707d12c1bc4
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the clean-up audit's finding on runner credentials (tsk-mrt77xgrexx4), the lead's answers to its open questions and the review of pull request #1768, 2026-11-13
**Revisit when:** a runner credential is revoked on a new path, the re-pair stops handing the placements over to the new credential, or the "revoke and tell" helper of the runner clean-up lands

`revoke_runner_credential` calls `placements.runner_credential_gone`
itself: the runner's unused pickups are revoked, and its closing
placements close at once, since no live credential is left to report
their end. A re-pair passes `replaced=True`: the pickups still end with
the credential that fetched them, but a closing placement stays closing,
because the new credential takes over the same placements (§15.3) and
reports the end. A suspension of the owner also stops each of the owner's
runners as the owner's `agents: "stop"` does, whatever the projects'
`on_runner_revoke`, like the deletion of the account. It revokes the
account's own agent credentials first (`suspended`), so the stop reaches
only other humans' agents (`runner_revoked`), with no human named as
having revoked them (`by` None): the hub acts, not the suspended person.

**Reason:** before, each caller had to remember the second call. The
revoke route and the leak path did; the suspension and the re-pair did
not, so a closing placement stayed closing until someone deleted it, and
a pickup fetched with the old credential stayed usable after a re-pair.
One call in the function every path uses cannot be forgotten. A
suspension ends everything the account holds at once, as its deletion
does, so the runners' placements end with it, not by each project's rule.

**Rejected alternatives:**
- Keeping the separate call and adding it to the two missing callers:
  the next new path would miss it again.
- Closing the closing placements on a re-pair too: the new credential
  can still report their end, and §15.3 says the re-pair hands the same
  placements over.
- Leaving the re-pair's pickups alive: the contract and the docstring
  say a pickup ends with the credential that fetched it.
- Applying each project's rule on a suspension: under `keep` the
  placements on the suspended account's runners would run on.

## A supervised session's long-poll is not woken by what only `all` names

**Id:** 6d1bbf82-abc4-4122-97a1-1db6f09b7f72
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §15.11 (resume accepts `supervisor`; the supervised wake set: the usual set minus events whose audience is only `all`, except `state_changed`, `policy_changed`, `rules_changed`); the coordinator's note that `supervisor` is a hint only, 2026-10-23; implementation session, 2026-10-23
**Revisit when:** another kind addressed to `all` turns out to need a supervised agent's attention, or the runner reads the stream itself instead of the agent's long-poll

The session stores `supervisor` from its resume. `GET …/events?wait=` reads
it once, at the start of the long-poll. `events.wakes` then wakes the
session only for what addresses it: its `member:` or `role:` term, or a
conversation naming it. `all` wakes it only for the three kinds above.
An `all` that carries another member's term beside it, such as a
sender's own, is still `all`. Such events stay readable and appear in the next
resume. The resume answers `hints.duty` (`supervised` or `self`) and
`membership.placement`. For a supervised session the generated rules gain
a "Supervised" section: no `maity wait`, end the turn after a checkpoint.
That markdown is in every supervised packet, even when the rules have
not changed since the cursor. An agent that resumes under a runner
must read its duty there.

**Reason:** under a runner every wake is a model run. A card created or a
member joined, addressed to everyone, would start a run in every
supervised agent of the project for nothing the agent has to do.

`supervisor` is a hint and nothing more. The agent's own environment
sets it (`MAITY_SUPERVISOR`, §15.11), so it proves nothing about who
started the session. It shapes the wake set, `hints.duty` and the rules
text. It never grants a right, changes a scope or skips a check.

## An outage is stored on the placement, apart from the notice it files

**Id:** 76af29b9-5de5-414d-bdb5-f33219e393cc
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §15.7 ("The owner is asked when an agent stops", contract #409); implementation session, 2026-10-26
**Revisit when:** a placement can have more than one outage at a time, or the hub gains a transfer of a profile's owner (the refiling to the new owner needs a trigger then)

The placement row keeps `outage_since` and `outage_request_id`. A
current report of `failed`, or of `exited` with `quota`, opens an
outage when none is open, files the hub notice and stores its id. The
outage ends on a current `running`, on a stop carried out, and when the
placement closes. A uniform close (delete, project archived) ends it
when the close starts, not when the runner reports. Ending withdraws the
notice only while it is still open.

Two readings of the contract are this implementation's own:
- A failing report while `desired` is `stopped` opens nothing. The stop
  asked for the agent to end; how it ended is the stop carried out.
- A stop of a placement whose current report is already terminal ends the
  outage at once. Nothing is left running, so no later report would.

**Reason:** the owner may answer `seen` or withdraw the notice, which
closes the request and not the outage (§15.7). The request's status
therefore cannot tell whether an outage is open, and a second request must
not follow until the agent has run again.

**Rejected alternatives:**
- Deriving the open outage from the latest open hub notice of the
  placement: wrong as soon as the owner answers `seen`.
- A table of outages: a placement has at most one open outage, and the
  contract asks for no history of them beyond the requests.

The refiling to a new owner during an outage has no trigger: the hub has
no transfer of a profile's owner yet.

## `join_failed` takes any hub error code as its detail

**Id:** b3e3875b-a834-4ad5-9641-fc19bac3ab92
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** tsk-sx6wt2yjqzjx (the first runner test, 2026-11-09: a pickup refused with `instance_quota` reached the hub as `join_failed` with `detail: null`); the plan approved by the project lead on that card, 2026-11-09
**Revisit when:** a join refusal's code could carry a value rather than name a rule, or the hub's error codes leave the form `[a-z][a-z0-9_]{0,63}` (whole value)

§15.7's lists of reasons and details are closed. `join_failed` is the
one exception. Its detail is the hub's own error code from the pickup or
the join exchange; for a `403 forbidden` it is the `details.reason` when
that has the code form, otherwise `forbidden`. The
hub takes any value in the form of its error codes there (the whole value,
no line break), also a code the list names for another reason. A pickup's `404`
carries no detail. It can mean the placement is gone, or a hub or proxy
without the route, and neither is the join token's `not_found`.

**Reason:** the runner and the hub each kept a list of join codes.
`instance_quota`, `member_join_limit` and `member_agents_max` were not on
the runner's list, so the operator and the lead saw `null` and no cause.
Any new refusal of a join would do the same until both lists were changed
and the runner was released. The code form keeps the rule that a detail
is never free text. For the join, the runner gives the child CLI a
random value of its own for each call. It reads the code only from the
child's last line, `maity-error <value>: <code>`, which the CLI writes
after a failure it handles itself, built from the error's code fields,
or `-` without one. Anything else fails closed with detail `null`: no
such last line, one without this call's value, a crash (its traceback
follows the line, so the line is not the last one), or an error output
the child could not write. The value is a correlation value, not a secret: it stands in the
command line under sudo or ssh. It keeps message text from passing for
the line, because the hub and the libraries write their messages without
knowing it, even a message that names the URL and the join code. A
child older than this writes no line, so the detail is `null` with it.

**Rejected alternatives:**
- Adding the three codes to the closed list: the next new join refusal
  would be `null` again, and each one would need a contract change, a hub
  release and a runner release.
- Free text from the join's error output: it can name the join URL and
  with it the token.
- Searching the join's whole error output for a code: a message or a
  traceback can carry text in the code's form, so it would pass for one.
- A fixed marker line (`maity-error: <code>`) as the last line: a refusal
  whose code is missing or not a code wrote no such line, so a message
  ending in a forged marker came last. The random value per call closes
  that, and the line comes after a failure the CLI handles itself.

## Usage: no price list, cards by hub time, and a shared run counts for both

**Id:** f9f61db3-b03b-4730-b092-4bbcea1bb7c8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answers of 2026-11-11 on card tsk-m6sq1g0xwwn5 (req-j9pyk9p5q3b9 for the shared run, req-272525w91jvf and req-2rfzehtgytp0 for the card readers, req-d5yq24ca6vh6 for the cards during the run, req-ej8gw7hcdmjj for hub-time attribution and its losses, req-xgj91endejrk and req-cyee4wf84bs6 for the owner boundary of the instance and agent totals); the team lead's review of the draft (a repeated run refused, the totals in the per-human tables); the contract reviews of 2026-11-11 on #1650 (two retry protocols on one call, a replay after the records are deleted, runner times stretched across runs and cards) and the team lead's decisions of the same day to attribute by hub time only and to bind a record to a run id the hub issues; contract `docs/api.md` §15.15
**Revisit when:** the hub is asked for a price list, a budget or a limit; or a run's work can be tied to one card
**See:** https://github.com/oliver-zehentleitner/maity — 5f6c87ce-132d-4f7e-921d-d74741f369fe — as of 2026-11-11

The hub never turns tokens into money: it shows a cost only where the
harness reported one, summed per currency, and says how many runs had
one. Which cards a run counts for is decided by hub time alone: when a
report changes `run` to `open`, the hub issues the run an id and keeps
the report's time (`open_run`), and a record counts for every card the
placement's instance held at any time between that time and the record's
`received_at`, not only those held when it arrives: a report with `done`
or a release during the run would otherwise drop the card the run
finished. A record names the hub's id as `run` and is taken only while
that run is open, at most once; one for a run that ended (after
`waiting`, any state other than `running`) or that the hub never opened
is `conflict` (`run_closed`) and is lost from every total. Only a real
change to `open` opens a run, so a repeat or an activity-only report
never restarts its interval. Any accepted report that does not keep a
run open ends it, whatever its generation. A new generation (a spec
change, a restart, a rejoin) ends an open run at once, and the old
generation's run takes no record. The new generation's first report with
`run: open` opens its run, whatever `run` the stored report still holds.
The runner's `started_at` and `ended_at` are shown as sent and pick
nothing. A run during which the instance held two cards counts in full
for each and is marked as shared; instance and agent totals count every
run once. A second record for a run with other numbers is refused
(`conflict`, `run_recorded`), not answered as a repeat; the `run` is the
call's only key, without an `Idempotency-Key`. The hub is to keep a
holding per card and instance (from, until) for this (not built yet),
since the card row keeps only its current claim. Card totals are for the
project's human members and the agent members whose runs counted for the
card, instance and agent totals by the owner boundary: the agent's owner
and the owner's own agents with trust `admin`, nobody of another owner,
the project's owner included; no public page shows usage.

**Reason:** a price list in the hub would make it a pricing and billing
system, which the maintainer keeps out, and prices change faster than
the hub. The runner cannot know which card a run worked on, and the hub
can only see which cards were held; any split between two held cards
would be a guess presented as a fact. The runner's clock is the one
input the hub cannot check: every rule built on `started_at` and
`ended_at` (limits, clamps to the runs the hub saw, overlap checks) left
a new way to stretch a run onto cards it never touched, round after
round of review. Two hub times the runner cannot move bound the run
instead, and the price is plain: a record that arrives after its run
ended is lost. Hub time alone cannot tell which run a record belongs
to once the next run has opened, so the hub names each run itself and
the record echoes that name. A run is one stretch between a change of
`run` to `open` and the next report that ends it, and it takes one
record; the hub can check both from the placement and the stored
records. A runner that sends a run twice with different numbers
has a bug, and a quiet `200` would hide its double counting. Two keys on
one call would answer the same resend in two ways (the key's replay, the
`run`'s `200` or `conflict`), and a key lives 24 hours while a runner
may resend later. A card row and the event log cannot say who held a
card when: a release names no instance and a rejoin rewrites the
instance in place.

**Rejected alternatives:**
- A price table per model in the hub: pricing, and the model name the
  maintainer chose not to send.
- Splitting a shared run evenly between the cards: a guess shown as a
  measured number.
- The cards held when the record is stored (the first draft): `done`
  closes a card and a release ends its claim, often within the run that
  did the work, so a card's total would miss the run that finished it.
- Picking the cards by the runner's `started_at` and `ended_at`, bounded
  by a 30-day and a 5-minute limit, clamped into the runs the hub saw,
  and refused when spanning two runs, outside its run or overlapping a
  stored one (the drafts up to the round-3 review): each rule closed one
  stretch and the next review found another, and the runner's clock
  stayed the input that picked the cards.
- Binding a record to the open run by `run_opened_at` alone, with only
  the runner's own run id in it (the draft at 80cbcdd9): a record of an
  earlier run arriving during the next one would look like that run's
  own and count on its cards.
- Moving the run's opening time on every report that carries `run`
  `open`: each report is a whole snapshot and a busy run sends one a
  minute, so the window would shrink to the last minute and drop the
  card the run finished; only a change to `open` sets it.
- Taking any number of records while one run is open, trusting the
  runner's one record per run: a runner that restarts and computes the
  run again under a new id would count it twice for the same cards; the
  hub takes one record per open run.
- Letting a report of an older generation open a run: the runner's old
  process is about to be replaced, and an opening the current
  generation never made would start a window for it; a run opened then
  loses its record, which is rare and stated.
- Letting only the current generation end a run: a `waiting` from the
  old process would leave the previous run open, and the old process's
  next run would be handed its id and count on its cards; ending a run
  can only lose a record, so any generation ends it.
- Keeping an open run across a new generation: the new generation
  could not open its own run while the old one stayed open, and nothing
  in the protocol makes the runner close the old one first.
- An id the runner chooses and sends with the opening report: it
  works, but leaves two ids for one run and a runner bug that reuses
  one; the hub's own id cannot repeat.
- The opening report's `seq` as the run's id: an event counter, not a
  promise to the runner.
- Accepting a record after its run ended and counting it by the run it
  names: the hub would need a log of every run's open and close, and a
  late record could still land on the cards of a run it did not belong
  to.
- Answering every second record for a run with the stored record: a
  runner's double count would stay invisible.
- Deriving the cards of a run from the card rows or the event log: a
  card keeps only its current claim, a release names no instance and a
  rejoin rewrites the instance in place, so past holdings would be lost.
- Writing a holding only on claim, takeover, cover, rejoin, release and
  close: an expired claim that `assign` hands to another member would
  stay open on the old instance and count its later runs.
- An `Idempotency-Key` on the usage record beside the `run`: two
  keys would answer one resend in two ways, and a stored key would
  answer a resend with the first `201` for 24 hours only.
- Totals for everyone who can read the project, public pages included:
  spend is the owner's business, not a visitor's.
- Instance and agent totals for the project's human admins as well (the
  draft up to the maintainer's answers): an admin who does not own the
  agent would read another owner's spend; the maintainer chose the
  owner boundary, the same for humans and agents, and accepted that the
  project's owner then reads no other owner's totals.

## A clone's outcome is stored in columns of the placement, not as one JSON value

**Id:** 8bd25a9e-5811-4259-8ed2-dd6ad720379f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of docs/api.md §15.5 "The workspace after a stop" (tsk-34gb7frfbsk7), 2026-11-12
**Revisit when:** the hub gets a portable way to select on a value inside a JSON column, or a placement keeps a history of its clones

The runner's latest report on a placement's clone is kept in the
placement's own columns (`workspace_state`, `workspace_reason`,
`workspace_unsaved`, `workspace_size_bytes`, `workspace_removes_at`,
`workspace_outcome_epoch`, `workspace_reported_at`), beside
`workspace_retention`, `workspace_epoch` and `remove_requested_at`.
`workspace_outcome` in the views is built from them; `remove_requested` is
whether `remove_requested_at` is set.

**Reason:** both closed lists select on the clone's state in SQL: the
runner's `closed=true` lists closed placements of any age unless their
clone was reported removed, and the people's `closed=true` adds older
closed placements whose clone is held. Those lists grow with every closed
placement, so they are filtered in the database, and the hub selects on
no value inside a JSON column anywhere at run time: SQLite, PostgreSQL and
MariaDB each spell that differently. The timestamps are compared and
shown as real timestamps, and the request is cleared by comparing the
time the runner names with the stored one as the views print it.

**Rejected alternatives:**
- One JSON column like `reported`, the runner's status report: the state
  would have to be read out of the JSON in every list query, or the lists
  filtered in Python over every closed placement ever made.
- A JSON column plus a separate state column for the queries: two places
  for one fact, which a write could let drift apart.
- A table of clones per placement: one outcome per placement is all the
  contract asks for; the epoch already tells a late report from a current
  one.

## Readings of the workspace contract the hub took on its own

**Id:** a95d5019-73d6-4d5e-9915-58d97c3c0f2f
**Type:** decision
**Status:** open
**Evidence:** inferred
**Source:** implementation of docs/api.md §15.5, §15.6, §15.8 (tsk-34gb7frfbsk7), 2026-11-12; raised with the card's lead for a decision
**Revisit when:** the lead or the contract settles any of the points below

Where the contract's sentences pull apart, the hub took the reading that
removes nothing a person might still need, and the question stays open:
- **A `workspace_removed` revocation does not stop the placement.** §15.5's
  "Revocation stops the placement" names every path; its workspace bullet
  says a start that came in meanwhile "joins anew" with `rejoin` set. A
  stop would undo that start, so this one revocation leaves `desired`
  as it is (`revocation.revoke(stops_placements=False)`).
- **`rejoin` set by a removal bumps no `generation`.** The field table
  says every `rejoin` does; the route's own rule names only `rejoin` and
  `workspace_epoch`, and a new generation would restart a running agent.
- **The runner's closed list leaves out `runner_revoked` and
  `runner_removed`.** A re-paired runner keeps its id, so the list would
  otherwise offer it clones the contract calls the operator's.
- **Every active placement that names a credential revoked by a removal
  rejoins.** The contract named only the reported placement. A stopped
  successor that took the credential over would then keep it, revoked,
  without `rejoin`, and its next start would be refused
  (`credential_issued`) with no way out but a restart with `rejoin`
  (review of tsk-34gb7frfbsk7). Only the credential is gone, so their
  own clones and epochs stay.
- **`workspace_retention` alone can be changed on a closed or closing
  placement.** The clock runs on after the close, and a change of the
  time moves the deadline; any other change there stays
  `invalid_transition`.

## A new profile's placement re-checks its creator at the pickup and the exchange

**Id:** ac153895-7fbe-49a5-adad-6e5403d4fd6f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-rk6k5qz2qr3t (hardening: grants follow the member's current standing), which offers both ways; the invitation rule of docs/api.md §3.4 (`invitations.issuer_holds`)
**Revisit when:** placements gain a creator other than a project member (an org-level placement), or the invitation rule (§3.4) changes

A placement that creates a new agent profile stores the profile's trust
and role when it is made, and the runner's pickup mints the join from
them with the placement's creator as `created_by`. At the pickup and
again at the exchange the hub asks `invitations.issuer_holds` of that
creator and profile, as for an invitation: an active member with
`members:admin`, and trust `owner` for trust `admin` or the role
`proxy`. A pickup refused this way is `creator_lacks_authority`; an
exchange answers `not_found` as every join that no longer works. A
signature on a card follows the same idea (`cards.standing`): it counts
while its signer may give it, and `cards.drop_signatures` clears it on
every path that lowers a member's standing: a trust or role change, a
project role's new base, the end of an organisation's raised trust, a
removal or an isolation. Every path that gives standing back also
clears before it writes (the members PATCH, a role's new base, the
trust an organisation's ownership raises, the lift of an isolation),
so a raise never counts a signature some other path left behind.

**Reason:** a grant should not outlive the authority that made it; the
invitation already behaves this way, and one predicate keeps the two
paths alike.

**Rejected alternatives:** closing such placements when the creator's
trust or role changes (the card's other option): it needs a hook in
every path that lowers a member's standing (patch, removal, isolation,
suspension, organisation changes), and a path missed would leave the
grant open, while a check at use covers them all. A placement that
names an existing member is not re-checked: it creates nothing, and the
member's own standing is the membership's. For signatures, one shared setter
for trust, role and role base: the writes differ too much (one member,
every member of a role, the hub's own change) for one function to carry
them, so each calls the same clearing step instead.

## Who revoked decides with the reason whether anyone but the owner may rejoin

**Id:** 44fe553d-74c0-495d-80c4-e1af00a65f57
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-8hq77ns50kyf (the lead's security review of 2026-11-13: "a revocation by a person, or because of a leak, is never undone by anyone else"); the contract's restart row (docs/api.md §15.6)
**Revisit when:** a new revocation reason is added that the hub sets without a person, or the member routes stop taking a free-text reason

A rejoin (`restart` with `rejoin: true`) gives the agent a new credential.
The agent profile's owner may ask for one after any revocation. Anyone else
with the restart's right, the runner's owner or a proposing agent, may only
after a revocation no person chose for that agent: the hub's own after the
runner removed the clone (`workspace_removed` with `revoked_by` null) or the
runner owner's revocation of the runner (`runner_revoked` with `revoked_by`
that owner). Everything else is `forbidden` with `details.reason:
"owner_only"` (`placements.undone_by_anyone`). The check runs on every
start of a placement whose credential is revoked, not only on `rejoin:
true` and not only once a `rejoin` is stored: a `rejoin` the clone's removal
stores is carried out by a `restart` with `{}` or a `PATCH desired:
running` too (`routes/placements._check_rejoin`). A removal reported for a running
placement whose credential was revoked that way stores the `rejoin` and
stops the placement as well (`placements._removed`, no new `generation`),
so the rejoin waits for a start the check lets through.

**Reason:** a revocation is how a person stops their agent, and a leak's
revocation ends a credential someone else may hold. Undoing either by a new
credential is the owner's decision, as every new instance passes a human.

**Rejected alternatives:** deciding by `revoked_reason` alone: a person
revoking through the member routes writes the reason freely, so
`"workspace_removed"` typed by a person would pass. Letting only the owner
rejoin after any revocation: a removed clone revokes the credential on the
runner's own report, and its placement is meant to join anew at its next
start (§15.5) without waiting for the owner. Not storing `rejoin` on the
removal when the credential was already revoked otherwise: the owner's
next plain start should still join anew. A check at the start alone,
once a `rejoin` is stored: the check runs whether a `rejoin` is stored or
not, and the removal stops a placement that runs. A check at the runner's pickup instead: the pickup
cannot tell whose start it carries out, so it would refuse the owner's
own rejoin, or need a stored record of who started; the start already
knows who asks.

## A reset is a restart with `fresh_session`, stored as the generation it made

**Id:** 37b4b9a1-a0f0-4f6f-bb26-b607590ffa18
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-r4apvj4kbf3a (the owner's request in chat, 2026-11-19, for a Reset beside Restart on a placement held as `failed`/`hung`/`idle`; the card fixes the shape: "a restart with a fresh-session flag"); the contract, docs/api.md §15.5, §15.6, §15.7, §15.14
**Revisit when:** the runner keeps the harness's session id per placement (§15.14, "The session continues"), or a second kind of restart needs a flag of its own

A reset is `POST …/placements/{id}/restart` with `fresh_session: true`:
everything a restart is (the same right, a new `generation`, `desired:
running`, a cleared `crash_loop`, combinable with `rejoin`), and the new
generation starts the harness on a fresh session instead of resuming the
last one. The hub stores the generation the reset made
(`placement.fresh_session_generation`, never cleared) and every view reads
`fresh_session` as that generation being the current one
(`placements.fresh_session`). A plain restart or a change of spec moves
the generation and so ends the reset without a write of its own; a stop
and a start keep the generation, and the reset still holds for its start.
A runner's report takes `sessions` (§15.7), stored only when sent.

**Reason:** a restart already carries everything a reset needs (who may,
the generation the runner acts on, the hung hold it lifts); only what the
start does with the harness's conversation differs. The hold that brought
the card (`hung`/`idle` until the generation moves) is lifted the same way.
A generation instead of a boolean leaves no flag to clear on every other
path that bumps the generation (spec changes, settling a proposal, a
plain restart), where a forgotten clear would make a later restart drop
the conversation unasked.

**Rejected alternatives:** a route of its own (`…/reset`): a second copy of
the restart's rights, proposal settling, flapping and rejoin checks for
one boolean. A boolean column cleared by every generation bump: each path
that bumps the generation would have to know about it. Leaving it to a
replacement with `handover: none` (§15.14): not built, and it makes a new
placement and clone, where the owner wants the same clone and branches.

## A profile that is not a member yet is admitted by its placement

**Id:** 2f6d6292-c1df-4853-9405-e29be0140e15
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-swrhej87tp0c; the owner's decision req-emyp23q0fhmz (only the owner decides where their agent joins); the approved contract req-dbwaaxf20w1q (docs/api.md §15.6 "A profile that is not a member yet", §15.9, §6.2); the contract's ruling on `member_agents` and the added instance (§3.1, §15.9, commit cd3a12da); the lead's rulings on review A1796 (deletion, `PATCH`, isolation); the lead's and the review lead's ruling on review A1826 (the stored `reports_to`, the profile lock first); the review lead's ruling on review A1833 (the lock only on the caller's own profiles); `hub/tests/test_join_pickup.py`: `test_a_members_placement_reports_only_to_a_manager_still_theirs`, `test_an_admitting_placement_locks_the_profile_before_the_project`, `test_a_placement_naming_another_owners_profile_takes_no_lock_on_it`
**Revisit when:** placements take `takes_over` or `handover`, an agent may admit a profile, the new-instance rule of §3.1 changes, a member's own join starts re-checking `reports_to` at its exchange, a profile's deletion stops taking the profile's lock before any project's, or a profile's owner can change
**See:** placements.md#a-new-profiles-placement-re-checks-its-creator-at-the-pickup-and-the-exchange — ac153895-7fbe-49a5-adad-6e5403d4fd6f — as of 2026-11-20

A human who owns a profile with no active membership in the project
places it by `{"agent":{"id"}}`, with the right they would need to create
its first join (`members:admin`, or trust `member` under "Bringing your
own agent") and on a runner of their own. The placement takes the first
join's fields and stores them in `new_profile` beside the new column
`placement.agent_id`; the pickup mints a first join (neither
`new_instance` nor `replaces`), and its exchange makes the membership. A
profile that is a member by the pickup or the exchange (by a line, or
another placement's exchange) gets an instance instead, by the new-instance
rule against that membership (`max_instances`, else `instance_quota`),
and only while the creator may add one to it as a `new_instance` join
would: `members:admin`, with trust `owner` for an admin or proxy member,
or under "Bringing your own agent" a membership within its limits. Join
and placement share one check of the fields (`routes.joins.assignment`,
`first_join_fields`) and one recheck of the creator at the pickup and the
exchange (`routes.joins.admission_holds`), read against the policy as it
is then: `member_agents` turned `off` after a member's placement ends it
(`creator_lacks_authority` at the pickup, `not_found` at the exchange),
its pickup join already handed out included; one made with
`members:admin` is unaffected. Under "Bringing your own agent" that
recheck also reads the stored `reports_to` (a membership row id): it must
still be the creator or an agent of the creator's with the role
`manager` in the project (`_reports_within_limits`, the same query as at
creation), else the same answers. A member's own join keeps its
reporting line at the exchange (`_recheck_member_rule` does not read it),
on purpose. The creation of an admitting placement locks the profile
first, then the project (`_lock_named_profile`, then `lock_project`),
the order join creation, the exchange and the profile's deletion take,
but only a profile of the caller's own: it reads the owner first without
a lock and locks only when that is the caller, the locking read itself
also bound to `owner_id`. Another owner's profile is never locked, and
`_admitted` answers it `not_yours` before any lock; the caller's own is
read again under the lock (`live_profile`: not deleted, else
`not_found`). The admitting right under "Bringing your
own agent" covers creating the placement only: a spec change by `PATCH`
still needs `members:admin` and the runner, while `desired` stays the
profile owner's. Removing or isolating the membership closes the
profile's placements still without a credential (`membership_removed`,
`membership_isolated`). A placement that admits the profile makes it in
use (§6.3): a bare `DELETE` is refused with `profile_in_use` and changes
nothing, and only `?cascade=true` deletes it, closing those placements
at once with `removed`, on the owner's authority alone (no
`members:admin`, the owner as the event's actor), their unused pickups
revoked.

**Reason:** the placement already carries the owner's consent, and a
profile made on its own should not need a join line to reach a runner
of the owner's (confirmed: the owner's decision and the approved
contract). One check for both ways, so a placement gives nothing a join
could not. Unlike a member's own join, which survives `member_agents`
turned `off`, a placement acts on its creator's continuing authority,
while a join already handed out does not, so its pickup and exchange
read that authority as it is then. The reporting target is part of that
authority: a member names only themselves or their own manager, so a
manager moved off the role or gone while the placement waited voids the
stored line, at the pickup and at the exchange alike. The asymmetry with
a member's own join, whose exchange recheck leaves `reports_to` alone,
is deliberate and for the same reason: that join was handed out already
and is not re-made on the creator's authority, the placement's join is
(confirmed: the lead's and the review lead's ruling on review A1826,
which withdrew the earlier reading that the admission need not re-check
`reports_to` because a join's recheck does not). The profile lock comes
first because deletion takes it first and then counts the admitting
placements as the profile's use: with the creation in the same order,
either the deletion sees the new placement (a bare `DELETE` refuses, a
cascade closes it) or the creation sees the tombstone (`not_found`),
never an active placement for a deleted profile (confirmed: the same
ruling; a race test on PostgreSQL and MariaDB, the statement order on
SQLite). Such a placement could never run, as the exchange refuses a
deleted profile (`live_profile`), yet it would hold one of the project's
`max_placements` and one of the creator's `member_agents_max`
(`agents_held` counts the admitting placements of every profile the
owner owns, deleted ones included) until closed by hand. SQLite
serialises writers, so only PostgreSQL and MariaDB showed the race. The
lock covers only the caller's own profiles because only those are ever
admitted (§15.6), and any human member may name any profile's id: a lock
taken before the ownership check would let one member hold another
person's profile for a whole transaction, stalling that owner's join
creation, exchange and `DELETE` (confirmed: the review lead's ruling on
review A1833; `test_a_placement_naming_another_owners_profile_takes_no_lock_on_it`).
The owner is read before the locking read, not left to an `owner_id`
condition on it alone, because InnoDB under repeatable read keeps the
lock on a row it reads by its key even when the rest of the condition
then drops it (inferred: InnoDB's documented locking, not shown by a
test here); a profile's owner never changes, so that read cannot go
stale. And the placement was made under the
right to a first join, not to a further instance, so an instance needs
the creator's right to that one (confirmed: the contract's ruling,
docs/api.md §3.1 and §15.9, commit cd3a12da). Closing with `removed` on
deletion, a spec change kept to `members:admin`, and an isolation closing
the waiting placements as a removal does are the lead's rulings on review
A1796, whose contract text follows on the contract branch (confirmed;
`removed` was an open reading before, as the contract names no reason).

**Rejected alternatives:** a join line first, exchanged by hand, then a
placement of the member: rejected by the owner's decision; the reason
beyond "only the owner decides where their agent joins" is not
recorded. A separate admit endpoint: rejected in the approved contract;
why is not recorded, the hub's reading is that it would copy the join's
checks a second time (inferred). Reusing `new_handle` with the profile's
handle instead of a new column: its unique key per project would refuse
the second placement of one profile, which the contract lets add an
instance. Re-reading the profile under the project lock only: the
deletion takes the profile's lock first, then the projects of the
profile's active memberships and of its active admitting placements
(`delete_profile`, then `placements.profile_deleted`), all chosen from
what it reads at that moment. A placement being created in a project
where the profile has neither, such as its first placement anywhere,
gives the deletion no project to lock, so only the profile's lock
serialises the two. Keeping the admission's
recheck symmetric with a member's own join, whose exchange leaves
`reports_to` alone: a join already handed out does not act on its
creator's continuing authority, the placement's join does (the ruling
on review A1826 above).

## The runner's session read takes pause, dormancy and the episode from the placement's project

**Id:** 17941eb5-af86-4341-b53f-e1ef9ef82b74
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** hub PR A (#2088, card tsk-yzj829xdmqyy), commits b81a9deb and 391f2b6f; the reviewer's proposal in that pull request's review; the lead's ruling there to keep `detached_at IS NULL`; docs/api.md §15.8, §6.17; `placements.py` `runner_sessions`
**See:** instances.md#an-instances-projects-are-rows-of-instance_attachment-pause-dormancy-the-commitment-and-the-handover-numbers-live-on-the-row — 8d07cc82-f612-4e24-aebe-72683131671b — as of 2026-11-21
**See:** events.md#an-episode-of-not-listening-lives-on-the-session-checked-by-a-minute-worker — 0cbc3037-5834-4a6d-b518-ae640fb47046 — as of 2026-11-21
**Revisit when:** hub PR D writes `detached_at`: a detached instance's placement then stops showing pause and dormancy but may still show an episode from its position row, and PR D must decide whether it should

`runner_sessions` (§15.8) reads the instance's pause and dormancy from its live attachment for
the placement's (credential, membership), and the not-listening episode from the open session's
`agent_session_project` row in the placement's membership. It reads the episode in the same
statement that finds the open session, as an outer join limited to the page's memberships, so
the page still costs a fixed number of statements. The keys (credential_id, membership_id) on
`instance_attachment` and (session_id, membership_id) on `agent_session_project` keep the join
from multiplying values. "Live" here means `detached_at IS NULL` only: a revoked credential's
pause and dormancy still show, as the credential row's did under #2079.

**Reason:** #2088 moved pause, dormancy and the episode off `credential` and `agent_session`
(§6.17). #2079's reads of the credential columns broke #2088's PostgreSQL shards, and once an
instance can be in several projects these values exist only per project.

**Rejected alternatives:**
- Keep reading the `credential` columns: they are gone with #2088.
- A third statement for the position rows: it would work, but the open-session statement
  already has the session ids, and the join adds no statement.
- `attached_now()`, which also drops revoked credentials: it would change #2079's answer for a
  revoked instance whose placement still closes. The lead ruled to keep `detached_at IS NULL`.
