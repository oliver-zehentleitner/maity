"""Jour fixe series (docs/api.md §20.1, §20.2): several per project, each with a topic and a circle.

`jour_fixe_series` holds a series' topic, circle and schedule (`config`, the shape the schedule
reads), `jour_fixe_moderator` the right to moderate a series (`active`, or `pending` until the
agent's owner and a keeper both said go), `jour_fixe_opt_out` the members who left a series,
and every round names its series.

The upgrade ("From the single schedule", §20.1): a project with `policy.jour_fixe`, or with
rounds started by hand, gets one series, `circle: all`, topic "How we work", the schedule and
windows as they were (`enabled: false` without a policy), and every round of the project is
assigned to it. `created_by` is the human named by the last `policy_changed` event that changed
`policy.jour_fixe`, while still a member; else null. The moderator right goes to every member
the old setting named or would have chosen: the member named in `moderator`, else the agents of
`jour_fixe_moderators`, else the project's admin agents. A named human holds it at once; an
agent holds it at once when its owner set the policy, and otherwise waits as `pending` for its
owner's consent (the keepers' is given: the policy was theirs), whose request the hub files
(`jourfixe.series`). The four project columns then go. The `jour_fixe_series_changed` event and
the rules bump of the upgrade are the hub's on its next start (`jourfixe.series.announce`),
since a migration writes no events.

Revision ID: 20261031190604_jour_fixe_series
Revises: 20261031125530_long_polls
Create Date: 2026-10-31
"""

import json
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "20261031190604_jour_fixe_series"
down_revision: str | None = "20261031125530_long_polls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}
CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"
WINDOWS = {"answer_window_minutes": 120, "step_window_minutes": 120, "report_window_hours": 12}
SCHEDULE = ("recurrence", "time", "timezone")


def _new_id() -> str:
    return "jfs-" + "".join(secrets.choice(CROCKFORD) for _ in range(12))


def _json(value: Any) -> Any:
    """A JSON column as read: decoded on every engine (SQLite and MariaDB may hand a string)."""
    return json.loads(value) if isinstance(value, str) else value


def _config(policy: dict[str, Any] | None) -> dict[str, Any]:
    policy = policy or {}
    found: dict[str, Any] = {name: policy.get(name) for name in SCHEDULE}
    found.update({name: policy.get(name, default) for name, default in WINDOWS.items()})
    return found


def _setter(conn: sa.Connection, project_id: str) -> str | None:
    """The human of the last `policy_changed` that changed `policy.jour_fixe`, if still a member."""
    rows = conn.execute(
        sa.text(
            "SELECT payload, actor_membership, actor_human_id FROM event"
            " WHERE project_id = :p AND kind = 'policy_changed' ORDER BY seq DESC"
        ),
        {"p": project_id},
    ).all()
    for payload, actor_membership, actor_human_id in rows:
        payload = _json(payload) or {}
        old, new = payload.get("old") or {}, payload.get("new") or {}
        if old.get("jour_fixe") == new.get("jour_fixe"):
            continue
        human = actor_human_id
        if human is None and actor_membership is not None:
            human = conn.execute(
                sa.text("SELECT human_id FROM membership WHERE id = :m"), {"m": actor_membership}
            ).scalar()
        if human is None:
            return None
        member = conn.execute(
            sa.text(
                "SELECT 1 FROM membership WHERE project_id = :p AND human_id = :h AND active = :t"
            ),
            {"p": project_id, "h": human, "t": True},
        ).first()
        return human if member else None
    return None


def _grantees(
    conn: sa.Connection, project_id: str, policy: dict[str, Any] | None, order: list[str] | None
) -> list[Any]:
    """The active memberships the old setting named or would have chosen (§20.1)."""
    members = conn.execute(
        sa.text(
            "SELECT m.id, m.agent_id, m.human_id, m.trust, m.role, a.owner_id FROM membership m"
            " LEFT JOIN agent_profile a ON a.id = m.agent_id"
            " WHERE m.project_id = :p AND m.active = :t"
        ),
        {"p": project_id, "t": True},
    ).all()
    named = (policy or {}).get("moderator")
    if isinstance(named, str) and named != "admin_agent":
        return [m for m in members if named in (m.agent_id, m.human_id)]
    if order:
        return [m for agent_id in order for m in members if m.agent_id == agent_id]
    return [m for m in members if m.agent_id and m.trust == "admin" and m.role != "proxy"]


