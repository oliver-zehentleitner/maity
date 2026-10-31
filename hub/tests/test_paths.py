"""The reserved first segments and the hub's own paths against the contract (docs/api.md
§16.11): the list in the code is the list in the document."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import Engine

from maity_hub import paths

API_MD = Path(__file__).resolve().parents[2] / "docs" / "api.md"


def _section() -> str:
    text = API_MD.read_text(encoding="utf-8")
    start = text.index("### 16.11 Paths and the app shell")
    return text[start : text.index("\n## 17.", start)]


def _words(after: str, until: str) -> set[str]:
    section = _section()
    block = section[section.index(after) :]
    block = block[: block.index(until)]
    return set(re.findall(r"`([a-z][a-z-]*)`", block))


def test_the_reserved_first_segments_are_the_contracts() -> None:
    listed = _words("The list:", "`components`, `health` and `imprint` name no route")
    assert frozenset(listed) == paths.RESERVED_FIRST


def test_every_project_view_the_contract_names_is_reserved_as_a_slug() -> None:
    section = _section()
    row = next(
        line for line in section.splitlines() if line.startswith("| `/<owner>/<slug>/<view>")
    )
    views = {
        word.split("/")[0]
        for word in re.findall(r"`([a-z][a-z/-]*?)(?:<[^`]*)?`", row.split("|")[2])
        if word != "message"
    }
    assert views - {"jour-fixe"} <= paths.PROJECT_VIEWS, views - paths.PROJECT_VIEWS


def test_the_hub_paths_are_the_contracts() -> None:
    section = _section()
    table = section[section.index("**Hub paths.**") : section.index("The join host is unchanged")]
    first = {
        re.match(r"/([a-z.-]+)", cell).group(1)  # type: ignore[union-attr]
        for cell in re.findall(r"\| `(/[^`|]+)`", table)
    }
    first = {segment.split(".")[0] for segment in first}
    assert {"api", "assets", "join", "r", "mail", "badge"} <= first
    assert {"api", "assets", "join", "r", "mail", "badge"} <= paths.HUB_FIRST
    assert paths.HUB_FIRST - first <= {"impressum", "privacy", "terms"}


@pytest.mark.parametrize(
    ("path", "hub"),
    [
        ("/api/v1/health", True),
        ("/assets/js/app.js", True),
        ("/join/abc", True),
        ("/r/abc", True),
        ("/mail/verify/abc", True),
        ("/badge/a/b.svg", True),
        ("/robots.txt", True),
        ("/sitemap.xml", True),
        ("/sitemap-2.xml", True),
        ("/impressum", True),
        ("/privacy/2026-01-01T00:00:00Z", True),
        ("/terms", True),
        ("/", False),
        ("/login", False),
        ("/maintainer/maity/board", False),
        ("/some-handle", False),
        ("/apiary", False),
        ("/sitemap.xml.bak", False),
    ],
)
def test_which_paths_the_hub_answers_itself(path: str, hub: bool) -> None:
    assert paths.is_hub_path(path) is hub


def test_a_word_that_is_reserved_and_already_held_is_named_and_stops_the_migration(
    migrated: Engine,
    database_url: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maity_hub import cli, namespace
    from tests import factory

    with migrated.connect() as conn:
        assert namespace.reserved_holders(conn) == []
    factory.human(migrated, "login")
    factory.project(migrated, "board")
    with migrated.connect() as conn:
        assert namespace.reserved_holders(conn) == ["handle 'login'", "slug 'board'"]
    monkeypatch.setenv("MAITY_DATABASE_URL", database_url)
    assert cli.main(["migrate"]) != 0
    assert "handle 'login', slug 'board'" in capsys.readouterr().err
