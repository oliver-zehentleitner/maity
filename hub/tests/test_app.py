from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from maity_hub import API_VERSION, __version__
from maity_hub.app import SchemaNotCurrentError, create_app
from maity_hub.config import ConfigError, Settings


def test_health_reports_a_migrated_database(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["api"] == API_VERSION
    assert body["database"] == {"reachable": True, "revision": "0001", "head": "0001"}


def test_help_is_markdown_and_names_the_api_version(client: TestClient) -> None:
    response = client.get("/api/v1/help")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.text.startswith("# Maity hub API")
    assert f"API version: {API_VERSION}" in response.text
    assert "https://hub.example" in response.text


def test_dashboard_is_served_at_the_root(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "<title>dashboard</title>" in response.text


def test_api_routes_take_precedence_over_the_dashboard(client: TestClient, web_dir: Path) -> None:
    (web_dir / "api").mkdir()
    assert client.get("/api/v1/health").headers["content-type"] == "application/json"


def test_refuses_to_start_on_an_unmigrated_database(settings: Settings, engine: Engine) -> None:
    with (
        pytest.raises(SchemaNotCurrentError, match="maity-hub migrate"),
        TestClient(create_app(settings, engine)),
    ):
        pass


def test_a_missing_explicit_web_dir_fails(settings: Settings, engine: Engine) -> None:
    broken = Settings.from_env(
        {"MAITY_DATABASE_URL": settings.database_url, "MAITY_WEB_DIR": "/nonexistent/web"}
    )
    with pytest.raises(ConfigError, match="MAITY_WEB_DIR"):
        create_app(broken, engine)


def test_without_a_dashboard_the_api_still_serves(
    settings: Settings, engine: Engine, tmp_path: Path
) -> None:
    from dataclasses import replace

    from maity_hub.db import migrate

    migrate(engine)
    api_only = replace(settings, web_dir=tmp_path / "absent", web_dir_required=False)
    with TestClient(create_app(api_only, engine)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/").status_code == 404
