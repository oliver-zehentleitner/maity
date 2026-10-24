"""docs/api.md §15.9 the join pickup and §15.11 supervised sessions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update

from maity_hub import clock, events
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_placements import REPOSITORY, Setup, events_of, placed
from tests.test_runner_stream import attach, hello, send
from tests.test_runners import error, paired


@pytest.fixture
def setup(make_client: ClientFactory, migrated: Engine) -> Setup:
    """As in test_placements: a project with a repository, an attached runner, an agent."""
    owner = flow.human(make_client, migrated)
    flow.project(owner, repository={"url": REPOSITORY})
    runner = paired(make_client, owner)
    attach(owner, runner)
    client = make_client()
    assert hello(client, runner).status_code == 200
    agent = flow.agent(make_client, owner, role="member")
    _allow_instances(migrated, agent.id, 2)  # the joined clone plus the placement's
    return Setup(owner, runner, client, agent, migrated)


def _allow_instances(engine: Engine, agent_id: str, count: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == agent_id)
            .values(max_instances=count)
        )


def pick_up(s: Setup, placement: dict[str, Any], generation: int | None = None) -> Any:
    path = f"/api/v1/runner/placements/{placement['id']}/join"
    body = {"observed_generation": placement["generation"] if generation is None else generation}
    return send(s.client, s.runner, "POST", path, body)


def exchange(client: TestClient, picked: dict[str, Any]) -> Any:
    token = picked["join_url"].rsplit("/", 1)[1]
    return client.post(
        f"/api/v1/join/{token}", json={"code": picked["code"], "client": "maity-cli/test"}
    )


def placement_row(s: Setup, placement_id: str) -> Any:
    with s.engine.connect() as conn:
        return conn.execute(select(t.placement).where(t.placement.c.id == placement_id)).one()


def test_a_pickup_joins_the_placements_member_and_binds_its_credential(
    setup: Setup, make_client: ClientFactory
) -> None:
    placement = placed(setup)
    picked = pick_up(setup, placement)
    assert picked.status_code == 201, picked.text
    body = picked.json()
    assert set(body) == {"join_url", "code", "expires_at", "credential_will_bind", "pickup"}
    assert body["credential_will_bind"] == setup.agent.id and body["pickup"] == 1
    joined = exchange(make_client(), body)
    assert joined.status_code == 201, joined.text
    assert joined.headers["Maity-Member-Id"] == setup.agent.id
    row = placement_row(setup, placement["id"])
    assert row.credential_id == joined.headers["Maity-Credential-Id"] and row.rejoin is False
    again = pick_up(setup, placement)
    assert (again.status_code, error(again)) == (409, "pickup_not_allowed")
    assert again.json()["error"]["details"] == {"why": "credential_issued"}


def test_a_new_profile_is_created_at_the_exchange(setup: Setup, make_client: ClientFactory) -> None:
    placement = placed(setup, agent={"handle": "agent-f", "display_name": "Agent F"},
                       briefing="You own the Runners view.")  # fmt: skip
    picked = pick_up(setup, placement).json()
    assert picked["credential_will_bind"] == "agent-f"
    joined = exchange(make_client(), picked)
    assert joined.status_code == 201, joined.text
    agent_id = joined.headers["Maity-Member-Id"]
    member = setup.owner.get(f"/projects/maity/members/{agent_id}").json()
    assert member["handle"] == "agent-f"
    with setup.engine.connect() as conn:
        owner = conn.execute(
            select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent_id)
        ).scalar_one()
        briefing = conn.execute(
            select(t.membership.c.briefing).where(t.membership.c.agent_id == agent_id)
        ).scalar_one()
    assert owner == setup.owner.id and briefing == "You own the Runners view."
    assert placement_row(setup, placement["id"]).membership_id is not None


def test_a_lost_answer_is_recovered_and_three_pickups_is_all(
    setup: Setup, make_client: ClientFactory
) -> None:
    placement = placed(setup)
    first = pick_up(setup, placement).json()
    second = pick_up(setup, placement).json()
    assert second["pickup"] == 2
    assert exchange(make_client(), first).status_code == 404  # revoked by the second
    assert pick_up(setup, placement).json()["pickup"] == 3
    fourth = pick_up(setup, placement)
    assert (fourth.status_code, error(fourth)) == (409, "pickup_used")


def test_what_a_pickup_needs(setup: Setup) -> None:
    placement = placed(setup)
    stale = pick_up(setup, placement, generation=placement["generation"] + 1)
    assert stale.json()["error"]["details"] == {"why": "stale_generation"}
    with setup.engine.begin() as conn:
        conn.execute(
            update(t.placement).where(t.placement.c.id == placement["id"]).values(desired="stopped")
        )
    stopped = pick_up(setup, placement)
    assert stopped.json()["error"]["details"] == {"why": "not_running"}


def test_a_rejoin_replaces_the_revoked_instance(setup: Setup, make_client: ClientFactory) -> None:
    placement = placed(setup)
    first = exchange(make_client(), pick_up(setup, placement).json())
    old_instance = first.headers["Maity-Instance"]
    with setup.engine.begin() as conn:  # the old instance holds one card and is assigned one
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == setup.agent.id)
        ).scalar_one()
    held = factory.card(setup.engine, project_id, member, status="in_progress",
                        claim_holder=member, claim_instance=old_instance)  # fmt: skip
    assigned = factory.card(setup.engine, project_id, member,
                            assigned_to=member, assigned_instance=old_instance)  # fmt: skip
    revoked = setup.owner.post(
        f"/projects/maity/credentials/{first.headers['Maity-Credential-Id']}/revoke", {}
    )
    assert revoked.status_code == 200, revoked.text
    restarted = setup.owner.post(
        f"/projects/maity/placements/{placement['id']}/restart", {"rejoin": True}
    )
    assert restarted.status_code == 200, restarted.text
    again = pick_up(setup, restarted.json())
    assert again.status_code == 201, again.text
    joined = exchange(make_client(), again.json())
    assert joined.status_code == 201, joined.text
    assert joined.headers["Maity-Instance"] != old_instance  # ids are never reused (§6.17)
    with setup.engine.connect() as conn:
        credential = conn.execute(
            select(t.credential).where(t.credential.c.id == joined.headers["Maity-Credential-Id"])
        ).one()
        revocations = conn.execute(
            select(t.event).where(t.event.c.kind == "credential_revoked")
        ).all()
    assert credential.replaces == old_instance
    assert len(revocations) == 1  # the owner's; the rejoin revokes nothing again
    with setup.engine.connect() as conn:  # the revoked instance's work moved over
        cards = {c.id: c for c in conn.execute(select(t.card)).all()}
    assert cards[held].claim_instance == credential.instance
    assert cards[assigned].assigned_instance == credential.instance
    row = placement_row(setup, placement["id"])
    assert row.credential_id == credential.id and row.rejoin is False


def test_a_pickup_never_takes_over_a_live_instance(
    setup: Setup, make_client: ClientFactory
) -> None:
    placement = placed(setup)
    exchange(make_client(), pick_up(setup, placement).json())
    with setup.engine.begin() as conn:  # rejoin set while the credential still lives
        conn.execute(
            update(t.placement).where(t.placement.c.id == placement["id"]).values(rejoin=True)
        )
    refused = pick_up(setup, placement)
    assert refused.json()["error"]["details"] == {"why": "credential_issued"}


def test_a_pickup_respects_the_teams_instances(setup: Setup) -> None:
    _allow_instances(setup.engine, setup.agent.id, 1)  # the joined clone has the one
    placement = placed(setup)
    refused = pick_up(setup, placement)
    assert (refused.status_code, error(refused)) == (409, "instance_quota")


def test_the_event_names_the_pickup_and_never_the_code(setup: Setup) -> None:
    placement = placed(setup)
    picked = pick_up(setup, placement).json()
    (event,) = events_of(setup, "join_picked_up")
    assert set(event["payload"]) == {"placement_id", "runner_id", "join_id", "pickup"}
    assert event["payload"]["placement_id"] == placement["id"]
    assert picked["code"] not in str(event) and picked["join_url"] not in str(event)
    assert event["actor"]["kind"] == "runner"
    with setup.engine.connect() as conn:
        audience = conn.execute(
            select(t.event.c.audience).where(t.event.c.kind == "join_picked_up")
        ).scalar_one()
    assert audience == [f"member:{setup.owner.id}", "role:owner"]


def test_another_runner_does_not_pick_it_up(setup: Setup, make_client: ClientFactory) -> None:
    placement = placed(setup)
    other = paired(make_client, setup.owner, name="other-box")
    path = f"/api/v1/runner/placements/{placement['id']}/join"
    refused = send(make_client(), other, "POST", path, {"observed_generation": 1})
    assert refused.status_code == 404


def _unrevoke_joins(s: Setup) -> None:
    """Undo the revocation, so the exchange's own re-check is what refuses."""
    with s.engine.begin() as conn:
        conn.execute(update(t.join_link).values(revoked_at=None))


