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


@pytest.mark.wheel
def test_help_is_markdown_and_names_the_api_version(client: TestClient) -> None:
    response = client.get("/api/v1/help")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.text.startswith("# Maity hub API")
    assert f"API version: {API_VERSION} · hub {__version__} · https://hub.example" in response.text


@pytest.mark.wheel
def test_help_keeps_literal_braces(client: TestClient) -> None:
    text = client.get("/api/v1/help").text
    assert "`/api/v1/projects/{project_id}`" in text
    assert '`{"title": "…"}`' in text


def test_no_swagger_ui_but_the_openapi_document(client: TestClient) -> None:
    assert client.get("/api/v1/docs").status_code == 404
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_the_shell_is_served_at_the_root_and_at_every_dashboard_path(
    client: TestClient, web_dir: Path
) -> None:
    for path in ("/", "/login", "/maintainer/maity/board", "/a/b/c/d", "/no-such-page"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "<title>dashboard</title>" in response.text
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-security-policy"] == "default-src 'self'"
        assert "set-cookie" not in response.headers
    # The root's `noindex` is the middleware's, while the landing page is off (§16.7); every
    # other path of the shell carries its own.
    assert client.get("/maintainer/maity/board").headers["x-robots-tag"] == "noindex"
    assert client.head("/login").status_code == 200


def test_built_files_are_served_under_assets(client: TestClient, web_dir: Path) -> None:
    (web_dir / "js").mkdir()
    (web_dir / "js" / "app.js").write_text("// dashboard")
    (web_dir / "brand").mkdir()
    (web_dir / "brand" / "logo.svg").write_text("<svg/>")
    assert client.get("/assets/js/app.js").text == "// dashboard"
    assert client.get("/assets/brand/logo.svg").status_code == 200
    # The old place of a file is not a file any more: it is a dashboard path, the shell.
    old = client.get("/js/app.js")
    assert old.status_code == 200 and "<title>dashboard</title>" in old.text


@pytest.mark.parametrize(
    "path",
    [
        "/assets/index.html",
        "/assets/.env",
        "/assets/js/.secret",
        "/assets/fixtures/me.json",
        "/assets/tools/serve.py",
        "/assets/README.md",
        "/assets/",
        "/assets",
        "/api/v1/page.html",
        "/api/x",
    ],
)
def test_nothing_but_the_built_files_is_served_as_a_file(
    client: TestClient, web_dir: Path, path: str
) -> None:
    for name in (".env", "js/.secret", "fixtures/me.json", "tools/serve.py", "README.md"):
        target = web_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("must not leak")
    response = client.get(path)
    assert response.status_code == 404
    assert "must not leak" not in response.text and "<title>dashboard</title>" not in response.text


def test_a_hub_path_that_names_nothing_is_not_the_shell(client: TestClient) -> None:
    for path in ("/mail/nothing/here", "/badge/x", "/join", "/r/token", "/impressum/1"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert "<title>dashboard</title>" not in response.text, path


def test_any_other_method_on_a_shell_path_is_not_found(client: TestClient) -> None:
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/maintainer/maity/board")
        assert response.status_code == 404, method
        assert response.json()["error"]["code"] == "not_found"


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


@pytest.mark.wheel
def test_the_default_dashboard_is_served(database_url: str, migrated: Engine) -> None:
    """Whatever this runs from, a checkout or the installed wheel (CI's hub-wheel job), the
    hub serves a dashboard without MAITY_WEB_DIR."""
    settings = Settings.from_env({"MAITY_DATABASE_URL": database_url})
    with TestClient(create_app(settings, migrated)) as client:
        root = client.get("/")
        assert root.status_code == 200 and "<title>" in root.text
        assert client.get("/assets/js/app.js").status_code == 200


def test_driver_reason_names_a_category_and_never_the_driver_text() -> None:
    from sqlalchemy.exc import OperationalError

    from maity_hub.errors import driver_reason

    class ConnectionTimeout(Exception):
        pass

    cases = {
        "dns": "failed to resolve host 'db': [Errno -2] Name or service not known",
        "timeout": 'connection to server at "10.0.0.5", port 5432 failed: timeout expired',
        "refused": "connection failed: Connection refused",
        "closed": "consuming input failed: server closed the connection unexpectedly",
        "no_slots": "FATAL: remaining connection slots are reserved",
        "unclassified": "something no list knows",
    }
    for category, text in cases.items():
        reason = driver_reason(OperationalError("SELECT 1", {}, ConnectionTimeout(text)))
        assert reason.endswith(f" {category}"), (category, reason)
        assert reason.startswith("tests.test_app.") or ".ConnectionTimeout " in reason
    assert driver_reason(Exception("no orig")) == ""


def test_driver_reason_never_carries_the_driver_text() -> None:
    """Every form in which a driver could quote a credential, however it is escaped or encoded."""
    from sqlalchemy.exc import OperationalError

    from maity_hub.errors import driver_reason

    texts = [
        "host=db password='prefix\\'LEAK_MARKER'",
        "password=prefix\\ LEAK_MARKER",
        "postgresql://user:prefix'LEAK_MARKER@db/name",
        "postgresql%3A%2F%2Fuser%3ALEAK_MARKER%40db%2Fname",
        "{'password': 'LEAK_MARKER'}",
        "failed to resolve host 'LEAK_MARKER' user=LEAK_MARKER",
        "timeout expired LEAK_MARKER\n" + "x" * 5000,
    ]
    for text in texts:
        reason = driver_reason(OperationalError("SELECT 1", {}, Exception(text)))
        assert "LEAK_MARKER" not in reason and "\n" not in reason and len(reason) < 120, reason


def test_the_database_error_handler_logs_the_cause_not_the_secret(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    from sqlalchemy.exc import OperationalError

    def broken() -> None:
        raise OperationalError(
            "SELECT 1", {}, Exception("failed to resolve host 'db' postgresql://u:pw-in-dsn@db/x")
        )

    client.app.add_api_route("/api/v1/_broken", broken)  # type: ignore[attr-defined]
    with caplog.at_level("ERROR", logger="maity_hub.errors"):
        response = client.get("/api/v1/_broken")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert logged.endswith(" dns") and "pw-in-dsn" not in logged
    assert "pw-in-dsn" not in response.text
