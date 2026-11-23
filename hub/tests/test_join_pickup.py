"""docs/api.md §15.9 the join pickup and §15.11 supervised sessions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import CLI_VERSION, clock, cross_owner, events, moderation
from maity_hub import tables as t
from maity_hub.routes import agents, joins
from tests import factory, flow
from tests import test_runners as runners
from tests.conftest import ClientFactory
from tests.test_placements import (
    REPOSITORY,
    Setup,
    _as_member_with_member_agents,
    events_of,
    place,
    placed,
)
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
    member = setup.owner.get(f"/projects/maintainer/maity/members/{agent_id}").json()
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


def test_an_account_override_does_not_gate_the_exchange(
    setup: Setup, make_client: ClientFactory
) -> None:
    # §16.5 "What it gates": the exchange of a link already issued is never counted, an
    # override on the creator's account included; its numbers never reach the runner's owner.
    placement = placed(setup, agent={"handle": "agent-f", "display_name": "Agent F"})
    picked = pick_up(setup, placement).json()
    held = len(setup.owner.get("/agents").json()["items"])
    account = f"/admin/users/{setup.owner.id}/limits"
    assert setup.owner.patch(account, {"max_agents_per_human": held}).status_code == 200
    joined = exchange(make_client(), picked)
    assert joined.status_code == 201, joined.text
    assert "agent_limit" not in joined.text and "account_override" not in joined.text
    assert len(setup.owner.get("/agents").json()["items"]) == held + 1
    refused = setup.owner.post("/agents", {"handle": "another", "display_name": "Another"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "agent_limit"
    assert refused.json()["error"]["details"] == {
        "limit": held,
        "count": held + 1,
        "source": "account_override",
    }


def _demote_owner(s: Setup) -> None:
    with s.engine.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.human_id == s.owner.id).values(trust="admin")
        )


@pytest.mark.parametrize("when", ["pickup", "exchange"])
def test_a_new_profile_follows_its_creators_current_standing(
    setup: Setup, make_client: ClientFactory, when: str
) -> None:
    # §3.4, §15.9: a new profile with trust admin, placed by an owner. Once that owner is
    # only an admin, it is what the creator may no longer give: the runner's pickup is
    # refused, and a code picked up before the change no longer exchanges.
    placement = placed(setup, agent={"handle": "agent-f", "display_name": "Agent F"}, trust="admin")
    if when == "pickup":
        _demote_owner(setup)
        refused = pick_up(setup, placement)
        assert (refused.status_code, error(refused)) == (409, "pickup_not_allowed")
        assert refused.json()["error"]["details"] == {"why": "creator_lacks_authority"}
        return
    picked = pick_up(setup, placement)
    assert picked.status_code == 201, picked.text
    _demote_owner(setup)
    gone = exchange(make_client(), picked.json())
    assert gone.status_code == 404, gone.text


@pytest.mark.parametrize("late", ["invalid", "unique"])
def test_a_handle_taken_during_the_exchange_is_not_found(
    setup: Setup, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch, late: str
) -> None:
    placement = placed(setup, agent={"handle": "agent-f", "display_name": "Agent F"})
    picked = pick_up(setup, placement).json()
    real = agents.create_profile

    def racing(conn: Any, *args: Any, **kwargs: Any) -> str:  # a POST /agents lands after the check
        if late == "unique":
            raise IntegrityError("INSERT", {}, Exception("duplicate handle"))
        real(conn, *args, **kwargs)  # the competing profile
        return real(conn, *args, **kwargs)

    monkeypatch.setattr(joins, "create_profile", racing)
    refused = exchange(make_client(), picked)
    assert refused.status_code == 404, refused.text
    assert placement_row(setup, placement["id"]).membership_id is None


def test_a_lost_answer_is_recovered_and_three_pickups_is_all(
    setup: Setup, make_client: ClientFactory
) -> None:
    placement = placed(setup)
    first = pick_up(setup, placement).json()
    second = pick_up(setup, placement).json()
    assert second["pickup"] == 2
    assert exchange(make_client(), first).status_code == 404  # revoked by the second
    with setup.engine.connect() as conn:  # the hub's own revocation: nobody named or told
        revoked = conn.execute(
            select(t.join_link.c.revoked_by).where(t.join_link.c.revoked_at.is_not(None))
        ).all()
        assert len(revoked) == 1 and revoked[0].revoked_by is None
        told = conn.execute(select(t.event.c.seq).where(t.event.c.kind == "join_revoked")).all()
        assert told == []
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
        f"/projects/maintainer/maity/credentials/{first.headers['Maity-Credential-Id']}/revoke", {}
    )
    assert revoked.status_code == 200, revoked.text
    restarted = setup.owner.post(
        f"/projects/maintainer/maity/placements/{placement['id']}/restart", {"rejoin": True}
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
    placement = placed(setup)
    # Lowered after the creation, which checked it too (§15.5): the pickup checks again.
    _allow_instances(setup.engine, setup.agent.id, 1)  # the joined clone has the one
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
    assert audience == [f"member:{setup.owner.id}", "trust:owner"]


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


def _suspend_owner(s: Setup) -> Any:
    with events.transaction(s.engine) as conn:
        moderation.suspend(conn, s.owner.id, "rpt-000000000000")
    return SimpleNamespace(status_code=200, text="")


def _leak(s: Setup) -> Any:
    leaked = s.owner.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": "all", "body": s.runner.value},
    )
    assert error(leaked) == "credential_in_payload"  # refused, and the credential revoked
    return SimpleNamespace(status_code=200, text="")


def _re_pair(s: Setup, make_client: ClientFactory) -> Any:
    answer = runners.exchange(
        make_client(), runners.enroll(s.owner, name=None, runner_id=s.runner.id)
    )
    assert answer.status_code == 201, answer.text
    return SimpleNamespace(status_code=200, text="")


@pytest.mark.parametrize(
    "gone",
    [
        "deleted",
        "stopped",
        "runner_revoked",
        "runner_leaked",
        "runner_removed",
        "re_paired",
        "owner_suspended",
    ],
)
def test_an_unused_pickup_dies_with_its_placement_or_runner(
    setup: Setup, make_client: ClientFactory, gone: str
) -> None:
    """A re-pair and the owner's suspension revoke the credential that fetched it, too."""
    placement = placed(setup)
    picked = pick_up(setup, placement).json()
    path = f"/projects/maintainer/maity/placements/{placement['id']}"
    answer = {
        "deleted": lambda: setup.owner.delete(path),
        "stopped": lambda: setup.owner.patch(path, {"desired": "stopped"}),
        "runner_revoked": lambda: setup.owner.post(f"/runners/{setup.runner.id}/revoke", {}),
        "runner_removed": lambda: setup.owner.delete(f"/runners/{setup.runner.id}"),
        "runner_leaked": lambda: _leak(setup),
        "re_paired": lambda: _re_pair(setup, make_client),
        "owner_suspended": lambda: _suspend_owner(setup),
    }[gone]()
    assert answer.status_code == 200, answer.text
    with setup.engine.connect() as conn:
        joins = conn.execute(
            select(t.join_link.c.revoked_at).where(t.join_link.c.placement_id.is_not(None))
        ).all()
    assert joins and all(j.revoked_at is not None for j in joins)
    if gone != "re_paired":  # a re-pair leaves a live credential: the revocation refuses
        _unrevoke_joins(setup)
    members = _members(setup)
    refused = exchange(make_client(), picked)
    # A suspended creator's join is refused before anything else is read (§16.8).
    assert refused.status_code == (403 if gone == "owner_suspended" else 404), refused.text
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
    removed = setup.owner.delete(f"/projects/maintainer/maity/members/{setup.agent.id}")
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
        f"/projects/maintainer/maity/credentials/{first.headers['Maity-Credential-Id']}/revoke", {}
    )
    assert revoked.status_code == 200, revoked.text
    restarted = setup.owner.post(
        f"/projects/maintainer/maity/placements/{placement['id']}/restart", {"rejoin": True}
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
    # The placement reserves the handle (§6.24): a profile can only land by a race, as here.
    with setup.engine.begin() as conn:
        agents.create_profile(conn, setup.owner.id, "agent-f", "F", None, placement=True)
    refused = pick_up(setup, placement)
    assert (refused.status_code, error(refused)) == (409, "pickup_not_allowed")
    assert refused.json()["error"]["details"] == {"why": "handle_taken"}


def test_a_new_profile_under_another_owners_boss_waits_for_the_boss_side(
    setup: Setup, make_client: ClientFactory
) -> None:
    """§6.2 "Joins and placements": the membership starts without the boss, and the creator's
    creating the profile is the subordinate owner's consent, so only the boss's side is asked."""
    friend = flow.human(make_client, setup.engine, "friend")
    with setup.engine.connect() as conn:
        project = conn.execute(select(t.project.c.id)).scalar_one()
    boss = factory.agent(setup.engine, project, friend.id).agent_id
    placement = placed(
        setup, agent={"handle": "agent-n", "display_name": "Agent N"}, reports_to=boss
    )
    picked = pick_up(setup, placement)
    assert picked.status_code == 201, picked.text
    joined = exchange(make_client(), picked.json())
    assert joined.status_code == 201, joined.text
    with setup.engine.connect() as conn:
        created = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == joined.headers["Maity-Member-Id"])
        ).one()
        boss_row = conn.execute(select(t.membership).where(t.membership.c.agent_id == boss)).one()
        [request] = [
            r
            for r in conn.execute(select(t.request)).all()
            if (r.proposal or {}).get("kind") == cross_owner.KIND
        ]
    assert created.reports_to is None
    assert (request.to_human, request.status) == (friend.id, "open")
    assert request.proposal["side"] == "boss"
    assert (request.proposal["target"], request.proposal["boss"]) == (created.id, boss_row.id)
    answered = friend.post(f"/requests/{request.id}/answer", {"reply_id": "go"})
    assert answered.status_code == 200, answered.text
    with setup.engine.connect() as conn:
        after = conn.execute(select(t.membership).where(t.membership.c.id == created.id)).one()
    assert after.reports_to == boss_row.id


