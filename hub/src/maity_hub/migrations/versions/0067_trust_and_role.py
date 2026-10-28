"""Trust × role (docs/api.md §2.3, contract #419): the single `role` splits in two.

Every membership, invitation, join and placement profile gets a `trust`, and its `role`
becomes what the member does, mapped once:

    owner → owner, coder        admin → admin, coder        proxy → admin, proxy
    reviewer → member, reviewer member → member, coder

`role` widens to 24 characters for the project roles of #506, and a request's
`to_role` to 32. The tokens that named the old roles are rewritten where they are
stored: `role:owner` becomes `trust:owner`, `role:admin` `trust:admin`, `role:member`
`role:coder`. That is
every event audience, a request's `to` (`to_role` now holds the whole token) and its
forwarding steps, the project's `contract_arbiter`, `coordinator` and
`settings.onboarding.check_in_with`, a membership's `availability_policy.substitutes`,
and a card contract's `arbiter`. Event payloads are the record of what was said then
and stay as they are.

The downgrade maps back: `guest` becomes `member`, and the roles the single role did
not know (`tester`, `designer`, `ops`) become `member`, `role:<them>` `role:member`.

Revision ID: 0067
Revises: 0071
"""

from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UP_ROLE = {
    "owner": ("owner", "coder"),
    "admin": ("admin", "coder"),
    "proxy": ("admin", "proxy"),
    "reviewer": ("member", "reviewer"),
    "member": ("member", "coder"),
}
UP_TOKEN = {"role:owner": "trust:owner", "role:admin": "trust:admin", "role:member": "role:coder"}
DOWN_TOKEN = {
    "trust:owner": "role:owner",
    "trust:admin": "role:admin",
    "role:coder": "role:member",
    "role:tester": "role:member",
    "role:designer": "role:member",
    "role:ops": "role:member",
}
# The bare role a request's `to_role` held before, and the token it holds now.
UP_TO_ROLE = {"owner": "trust:owner", "admin": "trust:admin", "member": "role:coder"}


def _down_role(trust: str, role: str) -> str:
    if trust in ("owner", "admin"):
        return "proxy" if role == "proxy" else trust
    return "reviewer" if role == "reviewer" else "member"


def _tokens(value: Any, mapping: dict[str, str]) -> Any:
    """`value` with every string that is exactly a mapped token replaced, at any depth."""
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_tokens(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: _tokens(v, mapping) for k, v in value.items()}
    return value


def _rewrite(table: str, key: str, column: str, fn: Callable[[Any], Any]) -> None:
    """Apply `fn` to `column` of every row of `table` whose value it changes."""
    bind = op.get_bind()
    is_json = column not in ("contract_arbiter", "coordinator", "to_role")
    rows = sa.table(table, sa.column(key), sa.column(column, sa.JSON if is_json else sa.String))
    for row in bind.execute(sa.select(rows.c[key], rows.c[column])).all():
        old = row[1]
        if old is None:
            continue
        new = fn(old)
        if new != old:
            bind.execute(sa.update(rows).where(rows.c[key] == row[0]).values({column: new}))


def _split_roles(table: str) -> None:
    bind = op.get_bind()
    rows = sa.table(table, sa.column("role", sa.String), sa.column("trust", sa.String))
    for old, (trust, role) in UP_ROLE.items():
        bind.execute(sa.update(rows).where(rows.c.role == old).values(role=role, trust=trust))


def _join_roles(table: str) -> None:
    bind = op.get_bind()
    rows = sa.table(table, sa.column("id"), sa.column("role", sa.String), sa.column("trust"))
    for row in bind.execute(sa.select(rows.c.id, rows.c.trust, rows.c.role)).all():
        bind.execute(
            sa.update(rows).where(rows.c.id == row.id).values(role=_down_role(row.trust, row.role))
        )


def _profile_up(profile: Any) -> Any:
    if not isinstance(profile, dict) or "role" not in profile or "trust" in profile:
        return profile
    trust, role = UP_ROLE.get(profile["role"], ("member", "coder"))
    return {**profile, "trust": trust, "role": role}


def _profile_down(profile: Any) -> Any:
    if not isinstance(profile, dict) or "trust" not in profile:
        return profile
    rest = {k: v for k, v in profile.items() if k != "trust"}
    return {**rest, "role": _down_role(profile["trust"], profile.get("role", "coder"))}


def _stored_tokens(mapping: dict[str, str], to_role: Callable[[str], str]) -> None:
    def tokens(value: Any) -> Any:
        return _tokens(value, mapping)

    _rewrite("event", "seq", "audience", tokens)
    _rewrite("request", "id", "forwarding", tokens)
    _rewrite("request", "id", "to_role", to_role)
    _rewrite("project", "id", "contract_arbiter", tokens)
    _rewrite("project", "id", "coordinator", tokens)
    _rewrite("project", "id", "settings", tokens)
    _rewrite("membership", "id", "availability_policy", tokens)
    _rewrite("card", "id", "contract", tokens)


def upgrade() -> None:
    for table in ("membership", "invitation", "join_link"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("trust", sa.String(16), server_default="member", nullable=False)
            )
            # Room for a project role's name of up to 24 characters (#506).
            batch.alter_column(
                "role", existing_type=sa.String(16), type_=sa.String(24), existing_nullable=False
            )
        _split_roles(table)
        with op.batch_alter_table(table) as batch:  # every writer names the trust from now on
            batch.alter_column(
                "trust", existing_type=sa.String(16), server_default=None, existing_nullable=False
            )
    with op.batch_alter_table("request") as batch:  # `role:` and a 24-character name
        batch.alter_column("to_role", existing_type=sa.String(16), type_=sa.String(32))
    _rewrite("placement", "id", "new_profile", _profile_up)
    _stored_tokens(UP_TOKEN, lambda bare: UP_TO_ROLE.get(bare, f"role:{bare}"))
    with op.batch_alter_table("project") as batch:
        batch.alter_column(
            "coordinator",
            existing_type=sa.String(48),
            server_default="trust:admin",
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.alter_column(
            "coordinator",
            existing_type=sa.String(48),
            server_default="role:admin",
            existing_nullable=False,
        )

    def to_role(token: str) -> str:
        return DOWN_TOKEN.get(token, token).split(":", 1)[1]

    _stored_tokens(DOWN_TOKEN, to_role)
    with op.batch_alter_table("request") as batch:
        batch.alter_column("to_role", existing_type=sa.String(32), type_=sa.String(16))
    _rewrite("placement", "id", "new_profile", _profile_down)
    for table in ("membership", "invitation", "join_link"):
        _join_roles(table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("trust")
            batch.alter_column(
                "role", existing_type=sa.String(24), type_=sa.String(16), existing_nullable=False
            )
