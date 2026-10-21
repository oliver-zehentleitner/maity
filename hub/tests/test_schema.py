"""The schema's invariants, on whichever engine the suite runs against."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, Engine, insert, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, StatementError

from maity_hub import tables as t
from maity_hub.db import metadata, migrate
from maity_hub.ids import new_id

# MariaDB reports a failed CHECK as an OperationalError (4025), the others as
# an IntegrityError; the API validates before it writes, so only tests see it.
CHECK_FAILED = (IntegrityError, OperationalError)

NOW = datetime(2026, 10, 21, 13, 41, 10, 123456, tzinfo=UTC)


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    migrate(engine)
    with engine.connect() as connection:
        yield connection
        connection.rollback()


def _human(conn: Connection) -> str:
    human_id = new_id("human")
    conn.execute(
        insert(t.human).values(
            id=human_id,
            handle=human_id,
            display_name="Maintainer",
            password_hash="scrypt$…",
            created_at=NOW,
        )
    )
    return human_id


def _project(conn: Connection) -> str:
    project_id = new_id("project")
    conn.execute(
        insert(t.project).values(
            id=project_id,
            slug=project_id,
            name="Maity",
            state="build",
            state_changed_at=NOW,
            keep_the_why=True,
            policy_preset="hierarchical",
            claim_policy="self-claim",
            done_authority="reviewer",
            contract_arbiter="role:admin",
            tag_authority="human",
            steward_writes="cards_only",
            lease_seconds=7200,
            settings={"release_checklist": []},
            rules_version=1,
            created_at=NOW,
        )
    )
    return project_id


def _membership(conn: Connection, project_id: str, **principal: str | None) -> int:
    result = conn.execute(
        insert(t.membership).values(
            project_id=project_id,
            role="owner",
            areas=["/"],
            capabilities=[],
            joined_at=NOW,
            **principal,
        )
    )
    key = result.inserted_primary_key
    assert key is not None
    return int(key[0])


def _card(conn: Connection, project_id: str, member: int, **values: Any) -> str:
    card_id = new_id("task")
    row = {
        "id": card_id,
        "project_id": project_id,
        "kind": "task",
        "title": "A card",
        "status": "open",
        "created_by": member,
        "created_at": NOW,
        "updated_at": NOW,
    }
    conn.execute(insert(t.card).values({**row, **values}))
    return card_id


def test_the_migrations_create_exactly_the_tables_in_code(conn: Connection) -> None:
    differences = compare_metadata(MigrationContext.configure(conn), metadata)
    assert differences == []


def test_a_membership_has_exactly_one_principal(conn: Connection) -> None:
    project_id = _project(conn)
    with pytest.raises(CHECK_FAILED):
        _membership(conn, project_id)


def test_a_membership_with_both_principals_is_refused(conn: Connection) -> None:
    project_id, human_id = _project(conn), _human(conn)
    agent_id = new_id("agent")
    conn.execute(
        insert(t.agent_profile).values(
            id=agent_id, owner_id=human_id, handle="agent-b", display_name="B", created_at=NOW
        )
    )
    with pytest.raises(CHECK_FAILED):
        _membership(conn, project_id, human_id=human_id, agent_id=agent_id)


def test_timestamps_keep_microseconds_and_come_back_in_utc(conn: Connection) -> None:
    human_id = _human(conn)
    vienna = NOW.astimezone(ZoneInfo("Europe/Vienna"))
    conn.execute(update(t.human).where(t.human.c.id == human_id).values(last_seen_at=vienna))
    stored = conn.execute(select(t.human.c.last_seen_at).where(t.human.c.id == human_id)).scalar()
    assert stored == NOW
    assert stored is not None and stored.tzinfo == UTC


def test_a_naive_timestamp_is_refused(conn: Connection) -> None:
    human_id = _human(conn)
    with pytest.raises(StatementError, match="naive datetime"):
        conn.execute(
            update(t.human)
            .where(t.human.c.id == human_id)
            .values(last_seen_at=NOW.replace(tzinfo=None))
        )


def test_the_claim_is_one_conditional_update(conn: Connection) -> None:
    project_id = _project(conn)
    owner = _membership(conn, project_id, human_id=_human(conn))
    other = _membership(conn, project_id, human_id=_human(conn))
    card_id = _card(conn, project_id, owner)

    def claim(member: int) -> int:
        return conn.execute(
            update(t.card)
            .where(t.card.c.id == card_id, t.card.c.claim_holder.is_(None))
            .values(claim_holder=member, claim_since=NOW, lease_until=NOW + timedelta(hours=2))
        ).rowcount

    assert claim(owner) == 1
    assert claim(other) == 0
    assert conn.execute(select(t.card.c.claim_holder)).scalar() == owner


def test_one_release_in_flight_per_project(conn: Connection) -> None:
    project_id = _project(conn)
    owner = _membership(conn, project_id, human_id=_human(conn))
    release = {"kind": "release", "release_in_flight": True}
    _card(conn, project_id, owner, release_version="0.1.0", **release)
    _card(conn, project_id, owner, release_version="0.0.9", kind="release")  # closed: NULL
    _card(conn, project_id, owner)  # tasks never count
    _card(conn, _project(conn), owner, release_version="0.1.0", **release)  # other project
    with pytest.raises(IntegrityError):
        _card(conn, project_id, owner, release_version="0.2.0", **release)


def test_a_release_version_is_unique_per_project(conn: Connection) -> None:
    project_id = _project(conn)
    owner = _membership(conn, project_id, human_id=_human(conn))
    _card(conn, project_id, owner, kind="release", release_version="0.1.0")
    with pytest.raises(IntegrityError):
        _card(conn, project_id, owner, kind="release", release_version="0.1.0")


def test_one_live_session_per_credential(conn: Connection) -> None:
    project_id = _project(conn)
    member = _membership(conn, project_id, human_id=_human(conn))
    credential_id = new_id("credential")
    conn.execute(
        insert(t.credential).values(
            id=credential_id, membership_id=member, verifier="0" * 64, created_at=NOW
        )
    )

    def session(live: bool | None) -> None:
        conn.execute(
            insert(t.agent_session).values(
                id=new_id("session"),
                credential_id=credential_id,
                membership_id=member,
                started_at=NOW,
                last_seen_at=NOW,
                acknowledged_seq=0,
                live=live,
            )
        )

    session(None)
    session(None)
    session(True)
    with pytest.raises(IntegrityError):
        session(True)


def test_event_seq_increases_and_holds_json(conn: Connection) -> None:
    project_id = _project(conn)
    seqs = []
    for kind in ("task_created", "task_claimed"):
        result = conn.execute(
            insert(t.event).values(
                project_id=project_id,
                kind=kind,
                at=NOW,
                audience=["member:agt-b", "role:admin"],
                payload={"reason": None, "nested": {"n": 1}},
                redacted=False,
            )
        )
        key = result.inserted_primary_key
        assert key is not None
        seqs.append(key[0])
    assert seqs[0] < seqs[1]
    payload = conn.execute(select(t.event.c.payload).where(t.event.c.seq == seqs[1])).scalar()
    assert payload == {"reason": None, "nested": {"n": 1}}


def test_a_markdown_body_at_the_cap_fits_in_four_byte_characters(conn: Connection) -> None:
    project_id = _project(conn)
    owner = _membership(conn, project_id, human_id=_human(conn))
    body = "🦄" * t.MARKDOWN
    card_id = _card(conn, project_id, owner, body=body, title="ü" * t.TITLE)
    stored = conn.execute(select(t.card.c.body).where(t.card.c.id == card_id)).scalar()
    assert stored == body


def test_ids_carry_their_prefix_and_differ() -> None:
    ids = {new_id("task") for _ in range(1000)}
    assert len(ids) == 1000
    assert all(i.startswith("tsk-") and len(i) == 16 for i in ids)