# --- supervised sessions (§15.11) ----------------------------------------------------------


def runs(s: Setup, placement: dict[str, Any], agent: Any) -> None:
    """The placement runs `agent`'s own instance, as after its pickup: the packet shows an
    instance the placement that names its credential, never a sibling's (§15.11)."""
    with s.engine.begin() as conn:
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == placement["id"])
            .values(credential_id=agent.credential_id)
        )


def test_a_supervised_resume_says_so(setup: Setup) -> None:
    placement = placed(setup)
    runs(setup, placement, setup.agent)
    supervised = setup.agent.resume(supervisor="maity-runner/0.1.0").json()
    assert supervised["hints"] == {"duty": "supervised", "cli_version": CLI_VERSION}
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
        latest = setup.agent.get(
            "/projects/maintainer/maity/events", params={"after": "latest", "wait": 0}
        )
        cursor = latest.json()["cursor"]
        said = setup.owner.post(
            "/projects/maintainer/maity/events",
            {"kind": "message", "type": "notice", "to": "all", "body": "hi"},
        )
        assert said.status_code == 201, said.text
        waited = setup.agent.get(
            "/projects/maintainer/maity/events", params={"after": cursor, "wait": 1}
        )
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
    # Before its pickup a placement runs no instance yet: nobody's packet shows it.
    assert setup.agent.resume().json()["membership"]["placement"] is None
    runs(setup, theirs, other)
    runs(setup, mine, setup.agent)
    assert setup.agent.resume().json()["membership"]["placement"]["id"] == mine["id"]
    assert other.resume().json()["membership"]["placement"]["id"] == theirs["id"]


