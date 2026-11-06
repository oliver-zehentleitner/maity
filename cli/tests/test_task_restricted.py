"""`maity task restricted show|set|clear` (docs/api.md §6.4 "Restricted text", §13) against
the fake hub: the text only from a file or stdin, never repeated from the command line, a
fresh version on every write, a conflict never retried and never printed."""

from __future__ import annotations

import io
import urllib.parse
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli

PATH = "/api/v1/projects/oliver/maity/tasks/tsk-1/restricted"
SECRET = "the vault code is 4711"
OLIVER = {"kind": "human", "id": "hum-oliver", "handle": "oliver"}


def state(version: int = 3, text: str | None = "Line one\nLine two", **more: Any) -> dict[str, Any]:
    return {"task_id": "tsk-1", "text": text, "version": version, "updated_by": OLIVER,
            "updated_at": "2026-11-04T18:00:00Z",
            "history": [{"version": version, "action": "set", "by": OLIVER,
                         "at": "2026-11-04T18:00:00Z"}], **more}  # fmt: skip


def written(version: int) -> dict[str, Any]:
    return {"task_id": "tsk-1", "version": version, "updated_by": OLIVER,
            "updated_at": "2026-11-05T09:00:00Z"}  # fmt: skip


def refusal(status: int, code: str, **details: Any) -> tuple[int, dict[str, Any]]:
    return status, {"error": {"code": code, "message": f"refused: {code}", "details": details}}


def calls(fake: fakehub.FakeHub) -> list[tuple[str, str]]:
    return [(s.method, s.path) for s in fake.signed()]


# --- show ----------------------------------------------------------------------------------


