"""A human's links to installations of the instance's GitHub App (docs/api.md §11.4).

A human links an installation to their account, not to a project. The link starts
with a `state` the hub hands to the forge: random, kept as its hash only, bound to the
session that started it, valid 15 minutes and used once. The forge sends the browser
back with the installation and an OAuth code. The hub reads the installation with the App's
key, exchanges the code for the user, and links it only when that user may link it: on a
user account, when its account is that user; on a forge organisation, when the forge reports
that user, read with the same user token, as an active owner of it. Listing the installations
a user can reach is not enough: a member of an organisation with access to one repository
would pass it.

A link on a forge organisation serves a read only on an owner check that succeeded less than
10 minutes before (`owner_ok_at`). The check runs at most every 10 minutes from the last one
(`checked_at`), whatever came of it; one process makes it, the one whose conditional update
of `checked_at` claimed it (`claim`). Its forge reads hold no database connection.
"""

from __future__ import annotations

import dataclasses
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import Connection, Engine, delete, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock, forge, github_app, wakeups, write_guard
from maity_hub import tables as t
from maity_hub.github_app import GitHubApp
from maity_hub.ids import new_id
from maity_hub.notifications import records

FORGE = "github"
STATE_TTL = timedelta(minutes=15)
REPOSITORIES_SHOWN = 100
ORGANISATION = "Organization"  # the forge's `account.type` of an organisation
CHECK_EVERY = timedelta(minutes=10)  # §11.4: the owner check's cadence and its freshness
# `suspended` and `removed` come from step 1 (or a refused mint), `not_admin` from a
# definite membership answer, `ok` from a check that succeeded; None is no answer.
OK, NOT_ADMIN = "ok", "not_admin"


class LinkError(Exception):
    """A link that fails its checks: `reason` is `link_state`, `installation_not_yours`,
    `not_organisation_admin`, `organisation_installation` or `installation_linked` (§11.4)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Link(NamedTuple):
    """A link as the source choice and the owner check read it."""

    id: str
    human_id: str
    installation_id: int
    status: str
    account_type: str
    account_id: int
    account_login: str
    forge_user_id: int | None
    checked_at: datetime
    owner_ok_at: datetime | None

    @classmethod
    def of(cls, row: Any) -> Link:
        return cls(*(getattr(row, name) for name in cls._fields))

    @property
    def organisation(self) -> bool:
        return self.account_type == ORGANISATION


class ReplaceCheck(Exception):  # noqa: N818  (a step of the flow, not a failure)
    """The installation is linked to another human on a forge organisation: that link's owner
    check runs at once, without a connection held, before the new link may replace it."""

    def __init__(self, existing: Link) -> None:
        super().__init__("the existing link is checked first")
        self.existing = existing


@dataclass(frozen=True)
class Check:
    """What an owner check found: `outcome` is `ok`, `not_admin`, `suspended`, `removed`, or
    None for no answer; `login` the account's current login from step 1, when it answered;
    `at` when the check started, which a success counts from, so it is never fresher than the
    reads it rests on."""

    outcome: str | None
    login: str | None = None
    at: datetime | None = None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def start(conn: Connection, app: GitHubApp, human_id: str, session_hash: str) -> str:
    """A new `state` for this human and session; the installation page's URL with it."""
    now = clock.now()
    conn.execute(
        delete(t.forge_link_state).where(
            t.forge_link_state.c.human_id == human_id, t.forge_link_state.c.expires_at <= now
        )
    )
    state = secrets.token_urlsafe(32)
    conn.execute(
        insert(t.forge_link_state).values(
            state_hash=_hash(state),
            human_id=human_id,
            session_hash=session_hash,
            expires_at=now + STATE_TTL,
        )
    )
    return app.install_url(state)


def take_state(conn: Connection, state: str, human_id: str, session_hash: str) -> None:
    """Use the `state` once: it must be this human's, from this session, not expired.
    `LinkError("link_state")` otherwise; a state of another human or session stays."""
    row = conn.execute(
        select(t.forge_link_state)
        .where(t.forge_link_state.c.state_hash == _hash(state))
        .with_for_update()
    ).first()
    if row is None or row.human_id != human_id or row.session_hash != session_hash:
        raise LinkError("link_state")
    conn.execute(
        delete(t.forge_link_state).where(t.forge_link_state.c.state_hash == row.state_hash)
    )
    if row.expires_at <= clock.now():
        raise LinkError("link_state")


