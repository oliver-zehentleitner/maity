"""docs/api.md §15.9 the join pickup and §15.11 supervised sessions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update

from maity_hub import events
from maity_hub import tables as t
from tests import flow
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
    return Setup(owner, runner, client, flow.agent(make_client, owner, role="member"), migrated)


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


def test_a_rejoin_picks_up_again(setup: Setup, make_client: ClientFactory) -> None:
    placement = placed(setup)
    exchange(make_client(), pick_up(setup, placement).json())
    with setup.engine.begin() as conn:
        conn.execute(
            update(t.placement).where(t.placement.c.id == placement["id"]).values(rejoin=True)
        )
    again = pick_up(setup, placement)
    assert again.status_code == 201, again.text
    joined = exchange(make_client(), again.json())
    row = placement_row(setup, placement["id"])
    assert row.credential_id == joined.headers["Maity-Credential-Id"] and row.rejoin is False


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
    ):
        row = _row(kind, audience)
        assert events.wakes(row, me, "agt-b") is plain, kind
        assert events.wakes(row, me, "agt-b", supervised=True) is supervised, (kind, audience)
