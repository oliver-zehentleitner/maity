"""Card links (docs/api.md §6.13): forge issues, pull requests and commits, and plain URLs.

The hub parses a forge URL itself and never takes a title or state from the client;
it observes only links that name the project's own repository.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import Field, field_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import Connection, Engine, insert, select, update

from maity_hub import clock, forge
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid
from maity_hub.ids import new_id
from maity_hub.models import Strict

MAX_LINKS = 20
URL_MAX = 2048
LABEL_MAX = 200
KINDS = ("issue", "pr", "commit", "url")
FORGE_KINDS = ("issue", "pr", "commit")
# GitHub, the one forge of V1 (§11): the path segment that names each kind.
_PATHS = {"issues": "issue", "pull": "pr", "commit": "commit"}
# A commit by its full sha: heads are compared whole, never as a prefix (§6.13).
_SHA = re.compile(r"[0-9a-fA-F]{40}")
_SEGMENT = re.compile(r"[A-Za-z0-9._-]{1,100}")
_NUMBER = re.compile(r"[1-9][0-9]{0,9}")
NUMBER_MAX = 2**31 - 1  # what the forge's API takes as a number


class LinkIn(Strict):
    """A link as a request names it: `{kind: issue|pr|commit, forge_url}` or `{kind: url,
    url, label?}`."""

    kind: str
    forge_url: str | None = Field(default=None, max_length=URL_MAX)
    url: str | None = Field(default=None, max_length=URL_MAX)
    label: str | None = Field(default=None, max_length=LABEL_MAX)
    # The hub's own read, never the client's (§6.13).
    title: Any = None
    state: Any = None
    observed: Any = None

    @field_validator("title", "state", "observed", mode="before")
    @classmethod
    def _read_only(cls, _value: Any) -> Any:
        raise PydanticCustomError("read_only", "observed by the hub")


class LinkError(ValueError):
    """A link the contract refuses; `code` is the `details.fields` value."""

    def __init__(self, field: str, code: str) -> None:
        super().__init__(f"{field}: {code}")
        self.field = field
        self.code = code


@dataclass(frozen=True)
class ForgeRef:
    forge: str
    repository: str  # owner/name
    number: int | None  # None for a commit, named by `sha`
    kind: str  # issue, pr or commit
    url: str  # normalised: no trailing slash, a commit's sha in lower case
    sha: str | None = None  # a commit's, lower case


def _plain_https(url: str, field: str) -> urllib.parse.SplitResult:
    """`https`, a host, no user info; what every link URL must be."""
    if len(url) > URL_MAX or any(c.isspace() or ord(c) < 0x20 for c in url):
        raise LinkError(field, "not_a_url")
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port  # noqa: B018  # a port that is no number raises here, not later
    except ValueError:  # a broken host ("[x"), a port that is no number
        raise LinkError(field, "not_a_url") from None
    if parts.scheme != "https" or not parts.hostname:
        raise LinkError(field, "not_https")
    if "@" in parts.netloc:
        raise LinkError(field, "user_info")
    return parts


def parse_forge(url: str, kind: str, repository_url: str | None) -> ForgeRef:
    """A forge link's URL as §6.13 accepts it, checked against the project's repository:
    `not_a_forge_url`, `kind_mismatch` or `foreign_repository` otherwise."""
    try:
        parts = _plain_https(url, "forge_url")
    except LinkError:
        raise LinkError("forge_url", "not_a_forge_url") from None
    if parts.query or parts.fragment or parts.port is not None:
        raise LinkError("forge_url", "not_a_forge_url")
    host = parts.hostname or ""
    forge_kind = forge.HOSTS.get(host)
    segments = parts.path.removesuffix("/").split("/")
    if forge_kind is None or len(segments) != 5 or segments[0] != "":
        raise LinkError("forge_url", "not_a_forge_url")
    _, owner, name, what, number = segments
    if what == "commit":
        good = bool(_SHA.fullmatch(number))
    else:
        good = bool(_NUMBER.fullmatch(number)) and int(number) <= NUMBER_MAX
    if not _SEGMENT.fullmatch(owner) or not _SEGMENT.fullmatch(name) or what not in _PATHS:
        good = False
    if not good:
        raise LinkError("forge_url", "not_a_forge_url")
    if _PATHS[what] != kind:
        raise LinkError("forge_url", "kind_mismatch")
    if repository_url is None or forge.kind_of(repository_url) != forge_kind:
        raise LinkError("forge_url", "foreign_repository")
    project_owner = forge.repository_of(repository_url).split("/")[0]
    if owner.lower() != project_owner.lower():
        raise LinkError("forge_url", "foreign_repository")
    sha = number.lower() if what == "commit" else None
    return ForgeRef(
        forge=forge_kind,
        repository=f"{owner}/{name}",
        number=None if sha else int(number),
        kind=kind,
        url=f"https://{host}/{owner}/{name}/{what}/{sha or number}",
        sha=sha,
    )


def sha_of(row: Any) -> str:
    """A stored commit link's sha: the last segment of its URL, stored in lower case."""
    return str(row.url).rsplit("/", 1)[-1]