def is_owner(membership: dict[str, Any] | None, account_id: Any, user_id: Any = None) -> bool:
    """Whether a membership the forge answered makes its user an active owner of the
    organisation with this id: `state: active`, `role: admin` (the forge's name for an owner),
    `organization.id` the account's id, and, where given, `user.id` the linking user's id. No
    membership (a `404`) is a definite "no" too. An id to compare with that is no number is no
    answer (`ForgeUnavailableError`): two missing ids must never match, nor make a "no"."""
    if not github_app.is_id(account_id) or not (user_id is None or github_app.is_id(user_id)):
        raise forge.ForgeUnavailableError("an owner check with no id to compare with")
    if membership is None:
        return False
    return (
        membership["state"] == "active"
        and membership["role"] == "admin"
        and membership["organization_id"] == account_id
        and (user_id is None or membership["user_id"] == user_id)
    )


def verify(app: GitHubApp, installation_id: int, code: str) -> dict[str, Any]:
    """The installation, read with the App's key, when the user the code belongs to may link
    it; `LinkError` otherwise, in the order of §11.4: the installation's existence, then the
    account check by kind. An installation on a forge organisation comes back with the
    linking user's id as `forge_user_id` and, as `owner_checked_at`, the time taken before the
    user's membership was read: the owner check at linking counts from it, never from when the
    link is written (a replacement's check of the other link runs in between). Makes forge
    reads: no connection is held."""
    found = app.installation(installation_id)
    if found is None:
        raise LinkError("installation_not_yours")
    account = found["account"]
    if account["type"] == "User":
        user = app.user_of_code(code)
        if account["id"] != user["id"]:
            raise LinkError("installation_not_yours")
        return found
    if account["type"] == ORGANISATION and isinstance(account.get("login"), str):
        # Any refusal of the membership read but a definite answer raises
        # `ForgeUnavailableError` from here: no answer, never a "no".
        started = clock.now()
        user = app.user_of_code(code, account["login"])
        if not is_owner(user["membership"], account["id"], user["id"]):
            raise LinkError("not_organisation_admin")
        return {**found, "forge_user_id": user["id"], "owner_checked_at": started}
    raise LinkError("organisation_installation")


