from __future__ import annotations

import inspect
import io
import json
import random
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
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
    "maity a\N{NO-BREAK SPACE}b",  # neither a word separator nor a safe character
    "\N{BYTE ORDER MARK}maity a ; x",  # leading, as the harness may trim it
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
    "env X='maity a' git status | cat",  # read again, its words are `X=maity` and `a`
]


def runner_refusal(command: str) -> str:
    """The reason a runner call is refused with: a `maity` line that is not one plain call is
    refused as that, its reason naming the way out."""
    if plaincall.held(command) and not plaincall.plain(command):
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
    # quotes inside a word that `eval` takes off again
    "eval \"'maity'\" \"'runner'\" status",
    "eval 'm\"a\"ity' 'r\\unner' status",
]
NOT_RUNNER = [
    "maity runners",
    "maity task show tsk-x",
    "ls runner/",
    "git log --oneline runner",
    "cp $SRC $DST",
    "maity files get fil-1 -o ~/out.txt",
]


def nested(line: str, levels: int) -> str:
    """`line` run by `watch`, `levels` times over: quoted text another shell reads again."""
    for _ in range(levels):
        line = "watch " + shlex.quote(line)
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


def test_nested_text_without_runner_is_refused_after_a_command_and_past_the_limit() -> None:
    assert plaincall.refusal(bash(nested("maity task show tsk-x", 4))) == (plaincall.PREFIX_REFUSED)
    assert plaincall.refusal(bash(nested("maity task show tsk-x", 5))) == (plaincall.RUNNER_REFUSED)


# A comment is text with quotes to the hook: the nesting it seems to have counts.
COMMENTED = json.loads(
    r'''"TZ=UTC maity status #\"#\\\"#\\\\\\\"#\\\\\\\\\\\\\\\"#\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\"\nmaity r''unner status #\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\"\\\\\\\\\\\\\\\"\\\\\\\"\\\"\""'''  # noqa: E501
)

UNREADABLE = [
    "FOO=1 m\\aity r\\unner status # it's",
    "FOO=1 m''aity r''unner status # it's",
    "FOO=1 $'\\x6daity' $'\\x72unner' status # it's",
    "FOO=1 m\\aity r\\unner status\necho 'x",
    "git status # it's",
    "echo 'never closed",
    "echo $'it\\'s the runner'",
    "printf $'a\\tb'",
]


@pytest.mark.parametrize("command", [COMMENTED, *UNREADABLE])
def test_a_line_not_read_to_the_end_is_refused_whatever_it_holds(command: str) -> None:
    assert plaincall.refusal(bash(command)) == runner_refusal(command)


