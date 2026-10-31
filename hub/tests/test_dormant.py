"""docs/api.md §6.17, "A dormant instance": an instance put to rest keeps its session and
answers only when asked by its own address (tsk-1vbs522stmb5)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import events, instances, listening
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_team_rules import _assigned, _last, _membership, _pair, _Reader, _team

PROJECT = "/projects/maintainer/maity"
MEMBERS = f"{PROJECT}/members"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity")
    return human


@pytest.fixture
def listens() -> Iterator[list[str]]:
    opened: list[str] = []
    yield opened
    for session_id in opened:
        listening.closed(session_id)


def _listen(listens: list[str], agent: flow.Agent) -> None:
    session_id = agent.resume().json()["session"]["id"]
    listening.opened(session_id)
    listens.append(session_id)


def rest(who: flow.Agent, value: bool = True) -> Any:
    return who.patch("/me", {"dormant": value})


def rest_by_owner(owner: flow.Human, agent: flow.Agent, instance: str, value: bool = True) -> Any:
    return owner.patch(f"{MEMBERS}/{agent.id}", {"dormant": value, "instance": instance})


def _credential(engine: Engine, agent: flow.Agent, instance: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.credential)
            .join(t.membership, t.membership.c.id == t.credential.c.membership_id)
            .where(t.membership.c.agent_id == agent.id, t.credential.c.instance == instance)
        ).one()


def _instance_view(owner: flow.Human, agent: flow.Agent, instance: str) -> dict[str, Any]:
    shown = owner.get(f"{MEMBERS}/{agent.id}").json()["instances"]
    [found] = [i for i in shown if i["id"] == instance]
    result: dict[str, Any] = found
    return result


# --- who sets it ---------------------------------------------------------------------------


def test_an_instance_rests_and_wakes_itself(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _pair(make_client, owner)
    done = rest(second)
    assert done.status_code == 200, done.text
    view = _instance_view(owner, first, second.instance)
    assert view["dormant"]["by"] == first.id and view["dormant"]["since"]
    assert _instance_view(owner, first, first.instance)["dormant"] is None
    updated = _last(migrated, "member_updated")
    assert updated.payload["changed"] == ["dormant"] and updated.payload["instance"] == (
        second.instance
    )
    # Its own change does not carry its own token (it knows), and nothing moves twice.
    assert f"instance:{first.id}#{second.instance}" not in updated.audience
    assert rest(second).status_code == 200  # resting a resting instance is no change
    assert rest(second, False).status_code == 200
    assert _instance_view(owner, first, second.instance)["dormant"] is None


def test_the_owner_puts_an_instance_to_rest_and_wakes_it_with_its_token(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _pair(make_client, owner)
    done = rest_by_owner(owner, first, second.instance)
    assert done.status_code == 200, done.text
    updated = _last(migrated, "member_updated")
    assert updated.payload["changed"] == ["dormant"]
    assert f"instance:{first.id}#{second.instance}" in updated.audience  # made by someone else
    shown = _instance_view(owner, first, second.instance)["dormant"]
    assert shown["by"] == owner.id
    missing = owner.patch(f"{MEMBERS}/{first.id}", {"dormant": True})
    assert missing.status_code == 400
    assert missing.json()["error"]["details"]["fields"] == {"instance": "required"}
    unknown = rest_by_owner(owner, first, "zzzz")
    assert unknown.status_code == 400
    assert rest_by_owner(owner, first, second.instance, False).status_code == 200


def test_an_agent_rests_no_instance_but_its_own(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first, second = _pair(make_client, owner)
    refused = first.patch(f"{MEMBERS}/{first.id}", {"dormant": True, "instance": second.instance})
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"reason": "humans_only"}
    mixed = first.patch("/me", {"dormant": True, "paused": None})
    assert mixed.status_code == 400


def test_the_lead_cannot_rest_and_a_resting_instance_cannot_lead(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first, second = _pair(make_client, owner)
    _team(owner, first.id, wake="lead", lead_instance=first.instance)
    lead = rest(first)
    assert lead.status_code == 400
    assert lead.json()["error"]["details"]["fields"] == {"dormant": "lead"}
    assert rest(second).status_code == 200
    naming = owner.patch(f"{MEMBERS}/{first.id}", {"team": {"lead_instance": second.instance}})
    assert naming.status_code == 400
    assert naming.json()["error"]["details"]["fields"] == {"team.lead_instance": "dormant"}


def test_another_owners_instance_rests_only_with_its_owner_s_go(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = factory.agent(migrated, _project(migrated), friend.id)
    credential = _lent_credential(migrated, lent)
    asked = owner.patch(
        f"{MEMBERS}/{lent.agent_id}", {"dormant": True, "instance": credential.instance}
    )
    assert asked.status_code == 202, asked.text
    assert "dormant" in asked.json()["summary"]
    assert _credential_by_id(migrated, credential.id).dormant_since is None
    done = friend.post(f"/requests/{asked.json()['id']}/answer", {"reply_id": "go"})
    assert done.status_code == 200, done.text
    assert _credential_by_id(migrated, credential.id).dormant_since is not None


def _lent_credential(engine: Engine, lent: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.credential)
            .join(t.membership, t.membership.c.id == t.credential.c.membership_id)
            .where(t.membership.c.agent_id == lent.agent_id)
        ).one()


def _credential_by_id(engine: Engine, credential_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.credential).where(t.credential.c.id == credential_id)).one()


def _project(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


# --- what wakes it -------------------------------------------------------------------------


def test_only_its_own_token_wakes_a_dormant_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _pair(make_client, owner)
    rest(second)
    reader = _Reader(_membership(migrated, first))
    owner.post(
        f"{PROJECT}/events", {"kind": "message", "type": "notice", "to": "all", "body": "All."}
    )
    broadcast = _last(migrated, "message")
    assert events.wakes(broadcast, reader, first.id, second.instance)  # awake: woken by `all`
    assert not events.wakes(broadcast, reader, first.id, second.instance, dormant=True)
    assert events.wakes(broadcast, reader, first.id, first.instance)
    owner.post(
        f"{PROJECT}/events",
        {
            "kind": "message",
            "type": "notice",
            "to": f"{first.id}#{second.instance}",
            "body": "You.",
        },
    )
    named = _last(migrated, "message")
    assert events.wakes(named, reader, first.id, second.instance, dormant=True)
    team = owner.post(
        f"{PROJECT}/events", {"kind": "message", "type": "notice", "to": first.id, "body": "Team."}
    )
    assert team.status_code == 201, team.text
    to_team = _last(migrated, "message")
    assert not events.wakes(to_team, reader, first.id, second.instance, dormant=True)


def test_the_long_poll_of_a_dormant_instance_ends_only_for_its_own_address(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first, second = _pair(make_client, owner)
    cursor = owner.get(f"{PROJECT}/events").json()["cursor"]
    assert rest(second).status_code == 200
    cursor = owner.get(f"{PROJECT}/events").json()["cursor"]
    owner.post(
        f"{PROJECT}/events", {"kind": "message", "type": "notice", "to": "all", "body": "All."}
    )
    quiet = second.get(f"{PROJECT}/events?after={cursor}&wait=1").json()["items"]
    assert quiet == []  # readable, but it does not end the wait
    woken = first.get(f"{PROJECT}/events?after={cursor}&wait=1").json()["items"]
    assert [i["payload"]["body"] for i in woken] == ["All."]
    owner.post(
        f"{PROJECT}/events",
        {
            "kind": "message",
            "type": "notice",
            "to": f"{first.id}#{second.instance}",
            "body": "You.",
        },
    )
    asked = second.get(f"{PROJECT}/events?after={cursor}&wait=1").json()["items"]
    assert [i["payload"]["body"] for i in asked][-1] == "You."
    assert instances  # the module under test


def test_the_team_rules_pass_over_a_dormant_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, listens: list[str]
) -> None:
    first, second = _pair(make_client, owner)
    _team(owner, first.id, wake="next_free")
    _listen(listens, first)
    _listen(listens, second)
    assert rest(second).status_code == 200
    _assigned(owner, first)
    assert _last(migrated, "task_assigned").wakes == {first.id: [first.instance]}
    # Round robin skips it like a paused one.
    _team(owner, first.id, wake="all", distribution="round_robin")
    picked = {_assigned(owner, first)["assigned_instance"] for _ in range(3)}
    assert picked == {first.instance}


def test_a_takeover_target_resolves_past_a_dormant_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _pair(make_client, owner)
    assert rest(second).status_code == 200
    with migrated.connect() as conn:
        member = _membership_row(conn, first)
        assert instances.resolve(conn, member, None, "to", past_dormant=True) == first.instance
        with pytest.raises(Exception):  # noqa: B017, PT011  (two awake would leave the choice open)
            instances.resolve(conn, member, None, "to")  # without the rule: several


def _membership_row(conn: Any, agent: flow.Agent) -> Any:
    return conn.execute(select(t.membership).where(t.membership.c.agent_id == agent.id)).one()


# --- every instance dormant, and what stays --------------------------------------------------


def test_with_every_instance_dormant_the_member_is_limited_by_dormancy(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first, second = _pair(make_client, owner)
    assert owner.get(f"{MEMBERS}/{first.id}").json()["availability"]["state"] == "available"
    assert rest(second).status_code == 200
    assert owner.get(f"{MEMBERS}/{first.id}").json()["availability"]["state"] == "available"
    assert rest(first).status_code == 200
    shown = owner.get(f"{MEMBERS}/{first.id}").json()["availability"]
    assert shown["state"] == "limited" and shown["source"] == "dormant"
    assert shown.get("until") is None
    assert rest(first, False).status_code == 200
    assert owner.get(f"{MEMBERS}/{first.id}").json()["availability"]["state"] == "available"


def test_resume_does_not_end_it_and_the_packet_says_so(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first, second = _pair(make_client, owner)
    assert rest(second).status_code == 200
    packet = second.resume().json()
    assert packet["me"]["dormant"]["by"] == first.id
    siblings = {s["id"]: s["dormant"] for s in packet["team"]}
    assert siblings[first.instance] is None
    again = second.resume().json()
    assert again["me"]["dormant"] is not None  # resume leaves it as it is
    assert first.resume().json()["me"]["dormant"] is None
    card = owner.post(f"{PROJECT}/tasks", {"title": "Still works"}).json()
    assert (
        second.post(f"{PROJECT}/tasks/{card['id']}/claim", {}).status_code == 200
    )  # refuses nothing


# --- mentions, group chats and runners ------------------------------------------------------


def _handle(owner: flow.Human, agent: flow.Agent) -> str:
    handle: str = owner.get(f"{MEMBERS}/{agent.id}").json()["handle"]
    return handle


def test_a_mention_in_a_message_to_all_still_wakes_a_dormant_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _pair(make_client, owner)
    handle = _handle(owner, first)
    token = f"instance:{first.id}#{second.instance}"
    # Awake: `all` reaches the mention already, no token of its own is added.
    owner.post(
        f"{PROJECT}/events",
        {
            "kind": "message",
            "type": "notice",
            "to": "all",
            "body": f"@{handle}#{second.instance} awake?",
        },
    )
    assert token not in _last(migrated, "message").audience
    assert rest(second).status_code == 200
    # Dormant: `all` does not reach it, so the mention puts its token in and wakes it.
    sent = owner.post(
        f"{PROJECT}/events",
        {
            "kind": "message",
            "type": "notice",
            "to": "all",
            "body": f"@{handle}#{second.instance} asleep?",
        },
    )
    assert sent.status_code == 201, sent.text
    event = _last(migrated, "message")
    assert token in event.audience
    reader = _Reader(_membership(migrated, first))
    assert events.wakes(event, reader, first.id, second.instance, dormant=True)
    assert not events.wakes(event, reader, first.id, first.instance, dormant=True)


def test_in_a_group_chat_only_an_instance_mention_wakes_a_dormant_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _pair(make_client, owner)
    other = flow.agent(make_client, owner)
    assert rest(second).status_code == 200
    chat = owner.post(
        f"{PROJECT}/conversations", {"title": "room", "participants": [first.id, other.id]}
    ).json()
    url = f"{PROJECT}/conversations/{chat['id']}/messages"
    reader = _Reader(_membership(migrated, first))
    plain = owner.post(url, {"body": "hello room"})
    assert plain.status_code == 201, plain.text
    plain_event = _last(migrated, "message")
    assert not events.wakes(plain_event, reader, first.id, second.instance, dormant=True)
    handle = _handle(owner, first)
    mention = owner.post(url, {"body": f"@{handle}#{second.instance} you?"})
    assert mention.status_code == 201, mention.text
    named = _last(migrated, "message")
    assert f"instance:{first.id}#{second.instance}" in named.audience
    assert events.wakes(named, reader, first.id, second.instance, dormant=True)


def test_under_a_runner_dormant_wins_over_the_supervised_set(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _pair(make_client, owner)
    assert rest(second).status_code == 200
    reader = _Reader(_membership(migrated, first))
    owner.post(
        f"{PROJECT}/events", {"kind": "message", "type": "notice", "to": "all", "body": "Everyone."}
    )
    broadcast = _last(migrated, "message")
    # A supervised awake session is woken by `all` for the supervised set; a dormant one never.
    for kind in sorted(events.SUPERVISED_ALL_WAKES):
        row = _SetRow(broadcast, kind)
        assert events.wakes(row, reader, first.id, first.instance, "cred", supervised=True)
        assert not events.wakes(
            row, reader, first.id, second.instance, "cred", supervised=True, dormant=True
        )


class _SetRow:
    """An event row with another kind, for the wake rule alone."""

    def __init__(self, row: Any, kind: str) -> None:
        self._row = row
        self.kind = kind

    def __getattr__(self, name: str) -> Any:
        return getattr(self._row, name)


# --- another owner's agent: what is asked at once, and the jour fixe ------------------------------


def test_a_further_request_supersedes_and_what_changes_nothing_or_is_refused_asks_nobody(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from sqlalchemy import update

    friend = flow.human(make_client, migrated, "friend")
    lent = factory.agent(migrated, _project(migrated), friend.id)
    credential = _lent_credential(migrated, lent)
    path = f"{MEMBERS}/{lent.agent_id}"
    first = owner.patch(path, {"dormant": True, "instance": credential.instance}).json()["id"]
    again = owner.patch(path, {"dormant": True, "instance": credential.instance})
    assert again.status_code == 202, again.text
    with migrated.connect() as conn:
        rows = {r.id: r for r in conn.execute(select(t.request)) if r.proposal}
    assert rows[first].status == "withdrawn" and rows[first].withdraw_reason == "superseded"
    assert rows[again.json()["id"]].status == "open"
    # Awake and asked to wake: nothing changes, nobody is asked, no request is filed.
    quiet = owner.patch(path, {"dormant": False, "instance": credential.instance})
    assert quiet.status_code == 200, quiet.text
    # The lead is refused now, not at the owner's go.
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == lent.agent_id)
            .values(lead_instance=credential.instance)
        )
    lead = owner.patch(path, {"dormant": True, "instance": credential.instance})
    assert lead.status_code == 400, lead.text
    assert lead.json()["error"]["details"]["fields"] == {"dormant": "lead"}


def test_the_jour_fixe_never_picks_a_dormant_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, listens: list[str]
) -> None:
    from maity_hub.jourfixe import rounds

    first, second = _pair(make_client, owner)
    _listen(listens, first)
    _listen(listens, second)
    assert rest(second).status_code == 200
    with migrated.connect() as conn:
        member = _membership_row(conn, first)
        shown = rounds._instances(conn, [member.id])[member.id]
    assert [i["instance"] for i in shown] == [first.instance]