def link(
    conn: Connection,
    human_id: str,
    found: dict[str, Any],
    replacing: tuple[Link, Check] | None = None,
    app: GitHubApp | None = None,
) -> str:
    """Store the verified installation as this human's link; the link's id. One human at a
    time: an installation linked to another human is `LinkError("installation_linked")`,
    except on a forge organisation, where another owner's link replaces it after an owner
    check of the existing link (§11.4): `ReplaceCheck` asks for that check, and the call comes
    again with `replacing`, the link as the check found it and what came of it. A link that
    changed meanwhile, or a concurrent first link of the same installation, is
    `ForgeUnavailableError` with nothing written: the human links again. `app` drops the
    installation's held tokens when a replacement removes the existing link."""
    now = clock.now()
    organisation = found["account"]["type"] == ORGANISATION
    # The owner check at linking is the link's first check and its first success, counted
    # from before `verify` read the membership (`owner_checked_at`), as `apply_check` counts
    # from the claim: never from now, which may be a replacement's whole check later.
    checked: datetime = found["owner_checked_at"] if organisation else now
    existing = _existing(conn, found["id"])
    if existing is not None:
        if existing.human_id != human_id:
            write_guard.share(conn, existing.human_id)  # the other human's record below
        # Locked whenever there is one, the caller's own included: a concurrent relink or
        # replacement of it waits for this one, then reads what it wrote (review A2545 #10).
        existing = _existing(conn, found["id"], lock=True)
    if replacing is not None and existing != replacing[0]:
        # The link the replacement's check was made for changed while it ran: its status, its
        # checks, its human, or it is gone (the lead's ruling Q2, seq 214797; review A2545 #1).
        # Decided before anything else, so neither an unlink, a removal nor a link of the
        # caller's own meanwhile lets the new link through on a check that did not decide it.
        raise forge.ForgeUnavailableError("the link changed while it was checked")
    columns: dict[str, Any] = {
        "account_id": found["account"]["id"],
        "account_login": found["account"]["login"] or "",
        "account_type": found["account"]["type"],
        "repository_selection": found.get("repository_selection") or "selected",
        "status": "suspended" if found.get("suspended") else "active",
        "checked_at": checked,
        "forge_user_id": found.get("forge_user_id") if organisation else None,
        "owner_ok_at": checked if organisation else None,
    }
    if existing is not None and existing.human_id != human_id:
        if not organisation:
            raise LinkError("installation_linked")
        login = existing.account_login
        if existing.status != "removed":
            _replace_after_check(conn, existing, replacing)
            assert replacing is not None  # `_replace_after_check` asked for the check otherwise
            login = replacing[1].login or login
        _drop(conn, existing, login)
        if app is not None:
            # The existing link's tokens go with it, here and on every replica (§11.4: a failed
            # check drops the installation's tokens; review A2545 #7).
            wakeups.forget_token_everywhere(conn, app, existing.installation_id)
        existing = None
    if existing is not None:
        updated = conn.execute(
            update(t.forge_link).where(t.forge_link.c.id == existing.id).values(columns)
        )
        if updated.rowcount != 1:  # held under its row lock: a link that went is no relink
            raise forge.ForgeUnavailableError("the link changed while it was written")
        records.forge_access_changed(conn, human_id, "app", "linked", columns["account_login"])
        return existing.id
    link_id = new_id("forge_link")
    try:
        conn.execute(
            insert(t.forge_link).values(
                id=link_id,
                human_id=human_id,
                forge=FORGE,
                installation_id=found["id"],
                linked_at=now,
                **columns,
            )
        )
    except IntegrityError:
        # Another first link of the installation committed since it was read: a link that
        # changed meanwhile, answered as one that changes during a replacement's check, never
        # as `installation_linked`, since it may be the caller's own (review A2545 #10).
        raise forge.ForgeUnavailableError("the installation was linked meanwhile") from None
    records.forge_access_changed(conn, human_id, "app", "linked", columns["account_login"])
    return link_id


class Kept(Exception):  # noqa: N818  (the outcome of a replacement's check, written first)
    """A replacement's check succeeded: the existing link stays, and the check is written as
    its last check and last success. The caller commits that, then refuses the new link with
    `installation_linked`."""


def _existing(conn: Connection, installation_id: int, lock: bool = False) -> Link | None:
    query = select(t.forge_link).where(
        t.forge_link.c.forge == FORGE, t.forge_link.c.installation_id == installation_id
    )
    row = conn.execute(query.with_for_update() if lock else query).first()
    return None if row is None else Link.of(row)


def _replace_after_check(
    conn: Connection, existing: Link, replacing: tuple[Link, Check] | None
) -> None:
    """Returns when the existing link is to be replaced: its check gave a definite answer that
    its human is no active owner, written here as on any failed check. `ReplaceCheck` while no
    check was made; `Kept` when it succeeded; `ForgeUnavailableError` when it gave no definite
    answer, or the link changed while it ran (the lead's ruling Q2, seq 214797: no retry):
    nothing is written then, the link's `checked_at` included."""
    if replacing is None:
        raise ReplaceCheck(existing)
    checked, check = replacing
    if checked != existing:
        raise forge.ForgeUnavailableError("the link changed while it was checked")
    if check.outcome == OK:
        at = check.at or clock.now()
        conn.execute(
            update(t.forge_link)
            .where(t.forge_link.c.id == existing.id)
            .values(**_login(check), status="active", checked_at=at, owner_ok_at=at)
        )
        raise Kept
    if check.outcome != NOT_ADMIN:
        # No answer; and step 1 finding the installation suspended (or gone, though the new
        # human's link just read it) is no definite answer for a replacement either.
        raise forge.ForgeUnavailableError("the existing link's owner check had no answer")
    if existing.status != NOT_ADMIN:
        records.forge_access_changed(
            conn, existing.human_id, "app", NOT_ADMIN, check.login or existing.account_login
        )


