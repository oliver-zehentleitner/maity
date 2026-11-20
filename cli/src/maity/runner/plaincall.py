"""The hook a placed Claude Code session runs before every tool call, under its sandbox.

`maity` runs outside the sandbox (`excludedCommands`). This hook lets a command line whose
first word is `maity`, or whose words before a word `maity` are only assignments to the names
in `ALLOWED_BEFORE_MAITY` (`held`), through only when it is one plain call: words of letters,
digits and `_-./:=@%+,~^#`, quoted text without expansions, and nothing else. A pipe, a chain, a
redirect, a background `&`, a substitution, a heredoc, a newline or an unescaped `$` outside
single quotes is refused before the command runs (cli/context/runner.md). Where the line's
command starts is read past its leading comment lines and blank lines, as Claude Code reads
it; the line itself is still judged whole, so such a line is refused. Any other line in
which `maity` is a word (`prefixed`) is
refused outright: an assignment to another name, a command word, a keyword, `!`, a redirection,
a subshell or a group before it, or `maity` by a path. A word counts as `maity` (and as
`runner`) also once its backslashes and quotes are taken off (`_reads_as`), and a word that
holds a `{` also as each part of it between `{`, `,` and `}` and as each word its brace
expansion makes, as Bash makes them from the word as written, quotes and all, and from its
text read again, up to `BRACE_LIMIT` words; a word that makes more, or whose braces the hook
does not read, is not read and counts as both (`_names`). On any line, a word
`maity` followed later by a word `runner`, as `calls_runner` splits words, is refused as well:
those commands are the runner's own, and the runner never starts them through an agent's tool
call. A line that names `maity` anywhere (`names_maity`) is refused when it holds a comment, a
heredoc or more than one line (`read_whole`), and any line is refused when its quotes never
close, when it holds `$'...'` text with a backslash or an unquoted `$"`, or when its quoted
text is nested too deep: the hook does not read such lines to the end. Nor does it read a
line that holds a construct it does not model exactly (`_unmodelled`): such a line is
refused as well. A command the shell
builds from values the hook cannot know, such as globs against files and expansions of
variables or of input, is not read. Any other tool call is left to the
permission rules: the hook prints nothing and exits 0.

It reads Claude Code's PreToolUse input on stdin and refuses with exit 2 and the reason on
stderr. Input it cannot read is refused too, and so is a call the hook fails on.
"""

from __future__ import annotations

import itertools
import json
import re
import sys
from collections.abc import Sequence
from typing import TypeAlias

# Characters a word may hold unquoted: none of them makes the shell do anything but take it
# as text (`#` starts a comment only at a word's start, where the rest is ignored).
UNQUOTED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./:=@%+,~^#")
# Inside double quotes the shell still expands `$` and backticks; `!` is left out as well.
NOT_IN_DOUBLE_QUOTES = frozenset("$`!\n")
# Leading spaces and characters a plain call may not hold are skipped before looking for
# `maity`, so a line counts as a maity call however the harness trims it; `plain` refuses
# what was skipped. A character a plain call may hold (`/`, `.`, `:` and the rest of
# `UNQUOTED`, a quote, a backslash) is not skipped: before `maity` it makes a path, another
# command or a quoted or escaped word of its own (`"[" maity`, `\! maity`, `"" maity`),
# which the word split reads. After `maity` only a space, a tab, an operator or the line's
# end may follow: anything else makes it part of a longer word, which the word split reads
# (`_placement`).
_MAITY = re.compile(r"[^0-9A-Za-z_\-./:=@%+,~^#'\"\\]*maity(?=[ \t();<>|&\n]|\Z)", re.IGNORECASE)

# Unquoted characters that end a word, besides spaces and tabs: the shell's operators.
_SEPARATORS = frozenset("();<>|&\n")
# Unquoted characters after which the shell may still change a word: an expansion, a glob, a
# brace.
_EXPANDS = frozenset("$`*?[{")
# How deep quoted text is read again as a line of its own (`sh -c '...'`).
_NESTING = 4
# How many words the brace expansion of one word may make, and how many brace groups it may
# hold, before the word is not read (`_expand`).
BRACE_LIMIT = 256
# Characters after which a `#` is inside a word, not the start of a comment: printable ASCII
# that is neither a space nor one of the shell's operators. After anything else, or at the
# line's start, a `#` counts as a comment.
_IN_WORD = frozenset(chr(c) for c in range(0x21, 0x7F)) - frozenset("|&;()<>`")

RUNNER_REFUSED = (
    "`maity runner` is the runner's own command and does not run from a placed session's tool "
    "call: a line where a word `runner` follows a word `maity` is refused, and so is a line "
    "the hook cannot read to the end (one that names `maity` and holds a comment, a heredoc "
    "or more than one line; a quote that never closes; `$'...'` text with a backslash or a "
    '`$"`; quoted text nested too deep; a word whose braces make more than '
    f"{BRACE_LIMIT} words or that the hook does not read; a construct the hook does not read "
    "exactly: `eval`, `source`, `.`, `trap` or `bash -c` with a quoted or expanded word, "
    "`$'...'`, a backslash-newline, a backtick or `${...}` that holds quotes, a substitution "
    "in a word with braces, a comment on a line with braces, a comment in `$(...)`, a heredoc "
    "in `$(...)` with a body line that starts with the delimiter and has a `)` after it). Run "
    "each `maity` command on a line of its own, without a comment; text that holds both "
    "words goes in a file in this clone, passed with `--body-file`."
)
REFUSED = (
    "A `maity` command runs only as one plain call: nothing piped, chained, redirected, sent to "
    "the background or substituted, no heredoc, no newline and no `$` outside single quotes. "
    "Run it alone; put text in single quotes, or write it to a file in this clone and pass that "
    "file (`--body-file`)."
)
FAILED = (
    "The hook failed on this tool call, so it is refused. Run each `maity` command alone, as "
    "one plain call; text goes in a file in this clone, passed with `--body-file`."
)
PREFIX_REFUSED = (
    "A line in which `maity` is a word runs only as one plain `maity …` call at the start of "
    "the line, after nothing but assignments to NO_COLOR, LANG, LC_* or TZ: no "
    "other assignment, command, keyword, `!`, redirection, subshell or group before it, and "
    "`maity` by its name, not by a path. Run "
    "`maity …` at the start of the line; text that mentions `maity` goes in a file in this "
    "clone, passed with `--body-file`."
)
# The reason for a refused line whose words before `maity` assign MAITY_WAIT_TIMEOUT
# (`_assigns_wait_timeout`): the same rule, led by the way to set a wait's timeout here.
WAIT_TIMEOUT_REFUSED = (
    "MAITY_WAIT_TIMEOUT does not go before `maity` here: run `maity wait --timeout N` "
    "instead. " + PREFIX_REFUSED
)