def test_each_instance_sees_its_own_placement(setup: Setup, make_client: ClientFactory) -> None:
    """§15.11: each instance's packet names the placement that runs it, and an instance
    joined by hand, which no placement runs, gets none, never a sibling's."""
    _allow_instances(setup.engine, setup.agent.id, 4)
    first, second = placed(setup), placed(setup)
    client = make_client()
    joined = exchange(client, pick_up(setup, second).json())
    assert joined.status_code == 201, joined.text
    runs(setup, first, setup.agent)  # the joined clone runs the first
    assert setup.agent.resume().json()["membership"]["placement"]["id"] == first["id"]
    with setup.engine.connect() as conn:
        bound = conn.execute(
            select(t.placement.c.credential_id).where(t.placement.c.id == second["id"])
        ).scalar_one()
    assert bound != setup.agent.credential_id  # the second runs an instance of its own
    picked_up = flow.Agent(
        client,
        joined.text,
        joined.headers["Maity-Credential-Id"],
        joined.headers["Maity-Member-Id"],
        joined.headers["Maity-Instance"],
    )
    assert picked_up.credential_id == bound
    resumed = picked_up.resume()
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["membership"]["placement"]["id"] == second["id"]
    by_hand = flow.agent(make_client, setup.owner, agent={"id": setup.agent.id}, new_instance=True)
    assert by_hand.id == setup.agent.id and by_hand.instance not in ("", picked_up.instance)
    assert by_hand.resume().json()["membership"]["placement"] is None


def test_a_supervisor_is_a_runners_name(setup: Setup) -> None:
    refused = setup.agent.resume(supervisor="something else")
    assert refused.status_code == 400


def test_an_agent_without_a_placement_has_none(setup: Setup, make_client: ClientFactory) -> None:
    other = flow.agent(make_client, setup.owner)
    assert other.resume().json()["membership"]["placement"] is None


def _row(kind: str, audience: list[str]) -> Any:
    return SimpleNamespace(seq=1, actor_membership=None, kind=kind, audience=audience,
                           conversation_id=None, payload={}, wakes=None)  # fmt: skip


def test_a_supervised_session_wakes_on_less() -> None:
    me = SimpleNamespace(id=7, trust="member", role="coder", role_base="coder", agent_id="agt-b")
    for kind, audience, plain, supervised in (
        ("task_created", ["all"], True, False),
        ("state_changed", ["all"], True, True),
        ("rules_changed", ["all"], True, True),
        ("message", ["member:agt-b"], True, True),
        ("message", ["all", "member:agt-b"], True, True),
        ("message", ["all", "member:hum-a"], True, False),  # the sender's own term
        ("message", ["role:coder"], True, True),
    ):
        row = _row(kind, audience)
        assert events.wakes(row, me, "agt-b") is plain, kind
        assert events.wakes(row, me, "agt-b", supervised=True) is supervised, (kind, audience)


def test_the_hub_revoking_an_unused_pickup_names_nobody_and_tells_nobody(
    setup: Setup,
) -> None:
    """`revoke_unused_joins` is the hub's own revocation, whoever moved the placement (§3.1)."""
    placement = placed(setup)
    pick_up(setup, placement)
    path = f"/projects/maintainer/maity/placements/{placement['id']}"
    assert setup.owner.delete(path).status_code == 200
    with setup.engine.connect() as conn:
        joins = conn.execute(
            select(t.join_link.c.revoked_at, t.join_link.c.revoked_by).where(
                t.join_link.c.placement_id.is_not(None)
            )
        ).all()
        told = conn.execute(select(t.event.c.seq).where(t.event.c.kind == "join_revoked")).all()
    assert joins and all(j.revoked_at is not None and j.revoked_by is None for j in joins)
    assert told == []


# --- a profile that is not a member yet (§15.6, §15.9) -------------------------------------


def _own_profile(s: Setup, handle: str = "agent-own") -> str:
    """A profile made on its own (`POST /agents`, §6.3): no membership anywhere."""
    made = s.owner.post("/agents", {"handle": handle, "display_name": "Own agent"})
    assert made.status_code == 201, made.text
    agent_id: str = made.json()["id"]
    return agent_id


def _membership(s: Setup, agent_id: str) -> Any:
    with s.engine.connect() as conn:
        return conn.execute(
            select(t.membership).where(
                t.membership.c.agent_id == agent_id, t.membership.c.active.is_(True)
            )
        ).first()


