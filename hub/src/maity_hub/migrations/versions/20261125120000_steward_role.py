"""The built-in role `steward` (docs/api.md §2.3 "The steward"): a project role named
`steward` is renamed `steward-custom`.

A project role named `steward` would turn into the built-in role on the upgrade, with other
scopes and duties. Unlike `expert` (20261108230000), whose upgrade stops, the lead's decision
of 2026-11-25 (point 7 of PR #2221) renames it, as §2.3 says for the security teams, and an
admin moves the members to the built-in role where that is wanted. The rename covers these
places, open or closed unless said: the project's role list, `outside_roles`, the onboarding's
`check_in_with` and the `role:` tokens of `settings.ticker.contract_implementers`; a
membership's `role` and the `role:` token in its `availability_policy.substitutes`; a join's
and an invitation's `role`; a card's `needs`; a request's `to`; an open request's `proposal`
(the member change it waits to apply: `role`, `role_base` where it holds the name, and the
`substitutes` token, with a consent's shown canonical form and hash); a placement's profile;
and the role memory. A membership's `role_base` is a built-in base and unchanged, so no
one's scopes move. The event log is not rewritten: a past event keeps the
audience it was written with, as for every rename of a project role (§2.3), so the built-in
stewards can see the history addressed to the old custom `steward`. The lead accepted this
(seq 221640): rewriting it would scan the largest table on every hub, and would help only the
hubs that had a custom `steward` role, for history only.

A project that already has a project role `steward-custom` gets the next free name,
`steward-custom-2`, then `-3` and on (the lead's ruling of 2026-11-25, seq 221098): an upgrade
that stopped would block the deploy of every hub with both names, and the operator cannot fix
that from the dashboard. Every rename is logged with the project and the name it got.

A project whose project role `steward` was removed while a request waited to apply it keeps
that request open. The name in its proposal would now mean the built-in role, which the owner
never agreed to, so the proposal is marked `role_gone` and a `go` is refused as
`409 role_unknown` (`_mark_gone`, A2692 P2-1). Before this revision only another owner's
consent answered so, for a removed `role` (A2733 P2). Binding every proposal to what its
role resolved to when it was filed would change how a rebase applies to a waiting request
(§2.3), which is outside this revision.

The downgrade does nothing: the built-in role and the renamed project role cannot be told
apart from the name the code before this revision reads.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261125120000_steward_role
Revises: 20261126090000_outside_claims
Create Date: 2026-11-25
"""

import hashlib
import json
import logging
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261125120000_steward_role"
down_revision: str | None = "20261126090000_outside_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("maity_hub.migrations.steward_role")

OLD = "steward"
NEW = "steward-custom"
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)

_project = sa.table(
    "project",
    sa.column("id", sa.String),
    sa.column("owner_id", sa.String),
    sa.column("slug", sa.String),
    sa.column("roles", JSON_VALUE),
    sa.column("outside_roles", JSON_VALUE),
    sa.column("settings", JSON_VALUE),
)
_membership = sa.table(
    "membership",
    sa.column("id", sa.Integer),
    sa.column("project_id", sa.String),
    sa.column("role", sa.String),
    sa.column("availability_policy", JSON_VALUE),
)
_join_link = sa.table("join_link", sa.column("project_id", sa.String), sa.column("role", sa.String))
_invitation = sa.table(
    "invitation", sa.column("project_id", sa.String), sa.column("role", sa.String)
)
_card = sa.table("card", sa.column("project_id", sa.String), sa.column("needs", sa.String))
_request = sa.table(
    "request",
    sa.column("id", sa.String),
    sa.column("project_id", sa.String),
    sa.column("to_role", sa.String),
    sa.column("status", sa.String),
    sa.column("proposal", JSON_VALUE),
)
_placement = sa.table(
    "placement",
    sa.column("id", sa.String),
    sa.column("project_id", sa.String),
    sa.column("new_profile", JSON_VALUE),
)
_memory = sa.table(
    "memory_entry",
    sa.column("project_id", sa.String),
    sa.column("store", sa.String),
    sa.column("role", sa.String),
)


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def free_name(taken: set[str]) -> str:
    """`steward-custom`, else the first of `steward-custom-2`, `-3`, … the project has not."""
    if NEW not in taken:
        return NEW
    n = 2
    while f"{NEW}-{n}" in taken:
        n += 1
    return f"{NEW}-{n}"


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.select(
            _project.c.id,
            _project.c.owner_id,
            _project.c.slug,
            _project.c.roles,
            _project.c.outside_roles,
            _project.c.settings,
        ).order_by(_project.c.owner_id, _project.c.slug)
    ).all()
    renamed: set[str] = set()
    for row in rows:
        roles = _json(row.roles) or []
        if not any(r.get("name") == OLD for r in roles):
            continue
        renamed.add(row.id)
        new = free_name({str(r.get("name")) for r in roles})
        _rename(conn, row, roles, new)
        log.warning(
            "project %s/%s: the project role `%s` is renamed `%s` (the built-in role `steward`, "
            "docs/api.md §2.3)",
            row.owner_id,
            row.slug,
            OLD,
            new,
        )
    _mark_gone(conn, renamed)