def upgrade() -> None:
    op.create_table(
        "jour_fixe_series",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("topic", sa.String(length=300), nullable=False),
        sa.Column("circle", sa.String(length=8), nullable=False),
        sa.Column("circle_owner", sa.String(length=40), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", JSON_VALUE, nullable=False),
        sa.Column("anchor", TIMESTAMP, nullable=True),
        sa.Column("last_slot", TIMESTAMP, nullable=True),
        sa.Column("created_by", sa.String(length=40), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_jour_fixe_series_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["circle_owner"], ["human.id"], name=op.f("fk_jour_fixe_series_circle_owner_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jour_fixe_series")),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_jour_fixe_series_project_id", "jour_fixe_series", ["project_id"])
    op.create_table(
        "jour_fixe_moderator",
        sa.Column("series_id", sa.String(length=40), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=8), nullable=False),
        sa.Column("granted_by", sa.String(length=40), nullable=True),
        sa.Column("granted_at", TIMESTAMP, nullable=False),
        sa.Column("owner_consent", sa.Boolean(), nullable=False),
        sa.Column("keeper_consent", sa.Boolean(), nullable=False),
        sa.Column("owner_request_id", sa.String(length=40), nullable=True),
        sa.Column("keeper_request_id", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["jour_fixe_series.id"],
            name=op.f("fk_jour_fixe_moderator_series_id_jour_fixe_series"),
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_jour_fixe_moderator_membership_id_membership"),
        ),
        sa.PrimaryKeyConstraint("series_id", "membership_id", name=op.f("pk_jour_fixe_moderator")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "jour_fixe_opt_out",
        sa.Column("series_id", sa.String(length=40), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["jour_fixe_series.id"],
            name=op.f("fk_jour_fixe_opt_out_series_id_jour_fixe_series"),
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_jour_fixe_opt_out_membership_id_membership"),
        ),
        sa.PrimaryKeyConstraint("series_id", "membership_id", name=op.f("pk_jour_fixe_opt_out")),
        **TABLE_OPTIONS,
    )
    with op.batch_alter_table("jour_fixe_round", schema=None) as batch_op:
        batch_op.add_column(sa.Column("series_id", sa.String(length=40), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_jour_fixe_round_series_id_jour_fixe_series"),
            "jour_fixe_series",
            ["series_id"],
            ["id"],
        )
        batch_op.create_index("ix_jour_fixe_round_series_id", ["series_id"])

    conn = op.get_bind()
    series = sa.table(
        "jour_fixe_series",
        sa.column("id"),
        sa.column("project_id"),
        sa.column("topic"),
        sa.column("circle"),
        sa.column("circle_owner"),
        sa.column("enabled"),
        sa.column("config", JSON_VALUE),
        sa.column("anchor"),
        sa.column("last_slot"),
        sa.column("created_by"),
        sa.column("created_at"),
    )
    moderator = sa.table(
        "jour_fixe_moderator",
        sa.column("series_id"),
        sa.column("membership_id"),
        sa.column("state"),
        sa.column("granted_by"),
        sa.column("granted_at"),
        sa.column("owner_consent"),
        sa.column("keeper_consent"),
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    projects = conn.execute(
        sa.text(
            "SELECT id, jour_fixe, jour_fixe_moderators, jour_fixe_anchor, jour_fixe_last_slot"
            " FROM project WHERE jour_fixe IS NOT NULL"
            " OR id IN (SELECT DISTINCT project_id FROM jour_fixe_round)"
        )
    ).all()
    for project_id, policy, order, anchor, last_slot in projects:
        policy, order = _json(policy), _json(order)
        series_id = _new_id()
        setter = _setter(conn, project_id) if policy else None
        conn.execute(
            series.insert().values(
                id=series_id,
                project_id=project_id,
                topic="How we work",
                circle="all",
                circle_owner=None,
                enabled=bool(policy and policy.get("enabled")),
                config=_config(policy),
                anchor=anchor,
                last_slot=last_slot,
                created_by=setter,
                created_at=now,
            )
        )
        conn.execute(
            sa.text("UPDATE jour_fixe_round SET series_id = :s WHERE project_id = :p"),
            {"s": series_id, "p": project_id},
        )
        for member in _grantees(conn, project_id, policy, order):
            at_once = member.agent_id is None or member.owner_id == setter
            conn.execute(
                moderator.insert().values(
                    series_id=series_id,
                    membership_id=member.id,
                    state="active" if at_once else "pending",
                    granted_by=member.human_id if member.agent_id is None else setter,
                    granted_at=now,
                    owner_consent=at_once,
                    keeper_consent=True,
                )
            )

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("jour_fixe_last_slot")
        batch_op.drop_column("jour_fixe_anchor")
        batch_op.drop_column("jour_fixe_moderators")
        batch_op.drop_column("jour_fixe")


def downgrade() -> None:
    """Back to one schedule per project: the oldest series' schedule as the policy, the right
    as `moderator: admin_agent`; the other series, the grants and the opt-outs are lost."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("jour_fixe", JSON_VALUE, nullable=True))
        batch_op.add_column(sa.Column("jour_fixe_moderators", JSON_VALUE, nullable=True))
        batch_op.add_column(sa.Column("jour_fixe_anchor", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("jour_fixe_last_slot", TIMESTAMP, nullable=True))
    conn = op.get_bind()
    project = sa.table(
        "project",
        sa.column("id"),
        sa.column("jour_fixe", JSON_VALUE),
        sa.column("jour_fixe_anchor"),
        sa.column("jour_fixe_last_slot"),
    )
    rows = conn.execute(
        sa.text(
            "SELECT project_id, enabled, config, anchor, last_slot FROM jour_fixe_series"
            " ORDER BY created_at DESC"
        )
    ).all()
    oldest: dict[str, Any] = {}
    for row in rows:
        oldest[row.project_id] = row  # the last one written is the oldest
    for project_id, row in oldest.items():
        config = _json(row.config) or {}
        if config.get("recurrence") is None:
            continue
        conn.execute(
            project.update()
            .where(project.c.id == project_id)
            .values(
                jour_fixe={**config, "enabled": bool(row.enabled), "moderator": "admin_agent"},
                jour_fixe_anchor=row.anchor,
                jour_fixe_last_slot=row.last_slot,
            )
        )
    with op.batch_alter_table("jour_fixe_round", schema=None) as batch_op:
        batch_op.drop_index("ix_jour_fixe_round_series_id")
        batch_op.drop_constraint(
            op.f("fk_jour_fixe_round_series_id_jour_fixe_series"), type_="foreignkey"
        )
        batch_op.drop_column("series_id")
    op.drop_table("jour_fixe_opt_out")
    op.drop_table("jour_fixe_moderator")
    op.drop_index("ix_jour_fixe_series_project_id", table_name="jour_fixe_series")
    op.drop_table("jour_fixe_series")