def test_a_profile_not_yet_a_member_joins_at_its_first_pickup(
    setup: Setup, make_client: ClientFactory
) -> None:
    # §15.9: the pickup is a first join, neither new_instance nor replaces, bound to the
    # handle; its exchange makes the membership with the stored join fields.
    agent_id = _own_profile(setup)
    placement = placed(
        setup,
        agent={"id": agent_id},
        trust="guest",
        role="reviewer",
        briefing="You review the runner.",
        subagents=True,
    )
    assert _membership(setup, agent_id) is None
    picked = pick_up(setup, placement)
    assert picked.status_code == 201, picked.text
    assert picked.json()["credential_will_bind"] == "agent-own"
    with setup.engine.connect() as conn:
        join = conn.execute(
            select(t.join_link).where(t.join_link.c.placement_id == placement["id"])
        ).one()
    assert (join.agent_id, join.new_instance, join.replaces) == (agent_id, False, None)
    joined = exchange(make_client(), picked.json())
    assert joined.status_code == 201, joined.text
    assert joined.headers["Maity-Member-Id"] == agent_id
    member = _membership(setup, agent_id)
    assert (member.trust, member.role, member.briefing) == ("guest", "reviewer", join.briefing)
    assert member.briefing == "You review the runner." and member.subagents is True
    assert member.subagents_by == setup.owner.id
    row = placement_row(setup, placement["id"])
    assert row.membership_id == member.id
    assert row.credential_id == joined.headers["Maity-Credential-Id"]


def test_a_new_profiles_placement_takes_the_subagent_instruction(
    setup: Setup, make_client: ClientFactory
) -> None:
    placement = placed(setup, agent={"handle": "agent-s", "display_name": "S"}, subagents=True)
    joined = exchange(make_client(), pick_up(setup, placement).json())
    assert joined.status_code == 201, joined.text
    assert _membership(setup, joined.headers["Maity-Member-Id"]).subagents is True


def test_a_profile_its_owner_no_longer_allows_here_is_not_picked_up(setup: Setup) -> None:
    agent_id = _own_profile(setup)
    placement = placed(setup, agent={"id": agent_id})
    with setup.engine.begin() as conn:  # the owner unticked every project (§6.3)
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == agent_id)
            .values(allowed_projects=[])
        )
    refused = pick_up(setup, placement)
    assert (refused.status_code, error(refused)) == (409, "pickup_not_allowed")
    assert refused.json()["error"]["details"] == {"why": "project_not_allowed"}


@pytest.mark.parametrize("when", ["pickup", "exchange"])
def test_a_profile_placed_while_not_a_member_follows_its_creators_standing(
    setup: Setup, make_client: ClientFactory, when: str
) -> None:
    # §15.9: trust admin, placed by an owner who is only an admin by the pickup or the
    # exchange: what the creator could no longer give in a first join.
    agent_id = _own_profile(setup)
    placement = placed(setup, agent={"id": agent_id}, trust="admin")
    if when == "pickup":
        _demote_owner(setup)
        refused = pick_up(setup, placement)
        assert (refused.status_code, error(refused)) == (409, "pickup_not_allowed")
        assert refused.json()["error"]["details"] == {"why": "creator_lacks_authority"}
        return
    picked = pick_up(setup, placement)
    assert picked.status_code == 201, picked.text
    _demote_owner(setup)
    assert exchange(make_client(), picked.json()).status_code == 404
    assert _membership(setup, agent_id) is None


def test_a_profile_that_joined_by_a_line_meanwhile_gets_an_instance(
    setup: Setup, make_client: ClientFactory
) -> None:
    # §15.9: a member by the exchange: the exchange adds an instance within max_instances,
    # instance_quota beyond it, never not_found; the stored join fields change nothing.
    agent_id = _own_profile(setup)
    placement = placed(setup, agent={"id": agent_id}, role="reviewer")
    picked = pick_up(setup, placement).json()
    line = flow.exchange(make_client(), flow.join(setup.owner, "maity", agent={"id": agent_id}))
    assert line.status_code == 201, line.text
    over = exchange(make_client(), picked)
    assert (over.status_code, error(over)) == (409, "instance_quota")
    _allow_instances(setup.engine, agent_id, 2)
    again = pick_up(setup, placement)
    assert again.status_code == 201, again.text
    joined = exchange(make_client(), again.json())
    assert joined.status_code == 201, joined.text
    assert joined.headers["Maity-Instance"] != line.headers["Maity-Instance"]
    member = _membership(setup, agent_id)
    assert member.role == "coder"  # the line's, not the placement's
    assert placement_row(setup, placement["id"]).membership_id == member.id


def test_of_two_placements_of_a_profile_the_second_adds_an_instance(
    setup: Setup, make_client: ClientFactory
) -> None:
    agent_id = _own_profile(setup)
    first = placed(setup, agent={"id": agent_id})
    second = placed(setup, agent={"id": agent_id})
    picked = [pick_up(setup, p).json() for p in (first, second)]
    assert exchange(make_client(), picked[0]).status_code == 201
    over = exchange(make_client(), picked[1])
    assert (over.status_code, error(over)) == (409, "instance_quota")
    _allow_instances(setup.engine, agent_id, 2)
    joined = exchange(make_client(), pick_up(setup, second).json())
    assert joined.status_code == 201, joined.text
    with setup.engine.connect() as conn:
        members = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == agent_id)
        ).all()
    assert len(members) == 1


def _member_agents(s: Setup, value: str) -> None:
    with s.engine.begin() as conn:
        conn.execute(update(t.project).values(member_agents=value))


@pytest.mark.parametrize("when", ["pickup", "exchange"])
def test_member_agents_turned_off_ends_a_members_placement(
    setup: Setup, make_client: ClientFactory, when: str
) -> None:
    # §3.1, §15.9: a placement acts on its creator's continuing authority, read against the
    # policy at the pickup and again at the exchange; a pickup join handed out before the
    # switch goes with it, unlike a member's own join (test_member_agents).
    agent_id = _own_profile(setup)
    _as_member_with_member_agents(setup)
    placement = placed(setup, agent={"id": agent_id})
    if when == "pickup":
        _member_agents(setup, "off")
        refused = pick_up(setup, placement)
        assert (refused.status_code, error(refused)) == (409, "pickup_not_allowed")
        assert refused.json()["error"]["details"] == {"why": "creator_lacks_authority"}
        return
    picked = pick_up(setup, placement)
    assert picked.status_code == 201, picked.text
    _member_agents(setup, "off")
    gone = exchange(make_client(), picked.json())
    assert (gone.status_code, error(gone)) == (404, "not_found")
    assert _membership(setup, agent_id) is None


