"""The hook a placed Claude Code session runs before every tool call, under its sandbox.

`maity` runs outside the sandbox (`excludedCommands`). This hook lets a command line that
starts with `maity`, or whose words before a word `maity` are only variable assignments
(`held`), through only when it is one plain call: words of letters, digits and
`_-./:=@%+,~^#`, quoted text without expansions, and nothing else. A pipe, a chain, a
redirect, a background `&`, a substitution, a heredoc, a newline or a `$` is refused before
the command runs (cli/context/runner.md). Any other line in which `maity` is a word
(`prefixed`) is refused outright: a command word, a keyword, `!`, a redirection, a subshell
or a group before it, or `maity` by a path. On any line, a word `maity` followed later by a
word `runner`, as `calls_runner` splits words, is refused as well: those commands are the
runner's own, and the runner never starts them through an agent's tool call. A line that
names `maity` anywhere (`names_maity`) is refused when it holds a comment, a heredoc or more
than one line (`read_whole`), and any line is refused when its quotes never close or its
quoted text is nested too deep: the hook does not read such lines to the end. A command the
shell builds only from expansions or from input is not read. Any other tool call is left to
the permission rules: the hook prints nothing and exits 0.

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
# Leading characters a plain call may not hold, spaces and quotes are skipped before looking
# for `maity`, so a line counts as a maity call however the harness trims it. A character a
# plain word may hold (`/`, `.`, `:` and the rest of `UNQUOTED`) is not skipped: before
# `maity` it makes a path or another command.
_MAITY = re.compile(r"[^0-9A-Za-z_\-./:=@%+,~^#]*maity", re.IGNORECASE)

# Unquoted characters that end a word, besides spaces and tabs: the shell's operators.
_SEPARATORS = frozenset("();<>|&\n")
# Unquoted characters after which the shell may still change a word: an expansion, a glob, a
# brace.
_EXPANDS = frozenset("$`*?[{")
# How deep quoted text is read again as a line of its own (`sh -c '...'`).
_NESTING = 4
# Characters after which a `#` is inside a word, not the start of a comment: printable ASCII
# that is neither a space nor one of the shell's operators. After anything else, or at the
# line's start, a `#` counts as a comment.
_IN_WORD = frozenset(chr(c) for c in range(0x21, 0x7F)) - frozenset("|&;()<>`")

RUNNER_REFUSED = (
    "`maity runner` is the runner's own command and does not run from a placed session's tool "
    "call: a line where a word `runner` follows a word `maity` is refused, and so is a line "
    "the hook cannot read to the end (one that names `maity` and holds a comment, a heredoc "
    "or more than one line; a quote that never closes; quoted text nested too deep). Run "
    "each `maity` command on a line of its own, without a comment; text that holds both "
    "words goes in a file in this clone, passed with `--body-file`."
)
REFUSED = (
    "A `maity` command runs only as one plain call: nothing piped, chained, redirected, sent to "
    "the background or substituted, no heredoc, no newline and no `$`. Run it alone; put text "
    "in single quotes, or write it to a file in this clone and pass that file (`--body-file`)."
)
PREFIX_REFUSED = (
    "A line in which `maity` is a word runs only as one plain `maity …` call at the start of "
    "the line, after nothing but variable assignments: no other command, keyword, `!`, "
    "redirection, subshell or group before it, and `maity` by its name, not by a path. Run "
    "`maity …` at the start of the line; text that mentions `maity` goes in a file in this "
    "clone, passed with `--body-file`."
)


# A variable assignment as the shell takes it before a command: a name, unquoted, then `=` or
# `+=`.
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")


def _placement(command: str) -> str | None:
    """Where `maity` stands on the line: "held" when the line starts with `maity`
    (`_MAITY`), when every word before its first word `maity` (`_is_maity`) is a variable
    assignment written unquoted and that word is `maity` alone (in any case, not by a path),
    or when a quote never closes on a line that names `maity`; "prefixed" when `maity` is a
    word after anything else, by a path, or a word of quoted text that holds spaces or
    operators, read again as a line (`_maity_in_text`); None when `maity` is no word of the
    line."""
    if _MAITY.match(command) is not None:
        return "held"
    try:
        words = _split(command)
    except _Unreadable:
        return "held" if names_maity(command) else None
    for index, (text, _, _) in enumerate(words):
        if _is_maity(text):
            before = words[:index]
            if text.lower() != "maity" or not all(
                _ASSIGNMENT.match(command, at) for _, _, at in before
            ):
                return "prefixed"
            return "held"
    if any(_maity_in_text(text, 1) for text, _, _ in words):
        return "prefixed"
    return None


def _maity_in_text(text: str, depth: int) -> bool:
    """Whether `maity` is a word of quoted text that holds spaces or operators, read again as
    a line the way `calls_runner` reads it, up to `_NESTING` levels deep; text nested deeper
    counts when it names `maity` anywhere (`names_maity`)."""
    if not any(c in " \t" or c in _SEPARATORS for c in text):
        return False
    if depth >= _NESTING:
        return names_maity(text)
    try:
        words = _words(text)
    except _Unreadable:
        return names_maity(text)
    return any(_is_maity(word) or _maity_in_text(word, depth + 1) for word, _ in words)


def held(command: str) -> bool:
    """Whether the line is held to one plain call (`_placement`)."""
    return _placement(command) == "held"


def prefixed(command: str) -> bool:
    """Whether `maity` is a word of the line after something that is not a variable
    assignment, or by a path (`_placement`): such a line is refused outright."""
    return _placement(command) == "prefixed"


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
    """The line's words and whether each expands, as `_split` reads them."""
    return [(text, expands) for text, expands, _ in _split(line)]


