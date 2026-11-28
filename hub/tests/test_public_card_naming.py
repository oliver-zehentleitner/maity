"""The cards whose page names a member, found once for both callers
(`public_cards.held_or_noted_by`, `public_cards.edited_by`): `public_cards.naming` for a change
of one member and `public_projects.pages_of_member` for a change of a person (§16.9).

`old_naming` and `old_pages` below are the two functions as they stood before the collector
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
from tests.statements import listening


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
        self.human = {
            name: factory.human(engine, name) for name in ("me", "other", "nobody", "owner")
        }
        self.project = {
            "public-one": self._project(engine, "public-one", "on"),
            "public-two": self._project(engine, "public-two", "on"),
            "public-three": self._project(engine, "public-three", "on"),
            "private": self._project(engine, "private", "off"),
        }
        self.agent = {
            "mine": self._agent("mine", self.human["me"]),
            "other": self._agent("other", self.human["other"]),
            "owned": self._agent("owned", self.human["owner"]),
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
            ("public-one", "owned", {"agent_id": self.agent["owned"]}),
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
                    author_kind="agent" if author.split("@", 1)[0] in self.agent else "human",
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
    and three public ones, two members of them removed; a non-member `owner` whose agent
    `owned` is an active member of a public project; and a card for each way a page can
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
    world.card("one: held by owned", "public-one", "owned@public-one")
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
    world.card("one: note by owned", "public-one")
    world.note("one: note by owned", "owned@public-one")
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
    # A private project's card, edited by a public-project membership, while the person is
    # also an active member of that private project: pages_of_member must not list it. The
    # editor's projects are the project ids of the frozen mine rows, which are only the
    # public ones.
    world.card("cross: private card edited by public membership", "private")
    world.note(
        "cross: private card edited by public membership",
        "other@private",
        edited_by="me@public-one",
    )
    return world


PRINCIPALS = ["me", "mine", "other", "other-agent", "nobody", "owner", "owned"]


def principal_ids(world: Cards) -> dict[str, str]:
    return {
        "me": world.human["me"],
        "mine": world.agent["mine"],
        "other": world.human["other"],
        "other-agent": world.agent["other"],
        "nobody": world.human["nobody"],
        "owner": world.human["owner"],
        "owned": world.agent["owned"],
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
    assert found[("public-one", "owner")] == []  # the person is not a member
    assert found[("public-three", "mine")] == []  # no membership there
    owned_cards = found[("public-one", "owned")]
    assert owned_cards
    assert cards.cards["one: held by owned"] in owned_cards


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
        for name in ("me", "other", "nobody", "owner"):
            got = public_projects.pages_of_member(conn, who[name])
            assert got == old_pages(conn, who[name]), name
            answers[name] = got
        assert public_projects.pages_of_member(conn, "hum-no-one") == old_pages(conn, "hum-no-one")
        assert public_projects.pages_of_member(conn, "hum-no-one") == []
    cards_of = {name: [i for kind, i in got if kind == "card"] for name, got in answers.items()}
    assert answers["nobody"] == []
    assert cards_of["me"] == sorted(cards_of["me"]) and len(cards_of["me"]) > 5
    ids = cards.cards
    # owner is not a member; pages come only from their active agent in a public project
    assert ("project", cards.project["public-one"]) in answers["owner"]
    assert ("project_views", cards.project["public-one"]) in answers["owner"]
    assert ids["one: held by owned"] in cards_of["owner"]
    assert ids["one: note by owned"] in cards_of["owner"]
    assert ids["one: held by mine"] not in cards_of["owner"]
    assert ids["one: held by other"] not in cards_of["owner"]
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
    assert ids["cross: private card edited by public membership"] not in cards_of["me"]


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


def test_the_statements_do_not_grow_with_the_cards_or_the_memberships(
    cards: Cards, migrated: Engine
) -> None:
    """Both callers send the same statements for the few cards and memberships of the world as
    for forty more: IN lists stay in one `chunks.CHUNK` at the default bound, and the edited
    notes are read once per chunk of projects, not of memberships. The exact counts of a
    one-chunk world are pinned so a silent rise is a failing test."""
    me = cards.human["me"]
    before = (
        _data_statements(migrated, lambda c: public_projects.pages_of_member(c, me)),
        _data_statements(
            migrated, lambda c: public_cards.naming(c, cards.project["public-one"], me)
        ),
    )
    assert before == (5, 4)
    for n in range(40):
        agent = cards._agent(f"extra{n}", me)
        cards.member[f"extra{n}@public-one"] = factory.membership(
            migrated, cards.project["public-one"], "member", agent_id=agent
        )
        cards.card(f"extra card {n}", "public-one", f"extra{n}@public-one")
        cards.note(f"extra card {n}", f"extra{n}@public-one", edited_by=f"extra{n}@public-one")
    after = (
        _data_statements(migrated, lambda c: public_projects.pages_of_member(c, me)),
        _data_statements(
            migrated, lambda c: public_cards.naming(c, cards.project["public-one"], me)
        ),
    )
    assert after == before
    with migrated.connect() as conn:
        listed = {i for kind, i in public_projects.pages_of_member(conn, me) if kind == "card"}
        assert {cards.cards[f"extra card {n}"] for n in range(40)} <= listed
        assert public_projects.pages_of_member(conn, me) == old_pages(conn, me)


def _former_memberships(world: Cards, project: str, human_id: str, count: int) -> None:
    """Extra removed rows for one human in one project, so `naming` sees more than one
    membership of the same principal. They are inserted already unset: a second active
    row would break the unique key."""
    from maity_hub.events import newest_seq

    trust, role = factory.trust_and_role("member")
    for _ in range(count):
        with world.engine.begin() as conn:
            conn.execute(
                insert(t.membership).values(
                    project_id=world.project[project],
                    human_id=human_id,
                    role=role,
                    role_base=role,
                    trust=trust,
                    areas=["/"],
                    capabilities=[],
                    joined_at=clock.now(),
                    joined_seq=newest_seq(conn, world.project[project]),
                    active=None,
                    removed_at=clock.now(),
                )
            )


def test_many_memberships_stay_under_the_engines_limit_on_bound_parameters(
    cards: Cards, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A person with 40 agent memberships cuts each IN list at `chunks.CHUNK`. The expected
    lists come from the former queries on one connection. A second, fresh engine to the same
    database (so no prepared-statement cache from that first run) lowers SQLite's
    bound-parameter limit to 16 *before* any statement and patches CHUNK to 2: the shared
    readers still match the former lists, and an unchunked IN of those ids (the former
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
    _former_memberships(cards, "public-one", me, 20)
    with migrated.connect() as conn:
        expected_pages = old_pages(conn, me)
        expected_naming = old_naming(conn, cards.project["public-one"], me)
    monkeypatch.setattr(chunks, "CHUNK", 2)
    # A new engine: setlimit on a pooled connection that already ran the 43-parameter
    # query does not apply (the statement cache keeps that plan).
    from sqlalchemy import create_engine

    fresh = create_engine(migrated.url)
    try:
        with fresh.connect() as conn:
            raw = conn.connection.dbapi_connection
            assert isinstance(raw, sqlite3.Connection)
            raw.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 16)
            assert public_projects.pages_of_member(conn, me) == expected_pages
            assert public_cards.naming(conn, cards.project["public-one"], me) == expected_naming
            with pytest.raises(Exception, match="too many SQL variables"):
                old_pages(conn, me)
    finally:
        fresh.dispose()
    assert len([i for kind, i in expected_pages if kind == "card"]) >= 40


def _data_sql(engine: Engine, call: Callable[[Connection], Any]) -> list[str]:
    """The SQL `call` sends, not the BEGIN/COMMIT `connect()` adds on SQLite."""
    seen: list[str] = []

    def collect(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        head = statement.lstrip().split(None, 1)[0].upper()
        if head not in {"BEGIN", "COMMIT", "ROLLBACK"}:
            seen.append(statement)

    with engine.connect() as conn, listening(engine, collect, async_engines=False):
        call(conn)
    return seen


def _data_statements(engine: Engine, call: Callable[[Connection], Any]) -> int:
    return len(_data_sql(engine, call))


def statement_kind(sql: str) -> str:
    """Which of the two callers' steps a statement is: enough to pin order and to fail a
    reordering or a re-filter of the editor's projects."""
    text = " ".join(sql.split()).upper()
    if "EDITED IS NOT NULL" in text:
        return "edited"
    if "CLAIM_HOLDER" in text:
        return "holder"
    if "CARD_NOTE" in text and "AUTHOR" in text:
        return "author"
    if "DISTINCT" in text and "PROJECT.ID" in text:
        return "projects"
    if "MEMBERSHIP.PROJECT_ID" in text and "JOIN PROJECT" in text:
        return "mine"
    if "FROM MEMBERSHIP" in text:
        return "ids"
    raise AssertionError(f"unclassified statement: {sql}")


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


