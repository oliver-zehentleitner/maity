from __future__ import annotations

from sqlalchemy import Engine

from maity_hub.db import current_revision, downgrade, head_revision, migrate


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