# Lines that name `maity` and hold a comment, a heredoc or more than one line.
NOT_ONE_READ_LINE = [
    'git status # \'"\nmaity --for="\' " runner status # "',
    'TZ=UTC maity roles # \'"\nmaity --for="\' " runner status # "',
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


# Lines whose command, read past their leading comment lines and blank lines as Claude Code
# reads a call, is `maity` after nothing but allowed assignments (S200): they are held to one
# plain call, and the comment line makes them more than one line, so they are refused with
# the plain-call reason.
AFTER_COMMENT_LINES = [
    "# check the board\nmaity status",
    "  # a note\n\n\t# another\nmaity status",
    "#!/bin/sh\nmaity task show tsk-x",
    "#\nmaity status",
    "# it's\nmaity status",
    '# "\nmaity status',
    "# note\nTZ=UTC maity status",
    "# note\nNO_COLOR=1 LC_ALL=C maity status",
    "# note\nmaity runner status",
    "# note\nmaity status && maity status",
    "# note\nmaity status # more",
]
# Past a comment line, anything else before `maity` still makes the line a prefixed one.
PREFIXED_AFTER_COMMENT_LINES = [
    "# note\nX=1 maity status",
    "# note\nPATH=/tmp maity status",
    "# note\nTZ+=x maity status",
    "# note\ntrue && maity status",
    "# note\nenv maity status",
    "# note\n/some/path/maity status",
    "# note\nTZ=UTC X=1 maity status",
    "# note\nMAITY_WAIT_TIMEOUT=5 maity wait",
]
# Comment lines that do not stand at the start, or lines with no `maity` word after them.
NOT_PAST_COMMENT_LINES = [
    "maity status\n# done",
    "echo x # maity\nmaity status",
    "x=1 # note\nmaity status",
]


@pytest.mark.parametrize("command", AFTER_COMMENT_LINES)
def test_a_maity_line_after_comment_lines_is_held_and_refused_as_not_plain(command: str) -> None:
    assert plaincall.held(command)
    assert plaincall.refusal(bash(command)) == plaincall.REFUSED


@pytest.mark.parametrize("command", PREFIXED_AFTER_COMMENT_LINES)
def test_maity_after_anything_but_allowed_assignments_past_comment_lines_is_prefixed(
    command: str,
) -> None:
    assert plaincall.prefixed(command)
    assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED


@pytest.mark.parametrize("command", NOT_PAST_COMMENT_LINES)
def test_comment_lines_elsewhere_still_refuse_a_line_naming_maity(command: str) -> None:
    assert plaincall.refusal(bash(command)) is not None


def test_a_line_of_comment_lines_only_is_decided_as_before() -> None:
    assert not plaincall.held("# maity status\n  # more")
    assert plaincall.refusal(bash("# maity status\n  # more")) == plaincall.RUNNER_REFUSED
    assert plaincall.refusal(bash("# a note\necho hi")) is None
    assert plaincall.refusal(bash("# maity\necho hi")) == plaincall.RUNNER_REFUSED


@pytest.mark.parametrize("comment", ["# note\n", "  # a\n\n", "#!/bin/sh\n# b\n", "#\n"])
def test_no_line_naming_maity_passes_after_comment_lines(comment: str) -> None:
    """Fail-closed: reading past comment lines only moves where the line's command starts;
    the line is judged whole, so a line that names `maity` is refused after them, whatever
    the line under them would get."""
    lines = [*ALLOWED, *REFUSED, *RUNNER, *NOT_DECIDED, *READ_TO_THE_END]
    lines += [
        prefix + " maity status" for prefix in (*ASSIGNMENTS, *NOT_ALLOWED, *WAIT_TIMEOUT_PREFIXES)
    ]
    for line in lines:
        if plaincall.names_maity(line):
            assert plaincall.refusal(bash(comment + line)) is not None, line


def test_an_assignment_that_names_maity_is_not_skipped_as_one() -> None:
    """Assignments are read past to find the line's command only while they do not count as
    `maity` themselves: a value whose path ends in `/maity` still makes the line prefixed."""
    assert plaincall.prefixed("TZ=/usr/share/zoneinfo/maity maity status")
    assert plaincall.refusal(bash("TZ=/x/maity maity status")) == plaincall.PREFIX_REFUSED


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


# Characters at which the shell does not split words, but another reader of the line may:
# control characters other than a tab and a newline, spaces other than the ASCII one, and
# invisible format characters (Unicode category Cf).
ODD = [
    "\r",
    "\v",
    "\f",
    "\x00",
    "\x1b",
    "\x7f",
    "\x85",
    "\N{NO-BREAK SPACE}",
    "\N{EM SPACE}",
    "\N{IDEOGRAPHIC SPACE}",
    "\N{LINE SEPARATOR}",
    "\N{ZERO WIDTH SPACE}",
    "\N{ZERO WIDTH NO-BREAK SPACE}",
    "\N{MONGOLIAN VOWEL SEPARATOR}",
    "\N{ZERO WIDTH JOINER}",
    "\N{ZERO WIDTH NON-JOINER}",
    "\N{WORD JOINER}",
    "\N{RIGHT-TO-LEFT OVERRIDE}",
    "\N{LEFT-TO-RIGHT ISOLATE}",
    "\N{SOFT HYPHEN}",
]
# Lines where such a character stands where a space would make `maity` a word, or between
# the letters of `maity`: to the shell `maity` is no word of any of them, so the other rules
# leave each of them through.
ODD_SHAPES = [
    "maity{c}resume",
    "maity{c}a ; x",
    "maity{c}a | sh",
    "LANG=C{c}maity a | x",
    "x{c}maity a",
    "ma{c}ity a ; x",
    "git commit -m 'maity{c}x'",
]


@pytest.mark.parametrize("shape", ODD_SHAPES)
@pytest.mark.parametrize("c", ODD)
def test_a_line_naming_maity_with_a_control_character_or_unicode_space_is_refused(
    c: str, shape: str
) -> None:
    command = shape.format(c=c)
    assert plaincall.odd_spacing(command)
    assert plaincall.refusal(bash(command)) == plaincall.SPACING_REFUSED


# Lines with such a character that another rule refused before: each keeps its reason.
ODD_REFUSED_BEFORE = [
    ("maity a{c}b", plaincall.REFUSED),  # `maity` then a space: held, and not plain
    ("maity resume{c}", plaincall.REFUSED),
    ("{c}maity a ; x", plaincall.REFUSED),  # skipped before `maity`, as the harness may trim
    ("{c}TZ=UTC maity a | x", plaincall.PREFIX_REFUSED),
]


@pytest.mark.parametrize(("shape", "reason"), ODD_REFUSED_BEFORE)
@pytest.mark.parametrize("c", ODD)
def test_a_line_refused_before_keeps_its_reason_with_an_odd_character(
    c: str, shape: str, reason: str
) -> None:
    assert plaincall.refusal(bash(shape.format(c=c))) == reason


@pytest.mark.parametrize("c", ODD)
def test_a_line_that_does_not_name_maity_may_hold_an_odd_character(c: str) -> None:
    for command in (f"echo a{c}b", f"printf 'x{c}y'", f"git commit -m 'fix{c}it'"):
        assert not plaincall.odd_spacing(command)
        assert plaincall.refusal(bash(command)) is None


@pytest.mark.parametrize("command", ["maity resume", "maity\tresume", "maityx resume"])
def test_a_line_with_only_ascii_spaces_and_tabs_is_decided_as_before(command: str) -> None:
    assert not plaincall.odd_spacing(command)
    assert plaincall.refusal(bash(command)) is None


# Assignments before `maity` to each name that may stand there: one, several, a quoted value.
ASSIGNMENTS = [
    "NO_COLOR=1",
    "LANG=C.UTF-8",
    "LC_ALL=C",
    "LC_CTYPE=C",
    "TZ=UTC",
    "TZ=UTC LANG=C",
    "TZ='x y'",
    'TZ="x y"',
    "NO_COLOR=1 LANG=C LC_ALL=C TZ=UTC",
]
# Prefixes that assign `MAITY_WAIT_TIMEOUT` (tsk-f5fy2zq26xcy): refused outright like any
# other name, with the reason that names `maity wait --timeout N`.
WAIT_TIMEOUT_PREFIXES = [
    "MAITY_WAIT_TIMEOUT=5",
    "MAITY_WAIT_TIMEOUT=5 TZ=UTC",
    "TZ=UTC MAITY_WAIT_TIMEOUT=5",
    "NO_COLOR=1 LANG=C LC_ALL=C TZ=UTC MAITY_WAIT_TIMEOUT=5",
    "MAITY_WAIT_TIMEOUT=5 MAITY_FOO=1",
    "X=1 MAITY_WAIT_TIMEOUT=5",
    "MAITY_WAIT_TIMEOUT+=5",
    "MAITY_WAIT_TIMEOUT='5'",
]
# Assignments to any other name, and every `+=`.
NOT_ALLOWED = [
    "PATH=.",
    "LD_PRELOAD=x.so",
    "DYLD_INSERT_LIBRARIES=x",
    "PYTHONPATH=.",
    "BASH_ENV=x",
    "ENV=x",
    "IFS=x",
    "HOME=/x",
    "NODE_ENV=1",
    "A=1 B=2",
    "a_b=1",
    "_=1",
    "_1=x",
    "maity_x=1",
    "MAITY_=1",
    "MAITY_FOO=1",
    "MAITY_X_1=1",
    "MAITY_WAIT_TIMEOUTX=5",
    "LANGUAGE=x",
    "TZ=UTC PATH=.",
    "A+=1",
    "_X=1 B+=2",
    "MAITY_X+=1",
    "TZ+=x",
    "tz=UTC",
    "lc_all=C",
    "LC_=x",
]

# The `MAITY_` names maity's code reads or sets that are not documented for agents: the
# runner, its supervisor or the placement sets them, and they decide what maity trusts (the
# placement's rules, the clone's `.git`, git's private repository and the runner's records,
# the state directory and with it the credential, the session's mode at the hub, the
# runner's config, the supervisor's error channel, the scratch). None may stand before
# `maity` (context/runner.md 63492c65).
RUNNER_TRUSTED = (
    "MAITY_PLACEMENT",
    "MAITY_GIT_INODE",
    "MAITY_GIT_DEVICE",
    "MAITY_GIT_PRIVATE",
    "MAITY_STATE_DIR",
    "MAITY_SUPERVISOR",
    "MAITY_RUNNER_CONFIG",
    "MAITY_ERROR_LINE",
    "MAITY_SCRATCH",
    # The test slots and the test cluster in the scratch, the cluster's password (set by the
    # runner's pgenv launcher) and who takes a slot (tsk-w7qtcbzcshn9): read by the repository's
    # test scripts, not by maity.
    "MAITY_RUN_SLOTS_DIR",
    "MAITY_PG_DIR",
    "MAITY_PG_PASSWORD",
    "MAITY_RUN_NAME",
    # Where the runner put the Keep the Why skill for this session (tsk-172s8y208whg), named by
    # `maity resume`: an agent's own value before `maity` would point the resume elsewhere.
    "MAITY_KTW_SKILL_DIR",
)
# The `MAITY_` names documented for agents in docs/agents.md and read by maity. None may stand
# before `maity` either: `MAITY_WAIT_TIMEOUT` was allowed until the S200 re-check showed such a
# line without the credential in a placement; a placed agent passes `maity wait --timeout N`
# (tsk-f5fy2zq26xcy, context/runner.md 63492c65).
AGENT_FACING = ("MAITY_WAIT_TIMEOUT",)
AGENTS_MD = SRC.parent.parent / "docs" / "agents.md"


def code_maity_names() -> set[str]:
    """The `MAITY_` environment names maity's code names: every string literal that starts
    with `MAITY_` and a letter (`"MAITY_STATE_DIR"`, `f"MAITY_SUPERVISOR is ..."`), in every
    module but this hook. Python names such as `MAITY_NOT_PLAIN` or `CLAUDE_MAITY_PROMPT` are
    no string literal, and the bare prefix `"MAITY_"` names no variable."""
    found: set[str] = set()
    for path in (SRC / "maity").rglob("*.py"):
        if path.name != "plaincall.py":
            text = path.read_text(encoding="utf-8")
            found.update(re.findall(r"[\"'](MAITY_[A-Z][A-Z0-9_]*)", text))
    return found


def test_the_scan_finds_every_runner_trusted_name_and_no_unclassified_one() -> None:
    assert code_maity_names() == set(RUNNER_TRUSTED) | set(AGENT_FACING)


def test_no_maity_name_is_on_the_allow_list() -> None:
    names = plaincall.ALLOWED_BEFORE_MAITY
    assert isinstance(names, tuple)
    assert not [n for n in names if n.upper().startswith("MAITY")]
    for name in [*RUNNER_TRUSTED, *AGENT_FACING, *code_maity_names(), "MAITY_FOO", "MAITY_"]:
        assert plaincall._ASSIGNMENT.match(name + "=1") is None, name


def test_every_agent_facing_maity_name_is_read_by_maity_and_documented_for_agents() -> None:
    docs = AGENTS_MD.read_text(encoding="utf-8")
    for name in AGENT_FACING:
        assert name in code_maity_names(), name
        assert re.search(rf"`{name}(=[^`]*)?`", docs), name


@pytest.mark.parametrize("name", RUNNER_TRUSTED)
def test_maity_after_a_runner_trusted_name_is_refused_outright(name: str) -> None:
    assert plaincall.refusal(bash(f"{name}=1 maity status")) == plaincall.PREFIX_REFUSED


@pytest.mark.parametrize("prefix", WAIT_TIMEOUT_PREFIXES)
@pytest.mark.parametrize("rest", ["wait", "wait --one", "status", "a > f"])
def test_a_maity_wait_timeout_prefix_is_refused_with_the_flag_as_the_way_out(
    prefix: str, rest: str
) -> None:
    command = prefix + " maity " + rest
    assert plaincall.prefixed(command)
    assert plaincall.refusal(bash(command)) == plaincall.WAIT_TIMEOUT_REFUSED
    assert "`maity wait --timeout N`" in plaincall.WAIT_TIMEOUT_REFUSED
    assert plaincall.WAIT_TIMEOUT_REFUSED.endswith(plaincall.PREFIX_REFUSED)


# Other refused prefixes: the shared reason, which names no wait timeout and does not list
# `MAITY_WAIT_TIMEOUT` among the allowed names.
OTHER_PREFIXED = [
    "X=1 maity status",
    "nice maity status",
    "X=1 maity wait",
    "env maity wait",
    "MAITY_WAIT_TIMEOUTX=5 maity wait",
    "MAITY_FOO=1 maity wait",
    "TZ=UTC X=1 maity wait --timeout 5",
    "/usr/bin/maity wait",
]


@pytest.mark.parametrize("command", OTHER_PREFIXED)
def test_another_refused_prefix_gets_the_shared_reason_without_the_timeout_hint(
    command: str,
) -> None:
    assert plaincall.refusal(bash(command)) == plaincall.PREFIX_REFUSED
    assert "MAITY_WAIT_TIMEOUT" not in plaincall.PREFIX_REFUSED
    assert "--timeout" not in plaincall.PREFIX_REFUSED


def test_maity_wait_with_its_timeout_flag_passes() -> None:
    assert plaincall.refusal(bash("maity wait --timeout 5")) is None
    assert plaincall.refusal(bash("TZ=UTC maity wait --timeout 5")) is None


@pytest.mark.parametrize("prefix", ASSIGNMENTS)
def test_a_plain_maity_call_after_assignments_passes(prefix: str) -> None:
    assert plaincall.refusal(bash(prefix + " maity status")) is None


@pytest.mark.parametrize("prefix", ASSIGNMENTS)
@pytest.mark.parametrize("rest", ["a > f", "a | x", "a && x", "a $X"])
def test_a_maity_line_after_assignments_that_is_not_one_plain_call_is_refused(
    prefix: str, rest: str
) -> None:
    assert plaincall.refusal(bash(prefix + " maity " + rest)) == plaincall.REFUSED


@pytest.mark.parametrize("prefix", ASSIGNMENTS)
def test_a_maity_line_after_assignments_reaching_runner_is_refused(prefix: str) -> None:
    assert plaincall.refusal(bash(prefix + " maity runner status")) == (plaincall.RUNNER_REFUSED)


@pytest.mark.parametrize("prefix", NOT_ALLOWED)
@pytest.mark.parametrize("rest", ["status", "a > f"])
def test_maity_after_an_assignment_to_another_name_is_refused_outright(
    prefix: str, rest: str
) -> None:
    assert plaincall.refusal(bash(prefix + " maity " + rest)) == plaincall.PREFIX_REFUSED


# Anything else before `maity`: a command word by name or path, listed in an earlier version
# or not, combined with assignments, or a shell keyword.
PREFIXES = [
    "env",
    "env -i A=1",
    "env -u A",
    "/usr/bin/env",
    "ENV",
    "command",
    "exec",
    "builtin",
    "nice -n 5",
    "nohup",
    "timeout 5",
    "time",
    "time -p",
    "stdbuf -oL",
    "sudo",
    "sudo -u x",
    "doas",
    "xargs",
    "setsid",
    "ionice -c 3",
    "taskset 1",
    "chrt 1",
    "eval",
    "TZ=UTC env nice -n 5",
    "sudo env A=1 nohup timeout 5",
    "if",
    "stubwrap",
    "./stubwrap -q",
]


@pytest.mark.parametrize("prefix", PREFIXES)
def test_a_prefixed_maity_line_reaching_runner_is_refused(prefix: str) -> None:
    assert plaincall.refusal(bash(prefix + " maity runner status")) == (plaincall.RUNNER_REFUSED)


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("rest", ["status", "a > f", "a | x", "a && x"])
def test_a_maity_line_after_anything_but_assignments_is_refused(prefix: str, rest: str) -> None:
    assert plaincall.refusal(bash(prefix + " maity " + rest)) == plaincall.PREFIX_REFUSED


@pytest.mark.parametrize("prefix", PREFIXES)
def test_a_prefixed_maity_line_with_an_expanding_word_keeps_the_runner_reason(prefix: str) -> None:
    assert plaincall.refusal(bash(prefix + " maity a $X")) == plaincall.RUNNER_REFUSED


# One line per kind of prefix that is neither assignments nor nothing.
REFUSED_OUTRIGHT = [
    "stubwrap maity status",  # a command word nobody listed
    "eval maity status",
    "xargs maity status",
    "source maity status",
    ". maity status",
    ": maity status",
    ">out maity status",  # a leading redirection
    "<in maity status",
    "2>&1 maity status",  # a leading fd duplication
    "if maity status",
    "then maity status",
    "do maity status",
    "coproc maity status",
    "! TZ=UTC maity status",
    "( true ; maity status )",  # a subshell
    "{ true; maity status; }",  # a group
    "/usr/local/bin/maity status",  # `maity` by a path
    "./maity status",
    "~/bin/maity status",
    "TZ=UTC /usr/local/bin/maity status",
    "-maity status",
    "'TZ=UTC' maity status",  # a quoted name is a command word, not an assignment
    '"TZ"=UTC maity status',
    "TZ\\=UTC maity status",
    "\ufeffTZ=UTC maity status",
]


@pytest.mark.parametrize("command", REFUSED_OUTRIGHT)
def test_maity_after_anything_but_assignments_is_refused_outright(command: str) -> None:
    assert plaincall.refusal(bash(command)) == plaincall.PREFIX_REFUSED


# Security round 5, S183/S203: the hook decides on the line's command as the shell runs it. A
# single `maity` call behind a wrapper command, known or not, by name or path, with or without
# its options, is refused outright; only the allowed assignments may stand before `maity`.
S203_WRAPPERS = [
    "nice",
    "nice -n 19",
    "NICE",
    "/usr/bin/nice",
    "timeout 60",
    "timeout -s KILL 60",
    "timeout --foreground 1m",
    "env",
    "env TZ=UTC",
    "env -- X=1",
    "nohup",
    "nohup nice",
    "command",
    "command -p",
    "exec",
    "exec -a x",
    "time",
    "stdbuf -i0 -o0",
    "ionice -c3",
    "chrt -i 0",
    "taskset -c 0",
    "setsid -w",
    "sudo",
    "doas -u x",
    "xargs",
    "xargs -0",
    "busybox",
    "unbuffer",
    "frobnicate",
    "TZ=UTC nice",
    "NO_COLOR=1 env",
]
# The allowed names, as in #1942 less `MAITY_WAIT_TIMEOUT` (tsk-f5fy2zq26xcy): a single plain
# call after them passes, held to one plain call.
S183_ALLOWED_SINGLE = [
    "TZ=1 maity status",
    "TZ=UTC maity status",
    "NO_COLOR=1 maity status",
    "LANG=C maity status",
    "LC_ALL=C maity status",
    "TZ=UTC LANG=C.UTF-8 NO_COLOR=1 maity status",
]


@pytest.mark.parametrize("wrapper", S203_WRAPPERS)
def test_s203_a_single_maity_call_behind_a_wrapper_is_refused_outright(wrapper: str) -> None:
    assert plaincall.prefixed(wrapper + " maity status")
    assert plaincall.refusal(bash(wrapper + " maity status")) == plaincall.PREFIX_REFUSED
    assert plaincall.refusal(bash(wrapper + " maity runner status")) == plaincall.RUNNER_REFUSED


@pytest.mark.parametrize("wrapper", S203_WRAPPERS)
def test_s203_a_wrapped_maity_call_after_comment_lines_is_refused(wrapper: str) -> None:
    assert plaincall.refusal(bash("# a note\n" + wrapper + " maity status")) is not None


@pytest.mark.parametrize("command", S183_ALLOWED_SINGLE)
def test_s183_a_single_call_after_allowed_assignments_is_held_to_one_plain_call(
    command: str,
) -> None:
    assert plaincall.held(command)
    assert plaincall.refusal(bash(command)) is None
    assert plaincall.refusal(bash(command + " && maity status")) == plaincall.REFUSED
    assert plaincall.refusal(bash(command + " > out.txt")) == plaincall.REFUSED
    runner = command.replace(" maity ", " maity runner ", 1)
    assert plaincall.refusal(bash(runner)) == plaincall.RUNNER_REFUSED


# `maity` in a backtick command substitution (tsk-12zb1s0zgdjw): the shell reads the text
# between the backticks as a line of its own, so `maity` is a word there however the word
# around it goes on. Refused outright, like `maity` after any other command.
IN_BACKTICKS = [
    "`maity`",
    "echo `maity`",
    "`PYTHONPATH=. maity`",
    "`LD_PRELOAD=./x.so maity`",
    "`MAITY_STATE_DIR=/x maity`",
    "`MAITY_WAIT_TIMEOUT=5 maity`",
    "`env maity`",
    "`nice maity`",
    "`/usr/bin/maity`",
    '"`maity`"',
    "`MAITY`",
    "`Maity`",
    "$(echo `maity`)",
    "true; `maity`",
    "true && `maity`",
    "true | `maity`",
    "true || `maity`",
    "`maity`x",
    "x`maity`",
    "x=`maity`",
    "`maity``maity`",
    "` maity`",
    "`\tmaity`",
    '"`/usr/bin/maity`"',
    "'`maity`'",
    'echo "a`maity`b"',
    "`./maity`",
    "`~/.local/bin/maity`",
    "`$HOME/.local/bin/maity`",
    "`! maity`",
    "`exec maity`",
    "`command maity`",
    "[[ `maity` ]]",
    "for i in `maity`; do :; done",
    "`maity`>/dev/null",
]
# The same in other forms, or with other constructs on the line: each is refused, for one
# reason or another.
SUBSTITUTED_ELSEWHERE = [
    "$(maity)",
    '"$(maity)"',
    "$(PYTHONPATH=. maity)",
    "$(/usr/bin/maity)",
    "$(env maity)",
    "$( maity )",
    "x$(maity)y",
    "<(maity)",
    ">(maity)",
    "cat <(maity)",
    "`maity -h`",
    "echo `maity status`",
    '`"maity"`',
    "`ma\\ity`",
    "`\\maity`",
    "`ma''ity`",
    "`echo $(maity)`",
    "`maity `",
    "`maity;`",
    "`(maity)`",
    "echo ${x:-`maity`}",
    "echo ${x:-$(maity)}",
    "case `maity` in *) ;; esac",
    "`maity`#",
]
# Backtick substitutions that do not run `maity`: left to the permission rules as before.
NOT_IN_BACKTICKS = [
    "echo `date`",
    "ls `pwd`",
    "x=`git rev-parse HEAD`",
    'echo "`date` done"',
    "echo `cat maity.txt`",
    "echo `maityx`",
]


@pytest.mark.parametrize("command", IN_BACKTICKS)
def test_maity_in_a_backtick_substitution_is_refused_outright(command: str) -> None:
    assert plaincall._placement(command) is not None
    assert plaincall.refusal(bash(command)) in (plaincall.PREFIX_REFUSED, plaincall.REFUSED)


@pytest.mark.parametrize("command", SUBSTITUTED_ELSEWHERE)
def test_maity_in_any_other_substitution_form_is_refused(command: str) -> None:
    assert plaincall.refusal(bash(command)) is not None


@pytest.mark.parametrize("command", NOT_IN_BACKTICKS)
def test_backtick_substitutions_without_maity_are_left_to_the_permission_rules(
    command: str,
) -> None:
    assert plaincall.refusal(bash(command)) is None


def test_a_word_names_maity_or_runner_between_its_backticks() -> None:
    assert plaincall._is_maity("`maity`", "`maity`")
    assert plaincall._is_maity("x=`/usr/bin/MAITY`y", "x=`/usr/bin/MAITY`y")
    assert not plaincall._is_maity("`maityx`", "`maityx`")
    assert plaincall._is_runner("`runner`", "`runner`")


# `maity` glued to an expansion right after it, which may make nothing (round 1 of #2026):
# the line starts with `maity`, so it is held to one plain call; or `maity` stands in a
# substitution's text.
GLUED_EXPANSIONS = [
    "maity$(true) status",
    "maity$( ) status",
    'maity"$(true)" status',
    "maity$x status",
    "maity${x} status",
    "maity${x:-} status",
    "maity$@ status",
    "maity${IFS}status",
    "maity`true` status",
    "maity$() run$()ner",
    "NO_COLOR=1 maity$(true) status",
    "TZ=UTC maity$x status",
    "true && maity$(true) status",
    "echo `maity$x`",
    "echo $(maity$x)",
    "echo `maity$() status`",
]
# A backtick substitution in double quotes whose words name `maity` once their braces expand.
BRACES_IN_QUOTED_BACKTICKS = [
    'echo "`{maity,} status`"',
    '"`{maity,} status`"',
    'echo "`ma{ity,} status`"',
    'echo "`ma{i..i}ty status`"',
    'echo "`./{maity,} status`"',
    'echo "`true``{maity,} status`"',
    'echo "`' + "{a,b}" * 9 + ' status`"',
    'echo "`{Z..a} status`"',
    'echo "`ma{i..i}ty' + "{a..a}" * 257 + ' status`"',
]
# A line that names `maity` with substitutions the hook does not read to the end: a `case`
# statement, whose pattern ends with a `)`, or nesting past `_NESTING`.
UNREAD_SUBSTITUTIONS = [
    'echo "$(case x in x) echo " \'"; x=`maity`; echo "\' ";; esac)"',
    "cat $(case x in x) echo y;; esac) maity.md",
    'echo "$(case $1 in a) echo;; esac)" maity.md',
    "cat $(echo $(echo $(echo $(echo $(echo x))))) maity.md",
    'echo "$(echo "$(echo "$(echo "$(echo "$(echo x)")")")")" maity.md',
]
# Substitutions and expansions in lines that do not name `maity`: left as before.
SUBSTITUTIONS_WITHOUT_MAITY = [
    'echo "$(date)"',
    "x=$(git rev-parse HEAD)",
    "echo `date`",
    "echo $HOME",
    'echo "${HOME}/x"',
    "echo $(( 1 + 2 ))",
    "diff <(sort a) <(sort b)",
    "echo file-$(date).log",
    'tar czf "backup-$(date +%F).tgz" src',
    "echo $# $@ $1",
    'printf "%s\\n" "$@"',
    "echo $(basename $(pwd))",
    "cp a.txt b-`date +%s`.txt",
    'git commit -m"$(cat msg.txt)"',
    "git commit -m \"$(cat <<'EOF'\nFix the thing\nEOF\n)\"",
    "gh pr create --title x --body \"$(cat <<'EOF'\nBody text\nEOF\n)\"",
    "echo a$(date) t`date`",
    "echo ma$(true)ty",
    "echo $(date)$(hostname)",
    "x=$(date)$(hostname)",
    "cat $(cat a)$(cat b)",
    "cp $(pwd)/$(basename f) x",
    'echo "$(whoami)@$(hostname)"',
    "echo v$(cat VERSION)-$(git rev-parse --short HEAD)",
    "echo $(echo $(echo $(echo $(echo $(echo x)))))",
    'echo "$(case x in x) echo y;; esac)"',
    "ls # see $(x)",
    "cat <<'EOF'\n$(not run) `nor this`\nEOF",
]
# The ordinary agent commands of a review of #2026 (round 1): each is left to the
# permission rules, as on main.
REVIEWED_ORDINARY = [
    'git commit -m "$(cat f)"',
    "cp $(pwd)/x dest",
    "echo v$(cat VERSION)-$(git rev-parse --short HEAD)",
    "echo file-$(date).log",
    'echo "$(whoami)@$(hostname)"',
    "python3 $(git rev-parse --show-toplevel)/main.py",
    "touch my-$(date).txt",
    "touch summary-$(date).md",
    "git tag main-$(git rev-parse --short HEAD)",
    "$(pwd)/my_script.sh",
    '$(dirname "$0")/run.sh',
    'cat "$1"/main.py',
    'echo "my $(date)"',
    'pytest -k "$(cat filter)"',
    'curl -H "X: $(cat t)" https://example.com',
    "tar czf backup-$(date +%Y%m%d).tar.gz .",
    "tail -f $(pwd)/activity.log",
    "mkdir -p m$(date +%m)",
    "touch m$(date +%Y%m%d)",
    "echo y$(date +%Y)",
    "sleep $(cat delay)m",
    "timeout $(cat secs)m pytest",
    "echo $(cat count)m",
    "echo $(date +%Y)y",
    "echo my$(date +%Y)",
    "touch my$(date +%Y%m%d)",
    "echo at$(date +%H%M)",
    "echo it$(cat id)",
    "echo ai$(cat ver)",
    "echo ma$(cat id)",
    "echo mi$(cat id)",
    "echo mt$(cat id)",
    "echo ty$(cat id)",
    "echo $(cat prefix)my",
    "echo $(cat prefix)at",
    "echo $(cat prefix)it",
    "echo $(cat prefix)ty",
    "echo $(cat prefix)y",
    "echo $(cat prefix)m",
    "echo $(cat prefix)mat",
    "echo $(cat prefix)may",
    "echo $(cat prefix)mit",
    'echo "$(git log -1 --format=%at)$(git rev-parse --short HEAD)"',
    "echo $(git log -1 --format=%at)-$(git rev-parse --short HEAD)",
    "echo $(git log -1 --format=%at)$(git log -1 --format=%h)",
    "echo $(cat my_a)$(cat my_b)",
    "echo $(cat my.txt)$(cat other.txt)",
    "echo $(cat it_1)$(cat it_2)",
    "echo $(cat ai_prompt)$(cat suffix)",
    "echo $(ls -at)$(echo x)",
    "echo $(docker exec -it c cmd)$(cat f)",
    "echo $(cat a)$(cat b)",
    'echo "$(date +%Y%m%d)$(date +%H%M%S)"',
    'echo "$(whoami)$(hostname)"',
    'echo "$(uname -m)$(uname -s)"',
    'echo "$(git branch --show-current)-$(git rev-parse --short HEAD)"',
    'git commit -m"$(cat msg.txt)"',
    "M=$(cat f)",
    "Y=$(date +%Y)",
    "MY=$(cat f)",
    "AT=$(date +%s)",
    "IT=$(cat id)",
    'export MY="$(cat f)"',
    "echo $MY",
    'echo "${MY}/file"',
    'git log -1 --format="%h %s" $(git rev-parse HEAD)',
    "diff -u <(git show HEAD:a.py) <(git show HEAD~1:a.py)",
    'python3 -m pytest -k "$(cat tests.txt)"',
    "gh pr view $(cat pr_num)",
    "git checkout -b fix/$(cat branch_name)",
    "git show $(git merge-base main HEAD):README.md",
    "jq -r .version package.json",
    'echo "tag: v$(cat VERSION)"',
    'echo "built at $(date -u +%FT%TZ)"',
    'echo "$(git rev-parse --show-toplevel)/cli/src"',
    "ls $(git rev-parse --show-toplevel)/tests",
    'wc -l $(git ls-files "*.py")',
    "grep -rn foo $(git rev-parse --show-toplevel)/src",
    'cp "$(mktemp)" /tmp/out.txt',
    'echo "$(dirname "$(pwd)")"',
    'echo "$(basename "$(pwd)")"',
    "echo $(realpath .)/foo",
    'echo $(python3 -c "print(1)")',
    'echo "count=$(wc -l < file.txt)"',
    'echo "sha=$(sha256sum file.txt | cut -d" " -f1)"',
    'git log --since="$(date -d "1 day ago" +%F)"',
    "echo $(date +%Y)/$(date +%m)/$(date +%d)",
    "echo $(date +%Y)/m$(date +%m)",
    "echo /tmp/m$(date +%s)",
    "echo /tmp/my$(date +%s)",
    "echo /tmp/at$(date +%s)",
    "echo /tmp/$(cat id)y",
    "echo /tmp/$(cat id)m",
    "touch /tmp/run$(date +%s)",
    "touch /tmp/tmp$(date +%s)",
    "touch /tmp/a$(date +%s)",
    "touch /tmp/i$(date +%s)",
    "touch /tmp/t$(date +%s)",
    "echo a$(date +%s) i$(date +%s) t$(date +%s)",
    "echo $(cat a) $(cat b)",
    'echo "a: $(cat a), b: $(cat b)"',
    'printf "%s\\n" "$(cat a)" "$(cat b)"',
    "echo $(git status -s)",
    "echo $(uname -a)",
    "echo $(id -u)",
    "echo $(nproc)",
    "make -j$(nproc)",
    "make -j $(nproc)",
    "pytest -n$(nproc)",
    "tar -czf /tmp/out-$(date +%s).tgz .",
    "docker build -t app:$(git rev-parse --short HEAD) .",
    'curl -s "https://api.example.com/v1/items?ts=$(date +%s)"',
    'echo "https://example.com/$(cat slug)"',
    'echo "prefix_$(date +%Y%m%d)_suffix"',
    'echo "m_$(date +%Y%m%d)"',
    'echo "my_$(date +%Y%m%d)"',
    'echo "at_$(date +%Y%m%d)"',
    'echo "y_$(date +%Y%m%d)"',
    "cat $(which python3)",
    "ls -la $(dirname $(which python3))",
    "echo $(cat a.json)$(cat b.json)",
    "echo $(jq -r .a f.json)$(jq -r .b f.json)",
    "echo $(jq -r .id f.json)$(jq -r .my f.json)",
    "echo $(jq -r .at f.json)$(jq -r .id f.json)",
    'echo $(python3 -c "print(1)")$(python3 -c "print(2)")',
    "echo $(date +%s)ms",
    "echo $(cat n)MB",
    "echo $(cat n)M",
    "echo $(cat n)k",
    "echo $(cat n)G",
    "dd if=/dev/zero of=/tmp/f bs=1M count=$(cat n)",
    "head -c $(cat n)M file.bin",
    "head -c $(cat n)m file.bin",
    "echo $(cat val)mi",
    "echo $(cat val)mt",
    "echo $(cat val)ai",
    "echo $(cat val)ay",
    "echo $(cat val)may",
    "echo $(cat val)mat",
    "echo $(cat val)mit",
    'echo "$1" "$2" "$@" "$*" "$#"',
    'echo "args: $1 $2"',
    'echo "${1}/foo"',
    'echo "${1}-bar"',
    'for f in $(git diff --name-only); do echo "$f"; done',
    "xargs -I{} echo {} < list.txt",
    'echo "my-app-$(git describe --tags)"',
    'echo "summary-$(date +%F).md"',
    'echo "main-$(git rev-parse --short HEAD)"',
    'echo "$(pwd)/main.py"',
    'echo "$(pwd)/my_app/main.py"',
]
# The shapes of the false refusals that review found, each left to the permission rules.
REVIEWED_SHAPES = [
    "sleep $(cat delay)m",
    "timeout $(cat secs)m pytest",
    "head -c $(cat n)M file.bin",
    "head -c $(cat n)m file.bin",
    "echo $(cat n)M",
    "mkdir -p m$(date +%m)",
    "touch m$(date +%Y%m%d)",
    "touch my$(date +%Y%m%d)",
    "echo y$(date +%Y)",
    "echo at$(date +%H%M)",
    "echo it$(cat id)",
    "echo /tmp/m$(date +%s)",
    "echo /tmp/my$(date +%s)",
    'echo "$(git log -1 --format=%at)$(git rev-parse --short HEAD)"',
    "echo $(git log -1 --format=%at)$(git log -1 --format=%h)",
    "echo $(cat my_a)$(cat my_b)",
    "echo $(cat my.txt)$(cat other.txt)",
    "echo $(cat it_1)$(cat it_2)",
    "echo $(cat ai_prompt)$(cat suffix)",
    "echo $(ls -at)$(echo x)",
    "echo $(docker exec -it c cmd)$(cat f)",
    "echo $(jq -r .id f.json)$(jq -r .my f.json)",
    "echo $(jq -r .at f.json)$(jq -r .id f.json)",
]


@pytest.mark.parametrize("command", [*GLUED_EXPANSIONS, *BRACES_IN_QUOTED_BACKTICKS])
def test_maity_glued_to_an_expansion_or_braced_in_a_substitution_is_refused(command: str) -> None:
    assert plaincall.refusal(bash(command)) is not None


@pytest.mark.parametrize("command", UNREAD_SUBSTITUTIONS)
def test_a_line_naming_maity_with_substitutions_not_read_to_the_end_is_refused(
    command: str,
) -> None:
    assert plaincall.refusal(bash(command)) is not None


@pytest.mark.parametrize(
    "command", [*SUBSTITUTIONS_WITHOUT_MAITY, *REVIEWED_ORDINARY, *REVIEWED_SHAPES]
)
def test_substitutions_in_lines_without_maity_are_left_to_the_permission_rules(
    command: str,
) -> None:
    assert plaincall.refusal(bash(command)) is None


def test_the_substitutions_of_a_line_and_the_line_without_them() -> None:
    assert plaincall._substitutions(r"""a `b` "$(c "d)")" <(e) '$(g)'""") == (
        ["b", 'c "d)"', "e"],
        """a  "" /dev/fd/0 '$(g)'""",
    )
    assert plaincall._substitutions("a # `b` '\nc $(d)") == (["d"], "a # `b` '\nc ")
    assert plaincall._substitutions("cat <<'E'\n`x` $(y) '\nE\nz `w`") == (
        ["w"],
        "cat <<'E'\n\nz ",
    )
    assert plaincall._substitutions("a `b") is None
    assert plaincall._substitutions("a $(b") is None
    assert plaincall._substitutions('a "b') is None


def test_a_wait_timeout_inside_a_substitution_gets_the_reason_of_the_words_as_split() -> None:
    assert plaincall.refusal(bash("`MAITY_WAIT_TIMEOUT=5 maity`")) == plaincall.PREFIX_REFUSED
    assert plaincall.refusal(bash("$(MAITY_WAIT_TIMEOUT=5 maity)")) == (
        plaincall.WAIT_TIMEOUT_REFUSED
    )


# A `!`, a subshell or a group right before `maity`: the line counts as starting with `maity`
# (a leading character a plain call may not hold is skipped) and is not one plain call.
NOT_PLAIN_BEFORE_MAITY = ["! maity status", "!maity status", "(maity status)", "{ maity status; }"]


@pytest.mark.parametrize("command", NOT_PLAIN_BEFORE_MAITY)
def test_a_bang_subshell_or_group_right_before_maity_is_refused(command: str) -> None:
    assert plaincall.refusal(bash(command)) == plaincall.REFUSED


# A command that takes the line it runs from an option, or reads its arguments from elsewhere.
WITH_OPTIONS = [
    "env -S 'maity status | x'",
    "sudo -s 'maity status | x'",
    "xargs -a list maity",
    "time -o out maity status",
]


@pytest.mark.parametrize("command", WITH_OPTIONS)
def test_maity_after_a_command_with_options_is_refused_outright(command: str) -> None:
    assert plaincall.refusal(bash(command)) == plaincall.PREFIX_REFUSED


# `maity` as a word of another command's arguments, quoted or not, or in quoted text: refused,
# and the reason names `--body-file`.
MENTIONS = [
    "env maity status",
    "sudo maity status",
    "git log --grep maity | head",
    "echo maity | cat",
    "echo maity > f",
    "echo 'maity' | cat",
    "git commit -m 'fix maity docs'",
    'git commit -m "a; maity"',
]


@pytest.mark.parametrize("command", MENTIONS)
def test_text_that_mentions_maity_as_a_word_is_refused_with_the_file_way_out(
    command: str,
) -> None:
    reason = plaincall.refusal(bash(command))
    assert reason == plaincall.PREFIX_REFUSED
    assert "--body-file" in reason


# Not `maity` as a word: left to the permission rules.
NOT_A_WORD = [
    "cat maity.md",
    "ls maity/",
    "git log --author maity-coder",
    "git commit -m 'fixmaity'",
]


@pytest.mark.parametrize("command", NOT_A_WORD)
def test_maity_inside_a_longer_word_is_not_decided(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


# A path counts as `maity` in any position only when its last component is `maity`: a clone
# directory named after a handle is no `maity` word.
PATH_ENDS_IN_OTHER_NAME = [
    "cd /some/path/maity-coder-claude-004 && make",
    "cd /some/path/maity-coder-claude-004-2 && make",
]


@pytest.mark.parametrize("command", PATH_ENDS_IN_OTHER_NAME)
def test_a_path_whose_last_component_is_longer_than_maity_is_not_decided(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


@pytest.mark.parametrize("command", ["cd /some/path/maity && make", "cd /some/path/MAITY && make"])
def test_a_path_ending_in_maity_counts_as_maity_after_another_command(command: str) -> None:
    assert plaincall.refusal(bash(command)) == plaincall.PREFIX_REFUSED


# A quoted `maity` or one with a backslash, after assignments.
DECIDED = [
    "TZ=UTC m'ai'ty a | x",
    "TZ=UTC mai\\ty a | x",
]


@pytest.mark.parametrize("command", DECIDED)
def test_other_spellings_of_a_maity_line_are_decided(command: str) -> None:
    assert plaincall.refusal(bash(command)) == plaincall.REFUSED


# Lines held to a plain call in an earlier version, refused outright now.
NOW_OUTRIGHT = [
    "/usr/local/bin/maity a | x",
    "! TZ=UTC maity a | x",
    "\ufeffTZ=UTC maity a | x",
]


@pytest.mark.parametrize("command", NOW_OUTRIGHT)
def test_a_path_a_bang_or_a_trimmed_character_before_maity_is_refused_outright(
    command: str,
) -> None:
    assert plaincall.refusal(bash(command)) == plaincall.PREFIX_REFUSED


def test_a_runner_call_after_a_prefix_keeps_the_runner_reason() -> None:
    assert plaincall.refusal(bash("! TZ=UTC maity runner status")) == plaincall.RUNNER_REFUSED


def test_an_unreadable_line_is_decided_only_when_it_names_maity() -> None:
    assert plaincall.held("TZ=UTC maity a 'x")
    assert not plaincall.held("TZ=UTC git a 'x")
    assert not plaincall.prefixed("TZ=UTC git a 'x")


# Words spelled with backslashes or quotes inside them, after another command.
SPELLED = [
    ("eval ma\\\\ity runner status", plaincall.RUNNER_REFUSED),
    ("eval ma\\'\\'ity runner status", plaincall.RUNNER_REFUSED),
    ("eval ma\\\\ity --version | cat", plaincall.RUNNER_REFUSED),
    ("eval $'ma\\x69ty runner status'", plaincall.RUNNER_REFUSED),
    ("eval ma\\\\ity status", plaincall.RUNNER_REFUSED),
    ("eval 'ma\\ity' status", plaincall.RUNNER_REFUSED),
    ("eval 'm\"a\"ity' status", plaincall.RUNNER_REFUSED),
    ("eval ma\\$\\'i\\'ty status", plaincall.RUNNER_REFUSED),
    ("eval ma\\$\\'\\\\x69\\'ty status", plaincall.RUNNER_REFUSED),
    ("eval $'ma\\x69ty' status", plaincall.RUNNER_REFUSED),
    ("sh -c $'ma\\x69ty status'", plaincall.RUNNER_REFUSED),
    ("eval maity r\\\\unner status", plaincall.RUNNER_REFUSED),
    ("eval maity \"r''unner\" status", plaincall.RUNNER_REFUSED),
]


@pytest.mark.parametrize(("command", "reason"), SPELLED)
def test_a_word_spelled_with_backslashes_or_quotes_counts_as_that_word(
    command: str, reason: str
) -> None:
    assert plaincall.refusal(bash(command)) == reason


# Spelled that way, still inside a longer word.
SPELLED_LONGER = ["cat ma\\\\ity.md", "ls 'ma\\ity'/", "git log --author m\\'\\'aity-coder"]


@pytest.mark.parametrize("command", SPELLED_LONGER)
def test_a_longer_word_spelled_with_backslashes_or_quotes_is_not_decided(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


# Words that hold literal brace alternatives: the shell makes a word of each alternative.
BRACE_ALTERNATIVES = [
    "{maity,runner} status",
    "{maity,runner,status}",
    "{maity,} {runner,} status",
    '{"maity",runner} status',
    "eval {maity,runner} status",
    "TZ=UTC {maity,runner} status",
    "[m]aity {runner,} status",
]


@pytest.mark.parametrize("command", BRACE_ALTERNATIVES)
def test_each_brace_alternative_counts_as_a_word_of_its_own(command: str) -> None:
    assert plaincall.calls_runner(command)
    assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED


@pytest.mark.parametrize("command", ["echo {maity,x}", "echo {,x}maity", "{MAITY,} status"])
def test_a_brace_alternative_maity_is_a_maity_word(command: str) -> None:
    assert plaincall.prefixed(command)
    assert plaincall.refusal(bash(command)) == plaincall.PREFIX_REFUSED


BRACES_WITHOUT_BOTH = [
    "echo {a,b}",
    "find . -exec ls {} \\;",
    "git log @{u}",
    "gh issue list --label bug,maity",
    "gh issue list --label maity,runner",
    "maity wait",
]


@pytest.mark.parametrize("command", BRACES_WITHOUT_BOTH)
def test_braces_and_commas_without_both_alternatives_are_not_refused(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


BRACES_JOINED = [
    "{mait,--for=}y {--for=,runne}r status",
    "{mait,--f=}y {--f=,runne}r status",
    "eval {mait,--for=}y {--for=,runne}r status",
    "ma{ity,} run{ner,} status",
    "{ma{ity,},runner} status",
    "{m,-}aity {r,-}unner status",
    "{l..m}aity {r..r}unner status",
    "{m,x}{a,x}ity {r,x}{u,x}nner status",
    "{m..m..+1}aity {r..r..+1}unner status",
]


@pytest.mark.parametrize("command", BRACES_JOINED)
def test_a_brace_expansion_joined_with_its_word_counts_as_each_word_it_makes(
    command: str,
) -> None:
    assert plaincall.prefixed(command)
    assert plaincall.calls_runner(command)
    assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED


EXPANSIONS = [
    ("{mait,--for=}y", ["maity", "--for=y"]),
    ("{ma{ity,},runner}", ["maity", "ma", "runner"]),
    ("a{b,c}{d,e}", ["abd", "abe", "acd", "ace"]),
    ("{x{a,b}}", ["{xa}", "{xb}"]),
    ("{a{b,c}d}", ["{abd}", "{acd}"]),
    ("x{}y{a,b}", ["x{}ya", "x{}yb"]),
    ("{a,{b}", ["{a,{b}"]),
    ("{,}", []),
    ("a{,}", ["a", "a"]),
    ("{a..e..2}", ["a", "c", "e"]),
    ("{a..e..+2}", ["a", "c", "e"]),
    ("{c..a}", ["c", "b", "a"]),
    ("{a..c..0}", ["a", "b", "c"]),
    ("{V..a..6}", ["V", ""]),
    ("{W..a..5}", ["W", "", "a"]),
    ("{Y..^}", ["{Y..^}"]),
    ("{Z..a}", None),
    ("{a..}", ["{a..}"]),
    ("{1..3}", ["1"]),
    ("{01..3..2}", ["01"]),
    ("@{u}", ["@{u}"]),
    ("{}", ["{}"]),
    ("{},mait}y", ["{},mait}y"]),
    ("x{},mait}y", ["x}y", "xmaity"]),
    ("{X=},mait}y", ["X=}y", "maity"]),
    ("{a}b,c}", ["a}b", "c"]),
    ("{a..bb},mait}y", ["{a..bb},mait}y"]),
    ("{a..b{c,d}}", ["a..bc", "a..bd"]),
    ("x{a,b}{},c}y", ["xa{},c}y", "xb{},c}y"]),
    ("{a:1}", ["{a:1}"]),
]


@pytest.mark.parametrize(("word", "words"), EXPANSIONS)
def test_a_word_expands_as_bash_expands_its_braces(word: str, words: list[str] | None) -> None:
    assert plaincall._brace_words(word, bash=(5, 2)) == words


# Where Bash 5.3 reads braces otherwise (`braces.c` of 5.3): a `..` after the first `,` does
# not count, and a group with a `..` opens only when its text starts like a range.
BASH_5_3_EXPANSIONS = [
    ("{a..b{c,d}}", ["{a..bc}", "{a..bd}"]),
    ("{ab..c{d,e}}", ["{ab..cd}", "{ab..ce}"]),
    ("{a..e}", ["a", "b", "c", "d", "e"]),
    ('{a..","}y', ["{a..,}y"]),
    ("{X=},mait}y", ["X=}y", "maity"]),
    ("{a,b..c}", ["a", "b..c"]),
]


@pytest.mark.parametrize(("word", "words"), BASH_5_3_EXPANSIONS)
def test_a_word_expands_as_bash_5_3_expands_its_braces(word: str, words: list[str]) -> None:
    assert plaincall._brace_words(word, bash=(5, 3)) == words


def test_a_range_only_bash_5_3_expands_into_a_backtick_is_not_read() -> None:
    word = "{a..b{Z..a}}"
    assert plaincall._brace_words(word, bash=(5, 2)) == [word]
    assert plaincall._brace_words(word) is None
    assert plaincall.refusal(bash("echo " + word)) == plaincall.RUNNER_REFUSED


def test_the_hook_reads_the_words_of_both_versions() -> None:
    both = plaincall._brace_words("{a..b{c,d}}")
    assert both == ["a..bc", "a..bd", "{a..bc}", "{a..bd}"]


NUMBER_EXPANSIONS = [
    ("{1..3}", ["1", "2", "3"]),
    ("{01..3}", ["01", "02", "03"]),
    ("{-01..2}", ["-01", "000", "001", "002"]),
    ("{1..5..-2}", ["1", "3", "5"]),
    ("{5..1..2}", ["5", "3", "1"]),
    ("x{1..3000000000}y", ["x{1..3000000000}y"]),
    ("{1..300}", None),
]


@pytest.mark.parametrize(("word", "words"), NUMBER_EXPANSIONS)
def test_a_number_range_makes_each_number_when_asked(word: str, words: list[str] | None) -> None:
    assert plaincall._expand(word, numbers=True) == words


# A `}` before any `,` or `..` of its group is text, and the group goes on to a later `}`.
BRACES_CLOSED_LATER = [
    "env {X=},mait}y {--for=},runne}r status",
    "env -u MAITY_PLACEMENT {X=},mait}y {--for=},runne}r status",
    "m{},a}ity {--for=},runne}r status",
]


@pytest.mark.parametrize("command", BRACES_CLOSED_LATER)
def test_a_group_closed_by_a_later_brace_counts_as_each_word_it_makes(command: str) -> None:
    assert plaincall.prefixed(command)
    assert plaincall.calls_runner(command)
    assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED


# A range of letters may make a `\`, which the shell then takes off.
RANGES_OVER_A_BACKSLASH = [
    "env -u m{V..a..6}aity --for r{V..a..6}unner status",
    "env -u m{W..a..5}aity --for r{W..a..5}unner status",
]


@pytest.mark.parametrize("command", RANGES_OVER_A_BACKSLASH)
def test_a_range_over_a_backslash_counts_as_the_words_the_shell_makes(command: str) -> None:
    assert plaincall.prefixed(command)
    assert plaincall.calls_runner(command)
    assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED


def test_a_range_that_makes_a_backtick_refuses_the_line() -> None:
    assert plaincall.refusal(bash("echo {Z..a}")) == plaincall.RUNNER_REFUSED


BRACES_THAT_PASS = [
    "git log @{u}",
    "find . -exec ls {} \\;",
    "echo {a,b}",
    "pytest tests/test_{a,b}.py",
    "curl -d '{\"a\":1}' https://example.org",
    "echo {}",
    "echo {a}b",
    "for i in {1..1000}; do echo $i; done",
    "cat cli/src/{maity,x}.py",
    "echo x{,maity}",
]


@pytest.mark.parametrize("command", BRACES_THAT_PASS)
def test_common_brace_forms_are_not_refused(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


# Quoted programs whose braces hold quoted commas.
QUOTED_PROGRAMS = [
    "awk 'BEGIN {FS=\",\"} {print $1}' f",
    "jq -r '.items[] | {\"a,b\": .x}' d.json",
    "python3 -c 'import json; x={\"a,b\":1}; print(x)'",
]


@pytest.mark.parametrize("command", QUOTED_PROGRAMS)
def test_quoted_programs_with_braces_are_not_refused(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


BRACES_BELOW_THE_LIMIT = [
    "echo {a..z} {1..1000}",
    "echo {x{a,b}}",
    "echo " + "{a,b}" * 8,
    "echo " + "{a..a}" * 256,
]


@pytest.mark.parametrize(
    "command", BRACES_BELOW_THE_LIMIT, ids=["ranges", "nested", "256 words", "256 groups"]
)
def test_brace_expansions_without_both_words_are_not_refused(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


def test_a_word_at_the_brace_limit_is_judged_by_the_words_it_makes() -> None:
    word = "{a,b}" * 7 + "/{mait,x}y"
    assert len(plaincall._expand(word) or []) == plaincall.BRACE_LIMIT == 256
    assert plaincall.refusal(bash(word + " {r,x}unner status")) == plaincall.RUNNER_REFUSED
    assert plaincall.refusal(bash(word + " status")) == plaincall.PREFIX_REFUSED
    assert plaincall.refusal(bash("echo " + "{a,b}" * 7 + "/{x,y}z")) is None


BRACES_OVER_THE_LIMIT = [
    "echo {x," + "{a,b}" * 8 + "}",
    "echo " + "{a,b}" * 9,
    "echo " + "{a,b}" * 64,
    "echo " + "{a..a}" * 257,
    "echo '" + "{a,b}" * 9 + "'",
]


@pytest.mark.parametrize(
    "command",
    BRACES_OVER_THE_LIMIT,
    ids=["257 words", "512 words", "2**64 words", "257 groups", "512 words quoted"],
)
def test_a_word_over_the_brace_limit_refuses_the_line(command: str) -> None:
    word = command.removeprefix("echo ").strip("'")
    assert plaincall._expand(word) is None
    assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED


def test_braces_nested_deeper_than_the_stack_allows_refuse_the_line() -> None:
    command = "echo " + "{a," * 255 + "}" * 255
    assert plaincall.refusal(bash(command)) is None
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(len(inspect.stack(0)) + 150)
    try:
        assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED
    finally:
        sys.setrecursionlimit(limit)


# Words whose groups hold quoted or escaped `{`, `}` or `,`: text in the group, as in Bash.
QUOTED_IN_BRACES = [
    "{mait,--for=\\}}y {--for=\\},runne}r status",
    '{mait,--for="}"}y {--for="}",runne}r status',
    "{mait,--for='}'}y {--for='}',runne}r status",
    "{mait,--f=\\{}y {--f=\\{,runne}r status",
    '{mait,--for="{"}y {--for="{",runne}r status',
]


@pytest.mark.parametrize("command", QUOTED_IN_BRACES)
def test_quoted_brace_characters_are_text_in_the_group(command: str) -> None:
    assert plaincall.prefixed(command)
    assert plaincall.calls_runner(command)
    assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED


@pytest.mark.parametrize("command", QUOTED_IN_BRACES)
def test_such_words_in_quoted_text_read_again_count_the_same(command: str) -> None:
    line = "bash -c " + shlex.quote(command)
    assert plaincall.prefixed(line)
    assert plaincall.calls_runner(line)
    assert plaincall.refusal(bash(line)) == plaincall.RUNNER_REFUSED


@pytest.mark.parametrize(
    "command", ["echo {a,'}'}", 'git diff -- cli/{src,"t,s"}', "echo {a,\\,b}"]
)
def test_quoted_brace_characters_without_both_words_pass(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


SPLIT_WRITTEN = [
    ("{a,'}'}", "{a,'}'}", "{a,}}"),
    ('x{a,b}"{"', 'x{a,b}"{"', "x{a,b}{"),
    ("\\{a,b}", "\\{a,b}", "{a,b}"),
]


@pytest.mark.parametrize(("line", "written", "text"), SPLIT_WRITTEN)
def test_the_split_gives_each_word_as_written(line: str, written: str, text: str) -> None:
    [(unquoted, _, _, as_written)] = plaincall._split(line)
    assert (unquoted, as_written) == (text, written)
    assert [w for _, _, _, w in plaincall._split(f"a {line}|b")] == ["a", written, "b"]


def test_the_runner_reason_names_the_file_way_out() -> None:
    assert "that the hook does not read" in plaincall.RUNNER_REFUSED
    assert "text that holds both words goes in a file" in plaincall.RUNNER_REFUSED


BRACE_PATHS = [
    "pytest tests/test_{a,b}.py",
    "git diff -- cli/{src,tests}",
    "echo {1..1000}",
    "echo {a..e..+2}",
]


@pytest.mark.parametrize("command", BRACE_PATHS)
def test_brace_paths_and_ranges_without_both_words_pass(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


# A first word that only starts with `maity`.
STARTS_WITH_MAITY = [
    "maity/maity status",
    "maity/../maity status",
    "Maity/maity status",
    '"maity"/maity status',
    "maity-wrapper maity status",
]


@pytest.mark.parametrize("command", STARTS_WITH_MAITY)
def test_a_first_word_longer_than_maity_before_maity_is_refused_outright(command: str) -> None:
    assert not plaincall.held(command)
    assert plaincall.refusal(bash(command)) == plaincall.PREFIX_REFUSED


@pytest.mark.parametrize("command", ["maityx status", "maity_ status", "maity.md status"])
def test_a_first_word_longer_than_maity_alone_is_not_decided(command: str) -> None:
    assert not plaincall.held(command)
    assert plaincall.refusal(bash(command)) is None


# `maity` as the first word, followed by a space, a tab, an operator or the line's end.
FIRST_WORD = [
    ("maity status", None),
    ("maity\tstatus", None),
    ("maity", None),
    ("MAITY status", None),
    ("maity;", plaincall.REFUSED),
    ("maity|x", plaincall.REFUSED),
    ("maity&", plaincall.REFUSED),
    ("maity>f", plaincall.REFUSED),
    ("maity(x)", plaincall.REFUSED),
    ("maity\nx", plaincall.REFUSED),
]


@pytest.mark.parametrize(("command", "reason"), FIRST_WORD)
def test_maity_as_the_first_word_is_held(command: str, reason: str | None) -> None:
    assert plaincall.held(command)
    assert plaincall.refusal(bash(command)) == reason


def test_unclosed_quoted_text_counts_only_when_it_names_maity() -> None:
    assert plaincall.prefixed('git commit -m "it\'s maity"')
    assert not plaincall.prefixed('git commit -m "it\'s done"')


@pytest.mark.parametrize("command", ["maity status", "TZ=UTC maity status", "git status"])
def test_ordinary_lines_pass(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


def test_any_tool_with_a_command_is_checked() -> None:
    assert plaincall.refusal(bash("maity a | x", tool="PowerShell")) == plaincall.REFUSED
    assert plaincall.refusal({"tool_name": "Read", "tool_input": {"file_path": "/x"}}) is None
    assert plaincall.refusal({"tool_name": "Bash", "tool_input": {"command": 3}}) is None


def test_unreadable_input_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    assert plaincall.refusal([1]) is not None
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"\xff{")))
    assert plaincall.main([]) == 2


def test_a_call_the_hook_fails_on_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fails(payload: object) -> str | None:
        raise ValueError(payload)

    monkeypatch.setattr(plaincall, "refusal", fails)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(bash("x")).encode())))
    assert plaincall.main([]) == 2
    assert capsys.readouterr().err.strip() == plaincall.FAILED


class _Broken:
    """A stream whose every use fails, as no stream the hook reads should."""

    def __getattr__(self, name: str) -> object:
        raise AttributeError(name)


@pytest.mark.parametrize("raised", [SystemExit(0), KeyboardInterrupt(), MemoryError(), KeyError()])
def test_anything_raised_while_deciding_refuses_the_call(
    monkeypatch: pytest.MonkeyPatch, raised: BaseException
) -> None:
    def fails(payload: object) -> str | None:
        raise raised

    monkeypatch.setattr(plaincall, "refusal", fails)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(bash("x")).encode())))
    assert plaincall.main([]) == 2


def test_input_or_output_the_hook_cannot_use_refuses_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "stdin", _Broken())
    assert plaincall.main([]) == 2
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"[]")))
    monkeypatch.setattr(sys, "stderr", _Broken())
    assert plaincall.main([]) == 2


