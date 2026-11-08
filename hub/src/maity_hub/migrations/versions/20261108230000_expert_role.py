"""The built-in role `expert` (docs/api.md §2.3 "The expert"): no project role may keep its name.

A project role named `expert` would turn into the built-in role on the upgrade, with other
scopes. It is not renamed here: a project role's name is stored in many places (a
membership, a join, an invitation, a card's `needs`, a request's `to`, a placement, the
onboarding's `check_in_with`, a `substitutes` list, the role memory, `outside_roles` and
the briefing keys), and a half rename would be worse than none. The upgrade stops instead
and names each such project; an admin moves its members to a new name as §2.3 says (add
the new name, move the members, remove the old one) and runs the upgrade again. The
migration changes no schema, so the downgrade does nothing.

Revision ID: 20261108230000_expert_role
Revises: 20261107160000_avatar_size
Create Date: 2026-11-08
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261108230000_expert_role"
down_revision: str | None = "20261107160000_avatar_size"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_project = sa.table(
    "project",
    sa.column("id", sa.String),
    sa.column("owner_id", sa.String),
    sa.column("slug", sa.String),
    sa.column("roles", sa.JSON),
)


def upgrade() -> None:
    found: list[str] = []
    rows = op.get_bind().execute(
        sa.select(_project.c.owner_id, _project.c.slug, _project.c.roles).order_by(
            _project.c.owner_id, _project.c.slug
        )
    )
    for row in rows:
        roles = json.loads(row.roles) if isinstance(row.roles, str) else row.roles
        if any(role.get("name") == "expert" for role in roles or []):
            found.append(f"{row.owner_id}/{row.slug}")
    if found:
        raise RuntimeError(
            "the built-in role `expert` (§2.3) needs the name, and these projects have a "
            f"project role named `expert`: {', '.join(found)}. Move its members to a new "
            "project role and remove `expert` (§2.3), then run the upgrade again."
        )


def downgrade() -> None:
    pass
