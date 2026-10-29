"""docs/api.md §20.6, §20.9: the report, its triage, and what an adoption opens."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock, listening
from maity_hub import tables as t
from maity_hub.jourfixe import worker
from tests import flow
from tests.conftest import ClientFactory
from tests.test_jour_fixe_exchange import Round, kinds, rounds_path


@pytest.fixture(autouse=True)
def _no_listeners() -> Iterator[None]:
    yield
    listening._open.clear()


@pytest.fixture
def now() -> list[datetime]:
    moment = [datetime.now(UTC).replace(microsecond=0)]
    clock.set_source(lambda: moment[0])
    return moment


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


@pytest.fixture
def reporting(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> Round:
    """A round whose exchange closed: the statement in, the response step over."""
    round_ = Round(owner, make_client, migrated, now)
    assert round_.statement().status_code == 201
    round_.tick()
    assert round_.get()["status"] == "reporting"
    return round_


def decided(owner: flow.Human, outcome: str = "adopt", **basis: Any) -> dict[str, Any]:
    return {
        "title": "Pin the runner image",
        "reason": "Fewer surprises.",
        "topic_id": "t1",
        "triage": "decided",
        "decision": {
            "outcome": outcome,
            "reason": "The rules let the admin agent pin images.",
            "basis": {"rules_version": 1, "human_id": owner.id, "preferences_version": 0, **basis},
        },
    }


TO_OWNER = {
    "title": "Cache the venv",
    "reason": "minutes per run",
    "topic_id": "t1",
    "statement_proposal_id": "t1.s1",
    "triage": "to_owner",
}


def report(round_: Round, who: Any = None, **body: Any) -> Any:
    payload = {
        "summary": "CI hurts.",
        "findings": [{"topic_id": "t1", "text": "CI is slow."}],
        "proposals": [decided(round_.owner), TO_OWNER],
        **body,
    }
    return (who or round_.lead).post(rounds_path(round_.id, "/report"), payload)


def test_a_decided_adoption_opens_a_card_and_to_owner_files_a_decision(
    reporting: Round,
) -> None:
    done = report(reporting)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["round"]["status"] == "reported" and body["round"]["reported_at"]
    [task_id], [request_id] = body["tasks"], body["requests"]
    card = reporting.owner.get(f"/projects/maintainer/maity/tasks/{task_id}").json()
    assert card["status"] == "open" and card["assigned_to"] is None
    assert card["created_by"] == reporting.lead.id and card["title"] == "Pin the runner image"
    assert card["jour_fixe"] == {"round_id": reporting.id, "proposal_id": "r1"}
    asked = reporting.owner.get(f"/projects/maintainer/maity/requests/{request_id}").json()
    assert asked["class"] == "decision" and asked["to"] == "owner"
    assert [o["id"] for o in asked["options"]] == ["adopt", "reject"]
    assert asked["jour_fixe"] == {"round_id": reporting.id, "proposal_id": "r2"}
    [proposal_one, proposal_two] = body["round"]["report"]["proposals"]
    assert proposal_one["task_id"] == task_id and proposal_two["request_id"] == request_id
    assert proposal_two["statement_proposal_id"] == "t1.s1"
    [reported] = kinds(reporting.engine, "jour_fixe_reported")
    assert reported.audience == ["all"]
    assert [p["outcome"] for p in reported.payload["proposals"]] == ["adopt", None]
    again = report(reporting)
    assert again.status_code == 409 and again.json()["error"]["code"] == "jour_fixe_state"


def test_the_owners_adopt_opens_the_card_a_reject_opens_nothing(reporting: Round) -> None:
    second = {**TO_OWNER, "title": "Drop the flaky test", "statement_proposal_id": None}
    body = report(reporting, proposals=[TO_OWNER, second]).json()
    first_request, second_request = body["requests"]
    path = "/projects/maintainer/maity/requests/{}/answer"
    assert (
        reporting.owner.post(path.format(first_request), {"reply_id": "adopt"}).status_code == 200
    )
    assert (
        reporting.owner.post(path.format(second_request), {"reply_id": "reject"}).status_code == 200
    )
    with reporting.engine.connect() as conn:
        cards = conn.execute(select(t.card).where(t.card.c.jour_fixe.isnot(None))).all()
    [card] = cards
    assert card.title == "Cache the venv" and card.jour_fixe["proposal_id"] == "r1"
    created_by = conn_principal(reporting.engine, card.created_by)
    assert created_by == reporting.owner.id  # the decider


def conn_principal(engine: Engine, membership_id: int) -> str:
    with engine.connect() as conn:
        row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
    found: str = row.agent_id or row.human_id
    return found


def test_who_may_report_and_decide(reporting: Round) -> None:
    other = report(reporting, who=reporting.member)
    assert other.json()["error"]["details"]["reason"] == "not_moderator"
    flagged = report(reporting, proposals=[{**decided(reporting.owner), "humans_only": True}])
    assert flagged.json()["error"]["details"]["reason"] == "humans_only"
    stranger = report(reporting, proposals=[decided(reporting.owner, human_id="hum-x")])
    assert stranger.json()["error"]["details"]["fields"] == {"basis": "not_owner_preferences"}
    unknown = report(reporting, proposals=[decided(reporting.owner, preferences_version=7)])
    assert unknown.json()["error"]["details"]["fields"] == {"basis": "unknown_version"}
    source = report(reporting, proposals=[{**TO_OWNER, "statement_proposal_id": "t1.s9"}])
    assert source.json()["error"]["details"]["fields"] == {
        "proposals": "unknown_statement_proposal"
    }
    assert report(reporting).status_code == 200


def test_no_report_before_the_exchange_closed(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    round_ = Round(owner, make_client, migrated, now)
    round_.statement()
    early = report(round_)
    assert early.status_code == 409 and early.json()["error"]["code"] == "jour_fixe_state"


def test_without_a_report_in_time_the_hub_builds_one_from_the_statement(
    reporting: Round,
) -> None:
    reporting.owner.patch("/projects/maintainer/maity", {"settings": {"ticker": {"enabled": True}}})
    reporting.tick(timedelta(hours=13))
    view = reporting.get()
    assert view["status"] == "reported"
    built = view["report"]
    assert built["source"] == "hub" and built["summary"] is None
    [finding] = built["findings"]
    assert finding["derived_from"] == "topic:t1" and finding["text"].startswith("CI is slow")
    [proposal] = built["proposals"]
    assert proposal["triage"] == "to_owner" and proposal["statement_proposal_id"] == "t1.s1"
    assert proposal["request_id"] is not None
    [item] = [e for e in kinds(reporting.engine, "ticker") if e.payload["type"] == "jour_fixe"]
    assert item.audience == ["all"]
    assert item.payload["text"].endswith("2 answers, 1 proposals (0 decided, 1 to the owner)")
    assert item.payload["dedupe_key"] == f"jour_fixe:{reporting.id}"


def test_a_closed_project_finishes_the_round_but_opens_no_card(reporting: Round) -> None:
    closed = reporting.owner.patch(
        "/projects/maintainer/maity", {"state": "accepted", "reason": "done"}
    )
    assert closed.status_code == 200, closed.text
    body = report(reporting, proposals=[decided(reporting.owner)])
    assert body.status_code == 200, body.text
    built = body.json()["round"]["report"]
    assert built["proposals"][0]["task_id"] is None
    assert built["proposals_not_carded"] == [{"proposal_id": "r1", "reason": "project_closed"}]


def test_a_report_replay_answers_only_a_member(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    from tests import factory
    from tests.test_jour_fixe_exchange import STEP, listen

    other = flow.human(make_client, migrated, "other")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "admin", human_id=other.id)
    series = {
        "enabled": False,
        "recurrence": {"freq": "daily"},
        "time": "10:00",
        "timezone": "UTC",
        "moderator": other.id,
    }
    assert (
        owner.patch(
            "/projects/maintainer/maity", {"policy": {"jour_fixe": series}, "reason": "r"}
        ).status_code
        == 200
    )
    member = flow.agent(make_client, owner)
    listen(member)
    other.get("/me")
    round_id = other.post("/projects/maintainer/maity/jour-fixe/rounds", {"reason": "r"}).json()[
        "id"
    ]
    member.post(rounds_path(round_id, "/answers"), {"went_well": "ok"})
    now[0] += STEP
    worker.sweep(migrated)
    other.get("/me")
    statement = {"topics": [{"title": "T", "items": [{"text": "ok", "from": member.id}]}]}
    assert other.post(rounds_path(round_id, "/statement"), statement).status_code == 201
    now[0] += STEP
    worker.sweep(migrated)
    path = f"/api/v1{rounds_path(round_id, '/report')}"
    headers = {"X-CSRF-Token": other.csrf, "Idempotency-Key": "jour-fixe-report-replay-1"}
    body = {"summary": "s", "findings": [], "proposals": []}
    first = other.client.post(path, json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert owner.delete(f"/projects/maintainer/maity/members/{other.id}").status_code == 200
    replay = other.client.post(path, json=body, headers=headers)
    assert replay.status_code == 404, replay.text


def test_a_demoted_moderator_no_longer_decides(reporting: Round) -> None:
    demoted = reporting.owner.patch(
        f"/projects/maintainer/maity/members/{reporting.lead.id}", {"trust": "member"}
    )
    assert demoted.status_code == 200, demoted.text
    refused = report(reporting, proposals=[decided(reporting.owner)])
    assert refused.json()["error"]["details"]["reason"] == "may_not_decide"


def test_the_report_keeps_its_byte_caps(reporting: Round) -> None:
    summary = report(reporting, summary="ä" * 4097)  # 8194 bytes
    assert summary.json()["error"]["details"]["fields"] == {"summary": "too_long"}
    finding = report(reporting, findings=[{"topic_id": "t1", "text": "ä" * 513}])
    assert finding.json()["error"]["details"]["fields"] == {"findings": "too_long"}
    reason = report(reporting, proposals=[{**TO_OWNER, "reason": "ä" * 1025}])
    assert reason.json()["error"]["details"]["fields"] == {"proposals": "too_long"}
    ascii_over = report(reporting, summary="a" * 8193)
    assert ascii_over.status_code == 400
    assert report(reporting, summary="ä" * 4096).status_code == 200  # 8192 bytes: in
