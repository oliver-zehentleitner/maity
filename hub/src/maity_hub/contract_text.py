"""A contract card's text, and the project's whole contract, read from the project's
repository (docs/api.md §6.8).

The hub keeps no copy: `path` and `section` name a section of a file, read through the
probe at the default branch's commit and cut out by the hub's own heading parser; the
whole contract is the file `settings.contract_path` names, with its table of contents.
One read is kept for `MAX_AGE` seconds and answers concurrent calls, keyed so that a
changed selection, repository or commit is never answered from an older read.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
import urllib.parse
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from maity_hub import bounded, clock, forge

DEFAULT_PATH = "docs/api.md"
FILE_CAP = 4 * 1024 * 1024  # bytes of the file read at all, for a section and the whole file
SETTING = "settings.contract_path"
MARKDOWN = (".md", ".markdown")  # compared case-insensitively
TOC_MAX = 2000  # headings listed in `toc`
TITLE_MAX = 300  # characters of a heading's `title`
TREES_KEPT = 512  # directory trees kept, per commit and directory
DIRECTORY = "040000"
FILE_MODES = ("100644", "100755")
NUMBER = re.compile(r"\d+(?:\.\d+)*")
TEXT_CAP = 64 * 1024  # bytes of the section shown
MAX_AGE = 60  # seconds one read answers (§6.8, as the observation cache of §11)
HEAD_AGE = 30.0  # seconds a default branch's head answers, per reader, repository and branch
HEADS_KEPT = 1024  # branch heads kept, the oldest written dropped first
PATH_MAX = 255
SECTION_MAX = 32

SECTION = re.compile(r"[^\s#]+")
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)$")


class ContractTextError(Exception):
    """A read that shows nothing: `field` and `reason` as `details.fields` names them."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


def path_error(path: str) -> str | None:
    """`not_a_path` unless `path` is a repository-relative file path: no leading slash, no
    `..` or empty segment, no URL, no scheme, no backslash, no control character."""
    if not 0 < len(path) <= PATH_MAX or path.startswith("/") or ":" in path or "\\" in path:
        return "not_a_path"
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in path):
        return "not_a_path"
    if any(part in ("", ".", "..") for part in path.split("/")):
        return "not_a_path"
    return None


def setting_error(path: str) -> str | None:
    """Why `settings.contract_path` cannot name `path` (§6.8 "The setting"): `not_a_path`
    under the rule of a card's `path`, `not_markdown` unless it ends in `.md` or
    `.markdown` in any case; None when it can."""
    if path_error(path) is not None:
        return "not_a_path"
    if not path.lower().endswith(MARKDOWN):
        return "not_markdown"
    return None


def section_error(section: str) -> str | None:
    """A heading number as the file writes it (`6.20`, `2.6.2`): one token, no `#`."""
    if len(section) > SECTION_MAX or not SECTION.fullmatch(section):
        return "invalid"
    return None


@dataclass(frozen=True)
class Section:
    heading: str
    text: str
    truncated: bool


