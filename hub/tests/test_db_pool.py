"""The server-database pool and the single retry of a name that did not resolve."""

from __future__ import annotations

import time
from typing import Any

import pytest

from maity_hub import db
from maity_hub.config import ConfigError, Settings
from maity_hub.errors import connection_cause

DNS = OSError("failed to resolve host 'db': Temporary failure in name resolution")


@pytest.fixture(autouse=True)
def no_pause(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    pauses: list[float] = []
    monkeypatch.setattr(time, "sleep", pauses.append)
    return pauses


def flaky(*failures: Exception) -> tuple[Any, list[int]]:
    calls: list[int] = []
    queue = list(failures)

    def connect(*_args: Any, **_kwargs: Any) -> str:
        calls.append(1)
        if queue:
            raise queue.pop(0)
        return "connection"

    return connect, calls


def test_a_name_that_did_not_resolve_is_tried_once_more(no_pause: list[float]) -> None:
    connect, calls = flaky(DNS)
    assert db.connect_once_more_on_dns(connect, (), {}) == "connection"
    assert len(calls) == 2 and len(no_pause) == 1
    assert db.RESOLVE_PAUSE_SECONDS <= no_pause[0] <= 2 * db.RESOLVE_PAUSE_SECONDS


def test_a_second_dns_failure_goes_on(no_pause: list[float]) -> None:
    connect, calls = flaky(DNS, DNS)
    with pytest.raises(OSError):
        db.connect_once_more_on_dns(connect, (), {})
    assert len(calls) == 2


def test_any_other_failure_is_not_retried(no_pause: list[float]) -> None:
    connect, calls = flaky(OSError("connection refused"))
    with pytest.raises(OSError):
        db.connect_once_more_on_dns(connect, (), {})
    assert len(calls) == 1 and no_pause == []


def test_arguments_reach_the_driver() -> None:
    seen: list[tuple[Any, Any]] = []
    db.connect_once_more_on_dns(lambda *a, **k: seen.append((a, k)), (1,), {"x": 2})
    assert seen == [((1,), {"x": 2})]


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ('could not translate host name "db" to address', "dns"),
        ("nodename nor servname provided", "dns"),
        ("getaddrinfo failed", "dns"),
        ("[Errno -3] Temporary failure in name resolution", "dns"),
        ("connection refused", "refused"),
        ("something new", "unclassified"),
    ],
)
def test_connection_cause_names_the_category(text: str, category: str) -> None:
    assert connection_cause(OSError(text)) == category


def test_a_server_engine_pools_and_reuses_the_latest_connection() -> None:
    engine = db.make_engine("postgresql+psycopg://u:p@localhost/h", 7, 3, 60)
    pool: Any = engine.pool
    assert (pool.size(), pool._max_overflow, pool._recycle, pool._pool.use_lifo) == (7, 3, 60, True)
    assert len(engine.dialect.dispatch.do_connect) == 1


def test_recycle_zero_means_never() -> None:
    engine = db.make_engine("postgresql+psycopg://u:p@localhost/h", pool_recycle=0)
    pool: Any = engine.pool
    assert pool._recycle == -1


def test_sqlite_has_no_connect_hook(tmp_path: Any) -> None:
    engine = db.make_engine(f"sqlite:///{tmp_path}/h.db")
    assert not engine.dialect.dispatch.do_connect


def test_settings_read_the_pool_from_the_environment() -> None:
    defaults = Settings.from_env({"MAITY_DATABASE_URL": "sqlite:///x.db"})
    assert (defaults.db_pool_size, defaults.db_max_overflow, defaults.db_pool_recycle) == (
        16,
        16,
        1800,
    )
    custom = Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite:///x.db",
            "MAITY_DB_POOL_RECYCLE": "0",
            "MAITY_DB_POOL_SIZE": "3",
        }
    )
    assert (custom.db_pool_size, custom.db_pool_recycle) == (3, 0)
    with pytest.raises(ConfigError):
        Settings.from_env(
            {"MAITY_DATABASE_URL": "sqlite:///x.db", "MAITY_DB_POOL_RECYCLE": "90000"}
        )
