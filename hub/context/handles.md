# Handles and aliases

## A handle given up becomes a row in one alias table, scoped by where handles are unique

**Id:** dd5b64e5-289d-4c8c-877e-8d246149bda7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.24 (contract #420); the coordinator's go on the plan for the card, 2026-10-28
**See:** namespace.md#the-namespace-leaves-two-hooks-for-the-trust-and-alias-cards — 3de94ffb-3359-4af4-b0f7-0f6ffba9d903 — as of 2026-10-28
**Revisit when:** a third kind of principal gets handles, or the alias cap moves

`handle_alias` holds one row per handle an id gave up, for humans and agent
profiles alike. Its `scope` is where the handle is unique: `human` for every
human, the owner's id for an owner's profiles. A deleted profile's aliases get
`live` NULL, as the profile itself does, so that the same owner may take the
handle and its aliases again at once (§6.3). Whether a name is taken is one
question for every path that gives a handle (`handles.ensure_free`): the
current handle, an alias, or an active placement that will create a profile
with it.

**Reason:** an alias must stay with its id and block everyone else, which a
column on `human` and `agent_profile` cannot express for a list of up to
eight, oldest first. One table keeps the cap, the order and the take-back in
one place.

**Rejected alternative:** a JSON list on each row — no unique constraint can
see inside it, so two ids could hold the same alias.

## A rename and a creation take a lock on the handle they want, not one on the whole scope

**Id:** ddfd0481-7a0a-4ebd-8a33-fc5e5c2787e1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the plan reported to the coordinator for the card, 2026-10-28 (it named an instance-wide lock for humans and was approved); the implementation, same day
**Revisit when:** a database shows lock waits on `handle_lock`, or handles get a third scope

`handles.lock` takes the row `(scope, handle)` in `handle_lock` (made when
first asked for), after the renamed id's own row. Two claims of one handle in
one scope run one after the other; renames of other handles never wait, and
nothing reads under it. The plan said "instance-wide lock for humans"; this is
the same guarantee with a finer grain, so a registration never waits for an
unrelated rename. The coordinator has not been asked about the change of grain.

**Reason:** a unique constraint cannot span the handle column and the alias
table, so the check "taken" needs a lock that both a rename and a creation
take, and the lost-update race (two renames to one handle, both seeing it
free) has to end in exactly one winner.

**Rejected alternative:** one lock for the whole human scope — correct, but
every registration and rename would queue behind each other for a rare event.
Relying on the unique constraints alone — they catch a handle against a
handle, not against an alias.

## The rename limit is counted in the database, not in the process

**Id:** 6a41b787-0a40-4d74-a320-f853f5658ca3
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the implementation of the card, 2026-10-28; `ratelimit.py` (in-process, one replica)
**Revisit when:** the hub keeps its limits in the database as a whole

Three renames in 24 hours per id (§6.24) are rows in `handle_change`, counted
under the renamed id's row lock. A no-op leaves no row.

**Reason:** the limit protects other people's names from churn, so it must
survive a restart and a second replica; the in-process `Limiter` forgets on
restart.

**Rejected alternative:** `ratelimit.Limiter` — fine for a login budget that
is minutes long, not for a window of a day.
