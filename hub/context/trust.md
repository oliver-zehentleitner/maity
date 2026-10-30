# Trust and role

## A proxy keeps the single role's scopes until the owner's go per call is in place

**Id:** 75d1458d-83a0-46b4-b478-f95be80d0453
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-28 (trust × role, first of the stacked pull requests for #419; the split agreed with the coordinator)
**Revisit when:** `Maity-On-Request` and `on_behalf_of` are enforced for a proxy (the third pull request of #419)

`scopes.py` gives a member with the role `proxy` the coder's scopes and
`requests:answer`, whatever its trust, and nothing else of the governance
scopes, until the hub checks the owner's go per call (`Maity-On-Request`,
docs/api.md §2.3 "The proxy").

**Reason:** the migration turns every old `proxy` into trust `admin`, role
`proxy`. Read literally, trust `admin` adds every governance scope, so a
proxy would gain `tasks:admin`, `agents:propose` and the rest on the day
the model lands, before the rule that binds each such call to the owner's
decision exists. maity.team runs on real data; a proxy must not hold more
than it held under the single role while the guard is missing.

**Rejected alternatives:**
- Grant the full trust `admin` scopes now and add the guard later: the
  contract's order, but for the time in between a proxy acts as an admin
  without the owner's go.
- Land trust × role and the proxy go in one pull request: one change of
  roughly fifty files plus the signed header and the action binding,
  too large to review as one piece.

## A request's `to_role` holds the whole token

**Id:** e4aab1dd-1c04-420e-aa09-59760ef88bc9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-28 (migration 0067)
**Revisit when:** a request needs to address something that is neither a member, the owner, a trust nor a role

A request filed `to: trust:admin` or `to: role:designer` is stored with
`to_kind: role` and `to_role` holding the token itself (`trust:admin`,
`role:designer`); migration 0067 rewrote the bare old values (`admin` →
`trust:admin`, `owner` → `trust:owner`, `member` → `role:coder`, the rest
`role:<role>`).

**Reason:** the addressee is compared with the tokens a membership answers
to (`scopes.tokens_of`) everywhere else (event audiences, onboarding,
messages); storing the token lets requests use the same comparison, and
`String(16)` holds the longest token.

**Rejected alternatives:**
- A new `to_kind: trust` with the bare trust in `to_role`: the table's
  `to_shape` check constraint names every `to_kind`, so the migration
  would rebuild that constraint on SQLite, PostgreSQL and MariaDB for a
  distinction the token already carries.

## The 0067 downgrade removes a guest instead of making it a member

**Id:** 3de05927-0c2d-4452-af37-14477aa945e3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of the first trust × role pull request, 2026-10-28 (the reviewer's decision, relayed by the coordinator)
**Revisit when:** the single role is gone for good and no downgrade below 0067 is supported

Downgrading below migration 0067 removes every guest membership, revokes
its credentials and closes its placements, and ends unused guest
invitations and joins. The single role has no trust below `member`, so a
guest cannot be mapped to anything it held.

**Reason:** a downgrade that turned a guest into `member` would hand a
read-only member the coder's scopes, a quiet escalation on the way back.
Losing the guest is the safer failure, and an admin can re-invite them.

**Rejected alternatives:**
- Map `guest` to `member`: the first version of 0067, rejected in review
  as fail-open.

## Every built-in role is one entry of `scopes`, and a security team counts as the role it is built on

**Id:** 6624a4bf-0aca-4338-b8fb-d12639ab7474
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §2.3 ("The security teams", the table of roles) and the coordinator's order on the card tsk-g62vwd7bqztk
**Revisit when:** a built-in role gets scopes no existing one has

`scopes._ROLE_SCOPES` holds the eleven built-in roles with their scopes, `red-team` with the tester's,
`blue-team` with the coder's and `purple-team` with the reviewer's. `ROLES`, `WORK_ROLES`,
`MEMBER_RULE_ROLES` and `SENSITIVE_ROLES` are derived from it, and the role of an invitation is checked
against `ROLES`, so a new role cannot be added to one list and forgotten in another (the invitation list had
no `writer` and the join list no security team). Where the hub resolves a built-in role by name (the
audience of a merge that wakes the done authority, the members whose change waits for a human's go),
`scopes.counts_as` gives the role whose scopes a security team has; `cover.cover_order` resolves a
`role:<role>` entry in `substitutes` the same way, so that a substitute is found among the holders of a
role as the done authority and the wakes find them, while `role:<team>` names only the team itself. The
project roles (§2.3) came later and count as their base through `role_base`, not `counts_as` (entry
25a99503). The audience of the events that
wake the holders of a role (`task_merged`, `task_reported`) is built with `scopes.role_tokens`, which adds
the teams' tokens (`role:reviewer` and `role:purple-team`): the audience is what lets a member read the event
at all, so widening only the check of who holds the done authority would leave the purple team blind to it.
A `role:` token in an address a person writes is not widened, so a request or a message to `role:reviewer`
does not reach the purple team.

**Reason:** the contract names the roles in a dozen places and each of them had its own list, which is how
the three roles and `writer` went missing from some.

**Rejected alternatives:**
- A `Literal` per model, kept in step by hand: that is the state that lost `writer`.
- Widening the `role:` tokens too, so that `role:reviewer` also reaches the purple team: the contract keeps
  addresses exact, and a request meant for a reviewer would reach a role that only counts as one for scopes.

## A membership keeps its role's base, and an unknown role has no scopes

**Id:** 25a99503-c0df-436b-a0b2-7b1d0b1a966f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §2.3 "Project roles"; the coordinator's go on the card tsk-chvx53e55hmg
**Revisit when:** a card's `needs`, the role memory store or `membership.guide` in the packet is built

A project's own roles live in `project.roles` (`[{name, base, description, guide, guide_by}]`, null for
none), and every membership carries `role_base` next to `role`: the role itself for a built-in one, the
base for a project role. Scopes (`has_scope`, `listed_scopes`) are always asked with `role_base`, and
`scopes.tokens_of` gives a membership both `role:<role>` and `role:<base>`, so a request, a wake or an
audience naming `role:reviewer` reaches a project role on `reviewer` with no change where it is resolved;
a security team stays its own base and is not widened (entry 6624a4bf). The done authority's wake takes
`counts_as(role_base)`, and `cover.cover_order` matches `role:<role>` against the role or what its base
counts as. A `PUT …/roles` that moves a role to another base rewrites the `role_base` of its members in
the same transaction. `scopes._granted` raises for a name that is not a built-in role: before, any
unknown role silently got the coder's scopes, which would have given a project role on `reviewer` too
little and hidden every caller that forgot the base.

`role_in_use` counts what exists in the hub today: an active membership, an open join or invitation, an
open request to `role:<name>`, a placement that has not made its membership yet, the onboarding's
`check_in_with`, an entry in a `substitutes` list. An assignment or invitation of a project role reads
the role list under the project's lock, the lock `PUT …/roles` holds while it checks these, so a role
cannot be removed between the check of a new join and its insert (a join exchanged later would
otherwise meet a role with no base). A card's `needs`, the role memory store
and `membership.guide` in the packet are in the contract but not built; the pull request that builds one
adds it to `project_roles.uses` (and, for the guide, takes it from `project.roles` as the rules text
does). The 0112 downgrade turns a project role into its base in memberships, joins, invitations and a
placement's profile, so
the older code meets no name it does not know.

**Reason:** about 25 places read a member's scopes or tokens from a membership row, most without the
project at hand; the base on the row lets each of them stay a one-line read.

**Rejected alternatives:**
- Looking the base up in `project.roles` at every read: each of those places would need the project, and
  one that forgot it would fall back to a wrong answer without an error.
- A nullable `role_base` read as `role_base or role`: the same silent fallback in another place.
- Keeping the coder fallback in `_granted` for names it does not know: it is what made a missing base
  invisible.
