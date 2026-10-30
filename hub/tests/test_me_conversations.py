"""`GET /me/conversations` (docs/api.md §9.3, "Across projects"): the conversations of every
project the human is an active member of, as one list."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, update

from maity_hub import clock, conversation_list
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.statements import count_statements

ME = "/me/conversations"


def base(slug: str) -> str:
    return f"/projects/maintainer/{slug}/conversations"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def project_id(engine: Engine, slug: str) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == slug)
        ).scalar_one()
    return found


def human_in(
    make_client: ClientFactory, engine: Engine, handle: str, slugs: tuple[str, ...], role: str
) -> flow.Human:
    human = flow.human(make_client, engine, handle)
    for slug in slugs:
        factory.membership(engine, project_id(engine, slug), role, human_id=human.id)
    return human


def talk(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> dict[str, Any]:
    """Three projects, an archived one among them, and one the owner left; direct chats and
    rooms with mentions; one agent in two projects (two chats of one id); an owner who
    reads along in a room."""
    for slug in ("alpha", "beta", "gamma", "gone"):
        flow.project(owner, slug)
    guest = human_in(make_client, migrated, "guest", ("alpha", "beta", "gamma", "gone"), "member")
    watcher = human_in(make_client, migrated, "watcher", ("alpha", "beta", "gamma"), "admin")
    a1 = flow.agent(make_client, owner, slug="alpha")
    a2 = flow.agent(make_client, owner, slug="beta")
    theirs = flow.agent(make_client, watcher, slug="alpha")
    factory.membership(migrated, project_id(migrated, "beta"), "member", agent_id=a1.id)
    for agent, slug in ((a1, "alpha"), (a2, "beta")):
        agent.post(f"{base(slug)}/{agent.id}/messages", {"body": f"hello from {slug}"})
    owner.post(f"{base('beta')}/{a1.id}/messages", {"body": "the same agent in beta"})
    for slug in ("alpha", "beta", "gamma"):
        room = owner.post(base(slug), {"title": f"room {slug}", "participants": [guest.id]}).json()
        guest.post(f"{base(slug)}/{room['id']}/messages", {"body": "@maintainer one"})
        guest.post(f"{base(slug)}/{room['id']}/messages", {"body": "two"})
    watched = owner.post(base("alpha"), {"title": "watched", "participants": [theirs.id]}).json()
    owner.post(f"{base('alpha')}/{watched['id']}/messages", {"body": "for the agent"})
    owner.post(base("gone"), {"title": "gone", "participants": [guest.id]})
    gone = project_id(migrated, "gone")
    with migrated.begin() as conn:
        conn.execute(update(t.project).where(t.project.c.slug == "gamma").values(state="archived"))
        conn.execute(
            update(t.membership)
            .where(
                t.membership.c.project_id == gone,
                t.membership.c.human_id == owner.id,
            )
            .values(active=None, removed_at=clock.now())
        )
    return {"guest": guest, "watcher": watcher, "a1": a1, "a2": a2}


def activity(engine: Engine, item: dict[str, Any]) -> Any:
    """What the list orders by: the newest message, else the chat's own start."""
    slug = item["project"]["slug"]
    with engine.connect() as conn:
        pid = project_id(engine, slug)
        last = conn.execute(
            select(func.max(t.event.c.at)).where(
                t.event.c.project_id == pid,
                t.event.c.kind == "message",
                t.event.c.conversation_id == item["id"],
            )
        ).scalar()
        if last is not None:
            return last
        if item["kind"] == "group":
            return conn.execute(
                select(t.conversation.c.created_at).where(t.conversation.c.id == item["id"])
            ).scalar_one()
        return conn.execute(
            select(t.membership.c.joined_at).where(
                t.membership.c.project_id == pid, t.membership.c.agent_id == item["id"]
            )
        ).scalar_one()


def key(item: dict[str, Any]) -> tuple[str, str]:
    return (item["project"]["full_name"], item["id"])


def pages(who: flow.Human, **query: Any) -> list[dict[str, Any]]:
    out = []
    cursor = None
    for _ in range(60):
        got = who.get(ME, params={**query, **({"cursor": cursor} if cursor else {})})
        assert got.status_code == 200, got.text
        out.append(got.json())
        cursor = out[-1]["next_cursor"]
        if cursor is None:
            return out
    raise AssertionError("a list that does not end")


