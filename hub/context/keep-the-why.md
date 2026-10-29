# Keep the Why export

## The export lives in memory, read on request and refreshed in the background for the view

**Id:** f5af1bd9-bb11-4310-b751-334de2668dfe
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (docs/api.md §11.3), with the hub owner's notes on caches; waiting rule and the 30 s floor from the coordinator's adversarial review, 2026-10-22
**See:** outbound.md#reads-whose-host-comes-from-data-connect-to-the-address-that-was-checked — a196b7db-8af0-4863-8852-031d4dbb35f8 — as of 2026-10-22
**Revisit when:** a second replica runs (each would read the families on its own), or the families grow so large that a cold read after a restart is felt

`ktw.Cache` holds, per project, the last read of the whole family and
each member's last good export.
- **The endpoint** reads through when the entry is older than `max_age`.
  One read per project runs at a time. While it runs, other requests get
  the cached answer at once (`fresh: false`); a request with nothing
  cached waits at most half a second, then gets `503`.
- **No read more often than every 30 seconds:** `max_age=0`, and any
  other `max_age` below 30, is answered from the cache within 30 seconds
  of the last read.
- **The project view** only reads the cache. A missing or stale entry
  schedules one background read per project on a pool of two threads,
  so a view built right after a restart shows `null` until that read
  lands.
- **What is stored:** the summaries and the entries that need
  attention, cleaned, never the export itself.
- **Ending:** all of it ends with the process.
- **Budget:** one read of a family has 30 seconds, configs and exports
  together. A member not read by then is `timeout`. Anyone who can push
  to the repository could otherwise name a slow host and tie up threads.

**Reason:**
- §11.3 forbids storing the export: Keep the Why stays external, and
  the database holds nothing from `context/`.
- A view must never wait on up to 32 outbound reads, nor let anyone who
  can list projects trigger them in the request.
- A restart is rare, and the first request after it reads the family
  anyway.

**Rejected alternatives:**
- A table for the summaries: against §11.3 and its rule that only the
  cache keeps entries.
- Reading the family inside the project view when the cache is stale:
  up to 32 reads of 10 seconds behind a page load.
- Requests waiting for a running read to share its result: the route
  runs on the server's request thread pool, so every waiter holds a
  thread for up to the whole budget, and a few dozen requests for one
  slow family stall unrelated requests.
- Only `max_age=0` held to 30 seconds: `max_age=1` would re-read up to
  32 configs and exports every second against the operator's token.
- The probe's worker sweeping all families: it exists only with a
  forge token, and a public repository's families are readable without
  one.

## The in-process caches per project keep the newest written, up to a bound

