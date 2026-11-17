"""The hook a placed Claude Code session runs before every tool call, under its sandbox.

`maity` runs outside the sandbox (`excludedCommands`). This hook lets a command line that
starts with `maity` through only when it is one plain call: words of letters, digits and
`_-./:=@%+,~^#`, quoted text without expansions, and nothing else. A pipe, a chain, a
redirect, a background `&`, a substitution, a heredoc, a newline or a `$` is refused before
the command runs (cli/context/runner.md). For any other line the hook decides on the words
the shell runs (`behind`): one that would run `maity` other than as the plain first word is
refused. Any other tool call, and a command line that does not run `maity`, is left to the
permission rules: the hook prints nothing and exits 0.

It reads Claude Code's PreToolUse input on stdin and refuses with exit 2 and the reason on
stderr. Input it cannot read is refused too.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field

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
    "`maity` runs only as the first word of its own line, spelled plainly: nothing in front of "
    "it and not after another command. Run it alone as `maity …`."
)

# Programs and shell words that run a command given in their arguments: what they run counts
# as a call. One list for every check; a program not on it keeps its arguments as its own
# (`git commit -m '… maity …'`).
WRAPPERS = frozenset({
    "env", "command", "builtin", "exec", "eval", "nice", "ionice", "renice", "chrt", "taskset",
    "timeout", "nohup", "setsid", "stdbuf", "unbuffer", "xargs", "parallel", "time", "sudo",
    "doas", "su", "runuser", "setpriv", "chpst", "flock", "script", "watch", "strace", "ltrace",
    "systemd-run", "busybox", "unshare", "nsenter", "chroot", "firejail", "caffeinate", "alias",
    "ssh",
    "sh", "bash", "dash", "zsh", "ksh", "mksh", "ash", "fish", "csh", "tcsh", "pwsh",
    "powershell",
})  # fmt: skip
# Shell words after which the next word is in command position again.
KEYWORDS = frozenset({"then", "do", "else", "elif", "if", "while", "until", "!", "{", "time",
                      "coproc"})  # fmt: skip
# `find` runs what follows one of these.
FIND_RUNS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_NAMES = frozenset({"maity", "maity.exe", "maity.cmd", "maity.bat"})
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
_OPERATORS = ("&&", "||", ";;&", ";;", ";&", "|&", ";", "&", "|")
_REDIRECT = re.compile(r"[0-9]*(<<<|<<-|<<|<>|<&|>&|>>|>\||&>>|&>|<|>)")
_DEPTH = 8


class Unreadable(ValueError):
    """A line the hook cannot take apart into the words the shell would run."""


@dataclass
class Word:
    """One word as the shell runs it: its text with quoting removed, and whether its value
    depends on an expansion, a glob or a brace."""

    text: str = ""
    dynamic: bool = False
    pattern: bool = False
    quoted: bool = False


@dataclass
class Command:
    """One simple command: its words, the text it reads as input when the shell gives it one
    here, and whether something else feeds it."""

    words: list[Word] = field(default_factory=list)
    bodies: list[str] = field(default_factory=list)
    fed: bool = False


class _Shell:
    """Takes a command line apart the way the shell would, as far as the hook needs: words,
    simple commands, substitutions, here-documents. What it cannot read raises Unreadable."""

    def __init__(self, text: str, depth: int) -> None:
        if depth > _DEPTH:
            raise Unreadable("nested too deep")
        self.text, self.i, self.depth = text, 0, depth
        self.commands: list[Command] = []
        self.heredocs: list[tuple[str, bool, bool, Command]] = []

    def peek(self, n: int = 1) -> str:
        return self.text[self.i : self.i + n]

    def nested(self, stop: str) -> None:
        """A substitution or subshell from here to `stop`: its commands are commands too."""
        inner = _Shell(self.text, self.depth + 1)
        inner.i = self.i
        inner.run(stop)
        self.i = inner.i
        self.commands += inner.commands

    def run(self, stop: str | None = None) -> None:
        cur, fed = Command(), False

        def end(piped: bool = False) -> None:
            nonlocal cur, fed
            if cur.words or cur.bodies:
                cur.fed = cur.fed or fed
                self.commands.append(cur)
            cur, fed = Command(), piped

        while self.i < len(self.text):
            c = self.peek()
            if c in " \t":
                self.i += 1
            elif self.peek(2) == "\\\n":
                self.i += 2
            elif stop is not None and c == stop:
                self.i += 1
                end()
                return
            elif c == "\n":
                self.i += 1
                end()
                self.read_heredocs()
            elif c == "#":
                while self.i < len(self.text) and self.peek() != "\n":
                    self.i += 1
            elif c == "(" or (c in "<>" and self.peek(2)[1:] == "("):
                if c != "(":
                    self.i += 1
                    cur.words.append(Word("", dynamic=True))
                self.i += 1
                end()
                self.nested(")")
            elif c == ")":
                self.i += 1  # a `case` pattern's end, or a stray one: a separator
                end()
            elif (m := _REDIRECT.match(self.text, self.i)) and (
                m.group(0)[0] in "<>&" or self.text[self.i : m.start(1)].isdigit()
            ):
                self.i = m.end()
                self.redirect(m.group(1), cur)
            elif op := next((o for o in _OPERATORS if self.text.startswith(o, self.i)), None):
                self.i += len(op)
                end(piped=op in ("|", "|&"))
            else:
                cur.words.append(self.word(stop))
        if stop is not None:
            raise Unreadable(f"no closing {stop}")
        end()
        if self.heredocs:
            self.read_heredocs()

    def redirect(self, op: str, cur: Command) -> None:
        while self.peek() in (" ", "\t"):
            self.i += 1
        target = self.word(None)
        if op in ("<<", "<<-"):
            self.heredocs.append((target.text, target.quoted, op == "<<-", cur))
            cur.fed = True
        elif op == "<<<":
            cur.bodies.append(target.text)
            cur.fed = True
        elif op in ("<", "<>", "<&"):
            cur.fed = True

    def read_heredocs(self) -> None:
        for delimiter, quoted, tabs, command in self.heredocs:
            lines: list[str] = []
            while self.i < len(self.text):
                nl = self.text.find("\n", self.i)
                line = self.text[self.i :] if nl < 0 else self.text[self.i : nl]
                self.i = len(self.text) if nl < 0 else nl + 1
                if (line.lstrip("\t") if tabs else line) == delimiter:
                    break
                lines.append(line)
            body = "\n".join(lines)
            command.bodies.append(body)
            if not quoted:  # its substitutions run, as in double quotes
                inner = _Shell(body, self.depth + 1)
                inner.double_quoted(end_on_quote=False)
                self.commands += inner.commands
        self.heredocs = []

    def word(self, stop: str | None) -> Word:
        w, braced = Word(), False
        while self.i < len(self.text):
            c = self.peek()
            if c in " \t\n;&|()<>" or (stop is not None and c == stop):
                break
            if c == "\\":
                nxt = self.peek(2)[1:]
                self.i += 2
                if nxt != "\n":
                    w.text += nxt
                    w.quoted = True
            elif c == "'":
                end = self.text.find("'", self.i + 1)
                if end < 0:
                    raise Unreadable("unclosed quote")
                w.text += self.text[self.i + 1 : end]
                w.quoted = True
                self.i = end + 1
            elif c == '"':
                self.i += 1
                w.quoted = True
                text, dynamic = self.double_quoted(end_on_quote=True)
                w.text += text
                w.dynamic = w.dynamic or dynamic
            elif c == "$" or c == "`":
                self.dollar(w)
            else:
                if c in "*?[":
                    w.pattern = True
                elif c == "{":
                    braced = True
                w.text += c
                self.i += 1
        if braced and re.search(r"\{[^}]*(,|\.\.)[^}]*\}", w.text):
            w.pattern = True  # a brace expansion
        if not w.text and not w.quoted and not w.dynamic:
            raise Unreadable(f"unexpected {self.peek()!r}")
        return w

    def dollar(self, w: Word) -> None:
        """An expansion or a substitution: the word's value is not known here."""
        w.dynamic = True
        if self.peek() == "`":
            self.i += 1
            self.nested("`")
        elif self.peek(2) == "$(":
            self.i += 2
            self.nested(")")
        elif self.peek(2) == "${":
            depth, j = 0, self.i + 1
            while j < len(self.text):
                depth += {"{": 1, "}": -1}.get(self.text[j], 0)
                if depth == 0:
                    break
                j += 1
            if j >= len(self.text):
                raise Unreadable("unclosed ${")
            inner = _Shell(self.text[self.i + 2 : j], self.depth + 1)
            inner.double_quoted(end_on_quote=False)
            self.commands += inner.commands
            self.i = j + 1
        elif self.peek(2) in ("$'", '$"'):
            self.i += 1
            self.word_part_quoted()
        else:
            self.i += 1
            w.text += "$"

    def word_part_quoted(self) -> None:
        if self.peek() == '"':
            self.i += 1
            self.double_quoted(end_on_quote=True)
            return
        j = self.i + 1
        while j < len(self.text) and self.text[j] != "'":
            j += 2 if self.text[j] == "\\" else 1
        if j >= len(self.text):
            raise Unreadable("unclosed quote")
        self.i = j + 1

    def double_quoted(self, end_on_quote: bool) -> tuple[str, bool]:
        text, dynamic = "", False
        while self.i < len(self.text):
            c = self.peek()
            if end_on_quote and c == '"':
                self.i += 1
                return text, dynamic
            if c == "\\" and self.peek(2)[1:] in ("$", "`", '"', "\\", "\n"):
                if self.peek(2)[1:] != "\n":
                    text += self.peek(2)[1:]
                self.i += 2
            elif c in "$`" and (
                c == "`"
                or self.peek(2)[1:2] in ("(", "{")
                or self.peek(2)[1:2].isalnum()
                or self.peek(2)[1:2] in "_@*#?-$!"
            ):
                w = Word()
                self.dollar(w)
                dynamic = True
            else:
                text += c
                self.i += 1
        if end_on_quote:
            raise Unreadable("unclosed quote")
        return text, dynamic