def _members(s: Setup) -> int:
    with s.engine.connect() as conn:
        return len(conn.execute(select(t.membership.c.id)).all())


@pytest.mark.parametrize("gone", ["deleted", "stopped", "runner_revoked", "runner_removed"])
def test_an_unused_pickup_dies_with_its_placement_or_runner(
    setup: Setup, make_client: ClientFactory, gone: str
) -> None:
    placement = placed(setup)
    picked = pick_up(setup, placement).json()
    path = f"/projects/maity/placements/{placement['id']}"
    answer = {
        "deleted": lambda: setup.owner.delete(path),
        "stopped": lambda: setup.owner.patch(path, {"desired": "stopped"}),
        "runner_revoked": lambda: setup.owner.post(f"/runners/{setup.runner.id}/revoke", {}),
        "runner_removed": lambda: setup.owner.delete(f"/runners/{setup.runner.id}"),
    }[gone]()
    assert answer.status_code == 200, answer.text
    with setup.engine.connect() as conn:
        joins = conn.execute(
            select(t.join_link.c.revoked_at).where(t.join_link.c.placement_id.is_not(None))
        ).all()
    assert joins and all(j.revoked_at is not None for j in joins)
    _unrevoke_joins(setup)
    members = _members(setup)
    refused = exchange(make_client(), picked)
    assert refused.status_code == 404, refused.text
    assert _members(setup) == members
    assert placement_row(setup, placement["id"]).credential_id is None


