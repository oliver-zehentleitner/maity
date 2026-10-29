"""docs/api.md §6.23: `why` on a code report."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import _report, task

BASE = "/projects/maintainer/maity"
REF = "context/keep-the-why.md#ktw-policy"


def _setup(
    make_client: ClientFactory, migrated: Engine, **project: Any
) -> tuple[flow.Human, flow.Agent, dict[str, Any]]:
    owner = flow.human(make_client, migrated)
    flow.project(owner, **project)
    agent = flow.agent(make_client, owner)
    card = task(owner)
    assert agent.post(f"{BASE}/tasks/{card['id']}/claim", {}).status_code == 200
    return owner, agent, card


def _send(agent: flow.Agent, card: dict[str, Any], **overrides: Any) -> Any:
    body = _report(**overrides)
    if body["why"] is None:
        body.pop("why")
    return agent.post(f"{BASE}/tasks/{card['id']}/report", body)


def _reason(response: Any) -> Any:
    assert response.headers["Maity-Error"] == "invalid", response.text
    return response.json()["error"]["details"]["fields"]["why"]


def test_a_code_report_without_why_is_refused_under_required(
    make_client: ClientFactory, migrated: Engine
) -> None:
    _, agent, card = _setup(make_client, migrated)
    assert _reason(_send(agent, card, why=None)) == "required"


def test_why_is_optional_under_optional_and_under_no_provider(
    make_client: ClientFactory, migrated: Engine
) -> None:
    _, agent, card = _setup(make_client, migrated, memory={"provider": "none"})
    assert _send(agent, card, why=None).status_code == 200


def test_a_ref_is_stored_and_the_card_learns_it(
    make_client: ClientFactory, migrated: Engine
) -> None:
    _, agent, card = _setup(make_client, migrated)
    done = _send(agent, card, why={"ref": REF})
    assert done.status_code == 200, done.text
    assert done.json()["ktw_ref"] == REF
    assert done.json()["report"]["why"] == {"ref": REF}


def test_a_ref_does_not_replace_the_cards_own(make_client: ClientFactory, migrated: Engine) -> None:
    owner, agent, card = _setup(make_client, migrated)
    owner.patch(f"{BASE}/tasks/{card['id']}", {"ktw_ref": "context/x.md#own"})
    assert _send(agent, card, why={"ref": REF}).json()["ktw_ref"] == "context/x.md#own"


def test_none_is_stored_with_its_reason(make_client: ClientFactory, migrated: Engine) -> None:
    _, agent, card = _setup(make_client, migrated)
    reason = "a mechanical rename, no decision"
    done = _send(agent, card, why={"none": reason})
    assert done.status_code == 200, done.text
    assert done.json()["report"]["why"] == {"none": reason}
    assert done.json()["ktw_ref"] is None


@pytest.mark.parametrize(
    "why",
    [
        {},
        {"ref": REF, "none": "a long enough reason"},
        {"ref": "context/keep-the-why.md"},
        {"ref": "context/keep-the-why.txt#id"},
        {"ref": "/etc/x.md#id"},
        {"ref": "../x.md#id"},
        {"ref": 3},
        {"none": "too short"},
        {"other": "a long enough reason"},
        "context/keep-the-why.md#id",
    ],
)
def test_other_shapes_are_malformed(make_client: ClientFactory, migrated: Engine, why: Any) -> None:
    _, agent, card = _setup(make_client, migrated)
    assert _reason(_send(agent, card, why=why)) == "malformed"


def test_the_shape_holds_under_optional_too(make_client: ClientFactory, migrated: Engine) -> None:
    _, agent, card = _setup(make_client, migrated, memory={"provider": "none"})
    assert _reason(_send(agent, card, why={"none": "short"})) == "malformed"


def test_why_on_a_report_without_code_is_refused(
    make_client: ClientFactory, migrated: Engine
) -> None:
    _, agent, card = _setup(make_client, migrated)
    refused = agent.post(
        f"{BASE}/tasks/{card['id']}/report",
        {"summary": "a review", "code": False, "pr_status": "none", "why": {"ref": REF}},
    )
    assert _reason(refused) == "not_for_no_code"
    ok = agent.post(
        f"{BASE}/tasks/{card['id']}/report",
        {"summary": "a review", "code": False, "pr_status": "none"},
    )
    assert ok.status_code == 200, ok.text