def _segments(text: str) -> list[str]:
    """The parts of a word that could name a program: the word, and what an option or an
    assignment in it holds, each by its last path element."""
    parts = [text, *re.split(r"[=:,]", text)]
    return [re.split(r"[/\\]", part)[-1].lower() for part in parts if part]


def _names_maity(word: Word, *, anywhere: bool = False) -> bool:
    """Whether the word, as the shell runs it, can be `maity`: its value names it, or its
    value depends on an expansion, a glob or a brace and so may. `anywhere`: an option or
    assignment inside the word counts too (a wrapper's arguments)."""
    if word.dynamic or word.pattern:
        return True
    names = _segments(word.text) if anywhere else _segments(word.text)[:1]
    return any(name in _NAMES for name in names)


def _wrapped(words: list[Word], depth: int) -> bool:
    """Whether a wrapper's arguments run `maity`: one of them names it, or holds a command
    line that does."""
    for word in words:
        if _names_maity(word, anywhere=True):
            return True
        if re.search(r"[\s;&|<>()`$]", word.text) and behind(word.text, depth + 1):
            return True
    return False


def _mentions(commands: list[Command]) -> bool:
    texts = [w.text for c in commands for w in c.words] + [b for c in commands for b in c.bodies]
    return any("maity" in text.lower() or "$" in text for text in texts)