def test_naming_and_pages_send_the_former_statements_in_the_former_order(
    cards: Cards, migrated: Engine
) -> None:
    """`naming` is one statement when empty (the membership read) and four when not: ids,
    holder, authors, edited notes. `pages_of_member` is five when mine is not empty
    (projects, mine, edited notes, holder, authors) and four when mine is empty (no edited
    read; the former query still sent one). The kinds are pinned in that order, and the
    edited read of a person's pages names no membership table: the projects are the frozen
    mine rows' project ids, not a second filter on active, owner or public_page."""
    nobody = cards.human["nobody"]
    me = cards.human["me"]
    empty = [
        statement_kind(sql)
        for sql in _data_sql(
            migrated,
            lambda c: public_cards.naming(c, cards.project["public-one"], nobody),
        )
    ]
    nonempty = [
        statement_kind(sql)
        for sql in _data_sql(
            migrated,
            lambda c: public_cards.naming(c, cards.project["public-one"], me),
        )
    ]
    pages = _data_sql(migrated, lambda c: public_projects.pages_of_member(c, me))
    pages_kinds = [statement_kind(sql) for sql in pages]
    empty_pages = [
        statement_kind(sql)
        for sql in _data_sql(migrated, lambda c: public_projects.pages_of_member(c, nobody))
    ]
    assert empty == ["ids"]
    assert nonempty == ["ids", "holder", "author", "edited"]
    assert pages_kinds == ["projects", "mine", "edited", "holder", "author"]
    assert empty_pages == ["projects", "mine", "holder", "author"]
    edited_sql = [sql for sql, kind in zip(pages, pages_kinds, strict=True) if kind == "edited"]
    assert edited_sql and all("membership" not in sql.lower() for sql in edited_sql)


