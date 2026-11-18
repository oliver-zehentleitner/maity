"""The hook a placed Claude Code session runs before every tool call, under its sandbox.

`maity` runs outside the sandbox (`excludedCommands`). This hook lets a command line that
starts with `maity` through only when it is one plain call: words of letters, digits and
`_-./:=@%+,~^#`, quoted text without expansions, and nothing else. A pipe, a chain, a
redirect, a background `&`, a substitution, a heredoc, a newline or a `$` is refused before
the command runs (cli/context/runner.md). For any other line the hook decides on the words
the shell runs (`behind`) and passes it only when it can tell what every command in it runs:
one that may run `maity` other than as the plain first word is refused, and so is one it
cannot vouch for. Any other tool call, and a line it passes, is left to the permission
rules: the hook prints nothing and exits 0.

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
    "ssh", "trap", "source", ".", "hash", "bind", "complete", "compgen", "mapfile",
    "readarray", "fc",
    "sh", "bash", "dash", "zsh", "ksh", "mksh", "ash", "fish", "csh", "tcsh", "pwsh",
    "powershell",
})  # fmt: skip
# Shell words after which the next word is in command position again.
STRUCTURE = frozenset({"then", "do", "else", "elif", "if", "while", "until", "!", "{"})
# Shell words that end a construct, and ones whose own words are data, not programs.
CLOSERS = frozenset({"fi", "done", "esac", "}", "]]"})
DATA = frozenset({"for", "select", "case"})
# Shell words the hook does not take apart: a line with one is refused.
REFUSED_WORDS = frozenset({"function", "coproc"})
# Programs on WRAPPERS that take a script from their input: fed by a pipe or a file, they run
# what the hook cannot see.
CODE_READERS = frozenset({
    "sh", "bash", "dash", "zsh", "ksh", "mksh", "ash", "fish", "csh", "tcsh", "pwsh",
    "powershell", "busybox", "source", ".", "ssh", "su", "eval", "sudo", "doas", "runuser",
    "script", "xargs", "parallel",
})  # fmt: skip
# A program word the hook vouches for: plain characters only.
_PROGRAM = re.compile(r"[A-Za-z0-9_.+/@%:,~\[\]-]+")
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
    lead: str = ""  # its literal start, before any quoting or expansion

    @property
    def literal(self) -> bool:
        """Plain text: nothing quoted, expanded or matched, and not empty."""
        return bool(self.text) and not (self.quoted or self.dynamic or self.pattern)


@dataclass
class Command:
    """One simple command: its words, the text it reads as input when the shell gives it one
    here, and whether something else feeds it."""

    words: list[Word] = field(default_factory=list)
    bodies: list[str] = field(default_factory=list)
    fed: bool = False  # a pipe or a file feeds it: input the hook does not see
    expanded_body: bool = False  # a here-document whose body the shell expands first


class _Shell:
    """Takes a command line apart the way the shell would, as far as the hook needs: words,
    simple commands, substitutions, here-documents. What it cannot read raises Unreadable."""

    def __init__(self, text: str, depth: int) -> None:
        if depth > _DEPTH:
            raise Unreadable("nested too deep")
        self.text, self.i, self.depth = text, 0, depth
        self.commands: list[Command] = []
        self.heredocs: list[tuple[str, bool, bool, Command]] = []
        # Here-document bodies with no closing line: not taken as data.
        self.open_bodies: list[str] = []
        # The text of arithmetic, which never names a program.
        self.arithmetic_texts: list[str] = []
        self.word_end = -1

    def peek(self, n: int = 1) -> str:
        return self.text[self.i : self.i + n]

    def nested(self, stop: str) -> None:
        """A substitution or subshell from here to `stop`: its commands are commands too."""
        inner = _Shell(self.text, self.depth + 1)
        inner.i = self.i
        inner.run(stop)
        self.i = inner.i
        self.absorb(inner)

    def absorb(self, inner: _Shell) -> None:
        self.commands += inner.commands
        self.open_bodies += inner.open_bodies
        self.arithmetic_texts += inner.arithmetic_texts

    def arithmetic(self, close: str) -> None:
        """Arithmetic up to `close`: only its substitutions run."""
        start, depth = self.i, 0
        opening = "(" if close == "))" else "["
        closing = close[0]
        while self.i < len(self.text):
            if depth == 0 and self.text.startswith(close, self.i):
                break
            c = self.peek()
            if c == "$" and self.peek(2)[1:2] in ("(", "{", "["):
                self.dollar(Word())
                continue
            if c == "`":
                self.dollar(Word())
                continue
            depth += 1 if c == opening else -1 if c == closing else 0
            self.i += 1
        else:
            raise Unreadable(f"no closing {close}")
        self.arithmetic_texts.append(self.text[start : self.i])
        self.i += len(close)

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
            elif self.peek(2) == "((":
                self.i += 2
                self.arithmetic("))")
                end()
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
                if cur.words and self.i == self.word_end and not cur.words[-1].literal:
                    raise Unreadable("a redirect glued to a word it does not take")
                if cur.words and self.i == self.word_end and cur.words[-1].text.startswith("{"):
                    raise Unreadable("a redirect to a named descriptor")
                self.i = m.end()
                self.redirect(m.group(1), cur)
            elif op := next((o for o in _OPERATORS if self.text.startswith(o, self.i)), None):
                self.i += len(op)
                end(piped=op in ("|", "|&"))
            else:
                cur.words.append(self.word(stop))
                self.word_end = self.i
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
            if not target.quoted:
                cur.expanded_body = True
        elif op == "<<<":
            cur.bodies.append(target.text)
            cur.expanded_body = cur.expanded_body or target.dynamic
        elif op in ("<", "<>", "<&"):
            cur.fed = True

    def read_heredocs(self) -> None:
        for delimiter, quoted, tabs, command in self.heredocs:
            lines: list[str] = []
            closed = False
            while self.i < len(self.text):
                nl = self.text.find("\n", self.i)
                line = self.text[self.i :] if nl < 0 else self.text[self.i : nl]
                self.i = len(self.text) if nl < 0 else nl + 1
                if (line.lstrip("\t") if tabs else line) == delimiter:
                    closed = True
                    break
                lines.append(line)
            body = "\n".join(lines)
            command.bodies.append(body)
            if not closed:
                self.open_bodies.append(body)
            if not quoted:  # its substitutions run, as in double quotes
                inner = _Shell(body, self.depth + 1)
                inner.double_quoted(end_on_quote=False)
                self.absorb(inner)
        self.heredocs = []

    def word(self, stop: str | None) -> Word:
        w, braced, bracketed = Word(), False, False
        while self.i < len(self.text):
            c = self.peek()
            if c in " \t\n;&|()<>" or (stop is not None and c == stop):
                break
            if (
                w.lead == w.text
                and c not in "\\'\"$`"
                and not (c in "@!+*?" and self.peek(2)[1:] == "(")
            ):
                w.lead += c
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
            elif c in "@!+*?" and self.peek(2)[1:] == "(":
                depth, j = 0, self.i + 1
                while j < len(self.text):
                    depth += {"(": 1, ")": -1}.get(self.text[j], 0)
                    if depth == 0:
                        break
                    j += 1
                if j >= len(self.text):
                    raise Unreadable("unclosed pattern")
                w.text += self.text[self.i : j + 1]
                w.pattern = True
                self.i = j + 1
            else:
                if c in "*?":
                    w.pattern = True
                elif c == "[":
                    bracketed = True
                elif c == "{":
                    braced = True
                w.text += c
                self.i += 1
        if braced and re.search(r"\{[^}]*(,|\.\.)[^}]*\}", w.text):
            w.pattern = True  # a brace expansion
        if bracketed and re.search(r"\[.+\]", w.text):
            w.pattern = True  # a bracket expression
        if not w.text and not w.quoted and not w.dynamic:
            raise Unreadable(f"unexpected {self.peek()!r}")
        return w

    def dollar(self, w: Word) -> None:
        """An expansion or a substitution: the word's value is not known here."""
        w.dynamic = True
        if self.peek() == "`":
            self.i += 1
            self.nested("`")
        elif self.peek(3) == "$((":
            self.i += 3
            self.arithmetic("))")
        elif self.peek(2) == "$[":
            raise Unreadable("legacy arithmetic")
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
            if re.search(r"['\"`\\]|\$\(", self.text[self.i + 2 : j]):
                raise Unreadable("quoting or a substitution inside ${…}")
            inner = _Shell(self.text[self.i + 2 : j], self.depth + 1)
            inner.double_quoted(end_on_quote=False)
            self.absorb(inner)
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
                or self.peek(2)[1:2] in ("(", "{", "[")
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
    return [re.split(r"[/\\]", part)[-1].lower() for part in parts if part] or [""]