def test_member_agents_turned_off_leaves_an_admins_placement(
    setup: Setup, make_client: ClientFactory
) -> None:
    # The rule's scope: a creator with members:admin never placed under member_agents.
    agent_id = _own_profile(setup)
    _member_agents(setup, "on")
    placement = placed(setup, agent={"id": agent_id})
    _member_agents(setup, "off")
    picked = pick_up(setup, placement)
    assert picked.status_code == 201, picked.text
    joined = exchange(make_client(), picked.json())
    assert joined.status_code == 201, joined.text
    assert _membership(setup, agent_id) is not None


@pytest.mark.parametrize("when", ["pickup", "exchange"])
@pytest.mark.parametrize("raised", [False, True])
def test_a_members_placement_adds_an_instance_only_where_the_member_may(
    setup: Setup, make_client: ClientFactory, when: str, raised: bool
) -> None:
    # §3.1, §15.9: the profile joined by the member's own line after the placement. The
    # pickup adds an instance to that membership, which needs what a new_instance join for
    # it needs of the creator: a membership an admin raised beyond the member limits gets
    # one only through members:admin, whatever the placement's stored fields say.
    agent_id = _own_profile(setup)
    _as_member_with_member_agents(setup)
    placement = placed(setup, agent={"id": agent_id})
    early = pick_up(setup, placement).json() if when == "exchange" else None
    line = flow.exchange(make_client(), flow.join(setup.owner, "maity", agent={"id": agent_id}))
    assert line.status_code == 201, line.text
    _allow_instances(setup.engine, agent_id, 2)
    if raised:
        with setup.engine.begin() as conn:
            conn.execute(
                update(t.membership)
                .where(t.membership.c.agent_id == agent_id)
                .values(trust="admin")
            )
    if early is None:
        picked = pick_up(setup, placement)
        if raised:
            assert (picked.status_code, error(picked)) == (409, "pickup_not_allowed")
            assert picked.json()["error"]["details"] == {"why": "creator_lacks_authority"}
            return
        assert picked.status_code == 201, picked.text
        early = picked.json()
    joined = exchange(make_client(), early)
    if raised:
        assert (joined.status_code, error(joined)) == (404, "not_found")
        assert placement_row(setup, placement["id"]).membership_id is None
        return
    assert joined.status_code == 201, joined.text
    assert joined.headers["Maity-Instance"] != line.headers["Maity-Instance"]
    assert placement_row(setup, placement["id"]).membership_id == _membership(setup, agent_id).id


@pytest.mark.parametrize("when", ["pickup", "exchange"])
def test_an_admins_placement_adds_an_instance_of_an_admin_only_as_an_owner(
    setup: Setup, make_client: ClientFactory, when: str
) -> None:
    # §3.1, §15.9: the profile joined with trust admin after the placement; its creator,
    # an admin by now, may still give the stored first join (trust member) but not a new
    # instance of an admin member, which is the owner's to give.
    agent_id = _own_profile(setup)
    placement = placed(setup, agent={"id": agent_id})
    early = pick_up(setup, placement).json() if when == "exchange" else None
    line = flow.exchange(
        make_client(), flow.join(setup.owner, "maity", agent={"id": agent_id}, trust="admin")
    )
    assert line.status_code == 201, line.text
    _allow_instances(setup.engine, agent_id, 2)
    _demote_owner(setup)
    if early is None:
        refused = pick_up(setup, placement)
        assert (refused.status_code, error(refused)) == (409, "pickup_not_allowed")
        assert refused.json()["error"]["details"] == {"why": "creator_lacks_authority"}
        return
    gone = exchange(make_client(), early)
    assert (gone.status_code, error(gone)) == (404, "not_found")


def test_removing_the_membership_closes_the_placements_still_without_a_credential(
    setup: Setup, make_client: ClientFactory
) -> None:
    # §6.2: a removal is not undone by a placement still waiting for its pickup.
    agent_id = _own_profile(setup)
    first = placed(setup, agent={"id": agent_id})
    waiting = placed(setup, agent={"id": agent_id})
    assert exchange(make_client(), pick_up(setup, first).json()).status_code == 201
    _allow_instances(setup.engine, agent_id, 2)
    picked = pick_up(setup, waiting).json()
    removed = setup.owner.delete(f"/projects/maintainer/maity/members/{agent_id}")
    assert removed.status_code == 200, removed.text
    row = placement_row(setup, waiting["id"])
    assert (row.active, row.closed_reason) == (None, "membership_removed")
    assert exchange(make_client(), picked).status_code == 404
    later = pick_up(setup, waiting)
    assert (later.status_code, error(later)) == (409, "pickup_not_allowed")
    assert later.json()["error"]["details"] == {"why": "not_running"}
    assert _membership(setup, agent_id) is None