@pytest.mark.parametrize(
    "change", [{"generation": 2}, {"approval_status": "pending"}, {"closed_at": "now"}]
)
def test_the_exchange_checks_the_placement_again(
    setup: Setup, make_client: ClientFactory, change: dict[str, Any]
) -> None:
    placement = placed(setup)
    picked = pick_up(setup, placement).json()
    values = {k: (clock.now() if v == "now" else v) for k, v in change.items()}
    with setup.engine.begin() as conn:  # behind the hub's back: no revocation runs
        conn.execute(
            update(t.placement).where(t.placement.c.id == placement["id"]).values(**values)
        )
    assert exchange(make_client(), picked).status_code == 404


def test_a_pickup_never_brings_back_a_removed_member(
    setup: Setup, make_client: ClientFactory
) -> None:
    placement = placed(setup)
    picked = pick_up(setup, placement).json()
    removed = setup.owner.delete(f"/projects/maity/members/{setup.agent.id}")
    assert removed.status_code == 200, removed.text
    _unrevoke_joins(setup)
    with setup.engine.begin() as conn:  # whatever the removal did to the placement
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == placement["id"])
            .values(closed_at=None, active=True, desired="running")
        )
    refused = exchange(make_client(), picked)
    assert refused.status_code == 404, refused.text
    with setup.engine.connect() as conn:
        active = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.agent_id == setup.agent.id, t.membership.c.active.is_(True)
            )
        ).all()
    assert active == []


