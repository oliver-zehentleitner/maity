"""A project's Keep the Why export, read from its repository (docs/api.md §11.3).

The repository is the one source: the root `.keep-the-why` on the default branch names
the published `state.json` (`dashboard-state:`) and the children, whose own
`.keep-the-why` files do the same, down to `MAX_DEPTH` levels and `MAX_MEMBERS` members.
The hub reads them, keeps the answer in memory for `max_age` seconds, and never stores the
export or reads `context/` itself.

Everything read is untrusted data: control characters go, strings are cut, the hub takes
no URL from an export, and a family location is followed only when it is a plain relative
directory below the file that lists it.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import threading
import time
import urllib.parse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from maity_hub import clock, forge, outbound

log = logging.getLogger(__name__)

CONFIG_CAP = 64 * 1024
STATE_CAP = 1024 * 1024
MAX_DEPTH = 4
MAX_MEMBERS = 32
MAX_ATTENTION = 200
IN_FLIGHT = 4
DEFAULT_MAX_AGE = 600
FAMILY_DEADLINE = 30.0  # seconds for one read of a whole family, configs and exports
LOCK_WAIT = 0.5  # seconds a request with nothing cached waits for a read in progress
FORCE_INTERVAL = 30.0
STATUSES = ("active", "open", "needs-review", "pending-confirmation", "superseded")
ATTENTION_ORDER = ("needs-review", "pending-confirmation", "open")
STATE_JSON_MAJOR = 2

_OPEN = {name: re.compile(rf"<!--\s*keep-the-why:{name}\s*-->") for name in ("config", "children")}
_CLOSE = {
    name: re.compile(rf"<!--\s*/keep-the-why:{name}\s*-->") for name in ("config", "children")
}
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
_SETTING = re.compile(r"^\s*-\s*([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$")
_CHILD = re.compile(r"^\s*-\s*([^:]+?)\s*:\s*(\S+)(?:\s+—\s+.*)?\s*$")
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_CONTROL = re.compile(
    "[\\x00-\\x1f\\x7f-\\x9f\\u061c\\u200b-\\u200f\\u2028-\\u202e\\u2066-\\u2069\\ufeff"
    "\\ud800-\\udfff]"  # lone surrogates: json.loads accepts them, UTF-8 cannot encode them
)


def _now() -> float:
    return time.monotonic()


class Busy(Exception):
    """The family is being read by another request beyond the budget, and nothing is cached."""


class NotConfigured(Exception):
    """No repository, no root `.keep-the-why`, or no `dashboard-state:` line in it."""


class RootUnavailable(Exception):
    """The root `.keep-the-why` could not be read; the whole export fails."""


class MemberError(Exception):
    def __init__(self, reason: str, **details: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details


# --- untrusted strings -----------------------------------------------------------------------


def text(value: Any, limit: int) -> str | None:
    """A string from outside the hub: control, direction and zero-width characters and lone
    surrogates removed, cut at `limit` characters with `…` as the last one; None when it is
    not a string."""
    if not isinstance(value, str):
        return None
    cleaned = _CONTROL.sub("", value)
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


# --- .keep-the-why ---------------------------------------------------------------------------


def _unquote(value: str) -> str:
    return value.strip().strip("`").strip()


def _block(source: str, name: str) -> str:
    """The text between the first `keep-the-why:<name>` marker and the closing one after it.
    Two linear searches: a non-greedy regex over the whole block is quadratic on a file of
    unclosed markers."""
    opened = _OPEN[name].search(source)
    if opened is None:
        return ""
    closed = _CLOSE[name].search(source, opened.end())
    return source[opened.end() : closed.start()] if closed else ""


def config(source: str) -> dict[str, str]:
    """The `- key: value` lines of the config block."""
    found: dict[str, str] = {}
    for line in _block(source, "config").splitlines():
        match = _SETTING.match(line)
        if match and match.group(1) not in found:
            found[match.group(1)] = _unquote(match.group(2))
    return found


def children(source: str) -> list[tuple[str, str]]:
    """(name, location) of each line of the children block, in order."""
    found = []
    for line in _block(source, "children").splitlines():
        match = _CHILD.match(line)
        if match:
            found.append((match.group(1), _unquote(match.group(2))))
    return found


def child_path(parent: str, location: str) -> str | None:
    """The child's directory inside the repository, or None when the location may not be
    followed: only relative paths of plain segments, never `.`, `..`, absolute, a
    backslash or a URL."""
    if not location or "\\" in location or "://" in location or location.startswith("/"):
        return None
    segments = location.rstrip("/").split("/")
    if not all(_SEGMENT.match(s) and s not in (".", "..") for s in segments):
        return None
    return "/".join([parent, *segments]) if parent else "/".join(segments)


def state_url_valid(url: str) -> bool:
    """https, at most 2048 characters, a host name (no address literal), no user info, no
    port but 443, and nothing a viewer could be misled by: no whitespace, control, direction
    or zero-width character."""
    if len(url) > 2048 or _CONTROL.search(url) or any(c.isspace() for c in url):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = parts.hostname
    if parts.scheme != "https" or not host or parts.username is not None or port not in (None, 443):
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return True
    return False


def dashboard_url(state_url: str) -> str:
    """The state URL without its last path segment, query and fragment."""
    parts = urllib.parse.urlsplit(state_url)
    path = parts.path.rsplit("/", 1)[0] + "/"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))


# --- the export ------------------------------------------------------------------------------


@dataclass
class Read:
    """One member's export as the hub relies on it: the counts, and only the entries that
    can reach the attention list (at most MAX_ATTENTION + 1, in attention order), so that a
    family of large exports does not stay in memory."""

    summary: dict[str, Any]
    entries: list[dict[str, Any]]
    skipped: int


def _major(version: Any) -> int | None:
    if isinstance(version, bool):
        return None
    if isinstance(version, int):
        return version
    if isinstance(version, str):
        head = version.split(".", 1)[0]
        if head.isdigit():
            return int(head)
    return None


def _generated(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if not _RFC3339.match(value):
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return text(value, 40)


def _attention_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    """Attention order inside one member: status, then file and line (§11.3)."""
    line = entry["line"] if entry["line"] is not None else 0
    return (ATTENTION_ORDER.index(entry["status"]), entry["file"] or "", line)


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def digest(data: Any, link_base: str) -> Read:
    """The parts of a parsed `state.json` the hub relies on; `MemberError` when the export
    cannot be used."""
    if not isinstance(data, dict):
        raise MemberError("shape")
    major = _major(data.get("state-json"))
    if major != STATE_JSON_MAJOR:
        raise MemberError("state_json_version", version=text(str(data.get("state-json")), 40))
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise MemberError("shape")
    topics: dict[str, str] = {}
    raw_topics = data.get("topics")
    for topic in raw_topics if isinstance(raw_topics, list) else []:
        if isinstance(topic, dict) and isinstance(topic.get("file"), str):
            title = text(topic.get("title"), 200)
            if title is not None:
                topics.setdefault(topic["file"], title)
    entries: list[dict[str, Any]] = []
    valid = 0
    skipped = 0
    status_counts = {s: 0 for s in STATUSES} | {"other": 0}
    for raw in raw_entries:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            skipped += 1
            continue
        entry_id = text(raw["id"], 300) or ""
        uuid = text(raw.get("uuid"), 64)
        types = raw.get("type")
        if isinstance(types, str):
            types = [types]
        type_list = (
            [t for t in (text(v, 40) for v in types[:8]) if t] if isinstance(types, list) else []
        )
        status: str = raw["status"] if raw.get("status") in STATUSES else "other"
        status_counts[status] += 1
        valid += 1
        if status not in ATTENTION_ORDER:
            continue
        file = text(raw.get("file"), 200)
        line = raw.get("line") if _count(raw.get("line")) is not None else None
        anchor = urllib.parse.quote(uuid or entry_id, safe="")
        entries.append(
            {
                "id": entry_id,
                "uuid": uuid,
                "title": text(raw.get("title"), 200) or entry_id,
                "type": type_list,
                "status": status,
                "file": file,
                "line": line,
                "topic": topics.get(raw["file"]) if isinstance(raw.get("file"), str) else None,
                "link": f"{link_base}#entry/{anchor}",
            }
        )
    entries.sort(key=_attention_key)
    del entries[MAX_ATTENTION + 1 :]
    found_findings = data.get("findings")
    findings: dict[str, Any] = found_findings if isinstance(found_findings, dict) else {}
    summary = {
        "generated": _generated(data.get("generated")),
        "state_json": major,
        "entries": valid,
        "status": status_counts,
        "attention": sum(status_counts[s] for s in ATTENTION_ORDER),
        "findings": {
            "errors": _count(findings.get("errors")),
            "warnings": _count(findings.get("warnings")),
        },
    }
    return Read(summary, entries, skipped)


_REFUSALS = {
    "address_refused": "address_refused",
    "redirect_refused": "redirect_refused",
    "timeout": "timeout",
    "too_large": "too_large",
    "url_invalid": "state_url_invalid",
    "unavailable": "unavailable",  # connection or TLS refused: the host did not answer
}


def read_state(url: str) -> Read:
    """GET a member's `state.json` under the transport rule and digest it."""
    try:
        answer = outbound.read(url, cap=STATE_CAP, headers={"Accept": "application/json"})
    except outbound.Refused as refused:
        raise MemberError(_REFUSALS.get(refused.reason, "unavailable")) from None
    if answer.status != 200:
        raise MemberError("http_status", status=answer.status)
    try:
        data = json.loads(answer.body)
    except (ValueError, UnicodeDecodeError, RecursionError):  # nesting deep enough to recurse
        raise MemberError("not_json") from None
    return digest(data, dashboard_url(url))


