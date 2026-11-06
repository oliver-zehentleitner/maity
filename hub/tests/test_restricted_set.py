"""docs/api.md §6.1 "Restricted access" and §6.4 "Restricted text", the part after the routes:
the setting (who may change it, its refusals, how it is served per reader), the change event
and who reads it, the five ways into the set and an owner change, the notices and the
`guide_role` sentence."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, events, restricted
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_restricted_text import MARKER, _card, _project, _set, _write
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def _member(
    make_client: ClientFactory, migrated: Engine, handle: str, trust: str = "member"
) -> flow.Human:
    who = flow.human(make_client, migrated, handle)
    factory.membership(migrated, _project(migrated).id, "coder", trust=trust, human_id=who.id)
    return who


def _membership(engine: Engine, principal: str) -> int:
    with engine.connect() as conn:
        found: int = conn.execute(
            select(t.membership.c.id).where(
                (t.membership.c.human_id == principal) | (t.membership.c.agent_id == principal),
                t.membership.c.active.is_(True),
            )
        ).scalar_one()
        return found


def _setting(who: Any, value: Any) -> Any:
    return who.patch(PROJECT, {"settings": {"restricted_access": value}})


def _served(who: Any) -> Any:
    response = who.get(PROJECT)
    assert response.status_code == 200, response.text
    return response.json()["settings"]["restricted_access"]


def _events(who: Any, kind: str | None = None) -> list[dict[str, Any]]:
    response = who.get(f"{PROJECT}/events", params={"after": 0, "limit": 200})
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return [e for e in items if kind is None or e["kind"] == kind]


def _set_events(who: Any) -> list[dict[str, Any]]:
    return [e for e in _events(who, "restricted_changed") if e["payload"]["task_id"] is None]


def _notices(who: flow.Human) -> list[dict[str, Any]]:
    response = who.get("/me/notifications", params={"limit": 50})
    assert response.status_code == 200, response.text
    return [
        n
        for n in response.json()["items"]
        if n["title"] in ("A restricted text changed", "The restricted-access set changed")
    ]


def _refusal(response: Any) -> dict[str, str]:
    assert response.status_code == 400, response.text
    fields: dict[str, str] = response.json()["error"]["details"]["fields"]
    return fields


# --- the setting ----------------------------------------------------------------------------


def test_the_setting_is_checked_and_stored_whole(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = _member(make_client, migrated, "anna")
    guest = _member(make_client, migrated, "gast", trust="guest")
    outsider = factory.human(migrated, "outsider")
    project = _project(migrated)
    orphan = factory.agent(migrated, project.id, outsider)  # its owner is no member
    field = "settings.restricted_access"
    assert _refusal(_setting(owner, {"mode": "everyone", "members": []})) == {
        f"{field}.mode": "unknown_mode"
    }
    many = [f"hum-{n:012d}" for n in range(201)]
    assert _refusal(_setting(owner, {"mode": "all_except", "members": many})) == {
        f"{field}.members": "too_many"
    }
    assert _refusal(_setting(owner, {"mode": "all_except", "members": [anna.id, anna.id]})) == {
        f"{field}.members": "duplicate"
    }
    refused = _refusal(
        _setting(
            owner,
            {"mode": "nobody_except", "members": [outsider, guest.id, orphan.agent_id, anna.id]},
        )
    )
    assert refused == {
        f"{field}.members.{outsider}": "not_a_member",
        f"{field}.members.{guest.id}": "guest",
        f"{field}.members.{orphan.agent_id}": "owner_not_a_member",
    }
    # Under all_except an agent whose owner is no member may be listed: it stays left out.
    assert _setting(owner, {"mode": "all_except", "members": [orphan.agent_id]}).status_code == 200
    # `included` and `cards_with_text` are the hub's: a read sent back is accepted.
    sent = {"mode": "nobody_except", "members": [anna.id], "included": True, "cards_with_text": 9}
    saved = _setting(owner, sent)
    assert saved.status_code == 200, saved.text
    with migrated.connect() as conn:
        stored = conn.execute(select(t.project.c.settings)).scalar_one()["restricted_access"]
    assert stored == {"mode": "nobody_except", "members": [anna.id]}
    # An id the stored list holds passes after its member left; a new one would not.
    anna_m = _membership(migrated, anna.id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == anna_m)
            .values(active=None, removed_at=clock.now())
        )
    assert _setting(owner, {"mode": "nobody_except", "members": [anna.id]}).status_code == 200
    assert _setting(owner, None).status_code == 200
    assert _served(owner) is None  # null restores the closed default


def test_only_a_human_with_project_admin_changes_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = _member(make_client, migrated, "anna")
    admin_agent = flow.agent(make_client, owner, trust="admin", role="coder")
    value = {"mode": "all_except", "members": []}
    refused = _setting(admin_agent, value)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "humans_only", refused.text
    assert _setting(anna, value).status_code == 403
    assert _served(owner) is None


def test_reading_the_setting_per_reader(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = _member(make_client, migrated, "anna")
    bert = _member(make_client, migrated, "bert")
    agent = flow.agent(make_client, owner)
    assert _served(anna) is None
    card = _card(owner)
    assert _setting(owner, {"mode": "nobody_except", "members": [anna.id]}).status_code == 200
    _write(anna, card["id"], MARKER)
    full = {"mode": "nobody_except", "members": [anna.id], "cards_with_text": 1}
    # The admin outside the set reads the list and the count, never the cards.
    assert _served(owner) == {**full, "included": False}
    assert _served(anna) == {**full, "included": True}
    assert _served(bert) == {"mode": "nobody_except", "included": False}
    assert _served(agent) == {"mode": "nobody_except", "included": False}
    listed = bert.get("/projects").json()["items"]
    assert [p["settings"]["restricted_access"] for p in listed] == [
        {"mode": "nobody_except", "included": False}
    ]
    # project_updated is served per reader at read, in the event stream too.
    [mine] = [
        e
        for e in _events(owner, "project_updated")
        if "settings.restricted_access" in e["payload"]["fields"]
    ]
    assert mine["payload"]["fields"]["settings.restricted_access"] == {
        "mode": "nobody_except",
        "members": [anna.id],
    }
    [theirs] = [
        e
        for e in _events(bert, "project_updated")
        if "settings.restricted_access" in e["payload"]["fields"]
    ]
    assert theirs["payload"]["fields"]["settings.restricted_access"] == {
        "mode": "nobody_except",
        "included": False,
    }
    assert anna.id not in json.dumps(_events(bert))


# --- the change event ---------------------------------------------------------------------


def test_a_change_is_read_by_the_set_alone_and_never_holds_the_text(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = _member(make_client, migrated, "anna")
    bert = _member(make_client, migrated, "bert")
    card = _card(owner)
    assert (
        _setting(owner, {"mode": "nobody_except", "members": [anna.id, bert.id]}).status_code == 200
    )
    _write(anna, card["id"], MARKER)
    [event] = _events(bert, "restricted_changed")[-1:]
    assert event["audience"] == [f"restricted:{card['id']}"]
    assert event["payload"]["task_id"] == card["id"] and event["payload"]["action"] == "set"
    assert event["payload"]["version"] == 1 and event["payload"]["by"]["id"] == anna.id
    assert set(event["payload"]) == {"task_id", "version", "action", "by", "at"}
    assert MARKER not in json.dumps(event)
    # Not the see-all: the owner outside the set reads none of it.
    assert [e for e in _events(owner, "restricted_changed") if e["payload"]["task_id"]] == []
    # Read again at every read: out of the set, out of its own events too.
    assert _setting(owner, {"mode": "nobody_except", "members": [bert.id]}).status_code == 200
    assert _events(anna, "restricted_changed") == []
    assert [e["seq"] for e in _events(bert, "restricted_changed") if e["payload"]["task_id"]] == [
        event["seq"]
    ]


def test_a_change_wakes_the_agents_in_the_set_but_the_writer(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    project = _project(migrated)
    writer = factory.agent(migrated, project.id, owner.id, "coder")
    reader = factory.agent(migrated, project.id, owner.id, "coder", instance="rdr1")
    outside = factory.agent(migrated, project.id, owner.id, "coder", instance="out1")
    card = _card(owner)
    _set(migrated, "nobody_except", [writer.agent_id, reader.agent_id])
    client = make_client()
    written = client.put(
        f"/api/v1{PROJECT}/tasks/{card['id']}/restricted",
        content=json.dumps({"text": "x", "base_version": 0}),
        headers={
            "Authorization": f"Bearer {writer.value}",
            "Idempotency-Key": "restricted-wake-0000001",
        },
    )
    assert written.status_code == 200, written.text

    def woken(agent: Any) -> list[str]:
        with migrated.connect() as conn:
            row = conn.execute(
                select(t.membership).where(t.membership.c.id == agent.membership_id)
            ).one()
            rows, _ = events.read_waking(conn, project.id, row, agent.agent_id, 0, 100)
        return [r.kind for r in rows if r.kind == "restricted_changed"]

    assert woken(reader) == ["restricted_changed"]
    assert woken(writer) == []  # its own echo
    assert woken(outside) == []


# --- the ways into the set ----------------------------------------------------------------


def test_widening_the_setting_is_told_to_the_set(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = _member(make_client, migrated, "anna")
    assert _setting(owner, {"mode": "nobody_except", "members": [anna.id]}).status_code == 200
    assert (
        _setting(owner, {"mode": "nobody_except", "members": [anna.id, owner.id]}).status_code
        == 200
    )
    first, entered = _set_events(anna)
    assert [m["id"] for m in first["payload"]["members"]] == [anna.id]  # opening it, too
    assert entered["payload"]["action"] == "entered" and entered["payload"]["cause"] == "setting"
    assert [m["id"] for m in entered["payload"]["members"]] == [owner.id]
    assert entered["payload"]["by"]["id"] == owner.id
    # Narrowing tells nobody.
    assert _setting(owner, {"mode": "nobody_except", "members": [anna.id]}).status_code == 200
    assert len(_set_events(anna)) == 2


def test_a_join_under_all_except_enters_the_set(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = _member(make_client, migrated, "anna")
    _set(migrated, "all_except", [])
    agent = flow.agent(make_client, owner)
    [entered] = _set_events(anna)
    assert entered["payload"]["cause"] == "joined"
    [member] = entered["payload"]["members"]
    assert member["id"] == agent.id and member["owner"]["id"] == owner.id
    assert entered["payload"]["by"]["id"] == owner.id  # who made the join
    with migrated.connect() as conn:
        listed = set(
            conn.execute(
                select(t.restricted_event_list.c.membership_id).where(
                    t.restricted_event_list.c.seq == entered["seq"]
                )
            ).scalars()
        )
    assert _membership(migrated, agent.id) in listed  # the list is the set after the change


def test_raising_a_guest_and_lifting_an_isolation_enter_the_set(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = _member(make_client, migrated, "anna")
    guest = _member(make_client, migrated, "gast", trust="guest")
    agent = flow.agent(make_client, owner)
    _set(migrated, "all_except", [])
    raised = owner.patch(f"{PROJECT}/members/{guest.id}", {"trust": "member"})
    assert raised.status_code == 200, raised.text
    isolated = owner.post(f"{PROJECT}/members/{agent.id}/isolate", {"reason": "a check"})
    assert isolated.status_code == 200, isolated.text
    lifted = owner.delete(f"{PROJECT}/members/{agent.id}/isolate")
    assert lifted.status_code == 200, lifted.text
    causes = [
        (e["payload"]["cause"], [m["id"] for m in e["payload"]["members"]])
        for e in _set_events(anna)
    ]
    assert causes == [("trust_raised", [guest.id]), ("isolation_ended", [agent.id])]


def test_an_owner_change_takes_a_listed_agent_off_under_nobody_except(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = _member(make_client, migrated, "anna")
    agent = flow.agent(make_client, owner)
    _set(migrated, "nobody_except", [anna.id, agent.id])
    with events.transaction(migrated) as conn:
        restricted.owner_changed(conn, agent.id, events.Actor(None))
    with migrated.connect() as conn:
        stored = conn.execute(select(t.project.c.settings)).scalar_one()["restricted_access"]
    assert stored == {"mode": "nobody_except", "members": [anna.id]}
    [left] = _set_events(anna)
    assert left["payload"]["action"] == "left" and left["payload"]["cause"] == "owner_changed"
    assert left["payload"]["by"] == "hub"
    assert [m["id"] for m in left["payload"]["members"]] == [agent.id]
    # An agent that was not in the set leaves nothing but the project_updated.
    _set(migrated, "nobody_except", [anna.id, agent.id])
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == agent.id)
            .values(isolated_since=clock.now())
        )
    with events.transaction(migrated) as conn:
        restricted.owner_changed(conn, agent.id, events.Actor(None))
    assert len(_set_events(anna)) == 1


# --- the notices ----------------------------------------------------------------------------


def test_the_notice_goes_to_the_humans_in_the_set_once_in_ten_minutes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = _member(make_client, migrated, "anna")
    bert = _member(make_client, migrated, "bert")
    card = _card(owner)
    _set(migrated, "nobody_except", [anna.id, bert.id])
    _write(anna, card["id"], MARKER)
    _write(anna, card["id"], MARKER + " again")
    [notice] = _notices(bert)
    assert notice["title"] == "A restricted text changed"
    assert notice["target"] == {"type": "task", "id": card["id"]}
    assert MARKER not in json.dumps(notice) and card["title"] not in json.dumps(notice)
    assert _notices(anna) == []  # the writer is not told of its own change
    assert _notices(owner) == []  # nor an owner outside the set
    with migrated.begin() as conn:  # ten minutes later another change is told again
        conn.execute(
            update(t.account_record)
            .where(t.account_record.c.type == "restricted_changed")
            .values(at=clock.now() - timedelta(minutes=11))
        )
    _write(anna, card["id"], MARKER)
    assert len(_notices(bert)) == 2
    # Out of the set, the notices drop out.
    _set(migrated, "nobody_except", [anna.id])
    assert _notices(bert) == []


def test_the_set_notice_names_no_member_and_skips_those_it_names(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = _member(make_client, migrated, "anna")
    assert _setting(owner, {"mode": "nobody_except", "members": [anna.id]}).status_code == 200
    assert (
        _setting(owner, {"mode": "nobody_except", "members": [anna.id, owner.id]}).status_code
        == 200
    )
    [notice] = _notices(anna)
    assert notice["title"] == "The restricted-access set changed"
    assert notice["target"] == {"type": "settings", "id": "restricted_access"}
    assert owner.id not in json.dumps(notice) and anna.id not in json.dumps(notice)
    assert _notices(owner) == []  # the member who entered is not told of itself


# --- the guide --------------------------------------------------------------------------------


def test_an_agent_in_the_set_is_told_to_keep_the_text_where_it_is(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)

    def role_guide() -> str:
        response = agent.resume()
        assert response.status_code == 200, response.text
        found: str = response.json()["membership"]["guide"]["role"] or ""
        return found

    assert "restricted text" not in role_guide()
    _set(migrated, "nobody_except", [agent.id])
    assert role_guide().endswith("it stays in the restricted text.")
    _set(migrated, "nobody_except", [])
    assert "restricted text" not in role_guide()


# --- more ways in, and the step-up ----------------------------------------------------------


def test_accepting_an_invitation_and_an_organisation_keep_enter_the_set(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub import org_projects
    from tests.test_invitations import accept, issue, token_of

    anna = _member(make_client, migrated, "anna")
    _set(migrated, "all_except", [])
    invited = issue(owner, trust="member", role="coder")
    bert = flow.human(make_client, migrated, "bert")
    assert accept(bert, token_of(invited)).status_code == 201
    carla = factory.human(migrated, "carla")
    project = _project(migrated)
    with events.transaction(migrated) as conn:
        org_projects.keep_owner(conn, project, carla, owner.id)
    causes = [
        (e["payload"]["cause"], [m["id"] for m in e["payload"]["members"]], e["payload"]["by"])
        for e in _set_events(anna)
    ]
    assert [(c, m, b["id"]) for c, m, b in causes] == [
        ("joined", [bert.id], bert.id),
        ("joined", [carla], owner.id),
    ]


def test_changing_the_setting_asks_for_the_second_factor(
    make_client: ClientFactory, migrated: Engine, moment: Any
) -> None:
    from tests.test_transfer_step_up import reason, verified
    from tests.test_two_factor import enrol, signed_in

    owner = signed_in(make_client, migrated)
    secret, _ = enrol(owner, moment)
    flow.project(owner, "maity")
    moment.move(minutes=11)
    value = {"mode": "nobody_except", "members": [owner.id]}
    assert reason(_setting(owner, value)) == (403, "step_up_required")
    assert _served(owner) is None
    verified(owner, secret, moment)
    assert _setting(owner, value).status_code == 200


# --- counter-tests for review findings (e5zv 79591, spq4 79602) -----------------------------


def test_an_admin_agent_outside_the_set_reads_no_members(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """e5zv 79591 / restricted.py reads_members: kind == "human". An admin-trust agent
    outside the set gets only {mode, included}, never members or cards_with_text (§6.1)."""
    from types import SimpleNamespace

    anna = _member(make_client, migrated, "anna")
    admin_agent = flow.agent(make_client, owner, trust="admin", role="coder")
    card = _card(owner)
    assert _setting(owner, {"mode": "nobody_except", "members": [anna.id]}).status_code == 200
    _write(anna, card["id"], MARKER)
    assert _served(admin_agent) == {"mode": "nobody_except", "included": False}
    [theirs] = [
        e
        for e in _events(admin_agent, "project_updated")
        if "settings.restricted_access" in e["payload"]["fields"]
    ]
    assert theirs["payload"]["fields"]["settings.restricted_access"] == {
        "mode": "nobody_except",
        "included": False,
    }
    assert anna.id not in json.dumps(_events(admin_agent))
    # The kind gate itself: a stub that would pass may("project:admin") still fails as an agent.
    with migrated.connect() as conn:
        stub = SimpleNamespace(
            kind="agent",
            id=_membership(migrated, admin_agent.id),
            may=lambda scope: scope == "project:admin",
        )
        assert restricted.reads_members(conn, _project(migrated), stub) is False


def test_restricted_wakes_are_projected_to_the_reader_alone(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """e5zv 79591 / spq4 79602 / views._wakes: the "restricted:" prefix. A multi-instance
    team in the set populates row.wakes; another reader in the set must not see that team's
    wakes on the served restricted_changed (§6.4)."""
    from maity_hub import listening

    anna = _member(make_client, migrated, "anna")
    lead = flow.agent(make_client, owner)
    teamed = owner.patch(
        f"{PROJECT}/members/{lead.id}",
        {"team": {"max_instances": 2, "wake": "lead", "lead_instance": lead.instance}},
    )
    assert teamed.status_code == 200, teamed.text
    sibling = flow.agent(make_client, owner, agent={"id": lead.id}, new_instance=True)
    reader = flow.agent(make_client, owner)
    for agent in (lead, sibling, reader):
        assert agent.resume().status_code == 200
    card = _card(owner)
    _set(migrated, "nobody_except", [anna.id, lead.id, reader.id])
    session_id = lead.resume().json()["session"]["id"]
    wait = listening.opened(session_id)
    try:
        _write(anna, card["id"], MARKER)
        with migrated.connect() as conn:
            row = conn.execute(
                select(t.event)
                .where(t.event.c.kind == "restricted_changed")
                .order_by(t.event.c.seq.desc())
            ).first()
        assert row is not None and row.wakes == {lead.id: [lead.instance]}
        [event] = [
            e
            for e in _events(reader, "restricted_changed")
            if e["payload"].get("task_id") == card["id"]
        ]
        assert "wakes" not in event
        [own] = [
            e
            for e in _events(lead, "restricted_changed")
            if e["payload"].get("task_id") == card["id"]
        ]
        assert own.get("wakes") == [f"{lead.id}#{lead.instance}"]
    finally:
        listening.closed(session_id, wait)


def test_a_set_change_wakes_no_agent_in_the_set(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """e5zv 79591 / spq4 79602 / events.wakes: task_id is None. A widening that emits
    restricted:set must not wake an agent already in the set (§6.4)."""
    project = _project(migrated)
    anna = _member(make_client, migrated, "anna")
    agent = flow.agent(make_client, owner)
    assert (
        _setting(owner, {"mode": "nobody_except", "members": [anna.id, agent.id]}).status_code
        == 200
    )
    assert (
        _setting(
            owner, {"mode": "nobody_except", "members": [anna.id, agent.id, owner.id]}
        ).status_code
        == 200
    )
    entered = _set_events(anna)[-1]
    assert entered["payload"]["task_id"] is None and entered["payload"]["action"] == "entered"

    def woken() -> list[str]:
        with migrated.connect() as conn:
            row = conn.execute(
                select(t.membership).where(t.membership.c.agent_id == agent.id)
            ).one()
            rows, _ = events.read_waking(conn, project.id, row, agent.id, 0, 100)
        return [r.kind for r in rows if r.kind == "restricted_changed"]

    assert woken() == []


def test_a_late_joiner_does_not_see_an_old_restricted_notice(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """spq4 79602 / _RestrictedNotices.reads: restricted_event_list row. A human who joins
    the set after a change must not see that change's notice, even with a planted record."""
    from maity_hub.notifications import records

    anna = _member(make_client, migrated, "anna")
    bert = _member(make_client, migrated, "bert")
    card = _card(owner)
    _set(migrated, "nobody_except", [anna.id])
    _write(anna, card["id"], MARKER)
    [event] = _events(anna, "restricted_changed")[-1:]
    project = _project(migrated)
    with events.transaction(migrated) as conn:
        records.write(
            conn,
            bert.id,
            "restricted_changed",
            {"project_id": project.id, "task_id": card["id"], "seq": event["seq"]},
        )
    _set(migrated, "nobody_except", [anna.id, bert.id])
    assert _notices(bert) == []
    assert _notices(anna) == []  # anna wrote it


