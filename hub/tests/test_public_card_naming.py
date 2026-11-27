"""The cards whose page names a member, found once for both callers
(`public_cards.held_or_noted_by`, `public_cards.edited_by`): `public_cards.naming` for a change
of one member and `public_projects.pages_of_member` for a change of a person (§16.9).

`OLD_NAMING` and `OLD_PAGES` below are the two functions as they stood before the collector
was shared, each with its own copy of the queries. The tests hold the shared form to them on
one world of projects, memberships and cards, row for row and in the same order, so that a
change of what the collector finds, or of which project's cards it looks at, fails here."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, insert, or_, select, update

from maity_hub import chunks, clock, public_cards, public_projects
from maity_hub import tables as t
from maity_hub.ids import new_id
from tests import factory
from tests.statements import count_statements


def old_naming(conn: Connection, project_id: str, principal_id: str) -> list[str]:
    c, n, m = t.card.c, t.card_note.c, t.membership.c
    held = select(m.id).where(
        m.project_id == project_id, or_(m.agent_id == principal_id, m.human_id == principal_id)
    )
    ids = set(conn.execute(held).scalars())
    if not ids:
        return []
    found = set(
        conn.execute(
            select(c.id).where(c.project_id == project_id, c.claim_holder.in_(ids))
        ).scalars()
    )
    found |= set(
        conn.execute(
            select(n.card_id)
            .join(t.card, c.id == n.card_id)
            .where(c.project_id == project_id, n.author.in_(ids))
        ).scalars()
    )
    edited = conn.execute(
        select(n.card_id, n.edited)
        .join(t.card, c.id == n.card_id)
        .where(c.project_id == project_id, n.edited.is_not(None))
    )
    found |= {row.card_id for row in edited if row.edited["by"] in ids}
    return sorted(found)


def old_pages(conn: Connection, human_id: str) -> list[tuple[str, str]]:
    m = t.membership.c
    agents = select(t.agent_profile.c.id).where(t.agent_profile.c.owner_id == human_id)
    theirs = (
        m.active.is_(True),
        (m.human_id == human_id) | m.agent_id.in_(agents),
    )
    ids = conn.execute(
        select(t.project.c.id)
        .join(t.membership, m.project_id == t.project.c.id)
        .where(t.project.c.public_page == "on", *theirs)
        .distinct()
        .order_by(t.project.c.id)
    ).scalars()
    held = (
        select(t.card.c.id)
        .join(t.membership, m.id == t.card.c.claim_holder)
        .join(t.project, t.project.c.id == t.card.c.project_id)
        .where(t.project.c.public_page == "on", *theirs)
    )
    noted = (
        select(t.card_note.c.card_id)
        .join(t.membership, m.id == t.card_note.c.author)
        .join(t.card, t.card.c.id == t.card_note.c.card_id)
        .join(t.project, t.project.c.id == t.card.c.project_id)
        .where(t.project.c.public_page == "on", *theirs)
    )
    mine = set(
        conn.execute(
            select(m.id)
            .join(t.project, t.project.c.id == m.project_id)
            .where(t.project.c.public_page == "on", *theirs)
        ).scalars()
    )
    edited = conn.execute(
        select(t.card_note.c.card_id, t.card_note.c.edited)
        .join(t.card, t.card.c.id == t.card_note.c.card_id)
        .where(
            t.card_note.c.edited.is_not(None),
            t.card.c.project_id.in_(select(m.project_id).where(m.id.in_(mine))),
        )
    )
    by_them = {row.card_id for row in edited if row.edited["by"] in mine}
    cards = sorted(set(conn.execute(held).scalars()) | set(conn.execute(noted).scalars()) | by_them)
    return [(kind, project_id) for project_id in ids for kind in ("project", "project_views")] + [
        ("card", card) for card in cards
    ]


class Cards:
    """Projects, members and cards put into the tables directly, with a way to name each."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.human = {name: factory.human(engine, name) for name in ("me", "other", "nobody")}
        self.project = {
            "public-one": self._project(engine, "public-one", "on"),
            "public-two": self._project(engine, "public-two", "on"),
            "public-three": self._project(engine, "public-three", "on"),
            "private": self._project(engine, "private", "off"),
        }
        self.agent = {
            "mine": self._agent("mine", self.human["me"]),
            "other": self._agent("other", self.human["other"]),
        }
        self.member: dict[str, int] = {}
        for project, who, principal in [
            ("public-one", "me", {"human_id": self.human["me"]}),
            ("public-two", "me", {"human_id": self.human["me"]}),
            ("private", "me", {"human_id": self.human["me"]}),
            ("public-three", "me", {"human_id": self.human["me"]}),
            ("public-one", "mine", {"agent_id": self.agent["mine"]}),
            ("private", "mine", {"agent_id": self.agent["mine"]}),
            ("public-two", "mine", {"agent_id": self.agent["mine"]}),
            ("public-one", "other", {"human_id": self.human["other"]}),
            ("public-two", "other", {"human_id": self.human["other"]}),
            ("private", "other", {"human_id": self.human["other"]}),
            ("public-one", "other-agent", {"agent_id": self.agent["other"]}),
        ]:
            role = "member"
            self.member[f"{who}@{project}"] = factory.membership(
                engine, self.project[project], role, **principal
            )
        # Removed from `public-two` (the agent) and `public-three` (the person): their rows stay.
        with engine.begin() as conn:
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id.in_([self.member["mine@public-two"]]))
                .values(active=None, removed_at=clock.now())
            )
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id == self.member["me@public-three"])
                .values(active=None, removed_at=clock.now())
            )
        self.cards: dict[str, str] = {}

    @staticmethod
    def _project(engine: Engine, slug: str, page: str) -> str:
        return factory.project(engine, slug, public_page=page)

    def _agent(self, name: str, owner: str) -> str:
        agent_id = new_id("agent")
        with self.engine.begin() as conn:
            conn.execute(
                insert(t.agent_profile).values(
                    id=agent_id,
                    owner_id=owner,
                    handle=f"{name}-{agent_id}",
                    display_name=name,
                    created_at=clock.now(),
                )
            )
        return agent_id

    def card(self, label: str, project: str, holder: str | None = None) -> str:
        """A card of `project`, held by the membership `holder` names (`member@project`)."""
        card_id = factory.card(
            self.engine,
            self.project[project],
            next(i for key, i in self.member.items() if key.endswith(f"@{project}")),
            claim_holder=self.member[holder] if holder else None,
        )
        self.cards[label] = card_id
        return card_id

    def note(self, label: str, author: str, edited_by: str | None = None) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                insert(t.card_note).values(
                    id=new_id("note"),
                    card_id=self.cards[label],
                    author=self.member[author],
                    author_kind="agent" if author.startswith(("mine", "other-agent")) else "human",
                    body="x",
                    state="open",
                    created_at=clock.now(),
                    redacted=False,
                    edited=(
                        {"by": self.member[edited_by], "at": "2026-11-27T10:00:00Z", "reason": "x"}
                        if edited_by
                        else None
                    ),
                )
            )


