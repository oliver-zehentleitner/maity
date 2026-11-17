from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from maity.runner import plaincall

SRC = Path(plaincall.__file__).resolve().parents[2]


def bash(command: str, tool: str = "Bash") -> dict[str, object]:
    return {"hook_event_name": "PreToolUse", "tool_name": tool,
            "tool_input": {"command": command, "description": "x"}}  # fmt: skip


REFUSED = [
    "maity a > f",
    "maity a >> f",
    "maity a 2>f",
    "maity a ; x",
    "maity a && x",
    "maity a || x",
    "maity a & x",
    "maity a &",
    "maity a | x",
    "maity a $(x)",
    "maity a `x`",
    "maity a <(x)",
    "maity a < f",
    "maity a <<< text",
    "maity say x - <<'EOF'\nhello\nEOF",
    "maity a\nx",
    "maity a $X",
    "maity a ${X@P}",
    "maity a $'x'",
    'maity a "$(x)"',
    'maity a "`x`"',
    'maity a "${X}"',
    "maity a 'unclosed",
    'maity a "unclosed',
    "maity a 'two\nlines'",
    "maity a \\",
    "maity a (x)",
    "maity a {x,y}",
    "maity a *",
    "maity a b",
    "﻿maity a ; x",  # a character the harness may trim before matching
    "\nmaity a > f",
    "  maity\ta | x",
    "MAITY a > f",
    "maity;x",  # stays in the sandbox anyway; refused all the same
]
ALLOWED = [
    "maity task show tsk-x",
    "maity say --to lotse#wtwy 'text with ; & | < > $ ` and (x)'",
    'maity say --to lotse "a \\"quoted\\" word, 50%"',
    "maity files get fil-1 -o out/a.txt",
    "maity a\\;b",  # an escaped character is a literal one
    "  maity resume  \n",
    "maity",
]
NOT_DECIDED = [
    "git status | head",
    "make test && echo ok",
    "FOO=1 maity a > f",  # starts with a variable: not a maity line for the hook
    "env maity a > f",
    "echo maity > f",
]


def runner_refusal(command: str) -> str:
    """The reason a runner call is refused with: a `maity` line that is not one plain call is
    refused as that, its reason naming the way out."""
    if plaincall.applies(command) and not plaincall.plain(command):
        return plaincall.REFUSED
    return plaincall.RUNNER_REFUSED


RUNNER = [
    "maity runner status",
    "maity runner loop --spec loop.json",
    "maity runner logcap out.log 100",
    "maity runner plaincall",
    "maity runner stub --exit-code 0",
    "MAITY_PLACEMENT= maity runner status",
    "FOO=1 maity runner status",
    "env -u MAITY_PLACEMENT maity runner status",
    "nohup maity runner status",
    "/usr/local/bin/maity runner status",
    "maity --for lotse runner status",
    "maity --for=lotse runner status",
    "maity --fo lotse runner status",
    "maity -- runner status",
    "maity 'runner' status",
    'maity run""ner status',
    "MAITY runner status",
    "true; maity runner status",
    "git status && maity runner status",
    "echo x\nmaity runner status",
    "echo x # note\nmaity runner status",
    "(maity runner status)",
    "maity runner status > out.txt",
]
# A word `maity` followed anywhere later by a word `runner`, however the line spells them.
RUNNER_ANYWHERE = [
    # a quoted or escaped operator is a word, not the end of a command
    "maity --for ';' runner status",
    "maity --for '|' runner status",
    'maity --for "&&" runner status',
    "maity --for \\; runner status",
    "maity --fo ')' runner status",
    # end-of-options markers, however many
    "maity -- -- runner status",
    "maity -- -- -- runner status",
    # quotes the line never closes, or that the hook reads differently from a comment
    "FOO=1 maity runner status # it's",
    "git status # it's\nmaity runner status",
    "echo $'a\\'b'; maity runner status",
    "echo 'never closed runner",
    # a backslash-newline joins the lines
    "FOO=1 mai\\\nty runner status",
    # words the shell still expands
    "maity $'runner' status",
    "maity $R status",
    "$M runner status",
    "FOO=1 maity $R status",
    # quoted text another shell reads again
    "sh -c 'maity runner status'",
    'bash -c "true; maity runner status"',
    # text: refused all the same, the reason names --body-file
    "maity say lotse runner",
    "maity say --to lotse 'maity runner status'",
    "maity task create maity --body runner",
    "echo maity; runner status",
]
NOT_RUNNER = [
    "maity runners",
    "maity say lotse 'the runner is up'",
    "maity task show tsk-x",
    "ls runner/",
    "git log --oneline runner",
    "cp $SRC $DST",
    "echo 'never closed",
    "echo $'it\\'s the runner'",  # ANSI-C quoting closes where the shell closes it
]