# The names an assignment before `maity` may set, each by its exact name; `LC_*` is the one
# family. An assignment can pick the program the shell runs or load code into it (`PATH`,
# `LD_PRELOAD`, `PYTHONPATH`, `BASH_ENV`, ...), and the runner's own `MAITY_` variables decide
# what maity trusts (the placement, the clone's `.git`, the state directory), so the names are
# allowed, not refused, and no `MAITY_` name is among them: `MAITY_WAIT_TIMEOUT=N maity wait`
# would not get the credential in a placement, so a placed agent passes `maity wait --timeout N`
# (cli/context/runner.md). `test_plaincall.py` fails when a `MAITY_` name is added here.
ALLOWED_BEFORE_MAITY = ("NO_COLOR", "LANG", "LC_*", "TZ")
# An assignment to MAITY_WAIT_TIMEOUT, unquoted, with `=` or `+=`: only for the reason a
# refused line gets (`WAIT_TIMEOUT_REFUSED`), never to let a line through.
_WAIT_ASSIGNMENT = re.compile(r"MAITY_WAIT_TIMEOUT\+?=")
# An allowed name, unquoted, then `=`; `+=` is refused as well. The value is not judged here:
# `plain` refuses one that expands.
_ASSIGNMENT = re.compile(
    "(?:"
    + "|".join(
        re.escape(name[:-1]) + "[A-Z0-9_]+" if name.endswith("*") else re.escape(name)
        for name in ALLOWED_BEFORE_MAITY
    )
    + ")="
)


def _past_comment_lines(command: str) -> str:
    """The line without its leading comment lines and blank lines: lines whose first
    character after spaces and tabs is a `#`, or that hold only spaces and tabs. Claude Code
    reads the command of a call after them, and so does `_placement` when it decides where
    the line's command starts. Only that decision reads what is left: `plain` and
    `read_whole` still read the whole line, so a line that holds a comment line and names
    `maity` is refused all the same (cli/context/runner.md)."""
    lines = command.split("\n")
    k = 0
    while k < len(lines) and lines[k].lstrip(" \t")[:1] in ("", "#"):
        k += 1
    return "\n".join(lines[k:])


def _placement(command: str) -> str | None:
    """Where `maity` stands on the line, read past its leading comment lines and blank lines
    (`_past_comment_lines`) and its leading assignments: "held" when the line's first word
    is `maity` (`_MAITY`), when every word before its first word `maity` (`_is_maity`) is an
    assignment `_ASSIGNMENT` allows and that word is `maity` alone (in any case, not by a
    path), or when a quote never closes on a line that names `maity`; "prefixed" when
    `maity` is a word after anything else (an assignment to another name included), by a
    path, or a word of quoted text that holds spaces or operators, read again as a line
    (`_maity_in_text`); None when `maity` is no word of the line."""
    command = _past_comment_lines(command)
    if _MAITY.match(command) is not None:
        return "held"
    try:
        words = _split(command)
    except _Unreadable:
        return "held" if names_maity(command) else None
    for index, (text, _, _, written) in enumerate(words):
        if _is_maity(text, written):
            before = words[:index]
            if text.lower() != "maity" or not all(
                _ASSIGNMENT.match(command, at) for _, _, at, _ in before
            ):
                return "prefixed"
            return "held"
    if any(_maity_in_text(text, 1) for text, _, _, _ in words):
        return "prefixed"
    return None


def _assigns_wait_timeout(command: str) -> bool:
    """Whether a word before the line's first word `maity` (`_is_maity`), read past its
    leading comment lines and blank lines as `_placement` reads it, is an unquoted assignment
    to MAITY_WAIT_TIMEOUT (`_WAIT_ASSIGNMENT`). It only picks the reason for a line that is
    refused anyway."""
    command = _past_comment_lines(command)
    try:
        words = _split(command)
    except _Unreadable:
        return False
    for text, _, at, written in words:
        if _is_maity(text, written):
            return False
        if _WAIT_ASSIGNMENT.match(command, at):
            return True
    return False


def _maity_in_text(text: str, depth: int) -> bool:
    """Whether `maity` is a word of quoted text that holds spaces or operators, read again as
    a line the way `calls_runner` reads it, up to `_NESTING` levels deep (`depth` is the
    level of `text`, 1 for quoted text on the line itself); text nested deeper counts when it
    names `maity` anywhere (`names_maity`)."""
    if not any(c in " \t" or c in _SEPARATORS for c in text):
        return False
    if depth > _NESTING:
        return names_maity(text)
    try:
        words = _words(text)
    except _Unreadable:
        return names_maity(text)
    return any(
        _is_maity(word, written) or _maity_in_text(word, depth + 1) for word, _, written in words
    )


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