**Id:** 07614661-8f1e-4f78-8cf6-d0906ed98461
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-7865c6c2gszb (the hub's in-process structures without a bound), the lead's ruling, 2026-10-29; `hub/src/maity_hub/bounded.py`; `hub/tests/test_bounded.py`
**Revisit when:** the load test (tsk-ryas52q9k53z) or prod's memory curve shows a bound too small (projects read anew too often) or too large; or projects can be deleted for good, so that their entries could go at once

The hub keeps several caches per project in the process. Each gained a
key for every project it served, and nothing removed one while it ran.
With open registration that grows with the instance. Each is now written
through `bounded.put`, which writes a key as the newest and drops the
oldest written beyond a bound:

| Cache | Bound |
|---|---|
| the Keep the Why answers (`ktw.CACHE`), largest at 10 to 100 KB a project; a dropped project takes its last good reads and its idle lock with it | 256 projects |
| the swarm page windows (`swarm.CACHE`) | 1024 |
| the reader chosen per project (`ForgeAccess._chosen`) | 1024 |
| the source last found (`forge_access._last_via`) | 4096 |
| the image read state per project and kind (`images`) | 4096 per map |

What a dropped key held is read or computed again on its next use. For
`_last_via` that means the default source shows until the next choice. A
gate that a read holds right now is never dropped. The maps that were
written without a lock (`ktw.last_good`, the image maps, `_last_via`) are
now written under their module's lock, because dropping walks the map
while other threads write it. `ktw.Cache.forget` drops the project's idle
lock too.

**Rejected alternatives:**
- Forgetting a project when it is deleted, as first planned: the
  hub deletes no project for good (an archived one is still viewed), so
  nothing would ever call it.
- An age limit alone: it bounds how old an entry is, not how many
  there are, so many projects viewed within the hour still grow the map.

## The Keep the Why policy stores only what a human set; the provider keeps its boolean column

**Id:** a0966b9e-2263-44c1-9098-3c1f5d709911
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session of the card for the memory provider and the Keep the Why policy, 2026-10-27; `docs/api.md` §6.1, §6.23
**Revisit when:** a second memory provider is added, or the policy needs a third value

`policy.keep_the_why` is read as `required` while the provider is `keep-the-why`
and nobody set it, `optional` under `none`. The column `keep_the_why_policy`
holds only a human's own value and is `NULL` otherwise; the policy object
carries the effective value, and `policy.columns()` never writes it back. The
provider stays in the boolean column `keep_the_why`; `memory.provider` is derived
from it, so no data migration and no second source of truth. The column is
storage only: since the cleanup before launch (2026-10-29) the API no longer
takes or shows a boolean `keep_the_why` next to `memory.provider`; only
`memory` names the provider. It was removed rather than kept as a silent
synonym because the maintainer's rule before launch is to drop legacy instead
of keeping compatibility layers (Maity is alpha, with one user). A project's
`keep_the_why_defaults` is a plain column with the default `adopt`.
`MAITY_KTW_SKILL_SOURCE` must be an `https` URL and the hub stops at start
otherwise: the three texts it produces are instructions that an agent reads.

**Reason:** every policy write rewrites all policy columns from the current policy
object. Storing the effective value would freeze the default on the first
unrelated policy change (a badge, a preset), so a project on `none` would
come back from `none` as `optional` instead of `required`. A provider
column would have had to be kept equal to the boolean the rules text and the
packet already read.

**Rejected alternatives:**
- Store the effective value in every policy write: freezes the default, as
  above.
- A `memory_provider` string column with the boolean as a mirror: two columns
  that must agree, for one provider. Replacing the boolean by a string column
  when the alias went was left out too: one provider fits a boolean, and a
  migration buys nothing until a second provider exists (its revisit
  condition).
- Accept any URL scheme for the skill source: the value ends up in an
  agent's instructions, so a `file:` or `javascript:` source is refused.

## The commitment's deadline is fixed on the credential; a minute-sweep and the policy change reconcile what is owed

**Id:** 2ac9f413-eaad-4e40-9637-af4430cb0128
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session of the commitment pull request of the memory-provider card, 2026-10-28; `docs/api.md` §6.23
**Revisit when:** a deadline or an owner's request has to be visible without a credential row, or the sweep's one-minute delay is a problem for a withdrawal

An instance is a credential, so its commitment lives on the credential row:
when it confirmed and in which session, its deadline `acknowledge_by`, the
time of the reminder and the id of the owner's request. The first resume under
`required` sets the deadline once; later resumes change nothing. One
reconcile function does the rest, and a worker runs it once a minute for
projects that still have an unconfirmed instance with a deadline: it sends the
reminder to an instance with an open session, files the owner's request 30
minutes after the deadline, and withdraws that request when its cause has ended
(the instance revoked or replaced, the membership ended, the profile deleted,
the policy `optional`, the provider `none`). A change of the policy or the
provider runs it at once. A resume runs it for its own instance once the new
session is open and any pause is cleared, so a reminder that fell due while no
session was open comes at that resume, as §6.23 asks. A new owner of the
profile gets the request, the old owner's is withdrawn.

**Reason:** the causes that end a request live in many modules (credentials,
memberships, profile deletion, ownership); one function that compares the
state to what is owed cannot miss one, where a hook in each place can. The
policy change is the one a human watches, so it runs at once; the other causes
wait for the next sweep, at most a minute.

**Rejected alternatives:**
- A withdrawal hook in every place that ends a cause: seven places, and a
  missed one leaves the owner with a request about something that is over.
- Remind at the next resume only: an agent that is already working would never
  hear of its deadline.
- Leave a missed reminder to the sweep after the next resume: the agent would
  read its packet and start working before the reminder woke it, up to a
  minute later; the review of the commitment pull request asked for it at the
  resume itself.
- Keep revoked credentials in the sweep until a cleanup job: a credential that
  owes nothing has nothing to reconcile. The sweep resets it when it withdraws,
  so the sweep's cost follows the outstanding commitments, not the history of
  instances.

## The why on a report is validated by the hub in code, and only its shape is checked

**Id:** 71939c22-e16b-42ba-9621-8454bb93d0ae
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session of the commitment pull request of the memory-provider card, 2026-10-28; `docs/api.md` §6.23
**Revisit when:** the hub may read the repository of a report's pull request, or the contract asks the hub to resolve a `ref`

`why` on a code report is validated in `_check_why`, not in the request model:
pydantic's error types are not the reasons the contract names (`malformed`,
`not_for_no_code`, `required`). The hub checks the shape (`ref` as
`<path>.md#<id>` with a relative path, or `none` with at least 10 characters)
and the policy's rule on when `why` is required. It does not read the file:
the repository is not the hub's to read, and the review is the gate that the
entry exists.

