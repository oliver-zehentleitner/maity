# The project namespace

How the hub serves projects as `<owner>/<slug>` (`docs/api.md` §6.25).

## `ProjectRoute` hands a route the full name as its `slug` parameter

**Id:** 1d27a56e-d926-4505-b731-dee852742c63
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the hub card "project namespace owner/slug" (contract #424); the coordinator's ruling of 2026-10-27 on the order (this PR before trust × role and handle aliases, the route rewrite as a script)
**Revisit when:** FastAPI stops passing a route class's rewritten path parameters to the dependencies, or a project route needs the owner and the slug apart

Every project route is declared as `/projects/{owner}/{slug}/…`, and every
router that has one uses `namespace.ProjectRoute`. Before the dependencies
and the endpoint run, it rewrites the request's path parameters so that
`slug` holds `<owner>/<slug>` and `owner` is gone. Every endpoint, `deps`
and `access.membership` therefore keep their one `slug` argument, and
`namespace.resolve` turns the full name into the project: the owner by
handle (`resolve_owner`), then the pair of the owner's id and the slug
among current names and `project_alias` rows. `scripts/namespace_codemod.py`
does the mechanical part (the route paths, the router class, the tests'
paths into the `maintainer` namespace of `tests/flow.py` and `tests/factory.py`).
It is idempotent, and a rebase runs it again instead of merging the
literals.

**Reason:** about 100 endpoints and the dependencies take the slug from the
path. Changing each signature would touch every handler and conflict with
every hub card in flight. The schema still lists `{owner}/{slug}`, which is
what clients read: the CLI matches its routes against `openapi.json`.

**Rejected alternatives:**
- An owner parameter on every endpoint: the same change a hundred times,
  and a hundred places to forget it.
- Rewriting the ASGI path to one segment (`owner~slug`) and keeping the old
  route paths: the schema would describe routes that do not exist.

## Old project paths are answered before routing, from route words that come from the schema

**Id:** ca7ae163-4698-4c3a-ae08-0fd24fabb3b7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.25 "Old routes"; FastAPI 0.159 keeps included routers behind `_IncludedRouter` objects, found while building this
**Revisit when:** a project route is left out of the schema, or the hub serves the old routes as `v1` next to a `v2`

Until 2026-10-29 the middleware answered a project path from before the namespace
(`/projects/<slug>` alone, or `/projects/<slug>/<word>/…`) before the body
was read, before authentication and without a lookup: `client_outdated`
(426) to a `maity-cli/…` User-Agent, `project_path_outdated` (410) to
everyone else; the forge webhook kept a pre-migration project's old address and the old badge
and public swarm addresses answered `301` (all through `legacy_slug`; the public swarm
page itself is gone since 2026-10-30, §6.22). That answer, those
addresses and the column itself (migration 0086) are removed: the maintainer's alpha rule is to
keep no compatibility layer, so an old path is `not_found` like any path, see
261f1ce2-819b-4aac-ae4a-387bb83d0907.

What stays is the slug check. The words are the literal segments that follow `{owner}/{slug}`
in the app's schema paths, joined with the set at this change as a floor and, since the same
date, the dashboard's project views (`paths.PROJECT_VIEWS`); that set refuses a slug at
`POST /projects` (`reserved`). The first segments the hub and the dashboard use are refused as
human handles, at registration and in `owner create` (`paths.RESERVED_FIRST`, §16.11).

**Reason:** an old path always has a route word where a new path has a
slug, so recognising it needs no database, and the answer cannot say
whether a project exists. Reading the routes from the schema follows
every route added later. The floor keeps a word reserved even if its route
ever leaves the schema. The badge and swarm addresses had to move in this
PR: a lookup by the current slug alone is ambiguous once two owners share
one, and a project made after the migration has no old address.

**Rejected alternatives:**
- Walking `app.routes`: FastAPI hides included routers behind internal
  objects, and their paths are not listed there.
- Comparing the CLI's version with a minimum: every caller of an old path
  is outdated already.

## The namespace leaves two hooks for the trust and alias cards

**Id:** 3de94ffb-3359-4af4-b0f7-0f6ffba9d903
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's ruling of 2026-10-27: this change lands before the hub cards for trust × role (`tsk-tryqzr76gh9q`) and for handle aliases (`tsk-xsqc4whfqj4h`), with the hooks named so that they are found
**Revisit when:** either card lands; then this entry is superseded by what it built

The hub had neither handle aliases nor a trust column, nor a request
`action`, when the namespace came. Two places stand in for them:
- `namespace.resolve_owner` resolves a namespace owner by the current
  handle only. The alias card extends this one function, so that
  `<old handle>/<slug>` reaches the project (§6.25 "Resolution").
- Migration 0060 rewrites no `action.path`, because the column does not
  exist yet. The migration that adds `action` writes paths in the
  `<owner>/<slug>` form.
The namespace owner is chosen by the `owner` role (the oldest active human
with it), since that role becomes trust `owner` in the trust migration.

**Reason:** the coordinator ordered this change first because it rewrites
every project route. Both cards would otherwise conflict with it on nearly
every file.

## Migration 0060 picks the namespace owner, stops rather than guesses, and keeps a downgrade possible

**Id:** a5ba3910-0b5d-496b-a065-9e55eac4ecfc
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.25 "Migration from instance-wide slugs"; the hub schema at 0055 (no creator column)
**Revisit when:** the project table records its creator

The namespace owner is the human with the oldest active `owner` membership,
ties by id. The creator's membership is the first of every project, so
while the creator is still an active owner it is the creator. A project
without such a human, a slug that is a route word, or a human handle that
is a dashboard word stops the migration. The message names each one for
the operator. Every existing project keeps its slug as `legacy_slug` (the column was dropped by 0086). A
limit's `show_reason_in` is rewritten to full names. The downgrade appends
the project id to slugs that two owners share (all but the oldest), as
0032's downgrade does for handles, so that the old instance-wide key holds
again.

**Reason:** the contract makes the creator the owner, but the schema keeps
no creator. The first owner membership is the creator by construction.
Guessing an owner for a project without one would hand a namespace to the
wrong person.

**Rejected alternatives:**
- An agent or a removed human as the fallback: the namespace owner is a
  human with trust `owner` (§6.25).

## A stale transfer `go` withdraws its request after the answer rolled back

**Id:** 7b5643b4-4feb-4a02-a037-9883745656da
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §6.25 "Transfer" (refuse the answer, withdraw the request, change nothing); the proposals mechanism of `hub/src/maity_hub/proposals.py`
**Revisit when:** a second proposal kind needs to close its request on a refused answer, or the answer route gets a general way to commit part of a refused call

The transfer is a `project_transfer` proposal. Its settle hook runs inside
the answer's transaction. When the `go` no longer applies (a changed owner
or name, a receiver no longer owner, a taken slug), the contract wants the
answer refused **and** the request withdrawn, with nothing else changed. The
hook raises `proposals.Stale(error, request_id, reason)`. The answer's
transaction rolls back completely, and the answer route then withdraws the
request in a transaction of its own (`close_request`, which does nothing if
the request is no longer open) and raises the error.

