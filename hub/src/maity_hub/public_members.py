"""Who a public page names (docs/api.md §16.9): a project's members as `Person` values.

`members` is the one read: every active member, an isolated agent not among them; a name only
for those the page shows (no profile hold on an agent, an account that is served). `team` on
the project page is those it shows, split by human, in handle order. Hidden members stay in
`members` unnamed; `team` drops them. `shown_data`, `holder_data`, `pictured` and `person_data`
name them on the pages; `shown_pictures` is the picture each one's own page shows.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import moderation, public_people
from maity_hub import tables as t


class Person:
    """A member as the views show them: `handle` is None for one that is not shown."""

    def __init__(
        self,
        row: Any,
        handle: str | None,
        name: str | None,
        human: bool,
        address: str | None = None,
        presence_named: bool = True,
        profile_on: bool = True,
    ) -> None:
        self.address = address  # the member's own page: a person's, or the agent's under its owner
        self.id = row.id
        self.role = row.role
        self.trust = row.trust
        self.reports_to = row.reports_to
        self.handle = handle
        self.name = name
        self.human = human
        # Named and counted as online on a public page: off by a person's `public_presence` (§16.9).
        self.presence_named = presence_named
        # The person or the agent, and whether their own page shows their picture (§16.9): a
        # person's `public_profile`; an agent's page always shows one.
        self.principal: str = row.human_id or row.agent_id
        self.profile_on = profile_on

    @property
    def shown(self) -> bool:
        return self.handle is not None


def members(
    conn: Connection, project_id: str, only: Collection[int] | None = None
) -> dict[int, Person]:
    """Every active member by membership id, an isolated agent not among them (§6.28); the names
    only of those the page shows (no profile hold on an agent, §16.8). With `only`, those
    memberships, for a page that names a few members (a card's holder and note authors)."""
    from maity_hub import public_agents

    m = t.membership.c
    found: dict[int, Person] = {}
    query = select(t.membership).where(
        m.project_id == project_id, m.active.is_(True), m.isolated_since.is_(None)
    )
    if only is not None:
        query = query.where(m.id.in_(list(only)))
    rows = conn.execute(query.order_by(m.id)).all()
    humans = {
        h.id: h
        for h in conn.execute(
            select(t.human).where(t.human.c.id.in_({r.human_id for r in rows if r.human_id}))
        )
    }
    agents = {
        a.id: a
        for a in conn.execute(
            select(t.agent_profile).where(
                t.agent_profile.c.id.in_({r.agent_id for r in rows if r.agent_id})
            )
        )
    }
    owners = {
        h.id: h
        for h in conn.execute(
            select(t.human).where(t.human.c.id.in_({a.owner_id for a in agents.values()}))
        )
    }
    held = moderation.holds_of(conn, "profile", [r.agent_id for r in rows if r.agent_id])
    for row in rows:
        if row.human_id:
            human = humans[row.human_id]
            ok = public_people.served(conn, human)
            found[row.id] = Person(
                row,
                human.handle if ok else None,
                human.display_name,
                True,
                f"/{human.handle}" if ok else None,
                bool(human.public_presence),
                bool(human.public_profile),
            )
        else:
            agent = agents[row.agent_id]
            ok = agent.id not in held and public_people.served(conn, owners[agent.owner_id])
            owner = owners[agent.owner_id]
            found[row.id] = Person(
                row,
                agent.handle if ok else None,
                agent.display_name,
                False,
                public_agents.path_of(owner.handle, agent.handle) if ok else None,
            )
    return found


def person_data(name: str, handle: str, page: str) -> dict[str, str]:
    """Someone shown, as the visitors' route names them (§16.9)."""
    return {"name": name, "handle": handle, "page": page}


def shown_data(person: Person) -> dict[str, str] | None:
    """The member as the page names them (`person_data`), None for one that is not shown."""
    if not person.shown:
        return None
    return person_data(person.name or "", person.handle or "", person.address or "")


def holder_data(person: Person | None, gone_agent: bool) -> dict[str, str] | str:
    """A card's holder, note author or editor as the page names them: the member shown, else
    the word `member` or `agent` (a hold, an account not served, an agent gone from the project)."""
    if person is None:
        return "agent" if gone_agent else "member"
    return shown_data(person) or ("member" if person.human else "agent")


def shown_pictures(conn: Connection, who: dict[int, Person]) -> dict[str, str | None]:
    """The picture of each member the views name, as their own page shows it (§16.9), by human
    or agent id: the project page's rule (`public_projects.member_pictures`). One read for the
    Team and the Organisation tab."""
    from maity_hub.public_projects import member_pictures

    shown = [p for p in who.values() if p.shown]
    return member_pictures(
        conn,
        [(p.principal, p.profile_on) for p in shown if p.human],
        [p.principal for p in shown if not p.human],
    )


def pictured(person: Person, pictures: dict[str, str | None]) -> dict[str, Any] | None:
    """Someone shown with the picture their own page shows; None for one the page does not name."""
    named = shown_data(person)
    return None if named is None else {**named, "picture": pictures.get(person.principal)}
