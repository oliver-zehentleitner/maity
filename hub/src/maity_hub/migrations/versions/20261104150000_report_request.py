"""The instance admin hears of a new abuse report through a personal request (docs/api.md §16.8,
§7): `request.report_id` names the report a request stands for, and every report still open gets
its request now, so that nothing open is only an account record `report_open`, which the hub no
longer shows. The downgrade deletes those requests (their account records stay, as every record
does, and name a request that is gone, which the notifications skip) and drops the column, its
foreign key before its index: MariaDB uses that index for the key.

Revision ID: 20261104150000_report_request
Revises: 20261104000000_required_check
Create Date: 2026-11-04
"""

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20261104150000_report_request"
down_revision: str | None = "20261104000000_required_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"  # maity_hub.ids, frozen here
TITLE = 200

human = sa.table("human", sa.column("id", sa.String), sa.column("created_at", sa.DateTime))
abuse_report = sa.table(
    "abuse_report",
    sa.column("id", sa.String),
    sa.column("reason", sa.String),
    sa.column("target_type", sa.String),
    sa.column("status", sa.String),
    sa.column("created_at", sa.DateTime),
)
request = sa.table(
    "request",
    sa.column("id", sa.String),
    sa.column("project_id", sa.String),
    sa.column("org_id", sa.String),
    sa.column("class", sa.String),
    sa.column("title", sa.String),
    sa.column("options", sa.JSON),
    sa.column("priority", sa.String),
    sa.column("to_kind", sa.String),
    sa.column("to_human", sa.String),
    sa.column("personal", sa.Boolean),
    sa.column("filed_by", sa.String),
    sa.column("while_open", sa.String),
    sa.column("status", sa.String),
    sa.column("report_id", sa.String),
    sa.column("humans_only", sa.Boolean),
    sa.column("created_at", sa.DateTime),
)
account_record = sa.table(
    "account_record",
    sa.column("human_id", sa.String),
    sa.column("type", sa.String),
    sa.column("data", sa.JSON),
    sa.column("at", sa.DateTime),
)


def upgrade() -> None:
    with op.batch_alter_table("request") as batch:
        batch.add_column(sa.Column("report_id", sa.String(40), nullable=True))
        batch.create_foreign_key(
            op.f("fk_request_report_id_abuse_report"), "abuse_report", ["report_id"], ["id"]
        )
        batch.create_index(op.f("ix_request_report_id"), ["report_id"], unique=False)
    conn = op.get_bind()
    # The instance admin is the earliest account (maity_hub.admin.instance_admin_id).
    admin = conn.execute(
        sa.select(human.c.id).order_by(human.c.created_at, human.c.id).limit(1)
    ).scalar()
    if admin is None:
        return
    open_reports = conn.execute(
        sa.select(abuse_report.c.id, abuse_report.c.reason, abuse_report.c.target_type)
        .where(abuse_report.c.status == "open")
        .order_by(abuse_report.c.created_at, abuse_report.c.id)
    ).all()
    now = datetime.now(UTC).replace(tzinfo=None)
    for report in open_reports:
        request_id = "req-" + "".join(secrets.choice(CROCKFORD) for _ in range(12))
        conn.execute(
            request.insert().values(
                id=request_id,
                project_id=None,
                org_id=None,
                **{"class": "info"},
                title=f"Report: {report.reason} — {report.target_type}"[:TITLE],
                options=[],
                priority="normal",
                to_kind="human",
                to_human=admin,
                personal=True,
                filed_by="hub",
                while_open="wait",
                status="open",
                report_id=report.id,
                humans_only=True,
                created_at=now,
            )
        )
        conn.execute(
            account_record.insert().values(
                human_id=admin,
                type="personal_request_created",
                data={
                    "request_id": request_id,
                    "project_id": None,
                    "org_id": None,
                    "status": "open",
                },
                at=now,
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(request.delete().where(request.c.report_id.isnot(None)))
    with op.batch_alter_table("request") as batch:
        batch.drop_constraint(op.f("fk_request_report_id_abuse_report"), type_="foreignkey")
        batch.drop_index(op.f("ix_request_report_id"))
        batch.drop_column("report_id")
