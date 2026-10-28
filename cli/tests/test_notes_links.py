"""`maity note` and `maity link` (§6.16, §6.13) against the fake hub."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli

BASE = "/api/v1/projects/oliver/maity/tasks/tsk-0004"
NOTE: dict[str, Any] = {"id": "nte-0031", "task_id": "tsk-0004", "body": "the CLI needs it too",
        "author": {"member_id": "agt-c", "handle": "agent-c", "kind": "agent"},
        "mentions": [], "state": "open", "resolution": None,
        "created_at": "2026-10-22T14:30:00Z"}  # fmt: skip


def test_note_add_posts_the_body(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", f"{BASE}/notes")] = lambda s: (201, NOTE)
    assert cli.main(["note", "add", "tsk-0004", "the CLI needs it too"]) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"body": "the CLI needs it too"}
    assert "note nte-0031 on tsk-0004" in capsys.readouterr().out


def test_note_list_asks_for_open_notes_by_default_and_shows_them_cleaned(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile = {**NOTE, "body": "line one\n\x1b]52;c;aGk=\x07line two"}
    fake.routes[("GET", f"{BASE}/notes")] = lambda s: (200, {"items": [hostile]})
    assert cli.main(["note", "list", "tsk-0004"]) == cli.EXIT_OK
    assert fake.signed()[-1].query == "limit=200&state=open"
    out = capsys.readouterr().out
    assert "nte-0031  open  agent-c" in out and "    line one" in out
    assert "\x1b" not in out  # a note's text is shown, never executed by the terminal


def test_note_list_all(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", f"{BASE}/notes")] = lambda s: (200, {"items": []})
    assert cli.main(["note", "list", "tsk-0004", "--all"]) == cli.EXIT_OK
    assert "state=all" in fake.signed()[-1].query


def test_note_list_follows_every_page(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    second = {**NOTE, "id": "nte-0032"}

    def page(seen: fakehub.Seen) -> tuple[Any, ...]:
        if "cursor=c2" in seen.query:
            return 200, {"items": [second], "next_cursor": None}
        return 200, {"items": [NOTE], "next_cursor": "c2"}

    fake.routes[("GET", f"{BASE}/notes")] = page
    assert cli.main(["note", "list", "tsk-0004", "--json"]) == cli.EXIT_OK
    assert [n["id"] for n in json.loads(capsys.readouterr().out)] == ["nte-0031", "nte-0032"]
    assert "limit=200" in fake.signed()[-1].query


def test_state_and_all_cannot_be_given_together(joined: Path) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(["note", "list", "tsk-0004", "--all", "--state", "dismissed"])
    assert exited.value.code == cli.EXIT_USAGE


@pytest.mark.parametrize("flag, state", [("--incorporated", "incorporated"),
                                          ("--dismissed", "dismissed")])  # fmt: skip
def test_note_resolve(joined: Path, fake: fakehub.FakeHub, flag: str, state: str) -> None:
    fake.routes[("POST", f"{BASE}/notes/nte-0031/resolve")] = lambda s: (200, NOTE)
    args = ["note", "resolve", "tsk-0004", "nte-0031", flag, "--reason", "in the body now"]
    assert cli.main(args) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"state": state, "reason": "in the body now"}


def test_note_resolve_needs_a_state(joined: Path) -> None:
    with pytest.raises(SystemExit) as exited:  # argparse: one of the two is required
        cli.main(["note", "resolve", "tsk-0004", "nte-0031"])
    assert exited.value.code == cli.EXIT_USAGE


@pytest.mark.parametrize(
    "url, kind",
    [
        ("https://github.com/o/r/issues/41", "issue"),
        ("https://github.com/o/r/pull/7/", "pr"),
        ("https://gitlab.example/group/sub/proj/-/issues/3", "url"),  # GitHub only in V1
        ("https://gitlab.example/group/proj/-/merge_requests/9", "url"),
        ("https://github.com/o/r/issues/41?x=1", "url"),  # not the forge's shape: plain
        ("https://github.com/o/r/issues/\u0664\u0661", "url"),  # ASCII digits only
        ("https://github.com/o/r/issues/41\n", "url"),
        ("https://keepthewhy.com/linting/", "url"),
    ],
)
def test_link_kind_follows_the_forge_shapes(url: str, kind: str) -> None:
    assert cli.link_kind(url) == kind


def test_link_add_sends_a_forge_link_as_forge_url_only(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", f"{BASE}/links")] = lambda s: (201, {"id": "lnk-0007"})
    url = "https://github.com/oliver-zehentleitner/maity/issues/41"
    assert cli.main(["link", "add", "tsk-0004", url]) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"kind": "issue", "forge_url": url}


def test_link_add_plain_with_a_label(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", f"{BASE}/links")] = lambda s: (201, {"id": "lnk-0008"})
    url = "https://github.com/o/r/issues/41"
    assert cli.main(["link", "add", "tsk-0004", url, "--plain", "--label", "upstream"]) == 0
    assert fake.signed()[-1].json() == {"kind": "url", "url": url, "label": "upstream"}


def test_a_label_on_a_forge_link_is_a_usage_error(joined: Path, fake: fakehub.FakeHub) -> None:
    before = len(fake.seen)
    args = ["link", "add", "tsk-0004", "https://github.com/o/r/pull/7", "--label", "x"]
    assert cli.main(args) == cli.EXIT_USAGE and len(fake.seen) == before


def test_link_list_shows_what_the_hub_observed(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    links = [
        {"id": "lnk-0007", "kind": "issue", "forge_url": "https://github.com/o/r/issues/41",
         "observed": {"found": True, "title": "Board: links", "state": "open"}},
        {"id": "lnk-0009", "kind": "pr", "forge_url": "https://github.com/o/r/pull/7",
         "observed": None},
        {"id": "lnk-0008", "kind": "url", "url": "https://keepthewhy.com/", "label": "docs"},
        {"id": "lnk-0010", "kind": "issue", "forge_url": "https://github.com/o/r/issues/7",
         "observed": {"found": False, "reason": "kind_mismatch"}},
    ]  # fmt: skip
    fake.routes[("GET", BASE)] = lambda s: (200, {"id": "tsk-0004", "links": links})
    assert cli.main(["link", "list", "tsk-0004"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "lnk-0007  issue  https://github.com/o/r/issues/41  (open: Board: links)" in out
    assert "lnk-0009  pr  https://github.com/o/r/pull/7  (not observed)" in out
    assert "lnk-0008  url  docs  https://keepthewhy.com/" in out
    assert "lnk-0010  issue  https://github.com/o/r/issues/7  (is a pull request:" in out
    assert cli.main(["link", "list", "tsk-0004", "--json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == links


def test_link_remove(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("DELETE", f"{BASE}/links/lnk-0007")] = lambda s: (200, {"id": "lnk-0007"})
    assert cli.main(["link", "remove", "tsk-0004", "lnk-0007"]) == cli.EXIT_OK
    assert fake.signed()[-1].method == "DELETE"


def test_a_cursor_that_comes_back_stops_the_paging(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = []

    def page(seen: fakehub.Seen) -> tuple[Any, ...]:
        calls.append(seen)
        return 200, {"items": [NOTE], "next_cursor": "same"}

    fake.routes[("GET", f"{BASE}/notes")] = page
    assert cli.main(["note", "list", "tsk-0004"]) not in (cli.EXIT_OK,)
    assert len(calls) == 2  # the first page, then the cursor once; never a third round
    assert "same page cursor twice" in capsys.readouterr().err


def test_release_list_stops_on_a_cursor_that_comes_back(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = []

    def page(seen: fakehub.Seen) -> tuple[Any, ...]:
        calls.append(seen)
        return 200, {"items": [], "next_cursor": "loop"}

    fake.routes[("GET", "/api/v1/projects/oliver/maity/tasks")] = page
    assert cli.main(["release", "list"]) != cli.EXIT_OK
    assert len(calls) == 2 and "same page cursor twice" in capsys.readouterr().err


def test_link_list_refuses_an_answer_without_links(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", BASE)] = lambda s: (200, {"id": "tsk-0004", "title": "x"})
    assert cli.main(["link", "list", "tsk-0004"]) == cli.EXIT_ERROR
    out = capsys.readouterr()
    assert "no links" not in out.out  # absent is not an empty list
    assert "this hub does not have card links yet" in out.err


NOT_FOUND = (404, {"error": {"code": "not_found", "message": "no such card", "details": {}}})


@pytest.mark.parametrize(
    ("openapi", "said"),
    [
        ({"paths": {}}, "this hub does not have card notes yet"),
        ({"paths": {"/api/v1/projects/{owner}/{slug}/tasks/{task_id}/notes": {"post": {}}}},
         "not_found: no such card"),
        ("not json", "not_found: no such card"),
    ],
)  # fmt: skip
def test_a_404_names_a_feature_the_hub_lacks(
    openapi: Any, said: str, joined: Path, fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    fake.openapi = openapi
    fake.routes[("POST", f"{BASE}/notes")] = lambda s: NOT_FOUND
    assert cli.main(["note", "add", "tsk-0004", "x"]) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert said in err
    if "does not have" in said:
        assert "POST /projects/oliver/maity/tasks/tsk-0004/notes" in err


@pytest.mark.parametrize(
    ("argv", "method", "path", "feature"),
    [
        (["limit", "--until", "3h"], "POST", "/api/v1/me/limit", "usage limits"),
        (["link", "remove", "tsk-0004", "lnk-0007"], "DELETE", f"{BASE}/links/lnk-0007",
         "card links"),
        (["messages"], "GET", "/api/v1/projects/oliver/maity/messages", "project messages"),
        (["takeover", "list"], "GET", "/api/v1/projects/oliver/maity/takeovers", "takeovers"),
        (["files", "get", "att-0001"], "GET", "/api/v1/projects/oliver/maity/attachments/att-0001",
         "attachments"),
    ],
)  # fmt: skip
def test_commands_on_routes_the_hub_lacks(
    argv: list[str], method: str, path: str, feature: str, joined: Path, fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    fake.routes[(method, path)] = lambda s: NOT_FOUND
    assert cli.main(argv) == cli.EXIT_ERROR
    assert f"this hub does not have {feature} yet" in capsys.readouterr().err