def _is_maity(word: str, written: str) -> bool:
    """Whether a word names `maity`: by any path, in any case, however its start is trimmed,
    also as `_names` takes it (`written` as `_split` gives it). A word in which `$'` is
    followed by a backslash counts whatever it holds."""
    if re.search(r"\$'.*\\", word, re.DOTALL):
        return True
    return any(
        re.sub(r"^[^0-9A-Za-z]+", "", name.rsplit("/", 1)[-1]).lower() == "maity"
        for name in _names(word, written)
    )


def _is_runner(word: str, written: str) -> bool:
    """Whether a word is `runner`, in any case, also as `_names` takes it (`written` as
    `_split` gives it)."""
    return any(name.lower() == "runner" for name in _names(word, written))


def _names(word: str, written: str) -> tuple[str, ...]:
    """The word as `_reads_as` takes it and, when it holds a `{`, each word its brace
    expansion makes (`_brace_names`): a brace expansion may make a word of its own of each
    alternative, joined with the text around it. A word whose braces are not read counts as
    `maity` and as `runner`."""
    names = _reads_as(word)
    if "{" not in word and "{" not in written:
        return names
    made = _brace_names(word, written)
    if made is None:
        return (*names, "maity", "runner")
    return (*names, *made)


def _brace_names(word: str, written: str) -> list[str] | None:
    """The words brace expansion makes of a word (`_brace_words`): of the word as it is
    `written`, as this shell expands it, and of its text `word` and of each word that
    expansion makes, as a shell that reads them again expands them (`eval`), up to
    `_NESTING` readings deep, with what each reading makes read again. A word with a space
    or an operator is read again as the words between them (`_pieces`), and counts as each
    of them too; text whose quotes do not close is not read again, since a shell that reads
    it stops there. None when one of them is not read, when a word the last reading made
    holds a `{` and would change if read once more, or when they make more than
    `BRACE_LIMIT` words in all."""
    made: list[str] = []
    first = [word]
    if "{" in written:
        expanded = _brace_words(written)
        if expanded is None:
            return None
        made += expanded
        first += expanded
    seen, again = {written}, first
    for _ in range(_NESTING):
        following: list[str] = []
        for text in _pieces(again):
            if "{" not in text or text in seen:
                continue
            seen.add(text)
            try:
                _split(text)
            except _Unreadable:
                continue
            read = _brace_words(text)
            if read is None:
                return None
            made += read
            following += read
            if len(set(made)) > BRACE_LIMIT:
                return None
        again = following
    if any("{" in text and text not in seen for text in _pieces(again)):
        return None  # a further reading would change it: past the bound, not read
    if len(set(made)) > BRACE_LIMIT:
        return None
    return made + [part for part in _pieces(made) if part not in made]


def _pieces(words: list[str]) -> list[str]:
    """The words, each split at spaces, tabs and operators, as a shell that reads it again
    as a line splits it."""
    return [part for w in words for part in re.split(r"[ \t();<>|&\n]+", w) if part]


def _brace_words(
    written: str, numbers: bool = False, bash: tuple[int, int] | None = None
) -> list[str] | None:
    """The words brace expansion makes of a word as `written` (`_expand`), each with its
    quotes and backslashes then taken off, as the shell's quote removal takes them off: a
    backslash a range of letters makes (`{V..a..6}`) goes too. Unless `bash` names one
    version, the words of Bash 5.2 and of Bash 5.3 together, since the two read some braces
    differently and either may run the line. None when an expansion is not read, or when a
    word it makes does not read as one (`_split`)."""
    made: list[str] = []
    for version in [(5, 2), (5, 3)] if bash is None else [bash]:
        some = _expand(written, numbers=numbers, bash=version)
        if some is None:
            return None
        made += [one for one in some if one not in made]
    words: list[str] = []
    for one in made:
        try:
            split = _split(one)
        except _Unreadable:
            return None
        words += [text for text, _, _, _ in split] or [""]  # a lone backslash: a quoted null
    return words


# The characters at which Bash's scan of a word for braces (`_expand`) does anything but step
# on.
_BRACE_STOPS = re.compile(r"[\\$'\"`<>{},.]")
# Integers as Bash reads the ends and the step of a range (`strtoimax`), and its limits.
_INTEGER = re.compile(r"[ \t\n\v\f\r]*([-+]?[0-9]+)")
_INTMAX = 2**63 - 1
# More digits than an integer Bash reads can have, leading zeros aside: Bash's range check
# (`ERANGE`) refuses it, and Python is not asked to convert it.
_DIGITS = 19
_INT_MAX = 2**31 - 1
# What `_expand` reads a word as: text, the words of a range, and groups of alternatives.
_Part: TypeAlias = "str | list[str] | tuple[list[_Part], ...]"


class _Unsure(ValueError):
    """Braces `_expand` does not read as Bash does: their words are not known."""


class _Over(ValueError):
    """Braces that make more words, or hold more groups, than `_expand` makes."""


def _has_comma(text: str) -> bool:
    """Whether Bash finds a `,` in the text between a group's braces: any `,` that no
    backslash escapes, quoted or not (`brace_expand`)."""
    i = 0
    while i < len(text):
        if text[i] == ",":
            return True
        i += 2 if text[i] == "\\" else 1
    return False