def _rename(conn: Any, row: Any, roles: list[dict[str, Any]], new: str) -> None:
    project_id = row.id
    values: dict[str, Any] = {
        "roles": [{**r, "name": new} if r.get("name") == OLD else r for r in roles]
    }
    outside = _json(row.outside_roles)
    if outside is not None and OLD in outside:
        values["outside_roles"] = [new if r == OLD else r for r in outside]
    settings = _json(row.settings) or {}
    renamed = dict(settings)
    onboarding = settings.get("onboarding") or {}
    if onboarding.get("check_in_with") == f"role:{OLD}":
        renamed["onboarding"] = {**onboarding, "check_in_with": f"role:{new}"}
    ticker = settings.get("ticker") or {}
    implementers = ticker.get("contract_implementers") or {}
    if any(f"role:{OLD}" in tokens for tokens in implementers.values()):
        renamed["ticker"] = {
            **ticker,
            "contract_implementers": {
                key: [f"role:{new}" if x == f"role:{OLD}" else x for x in tokens]
                for key, tokens in implementers.items()
            },
        }
    if renamed != settings:
        values["settings"] = renamed
    conn.execute(sa.update(_project).where(_project.c.id == project_id).values(**values))
    for table, column, old_value, new_value in (
        (_membership, _membership.c.role, OLD, new),
        (_join_link, _join_link.c.role, OLD, new),
        (_invitation, _invitation.c.role, OLD, new),
        (_card, _card.c.needs, OLD, new),
        (_request, _request.c.to_role, f"role:{OLD}", f"role:{new}"),
    ):
        conn.execute(
            sa.update(table)
            .where(table.c.project_id == project_id, column == old_value)
            .values({column.name: new_value})
        )
    conn.execute(
        sa.update(_memory)
        .where(_memory.c.project_id == project_id, _memory.c.store == "role", _memory.c.role == OLD)
        .values(role=new)
    )
    members = conn.execute(
        sa.select(_membership.c.id, _membership.c.availability_policy).where(
            _membership.c.project_id == project_id
        )
    ).all()
    for member in members:
        policy = _json(member.availability_policy)
        if not policy or f"role:{OLD}" not in policy.get("substitutes", []):
            continue
        substitutes = [f"role:{new}" if s == f"role:{OLD}" else s for s in policy["substitutes"]]
        conn.execute(
            sa.update(_membership)
            .where(_membership.c.id == member.id)
            .values(availability_policy={**policy, "substitutes": substitutes})
        )
    _rename_proposals(conn, project_id, new)
    placements = conn.execute(
        sa.select(_placement.c.id, _placement.c.new_profile).where(
            _placement.c.project_id == project_id
        )
    ).all()
    for placement in placements:
        profile = _json(placement.new_profile)
        if profile and profile.get("role") == OLD:
            conn.execute(
                sa.update(_placement)
                .where(_placement.c.id == placement.id)
                .values(new_profile={**profile, "role": new})
            )


