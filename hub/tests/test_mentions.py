"""docs/api.md §8.6 mentions, §6.2 member owner and credentials, §9 last_message, §16 admin."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, events, mentions
from maity_hub import tables as t
from maity_hub.errors import ApiError
from tests import factory, flow
from tests.conftest import ClientFactory


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
        ("@all @here @everyone @owner @trust:admin", []),
        ("`@agent-b` and @agent-c", ["agent-c"]),
        ("``x ` @agent-b ``", []),
        ("```\n@agent-b\n```\n@agent-c", ["agent-c"]),
        ("~~~\n@agent-b", []),
        ("` unmatched @agent-b", ["agent-b"]),
        ("\\@agent-b", ["agent-b"]),
        # Only \n ends a line: a fence after \x0b, \x85 or U+2028 opens nothing.
        ("x\u2028```\n@agent-b", ["agent-b"]),
        ("x\x85~~~\n@agent-b", ["agent-b"]),
        ("x\x0b```\n@agent-b", ["agent-b"]),
        ("```\r\n@agent-b\r\n```\r\n@agent-c", ["agent-c"]),
        # The global name (§6.3): a run, `/`, a run — judged whole.
        ("ask @oliver/agent-b about it", ["oliver/agent-b"]),
        ("(@oliver/agent-b).", ["oliver/agent-b"]),
        ("@oliver/agent-b-", ["oliver/agent-b"]),
        ("@oliver/agent-b/docs", ["oliver/agent-b"]),
        ("@oliver/", ["oliver"]),  # a trailing `/` is a boundary of the short form
        ("@oliver/-", ["oliver"]),
        ("@oliver/agent_b", []),  # no boundary after the global name: no mention at all
        ("@oliver/Agent-B", ["oliver"]),
        ("a/@oliver/agent-b", []),
        ("oliver@example.org/agent-b", []),
        ("`@oliver/agent-b` and @oliver/agent-c", ["oliver/agent-c"]),
        ("@all/agent-b @owner/agent-c", ["all/agent-b", "owner/agent-c"]),  # names, not groups
        # An instance id directly after the name belongs to it (§6.17).
        ("ask @agent-b#wqe2.", ["agent-b#wqe2"]),
        ("@oliver/agent-b#wqe2", ["oliver/agent-b#wqe2"]),
        ("@agent-b#wqe2x9", ["agent-b"]),  # no id: the `#` is a boundary
        ("@agent-b#wle2", ["agent-b"]),  # `l` is not in the id alphabet
        ("@agent-b#WLE2 @agent-c#1 @agent-d#", ["agent-b", "agent-c", "agent-d"]),
        ("@agent-b-#wqe2", ["agent-b"]),
        ("`@agent-b#wqe2`", []),
    ],
)
def test_the_rule(text: str, handles: list[str]) -> None:
    found = mentions.candidates(text)
    shown = [
        (f"{c.owner}/{c.handle}" if c.owner else c.handle)
        + (f"#{c.instance}" if c.instance else "")
        for c in found
    ]
    assert shown == handles


def test_offsets_count_code_points() -> None:
    [(offset, length, handle, owner, instance)] = mentions.candidates("ä 😀 @agent-b")
    assert (offset, length, handle, owner, instance) == (4, 8, "agent-b", None, None)
    [found] = mentions.candidates("ä @oliver/agent-b.")
    assert (found.offset, found.length, found.handle, found.owner) == (2, 15, "agent-b", "oliver")


# --- messages ------------------------------------------------------------------------------


def say(who: Any, **body: Any) -> Any:
    return who.post(
        "/projects/maintainer/maity/events", {"kind": "message", "type": "notice", **body}
    )


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
        {
            "member_id": named.id,
            "handle": "agent-c",
            "name": "maintainer/agent-c",
            "instance": None,
            "field": "body",
            "offset": 3,
            "length": 8,
        }
    ]


@pytest.mark.parametrize("to", ["all", "role:reviewer", "self"])
def test_a_mention_covered_by_to_adds_no_member_token(
    make_client: ClientFactory, owner: flow.Human, to: str
) -> None:
    writer = agent_named(make_client, owner, "agent-a")
    named = agent_named(make_client, owner, "agent-c", role="reviewer")
    addressed = named.id if to == "self" else to
    event = say(writer, to=addressed, body="cc @agent-c").json()
    assert [m["member_id"] for m in event["payload"]["mentions"]] == [named.id]
    target = {"all": "all", "role:reviewer": "role:reviewer", "self": f"member:{named.id}"}[to]
    assert event["audience"] == [target, f"member:{writer.id}"]  # the sender reads its own


def test_a_chat_is_never_resolved(make_client: ClientFactory, owner: flow.Human) -> None:
    agent = agent_named(make_client, owner, "agent-a")
    other = agent_named(make_client, owner, "agent-c")
    response = owner.post(
        f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": "ask @agent-c"}
    )
    assert response.status_code == 201, response.text
    message = response.json()
    assert message["mentions"] == [] and message["body"] == "ask @agent-c"
    events = owner.get("/projects/maintainer/maity/events?after=0&limit=200").json()["items"]
    [chat] = [e for e in events if e["kind"] == "message" and e["payload"].get("type") == "chat"]
    assert chat["payload"]["mentions"] == [] and f"member:{other.id}" not in chat["audience"]


def second_owners_agent(engine: Engine, owner_handle: str, handle: str) -> str:
    """Another owner's agent with the same short handle, a member of the project."""
    with engine.connect() as conn:
        known = conn.execute(select(t.human.c.id).where(t.human.c.handle == owner_handle)).scalar()
    owner_id = known or factory.human(engine, owner_handle)
    agent_id = f"agt-{owner_handle}-{handle}"
    with engine.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        conn.execute(
            insert(t.agent_profile).values(
                id=agent_id,
                owner_id=owner_id,
                handle=handle,
                display_name=handle,
                created_at=clock.now(),
            )
        )
    factory.membership(engine, project_id, "member", agent_id=agent_id)
    return agent_id