def check_url(url: str) -> str:
    """A `kind: url` link: `https`, at most 2048 characters, no user info."""
    _plain_https(url, "url")
    return url


def check_label(label: str | None) -> str | None:
    if label is None:
        return None
    if len(label) > LABEL_MAX or any(ord(c) < 0x20 for c in label):
        raise LinkError("label", "too_long" if len(label) > LABEL_MAX else "control_character")
    return label


def is_own_repository(ref: ForgeRef, repository_url: str | None) -> bool:
    """Only the project's repository is ever read (§6.13)."""
    if repository_url is None:
        return False
    return forge.repository_of(repository_url).lower() == ref.repository.lower()


# --- stored links ---------------------------------------------------------------------------


def view(row: Any, members: dict[int, str]) -> dict[str, Any]:
    """A link as §6.13 shows it; `members` maps membership rows to member ids."""
    shown: dict[str, Any] = {"id": row.id, "kind": row.kind}
    if row.kind in FORGE_KINDS:
        shown.update(forge_url=row.url, forge=row.forge, repository=row.repository)
        if row.kind == "commit":
            shown.update(sha=sha_of(row))
        else:
            shown.update(number=row.number)
        shown.update(observed=public_observed(row.observed))
    else:
        shown.update(url=row.url, label=row.label)
    shown.update(added_by=members[row.added_by], added_at=clock.rfc3339(row.added_at))
    return shown


def rows_of(conn: Connection, card_ids: Iterable[str]) -> dict[str, list[Any]]:
    """Every card's links in the order they were added, in one query."""
    wanted = list(dict.fromkeys(card_ids))
    found: dict[str, list[Any]] = {card_id: [] for card_id in wanted}
    if not wanted:
        return found
    for row in conn.execute(
        select(t.card_link)
        .where(t.card_link.c.card_id.in_(wanted))
        .order_by(t.card_link.c.added_at, t.card_link.c.id)
    ):
        found[row.card_id].append(row)
    return found