**Rejected alternative:** refuse a `ref` the hub cannot resolve. That would need
the probe to read the pull request's head and would fail reports whenever the
forge is slow.

## A human's `policy.keep_the_why` is a policy change even when the view does not move

**Id:** 3ea58d8b-ccdd-41f7-8a15-f444565d803e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review findings on the policy pull request (a P2, fixed in commit 3521a9d2; recorded after a P3 of the second review), 2026-10-28/29; `docs/api.md` §6.1, §6.23
**See:** keep-the-why.md#the-keep-the-why-policy-stores-only-what-a-human-set-the-provider-keeps-its-boolean-column — a0966b9e-2263-44c1-9098-3c1f5d709911 — as of 2026-10-29
**Revisit when:** the stored and the effective policy become one value, or §6.1 stops requiring a reason for every policy change

An explicit `policy.keep_the_why` is compared with the stored column
`keep_the_why_policy`, not with the policy as it reads. When it differs, the
change needs `reason`, bumps `rules_version` and emits `policy_changed`, even
when the policy reads the same before and after (`optional` set while
`memory.provider` is `none`). An explicit `null` is refused (`unknown`): it
would clear the human's value without naming one of the two §6.1 allows.

**Reason:** the stored value decides what the project reads once the provider
is switched back on. A human who sets `optional` under `none` changes what
happens later, so it leaves the same audit trail (reason, version, event) as
any other policy change.

**Rejected alternative:** compare with the policy view, as every other field
is compared. Under `none` the view already reads `optional`, so the change
would have been dropped silently and the human's intent lost on the next
switch to `keep-the-why`; this is how the first version behaved.

## The installer line is non-interactive and names no agent

**Id:** e8e57725-6f5a-4922-a151-3d6b0a16a6e5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review finding on the policy pull request and the contract owner's ruling, 2026-10-29; `docs/api.md` §5.2, §6.23; keepthewhy.com/installation
**Revisit when:** the skills installer changes its flags, or the hub learns the installer's id for an agent's harness

`skill.install[0]` is `npx skills add <source> -g -y`: for every project of
the user, with no prompt.

**Reason:** without flags the installer asks which agents and which scope to
install for. An agent's shell has no terminal to answer, so the agent stalls
at the prompt or the installer aborts.

