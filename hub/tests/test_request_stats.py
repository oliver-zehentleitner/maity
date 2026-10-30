"""The request log's `ms=` and `route=`, and the `stats` line once a minute
(hub/context/serving.md)."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from maity_hub import db, request_stats
from maity_hub.app import create_app
from maity_hub.config import Settings

ACCESS = "maity_hub.access"


@pytest.fixture(autouse=True)
def _fresh_window() -> None:
    request_stats.WINDOW.take()


def access_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == ACCESS]


def test_the_route_is_the_declared_pattern_whatever_the_values_look_like(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Values that are also words of the prefix or of the pattern (`api`, `v1`, `badge`) must
    neither shift the pattern nor reach the log: it is the route's own text, not a rebuilt path."""
    with caplog.at_level(logging.INFO, logger=ACCESS):
        client.get("/api/v1/projects/api/v1/tasks")
        client.get("/api/v1/join/api")
        client.get("/badge/badge/badge.svg")
    project, join, badge = access_lines(caplog)
    assert project.endswith("route=/api/v1/projects/{owner}/{slug}/tasks")
    assert join.startswith("GET /api/v1/join/… 404 ") and join.endswith(
        "route=/api/v1/join/{token}"
    )
    assert badge.endswith("route=/badge/{owner}/{slug}.svg")


def test_a_method_the_route_refuses_still_names_the_route(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A 405 on a project route (`ProjectRoute` rewrites its path parameters before the endpoint)
    logs the same pattern as an answered request would."""
    with caplog.at_level(logging.INFO, logger=ACCESS):
        client.delete("/api/v1/projects/o/s/tasks")
        client.put("/api/v1/health")
    project, health = access_lines(caplog)
    assert " 405 " in project and project.endswith("route=/api/v1/projects/{owner}/{slug}/tasks")
    assert " 405 " in health and health.endswith("route=/api/v1/health")


def test_a_route_that_cannot_be_told_from_the_path_is_a_dash() -> None:
    import re as regex

    class Route:
        path = "/x/{id}"
        path_format = "/x/{id}"
        path_regex = regex.compile(r"^/x/(?P<id>[^/]+)$")

    assert request_stats.route_of({"route": Route(), "path": "/x/1"}) == "/x/{id}"
    assert request_stats.route_of({"route": Route(), "path": "/api/v1/x/1"}) == "/api/v1/x/{id}"
    assert request_stats.route_of({"route": Route(), "path": "/elsewhere"}) == "-"
    assert request_stats.route_of({"route": object(), "path": "/x/1"}) == "-"
    assert request_stats.route_of({"path": "/x"}) == "-"


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


def stats_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "maity-stats" and t.is_alive()]


def test_the_serving_hub_starts_and_stops_its_reporter(
    settings: Settings, migrated: Engine
) -> None:
    before = len(stats_threads())
    with TestClient(create_app(settings, migrated)):  # the lifespan runs inside `with`
        assert len(stats_threads()) == before + 1
    assert len(stats_threads()) == before
