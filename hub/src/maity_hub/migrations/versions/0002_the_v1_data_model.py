"""The V1 data model: every table of docs/architecture.md §3.6.

Self-contained: the types are spelled out here instead of imported from
maity_hub, so that later changes to the application cannot change what
this revision creates.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21 14:17:01.473383
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# maity_hub.types.UtcDateTime stores naive UTC; microseconds on MySQL/MariaDB.
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
MARKDOWN_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")


def upgrade() -> None:
    op.create_table(
        "human",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("handle", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("last_seen_at", TIMESTAMP, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_human")),
        sa.UniqueConstraint("handle", name=op.f("uq_human_handle")),
    )
    op.create_table(
        "idempotency_key",
        sa.Column("caller", sa.String(length=40), nullable=False),
        sa.Column("idem_key", sa.String(length=128), nullable=False),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=True),
        sa.Column("resource_id", sa.String(length=40), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("caller", "idem_key", name=op.f("pk_idempotency_key")),
    )
    op.create_index(
        op.f("ix_idempotency_key_created_at"), "idempotency_key", ["created_at"], unique=False
    )

    op.create_table(
        "project",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("state_note", MARKDOWN_TEXT, nullable=True),
        sa.Column("state_changed_at", TIMESTAMP, nullable=False),
        sa.Column("repository_url", sa.String(length=255), nullable=True),
        sa.Column("repository_default_branch", sa.String(length=255), nullable=True),
        sa.Column("keep_the_why", sa.Boolean(), nullable=False),
        sa.Column("policy_preset", sa.String(length=32), nullable=False),
        sa.Column("claim_policy", sa.String(length=32), nullable=False),
        sa.Column("done_authority", sa.String(length=32), nullable=False),
        sa.Column("contract_arbiter", sa.String(length=48), nullable=False),
        sa.Column("tag_authority", sa.String(length=32), nullable=False),
        sa.Column("steward_writes", sa.String(length=32), nullable=False),
        sa.Column("lease_seconds", sa.Integer(), nullable=False),
        sa.Column("absence_until", TIMESTAMP, nullable=True),
        sa.Column("absence_scope", MARKDOWN_TEXT, nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("rules_markdown", MARKDOWN_TEXT, nullable=True),
        sa.Column("rules_version", sa.Integer(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project")),
        sa.UniqueConstraint("slug", name=op.f("uq_project_slug")),
    )
    op.create_table(
        "agent_profile",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("owner_id", sa.String(length=40), nullable=False),
        sa.Column("handle", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("git_name", sa.String(length=200), nullable=True),
        sa.Column("git_email", sa.String(length=200), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["human.id"], name=op.f("fk_agent_profile_owner_id_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_profile")),
        sa.UniqueConstraint("owner_id", "handle", name=op.f("uq_agent_profile_owner_id_handle")),
    )
    op.create_table(
        "forge_observation",
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("ref", sa.String(length=255), nullable=False),
        sa.Column("observed_at", TIMESTAMP, nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_forge_observation_project_id_project")
        ),
        sa.PrimaryKeyConstraint("project_id", "kind", "ref", name=op.f("pk_forge_observation")),
    )
    op.create_table(
        "human_session",
        sa.Column("id_hash", sa.String(length=64), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("last_seen_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("ended_at", TIMESTAMP, nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_human_session_human_id_human")
        ),
        sa.PrimaryKeyConstraint("id_hash", name=op.f("pk_human_session")),
    )
    op.create_index(op.f("ix_human_session_human_id"), "human_session", ["human_id"], unique=False)

    op.create_table(
        "membership",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=True),
        sa.Column("agent_id", sa.String(length=40), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("reports_to", sa.Integer(), nullable=True),
        sa.Column("areas", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("paused_reason", MARKDOWN_TEXT, nullable=True),
        sa.Column("paused_since", TIMESTAMP, nullable=True),
        sa.Column("paused_by", sa.String(length=40), nullable=True),
        sa.Column("joined_at", TIMESTAMP, nullable=False),
        sa.Column("last_seen_at", TIMESTAMP, nullable=True),
        sa.Column("removed_at", TIMESTAMP, nullable=True),
        sa.CheckConstraint(
            "(human_id IS NULL AND agent_id IS NOT NULL)"
            " OR (human_id IS NOT NULL AND agent_id IS NULL)",
            name=op.f("ck_membership_one_principal"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agent_profile.id"], name=op.f("fk_membership_agent_id_agent_profile")
        ),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_membership_human_id_human")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_membership_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["reports_to"], ["membership.id"], name=op.f("fk_membership_reports_to_membership")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_membership")),
        sa.UniqueConstraint(
            "project_id", "agent_id", name=op.f("uq_membership_project_id_agent_id")
        ),
        sa.UniqueConstraint(
            "project_id", "human_id", name=op.f("uq_membership_project_id_human_id")
        ),
    )
    op.create_table(
        "card",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", MARKDOWN_TEXT, nullable=True),
        sa.Column("label", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("status_before_block", sa.String(length=16), nullable=True),
        sa.Column("area", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("assigned_to", sa.Integer(), nullable=True),
        sa.Column("claim_holder", sa.Integer(), nullable=True),
        sa.Column("claim_session_id", sa.String(length=40), nullable=True),
        sa.Column("claim_since", TIMESTAMP, nullable=True),
        sa.Column("lease_until", TIMESTAMP, nullable=True),
        sa.Column("checkpoint", sa.JSON(), nullable=True),
        sa.Column("blocked_by_request", sa.String(length=40), nullable=True),
        sa.Column("ktw_ref", sa.String(length=255), nullable=True),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("contract", sa.JSON(), nullable=True),
        sa.Column("release_version", sa.String(length=64), nullable=True),
        sa.Column("release_data", sa.JSON(), nullable=True),
        sa.Column("release_in_flight", sa.Boolean(), nullable=True),
        sa.Column("changed_by_credential", sa.String(length=40), nullable=True),
        sa.Column("changed_via", sa.String(length=16), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.Column("closed_at", TIMESTAMP, nullable=True),
        sa.ForeignKeyConstraint(
            ["assigned_to"], ["membership.id"], name=op.f("fk_card_assigned_to_membership")
        ),
        sa.ForeignKeyConstraint(
            ["claim_holder"], ["membership.id"], name=op.f("fk_card_claim_holder_membership")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["membership.id"], name=op.f("fk_card_created_by_membership")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_card_project_id_project")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card")),
        sa.UniqueConstraint(
            "project_id", "release_in_flight", name="uq_card_one_release_in_flight"
        ),
        sa.UniqueConstraint(
            "project_id", "release_version", name=op.f("uq_card_project_id_release_version")
        ),
    )
    op.create_index("ix_card_claim_holder", "card", ["claim_holder"], unique=False)
    op.create_index("ix_card_project_updated", "card", ["project_id", "updated_at"], unique=False)

    op.create_table(
        "conversation_read",
        sa.Column("reader", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("last_seq", BIG_ID, nullable=False),
        sa.ForeignKeyConstraint(
            ["reader"], ["membership.id"], name=op.f("fk_conversation_read_reader_membership")
        ),
        sa.PrimaryKeyConstraint("reader", "conversation_id", name=op.f("pk_conversation_read")),
    )
    op.create_table(
        "event",
        sa.Column("seq", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("at", TIMESTAMP, nullable=False),
        sa.Column("actor_membership", sa.Integer(), nullable=True),
        sa.Column("actor_session_id", sa.String(length=40), nullable=True),
        sa.Column("actor_credential_id", sa.String(length=40), nullable=True),
        sa.Column("actor_via", sa.String(length=16), nullable=True),
        sa.Column("actor_harness", sa.String(length=200), nullable=True),
        sa.Column("actor_model", sa.String(length=200), nullable=True),
        sa.Column("subject_type", sa.String(length=32), nullable=True),
        sa.Column("subject_id", sa.String(length=40), nullable=True),
        sa.Column("audience", sa.JSON(), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("redacted", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_membership"],
            ["membership.id"],
            name=op.f("fk_event_actor_membership_membership"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_event_project_id_project")
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_event")),
    )
    op.create_index(
        "ix_event_conversation", "event", ["project_id", "conversation_id", "seq"], unique=False
    )
    op.create_index("ix_event_project_seq", "event", ["project_id", "seq"], unique=False)

    op.create_table(
        "join_link",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=40), nullable=True),
        sa.Column("new_agent_handle", sa.String(length=64), nullable=True),
        sa.Column("new_agent_display_name", sa.String(length=200), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("reports_to", sa.Integer(), nullable=True),
        sa.Column("areas", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=40), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("used_at", TIMESTAMP, nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("burned_at", TIMESTAMP, nullable=True),
        sa.Column("revoked_at", TIMESTAMP, nullable=True),
        sa.CheckConstraint(
            "agent_id IS NOT NULL OR new_agent_handle IS NOT NULL",
            name=op.f("ck_join_link_names_an_agent"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agent_profile.id"], name=op.f("fk_join_link_agent_id_agent_profile")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["human.id"], name=op.f("fk_join_link_created_by_human")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_join_link_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["reports_to"], ["membership.id"], name=op.f("fk_join_link_reports_to_membership")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_join_link")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_join_link_token_hash")),
    )
    op.create_index(op.f("ix_join_link_project_id"), "join_link", ["project_id"], unique=False)

    op.create_table(
        "card_edge",
        sa.Column("from_card", sa.String(length=40), nullable=False),
        sa.Column("to_card", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.CheckConstraint("from_card <> to_card", name=op.f("ck_card_edge_no_self_edge")),
        sa.ForeignKeyConstraint(
            ["from_card"], ["card.id"], name=op.f("fk_card_edge_from_card_card")
        ),
        sa.ForeignKeyConstraint(["to_card"], ["card.id"], name=op.f("fk_card_edge_to_card_card")),
        sa.PrimaryKeyConstraint("from_card", "to_card", "kind", name=op.f("pk_card_edge")),
    )
    op.create_index(op.f("ix_card_edge_to_card"), "card_edge", ["to_card"], unique=False)

    op.create_table(
        "credential",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("verifier", sa.String(length=64), nullable=False),
        sa.Column("join_id", sa.String(length=40), nullable=True),
        sa.Column("client", sa.String(length=200), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("resumed_at", TIMESTAMP, nullable=True),
        sa.Column("last_used_at", TIMESTAMP, nullable=True),
        sa.Column("revoked_at", TIMESTAMP, nullable=True),
        sa.Column("revoked_by", sa.String(length=40), nullable=True),
        sa.Column("revoked_reason", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["join_id"], ["join_link.id"], name=op.f("fk_credential_join_id_join_link")
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_credential_membership_id_membership"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credential")),
    )
    op.create_index(
        op.f("ix_credential_membership_id"), "credential", ["membership_id"], unique=False
    )

    op.create_table(
        "message_delivery",
        sa.Column("seq", BIG_ID, nullable=False),
        sa.Column("delivered_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["seq"], ["event.seq"], name=op.f("fk_message_delivery_seq_event")),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_message_delivery")),
    )
    op.create_table(
        "request",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("class", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", MARKDOWN_TEXT, nullable=True),
        sa.Column("tried", MARKDOWN_TEXT, nullable=True),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("to_kind", sa.String(length=16), nullable=False),
        sa.Column("to_member", sa.Integer(), nullable=True),
        sa.Column("to_role", sa.String(length=16), nullable=True),
        sa.Column("asked_by", sa.Integer(), nullable=False),
        sa.Column("asked_session_id", sa.String(length=40), nullable=True),
        sa.Column("on_behalf_of", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.String(length=40), nullable=True),
        sa.Column("while_open", sa.String(length=32), nullable=False),
        sa.Column("needs_in_session", sa.JSON(), nullable=True),
        sa.Column("ktw_ref", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("answer", sa.JSON(), nullable=True),
        sa.Column("answered_by", sa.Integer(), nullable=True),
        sa.Column("answered_at", TIMESTAMP, nullable=True),
        sa.Column("withdrawn_at", TIMESTAMP, nullable=True),
        sa.Column("withdraw_reason", MARKDOWN_TEXT, nullable=True),
        sa.Column("changed_by_credential", sa.String(length=40), nullable=True),
        sa.Column("changed_via", sa.String(length=16), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["answered_by"], ["membership.id"], name=op.f("fk_request_answered_by_membership")
        ),
        sa.ForeignKeyConstraint(
            ["asked_by"], ["membership.id"], name=op.f("fk_request_asked_by_membership")
        ),
        sa.ForeignKeyConstraint(
            ["on_behalf_of"], ["membership.id"], name=op.f("fk_request_on_behalf_of_membership")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_request_project_id_project")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["card.id"], name=op.f("fk_request_task_id_card")),
        sa.ForeignKeyConstraint(
            ["to_member"], ["membership.id"], name=op.f("fk_request_to_member_membership")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request")),
    )
    op.create_index("ix_request_project_status", "request", ["project_id", "status"], unique=False)
    op.create_index("ix_request_to_member_status", "request", ["to_member", "status"], unique=False)

    op.create_table(
        "agent_session",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("credential_id", sa.String(length=40), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("harness", sa.String(length=200), nullable=True),
        sa.Column("harness_version", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("client", sa.String(length=200), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("started_at", TIMESTAMP, nullable=False),
        sa.Column("last_seen_at", TIMESTAMP, nullable=False),
        sa.Column("ended_at", TIMESTAMP, nullable=True),
        sa.Column("acknowledged_seq", BIG_ID, nullable=False),
        sa.Column("live", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credential.id"],
            name=op.f("fk_agent_session_credential_id_credential"),
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_agent_session_membership_id_membership"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_session")),
        sa.UniqueConstraint("credential_id", "live", name="uq_agent_session_one_live"),
    )
    op.create_index(
        op.f("ix_agent_session_membership_id"), "agent_session", ["membership_id"], unique=False
    )


def downgrade() -> None:
    op.drop_table("agent_session")
    op.drop_table("request")
    op.drop_table("message_delivery")
    op.drop_table("credential")
    op.drop_table("card_edge")
    op.drop_table("join_link")
    op.drop_table("event")
    op.drop_table("conversation_read")
    op.drop_table("card")
    op.drop_table("membership")
    op.drop_table("human_session")
    op.drop_table("forge_observation")
    op.drop_table("agent_profile")
    op.drop_table("project")
    op.drop_table("idempotency_key")
    op.drop_table("human")
