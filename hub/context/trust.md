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
**Revisit when:** a project's own roles (§2.3) are built, or a built-in role gets scopes no existing one has

`scopes._ROLE_SCOPES` holds the eleven built-in roles with their scopes, `red-team` with the tester's,
`blue-team` with the coder's and `purple-team` with the reviewer's. `ROLES`, `WORK_ROLES`,
`MEMBER_RULE_ROLES` and `SENSITIVE_ROLES` are derived from it, and the role of an invitation is checked
against `ROLES`, so a new role cannot be added to one list and forgotten in another (the invitation list had
no `writer` and the join list no security team). Where the hub resolves a built-in role by name (the
audience of a merge that wakes the done authority, the members whose change waits for a human's go),
`scopes.counts_as` gives the role whose scopes a security team has; a `role:` token in an address is not
widened, so a request to `role:reviewer` does not reach the purple team.

**Reason:** the contract names the roles in a dozen places and each of them had its own list, which is how
the three roles and `writer` went missing from some.

**Rejected alternatives:**
- A `Literal` per model, kept in step by hand: that is the state that lost `writer`.
- Widening the `role:` tokens too, so that `role:reviewer` also reaches the purple team: the contract keeps
  addresses exact, and a request meant for a reviewer would reach a role that only counts as one for scopes.
