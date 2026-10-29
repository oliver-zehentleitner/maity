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
provider stays in the boolean `keep_the_why`; `memory.provider` is derived from
it, so no data migration and no second source of truth. A project's
`keep_the_why_defaults` is a plain column with the default `adopt`.
`MAITY_KTW_SKILL_SOURCE` must be an `https` URL and the hub stops at start
otherwise: the three texts it produces are instructions that an agent reads.

**Reason:** every policy write rewrites all policy columns from the current policy
object. Storing the effective value would freeze the default on the first
unrelated policy change (a badge, a preset), so a project on `none` would
come back from `none` as `optional` instead of `required`. A provider
column would have had to be kept equal to the boolean the view and the rules
text already read.

**Rejected alternatives:**
- Store the effective value in every policy write: freezes the default, as
  above.
- A `memory_provider` string column with the boolean as a mirror: two columns
  that must agree, for one provider and one alias.
- Accept any URL scheme for the skill source: the value ends up in an
  agent's instructions, so a `file:` or `javascript:` source is refused.

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