def test_isolating_the_membership_closes_the_placements_still_without_a_credential(
    setup: Setup, make_client: ClientFactory
) -> None:
    # §6.2: an isolation closes the profile's waiting placements as a removal does, those
    # made while it was not a member included.
    agent_id = _own_profile(setup)
    waiting = placed(setup, agent={"id": agent_id})
    line = flow.exchange(make_client(), flow.join(setup.owner, "maity", agent={"id": agent_id}))
    assert line.status_code == 201, line.text
    isolated = setup.owner.post(
        f"/projects/maintainer/maity/members/{agent_id}/isolate", {"reason": "it did a thing"}
    )
    assert isolated.status_code == 200, isolated.text
    row = placement_row(setup, waiting["id"])
    assert (row.active, row.closed_reason) == (None, "membership_isolated")
    later = pick_up(setup, waiting)
    assert (later.status_code, error(later)) == (409, "pickup_not_allowed")
    assert later.json()["error"]["details"] == {"why": "not_running"}


def test_a_profile_a_waiting_placement_admits_is_in_use(setup: Setup) -> None:
    # §6.3: an active placement makes the profile in use, one that admits it included; a
    # bare DELETE is refused and changes nothing.
    agent_id = _own_profile(setup)
    placement = placed(setup, agent={"id": agent_id})
    refused = setup.owner.client.delete(
        f"/api/v1/agents/{agent_id}", headers={"X-CSRF-Token": setup.owner.csrf}
    )
    assert (refused.status_code, error(refused)) == (409, "profile_in_use")
    assert refused.json()["error"]["details"] == {
        "memberships": [],
        "placements": [placement["id"]],
    }
    row = placement_row(setup, placement["id"])
    assert (row.active, row.closed_reason) == (True, None)
    with setup.engine.connect() as conn:
        deleted_at = conn.execute(
            select(t.agent_profile.c.deleted_at).where(t.agent_profile.c.id == agent_id)
        ).scalar()
    assert deleted_at is None


def test_a_deleted_profiles_waiting_placement_closes(
    setup: Setup, make_client: ClientFactory
) -> None:
    # §6.3: the cascade delete closes it at once (`removed`), on the owner's authority
    # alone: a member under "Bringing your own agent", without members:admin. The event
    # names the owner, and the unused pickup is revoked with it.
    agent_id = _own_profile(setup)
    _as_member_with_member_agents(setup)
    placement = placed(setup, agent={"id": agent_id})
    picked = pick_up(setup, placement)
    assert picked.status_code == 201, picked.text
    deleted = setup.owner.client.delete(
        f"/api/v1/agents/{agent_id}?cascade=true", headers={"X-CSRF-Token": setup.owner.csrf}
    )
    assert deleted.status_code == 200, deleted.text
    row = placement_row(setup, placement["id"])
    assert (row.active, row.closed_reason) == (None, "removed")
    closed = events_of(setup, "placement_updated")[-1]
    assert closed["payload"]["closed_reason"] == "removed"
    assert (closed["actor"]["kind"], closed["actor"]["member_id"]) == ("member", setup.owner.id)
    with setup.engine.connect() as conn:
        join = conn.execute(
            select(t.join_link).where(t.join_link.c.placement_id == placement["id"])
        ).one()
    assert join.revoked_at is not None
    assert exchange(make_client(), picked.json()).status_code == 404
    later = pick_up(setup, placement)
    assert (later.status_code, error(later)) == (409, "pickup_not_allowed")


def _placements_of(s: Setup, agent_id: str) -> list[Any]:
    with s.engine.connect() as conn:
        return list(
            conn.execute(select(t.placement).where(t.placement.c.agent_id == agent_id)).all()
        )


def _deleted_at(s: Setup, agent_id: str) -> Any:
    with s.engine.connect() as conn:
        return conn.execute(
            select(t.agent_profile.c.deleted_at).where(t.agent_profile.c.id == agent_id)
        ).scalar()


@pytest.mark.parametrize("creator", ["admin", "member"])
def test_a_profile_deleted_before_the_placement_is_never_admitted(
    setup: Setup, creator: str
) -> None:
    # §6.3: deleted first, the profile is never placed: an admin's placement is
    # `not_found`, a member's has no profile to admit and so needs `members:admin`, as
    # before; no placement either way.
    agent_id = _own_profile(setup)
    deleted = setup.owner.client.delete(
        f"/api/v1/agents/{agent_id}", headers={"X-CSRF-Token": setup.owner.csrf}
    )
    assert deleted.status_code == 200, deleted.text
    if creator == "member":
        _as_member_with_member_agents(setup)
    refused = place(setup, agent={"id": agent_id})
    expected = (404, "not_found") if creator == "admin" else (403, "forbidden")
    assert (refused.status_code, error(refused)) == expected
    assert _placements_of(setup, agent_id) == []


def test_an_admitting_placement_locks_the_profile_before_the_project(setup: Setup) -> None:
    # §6.3: join creation, the exchange and the deletion take the profile's lock first,
    # then the project's; the creation of a placement that admits the profile does too.
    from tests.test_moderation import transactions

    agent_id = _own_profile(setup)
    with transactions(setup.engine) as seen:
        placed(setup, agent={"id": agent_id})
    [statements] = [x for x in seen if any(y.startswith("INSERT INTO placement ") for y in x)]

    def first(test: Any) -> int:
        return next(i for i, x in enumerate(statements) if test(x))

    profile = first(
        lambda x: x.startswith(
            "SELECT agent_profile.id \nFROM agent_profile \nWHERE agent_profile.id ="
        )
    )
    project = first(lambda x: x.startswith("SELECT project.id,") and "WHERE project.id =" in x)
    assert profile < project, statements
    if setup.engine.dialect.name != "sqlite":  # SQLite renders no lock clause
        assert "FOR UPDATE" in statements[profile] and "FOR UPDATE" in statements[project]
    assert "agent_profile.owner_id =" in statements[profile]  # the caller's own only
    # Before its lock, only whose it is, which never changes.
    reads = [x for x in statements[:profile] if "FROM agent_profile" in x]
    assert [x.startswith("SELECT agent_profile.owner_id \nFROM") for x in reads] == [True]


