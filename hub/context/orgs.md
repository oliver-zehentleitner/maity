# Organisations

How the hub keeps organisations, their members and the handles they share with humans (`docs/api.md` §6.24, §6.26).

## A human's and an organisation's current handle share one table whose primary key is the handle

**Id:** 5b83b989-f8b7-41c8-88dc-3e5e9d059e6a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.24, §6.26; the coordinator's ruling of 2026-10-29 on the card tsk-whe4wv1jpsae
**Revisit when:** a third kind of principal gets a handle, the aliases of §6.24 are stored in the same table, or an engine the hub supports cannot enforce a primary key under concurrent inserts

A human and an organisation may not have the same handle, and the check must hold under any
race on every engine (SQLite, PostgreSQL, MariaDB). `handle_register` has the handle as its
primary key and `kind` (`human`, `org`) and `owner_id` beside it; `owner_id` is unique, so a
principal has one current handle. Every path that makes a human (registration, `maity-hub
owner create`) or an organisation enters its handle in the same transaction, through
`handle_register.claim`, which runs the insert in a savepoint and answers `False` for the
loser. The migration entered every existing human. A row is never deleted: the handle of a
deleted account or organisation stays taken for good, so an old link or project name never
comes to mean someone else. `human.handle` and `org.handle` stay as columns, and
`registration_accounts.check_names` asks the register first. Agent profiles are not in it, their
handles are unique per owner only. An account's deletion leaves the row: the table is in
`DELETION_KEEPS` of `tests/test_per_human_tables.py`, which fails for a table that names a human
and is neither handled nor kept on purpose.

**Reason:** a primary key is enforced by the database itself, in the same statement as the
insert, so no path has to remember a lock or a check and a new path cannot forget it. The
alternative leaves the guarantee in code that every future creation of a human or an
organisation has to repeat.

**Rejected alternatives:**
- A check in code under a lock (a lookup of both tables while one lock is held): it works only
  while every path takes that lock, and a missed one would not fail anywhere.
- A unique index on each of `human.handle` and `org.handle` and a cross-check between them: a
  database cannot say that two tables share one namespace without a trigger, and the hub keeps
  no trigger on any engine.
- Putting the aliases of §6.24 in the same table now: they are another change (#523), and
  whether an alias belongs in the register is settled with it.

**Known limit:** `PATCH /orgs/{org}` takes no `handle` yet, and `{org}` resolves the current
handle only: the rename, the aliases and their limits wait for #523's alias table.

## An organisation's changes run under its row lock, and the caller's role is read under it

**Id:** 3d679346-7e9d-45be-a4f7-f1137a2a274e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.26 "One organisation, one lock"; the implementation of tsk-whe4wv1jpsae (PR 1)
**Revisit when:** a project can be owned by an organisation (the project locks and the order organisation row, then project then come in), or a change of an organisation's members is made outside `orgs`

Every change of who belongs to an organisation and in which role (`PATCH` and `DELETE` of a
member, the organisation's own `PATCH` and `DELETE`) reads the caller's role again after
`orgs.lock` has taken `SELECT … FOR UPDATE` on the organisation's row, and decides on that
role and on the owners counted under the lock. `POST /orgs` locks the creating human's row
first and counts the organisations they own under it, so two creations at `limit − 1` give
one organisation and one `org_limit`. Two owners who demote each other at once leave one: the
second call, running after the first, finds its caller no owner any more and gets `forbidden`
(`org_role`), not `org_last_owner`. A caller who is not a member gets `not_found` on every
route, before and after the lock, and so does a handle that names nothing.
The deletion of an account takes its place in that order: `account_deletion.confirm` locks
the account first, then the projects of its namespace, then every organisation it belongs to
in the order of their ids (`orgs.lock_all_of`), and only then checks `blocker`, which refuses
with `org_last_owner` (`details.orgs`, the handles) for an organisation of which it is the only
owner, at `POST /me/deletion` as at the link's `POST`. Its memberships in organisations end with
the deletion; the organisations and their handles stay.

**Reason:** a role read before the lock could be stale by the time the change commits, which is
how two demotions would both succeed and leave an organisation with no owner. One order (a
human's row, then the organisation's, later every project's) keeps the changes from waiting on
each other.

**Rejected alternatives:**
- A `CHECK` or trigger that the last owner stays: it cannot count other rows without one, and
  `org_last_owner` needs the organisation's handle in its details anyway.
- Reading the role before the lock and only counting owners under it: an admin demoted
  meanwhile would still change roles on a stale decision.

**Known limit:** `max_orgs_per_human` is read from the environment (`MAITY_MAX_ORGS_PER_HUMAN`);
the admin's value of §16.5 (`GET`/`PATCH /admin/settings/limits`) is not built, and neither is
the limit for agent profiles that shares it.
