"""Agent instances and the team's rulebook (docs/api.md §6.17, §6.18)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, func, insert, select, text

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.db import migrate
from maity_hub.ids import new_id, new_instance_id
from maity_hub.instances import INSTANCE_PATTERN
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def _team(owner: flow.Human, member_id: str, **team: Any) -> Any:
    return owner.patch(f"/projects/maintainer/maity/members/{member_id}", {"team": team})


def _second(make_client: ClientFactory, owner: flow.Human, first: flow.Agent) -> flow.Agent:
    """Another instance of `first`'s team, the rulebook raised to make room."""
    count = len(owner.get(f"/projects/maintainer/maity/members/{first.id}").json()["instances"])
    assert _team(owner, first.id, max_instances=count + 1).status_code == 200
    return flow.agent(make_client, owner, agent={"id": first.id}, new_instance=True)


def _card(who: Any) -> str:
    response = who.post("/projects/maintainer/maity/tasks", {"title": "A card"})
    assert response.status_code == 201, response.text
    card_id: str = response.json()["id"]
    return card_id


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


# --- the instance id ----------------------------------------------------------------------


def test_the_exchange_gives_the_credential_its_instance_id(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    assert INSTANCE_PATTERN.fullmatch(agent.instance) and len(agent.instance) == 4
    view = owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()
    assert [i["id"] for i in view["instances"]] == [agent.instance]
    assert view["instances"][0]["address"] == f"{agent.id}#{agent.instance}"
    assert view["instances"][0]["credential_id"] == agent.credential_id  # the owner reads it
    credentials = owner.get(f"/projects/maintainer/maity/members/{agent.id}/credentials").json()[
        "items"
    ]
    assert credentials[0]["instance"] == agent.instance


def test_an_instance_id_is_never_reused() -> None:
    taken = {new_instance_id(set()) for _ in range(50)}
    assert all(INSTANCE_PATTERN.fullmatch(i) and set(i).isdisjoint("01ilo") for i in taken)
    assert new_instance_id(taken) not in taken


# --- joining as an instance ----------------------------------------------------------------


def test_a_member_join_says_which_instance_it_adds(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    neither = owner.post("/projects/maintainer/maity/joins", {"agent": {"id": agent.id}})
    assert neither.json()["error"]["details"]["fields"] == {"instance": "required"}
    both = owner.post(
        "/projects/maintainer/maity/joins",
        {"agent": {"id": agent.id}, "new_instance": True, "replaces": agent.instance},
    )
    assert both.json()["error"]["details"]["fields"] == {"instance": "one_of"}
    unknown = owner.post(
        "/projects/maintainer/maity/joins", {"agent": {"id": agent.id}, "replaces": "zzzz"}
    )
    assert unknown.json()["error"]["details"]["fields"] == {"replaces": "not_an_instance"}
    first = owner.post(
        "/projects/maintainer/maity/joins",
        {"agent": {"handle": "fresh", "display_name": "F"}, "new_instance": True},
    )
    assert first.json()["error"]["details"]["fields"] == {"new_instance": "not_a_member"}


def test_new_instances_stay_within_max_instances(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    over = owner.post(
        "/projects/maintainer/maity/joins", {"agent": {"id": agent.id}, "new_instance": True}
    )
    assert over.status_code == 409
    assert over.json()["error"]["code"] == "instance_quota"
    assert over.json()["error"]["details"] == {"max": 1}
    assert _team(owner, agent.id, max_instances=2).status_code == 200
    one = flow.join(owner, "maity", agent={"id": agent.id}, new_instance=True)
    two = flow.join(owner, "maity", agent={"id": agent.id}, new_instance=True)
    assert flow.exchange(make_client(), one).status_code == 201
    # Checked again at the exchange, and the code is not consumed.
    refused = flow.exchange(make_client(), two)
    assert refused.status_code == 409 and refused.headers["Maity-Error"] == "instance_quota"
    assert _team(owner, agent.id, max_instances=3).status_code == 200
    assert flow.exchange(make_client(), two).status_code == 201
    view = owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()
    assert len({i["id"] for i in view["instances"]}) == 3
    listed = {j["id"]: j for j in owner.get("/projects/maintainer/maity/joins").json()["items"]}
    assert listed[two["id"]]["new_instance"] is True and listed[two["id"]]["instance"]


def test_lowering_max_instances_revokes_nothing(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first = flow.agent(make_client, owner)
    second = _second(make_client, owner, first)
    assert _team(owner, first.id, max_instances=1).status_code == 200
    assert first.resume().status_code == 200 and second.resume().status_code == 200


# --- one claim, one instance ----------------------------------------------------------------


def test_a_card_is_held_by_exactly_one_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first = flow.agent(make_client, owner)
    second = _second(make_client, owner, first)
    first.resume()
    second.resume()
    card_id = _card(owner)
    claimed = first.post(f"/projects/maintainer/maity/tasks/{card_id}/claim", {})
    assert claimed.status_code == 200, claimed.text
    claim = claimed.json()["claim"]
    assert (claim["holder"], claim["instance"]) == (first.id, first.instance)
    assert claim["address"] == f"{first.id}#{first.instance}"
    again = second.post(f"/projects/maintainer/maity/tasks/{card_id}/claim", {})
    assert again.json()["error"]["code"] == "already_claimed"
    assert again.json()["error"]["details"]["instance"] == first.instance
    step = {"last_step": "a", "next_step": "b"}
    sibling = second.post(f"/projects/maintainer/maity/tasks/{card_id}/checkpoint", step)
    assert sibling.status_code == 409
    assert sibling.json()["error"]["code"] == "not_holder"
    assert sibling.json()["error"]["details"] == {"instance": first.instance}
    assert second.post(f"/projects/maintainer/maity/tasks/{card_id}/release").status_code == 409
    held = first.post(f"/projects/maintainer/maity/tasks/{card_id}/checkpoint", step).json()
    assert held["checkpoint"]["instance"] == first.instance
    event = _events(migrated, "task_checkpoint")[-1]
    view = owner.get("/projects/maintainer/maity/events", params={"after": event.seq - 1}).json()
    actors = [e["actor"] for e in view["items"] if e["kind"] == "task_checkpoint"]
    assert actors and actors[0]["instance"] == first.instance


def test_a_sibling_does_not_renew_the_holders_lease(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first = flow.agent(make_client, owner)
    second = _second(make_client, owner, first)
    card_id = _card(owner)
    first.post(f"/projects/maintainer/maity/tasks/{card_id}/claim", {})
    with migrated.begin() as conn:
        conn.execute(
            t.card.update()
            .where(t.card.c.id == card_id)
            .values(lease_until=factory.at("2000-01-01T00:00:00Z"))
        )
    second.get("/projects/maintainer/maity/tasks")
    with migrated.connect() as conn:
        lease = conn.execute(select(t.card.c.lease_until).where(t.card.c.id == card_id)).scalar()
    assert lease == factory.at("2000-01-01T00:00:00Z")
    first.get("/projects/maintainer/maity/tasks")
    with migrated.connect() as conn:
        lease = conn.execute(select(t.card.c.lease_until).where(t.card.c.id == card_id)).scalar()
    assert lease is not None and lease > clock.now()


def test_the_packet_lists_this_instances_claims_and_its_siblings(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first = flow.agent(make_client, owner)
    second = _second(make_client, owner, first)
    card_id = _card(owner)
    first.post(f"/projects/maintainer/maity/tasks/{card_id}/claim", {})
    mine = first.resume().json()
    theirs = second.resume().json()
    assert [c["id"] for c in mine["claims"]] == [card_id]
    assert theirs["claims"] == []
    assert theirs["me"]["instance"] == second.instance
    assert [i["id"] for i in theirs["team"]] == [first.instance]
    assert theirs["team"][0]["claims"] == 1
    assert set(theirs["team"][0]) == {
        "id",
        "address",
        "harness",
        "model",
        "presence",
        "paused",
        "lead",
        "claims",
    }


def test_an_admin_claim_for_a_team_names_the_instance(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first = flow.agent(make_client, owner)
    second = _second(make_client, owner, first)
    card_id = _card(owner)
    open_choice = owner.post(
        f"/projects/maintainer/maity/tasks/{card_id}/claim", {"holder": first.id}
    )
    assert open_choice.json()["error"]["details"]["fields"] == {"holder": "instance_required"}
    named = owner.post(
        f"/projects/maintainer/maity/tasks/{card_id}/claim",
        {"holder": f"{first.id}#{second.instance}"},
    )
    assert named.status_code == 200, named.text
    assert named.json()["claim"]["instance"] == second.instance


def test_an_unbound_claim_is_held_by_no_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first = flow.agent(make_client, owner)
    second = _second(make_client, owner, first)
    with migrated.connect() as conn:
        membership_id, project_id = conn.execute(
            select(t.membership.c.id, t.membership.c.project_id).where(
                t.membership.c.agent_id == first.id
            )
        ).one()
    card_id = factory.card(
        migrated,
        project_id,
        membership_id,
        status="in_progress",
        claim_holder=membership_id,
        lease_until=clock.now(),
    )
    for agent in (first, second):
        assert agent.get(f"/projects/maintainer/maity/members/{agent.id}").status_code == 200
        checkpoint = agent.post(
            f"/projects/maintainer/maity/tasks/{card_id}/checkpoint",
            {"last_step": "a", "next_step": "b"},
        )
        assert checkpoint.status_code == 409, checkpoint.text
    card = owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()
    assert card["claim"]["instance"] is None  # no call bound it


def test_an_expired_claim_assigned_to_a_team_names_the_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    holder = flow.agent(make_client, owner)
    team = flow.agent(make_client, owner)
    second = _second(make_client, owner, team)
    card_id = _card(owner)
    assert holder.post(f"/projects/maintainer/maity/tasks/{card_id}/claim", {}).status_code == 200
    with migrated.begin() as conn:
        conn.execute(t.card.update().where(t.card.c.id == card_id).values(lease_until=clock.now()))
    path = f"/projects/maintainer/maity/tasks/{card_id}/assign"
    open_choice = owner.post(path, {"assignee": team.id})
    assert open_choice.status_code == 400
    assert open_choice.json()["error"]["details"]["fields"] == {"instance": "instance_required"}
    named = owner.post(path, {"assignee": team.id, "instance": second.instance})
    assert named.status_code == 200, named.text
    assert named.json()["claim"]["instance"] == second.instance
    assert named.json()["assigned_instance"] is None  # under free no instance is assigned
    assigned = _events(migrated, "task_assigned")[-1].payload
    assert (assigned["instance"], assigned["assigned_instance"]) == (second.instance, None)


def test_each_instance_resumes_its_own_session(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first = flow.agent(make_client, owner)
    second = _second(make_client, owner, first)
    one = first.resume().json()["session"]["id"]
    two = second.resume().json()["session"]["id"]
    again = first.resume().json()["session"]["id"]  # closes only its own previous one
    with migrated.connect() as conn:
        live = set(
            conn.execute(
                select(t.agent_session.c.id).where(t.agent_session.c.live.is_(True))
            ).scalars()
        )
    assert live == {two, again} and one not in live


# --- the instance on what an instance wrote ----------------------------------------------------


def test_a_chat_message_names_the_instance_that_sent_it(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first = flow.agent(make_client, owner)
    second = _second(make_client, owner, first)
    path = f"/projects/maintainer/maity/conversations/{first.id}/messages"
    for who, body in ((first, "one"), (second, "two"), (owner, "three")):
        assert who.post(path, {"body": body}).status_code == 201
    items = owner.get(path).json()["items"]
    assert [(m["body"], m["from_instance"]) for m in items] == [
        ("one", first.instance),
        ("two", second.instance),
        ("three", None),  # a human has no instances
    ]


def test_a_request_names_the_instance_that_asked(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first = flow.agent(make_client, owner)
    second = _second(make_client, owner, first)
    first.resume()
    second.resume()
    for who in (first, second):
        response = who.post(
            "/projects/maintainer/maity/requests", {"class": "decision", "title": "Which?"}
        )
        assert response.status_code == 201, response.text
        assert response.json()["asked_by"]["instance"] == who.instance
    items = owner.get("/projects/maintainer/maity/requests").json()["items"]
    assert sorted(r["asked_by"]["instance"] for r in items) == sorted(
        [first.instance, second.instance]
    )
    mine = owner.post(
        "/projects/maintainer/maity/requests", {"class": "decision", "title": "Mine?"}
    )
    assert mine.status_code == 201, mine.text
    assert mine.json()["asked_by"]["instance"] is None  # a human has no instances


# --- replacing and revoking ------------------------------------------------------------------


def test_a_replacement_takes_the_claims_and_the_lead(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    old = flow.agent(make_client, owner)
    card_id = _card(owner)
    old.post(f"/projects/maintainer/maity/tasks/{card_id}/claim", {})
    old.post(
        f"/projects/maintainer/maity/tasks/{card_id}/checkpoint",
        {"last_step": "a", "next_step": "b"},
    )
    assert _team(owner, old.id, lead_instance=old.instance).status_code == 200
    new = flow.agent(make_client, owner, agent={"id": old.id}, replaces=old.instance)
    assert new.instance != old.instance
    assert (
        old.get("/projects/maintainer/maity/tasks").headers["Maity-Error"] == "credential_revoked"
    )
    view = owner.get(f"/projects/maintainer/maity/members/{old.id}").json()
    assert [i["id"] for i in view["instances"]] == [new.instance]
    assert view["instances"][0]["replaces"] == old.instance
    assert view["team"]["lead_instance"] == new.instance
    with migrated.connect() as conn:
        head = conn.execute(select(func.max(t.event.c.seq))).scalar_one()
    packet = new.resume().json()
    # The replacing instance starts at the project's head, not at the old one's backlog (§8.3).
    assert packet["events"]["after"] == head
    assert [c["id"] for c in packet["claims"]] == [card_id]
    assert packet["claims"][0]["checkpoint"]["last_step"] == "a"
    moved = _events(migrated, "task_claimed")[-1]
    assert (moved.payload["instance"], moved.payload["replaces"]) == (new.instance, old.instance)
    with migrated.connect() as conn:
        reason = conn.execute(
            select(t.credential.c.revoked_reason).where(t.credential.c.id == old.credential_id)
        ).scalar()
    assert reason == "replaced"


def test_revoking_one_instance_leaves_the_others_working(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first = flow.agent(make_client, owner)
    second = _second(make_client, owner, first)
    assert _team(owner, first.id, lead_instance=first.instance).status_code == 200
    card_id = _card(owner)
    first.post(f"/projects/maintainer/maity/tasks/{card_id}/claim", {})
    revoked = owner.post(f"/projects/maintainer/maity/credentials/{first.credential_id}/revoke", {})
    assert revoked.status_code == 200
    assert second.resume().status_code == 200
    view = owner.get(f"/projects/maintainer/maity/members/{first.id}").json()
    assert view["team"]["lead_instance"] is None
    assert [i["id"] for i in view["instances"]] == [second.instance]
    card = owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()
    assert card["claim"]["instance"] == first.instance  # stays with the revoked instance
    updated = _events(migrated, "member_updated")[-1]
    assert updated.payload["changed"] == ["team"]


def test_removing_the_member_revokes_every_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first = flow.agent(make_client, owner)
    second = _second(make_client, owner, first)
    assert _team(owner, first.id, lead_instance=first.instance).status_code == 200
    before = _events(migrated, "member_updated")[-1].seq
    assert owner.delete(f"/projects/maintainer/maity/members/{first.id}").status_code == 200
    with migrated.connect() as conn:
        open_ = conn.execute(
            select(t.credential.c.id).where(t.credential.c.revoked_at.is_(None))
        ).all()
    assert open_ == []
    for agent in (first, second):
        assert agent.get("/me").headers["Maity-Error"] == "credential_revoked"
    # The lead's revocation is part of the removal, not a rulebook change of its own.
    after = [e for e in _events(migrated, "member_updated") if e.seq > before]
    assert [e.payload.get("changed") for e in after] == [None]  # the removal's own


# --- the rulebook -------------------------------------------------------------------------------


def test_only_the_agents_owner_sets_the_rulebook(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    admin_agent = flow.agent(make_client, owner, role="admin")
    by_agent = admin_agent.patch(
        f"/projects/maintainer/maity/members/{agent.id}", {"team": {"wake": "all"}}
    )
    assert by_agent.status_code == 403
    assert by_agent.json()["error"]["details"]["reason"] == "humans_only"
    # An agent learns it is a human's call before any other check (§2.3).
    on_a_human = admin_agent.patch(
        f"/projects/maintainer/maity/members/{owner.id}", {"team": {"wake": "all"}}
    )
    mixed = admin_agent.patch(
        f"/projects/maintainer/maity/members/{agent.id}",
        {"team": {"wake": "all"}, "trust": "admin"},
    )
    for refused in (on_a_human, mixed):
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["details"]["reason"] == "humans_only"
    colleague = flow.human(make_client, migrated, "colleague")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "admin", human_id=colleague.id)
    not_theirs = _team(colleague, agent.id, max_instances=2)
    assert not_theirs.status_code == 403
    assert not_theirs.json()["error"]["details"]["reason"] == "humans_only"
    changed = _team(owner, agent.id, max_instances=3, review_within_team=True)
    assert changed.status_code == 200
    team = changed.json()["team"]
    assert (team["max_instances"], team["review_within_team"]) == (3, True)
    assert team["updated_by"] == {"kind": "human", "id": owner.id, "handle": "maintainer"}


def test_team_is_set_on_its_own(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    mixed = owner.patch(
        f"/projects/maintainer/maity/members/{agent.id}",
        {"team": {"max_instances": 2}, "trust": "admin"},
    )
    assert mixed.status_code == 400
    assert mixed.json()["error"]["details"]["fields"] == {"team": "alone"}
    view = owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()
    assert (view["trust"], view["role"], view["team"]["max_instances"]) == ("member", "coder", 1)


def test_a_lead_rule_needs_a_lead(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    missing = _team(owner, agent.id, distribution="lead")
    assert missing.json()["error"]["details"]["fields"] == {"team.lead_instance": "required"}
    wrong = _team(owner, agent.id, wake="lead", lead_instance="zzzz")
    assert wrong.json()["error"]["details"]["fields"] == {"team.lead_instance": "not_an_instance"}
    assert _team(owner, agent.id, wake="lead", lead_instance=agent.instance).status_code == 200


def test_an_owner_who_is_no_member_sets_the_rulebook(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    colleague = flow.human(make_client, migrated, "colleague")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "admin", human_id=colleague.id)
    theirs = flow.agent(make_client, colleague, agent={"handle": "theirs", "display_name": "T"})
    assert owner.delete(f"/projects/maintainer/maity/members/{colleague.id}").status_code == 200
    # Outside the project it sees nothing of it: no member view, no briefing (§1.3).
    outside = _team(colleague, theirs.id, max_instances=2)
    assert outside.status_code == 204 and outside.content == b""
    assert (
        owner.get(f"/projects/maintainer/maity/members/{theirs.id}").json()["team"]["max_instances"]
        == 2
    )
    stranger = flow.human(make_client, migrated, "stranger")
    assert _team(stranger, theirs.id, max_instances=4).status_code == 404


def test_the_rulebooks_answer_shows_the_briefing_only_to_members_admin(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    colleague = flow.human(make_client, migrated, "colleague")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "admin", human_id=colleague.id)
    theirs = flow.agent(make_client, colleague, agent={"handle": "theirs", "display_name": "T"})
    demoted = owner.patch(f"/projects/maintainer/maity/members/{colleague.id}", {"trust": "member"})
    assert demoted.status_code == 200, demoted.text
    plain = _team(colleague, theirs.id, max_instances=2)
    assert plain.status_code == 200 and "briefing" not in plain.json()
    mine = flow.agent(make_client, owner)
    assert "briefing" in _team(owner, mine.id, wake="all").json()  # an owner has members:admin


# --- the migration ------------------------------------------------------------------------------


def test_existing_credentials_become_instances(engine: Engine) -> None:
    migrate(engine, "0013")
    project_id = factory.project(engine)
    human_id = factory.human(engine)
    factory.membership(engine, project_id, human_id=human_id)  # its namespace owner (0060)
    agent_id = new_id("agent")
    with engine.begin() as conn:
        conn.execute(
            insert(t.agent_profile).values(
                id=agent_id,
                owner_id=human_id,
                handle="old-agent",
                display_name="Old",
                created_at=clock.now(),
            )
        )
    membership_id = factory.membership(engine, project_id, "member", agent_id=agent_id)
    stamp = clock.now().strftime("%Y-%m-%d %H:%M:%S.%f")  # as text: no driver adapter
    credentials = [new_id("credential") for _ in range(3)]
    session_id = new_id("session")
    with engine.begin() as conn:
        for credential_id, revoked in zip(credentials, (None, None, stamp), strict=True):
            conn.execute(
                text(
                    "INSERT INTO credential (id, membership_id, verifier, created_at, revoked_at)"
                    " VALUES (:id, :m, :v, :c, :r)"
                ),
                {"id": credential_id, "m": membership_id, "v": "0" * 64, "c": stamp, "r": revoked},
            )
        conn.execute(
            text(
                "INSERT INTO agent_session (id, credential_id, membership_id, started_at,"
                " last_seen_at, acknowledged_seq) VALUES (:id, :cr, :m, :s, :s, 0)"
            ),
            {"id": session_id, "cr": credentials[1], "m": membership_id, "s": stamp},
        )
    # A claim its session names, and one whose session is unknown (§6.17).
    held = factory.card(
        engine,
        project_id,
        membership_id,
        status="in_progress",
        claim_holder=membership_id,
        claim_session_id=session_id,
    )
    orphan = factory.card(
        engine, project_id, membership_id, status="in_progress", claim_holder=membership_id
    )
    migrate(engine)
    with engine.connect() as conn:
        ids = dict(conn.execute(select(t.credential.c.id, t.credential.c.instance)).all())
        team = conn.execute(
            select(t.membership.c.max_instances).where(t.membership.c.id == membership_id)
        ).scalar()
        claims = dict(conn.execute(select(t.card.c.id, t.card.c.claim_instance)).all())
    assert len(set(ids.values())) == 3
    assert all(INSTANCE_PATTERN.fullmatch(i) for i in ids.values())
    assert team == 2  # the active ones
    # The orphan is held by no instance: nobody adopts it (fails closed).
    assert claims == {held: ids[credentials[1]], orphan: None}
