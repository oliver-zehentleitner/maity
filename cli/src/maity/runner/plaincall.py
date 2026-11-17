"""The hook a placed Claude Code session runs before every tool call, under its sandbox.

`maity` runs outside the sandbox (`excludedCommands`). This hook lets a command line that
starts with `maity` through only when it is one plain call: words of letters, digits and
`_-./:=@%+,~^#`, quoted text without expansions, and nothing else. A pipe, a chain, a
redirect, a background `&`, a substitution, a heredoc, a newline or a `$` is refused before
the command runs (cli/context/runner.md). On any line, a word `maity` followed anywhere
later by a word `runner` is refused as well (`calls_runner`, which says how it reads words):
those commands are the runner's own, and the runner never starts them through an agent's tool
call. A command the shell builds only from expansions or from input is not read; such a line
is not one plain `maity` call, so its `maity` runs inside the sandbox. Any other tool call is
left to the permission rules: the hook prints nothing and exits 0.

It reads Claude Code's PreToolUse input on stdin and refuses with exit 2 and the reason on
stderr. Input it cannot read is refused too.
"""

from __future__ import annotations

import json
import re
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

# Unquoted characters that end a word, besides spaces and tabs: the shell's operators.
_SEPARATORS = frozenset("();<>|&\n")
# Unquoted characters after which the shell may still change a word: an expansion, a glob, a
# brace.
_EXPANDS = frozenset("$`*?[{")
# How deep quoted text is read again as a line of its own (`sh -c '...'`).
_NESTING = 4

RUNNER_REFUSED = (
    "`maity runner` is the runner's own command and does not run from a placed session's tool "
    "call: a line where a word `runner` follows a word `maity` is refused. Use the other "
    "`maity` commands; text that holds both words goes in a file in this clone, passed with "
    "`--body-file`."
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
    """Whether a word names `maity`: by any path, in any case, however its start is trimmed."""
    name = word.rsplit("/", 1)[-1]
    return re.sub(r"^[^0-9A-Za-z]+", "", name).lower() == "maity"


class _Unreadable(ValueError):
    """A quote the line never closes: its words are not known."""


def _words(line: str) -> list[tuple[str, bool]]:
    """The line's words as the shell splits and unquotes them, each with whether the shell
    would still expand it (`$`, a backtick, a glob, a brace), so that its final text is not
    known here; a word that starts with an unquoted `~` and holds no `/` counts as one too.
    Words end at unquoted spaces, tabs and operators; a backslash-newline joins
    the lines; nothing is expanded and comments are read like any other text. Raises
    _Unreadable for a quote that is never closed."""
    words: list[tuple[str, bool]] = []
    chars: list[str] = []
    started = expands = tilde = False
    i, n = 0, len(line)

    def end() -> None:
        nonlocal chars, started, expands, tilde
        if started:
            text = "".join(chars)
            # `~`, `~-`, `~+`, `~user` alone: the shell puts a directory in their place.
            words.append((text, expands or (tilde and "/" not in text)))
        chars, started, expands, tilde = [], False, False, False

    def closing(start: int, escapes: bool) -> int:
        """The index of the `'` that closes the quote opened before `start`."""
        j = start
        while j < n and line[j] != "'":
            j += 2 if escapes and line[j] == "\\" else 1
        if j >= n:
            raise _Unreadable(line)
        return j

    while i < n:
        c = line[i]
        if c in " \t" or c in _SEPARATORS:
            end()
        elif c == "\\":
            if i + 1 < n and line[i + 1] != "\n":
                started = True
                chars.append(line[i + 1])
            i += 1  # a backslash-newline is a line continuation: nothing
        elif c == "$" and i + 1 < n and line[i + 1] == "'":
            end_at = closing(i + 2, escapes=True)  # $'...': the shell decodes its escapes
            started = expands = True
            chars.append(line[i + 2 : end_at])
            i = end_at
        elif c == "'":
            end_at = closing(i + 1, escapes=False)
            started = True
            chars.append(line[i + 1 : end_at])
            i = end_at
        elif c == '"':
            started = True
            i += 1
            while i < n and line[i] != '"':
                if line[i] == "\\" and i + 1 < n and line[i + 1] in '$`"\\\n':
                    if line[i + 1] != "\n":
                        chars.append(line[i + 1])
                    i += 2
                    continue
                expands = expands or line[i] in "$`"
                chars.append(line[i])
                i += 1
            if i >= n:
                raise _Unreadable(line)
        else:
            tilde = tilde or (c == "~" and not started)
            started = True
            expands = expands or c in _EXPANDS
            chars.append(c)
        i += 1
    end()
    return words


def calls_runner(command: str, depth: int = 0) -> bool:
    """Whether the line may run `maity runner`: a word `maity` (`_is_maity`) is followed
    anywhere later on the line by a word `runner` (in any case). Neither has to be the
    command word, and operators between them do not matter. A word the shell would still
    expand (`_words` says which) counts as `runner` after a `maity` word and as `maity`
    before a `runner` word.
    Quoted text that holds spaces or operators is read again the same way, as another shell
    would read it, up to `_NESTING` levels deep; text below that counts when it holds
    `runner` at all. A line whose quotes never close counts when it holds `maity` or
    `runner` at all."""
    try:
        words = _words(command)
    except _Unreadable:
        low = command.lower()
        return "runner" in low or "maity" in low
    seen_maity = seen_open = False
    for text, expands in words:
        if text.lower() == "runner" and (seen_maity or seen_open):
            return True
        if expands and seen_maity:
            return True
        if any(c in " \t" or c in _SEPARATORS for c in text) and (
            calls_runner(text, depth + 1) if depth < _NESTING else "runner" in text.lower()
        ):
            return True
        seen_maity = seen_maity or _is_maity(text)
        seen_open = seen_open or expands
    return False


def refusal(payload: object) -> str | None:
    """The reason to refuse the tool call in Claude Code's PreToolUse input, or None."""
    if not isinstance(payload, dict):
        return "the hook's input is not a JSON object"
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return None
    if applies(command) and not plain(command):
        return REFUSED  # refused either way; this reason names the way out
    if calls_runner(command):
        return RUNNER_REFUSED
    return None


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