# Steps and ends with more digits than an integer holds: Bash leaves the range as text.
LONG_NUMBERS = [
    ("{a..e.." + "1" * 5000 + "}", ["{a..e.." + "1" * 5000 + "}"]),
    ("{1.." + "9" * 5000 + "}", ["{1.." + "9" * 5000 + "}"]),
    ("{a..e.." + "0" * 30 + "2}", ["a", "c", "e"]),
    ("{a..e..9223372036854775808}", ["{a..e..9223372036854775808}"]),
    ("{a..e..-9223372036854775808}", ["{a..e..-9223372036854775808}"]),
    ("{a..e..9223372036854775807}", ["a"]),
    ("{-9223372036854775808..-9223372036854775807}", ["-9223372036854775808"]),
]


@pytest.mark.parametrize(("word", "words"), LONG_NUMBERS, ids=range(len(LONG_NUMBERS)))
def test_a_range_with_an_integer_out_of_range_is_text(word: str, words: list[str]) -> None:
    assert plaincall._expand(word) == words
    assert plaincall.refusal(bash("echo " + word)) is None


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


# A first word that is quoted or escaped and holds no letter: a word of its own before
# `maity`, not leading text to skip.
QUOTED_FIRST_WORDS = [
    '"[" maity status',
    "\\[ maity status",
    '"" maity status',
    "'' maity status",
    "\\! maity status",
    "'!' maity status",
    '"maity status"',
    "'maity status' x",
    "/maity status",  # `maity` by a path from the root
    "//maity status",
]


