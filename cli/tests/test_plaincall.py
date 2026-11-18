from __future__ import annotations

import io
import json
import shlex
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
# A word `maity` followed later by a word `runner`, in the spellings below.
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
    "maity say lotse 'the runner is up'",
    "maity task create maity --body runner",
    "echo maity; runner status",
    # a quote that never closes, with `maity` and an expanding word
    "FOO=1 maity $R status # it's",
    "FOO=1 maity $'\\x72unner' status # it's",
    "FOO=1 maity 'r'unner status # it's",
    "FOO=1 maity r\\unner status # it's",
    # words the shell puts a directory in place of
    "maity ~- status",
    "maity ~ status",
]
NOT_RUNNER = [
    "maity runners",
    "maity task show tsk-x",
    "ls runner/",
    "git log --oneline runner",
    "cp $SRC $DST",
    "echo $'it\\'s the runner'",  # ANSI-C quoting closes where the shell closes it
    "maity files get fil-1 -o ~/out.txt",
]


def nested(line: str, levels: int) -> str:
    """`line` run by `sh -c`, `levels` times over."""
    for _ in range(levels):
        line = "sh -c " + shlex.quote(line)
    return line


@pytest.mark.parametrize("levels", [1, 4, 5, 6, 12])
def test_a_runner_call_nested_in_any_depth_of_quoted_text_is_refused(levels: int) -> None:
    assert plaincall.refusal(bash(nested("maity runner status", levels))) == (
        plaincall.RUNNER_REFUSED
    )


SPELLINGS = [
    "maity r\\unner status",
    "maity 'r'unner status",
    "maity r''unner status",
    "maity $'\\x72unner' status",
    "m\\aity r\\unner status",
]


@pytest.mark.parametrize("levels", [5, 6])
@pytest.mark.parametrize("line", SPELLINGS)
def test_quoted_text_nested_past_the_limit_is_refused_whatever_it_holds(
    line: str, levels: int
) -> None:
    assert plaincall.refusal(bash(nested(line, levels))) == plaincall.RUNNER_REFUSED


def test_nested_text_without_runner_passes_only_up_to_the_limit() -> None:
    assert plaincall.refusal(bash(nested("maity task show tsk-x", 4))) is None
    assert plaincall.refusal(bash(nested("maity task show tsk-x", 5))) == (plaincall.RUNNER_REFUSED)


# A comment is text with quotes to the hook: the nesting it seems to have counts.
COMMENTED = json.loads(
    r'''"NODE_ENV=1 maity status #\"#\\\"#\\\\\\\"#\\\\\\\\\\\\\\\"#\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\"\nmaity r''unner status #\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\"\\\\\\\\\\\\\\\"\\\\\\\"\\\"\""'''  # noqa: E501
)

UNREADABLE = [
    "FOO=1 m\\aity r\\unner status # it's",
    "FOO=1 m''aity r''unner status # it's",
    "FOO=1 $'\\x6daity' $'\\x72unner' status # it's",
    "FOO=1 m\\aity r\\unner status\necho 'x",
    "git status # it's",
    "echo 'never closed",
]


@pytest.mark.parametrize("command", [COMMENTED, *UNREADABLE])
def test_a_line_not_read_to_the_end_is_refused_whatever_it_holds(command: str) -> None:
    assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED


# Lines that name `maity` and hold a comment, a heredoc or more than one line.
NOT_ONE_READ_LINE = [
    'git status # \'"\nmaity --for="\' " runner status # "',
    'NODE_ENV=1 maity roles # \'"\nmaity --for="\' " runner status # "',
    'cat <<EOF >/dev/null\n\'"\nEOF\nmaity --for="\' " runner status # "',
]
WITH_A_COMMENT = [
    "maity status # note",
    "maity status #",
    "git status # maity",
    "true;#maity",
    "x 'a #b' maity",
    "# maity",
    "git status # M\\aity",
    "git status # m''aity",
    "git status # MAITY",
]
WITH_A_HEREDOC = [
    "cat <<EOF maity",
    "cat <<<maity",
    "cat <<-'EOF' MAITY",
]
ON_MORE_THAN_ONE_LINE = [
    "echo x\nmaity status",
    "maity status\necho x",
    'echo x\n\nM""aity',
]
# Lines these rules do not refuse.
READ_TO_THE_END = [
    "maity say --to lotse#wtwy x",
    "maity say x a#b",
    "maity say x 'a#b'",
    "  maity resume  \n",
    "git status # no name here",
    "cat <<EOF x",
    "echo a\necho b",
]


@pytest.mark.parametrize(
    "command", [*NOT_ONE_READ_LINE, *WITH_A_COMMENT, *WITH_A_HEREDOC, *ON_MORE_THAN_ONE_LINE]
)
def test_a_line_naming_maity_that_is_not_one_read_line_is_refused(command: str) -> None:
    assert plaincall.refusal(bash(command)) == runner_refusal(command)


@pytest.mark.parametrize("command", READ_TO_THE_END)
def test_a_line_read_to_the_end_is_not_refused_as_unread(command: str) -> None:
    assert plaincall.refusal(bash(command)) != plaincall.RUNNER_REFUSED


# Words in quoted text count in the line's order, with the words around them.
IN_LINE_ORDER = [
    "echo 'maity --for=' ' runner status'",
    "echo 'a maity' 'b' 'runner c'",
    "echo 'maity' \"x runner\"",
    "sh -c 'maity x' -- 'sh -c \"runner y\"'",
]


@pytest.mark.parametrize("command", IN_LINE_ORDER)
def test_quoted_words_count_in_line_order(command: str) -> None:
    assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED


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
