"""`Server-Timing` on the API's answers: the statements an answer sent, their time and the
hub's whole time, nothing else; only to the instance admin's signed-in session, never to
anyone else and never outside the API."""

from __future__ import annotations

import logging
import re
from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.statements import count_statements

SHAPE = re.compile(r'db;dur=(\d+\.\d), sql;desc="n=(\d+)", total;dur=(\d+\.\d)')


def _timing(response: Any) -> tuple[float, int, float]:
    found = SHAPE.fullmatch(response.headers["server-timing"])
    assert found, response.headers["server-timing"]
    return float(found[1]), int(found[2]), float(found[3])


def test_the_instance_admin_sees_each_answers_statements_and_time(
    make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.human(make_client, migrated)  # the earliest account is the instance admin
    flow.project(admin)
    for path in ("/projects/maintainer/maity/tasks?status=all", "/projects/maintainer/maity"):
        answers: list[Any] = []
        sent = count_statements(
            migrated, lambda path=path, answers=answers: answers.append(admin.get(path))
        )
        [response] = answers
        assert response.status_code == 200, response.text
        db, statements, total = _timing(response)
        assert statements == sent > 0
        assert 0 <= db <= total
    # A refusal too: the admin measures it, and nobody else sees the header at all.
    missing = admin.get("/projects/maintainer/nothing-here")
    assert missing.status_code == 404
    _timing(missing)
    assert "server-timing" not in admin.client.get("/").headers


def test_nobody_else_learns_hidden_data_from_it(
    make_client: ClientFactory, migrated: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    served = lambda **kw: make_client(public_pages=True, **kw)  # noqa: E731
    admin = flow.human(served, migrated)
    pat = flow.human(served, migrated, "pat")
    stranger = flow.human(served, migrated, "sam")
    assert pat.patch("/me", {"public_profile": True, "public_bio": "here"}).status_code == 200
    flow.project(pat, "secret")  # private: its agents are not on pat's page
    seen = []
    for _ in range(3):
        response = stranger.get("/people/pat")
        assert response.status_code == 200, response.text
        # The answer stays the same while pat's hidden agents grow, and nothing beside it
        # (a statement count, a duration) may tell the stranger that they did.
        assert "server-timing" not in response.headers
        seen.append(response.json())
        agent = flow.agent(make_client, pat, "pat/secret")
        assert "server-timing" not in agent.get("/me").headers
    assert seen[0] == seen[1] == seen[2]
    # The operators read every request's count in the log, by route pattern, never the path.
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="maity_hub.timing"):
        stranger.get("/people/pat")
    [line] = [r.getMessage() for r in caplog.records if r.name == "maity_hub.timing"]
    assert re.fullmatch(
        r"route=/api/v1/people/\{handle\} status=200 sql=\d+ db_ms=\d+\.\d total_ms=\d+\.\d",
        line,
    ), line
    assert "server-timing" not in pat.get("/people/pat").headers
    _timing(admin.get("/people/pat"))