@pytest.mark.parametrize("command", QUOTED_FIRST_WORDS)
def test_a_quoted_or_escaped_first_word_before_maity_is_refused_outright(command: str) -> None:
    assert plaincall.prefixed(command)
    assert plaincall.refusal(bash(command)) == plaincall.PREFIX_REFUSED


@pytest.mark.parametrize("command", ["\\maity status", '"maity" status', "'maity' status"])
def test_maity_itself_quoted_or_escaped_is_held_to_one_plain_call(command: str) -> None:
    assert plaincall.held(command)
    assert plaincall.refusal(bash(command)) is None
    assert plaincall.refusal(bash(command + " | cat")) == plaincall.REFUSED


# Bash's locale quoting: `$"..."` is the text, or its translation.
LOCALE_QUOTED = [
    'ma$"ity" run$"ner"',
    'TZ=UTC ma$"ity" status',
    'x; $"maity" $"runner"',
    'maity $"runner" status',
    'maity say lotse $"text"',
    'echo $"hi"',
]


@pytest.mark.parametrize("command", LOCALE_QUOTED)
def test_a_line_with_locale_quoting_is_refused_whatever_it_holds(command: str) -> None:
    assert plaincall.refusal(bash(command)) in (plaincall.RUNNER_REFUSED, plaincall.REFUSED)
    assert plaincall.calls_runner(command)