@pytest.mark.parametrize("command", RUNNER_ANYWHERE)
def test_a_runner_word_after_a_maity_word_is_refused_in_any_spelling(command: str) -> None:
    assert plaincall.refusal(bash(command)) == runner_refusal(command)


@pytest.mark.parametrize("command", NOT_RUNNER)
def test_a_line_without_a_runner_word_after_a_maity_word_is_not_a_runner_call(
    command: str,
) -> None:
    assert plaincall.refusal(bash(command)) != plaincall.RUNNER_REFUSED


# Words after `maity`, as its own parser reads them on this Python: every shape whose
# subcommand it takes as `runner` is refused by the hook.
PARSER_SHAPES = [
    ["runner", "status"],
    ["--", "runner", "status"],
    ["--", "--", "runner", "status"],
    ["--", "--", "--", "runner", "status"],
    ["--for", "x", "runner", "status"],
    ["--for", "x", "--", "--", "runner", "status"],
    ["--for=;", "runner", "status"],
    ["--fo", "|", "runner", "status"],
    ["--f", "&&", "--", "runner", "status"],
    ["--for", "--", "runner", "status"],
]


@pytest.mark.parametrize("words", PARSER_SHAPES)
def test_every_line_maitys_parser_reads_as_runner_is_refused(words: list[str]) -> None:
    from maity import cli

    try:
        args, _ = cli.build_parser().parse_known_args(words)
        command = args.command
    except SystemExit:
        command = None
    line = "maity " + " ".join("'" + word + "'" for word in words)
    if command == "runner":
        assert plaincall.refusal(bash(line)) == plaincall.RUNNER_REFUSED
    else:
        assert plaincall.refusal(bash(line)) in (plaincall.RUNNER_REFUSED, None)


@pytest.mark.parametrize("command", RUNNER)
def test_a_line_that_runs_maity_runner_is_refused(command: str) -> None:
    assert plaincall.refusal(bash(command)) == runner_refusal(command)


@pytest.mark.parametrize("command", NOT_RUNNER)
def test_runner_as_a_word_elsewhere_is_not_a_runner_call(command: str) -> None:
    assert plaincall.refusal(bash(command)) != plaincall.RUNNER_REFUSED


@pytest.mark.parametrize("command", REFUSED)
def test_a_maity_line_that_is_not_one_plain_call_is_refused(command: str) -> None:
    assert plaincall.refusal(bash(command)) == plaincall.REFUSED


@pytest.mark.parametrize("command", ALLOWED)
def test_one_plain_maity_call_passes(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


@pytest.mark.parametrize("command", NOT_DECIDED)
def test_other_command_lines_are_left_to_the_permission_rules(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


def test_any_tool_with_a_command_is_checked() -> None:
    assert plaincall.refusal(bash("maity a | x", tool="PowerShell")) == plaincall.REFUSED
    assert plaincall.refusal({"tool_name": "Read", "tool_input": {"file_path": "/x"}}) is None
    assert plaincall.refusal({"tool_name": "Bash", "tool_input": {"command": 3}}) is None


def test_unreadable_input_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    assert plaincall.refusal([1]) is not None
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"\xff{")))
    assert plaincall.main([]) == 2


def run_hook(payload: bytes) -> subprocess.CompletedProcess[str]:
    """As Claude Code runs it: a separate process, input on stdin, isolated mode."""
    return subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-I", "-c",
         f"import sys; sys.path.insert(0, {str(SRC)!r}); "
         "from maity.runner import plaincall; raise SystemExit(plaincall.main())"],
        input=payload.decode("utf-8", "surrogateescape"), capture_output=True, text=True,
        check=False, timeout=60,
    )  # fmt: skip


def test_the_hook_process_refuses_with_exit_2_and_the_reason_on_stderr() -> None:
    done = run_hook(json.dumps(bash("maity a > f")).encode())
    assert done.returncode == 2 and done.stdout == ""
    assert done.stderr.strip() == plaincall.REFUSED
    done = run_hook(json.dumps(bash("maity task show tsk-x")).encode())
    assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    assert run_hook(b"not json").returncode == 2


def test_the_hook_process_refuses_a_runner_call() -> None:
    done = run_hook(json.dumps(bash("maity runner status")).encode())
    assert done.returncode == 2 and done.stdout == ""
    assert done.stderr.strip() == plaincall.RUNNER_REFUSED
