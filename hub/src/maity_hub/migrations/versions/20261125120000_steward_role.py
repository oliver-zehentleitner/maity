"""The built-in role `steward` (docs/api.md §2.3 "The steward"): a project role named
`steward` is renamed `steward-custom`.

A project role named `steward` would turn into the built-in role on the upgrade, with other
scopes and duties. Unlike `expert` (20261108230000), whose upgrade stops, the lead's decision
of 2026-11-25 (point 7 of PR #2221) renames it, as §2.3 says for the security teams, and an
admin moves the members to the built-in role where that is wanted. The rename covers every
place that stores a project role's name, the same list `project_roles.uses` reads: the role
list itself, a membership, an open or used join and invitation, a card's `needs`, a request's
`to`, a placement's profile, the onboarding's `check_in_with`, a `substitutes` list, the role
memory and `outside_roles`. A membership's `role_base` is unchanged, so no one's scopes move.

A project that already has a project role `steward-custom` is not renamed by halves: the
upgrade stops and names each such project, and an admin renames one of the two (§2.3: add the
new name, move the members, remove the old one) before the upgrade runs again.

The downgrade does nothing: the built-in role and the renamed project role cannot be told
apart from the name the code before this revision reads.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261125120000_steward_role
Revises: 20261124170513_org_link_check
Create Date: 2026-11-25
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261125120000_steward_role"
down_revision: str | None = "20261124170513_org_link_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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
    named = [(row, _json(row.roles) or []) for row in rows]
    named = [(row, roles) for row, roles in named if any(r.get("name") == OLD for r in roles)]
    both = [
        f"{row.owner_id}/{row.slug}"
        for row, roles in named
        if any(r.get("name") == NEW for r in roles)
    ]
    if both:
        raise RuntimeError(
            "the built-in role `steward` (§2.3) needs the name, and these projects have both a "
            f"project role `steward` and one named `steward-custom`: {', '.join(both)}. Rename "
            "one of them (§2.3), then run the upgrade again."
        )
    for row, roles in named:
        _rename(conn, row, roles)


def _rename(conn: Any, row: Any, roles: list[dict[str, Any]]) -> None:
    project_id = row.id
    values: dict[str, Any] = {
        "roles": [{**r, "name": NEW} if r.get("name") == OLD else r for r in roles]
    }
    outside = _json(row.outside_roles)
    if outside is not None and OLD in outside:
        values["outside_roles"] = [NEW if r == OLD else r for r in outside]
    settings = _json(row.settings) or {}
    onboarding = settings.get("onboarding") or {}
    if onboarding.get("check_in_with") == f"role:{OLD}":
        values["settings"] = {
            **settings,
            "onboarding": {**onboarding, "check_in_with": f"role:{NEW}"},
        }
    conn.execute(sa.update(_project).where(_project.c.id == project_id).values(**values))
    for table, column, old, new in (
        (_membership, _membership.c.role, OLD, NEW),
        (_join_link, _join_link.c.role, OLD, NEW),
        (_invitation, _invitation.c.role, OLD, NEW),
        (_card, _card.c.needs, OLD, NEW),
        (_request, _request.c.to_role, f"role:{OLD}", f"role:{NEW}"),
    ):
        conn.execute(
            sa.update(table)
            .where(table.c.project_id == project_id, column == old)
            .values({column.name: new})
        )
    conn.execute(
        sa.update(_memory)
        .where(_memory.c.project_id == project_id, _memory.c.store == "role", _memory.c.role == OLD)
        .values(role=NEW)
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
        substitutes = [f"role:{NEW}" if s == f"role:{OLD}" else s for s in policy["substitutes"]]
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
                .values(new_profile={**profile, "role": NEW})
            )


def downgrade() -> None:
    pass