@pytest.mark.parametrize("levels", [1, 2, 3, 4])
def test_quoted_text_without_a_maity_word_is_read_four_levels_deep(levels: int) -> None:
    command = nested("cat maity.md", levels)
    assert not plaincall.prefixed(command)
    assert plaincall.refusal(bash(command)) is None


def test_quoted_text_past_four_levels_counts_when_it_names_maity() -> None:
    command = nested("cat maity.md", 5)
    assert plaincall.prefixed(command)
    assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED


def test_quoted_text_the_hook_cannot_read_counts_only_when_it_names_maity() -> None:
    assert plaincall.prefixed('echo "\'maity status"')
    assert not plaincall.prefixed('echo "\'x status"')


def _bash_5_2() -> tuple[str, tuple[int, int], str] | None:
    """A Bash of version 5.2 or later on the path, its version and its full version string,
    or None; on Windows none is looked for, since `bash` there may be WSL's launcher or a Bash
    that needs its own environment."""
    found = shutil.which("bash")
    if found is None or sys.platform == "win32":
        return None
    try:
        done = subprocess.run(
            [found, "-c", 'echo "${BASH_VERSINFO[0]} ${BASH_VERSINFO[1]} $BASH_VERSION"'],
            capture_output=True, text=True, timeout=30, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        major, minor, full = done.stdout.split()
        version = (int(major), int(minor))
    except ValueError:
        return None
    return (found, version, full) if version >= (5, 2) else None


FOUND = _bash_5_2()
BASH = None if FOUND is None else FOUND[0]
# The brace rules of the Bash on the path, as `_expand` knows them: 5.2's, or 5.3's for 5.3
# and later.
BASH_RULES = (5, 2) if FOUND is None or FOUND[1] < (5, 3) else (5, 3)
BASH_NAME = "no bash" if FOUND is None else f"bash {FOUND[2]}"


def bash_records(
    words: list[str], commands: list[str], tmp_path: Path, label: str = ""
) -> list[list[list[str]]]:
    """What Bash prints for each word: for each of `commands` (a line with `{w}` for the word,
    that prints `$#` and the words, or `E`), the words it made. Each word's records start
    with a mark, and the script ends with one, so a record Bash does not print fails the
    test with the word and the Bash version, not with a misread count."""
    lines = ["set -f"]
    for k, word in enumerate(words):
        lines.append(f"printf 'R{k}\\0'; " + "; ".join(c.format(w=word) for c in commands))
    lines.append("printf 'END\\0'")
    script = tmp_path / "words.sh"
    script.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    assert BASH is not None
    done = subprocess.run(
        [BASH, "--norc", "--noprofile", str(script)], cwd=tmp_path, capture_output=True,
        timeout=120, check=False, env={"PATH": "", "LC_ALL": "C"},
    )  # fmt: skip
    out = done.stdout.decode("utf-8", "replace").split("\0")
    err = done.stderr.decode("utf-8", "replace")[-2000:]
    records: list[list[list[str]]] = []
    at = 0
    for k, word in enumerate(words):
        if at >= len(out) or out[at] != f"R{k}":
            pytest.fail(
                f"{label}{BASH_NAME} printed no record for word {word!r} "
                f"(exit {done.returncode}): {err}"
            )
        at += 1
        made: list[list[str]] = []
        for _ in commands:
            head = out[at] if at < len(out) else ""
            if head == "E":
                made.append([])
                at += 1
                continue
            if not head.isdigit():
                pytest.fail(
                    f"{label}{BASH_NAME} printed {head!r} for word {word!r} "
                    f"(exit {done.returncode}): {err}"
                )
            made.append(out[at + 1 : at + 1 + int(head)])
            at += 1 + int(head)
        records.append(made)
    assert out[at:] == ["END", ""], f"{label}{BASH_NAME}: {err}"
    return records


BRACE_TOKENS = ["{", "}", ",", "..", "a", "e", "m", "z", "A", "V", "Z", "0", "1", "5", "-2", "+3"]
BRACE_ENDS = ["a", "e", "z", "A", "V", "W", "Z", "1", "5", "01", "-2", "x"]


def brace_word(generate: random.Random, depth: int = 0) -> str:
    """Text, groups of alternatives, ranges and stray brace characters, joined."""
    parts = []
    for _ in range(generate.randint(1, 4)):
        kind = generate.random()
        if kind < 0.3 and depth < 2:
            alternatives = [brace_word(generate, depth + 1) for _ in range(generate.randint(0, 3))]
            parts.append("{" + ",".join(alternatives) + "}")
        elif kind < 0.5:
            step = generate.choice(["", "", "..2", "..-3", "..0", "..+6", "..5", ".."])
            parts.append(
                "{" + generate.choice(BRACE_ENDS) + ".." + generate.choice(BRACE_ENDS) + step + "}"
            )
        else:
            parts.append("".join(generate.choices(BRACE_TOKENS, k=generate.randint(1, 3))))
    word = list("".join(parts))
    for _ in range(generate.randint(0, 2)):  # a stray, a lost or a moved character
        at = generate.randint(0, len(word))
        if generate.random() < 0.5:
            word.insert(at, generate.choice("{},."))
        elif word:
            del word[min(at, len(word) - 1)]
    return "".join(word)


def brace_words(count: int, seed: int) -> list[str]:
    generate = random.Random(seed)  # noqa: S311 - test data, seeded on purpose
    return [brace_word(generate) for _ in range(count)]


@pytest.mark.skipif(BASH is None, reason="needs Bash 5.2 or later on the path (not on Windows)")
def test_braces_expand_as_bash_expands_them_or_are_not_read(tmp_path: Path) -> None:
    """The words `_expand` makes under the rules of the Bash on the path are Bash's, or it
    does not read the word; the hook's words, both versions' together, hold Bash's."""
    words = brace_words(600, seed=1942)
    asked = [w for w in words if plaincall._brace_words(w, True, BASH_RULES) is not None]
    printed = bash_records(asked, ['set -- {w}; printf \'%s\\0\' "$#" "$@"'], tmp_path)
    made = {w: records[0] for w, records in zip(asked, printed, strict=True)}
    for w in asked:
        exact = plaincall._brace_words(w, True, BASH_RULES)
        assert exact == made[w], f"{BASH_NAME}: {w!r}"
        both = plaincall._brace_words(w, True)
        assert both is None or set(made[w]) <= set(both), f"{BASH_NAME}: {w!r}"
    assert len(asked) > len(words) // 2
    assert sum(1 for w in asked if made[w] != [w]) > len(words) // 3  # most of them expand


QUOTED_TOKENS = ["{", "}", ",", "..", ".", "a", "b", "1", "mait", "y", "runne", "r", "--for="]
QUOTED_TOKENS += ["'}'", "'{'", "','", "'.'", "''", '""', '"}"', '","', '"."', "'\"'", '"\'"']
QUOTED_TOKENS += ['"\\\\"', "'a b'", "\\}", "\\{", "\\,", "\\.", "\\\\", "\\'", '\\"']
QUOTED_INNER = ["a", "b", "1", "2", ".", "..", "\\.", "''", '""', "'.'", '"."', '"\'"', "'\"'"]
QUOTED_INNER += ['"\\\\"', "\\}", "'}'", "\\,", "','", "X=", "--for=", "{", "}", ","]


def quoted_brace_word(generate: random.Random) -> str:
    """A word of unquoted, quoted and escaped brace characters, often a group that a `}`
    before its `,` may or may not close, with `maity` or `runner` after it."""
    if generate.random() < 0.5:
        return "".join(generate.choices(QUOTED_TOKENS, k=generate.randint(1, 9)))
    inner = "".join(generate.choices(QUOTED_INNER, k=generate.randint(1, 4)))
    head, tail = generate.choice([("mait", "y"), ("runne", "r")])
    body = "{" + inner + "}," + head + "}" + tail
    return f"'{body}'" if "'" not in body and generate.random() < 0.3 else body


# Lines in which Bash makes `maity` and `runner` of braces with quoted, escaped or stray
# characters; each is refused.
BRACE_CORPUS = [
    "{m..m..+1}aity {r..r..+1}unner status",
    "ma{i..i..+1}ty run{n..n..+5}er status",
    *QUOTED_IN_BRACES,
    *BRACES_CLOSED_LATER,
    *RANGES_OVER_A_BACKSLASH,
    "eval '{mait,--for=\\}}y' '{--for=\\},runne}r' status",
    'eval "{mait,--for=\\\\}}y" "{--for=\\\\},runne}r" status',
    "eval 'MAITY_PLACEMENT=' '{mait,--for=\\}}y' status",
    "env -u {a\\..b},mait}y --for {a\\..b},runne}r status",
    "env {X=1\\..2},mait}y {--for=1\\..2},runne}r status",
    "env -u {1\\..2},mait}y --for {1\\..2},runne}r status",
    "env -u {a.''.b},mait}y --for {a.''.b},runne}r status",
    'env -u {a."".b},mait}y --for {a."".b},runne}r status',
    'env -u {a."\'".b},mait}y --for {a."\'".b},runne}r status',
    "env -u {a.'\"'.b},mait}y --for {a.'\"'.b},runne}r status",
    'env -u {a."\\\\".b},mait}y --for {a."\\\\".b},runne}r status',
]


@pytest.mark.parametrize("command", BRACE_CORPUS)
def test_braces_that_make_maity_and_runner_refuse_the_line(command: str) -> None:
    assert plaincall.refusal(bash(command)) is not None
    assert plaincall.calls_runner(command) or plaincall.prefixed(command)


def bash_names(word: str) -> tuple[bool, bool]:
    """Whether a word Bash made is `maity`, and whether it is `runner`, as the hook judges a
    word with nothing left to expand."""
    base = re.sub(r"^[^0-9A-Za-z]+", "", word.rsplit("/", 1)[-1]).lower()
    return base == "maity", word.lower() == "runner"


def corpus_words() -> list[str]:
    words = []
    for line in BRACE_CORPUS:
        words += [w for _, _, _, w in plaincall._split(line) if "{" in w]
    return words


@pytest.mark.skipif(BASH is None, reason="needs Bash 5.2 or later on the path (not on Windows)")
def test_quoted_brace_words_name_maity_only_where_the_hook_sees_it(tmp_path: Path) -> None:
    """Each word Bash makes of the word, and of its text read again (`eval`), that is
    `maity` or `runner` the hook counts as such, or it does not read the word: no word
    passes that Bash makes into either name. A fixed seed and a fresh one each run."""
    print(BASH_NAME)  # noqa: T201 - recorded in the test log
    fresh = random.SystemRandom().randrange(2**32)
    for seed in (19420, fresh):
        generate = random.Random(seed)  # noqa: S311 - test data, seeded on purpose
        words = corpus_words() + [quoted_brace_word(generate) for _ in range(3000)]
        read = []
        for word in words:
            try:
                [(text, _, _, written)] = plaincall._split(word)
            except (plaincall._Unreadable, ValueError):
                continue
            if "{" in written and plaincall._brace_names(text, written) is None:
                continue  # not read: the line is refused, and Bash may not finish it
            read.append((word, text, written))
        printed = bash_records(
            [w for w, _, _ in read],
            [
                'set -- {w}; printf \'%s\\0\' "$#" "$@"',
                'if eval "set -- $*" 2>/dev/null; then printf \'%s\\0\' "$#" "$@"; '
                "else printf 'E\\0'; fi",
            ],
            tmp_path,
            f"seed {seed}, ",
        )
        opened = []
        for (word, text, written), records in zip(read, printed, strict=True):
            maity, runner = plaincall._is_maity(text, written), plaincall._is_runner(text, written)
            for again, made in zip((False, True), records, strict=True):
                if again and plaincall.calls_runner("eval " + word):
                    continue  # the line `eval WORD` is refused
                for one in made:
                    is_maity, is_runner = bash_names(one)
                    if (is_maity and not maity) or (is_runner and not runner):
                        opened.append((word, again, one))
        assert len(read) >= 2900, f"seed {seed}"
        assert opened == [], f"seed {seed} {BASH_NAME}"


def escaped(word: str, layers: int, depth_of: Callable[[str], int] | None = None) -> str:
    """`word` with each brace character escaped to stay text for `layers` readings, so that
    the reading after them expands it (or each character as deep as `depth_of` says)."""
    depth = depth_of or (lambda c: layers if c in "{},." else 0)
    return "".join("\\" * (2 ** depth(c) - 1) + c for c in word)


READ_AGAIN = [
    "{m..m}aity {r..r}unner status",
    "{m..m..+1}aity {r..r..+1}unner status",
    "{mait,--for=}y {--for=,runne}r status",
]


@pytest.mark.parametrize("evals", [plaincall._NESTING - 1, plaincall._NESTING + 1, 6])
@pytest.mark.parametrize("words", READ_AGAIN)
def test_braces_read_again_past_the_bound_refuse_the_line(words: str, evals: int) -> None:
    line = "eval " * evals + " ".join(escaped(w, evals) for w in words.split())
    assert plaincall.calls_runner(line)
    assert plaincall.refusal(bash(line)) == plaincall.RUNNER_REFUSED


def test_the_words_an_expansion_makes_are_read_again() -> None:
    word = "{,..}{},mait}y"  # makes `..{},mait}y`, which a shell that reads it again expands
    assert plaincall._is_maity(word, word)
    assert plaincall.refusal(bash(f"env {word} status")) == plaincall.PREFIX_REFUSED
    line = "echo {'maity {r,x}unner',x}"  # makes `maity {r,x}unner`, read again as a line
    assert plaincall.calls_runner(line)


def test_braces_over_the_limit_still_refuse_the_line() -> None:
    assert plaincall.refusal(bash("echo {a..z}{a..z}")) == plaincall.RUNNER_REFUSED


def test_a_word_that_still_changes_after_the_last_reading_is_not_read() -> None:
    within = escaped("{m..m}aity", plaincall._NESTING)
    [(text, _, _, written)] = plaincall._split(within)
    assert plaincall._is_maity(text, written) and not plaincall._is_runner(text, written)
    past = escaped("{m..m}aity", plaincall._NESTING + 1)
    [(text, _, _, written)] = plaincall._split(past)
    assert plaincall._is_maity(text, written) and plaincall._is_runner(text, written)


def test_a_word_made_with_spaces_is_read_again_by_its_parts() -> None:
    written = "{x,'a {r,x}unner'}"
    [(text, _, _, as_written)] = plaincall._split(written)
    assert as_written == written
    assert plaincall._is_runner(text, written)


def test_more_readers_than_the_bound_refuse_braces_whatever_they_name() -> None:
    assert plaincall.calls_runner("eval " * (plaincall._NESTING + 1) + "echo {a,b}")
    assert plaincall.calls_runner("x; . x{a,b}")
    assert plaincall.calls_runner("eval echo {a,b}")
    assert not plaincall.calls_runner("eval " * (plaincall._NESTING + 1) + "echo a")
    assert not plaincall.calls_runner("find . -name x{a,b}")


EVAL_BASES = [
    "{m..m}aity",
    "{r..r}unner",
    "{mait,--for=}y",
    "{--for=,runne}r",
    "{X=},mait}y",
    "m{V..a..6}aity",
    "{ma,x}ity",
]


@pytest.mark.skipif(BASH is None, reason="needs Bash 5.2 or later on the path (not on Windows)")
def test_words_read_again_by_eval_chains_name_maity_only_where_the_hook_sees_it(
    tmp_path: Path,
) -> None:
    """A word escaped for `k` readings after `eval` × `k` (k from 1 to 6), each character
    as deep as chance says: no word passes that Bash makes into `maity` or `runner` at the
    end of the chain, unless the hook counts it as such or refuses the line."""
    print(BASH_NAME)  # noqa: T201 - recorded in the test log
    fresh = random.SystemRandom().randrange(2**32)
    for seed in (19421, fresh):
        generate = random.Random(seed)  # noqa: S311 - test data, seeded on purpose
        lines, judged, refused = [], [], []
        for n in range(800):
            k = generate.randint(1, 6)
            base = EVAL_BASES[n % len(EVAL_BASES)] if n < 70 else brace_word(generate)
            full = n % 2 == 0

            def depth(c: str, k: int = k, full: bool = full, g: random.Random = generate) -> int:
                if c in "{},.":
                    return k if full else g.randint(0, k)
                return 0

            word = escaped(base, k, depth)
            line = "eval " * k + word
            try:
                [*_, (text, _, _, written)] = plaincall._split(line)
            except (plaincall._Unreadable, ValueError):
                continue
            if plaincall.calls_runner(line):
                refused.append(line)
                continue
            lines.append("eval " * k + "set -- " + word)
            judged.append(
                (line, plaincall._is_maity(text, written), plaincall._is_runner(text, written))
            )
        printed = bash_records(
            lines,
            [
                "if {w}; then printf '%s\\0' \"$#\" \"$@\"; else printf 'E\\0'; fi",
            ],
            tmp_path,
            f"seed {seed}, ",
        )
        opened = []
        for (line, maity, runner), [made] in zip(judged, printed, strict=True):
            for one in made:
                is_maity, is_runner = bash_names(one)
                if (is_maity and not maity) or (is_runner and not runner):
                    opened.append((line, one))
        assert len(judged) + len(refused) >= 700, f"seed {seed}"
        assert opened == [], f"seed {seed} {BASH_NAME}"


_B = "\\" * 31  # five readings: escaped five times over
# Lines with a construct the hook does not read exactly, around braces that make `maity`
# and `runner`: each is refused.
CONSTRUCT_LINES = [
    f"eval eval eval eval eval {_B}{{m..m{_B}}}aity {_B}{{r..r{_B}}}unner status",
    f"eval eval eval eval eval {_B}{{m..m..+1{_B}}}aity {_B}{{r..r..+1{_B}}}unner status",
    f"eval eval eval eval eval {_B}{{mait{_B},--for={_B}}}y {_B}{{--for={_B},runne{_B}}}r status",
    "$\\\n'\\x6daity' $\\\n'\\x72unner' status",
    "env $\\\n'\\x6daity' status",
    'echo $\\\n"hi"',
    "env -u {a\\..b},{m.\\\n.m}ait}y --for {a\\..b},{r.\\\n.r}unne}r status",
    "env -u {a\\..b},{m\\\n..m}ait}y --for {a\\..b},{r\\\n..r}unne}r status",
    "env -u {a\\..b},{m..\\\nm}ait}y --for {a\\..b},{r..\\\nr}unne}r status",
    "env -u {a\\..b},{m..m..\\\n1}ait}y --for {a\\..b},{r..r..\\\n1}unne}r status",
    'env -u {a..\\\n},"{",mait}y --for {a..\\\n},"{",runne}r status',
    "eval {X=a\\..b},'{mait,--for=}'}y {--for=a\\..b},'{--for=,runne}'}r status",
    "eval {MAITY_PLACEMENT=a\\..b},'{mait,--for=}'}y status",
    "eval {X=1,'{mait,--for=}y {--for=,runne}r'} status",
    "eval {X=1,'{mait,--for=}y --for='} {--for=1,'{--for=,runne}r --for='} status",
    "eval {MAITY_PLACEMENT=,'{mait,--for=}y --for='} status",
    "`# '` {mait,--for='x '}y {--for='x ',runne}r status `# '`",
    "eval env -u {1..${x:-'}'}},mait}y --for {1..${x:-'}'}},runne}r status",
    "true # '\n{mait,--for='x '}y {--for='x ',runne}r status # '",
    "cat <<EOF >/dev/null\n'\nEOF\n{mait,--for='x '}y {--for='x ',runne}r status # '",
    "eval {X=''}V,\"{mait,--for=}\"}y {--for=''}V,\"{--for=,runne}\"}r status",
]


@pytest.mark.parametrize("command", CONSTRUCT_LINES, ids=range(len(CONSTRUCT_LINES)))
def test_a_construct_the_hook_does_not_read_exactly_refuses_the_line(command: str) -> None:
    assert plaincall.calls_runner(command)
    assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED


# `$(…)` in double quotes with a heredoc whose delimiter is quoted, or with a quoted word
# that holds a space (review A1437): the commit form Claude Code writes, and its neighbours.
PLAIN_SUBSTITUTIONS = [
    "git commit -m \"$(cat <<'EOF'\nFix the thing\nEOF\n)\"",
    "git commit -m \"$(cat <<'EOF'\nFix the thing ) \" ' ` $(x)\n\nMore text.\nEOF\n)\"",
    'git commit -m "$(cat <<"EOF"\nFix the thing\nEOF\n)"',
    "git commit -m \"$(cat <<-'EOF'\n\tFix the thing\n\tEOF\n)\"",
    "git commit -m \"$(cat <<'A'; cat <<'B'\na\nA\nb\nB\n)\" --no-verify",
    'echo "$(git log -1 --format="%h %s")"',
    'git commit -m "$(cat "msg file.txt")"',
    'echo "x $(cat "a b" "$(echo "c d")") y"',
    "git commit -m \"$(cat <<'EOF'\nRead to EOF\n EOF is not the end\nEOF\n)\"",
    'echo "$(echo a#b)"',
    "echo \"$(git log -1 --format='%h #%s')\"",
    # A body line that starts with the delimiter but has no `)` after it (review P3-1).
    "git commit -m \"$(cat <<'EOF'\nFix the thing\n\nEOFError is handled now\nEOF\n)\"",
    "git commit -m \"$(cat <<'EOF'\nFix the thing\n\nEOFs are fine\nEOF\n)\"",
    "git commit -m \"$(cat <<-'EOF'\n\tFix the thing\n\tEOFError is handled now\n\tEOF\n)\"",
    'git commit -m "$(cat <<"EOF"\nEOFs are fine; so is EOF\'s end.\nEOF\n)"',
]
# Heredocs and substitutions without such constructs.
PLAIN_CONSTRUCTS = [
    "x=\"$(jq '{a:1}' f.json)\"",
    'x="$(curl -s -d \'{"a":1}\' https://example.com)"',
    "echo \"author $(git log -1 --format='%an'): {ok}\"",
    'echo "$((1 + 2)) {a,b}"',
    "cat <<EOF\nhello {a,b}\nEOF",
    "python3 - <<'EOF'\nprint({'a': 1})\nEOF",
    "cat <<EOF x",
    *PLAIN_SUBSTITUTIONS,
]
# The same forms where `maity … runner` runs, or is named on a line that is not one read
# line: each is refused.
SUBSTITUTIONS_WITH_RUNNER = [
    "git commit -m \"$(maity runner status <<'EOF'\nx\nEOF\n)\"",
    "git commit -m \"$(cat <<'EOF'\nx\nEOF\nmaity runner status\n)\"",
    "git commit -m \"$(cat <<'EOF'\nx\nEOF\nma?ty runner status\n)\"",
    "git commit -m \"$(cat <<'EOF'\nmaity runner status\nEOF\n)\"",
    "git commit -m \"$(cat <<'EOF'\nx\n EOF\nmaity runner status\nEOF\n)\"",
    "git commit -m \"$(cat <<'EOF'\nx\nEOF\n)\" && ma?ty runner status",
    "echo \"$(cat <<'EOF'\nx\nEOF\n)\" runner status",
    'echo "$(git log -1 --format="%h maity runner")"',
    'echo "$(maity runner "a b")"',
    'echo "$(cat "a b"; maity runner status)"',
    'git commit -m "$(cat "msg file.txt")"; maity runner status',
    'git commit -m "$(cat "msg file.txt")" && ma?ty runner status',
    '"$(cat "msg file.txt")" runner status',
    'maity "$(cat "msg file.txt")" runner',
    # A heredoc in it whose end the hook does not read exactly (review A1536).
    'echo "$(cat <<\'A\'\nx\nA)" ; ma?ty runner s ; echo "\nA\n)"',
    'echo "$(cat <<\'A\'\nx\nA)"\nma?ty runner s\n: "\nA\n)"',
    'echo "$(cat <<\'A\'\nx\nA)" ; ma[i]ty runner s ; echo "\nA\n)"',
    'echo "$(cat <<\'A\'\nx\nA)"\nma[i]ty runner s\n: "\nA\n)"',
    'echo "$(cat <<\'A\'\nx\nA )" ; ma?ty runner s ; echo "\nA\n)"',
    'echo "$(cat <<\'A\'\nx\nA))" ; ma?ty runner s ; echo "\nA\n)"',
    'echo "$(cat <<\'A\'\nx\nA)x" ; ma?ty runner s ; echo "\nA\n)"',
    'echo "$(cat <<-\'A\'\n\tx\n\tA)" ; ma?ty runner s ; echo "\n\tA\n)"',
    'echo "$(cat <<"A"\nx\nA)" ; ma?ty runner s ; echo "\nA\n)"',
    'echo "$(cat <<\\A\nx\nA)" ; ma?ty runner s ; echo "\nA\n)"',
    'git commit -m "$(cat <<\'EOF\'\nx\nEOF)" ; ma?ty runner s ; echo "\nEOF\n)"',
    'echo "$(cat <<\'A\'\nx\nA\t)" ; ma?ty runner s ; echo "\nA\n)"',
    "echo \"$(cat <<'A' <<'B'\nx\nA)\" ; ma?ty runner s ; echo \"\nA\ny\nB\n)\"",
    "echo \"$(cat <<'A' <<'B'\nx\nA\ny\nB)\" ; ma?ty runner s ; echo \"\nB\n)\"",
    "echo \"$(cat <<'A'; cat <<'B'\nx\nA\ny\nB)\" ; ma?ty runner s ; echo \"\nB\n)\"",
    'echo "$(echo "$(cat <<\'A\'\nx\nA)" ; ma?ty runner s ; echo "\nA\n)")"',
    "echo \"$(cat <<'A'''\nx\nA)\" ; ma?ty runner s ; echo \"\nA\n)\"",
    'X="$(cat <<\'A\'\nx\nA)" true ; ma?ty runner s ; echo "\nA\n)"',
    # A `)` anywhere after the delimiter, not only right after it (review P3-1).
    'echo "$(cat <<\'A\'\nx\nA$)" ; ma?ty runner s ; echo "\nA\n)"',
    'echo "$(cat <<\'A\'\nx\nA a)" ; ma?ty runner s ; echo "\nA\n)"',
    "git commit -m \"$(cat <<'EOF'\nx\nEOF ma?ty runner s)\"",
    "git commit -m \"$(cat <<'EOF'\nx\nEOFError; y; ma?ty runner s; y)\"",
    "git commit -m \"$(cat <<'EOF'\nx\nEOFError || ma?ty runner s)\"",
    "git commit -m \"$(cat <<'EOF'\nx\nEOF `ma?ty runner s`)\"",
    # A comment in it (review A1537).
    'echo "$(true;#<<"EOF"\nma?ty runner status\nEOF\n)"',
    "echo \"$(true;#<<'EOF'\nma?ty runner status\nEOF\n)\"",
    'echo "$(true;#<<\\EOF\nma?ty runner status\nEOF\n)"',
    'echo "$(true|#<<"EOF"\nma?ty runner status\nEOF\n)"',
    'echo "$(true&#<<"EOF"\nma?ty runner status\nEOF\n)"',
    'echo "$(true&&#<<"EOF"\nma?ty runner status\nEOF\n)"',
    'echo "$(false||#<<"EOF"\nma?ty runner status\nEOF\n)"',
    'echo "$( (true)#<<"EOF"\nma?ty runner status\nEOF\n)"',
    'echo "$(echo "$(true;#<<"EOF"\nma?ty runner status\nEOF\n)")"',
    'echo "$(cat <(true;#<<"EOF"\nma?ty runner status\nEOF\n))"',
]


@pytest.mark.parametrize("command", PLAIN_CONSTRUCTS, ids=range(len(PLAIN_CONSTRUCTS)))
def test_plain_heredocs_and_substitutions_pass(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


@pytest.mark.parametrize(
    "command", SUBSTITUTIONS_WITH_RUNNER, ids=range(len(SUBSTITUTIONS_WITH_RUNNER))
)
def test_a_substitution_in_double_quotes_with_runner_is_refused(command: str) -> None:
    assert plaincall.refusal(bash(command)) is not None


def test_the_split_keeps_a_substitution_in_double_quotes_whole() -> None:
    line = 'echo "$(git log -1 --format="%h %s")" b'
    assert [w for _, _, _, w in plaincall._split(line)] == [
        "echo", '"$(git log -1 --format="%h %s")"', "b"
    ]  # fmt: skip


@pytest.mark.skipif(BASH is None, reason="needs Bash 5.2 or later on the path (not on Windows)")
def test_substitutions_in_double_quotes_run_maity_runner_only_if_refused(tmp_path: Path) -> None:
    """Each line above in Bash, with `maity`, `git` and `cat` functions, the first printing
    its words to stderr, which a substitution does not take, and with files `maity` (for
    `ma?ty`) and `msg file.txt` (that says `maity`): every plain form runs without a syntax
    error and calls no `maity`, and Bash runs `maity runner` from no line the hook lets
    through."""
    print(BASH_NAME)  # noqa: T201 - recorded in the test log
    (tmp_path / "maity").write_text("")
    (tmp_path / "msg file.txt").write_text("maity\n")
    functions = (
        "maity() { printf 'M %s\\n' \"$*\" >&2; }\ngit() { :; }\n"
        'cat() { local l; while IFS= read -r l || [ -n "$l" ]; do printf \'%s\\n\' "$l";'
        ' done < "${1:-/dev/stdin}"; }\n'
    )
    opened, ran = [], 0
    for line in [*PLAIN_SUBSTITUTIONS, *SUBSTITUTIONS_WITH_RUNNER]:
        assert BASH is not None
        script = functions + line
        done = subprocess.run(
            [BASH, "--norc", "--noprofile", "-c", script], cwd=tmp_path,
            capture_output=True, text=True, timeout=30, check=False,
            env={"PATH": "", "LC_ALL": "C"},
        )  # fmt: skip
        runs = [out.split() for out in done.stderr.splitlines() if out.startswith("M ")]
        if line in PLAIN_SUBSTITUTIONS:
            assert runs == [], line
            assert "syntax error" not in done.stderr and "warning" not in done.stderr, line
        if any("runner" in words for words in runs):
            ran += 1
            if plaincall.refusal(bash(line)) is None:
                opened.append(line)
    assert opened == [], BASH_NAME
    assert ran >= 44, ran  # the lines that run `maity runner` do run it in Bash


# One construct each, without braces or names: each refuses the line.
CONSTRUCTS = [
    "eval 'echo hi'",
    "bash -c 'echo hi'",
    "sh -ec 'echo hi'",
    "x; . ./{a,b}.sh",
    "echo $'hi'",
    "echo a \\\nb {c,d}",
    "echo `echo 'x'`",
    "echo `x",
    "echo ${x:-'y'}",
    "echo {a,${x}}",
    "echo {a,$(x)}",
    "echo {a,`x`}",
    'echo "${HOME}"{a,b}',
    "echo {mait,$(true)--for=}y",
    "echo {a,b} # c",
    "cat <<EOF\n$(date)\nEOF",
    'echo "$(cat <<EOF\nx\nEOF\n)"',
    "echo \"$(cat <<'EOF'\nx\nEOF)\"",
    "echo \"$(cat <<'EOF')\"\nx\nEOF",
    "echo \"$(cat <<<'x y')\"",
]


@pytest.mark.parametrize("command", CONSTRUCTS, ids=range(len(CONSTRUCTS)))
def test_each_construct_refuses_the_line(command: str) -> None:
    assert plaincall._unmodelled(command)
    assert plaincall.refusal(bash(command)) == plaincall.RUNNER_REFUSED


# The same constructs where the hook reads them exactly.
NOT_CONSTRUCTS = [
    "eval echo hi",
    ". venv/bin/activate",
    "find . -name x",
    "echo '$'\"'\"'x'",
    "echo '\\\n'",
    "echo `date`",
    "echo ${HOME}",
    "echo hi # c",
    "cat <<'EOF'\n$(date)\nEOF",
]


@pytest.mark.parametrize("command", NOT_CONSTRUCTS, ids=range(len(NOT_CONSTRUCTS)))
def test_the_same_constructs_read_exactly_pass(command: str) -> None:
    assert not plaincall._unmodelled(command)
    assert plaincall.refusal(bash(command)) is None


LINE_SHAPES = [
    "{w}",
    "true # '\n{w}",
    'true # "\n{w} # "',
    "cat <<E >/dev/null\n'\nE\n{w}",
    "cat <<'E' >/dev/null\n\"\nE\n{w} # '",
    "`# '` {w} `# '`",
    "`true` {w}",
    "x=$'\\x61' {w}",
    "{w} \\\n# '",
    "true \\\n'' {w}",
    "eval {w}",
    "eval eval {w}",
]
LINE_WORDS = [
    "{mait,--for='x '}y {--for='x ',runne}r status",
    "{mait,--for=}y {--for=,runne}r status",
    "{m..m}aity {r..r}unner status",
    "ma{i,}ty run{n,}er status",
    "\\{mait,--for=\\}y \\{--for=,runne\\}r status",
]


@pytest.mark.skipif(BASH is None, reason="needs Bash 5.2 or later on the path (not on Windows)")
def test_lines_with_comments_heredocs_and_substitutions_run_maity_runner_only_if_refused(
    tmp_path: Path,
) -> None:
    """Brace words that make `maity … runner` set in lines with comments, heredocs,
    backticks, `$'...'`, continuations and `eval`: Bash runs `maity runner` from none of
    them unless the hook refuses the line. Each line runs in its own Bash, with `maity` a
    function that prints its words."""
    print(BASH_NAME)  # noqa: T201 - recorded in the test log
    fresh = random.SystemRandom().randrange(2**32)
    ran = 0
    for seed in (19422, fresh):
        generate = random.Random(seed)  # noqa: S311 - test data, seeded on purpose
        lines = [shape.format(w=w) for shape in LINE_SHAPES for w in LINE_WORDS]
        for _ in range(60):
            words = generate.choice(LINE_WORDS).split()
            junk = generate.choice(["'", '"', "\\", "`", "#", "$'", "''", " "])
            at = generate.randint(0, len(words))
            line = " ".join([*words[:at], junk, *words[at:]])
            lines.append(generate.choice(LINE_SHAPES).format(w=line))
        opened = []
        for line in lines:
            assert BASH is not None
            script = "maity() { printf 'M %s\\n' \"$*\"; }\n" + line
            done = subprocess.run(
                [BASH, "--norc", "--noprofile", "-c", script], cwd=tmp_path,
                capture_output=True, text=True, timeout=30, check=False,
                env={"PATH": "", "LC_ALL": "C"},
            )  # fmt: skip
            runs = [out.split() for out in done.stdout.splitlines() if out.startswith("M ")]
            if any("runner" in words for words in runs):
                ran += 1
                if plaincall.refusal(bash(line)) is None:
                    opened.append(line)
        assert opened == [], f"seed {seed} {BASH_NAME}"
    assert ran > 50  # most of the lines do run `maity runner` in Bash


def test_text_with_braces_and_backticks_in_a_maity_call_passes() -> None:
    assert plaincall.refusal(bash("maity say x 'see `{x}` and {a,b}'")) is None
    assert plaincall.refusal(bash("watch 'eval echo \\{a,b\\}'")) == plaincall.RUNNER_REFUSED


def test_the_runner_reason_names_the_constructs() -> None:
    assert "`eval`, `source`, `.`, `trap` or `bash -c`" in plaincall.RUNNER_REFUSED
    assert "a backslash-newline" in plaincall.RUNNER_REFUSED


# Substitution shapes around the commands an agent may put `maity` behind.
SUBSTITUTION_SHAPES = [
    "`{c}`",
    "$({c})",
    '"$({c})"',
    '"`{c}`"',
    "cat <({c})",
    "x=`{c}`",
    "echo `{c}`",
    "`{c}`y",
    "$(echo `{c}`)",
    "true; `{c}`",
    "true && `{c}`",
    "true | `{c}`",
    'echo "a`{c}`b"',
    "for i in `{c}`; do :; done",
    "echo $(echo $({c}))",
]
SUBSTITUTED_COMMANDS = [
    "maity",
    "{bin}/maity",
    "./maity",
    "env maity",
    "nice maity",
    "command maity",
    "exec maity",
    "PYTHONPATH=. maity",
    "NO_COLOR=1 maity",
    "MAITY_WAIT_TIMEOUT=5 maity",
    "nohup maity",
    "{{ maity; }}",
    "(maity)",
    "true; maity",
    "false || maity",
    "true | maity",
    "! maity",
    " maity",
    "maity ",
    "\tmaity",
]
# What may stand right after `maity` at the start of a line, glued to it: expansions that
# may make nothing, and quoting that makes nothing.
GLUED_AFTER_MAITY = [
    "",
    "$(true)",
    "$( )",
    "$()",
    "$x",
    "${x}",
    "${x:-}",
    "$@",
    "$*",
    "$1",
    "${IFS}",
    "`true`",
    '"$(true)"',
    '"$x"',
    "''$x",
    '""',
    "''",
]
# The allowed assignments, and none, before a line's `maity`.
ALLOWED_PREFIXES = ["", "NO_COLOR=1 ", "TZ=UTC LANG=C ", "LC_ALL=C ", " ", "\t"]


def bash_runs_maity(lines: list[str], tmp_path: Path) -> tuple[list[str], int, int]:
    """Each line in its own Bash, with `maity` a program on the path and in the working
    directory that records its arguments: the lines Bash runs `maity` from that the hook
    lets through and that are not one plain call, how many lines run `maity`, and how many
    run `maity runner`."""
    print(BASH_NAME)  # noqa: T201 - recorded in the test log
    assert BASH is not None
    bin_dir, mark = tmp_path / "bin", tmp_path / "ran"
    bin_dir.mkdir(exist_ok=True)
    program = f'#!{BASH}\necho "ran $*" >> "$MARK"\n'
    for where in (bin_dir / "maity", tmp_path / "maity"):
        where.write_text(program)
        where.chmod(0o755)
    env = {"PATH": ":".join([str(bin_dir), "/usr/bin", "/bin"]), "MARK": str(mark),
           "HOME": str(tmp_path), "LC_ALL": "C"}  # fmt: skip
    found = subprocess.run(
        [BASH, "--norc", "--noprofile", "-c", "command -v maity"], capture_output=True,
        text=True, timeout=30, check=False, env=env,
    )  # fmt: skip
    assert found.stdout.strip() == str(bin_dir / "maity")
    opened, ran, runner = [], 0, 0
    for line in lines:
        mark.unlink(missing_ok=True)
        subprocess.run(
            [BASH, "--norc", "--noprofile", "-c", line], cwd=tmp_path, capture_output=True,
            timeout=30, check=False, stdin=subprocess.DEVNULL, env=env,
        )  # fmt: skip
        if mark.exists():
            ran += 1
            runner += "ran runner" in mark.read_text()
            one_plain_call = plaincall.held(line) and plaincall.plain(line)
            if plaincall.refusal(bash(line)) is None and not one_plain_call:
                opened.append(line)
    return opened, ran, runner


@pytest.mark.skipif(BASH is None, reason="needs Bash 5.2 or later on the path (not on Windows)")
def test_a_line_that_starts_with_maity_runs_it_only_as_one_plain_call(tmp_path: Path) -> None:
    """A line that starts with `maity`, after nothing or the allowed assignments, with each
    glued expansion or quoting after it, with and without arguments and with `runner`: Bash
    runs `maity` from none that the hook lets through unless it is one plain call, and from
    none with `runner`."""
    lines = [
        prefix + "maity" + glued + args
        for prefix in ALLOWED_PREFIXES
        for glued in GLUED_AFTER_MAITY
        for args in ("", " status", " runner status", "${IFS}status", "$(true) status")
    ]
    opened, ran, runner = bash_runs_maity(lines, tmp_path)
    assert opened == [], BASH_NAME
    assert ran >= len(lines) - 10, ran
    assert runner >= len(ALLOWED_PREFIXES) * len(GLUED_AFTER_MAITY) - 5, runner


@pytest.mark.skipif(BASH is None, reason="needs Bash 5.2 or later on the path (not on Windows)")
def test_maity_runner_runs_from_no_line_the_hook_lets_through(tmp_path: Path) -> None:
    """Each shape with each command and `runner` after it: Bash runs `maity runner` from
    none of the lines the hook lets through."""
    bin_dir = tmp_path / "bin"
    lines = [
        shape.format(c=command.format(bin=bin_dir) + " runner status")
        for shape in SUBSTITUTION_SHAPES
        for command in SUBSTITUTED_COMMANDS
    ]
    opened, ran, runner = bash_runs_maity(lines, tmp_path)
    assert opened == [], BASH_NAME
    assert runner >= 250, runner  # most of the lines do run `maity runner` in Bash
