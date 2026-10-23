from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path

from sqlalchemy import Engine

from maity_hub.db import create_revision, current_revision, downgrade, head_revision, migrate


def test_migrate_reaches_head_and_is_idempotent(engine: Engine) -> None:
    assert current_revision(engine) is None
    migrate(engine)
    assert current_revision(engine) == head_revision(engine)
    migrate(engine)
    assert current_revision(engine) == head_revision(engine)


def test_every_migration_downgrades(engine: Engine) -> None:
    migrate(engine)
    downgrade(engine)
    assert current_revision(engine) is None


def test_sqlite_keeps_foreign_keys_on_after_a_migration(engine: Engine) -> None:
    """Migrations switch SQLite's foreign keys off to rebuild tables; the pooled
    connection must come back with them on, or the hub would stop enforcing them."""
    if engine.dialect.name != "sqlite":
        return
    migrate(engine)
    downgrade(engine, "0002")  # a downgrade rebuilds referenced tables
    migrate(engine)
    for _ in range(3):  # whichever pooled connection comes next
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_create_revision_numbers_the_next_migration(engine: Engine, tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    shutil.copytree(Path(str(files("maity_hub") / "migrations")), migrations)
    head = head_revision(engine)
    assert head is not None
    following = f"{int(head) + 1:04d}"
    created = create_revision(engine, "add the task table", migrations)
    assert created.name == f"{following}_add_the_task_table.py"
    assert f'revision: str = "{following}"' in created.read_text()
    assert f'down_revision: str | None = "{head}"' in created.read_text()


def test_the_profile_delete_downgrade_restores_one_handle_per_owner(engine: Engine) -> None:
    """0019 down: deleted profiles whose handle a live one took get their id appended, so
    the old `(owner_id, handle)` key holds again and is enforced."""
    from datetime import UTC, datetime

    import pytest
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    from maity_hub import tables as t

    migrate(engine)
    now = datetime(2026, 10, 23, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(
            insert(t.human).values(
                id="hum-o", handle="o", display_name="O", password_hash="x", created_at=now
            )
        )
        for n, deleted in (("1", now), ("2", now), ("3", None)):
            conn.execute(
                insert(t.agent_profile).values(
                    id=f"agt-{n}", owner_id="hum-o", handle="same", display_name="Same",
                    created_at=now, deleted_at=deleted, live=None if deleted else True,
                )
            )  # fmt: skip
    downgrade(engine, "0018")
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT id, handle FROM agent_profile ORDER BY id").all()
    assert [tuple(r) for r in rows] == [
        ("agt-1", "same~agt-1"),
        ("agt-2", "same~agt-2"),
        ("agt-3", "same"),
    ]
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO agent_profile (id, owner_id, handle, display_name, created_at) "
            "VALUES ('agt-4', 'hum-o', 'same', 'Same', '2026-10-23 00:00:00')"
        )