def test_chunked_in_lists_keep_order_and_cost_one_statement_per_chunk(
    cards: Cards, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When an IN list is longer than `chunks.CHUNK`, each chunk is its own statement, in
    the same overall order. `naming` repeats holder and author per membership chunk, then
    reads the edited notes once. `pages_of_member` reads the edited notes once per project
    chunk, then holder and author once (a subquery, no bound list of memberships). On
    SQLite, a fresh connection with the bound-parameter limit lowered to 16 before any
    statement still answers what the former queries answered without the cap."""
    me = cards.human["me"]
    for n in range(8):
        name = f"chunk-pub-{n}"
        cards.project[name] = factory.project(migrated, name, public_page="on")
        cards.member[f"me@{name}"] = factory.membership(
            migrated, cards.project[name], "member", human_id=me
        )
        # created_by must be a membership of this project; me is one.
        cards.card(f"{name}: edited by me", name, f"me@{name}")
        cards.note(f"{name}: edited by me", f"me@{name}", edited_by=f"me@{name}")
    # Further (removed) memberships of the same human in public-one, so naming's IN
    # list of that principal crosses a chunk at CHUNK=2. Owned agents are a different
    # principal and do not appear in this naming() call.
    _former_memberships(cards, "public-one", me, 6)
    monkeypatch.setattr(chunks, "CHUNK", 2)
    with migrated.connect() as conn:
        expected_pages = old_pages(conn, me)
        expected_naming = old_naming(conn, cards.project["public-one"], me)
        assert public_projects.pages_of_member(conn, me) == expected_pages
        assert public_cards.naming(conn, cards.project["public-one"], me) == expected_naming

    naming_kinds = [
        statement_kind(sql)
        for sql in _data_sql(
            migrated,
            lambda c: public_cards.naming(c, cards.project["public-one"], me),
        )
    ]
    # 1 active + 6 removed = 7 memberships -> 4 holder chunks and 4 author chunks, then one
    # edited read.
    assert naming_kinds == ["ids"] + ["holder", "author"] * 4 + ["edited"]

    pages_sql = _data_sql(migrated, lambda c: public_projects.pages_of_member(c, me))
    pages_kinds = [statement_kind(sql) for sql in pages_sql]
    # public-one, public-two, and 8 new public projects (public-three is inactive): 10
    # project ids -> 5 edited chunks, then holder and author once.
    assert pages_kinds == ["projects", "mine"] + ["edited"] * 5 + ["holder", "author"]
    assert all(
        "membership" not in sql.lower()
        for sql, kind in zip(pages_sql, pages_kinds, strict=True)
        if kind == "edited"
    )

    if migrated.dialect.name != "sqlite":
        return
    from sqlalchemy import create_engine

    # The list of project ids is short (ten), so the cap is a proof that the per-chunk
    # statements still run, not that an unchunked project IN would fail (that is this
    # file's membership-list test, with many more ids).
    fresh = create_engine(migrated.url)
    try:
        with fresh.connect() as conn:
            raw = conn.connection.dbapi_connection
            assert isinstance(raw, sqlite3.Connection)
            raw.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 16)
            assert public_projects.pages_of_member(conn, me) == expected_pages
            assert public_cards.naming(conn, cards.project["public-one"], me) == expected_naming
    finally:
        fresh.dispose()
