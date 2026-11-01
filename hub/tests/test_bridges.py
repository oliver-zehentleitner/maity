"""docs/api.md §2.3, "The bridge": an agent that lends its hands to another agent of the project,
connected by the served agent's owner, across owners only after two consents
(tsk-emy3a9vtqxym)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
PURPOSE = "git for the designer's files"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _project(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def _agent(engine: Engine, human: flow.Human, role: str = "coder") -> str:
    return factory.agent(engine, _project(engine), human.id, role).agent_id


def _member(engine: Engine, handle: str, make_client: ClientFactory, role: str) -> flow.Human:
    human = flow.human(make_client, engine, handle)
    factory.membership(engine, _project(engine), role, human_id=human.id)
    return human


def connect(who: Any, served: str, bridge: str, purpose: str = PURPOSE) -> Any:
    return who.post(f"{PROJECT}/members/{served}/bridges", {"bridge": bridge, "purpose": purpose})


def answer(who: Any, request_id: str, reply: str) -> Any:
    """A personal request, the bridge owner's, on the inbox route."""
    return who.post(f"/requests/{request_id}/answer", {"reply_id": reply})


def answer_project(who: Any, request_id: str, reply: str) -> Any:
    return who.post(f"{PROJECT}/requests/{request_id}/answer", {"reply_id": reply})


def _requests(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.request)
                .where(t.request.c.proposal.is_not(None))
                .order_by(t.request.c.created_at, t.request.c.id)
            )
        )


def _bridges(engine: Engine) -> list[Any]:
    """The live connections; an ended one keeps its row (§12)."""
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.bridge).where(t.bridge.c.live.is_(True)).order_by(t.bridge.c.created_at)
            )
        )


def _fields(response: Any) -> Any:
    return response.json()["error"]["details"]["fields"]


def _reason(response: Any) -> Any:
    return response.json()["error"]["details"].get("reason")


def _cross(
    owner: flow.Human, make_client: ClientFactory, engine: Engine
) -> tuple[flow.Human, str, str]:
    """A friend outside the project, the owner's served agent and the friend's agent."""
    friend = flow.human(make_client, engine, "friend")
    return friend, _agent(engine, owner), _agent(engine, friend)


# --- one owner ------------------------------------------------------------------------------


def test_with_one_owner_the_bridge_exists_at_once_and_both_views_show_it(
    owner: flow.Human, migrated: Engine
) -> None:
    served, bridge = _agent(migrated, owner), _agent(migrated, owner)
    made = connect(owner, served, bridge)
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["id"].startswith("brg-")
    assert (body["served"], body["bridge"], body["purpose"]) == (served, bridge, PURPOSE)
    assert body["cross_owner"] is False and body["created_by"] == owner.id
    view = owner.get(f"{PROJECT}/members/{served}").json()
    assert [(b["member_id"], b["purpose"]) for b in view["bridges"]] == [(bridge, PURPOSE)]
    assert view["bridging_for"] == []
    other = owner.get(f"{PROJECT}/members/{bridge}").json()
    assert [b["member_id"] for b in other["bridging_for"]] == [served]
    with migrated.connect() as conn:
        told = [
            e.payload["id"]
            for e in conn.execute(select(t.event).where(t.event.c.kind == "member_updated"))
            if e.payload.get("changed") == ["bridges"]
        ]
    assert sorted(told) == sorted([served, bridge])


def test_the_rules_refuse_what_is_no_bridge(owner: flow.Human, migrated: Engine) -> None:
    served, bridge = _agent(migrated, owner), _agent(migrated, owner)
    assert _fields(connect(owner, served, served)) == {"bridge": "self"}
    assert _fields(connect(owner, served, owner.id)) == {"bridge": "not_an_agent"}
    assert _fields(connect(owner, served, "agt-nobody")) == {"bridge": "not_a_member"}
    proxy = _agent(migrated, owner, "proxy")
    assert _fields(connect(owner, served, proxy)) == {"bridge": "role"}
    assert _fields(connect(owner, proxy, bridge)) == {"member": "role"}
    assert connect(owner, served, bridge).status_code == 201
    assert _fields(connect(owner, served, bridge)) == {"bridge": "already"}
    too_long = connect(owner, bridge, served, "x" * 201)
    assert too_long.status_code == 400


def test_an_agent_has_at_most_five_bridges(owner: flow.Human, migrated: Engine) -> None:
    served = _agent(migrated, owner)
    for _ in range(5):
        assert connect(owner, served, _agent(migrated, owner)).status_code == 201
    assert _fields(connect(owner, served, _agent(migrated, owner))) == {"member": "too_many"}


