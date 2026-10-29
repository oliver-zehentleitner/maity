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
the account first, then every organisation it belongs to in the order of their ids
(`orgs.lock_all_of`), then the projects of its namespace, and only then checks `blocker`, which refuses
with `org_last_owner` (`details.orgs`, the handles) for an organisation of which it is the only
owner, at `POST /me/deletion` as at the link's `POST`. Its memberships in organisations end with
the deletion, and the invitations it sent that are still open are withdrawn; the organisations
and their handles stay.


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

## An organisation's invitation is a personal consent request with no project, on the request row

**Id:** fa2cf0ea-591f-478b-a162-952ac0e138df
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.26, §7 "Personal requests", §18.1; the coordinator's ruling of 2026-10-29 on the card tsk-whe4wv1jpsae (the sender must be visible to the invited human)
**Revisit when:** a second thing without a project needs to ask a human (a request the instance files, a transfer between organisations), or the request routes are split by scope

The contract files the invitation as a `consent` request to the invited human with `project: null`
and `org: {id, handle}`. The `request` row got the case instead of a table of its own:
`project_id` and `asked_by` (a membership) are nullable, `org_id` names the organisation and
`asked_by_human` the human who invites, whom the invited human has to see (`asked_by` in the
view); a check allows no project only for a personal request with an organisation and no
asking membership. The personal routes work on it with three differences: they lock the
organisation's row where they lock a project (`routes.requests._locked_personal`), they write no
`request_*` project event (there is no project to write it to; the invited human learns of it
from the account record, which now carries `org_id` too), and the human's own withdrawal settles
the proposal like any other close, which for an invitation counts as their `no`. The bell counts
such a request in `inbox` and in no project's `by_project`; the listing and `GET /requests/{id}`
show `project: null` and the organisation; the account deletion withdraws the open ones that name
the human and those they sent before it ends their memberships.

**Reason:** the personal-request machinery already does everything an invitation needs (the
inbox, the answer with `go` and `no`, the position and read flag in the notifications, the
export, the withdrawal on deletion), and each of these places had to learn only that a request
may have no project.

**Rejected alternatives:**
- A table of its own for organisation requests with its own routes: it would repeat the answer,
  the withdrawal, the listing, the counts and the record, and a second inbox would have been a
  second place to keep in step.
- Hanging the request on a project of the organisation: an organisation may own none, and the
  request would then show in that project's lists and permissions.
- Keeping `asked_by` required and filing the request in the inviter's name as a membership: the
  inviter has no membership to put there.

## An invitation is closed by whoever closes it, with its reason; the answer only closes one that is still open

**Id:** 506a6ea2-4f34-4174-a86f-09c3c5c66200
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.26 "Adding a member" (contract #585, the coordinator's rules for who withdraws an invitation and when); the implementation of tsk-whe4wv1jpsae (part 2)
**Revisit when:** an invitation gets a second way to be answered, or the aliases of §6.24 let two names reach one human, which the contract's "two open invitations" rule is written for

`org_invitations.close` sets the row closed (`live` NULL, `closed_by` the reason: `revoked`,
`inviter_role`, `org_deleted`, `expired`, `superseded`, `invitee_deleted`, `inviter_deleted`) and
then withdraws its request. The request's own settlement (`org_invitations.settle`, run by
`proposals.settle` wherever a request closes) closes a row that is still open as `declined`, which
is the invited human's `no` and their withdrawal, and makes them a member on `go` only while the
invitation is open, not expired and the organisation not deleted, else the `go` is `transfer_stale`'s
sibling `invitation_stale`. A `go` also supersedes every other open invitation of the organisation
whose request went to the same human. Expiry is 14 days; it runs in a minute worker and at the
start of every read or filing in the organisation. The limit of 20 invitations per organisation
in 24 hours is counted from the rows, so a restart forgets none.