def _login(check: Check) -> dict[str, Any]:
    return {"account_login": check.login} if check.login else {}


def _drop(conn: Connection, existing: Link, login: str) -> None:
    """The existing link goes, and its human gets the `unlinked` record, naming the account by
    `login`: the current one when the replacement's check read it, as its `not_admin` record
    does."""
    conn.execute(delete(t.forge_link).where(t.forge_link.c.id == existing.id))
    records.forge_access_changed(conn, existing.human_id, "app", "unlinked", login)
    _forget_reads_of(conn, existing.human_id)


def _forget_reads_of(conn: Connection, human_id: str) -> None:
    """A link on a forge organisation that goes: the Keep the Why reads of every project whose
    grants may have been that human's, here and on every replica at commit
    (`wakeups.forget_repository_everywhere`). Without the link the source choice refuses with
    `no_grant`, which §11.3 does not ask about, so an export the link read must not stay in the
    cache to be answered (review A2545 #5). More projects than the link served may lose their
    reads: that costs one read each, nothing else."""
    p = t.project.c
    projects = conn.execute(
        select(p.id).where(or_(p.repository_confirmed_by == human_id, p.owner_id == human_id))
    ).scalars()
    for project_id in list(projects):
        wakeups.forget_repository_everywhere(conn, project_id)


def unlink(conn: Connection, app: GitHubApp | None, human_id: str, link_id: str) -> bool:
    """Remove the human's own link; False when there is none of theirs with that id."""
    row = conn.execute(
        select(t.forge_link).where(
            t.forge_link.c.id == link_id, t.forge_link.c.human_id == human_id
        )
    ).first()
    if row is None:
        return False
    conn.execute(delete(t.forge_link).where(t.forge_link.c.id == link_id))
    records.forge_access_changed(conn, human_id, "app", "unlinked", row.account_login)
    if row.account_type == ORGANISATION:
        _forget_reads_of(conn, human_id)
    if app is not None:
        wakeups.forget_token_everywhere(conn, app, row.installation_id)
    return True


def row(conn: Connection, link_id: str) -> Any:
    return conn.execute(select(t.forge_link).where(t.forge_link.c.id == link_id)).one()


def rows(conn: Connection, human_id: str) -> list[Any]:
    return list(
        conn.execute(
            select(t.forge_link)
            .where(t.forge_link.c.human_id == human_id)
            .order_by(t.forge_link.c.linked_at, t.forge_link.c.id)
        )
    )


# --- when a link serves, and its owner check ---------------------------------------------------


def serves(link: Any, now: datetime | None = None) -> bool:
    """Whether the link serves reads (§11.4): `active`, and on a forge organisation only while
    its last successful owner check is less than 10 minutes old."""
    if link.status != "active":
        return False
    if link.account_type != ORGANISATION:
        return True
    moment = now or clock.now()
    return link.owner_ok_at is not None and moment - link.owner_ok_at < CHECK_EVERY


def due(link: Any, now: datetime | None = None) -> bool:
    """Whether the link's owner check is due: a link on a forge organisation that is not
    `removed`, last checked 10 minutes ago or longer, whatever came of that check."""
    if link.account_type != ORGANISATION or link.status == "removed":
        return False
    return retry_due(link, now)


def retry_due(link: Any, now: datetime | None = None) -> bool:
    """Whether a `suspended` link on a user account may be minted for again: at most every 10
    minutes from its last check (§11.4)."""
    checked: datetime = link.checked_at
    return (now or clock.now()) - checked >= CHECK_EVERY


def claim(conn: Connection, link_id: str, now: datetime) -> bool:
    """Take the due check for this process: one conditional update of `checked_at`, which a
    second process, another engine or connection, finds no longer due. Committed before the
    check's forge reads, so the others see it."""
    c = t.forge_link.c
    claimed = conn.execute(
        update(t.forge_link)
        .where(
            c.id == link_id,
            c.account_type == ORGANISATION,
            c.status != "removed",
            c.checked_at <= now - CHECK_EVERY,
        )
        .values(checked_at=now)
    )
    return claimed.rowcount == 1


