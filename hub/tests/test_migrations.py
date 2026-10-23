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


def test_sqlite_keeps_the_event_seq_autoincrement_through_every_migration(engine: Engine) -> None:
    """A migration that rebuilds `event` on SQLite must keep AUTOINCREMENT, or a seq
    freed by a delete could be handed out again (0002, docs/api.md §8)."""
    if engine.dialect.name != "sqlite":
        return

    def ddl() -> str:
        with engine.connect() as conn:
            sql: str = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'event'"
            ).scalar_one()
        return sql

    migrate(engine)
    assert "AUTOINCREMENT" in ddl()
    downgrade(engine, "0002")
    assert "AUTOINCREMENT" in ddl()


def test_create_revision_numbers_the_next_migration(engine: Engine, tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    shutil.copytree(Path(str(files("maity_hub") / "migrations")), migrations)
    head = head_revision(engine)
    assert head is not None
    # The highest number in use plus one, which is not head + 1 when a reserved number
    # landed after a higher one; down_revision is the head all the same.
    used = [int(p.name[:4]) for p in (migrations / "versions").glob("[0-9][0-9][0-9][0-9]_*.py")]
    following = f"{max(used) + 1:04d}"
    created = create_revision(engine, "add the task table", migrations)
    assert created.name == f"{following}_add_the_task_table.py"
    assert f'revision: str = "{following}"' in created.read_text()
    assert f'down_revision: str | None = "{head}"' in created.read_text()
