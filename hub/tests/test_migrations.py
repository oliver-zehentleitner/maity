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