**Reason:** a refusal is an exception, and every write before it rolls back
with it, the withdrawal included. Two transactions keep the refusal's
"nothing changes" for everything but the withdrawal the contract asks for.

**Rejected alternatives:**
- Withdrawing in the answer's transaction and returning an error outcome:
  the answer, already recorded in the same transaction, would commit with
  it, and the error would bypass the hub's error rendering
  (`Maity-Error`).
- Leaving the request open as other failing settles do (`proposals.md`):
  the contract says it is withdrawn, and a stale `go` would stay
  answerable forever.

## Renames and transfers per day are counted from `project_updated` events

**Id:** 74f0a2a8-d9ac-413d-a14b-fde9f3a0ad8c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §6.25 "Aliases" (3 per 24 hours per project), §6.24 (a name taken back leaves the list)
**Revisit when:** the event log is pruned within 24 hours, or a rename stops emitting `project_updated` with `full_name`

`namespace.check_change` counts the project's `project_updated` events of
the last 24 hours whose `fields` include `full_name`; `Retry-After` is
counted from the oldest of the last three. A name taken back is removed
from `project_alias`, as a handle taken back leaves a member's aliases
(§6.24), so the list never shows the current name. It is never given to
another project either, since it is the current name again.

**Reason:** every rename and every transfer emits exactly one such event in
the transaction that changes the name. The log is already the record, and
counting from it needs no migration.

**Rejected alternatives:**
- Counting `project_alias` rows by `created_at`: a name taken back adds no
  row and removes one, so the count would miss changes.
- A counter column or a table of changes: a migration and a second record
  of what the log holds.

## Claiming a slug locks the namespace owner's row

**Id:** 40bb824a-6d56-405e-bca1-5bae5600ecdc
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** review of the rename and transfer pull request (a create racing a rename); `docs/api.md` §6.25 "a full name belongs to one project, for good"
**Revisit when:** names and aliases move into one table with one unique index, or projects get an owner other than a human

`namespace.taken` locks the namespace owner's `human` row (`FOR UPDATE`)
before it looks. Every caller is about to claim the slug: a create, a
rename's `check_change`, and a transfer's `go`. Claims in one namespace
therefore run one after another.

**Reason:** a project's slug is unique per owner by `uq_project_owner_slug`,
and an alias is unique by its own index. Nothing ties the two together. A
create of `s` that checked before a rename away from `s` committed could
otherwise commit beside the alias `s`, and the old name would then resolve
to a different project.

**Rejected alternatives:**
- One constraint across both tables: SQL has no unique index spanning two
  tables, and a shared name table would be a migration of every project.
- Checking again just before the alias insert: without a lock the second
  check races in the same way.

## A transfer asks for no step-up until the second factor lands

**Id:** ab5aa0b9-37cf-4d45-abe4-96b1326747e4
**Type:** workaround
**Status:** open
**Evidence:** confirmed
**Source:** `docs/api.md` §6.25 and the endpoint table (the namespace owner transfers "human, with the step-up"); review of the rename and transfer pull request
**Revisit when:** the second-factor pull request #471 (`second_factor.require_step_up`) is on `main`; card tsk-svg6mfthm7xv

`POST /projects/{owner}/{slug}/transfer` does not call a step-up yet: the
hub this landed on has no second factor. Whichever of the two pull requests
merges second adds `second_factor.require_step_up(conn, hub, caller)` to the
transfer route before `transfer(...)`, plus a test. Until then a stolen
session of a namespace owner can file a transfer, which still needs the
receiver's `go`.

## A human membership that ends checks the namespace owner

**Id:** 035104e6-f041-4d9e-9813-163671458358
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** `hub/src/maity_hub/routes/members.py` (demotion and removal); review of the rename and transfer pull request
**Revisit when:** a route deletes a human account or ends a human's membership in another way

A project's namespace owner must stay one of its owners (§6.25). Today a
human's owner membership ends or drops in two places, the demotion by
`PATCH` and the removal by `DELETE` in `routes/members.py`, and both call
`namespace_owner_of` after the last-owner checks. A route added later that
deletes a human account, or ends a membership any other way, has to call it
too. Otherwise a project keeps a namespace owner who is no longer in it.
