"""The Keep the Why views' reads (docs/api.md §11.5): a published export whole, and a lean
export's entry texts, for the project's family and the public repositories it names.

Nothing here reads a URL of its own: a state URL comes from a `.keep-the-why` that §11.3's
walk read through the forge, a bodies file is one segment beside it, and a repository other
than the project's own is served only when the project's own `.keep-the-why` files name it
(a URL-form child or a `parent:` line), it is public, and it is among the first MAX_NAMED.
The files are read under §11.1 by `outbound`, kept in `ktw.RAW` (shared with §11.3's reads),
and never stored.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from maity_hub import bounded, forge, ktw, outbound

BODIES_CAP = 4 * 1024 * 1024
MAX_NAMED = 8
_BODIES_NAME = re.compile(r"[A-Za-z0-9._-]{1,95}\.json", re.ASCII)  # fullmatch
# §11.5 "A repository's name": the one accepted form, and nothing else.
# ASCII only (explicit ranges), matched whole with fullmatch: `$` would admit a final newline.
_NAME = re.compile(
    r"https://github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?", re.ASCII
)
IN_FLIGHT_ALL = 16  # §11.5's reads in flight across the hub
HELD_KEPT = 4096  # when each file and family was last read, for the 30 s hold after a drop


class Refused(Exception):
    """An answer of §11.5's error list: `status`, `code`, and `details`."""

    def __init__(self, http_status: int, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.status = http_status
        self.code = code
        self.message = message
        self.details = details


@dataclass
class Served:
    canonical: str
    root: str
    raw: ktw.Raw
    fresh: bool

    @property
    def etag(self) -> str:
        key = "\n".join((self.canonical, self.root, self.raw.url, self.raw.digest))
        return '"' + hashlib.sha256(key.encode()).hexdigest()[:32] + '"'

    def document(self, field_name: str) -> bytes:
        """The answer's bytes: the fields, then the file as kept, spliced in unparsed."""
        head = {
            "canonical": self.canonical,
            "root": self.root,
            "url": self.raw.url,
            "observed_at": self.raw.observed_at,
            "fresh": self.fresh,
        }
        if field_name == "state":
            head["fork_of"] = None
        start = json.dumps(head, ensure_ascii=False, separators=(",", ":")).encode()
        return start[:-1] + b',"' + field_name.encode() + b'":' + self.raw.body + b"}"


# --- which repositories ----------------------------------------------------------------------


def _repository(url: str | None) -> str | None:
    """`owner/repo`, lower case, when `url` has exactly the accepted form; None otherwise.
    Every read of a named repository is built from this value alone."""
    if not isinstance(url, str):
        return None
    match = _NAME.fullmatch(url)
    if match is None or match.group(2) in (".", "..") or match.group(2).lower().endswith(".git"):
        return None
    return f"{match.group(1)}/{match.group(2)}".lower()  # ASCII only: ASCII case folding


def named(members: list[ktw.Member], own: str) -> list[str]:
    """The repositories the project's own `.keep-the-why` files name, in the order §11.3
    lists the members: a URL-form child location, then each member's `parent:` line."""
    found: list[str] = []
    for member in members:
        candidates: list[str | None] = []
        if (member.error or {}).get("reason") == "location_not_followed":
            candidates.append(member.location)
        candidates.append(member.parent)
        for url in candidates:
            repository = _repository(url)
            if repository and repository != own and repository not in found:
                found.append(repository)
    return found


# --- the families of named repositories -------------------------------------------------------


@dataclass
class _Foreign:
    family: ktw.Family | None  # None: not configured
    error: str | None
    at: float


FOREIGN_KEPT = ktw.PROJECTS_KEPT * MAX_NAMED


@dataclass
class ForeignCache:
    """The family of each named repository, per project and repository, read at most once
    per FORCE_INTERVAL; one read of one at a time."""

    entries: OrderedDict[tuple[str, str], _Foreign] = field(default_factory=OrderedDict)
    locks: dict[tuple[str, str], threading.Lock] = field(default_factory=dict)
    guard: threading.Lock = field(default_factory=threading.Lock)

    def clear(self) -> None:
        with self.guard:
            self.entries.clear()
            self.locks.clear()

    def get(
        self, reader: forge.Forge, project_id: str, repository: str, max_age: int
    ) -> tuple[_Foreign, bool]:
        key = (project_id, repository)
        with self.guard:
            lock = self.locks.setdefault(key, threading.Lock())
            current = self.entries.get(key)
        if not lock.acquire(timeout=ktw.LOCK_WAIT):
            if current is not None:
                return current, False
            raise ktw.Busy
        try:
            with self.guard:
                current = self.entries.get(key)
            if current is not None and ktw._now() - current.at < _refresh(max_age):
                return current, False
            held = f"{project_id}|{repository}"
            if current is None and _held("family", held):
                return _Foreign(None, "timeout", ktw._now()), False  # dropped for room
            _mark_read("family", held)
            found = self._read(reader, repository)
            with self.guard:
                for gone in bounded.put(self.entries, key, found, FOREIGN_KEPT, lambda k: False):
                    self.locks.pop(gone, None)
            return found, True
        finally:
            lock.release()

    @staticmethod
    def _read(reader: forge.Forge, repository: str) -> _Foreign:
        now = ktw._now()
        seen = _visibility(reader, repository)
        if seen is not None:
            return _Foreign(None, seen, now)
        try:
            family = ktw.walk(reader, repository, ktw._now() + ktw.FAMILY_DEADLINE)
        except ktw.NotConfigured:
            return _Foreign(None, "config_missing", now)
        except ktw.RootUnavailable as failed:
            if failed.retry_at is not None:  # the source's budget is spent: probe_unavailable
                raise forge.ForgeUnavailableError(
                    "the forge's rate limit is spent", rate_limited=True, retry_at=failed.retry_at
                ) from None
            return _Foreign(None, "forge_unavailable", now)
        return _Foreign(family, None, now)


VISIBILITY_SECONDS = 600  # a named repository's visibility, read again at least this often


def _refresh(max_age: int) -> float:
    """How long a named repository's family and visibility answer: `max_age` (at least
    FORCE_INTERVAL), never more than VISIBILITY_SECONDS (§11.5)."""
    return min(max(max_age, ktw.FORCE_INTERVAL), VISIBILITY_SECONDS)


def _visibility(reader: forge.Forge, repository: str) -> str | None:
    """None when the forge reports the repository public; else why it is not served:
    `repository_moved` for a redirect (never followed, §11.4), `not_public` for a private
    repository or one whose visibility cannot be read. A spent budget is `forge.
    ForgeUnavailableError` with `retry_at`, for the caller to answer `probe_unavailable`."""
    path = f"/repos/{repository}"
    try:
        # without a token the hub asks anonymously: `_get` needs a token
        found = reader._get(path, uncached=True) if reader.token else reader._send(path)
    except forge.NotCoveredError as error:
        return "repository_moved" if error.reason == "repository_moved" else "not_public"
    except forge.ForgeUnavailableError as error:
        if error.retry_at is not None:
            raise
        return "not_public"
    return None if isinstance(found, dict) and found.get("private") is False else "not_public"


FOREIGN = ForeignCache()


def named_reader(instance: forge.Forge) -> forge.Forge:
    """The reader of a named repository (§11.5): the operator's instance token where one is
    set, else none; never a project owner's grant, and bound to no project, so no source of
    §11.4 is chosen for it. Its reads count against that source's hub-wide budget."""
    return forge.Forge(instance.token)


def require_covered(reader: forge.Forge, repository: str) -> None:
    """The project's own repository is still covered by the source `for_project` chose, on
    every call and not only when the cache is refreshed, so no export held in memory is
    served after a grant is gone or the repository turned private. With the instance token
    this is §11.4's visibility check (kept for 10 minutes); an owner's grant is re-chosen by
    `for_project` itself. `forge.NotCoveredError` or `forge.ForgeUnavailableError` else."""
    if reader.refused is not None:
        raise forge.NotCoveredError(reader.refused)
    if reader.granted is None and reader.token is not None:
        reader._require_public(repository)


# At most ktw.IN_FLIGHT of one project's §11.5 reads at once.
_slots: dict[str, threading.BoundedSemaphore] = {}
_slots_guard = threading.Lock()


SLOTS_KEPT = 1024


def _slot(project_id: str) -> threading.BoundedSemaphore:
    with _slots_guard:
        if project_id not in _slots and len(_slots) >= SLOTS_KEPT:
            # forget the projects with no read in flight; one in use is kept
            for idle in [p for p, sem in _slots.items() if sem._value == ktw.IN_FLIGHT]:
                del _slots[idle]
        return _slots.setdefault(project_id, threading.BoundedSemaphore(ktw.IN_FLIGHT))


_all = threading.BoundedSemaphore(IN_FLIGHT_ALL)
# When each file was last read, kept apart from the store, so that a file dropped for room
# is not read again inside FORCE_INTERVAL (§11.5).
_read_at: OrderedDict[tuple[str, str], float] = OrderedDict()
_read_at_guard = threading.Lock()


def _held(kind: str, url: str) -> bool:
    with _read_at_guard:
        at = _read_at.get((kind, url))
    return at is not None and ktw._now() - at < ktw.FORCE_INTERVAL


def _mark_read(kind: str, url: str) -> None:
    with _read_at_guard:
        _read_at[(kind, url)] = ktw._now()
        _read_at.move_to_end((kind, url))
        while len(_read_at) > HELD_KEPT:
            _read_at.popitem(last=False)


# --- the reads -------------------------------------------------------------------------------


def _unavailable(reason: str, last: Served | None = None, **details: Any) -> Refused:
    if last is not None:
        details["last"] = json.loads(last.document("state"))
    return Refused(
        503,
        "ktw_unavailable",
        "the Keep the Why export could not be read",
        reason=reason,
        **details,
    )


def _member(
    reader: forge.Forge,
    others: forge.Forge,
    project_id: str,
    repository_url: str,
    canonical: str | None,
    root: str,
    max_age: int,
) -> tuple[str, ktw.Member]:
    """(canonical URL, member) for the request, or `Refused`."""
    own = forge.repository_of(repository_url).lower()
    try:
        entry, _fresh = ktw.CACHE.get(reader, project_id, repository_url, max_age)
    except ktw.Busy:
        raise _unavailable("forge_unavailable") from None
    snapshot = entry.snapshot
    if snapshot is None:
        raise Refused(
            409,
            "ktw_not_configured",
            "the repository names no Keep the Why export (.keep-the-why, dashboard-state)",
        )
    if snapshot.not_covered is not None:
        raise forge.NotCoveredError(snapshot.not_covered)
    if snapshot.retry_at is not None:
        raise forge.ForgeUnavailableError(
            "the forge's rate limit is spent", rate_limited=True, retry_at=snapshot.retry_at
        )
    if snapshot.error is not None:
        raise _unavailable(snapshot.error["reason"])
    wanted = own if not canonical else _repository(canonical)
    if wanted is None:
        raise Refused(
            404, "not_found", "not a repository of this project's family", reason="not_in_family"
        )
    members = snapshot.members
    if wanted != own:
        names = named(snapshot.members, own)
        if wanted not in names:
            raise Refused(
                404,
                "not_found",
                "not a repository of this project's family",
                reason="not_in_family",
            )
        if names.index(wanted) >= MAX_NAMED:
            raise Refused(
                404, "not_found", "past the repositories a project may name", reason="family_cap"
            )
        try:
            foreign, _fresh = FOREIGN.get(others, project_id, wanted, max_age)
        except ktw.Busy:
            raise _unavailable("forge_unavailable") from None
        if foreign.error == "not_public":
            raise Refused(404, "not_found", "the repository is not public", reason="not_public")
        if foreign.error is not None or foreign.family is None:
            raise _unavailable(foreign.error or "config_missing")
        members = foreign.family.members
    for member in members:
        if member.path == root and (member.error or {}).get("reason") != "location_not_followed":
            return f"https://github.com/{wanted}", member
    raise Refused(404, "not_found", "not a member of this family", reason="not_in_family")


def _read(kind: str, url: str, cap: int) -> ktw.Raw:
    """Reads a published file under §11.1 and keeps it; `ktw.MemberError` on failure."""
    try:
        answer = outbound.read(url, cap=cap, headers={"Accept": "application/json"})
    except outbound.Refused as refused:
        raise ktw.MemberError(ktw._REFUSALS.get(refused.reason, "unavailable")) from None
    if answer.status != 200:
        raise ktw.MemberError("http_status", status=answer.status)
    data = ktw.parse(answer.body)
    if kind == "state":
        ktw.digest(data, ktw.dashboard_url(url))  # §11.3's checks: version and shape
        return ktw.RAW.keep_state(url, data)
    if not isinstance(data, dict) or not isinstance(data.get("bodies"), dict):
        raise ktw.MemberError("shape")
    return ktw.RAW.put("bodies", url, data["bodies"])


def _file(
    project_id: str, kind: str, url: str, cap: int, max_age: int, start: float
) -> tuple[ktw.Raw, bool]:
    """(file, fresh): `fresh` when it was read since `start`, the request's beginning, by
    this call or by §11.3's read of the family that the same call made."""
    kept = ktw.RAW.get(kind, url)
    if kept is not None and ktw._now() - kept.at < max(max_age, ktw.FORCE_INTERVAL):
        return kept, kept.at >= start
    if _held(kind, url):  # a read, or a failed one, less than 30 s ago
        if kept is not None:
            return kept, False
        raise ktw.MemberError("timeout")  # dropped for room meanwhile
    slot = _slot(project_id)
    if not slot.acquire(timeout=ktw.FAMILY_DEADLINE):
        raise ktw.MemberError("timeout")
    try:
        if not _all.acquire(timeout=ktw.FAMILY_DEADLINE):
            raise ktw.MemberError("timeout")
        try:
            _mark_read(kind, url)
            return _read(kind, url, cap), True
        finally:
            _all.release()
    finally:
        slot.release()


def export(
    reader: forge.Forge,
    others: forge.Forge,
    project_id: str,
    repository_url: str,
    canonical: str | None,
    root: str,
    max_age: int,
) -> Served:
    start = ktw._now()
    canonical_url, member = _member(
        reader, others, project_id, repository_url, canonical, root, max_age
    )
    if member.error is not None or not member.state_url:
        error = member.error or {"reason": "no_state_url"}
        extra = {k: v for k, v in error.items() if k in ("status", "version")}
        kept = ktw.RAW.get("state", member.state_url) if member.state_url else None
        last = Served(canonical_url, root, kept, False) if kept is not None else None
        raise _unavailable(error["reason"], last, **extra)
    try:
        raw, fresh = _file(project_id, "state", member.state_url, ktw.STATE_CAP, max_age, start)
    except ktw.MemberError as failed:
        kept = ktw.RAW.get("state", member.state_url)
        last = Served(canonical_url, root, kept, False) if kept is not None else None
        raise _unavailable(failed.reason, last, **failed.details) from None
    return Served(canonical_url, root, raw, fresh)


def bodies_url(state_url: str, name: Any) -> str | None:
    """The bodies file beside the state, or None when `name` is not one plain segment."""
    if not isinstance(name, str) or not _BODIES_NAME.fullmatch(name) or name in (".json", "..json"):
        return None
    return ktw.dashboard_url(state_url) + name


def bodies(
    reader: forge.Forge,
    others: forge.Forge,
    project_id: str,
    repository_url: str,
    canonical: str | None,
    root: str,
    max_age: int,
) -> Served:
    start = ktw._now()
    state = export(reader, others, project_id, repository_url, canonical, root, max_age)
    if state.raw.bodies is None:
        raise Refused(
            404, "not_found", "this export carries its bodies inline", reason="no_bodies_file"
        )
    url = bodies_url(state.raw.url, state.raw.bodies)
    if url is None:
        raise _unavailable("bodies_url_invalid")
    try:
        raw, fresh = _file(project_id, "bodies", url, BODIES_CAP, max_age, start)
    except ktw.MemberError as failed:
        raise _unavailable(failed.reason, **failed.details) from None
    return Served(state.canonical, root, raw, fresh)