def _rejoin_picked(setup: Setup, make_client: ClientFactory) -> tuple[Any, Any, dict[str, Any]]:
    """A placement whose credential was revoked and restarted with rejoin: the first
    exchange, the restarted placement and the rejoin's pickup."""
    placement = placed(setup)
    first = exchange(make_client(), pick_up(setup, placement).json())
    assert first.status_code == 201, first.text
    revoked = setup.owner.post(
        f"/projects/maity/credentials/{first.headers['Maity-Credential-Id']}/revoke", {}
    )
    assert revoked.status_code == 200, revoked.text
    restarted = setup.owner.post(
        f"/projects/maity/placements/{placement['id']}/restart", {"rejoin": True}
    )
    assert restarted.status_code == 200, restarted.text
    again = pick_up(setup, restarted.json())
    assert again.status_code == 201, again.text
    return first, restarted.json(), again.json()


def test_a_rejoin_after_the_member_was_removed_is_not_found(
    setup: Setup, make_client: ClientFactory
) -> None:
    _, restarted, picked = _rejoin_picked(setup, make_client)
    with setup.engine.begin() as conn:  # removed behind the hub's back: only the exchange
        conn.execute(  # stands between the join and a new membership
            update(t.membership)
            .where(t.membership.c.agent_id == setup.agent.id)
            .values(active=None)
        )
    refused = exchange(make_client(), picked)
    assert refused.status_code == 404, refused.text
    assert placement_row(setup, restarted["id"]).rejoin is True


def test_a_rejoin_never_replaces_an_instance_that_lives_again(
    setup: Setup, make_client: ClientFactory
) -> None:
    first, _, picked = _rejoin_picked(setup, make_client)
    with setup.engine.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == first.headers["Maity-Credential-Id"])
            .values(revoked_at=None)
        )
    refused = exchange(make_client(), picked)
    assert (refused.status_code, error(refused)) == (400, "invalid"), refused.text


def test_a_rejoin_checks_the_teams_instances_at_the_exchange(
    setup: Setup, make_client: ClientFactory
) -> None:
    _, _, picked = _rejoin_picked(setup, make_client)
    _allow_instances(setup.engine, setup.agent.id, 1)  # the joined clone has the one
    refused = exchange(make_client(), picked)
    assert (refused.status_code, error(refused)) == (409, "instance_quota")


def test_a_rejoin_leaves_the_lead_cleared(setup: Setup, make_client: ClientFactory) -> None:
    first, _, picked = _rejoin_picked(setup, make_client)
    with setup.engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == setup.agent.id)
            .values(lead_instance=None)
        )
    joined = exchange(make_client(), picked)
    assert joined.status_code == 201, joined.text
    with setup.engine.connect() as conn:
        lead = conn.execute(
            select(t.membership.c.lead_instance).where(t.membership.c.agent_id == setup.agent.id)
        ).scalar_one()
    assert lead is None


def test_a_rejoin_never_replaces_an_instance_twice(
    setup: Setup, make_client: ClientFactory
) -> None:
    first, _, picked = _rejoin_picked(setup, make_client)
    with setup.engine.begin() as conn:  # a successor already names the old instance
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == setup.agent.credential_id)
            .values(replaces=first.headers["Maity-Instance"])
        )
    refused = exchange(make_client(), picked)
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"replaces": "already_replaced"}


def test_a_pending_placement_is_not_picked_up(setup: Setup) -> None:
    placement = placed(setup)
    with setup.engine.begin() as conn:
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == placement["id"])
            .values(approval_status="pending")
        )
    assert pick_up(setup, placement).status_code == 404


def test_a_taken_handle_is_refused_at_the_pickup(setup: Setup, make_client: ClientFactory) -> None:
    placement = placed(setup, agent={"handle": "agent-f", "display_name": "Agent F"})
    flow.agent(make_client, setup.owner, agent={"handle": "agent-f", "display_name": "F"})
    refused = pick_up(setup, placement)
    assert (refused.status_code, error(refused)) == (409, "pickup_not_allowed")
    assert refused.json()["error"]["details"] == {"why": "handle_taken"}