# --- the family ------------------------------------------------------------------------------


@dataclass
class Member:
    path: str
    name: str | None
    id: str | None = None
    state_url: str | None = None
    observed_at: str | None = None
    read: Read | None = None
    error: dict[str, Any] | None = None

    def view(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "id": self.id,
            "name": self.name,
            "state_url": self.state_url,
            "dashboard_url": dashboard_url(self.state_url) if self.state_url else None,
            "observed_at": self.observed_at,
            "summary": self.read.summary if self.read else None,
            "error": self.error,
        }


@dataclass
class Family:
    members: list[Member]
    truncated: bool


def _error(reason: str, **details: Any) -> dict[str, Any]:
    return {"code": "ktw_unavailable", "reason": reason, **details}


def walk(reader: forge.Forge, repository: str, deadline: float | None = None) -> Family:
    """The family's members in order, depth first, with their config read; the exports are
    read afterwards. `NotConfigured`/`RootUnavailable` for the root. A child whose config
    would be read after `deadline` (`_now()`) is listed with `timeout`, not read."""
    members: list[Member] = []
    seen: set[str] = set()
    truncated = False

    def read_config(path: str) -> str | None:
        file = f"{path}/.keep-the-why" if path else ".keep-the-why"
        try:
            data = reader.file(repository, file, CONFIG_CAP)
        except forge.ForgeUnavailableError:
            raise MemberError("forge_unavailable") from None
        except ValueError:
            raise MemberError("too_large") from None
        return None if data is None else data.decode("utf-8", errors="replace")

    def visit(path: str, name: str | None, source: str, depth: int) -> None:
        nonlocal truncated
        settings = config(source)
        member = Member(path=path, name=name, id=text(settings.get("id"), 200))
        state = settings.get("dashboard-state")
        if not state:
            member.error = _error("no_state_url")
        elif not state_url_valid(state):
            member.error = _error("state_url_invalid")
        else:
            member.state_url = state
        members.append(member)
        for child_name, location in children(source):
            if len(members) >= MAX_MEMBERS:
                truncated = True
                return
            clean_name = text(child_name, 200)
            target = child_path(path, location)
            if target is None:
                shown = text(location, 200)
                if not shown or shown in seen:
                    continue  # nothing left to show, or listed already: never a second ""
                seen.add(shown)
                members.append(
                    Member(path=shown, name=clean_name, error=_error("location_not_followed"))
                )
                continue
            if target in seen:
                continue
            seen.add(target)
            if depth + 1 > MAX_DEPTH:
                truncated = True
                continue
            if deadline is not None and _now() >= deadline:
                members.append(Member(path=target, name=clean_name, error=_error("timeout")))
                continue
            try:
                child_source = read_config(target)
            except MemberError as failed:
                members.append(Member(path=target, name=clean_name, error=_error(failed.reason)))
                continue
            if child_source is None:
                members.append(Member(path=target, name=clean_name, error=_error("config_missing")))
                continue
            visit(target, clean_name, child_source, depth + 1)

    try:
        root = read_config("")
    except MemberError:
        raise RootUnavailable from None
    if root is None or not config(root).get("dashboard-state"):
        raise NotConfigured
    seen.add("")
    visit("", None, root, 0)
    return Family(members, truncated)