def _expand(
    word: str, limit: int = BRACE_LIMIT, numbers: bool = False, bash: tuple[int, int] = (5, 2)
) -> list[str] | None:
    """The words Bash's brace expansion makes of `word` as it is written, quotes and
    backslashes and all (`braces.c` of the `bash` version given, 5.2 or 5.3, the two that
    read braces differently), before quote removal, or None when they are
    not known: more than `limit` words or brace groups, braces nested deeper than the stack
    allows, a letter range that makes a backtick (the shell reads it as the start of a
    command), or a part the reading below does not cover. Quoted and escaped characters,
    and substitutions, are passed over as Bash passes over them: they open, close and split
    no group. A `{` opens a group when a `}`
    closes it: the first `}` outside nested braces after a `,` or a `..` outside nested
    braces, a `..` right before that `}` not counting (a `}` before that is text), except a
    `{` at the word's start, or after a space, followed by a `}` or a space. Bash 5.3 counts
    a `..` only before the first such `,`, and a group with a `..` and no `,` opens only when
    its text starts like a range (`valid_seqterm`). A scan that
    visits more characters than a bound set by the word's length does not read it. A group
    with a `,` makes a word of each alternative, one without one a range (`_sequence`), or
    stays text when it is none; any other brace is text, and a group after it, or inside
    it, still expands. A word the expansion leaves empty is dropped. Unless `numbers`, a
    number range makes only its first number: its other words differ from that one only in
    digits, which neither `maity` nor `runner` holds, so the names read the same."""
    budget = 64 * len(word) + 2**20  # characters the scan may visit: the work stays bounded
    groups = 0

    def substitution(i: int, hi: int) -> int:
        """The index of the `)` that closes the substitution opened at `i`, which Bash steps
        over by its own parse (`_substitution_end`); _Unsure when that is not known."""
        try:
            close = _substitution_end(word, i)
        except ValueError:
            raise _Unsure(word) from None
        if close >= hi:
            raise _Unsure(word)
        return close

    kind = ""  # what the last scan for a `}` found first: "," or ".." (Bash 5.3's `btype`)
    new = bash >= (5, 3)

    def gobble(lo: int, hi: int, i: int, satisfy: str) -> int | None:
        """Where Bash's `brace_gobbler` stops in `word[lo:hi]` from `i`: the index of the
        `satisfy` that ends the scan, or None at the end."""
        nonlocal budget, kind
        level, quoted, commas, pass_next = 0, "", int(satisfy != "}"), False
        kind = ""
        while True:
            if pass_next:
                pass_next, i = False, i + 1
            elif not quoted:
                stop = _BRACE_STOPS.search(word, i, hi)
                i = hi if stop is None else stop.start()
            if i >= hi:
                return None
            budget -= 1
            if budget < 0:
                raise _Over(word)
            c, after = word[i], word[i + 1 : min(i + 2, hi)]
            if c == "\\" and quoted in ("", '"', "`"):
                pass_next = True
            elif c == "$" and after == "{" and quoted != "'":
                if word[i + 2 : min(i + 3, hi)] in (" ", "\t", "\n", "|", "("):
                    raise _Unsure(word)  # Bash 5.3 runs `${ ...; }` as a command
                pass_next, level = True, level + (not quoted)
            elif quoted:
                if c == quoted:
                    quoted = ""
                elif quoted == '"' and c == "$" and after == "(":
                    i = substitution(i, hi)
            elif c in "\"'`":
                quoted = c
            elif c in "$<>" and after == "(":
                i = substitution(i, hi)
            elif c == satisfy and level == 0 and commas:
                if not (
                    c == "{"
                    and (i == lo or word[i - 1] in " \t\n")
                    and after != ""
                    and after in " \t\n}"
                ):
                    return i
            elif c == "{":
                level += 1
            elif c == "}" and level:
                level -= 1
            elif satisfy == "}" and level == 0 and c == ",":
                commas, kind = commas + 1, ","
            elif satisfy == "}" and level == 0 and word.startswith("..", i) and i + 1 < hi:
                if word[i + 2 : min(i + 3, hi)] != "}" and not (new and kind):
                    commas, kind = commas + 1, ".."
            i += 1

    def parse(lo: int, hi: int) -> list[_Part]:
        """`word[lo:hi]` as text and groups in turn: a group is the words of its range or
        the parts of each of its alternatives (`brace_expand`)."""
        nonlocal groups
        parts: list[_Part] = []
        while True:
            i = lo
            while True:  # the first `{` that a `}` closes
                start = gobble(lo, hi, i, "{")
                end = None if start is None else gobble(lo, hi, start + 1, "}")
                if start is not None and end is not None and new and kind == "..":
                    end = end if _ranges_like(word, start, end) else None
                if start is None or end is not None:
                    break
                i = start + 1
            if start is None or end is None:
                parts.append(word[lo:hi])
                return parts
            parts.append(word[lo:start])
            group: _Part | None
            if (kind == "..") if new else not _has_comma(word[start + 1 : end]):
                group = _sequence(word[start + 1 : end], limit, numbers, bash)
            else:
                alternatives, a = [], start + 1
                while True:
                    b = gobble(start + 1, end, a, ",")
                    alternatives.append(parse(a, end if b is None else b))
                    if b is None:
                        break
                    a = b + 1
                group = tuple(alternatives)
            if group is None:
                parts.append(word[start : end + 1])  # no range: text, braces and all
            else:
                groups += 1
                if groups > limit:
                    raise _Over(word)
                parts.append(group)
            lo = end + 1

    def words(parts: list[_Part]) -> list[str]:
        """The words `parts` make, or _Over past `limit`."""
        made: list[list[str]] = []
        count = 1
        for part in parts:
            if isinstance(part, str):
                options = [part]
            elif isinstance(part, tuple):
                options = []
                for alternative in part:
                    options.extend(words(alternative))
                    if len(options) > limit:
                        raise _Over(word)
            else:
                options = part
            count *= len(options)
            if count > limit:
                raise _Over(word)
            made.append(options)
        return ["".join(chosen) for chosen in itertools.product(*made)]

    try:
        made = words(parse(0, len(word)))
    except (_Over, _Unsure):
        return None
    except RecursionError:
        return None  # nested deeper than the stack the hook runs with: not read
    return [made_word for made_word in made if made_word]