# --- supervised sessions (§15.11) ----------------------------------------------------------


def test_a_supervised_resume_says_so(setup: Setup) -> None:
    placement = placed(setup)
    supervised = setup.agent.resume(supervisor="maity-runner/0.1.0").json()
    assert supervised["hints"] == {"duty": "supervised"}
    assert "## Supervised" in supervised["rules"]["markdown"]
    assert supervised["membership"]["placement"] == {
        "id": placement["id"], "runner_name": "home-laptop", "harness": "claude-code",
        "mode": placement["mode"], "stop_grace_seconds": placement["stop_grace_seconds"],
    }  # fmt: skip
    plain = setup.agent.resume().json()
    assert plain["hints"]["duty"] == "self" and "wait_timeout" in plain["hints"]
    assert "## Supervised" not in plain["rules"]["markdown"]


def test_a_supervised_long_poll_skips_what_does_not_wake_it(setup: Setup) -> None:
    def poll() -> list[Any]:
        latest = setup.agent.get("/projects/maity/events", params={"after": "latest", "wait": 0})
        cursor = latest.json()["cursor"]
        said = setup.owner.post(
            "/projects/maity/events",
            {"kind": "message", "type": "notice", "to": "all", "body": "hi"},
        )
        assert said.status_code == 201, said.text
        waited = setup.agent.get("/projects/maity/events", params={"after": cursor, "wait": 1})
        assert waited.status_code == 200, waited.text
        return [e["kind"] for e in waited.json()["items"]]

    assert setup.agent.resume(supervisor="maity-runner/0.1.0").status_code == 200
    assert poll() == []  # a note to everyone is no model run for a supervised session
    assert setup.agent.resume().status_code == 200
    assert poll() == ["message"]


def test_a_supervised_packet_always_carries_the_rules(setup: Setup) -> None:
    placed(setup)
    first = setup.agent.resume(supervisor="maity-runner/0.1.0").json()
    again = setup.agent.resume(
        supervisor="maity-runner/0.1.0", cursor=first["events"]["cursor"]
    ).json()
    assert again["rules"]["changed"] is False
    assert "## Supervised" in again["rules"]["markdown"]


def test_each_agent_sees_its_own_placement(setup: Setup, make_client: ClientFactory) -> None:
    other = flow.agent(make_client, setup.owner, role="member")
    _allow_instances(setup.engine, other.id, 2)
    theirs = placed(setup, agent={"id": other.id})
    mine = placed(setup)
    assert setup.agent.resume().json()["membership"]["placement"]["id"] == mine["id"]
    assert other.resume().json()["membership"]["placement"]["id"] == theirs["id"]


def test_a_supervisor_is_a_runners_name(setup: Setup) -> None:
    refused = setup.agent.resume(supervisor="something else")
    assert refused.status_code == 400


def test_an_agent_without_a_placement_has_none(setup: Setup, make_client: ClientFactory) -> None:
    other = flow.agent(make_client, setup.owner)
    assert other.resume().json()["membership"]["placement"] is None


def _row(kind: str, audience: list[str]) -> Any:
    return SimpleNamespace(actor_membership=None, kind=kind, audience=audience,
                           conversation_id=None)  # fmt: skip


def test_a_supervised_session_wakes_on_less() -> None:
    me = SimpleNamespace(id=7, role="member")
    for kind, audience, plain, supervised in (
        ("task_created", ["all"], True, False),
        ("state_changed", ["all"], True, True),
        ("rules_changed", ["all"], True, True),
        ("message", ["member:agt-b"], True, True),
        ("message", ["all", "member:agt-b"], True, True),
        ("message", ["all", "member:hum-a"], True, False),  # the sender's own term
        ("message", ["role:member"], True, True),
    ):
        row = _row(kind, audience)
        assert events.wakes(row, me, "agt-b") is plain, kind
        assert events.wakes(row, me, "agt-b", supervised=True) is supervised, (kind, audience)