def _one_export(url: str) -> Read | dict[str, Any]:
    """A member's export, or its error. The export is foreign data: whatever goes wrong
    reading or digesting it stays with this member (§11.3)."""
    try:
        return read_state(url)
    except MemberError as failed:
        return _error(failed.reason, **failed.details)
    except Exception:
        log.warning("a Keep the Why export could not be digested", exc_info=False)
        return _error("shape")


def _read_exports(family: Family, deadline: float) -> None:
    """Every member's export, at most IN_FLIGHT at once; a member not read by `deadline`
    is `timeout`. The results are assigned here, never by the reading threads, so a read
    that finishes late changes nothing."""
    readable = [m for m in family.members if m.state_url and m.error is None]
    if not readable:
        return
    pool = ThreadPoolExecutor(max_workers=IN_FLIGHT, thread_name_prefix="maity-ktw-read")
    try:
        futures = {pool.submit(_one_export, m.state_url or ""): m for m in readable}
        for future, member in futures.items():
            try:
                found = future.result(timeout=max(deadline - _now(), 0.0))
            except FutureTimeout:
                found = _error("timeout")
            if isinstance(found, Read):
                member.read = found
            else:
                member.error = found
            member.observed_at = clock.rfc3339(clock.now())
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


# --- the answer ------------------------------------------------------------------------------