def owner_check(app: GitHubApp, link: Link, replacing: bool = False) -> Check:
    """The owner check of a link on a forge organisation (§11.4, "How it checks"), forge reads
    only, no connection held: the installation with the App's key; the forge user by the id
    kept with the link; that user's membership in the organisation, the last two with an
    installation token of this installation. The token is kept only for a link that serves
    already; for any other, and for a replacement's check (`replacing`), whose link may be
    gone right after it, it is minted for these reads alone (review A2545 #7)."""
    started = clock.now()
    return dataclasses.replace(_steps(app, link, keep=serves(link) and not replacing), at=started)


def _steps(app: GitHubApp, link: Link, keep: bool) -> Check:
    try:
        found = app.installation(link.installation_id)
    except forge.ForgeUnavailableError:
        return Check(None)
    if found is None:
        return Check("removed")
    account = found["account"]
    login = account.get("login") if isinstance(account.get("login"), str) else None
    if found.get("suspended"):
        return Check("suspended", login)
    if login is None or link.forge_user_id is None:
        return Check(None, login)
    if account.get("id") != link.account_id:
        # The installation's account is not the one linked: no answer about the human, so no
        # status changes on it (and no membership read for an account the link is not on).
        return Check(None, login)
    try:
        token = app.token(link.installation_id, keep=keep)
        username = app.user_login(token, link.forge_user_id)
        if username is None:
            return Check(NOT_ADMIN, login)  # the user by id is gone: a `404`, as at linking
        membership = app.org_membership(token, login, username)
        owner = is_owner(membership, link.account_id, link.forge_user_id)
    except github_app.InstallationGoneError as gone:
        return Check(gone.state, login)
    except forge.ForgeUnavailableError:
        return Check(None, login)
    return Check(OK if owner else NOT_ADMIN, login)


STALE = "stale"  # `apply_check`: a newer check or link was written while this one ran


def apply_check(conn: Connection, link_id: str, check: Check, at: datetime) -> str | None:
    """Write what a claimed check found (§11.4, "What comes of it"); the link's status after
    it, None when the link is gone or `removed`, `STALE` when its `checked_at` is no longer the
    claim's `at`: a replacement's check that kept it, or a relink of its own human, wrote a
    newer check meanwhile, and this older one writes nothing over it (review A2545 #8). Only
    a definite answer changes the status: a success sets `active` and `owner_ok_at` to `at`
    (when the check was claimed, so it is never fresher than it was), a definite "no"
    `not_admin` with its record when the status becomes it, step 1's suspension or removal as
    a refused mint does. No answer changes nothing but the login step 1 read. The human's
    account lock first, as in `set_status`."""
    owner = conn.execute(
        select(t.forge_link.c.human_id).where(t.forge_link.c.id == link_id)
    ).scalar()
    if owner is None:
        return None
    write_guard.share(conn, owner)
    found = conn.execute(
        select(t.forge_link).where(t.forge_link.c.id == link_id).with_for_update()
    ).first()
    if found is None or found.status == "removed":
        return None
    if found.checked_at != at:
        return STALE
    values: dict[str, Any] = _login(check)
    status: str = found.status
    if check.outcome == OK:
        status = "active"
        values.update(status=status, owner_ok_at=at)
    elif check.outcome is not None:
        status = check.outcome
        values["status"] = status
        if status != found.status:
            login = check.login or found.account_login
            records.forge_access_changed(conn, found.human_id, "app", status, login)
    if values:
        conn.execute(update(t.forge_link).where(t.forge_link.c.id == link_id).values(values))
    return status