def test_the_global_name_resolves_and_a_shared_short_handle_is_refused(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    writer = agent_named(make_client, owner, "agent-a")
    mine = agent_named(make_client, owner, "agent-b")
    alone = say(writer, to=owner.id, body="cc @agent-b").json()
    assert [m["member_id"] for m in alone["payload"]["mentions"]] == [mine.id]
    theirs = second_owners_agent(migrated, "anna", "agent-b")
    refused = say(writer, to=owner.id, body="cc @agent-b and @agent-a")
    assert refused.status_code == 400, refused.text
    details = refused.json()["error"]["details"]
    assert details == {
        "fields": {"body": "ambiguous_mention"},
        "mentions": {"agent-b": ["anna/agent-b", "maintainer/agent-b"]},
    }
    long = say(writer, to=owner.id, body="cc @anna/agent-b, not @maintainer/agent-b.").json()
    assert long["payload"]["mentions"] == [
        {
            "member_id": theirs,
            "handle": "agent-b",
            "name": "anna/agent-b",
            "instance": None,
            "field": "body",
            "offset": 3,
            "length": 13,
        },
        {
            "member_id": mine.id,
            "handle": "agent-b",
            "name": "maintainer/agent-b",
            "instance": None,
            "field": "body",
            "offset": 22,
            "length": 19,
        },
    ]
    assert f"member:{theirs}" in long["audience"] and f"member:{mine.id}" in long["audience"]
    # A global name that is no member, and a human's handle, which has no long form.
    other = say(writer, to=owner.id, body="@nobody/agent-b @maintainer/maintainer @maintainer")
    [human] = other.json()["payload"]["mentions"]
    assert (human["member_id"], human["handle"], human["name"]) == (owner.id, "maintainer", None)


def test_a_human_comes_first_and_the_refusal_names_every_shared_handle(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    writer = agent_named(make_client, owner, "agent-a")
    # Two agents named like the human: `@maintainer` is the human, the agents have long forms.
    second_owners_agent(migrated, "anna", "maintainer")
    second_owners_agent(migrated, "bob", "maintainer")
    plain = say(writer, to=owner.id, body="@maintainer @anna/maintainer").json()
    assert [m["member_id"] for m in plain["payload"]["mentions"]] == [
        owner.id,
        "agt-anna-maintainer",
    ]
    agent_named(make_client, owner, "agent-z")
    second_owners_agent(migrated, "anna", "agent-z")
    second_owners_agent(migrated, "bob", "agent-b")
    agent_named(make_client, owner, "agent-b")
    refused = say(writer, to=owner.id, body="@agent-z then @agent-b")
    assert refused.json()["error"]["details"]["mentions"] == {
        "agent-b": ["bob/agent-b", "maintainer/agent-b"],
        "agent-z": ["anna/agent-z", "maintainer/agent-z"],
    }
    assert list(refused.json()["error"]["details"]["mentions"]) == ["agent-b", "agent-z"]


def test_a_card_body_with_a_shared_short_handle_stores_nothing(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent_named(make_client, owner, "agent-b")
    second_owners_agent(migrated, "anna", "agent-b")
    refused = owner.post("/projects/maintainer/maity/tasks", {"title": "x", "body": "for @agent-b"})
    assert refused.json()["error"]["details"]["fields"] == {"body": "ambiguous_mention"}
    with migrated.connect() as conn:
        assert conn.execute(select(t.card)).first() is None


def test_ambiguity_is_judged_among_whom_a_text_may_name(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    mine = agent_named(make_client, owner, "agent-b")
    theirs = second_owners_agent(migrated, "anna", "agent-b")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        found = mentions.resolve(conn, project_id, "@agent-b", "body", among={theirs})
        assert [m["member_id"] for m in found] == [theirs]
        assert mentions.resolve(conn, project_id, "@agent-b", "body", among={owner.id}) == []
    del mine


def team_of_two(make_client: ClientFactory, owner: flow.Human) -> tuple[flow.Agent, flow.Agent]:
    first = agent_named(make_client, owner, "agent-b")
    team = owner.patch(
        f"/projects/maintainer/maity/members/{first.id}", {"team": {"max_instances": 2}}
    )
    assert team.status_code == 200, team.text
    second = flow.agent(make_client, owner, agent={"id": first.id}, new_instance=True)
    return first, second


def test_an_instance_mention_pings_that_instance_only(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    writer = agent_named(make_client, owner, "agent-a")
    first, second = team_of_two(make_client, owner)
    text = f"@agent-b#{second.instance} and @maintainer/agent-b#{second.instance}"
    event = say(writer, to=owner.id, body=text).json()
    stored = event["payload"]["mentions"]
    assert [(m["member_id"], m["instance"], m["length"]) for m in stored] == [
        (first.id, second.instance, 13),
        (first.id, second.instance, 24),
    ]
    assert f"instance:{first.id}#{second.instance}" in event["audience"]
    assert f"member:{first.id}" not in event["audience"]
    # The handle alone is the team.
    team = say(writer, to=owner.id, body="@agent-b").json()
    assert team["payload"]["mentions"][0]["instance"] is None
    assert f"member:{first.id}" in team["audience"]


def test_to_the_team_still_wakes_the_mentioned_instance(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """`to` naming the team wakes the instances its rule chooses; the named instance is
    pinged on top (§8.6 "exactly that instance" over §8.2's coverage)."""
    writer = agent_named(make_client, owner, "agent-a")
    lead, other = team_of_two(make_client, owner)
    team = {"wake": "lead", "lead_instance": lead.instance}
    assert (
        owner.patch(f"/projects/maintainer/maity/members/{lead.id}", {"team": team}).status_code
        == 200
    )
    event = say(writer, to=lead.id, body=f"@agent-b#{other.instance} please").json()
    assert f"instance:{lead.id}#{other.instance}" in event["audience"]
    with migrated.connect() as conn:
        row = conn.execute(select(t.event).where(t.event.c.seq == event["seq"])).one()
        membership = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == lead.id)
        ).one()
    assert events.wakes(row, membership, lead.id, other.instance)
    # A mention `to` reaches by its own token adds nothing and charges nothing.
    direct = say(writer, to=f"{lead.id}#{other.instance}", body=f"@agent-b#{other.instance}").json()
    assert direct["audience"].count(f"instance:{lead.id}#{other.instance}") == 1


def test_an_unknown_or_revoked_instance_leaves_the_whole_text_plain(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    writer = agent_named(make_client, owner, "agent-a")
    first, second = team_of_two(make_client, owner)
    unknown = say(writer, to=owner.id, body="@agent-b#zzzz").json()
    assert unknown["payload"]["mentions"] == []
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == second.credential_id)
            .values(revoked_at=clock.now())
        )
    revoked = say(writer, to=owner.id, body=f"@agent-b#{second.instance}").json()
    assert revoked["payload"]["mentions"] == []
    assert say(writer, to=owner.id, body="@maintainer#wqe2").json()["payload"]["mentions"] == []
    del first


def test_an_ambiguous_short_handle_is_refused_even_with_an_instance(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    writer = agent_named(make_client, owner, "agent-a")
    first, _ = team_of_two(make_client, owner)
    second_owners_agent(migrated, "anna", "agent-b")
    refused = say(writer, to=owner.id, body=f"@agent-b#{first.instance}")
    assert refused.json()["error"]["details"]["fields"] == {"body": "ambiguous_mention"}
    long = say(writer, to=owner.id, body=f"@maintainer/agent-b#{first.instance}").json()
    assert long["payload"]["mentions"][0]["instance"] == first.instance


def test_a_card_mention_of_an_instance_wakes_that_instance(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    first, second = team_of_two(make_client, owner)
    created = owner.post(
        "/projects/maintainer/maity/tasks", {"title": "x", "body": f"@agent-b#{second.instance}"}
    )
    assert created.status_code == 201, created.text
    with migrated.connect() as conn:
        event = conn.execute(select(t.event).where(t.event.c.kind == "mentioned")).one()
    assert event.audience == [f"instance:{first.id}#{second.instance}"]


def test_in_a_group_chat_an_instance_mention_wakes_that_instance_only(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    first, second = team_of_two(make_client, owner)
    other = agent_named(make_client, owner, "agent-c")
    created = owner.post(
        "/projects/maintainer/maity/conversations",
        {"title": "Room", "participants": [first.id, other.id]},
    )
    assert created.status_code == 201, created.text
    chat = created.json()
    sent = owner.post(
        f"/projects/maintainer/maity/conversations/{chat['id']}/messages",
        {"body": f"@agent-b#{second.instance} please"},
    )
    assert sent.status_code == 201, sent.text
    with migrated.connect() as conn:
        row = conn.execute(
            select(t.event).where(t.event.c.kind == "message").order_by(t.event.c.seq.desc())
        ).first()
        membership = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == first.id)
        ).one()
    assert events.wakes(row, membership, first.id, second.instance)
    assert not events.wakes(row, membership, first.id, first.instance)


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


def test_a_write_that_does_not_commit_gives_its_pings_back(migrated: Engine) -> None:
    with pytest.raises(RuntimeError), events.transaction(migrated) as conn:
        mentions.charge(conn, 7, mentions.PINGS_PER_WINDOW)
        raise RuntimeError("a later failure")
    with events.transaction(migrated) as conn:
        mentions.charge(conn, 7, mentions.PINGS_PER_WINDOW)  # the whole budget is there
    with pytest.raises(ApiError), events.transaction(migrated) as conn:
        mentions.charge(conn, 7, 1)


def test_retry_after_waits_for_room_for_every_ping(
    make_client: ClientFactory, owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = agent_named(make_client, owner, "agent-a")
    for handle in ("agent-c", "agent-d"):
        agent_named(make_client, owner, handle)

    class Frozen:  # the limiter's clock only: a second boundary would make it 599
        @staticmethod
        def monotonic() -> float:
            return 1000.0

    monkeypatch.setattr("maity_hub.ratelimit.time", Frozen)
    for _ in range(29):
        assert say(agent, to=owner.id, body="@agent-c").status_code == 201
    limited = say(agent, to=owner.id, body="@agent-c @agent-d")
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) == 600  # all 29 were sent at this instant


def test_a_chat_refuses_mentions_as_read_only(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = agent_named(make_client, owner, "agent-a")
    response = owner.post(
        f"/projects/maintainer/maity/conversations/{agent.id}/messages",
        {"body": "x", "mentions": []},
    )
    assert response.json()["error"]["details"]["fields"] == {"mentions": "read_only"}


def test_many_code_spans_in_a_long_text_pair_as_commonmark_does() -> None:
    # 3000 single backticks: pairs (0,1), (2,3), …; the handle after each closer is text.
    text = "x " + "` @agent-b " * 3000 + "``"  # the `` at the end closes nothing
    assert len(mentions.candidates(text)) == 1500


# --- cards, reports, requests --------------------------------------------------------------


def test_a_card_body_pings_only_new_mentions(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    named = agent_named(make_client, owner, "agent-c")
    card = owner.post(
        "/projects/maintainer/maity/tasks", {"title": "t", "body": "for @agent-c"}
    ).json()
    assert card["mentions"][0]["member_id"] == named.id
    owner.patch(
        f"/projects/maintainer/maity/tasks/{card['id']}", {"body": "still for @agent-c, now longer"}
    )
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
        "/projects/maintainer/maity/requests",
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
    view = owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()
    assert view["owner"] == {
        "id": owner.id,
        "handle": "maintainer",
        "display_name": "Human maintainer",
        "avatar_url": None,
    }
    assert view["credentials"]["active"] == 1 and view["credentials"]["never_resumed"] == 1
    agent.resume()
    after = owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()["credentials"]
    assert after["never_resumed"] == 0 and after["last_used_via"] == "bearer"
    plain = flow.human(make_client, migrated, "reader")
    factory.membership(migrated, _project_id(migrated), "member", human_id=plain.id)
    seen = plain.get(f"/projects/maintainer/maity/members/{agent.id}").json()
    assert "owner" not in seen and "credentials" not in seen
    listed = owner.get("/projects/maintainer/maity/members").json()["items"]
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
    assert (
        owner.get("/projects/maintainer/maity/conversations").json()["items"][0]["last_message"]
        is None
    )
    owner.post(f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": "ä" * 250})
    [item] = owner.get("/projects/maintainer/maity/conversations").json()["items"]
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
    with migrated.begin() as conn:
        conn.execute(
            update(t.human).where(t.human.c.handle == "someone").values(display_name="Jörg 100%")
        )
    for q, handles in [("JÖRG", ["someone"]), ("%", ["someone"]), ("_", []), ("0%", ["someone"])]:
        found = owner.get("/admin/users", params={"q": q}).json()["items"]
        assert [u["handle"] for u in found] == handles, q
    assert owner.get("/admin/users?disabled=true").json()["items"] == []