def _integer(number: re.Match[str]) -> int | None:
    """The integer `_INTEGER` matched, or None when Bash's `strtoimax` finds it out of range."""
    digits = number.group(1).lstrip("+-").lstrip("0")
    if len(digits) > _DIGITS:
        return None
    value = int(number.group(1))
    return value if -_INTMAX - 1 <= value <= _INTMAX else None


def _ranges_like(word: str, start: int, end: int) -> bool:
    """Whether the text of the group `word[start:end + 1]` starts like a range, as Bash 5.3
    checks it before it takes the `{` as one (`valid_seqterm`)."""
    text = word[start + 1 : end]
    at = text.find("..")
    if at < 0:
        return False
    left, right = text, text[at + 2 :] + "}"

    def kind(side: str, letter_ends: str) -> str:
        if side[:1].isdigit() or (side[:1] in "+-" and side[1:2].isdigit()):
            return "int"
        if side[:1].isascii() and side[:1].isalpha() and side[1:2] in letter_ends:
            return "char"
        return ""

    if left[:1] == "." or right[0] == "}":
        return False
    return kind(left, ".") == kind(right, "}.") != ""


def _sequence(
    text: str, limit: int, numbers: bool, bash: tuple[int, int] = (5, 2)
) -> list[str] | None:
    """The words Bash makes of a range `text` between braces (`expand_seqterm` and `mkseq`):
    `a..e`, `1..9`, each with an optional `..step`, letters and numbers either way, the
    step's sign not counting and a step of 0 counting as 1, numbers padded with zeros when an
    end starts with a `0`; None when `text` is no range Bash makes. Raises _Unsure for a
    letter range that makes a backtick or for padded numbers past an `int`, and _Over for
    more than `limit` words (only when `numbers`, see `_expand`)."""
    at = text.find("..")
    left, right = text[:at], text[at + 2 :]
    if at < 0 or not left or not right:
        return None
    first = _INTEGER.fullmatch(left.rstrip(" \t\n\v\f\r" if bash >= (5, 3) else " \t"))
    end = _INTEGER.match(right) if right[0] in "0123456789+-" else None
    if end is not None and end.start(1) == 0 and first is not None:
        a, b, rest = _integer(first), _integer(end), right[end.end() :]
        if rest[:1] not in ("", ".") or a is None or b is None:
            return None
        width = 0
        for side, size in ((left, len(left)), (right, end.end())):
            if (size > 1 and side[0] == "0") or (size > 2 and side[:2] == "-0"):
                width = max(width, len(left), end.end())
    elif len(left) == 1 and left.isascii() and left.isalpha():
        if not (right[0].isascii() and right[0].isalpha() and right[1:2] in ("", ".")):
            return None
        a, b, rest, width = ord(left), ord(right[0]), right[1:], -1
    else:
        return None
    step = 1
    if rest:
        given = _INTEGER.match(rest, 2) if rest.startswith("..") else None
        value = None if given is None or given.end() != len(rest) else _integer(given)
        if value is None or value == -_INTMAX - 1:
            return None  # Bash leaves a range with the least integer as its step as text
        step = abs(value) or 1
    if bash >= (5, 3):
        if abs(b - a) > _INTMAX:
            return None  # Bash 5.3's checked subtraction
    elif not -_INTMAX + 2 <= b - a <= _INTMAX - 2 or abs(b - a) // step > _INT_MAX - 3:
        return None
    count = abs(b - a) // step + 1
    if width < 0:
        letters = [chr(a + k * step * (1 if a <= b else -1)) for k in range(count)]
        if "`" in letters:
            raise _Unsure(text)
        return letters
    if not numbers:
        count = 1
    elif count > limit:
        raise _Over(text)
    values = [a + k * step * (1 if a <= b else -1) for k in range(count)]
    if width and max(abs(a), abs(b)) > _INT_MAX and bash < (5, 3):
        raise _Unsure(text)  # Bash 5.2 pads an `int`
    return [f"{value:0{width}d}" if width else str(value) for value in values]


def _reads_as(word: str) -> tuple[str, str]:
    """The word, and the word with its backslashes, quotes and a `$` before a quote taken off,
    as a shell that reads it again may take it."""
    return word, re.sub(r"\$(?=['\"])|[\\'\"]", "", word)


