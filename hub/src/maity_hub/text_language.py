"""The language of what the hub itself composes for a human (docs/api.md §6.2): mails, link
pages, bell titles. The interface language they chose, else what agents write in for them
when the portal has it, else English (`languages.of_interface`).

It reads the two stored values directly, so every module that composes a text for a human
can import it without importing the notification settings (hub/context/notifications.md,
"The hub's own words live in one catalog per language").
"""

from __future__ import annotations

from sqlalchemy import Connection, select

from maity_hub import languages
from maity_hub import tables as t


def text_language(conn: Connection, human_id: str) -> str:
    """The language of what the hub itself composes for this human (§6.2)."""
    chosen = conn.execute(
        select(t.human.c.interface_language).where(t.human.c.id == human_id)
    ).scalar_one_or_none()
    stored = conn.execute(
        select(t.notification_settings.c.preferences).where(
            t.notification_settings.c.human_id == human_id
        )
    ).scalar_one_or_none()
    # What agents write in, as the notification settings store it (`email.language`); none
    # stored reads as their default, English, which `of_interface` falls back to anyway.
    email = stored.get("email") if isinstance(stored, dict) else None
    language = email.get("language") if isinstance(email, dict) else None
    return languages.of_interface(chosen, language)