def test_an_admitting_placement_reads_the_named_profile_three_times(setup: Setup) -> None:
    """Whose it is before its lock, the lock, then one read of owner, handle, deletion and
    membership here under both locks (`_named_profile`): not one read per check, and no
    second `_admits` (audit R5 batch 2, finding 5)."""
    from tests.test_moderation import transactions

    agent_id = _own_profile(setup)
    with transactions(setup.engine) as seen:
        placed(setup, agent={"id": agent_id})
    [statements] = [x for x in seen if any(y.startswith("INSERT INTO placement ") for y in x)]
    # Up to the profile's `allowed_projects` check, where the checks of the name end; what
    # comes after (the placement's creator, the view) is not this lookup.
    end = next(i for i, x in enumerate(statements) if "agent_profile.allowed_projects" in x)
    named = [x for x in statements[:end] if x.startswith("SELECT") and "agent_profile.id = " in x]
    assert len(named) == 3, "\n----\n".join(named)


def _is_profile_lock(statement: str) -> bool:
    """`_lock_named_profile`'s locking read: the profile's id alone, by id and owner (the one
    read after it, `_named_profile`, selects other columns)."""
    lock = "SELECT agent_profile.id \nFROM agent_profile \nWHERE agent_profile.id ="
    return statement.startswith(lock) and "deleted_at" not in statement


@pytest.mark.parametrize("creator", ["admin", "member"])
def test_a_placement_naming_another_owners_profile_takes_no_lock_on_it(
    setup: Setup, make_client: ClientFactory, creator: str
) -> None:
    # §15.6: only the caller's own profile is admitted, so only it is locked; another
    # member naming someone else's profile must not hold the lock that owner's join
    # creation, exchange and deletion wait for (§6.3). The answer stays `not_yours`.
    from tests.test_moderation import transactions

    other = flow.human(make_client, setup.engine, "someone")
    made = other.post("/agents", {"handle": "theirs", "display_name": "Their agent"})
    assert made.status_code == 201, made.text
    if creator == "member":
        _as_member_with_member_agents(setup)
    with transactions(setup.engine) as seen:
        refused = place(setup, agent={"id": made.json()["id"]})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"agent.id": "not_yours"}
    statements = [x for each in seen for x in each]
    assert any("FROM project" in x for x in statements)  # the creation's were seen
    assert not [x for x in statements if _is_profile_lock(x)], statements
    locks = [x for x in statements if "FROM agent_profile" in x and "FOR UPDATE" in x]
    assert locks == [], locks  # SQLite renders no lock clause; the servers would show it


def test_a_deletion_holding_the_profile_makes_the_placement_wait_and_find_it_gone(
    setup: Setup,
) -> None:
    # §6.3: the deletion took the profile's lock and tombstoned it; the placement waits
    # for its commit and then answers `not_found`, with no placement (PostgreSQL, MariaDB).
    from tests.concurrency import finished, race, waiting

    agent_id = _own_profile(setup)
    with race(setup.engine) as r:
        deletion, other = r.first, r.second
        agents.owned(deletion, agent_id, setup.owner.id, deleted=True, lock=True)
        deletion.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == agent_id)
            .values(deleted_at=clock.now())
        )
        creating = r.run(other, lambda: place(setup, agent={"id": agent_id}))
        assert waiting(creating)  # on the profile's lock the deletion holds
        deletion.commit()
        refused = finished(creating)
    assert (refused.status_code, error(refused)) == (404, "not_found")
    assert _placements_of(setup, agent_id) == []


