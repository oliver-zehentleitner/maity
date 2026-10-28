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

The middleware answers a project path from before the namespace
(`/projects/<slug>` alone, or `/projects/<slug>/<word>/…`) before the body
is read, before authentication and without a lookup: `client_outdated`
(426) to a `maity-cli/…` User-Agent, `project_path_outdated` (410) to
everyone else. The words are the literal segments that follow `{owner}/{slug}`
in the app's schema paths, joined with the set at this change as a floor.
The same set refuses a slug at `POST /projects` (`reserved`). The
dashboard's top-level route words are refused as human handles, at
registration and in `owner create`. The forge webhook keeps a
pre-migration project's old address through `legacy_slug`. The old badge
and public swarm addresses answer `301` to the new ones while they are
served, and otherwise the same `not_found` from the same shared bucket.
Any CLI that calls an old path is older than the release by construction,
so no version is compared.

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
**Status:** needs-review
**Evidence:** confirmed
**Source:** the coordinator's ruling of 2026-10-27: this change lands before the hub cards for trust × role (`tsk-tryqzr76gh9q`) and for handle aliases (`tsk-xsqc4whfqj4h`), with the hooks named so that they are found
**Revisit when:** either card lands; then this entry is superseded by what it built
**Verification:** contradicted — the alias card landed: `resolve_owner` resolves aliases through `handles.human_id_of` (handles.md); the `action` half is still open

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
the operator. Every existing project keeps its slug as `legacy_slug`. A
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