**Reason:** the reason of a closed invitation must be the one that really closed it, and a
settlement that closed every invitation the same way would lose it. Closing the row first makes
the settlement of the request that follows a no-op, so nothing is closed twice.

**Rejected alternatives:**
- Letting `settle` close the row with a reason read from the request's `withdraw_reason`: the row
  is written before the request, and a text is a poor key for logic.
- An in-process limiter for the daily 20 (`ratelimit.Limiter`): it forgets on every restart and
  does not hold across replicas, and the rows are there.

**Known limit:** an invitation names a human by their current handle only; the alias of §6.24
joins it with #523, together with the duplicate-name case above.

## A project's owner is a human or an organisation: `owner_id` for readers, two foreign keys for the database

**Id:** 5332d7e2-c492-4083-8527-9cff0630e16a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.25, §6.26; the coordinator's ruling of 2026-10-29 on the card tsk-whe4wv1jpsae (no polymorphic column without a foreign key)
**Revisit when:** a third kind of namespace owner exists, or the readers of `project.owner_id` are few enough to drop the redundant column

`project` and `project_alias` keep `owner_id`, now a `hum-…` or an `org-…` id and no longer a
foreign key, and gain `owner_human_id` (to `human`) and `owner_org_id` (to `org`), exactly one
set; a check (`tables.OWNER_SHAPE`) holds that and that `owner_id` is the same id. Every
reader, every join and the unique constraints on `(owner_id, slug)` stay as they were; every
write goes through `namespace.owner_values(owner_id)`, and the handle of an owner of either kind
is read by `namespace.join_owner` and `owner_handle`, outer joins on both tables. A project of an
organisation is created with `owner` in `POST /projects`, under the organisation's lock.

**Reason:** the database keeps a project from naming an owner that does not exist, which a
single column holding two kinds of id cannot say, and a project's owner is read in a dozen
places that need one id.

**Rejected alternatives:**
- One polymorphic `owner_id` with no foreign key: the integrity of the namespace owner would
  live in code only (the coordinator's ruling).
- Replacing `owner_id` by the two columns: every reader, the unique key `(owner_id, slug)` and
  every test that inserts a project would change, for the same guarantee the check gives.
- A generated `owner_id`: not portable across SQLite, PostgreSQL and MariaDB.

## The hub keeps an organisation's owners owners of its projects, and says which memberships are its own

**Id:** e8d259ff-3aa3-41fa-9258-8d9e3ddb3bf9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.26 "Organisation owners in its projects"
**Revisit when:** a membership may be kept for more than one organisation (a project owned by two), or an owner's seat should be visible apart from `org_owner`

`org_projects` keeps every owner of the organisation a member with trust `owner` of every
project it owns, archived ones included: one who is no member joins (`member_joined`, marked
`org_keep = 'created'`), one with a lower trust is raised (`member_updated`, `changed:
["trust"]`, `org_keep = 'raised'`, the earlier trust in `org_keep_trust`), one who holds `owner`
already is not marked. Becoming an owner (a promotion, an invitation's `go`), ceasing to be one
(a demotion, a removal, leaving, the organisation's deletion) and a project's creation call it,
all under the organisation's row lock. The ending reverses what the hub did: a `created`
membership ends as a removal does, a `raised` one returns to its trust, an own one stays. The
member view says `org_owner` for a human from the organisation's owners, not from the mark, and
no call demotes or removes such an owner while they own the organisation (`namespace_owner`).
The organisation cannot be deleted while it owns a project that is not archived.

**Reason:** the contract makes the organisation's owners the project's owners collectively, so
the hub does the memberships rather than leaving every owner to be added by hand, and the mark is
what lets it undo exactly that and nothing a person did themselves.

**Rejected alternatives:**
- Deriving the ownership from `org_member` at read time and giving no membership: the project's
  rules (trust, areas, the member list, `reports_to`) all work on memberships.
- Ending every owner's membership when they stop being an owner: it would remove seats they held
  before, or kept for another reason.