@pytest.fixture
def cards(migrated: Engine) -> Cards:
    """One world: `me` and their agent `mine`, `other` and their agent, in a private project
    and three public ones, two members of them removed; and a card for each way a page can
    name a member, with the ones that do not."""
    world = Cards(migrated)
    for project in ("public-one", "public-two", "public-three", "private"):
        world.card(f"{project}: nobody", project)
        world.card(
            f"{project}: holder me",
            project,
            f"me@{project}" if project != "public-three" else "me@public-three",
        )
    # holders: a person, their agent, a removed agent, someone else, another's agent
    world.card("one: held by mine", "public-one", "mine@public-one")
    world.card("one: held by other", "public-one", "other@public-one")
    world.card("one: held by other agent", "public-one", "other-agent@public-one")
    world.card("two: held by removed mine", "public-two", "mine@public-two")
    world.card("private: held by mine", "private", "mine@private")
    # authors and latest editors
    world.card("one: note by me", "public-one")
    world.note("one: note by me", "me@public-one")
    world.card("one: note by mine", "public-one")
    world.note("one: note by mine", "mine@public-one")
    world.card("one: note by other, edited by me", "public-one")
    world.note("one: note by other, edited by me", "other@public-one", edited_by="me@public-one")
    world.card("one: note by me, edited by other", "public-one")
    world.note("one: note by me, edited by other", "me@public-one", edited_by="other@public-one")
    world.card("one: note by other, edited by mine", "public-one")
    world.note(
        "one: note by other, edited by mine", "other@public-one", edited_by="mine@public-one"
    )
    world.card("two: edited by removed mine", "public-two")
    world.note("two: edited by removed mine", "other@public-two", edited_by="mine@public-two")
    world.card("two: edited by me", "public-two")
    world.note("two: edited by me", "other@public-two", edited_by="me@public-two")
    world.card("private: edited by me", "private")
    world.note("private: edited by me", "other@private", edited_by="me@private")
    world.card("private: note by me", "private")
    world.note("private: note by me", "me@private")
    world.card("three: edited by removed me", "public-three")
    world.note("three: edited by removed me", "other@public-two", edited_by="me@public-three")
    # a name by every way on one card, and the same card named twice by one way
    world.card("one: every way", "public-one", "me@public-one")
    world.note("one: every way", "mine@public-one", edited_by="me@public-one")
    world.note("one: every way", "me@public-one", edited_by="mine@public-one")
    world.card("one: edited notes of no one of theirs", "public-one")
    world.note(
        "one: edited notes of no one of theirs",
        "other@public-one",
        edited_by="other-agent@public-one",
    )
    # A membership of another project on a card (the tables do not forbid it): held in a
    # public project by a membership in the private one, and the reverse.
    world.card("cross: public card held by private membership", "public-one", "me@private")
    world.card("cross: private card held by public membership", "private", "me@public-one")
    world.card("cross: public card noted by private membership", "public-two")
    world.note("cross: public card noted by private membership", "mine@private")
    world.card("cross: public card edited by private membership", "public-two")
    world.note(
        "cross: public card edited by private membership",
        "other@public-two",
        edited_by="me@private",
    )
    world.card("cross: card of a project they are not in", "public-three")
    world.note(
        "cross: card of a project they are not in", "other@public-two", edited_by="mine@public-one"
    )
    return world


