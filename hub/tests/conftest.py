"""Fixtures. `MAITY_TEST_DATABASE_URL` points the suite at PostgreSQL or
MariaDB; without it every test gets its own SQLite file."""

from __future__ import annotations

import os
from collections.abc import Iterator
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
