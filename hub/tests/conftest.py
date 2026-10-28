"""Fixtures. `MAITY_TEST_DATABASE_URL` points the suite at PostgreSQL or
MariaDB; without it every test gets its own SQLite file."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from maity_hub.app import create_app
from maity_hub.config import Settings, normalize_database_url
from maity_hub.db import downgrade, make_engine, migrate


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    url = os.environ.get("MAITY_TEST_DATABASE_URL")
    return normalize_database_url(url) if url else f"sqlite:///{tmp_path / 'hub.db'}"


@pytest.fixture(autouse=True)
def _no_background_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app's mail worker would send the outbox behind a test's back; tests drive
    `outbox.send_due` themselves."""
    from maity_hub.mail import outbox

    monkeypatch.setattr(outbox.Worker, "start", lambda self: None)


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    engine = make_engine(database_url)
    downgrade(engine)  # a shared server database may hold a previous run's schema
    yield engine
    downgrade(engine)
    engine.dispose()


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>dashboard</title>")
    return web


@pytest.fixture
def settings(database_url: str, web_dir: Path) -> Settings:
    return Settings.from_env(
        {
            "MAITY_DATABASE_URL": database_url,
            "MAITY_PUBLIC_URL": "https://hub.example",
            "MAITY_WEB_DIR": str(web_dir),
        }
    )


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    migrate(engine)
    with TestClient(create_app(settings, engine)) as client:
        yield client


@pytest.fixture(autouse=True)
def _no_forge_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test ever reaches the real forge, whatever token a test sets."""
    from maity_hub import forge

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise forge.ForgeUnavailableError("no network in tests")

    monkeypatch.setattr(forge._opener, "open", refuse)


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nor does any read under §11.1: resolution and connection both refuse unless a
    test puts its own fakes in their place."""
    from maity_hub import outbound

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise outbound.Refused("unavailable")

    monkeypatch.setattr(outbound, "resolver", refuse)
    monkeypatch.setattr(outbound, "connector", refuse)


@pytest.fixture(autouse=True)
def _no_background_ktw_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """A project view schedules a Keep the Why read in the background; in tests that
    would race the next test's cache. Tests of the scheduling replace this themselves."""
    from maity_hub import ktw

    monkeypatch.setattr(ktw, "_refresh_later", lambda *args: None)


@pytest.fixture(autouse=True)
def _fresh_process_state() -> Iterator[None]:
    """In-process state (limits, nonces, clock, the forge's repository visibility)
    must not leak between tests."""
    from maity_hub import availability, clock, forge, images, ktw, mentions
    from maity_hub.auth import caller
    from maity_hub.auth.credentials import NonceWindow
    from maity_hub.board import notes
    from maity_hub.routes import auth, badges, device_codes, joins, mail_settings, runners

    badges.BY_ADDRESS.reset()
    badges.NOT_SERVED.reset()
    auth.LOGIN_BY_ADDRESS.reset()
    joins.EXCHANGE_BY_ADDRESS.reset()
    runners.PAIR_BY_ADDRESS.reset()
    auth.LOGIN_BY_HANDLE.reset()
    mentions.PINGS.reset()
    mail_settings.test_limiter.reset()
    for limiter in (
        device_codes.CODES_BY_HUMAN,
        device_codes.REDEEM_BY_ADDRESS,
        device_codes.WRONG_CODES,
    ):
        limiter.reset()
    device_codes._holding.clear()
    device_codes._breaker["until"] = 0.0
    notes.POSTED.reset()
    # Tests run the availability sweep themselves; a worker's sweep in the middle of a
    # slow test would write to its database unasked.
    availability.INTERVAL = 24 * 3600.0
    from maity_hub.jourfixe import worker as jour_fixe_worker

    jour_fixe_worker.INTERVAL = 24 * 3600.0
    caller.NONCES = NonceWindow()
    forge._visible.clear()
    forge._budgets.clear()
    images.reset()
    ktw.CACHE.clear()
    yield
    clock.reset()
    from maity_hub import longpoll

    longpoll.stopping.clear()


@pytest.fixture
def migrated(engine: Engine) -> Engine:
    migrate(engine)
    return engine


ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client(settings: Settings, migrated: Engine) -> Iterator[ClientFactory]:
    """A client with settings overrides, a base URL (https for TLS) and a peer address."""
    opened: list[TestClient] = []

    def factory(
        base_url: str = "https://hub.example",
        peer: str = "203.0.113.7",
        **overrides: object,
    ) -> TestClient:
        app = create_app(replace(settings, **overrides), migrated)  # type: ignore[arg-type]
        client = TestClient(app, base_url=base_url, client=(peer, 50000))
        client.__enter__()
        opened.append(client)
        return client

    yield factory
    for client in opened:
        client.__exit__(None, None, None)
