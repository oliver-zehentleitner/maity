"""docs/api.md §1.1 `Maity-Web-Version` and §16.11: every API answer carries the dashboard's
version, the app shell carries the same value, and it changes when, and only when, a file of
the dashboard changes (web/context/refresh.md d499ba75)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from maity_hub import shell
from tests.conftest import ClientFactory

VERSION = re.compile(r"[0-9a-f]{16}")
META = re.compile(r'<meta name="maity-web-version" content="([0-9a-f]{16})">')


@pytest.fixture(autouse=True)
def fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    # Read the files again on every answer, so a change shows at once.
    monkeypatch.setattr(shell, "WEB_VERSION_TTL", 0.0)


@pytest.fixture
def dashboard(web_dir: Path) -> Path:
    (web_dir / "js").mkdir()
    (web_dir / "js" / "app.js").write_text("// one\n", encoding="utf-8")
    return web_dir


def version_of(client: Any, path: str = "/api/v1/health") -> str:
    value = client.get(path).headers.get("maity-web-version")
    assert value is not None and VERSION.fullmatch(value), value
    return str(value)


def test_an_api_answer_carries_the_version_the_shell_carries(
    make_client: ClientFactory, dashboard: Path
) -> None:
    client = make_client()
    header = version_of(client)
    page = client.get("/")
    found = META.search(page.text)
    assert found is not None and found[1] == header
    assert "maity-web-version" not in page.headers  # the shell carries it in its head
    # An error answers it too: every answer under /api/v1/.
    assert version_of(client, "/api/v1/no-such-route") == header


def test_it_changes_with_a_file_of_the_dashboard_and_with_index_html(
    make_client: ClientFactory, dashboard: Path
) -> None:
    client = make_client()
    first = version_of(client)
    (dashboard / "js" / "app.js").write_text("// two\n", encoding="utf-8")
    second = version_of(client)
    assert second != first
    shell_file = dashboard / "index.html"
    shell_file.write_text(shell_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert version_of(client) not in (first, second)


def test_a_file_the_dashboard_does_not_serve_leaves_it(
    make_client: ClientFactory, dashboard: Path
) -> None:
    client = make_client()
    first = version_of(client)
    (dashboard / "fixtures").mkdir()
    (dashboard / "fixtures" / "me.json").write_text("{}", encoding="utf-8")
    (dashboard / "README.md").write_text("notes", encoding="utf-8")
    assert version_of(client) == first


def test_a_hub_without_a_dashboard_sends_none(make_client: ClientFactory, tmp_path: Path) -> None:
    empty = tmp_path / "no-dashboard"
    empty.mkdir()
    for web_dir in (None, empty):
        answer = make_client(web_dir=web_dir, web_dir_required=False).get("/api/v1/health")
        assert answer.status_code == 200
        assert "maity-web-version" not in answer.headers


def test_a_route_cannot_set_it(dashboard: Path) -> None:
    # The middleware owns the header, as it owns `Maity-Server-Time`.
    from maity_hub import middleware

    assert b"maity-web-version" in middleware._SET


def test_the_value_is_kept_for_a_few_seconds(
    dashboard: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shell, "WEB_VERSION_TTL", 60.0)
    shell._WEB_VERSIONS.clear()
    first = shell.web_version(dashboard)
    (dashboard / "js" / "app.js").write_text("// three\n", encoding="utf-8")
    assert shell.web_version(dashboard) == first
    shell._WEB_VERSIONS.clear()
    assert shell.web_version(dashboard) != first


def test_a_restart_keeps_it(dashboard: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Taken from the files alone: a new process, here with every cache of the module empty,
    # computes the same value.
    shell._WEB_VERSIONS.clear()
    first = shell.web_version(dashboard)
    monkeypatch.setattr(shell, "_FORMS", {})
    monkeypatch.setattr(shell, "_WEB_VERSIONS", {})
    assert shell.web_version(dashboard) == first
