from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path

from sqlalchemy import Engine, Insert

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
    # The highest number plus one, not the head's: numbers are reserved ahead, so a
    # revision chained later may carry a lower number than one merged before it.
    numbers = [int(p.name[:4]) for p in (migrations / "versions").glob("[0-9]*.py")]
    following = f"{max(numbers) + 1:04d}"
    created = create_revision(engine, "add the task table", migrations)
    assert created.name == f"{following}_add_the_task_table.py"
    assert f'revision: str = "{following}"' in created.read_text()
    assert f'down_revision: str | None = "{head}"' in created.read_text()


def test_the_profile_delete_downgrade_restores_one_handle_per_owner(engine: Engine) -> None:
    """0032 down: deleted profiles whose handle a live one took get their id appended, so
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
    downgrade(engine, "0020")
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


def _namespace_rows(engine: Engine) -> dict[str, str]:
    """Humans a, b and c, and a project `shop` whose first owner (a) left: before the
    namespace it has no owner column; returns the ids."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from maity_hub import tables as t
    from tests import factory

    migrate(engine)
    ids = {h: factory.human(engine, h) for h in ("a", "b", "c")}
    ids["shop"] = factory.project(engine, "shop", owner_id=ids["a"])
    start = datetime(2026, 10, 1, tzinfo=UTC)
    with engine.begin() as conn:
        for n, (who, active) in enumerate((("a", None), ("b", True), ("c", True))):
            conn.execute(
                insert_membership(ids["shop"], ids[who], start + timedelta(days=n), active)
            )
    downgrade(engine, "0055")
    with engine.begin() as conn:  # a limit as the old schema stored it: slugs
        conn.execute(update(t.human).where(t.human.c.id == ids["b"]).values(
            limit_show_reason_in=["shop", "gone"]))  # fmt: skip
    return ids


def insert_membership(project_id: str, human_id: str, joined: object, active: object) -> Insert:
    from sqlalchemy import insert

    from maity_hub import tables as t

    return insert(t.membership).values(
        project_id=project_id, human_id=human_id, role="owner", areas=["/"], capabilities=[],
        joined_at=joined, active=active,
    )  # fmt: skip


def test_the_namespace_owner_is_the_oldest_active_owner(engine: Engine) -> None:
    """0060: the creator left, so the next oldest active owner holds the namespace; the
    slug is kept as `legacy_slug`; a limit's `show_reason_in` names full names."""
    from sqlalchemy import select

    from maity_hub import tables as t

    ids = _namespace_rows(engine)
    migrate(engine)
    with engine.connect() as conn:
        project = conn.execute(select(t.project).where(t.project.c.id == ids["shop"])).one()
        shown = conn.execute(
            select(t.human.c.limit_show_reason_in).where(t.human.c.id == ids["b"])
        ).scalar()
    assert (project.owner_id, project.legacy_slug) == (ids["b"], "shop")
    assert shown == ["b/shop"]


def test_the_namespace_migration_stops_on_a_project_without_an_active_human_owner(
    engine: Engine,
) -> None:
    import pytest
    from sqlalchemy import update

    from maity_hub import tables as t

    _namespace_rows(engine)
    with engine.begin() as conn:
        conn.execute(update(t.membership).values(active=None))
    with pytest.raises(Exception, match="no human with an active owner membership in: shop"):
        migrate(engine)
    assert current_revision(engine) == "0055"