def _substitution_end(text: str, i: int, bodies: list[tuple[int, int]] | None = None) -> int:
    """The index of the `)` that closes the `$(` (or `<(`, `>(`) at `i`, quotes, escapes and
    nested substitutions and parentheses inside it passed over; ValueError when it never
    closes or holds a backtick, a comment or a heredoc, whose reading is not modelled.
    Given a list of `bodies`, a heredoc whose delimiter is quoted is read as Bash reads it
    (its body is plain text, from the line after the operator's to a line that is the
    delimiter alone) and the span of each body is added to the list; one followed by
    anything but a space, a tab, a newline or an operator, one the `)` closes before its
    body, one whose delimiter line never comes, and one with a body line that starts with
    the delimiter and has a `)` after it still raise ValueError."""
    depth, j, n = 0, i + 1, len(text)
    pending: list[tuple[str, bool]] = []
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "'":
            j = text.find("'", j + 1)
            if j < 0:
                raise ValueError(text)
        elif c == '"':
            j += 1
            while j < n and text[j] != '"':
                if text[j] == "\\":
                    j += 1
                elif text[j] == "`":
                    raise ValueError(text)
                elif text[j] == "$" and text[j + 1 : j + 2] == "(":
                    j = _substitution_end(text, j, bodies)
                j += 1
            if j >= n:
                raise ValueError(text)
        elif c == "(":
            depth += 1
        elif c == ")":
            if pending:
                raise ValueError(text)  # closed before the body Bash reads after a newline
            depth -= 1
            if depth == 0:
                return j
        elif bodies is not None and text.startswith("<<", j) and not text.startswith("<<<", j):
            m = _HEREDOC.match(text, j)
            if m is None or text[m.end() : m.end() + 1] not in tuple(" \t\n;&|<>"):
                raise ValueError(text)
            delimiter = re.sub(r"['\"\\]", "", m.group(2))
            if delimiter == m.group(2):
                raise ValueError(text)  # an unquoted delimiter: its body expands
            pending.append((delimiter, m.group(1) == "-"))
            j = m.end()
            continue
        elif c == "\n" and pending:
            assert bodies is not None  # noqa: S101 - pending is only filled with a list
            j += 1
            for delimiter, tabs in pending:
                start = j
                while True:
                    stop = text.find("\n", j)
                    if stop < 0:
                        raise ValueError(text)  # no delimiter line that a newline ends
                    line = text[j:stop]
                    j = stop + 1
                    read = line.lstrip("\t") if tabs else line
                    if read == delimiter:
                        bodies.append((start, stop - len(line)))
                        break
                    if read.startswith(delimiter) and ")" in read[len(delimiter) :]:
                        raise ValueError(text)  # Bash may end the body there
            pending = []
            continue
        elif c == "#" and (text[j - 1] in " \t" or text[j - 1] in _SEPARATORS):
            raise ValueError(text)
        elif c == "`" or text.startswith("<<", j):
            raise ValueError(text)
        j += 1
    raise ValueError(text)