**Rejected alternative:** add `-a <agent>` as the installation guide shows for
agents. The hub knows only the harness name a session reports (`Claude
Code`), not the installer's id for it, and a mapping from one to the other
would be a guess. An agent that needs it finds it through `skill.guide`.

## The Keep the Why policy fields are `humans_only`, not a scope

**Id:** c8554ba1-73f0-4c38-804d-c2256befefdc
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review findings on the policy pull request and its follow-up, with the contract owner's ruling, 2026-10-29; `docs/api.md` §2.3, §6.1, §6.23
**Revisit when:** an agent role is meant to set what is asked of agents, or §2.3's list of fields no agent changes is replaced

`policy.keep_the_why` and `policy.keep_the_why_defaults` are in
`HUMANS_ONLY_POLICY`: every agent, an admin agent included, gets `403
humans_only` before any scope is checked.

**Reason:** both fields decide what is asked of every agent: the commitment and
the `why` on reports, and whether a joining agent takes the project's personal
defaults without asking its human. An agent that could change them would set
its own obligations. `humans_only` also tells the agent that no role would let
it, where a scope error suggests that a better role would.

**Rejected alternative:** leave them to the `project:admin` scope, as the
first version did. Today only humans hold that scope, so the effect was the
same, but the answer was a bare `forbidden {scope: project:admin}`, and the
fields would open to agents the day an agent role gained the scope.

## `skill.guide` is an instance setting, https only

**Id:** 44722ffc-ead3-4f07-8744-204609053b2f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review finding on the policy pull request, 2026-10-29; `docs/api.md` §6.23, §16
**Revisit when:** projects need their own installation guide, or the packet's texts stop being instructions an agent follows

The installation guide in the packet's `skill.guide` comes from
`MAITY_KTW_SKILL_GUIDE` (default `https://keepthewhy.com/installation/`) and is
checked like `MAITY_KTW_SKILL_SOURCE`: an `https` URL, or the hub does not
start.

**Reason:** the value ends up in every agent's instructions and is the page an
agent names to its human. A `file:`, `javascript:` or plain `http` value would
put an untrusted or local target there. An operator who mirrors the skill
mirrors its guide the same way, so one instance setting is enough.

**Rejected alternatives:**
- A per-project setting: a project admin could point every joining agent at a
  page of their choosing, and no project has asked for its own guide.
- Accept any URL as configured: the check costs one function, shared with the
  skill source, and a wrong value is caught at start, not by an agent.

## Setup options live in a column of the project; the setup cards are the hub's, found by their kind

**Id:** 56fcd342-aa6a-4191-8701-e76fc49be399
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session of the setup-cards pull request of the memory-provider card, 2026-10-28; `docs/api.md` §6.21
**Revisit when:** a project may change its setup options after creation, or setup cards need to be told apart by option

`project.setup` is a JSON column holding the three booleans and `cards`: `null`
before the cards exist, the list of ids after (`[]` when no option was on),
and the whole column `NULL` for a project that predates it. The cards carry
`kind: setup`, which only the hub creates (`POST …/tasks` answers `kind: hub_only`).
The packet's `setup` is read from the cards by kind and status, not from the
stored id list, so a cancelled or done card drops out without any bookkeeping.
The body of `setup` is validated in code: the contract names the reasons
`not_a_boolean` and `unknown_field`, which pydantic's own types would not give.
The Maity badge card carries the §6.20 snippet with path addresses (§16.11),
never a hash route: the snippet ends up in a README for good, and the hub serves
no `/#/…` and no redirect from it.

**Reason:** the options are chosen once at creation and the cards do not change
them, so the column is the record of the choice, and `cards` being `null` is
what tells "no repository yet" from "processed, nothing to create". The
packet has to follow the board, where owners cancel and agents finish cards,
and the board is the cards.

**Rejected alternatives:**
- Derive `setup` from the cards alone: a project with no repository has no
  cards yet, so the choice would have to live somewhere else anyway.
- Keep the options in `settings`: that object is merged and shown to clients
  as editable, and `setup` is read-only after creation.