def test_a_late_joiner_does_not_see_an_old_restricted_event(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """akbp 82280 / vuur 82282 / restricted.readable_seqs: membership_id predicate. A human
    admitted after a card restricted_changed must not read that earlier event from history
    (the private-list row was written for members in the set at write time)."""
    anna = _member(make_client, migrated, "anna")
    bert = _member(make_client, migrated, "bert")
    card = _card(owner)
    _set(migrated, "nobody_except", [anna.id])
    _write(anna, card["id"], MARKER)
    [event] = [
        e
        for e in _events(anna, "restricted_changed")
        if e["payload"].get("task_id") == card["id"]
    ][-1:]
    _set(migrated, "nobody_except", [anna.id, bert.id])
    assert [
        e
        for e in _events(bert, "restricted_changed")
        if e["payload"].get("task_id") == card["id"] and e["seq"] == event["seq"]
    ] == []
    assert [
        e["seq"]
        for e in _events(anna, "restricted_changed")
        if e["payload"].get("task_id") == card["id"]
    ] == [event["seq"]]


def test_org_promotion_raises_an_existing_member_into_the_set(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """spq4 79602 / org_projects.keep_owner trust_raised, and routes/orgs set_role's by.
    Promoting an org member who is already a project member under all_except emits entered
    with cause trust_raised and by the promoter (§6.4, §6.26)."""
    from tests.test_org_projects import create, members, owner_joined
    from tests.test_orgs import team

    org, people = team(make_client, migrated, owner)
    assert create(owner, "shop").status_code in (200, 201)
    admin = people["admin"]
    joined = owner_joined(migrated)
    with migrated.begin() as conn:
        pid = conn.execute(select(t.project.c.id).where(t.project.c.slug == "shop")).scalar_one()
        conn.execute(
            t.membership.insert().values(
                project_id=pid,
                human_id=admin.id,
                trust="guest",
                role="coder",
                role_base="coder",
                areas=["/"],
                capabilities=[],
                joined_at=joined,
                last_seen_at=joined,
            )
        )
        # all_except: a guest is out of the set; the org raise puts them in as owner.
        conn.execute(
            update(t.project)
            .where(t.project.c.id == pid)
            .values(settings={"restricted_access": {"mode": "all_except", "members": []}})
        )
    promoted = owner.patch(f"/orgs/oz-team/members/{admin.id}", {"role": "owner"})
    assert promoted.status_code == 200, promoted.text
    assert members(owner, "shop")["team-admin"]["trust"] == "owner"
    response = owner.get("/projects/oz-team/shop/events", params={"after": 0, "limit": 200})
    assert response.status_code == 200, response.text
    entered = [
        e
        for e in response.json()["items"]
        if e["kind"] == "restricted_changed" and e["payload"].get("task_id") is None
    ]
    assert len(entered) == 1
    assert entered[0]["payload"]["action"] == "entered"
    assert entered[0]["payload"]["cause"] == "trust_raised"
    assert [m["id"] for m in entered[0]["payload"]["members"]] == [admin.id]
    assert entered[0]["payload"]["by"]["id"] == owner.id


def test_a_transfer_into_an_organisation_names_by_on_entered(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """spq4 79602 / project_names.move_to passes by into org_projects.moved. A transfer that
    lets an organisation owner into the set under all_except names by as the transferrer."""
    from tests.test_org_transfer import members, transfer
    from tests.test_orgs import team

    org, people = team(make_client, migrated, owner)
    flow.project(owner, "shop")
    with migrated.begin() as conn:
        conn.execute(
            update(t.project)
            .where(t.project.c.slug == "shop")
            .values(settings={"restricted_access": {"mode": "all_except", "members": []}})
        )
    moved = transfer(owner, "maintainer/shop", org["id"])
    assert moved.status_code == 200, moved.text
    second = people["owner2"]
    assert members(owner, "oz-team/shop")["team-owner2"]["trust"] == "owner"
    response = owner.get("/projects/oz-team/shop/events", params={"after": 0, "limit": 200})
    assert response.status_code == 200, response.text
    entered = [
        e
        for e in response.json()["items"]
        if e["kind"] == "restricted_changed"
        and e["payload"].get("task_id") is None
        and e["payload"].get("action") == "entered"
        and second.id in [m["id"] for m in e["payload"]["members"]]
    ]
    assert len(entered) == 1
    assert entered[0]["payload"]["cause"] == "joined"
    assert entered[0]["payload"]["by"]["id"] == owner.id


def test_restricted_list_feeds_team_wakes_for_a_narrowed_rule(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """spq4 79602 / events.emit: restricted_list into team_wakes. An agent with a narrowed
    wake rule in the set gets its instances recorded on a card's restricted_changed."""
    from maity_hub import listening

    anna = _member(make_client, migrated, "anna")
    lead = flow.agent(make_client, owner)
    teamed = owner.patch(
        f"{PROJECT}/members/{lead.id}",
        {"team": {"max_instances": 2, "wake": "lead", "lead_instance": lead.instance}},
    )
    assert teamed.status_code == 200, teamed.text
    sibling = flow.agent(make_client, owner, agent={"id": lead.id}, new_instance=True)
    for agent in (lead, sibling):
        assert agent.resume().status_code == 200
    card = _card(owner)
    _set(migrated, "nobody_except", [anna.id, lead.id])
    session_id = lead.resume().json()["session"]["id"]
    wait = listening.opened(session_id)
    try:
        _write(anna, card["id"], MARKER)
        with migrated.connect() as conn:
            row = conn.execute(
                select(t.event)
                .where(t.event.c.kind == "restricted_changed")
                .order_by(t.event.c.seq.desc())
            ).first()
        assert row is not None and row.wakes == {lead.id: [lead.instance]}
    finally:
        listening.closed(session_id, wait)