def _unquoted_brace(written: str) -> bool:
    """Whether a word as written holds a `{` outside quotes and escapes that does not open a
    `${`: a brace the shell may expand. Unsure counts as yes."""
    i, n = 0, len(written)
    while i < n:
        c = written[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            i = written.find("'", i + 1)
            if i < 0:
                return True
        elif c == '"':
            i += 1
            while i < n and written[i] != '"':
                if written[i] == "\\":
                    i += 1
                elif written[i] == "$" and written[i + 1 : i + 2] == "(":
                    try:
                        i = _substitution_end(written, i, [])
                    except ValueError:
                        return True
                i += 1
            if i >= n:
                return True
        elif c == "{" and written[i - 1 : i] != "$":
            return True
        i += 1
    return False


# A heredoc operator and its delimiter, plain or quoted.
_HEREDOC = re.compile(
    r"<<(-?)[ \t]*((?:[A-Za-z0-9_.-]|'[A-Za-z0-9_.-]*'|\"[A-Za-z0-9_.-]*\"|\\[A-Za-z0-9_.-])+)"
)


def _without_heredocs(command: str) -> tuple[str, list[tuple[str, bool]]] | None:
    """The line with the bodies of its heredocs taken out, and each body with whether its
    delimiter is quoted (the body then is plain text); None when the hook is not sure where
    one starts or ends. Quotes, escapes and comments are passed over, so a `<<` in them
    starts none; a `$(` in double quotes is read to its `)` (`_substitution_end`), and the
    bodies of the heredocs with a quoted delimiter in it are taken out as well."""
    out: list[str] = []
    bodies: list[tuple[str, bool]] = []
    pending: list[tuple[str, bool, bool]] = []
    i, n, quote = 0, len(command), ""
    while i < n:
        c = command[i]
        if quote:
            if c == quote:
                quote = ""
            elif c == "\\" and quote == '"':
                out.append(command[i : i + 2])
                i += 2
                continue
            elif quote == '"' and command.startswith("$(", i):
                spans: list[tuple[int, int]] = []
                try:
                    close = _substitution_end(command, i, spans)
                except ValueError:
                    close = -1  # read on as before: `_unsure_quoting` refuses the line
                if close >= 0:
                    at = i
                    for start, stop in spans:  # a heredoc's body in it: taken out too
                        out.append(command[at:start])
                        bodies.append((command[start:stop], True))
                        at = stop
                    out.append(command[at : close + 1])
                    i = close + 1
                    continue
            out.append(c)
            i += 1
            continue
        if c == "\\":
            out.append(command[i : i + 2])
            i += 2
            continue
        if c in "'\"":
            quote = c
        elif c == "#" and (i == 0 or command[i - 1] in " \t\n;&|()"):
            stop = command.find("\n", i)
            stop = n if stop < 0 else stop
            out.append(command[i:stop])
            i = stop
            continue
        elif command.startswith("<<", i) and not command.startswith("<<<", i):
            m = _HEREDOC.match(command, i)
            if m is None:
                return None
            raw = m.group(2)
            pending.append(
                (re.sub(r"['\"\\]", "", raw), m.group(1) == "-", raw != re.sub(r"['\"\\]", "", raw))
            )
            out.append(m.group(0))
            i = m.end()
            continue
        elif c == "\n" and pending:
            out.append(c)
            i += 1
            for delimiter, tabs, quoted in pending:
                body: list[str] = []
                while True:
                    if i >= n:
                        break  # the body runs to the end, as Bash reads it
                    stop = command.find("\n", i)
                    stop = n if stop < 0 else stop
                    text = command[i:stop]
                    i = stop + 1
                    if (text.lstrip("\t") if tabs else text) == delimiter:
                        break
                    body.append(text)
                bodies.append(("\n".join(body), quoted))
            pending = []
            if i > n:
                break
            out.append("\n")
            continue
        out.append(c)
        i += 1
    bodies += [("", quoted) for _, _, quoted in pending]  # no line after it: an empty body
    return "".join(out), bodies


class _Unreadable(ValueError):
    """A quote the line never closes, `$'...'` text with a backslash or a `$"`: its words are
    not known."""


def _words(line: str) -> list[tuple[str, bool, str]]:
    """The line's words, whether each expands and each as written, as `_split` reads them."""
    return [(text, expands, written) for text, expands, _, written in _split(line)]


def _split(line: str) -> list[tuple[str, bool, int, str]]:
    """The line's words, split and unquoted by the rules below, each with whether it holds
    something the shell would still expand (`$`, a backtick, a glob, a brace), so that its
    final text is not known here; a word that starts with an unquoted `~` and holds no `/`
    counts as one too. Words end at unquoted spaces, tabs and operators; single quotes,
    double quotes, `$'...'` and backslashes are taken off; a backslash-newline joins the
    lines; nothing is expanded. A `$(` in double quotes that `_substitution_end` delimits
    stays in the word as written, up to its `)`. Each word comes with the index in the line
    where it starts,
    and as it is written there, quotes and backslashes and all (`_names` expands its braces
    from that). A
    `#` and a heredoc are read like any other text, so a line that holds them is not split as
    the shell splits it: `read_whole` refuses such a line when it names `maity`. Raises
    _Unreadable for a quote that is never closed, for `$'...'` text that holds a backslash,
    whose escapes the shell decodes and this split does not, and for an unquoted `$"`, Bash's
    locale quoting, whose text a translation may replace."""
    words: list[tuple[str, bool, int, str]] = []
    chars: list[str] = []
    started = expands = tilde = False
    i, n, begin = 0, len(line), 0

    def end(at: int) -> None:
        nonlocal chars, started, expands, tilde
        if started:
            text = "".join(chars)
            # `~`, `~-`, `~+`, `~user` alone: the shell puts a directory in their place.
            tilde_alone = tilde and "/" not in text
            words.append((text, expands or tilde_alone, begin, line[begin:at]))
        chars, started, expands, tilde = [], False, False, False

    def quoted(text: str) -> None:
        """Take quoted or escaped `text` into the word."""
        nonlocal started
        started = True
        chars.append(text)

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
            end(i)
        elif c == "\\":
            if i + 1 < n and line[i + 1] != "\n":
                quoted(line[i + 1])
            i += 1  # a backslash-newline is a line continuation: nothing
        elif c == "$" and i + 1 < n and line[i + 1] == '"':
            raise _Unreadable(line)  # $"...": Bash may translate it, so its text is not known
        elif c == "$" and i + 1 < n and line[i + 1] == "'":
            end_at = closing(i + 2, escapes=True)  # $'...': the shell decodes its escapes
            if "\\" in line[i + 2 : end_at]:
                raise _Unreadable(line)
            expands = True
            quoted(line[i + 2 : end_at])
            i = end_at
        elif c == "'":
            end_at = closing(i + 1, escapes=False)
            quoted(line[i + 1 : end_at])
            i = end_at
        elif c == '"':
            started = True
            i += 1
            while i < n and line[i] != '"':
                if line[i] == "\\" and i + 1 < n and line[i + 1] in '$`"\\\n':
                    if line[i + 1] != "\n":
                        quoted(line[i + 1])
                    i += 2
                    continue
                if line.startswith("$(", i):
                    try:
                        close = _substitution_end(line, i, [])
                    except ValueError:
                        close = -1  # read on as before: `_unsure_quoting` refuses the line
                    if close >= 0:  # one piece, as written: its own quotes are its own
                        expands = True
                        quoted(line[i : close + 1])
                        i = close + 1
                        continue
                expands = expands or line[i] in "$`"
                quoted(line[i])
                i += 1
            if i >= n:
                raise _Unreadable(line)
        else:
            tilde = tilde or (c == "~" and not started)
            started = True
            expands = expands or c in _EXPANDS
            chars.append(c)
        i += 1
    end(n)
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


# Words after which a word is a command too, and the commands whose `-c` option makes the
# shell read the word after it again (`bash -c`).
_BEFORE_COMMAND = frozenset(("command", "builtin", "exec", "time", "nohup", "sudo", "env"))
_SHELLS = frozenset(("sh", "bash", "dash", "ksh", "mksh", "zsh", "busybox", "su", "script"))
# A word the shell takes as it is written: no quotes, escapes, braces or expansions.
_LITERAL = re.compile(r"[A-Za-z0-9_./:=@%+,-]*")


def _readers(line: str) -> list[int]:
    """The indexes of the words of the line (`_split`) that make the shell read the words
    after them again: `eval` and `trap` anywhere, `source` and `.` as a command (at the
    line's start, after an operator or after a word such as `command`), and an option with a
    `c` after a shell (`bash -c`, `sh -ec`)."""
    found, before = [], ""
    for k, (text, _, at, _) in enumerate(_split(line)):
        name = text.rsplit("/", 1)[-1]
        head = line[:at].rstrip(" \t")
        command = not head or head[-1] in ";&|()\n!" or before in _BEFORE_COMMAND
        if (
            name in ("eval", "trap")
            or (name in ("source", ".") and command)
            or (before in _SHELLS and text.startswith("-") and "c" in text and "-" not in text[1:])
        ):
            found.append(k)
        before = name
    return found


def _unsure_quoting(line: str) -> bool:
    """Whether the line, outside single quotes and comments, holds `$'...'`, a
    backslash-newline, a backtick whose text holds a quote, a backslash or a `#` or that
    never closes, a `${` whose text holds a quote, a backslash or a backtick or that never
    closes, a `$(` in double quotes the hook cannot delimit, or a double quote that never
    closes: quoting the split does not read exactly."""
    i, n, double = 0, len(line), False
    while i < n:
        c = line[i]
        if not double:
            if c == "'":
                close = line.find("'", i + 1)
                if close < 0:
                    return True
                i = close + 1
                continue
            if c == "$" and line[i + 1 : i + 2] == "'":
                return True
            if c == "#" and (i == 0 or line[i - 1] in " \t\n;&|()"):
                close = line.find("\n", i)
                i = n if close < 0 else close
                continue
        if c == '"':
            double = not double
        elif c == "\\":
            if line[i + 1 : i + 2] == "\n":
                return True
            i += 1
        elif c == "`":
            close = line.find("`", i + 1)
            if close < 0 or any(x in "'\"\\#" for x in line[i + 1 : close]):
                return True
            i = close
        elif c == "$" and line[i + 1 : i + 2] == "{":
            close = line.find("}", i + 2)
            if close < 0 or any(x in "'\"\\`" for x in line[i + 2 : close]):
                return True
        elif c == "$" and line[i + 1 : i + 2] == "(" and double:
            try:
                i = _substitution_end(line, i, [])
            except ValueError:
                return True
        i += 1
    return double


def _touching(line: str) -> list[str]:
    """The line's words as written (`_split`), those with nothing but parentheses, `<`, `>`
    or nothing at all between them joined with what stands between: one word to Bash where a
    substitution splits it for the split (`{a,$(x)}y`)."""
    joined: list[str] = []
    end = -1
    for _, _, at, written in _split(line):
        if joined and set(line[end:at]) <= set("()<>"):
            joined[-1] += line[end:at] + written
        else:
            joined.append(written)
        end = at + len(written)
    return joined


def _unmodelled(command: str, nested: bool = False) -> bool:
    """Whether the line holds a construct the hook does not read exactly, so that it does
    not try (cli/context/runner.md): a word read again after `eval`, `source`, `.`, `trap`
    or `bash -c` that is not a plain literal; `$'...'`; a backslash-newline; a word with a
    brace the shell may expand that also holds `${`, `$(` or a backtick; a backtick whose
    text holds a quote, a backslash or a `#`, or that never closes; a `${` whose text holds a
    quote, a backslash or a backtick; a comment on a line with a `{`; a heredoc the hook
    cannot delimit, or one with an unquoted delimiter whose body holds `$(` or a backtick;
    and a line whose quotes the split cannot read. In quoted text read again (`nested`),
    which may be text and no command at all, only the first of these counts, and only when
    the text holds a `{`."""
    stripped = _without_heredocs(command)
    if stripped is None:
        return True
    line, bodies = stripped
    if nested and "{" not in line:
        return False
    if not nested and any(not quoted and ("$(" in b or "`" in b) for b, quoted in bodies):
        return True
    if not nested and _unsure_quoting(line):
        return True
    if not nested and "{" in line and not read_whole(line.replace("\n", " ")):
        return True  # a comment: its quotes are not the line's
    try:
        words = _words(line)
    except _Unreadable:
        return True
    readers = _readers(line)
    if readers and any(not _LITERAL.fullmatch(w) for _, _, w in words[readers[0] + 1 :]):
        return True
    return not nested and any(
        _unquoted_brace(text) and any(s in text for s in ("${", "$(", "`", "<(", ">("))
        for text in _touching(line)
    )


def calls_runner(command: str, depth: int = 0, seen: _Seen | None = None) -> bool:
    """Whether the line may run `maity runner`: a word `maity` (`_is_maity`) is followed
    later on the line by a word `runner` (`_is_runner`), as `_words` splits them. Neither has
    to be the command word, and operators between them do not matter. A word that `_words`
    says the shell would still expand counts as `maity` before a later `runner` word, and as
    `runner` after a `maity` word in the same text.
    Quoted text that holds spaces or operators is read again the same way, as another shell
    would read it, up to `_NESTING` levels deep; its words continue the line where the text
    stands, so a `maity` word in it counts before a `runner` word after it and the other way
    round. Such text below that depth counts whatever it holds. A line whose quotes never
    close counts whatever it holds, and so does one with a construct the hook does not read
    exactly (`_unmodelled`), on the line or in quoted text read again."""
    if _unmodelled(command, nested=depth > 0):
        return True  # a construct the hook does not read exactly: refused
    command = _without_heredocs(command)[0]  # type: ignore[index]
    try:
        words = _words(command)
    except _Unreadable:
        return True  # not read to the end: refused, whatever it holds
    seen = _Seen() if seen is None else seen
    maity_here = False  # a `maity` word in this text: an expanding word after it counts
    for text, expands, written in words:
        if _is_runner(text, written) and (seen.maity or seen.open):
            return True
        if expands and maity_here:
            return True
        if _is_maity(text, written) and _is_runner(text, written):
            return True  # both words as alternatives of one brace, or a word not read
        if any(c in " \t" or c in _SEPARATORS for c in text) and (
            depth >= _NESTING or calls_runner(text, depth + 1, seen)
        ):
            return True  # past the depth limit, text that could be a command is refused
        maity_here = maity_here or _is_maity(text, written)
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
        return WAIT_TIMEOUT_REFUSED if _assigns_wait_timeout(command) else PREFIX_REFUSED
    return None


def main(args: Sequence[str] | None = None) -> int:
    """Exit 0 to leave the call to the permission rules, 2 to refuse it."""
    del args  # takes none
    try:
        payload = json.loads(sys.stdin.buffer.read())
    except (ValueError, OSError, RecursionError):
        payload = None
    try:
        reason = refusal(payload)
    except Exception:  # noqa: BLE001 - a line the hook fails on is refused, not let through
        reason = FAILED
    if reason is None:
        return 0
    print(reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
