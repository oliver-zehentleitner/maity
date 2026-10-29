"""The request log's `ms=` and `route=`, and the `stats` line once a minute
(hub/context/serving.md)."""

from __future__ import annotations

import logging
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from maity_hub import db, request_stats
from tests.conftest import ClientFactory

ACCESS = "maity_hub.access"


@pytest.fixture(autouse=True)
def _fresh_window() -> None:
    request_stats.WINDOW.take()


def access_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == ACCESS]


def test_the_route_is_the_path_with_the_values_put_back_as_names() -> None:
    scope = {
        "route": object(),
        "path": "/api/v1/projects/ann/maity/tasks/tsk-1",
        "path_params": {"owner": "ann", "slug": "maity", "card": "tsk-1"},
    }
    assert request_stats.route_of(scope) == "/api/v1/projects/{owner}/{slug}/tasks/{card}"
    assert request_stats.route_of({"path": "/x"}) == "-"
    # A value that is also a word of the path is put back at the first place it occurs.
    twin = {"route": object(), "path": "/projects/projects/x", "path_params": {"a": "projects"}}
    assert request_stats.route_of(twin) == "/{a}/projects/x"


def test_a_routed_request_logs_its_time_and_the_pattern_not_the_values(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=ACCESS):
        client.get("/api/v1/health")
        client.get("/api/v1/projects/someone/nothing-here")
    health, project = access_lines(caplog)
    assert re.fullmatch(r"GET /api/v1/health 200 ms=\d+ route=/api/v1/health", health)
    assert project.startswith("GET /api/v1/projects/someone/nothing-here 4")
    assert re.search(r" ms=\d+ route=/api/v1/\S*\{\S+\}", project)  # a pattern, not the slug


def test_an_unrouted_request_has_a_dash(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=ACCESS):
        client.get("/api/v1/no/such/route/at/all")
    (only,) = access_lines(caplog)
    assert re.fullmatch(r"GET /api/v1/no/such/route/at/all 404 ms=\d+ route=-", only)


def test_the_window_counts_requests_errors_and_the_slowest_and_starts_again() -> None:
    window = request_stats.Window()
    for status, ms in ((200, 5), (404, 7), (500, 90), (503, 12)):
        window.record(status, ms)
    assert window.take() == request_stats.Snapshot(requests=4, errors=2, slowest_ms=90)
    assert window.take() == request_stats.Snapshot(requests=0, errors=0, slowest_ms=0)


def test_every_logged_request_is_counted(client: TestClient) -> None:
    client.get("/api/v1/health")
    client.get("/api/v1/health")
    taken = request_stats.WINDOW.take()
    assert taken.requests >= 2 and taken.errors == 0


def test_a_server_error_is_counted_as_5xx(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("broken")

    monkeypatch.setattr("maity_hub.app.current_revision", boom)
    quiet = TestClient(client.app, raise_server_exceptions=False)  # no lifespan: it checks too
    assert quiet.get("/api/v1/health").status_code == 500
    assert request_stats.WINDOW.take().errors >= 1


def test_the_stats_line_is_key_value_and_names_the_pool_of_a_server_database() -> None:
    engine = db.make_engine("postgresql+psycopg://u:p@localhost/h", 5, 3)
    window = request_stats.Window()
    window.record(200, 41)
    window.record(502, 80)
    assert request_stats.line(window, engine, 60) == (
        "stats window=60s requests=2 5xx=1 max_ms=80 pool_open=0 pool_checked_out=0 pool_max=8"
    )


def test_a_pool_that_cannot_be_counted_says_none() -> None:
    class Bare:
        pool = object()

    assert request_stats.pool_fields(Bare()) == "pool=none"  # type: ignore[arg-type]


def test_the_reporter_logs_once_per_interval_and_stops(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    window = request_stats.Window()
    window.record(500, 3)
    reporter = request_stats.Reporter(engine, interval=0.05, window=window)
    with caplog.at_level(logging.INFO, logger="maity_hub.stats"):
        reporter.start()
        deadline = 100
        while deadline and not [r for r in caplog.records if r.name == "maity_hub.stats"]:
            import time

            time.sleep(0.05)
            deadline -= 1
        reporter.stop()
    lines = [r.getMessage() for r in caplog.records if r.name == "maity_hub.stats"]
    assert lines and lines[0].startswith("stats window=0.05s requests=1 5xx=1 max_ms=3 ")


def test_the_serving_hub_starts_and_stops_its_reporter(make_client: ClientFactory) -> None:
    with make_client():  # the lifespan runs with the client
        pass
