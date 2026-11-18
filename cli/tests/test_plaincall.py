from __future__ import annotations

import io
import json
import re
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


# Assignments before `maity` to each name that may stand there: one, several, a quoted value.
ASSIGNMENTS = [
    "MAITY_WAIT_TIMEOUT=5",
    "NO_COLOR=1",
    "LANG=C.UTF-8",
    "LC_ALL=C",
    "LC_CTYPE=C",
    "TZ=UTC",
    "TZ=UTC LANG=C",
    "TZ='x y'",
    'TZ="x y"',
    "MAITY_WAIT_TIMEOUT=5 NO_COLOR=1 LANG=C LC_ALL=C TZ=UTC",
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
    "MAITY_WAIT_TIMEOUT=5 MAITY_FOO=1",
    "LANGUAGE=x",
    "TZ=UTC PATH=.",
    "A+=1",
    "_X=1 B+=2",
    "MAITY_X+=1",
    "MAITY_WAIT_TIMEOUT+=5",
    "TZ+=x",
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
    "MAITY_GIT_PRIVATE",
    "MAITY_STATE_DIR",
    "MAITY_SUPERVISOR",
    "MAITY_RUNNER_CONFIG",
    "MAITY_ERROR_LINE",
    "MAITY_SCRATCH",
)
AGENTS_MD = SRC.parent.parent / "docs" / "agents.md"


def code_maity_names() -> set[str]:
    """The `MAITY_` environment names maity's code names: every string literal that starts
    with `MAITY_` and a letter (`"MAITY_STATE_DIR"`, `f"MAITY_SUPERVISOR is ..."`), in every
    module but this hook. Python names such as `MAITY_NOT_PLAIN` or `CLAUDE_MAITY_PROMPT` are
    no string literal, and the bare prefix `"MAITY_"` names no variable."""
    found: set[str] = set()
    for path in (SRC / "maity").rglob("*.py"):
        if path.name != "plaincall.py":
            found.update(re.findall(r"[\"'](MAITY_[A-Z][A-Z0-9_]*)", path.read_text()))
    return found


def test_the_scan_finds_every_runner_trusted_name_and_no_unclassified_one() -> None:
    allowed = {n for n in plaincall.ALLOWED_BEFORE_MAITY if n.startswith("MAITY_")}
    assert code_maity_names() == set(RUNNER_TRUSTED) | allowed


def test_no_runner_trusted_name_is_on_the_allow_list() -> None:
    names = plaincall.ALLOWED_BEFORE_MAITY
    assert isinstance(names, tuple)
    assert not set(names) & set(RUNNER_TRUSTED)
    patterns = [n for n in names if n.startswith("MAITY") and not re.fullmatch(r"MAITY_\w+", n)]
    assert not patterns  # no `MAITY_*`: a `MAITY_` name stands on the list by its name
    for name in [*RUNNER_TRUSTED, *code_maity_names() - set(names), "MAITY_FOO", "MAITY_"]:
        assert plaincall._ASSIGNMENT.match(name + "=1") is None, name


def test_every_maity_name_on_the_allow_list_is_read_by_maity_and_documented_for_agents() -> None:
    docs = AGENTS_MD.read_text()
    for name in plaincall.ALLOWED_BEFORE_MAITY:
        if name.startswith("MAITY_"):
            assert name in code_maity_names(), name
            assert re.search(rf"`{name}(=[^`]*)?`", docs), name


@pytest.mark.parametrize("name", RUNNER_TRUSTED)
def test_maity_after_a_runner_trusted_name_is_refused_outright(name: str) -> None:
    assert plaincall.refusal(bash(f"{name}=1 maity status")) == plaincall.PREFIX_REFUSED


def test_maity_wait_after_its_timeout_variable_passes() -> None:
    assert plaincall.refusal(bash("MAITY_WAIT_TIMEOUT=5 maity wait")) is None


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
    "eval 'maity status'",
    "sh -c 'maity status'",
    "bash -c 'maity status'",
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
    ("eval ma\\\\ity --version | cat", plaincall.PREFIX_REFUSED),
    ("eval $'ma\\x69ty runner status'", plaincall.RUNNER_REFUSED),
    ("eval ma\\\\ity status", plaincall.PREFIX_REFUSED),
    ("eval 'ma\\ity' status", plaincall.PREFIX_REFUSED),
    ("eval 'm\"a\"ity' status", plaincall.PREFIX_REFUSED),
    ("eval ma\\$\\'i\\'ty status", plaincall.PREFIX_REFUSED),
    ("eval ma\\$\\'\\\\x69\\'ty status", plaincall.PREFIX_REFUSED),
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
