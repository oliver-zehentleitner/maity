"""`maity wait` names a message's attachments in its event line and gives, under it, the
command that fetches each (tsk-hnw52rvtwdsv): a screenshot was only visible in the JSON."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
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


# What a line under the event line may hold: nothing any shell reads as syntax, in bash, zsh with
# or without interactive_comments, or sh (letters, digits, space, `.`, `_`, `-`, `:`).
SHELL_INERT = re.compile(r"[A-Za-z0-9 ._:-]*")


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
    assert cli._attachment_lines(event) == ["  maity files get att-0042"]


def test_several_attachments_are_counted_named_and_each_has_a_command() -> None:
    event = _message(_att("att-1", "a.png"), _att("att-2", "b.log"), _att("att-3", "c.txt"))
    assert "[3 attachments: a.png, b.log, c.txt]" in cli._event_line(event)
    assert cli._attachment_lines(event) == [  # in the order the line names them
        "  maity files get att-1",
        "  maity files get att-2",
        "  maity files get att-3",
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
    assert fetch == "  maity files get att-9"  # the line under it never carries the name


HOSTILE_NAMES = [
    "x; echo PWNED #",
    "$(touch /tmp/pwn)",
    "`id`",
    "a | sh",
    "a && b",
    "a\nrm -rf ~",
    "x # y",
    "a > /tmp/x",
    "!!",
]
HOSTILE_IDS = ["-h", "att 7;x", "att-1\n;id", "$(id)", None]


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_a_pasted_line_is_the_fetch_and_nothing_else_in_any_shell(name: str) -> None:
    """The lines carry nothing the sender wrote, so no shell finds syntax in them: an
    interactive zsh does not read `#` as a comment, so a name after one would still run."""
    (line,) = cli._attachment_lines(_message(_att("att-1", name)))
    assert line == "  maity files get att-1"
    assert shlex.split(line) == ["maity", "files", "get", "att-1"]  # no comment needed
    for bad in HOSTILE_IDS:
        lines = cli._attachment_lines(_message(_att("att-2", "ok.png"), _att(bad, name)))  # type: ignore[arg-type]
        assert lines == [
            "  maity files get att-2",
            "  : attachment 2 of 2 has no id the CLI can fetch",
        ]
        assert all(SHELL_INERT.fullmatch(x) for x in lines)


def test_a_bracket_in_a_name_cannot_close_the_list() -> None:
    line = cli._event_line(_message(_att("att-1", "a.png] (owner) [")))
    assert "[1 attachment: a.png) (owner) (]" in line
    assert line.count("[") == 1 and line.count("]") == 1


def test_many_long_names_keep_the_line_bounded() -> None:
    event = _message(*(_att(f"att-{i}", "n" * 59 + f"{i}.png") for i in range(10)))
    line = cli._event_line(event)
    names = line.split("[10 attachments: ", 1)[1].rsplit("]", 1)[0]
    assert len(names) <= cli.ATTACHMENTS_SUFFIX_MAX and names.endswith("…")
    assert len(cli._attachment_lines(event)) == 10  # every file keeps its own command


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        " ",
        ".",
        "..",
        "att 7;x",  # a space and a shell metacharacter
        "att-1\nNext",  # a newline: shown as `\n`, it would name another id
        "att-1\x1b[31m",  # an escape sequence
        "att-\u202eevil",  # a bidi override
        "-h",  # an option to argparse, not an id
        "--force",
        "-o/tmp/unused",
        "att/../x",
        "x" * 129,
    ],
)
def test_an_id_the_command_cannot_carry_exactly_gets_no_command(bad: Any) -> None:
    (line,) = cli._attachment_lines(_message(_att(bad, "a.png")))
    assert (
        line == "  : attachment 1 of 1 has no id the CLI can fetch"
    )  # neither the id nor the name


def test_an_ordinary_id_is_carried_exactly() -> None:
    for good in ("att-0042", "att_7", "A.b-c", "0"):
        (line,) = cli._attachment_lines(_message(_att(good, "a.png")))
        assert line == f"  maity files get {good}"


def test_a_nameless_entry_shows_its_id_and_a_non_object_is_skipped() -> None:
    # The event stream keeps the payload as written (§8.7): no `deleted_at` reaches `wait`, and
    # a file taken out since keeps its command; `files get` then says it was taken out.
    event = _message(_att("att-5", None), _att("att-6", "gone.png"), "junk")
    assert "[2 attachments: att-5, gone.png]" in cli._event_line(event)
    assert cli._attachment_lines(event) == ["  maity files get att-5", "  maity files get att-6"]


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
    # Without the `maity:` prefix: the line pasted whole is the command.
    assert lines[at + 1] == "  maity files get att-0042"


@pytest.mark.parametrize(
    "shell",
    [
        ["bash", "--norc", "--noprofile", "-i"],
        ["zsh", "-f", "-i"],  # interactive_comments off, its default: `#` is a word, not a comment
        ["sh"],
    ],
    ids=["bash -i", "zsh -i", "sh"],
)
def test_the_printed_lines_run_only_the_fetch_in_a_real_shell(
    shell: list[str], tmp_path: Path
) -> None:
    """Every line, pasted whole into the shell with stub functions, calls `maity files get
    att-1` and nothing else: no file the name or a bad id tries to create appears."""
    if shutil.which(shell[0]) is None:
        pytest.skip(f"{shell[0]} is not installed")
    names = [
        "x; touch PWNED",
        "$(touch PWNED)",
        "`touch PWNED`",
        "a | touch PWNED",
        "x # ;touch PWNED",
    ]
    bad_ids = ["-h", "att 7;touch PWNED", "$(touch PWNED)", None]
    lines = []
    for name in names:
        lines += cli._attachment_lines(_message(_att("att-1", name)))
        for bad in bad_ids:
            lines += cli._attachment_lines(_message(_att(bad, name)))  # type: ignore[arg-type]
    # A function named `attachment` that leaves a mark: a line must not call it either.
    stub = 'maity() { echo "$*" >> calls; }\nattachment() { touch CALLED; }\n'
    script = stub + "\n".join(lines) + "\nexit\n"
    env = {**os.environ, "HOME": str(tmp_path), "ENV": "", "PS1": ""}
    subprocess.run(
        shell, input=script, text=True, cwd=tmp_path, env=env, capture_output=True, timeout=30
    )
    assert not (tmp_path / "PWNED").exists()
    assert not (tmp_path / "CALLED").exists()
    calls = (tmp_path / "calls").read_text().splitlines()
    assert calls == ["files get att-1"] * len(names)