def _aggregate(members: list[Member]) -> dict[str, Any]:
    reads = [m.read for m in members if m.read is not None]
    status = {s: sum(r.summary["status"][s] for r in reads) for s in (*STATUSES, "other")}
    errors = [r.summary["findings"]["errors"] for r in reads]
    warnings = [r.summary["findings"]["warnings"] for r in reads]
    return {
        "members": len(members),
        "failed": sum(1 for m in members if m.error is not None),
        "entries": sum(r.summary["entries"] for r in reads),
        "status": status,
        "attention": sum(r.summary["attention"] for r in reads),
        "findings": {
            "errors": (
                sum(e for e in errors if e is not None)
                if any(e is not None for e in errors)
                else None
            ),
            "warnings": (
                sum(w for w in warnings if w is not None)
                if any(w is not None for w in warnings)
                else None
            ),
        },
    }


def _attention(members: list[Member]) -> tuple[list[dict[str, Any]], bool]:
    found: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for order, member in enumerate(members):
        for entry in member.read.entries if member.read else []:
            status, *place = _attention_key(entry)
            found.append(((status, order, *place), {"member": member.path, **entry}))
    found.sort(key=lambda item: item[0])
    return [entry for _key, entry in found[:MAX_ATTENTION]], len(found) > MAX_ATTENTION


@dataclass
class Snapshot:
    """One read of the family, as answers and the project view need it."""

    observed_at: str
    members: list[Member]
    family_truncated: bool
    error: dict[str, Any] | None = None

    def answer(self, member: str | None = None, fresh: bool = True) -> dict[str, Any]:
        members = self.members
        if member is not None:
            members = [m for m in self.members if m.path == member]
        attention, truncated = _attention(members)
        return {
            "observed_at": self.observed_at,
            "fresh": fresh,
            "summary": _aggregate(members),
            "members": [m.view() for m in members],
            "attention": attention,
            "family_truncated": self.family_truncated,
            "truncated": truncated,
            "skipped": sum(m.read.skipped for m in members if m.read),
            "error": self.error,
        }

    def export(self) -> dict[str, Any]:
        """The project view's `keep_the_why_export` (§6.1)."""
        return {
            "observed_at": self.observed_at,
            "summary": _aggregate(self.members),
            "members": [m.view() for m in self.members],
            "family_truncated": self.family_truncated,
            "error": self.error,
        }


# --- the cache -------------------------------------------------------------------------------


@dataclass
class _Entry:
    snapshot: Snapshot | None  # None: the project is not configured
    at: float  # _now() of the read
    repository_url: str | None


