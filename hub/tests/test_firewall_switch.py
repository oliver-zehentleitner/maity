"""docs/api.md §9.6, "The switch" (req-5tngzfgp3nne o2): `MAITY_AGENT_FIREWALL`, off by default.

Off, group chats and work messages reach as before the gate: no agent waits, nothing is held,
no request is filed, a deny entry stops no one, and marks stored while it was on (or by
revision 20261113010000 in 0.1.0a6) are kept and read as no one waiting; the entries stay
editable. On, a start judges every open chat once (`chat_gate.switch_on`): each agent of another
side waits unless an allow entry covers the pair, each owner whose agent waits gets one request,
and a second start changes nothing.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, update

from maity_hub import app as hub_app
from maity_hub import chat_gate, chat_request
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from tests import flow
from tests.conftest import ClientFactory
from tests.test_chat_gate import BASE, add, allow, create, item, say, view
from tests.test_work_gate import PROJECT, human, send


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """The hub as installed: the switch at its default, off."""
    return replace(settings, agent_firewall=False)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    found = flow.human(make_client, migrated)
    flow.project(found)
    return found


@pytest.fixture
def sides(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> dict[str, Any]:
    """`other` (admin) owns `theirs` and `trusted`; `writer`, a plain member, writes."""
    other = human(make_client, migrated, "other", "admin")
    writer = human(make_client, migrated, "writer", "member")
    return {
        "other": other,
        "writer": writer,
        "theirs": flow.agent(make_client, other),
        "trusted": flow.agent(make_client, other),
    }


def marks(engine: Engine, chat_id: str) -> dict[str, tuple[Any, bool]]:
    """`waiting_for` and `waiting` of each agent's stay in the chat, as stored."""
    p, m = t.conversation_participant.c, t.membership.c
    with engine.connect() as conn:
        rows = conn.execute(
            select(m.agent_id, p.waiting_for, p.waiting)
            .join(t.membership, m.id == p.membership_id)
            .where(p.conversation_id == chat_id, p.here.is_(True), m.agent_id.is_not(None))
        ).all()
    return {r.agent_id: (r.waiting_for, bool(r.waiting)) for r in rows}


def mark(engine: Engine, chat_id: str, agent_id: str, sides: list[str]) -> None:
    """What 0.1.0a6's data step left on a stay."""
    p, m = t.conversation_participant.c, t.membership.c
    with engine.begin() as conn:
        membership_id = conn.execute(select(m.id).where(m.agent_id == agent_id)).scalar_one()
        conn.execute(
            update(t.conversation_participant)
            .where(p.conversation_id == chat_id, p.membership_id == membership_id)
            .values(waiting_for=sides, waiting=True)
        )


def requests_to(engine: Engine, human_id: str) -> list[Any]:
    """The hub's chat-access requests to the human, open or not."""
    r = t.request.c
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.request).where(r.to_human == human_id, r.filed_by == "hub").order_by(r.id)
        ).all()
    return [x for x in rows if (x.proposal or {}).get("kind") == chat_request.KIND]


def updated(engine: Engine) -> int:
    with engine.connect() as conn:
        found: int = conn.execute(
            select(func.count())
            .select_from(t.event)
            .where(t.event.c.kind == "conversation_updated")
        ).scalar_one()
    return found


def start(engine: Engine, settings: Settings, on: bool) -> None:
    """A hub start with the switch as given (`app.start_once`)."""
    hub_app.start_once(engine, replace(settings, agent_firewall=on))


# --- the setting -----------------------------------------------------------------------


def test_the_setting_is_off_by_default_and_on_or_off_only() -> None:
    assert Settings.from_env({}).agent_firewall is False
    assert Settings.from_env({"MAITY_AGENT_FIREWALL": "off"}).agent_firewall is False
    assert Settings.from_env({"MAITY_AGENT_FIREWALL": "on"}).agent_firewall is True
    with pytest.raises(ConfigError, match="MAITY_AGENT_FIREWALL"):
        Settings.from_env({"MAITY_AGENT_FIREWALL": "yes"})


def test_the_app_takes_the_switch_from_the_settings(
    make_client: ClientFactory, settings: Settings
) -> None:
    make_client()
    assert chat_gate.ON is False
    make_client(agent_firewall=True)
    assert chat_gate.ON is True


# --- off -------------------------------------------------------------------------------


