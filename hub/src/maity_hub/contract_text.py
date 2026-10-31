"""A contract card's text, read from the project's repository (docs/api.md §6.8).

The hub keeps no copy: `path` and `section` name a section of a file, read through the
probe at the default branch's commit and cut out by the hub's own heading parser. One
read is kept for `MAX_AGE` seconds and answers concurrent calls, keyed so that a changed
selection, repository or commit is never answered from an older read.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from maity_hub import clock, forge

DEFAULT_PATH = "docs/api.md"
FILE_CAP = 1024 * 1024  # bytes of the file read at all
TEXT_CAP = 64 * 1024  # bytes of the section shown
MAX_AGE = 60  # seconds one read answers (§6.8, as the observation cache of §11)
PATH_MAX = 255
SECTION_MAX = 32

SECTION = re.compile(r"[^\s#]+")
ATX = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
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
        heading = ATX.match(bare)
        if heading:
            title = re.sub(r"[ \t]+#+$", "", heading.group(2) or "")  # a closing sequence
            found.append((index, len(heading.group(1)), title.strip()))
    return found


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


def forget() -> None:
    """Drop every kept read (tests)."""
    with _lock:
        _reads.clear()
        _pending.clear()


def read(fg: forge.Forge, repository: str, branch: str, path: str, section: str) -> dict[str, Any]:
    """The section at the default branch's commit: `{path, section, ref, heading, text,
    url, truncated, fetched_at}`. `forge.ForgeUnavailableError` when the forge does not
    answer; `ContractTextError` when there is nothing to show."""
    head = fg.branch(repository, branch)
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