PRINCIPALS = ["me", "mine", "other", "other-agent", "nobody"]


def principal_ids(world: Cards) -> dict[str, str]:
    return {
        "me": world.human["me"],
        "mine": world.agent["mine"],
        "other": world.human["other"],
        "other-agent": world.agent["other"],
        "nobody": world.human["nobody"],
    }


def test_naming_finds_the_cards_the_former_query_found(cards: Cards, migrated: Engine) -> None:
    """Every principal in every project, a project with no membership of theirs, removed and
    active memberships, public and private projects: the same list, in the same order."""
    who = principal_ids(cards)
    found = {}
    with migrated.connect() as conn:
        for name, project in cards.project.items():
            for principal, principal_id in who.items():
                got = public_cards.naming(conn, project, principal_id)
                assert got == old_naming(conn, project, principal_id), (name, principal)
                assert got == sorted(set(got))
                found[(name, principal)] = got
    # the world is not one in which every answer is empty
    assert sum(1 for got in found.values() if got) >= 10
    assert found[("public-two", "mine")] != [], "a removed membership still names its cards"
    assert found[("public-one", "nobody")] == []
    assert found[("public-three", "mine")] == []  # no membership there


def test_naming_covers_holder_author_and_latest_editor_once_each(
    cards: Cards, migrated: Engine
) -> None:
    with migrated.connect() as conn:
        got = public_cards.naming(conn, cards.project["public-one"], cards.human["me"])
    expected = {
        cards.cards[label]
        for label in (
            "public-one: holder me",
            "one: note by me",
            "one: note by other, edited by me",
            "one: note by me, edited by other",
            "one: every way",
        )
    }
    assert set(got) == expected
    assert len(got) == len(expected), "a card named in several ways is one card"


def test_the_pages_of_a_person_are_what_the_former_query_found(
    cards: Cards, migrated: Engine
) -> None:
    """The person, the one with only an agent's projects, a person with no membership, and
    an id that is no one's: the project pages, then the card pages, in the former order."""
    who = principal_ids(cards)
    answers = {}
    with migrated.connect() as conn:
        for name in ("me", "other", "nobody"):
            got = public_projects.pages_of_member(conn, who[name])
            assert got == old_pages(conn, who[name]), name
            answers[name] = got
        assert public_projects.pages_of_member(conn, "hum-no-one") == old_pages(conn, "hum-no-one")
        assert public_projects.pages_of_member(conn, "hum-no-one") == []
    cards_of = {name: [i for kind, i in got if kind == "card"] for name, got in answers.items()}
    assert answers["nobody"] == []
    assert cards_of["me"] == sorted(cards_of["me"]) and len(cards_of["me"]) > 5
    ids = cards.cards
    # a removed agent's and a private project's cards are named by the former rules only
    assert ids["two: held by removed mine"] not in cards_of["me"]
    assert ids["private: held by mine"] not in cards_of["me"]
    assert ids["private: holder me"] not in cards_of["me"]
    assert ids["one: held by mine"] in cards_of["me"]
    # the same rules, not a single selection, for the cases the tables do not forbid: a
    # holder or an author counts in any project of theirs for a card of a public project, an
    # editor only a membership in a public project, for a card of one of its projects
    assert ids["cross: public card held by private membership"] in cards_of["me"]
    assert ids["cross: public card noted by private membership"] in cards_of["me"]
    assert ids["cross: public card edited by private membership"] not in cards_of["me"]
    assert ids["cross: card of a project they are not in"] not in cards_of["me"]
    assert ids["two: edited by removed mine"] not in cards_of["me"]
    assert ids["two: edited by me"] in cards_of["me"]