def views_of(conn: Connection, card_ids: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    """`links` of several cards: two queries whatever their number (the board reads 200)."""
    from maity_hub.views import principal_ids  # views reads this module for task views

    rows = rows_of(conn, card_ids)
    members = principal_ids(conn, (r.added_by for found in rows.values() for r in found))
    return {card_id: [view(r, members) for r in found] for card_id, found in rows.items()}


def checked(link: Any, repository_url: str | None) -> dict[str, Any]:
    """The columns of a link the request names, `LinkError` when the contract refuses it.
    `link` has `kind`, `forge_url`, `url`, `label` (a request model)."""
    if link.kind not in KINDS:
        raise LinkError("kind", "unknown")
    if link.kind in FORGE_KINDS:
        if link.url is not None or link.label is not None or link.forge_url is None:
            raise LinkError("forge_url" if link.forge_url is None else "url", "not_with_kind")
        ref = parse_forge(link.forge_url, link.kind, repository_url)
        return {
            "kind": ref.kind,
            "url": ref.url,
            "label": None,
            "forge": ref.forge,
            "repository": ref.repository,
            "number": ref.number,
        }
    if link.forge_url is not None or link.url is None:
        raise LinkError("url" if link.url is None else "forge_url", "not_with_kind")
    return {
        "kind": "url",
        "url": check_url(link.url),
        "label": check_label(link.label),
        "forge": None,
        "repository": None,
        "number": None,
    }


def insert_link(conn: Connection, card_id: str, columns: dict[str, Any], added_by: int) -> Any:
    """Store one checked link, `already_linked` or `link_cap` refused by the caller first."""
    link_id = new_id("link")
    conn.execute(
        insert(t.card_link).values(
            id=link_id,
            card_id=card_id,
            **columns,
            observed=None,
            added_by=added_by,
            added_at=clock.now(),
        )
    )
    return conn.execute(select(t.card_link).where(t.card_link.c.id == link_id)).one()


def link_view(conn: Connection, row: Any) -> dict[str, Any]:
    from maity_hub.views import principal_ids  # views reads this module for task views

    return view(row, principal_ids(conn, [row.added_by]))


def add(
    conn: Connection, card: Any, body: LinkIn, repository_url: str | None, by: int
) -> dict[str, Any]:
    """Check and store one link on `card`; the link's view. The caller records and
    announces it (one `task_updated` per call, or the creation's one entry)."""
    try:
        columns = checked(body, repository_url)
    except LinkError as error:
        raise invalid({error.field: error.code}) from None
    present = rows_of(conn, [card.id])[card.id]
    found = same(present, columns)
    if found is not None:
        raise ApiError(
            409, "already_linked", "the card has this link", {"link": link_view(conn, found)}
        )
    if len(present) >= MAX_LINKS:
        raise invalid({"links": "too_many"}, f"at most {MAX_LINKS} links per card")
    return link_view(conn, insert_link(conn, card.id, columns, by))


def same(rows: Sequence[Any], columns: dict[str, Any]) -> Any | None:
    """The link already on the card with this URL, compared as stored."""
    for row in rows:
        if row.url == columns["url"]:
            return row
    return None


# --- observation (the probe's worker only) ---------------------------------------------------

BATCH = 50  # items per forge read
TITLE_MAX = 200


def observed(link_kind: str, item: dict[str, Any] | None, at: str) -> dict[str, Any]:
    """The `observed` of a link from the forge's answer for its number (§6.13)."""
    if item is None:
        return {"found": False, "observed_at": at}
    is_pr = item["type"] == "PullRequest"
    if link_kind == "issue" and is_pr:
        return {"found": False, "reason": "kind_mismatch", "observed_at": at}
    if link_kind == "pr" and not is_pr:
        return {"found": False, "observed_at": at}
    state = "merged" if is_pr and item["merged"] else item["state"]
    return {"found": True, "title": item["title"][:TITLE_MAX], "state": state, "observed_at": at}


COMMIT_SHOWN = ("found", "sha", "checks", "required_check", "branch_head_sha", "ahead")

# Kept with a commit link's stored observation, never shown: the last `ahead` a read could
# tell, so a refused branch read (`ahead: null`) between two `true` is no new transition.
AHEAD_KNOWN = "_ahead_known"


def public_observed(observation: dict[str, Any] | None) -> dict[str, Any] | None:
    """A stored observation as §6.13 shows it: without the hub's own bookkeeping keys."""
    if observation is None:
        return None
    return {k: v for k, v in observation.items() if not k.startswith("_")}


def _ahead_known(observation: dict[str, Any] | None) -> Any:
    """The last `ahead` a read could tell (`true` or `false`), `None` when none could yet."""
    observation = observation or {}
    if observation.get("ahead") is not None:
        return observation.get("ahead")
    return observation.get(AHEAD_KNOWN)


def _shown(observation: dict[str, Any] | None, kind: str = "issue") -> dict[str, Any] | None:
    """What `link_observed` compares and carries: `{found, title, state}`, on a `commit` link
    `{found, sha, checks, required_check, branch_head_sha, ahead}` (§8.2)."""
    if observation is None:
        return None
    keys = COMMIT_SHOWN if kind == "commit" else ("found", "title", "state")
    return {k: observation.get(k) for k in keys}


def _wakes_holder(kind: str, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
    """Whether a change wakes the card's holder: its `state`, or a commit link's `ahead`
    turning `true` (§6.13); an `ahead` that stays `true` wakes nobody again, also across a
    refused branch read (`null`) in between: `old` is the stored observation, compared by
    its last known `ahead`."""
    if kind == "commit":
        return new.get("ahead") is True and _ahead_known(old) is not True
    return (old or {}).get("state") != new.get("state")


def due(conn: Connection, project_id: str) -> list[Any]:
    """The project's forge links to read now: on cards not closed, and on a closed card
    once more after it closed, then never; a commit link only while its card is not closed
    (§6.13)."""
    rows = conn.execute(
        select(t.card_link, t.card.c.closed_at, t.card.c.claim_holder)
        .join(t.card, t.card.c.id == t.card_link.c.card_id)
        .where(t.card.c.project_id == project_id, t.card_link.c.kind.in_(FORGE_KINDS))
        .order_by(t.card_link.c.id)
    ).all()
    found = []
    for row in rows:
        if row.closed_at is not None:
            if row.kind == "commit":
                continue
            seen = (row.observed or {}).get("observed_at")
            if seen is not None and seen >= clock.rfc3339(row.closed_at):
                continue
        found.append(row)
    return found


def observe(engine: Engine, fg: forge.Forge, project_id: str) -> int:
    """Read the project's due links of its own repository, batched, and store what the
    forge said; `link_observed` on a change. A read that fails keeps every observation
    as it was (`forge.ForgeUnavailableError` goes to the caller). Returns the reads."""
    from maity_hub.events import lock_project, transaction

    with engine.connect() as conn:
        project = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
        if project.repository_url is None or forge.kind_of(project.repository_url) != "github":
            return 0  # a forge link is read only on GitHub (§6.13, §11)
        own = forge.repository_of(project.repository_url).lower()
        wanted = [r for r in due(conn, project_id) if (r.repository or "").lower() == own]
    fg = fg.for_project(project_id)  # the source that covers this project (§11.4)
    commits = [r for r in wanted if r.kind == "commit"]
    wanted = [r for r in wanted if r.kind != "commit"]
    # A commit read that is refused (a spent budget) leaves the round's issue and pull
    # request links still read; the refusal goes to the caller after them.
    refused: forge.ForgeUnavailableError | None = None
    try:
        reads = _observe_commits(engine, fg, project, commits)
    except forge.ForgeUnavailableError as error:
        refused, reads = error, 0
    for start in range(0, len(wanted), BATCH):
        batch = wanted[start : start + BATCH]
        at = clock.rfc3339(clock.now())  # when the read started
        answer, public = fg.items(
            forge.repository_of(project.repository_url), sorted({r.number for r in batch})
        )
        reads += 1
        with transaction(engine) as conn:
            lock_project(conn, project_id)
            for row in batch:
                current = conn.execute(
                    select(t.card_link).where(t.card_link.c.id == row.id)
                ).first()
                if current is None:  # removed meanwhile
                    continue
                card = _card_now(conn, row.card_id)
                if card is None:
                    continue
                new = observed(row.kind, answer.get(row.number), at)
                # The one read after the card closed is stored and shown, and wakes nobody.
                holder = card.claim_holder if card.closed_at is None else None
                _store(conn, project_id, row, current, new, public, fg.via, holder)
    if refused is not None:
        raise refused
    return reads


def _card_now(conn: Connection, card_id: str) -> Any | None:
    """The card's closure and holder as they are now, read under the project lock: the
    forge read ran without it, and the card may have closed or changed hands meanwhile."""
    return conn.execute(
        select(t.card.c.closed_at, t.card.c.claim_holder).where(t.card.c.id == card_id)
    ).first()


def _store(
    conn: Connection,
    project_id: str,
    row: Any,
    current: Any,
    new: dict[str, Any],
    public: bool,
    via: str | None,
    holder: int | None,
) -> None:
    """Store one link's observation; `link_observed` when what it shows changed (§8.2),
    read by everyone and waking only `holder` (the card's current one, `None` on a closed
    card) when the change is one that wakes."""
    from maity_hub.events import emit

    conn.execute(update(t.card_link).where(t.card_link.c.id == row.id).values(observed=new))
    old_shown, new_shown = _shown(current.observed, row.kind), _shown(new, row.kind) or {}
    if old_shown == new_shown:
        return
    audience = ["all"]
    if _wakes_holder(row.kind, current.observed, new_shown) and holder:
        from maity_hub.views import principal_id

        audience.append(f"member:{principal_id(conn, holder)}")
    emit(
        conn,
        project_id,
        "link_observed",
        audience,
        {
            "task_id": row.card_id,
            "link_id": row.id,
            "forge_url": row.url,
            "old": old_shown,
            "new": new_shown,
            # Whether the read itself found the repository public, and which source read it:
            # a page without sign-in counts a merge the read found public, whichever source
            # read it (§11.4).
            "public": public,
            "read_via": via,
        },
        subject=("task", row.card_id),
    )


def _observe_commits(engine: Engine, fg: forge.Forge, project: Any, rows: list[Any]) -> int:
    """The project's due commit links (§6.13): one composite read per distinct sha, through
    the probe's cache, so two cards linking one commit and all commits sharing the default
    branch's head cost one read each. A read dropped as a whole (a spent budget, no answer)
    goes to the caller with every observation kept as it was. Returns the shas read."""
    from maity_hub import probe  # the probe reads this module for its links
    from maity_hub.events import lock_project, transaction

    by_sha: dict[str, list[Any]] = {}
    for row in rows:
        by_sha.setdefault(sha_of(row), []).append(row)
    for sha, linked in by_sha.items():
        read = probe.observe_commit(engine, fg, project, sha)
        with transaction(engine) as conn:
            lock_project(conn, project.id)
            for row in linked:
                current = conn.execute(
                    select(t.card_link).where(t.card_link.c.id == row.id)
                ).first()
                if current is None:  # removed meanwhile
                    continue
                card = _card_now(conn, row.card_id)
                if card is None or card.closed_at is not None:
                    continue  # closed meanwhile: commit links are read on open cards only
                new = read.link()
                if new.get("ahead") is None and _ahead_known(current.observed) is not None:
                    new[AHEAD_KNOWN] = _ahead_known(current.observed)
                if current.observed == new:  # the same cached read: nothing to store
                    continue
                # A commit link's events are not a merge the public page counts (§11.4).
                _store(conn, project.id, row, current, new, False, fg.via, card.claim_holder)
    return len(by_sha)
