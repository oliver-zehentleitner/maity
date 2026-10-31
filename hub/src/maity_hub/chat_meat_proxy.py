"""The meat-proxy mode per conversation (docs/api.md §9.3, "Meat proxy per chat", §5.2).

A human sets the mode for one conversation it takes part in, without changing its profile: `true`
(on, both parts unless the profile already has the mode on, whose parts then stay), `false` (off),
`null` (follow the profile, no row). Every human entry of a conversation's participants carries the
value that holds there as `meat_proxy`, the human's own choice as `meat_proxy_chat` (for the human
itself only), and while it is on the `meat_proxy_note`. Context for an agent, never a permission;
a change emits no event and wakes nobody.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from maity_hub import tables as t
from maity_hub.views import meat_proxy_note


def parts(lead: bool, hands: bool, chat: bool | None) -> tuple[bool, bool]:
    """The parts that hold in a chat: the profile's when the chat follows it or the profile is on
    already, none when the chat says off, both when the chat says on over a profile that is off."""
    if chat is None:
        return lead, hands
    if not chat:
        return False, False
    return (lead, hands) if (lead or hands) else (True, True)


def put(
    conn: Connection, human_id: str, project_id: str, conversation_id: str, value: bool | None
) -> None:
    """Set the choice: `None` removes the row. Idempotent, no event."""
    key = (
        t.conversation_meat_proxy.c.human_id == human_id,
        t.conversation_meat_proxy.c.project_id == project_id,
        t.conversation_meat_proxy.c.conversation_id == conversation_id,
    )
    if value is None:
        conn.execute(delete(t.conversation_meat_proxy).where(*key))
    elif not conn.execute(
        update(t.conversation_meat_proxy).where(*key).values(meat_proxy=value)
    ).rowcount:
        conn.execute(
            insert(t.conversation_meat_proxy).values(
                human_id=human_id,
                project_id=project_id,
                conversation_id=conversation_id,
                meat_proxy=value,
            )
        )


Chat = tuple[str, str, list[dict[str, Any]]]  # project id, conversation id, its participants


def shown(conn: Connection, chats: Iterable[Chat], viewer: str | None = None) -> None:
    """Add the three fields to every human entry of the participants lists given, in place;
    `viewer` is the human reading, who alone sees its own choice. A direct conversation's id is
    its agent's, the same in every project the agent is in: the project tells them apart."""
    chats = list(chats)
    humans = {p["member_id"] for _, _, people in chats for p in people if p["kind"] == "human"}
    if not humans:
        return
    profiles = {
        row.id: (row.meat_proxy_lead, row.meat_proxy_hands)
        for row in conn.execute(
            select(t.human.c.id, t.human.c.meat_proxy_lead, t.human.c.meat_proxy_hands).where(
                t.human.c.id.in_(humans)
            )
        )
    }
    choices: dict[tuple[str, str, str], bool] = {
        (row.human_id, row.project_id, row.conversation_id): bool(row.meat_proxy)
        for row in conn.execute(
            select(t.conversation_meat_proxy).where(
                t.conversation_meat_proxy.c.human_id.in_(humans),
                t.conversation_meat_proxy.c.project_id.in_({p for p, _, _ in chats}),
                t.conversation_meat_proxy.c.conversation_id.in_({c for _, c, _ in chats}),
            )
        )
    }
    for project_id, conversation_id, people in chats:
        for person in people:
            if person["kind"] != "human":
                continue
            who = person["member_id"]
            chat = choices.get((who, project_id, conversation_id))
            lead, hands = parts(*profiles.get(who, (False, False)), chat)
            person["meat_proxy"] = lead or hands
            person["meat_proxy_chat"] = chat if who == viewer else None
            if lead or hands:
                person["meat_proxy_note"] = meat_proxy_note(lead, hands)


def packet(people: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The resume packet's `meat_proxy` of one chat: the humans for whom the mode holds there,
    `[{member_id, handle, meat_proxy_note}]` (§5.2), after `shown` ran on the participants."""
    return [
        {
            "member_id": p["member_id"],
            "handle": p["handle"],
            "meat_proxy_note": p["meat_proxy_note"],
        }
        for p in people
        if p.get("meat_proxy")
    ]
