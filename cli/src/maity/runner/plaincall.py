"""The hook a placed Claude Code session runs before every tool call, under its sandbox.

`maity` runs outside the sandbox (`excludedCommands`). This hook lets a command line that
starts with `maity` through only when it is one plain call: words of letters, digits and
`_-./:=@%+,~^#`, quoted text without expansions, and nothing else. A pipe, a chain, a
redirect, a background `&`, a substitution, a heredoc, a newline or a `$` is refused before
the command runs (cli/context/runner.md). A line that runs `maity` anywhere but as its first
word is refused too: after a variable, a wrapper such as `env`, `command`, `exec`, `nice` or
`timeout`, a shell given a script, or another command (`behind`). Any other tool call, and a
command line that does not run `maity`, is left to the permission rules: the hook prints
nothing and exits 0.

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

REFUSED = (
    "A `maity` command runs only as one plain call: nothing piped, chained, redirected, sent to "
    "the background or substituted, no heredoc, no newline and no `$`. Run it alone; put text "
    "in single quotes, or write it to a file in this clone and pass that file (`--body-file`)."
)


BEHIND = (
    "`maity` runs only as the first word of its own line: nothing in front of it (no variable, "
    "no `env`, `command`, `exec`, `nice`, `timeout` or other wrapper, no shell or `eval` running "
    "it) and not after another command. Run it alone as `maity …`."
)

# Programs and shell words that run the command given in their arguments: a `maity` in any of
# their arguments counts as a call. One list for every check; a name not on it is a program
# whose arguments are its own (`git commit -m 'maity …'`).
WRAPPERS = frozenset({
    "env", "command", "builtin", "exec", "eval", "nice", "ionice", "renice", "chrt", "taskset",
    "timeout", "nohup", "setsid", "stdbuf", "unbuffer", "xargs", "parallel", "time", "sudo",
    "doas", "su", "runuser", "setpriv", "chpst", "flock", "script", "watch", "strace", "ltrace",
    "systemd-run", "busybox", "unshare", "nsenter", "chroot", "firejail", "caffeinate", "then",
    "do", "else", "elif", "if", "while", "until", "!", "{", "coproc",
    "sh", "bash", "dash", "zsh", "ksh", "mksh", "ash", "fish", "csh", "tcsh", "pwsh",
    "powershell",
})  # fmt: skip
# Shell separators: a word after one of them is in command position again.
_SEPARATORS = frozenset({";", "&", "|", "&&", "||", "(", ")", ";;", "|&", ";&", ";;&"})
# Characters that make a quoted argument a command line of its own for a wrapper.
_SCRIPT = re.compile(r"[\s;&|<>()`$]")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
_WORD = re.compile(r"maity", re.IGNORECASE)


def _is_maity(word: str) -> bool:
    """Whether the word names `maity` as a program, under any path, case or extension."""
    name = re.split(r"[/\\]", word)[-1].lower()
    return name in ("maity", "maity.exe", "maity.cmd", "maity.bat")


def _program(word: str) -> str:
    return re.split(r"[/\\]", word)[-1].lower().removesuffix(".exe")


def behind(command: str, depth: int = 0) -> bool:
    """Whether the line runs `maity` other than as its first word: after an assignment, a
    wrapper (WRAPPERS) or another command, or inside a substitution. Conservative: a line
    that cannot be read as words, or that nests too deep, counts when it holds `maity`."""
    if _WORD.search(command) is None:
        return False
    if depth > 4 or "`" in command or "$(" in command or "<(" in command or ">(" in command:
        return True  # a substitution runs its own command; not taken apart here
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        words = list(lexer)
    except ValueError:
        return True
    start, redirect = True, False
    wrapped = False
    for i, word in enumerate(words):
        if word in _SEPARATORS:
            start, wrapped, redirect = True, False, False
            continue
        if word and set(word) <= set("<>&|"):
            redirect = True  # its target is the next word, never a command
            continue
        if redirect:
            redirect = False
            continue
        if start:
            if _ASSIGNMENT.match(word):
                continue
            if _is_maity(word):
                if i > 0 or depth > 0 or word.lower() != "maity":
                    return True  # something stands in front of it or runs it, or a path
                start = False
                continue
            if "$" in word:
                return True  # a program named by an expansion: unknown, and `maity` is here
            start, wrapped = False, _program(word) in WRAPPERS
            continue
        if wrapped and (_is_maity(word) or _SCRIPT.search(word) and behind(word, depth + 1)):
            return True
    return False


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


def refusal(payload: object) -> str | None:
    """The reason to refuse the tool call in Claude Code's PreToolUse input, or None."""
    if not isinstance(payload, dict):
        return "the hook's input is not a JSON object"
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return None
    if applies(command):
        if not plain(command):
            return REFUSED
        # `maity` itself, not a path to a program of that name or a quoted spelling
        return None if command.split()[0].lower() == "maity" else BEHIND
    return BEHIND if behind(command) else None


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
