"""docs/api.md §1.1 `Maity-Web-Version` and §16.11: every API answer carries the dashboard's
version, the app shell carries the same value, and it changes when, and only when, a file of
the dashboard changes (web/context/refresh.md 9d7aee6c)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from starlette.responses import Response

from maity_hub import shell
from tests import flow
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


def test_a_route_cannot_set_it(make_client: ClientFactory, dashboard: Path) -> None:
    # The middleware owns the header, as it owns `Maity-Server-Time`: a route's own value is
    # replaced on an API answer, and dropped outside the API.
    client = make_client()
    real = version_of(client)

    def sets_it() -> Response:
        return Response("x", headers={"Maity-Web-Version": "0" * 16})

    client.app.add_api_route("/api/v1/sets-web-version", sets_it)  # type: ignore[attr-defined]
    client.app.add_api_route("/sets-web-version", sets_it)  # type: ignore[attr-defined]
    answer = client.get("/api/v1/sets-web-version")
    assert answer.status_code == 200
    assert answer.headers.get_list("maity-web-version") == [real]
    assert "maity-web-version" not in client.get("/sets-web-version").headers


def test_a_shell_served_just_after_a_change_names_the_new_version(
    make_client: ClientFactory, dashboard: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With the value kept (the hub's own TTL), the shell still reads the files afresh: a page
    # loaded right after a deploy names the new dashboard and never shows the band.
    monkeypatch.setattr(shell, "WEB_VERSION_TTL", 60.0)
    client = make_client()
    old = version_of(client)
    (dashboard / "js" / "app.js").write_text("// deployed\n", encoding="utf-8")
    assert version_of(client) == old  # kept
    found = META.search(client.get("/").text)
    assert found is not None and found[1] != old
    assert version_of(client) == found[1]  # the shell's reading is kept for the API too


def test_the_value_is_kept_for_a_few_seconds(
    dashboard: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shell, "WEB_VERSION_TTL", 60.0)
    shell._WEB_VERSIONS.clear()
    assert shell.kept_web_version(dashboard) is shell.STALE
    first = shell.web_version(dashboard)
    (dashboard / "js" / "app.js").write_text("// three\n", encoding="utf-8")
    assert shell.kept_web_version(dashboard) == first  # no file is read while it is fresh
    assert shell.web_version(dashboard) != first


def test_a_restart_keeps_it(dashboard: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Taken from the files alone: a new process, here with every cache of the module empty,
    # computes the same value.
    shell._WEB_VERSIONS.clear()
    first = shell.web_version(dashboard)
    monkeypatch.setattr(shell, "_FORMS", {})
    monkeypatch.setattr(shell, "_WEB_VERSIONS", {})
    assert shell.web_version(dashboard) == first


JOIN = "https://join.example"


def test_on_the_join_host_only_the_exchange_carries_it(
    make_client: ClientFactory, migrated: Any, dashboard: Path
) -> None:
    """`POST /{token}` answers as `POST /api/v1/join/{token}` does, its `Maity-*` headers
    included (§1.1); the join host's redirects and `404`s are no API answers."""
    real = version_of(make_client())
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    made = owner.post(
        f"/projects/{owner.handle}/maity/joins",
        {"agent": {"handle": "agent-w", "display_name": "Agent W"}},
    ).json()
    token = made["join_url"].rsplit("/", 1)[1]
    host = make_client(base_url=JOIN, join_url=JOIN)
    exchange = host.post(f"/{token}", json={"code": made["code"], "client": "curl"})
    assert exchange.status_code == 201, exchange.text
    assert exchange.headers["maity-web-version"] == real
    refused = host.post("/" + "A" * 22, json={"code": "x", "client": "curl"})
    assert refused.status_code == 404 and refused.headers["maity-web-version"] == real
    for method, path in (("GET", "/api/v1/health"), ("POST", "/api/v1/join/" + "A" * 22)):
        other = host.request(method, path, follow_redirects=False)
        assert other.status_code in (302, 404), (method, path)
        assert "maity-web-version" not in other.headers, (method, path)
