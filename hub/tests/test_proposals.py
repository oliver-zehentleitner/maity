"""The shared mechanism for changes that wait for a human's go (`maity_hub.proposals`)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, select, update

from maity_hub import proposals
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError
from maity_hub.events import transaction
from maity_hub.routes.requests import file_consent
from tests import factory, flow
from tests.conftest import ClientFactory

settled: list[proposals.Settlement] = []
failing: list[bool] = []


def _settle(conn: Connection, settlement: proposals.Settlement) -> None:
    if failing:
        raise ApiError(409, "test_refused", "the change is no longer allowed")
    settled.append(settlement)


def _shown(conn: Connection, request: Any, proposal: dict[str, Any]) -> dict[str, Any]:
    return {"test_proposal": {"value": proposal["value"]}}


@pytest.fixture(autouse=True)
def _kinds() -> Iterator[None]:
    proposals.register("test", _settle, proposals.Answerer())
    proposals.register(
        "test-admin",
        _settle,
        proposals.Answerer(scope="project:admin", refusal="a human with project:admin decides"),
        view=_shown,
    )
    settled.clear()
    failing.clear()
    yield
    proposals.KINDS.pop("test", None)
    proposals.KINDS.pop("test-admin", None)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _membership_id(migrated: Engine, agent: flow.Agent) -> int:
    with migrated.connect() as conn:
        found: int = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == agent.id)
        ).scalar_one()
    return found


def _file(migrated: Engine, agent: flow.Agent, kind: str = "test") -> str:
    with transaction(migrated) as conn:
        row = conn.execute(select(t.membership).where(t.membership.c.agent_id == agent.id)).one()
        caller = Caller(
            kind="agent",
            via="bearer",
            agent_id=agent.id,
            credential_id=agent.credential_id,
            membership_id=row.id,
            project_id=row.project_id,
        )
        mine = membership(conn, caller, "maintainer/maity")
        return file_consent(
            conn, mine, caller, "Test it", "why", proposal={"kind": kind, "value": 7}
        )


def answer(who: Any, request_id: str, **body: Any) -> Any:
    return who.post(f"/projects/maintainer/maity/requests/{request_id}/answer", body)


def status(owner: flow.Human, request_id: str) -> str:
    found: str = owner.get(f"/projects/maintainer/maity/requests/{request_id}").json()["status"]
    return found


def test_a_go_settles_with_the_proposer_as_actor_and_the_human_as_approver(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    request_id = _file(migrated, admin)
    go = answer(owner, request_id, reply_id="go")
    assert go.status_code == 200, go.text
    [done] = settled
    assert (done.request.id, done.outcome, done.proposal) == (
        request_id,
        "go",
        {"kind": "test", "value": 7},
    )
    assert done.proposer.membership_id == _membership_id(migrated, admin)  # not the approver
    assert done.approver == owner.id
    assert done.closer is not None and done.closer.membership_id != done.proposer.membership_id


@pytest.mark.parametrize("body", [{"reply_id": "no"}, {"text": "not like this"}])
def test_any_other_answer_settles_no(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, body: dict[str, Any]
) -> None:
    request_id = _file(migrated, flow.agent(make_client, owner, role="admin"))
    assert answer(owner, request_id, **body).status_code == 200
    assert [(s.outcome, s.approver) for s in settled] == [("no", owner.id)]


def test_no_agent_answers_not_even_the_asker(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    request_id = _file(migrated, admin)
    for agent in (flow.agent(make_client, owner, role="admin"), admin):
        refused = answer(agent, request_id, reply_id="go")
        assert refused.status_code == 403
        assert refused.json()["error"]["details"] == {"reason": "humans_only"}
    assert settled == [] and status(owner, request_id) == "open"


def test_a_failing_settle_leaves_the_request_open(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    request_id = _file(migrated, flow.agent(make_client, owner, role="admin"))
    failing.append(True)
    refused = answer(owner, request_id, reply_id="go")
    assert (refused.status_code, refused.headers["Maity-Error"]) == (409, "test_refused")
    assert status(owner, request_id) == "open"


def test_a_withdrawal_settles_once_and_none_follows_a_go(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    withdrawn = _file(migrated, admin)
    admin.post(f"/projects/maintainer/maity/requests/{withdrawn}/withdraw", {"reason": "no longer"})
    assert [(s.outcome, s.approver) for s in settled] == [("withdrawn", None)]
    answered = _file(migrated, admin)
    answer(owner, answered, reply_id="go")
    late = admin.post(
        f"/projects/maintainer/maity/requests/{answered}/withdraw", {"reason": "late"}
    )
    assert (late.status_code, late.headers["Maity-Error"]) == (409, "request_not_open")
    assert [s.outcome for s in settled] == ["withdrawn", "go"]


def test_the_proposers_removal_withdraws_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    request_id = _file(migrated, admin)
    removed = owner.delete(f"/projects/maintainer/maity/members/{admin.id}")
    assert removed.status_code == 200, removed.text
    assert status(owner, request_id) == "withdrawn"
    assert [(s.outcome, s.approver) for s in settled] == [("withdrawn", None)]
    late = answer(owner, request_id, reply_id="go")
    assert (late.status_code, late.headers["Maity-Error"]) == (409, "request_not_open")
    assert len(settled) == 1


def test_a_replayed_answer_settles_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    request_id = _file(migrated, flow.agent(make_client, owner, role="admin"))
    headers = {"X-CSRF-Token": owner.csrf, "Idempotency-Key": "proposal-replay-0001"}
    url = f"/api/v1/projects/maintainer/maity/requests/{request_id}/answer"
    first = owner.client.post(url, json={"reply_id": "go"}, headers=headers)
    again = owner.client.post(url, json={"reply_id": "go"}, headers=headers)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert len(settled) == 1


def test_the_proposal_stays_in_the_hub(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    request_id = _file(migrated, admin)
    answered = answer(owner, request_id, reply_id="go").json()
    shown = [owner.get(f"/projects/maintainer/maity/requests/{request_id}").json(), answered]
    shown += admin.resume().json()["requests"]["answered_since_cursor"]
    with migrated.connect() as conn:
        shown += [
            row.payload
            for row in conn.execute(select(t.event).where(t.event.c.subject_id == request_id))
        ]
    # A replay is loaded through the same view (idempotency.LOADERS), never stored.
    assert shown and all("proposal" not in view and "value" not in view for view in shown)


def test_a_kind_names_who_answers_it_whatever_the_answer(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    proxy = flow.human(make_client, migrated, "proxy")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "proxy", human_id=proxy.id)
    request_id = _file(migrated, flow.agent(make_client, owner, role="admin"), "test-admin")
    # requests:answer, not project:admin: refused for go, no, free text and talk alike
    for body in ({"reply_id": "go"}, {"reply_id": "no"}, {"text": "hm"}, {"talk": True}):
        refused = answer(proxy, request_id, **body)
        assert (refused.status_code, refused.json()["error"]["details"]) == (
            403,
            {"scope": "project:admin"},
        ), body
    agent = answer(flow.agent(make_client, owner, role="admin"), request_id, reply_id="no")
    assert agent.json()["error"]["message"] == "a human with project:admin decides"
    assert status(owner, request_id) == "open" and settled == []
    assert answer(owner, request_id, reply_id="go").status_code == 200
    assert len(settled) == 1


def test_a_kinds_fields_show_on_the_request_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    request_id = _file(migrated, flow.agent(make_client, owner, role="admin"), "test-admin")
    view = owner.get(f"/projects/maintainer/maity/requests/{request_id}").json()
    assert view["test_proposal"] == {"value": 7} and "proposal" not in view
    answered = answer(owner, request_id, reply_id="go").json()
    listed = owner.get("/projects/maintainer/maity/requests?status=all").json()["items"]
    with migrated.connect() as conn:
        payloads = [
            row.payload
            for row in conn.execute(select(t.event).where(t.event.c.subject_id == request_id))
        ]
    assert len(payloads) == 2  # request_created, request_answered
    assert all("test_proposal" not in v for v in [answered, *listed, *payloads])


def test_an_unknown_kind_is_not_filed_and_fails_on_its_request_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    with pytest.raises(ValueError, match="not registered"):
        _file(migrated, admin, "nobody")
    request_id = _file(migrated, admin)
    with transaction(migrated) as conn:  # a hub that no longer knows the kind
        conn.execute(
            update(t.request)
            .where(t.request.c.id == request_id)
            .values(proposal={"kind": "gone", "value": 7})
        )
    failed = answer(owner, request_id, reply_id="go")
    assert (failed.status_code, failed.headers["Maity-Error"]) == (500, "proposal_kind_unknown")
    withdrawn = admin.post(
        f"/projects/maintainer/maity/requests/{request_id}/withdraw", {"reason": "x"}
    )
    assert withdrawn.status_code == 500
    assert owner.get("/projects/maintainer/maity/requests?status=open").status_code == 200
    other = flow.agent(make_client, owner, role="admin")
    packet = other.resume()
    assert packet.status_code == 200
    assert request_id not in [r["id"] for r in packet.json()["requests"]["to_answer"]]


def test_the_proposers_removal_withdraws_an_unknown_kind_without_settling(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    request_id = _file(migrated, admin)
    with transaction(migrated) as conn:  # a hub that no longer knows the kind
        conn.execute(
            update(t.request)
            .where(t.request.c.id == request_id)
            .values(proposal={"kind": "gone", "value": 7})
        )
    removed = owner.delete(f"/projects/maintainer/maity/members/{admin.id}")
    assert removed.status_code == 200, removed.text  # the removal is not held up by it
    with migrated.connect() as conn:
        row = conn.execute(select(t.request).where(t.request.c.id == request_id)).one()
    assert row.status == "withdrawn" and settled == []
    assert "'gone' is unknown to this hub" in row.withdraw_reason
    assert row.withdraw_reason.startswith("the proposer was removed")


def test_a_kind_is_registered_once() -> None:
    with pytest.raises(ValueError, match="registered already"):
        proposals.register("test", _settle, proposals.Answerer(humans_only=False))
    assert proposals.KINDS["test"].answerer.humans_only


def test_a_consent_carries_a_placement_or_a_proposal(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner, role="admin")
    with transaction(migrated) as conn:
        row = conn.execute(select(t.membership).where(t.membership.c.agent_id == agent.id)).one()
        caller = Caller(
            kind="agent",
            via="bearer",
            agent_id=agent.id,
            credential_id=agent.credential_id,
            membership_id=row.id,
            project_id=row.project_id,
        )
        mine = membership(conn, caller, "maintainer/maity")
        with pytest.raises(ValueError, match="not both"):
            file_consent(
                conn, mine, caller, "x", "y", placement_id="plc-x", proposal={"kind": "test"}
            )