def behind(command: str, depth: int = 0) -> bool:
    """Whether the line runs `maity` other than as the plain first word of a line the hook
    has already decided: it decides on the words the shell runs, after quoting, escapes and
    line continuations. A word in command position that can become `maity` counts, and so
    do a wrapper's arguments and the scripts it is given. A line it cannot take apart
    counts, whatever it holds."""
    try:
        shell = _Shell(command, depth)
        shell.run()
    except (Unreadable, RecursionError):
        return True
    for cmd in shell.commands:
        words = list(cmd.words)
        while words and (
            (_ASSIGNMENT.match(words[0].text) and not words[0].quoted)
            or (words[0].text in KEYWORDS and not words[0].quoted and not words[0].dynamic)
        ):
            words.pop(0)
        if not words:
            continue
        program, args = words[0], words[1:]
        if _names_maity(program):
            return True
        name = _segments(program.text)[0].removesuffix(".exe")
        if name == "find":
            runs = [i for i, w in enumerate(args) if w.text in FIND_RUNS]
            if runs and _wrapped(args[runs[0] + 1 :], depth):
                return True
            continue
        if name not in WRAPPERS:
            continue
        if _wrapped(args, depth):
            return True
        for body in cmd.bodies:
            if behind(body, depth + 1) or "maity" in body.lower():
                return True
        if cmd.fed and not cmd.bodies and _mentions(shell.commands):
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
