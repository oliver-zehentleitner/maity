"""Does a review's text name only what stands at its head? (docs/api.md §8.4, "A review's text
names only what stands at its head", §13)

The cites are checked by `citecheck`; reviews still passed with prose that named tests, keys or
files that were not there. This reads the message's text in the same clone and looks for four
forms: a file and line, a name in a code span, an object hash, and a quotation from a file that
the text ties to that file. A numeric ratio is not a file and line. A Keep-the-Why id has to be
the full UUID at the head, and a cited test name has to be a test there. It catches names and
quotes that are not there, not wrong claims.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
from pathlib import Path

from maity import proc

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]|$)")
_RAN = re.compile(r"^ {0,3}(#{1,6})[ \t]+ran[ \t]*(?:#+[ \t]*)?$", re.IGNORECASE)
_TICKS = re.compile(r"`+")
# Form 1: a path whose last part has an extension, then `:` and a line or a range.
_FILE_LINE = re.compile(
    r"(?<![\w./-])((?:[\w-][\w.-]*/)*[\w-][\w-]*(?:\.[\w-]+)*\.[A-Za-z0-9]+):(\d+)(?:-(\d+))?(?!\w)"
)
# A Keep-the-Why id is the full UUID. A hyphenated shorter form is a prefix, not an id.
_UUID_AT = re.compile(
    r"(?<![0-9A-Za-z])([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})(?![0-9A-Za-z])"
)
# A hyphenated id that is not 8-4-4-4-12. The last group may be 1–11 hex digits, so a cut
# of five to eleven characters is refused too; a full last group of twelve is `_UUID_AT`.
_UUID_SHORT = re.compile(
    r"(?<![0-9A-Za-z])("
    r"[0-9a-fA-F]{8}"
    r"(?:"
    r"(?:-[0-9a-fA-F]{1,4}){3}-[0-9a-fA-F]{1,11}"
    r"|"
    r"(?:-[0-9a-fA-F]{1,4}){1,3}"
    r")"
    r")(?![0-9A-Za-z-])"
)
_TEST_NAME = re.compile(r"test_[A-Za-z0-9_]+")
# Form 3: lowercase hex as a word bounded by anything but letters, digits, `_` and `-`.
_HEX = re.compile(r"(?<![A-Za-z0-9_-])[0-9a-f]{7,40}(?![A-Za-z0-9_-])")
_HUB_ID = re.compile(r"[a-z]+-[0-9a-z]{12}")
_UUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")
_CORE = re.compile(r"[A-Za-z_][A-Za-z0-9_./-]{2,}")
_SKIP_CHARS = set("#@{}<>")
# Form 4: a quotation, between "…" or “…”, of four words or more.
_QUOTE = re.compile(r'"[^"]*"|“[^“”]*”|„[^„“”]*[“”]')
_GAP_STOPS = set('.;!?|"“”„')  # `|`: a table's cell is no sentence of its own
# One backslash (or any odd number) before a quote mark masks it; two (or any even number) are
# backslashes in the text, and the quote mark after them closes the quote.
_ESCAPED_QUOTE = re.compile(r'(?<!\\)(?:\\\\)*\\"')
# A comment marker at a line's start, so that a quote of a wrapped comment matches.
_COMMENT = re.compile(r"^[ \t]*(?:#+|//+|/?\*+/?|--|;+)[ \t]?", re.MULTILINE)
# "…" (path:n): the place in brackets, on the same line or the paragraph's next one.
_AFTER_GAP = re.compile(r"[ \t]*\n?[ \t]*\([ \t]*`?")
_QUOTE_WORDS = 4
_CUT = re.compile(r"…|\.\.\.")
_HEADING_TEXT = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*(?:#+[ \t]*)?$")
_PATH_IN_HEADING = re.compile(
    r"(?<![\w./-])((?:[\w-][\w.-]*/)*[\w-][\w-]*(?:\.[\w-]+)*\.[A-Za-z0-9]+)"
)
_DEFAULT_BRANCH = "origin/HEAD"


@dataclasses.dataclass(frozen=True)
class Result:
    bad: list[str]  # one line per name that is not there


def is_object_hash(word: str) -> bool:
    """7–40 lowercase hex with a letter and a digit: an English word such as `defaced` is not
    one, nor is a number."""
    return (
        7 <= len(word) <= 40
        and re.fullmatch(r"[0-9a-f]+", word) is not None
        and re.search(r"[a-f]", word) is not None
        and re.search(r"[0-9]", word) is not None
    )


def checked_text(body: str) -> str:
    """The text without fenced code blocks and without the sections under a heading `Ran`."""
    kept: list[str] = []
    fence: str | None = None
    ran_level: int | None = None
    for line in body.splitlines():
        if fence is not None:
            if line.lstrip(" ").startswith(fence) and line.strip(fence[0] + " \t") == "":
                fence = None
            continue
        opened = _FENCE.match(line)
        if opened:
            fence = opened.group(1)
            continue
        heading = _HEADING.match(line)
        if heading and ran_level is not None and len(heading.group(1)) <= ran_level:
            ran_level = None
        ran = _RAN.match(line)
        if ran:
            ran_level = len(ran.group(1))
            continue
        if ran_level is None:
            kept.append(line)
    return "\n".join(kept)


def _span_ranges(text: str) -> list[tuple[int, int, int]]:
    """(start, end, width) of each code span, backticks included, paired as CommonMark pairs
    them: a run of n backticks closes at the next run of exactly n; a run that never closes is
    text."""
    runs = list(_TICKS.finditer(text))
    ranges: list[tuple[int, int, int]] = []
    index = 0
    while index < len(runs):
        opening = runs[index]
        width = len(opening.group())
        closing = next(
            (j for j in range(index + 1, len(runs)) if len(runs[j].group()) == width), None
        )
        if closing is None:
            index += 1
            continue
        ranges.append((opening.start(), runs[closing].end(), width))
        index = closing + 1
    return ranges


def code_spans(text: str) -> list[str]:
    """What stands between single backticks (see `_span_ranges`)."""
    return [text[start + 1 : end - 1] for start, end, width in _span_ranges(text) if width == 1]


def _unquote(span: str) -> str:
    if len(span) >= 2 and span[0] == span[-1] and span[0] in "\"'":
        return span[1:-1]
    return span


def _skipped(span: str) -> bool:
    if not span or any(c.isspace() for c in span) or not span.isascii():
        return True
    if _SKIP_CHARS & set(span):
        return True
    if _HUB_ID.fullmatch(span) or _UUID.fullmatch(span):
        return True
    if not re.search(r"[A-Za-z]", span):
        return True  # digits and punctuation only
    ends = span.split("..")
    return all(is_object_hash(end) for end in ends if end) and any(ends)


class _Repo:
    def __init__(self, cwd: Path, head: str) -> None:
        self.cwd = cwd
        self.revs = [head]
        default = self._git("rev-parse", "--verify", "-q", f"{_DEFAULT_BRANCH}^{{commit}}")
        if default.returncode == 0 and default.stdout.strip() != head:
            self.revs.append(default.stdout.strip())
        self._files: dict[str, list[str]] = {}
        self._flat: dict[str, tuple[str, ...]] = {}

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return proc.run([*proc.GIT, "--literal-pathspecs", *args], self.cwd)

    def files(self, rev: str) -> list[str]:
        if rev not in self._files:
            out = self._git("ls-tree", "-r", "--name-only", "-z", rev)
            self._files[rev] = [f for f in out.stdout.split("\0") if f]
        return self._files[rev]

    def line_count(self, rev: str, path: str) -> int | None:
        shown = self._git("show", f"{rev}:{path}")
        if shown.returncode != 0:
            return None
        text = shown.stdout
        return text.count("\n") + (0 if text.endswith("\n") or not text else 1)

    def has_text(self, needle: str) -> bool:
        return any(
            self._git("grep", "-q", "-F", "-e", needle, rev, "--").returncode == 0
            for rev in self.revs
        )

    def has_path(self, path: str, prefix: bool) -> bool:
        path = path.removeprefix("./")
        for rev in self.revs:
            for name in self.files(rev):
                if prefix and name.startswith(path):
                    return True
                if not prefix and (name == path or name.startswith(path.rstrip("/") + "/")):
                    return True
        return False

    def has_file_name(self, name: str) -> bool:
        return any(f.rsplit("/", 1)[-1] == name for rev in self.revs for f in self.files(rev))

    def has_object(self, word: str) -> bool:
        return self._git("cat-file", "-e", word).returncode == 0

    def has_id(self, ident: str) -> bool:
        """The full UUID stands in a file at the head. A prefix of it does not match."""
        found = self._git("grep", "-q", "-i", "-F", "-e", ident, self.revs[0], "--")
        return found.returncode == 0

    def has_test(self, name: str) -> bool:
        """A definition at the head: after indentation, `def` or `async def`, the name,
        optional whitespace and `(`. A comment line is not one, a space before `(` is,
        and a longer name does not count as this one."""
        if _TEST_NAME.fullmatch(name) is None:
            return False
        pattern = f"^[ \t]*(async[ \t]+)?def[ \t]+{name}[ \t]*\\("
        found = self._git("grep", "-q", "-E", "-e", pattern, self.revs[0], "--")
        return found.returncode == 0

    def flat_text(self, rev: str, path: str) -> tuple[str, ...]:
        """The file with every run of whitespace as one space, so that a quote of wrapped
        prose matches, once as it is and once without the comment markers at the lines'
        starts, so that a quote of a wrapped comment does too; nothing for a missing file."""
        key = f"{rev}:{path}"
        if key not in self._flat:
            shown = self._git("show", key)
            text = shown.stdout
            self._flat[key] = (
                (_flat(text), _flat(_COMMENT.sub("", text))) if shown.returncode == 0 else ()
            )
        return self._flat[key]


def _file_lines_in(text: str) -> list[re.Match[str]]:
    """File-and-line cites. A ratio such as `5.60:1` or `4.5:1` is digits and dots, not a path;
    `3:1` has no extension, so the pattern never takes it."""
    return [
        match
        for match in _FILE_LINE.finditer(text)
        if not match.group(1).replace(".", "").isdigit()
    ]


def _file_lines(repo: _Repo, head: str, text: str) -> list[str]:
    bad = []
    files = repo.files(head)
    for match in _file_lines_in(text):
        path, first, last = match.group(1), int(match.group(2)), match.group(3)
        end = int(last) if last else first
        if path not in files:
            near = [f for f in files if f.endswith("/" + path)]
            hint = f"; did you mean {near[0]}?" if len(near) == 1 else ""
            bad.append(f"body: {match.group(0)}: not a full path of a file at the head{hint}")
            continue
        count = repo.line_count(head, path)
        if count is not None and count < end:
            bad.append(f"body: {match.group(0)}: the file has {count} lines at the head")
    return bad


def _name(repo: _Repo, span: str) -> str | None:
    """Why the span names nothing at the head or on the default branch, or None.
    A test name is checked at the head only; the reason is then `not a test`."""
    if "/" in span:
        path = span.split(":", 1)[0]
        if "*" in path:
            if repo.has_path(path.split("*", 1)[0], prefix=True):
                return None
        elif repo.has_path(path, prefix=False):
            return None
        if repo.has_text(path):
            return None  # a route or a path the repository spells out
        return "no such file or directory"
    cores = _CORE.findall(span)
    if not cores:
        return None
    # `test_real[longer-parameter-than-test]` has two cores; the parameter can be the
    # longer one. A core that is a test name is what gets checked.
    tests = [core for core in cores if _TEST_NAME.fullmatch(core)]
    if tests:
        name = max(tests, key=len)
        if repo.has_test(name):
            return None
        return "not a test"
    core = max(cores, key=len)
    if repo.has_text(core) or repo.has_file_name(core):
        return None
    parts = [part for part in core.split(".") if len(part) >= 3]
    if "." in core and parts and all(repo.has_text(part) for part in parts):
        return None
    return "not found as text or as a file name"


def _flat(text: str) -> str:
    """Whitespace runs as one space and no backticks, so that a quote of wrapped prose matches
    and one that dropped the code marks of `.flag` does too."""
    return " ".join(text.replace("`", "").split())


def _blank_spans(text: str) -> str:
    """The text with each code span's characters but newlines as spaces, so that a `"` in a
    span opens no quote while positions stay those of the text."""
    out = list(text)
    for start, end, _ in _span_ranges(text):
        for i in range(start, end):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


@dataclasses.dataclass(frozen=True)
class Quotation:
    text: str  # whitespace runs as one space
    files: list[str]  # it stands in one of them
    by_line: bool  # tied by a file and line (head only), else by its section


def _next_to(gap: str, words: int) -> bool:
    """Does a file and line stand right before a quote, with only `gap` between? Nothing that
    ends a sentence or quotes, and at most `words` words (`says`, `reads:`)."""
    return not (set(gap) & _GAP_STOPS) and len(gap.split()) <= words and len(gap) <= 24


def quotations(text: str, files: list[str]) -> list[Quotation]:
    """Each quotation the text ties to a file of the head.

    A quote lies between `"` and the next `"`, `“` and the next `”`, or `„` and the next `“`
    or `”`, within one paragraph and outside code spans, and has four words or more. It is
    tied to a file by a file and line (form 1) right before it (`path:n says "…"`) or right
    after it in brackets (`"…" (path:n)`), also on the paragraph's next line, when those places
    name one file between them; with no file and line next to it, to the file of the section it sits
    in: the nearest heading above that names a file at the head, when it names exactly one.
    A quote mark after an odd number of backslashes closes no quote."""
    quotes: list[Quotation] = []
    section: list[tuple[int, list[str]]] = []  # (level, files at the head) of the headings
    paragraph: list[str] = []

    def flush() -> None:
        if not paragraph:
            return
        para = "\n".join(paragraph)
        blanked = _ESCAPED_QUOTE.sub(lambda m: " " * len(m.group()), _blank_spans(para))
        lines = [m for m in _file_lines_in(para) if m.group(1) in files]
        nearest = next((named for _, named in reversed(section) if named), [])
        here = nearest[0] if len(nearest) == 1 else None
        used = -1  # the end of the brackets the last quote took: no place before the next one
        for match in _QUOTE.finditer(blanked):
            quote = para[match.start() + 1 : match.end() - 1]
            if len(quote.split()) < _QUOTE_WORDS:
                continue
            before = [m for m in lines if m.end() <= match.start()]
            after = [m for m in lines if m.start() >= match.end()]
            named = []
            if (
                before
                and before[-1].start() > used
                and _next_to(para[before[-1].end() : match.start()], 2)
            ):
                named.append(before[-1].group(1))
            if after and _AFTER_GAP.fullmatch(para[match.end() : after[0].start()]):
                close = para.find(")", after[0].end())
                used = close if close != -1 else len(para)
                inside = para[after[0].start() : used]
                named.extend(m.group(1) for m in _FILE_LINE.finditer(inside))
            if named:
                # Places of two files next to one quote name no one source: it is tied to none.
                if len(set(named)) == 1:
                    quotes.append(Quotation(_flat(quote), named[:1], True))
            elif here is not None:
                quotes.append(Quotation(_flat(quote), [here], False))
        paragraph.clear()

    for line in text.splitlines():
        heading = _HEADING_TEXT.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            while section and section[-1][0] >= level:
                section.pop()
            named = {m.group(1) for m in _PATH_IN_HEADING.finditer(heading.group(2))}
            section.append((level, sorted(f for f in named if f in files)))
        elif line.strip():
            paragraph.append(line)
        else:
            flush()
    flush()
    return quotes


def _quote_stands(repo: _Repo, revs: list[str], quote: str, path: str) -> bool:
    """`\\"` in the quote may be Markdown's escape of `"` or the file's own text: both count."""
    for text in dict.fromkeys([quote, quote.replace('\\"', '"')]):
        parts = [part.strip() for part in _CUT.split(text)]
        parts[-1] = parts[-1].rstrip(".,;:!?")
        for rev in revs:
            for flat in repo.flat_text(rev, path):
                if all(part in flat for part in parts if part):
                    return True
    return False


def _ids(repo: _Repo, text: str) -> list[str]:
    """A Keep-the-Why id is the full UUID at the head. A hyphenated shorter form is refused,
    even when an id at the head starts with it. Eight hex digits and no hyphen stay an object
    hash (form 3), checked apart from this."""
    bad: list[str] = []
    full = list(_UUID_AT.finditer(text))
    seen: set[str] = set()
    for match in full:
        ident = match.group(1).lower()
        if ident in seen:
            continue
        seen.add(ident)
        if not repo.has_id(ident):
            bad.append(f"body: {match.group(1)}: no such id at the head")
    covered = [(match.start(), match.end()) for match in full]
    seen_short: set[str] = set()
    for match in _UUID_SHORT.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in covered):
            continue
        ident = match.group(1)
        key = ident.lower()
        if key in seen_short:
            continue
        seen_short.add(key)
        bad.append(f"body: {ident}: not a full id")
    return bad


def _short(quote: str) -> str:
    return quote if len(quote) <= 80 else quote[:79] + "…"


def check(cwd: Path, head: str, body: str) -> Result:
    """`cwd` is the top of a clone that has `head` (the caller made sure of both)."""
    repo = _Repo(cwd, head)
    text = checked_text(body)
    bad = _file_lines(repo, head, text)
    seen: set[str] = set()
    for raw in code_spans(text):
        span = _unquote(raw)
        if span in seen or _skipped(span):
            continue
        seen.add(span)
        problem = _name(repo, span)
        if problem is not None:
            # A test is resolved at the head only. Other names also stand on the default branch.
            if problem == "not a test":
                where = "the head"
            else:
                where = "the head nor the default branch" if len(repo.revs) > 1 else "the head"
            bad.append(f"body: `{span}`: {problem} at {where}")
    bad.extend(_ids(repo, text))
    for word in sorted(set(_HEX.findall(text))):
        if is_object_hash(word) and not repo.has_object(word):
            bad.append(f"body: {word}: no such object in this clone")
    for quote in quotations(text, repo.files(head)):
        revs = [head] if quote.by_line else repo.revs
        if not any(_quote_stands(repo, revs, quote.text, path) for path in quote.files):
            where = "the head" if len(revs) == 1 else "the head nor the default branch"
            names = " nor ".join(quote.files)
            bad.append(f'body: "{_short(quote.text)}": not in {names} at {where}, verbatim')
    return Result(bad)