def _assignment(word: Word) -> bool:
    """A `NAME=value` word: the shell sets the name, whatever quoting the value has."""
    return _ASSIGNMENT.match(word.lead) is not None


def _candidates(text: str) -> list[str]:
    """What a program that runs others may take from one argument as a program or a command
    line: the argument, what follows each `=`, and for an option every rest of it."""
    found = [text, *(text[m.end() :] for m in re.finditer("=", text))]
    if text.startswith("-"):
        found += [text[i:] for i in range(1, len(text))]
    return found


def _runs_maity(words: list[Word], depth: int) -> bool:
    """Whether the arguments of a program that runs others may run `maity`. Every argument
    must be plain text, each of its candidates read as a command line of its own; only an
    assignment's value may be an expansion."""
    for word in words:
        if _assignment(word):
            value = word.text.split("=", 1)[1]
            texts = [] if word.dynamic or word.pattern else [value, *_candidates(value)[1:]]
        elif word.dynamic or word.pattern:
            return True
        else:
            texts = _candidates(word.text)
        for text in texts:
            if any(name in _NAMES for name in _segments(text)):
                return True
            if text and behind(text, depth + 1):
                return True
    return False


def _refused(cmd: Command, depth: int) -> bool:
    """Whether one simple command may run `maity` or is one the hook cannot vouch for."""
    words = list(cmd.words)
    while words:
        first = words[0]
        if _assignment(first):
            words.pop(0)
        elif first.literal and first.text in STRUCTURE:
            words.pop(0)
        elif first.literal and first.text == "time":
            words.pop(0)
            while words and words[0].literal and words[0].text in ("-p", "--"):
                words.pop(0)
        else:
            break
    if not words:
        return False
    program, args = words[0], words[1:]
    if program.literal and program.text in CLOSERS:
        return False
    if not program.literal or not _PROGRAM.fullmatch(program.text):
        return True
    name = _segments(program.text)[0]
    if name in _NAMES or name in REFUSED_WORDS:
        return True
    if name in DATA or name in CLOSERS:
        return False
    if name == "find":
        runs = [i for i, w in enumerate(args) if w.literal and w.text in FIND_RUNS]
        return bool(runs) and _runs_maity(args[runs[0] + 1 :], depth)
    if name.removesuffix(".exe") not in WRAPPERS:
        return False
    if _runs_maity(args, depth):
        return True
    reads_code = name.removesuffix(".exe") in CODE_READERS
    if reads_code and cmd.fed:
        return True  # a script from a pipe or a file: not something the hook can read
    if cmd.bodies and (cmd.expanded_body or reads_code and cmd.fed):
        return True
    return any(behind(body, depth + 1) or "maity" in body.lower() for body in cmd.bodies)


def behind(command: str, depth: int = 0) -> bool:
    """Whether the line may run `maity` other than as the plain first word of a line the
    hook has already decided, or is one the hook cannot take apart: it passes a line only
    when it can tell what every command in it runs."""
    try:
        shell = _Shell(command, depth)
        shell.run()
    except (Unreadable, RecursionError):
        return True
    if any("maity" in text.lower() for text in shell.arithmetic_texts):
        return True
    if shell.open_bodies:
        return True
    return any(_refused(cmd, depth) for cmd in shell.commands)


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
    try:
        return BEHIND if behind(command) else None
    except Exception:  # noqa: BLE001 - anything unforeseen refuses the call
        return BEHIND


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
