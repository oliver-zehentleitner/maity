"""docs/api.md §9.6 "The lists": a human's allow and deny entries for their agents,
`/me/chat-access`, the cleanup when what an entry names goes, and the export."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, insert, select

from maity_hub import chat_access, clock
from maity_hub import tables as t
from maity_hub.ids import new_id
from tests import flow
from tests.conftest import ClientFactory


@pytest.fixture
def anna(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated, "anna")


@pytest.fixture
def ben(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated, "ben")


def profile(engine: Engine, owner_id: str, handle: str) -> str:
    agent_id = new_id("agent")
    with engine.begin() as conn:
        conn.execute(
            insert(t.agent_profile).values(
                id=agent_id,
                owner_id=owner_id,
                handle=handle,
                display_name=handle,
                created_at=clock.now(),
            )
        )
    return agent_id


def allow(who: flow.Human, **body: Any) -> Any:
    return who.post("/me/chat-access/allow", body)


def deny(who: flow.Human, **body: Any) -> Any:
    return who.post("/me/chat-access/deny", body)


def listed(who: flow.Human, **query: Any) -> dict[str, Any]:
    got = who.get("/me/chat-access", params=query)
    assert got.status_code == 200, got.text
    assert got.headers["cache-control"] == "private, no-store"
    body: dict[str, Any] = got.json()
    return body


def fields(response: Any) -> dict[str, Any]:
    assert response.status_code == 400, response.text
    details: dict[str, Any] = response.json()["error"]["details"]
    return details


def _entries(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(t.chat_access)).scalar_one())


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_an_allow_for_a_side_and_how_it_shows(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    theirs = profile(migrated, ben.id, "ben-b")
    created = allow(
        anna,
        agents=[mine],
        owner_id=ben.id,
        their_agents=[theirs],
        duration="day",
        allowed="web and frontend",
        denied="nothing about releases",
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    assert set(entry) == {
        "id",
        "agents",
        "owner_id",
        "handle",
        "their_agents",
        "their_human",
        "project",
        "duration",
        "until",
        "allowed",
        "denied",
        "by",
        "since",
    }
    assert entry["id"].startswith("cha-")
    assert entry["agents"] == [mine] and entry["their_agents"] == [theirs]
    assert entry["owner_id"] == ben.id and entry["handle"] == "ben"
    assert entry["their_human"] is False  # never set automatically (req-ssgyxfs5wdjw)
    assert entry["project"] is None and entry["by"] == anna.id
    assert _at(entry["until"]) - _at(entry["since"]) == timedelta(days=1)
    assert listed(anna) == {"allow": [entry], "deny": []}
    assert listed(ben) == {"allow": [], "deny": []}  # only the human who keeps it reads it


def test_the_defaults_and_a_project_entry(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    side = allow(anna, agents="all", owner_id=ben.id).json()
    assert side["agents"] == "all" and side["their_agents"] == "all"
    assert side["duration"] is None and side["until"] is None
    flow.project(anna, "maity")
    project = allow(anna, agents=[mine], project={"owner": "anna", "slug": "maity"}).json()
    assert project["project"] == {"owner": "anna", "slug": "maity"}
    assert project["owner_id"] is None and project["handle"] is None
    assert project["their_agents"] is None and project["their_human"] is None
    assert [e["id"] for e in listed(anna)["allow"]] == [project["id"], side["id"]]  # newest first
    refused = allow(
        anna, agents=[mine], project={"owner": "anna", "slug": "maity"}, their_human=True
    )
    assert fields(refused) == {"fields": {"their_human": "project_entry"}}


def test_what_an_entry_may_name(anna: flow.Human, ben: flow.Human, migrated: Engine) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    bens = profile(migrated, ben.id, "ben-b")
    other = profile(migrated, anna.id, "anna-c")
    assert fields(allow(anna, agents=[bens], owner_id=ben.id)) == {
        "fields": {"agents": "not_yours"}
    }
    assert fields(allow(anna, agents=[mine], owner_id=ben.id, their_agents=[other])) == {
        "fields": {"their_agents": "not_theirs"}
    }
    assert fields(allow(anna, agents=[mine], owner_id=anna.id)) == {"fields": {"owner_id": "self"}}
    assert fields(allow(anna, agents=[mine], owner_id="hum-NOBODY")) == {
        "fields": {"owner_id": "not_found"}
    }
    assert fields(allow(anna, agents=[mine], owner_id=ben.id, duration="month")) == {
        "fields": {"duration": "format"}
    }
    assert fields(allow(anna, agents=[mine], owner_id=ben.id, allowed="x" * 1001)) == {
        "fields": {"allowed": "format"}
    }
    both = allow(anna, agents=[mine], owner_id=ben.id, project={"owner": "anna", "slug": "x"})
    assert fields(both) == {"fields": {"owner_id": "one_subject", "project": "one_subject"}}
    assert allow(anna, agents=[mine], owner_id=ben.id, extra=1).status_code == 400
    flow.project(ben, "bens")  # anna is no member, nor is any agent of hers
    assert fields(allow(anna, agents=[mine], project={"owner": "ben", "slug": "bens"})) == {
        "fields": {"project": "not_found"}
    }
    assert _entries(migrated) == 0


def test_a_patch_restarts_the_duration_only_when_it_sends_one(
    anna: flow.Human, ben: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    start = clock.now()
    monkeypatch.setattr(clock, "now", lambda: start)
    entry = allow(anna, agents=[mine], owner_id=ben.id, duration="hour").json()
    later = start + timedelta(minutes=30)
    monkeypatch.setattr(clock, "now", lambda: later)
    kept = anna.patch(f"/me/chat-access/allow/{entry['id']}", {"denied": "no releases"})
    assert kept.status_code == 200, kept.text
    assert kept.json()["until"] == entry["until"] and kept.json()["denied"] == "no releases"
    again = anna.patch(f"/me/chat-access/allow/{entry['id']}", {"duration": "hour"}).json()
    assert _at(again["until"]) == _at(entry["until"]) + timedelta(minutes=30)
    ended = anna.patch(f"/me/chat-access/allow/{entry['id']}", {"duration": None}).json()
    assert ended["duration"] is None and ended["until"] is None
    human = anna.patch(f"/me/chat-access/allow/{entry['id']}", {"their_human": True}).json()
    assert human["their_human"] is True
    assert ben.patch(f"/me/chat-access/allow/{entry['id']}", {"denied": None}).status_code == 404


def test_a_deny_removes_the_allows_for_the_same_agents_and_side(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    a1 = profile(migrated, anna.id, "anna-a")
    a2 = profile(migrated, anna.id, "anna-b")
    listed_both = allow(anna, agents=[a1, a2], owner_id=ben.id).json()
    for_all = allow(anna, agents="all", owner_id=ben.id).json()
    created = deny(anna, agents=[a1], owner_id=ben.id)
    assert created.status_code == 201, created.text
    entry = created.json()
    assert set(entry) == {"id", "agents", "owner_id", "handle", "by", "since"}
    allows = {e["id"]: e for e in listed(anna)["allow"]}
    assert allows[listed_both["id"]]["agents"] == [a2]  # narrowed
    assert allows[for_all["id"]]["agents"] == "all"  # stays: the deny wins over it anyway
    deny(anna, agents="all", owner_id=ben.id)
    assert listed(anna)["allow"] == []  # a deny of all agents removes every allow of the side


def test_a_deny_names_one_human_one_agent_or_a_project(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    bens = profile(migrated, ben.id, "ben-b")
    human = deny(anna, agents=[mine], human_id=ben.id).json()
    assert human["human_id"] == ben.id and human["handle"] == "ben"
    agent = deny(anna, agents=[mine], agent_id=bens).json()
    assert agent["agent_id"] == bens
    assert fields(deny(anna, agents=[mine], agent_id=mine)) == {"fields": {"agent_id": "self"}}
    flow.project(anna, "maity")
    project = deny(anna, agents="all", project={"owner": "anna", "slug": "maity"}).json()
    assert project["project"] == {"owner": "anna", "slug": "maity"}
    assert [e["id"] for e in listed(anna)["deny"]] == [project["id"], agent["id"], human["id"]]


def test_delete_answers_204_also_when_nothing_is_there(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    entry = allow(anna, agents=[mine], owner_id=ben.id).json()
    assert ben.delete(f"/me/chat-access/allow/{entry['id']}").status_code == 204
    assert len(listed(anna)["allow"]) == 1  # another human's delete changes nothing
    assert anna.delete(f"/me/chat-access/deny/{entry['id']}").status_code == 204  # wrong kind
    assert len(listed(anna)["allow"]) == 1
    assert anna.delete(f"/me/chat-access/allow/{entry['id']}").status_code == 204
    assert anna.delete(f"/me/chat-access/allow/{entry['id']}").status_code == 204
    assert _entries(migrated) == 0


def test_the_filter_by_agent(anna: flow.Human, ben: flow.Human, migrated: Engine) -> None:
    a1 = profile(migrated, anna.id, "anna-a")
    a2 = profile(migrated, anna.id, "anna-b")
    one = allow(anna, agents=[a1], owner_id=ben.id).json()
    every = allow(anna, agents="all", owner_id=ben.id).json()
    allow(anna, agents=[a2], owner_id=ben.id)
    assert [e["id"] for e in listed(anna, agent=a1)["allow"]] == [every["id"], one["id"]]


def test_an_agent_does_not_open_its_own_door(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    for response in (
        agent.get("/me/chat-access"),
        agent.post("/me/chat-access/allow", {"agents": "all", "owner_id": owner.id}),
    ):
        assert response.status_code == 403, response.text
        assert response.json()["error"]["details"]["reason"] == "humans_only"


def test_at_most_a_number_of_entries(
    anna: flow.Human, ben: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    monkeypatch.setattr(chat_access, "MAX_ENTRIES", 2)
    allow(anna, agents=[mine], owner_id=ben.id)
    deny(anna, agents=[mine], human_id=ben.id)
    assert fields(allow(anna, agents=[mine], owner_id=ben.id)) == {"reason": "too_many_entries"}


def test_a_gone_agent_is_taken_out_and_an_entry_naming_no_one_goes(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    a1 = profile(migrated, anna.id, "anna-a")
    a2 = profile(migrated, anna.id, "anna-b")
    bens = profile(migrated, ben.id, "ben-b")
    two = allow(anna, agents=[a1, a2], owner_id=ben.id).json()
    only_bens = allow(anna, agents=[a1], owner_id=ben.id, their_agents=[bens]).json()
    with_human = allow(
        anna, agents=[a1], owner_id=ben.id, their_agents=[bens], their_human=True
    ).json()
    denied = deny(anna, agents=[a1], agent_id=bens).json()
    with migrated.begin() as conn:
        chat_access.forget_agent(conn, bens)
    allows = {e["id"]: e for e in listed(anna)["allow"]}
    assert only_bens["id"] not in allows  # names no one now
    assert allows[with_human["id"]]["their_agents"] == "none"  # still names the human
    assert denied["id"] not in {e["id"] for e in listed(anna)["deny"]}
    with migrated.begin() as conn:
        chat_access.forget_agent(conn, a1)
    allows = {e["id"]: e for e in listed(anna)["allow"]}
    assert allows[two["id"]]["agents"] == [a2]
    assert with_human["id"] not in allows  # no agent left on the owner's side


def test_a_deleted_account_takes_its_entries_and_those_naming_it(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    bens = profile(migrated, ben.id, "ben-b")
    allow(anna, agents=[mine], owner_id=ben.id)
    deny(anna, agents=[mine], human_id=ben.id)
    allow(ben, agents=[bens], owner_id=anna.id)
    with migrated.begin() as conn:
        chat_access.forget_human(conn, ben.id)
    assert listed(anna) == {"allow": [], "deny": []}
    assert _entries(migrated) == 0


def test_the_export_carries_the_lists(anna: flow.Human, ben: flow.Human, migrated: Engine) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    first = allow(anna, agents=[mine], owner_id=ben.id).json()
    second = deny(anna, agents=[mine], human_id=ben.id).json()
    exported = anna.get("/me/export").json()["chat_access"]
    assert exported == {"allow": [first], "deny": [second]}