def test_a_placement_holding_the_profile_makes_the_deletion_wait_and_find_it_in_use(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    # §6.3: the creation took the profile's lock before the project's; a deletion waits for
    # its commit and then finds the profile in use by the placement that admits it, which
    # a bare DELETE refuses and a cascade closes (PostgreSQL, MariaDB).
    from maity_hub.routes import placements as placement_routes
    from tests.concurrency import FINISH_WITHIN, finished, race, waiting
    from tests.test_account_deletion import paused

    agent_id = _own_profile(setup)
    reached, go = paused(monkeypatch, placement_routes, "_admitted")
    with race(setup.engine) as r:
        other, deletion = r.first, r.second
        creating = r.run(other, lambda: place(setup, agent={"id": agent_id}))
        try:
            assert reached.wait(FINISH_WITHIN)  # both locks held, the placement not yet made

            def deleting() -> list[str]:
                agents.owned(deletion, agent_id, setup.owner.id, deleted=True, lock=True)
                return agents._in_use(deletion, agent_id)[1]

            checking = r.run(deletion, deleting)
            assert waiting(checking)  # on the profile's lock the creation holds
        finally:
            go.set()
        made = finished(creating)
        assert made.status_code == 201, made.text
        assert finished(checking) == [made.json()["id"]]
    refused = setup.owner.client.delete(
        f"/api/v1/agents/{agent_id}", headers={"X-CSRF-Token": setup.owner.csrf}
    )
    assert (refused.status_code, error(refused)) == (409, "profile_in_use")
    assert _deleted_at(setup, agent_id) is None


def test_a_placement_made_before_the_cascade_delete_is_closed_by_it(setup: Setup) -> None:
    # §6.3: the other order, one after the other: the cascade closes it (`removed`).
    agent_id = _own_profile(setup)
    placement = placed(setup, agent={"id": agent_id})
    deleted = setup.owner.client.delete(
        f"/api/v1/agents/{agent_id}?cascade=true", headers={"X-CSRF-Token": setup.owner.csrf}
    )
    assert deleted.status_code == 200, deleted.text
    row = placement_row(setup, placement["id"])
    assert (row.active, row.closed_reason) == (None, "removed")
    assert _deleted_at(setup, agent_id) is not None


NEW_AGENT = {"handle": "agent-n", "display_name": "Agent N"}


def test_a_new_profiles_placement_reads_its_handle_under_the_handles_lock(setup: Setup) -> None:
    # §6.24: the handle's lock after the project's, as a pickup's exchange takes them, and
    # before the read of who holds the handle (the statement order, any database).
    from tests.test_moderation import transactions

    with transactions(setup.engine) as seen:
        placed(setup, agent=NEW_AGENT)
    [statements] = [x for x in seen if any(y.startswith("INSERT INTO placement ") for y in x)]

    def first(test: Any) -> int:
        return next(i for i, x in enumerate(statements) if test(x))

    project = first(lambda x: x.startswith("SELECT project.id,") and "WHERE project.id =" in x)
    handle = first(lambda x: x.startswith("INSERT INTO handle_lock "))
    locked = first(lambda x: x.startswith("SELECT handle_lock.handle \nFROM handle_lock"))
    holder = first(lambda x: "FROM handle_alias" in x)
    assert project < handle < locked < holder, statements
    if setup.engine.dialect.name != "sqlite":  # SQLite renders no lock clause
        assert "FOR UPDATE" in statements[project] and "FOR UPDATE" in statements[locked]


def test_a_post_agents_waits_for_a_new_profiles_placement_and_finds_the_handle_reserved(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    # §6.24, §15.5: the placement read the handle as free under its lock and holds it; a
    # `POST /agents` of the same owner and handle waits for it and is then refused `taken`,
    # where before both committed and only the pickup refused the placement (`handle_taken`)
    # (PostgreSQL, MariaDB).
    # TODO(tsk-447hj5cxcjvc): move to the shared barrier helper in tests/concurrency.py once
    # it lands, if it can hold one side after the meeting; this test needs the placement's
    # transaction kept open while the other side tries the lock, which `paused` gives.
    from maity_hub.errors import ApiError
    from maity_hub.routes import placements as placement_routes
    from tests.concurrency import FINISH_WITHIN, finished, race, waiting
    from tests.test_account_deletion import paused

    # `_exists` is the creation's first call after the handle's read.
    reached, go = paused(monkeypatch, placement_routes, "_exists")
    with race(setup.engine) as r:
        other, giving = r.first, r.second
        creating = r.run(other, lambda: place(setup, agent=NEW_AGENT))
        try:
            assert reached.wait(FINISH_WITHIN)  # the handle read, the placement not yet made
            step = r.run(
                giving,
                lambda: agents.create_profile(giving, setup.owner.id, "agent-n", "Agent N", None),
            )
            assert waiting(step)  # on the handle's lock the placement holds
        finally:
            go.set()
        made = finished(creating)
        assert made.status_code == 201, made.text
        with pytest.raises(ApiError) as refused:
            finished(step)
    assert refused.value.code == "invalid"
    assert refused.value.details == {"fields": {"handle": "taken"}}
    with setup.engine.connect() as conn:
        profiles = conn.execute(
            select(t.agent_profile.c.id).where(t.agent_profile.c.handle == "agent-n")
        ).all()
    assert profiles == []
    picked = pick_up(setup, made.json())
    assert picked.status_code == 201, picked.text


def _manager(s: Setup, role: str = "manager") -> None:
    """The owner's joined agent with the role `manager`, or moved off it."""
    with s.engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == s.agent.id)
            .values(role=role, role_base=role)
        )


@pytest.mark.parametrize("when", ["pickup", "exchange"])
@pytest.mark.parametrize("change", [None, "role", "left"])
def test_a_members_placement_reports_only_to_a_manager_still_theirs(
    setup: Setup, make_client: ClientFactory, when: str, change: str | None
) -> None:
    # §3.1, §15.9: a member's placement may name their own manager as `reports_to`; it acts
    # on the creator's continuing authority, so the stored reporting line is read again at
    # the pickup and at the exchange: a manager moved off the role or gone since voids it
    # (a member's own join, already handed out, keeps it: test_member_agents).
    agent_id = _own_profile(setup)
    _manager(setup)
    _as_member_with_member_agents(setup)
    placement = placed(setup, agent={"id": agent_id}, reports_to=setup.agent.id)
    early = pick_up(setup, placement) if when == "exchange" else None
    if early is not None:
        assert early.status_code == 201, early.text
    if change == "role":
        _manager(setup, "coder")
    elif change == "left":
        with setup.engine.begin() as conn:
            conn.execute(
                update(t.membership)
                .where(t.membership.c.agent_id == setup.agent.id)
                .values(active=None)
            )
    picked = early if early is not None else pick_up(setup, placement)
    if change is not None and when == "pickup":
        assert (picked.status_code, error(picked)) == (409, "pickup_not_allowed")
        assert picked.json()["error"]["details"] == {"why": "creator_lacks_authority"}
        assert _membership(setup, agent_id) is None
        return
    assert picked.status_code == 201, picked.text
    joined = exchange(make_client(), picked.json())
    if change is not None:
        assert (joined.status_code, error(joined)) == (404, "not_found")
        assert _membership(setup, agent_id) is None
        return
    assert joined.status_code == 201, joined.text
    assert _membership(setup, agent_id).reports_to == _membership(setup, setup.agent.id).id
