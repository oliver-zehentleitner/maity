"""The request log's `ms=` and `route=`, and the `stats` line once a minute
(hub/context/serving.md)."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from typing import Any

import anyio
import anyio.to_thread
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from maity_hub import db, middleware, request_stats
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
    assert request_stats.lines(window, engine, 60, request_stats.LoadWindow()) == [
        "stats window=60s requests=2 5xx=1 max_ms=80 slow_routes=0 "
        "pool_open=0 pool_checked_out=0 pool_max=8 loop_late_avg_ms=0 loop_late_max_ms=0 "
        "threads_busy_avg=0.0 threads_busy_max=0 threads_waiting_max=0 threads_limit=0"
    ]


def _engine() -> Engine:
    return db.make_engine("postgresql+psycopg://u:p@localhost/h", 5, 3)


def test_a_route_with_a_slow_request_gets_its_line_and_a_fast_one_none() -> None:
    window = request_stats.Window()
    window.record(200, 40, "GET", "/api/v1/fast")
    window.record(200, 200, "GET", "/api/v1/tasks/{id}")
    window.record(200, 1200, "GET", "/api/v1/tasks/{id}")
    window.record(500, 3100, "GET", "/api/v1/tasks/{id}")
    stats, *routes = request_stats.lines(window, _engine(), 60, request_stats.LoadWindow())
    assert " requests=4 5xx=1 max_ms=3100 slow_routes=1 " in stats
    assert routes == [
        "stats_route window=60s method=GET route=/api/v1/tasks/{id} requests=3 over_1s=2 "
        "over_3s=1 total_ms=4500 max_ms=3100"
    ]
    assert (
        request_stats.lines(window, _engine(), 60, request_stats.LoadWindow())[1:] == []
    )  # the window started again


def test_the_routes_are_kept_apart_by_method_and_the_worst_come_first() -> None:
    window = request_stats.Window()
    window.record(200, 1000, "POST", "/x")
    window.record(200, 1000, "GET", "/x")
    window.record(200, 1000, "GET", "/x")
    window.record(200, 9000, "GET", "/y")
    routes = request_stats.lines(window, _engine(), 60, request_stats.LoadWindow())[1:]
    assert [line.split()[2:4] for line in routes] == [
        ["method=GET", "route=/x"],  # two slow requests outrank one long one
        ["method=GET", "route=/y"],
        ["method=POST", "route=/x"],
    ]


def test_the_lines_are_capped_and_the_stats_line_says_how_many_there_were() -> None:
    window = request_stats.Window()
    for n in range(request_stats.ROUTE_LINES + 5):
        window.record(200, 2000 + n, "GET", f"/r{n}")
    stats, *routes = request_stats.lines(window, _engine(), 60, request_stats.LoadWindow())
    assert f" slow_routes={request_stats.ROUTE_LINES + 5} " in stats
    assert len(routes) == request_stats.ROUTE_LINES


def test_a_method_a_client_made_up_neither_grows_the_window_nor_reaches_the_line() -> None:
    window = request_stats.Window()
    for n in range(50):
        window.record(405, 1500, f"M{n}", "/x")
    routes = request_stats.lines(window, _engine(), 60, request_stats.LoadWindow())[1:]
    assert len(routes) == 1 and " method=OTHER route=/x requests=50 " in routes[0]


def test_a_held_long_poll_counts_in_the_totals_but_not_for_its_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from starlette.requests import Request

    from maity_hub import deps

    scope: dict[str, Any] = {"type": "http", "query_string": b"wait=5", "state": {}}
    assert deps.wait_of(Request(scope)) == 5
    assert scope["state"]["held"] is True
    plain: dict[str, Any] = {"type": "http", "query_string": b"wait=0", "state": {}}
    assert deps.wait_of(Request(plain)) == 0
    assert "held" not in plain["state"]

    window = request_stats.Window()
    monkeypatch.setattr(request_stats, "WINDOW", window)
    middleware._access(
        {
            "method": "GET",
            "path": "/api/v1/x",
            "state": {"began": time.monotonic() - 2, "held": True},
        },
        200,
    )
    middleware._access(
        {"method": "GET", "path": "/api/v1/x", "state": {"began": time.monotonic() - 2}}, 200
    )
    taken = window.take()
    assert taken.requests == 2 and taken.slowest_ms >= 2000
    assert {key: times.requests for key, times in taken.routes.items()} == {("GET", "-"): 1}


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


def _load_fields(load: request_stats.LoadWindow) -> dict[str, str]:
    return dict(pair.split("=") for pair in load.fields().split())


def test_a_blocked_event_loop_shows_as_late_ticks() -> None:
    load = request_stats.LoadWindow()

    async def run() -> None:
        watch = asyncio.create_task(request_stats.watch_load(load, tick=0.01))
        await asyncio.sleep(0.05)
        time.sleep(0.3)  # what a blocking call in an `async def` does to every request
        await asyncio.sleep(0.05)
        watch.cancel()

    asyncio.run(run())
    fields = _load_fields(load)
    assert int(fields["loop_late_max_ms"]) >= 250
    assert int(fields["loop_late_avg_ms"]) > 0
    assert _load_fields(load)["loop_late_max_ms"] == "0"  # the window started again


def test_a_loop_stuck_right_now_shows_in_the_line_without_a_tick() -> None:
    load = request_stats.LoadWindow()
    load.record(0, 0, 0, 40, due=time.monotonic() - 2)
    assert int(_load_fields(load)["loop_late_max_ms"]) >= 2000
    load.record(0, 0, 0, 40, due=time.monotonic() - 2)
    load.stopped()
    assert _load_fields(load)["loop_late_max_ms"] == "0"  # no loop, nothing overdue


def test_the_threads_busy_and_waiting_are_those_of_the_loops_limiter() -> None:
    load = request_stats.LoadWindow()

    async def run() -> None:
        anyio.to_thread.current_default_thread_limiter().total_tokens = 2
        watch = asyncio.create_task(request_stats.watch_load(load, tick=0.01))
        async with anyio.create_task_group() as group:
            for _ in range(3):  # one more than there are threads: it has to wait
                group.start_soon(anyio.to_thread.run_sync, time.sleep, 0.1)
        watch.cancel()

    asyncio.run(run())
    fields = _load_fields(load)
    assert fields["threads_busy_max"] == "2"
    assert fields["threads_waiting_max"] == "1"
    assert fields["threads_limit"] == "2"
    assert float(fields["threads_busy_avg"]) > 0


def test_the_running_hub_watches_its_load(client: TestClient) -> None:
    """The fixture's client has run the lifespan, and with it the first tick."""
    assert _load_fields(request_stats.LOAD)["threads_limit"] == "40"


def test_the_tick_ends_before_the_hub_stops_reporting(
    settings: Settings, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelled by the lifespan itself, not left for the closing loop to clean up."""
    seen: list[float | None] = []
    stop = request_stats.Reporter.stop

    def noting(reporter: request_stats.Reporter) -> None:
        seen.append(request_stats.LOAD._due)
        stop(reporter)

    monkeypatch.setattr(request_stats.Reporter, "stop", noting)
    with TestClient(create_app(settings, migrated)):
        assert request_stats.LOAD._due is not None
    assert seen == [None]
