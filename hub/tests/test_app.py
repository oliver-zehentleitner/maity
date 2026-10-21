from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from maity_hub import API_VERSION, __version__
from maity_hub.app import SchemaNotCurrentError, create_app
from maity_hub.config import ConfigError, Settings
from maity_hub.db import downgrade, head_revision, migrate


def test_health_reports_a_migrated_database(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["api"] == API_VERSION
    head = head_revision(client.app.state.engine)  # type: ignore[attr-defined]
    assert body["database"] == {"reachable": True, "revision": head, "head": head}


def test_health_turns_503_when_the_schema_falls_behind(client: TestClient, engine: Engine) -> None:
    downgrade(engine)
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.headers["Maity-Error"] == "schema_outdated"
    error = response.json()["error"]
    assert error["code"] == "schema_outdated"
    assert error["details"] == {"revision": None, "head": head_revision(engine)}


def test_help_is_markdown_and_names_the_api_version(client: TestClient) -> None:
    response = client.get("/api/v1/help")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.text.startswith("# Maity hub API")
    assert f"API version: {API_VERSION} · hub {__version__} · https://hub.example" in response.text


def test_help_keeps_literal_braces(client: TestClient) -> None:
    text = client.get("/api/v1/help").text
    assert "`/api/v1/projects/{project_id}`" in text
    assert '`{"title": "…"}`' in text


def test_no_swagger_ui_but_the_openapi_document(client: TestClient) -> None:
    assert client.get("/api/v1/docs").status_code == 404
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_dashboard_is_served_at_the_root(client: TestClient, web_dir: Path) -> None:
    (web_dir / "app.js").write_text("// dashboard")
    assert "<title>dashboard</title>" in client.get("/").text
    assert client.get("/app.js").text == "// dashboard"


@pytest.mark.parametrize(
    "path",
    [
        "/.env",
        "/.git/config",
        "/assets/.secret",
        "/api/v1/page.html",
        "/api/x",
        "/fixtures/me.json",
        "/tools/serve.py",
    ],
)
def test_dotfiles_and_the_api_prefix_are_never_served_as_files(
    client: TestClient, web_dir: Path, path: str
) -> None:
    target = web_dir / path.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("must not leak")
    response = client.get(path)
    assert response.status_code == 404
    assert "must not leak" not in response.text


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


@pytest.mark.parametrize("web_dir", ["absent", None])
def test_without_a_dashboard_the_api_still_serves(
    settings: Settings, engine: Engine, tmp_path: Path, web_dir: str | None
) -> None:
    migrate(engine)
    api_only = replace(
        settings,
        web_dir=tmp_path / web_dir if web_dir else None,
        web_dir_required=False,
    )
    with TestClient(create_app(api_only, engine)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/").status_code == 404
