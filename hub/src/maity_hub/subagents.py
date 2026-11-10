"""The owner's instruction to work in subagents (docs/api.md §3.1, §5.2, §6.2).

A join carries `subagents` and the language of the instruction; the exchange moves both to the
membership with the join's creator as who set it. The instruction is one fixed text in the
hub's words (`subagents.instruction`), with the handle of the human who owns the agent.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select

from maity_hub import catalog, languages
from maity_hub import tables as t
from maity_hub.errors import invalid
from maity_hub.notifications import preferences

# The roles a join without `subagents` switches it on for (§3.1); the migration that added
# the field gave the same default to the memberships and open joins before it (§6.2).
ROLES = frozenset({"coder", "reviewer"})


def default_for(role: str) -> bool:
    return role in ROLES


def language_of(conn: Connection, requested: str | None, human_id: str) -> str:
    """The instruction's language: the one asked for, which must be an interface language,
    else the language the hub writes to that human in (§6.2)."""
    if requested is None:
        return preferences.text_language(conn, human_id)
    if requested not in languages.INTERFACE:
        raise invalid({"subagents_language": "not_interface"}, "not an interface language")
    return requested


def instruction(language: str, owner_handle: str) -> str:
    return catalog.section("subagents", language)["instruction"].replace("{owner}", owner_handle)


def handle_of(conn: Connection, human_id: str) -> str:
    handle: str = conn.execute(
        select(t.human.c.handle).where(t.human.c.id == human_id)
    ).scalar_one()
    return handle


def block(conn: Connection, row: Any) -> dict[str, Any]:
    """`membership.subagents` of the resume packet (§5.2), from a membership row."""
    if not row.subagents or row.subagents_by is None:
        return {"on": False, "language": None, "by": None, "instruction": None}
    handle = handle_of(conn, row.subagents_by)
    language = row.subagents_language or "en"
    return {
        "on": True,
        "language": language,
        "by": {"kind": "human", "id": row.subagents_by, "handle": handle},
        "instruction": instruction(language, handle),
    }


def may_configure(mine: Any, target: Any, owner_id: str | None) -> bool:
    """Whoever may let the agent join may configure it (§3.1, "Who changes it"): the human
    who owns the agent profile, with `members:admin`, or with trust `member` under
    `policy.member_agents` while the membership is within the member limits. The join's own
    checks, made now."""
    from maity_hub.routes import joins  # the join rules live with the joins

    if mine.kind != "human" or owner_id is None or owner_id != mine.principal_id:
        return False
    if mine.may("members:admin"):
        return True
    return (
        joins.may_bring(mine) and mine.project.member_agents == "on" and joins.within_limits(target)
    )
