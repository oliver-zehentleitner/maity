"""A page of requests costs the same statements for 5 requests as for 30: the views of
a page are built in one batch (`request_views`), never with lookups per row; a single
read goes through the same batch and shows the same view."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.statements import count_statements
from tests.test_claims import _claim
from tests.test_requests import asked
from tests.test_tasks import task

_ROUND = [0]
LIST = "/projects/maintainer/maity/requests?status=all&to=all&limit=200"


Pair = tuple[flow.Agent, flow.Agent]


def _pairs(owner: flow.Human, make_client: ClientFactory) -> list[Pair]:
    """Two agents and two admins, each with a session: few joins, under their rate limit."""
    pairs = []
    for _ in range(2):
        worker = flow.agent(make_client, owner)
        admin = flow.agent(make_client, owner, role="admin")
        worker.resume(harness="Claude Code")
        admin.resume(harness="Claude Code")
        pairs.append((worker, admin))
    return pairs


def _grow(owner: flow.Human, pairs: list[Pair], rounds: int) -> None:
    """Five requests a round, the pairs taking turns: an agent's on its card to an
    instance, an admin's on behalf of the agent, a forwarded one, one that needs the
    agent's session, and the owner's own to the agent."""
    for _ in range(rounds):
        worker, admin = pairs[_ROUND[0] % len(pairs)]
        _ROUND[0] += 1
        card = task(owner)
        assert _claim(worker, card).status_code == 200
        asked(worker, task_id=card["id"], to=f"{admin.id}#{admin.instance}")
        asked(admin, on_behalf_of=worker.id, to="role:coder")
        forwarded = asked(worker)
        moved = owner.post(
            f"/projects/maintainer/maity/requests/{forwarded['id']}/forward", {"to": admin.id}
        )
        assert moved.status_code == 200, moved.text
        asked(worker, needs_in_session={"reason": "a production write", "member_id": worker.id})
        asked(owner, to=worker.id)


def _statements(engine: Engine, call: Callable[[], Any]) -> int:
    def checked() -> None:
        response = call()
        assert response.status_code == 200, response.text

    return count_statements(engine, checked)


def test_a_page_of_requests_costs_the_same_for_5_and_for_30(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    calls: dict[str, Callable[[], Any]] = {
        "project": lambda: owner.get(LIST),
        "all": lambda: owner.get("/requests?status=all&to=all&limit=200"),
    }
    pairs = _pairs(owner, make_client)
    _grow(owner, pairs, 1)
    small = {name: _statements(migrated, call) for name, call in calls.items()}
    _grow(owner, pairs, 5)
    large = {name: _statements(migrated, call) for name, call in calls.items()}
    assert len(owner.get(LIST).json()["items"]) == 30
    assert large == small


def test_a_listed_request_is_the_request_read_alone(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    _grow(owner, _pairs(owner, make_client), 2)
    items = owner.get(LIST).json()["items"]
    assert len(items) == 10
    for item in items:
        alone = owner.get(f"/projects/maintainer/maity/requests/{item['id']}").json()
        alone.pop("agent_change")  # the single read's own field (§7)
        assert item == alone
