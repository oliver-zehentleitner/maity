"""docs/api.md §8.6 mentions, §6.2 member owner and credentials, §9 last_message, §16 admin."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import mentions
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture(autouse=True)
def _fresh_pings() -> None:
    mentions.PINGS.reset()


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def agent_named(
    make_client: ClientFactory, owner: flow.Human, handle: str, **body: Any
) -> flow.Agent:
    return flow.agent(make_client, owner, agent={"handle": handle, "display_name": handle}, **body)


# --- the rule ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "handles"),
    [
        ("ask @agent-b about it", ["agent-b"]),
        ("@agent-b.", ["agent-b"]),
        ("(@agent-b)", ["agent-b"]),
        ("@agent-b-", ["agent-b"]),
        ("@Agent-B", []),
        ("oliver@example.org", []),
        ("a/@b-c", []),
        ("@agent-bX", []),
        ("@all @here @everyone @owner @role:admin", []),
        ("`@agent-b` and @agent-c", ["agent-c"]),
        ("``x ` @agent-b ``", []),
        ("```\n@agent-b\n```\n@agent-c", ["agent-c"]),
        ("~~~\n@agent-b", []),
        ("` unmatched @agent-b", ["agent-b"]),
        ("\\@agent-b", ["agent-b"]),
    ],
)
def test_the_rule(text: str, handles: list[str]) -> None:
    assert [h for _, _, h in mentions.candidates(text)] == handles


def test_offsets_count_code_points() -> None:
    [(offset, length, handle)] = mentions.candidates("ä 😀 @agent-b")
    assert (offset, length, handle) == (4, 8, "agent-b")


# --- messages ------------------------------------------------------------------------------


def say(who: Any, **body: Any) -> Any:
    return who.post("/projects/maity/events", {"kind": "message", "type": "notice", **body})


def test_a_message_mention_joins_the_audience(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    writer = agent_named(make_client, owner, "agent-a")
    named = agent_named(make_client, owner, "agent-c")
    response = say(writer, to=owner.id, body="cc @agent-c, and `@agent-c` in code")
    assert response.status_code == 201, response.text
    event = response.json()
    assert f"member:{named.id}" in event["audience"]
    assert event["payload"]["mentions"] == [
        {"member_id": named.id, "handle": "agent-c", "field": "body", "offset": 3, "length": 8}
    ]


def test_a_chat_is_never_resolved(make_client: ClientFactory, owner: flow.Human) -> None:
    agent = agent_named(make_client, owner, "agent-a")
    other = agent_named(make_client, owner, "agent-c")
    response = owner.post(
        f"/projects/maity/conversations/{agent.id}/messages", {"body": "ask @agent-c"}
    )
    assert response.status_code == 201, response.text
    message = response.json()
    assert message["mentions"] == [] and message["body"] == "ask @agent-c"
    events = owner.get("/projects/maity/events?after=0&limit=200").json()["items"]
    [chat] = [e for e in events if e["kind"] == "message" and e["payload"].get("type") == "chat"]
    assert chat["payload"]["mentions"] == [] and f"member:{other.id}" not in chat["audience"]


def test_mentions_are_read_only(make_client: ClientFactory, owner: flow.Human) -> None:
    agent = agent_named(make_client, owner, "agent-a")
    response = say(agent, to="all", body="x", mentions=[])
    assert response.json()["error"]["details"]["fields"] == {"mentions": "read_only"}


def test_too_many_mentions_store_nothing(make_client: ClientFactory, owner: flow.Human) -> None:
    agent = agent_named(make_client, owner, "agent-a")
    named = agent_named(make_client, owner, "agent-c")
    del named
    response = say(agent, to="all", body=" ".join(["@agent-c"] * 51))
    assert response.json()["error"]["details"]["fields"] == {"body": "too_many_mentions"}


def test_pings_are_rate_limited(make_client: ClientFactory, owner: flow.Human) -> None:
    agent = agent_named(make_client, owner, "agent-a")
    agent_named(make_client, owner, "agent-c")
    for _ in range(30):
        assert say(agent, to=owner.id, body="@agent-c").status_code == 201
    limited = say(agent, to=owner.id, body="@agent-c")
    assert limited.status_code == 429 and int(limited.headers["Retry-After"]) > 0
    assert say(agent, to="all", body="@agent-c").status_code == 201  # `all` reaches it already


# --- cards, reports, requests --------------------------------------------------------------


def test_a_card_body_pings_only_new_mentions(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    named = agent_named(make_client, owner, "agent-c")
    card = owner.post("/projects/maity/tasks", {"title": "t", "body": "for @agent-c"}).json()
    assert card["mentions"][0]["member_id"] == named.id
    owner.patch(f"/projects/maity/tasks/{card['id']}", {"body": "still for @agent-c, now longer"})
    with migrated.connect() as conn:
        pinged = conn.execute(select(t.event).where(t.event.c.kind == "mentioned")).all()
    assert len(pinged) == 1
    assert pinged[0].audience == [f"member:{named.id}"]
    assert pinged[0].payload["task"]["id"] == card["id"] and pinged[0].payload["field"] == "body"


def test_a_request_mention_is_a_link_only(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    asker = agent_named(make_client, owner, "agent-a")
    agent_named(make_client, owner, "agent-c")
    request = asker.post(
        "/projects/maity/requests",
        {"class": "info", "title": "q", "summary": "as @agent-c said", "tried": "@agent-c"},
    ).json()
    assert [m["field"] for m in request["mentions"]] == ["summary", "tried"]
    with migrated.connect() as conn:
        assert conn.execute(select(t.event).where(t.event.c.kind == "mentioned")).all() == []


# --- members, conversations, admin -----------------------------------------------------------


def test_admins_and_owners_see_owner_and_credentials(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = agent_named(make_client, owner, "agent-a")
    view = owner.get(f"/projects/maity/members/{agent.id}").json()
    assert view["owner"] == {
        "id": owner.id,
        "handle": "maintainer",
        "display_name": "Human maintainer",
    }
    assert view["credentials"]["active"] == 1 and view["credentials"]["never_resumed"] == 1
    agent.resume()
    after = owner.get(f"/projects/maity/members/{agent.id}").json()["credentials"]
    assert after["never_resumed"] == 0 and after["last_used_via"] == "bearer"
    plain = flow.human(make_client, migrated, "reader")
    factory.membership(migrated, _project_id(migrated), "member", human_id=plain.id)
    seen = plain.get(f"/projects/maity/members/{agent.id}").json()
    assert "owner" not in seen and "credentials" not in seen
    listed = owner.get("/projects/maity/members").json()["items"]
    human_row = next(m for m in listed if m["id"] == owner.id)
    assert human_row["owner"] is None and human_row["credentials"] is None


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
    return project_id


def test_the_conversation_list_previews_the_last_message(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = agent_named(make_client, owner, "agent-a")
    assert owner.get("/projects/maity/conversations").json()["items"][0]["last_message"] is None
    owner.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": "ä" * 250})
    [item] = owner.get("/projects/maity/conversations").json()["items"]
    preview = item["last_message"]
    assert preview["from"] == owner.id and preview["body"] == "ä" * 200
    assert preview["redacted"] is False and "mentions" not in preview


def test_the_instance_admin_and_the_user_list(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    assert owner.get("/me").json()["member"]["instance_admin"] is True
    other = flow.human(make_client, migrated, "someone")
    assert other.get("/me").json()["member"]["instance_admin"] is False
    refused = other.get("/admin/users")
    assert (refused.status_code, refused.json()["error"]["details"]) == (
        403,
        {"scope": "instance:admin"},
    )
    agent = agent_named(make_client, owner, "agent-a")
    assert agent.get("/admin/users").status_code == 403
    listed = owner.get("/admin/users").json()
    assert [u["handle"] for u in listed["items"]] == ["maintainer", "someone"]
    first = listed["items"][0]
    assert (first["instance_admin"], first["memberships"], first["agents"]) == (True, 1, 1)
    assert first["last_login_at"] is not None and first["disabled"] is False
    page = owner.get("/admin/users?limit=1").json()
    assert len(page["items"]) == 1 and page["next_cursor"] == "maintainer"
    rest = owner.get(f"/admin/users?limit=1&cursor={page['next_cursor']}").json()
    assert [u["handle"] for u in rest["items"]] == ["someone"]
    assert [u["handle"] for u in owner.get("/admin/users?q=SOME").json()["items"]] == ["someone"]
    assert owner.get("/admin/users?disabled=true").json()["items"] == []
