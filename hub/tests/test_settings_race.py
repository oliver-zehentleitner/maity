"""docs/api.md §18.4: two first writes of one human's settings, on two real connections."""

from __future__ import annotations

from sqlalchemy import Engine, func, select

from maity_hub import tables as t
from maity_hub.notifications import preferences
from tests import factory
from tests.concurrency import finished, race, waiting


def test_two_first_writes_of_the_same_human_make_one_row(migrated: Engine) -> None:
    """Neither found a row; the first inserts and commits while the second waits on the
    key. The second does not fail: it finds the row the first made and goes on."""
    human = factory.human(migrated)
    with race(migrated) as r:
        first = preferences.row_of(r.first, human, lock=True)
        step = r.run(r.second, lambda: preferences.row_of(r.second, human, lock=True))
        assert waiting(step)
        r.first.commit()
        second = finished(step)
        r.second.commit()
    assert first.human_id == second.human_id == human
    with migrated.connect() as conn:
        rows = conn.execute(select(func.count()).select_from(t.notification_settings)).scalar()
    assert rows == 1