def test_show_quotes_the_text_as_data_with_its_changes(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", PATH)] = lambda s: (200, state(text="Line one\nLine \u202etwo"))
    assert cli.main(["task", "restricted", "show", "tsk-1"]) == cli.EXIT_OK
    assert capsys.readouterr().out == (
        "tsk-1 restricted text, version 3, changed by @oliver at 2026-11-04T18:00:00Z\n"
        "  > Line one\n"
        "  > Line \\u202etwo\n"
        "  changes:\n"
        "    version 3 set by @oliver at 2026-11-04T18:00:00Z\n"
    )


def test_show_says_when_there_is_no_text(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", PATH)] = lambda s: (
        200, {"task_id": "tsk-1", "text": None, "version": 0, "updated_by": None,
              "updated_at": None, "history": []})  # fmt: skip
    assert cli.main(["task", "restricted", "show", "tsk-1"]) == cli.EXIT_OK
    assert capsys.readouterr().out == "tsk-1 restricted text, version 0\n  no restricted text\n"


def test_show_json_is_the_answer_escaped(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", PATH)] = lambda s: (200, state(text="bidi \u202e here"))
    assert cli.main(["task", "restricted", "show", "tsk-1", "--json"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "\u202e" not in out and "\\u202e" in out and '"version": 3' in out


def test_outside_the_set_the_refusal_says_so(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", PATH)] = lambda s: refusal(403, "forbidden", reason="restricted")
    assert cli.main(["task", "restricted", "show", "tsk-1"]) == cli.EXIT_ERROR
    assert "reason: restricted" in capsys.readouterr().err


# --- set -----------------------------------------------------------------------------------


def test_set_reads_the_file_and_sends_the_version_just_read(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "text.txt"
    source.write_text(SECRET + "\nsecond line\n", encoding="utf-8")
    fake.routes[("GET", PATH)] = lambda s: (200, state(version=3))
    fake.routes[("PUT", PATH)] = lambda s: (200, written(4))
    assert cli.main(["task", "restricted", "set", "tsk-1", "--file", str(source)]) == cli.EXIT_OK
    assert calls(fake) == [("GET", PATH), ("PUT", PATH)]
    # One final line ending dropped, the rest as written.
    assert fake.signed()[-1].json() == {"text": SECRET + "\nsecond line", "base_version": 3}
    captured = capsys.readouterr()
    assert (
        captured.out == "set the restricted text of tsk-1: version 4, changed by @oliver"
        " at 2026-11-05T09:00:00Z\n"
    )
    assert SECRET not in captured.out + captured.err


def test_set_reads_stdin_with_file_dash(
    joined: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("\ufeff" + SECRET + "\r\n"))
    fake.routes[("GET", PATH)] = lambda s: (200, state(version=0, text=None))
    fake.routes[("PUT", PATH)] = lambda s: (200, written(1))
    assert cli.main(["task", "restricted", "set", "tsk-1", "--file", "-"]) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"text": SECRET, "base_version": 0}


@pytest.mark.parametrize(
    "argv",
    [
        ["task", "restricted", "set", "tsk-1", SECRET],
        ["task", "restricted", "set", "tsk-1", "--file", "-", SECRET],
        ["task", "restricted", "set", "tsk-1", "--" + SECRET.replace(" ", "-")],
        ["task", "restricted", "set", "tsk-1", "--", SECRET],
    ],
)
def test_a_text_on_the_command_line_is_refused_without_repeating_it(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(argv)
    assert stopped.value.code == cli.EXIT_USAGE
    captured = capsys.readouterr()
    assert "never an argument" in captured.err
    assert "vault" not in captured.out + captured.err
    assert not fake.signed()


def test_set_without_a_file_is_refused_before_any_call(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    # The text where the card belongs: refused, not repeated, nothing sent.
    assert cli.main(["task", "restricted", "set", SECRET]) == cli.EXIT_USAGE
    captured = capsys.readouterr()
    assert "never an argument" in captured.err and "vault" not in captured.out + captured.err
    assert not fake.signed()


def test_a_card_with_white_space_is_refused_without_repeating_it(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "text.txt"
    source.write_text("x", encoding="utf-8")
    argv = ["task", "restricted", "set", SECRET, "--file", str(source)]
    assert cli.main(argv) == cli.EXIT_USAGE
    captured = capsys.readouterr()
    assert "white space" in captured.err and "vault" not in captured.out + captured.err
    assert not fake.signed()


def test_an_unreadable_file_is_not_named(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = str(tmp_path / SECRET)
    assert cli.main(["task", "restricted", "set", "tsk-1", "--file", missing]) == cli.EXIT_USAGE
    captured = capsys.readouterr()
    assert "cannot be read" in captured.err and "vault" not in captured.out + captured.err
    assert not fake.signed()


def test_a_conflict_is_not_retried_and_the_text_is_not_printed(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "text.txt"
    source.write_text("mine", encoding="utf-8")
    reads = iter([state(version=3), state(version=4, text=SECRET)])
    fake.routes[("GET", PATH)] = lambda s: (200, next(reads))
    fake.routes[("PUT", PATH)] = lambda s: refusal(
        409, "conflict", current_version=4, base_version=3
    )
    assert cli.main(["task", "restricted", "set", "tsk-1", "--file", str(source)]) == cli.EXIT_ERROR
    assert calls(fake) == [("GET", PATH), ("PUT", PATH), ("GET", PATH)]
    captured = capsys.readouterr()
    assert "changed after it was read; it is now version 4, changed by @oliver" in captured.err
    assert "vault" not in captured.out + captured.err


@pytest.mark.parametrize(
    ("status", "code", "details", "shown"),
    [
        (409, "restricted_quota", {"max": 200}, "restricted_quota"),
        (429, "rate_limited", {}, "rate_limited"),
        (400, "invalid", {"fields": {"text": "control_character"}}, "control_character"),
    ],
)
def test_the_hubs_refusals_are_said_by_their_code(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    status: int, code: str, details: dict[str, Any], shown: str,
) -> None:  # fmt: skip
    source = tmp_path / "text.txt"
    source.write_text(SECRET, encoding="utf-8")
    fake.routes[("GET", PATH)] = lambda s: (200, state(version=3))
    fake.routes[("PUT", PATH)] = lambda s: refusal(status, code, **details)
    assert cli.main(["task", "restricted", "set", "tsk-1", "--file", str(source)]) == cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert shown in captured.err and "vault" not in captured.out + captured.err


# --- clear ---------------------------------------------------------------------------------


def test_clear_sends_the_version_just_read_in_the_query(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", PATH)] = lambda s: (200, state(version=5))
    fake.routes[("DELETE", PATH)] = lambda s: (200, written(6))
    assert cli.main(["task", "restricted", "clear", "tsk-1"]) == cli.EXIT_OK
    assert calls(fake) == [("GET", PATH), ("DELETE", PATH)]
    assert dict(urllib.parse.parse_qsl(fake.signed()[-1].query)) == {"base_version": "5"}
    assert capsys.readouterr().out.startswith("cleared the restricted text of tsk-1: version 6")