def test_off_an_agent_of_another_owner_takes_part_at_once(
    owner: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, other = sides["theirs"], sides["other"]
    created = create(owner, theirs.id)
    assert created.status_code == 201, created.text
    chat = created.json()
    assert "waiting_for" not in item(chat, theirs.id)
    assert view(theirs, chat["id"]).status_code == 200
    posted = say(theirs, chat["id"], "hello")
    assert posted.status_code == 201, posted.text
    assert chat["id"] in [i["id"] for i in theirs.get(BASE).json()["items"]]
    assert marks(migrated, chat["id"]) == {theirs.id: (None, False)}
    assert requests_to(migrated, other.id) == []
    assert other.get("/me/chat-access").json()["allow"] == []  # an add writes no yes


def test_off_the_entries_stay_editable_and_a_deny_stops_no_one(
    owner: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    allow(other, agents=[sides["trusted"].id], owner_id=owner.id, their_human=True)
    denied = other.post("/me/chat-access/deny", {"agents": [theirs.id], "human_id": writer.id})
    assert denied.status_code == 201, denied.text
    listed = other.get("/me/chat-access").json()
    assert len(listed["allow"]) == 1 and len(listed["deny"]) == 1
    chat = create(owner, theirs.id, writer.id)
    assert chat.status_code == 201, chat.text  # on, `chat_denied`
    room = create(owner, sides["trusted"].id).json()
    added = add(owner, room["id"], theirs.id)
    assert added.status_code == 200, added.text
    assert add(owner, room["id"], writer.id).status_code == 200
    for chat_id in (chat.json()["id"], room["id"]):
        assert all(v == (None, False) for v in marks(migrated, chat_id).values())
        assert view(theirs, chat_id).status_code == 200
    assert requests_to(migrated, other.id) == []


def test_off_a_notice_a_request_and_a_ticker_item_are_held_for_no_one(
    sides: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    sent = send(writer, theirs.id)
    assert sent["payload"]["held"] == []
    with migrated.connect() as conn:
        audience = conn.execute(
            select(t.event.c.audience).where(t.event.c.seq == sent["seq"])
        ).scalar_one()
    assert f"member:{theirs.id}" in audience and f"held:{theirs.id}" not in audience
    asked = writer.post(
        f"{PROJECT}/requests", {"class": "decision", "title": "Which way?", "to": theirs.id}
    )
    assert asked.status_code == 201, asked.text
    assert asked.json()["held"] == []
    poster = human(make_client, migrated, "poster", "ops")
    posted = poster.post(
        f"{PROJECT}/ticker",
        {"type": "note", "text": "Staging is down.", "to": [f"member:{theirs.id}"]},
    )
    assert posted.status_code == 201, posted.text
    assert theirs.id not in posted.json()["payload"].get("held", [])
    assert requests_to(migrated, other.id) == []


def test_off_marks_from_before_are_kept_and_inert(
    owner: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    """A hub that ran 0.1.0a6 keeps the marks its revision wrote; off, nothing reads them."""
    theirs, other = sides["theirs"], sides["other"]
    chat = create(owner, theirs.id).json()
    mark(migrated, chat["id"], theirs.id, [owner.id])
    shown = view(theirs, chat["id"])
    assert shown.status_code == 200, shown.text
    assert "waiting_for" not in item(shown.json(), theirs.id)
    assert say(theirs, chat["id"], "hello").status_code == 201
    said = say(owner, chat["id"], "and you?").json()
    read = theirs.get(f"{BASE}/{chat['id']}/messages").json()["items"]
    assert said["seq"] in [m["seq"] for m in read]
    with migrated.begin() as conn:
        chat_request.sweep_owners(conn)
        chat_request.sync(conn, other.id)
    assert requests_to(migrated, other.id) == []
    assert marks(migrated, chat["id"]) == {theirs.id: ([owner.id], True)}  # kept


# --- switched on -----------------------------------------------------------------------


def test_switching_on_marks_honours_allow_entries_and_files_one_request(
    owner: flow.Human, sides: dict[str, Any], migrated: Engine, settings: Settings
) -> None:
    """A fresh install: nothing marked, then a start with the switch on."""
    theirs, trusted, other = sides["theirs"], sides["trusted"], sides["other"]
    allow(other, agents=[trusted.id], owner_id=owner.id, their_human=True)
    chat = create(owner, theirs.id, trusted.id).json()
    assert marks(migrated, chat["id"]) == {theirs.id: (None, False), trusted.id: (None, False)}
    start(migrated, settings, on=True)
    assert chat_gate.ON is True
    assert marks(migrated, chat["id"]) == {
        theirs.id: ([owner.id], True),
        trusted.id: ([], False),
    }
    [request] = requests_to(migrated, other.id)
    assert request.status == "open" and request.proposal["side"] == owner.id
    assert view(theirs, chat["id"]).status_code == 404  # it waits, as the gate has it
    assert view(trusted, chat["id"]).status_code == 200
    # A restart, or a second pod starting: nothing more is written or filed.
    seen = updated(migrated)
    start(migrated, settings, on=True)
    assert marks(migrated, chat["id"]) == {
        theirs.id: ([owner.id], True),
        trusted.id: ([], False),
    }
    assert [r.id for r in requests_to(migrated, other.id)] == [request.id]
    assert updated(migrated) == seen


def test_switching_on_judges_marks_from_before_again(
    owner: flow.Human, sides: dict[str, Any], migrated: Engine, settings: Settings
) -> None:
    """An instance that ran 0.1.0a6: every agent marked, whatever the entries. A start with
    the switch on admits the one an allow entry covers and asks once for the other."""
    theirs, trusted, other = sides["theirs"], sides["trusted"], sides["other"]
    chat = create(owner, theirs.id, trusted.id).json()
    for agent in (theirs, trusted):
        mark(migrated, chat["id"], agent.id, [owner.id])
    allow(other, agents=[trusted.id], owner_id=owner.id, their_human=True)
    start(migrated, settings, on=True)
    assert marks(migrated, chat["id"]) == {
        theirs.id: ([owner.id], True),
        trusted.id: ([], False),
    }
    [request] = requests_to(migrated, other.id)
    assert request.status == "open"
    start(migrated, settings, on=True)
    assert [r.id for r in requests_to(migrated, other.id)] == [request.id]


def test_switching_on_keeps_an_open_request_and_withdraws_none_off(
    owner: flow.Human, sides: dict[str, Any], migrated: Engine, settings: Settings
) -> None:
    """A request open from a time the switch was on stays as it is while it is off, and the
    next start with it on finds it instead of filing another."""
    theirs, other = sides["theirs"], sides["other"]
    chat = create(owner, theirs.id).json()
    start(migrated, settings, on=True)
    [request] = requests_to(migrated, other.id)
    start(migrated, settings, on=False)
    assert chat_gate.ON is False
    with migrated.begin() as conn:
        chat_request.sweep_owners(conn)
    assert [(r.id, r.status) for r in requests_to(migrated, other.id)] == [(request.id, "open")]
    assert view(theirs, chat["id"]).status_code == 200  # the mark is inert
    start(migrated, settings, on=True)
    assert [(r.id, r.status) for r in requests_to(migrated, other.id)] == [(request.id, "open")]
    assert view(theirs, chat["id"]).status_code == 404


def test_switched_on_the_gate_holds_as_before(
    sides: dict[str, Any], migrated: Engine, settings: Settings
) -> None:
    theirs, writer = sides["theirs"], sides["writer"]
    start(migrated, settings, on=True)
    assert send(writer, theirs.id)["payload"]["held"] == [theirs.id]
    asked = writer.post(
        f"{PROJECT}/requests", {"class": "decision", "title": "Which way?", "to": theirs.id}
    )
    assert asked.status_code == 201, asked.text
    assert asked.json()["held"] == [theirs.id]


def test_two_hubs_switching_on_at_once_mark_and_ask_once(
    owner: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    """Several pods start together: each settles the same chats; the project lock orders
    them, the second sees what the first wrote, and the request is filed once."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("two writers at once need a server database; SQLite serialises them")
    import threading

    theirs, other = sides["theirs"], sides["other"]
    chats = [create(owner, theirs.id).json()["id"] for _ in range(3)]
    chat_gate.configure(True)
    failed: list[BaseException] = []

    def run() -> None:
        try:
            chat_gate.switch_on(migrated)
        except BaseException as error:  # noqa: BLE001 — reported below
            failed.append(error)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert failed == []
    for chat_id in chats:
        assert marks(migrated, chat_id) == {theirs.id: ([owner.id], True)}
    [request] = requests_to(migrated, other.id)
    assert request.status == "open"


def entries_of(engine: Engine, human_id: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.chat_access).where(t.chat_access.c.human_id == human_id)).all()
        )


@pytest.mark.parametrize(
    ("reply", "chat_access", "kind", "their_human"),
    [
        ("allow_always", None, "allow", False),
        ("allow_always", {"their_human": True}, "allow", True),
        ("block", None, "deny", None),
    ],
)
def test_off_an_answer_to_a_request_still_open_writes_its_entries(
    owner: flow.Human,
    sides: dict[str, Any],
    make_client: ClientFactory,
    migrated: Engine,
    settings: Settings,
    reply: str,
    chat_access: dict[str, Any] | None,
    kind: str,
    their_human: bool | None,
) -> None:
    """v5vp on #1842: a request filed while the switch was on, with no held message, answered
    after it was switched off: the answer names the agents it was filed for from the stored
    marks and writes the owner's entries, as with the switch on; no agent leaves a chat."""
    theirs, other = sides["theirs"], sides["other"]
    mine = flow.agent(make_client, owner)
    chat = create(owner, theirs.id, mine.id).json()
    start(migrated, settings, on=True)
    [request] = requests_to(migrated, other.id)
    assert request.proposal.get("held", []) == []
    start(migrated, settings, on=False)
    shown = other.get(f"/requests/{request.id}").json()
    assert [a["id"] for a in shown["chat_access_request"]["agents"]] == [theirs.id]
    body: dict[str, Any] = {"reply_id": reply}
    if chat_access is not None:
        body["chat_access"] = chat_access
    answered = other.post(f"/requests/{request.id}/answer", body)
    assert answered.status_code == 200, answered.text
    [entry] = entries_of(migrated, other.id)
    assert entry.kind == kind and entry.owner_id == owner.id
    if kind == "allow":
        listed = other.get("/me/chat-access").json()["allow"]
        assert [(e["agents"], e["their_agents"], e["their_human"]) for e in listed] == [
            ([theirs.id], [mine.id], their_human)
        ]
        assert listed[0]["duration"] is None
    else:
        [deny] = other.get("/me/chat-access").json()["deny"]
        assert deny["agents"] == [theirs.id]
    assert view(theirs, chat["id"]).status_code == 200  # still in it, the switch is off