def test_both_callers_ignore_the_cards_of_a_project_with_no_page_as_before(
    cards: Cards, migrated: Engine
) -> None:
    """`pages_of_member` lists no card of a private project, `naming` (asked for one project
    by a caller that decided to ask) does: each as it did."""
    with migrated.connect() as conn:
        pages = public_projects.pages_of_member(conn, cards.human["me"])
        private = [
            cards.cards[label]
            for label in ("private: holder me", "private: note by me", "private: edited by me")
        ]
        listed = {i for kind, i in pages if kind == "card"}
        assert not listed & set(private)
        assert set(private) <= set(
            public_cards.naming(conn, cards.project["private"], cards.human["me"])
        )


def _statements(engine: Engine, call: Callable[[Connection], Any]) -> int:
    with engine.connect() as conn:
        return count_statements(engine, lambda: call(conn), async_engines=False)


def test_the_statements_do_not_grow_with_the_cards_or_the_memberships(
    cards: Cards, migrated: Engine
) -> None:
    """Both callers send the same statements for the few cards and memberships of the world as
    for ten times as many: the memberships are a subquery and the edited notes are read once."""
    me = cards.human["me"]
    before = (
        _statements(migrated, lambda c: public_projects.pages_of_member(c, me)),
        _statements(migrated, lambda c: public_cards.naming(c, cards.project["public-one"], me)),
    )
    for n in range(40):
        agent = cards._agent(f"extra{n}", me)
        cards.member[f"extra{n}@public-one"] = factory.membership(
            migrated, cards.project["public-one"], "member", agent_id=agent
        )
        cards.card(f"extra card {n}", "public-one", f"extra{n}@public-one")
        cards.note(f"extra card {n}", f"extra{n}@public-one", edited_by=f"extra{n}@public-one")
    after = (
        _statements(migrated, lambda c: public_projects.pages_of_member(c, me)),
        _statements(migrated, lambda c: public_cards.naming(c, cards.project["public-one"], me)),
    )
    assert after == before
    with migrated.connect() as conn:
        listed = {i for kind, i in public_projects.pages_of_member(conn, me) if kind == "card"}
        assert {cards.cards[f"extra card {n}"] for n in range(40)} <= listed
        assert public_projects.pages_of_member(conn, me) == old_pages(conn, me)


def test_many_memberships_stay_under_the_engines_limit_on_bound_parameters(
    cards: Cards, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A person with 40 agent memberships has no IN list of ids to cut: with SQLite's limit on
    bound parameters lowered to 16 and `chunks.CHUNK` to 2 the statements still run and answer
    what they answer without the limit, where a list of the 40 ids (the former
    `pages_of_member`) fails with "too many SQL variables"."""
    if migrated.dialect.name != "sqlite":
        pytest.skip("the bound-parameter limit is lowered on a SQLite connection")
    me = cards.human["me"]
    for n in range(40):
        agent = cards._agent(f"extra{n}", me)
        cards.member[f"extra{n}@public-one"] = factory.membership(
            migrated, cards.project["public-one"], "member", agent_id=agent
        )
        cards.card(f"extra card {n}", "public-one", f"extra{n}@public-one")
        cards.note(f"extra card {n}", f"extra{n}@public-one", edited_by=f"extra{n}@public-one")
    with migrated.connect() as conn:
        whole = public_projects.pages_of_member(conn, me)
        whole_naming = public_cards.naming(conn, cards.project["public-one"], me)
        raw = conn.connection.dbapi_connection
        assert isinstance(raw, sqlite3.Connection)
        was = raw.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
        monkeypatch.setattr(chunks, "CHUNK", 2)
        raw.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 16)
        try:
            assert public_projects.pages_of_member(conn, me) == whole
            assert public_cards.naming(conn, cards.project["public-one"], me) == whole_naming
            with pytest.raises(Exception, match="too many SQL variables"):
                old_pages(conn, me)
        finally:
            raw.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, was)
    assert len([i for kind, i in whole if kind == "card"]) >= 40


def test_a_membership_selection_that_names_none_reads_no_notes(
    cards: Cards, migrated: Engine
) -> None:
    """An empty set: no edited note is read for a principal with no membership, and no card is
    found."""
    edited_reads = []
    from sqlalchemy import event

    def seen(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        if "card_note.edited IS NOT NULL" in statement:
            edited_reads.append(statement)

    with migrated.connect() as conn:
        event.listen(migrated, "before_cursor_execute", seen)
        try:
            assert (
                public_cards.naming(conn, cards.project["public-one"], cards.human["nobody"]) == []
            )
            assert edited_reads == []
            public_cards.naming(conn, cards.project["public-one"], cards.human["me"])
            assert len(edited_reads) == 1
        finally:
            event.remove(migrated, "before_cursor_execute", seen)