def _canonical(value: Any) -> tuple[str, str]:
    """The JCS form of a stored value and its SHA-256, as `foreign_agent._hash` gives them:
    the values here are strings, integers in JCS's range (`grace_minutes`, 0 to 1440),
    booleans, null, and lists and objects of them, which `json.dumps` with sorted keys and no
    spaces writes exactly as JCS does."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _renamed_value(name: str, value: Any, new: str) -> Any:
    """`value` of a proposal's field `name` with the project role `steward` renamed: `role`,
    and `role_base` only where it holds that name (a built-in base such as `coder` stays), and
    the `role:` token in `availability_policy.substitutes`."""
    if name in ("role", "role_base"):
        return new if value == OLD else value
    if isinstance(value, dict) and isinstance(value.get("substitutes"), list):
        substitutes = [f"role:{new}" if s == f"role:{OLD}" else s for s in value["substitutes"]]
        return {**value, "substitutes": substitutes}
    return value


def _rename_proposals(conn: Any, project_id: str, new: str) -> None:
    """The member change an open request waits to apply (`request.proposal["values"]`: the
    owner's consent for another owner's agent, an admin agent's and a line lead's proposal):
    `role`, `role_base` where it holds the project role's name, and the `role:` token in
    `availability_policy.substitutes`. A consent's stored canonical form and hash of a renamed
    field are written again, so that what the owner is shown is what the go applies. The
    request's summary text is not rewritten and keeps the old name `steward`, while the shown
    canonical form, its hash and the go use the new name. A closed request is history and keeps
    what it applied."""
    rows = conn.execute(
        sa.select(_request.c.id, _request.c.proposal).where(
            _request.c.project_id == project_id,
            _request.c.status == "open",
            _request.c.proposal.is_not(None),
        )
    ).all()
    for row in rows:
        proposal = _json(row.proposal)
        values = proposal.get("values") if isinstance(proposal, dict) else None
        if not isinstance(values, dict):
            continue
        changed = {
            name: _renamed_value(name, values[name], new)
            for name in ("role", "role_base", "availability_policy")
            if name in values and _renamed_value(name, values[name], new) != values[name]
        }
        if not changed:
            continue
        renamed = {**proposal, "values": {**values, **changed}}
        canonical, digest = proposal.get("canonical"), proposal.get("sha256")
        if isinstance(canonical, dict) and isinstance(digest, dict):
            canonical, digest = dict(canonical), dict(digest)
            for name in changed:
                if name in canonical:  # what the owner was shown, renamed the same way
                    shown = _renamed_value(name, json.loads(canonical[name]), new)
                    canonical[name], digest[name] = _canonical(shown)
            renamed["canonical"], renamed["sha256"] = canonical, digest
        conn.execute(sa.update(_request).where(_request.c.id == row.id).values(proposal=renamed))


def _names_old(values: dict[str, Any]) -> bool:
    """The proposal's member change names `steward`: as `role`, as `role_base`, or as the
    `role:` token in `availability_policy.substitutes`."""
    if OLD in (values.get("role"), values.get("role_base")):
        return True
    policy = values.get("availability_policy")
    return isinstance(policy, dict) and f"role:{OLD}" in (policy.get("substitutes") or [])


def _mark_gone(conn: Any, renamed: set[str]) -> None:
    """An open request, in a project that has no project role `steward` any more, whose
    proposal still names it. Before this revision the name could only have meant a project role
    that was removed while the request waited. A `go` then depended on the path: another
    owner's consent refused a removed `role` as `409 role_unknown`, an admin agent's change
    refused a removed `role:` substitute as `400 invalid`, and the rest applied the change as
    filed, except an admin agent's role change of another owner's agent (docs/api.md §2.3).
    Only these two kinds carry the fields: a manager's `line_change` sets neither (`line.py`
    `LINE_FIELDS`). After it, the name resolves to the built-in steward. So the proposal is marked
    `role_gone`, and every `go` on it is refused as `409 role_unknown` (`proposals.settle`,
    new for every path but the first): the owner never consented to the built-in role. The
    request stays open for a `no` or a withdrawal (A2692 P2-1), and a new change asks again.
    A project in `renamed` had its proposals renamed above instead."""
    rows = conn.execute(
        sa.select(_request.c.id, _request.c.project_id, _request.c.proposal).where(
            _request.c.status == "open", _request.c.proposal.is_not(None)
        )
    ).all()
    for row in rows:
        if row.project_id in renamed:
            continue
        proposal = _json(row.proposal)
        values = proposal.get("values") if isinstance(proposal, dict) else None
        if not isinstance(values, dict) or not _names_old(values):
            continue
        conn.execute(
            sa.update(_request)
            .where(_request.c.id == row.id)
            .values(proposal={**proposal, "role_gone": OLD})
        )


def downgrade() -> None:
    pass
