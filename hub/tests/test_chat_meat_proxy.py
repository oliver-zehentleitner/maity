"""docs/api.md §9.3, "Meat proxy per chat": a human's own choice of the meat-proxy mode for one
conversation, shown in the participants' entries and in the resume packet; it emits nothing."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, func, select

from maity_hub import chat_meat_proxy
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_group_chats import BASE, create, other_human

ME = "/me"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


@pytest.fixture
def agent(owner: flow.Human, make_client: ClientFactory) -> flow.Agent:
    return flow.agent(make_client, owner)


def put(who: Any, chat: str, value: Any) -> Any:
    return who.client.put(
        f"/api/v1{BASE}/{chat}/meat-proxy",
        json={"meat_proxy": value},
        headers={"X-CSRF-Token": who.csrf},
    )


def entry(view: dict[str, Any], member_id: str) -> dict[str, Any]:
    [found] = [p for p in view["participants"] if p["member_id"] == member_id]
    return dict(found)


def chat_of(owner: flow.Human, agent: flow.Agent, guest: flow.Human) -> str:
    created = create(owner, agent.id, guest.id)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def events(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(t.event)).scalar_one())


def test_the_choice_is_shown_in_the_chat_and_only_the_human_itself_reads_it(
    owner: flow.Human, agent: flow.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    guest = other_human(make_client, migrated, "guest")
    chat = chat_of(owner, agent, guest)
    before = entry(owner.get(f"{BASE}/{chat}").json(), owner.id)
    assert (before["meat_proxy"], before["meat_proxy_chat"]) == (False, None)
    assert "meat_proxy_note" not in before
    seen = events(migrated)
    assert put(owner, chat, True).status_code == 204
    assert events(migrated) == seen  # no event, wakes nobody
    mine = entry(owner.get(f"{BASE}/{chat}").json(), owner.id)
    assert (mine["meat_proxy"], mine["meat_proxy_chat"]) == (True, True)
    assert "Lead me step by step" in mine["meat_proxy_note"]
    assert "hands" in mine["meat_proxy_note"]  # both parts
    theirs = entry(guest.get(f"{BASE}/{chat}").json(), owner.id)
    assert (theirs["meat_proxy"], theirs["meat_proxy_chat"]) == (True, None)
    assert "meat_proxy" not in entry(owner.get(f"{BASE}/{chat}").json(), agent.id)  # no agent
    assert put(owner, chat, True).status_code == 204  # idempotent
    assert put(owner, chat, None).status_code == 204  # follows the profile again
    again = entry(owner.get(f"{BASE}/{chat}").json(), owner.id)
    assert (again["meat_proxy"], again["meat_proxy_chat"]) == (False, None)


def test_the_chat_beats_the_profile_and_a_profile_that_is_on_keeps_its_parts(
    owner: flow.Human, agent: flow.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    guest = other_human(make_client, migrated, "guest")
    chat = chat_of(owner, agent, guest)
    assert owner.patch(ME, {"meat_proxy_lead": True}).status_code == 200
    follows = entry(owner.get(f"{BASE}/{chat}").json(), owner.id)
    assert follows["meat_proxy"] is True and "hands" not in follows["meat_proxy_note"]
    assert put(owner, chat, True).status_code == 204  # on over a profile that is on: its parts stay
    kept = entry(owner.get(f"{BASE}/{chat}").json(), owner.id)
    assert "Lead me step by step" in kept["meat_proxy_note"]
    assert "hands" not in kept["meat_proxy_note"]
    assert put(owner, chat, False).status_code == 204  # off in this chat, on in the profile
    off = entry(owner.get(f"{BASE}/{chat}").json(), owner.id)
    assert (off["meat_proxy"], off["meat_proxy_chat"]) == (False, False)
    assert "meat_proxy_note" not in off
    assert owner.get(ME).json()["member"]["meat_proxy"] is True  # the profile is untouched


def test_a_direct_chat_has_it_too_and_the_agent_reads_it_in_its_packet(
    owner: flow.Human, agent: flow.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    guest = other_human(make_client, migrated, "guest")
    chat = chat_of(owner, agent, guest)
    packet = agent.resume().json()["conversations"]
    assert [c["meat_proxy"] for c in packet] == [[] for _ in packet]
    assert put(owner, agent.id, True).status_code == 204  # the direct chat's id is the agent's
    direct = owner.get(f"{BASE}/{agent.id}").json()
    assert entry(direct, owner.id)["meat_proxy_chat"] is True
    listed = [i for i in owner.get(BASE).json()["items"] if i["id"] == agent.id][0]
    assert entry(listed, owner.id)["meat_proxy"] is True
    by_id = {c["id"]: c for c in agent.resume().json()["conversations"]}
    [named] = by_id[agent.id]["meat_proxy"]
    assert named["member_id"] == owner.id and named["handle"] == "maintainer"
    assert named["meat_proxy_note"].startswith("This person says: I am a meat proxy.")
    assert by_id[chat]["meat_proxy"] == []  # the group chat has no choice
    assert put(owner, chat, True).status_code == 204
    by_id = {c["id"]: c for c in agent.resume().json()["conversations"]}
    assert [h["member_id"] for h in by_id[chat]["meat_proxy"]] == [owner.id]


def test_only_a_human_taking_part_sets_it(
    owner: flow.Human, agent: flow.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    guest = other_human(make_client, migrated, "guest")
    stranger = other_human(make_client, migrated, "stranger")
    other = other_human(make_client, migrated, "other-owner", role="admin")
    theirs = flow.agent(make_client, other)
    chat = chat_of(owner, agent, guest)
    watched = create(owner, theirs.id, guest.id, title="watched").json()["id"]
    refused = agent.client.put(
        f"/api/v1{BASE}/{chat}/meat-proxy",
        json={"meat_proxy": True},
        headers=agent.auth | agent.key(),
    )
    assert refused.status_code == 403 and refused.json()["error"]["details"] == {
        "reason": "humans_only"
    }
    assert put(stranger, chat, True).status_code == 404  # cannot read it
    assert put(stranger, agent.id, True).status_code == 404  # nor a direct one
    assert put(guest, agent.id, True).status_code == 404  # a direct chat is its two parties'
    reading = put(other, watched, True)  # reads along as the owner of an agent in it
    assert reading.status_code == 403
    assert reading.json()["error"]["details"] == {"reason": "not_a_participant"}
    assert put(guest, chat, True).status_code == 204  # a participant, for itself
    assert entry(owner.get(f"{BASE}/{chat}").json(), guest.id)["meat_proxy_chat"] is None
    assert entry(guest.get(f"{BASE}/{chat}").json(), guest.id)["meat_proxy_chat"] is True
    assert put(owner, chat, "yes").status_code == 400  # a boolean or null


def test_the_projects_tell_one_agents_direct_chats_apart(
    owner: flow.Human, agent: flow.Agent, migrated: Engine
) -> None:
    with migrated.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        chat_meat_proxy.put(conn, owner.id, project_id, agent.id, True)
        here: list[dict[str, Any]] = [
            {"member_id": owner.id, "kind": "human", "handle": "maintainer"}
        ]
        there: list[dict[str, Any]] = [
            {"member_id": owner.id, "kind": "human", "handle": "maintainer"}
        ]
        chat_meat_proxy.shown(
            conn, [(project_id, agent.id, here), ("prj-other", agent.id, there)], owner.id
        )
    assert here[0]["meat_proxy_chat"] is True
    assert there[0]["meat_proxy_chat"] is None and there[0]["meat_proxy"] is False


def test_the_export_names_the_choices_and_the_deletion_takes_them(
    owner: flow.Human, agent: flow.Agent, migrated: Engine
) -> None:
    from maity_hub import account_deletion  # noqa: F401  (the deletion's own test is below)
    from maity_hub.routes import me

    assert put(owner, agent.id, True).status_code == 204
    me.EXPORTS.reset()
    exported = owner.get("/me/export").json()["conversation_meat_proxy"]
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    assert exported == [{"project_id": project_id, "conversation_id": agent.id, "meat_proxy": True}]


def test_one_agents_direct_chats_in_two_projects_keep_their_own_choice(
    owner: flow.Human, agent: flow.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    """The same agent has the same direct-chat id in every project it is in (§9.1): the choice is
    stored per project, through the route, in the migrated schema."""
    flow.project(owner, "beta")
    created = flow.join(owner, "beta", agent={"id": agent.id})
    assert flow.exchange(make_client(), created).status_code == 201
    here, there = "/projects/maintainer/maity", "/projects/maintainer/beta"

    def set_in(base: str, value: bool) -> Any:
        return owner.client.put(
            f"/api/v1{base}/conversations/{agent.id}/meat-proxy",
            json={"meat_proxy": value},
            headers={"X-CSRF-Token": owner.csrf},
        )

    assert set_in(here, True).status_code == 204
    assert set_in(there, False).status_code == 204
    chat_here = owner.get(f"{here}/conversations/{agent.id}").json()
    chat_there = owner.get(f"{there}/conversations/{agent.id}").json()
    assert entry(chat_here, owner.id)["meat_proxy_chat"] is True
    assert entry(chat_there, owner.id)["meat_proxy_chat"] is False
    with migrated.connect() as conn:
        rows = conn.execute(select(t.conversation_meat_proxy)).all()
    assert sorted((r.project_id != "", bool(r.meat_proxy)) for r in rows) == [
        (True, False),
        (True, True),
    ]