def test_only_the_served_agents_owner_connects(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = _member(migrated, "admin", make_client, "admin")
    served, bridge = _agent(migrated, owner), _agent(migrated, owner)
    refused = connect(admin, served, bridge)
    assert (refused.status_code, _reason(refused)) == (403, "agent_owner")
    agent = flow.agent(make_client, owner, role="admin", reports_to=owner.id)
    refused = connect(agent, served, bridge)
    assert (refused.status_code, _reason(refused)) == (403, "humans_only")


def test_a_patch_with_one_owner_changes_the_purpose_at_once(
    owner: flow.Human, migrated: Engine
) -> None:
    served, bridge = _agent(migrated, owner), _agent(migrated, owner)
    bridge_id = connect(owner, served, bridge).json()["id"]
    changed = owner.patch(f"{PROJECT}/members/{served}/bridges/{bridge_id}", {"purpose": "ci"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["purpose"] == "ci"
    missing = owner.patch(f"{PROJECT}/members/{bridge}/bridges/{bridge_id}", {"purpose": "ci"})
    assert missing.status_code == 404


def test_who_ends_a_bridge(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> None:
    coder = _member(migrated, "coder", make_client, "coder")
    served, bridge = _agent(migrated, owner), _agent(migrated, owner)
    bridge_id = connect(owner, served, bridge).json()["id"]
    path = f"{PROJECT}/members/{served}/bridges/{bridge_id}"
    assert coder.delete(path).status_code == 403
    ended = owner.delete(path)
    assert ended.status_code == 200, ended.text
    body = ended.json()  # the connection in its final state (§12)
    assert (body["id"], body["ended_by"], body["end_reason"]) == (
        bridge_id,
        owner.id,
        "bridge_ended",
    )
    assert body["ended_at"] is not None
    assert _bridges(migrated) == []
    assert owner.get(f"{PROJECT}/members/{served}").json()["bridges"] == []
    assert owner.delete(path).status_code == 404  # ended is gone for the route
    again = connect(owner, served, bridge)  # the pair connects again with a new row
    assert again.status_code == 201, again.text
    assert again.json()["id"] != bridge_id


def test_removing_a_member_or_making_it_a_proxy_ends_its_bridges(
    owner: flow.Human, migrated: Engine
) -> None:
    served, first, second = (_agent(migrated, owner) for _ in range(3))
    connect(owner, served, first)
    connect(owner, served, second)
    assert owner.delete(f"{PROJECT}/members/{first}").status_code == 200
    assert len(_bridges(migrated)) == 1
    done = owner.patch(f"{PROJECT}/members/{served}", {"role": "proxy", "trust": "admin"})
    assert done.status_code == 200, done.text
    assert _bridges(migrated) == []


# --- across owners ----------------------------------------------------------------------------


def test_across_owners_an_admin_asker_waits_only_for_the_bridges_owner(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, served, bridge = _cross(owner, make_client, migrated)
    asked = connect(owner, served, bridge)
    assert asked.status_code == 202, asked.text
    body = asked.json()
    assert body["class"] == "consent" and body["to"] == f"human:{friend.id}"
    assert PURPOSE in body["summary"]
    [pending] = _requests(migrated)
    assert pending.proposal["kind"] == "bridge_owner" and pending.personal is True
    assert _bridges(migrated) == []
    assert answer(owner, pending.id, "go").status_code == 404  # only the addressee answers
    done = answer(friend, pending.id, "go")
    assert done.status_code == 200, done.text
    [made] = _bridges(migrated)
    assert made.cross_owner is True and made.purpose == PURPOSE and made.created_by == owner.id


def test_an_asker_without_members_admin_also_needs_the_projects_consent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    coder = _member(migrated, "coder", make_client, "coder")
    friend = flow.human(make_client, migrated, "friend")
    served, bridge = _agent(migrated, coder), _agent(migrated, friend)
    asked = connect(coder, served, bridge)
    assert asked.status_code == 202, asked.text
    first, second = _requests(migrated)
    assert asked.json()["id"] == first.id
    assert (first.proposal["kind"], second.proposal["kind"]) == ("bridge_owner", "bridge_project")
    assert first.proposal["requests"] == second.proposal["requests"] == [first.id, second.id]
    assert answer_project(coder, second.id, "go").status_code == 403  # no members:admin
    assert answer(friend, first.id, "go").status_code == 200
    assert _bridges(migrated) == []  # the project has not answered
    assert answer_project(owner, second.id, "go").status_code == 200
    assert len(_bridges(migrated)) == 1


def test_a_no_to_either_withdraws_the_other(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    coder = _member(migrated, "coder", make_client, "coder")
    friend = flow.human(make_client, migrated, "friend")
    served, bridge = _agent(migrated, coder), _agent(migrated, friend)
    connect(coder, served, bridge)
    first, second = _requests(migrated)
    assert answer_project(owner, second.id, "no").status_code == 200
    with migrated.connect() as conn:
        row = conn.execute(select(t.request).where(t.request.c.id == first.id)).one()
    assert (row.status, row.withdraw_reason) == ("withdrawn", "refused")
    assert _bridges(migrated) == []


def test_a_further_post_supersedes_the_open_request_with_the_new_purpose(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, served, bridge = _cross(owner, make_client, migrated)
    connect(owner, served, bridge)
    again = connect(owner, served, bridge, "reviews")
    assert again.status_code == 202, again.text
    old, new = _requests(migrated)
    assert (old.status, old.withdraw_reason) == ("withdrawn", "superseded")
    assert new.status == "open" and new.proposal["purpose"] == "reviews"
    assert answer(friend, new.id, "go").status_code == 200
    assert [r.purpose for r in _bridges(migrated)] == ["reviews"]


def test_a_patch_across_owners_keeps_the_old_purpose_until_the_go(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, served, bridge = _cross(owner, make_client, migrated)
    first = connect(owner, served, bridge).json()["id"]
    answer(friend, first, "go")
    [row] = _bridges(migrated)
    path = f"{PROJECT}/members/{served}/bridges/{row.id}"
    asked = owner.patch(path, {"purpose": "reviews"})
    assert asked.status_code == 202, asked.text
    assert [r.purpose for r in _bridges(migrated)] == [PURPOSE]
    assert answer(friend, asked.json()["id"], "go").status_code == 200
    assert [r.purpose for r in _bridges(migrated)] == ["reviews"]


def test_ending_a_bridge_withdraws_an_open_change(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, served, bridge = _cross(owner, make_client, migrated)
    answer(friend, connect(owner, served, bridge).json()["id"], "go")
    [row] = _bridges(migrated)
    path = f"{PROJECT}/members/{served}/bridges/{row.id}"
    change = owner.patch(path, {"purpose": "reviews"}).json()["id"]
    assert owner.delete(path).status_code == 200
    with migrated.connect() as conn:
        closed = conn.execute(select(t.request).where(t.request.c.id == change)).one()
    assert (closed.status, closed.withdraw_reason) == ("withdrawn", "bridge_ended")


def test_the_limits_across_owners(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    bridge = _agent(migrated, friend)
    red = _agent(migrated, owner, "red-team")
    assert _fields(connect(owner, red, bridge)) == {"member": "security_team"}
    reviewer = _agent(migrated, owner, "reviewer")
    assert _fields(connect(owner, reviewer, bridge)) == {"member": "outside_role"}
    factory.membership(migrated, _project(migrated), "member", human_id=friend.id)
    assert connect(owner, reviewer, bridge).status_code == 202  # the owner is a member now


def test_a_role_the_limits_exclude_ends_a_bridge_across_owners(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, served, bridge = _cross(owner, make_client, migrated)
    answer(friend, connect(owner, served, bridge).json()["id"], "go")
    assert len(_bridges(migrated)) == 1
    done = owner.patch(f"{PROJECT}/members/{served}", {"role": "reviewer"})
    assert done.status_code == 200, done.text
    assert _bridges(migrated) == []


def test_a_proxy_neither_lists_nor_answers_the_projects_consent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    coder = _member(migrated, "coder", make_client, "coder")
    friend = flow.human(make_client, migrated, "friend")
    connect(coder, _agent(migrated, coder), _agent(migrated, friend))
    _, project_side = _requests(migrated)
    proxy = flow.agent(make_client, owner, role="proxy", reports_to=owner.id)
    listed = proxy.get(f"{PROJECT}/requests")
    assert listed.status_code == 200, listed.text
    assert project_side.id not in [r["id"] for r in listed.json()["items"]]
    assert answer_project(proxy, project_side.id, "go").status_code == 403


# --- what the agents see ----------------------------------------------------------------------


def test_the_resume_of_a_bridge_names_whom_it_carries_for(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    carrier = flow.agent(make_client, owner, role="coder", reports_to=owner.id)
    served = _agent(migrated, owner)
    assert connect(owner, served, carrier.id).status_code == 201
    resumed = carrier.resume()
    assert resumed.status_code == 200, resumed.text
    body = resumed.json()
    [entry] = body["membership"]["bridging_for"]
    assert (entry["member_id"], entry["purpose"]) == (served, PURPOSE)
    assert "You lend your hands to the agents listed in `bridging_for`" in (
        body["rules"]["markdown"]
    )
    assert body["membership"]["bridges"] == []
    rules = carrier.get(f"{PROJECT}/rules")
    assert "You lend your hands to the agents listed in `bridging_for`" in rules.text


def test_a_group_chat_shows_a_bridge_across_owners_as_an_observer(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    served = flow.agent(make_client, owner, role="coder", reports_to=owner.id)
    bridge = _agent(migrated, friend)
    same = _agent(migrated, owner)
    guest = _member(migrated, "guest", make_client, "member")
    answer(friend, connect(owner, served.id, bridge).json()["id"], "go")
    assert connect(owner, served.id, same).status_code == 201
    made = owner.post(
        f"{PROJECT}/conversations", {"title": "Release", "participants": [guest.id, served.id]}
    )
    assert made.status_code == 201, made.text
    chat = made.json()
    assert bridge in chat["observers"] and same not in chat["observers"]
    with migrated.begin() as conn:
        conn.execute(update(t.bridge).values(cross_owner=False))
    view = owner.get(f"{PROJECT}/conversations/{chat['id']}").json()
    assert bridge not in view["observers"]


def test_a_replayed_post_answers_the_connection_again(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _agent(migrated, owner), _agent(migrated, owner)
    path = f"{PROJECT}/members/{served}/bridges"
    body = {"bridge": bridge, "purpose": PURPOSE}
    headers = {"X-CSRF-Token": owner.csrf, "Idempotency-Key": "bridge-replay-000001"}
    first = owner.client.post(f"/api/v1{path}", json=body, headers=headers)
    assert first.status_code == 201, first.text
    again = owner.client.post(f"/api/v1{path}", json=body, headers=headers)
    assert again.status_code == 201, again.text
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["id"] == first.json()["id"]


def test_the_bridges_owner_outside_the_project_ends_the_connection(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, served, bridge = _cross(owner, make_client, migrated)
    answer(friend, connect(owner, served, bridge).json()["id"], "go")
    [row] = _bridges(migrated)
    path = f"{PROJECT}/members/{served}/bridges/{row.id}"
    stranger = flow.human(make_client, migrated, "stranger")
    assert stranger.delete(path).status_code == 404  # owns neither agent
    ended = friend.delete(path)
    assert ended.status_code == 200, ended.text
    assert (ended.json()["ended_by"], ended.json()["end_reason"]) == (friend.id, "bridge_ended")
    assert _bridges(migrated) == []
    assert friend.get(f"{PROJECT}/members/{served}").status_code == 404  # nothing else


@pytest.mark.parametrize(
    ("side", "values", "expected"),
    [
        ("bridge", {"active": None}, {"bridge": "not_a_member"}),
        ("served", {"active": None}, {"member": "not_an_agent"}),
        ("bridge", {"isolated_since": "now"}, {"bridge": "isolated"}),
    ],
)
def test_a_change_of_purpose_is_refused_at_the_go_for_a_side_that_is_gone(
    side: str,
    values: dict[str, Any],
    expected: dict[str, str],
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
) -> None:
    """Checked again at the last `go` (§2.3): a side that left is named as such, not as
    isolated, and the request stays open."""
    from maity_hub import clock

    friend, served, bridge = _cross(owner, make_client, migrated)
    answer(friend, connect(owner, served, bridge).json()["id"], "go")
    [row] = _bridges(migrated)
    change = owner.patch(f"{PROJECT}/members/{served}/bridges/{row.id}", {"purpose": "reviews"})
    assert change.status_code == 202, change.text
    gone = {k: (clock.now() if v == "now" else v) for k, v in values.items()}
    with migrated.begin() as conn:  # meanwhile, as a race with the answer would leave it
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == (row.served if side == "served" else row.bridge))
            .values(**gone)
        )
    refused = answer(friend, change.json()["id"], "go")
    assert refused.status_code == 400, refused.text
    assert _fields(refused) == expected
    with migrated.connect() as conn:
        still = conn.execute(select(t.request).where(t.request.c.id == change.json()["id"])).one()
    assert still.status == "open" and [r.purpose for r in _bridges(migrated)] == [PURPOSE]


def test_a_new_connection_is_refused_at_the_go_when_the_check_fails_then(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, served, bridge = _cross(owner, make_client, migrated)
    asked = connect(owner, served, bridge)
    assert asked.status_code == 202, asked.text
    with migrated.begin() as conn:  # the served agent took a role the limits exclude
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == served)
            .values(role="reviewer", role_base="reviewer")
        )
    refused = answer(friend, asked.json()["id"], "go")
    assert refused.status_code == 400, refused.text
    assert _fields(refused) == {"member": "outside_role"}
    assert _bridges(migrated) == []


def test_the_bridges_owner_leaving_the_project_ends_its_connections(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, served, bridge = _cross(owner, make_client, migrated)
    factory.membership(migrated, _project(migrated), "member", human_id=friend.id)
    answer(friend, connect(owner, served, bridge).json()["id"], "go")
    [row] = _bridges(migrated)
    left = owner.delete(f"{PROJECT}/members/{friend.id}")
    assert left.status_code == 200, left.text
    assert _bridges(migrated) == []
    with migrated.connect() as conn:
        ended = conn.execute(select(t.bridge).where(t.bridge.c.id == row.id)).one()
    assert (ended.end_reason, ended.ended_by) == ("owner_not_member", None)
