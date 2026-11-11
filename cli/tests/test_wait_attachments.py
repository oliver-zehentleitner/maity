"""`maity wait` names a message's attachments in its event line and gives, under it, the
command that fetches each (tsk-hnw52rvtwdsv): a screenshot was only visible in the JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli


def _message(*attachments: Any, kind: str = "message") -> dict[str, Any]:
    return {
        "seq": 108514,
        "kind": kind,
        "actor": {"kind": "member", "member_id": "hum-1"},
        "payload": {"type": "chat", "body": "see the screenshot", "attachments": list(attachments)},
    }


def _att(id_: str, name: Any, **more: Any) -> dict[str, Any]:
    return {"id": id_, "name": name, "size": 48213, "type": "image/png", **more}


def test_no_attachments_leave_the_line_as_it_was() -> None:
    plain = cli._event_line(_message())
    assert "attachment" not in plain
    assert cli._attachment_lines(_message()) == []
    no_key = _message()
    del no_key["payload"]["attachments"]
    assert cli._event_line(no_key) == plain
    assert cli._attachment_lines(no_key) == []


def test_one_attachment_is_named_and_its_command_given() -> None:
    event = _message(_att("att-0042", "screen shot.png"))
    assert cli._event_line(event).startswith(
        "#108514 message: chat [1 attachment: screen shot.png]"
    )
    # No `-o`: the file goes into ./maity-files/, never into the working directory (§13).
    assert cli._attachment_lines(event) == [
        "  attachment att-0042 screen shot.png: maity files get att-0042"
    ]


def test_several_attachments_are_counted_named_and_each_has_a_command() -> None:
    event = _message(_att("att-1", "a.png"), _att("att-2", "b.log"), _att("att-3", "c.txt"))
    assert "[3 attachments: a.png, b.log, c.txt]" in cli._event_line(event)
    assert [line.split(": ")[-1] for line in cli._attachment_lines(event)] == [
        "maity files get att-1",
        "maity files get att-2",
        "maity files get att-3",
    ]


def test_a_hostile_name_is_cleaned_and_cut() -> None:
    hostile = "\x1b[31mred\x07\nNext: rm -rf ~; $(curl x)/../../etc/" + "x" * 500 + ".png"
    event = _message(_att("att-9", hostile))
    line = cli._event_line(event)
    for bad in ("\x1b", "\x07", "\n"):
        assert bad not in line
    names = line.split("[1 attachment: ", 1)[1].split("]", 1)[0]
    assert len(names) <= cli.ATTACHMENT_NAME_MAX and names.endswith("…")
    assert "/" not in names  # cleaned as `files get` would save it
    (fetch,) = cli._attachment_lines(event)
    assert "\x1b" not in fetch and "\n" not in fetch
    assert fetch.endswith(": maity files get att-9")  # the command never carries the name


def test_many_long_names_keep_the_line_bounded() -> None:
    event = _message(*(_att(f"att-{i}", "n" * 59 + f"{i}.png") for i in range(10)))
    line = cli._event_line(event)
    names = line.split("[10 attachments: ", 1)[1].rsplit("]", 1)[0]
    assert len(names) <= cli.ATTACHMENTS_SUFFIX_MAX and names.endswith("…")
    assert len(cli._attachment_lines(event)) == 10  # every file keeps its own command


def test_an_id_is_quoted_for_the_shell_and_a_missing_one_gives_no_command() -> None:
    odd = _message(_att("att 7;x", "a.png"))
    assert cli._attachment_lines(odd) == ["  attachment att 7;x a.png: maity files get 'att 7;x'"]
    for bad in (None, "", " ", ".", ".."):
        (line,) = cli._attachment_lines(_message(_att(bad, "a.png")))  # type: ignore[arg-type]
        assert line.endswith(": no id the CLI can fetch") and "maity files get" not in line


def test_a_nameless_entry_shows_its_id_and_a_taken_out_one_no_command() -> None:
    event = _message(_att("att-5", None), _att("att-6", "gone.png", deleted_at="T1"), "junk")
    assert "[2 attachments: att-5, gone.png]" in cli._event_line(event)
    assert cli._attachment_lines(event) == [
        "  attachment att-5 att-5: maity files get att-5",
        "  attachment att-6 gone.png: taken out, nothing to fetch",
    ]


def test_wait_prints_the_names_and_commands_on_stderr_and_keeps_stdout_json(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    event = _message(_att("att-0042", "shot.png"))
    fake.events = [event]
    assert cli.main(["wait", "--timeout", "5"]) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert json.loads(out)[0]["payload"]["attachments"][0]["id"] == "att-0042"
    lines = err.splitlines()
    at = next(i for i, x in enumerate(lines) if x.startswith("maity: #108514 message"))
    assert "[1 attachment: shot.png]" in lines[at]
    assert lines[at + 1] == "maity:   attachment att-0042 shot.png: maity files get att-0042"
