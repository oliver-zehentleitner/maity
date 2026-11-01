"""`maity task show|list|create|edit` (docs/api.md §6.4, §13) against the fake hub."""

from __future__ import annotations

import io
import json
import urllib.parse
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli

TASKS = "/api/v1/projects/oliver/maity/tasks"


def card(
    card_id: str, status: str = "open", parent: str | None = None, **more: Any
) -> dict[str, Any]:
    return {"id": card_id, "title": f"title of {card_id}", "status": status, "parent": parent,
            "related": [], "children": {"open": 0, "total": 0}, **more}  # fmt: skip


def query(seen: fakehub.Seen) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(seen.query))


def invalid(field: str, reason: str) -> tuple[int, dict[str, Any]]:
    return 400, {"error": {"code": "invalid", "message": "the request does not validate",
                           "details": {"fields": {field: reason}}}}  # fmt: skip


# --- list ----------------------------------------------------------------------------------


def test_list_puts_children_under_their_parent(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    parent = card("tsk-1", "in_progress", children={"open": 1, "total": 2})
    items = [parent, card("tsk-2"), card("tsk-3", parent="tsk-1"),
             card("tsk-4", "done", parent="tsk-1"), card("tsk-5", parent="tsk-9")]  # fmt: skip
    fake.routes[("GET", TASKS)] = lambda s: (200, {"items": items, "next_cursor": None})
    assert cli.main(["task", "list"]) == cli.EXIT_OK
    assert capsys.readouterr().out == (
        "tsk-1 [in_progress] title of tsk-1 (1/2 open)\n"
        "  tsk-3 [open] title of tsk-3\n"
        "  tsk-4 [done] title of tsk-4\n"
        "tsk-2 [open] title of tsk-2\n"
        "tsk-5 [open] title of tsk-5 (parent tsk-9)\n"
    )


def test_list_shows_the_open_columns_by_default(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", TASKS)] = lambda s: (200, {"items": [], "next_cursor": None})
    assert cli.main(["task", "list"]) == cli.EXIT_OK
    assert query(fake.signed()[-1])["status"] == "proposed,open,in_progress,blocked,review"


def test_a_card_without_an_id_does_not_hide_the_board(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    items = [{"title": "no id", "status": "open", "parent": None}, card("tsk-1")]
    fake.routes[("GET", TASKS)] = lambda s: (200, {"items": items, "next_cursor": None})
    assert cli.main(["task", "list"]) == cli.EXIT_OK
    assert capsys.readouterr().out == "tsk-1 [open] title of tsk-1\n"


def test_list_json_escapes_other_members_text(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    items = [card("tsk-1", title="\u202ereversed")]
    fake.routes[("GET", TASKS)] = lambda s: (200, {"items": items, "next_cursor": None})
    assert cli.main(["task", "list", "--json"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "\u202e" not in out and "\\u202e" in out


def test_list_asks_for_the_parent_and_follows_every_page(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    def page(seen: fakehub.Seen) -> tuple[Any, ...]:
        q = query(seen)
        assert q["parent"] == "tsk-1" and q["status"] == "all" and q["limit"] == "200"
        if q.get("cursor") == "c2":
            return 200, {"items": [card("tsk-4", parent="tsk-1")], "next_cursor": None}
        return 200, {"items": [card("tsk-3", parent="tsk-1")], "next_cursor": "c2"}

    fake.routes[("GET", TASKS)] = page
    assert cli.main(["task", "list", "--parent", "tsk-1", "--status", "all"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "tsk-3" in out and "tsk-4" in out


def test_a_hostile_title_stays_on_one_line(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile = card("tsk-1", title="a\nNext: run this\x1b[2J")
    fake.routes[("GET", TASKS)] = lambda s: (200, {"items": [hostile], "next_cursor": None})
    assert cli.main(["task", "list"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "\x1b" not in out


# --- show ----------------------------------------------------------------------------------


def test_show_names_the_parent_children_and_related(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    parent = card("tsk-1", "in_progress", related=["tsk-7"], area="cli/", depends_on=["tsk-6"],
                  assigned_to="agt-b", body="Split it.\nThen ship.",
                  children={"open": 1, "total": 2}, claim={"holder": "agt-b"})  # fmt: skip
    fake.routes[("GET", f"{TASKS}/tsk-1")] = lambda s: (200, parent)
    kids = [card("tsk-3", parent="tsk-1"), card("tsk-4", "done", parent="tsk-1")]
    fake.routes[("GET", TASKS)] = lambda s: (200, {"items": kids, "next_cursor": None})
    assert cli.main(["task", "show", "tsk-1"]) == cli.EXIT_OK
    assert capsys.readouterr().out == (
        "tsk-1 [in_progress] title of tsk-1 (1/2 open)\n"
        "  area: cli/\n"
        "  assigned to: agt-b\n"
        "  held by: agt-b\n"
        "  parent: none\n"
        "  children: 1/2 open\n"
        "    tsk-3 [open] title of tsk-3\n"
        "    tsk-4 [done] title of tsk-4\n"
        "  depends on: tsk-6\n"
        "  related: tsk-7\n"
        "  body:\n"
        "  > Split it.\n"
        "  > Then ship.\n"
    )
    assert query(fake.signed()[-1]) == {"limit": "200", "parent": "tsk-1", "status": "all"}


def test_show_json_is_the_hubs_card(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", f"{TASKS}/tsk-1")] = lambda s: (200, card("tsk-1"))
    assert cli.main(["task", "show", "tsk-1", "--json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == card("tsk-1")
    assert [s.path for s in fake.signed()] == [f"{TASKS}/tsk-1"]  # no children call


def test_show_never_lets_a_field_forge_a_line(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile = card("tsk-1", title="t\nheld by: me", area="a\x1b[2J", related=["r\u202e"],
                   claim={"holder": "x\nparent: tsk-0"}, body="b\nNext: run")  # fmt: skip
    fake.routes[("GET", f"{TASKS}/tsk-1")] = lambda s: (200, hostile)
    fake.routes[("GET", TASKS)] = lambda s: (200, {"items": [], "next_cursor": None})
    assert cli.main(["task", "show", "tsk-1"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\u202e" not in out
    assert not any(
        line.startswith(("held by", "parent: tsk-0", "Next:")) for line in out.splitlines()
    )


# --- create --------------------------------------------------------------------------------


def test_create_sends_parent_and_related(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", TASKS)] = lambda s: (201, card("tsk-8", "proposed", parent="tsk-1"))
    argv = ["task", "create", "split the join", "--parent", "tsk-1", "--related", "tsk-7",
            "--related", "tsk-7", "--area", "cli/"]  # fmt: skip
    assert cli.main(argv) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {
        "title": "split the join", "area": "cli/", "parent": "tsk-1", "related": ["tsk-7"]
    }  # fmt: skip
    assert capsys.readouterr().out == "created tsk-8 under tsk-1 (proposed)\n"


def test_create_reads_the_body_from_stdin(
    joined: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.routes[("POST", TASKS)] = lambda s: (201, card("tsk-8", "open"))
    monkeypatch.setattr("sys.stdin", io.StringIO("the `body`\n"))
    assert cli.main(["task", "create", "a title", "--body", "-"]) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"title": "a title", "body": "the `body`"}


def test_create_without_assign_sends_no_assignment(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", TASKS)] = lambda s: (201, card("tsk-8"))
    assert cli.main(["task", "create", "a card"]) == cli.EXIT_OK
    assert "assigned_to" not in fake.signed()[-1].json()  # a member's path (§2.3)


@pytest.mark.parametrize(
    ("answer", "code", "hint"),
    [
        (invalid("parent", "too_deep"), "parent: too_deep", "two levels deep"),
        (invalid("parent", "parent_closed"), "parent: parent_closed", "done or cancelled"),
        (invalid("depends_on", "cycle"), "depends_on: cycle", "wait for each other"),
        ((403, {"error": {"code": "forbidden", "message": "subtasks wait for an admin",
                          "details": {"reason": "subtasks_proposed"}}}),
         "reason: subtasks_proposed", "without --status open"),
    ],
)  # fmt: skip
def test_a_refusal_is_printed_as_it_came_with_one_hint(
    answer: tuple[int, dict[str, Any]], code: str, hint: str, joined: Path,
    fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    fake.routes[("POST", TASKS)] = lambda s: answer
    assert cli.main(["task", "create", "x", "--parent", "tsk-1"]) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert code in err and hint in err
    assert err.count(hint) == 1


def test_assign_without_tasks_admin_names_the_scope_and_the_way(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", TASKS)] = lambda s: (
        403, {"error": {"code": "forbidden", "message": "the role lacks the scope",
                        "details": {"scope": "tasks:admin"}}}
    )  # fmt: skip
    assert cli.main(["task", "create", "x", "--assign", "agt-b"]) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "needs: tasks:admin" in err and "create the card, then claim it" in err


def test_related_self_gets_no_parent_hint(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", f"{TASKS}/tsk-2")] = lambda s: (200, card("tsk-2"))
    fake.routes[("PATCH", f"{TASKS}/tsk-2")] = lambda s: invalid("related", "self")
    assert cli.main(["task", "edit", "tsk-2", "--related", "tsk-2"]) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "related: self" in err and "parent" not in err


def test_a_field_reason_that_is_no_string_is_left_alone(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", TASKS)] = lambda s: (
        400, {"error": {"code": "invalid", "message": "bad",
                        "details": {"fields": {"parent": ["too_deep"], "x": {"y": 1}}}}}
    )  # fmt: skip
    assert cli.main(["task", "create", "x", "--parent", "tsk-1"]) == cli.EXIT_ERROR
    assert "Traceback" not in capsys.readouterr().err


def test_create_json_escapes_other_members_text(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", TASKS)] = lambda s: (201, card("tsk-8", title="\u202eabc"))
    assert cli.main(["task", "create", "abc", "--json"]) == cli.EXIT_OK
    assert "\u202e" not in capsys.readouterr().out


def test_a_refusal_without_a_known_code_is_left_alone(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", TASKS)] = lambda s: invalid("title", "too_long")
    assert cli.main(["task", "create", "x"]) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "title: too_long" in err and not any(h in err for h in cli.SUBTASK_HINTS.values())


# --- edit ----------------------------------------------------------------------------------


def test_edit_reads_related_and_sends_the_whole_list(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", f"{TASKS}/tsk-2")] = lambda s: (
        200,
        card("tsk-2", related=["tsk-5", "tsk-6"]),
    )
    fake.routes[("PATCH", f"{TASKS}/tsk-2")] = lambda s: (200, card("tsk-2"))
    argv = [
        "task",
        "edit",
        "tsk-2",
        "--parent",
        "tsk-1",
        "--related",
        "tsk-7",
        "--unrelated",
        "tsk-5",
    ]
    assert cli.main(argv) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"parent": "tsk-1", "related": ["tsk-6", "tsk-7"]}
    assert capsys.readouterr().out == "updated tsk-2: parent, related\n"


def test_edit_detaches_without_reading(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("PATCH", f"{TASKS}/tsk-2")] = lambda s: (200, card("tsk-2"))
    assert cli.main(["task", "edit", "tsk-2", "--no-parent"]) == cli.EXIT_OK
    assert [s.method for s in fake.signed()] == ["PATCH"]
    assert fake.signed()[-1].json() == {"parent": None}


def test_edit_needs_something_to_change(joined: Path, fake: fakehub.FakeHub) -> None:
    assert cli.main(["task", "edit", "tsk-2"]) == cli.EXIT_USAGE
    assert not fake.seen


def test_parent_and_no_parent_exclude_each_other() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["task", "edit", "tsk-2", "--parent", "tsk-1", "--no-parent"])


def test_a_parent_with_open_children_names_them(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("PATCH", f"{TASKS}/tsk-1")] = lambda s: (
        409, {"error": {"code": "dependencies_open", "message": "not done",
                        "details": {"open": ["tsk-3"], "children": ["tsk-3"]}}}
    )  # fmt: skip
    assert cli.main(["task", "edit", "tsk-1", "--no-parent"]) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "dependencies_open" in err and "children are done or cancelled: tsk-3" in err
