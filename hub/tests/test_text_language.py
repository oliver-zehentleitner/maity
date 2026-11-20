"""The language of the hub's own texts for a human (docs/api.md §6.2), read by `text_language`
straight from the two stored values: the same answer as reading it through the merged
notification settings, which is where it was read before."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Connection, Engine, select, update

from maity_hub import languages
from maity_hub import tables as t
from maity_hub.notifications import preferences
from maity_hub.notifications.address import row_of
from maity_hub.text_language import text_language
from tests import factory

# (interface language chosen, the stored settings or None for no row, what the hub speaks)
CASES: list[tuple[str | None, dict[str, Any] | None, str]] = [
    (None, None, "en"),  # never set anything: no settings row
    (None, {}, "en"),  # a row, nothing stored
    (None, {"browser": {"enabled": True}}, "en"),  # other settings only
    (None, {"email": {}}, "en"),
    (None, {"email": {"timezone": "Europe/Vienna"}}, "en"),  # an email setting, not the language
    (None, {"email": {"language": "ko"}}, "ko"),  # what agents write in, an interface language
    (None, {"email": {"language": "sw"}}, "en"),  # what agents write in, no interface language
    ("de", None, "de"),  # the interface language, no row
    ("de", {"email": {"language": "ko"}}, "de"),  # the interface language comes first
    ("ja", {"email": {"language": "sw"}}, "ja"),
]


def _old(conn: Connection, human_id: str) -> str:
    """How `notifications.preferences.text_language` read it: the merged settings."""
    chosen = conn.execute(
        select(t.human.c.interface_language).where(t.human.c.id == human_id)
    ).scalar_one_or_none()
    merged = preferences.preferences(conn, human_id)
    return languages.of_interface(chosen, merged["email"]["language"])


@pytest.mark.parametrize(("chosen", "stored", "expected"), CASES)
def test_text_language_reads_as_the_merged_settings_did(
    migrated: Engine, chosen: str | None, stored: dict[str, Any] | None, expected: str
) -> None:
    human_id = factory.human(migrated)
    with migrated.begin() as conn:
        conn.execute(
            update(t.human).where(t.human.c.id == human_id).values(interface_language=chosen)
        )
        if stored is not None:
            row_of(conn, human_id, lock=True)  # the row the first write makes
            conn.execute(
                update(t.notification_settings)
                .where(t.notification_settings.c.human_id == human_id)
                .values(preferences=stored)
            )
    with migrated.connect() as conn:
        assert text_language(conn, human_id) == expected
        assert text_language(conn, human_id) == _old(conn, human_id)


def test_a_human_who_does_not_exist_reads_english(migrated: Engine) -> None:
    with migrated.connect() as conn:
        assert text_language(conn, "hum-nobody") == "en"