def refresh(engine: Engine, app: GitHubApp, link: Any) -> Any | None:
    """The link's row as it stands after its owner check, when one is due and this process
    claimed it; as stored otherwise (`due` false, or another process claimed the check); None
    when it is gone. A definite answer that does not end in `active` drops the installation's
    tokens this process and the others hold; a check a newer one overtook (`STALE`) drops
    nothing.

    Both transactions are exempt from the calling request's write guard (review A2545 #2): what
    they write is the link's human's, never the caller's, so a caller deleted, suspended or
    whose bridge ended meanwhile must not drop a definite `not_admin` after the claim moved
    `checked_at`. It also keeps §2.9's lock order: `apply_check` takes the link human's
    `account_lock` (shared) first, then the link's row, as `account_deletion` takes the
    `account_lock` (exclusively) before anything else; the guard's own check of a bridged call
    would otherwise take the organisation's and the project's locks before that
    `account_lock`, the order a deletion takes them the other way round."""
    if not due(link):
        return link
    at = clock.now()
    with engine.begin() as conn:
        write_guard.exempt(conn)
        claimed = claim(conn, link.id, at)
        if not claimed:
            return conn.execute(select(t.forge_link).where(t.forge_link.c.id == link.id)).first()
    check = owner_check(app, Link.of(link))
    with engine.begin() as conn:
        write_guard.exempt(conn)
        status = apply_check(conn, link.id, check, at)
        if check.outcome is not None and status not in ("active", STALE):
            wakeups.forget_token_everywhere(conn, app, link.installation_id)
        return conn.execute(select(t.forge_link).where(t.forge_link.c.id == link.id)).first()


def shown(app: GitHubApp | None, row: Any) -> tuple[list[str], str | None]:
    """The repositories the installation covers, read with its token when the list is
    asked for, and the status this read found, if any: `suspended` or `removed` from a refused
    mint, `active` from one that succeeded on a link on a user account that was not. A link on
    a forge organisation lists only while it serves, and a mint alone never sets it `active`;
    a `suspended` link on a user account is minted for at most every 10 minutes (§11.4).
    Makes forge reads: no connection is held."""
    if app is None or row.status == "removed":
        return [], None
    organisation = row.account_type == ORGANISATION
    if organisation and not serves(row):
        return [], None
    if row.status == "suspended" and not retry_due(row):
        return [], None
    if row.status != "active":  # only a new mint says it is back, not a token held from before
        github_app.forget_token(app.app_id, row.installation_id)
    try:
        repositories = app.repositories(row.installation_id, REPOSITORIES_SHOWN)
        return repositories, ("active" if row.status != "active" else None)
    except github_app.InstallationGoneError as gone:
        return [], gone.state
    except forge.ForgeUnavailableError:
        return [], None


def set_status(conn: Connection, link_id: str, status: str) -> None:
    """The status a mint found; a link that becomes `suspended` or `removed` writes the
    human's account record (§11.4). The human's account lock comes first, shared, before the
    link's row: the record locks the human's row, and a deletion of the account takes the lock
    exclusively before anything else, so the two run one after the other
    (`write_guard.share`). A mint alone never sets a link on a forge organisation `active`:
    only its owner check does (`apply_check`)."""
    owner = conn.execute(
        select(t.forge_link.c.human_id).where(t.forge_link.c.id == link_id)
    ).scalar()
    if owner is None:
        return
    write_guard.share(conn, owner)
    row = conn.execute(
        select(t.forge_link).where(t.forge_link.c.id == link_id).with_for_update()
    ).first()
    if row is None or row.status == "removed":
        return  # final: a listing that minted before the removal does not undo it
    if status == "active" and row.account_type == ORGANISATION:
        return
    if row.account_type == ORGANISATION:
        # the owner check's cadence stays its own: a refused mint is no owner check
        conn.execute(update(t.forge_link).where(t.forge_link.c.id == link_id).values(status=status))
    else:
        conn.execute(
            update(t.forge_link)
            .where(t.forge_link.c.id == link_id)
            .values(status=status, checked_at=clock.now())
        )
    if status != row.status and status in ("suspended", "removed"):
        records.forge_access_changed(conn, row.human_id, "app", status, row.account_login)


def view(row: Any, repositories: list[str], status: str) -> dict[str, Any]:
    return {
        "id": row.id,
        "forge": row.forge,
        "installation_id": row.installation_id,
        "account": {"login": row.account_login, "type": row.account_type},
        "repository_selection": row.repository_selection,
        "repositories_shown": repositories,
        "status": status,
        "linked_at": clock.rfc3339(row.linked_at),
        "checked_at": clock.rfc3339(row.checked_at),
    }
