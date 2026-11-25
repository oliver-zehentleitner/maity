"""The helpers `cli.py` shares between commands: the every-page read, the `more:` line, a card's
linked pull requests, JSON input and project paths (tsk-sgaz43qazfzx)."""

from __future__ import annotations

import io
from typing import Any

import pytest

from maity import cli


class _Client:
    def __init__(self, pages: list[Any]) -> None:
        self.pages = pages
        self.queries: list[list[tuple[str, str]]] = []

    def call(self, method: str, path: str, *, query: list[tuple[str, str]]) -> Any:
        assert method == "GET" and path == "/p"
        self.queries.append(query)
        return self.pages[len(self.queries) - 1]


class _Session:
    def __init__(self, pages: list[Any]) -> None:
        self.client = _Client(pages)


def test_all_pages_follows_the_cursor_keeps_objects_and_adds_the_limit_last() -> None:
    session = _Session([{"items": [{"a": 1}, 7], "next_cursor": "c2"}, {"items": [{"a": 2}]}])
    items = cli._all_pages(session, "/p", [("state", "open")], limit=200)  # type: ignore[arg-type]
    assert items == [{"a": 1}, {"a": 2}]
    assert session.client.queries == [
        [("state", "open"), ("limit", "200")],
        [("state", "open"), ("limit", "200"), ("cursor", "c2")],
    ]


def test_all_pages_without_a_limit_sends_none_and_a_bad_page_is_empty() -> None:
    session = _Session(["not an object"])
    assert cli._all_pages(session, "/p", []) == []  # type: ignore[arg-type]
    assert session.client.queries == [[]]


def test_all_pages_stops_on_a_cursor_that_comes_back() -> None:
    session = _Session([{"next_cursor": "x"}, {"next_cursor": "x"}])
    with pytest.raises(cli.CommandError, match="same page cursor twice"):
        cli._all_pages(session, "/p", [])  # type: ignore[arg-type]


def test_more_line_quotes_the_command_and_ends_with_the_cursor() -> None:
    assert cli._more_line(["maity", "ticker", "--area", "a b"], "c1") == (
        "more: maity ticker --area 'a b' --cursor c1"
    )


def test_linked_prs_keeps_pr_links_with_a_pull_request_url_only() -> None:
    card = {
        "links": [
            {"kind": "pr", "forge_url": "https://github.com/O/R/pull/7", "number": 7},
            {"kind": "pr", "forge_url": "https://github.com/o/r/pull/8"},
            {"kind": "pr", "forge_url": "https://github.com/o/r/issues/9"},
            {"kind": "issue", "forge_url": "https://github.com/o/r/pull/10"},
            "junk",
        ]
    }
    assert cli._linked_prs(card) == {("o/r", 7), ("o/r", 8)}
    assert cli._linked_prs({"links": None}) == set() and cli._linked_prs(None) == set()


def test_path_in_names_a_project_by_its_full_name() -> None:
    assert cli.Session.path_in("o/p", "tasks", "t 1") == "/projects/o/p/tasks/t%201"


def test_json_file_checks_the_object_and_the_one_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    review = tmp_path / "r.json"
    review.write_text("[1]", encoding="utf-8")
    with pytest.raises(cli.UsageError, match="--file: the body is one JSON object"):
        cli._json_file(str(review), "--file")
    assert cli._json_file(str(review), "--file", object_only=False) == [1]
    review.write_text("{oops", encoding="utf-8")
    with pytest.raises(cli.UsageError, match="--file: not JSON: Expecting property name"):
        cli._json_file(str(review), "--file")
    monkeypatch.setattr("sys.stdin", io.StringIO('{"a": 1}'))
    assert cli._json_file("-", "--file") == {"a": 1}
    with pytest.raises(cli.UsageError, match="cannot both come from stdin"):
        cli._json_file("-", "--review-file", stdin_used=True)
