"""`Server-Timing` on the API's answers: the statements an answer sent, their time and the
hub's whole time, nothing else; on a success only, never on a refusal or outside the API."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.statements import count_statements

SHAPE = re.compile(r'db;dur=(\d+\.\d), sql;desc="n=(\d+)", total;dur=(\d+\.\d)')


def _timing(response: Any) -> tuple[float, int, float]:
    found = SHAPE.fullmatch(response.headers["server-timing"])
    assert found, response.headers["server-timing"]
    return float(found[1]), int(found[2]), float(found[3])


def test_a_list_and_a_single_read_say_their_statements_and_time(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    for path in ("/projects/maintainer/maity/tasks?status=all", "/projects/maintainer/maity"):
        answers: list[Any] = []
        sent = count_statements(migrated, lambda path=path: answers.append(owner.get(path)))
        [response] = answers
        assert response.status_code == 200, response.text
        db, statements, total = _timing(response)
        assert statements == sent > 0
        assert 0 <= db <= total


def test_a_refusal_and_a_page_outside_the_api_carry_none(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    # How many statements a 404 took could tell a hidden project from a missing one.
    missing = owner.get("/projects/maintainer/nothing-here")
    assert missing.status_code == 404
    assert "server-timing" not in missing.headers
    assert "server-timing" not in owner.client.get("/").headers
