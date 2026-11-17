"""The hook a placed Claude Code session runs before every tool call, under its sandbox.

`maity` runs outside the sandbox (`excludedCommands`). This hook lets a command line that
starts with `maity` through only when it is one plain call: words of letters, digits and
`_-./:=@%+,~^#`, quoted text without expansions, and nothing else. A pipe, a chain, a
redirect, a background `&`, a substitution, a heredoc, a newline or a `$` is refused before
the command runs (cli/context/runner.md). A line that calls `maity runner` anywhere is
refused outright, whatever it starts with: those commands are the runner's own, and the runner
never starts them through an agent's tool call. Any other tool call, and a command line
that does not start with `maity`, is left to the permission rules: the hook prints nothing and
exits 0.

It reads Claude Code's PreToolUse input on stdin and refuses with exit 2 and the reason on
stderr. Input it cannot read is refused too.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from collections.abc import Sequence

# Characters a word may hold unquoted: none of them makes the shell do anything but take it
# as text (`#` starts a comment only at a word's start, where the rest is ignored).
UNQUOTED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./:=@%+,~^#")
# Inside double quotes the shell still expands `$` and backticks; `!` is left out as well.
NOT_IN_DOUBLE_QUOTES = frozenset("$`!\n")
# Every leading character that is not a letter or a digit is skipped before looking for
# `maity`, so a line counts as a maity call however the harness trims it.
_MAITY = re.compile(r"[^0-9A-Za-z]*maity", re.IGNORECASE)

# `maity`'s options that come before its subcommand and take a value (`--for AGENT`); argparse
# also takes an unambiguous prefix of an option.
_VALUE_OPTIONS = ("--for",)
# Characters that end one command on a line and start the next (or a redirect's target).
_SEPARATORS = "();<>|&\n"

RUNNER_REFUSED = (
    "`maity runner` is the runner's own command and does not run from a placed session's tool "
    "call. Use the other `maity` commands."
)
REFUSED = (
    "A `maity` command runs only as one plain call: nothing piped, chained, redirected, sent to "
    "the background or substituted, no heredoc, no newline and no `$`. Run it alone; put text "
    "in single quotes, or write it to a file in this clone and pass that file (`--body-file`)."
)


def applies(command: str) -> bool:
    """Whether the line is one the hook decides: it starts with `maity`."""
    return _MAITY.match(command) is not None


def plain(command: str) -> bool:
    """Whether `command` is one simple command of literal words: unquoted safe characters,
    a backslash before any character but a newline, single-quoted text without a newline,
    double-quoted text without `$`, a backtick, `!` or a newline. Spaces and tabs separate
    words; spaces, tabs and newlines at either end are ignored."""
    text = command.strip(" \t\n")
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t" or c in UNQUOTED:
            i += 1
        elif c == "\\":
            if i + 1 >= n or text[i + 1] == "\n":
                return False
            i += 2
        elif c == "'":
            end = text.find("'", i + 1)
            if end < 0 or "\n" in text[i + 1 : end]:
                return False
            i = end + 1
        elif c == '"':
            i += 1
            while True:
                if i >= n or text[i] in NOT_IN_DOUBLE_QUOTES:
                    return False
                if text[i] == '"':
                    i += 1
                    break
                if text[i] == "\\":
                    if i + 1 >= n or text[i + 1] == "\n":
                        return False
                    i += 1
                i += 1
        else:
            return False
    return True


def _is_maity(word: str) -> bool:
    """Whether a word names `maity`, by any path and however the harness trims it."""
    name = word.rsplit("/", 1)[-1]
    return re.sub(r"^[^0-9A-Za-z]+", "", name).lower() == "maity"


def _runs_runner(words: Sequence[str]) -> bool:
    """Whether a `maity` word in one command is followed by `runner` as its subcommand,
    after the options maity takes before one. Any `maity` word counts, not only the command
    word, so one behind an assignment or a wrapper (`env`, `nohup`, ...) counts too."""
    for start, word in enumerate(words):
        if not _is_maity(word):
            continue
        i = start + 1
        while i < len(words) and words[i].startswith("-"):
            option = words[i]
            i += 1
            if option == "--":
                break
            if "=" not in option and any(
                len(option) > 2 and name.startswith(option) for name in _VALUE_OPTIONS
            ):
                i += 1  # the option's value
        if i < len(words) and words[i] == "runner":
            return True
    return False


def calls_runner(command: str) -> bool:
    """Whether any command on the line is `maity runner`: the line is split into words as the
    shell splits it, and into commands at `;`, `&`, `|`, `(`, `)`, `<`, `>` and newlines. A
    line the shell could not split is not looked at here (`plain` decides a `maity` line)."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_SEPARATORS)
    lexer.whitespace = " \t\r"
    lexer.commenters = ""  # a comment ends at a newline the lexer would swallow with it
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return False
    words: list[str] = []
    for token in [*tokens, ";"]:
        if token and all(c in _SEPARATORS for c in token):
            if _runs_runner(words):
                return True
            words = []
        else:
            words.append(token)
    return False


def refusal(payload: object) -> str | None:
    """The reason to refuse the tool call in Claude Code's PreToolUse input, or None."""
    if not isinstance(payload, dict):
        return "the hook's input is not a JSON object"
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return None
    if calls_runner(command):
        return RUNNER_REFUSED
    if not applies(command) or plain(command):
        return None
    return REFUSED


def main(args: Sequence[str] | None = None) -> int:
    """Exit 0 to leave the call to the permission rules, 2 to refuse it."""
    del args  # takes none
    try:
        payload = json.loads(sys.stdin.buffer.read())
    except (ValueError, OSError, RecursionError):
        payload = None
    reason = refusal(payload)
    if reason is None:
        return 0
    print(reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
