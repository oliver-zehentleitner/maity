"""The built-in role `steward` (docs/api.md §2.3 "The steward"): a project role named
`steward` is renamed `steward-custom`.

A project role named `steward` would turn into the built-in role on the upgrade, with other
scopes and duties. Unlike `expert` (20261108230000), whose upgrade stops, the lead's decision
of 2026-11-25 (point 7 of PR #2221) renames it, as §2.3 says for the security teams, and an
admin moves the members to the built-in role where that is wanted. The rename covers every
setting and column that stores a project role's name or its `role:` token: the places
`project_roles.uses` reads (the role list itself, a membership, a join and an invitation, a
card's `needs`, a request's `to`, a placement's profile, the onboarding's `check_in_with`, a
`substitutes` list, the role memory and `outside_roles`), whether open or not, and the
`role:` tokens of `settings.ticker.contract_implementers`. A membership's `role_base` is
unchanged, so no one's scopes move. The event log is not rewritten: a past event keeps the
audience it was written with, as for every rename of a project role (§2.3), so the built-in
stewards can see the history addressed to the old custom `steward`. The lead accepted this
(seq 221640): rewriting it would scan the largest table on every hub, for history only.

A project that already has a project role `steward-custom` gets the next free name,
`steward-custom-2`, then `-3` and on (the lead's ruling of 2026-11-25, seq 221098): an upgrade
that stopped would block the deploy of every hub with both names, and the operator cannot fix
that from the dashboard. Every rename is logged with the project and the name it got.

The downgrade does nothing: the built-in role and the renamed project role cannot be told
apart from the name the code before this revision reads.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261125120000_steward_role
Revises: 20261124170513_org_link_check
Create Date: 2026-11-25
"""

import json
import logging
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261125120000_steward_role"
down_revision: str | None = "20261124170513_org_link_check"
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
_request = sa.table("request", sa.column("project_id", sa.String), sa.column("to_role", sa.String))
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
    for row in rows:
        roles = _json(row.roles) or []
        if not any(r.get("name") == OLD for r in roles):
            continue
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


def downgrade() -> None:
    pass