@dataclass
class Cache:
    """The answers per project, in memory; the last good read of each member until the hub
    restarts. One read of a project's family at a time."""

    entries: dict[str, _Entry] = field(default_factory=dict)
    last_good: dict[tuple[str, str], tuple[Read, str | None]] = field(default_factory=dict)
    locks: dict[str, threading.Lock] = field(default_factory=dict)
    guard: threading.Lock = field(default_factory=threading.Lock)

    def clear(self) -> None:
        with self.guard:
            self.entries.clear()
            self.last_good.clear()
            self.locks.clear()

    def forget(self, project_id: str) -> None:
        with self.guard:
            self.entries.pop(project_id, None)
            for key in [k for k in self.last_good if k[0] == project_id]:
                del self.last_good[key]

    def cached(self, project_id: str) -> _Entry | None:
        with self.guard:
            return self.entries.get(project_id)

    def _lock(self, project_id: str) -> threading.Lock:
        with self.guard:
            return self.locks.setdefault(project_id, threading.Lock())

    def get(
        self,
        reader: forge.Forge,
        project_id: str,
        repository_url: str | None,
        max_age: int = DEFAULT_MAX_AGE,
    ) -> tuple[_Entry, bool]:
        """(entry, fresh): a cached answer younger than `max_age`, else a new read. No
        `max_age` reads more often than FORCE_INTERVAL (`0` forces a read at that rate).

        While another request reads the family, the cached answer is served at once, and a
        request with nothing cached waits at most LOCK_WAIT before `Busy`: a waiter holds a
        request thread, and a family read may take FAMILY_DEADLINE."""
        current = self.cached(project_id)
        lock = self._lock(project_id)
        usable = current is not None and current.repository_url == repository_url
        if not (lock.acquire(blocking=False) if usable else lock.acquire(timeout=LOCK_WAIT)):
            if current is not None and usable:
                return current, False
            raise Busy
        try:
            entry = self.cached(project_id)
            if (
                entry is not None
                and entry.repository_url == repository_url
                and _now() - entry.at < max(max_age, FORCE_INTERVAL)
            ):
                return entry, False
            entry = self._read(reader, project_id, repository_url, entry)
            with self.guard:
                self.entries[project_id] = entry
            return entry, True
        finally:
            lock.release()

    def _read(
        self, reader: forge.Forge, project_id: str, repository_url: str | None, last: _Entry | None
    ) -> _Entry:
        now = _now()
        observed = clock.rfc3339(clock.now())
        if forge.kind_of(repository_url) != "github" or repository_url is None:
            return _Entry(None, now, repository_url)
        repository = forge.repository_of(repository_url)
        deadline = _now() + FAMILY_DEADLINE
        reader = reader.for_project(project_id)  # the source that covers it (§11.4)
        try:
            family = walk(reader, repository, deadline)
        except NotConfigured:
            return _Entry(None, now, repository_url)
        except RootUnavailable:
            previous = last.snapshot if last and last.repository_url == repository_url else None
            error = _error("forge_unavailable")
            if previous is None:
                return _Entry(Snapshot(observed, [], False, error), now, repository_url)
            kept = Snapshot(
                previous.observed_at, previous.members, previous.family_truncated, error
            )
            return _Entry(kept, now, repository_url)
        _read_exports(family, deadline)
        for member in family.members:
            if (member.error or {}).get("reason") == "location_not_followed":
                continue  # its path is location text, never read: no last good read
            key = (project_id, member.path)
            if member.read is not None:
                self.last_good[key] = (member.read, member.observed_at)
            elif member.error is not None and key in self.last_good:
                member.read, _at = self.last_good[key]
        return _Entry(Snapshot(observed, family.members, family.truncated), now, repository_url)


CACHE = Cache()


# --- for the project view: never a read in the request ---------------------------------------

_background = ThreadPoolExecutor(max_workers=2, thread_name_prefix="maity-ktw")
_pending: set[str] = set()
_pending_lock = threading.Lock()


def export_for_view(
    reader: forge.Forge,
    project_id: str,
    repository_url: str | None,
    schedule: Callable[[Callable[[], None]], None] | None = None,
) -> dict[str, Any] | None:
    """The cached export, or None; a missing or stale one is refreshed in the background so
    that building the view never waits on a read."""
    entry = CACHE.cached(project_id)
    stale = (
        entry is None
        or entry.repository_url != repository_url
        or _now() - entry.at >= DEFAULT_MAX_AGE
    )
    if stale and forge.kind_of(repository_url) == "github":
        _refresh_later(reader, project_id, repository_url, schedule)
    if entry is None or entry.snapshot is None or entry.repository_url != repository_url:
        return None
    return entry.snapshot.export()


def _refresh_in_background(
    reader: forge.Forge,
    project_id: str,
    repository_url: str | None,
    schedule: Callable[[Callable[[], None]], None] | None,
) -> None:
    """One background read per project at a time, on a small pool."""
    with _pending_lock:
        if project_id in _pending:
            return
        _pending.add(project_id)

    def run() -> None:
        try:
            CACHE.get(reader, project_id, repository_url)
        except Exception:  # a failed background read leaves the cache as it was
            pass
        finally:
            with _pending_lock:
                _pending.discard(project_id)

    if schedule is not None:
        schedule(run)
    else:
        _background.submit(run)


# What a view calls; tests replace it so that no read outlives a test.
_refresh_later = _refresh_in_background
