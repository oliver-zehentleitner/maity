"""Does a review's text name only what stands at its head? (docs/api.md §8.4, "A review's text
names only what stands at its head", §13)

The cites are checked by `citecheck`; reviews still passed with prose that named tests, keys or
files that were not there. This reads the message's text in the same clone and looks for three
forms: a file and line, a name in a code span, an object hash. It catches names that are not
there, not wrong claims.
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
# Form 3: lowercase hex as a word bounded by anything but letters, digits, `_` and `-`.
_HEX = re.compile(r"(?<![A-Za-z0-9_-])[0-9a-f]{7,40}(?![A-Za-z0-9_-])")
_HUB_ID = re.compile(r"[a-z]+-[0-9a-z]{12}")
_UUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")
_CORE = re.compile(r"[A-Za-z_][A-Za-z0-9_./-]{2,}")
_SKIP_CHARS = set("#@{}<>")
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


def code_spans(text: str) -> list[str]:
    """What stands between single backticks, paired as CommonMark pairs them: a run of n
    backticks closes at the next run of exactly n; a run that never closes is text."""
    runs = list(_TICKS.finditer(text))
    spans: list[str] = []
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
        if width == 1:
            spans.append(text[opening.end() : runs[closing].start()])
        index = closing + 1
    return spans


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


def _file_lines(repo: _Repo, head: str, text: str) -> list[str]:
    bad = []
    files = repo.files(head)
    for match in _FILE_LINE.finditer(text):
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
    """Why the span names nothing at the head or on the default branch, or None."""
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
    core = max(cores, key=len)
    if repo.has_text(core) or repo.has_file_name(core):
        return None
    parts = [part for part in core.split(".") if len(part) >= 3]
    if "." in core and parts and all(repo.has_text(part) for part in parts):
        return None
    return "not found as text or as a file name"


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
            where = "the head nor the default branch" if len(repo.revs) > 1 else "the head"
            bad.append(f"body: `{span}`: {problem} at {where}")
    for word in sorted(set(_HEX.findall(text))):
        if is_object_hash(word) and not repo.has_object(word):
            bad.append(f"body: {word}: no such object in this clone")
    return Result(bad)
