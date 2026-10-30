# Availability

## Availability is computed on read; the announced state is stored, and a sweep notices what time alone changes

**Id:** 240dae0b-9ea9-4cbb-a447-5ca3d39b1f38
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (the availability slice)
**See:** https://github.com/oliver-zehentleitner/maity — 10798a45-310b-4c30-859f-30fea2454ece — as of 2026-10-23
**Revisit when:** a second replica runs (each would sweep the same projects), or one sweep takes longer than its interval

Every member view computes `availability` from the row as it is: pause,
stored limit, the owner's absence, presence. The membership also stores
the state the hub last announced, since when, and when the current outage
began. `reconcile` compares the two under the project lock and emits
`member_availability_changed` at an outage's start and end. It runs in
every request that changes an input (a limit, a pause, a resume, a
runner's report, the absence), and a worker thread runs it for every
project once a minute, which also clears passed limits and emits
`member_limit_ended`.

**Reason:** some ends of an outage come with no request at all: a limit's
`until` passes, an agent's session goes away. Computing on read keeps the
view right between sweeps; the stored state is what lets an outage be
announced once, gives `since` a stable value and gives the 24-hour lease
bound its start. The worker fits the single replica V1 runs, as the
probe's does.

**Rejected alternatives:**
- Compute only, store nothing: nothing to compare against, so nothing to
  announce once, and `since` would move with every read.
- Store the state only where a request writes it: a passed limit or a
  vanished session would never be announced.
- A timer per limit: lost on restart, and still blind to sessions going
  away.

## An agent's first look is a silent baseline; a human starts available

**Id:** 38589c62-d04b-40f6-b481-c1b9117c91e7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (the availability slice)
**See:** availability.md#availability-is-computed-on-read-the-announced-state-is-stored-and-a-sweep-notices-what-time-alone-changes — 240dae0b-9ea9-4cbb-a447-5ca3d39b1f38 — as of 2026-10-23
**Revisit when:** a client needs an event for an agent's very first state, or memberships get an initial state at creation

A membership without an announced state (every row after the migration,
every new agent until its first resume) is stored as it is found the
first time an agent's row is reconciled, with no event. A human's
missing state reads as `available`, so their first limit is announced.

**Reason:** after the migration every agent that is not running would
otherwise be announced as going out on the first sweep: a burst to the
admins and owners that reports no change. A human's only outage is a
limit or the owner's absence, both declared after this code exists, so
for them `available` is the true starting point.

**Rejected alternatives:**
- Announce whatever the first look finds: the burst above, once per
  deploy and once per new agent.
- Set the state when the membership is created: every new agent would
  start `offline` and announce a return on its first resume.

## A limit only ever lengthens a lease

**Id:** 98ea3f6d-dbc2-4163-92e2-e2717c794b9b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (the availability slice); stated in `docs/api.md` §6.12 "Leases under a limit" in the same change
**See:** https://github.com/oliver-zehentleitner/maity — 42d8258e-7dd7-4c6f-96e4-61926576d299 — as of 2026-10-23
**Revisit when:** the contract owner reads "moves the extension" as allowing a shorter lease, or a short limit is used to keep a card longer than intended

When a limit is stored, each lease the member holds becomes the later of
its current end and the target (`until` plus the grace, capped 24 hours
after the outage began). A second, shorter limit in the same outage, or a
limit shorter than the remaining lease, leaves the lease where it is.

**Reason:** the contract says leases are *extended*; a declaration is
there to keep the member's cards through an outage, not to hand them out
sooner than if the member had said nothing. The 24-hour cap still bounds
every hold, so keeping the longer end never holds a card past it.

**Rejected alternative:** set the lease to exactly the new target, the
literal reading of "moves the extension": a member that first declared
five hours and then thirty minutes would lose its cards hours earlier
than its first declaration promised, and a ten-minute limit would cut a
fresh two-hour lease to twenty-five minutes.

## A human's limit is stored on the account, an agent's on its membership

**Id:** 08e652fb-f5e6-4f0a-a7b7-b4fb84355ce4
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (the availability slice)
**See:** https://github.com/oliver-zehentleitner/maity — 83a2f234-1d68-4dc0-8451-f1ad1ff9dedc — as of 2026-10-23
**Revisit when:** absence moves from the project to the membership, or a human needs a different limit per project

`POST /me/limit` from a human writes `human.limit_*` and reconciles every
active membership of the account; from an agent it writes the agent
membership's own columns, next to the runner's placement that may have
set it. A slug in `show_reason_in` must be a project the human is a
member of (`not_a_member`), so a typo never silently hides the reason.

**Reason:** the contract says a human's limit applies to every membership
of the account, a project joined later included; one row holds that
without copies to keep in step. An agent's credential is one membership,
and a runner's limit belongs to one placement of it.

**Rejected alternative:** copy the human's limit onto each membership:
a membership created during the limit would miss it, and clearing it
would have to find every copy.

## A cover run is named by its start; on return every item of it loses `cover`

**Id:** 8e2ac695-1298-42a5-9c00-fb3fc7f5e20a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (availability stage 2, cover); the review of #285 by oz-agent-h (a return overwrote a third party's claim)
**See:** https://github.com/oliver-zehentleitner/maity — 10798a45-310b-4c30-859f-30fea2454ece — as of 2026-10-29
**Revisit when:** a moved item needs to show after the return who once covered it

The membership stores its cover state (`wait`, `covered` by whom since
when, `none_available`). Each card and request a cover moves, and each
card area routing sends to the substitute meanwhile, carries
`cover: {for, by, since}` with that run's start. On return only the items
of that run are settled: what the substitute touched stays with it,
everything else goes back, and `cover` is cleared on both. An item that
left the substitute meanwhile (the card reassigned, or claimed by a
third member) has its `cover` cleared and is never returned, so the
return never overwrites somebody else's claim or assignment. A returned
assignment gets its instance again by the member's team distribution
(`assigned_for`), as every assignment does (§6.18).

**Reason:** a kept card that kept its `cover` would look covered forever:
the next cover of its new holder would skip it, and a later return of
the first member would list it again. The run's start tells one cover
from the next without a table of its own.

**Rejected alternatives:**
- Keep `cover` on kept items as a record of where they came from: the
  two problems above; the events `cover_started` and `cover_ended`
  already record it.
- A table of cover runs with their items: a second place to keep in step
  with the cards and requests, for what one timestamp already names.
- Checking only `cover.by` at the return: a card that had moved on to a
  third member still carried the run's `cover`, so the return took it
  from that member and overwrote an active claim.
- Setting `assigned_instance` to null on the return: under `round_robin`
  the card lost its instance and lay with the whole team.

## Only a substitute that took something hears cover_started; what nobody could take is named once

**Id:** 045e13cf-6d97-4940-8a4a-4ab5e8dcc499
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (availability stage 2, cover)
**Revisit when:** a substitute needs to know it was skipped, or `left` has to reach every listed entry

A cover sends `cover_started` to each substitute that took at least one
item, and `left` (what no entry could take) only on the first of those
events. When nothing moved at all, the first available entry is told,
becomes `covered_by`, and receives area-routed cards meanwhile. When
the policy acts at once (a grace of 0), `member_availability_changed`
goes out before the cover.

**Reason:** the event wakes its audience; waking an entry that holds
nothing for the member only adds noise, and repeating `left` on every
event would make each substitute think it should do something about it.
The covered member, its boss and the admins are on every one of these
events and see `left` once.

**Rejected alternative:** one `cover_started` per listed entry, taken or
not: wakes members with nothing to do, and the contract names the event
by the substitute that covers.

## A substitute is chosen by the answer rule of a proposal's kind, not by `requests:answer` alone

**Id:** 4a789780-f18f-42fd-b51a-e2aa846eaf2c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the review of #285 by oz-agent-h (a delegated decision stalled at a substitute that got 403)
**Revisit when:** a proposal kind's answer rule depends on more than a scope and `humans_only`

For a `consent` request or a request that carries a proposal, the cover
order is walked with the kind's answer rule (`proposals.answerer`): the
entry must hold the rule's scope, with its own trust and role, and be a
human where the rule says `humans_only`. An entry that could not answer
is skipped, and the next one is tried; with nobody left, the request
stays with the covered member and is named in `left`.

**Reason:** `requests:answer` alone let a substitute take a request it
would then answer with `403`. The decision stalled there for the whole
cover, while the next member in the order, who could have answered, was
never asked.

**Rejected alternative:** check only `requests:answer` and let the
answer fail: the request is moved to someone who cannot settle it.

## A substitute acts with its own trust and role; cover transfers no scope

**Id:** 85937747-12e7-42bd-98d7-6fd923e18ef0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's ruling on the cover's rights against trust × role, the manager and takeovers, 2026-10-29 (the draft for the PR that replaces #285, and its two open points)
**See:** https://github.com/oliver-zehentleitner/maity — 10798a45-310b-4c30-859f-30fea2454ece — as of 2026-10-29
**Revisit when:** requests carry an `action` (§2.3, `action_needs_owner`: such a request then moves only to a human with trust `owner`), or cover is to move a manager's `line:lead`

Every check on a substitute reads its own trust and role
(`has_scope(trust, role, kind, scope)`), never the covered member's:
- The cover order is checked as it stands when the cover runs: an entry
  that has become a guest or a proxy since the policy was set is
  skipped, as a guest or a proxy never covers.
- An owner decision (`owner`, `trust:owner` or the owner's member id)
  moves only to a human entry; a human's `consent`, `contract` and
  `humans_only` requests only to a human.
- A `review` card never goes to an entry that holds the done authority
  (`tasks:review`, `tasks:test`, `tasks:admin` by `done_authority`).
- A card with an open takeover, an objection hold included, stays with
  the covered member (`left`); the takeover's `from` is not rewritten.
- A substitute gets no `line:lead`: a manager's cards and requests move
  like anyone's, and the reach, read from `reports_to`, is unchanged.
- A new takeover by an agent is held by the coordinator gate as `assign`
  is; `respond`, `escalate` and `withdraw` are not, nor are humans.

**Reason:** cover is the member's own policy acting during its outage,
not a grant: a substitute that acted with the covered member's rights
would hold, for a while, scopes nobody gave it. A takeover moves a card
on an agent's initiative exactly as an assignment does, so the gate that
holds one holds the other.

**Rejected alternatives:**
- Moving a card under takeover and rewriting the takeover to the
  substitute: the holder of an objection would argue with someone who
  never held the card.
- Gating every takeover call while the coordinator is out: a holder
  could then not answer or object to one that was already open.

## A cover does not chain; `covering` comes from the items each substitute holds

**Id:** 9beeec47-0887-4b6b-9da3-108d97737cbc
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the reviews of #626 (2026-10-30) and the coordinator's ruling on them that `covering` is derived from the items
**Revisit when:** a substitute's own outage leaves covered work waiting long enough to matter, or `cover` gains a second level

Cards and requests that already carry `cover` are not in the next cover
set (`cover.is_(None)` in `_cover_set`). When a substitute goes out
itself, its own policy applies to its own work only; the covered
member's items wait with it until one of the two is back. A member's
`covering` lists every member of whom it still holds an item as cover
(`cover.by`): a card by the rule `cover.end` uses for the return
(`cover.still_with`), a request while it is open. `since` is the
earliest `cover.since`. A second entry that took what the first could
not sees the member as well; one that released or lost every item no
longer does; `covered_by` still names the run's first substitute. `covering` and `cover.end` share
the one rule, so what the view shows and what the return gives back
cannot drift apart; requests count only while open, because `end`
leaves an answered request with the substitute.

**Reason:** a chain would move the same card through several hands, the
returning member would not know where its work went, and `cover_ended`
could no longer name one run. `covering` from the membership row named
only the substitute the run started with, while the cards of a second
one carried `cover` too: the items are what a substitute actually holds.

**Rejected alternatives:**
- Passing covered items on to the substitute's substitute: the ping-pong
  that trust.md 10798a45 names as its revisit case.
- Returning them to the covered member's next list entry: a second run
  inside the first.
- `covering` from `membership.cover_by` alone: blind to every substitute
  but the first.
- `covering` from `cover.by` alone: a substitute went on listing the
  covered member after it had released the card or a third member had
  taken it over.
