"""A human's start tabs (docs/api.md §5.1 "Start tabs"): the projects a browser with no tabs
of its own opens, in order, named by the project's fixed id so that a rename or a transfer
keeps them. The open tabs themselves stay in each browser; the hub keeps only this list."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Connection, select, update

from maity_hub import tables as t
from maity_hub.errors import invalid


def visible(stored: list[str] | None, current: Iterable[str]) -> list[str] | None:
    """The list as `GET /me` shows it: only current memberships, `null` stays `null`."""
    if stored is None:
        return None
    mine = set(current)
    return [project_id for project_id in stored if project_id in mine]


def _memberships(conn: Connection, human_id: str) -> set[str]:
    return set(
        conn.execute(
            select(t.membership.c.project_id).where(
                t.membership.c.human_id == human_id, t.membership.c.removed_at.is_(None)
            )
        ).scalars()
    )


def checked(conn: Connection, human_id: str, given: list[str] | None) -> list[str] | None:
    """`PATCH /me`'s `start_tabs`, always the whole list: current memberships, each once."""
    if given is None:
        return None
    if len(set(given)) != len(given):
        raise invalid({"start_tabs": "duplicate"}, "a project is in the list twice")
    if not set(given) <= _memberships(conn, human_id):
        raise invalid({"start_tabs": "not_a_member"}, "a project you are not a member of")
    return list(given)


def append(conn: Connection, human_id: str, project_id: str) -> None:
    """A new membership of the human goes to the end of a list they set, its earlier place
    dropped, so a project joined later opens as the last tab. `null` stays `null`: it opens
    every membership already. A browser cannot tell a newly joined project from one the
    human took out of the list, so the hub does it where the membership is made."""
    row = conn.execute(
        select(t.human.c.start_tabs).where(t.human.c.id == human_id).with_for_update()
    ).first()
    if row is None or row.start_tabs is None:
        return
    kept = [entry for entry in row.start_tabs if entry != project_id]
    conn.execute(
        update(t.human).where(t.human.c.id == human_id).values(start_tabs=[*kept, project_id])
    )