def _names(title: str, section: str) -> bool:
    """`title` begins with `section` as a whole token: followed by a space, the end of the
    line, or a period that is itself followed by a space or the end — `6.2` names
    `6.2 Members` and `6.2. Members`, never `6.20` or `6.2.1`."""
    if not title.startswith(section):
        return False
    rest = title[len(section) :]
    if rest.startswith("."):
        rest = rest[1:]
    return rest == "" or rest[0] in " \t"


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(line index, level, title) of every ATX heading outside fenced code."""
    found: list[tuple[int, int, str]] = []
    fence: str | None = None
    for index, line in enumerate(lines):
        bare = line.rstrip("\r\n")
        opening = FENCE.match(bare)
        if fence is not None:
            # A closing fence: the same character, at least as long, nothing after it.
            if (
                opening
                and opening.group(1)[0] == fence[0]
                and len(opening.group(1)) >= len(fence)
                and not opening.group(2).strip()
            ):
                fence = None
            continue
        if opening and not (opening.group(1)[0] == "`" and "`" in opening.group(2)):
            fence = opening.group(1)
            continue
        heading = _atx(bare)
        if heading:
            found.append((index, heading[0], heading[1]))
    return found


def _atx(line: str) -> tuple[int, str] | None:
    """(level, title) of an ATX heading: up to three spaces, one to six `#`, then the end or a
    space or a tab and the title, without a closing sequence of `#` after a space or a tab.
    String steps, each one pass over the line, so the work grows with the line's length: the
    patterns they replace tried every start in a run of spaces."""
    marks = line.lstrip(" ")
    if len(line) - len(marks) > 3:
        return None
    rest = marks.lstrip("#")
    level = len(marks) - len(rest)
    if not 1 <= level <= 6 or (rest and rest[0] not in " \t"):
        return None
    title = rest.strip(" \t")
    bare = title.rstrip("#")
    if bare != title and bare[-1:] in (" ", "\t"):
        title = bare  # a closing sequence
    return level, title.strip()


def find_section(markdown: str, section: str) -> Section:
    """The ATX heading of level 2 to 4 whose first token is `section`, and the Markdown up
    to the next heading of the same or a higher level; `not_found_in_file` without one,
    `ambiguous_in_file` with two or more — the hub never picks one."""
    lines = markdown.splitlines(keepends=True)
    headings = _headings(lines)
    matches = [h for h in headings if 2 <= h[1] <= 4 and _names(h[2], section)]
    if not matches:
        raise ContractTextError("contract.section", "not_found_in_file")
    if len(matches) > 1:
        raise ContractTextError("contract.section", "ambiguous_in_file")
    start, level, _ = matches[0]
    end = next((i for i, lv, _ in headings if i > start and lv <= level), len(lines))
    text = "".join(lines[start:end]).rstrip() + "\n"
    data = text.encode()
    truncated = len(data) > TEXT_CAP
    if truncated:
        text = data[:TEXT_CAP].decode("utf-8", errors="ignore")  # on a character boundary
    return Section(lines[start].rstrip("\r\n"), text, truncated)


def _numbered(title: str) -> tuple[str | None, str]:
    """A heading's section number and the rest: `8. Events` → (`8`, `Events`); a heading
    whose first token is no section number has none (`None`, the whole title)."""
    first, _, rest = title.partition(" ")
    bare = first[:-1] if first.endswith(".") else first
    if NUMBER.fullmatch(bare):
        return bare, rest.strip()
    return None, title


def toc(markdown: str) -> list[dict[str, Any]]:
    """The file's ATX headings of level 2 to 4 in file order, as the section's parser finds
    them, at most `TOC_MAX` (§6.8 `toc`). A number that occurs once anchors as `s-<number>`;
    a heading without one, or with a number another heading shares, as `h-<position>`."""
    found = [h for h in _headings(markdown.splitlines(keepends=True)) if 2 <= h[1] <= 4]
    numbered = [(index, level, *_numbered(title)) for index, level, title in found]
    # Counted over every heading of the file, before the cut: a number that occurs again
    # past `TOC_MAX` is not unique, as the card's section read would find two.
    counts: dict[str, int] = {}
    for _, _, number, _ in numbered:
        if number is not None:
            counts[number] = counts.get(number, 0) + 1
    numbered = numbered[:TOC_MAX]
    return [
        {
            "level": level,
            "number": number,
            "title": title[:TITLE_MAX],
            "anchor": f"s-{number}" if number is not None and counts[number] == 1 else f"h-{n}",
            "line": index + 1,
        }
        for n, (index, level, number, title) in enumerate(numbered)
    ]


def blob_url(repository: str, ref: str, path: str) -> str:
    return f"https://github.com/{repository}/blob/{ref}/{urllib.parse.quote(path)}"


# --- the one read kept --------------------------------------------------------------------

Key = tuple[str, str, str, str]  # repository, commit, path, section

_lock = threading.Lock()
_reads: dict[Key, tuple[float, dict[str, Any] | ContractTextError]] = {}
_pending: dict[Key, threading.Lock] = {}


def _kept(key: Key) -> dict[str, Any] | ContractTextError | None:
    entry = _reads.get(key)
    if entry is None or time.monotonic() - entry[0] > MAX_AGE:
        return None
    return entry[1]


def _remember(key: Key, value: dict[str, Any] | ContractTextError) -> None:
    now = time.monotonic()
    for old in [k for k, (at, _) in _reads.items() if now - at > MAX_AGE]:
        del _reads[old]
    _reads[key] = (now, value)


def _once(key: Key, read: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """`read` for `key` unless a read of the last `MAX_AGE` seconds answers; concurrent
    calls for the same key wait for the one read instead of asking the forge again."""
    with _lock:
        kept = _kept(key)
        if kept is None:
            gate = _pending.setdefault(key, threading.Lock())
    if kept is None:
        with gate:
            with _lock:
                kept = _kept(key)
            if kept is None:
                try:
                    try:
                        kept = read()
                    except ContractTextError as error:
                        kept = error
                    with _lock:
                        _remember(key, kept)
                finally:
                    # Also when the forge did not answer (nothing kept): otherwise every
                    # failed read would leave its key's gate behind for good.
                    with _lock:
                        _pending.pop(key, None)
    if isinstance(kept, ContractTextError):
        raise kept
    return kept


# --- the default branch's head -------------------------------------------------------------

HeadKey = tuple[str, str, str]  # digest of the reader's token, repository, branch
_heads: OrderedDict[HeadKey, tuple[float, dict[str, Any]]] = OrderedDict()


def _head(fg: forge.Forge, repository: str, branch: str) -> dict[str, Any]:
    """`fg.branch(repository, branch)`, kept for HEAD_AGE seconds: within it a call asks the
    forge nothing, so the calls of many viewers cost one read of the branch, and a read that
    a kept head and a kept text answer goes on while the source's budget is spent. Keyed by
    the reader's token too, so a head is answered only to a reader that read it itself (a
    token that cannot see a repository never gets its head from another's read). A forge
    that did not answer is not kept."""
    token = hashlib.sha256((fg.token or "").encode()).hexdigest()
    key = (token, repository, branch)
    now = time.monotonic()
    with _lock:
        kept = _heads.get(key)
        if kept is not None and now - kept[0] < HEAD_AGE:
            return kept[1]
    found = fg.branch(repository, branch)
    with _lock:
        bounded.put(_heads, key, (time.monotonic(), found), HEADS_KEPT)
    return found


def forget() -> None:
    """Drop every kept read and tree (tests)."""
    with _lock:
        _reads.clear()
        _pending.clear()
        _trees.clear()
        _heads.clear()


# --- what the setting's name points to ----------------------------------------------------

_trees: dict[tuple[str, str, str], dict[str, Any]] = {}


def _tree(fg: forge.Forge, repository: str, ref: str, directory: str) -> dict[str, Any] | None:
    """A directory's tree at a commit, which never changes: kept per commit and directory,
    the oldest dropped beyond `TREES_KEPT`. A tree the forge did not answer is not kept:
    a 404 may be a refusal, and the next read asks again."""
    key = (repository, ref, directory)
    with _lock:
        if key in _trees:
            return _trees[key]
    found = fg.tree(repository, ref, directory)
    if found is None:
        return None
    with _lock:
        while len(_trees) >= TREES_KEPT:
            del _trees[next(iter(_trees))]
        _trees[key] = found
    return found


def check_file(fg: forge.Forge, repository: str, ref: str, path: str) -> None:
    """That `path` is a regular file down every segment at `ref` (§6.8 "The setting"):
    each directory's non-recursive tree from the root down; a tree answered truncated is
    `not_markdown` before any segment is looked up in it, a segment a complete tree does
    not list `not_found_on_forge`, a directory not `040000` or a file not `100644` or
    `100755` (a symlink, a submodule) `not_markdown`. Names compare byte for byte."""
    segments = path.split("/")
    for depth, name in enumerate(segments):
        directory = "/".join(segments[:depth])
        tree = _tree(fg, repository, ref, directory)
        if tree is None:
            raise ContractTextError(SETTING, "not_found_on_forge")
        if tree["truncated"]:
            raise ContractTextError(SETTING, "not_markdown")
        entry = next((e for e in tree["entries"] if e["path"] == name), None)
        if entry is None:
            raise ContractTextError(SETTING, "not_found_on_forge")
        last = depth == len(segments) - 1
        if entry["mode"] not in (FILE_MODES if last else (DIRECTORY,)):
            raise ContractTextError(SETTING, "not_markdown")


def read(fg: forge.Forge, repository: str, branch: str, path: str, section: str) -> dict[str, Any]:
    """The section at the default branch's commit: `{path, section, ref, heading, text,
    url, truncated, fetched_at}`. `forge.ForgeUnavailableError` when the forge does not
    answer; `ContractTextError` when there is nothing to show."""
    head = _head(fg, repository, branch)
    if not head["found"]:
        raise ContractTextError("contract.path", "not_found_on_forge")
    ref: str = head["head_sha"]

    def fetch() -> dict[str, Any]:
        try:
            data = fg.file_at(repository, path, ref, FILE_CAP)
        except ValueError as error:
            if str(error) == "too large":
                raise ContractTextError("contract.path", "too_large") from None
            raise ContractTextError("contract.path", "not_found_on_forge") from None
        if data is None:
            raise ContractTextError("contract.path", "not_found_on_forge")
        try:
            markdown = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ContractTextError("contract.path", "not_text") from None
        found = find_section(markdown, section)
        return {
            "path": path,
            "section": section,
            "ref": ref,
            "heading": found.heading,
            "text": found.text,
            "url": blob_url(repository, ref, path),
            "truncated": found.truncated,
            "fetched_at": clock.rfc3339(clock.now()),
        }

    return _once((repository, ref, path, section), fetch)


WHOLE = "\0whole"  # the section key of a whole read: no card's section is ever this


def read_whole(fg: forge.Forge, repository: str, branch: str, path: str) -> dict[str, Any]:
    """The file `path` names, whole, at the default branch's commit: `{path, ref, url,
    size, fetched_at, toc, text}` and its `etag` (§6.8 "The whole contract"), a digest
    over the repository, `path` and the bytes. `forge.ForgeUnavailableError` when the
    forge does not answer; `ContractTextError` under `settings.contract_path` when there
    is nothing to show."""
    reason = setting_error(path)
    if reason is not None:  # a setting stored before the rule: the read checks it too
        raise ContractTextError(SETTING, reason)
    head = _head(fg, repository, branch)
    if not head["found"]:
        raise ContractTextError(SETTING, "not_found_on_forge")
    ref: str = head["head_sha"]

    def fetch() -> dict[str, Any]:
        check_file(fg, repository, ref, path)
        try:
            data = fg.file_at(repository, path, ref, FILE_CAP)
        except ValueError as error:
            if str(error) == "too large":
                raise ContractTextError(SETTING, "too_large") from None
            raise ContractTextError(SETTING, "not_found_on_forge") from None
        if data is None:
            raise ContractTextError(SETTING, "not_found_on_forge")
        try:
            markdown = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ContractTextError(SETTING, "not_text") from None
        digest = hashlib.sha256()
        for part in (repository.encode(), path.encode(), data):
            digest.update(len(part).to_bytes(8, "big") + part)
        return {
            "path": path,
            "ref": ref,
            "url": blob_url(repository, ref, path),
            "size": len(data),
            "fetched_at": clock.rfc3339(clock.now()),
            "toc": toc(markdown),
            "text": markdown,
            "etag": f'"{digest.hexdigest()[:32]}"',
        }

    return _once((repository, ref, path, WHOLE), fetch)