def _split(line: str) -> list[tuple[str, bool, int]]:
    """The line's words, split and unquoted by the rules below, each with whether it holds
    something the shell would still expand (`$`, a backtick, a glob, a brace), so that its
    final text is not known here; a word that starts with an unquoted `~` and holds no `/`
    counts as one too. Words end at unquoted spaces, tabs and operators; single quotes,
    double quotes, `$'...'` and backslashes are taken off; a backslash-newline joins the
    lines; nothing is expanded. Each word comes with the index in the line where it starts. A
    `#` and a heredoc are read like any other text, so a line
    that holds them is not split as the shell splits it: `read_whole` refuses such a line
    when it names `maity`. Raises _Unreadable for a quote that is never closed."""
    words: list[tuple[str, bool, int]] = []
    chars: list[str] = []
    started = expands = tilde = False
    i, n, begin = 0, len(line), 0

    def end() -> None:
        nonlocal chars, started, expands, tilde
        if started:
            text = "".join(chars)
            # `~`, `~-`, `~+`, `~user` alone: the shell puts a directory in their place.
            words.append((text, expands or (tilde and "/" not in text), begin))
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
        if not started:
            begin = i
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


def names_maity(command: str) -> bool:
    """Whether `maity` appears anywhere in the line, in any case, also with quotes or
    backslashes between its letters."""
    return "maity" in re.sub(r"[\\'\"]", "", command).lower()


def read_whole(command: str) -> bool:
    """Whether the hook reads the line to the end as one line: it holds no newline (once
    spaces, tabs and newlines at either end are taken off), no `<<` and no `#` that may start
    a comment, that is, a `#` at the line's start or after anything but printable ASCII other
    than the shell's operators. Quoting is not looked at: a `#` or `<<` inside quotes counts
    the same."""
    text = command.strip(" \t\n")
    if "\n" in text or "<<" in text:
        return False
    return all(c != "#" or (i > 0 and text[i - 1] in _IN_WORD) for i, c in enumerate(text))


class _Seen:
    """What `calls_runner` has seen so far on the line, quoted text read again included."""

    def __init__(self) -> None:
        self.maity = self.open = False


def calls_runner(command: str, depth: int = 0, seen: _Seen | None = None) -> bool:
    """Whether the line may run `maity runner`: a word `maity` (`_is_maity`) is followed
    later on the line by a word `runner` (in any case), as `_words` splits them. Neither has
    to be the command word, and operators between them do not matter. A word that `_words`
    says the shell would still expand counts as `maity` before a later `runner` word, and as
    `runner` after a `maity` word in the same text.
    Quoted text that holds spaces or operators is read again the same way, as another shell
    would read it, up to `_NESTING` levels deep; its words continue the line where the text
    stands, so a `maity` word in it counts before a `runner` word after it and the other way
    round. Such text below that depth counts whatever it holds. A line whose quotes never
    close counts whatever it holds."""
    try:
        words = _words(command)
    except _Unreadable:
        return True  # not read to the end: refused, whatever it holds
    seen = _Seen() if seen is None else seen
    maity_here = False  # a `maity` word in this text: an expanding word after it counts
    for text, expands in words:
        if text.lower() == "runner" and (seen.maity or seen.open):
            return True
        if expands and maity_here:
            return True
        if any(c in " \t" or c in _SEPARATORS for c in text) and (
            depth >= _NESTING or calls_runner(text, depth + 1, seen)
        ):
            return True  # past the depth limit, text that could be a command is refused
        maity_here = maity_here or _is_maity(text)
        seen.maity = seen.maity or maity_here
        seen.open = seen.open or expands
    return False


def refusal(payload: object) -> str | None:
    """The reason to refuse the tool call in Claude Code's PreToolUse input, or None."""
    if not isinstance(payload, dict):
        return "the hook's input is not a JSON object"
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return None
    placement = _placement(command)
    if placement == "held" and not plain(command):
        return REFUSED  # refused either way; this reason names the way out
    if calls_runner(command) or (names_maity(command) and not read_whole(command)):
        return RUNNER_REFUSED
    if placement == "prefixed":
        return PREFIX_REFUSED
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
