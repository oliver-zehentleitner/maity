"""MAITY_ROUTE_LIMITS (§1.7) and the configurable read limits of the public pages and badges."""

from __future__ import annotations

import ipaddress
from typing import Any

import pytest

from maity_hub import public_pages, shared_counts
from maity_hub.app import create_app
from maity_hub.config import ConfigError, RouteLimit, Settings, parse_route_limits
from maity_hub.ratelimit import Limiter
from maity_hub.routes import badges

EVENTS = "/api/v1/projects/{owner}/{slug}/events"


def _env(settings: Settings, **env: str) -> Settings:
    return Settings.from_env(
        {
            "MAITY_DATABASE_URL": settings.database_url,
            "MAITY_PUBLIC_URL": "https://hub.example",
            "MAITY_WEB_DIR": str(settings.web_dir),
            **env,
        }
    )


def test_entries_are_read_one_per_line_or_semicolon() -> None:
    assert parse_route_limits(
        f"GET {EVENTS} = 120/60\n  POST /api/v1/me/export=1/600 ;; DELETE /api/v1/me = 3/86400\n"
    ) == (
        RouteLimit("GET", EVENTS, 120, 60),
        RouteLimit("POST", "/api/v1/me/export", 1, 600),
        RouteLimit("DELETE", "/api/v1/me", 3, 86400),
    )
    assert parse_route_limits("") == ()
    assert parse_route_limits(" ;\n ") == ()


@pytest.mark.parametrize(
    "value",
    [
        "GET /api/v1/health",  # no limit
        "GET /api/v1/health = 10",  # no window
        "get /api/v1/health = 10/60",  # the method in capitals
        "HEAD /api/v1/health = 10/60",  # not one of the methods a limit names
        "GET api/v1/health = 10/60",  # the route starts with /
        "GET /api/v1/health = 0/60",
        "GET /api/v1/health = 100001/60",
        "GET /api/v1/health = 10/0",
        "GET /api/v1/health = 10/86401",
        "GET /api/v1/health = 10/60; GET /api/v1/health = 20/60",  # named twice
    ],
)
def test_a_malformed_entry_stops_the_hub(value: str) -> None:
    with pytest.raises(ConfigError, match="MAITY_ROUTE_LIMITS"):
        parse_route_limits(value)


def test_the_same_route_for_two_methods_is_two_limits() -> None:
    assert len(parse_route_limits(f"GET {EVENTS} = 1/60; POST {EVENTS} = 1/60")) == 2


@pytest.mark.parametrize(
    "entry",
    [
        "GET /api/v1/projects/{owner}/{slug}/event = 10/60",  # a typo
        "GET /api/v1/projects/maintainer/maity/events = 10/60",  # a path, not the route
        f"DELETE {EVENTS} = 10/60",  # the route, but not with that method
    ],
)
def test_a_route_the_hub_does_not_declare_stops_the_app(settings: Settings, entry: str) -> None:
    configured = _env(settings, MAITY_ROUTE_LIMITS=entry)
    with pytest.raises(ConfigError, match="has no route"):
        create_app(configured)


def test_a_limited_route_is_refused_past_its_limit_before_the_caller_is_known(
    make_client: Any,
) -> None:
    client = make_client(route_limits=(RouteLimit("GET", EVENTS, 2, 60),))
    path = "/api/v1/projects/maintainer/maity/events"
    # No credential: the route itself answers 401, the limit counts it all the same.
    assert [client.get(path).status_code for _ in range(2)] == [401, 401]
    refused = client.get(path)
    assert refused.status_code == 429
    assert refused.headers["Maity-Error"] == "rate_limited"
    assert 1 <= int(refused.headers["Retry-After"]) <= 60
    assert refused.json()["error"]["code"] == "rate_limited"
    # Another project's events are the same route, so the same count.
    assert client.get("/api/v1/projects/other/thing/events").status_code == 429
    # Another method on the path and another route are not counted.
    assert client.post(path).status_code != 429
    assert client.get("/api/v1/health").status_code == 200


def test_the_count_is_per_client_address(make_client: Any) -> None:
    client = make_client(
        base_url="http://hub.internal",
        peer="10.0.0.5",
        trusted_proxies=(ipaddress.ip_network("10.0.0.0/8"),),
        route_limits=(RouteLimit("GET", "/api/v1/health", 1, 60),),
    )

    def health(address: str) -> int:
        headers = {"X-Forwarded-For": address, "X-Forwarded-Proto": "https"}
        return int(client.get("/api/v1/health", headers=headers).status_code)

    assert [health("198.51.100.1"), health("198.51.100.1")] == [200, 429]
    assert health("198.51.100.2") == 200


def test_without_limits_nothing_is_counted(make_client: Any) -> None:
    client = make_client()
    assert not client.app.state.route_limits
    assert {client.get("/api/v1/health").status_code for _ in range(30)} == {200}


def test_a_route_limit_never_writes_to_the_shared_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shared_counts, "active", lambda: True)

    def no_database(*args: object, **kwargs: object) -> None:
        raise AssertionError("a local limit reached the shared counts")

    for name in ("add", "log_take", "log_read", "read", "subtract", "clear"):
        monkeypatch.setattr(shared_counts, name, no_database)
    limiter = Limiter(1, 60, name="t", local=True)
    assert limiter.hit("a") == 0
    assert limiter.hit("a") > 0
    assert limiter.blocked("a") > 0
    limiter.reset()
    assert limiter.hit("a") == 0


def test_the_read_limits_of_public_pages_and_badges_come_from_the_settings(
    settings: Settings,
) -> None:
    create_app(_env(settings, MAITY_PUBLIC_PAGE_LIMIT="600/60", MAITY_BADGE_LIMIT="5/10"))
    assert (public_pages.BY_ADDRESS.limit, public_pages.BY_ADDRESS.window) == (600, 60)
    assert (badges.BY_ADDRESS.limit, badges.BY_ADDRESS.window) == (5, 10)
    create_app(settings)
    assert (public_pages.BY_ADDRESS.limit, public_pages.BY_ADDRESS.window) == (60, 60)
    assert (badges.BY_ADDRESS.limit, badges.BY_ADDRESS.window) == (60, 60)


@pytest.mark.parametrize("name", ["MAITY_PUBLIC_PAGE_LIMIT", "MAITY_BADGE_LIMIT"])
@pytest.mark.parametrize("value", ["60", "60/", "0/60", "60/0", "a/60", "60 / 60"])
def test_a_malformed_read_limit_stops_the_hub(settings: Settings, name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        _env(settings, **{name: value})


def test_configure_forgets_what_was_counted() -> None:
    limiter = Limiter(1, 60, name="t")
    assert limiter.hit("a") == 0 and limiter.hit("a") > 0
    limiter.configure(2, 30)
    assert (limiter.limit, limiter.window) == (2, 30)
    assert [limiter.hit("a"), limiter.hit("a")] == [0, 0]
    assert limiter.hit("a") > 0


def test_a_request_counts_for_the_route_that_serves_it_not_a_template_it_also_fits(
    make_client: Any,
) -> None:
    # `GET /api/v1/runners/enrollments` comes first and fits `/api/v1/runners/{runner_id}` too.
    client = make_client(route_limits=(RouteLimit("GET", "/api/v1/runners/{runner_id}", 1, 60),))
    assert {client.get("/api/v1/runners/enrollments").status_code for _ in range(3)} != {429}
    assert client.get("/api/v1/runners/rnr-1").status_code != 429
    assert client.get("/api/v1/runners/rnr-2").status_code == 429