def test_the_list_is_the_lists_of_every_project_merged(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    talk(owner, make_client, migrated)
    for observed in (False, True):
        one = [p for page in pages(owner, observed=observed, limit=200) for p in page["items"]]
        expected = []
        for slug in ("alpha", "beta", "gamma"):
            listed = owner.get(base(slug), params={"observed": observed, "limit": 200}).json()
            for item in listed["items"]:
                expected.append(
                    {
                        **item,
                        "project": {
                            "owner": "maintainer",
                            "slug": slug,
                            "full_name": f"maintainer/{slug}",
                            "name": slug.title(),
                        },
                    }
                )
        assert sorted(one, key=key) == sorted(expected, key=key)
        assert {i["project"]["slug"] for i in one} == {"alpha", "beta", "gamma"}  # not "gone"
        # newest first; where the moment is equal, by project name, then id
        want = sorted(one, key=lambda i: (i["project"]["full_name"], i["id"]))
        want.sort(key=lambda i: activity(migrated, i), reverse=True)
        assert [key(i) for i in one] == [key(i) for i in want]


def test_one_agent_in_two_projects_has_two_chats_of_one_id(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    people = talk(owner, make_client, migrated)
    mine = [p for page in pages(owner, limit=200) for p in page["items"]]
    same = [i for i in mine if i["id"] == people["a1"].id]
    assert sorted(i["project"]["slug"] for i in same) == ["alpha", "beta"]
    assert {i["last_message"]["body"] for i in same} == {
        "hello from alpha",
        "the same agent in beta",
    }
    with migrated.begin() as conn:  # the same moment in both: the project name decides
        moment = conn.execute(select(func.max(t.event.c.at))).scalar_one()
        conn.execute(
            update(t.event).where(t.event.c.conversation_id == people["a1"].id).values(at=moment)
        )
    after = [p for page in pages(owner, limit=200) for p in page["items"]]
    tied = [i["project"]["full_name"] for i in after if i["id"] == people["a1"].id]
    assert tied == sorted(tied)


def test_paging_never_skips_or_repeats_and_totals_are_the_same_on_every_page(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    talk(owner, make_client, migrated)
    whole = pages(owner, limit=200)
    assert len(whole) == 1 and whole[0]["next_cursor"] is None
    order = [(i["project"]["full_name"], i["id"]) for i in whole[0]["items"]]
    assert len(order) >= 7
    for limit in (1, 2, 3):
        got = pages(owner, limit=limit)
        assert [(i["project"]["full_name"], i["id"]) for p in got for i in p["items"]] == order
        assert all(p["totals"] == whole[0]["totals"] for p in got)
    counted = [i for i in whole[0]["items"] if i["unread"] is not None]
    assert whole[0]["totals"] == {
        "unread": sum(i["unread"] for i in counted),
        "mentions_unread": sum(i["mentions_unread"] for i in counted),
    }
    assert whole[0]["totals"]["unread"] >= 6 and whole[0]["totals"]["mentions_unread"] == 3


def test_an_observers_items_count_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    people = talk(owner, make_client, migrated)
    watcher = people["watcher"]
    got = pages(watcher, observed=True, limit=200)[0]
    [watched] = [i for i in got["items"] if i["title"] == "watched"]
    assert (watched["access"], watched["unread"], watched["mentions_unread"]) == (
        "observer",
        None,
        None,
    )
    mine = [i for i in got["items"] if i["unread"] is not None]
    assert got["totals"]["unread"] == sum(i["unread"] for i in mine)
    plain = pages(watcher, limit=200)[0]
    assert all(i["title"] != "watched" for i in plain["items"])


def test_only_a_human_reads_it_and_an_empty_list_counts_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "alpha")
    agent = flow.agent(make_client, owner, slug="alpha")
    refused = agent.get(ME)
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"reason": "humans_only"}
    nobody = flow.human(make_client, migrated, "nobody")
    assert nobody.get(ME).json() == {
        "items": [],
        "next_cursor": None,
        "totals": {"unread": 0, "mentions_unread": 0},
    }


def test_the_cost_does_not_grow_with_the_projects(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "alpha")
    guest = human_in(make_client, migrated, "guest", ("alpha",), "member")

    def add(slug: str) -> None:
        flow.project(owner, slug)
        agent = factory.agent(migrated, project_id(migrated, slug), owner.id)
        factory.membership(migrated, project_id(migrated, slug), "member", human_id=guest.id)
        room = owner.post(base(slug), {"title": slug, "participants": [guest.id]}).json()
        guest.post(f"{base(slug)}/{room['id']}/messages", {"body": "@maintainer hi"})
        owner.post(f"{base(slug)}/{agent.agent_id}/messages", {"body": "hello"})

    for slug in ("beta", "gamma"):
        add(slug)

    def build() -> int:
        """The list's own statements: the sign-in renews a lease per project and is not it."""
        with migrated.connect() as conn:
            caller = SimpleNamespace(
                kind="human", human_id=owner.id, agent_id=None, session_id=None
            )
            mines = conversation_list.memberships(conn, owner.id)
            owned = conversation_list.owned_agents(conn, mines, caller)
            return len(
                conversation_list.direct_entries(conn, mines, caller, owned)
                + conversation_list.group_entries(conn, mines, True)
            )

    few = count_statements(migrated, build)
    for slug in ("delta", "epsilon", "zeta", "eta"):
        add(slug)
    many = count_statements(migrated, build)
    assert many == few, (few, many)
    assert len(owner.get(ME).json()["items"]) == 12


def test_the_bell_counts_what_the_list_totals_rooms_included(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    people = talk(owner, make_client, migrated)
    for who in (owner, people["guest"]):
        listed = pages(who, observed=True, limit=200)[0]
        bell = who.get("/me/notifications").json()["counts"]
        assert bell["chat"] == listed["totals"]["unread"], (bell, listed["totals"])
    owned = pages(owner, observed=True, limit=200)[0]["totals"]["unread"]
    assert owned >= 6  # the owner's rooms count, not only the direct chats
    # an observer's reading along counts nothing, on the bell either
    watcher = people["watcher"]
    assert (
        watcher.get("/me/notifications").json()["counts"]["chat"]
        == pages(watcher, observed=True, limit=200)[0]["totals"]["unread"]
    )
    # a read mark lowers both by the same amount
    items = pages(owner, limit=200)[0]["items"]
    room = next(i for i in items if i["kind"] == "group" and i["unread"])
    slug = room["project"]["slug"]
    assert owner.get(f"{base(slug)}/{room['id']}/messages").status_code == 200  # reading marks
    after = owner.get("/me/notifications").json()["counts"]["chat"]
    assert after < owned
    assert after == pages(owner, observed=True, limit=200)[0]["totals"]["unread"]
