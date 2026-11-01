"""docs/api.md §6.1, §6.4, §6.6: `done_authority` `tester` and `reviewer_and_tester`, the two
signatures on a card, per report revision."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_tasks import _report, task

BASE = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity")
    return human


def _authority(owner: flow.Human, authority: str) -> None:
    done = owner.patch(BASE, {"policy": {"done_authority": authority}, "reason": "t"})
    assert done.status_code == 200, done.text


def _person(make_client: ClientFactory, engine: Engine, handle: str, role: str) -> flow.Human:
    human = flow.human(make_client, engine, handle)
    with engine.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(engine, project_id, role, trust="member", human_id=human.id)
    return human


def _in_review(owner: flow.Human, worker: Any) -> dict[str, Any]:
    card = task(owner)
    path = f"{BASE}/tasks/{card['id']}"
    assert worker.post(f"{path}/claim", {}).status_code == 200
    reported = worker.post(f"{path}/report", _report())
    assert reported.status_code == 200, reported.text
    assert reported.json()["status"] == "review"
    return dict(reported.json())


def _sign(who: Any, card: dict[str, Any], **body: Any) -> Any:
    return who.patch(f"{BASE}/tasks/{card['id']}", {"status": "done", **body})


@pytest.fixture
def team(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> dict[str, Any]:
    _authority(owner, "reviewer_and_tester")
    return {
        "reviewer": _person(make_client, migrated, "rev", "reviewer"),
        "tester": _person(make_client, migrated, "tes", "tester"),
        "worker": _person(make_client, migrated, "wor", "coder"),
    }


def test_two_members_sign_and_only_the_second_closes_the_card(
    owner: flow.Human, team: dict[str, Any], migrated: Engine
) -> None:
    card = _in_review(owner, team["worker"])
    assert card["approvals"] == {"review": None, "test": None}
    assert card["report"]["revision"] == 1
    first = _sign(team["reviewer"], card)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "review"
    mark = first.json()["approvals"]["review"]
    assert (mark["by"], mark["revision"]) == (team["reviewer"].id, 1)
    assert first.json()["approvals"]["test"] is None
    with migrated.connect() as conn:
        event = conn.execute(
            select(t.event).where(t.event.c.kind == "task_updated").order_by(t.event.c.seq.desc())
        ).first()
    assert event is not None and event.payload["fields"] == ["approvals"]
    second = _sign(team["tester"], card)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "done"
    assert second.json()["approvals"] is None  # only while it is in review


def test_a_caller_holding_both_says_which_and_never_fills_both(
    owner: flow.Human, team: dict[str, Any]
) -> None:
    card = _in_review(owner, team["worker"])
    required = _sign(owner, card)
    assert required.status_code == 400, required.text
    assert required.json()["error"]["details"]["fields"] == {"approve": "required"}
    signed = _sign(owner, card, approve="review")
    assert signed.status_code == 200, signed.text
    twice = _sign(owner, card, approve="test")
    assert twice.status_code == 400, twice.text
    assert twice.json()["error"]["details"]["fields"] == {"approve": "same_member"}


def test_a_signature_needs_its_scope(owner: flow.Human, team: dict[str, Any]) -> None:
    card = _in_review(owner, team["worker"])
    assert _sign(team["reviewer"], card, approve="test").status_code == 403
    assert _sign(team["worker"], card).status_code == 403


def test_rework_and_a_new_report_clear_both_and_the_revision_counts(
    owner: flow.Human, team: dict[str, Any]
) -> None:
    card = _in_review(owner, team["worker"])
    path = f"{BASE}/tasks/{card['id']}"
    assert _sign(team["reviewer"], card).status_code == 200
    again = team["worker"].post(f"{path}/report", _report(summary="A second try."))
    assert again.status_code == 200, again.text
    assert again.json()["report"]["revision"] == 2
    assert again.json()["approvals"] == {"review": None, "test": None}
    assert _sign(team["tester"], card).json()["approvals"]["test"]["revision"] == 2
    rework = team["reviewer"].patch(path, {"status": "in_progress"})
    assert rework.status_code == 200, rework.text
    third = team["worker"].post(f"{path}/report", _report(summary="A third."))
    assert third.json()["report"]["revision"] == 3
    assert third.json()["approvals"] == {"review": None, "test": None}


def test_a_report_with_done_fills_the_callers_signature_and_never_closes(
    owner: flow.Human, team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    card = task(owner)
    path = f"{BASE}/tasks/{card['id']}"
    assert team["reviewer"].post(f"{path}/claim", {}).status_code == 200
    reported = team["reviewer"].post(f"{path}/report", _report(done=True))
    assert reported.status_code == 200, reported.text
    assert reported.json()["status"] == "review"
    assert reported.json()["approvals"]["review"]["by"] == team["reviewer"].id
    assert reported.json()["approvals"]["test"] is None


def test_the_body_cannot_set_approvals_and_approve_needs_the_policy(
    owner: flow.Human, team: dict[str, Any]
) -> None:
    card = _in_review(owner, team["worker"])
    path = f"{BASE}/tasks/{card['id']}"
    set_it = owner.patch(path, {"approvals": {"review": None, "test": None}})
    assert set_it.status_code == 400, set_it.text
    assert set_it.json()["error"]["details"]["fields"] == {"approvals": "read_only"}
    assert owner.patch(path, {"status": "in_progress", "approve": "test"}).status_code == 400
    _authority(owner, "reviewer")
    assert owner.get(path).json()["approvals"] is None
    assert _sign(owner, card, approve="review").status_code == 400


def test_a_tester_alone_closes_under_tester_and_a_reviewer_does_not(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _authority(owner, "tester")
    worker = _person(make_client, migrated, "wor", "coder")
    tester = _person(make_client, migrated, "tes", "tester")
    reviewer = _person(make_client, migrated, "rev", "reviewer")
    card = _in_review(owner, worker)
    refused = _sign(reviewer, card)
    assert refused.status_code == 403, refused.text
    done = _sign(tester, card)
    assert done.status_code == 200, done.text
    assert (done.json()["status"], done.json()["approvals"]) == ("done", None)


@pytest.mark.parametrize("authority", ["tester", "reviewer_and_tester"])
def test_a_preset_change_keeps_the_authorities_that_require_a_test(
    owner: flow.Human, authority: str
) -> None:
    _authority(owner, authority)
    changed = owner.patch(BASE, {"policy": {"preset": "hybrid"}, "reason": "t"})
    assert changed.status_code == 200, changed.text
    assert owner.get(BASE).json()["policy"]["done_authority"] == authority


def test_the_export_lists_the_signatures_a_person_gave(
    owner: flow.Human, team: dict[str, Any]
) -> None:
    card = _in_review(owner, team["worker"])
    assert _sign(team["reviewer"], card).status_code == 200
    exported = team["reviewer"].get("/me/export").json()
    assert [row["card"]["id"] for row in exported["card_approvals"]] == [card["id"]]
    assert team["tester"].get("/me/export").json()["card_approvals"] == []
