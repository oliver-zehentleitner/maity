# A project's limits and their ceilings

## A ceiling resolves project override, account override, default; `unlimited` is the bound of 1000; an override PATCH locks its parent row first

**Id:** 3e9b7c41-5a2d-4f86-b0c3-8d17e64a92f5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-t63d50qy3s0k and tsk-spmhjqm7szag (built by jg97 on agent-e/limits-hub, finished by k5ax); the lead's decisions of 2026-11-18 on PR 2 (seq 160760: the `out_of_range` alignment, the lock in `limit_overrides.patch`, the CLI in its own PR; seq 160775: the migration slot after #1938); contract `docs/api.md` §6.31, §16.5, §16.5.1; code `hub/src/maity_hub/ceilings.py`, `hub/src/maity_hub/limit_overrides.py`, `hub/src/maity_hub/placements.py`
**Revisit when:** the members, placements or credentials lists get paging (the bound of 1000 could move); or plans (§2.7 part two) set limits per account; or a project gets more than one owner account
**See:** https://github.com/oliver-zehentleitner/maity — 7d8669c6-3dd9-4b4f-a257-8a9135cf1141 — as of 2026-11-18

The four values a project or a membership sets (`max_placements`, `member_agents_max`,
`max_open_claims`, `max_instances`) are each set at most up to a ceiling, resolved first to
last: the instance admin's override on the project; the override on an account; the default
ceiling, which is the product bound the hub had before ceilings (1000, 20, 1000, 16), so a hub
with no override behaves as before. The account is the project owner's for the first three (none
for a project in an organisation's namespace) and the agent profile owner's for
`max_instances`: an agent's instances are its owner's, whoever owns the project it works in.
`unlimited` is stored as the string and resolves to the hub's bound of 1000 (`ceilings.BOUND`),
never past it. The value in effect is the stored value, or the ceiling when that is lower; a
ceiling lowered below a stored value ends nothing and only refuses new things. A placement's
creation or proposal meets the same `max_instances` in effect as a join and the pickup do
(`placements.refuse_over_instances` resolves it through `instances.max_instances_limit`), so
the ceiling holds however an instance comes about.

Only who holds the right that sets a value reads the ceiling's `value` in the quota details
and the overview (`project:admin` for the project's values, the agent's owner for
`max_instances`); everyone else reads its `source` alone. `raise` names a right and a path,
for the operator always the project's admin route, never the account route.

`limit_overrides.patch` takes the parent row's lock before it writes: the project's row
(`events.lock_project`), or for an account the human's `account_lock` shared and then the
human row `FOR UPDATE`, the order `write_guard` and the account deletion keep. It then deletes
and inserts one row per field. `PATCH /admin/settings/limits` answers a value outside its
range with the reason `out_of_range`, as the per-project and per-account routes do; the
dashboard reads `invalid` too for one release.

**Reason:** the defaults protect an instance that serves strangers, and an override must not
change anything for anybody else (`context/scope.md` 7d8669c6). The project override comes
first because it is the operator's most specific word. 1000 stays because the lists that
carry members, placements, an agent's credentials and a runner's placements come in one
answer without pages, and `wake: all` wakes every instance one by one. An override is a
number the operator set for a person, so only those who set the value need it. Without the
lock, two `PATCH`es of one field both delete the row that is not there yet and both insert;
the second fails on `uq_limit_override_project`/`uq_limit_override_human`, a 500 on
PostgreSQL (SQLite's `BEGIN IMMEDIATE` hides it). Under the lock the second waits and replaces
the first's row. One reason code for one kind of error across the limit routes lets a client
read one.

**Rejected alternatives:**
- Account override before project override: the account value is a blanket for every project
  a human owns, the project value the exception for one; the other order would make the
  exception unreachable.
- `unlimited` as no bound at all: one project could make a list the hub answers in one piece
  without end; paging comes first.
- `max_instances` from the project owner's account: the instances belong to the agent's
  owner, who sets `team.max_instances`; a project owner's override would decide about agents
  that are not theirs.
- An upsert (`ON CONFLICT … DO UPDATE`) for the race: it needs a statement per dialect
  (PostgreSQL, MariaDB, SQLite), where the hub's other writes of one parent's rows take the
  parent's lock; the lock also orders an override `PATCH` against a policy `PATCH` of the same
  project, which reads the ceiling under the same project lock.
- Keeping `invalid` as the reason in `PATCH /admin/settings/limits`: two spellings for the
  same refusal on neighbouring admin routes; the code `invalid` stays, only the field's
  reason changes, and the dashboard reads both for one release.
