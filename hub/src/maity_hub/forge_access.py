"""Which source reads a project's repository (docs/api.md §11.4).

The first that covers it, decided per project:

1. the namespace owner's installation of the instance's GitHub App: the forge names an
   installation for the repository, and it is one of the owner's links;
2. the namespace owner's own token: a read of the repository with it answers;
3. the operator's token, only for a project in one of the operator's own namespaces
   (`MAITY_FORGE_INSTANCE_NAMESPACES`) and only for a repository the forge reports public.

Only the namespace owner's grants count, and only while the owner has confirmed the URL
the project carries (`repository_owner_confirmed`): no co-admin can point a project at
another of the owner's private repositories and have it read with the owner's access.

The choice is kept per project for at most 10 minutes, keyed by everything it depends
on (the URL, the owner, the confirmation, the owner's links and token). A change of any
of them chooses again at once, and so does a refused read. Forge reads happen without
a database connection held.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, select, update

from maity_hub import (
    bounded,
    clock,
    errors,
    forge,
    forge_links,
    github_app,
    namespace,
    secretbox,
    wakeups,
    write_guard,
)
from maity_hub import tables as t
from maity_hub.github_app import GitHubApp
from maity_hub.notifications import records

log = logging.getLogger(__name__)

KEEP_SECONDS = forge.PUBLIC_SECONDS


@dataclass(frozen=True)
class _Facts:
    """What the choice depends on, read in one short transaction."""

    repository_url: str | None
    owner_id: str  # the human whose grants count: who confirmed (§11.4), "" while nobody did
    confirmed: bool
    links: tuple[forge_links.Link, ...]  # with their status and owner checks
    token: tuple[str, Any, bytes] | None  # (status, set_at, sealed)
    namespace: str  # the project's namespace by its current handle, in lower case

    def key(self, base: forge.Forge) -> tuple[Any, ...]:
        digest = hashlib.sha256((base.token or "").encode()).hexdigest()
        token = None if self.token is None else self.token[:2]
        return (
            self.repository_url,
            self.owner_id,
            self.confirmed,
            self.links,
            token,
            digest,
            self.namespace,
        )


class ForgeAccess:
    """The grants the hub knows, for `Forge.for_project`."""

    def __init__(
        self,
        engine: Engine,
        app: GitHubApp | None,
        secret_key: bytes | None,
        instance_namespaces: frozenset[str] = frozenset(),
    ) -> None:
        self.engine = engine
        self.app = app
        self.secret_key = secret_key
        self.instance_namespaces = instance_namespaces
        self._lock = threading.Lock()
        # project id -> (when chosen, what it depended on, the reader, kept until): a choice
        # that rests on a link on a forge organisation is kept no longer than that link's
        # owner check (§11.4): until 10 minutes after its last success while it serves, until
        # its next check is due while it does not.
        self._chosen: OrderedDict[
            str, tuple[float, tuple[Any, ...], forge.Forge, datetime | None]
        ] = OrderedDict()

    def reader(self, project_id: str, base: forge.Forge) -> forge.Forge:
        facts = self._facts(project_id)
        key = facts.key(base)
        with self._lock:
            kept = self._chosen.get(project_id)
        if (
            kept is not None
            and kept[1] == key
            and time.monotonic() - kept[0] < KEEP_SECONDS
            and (kept[3] is None or clock.now() < kept[3])
        ):
            return kept[2]
        try:
            chosen, until = self._choose(project_id, facts, base)
        except forge.ForgeUnavailableError:
            # The forge did not answer the choice: a reader without a token, whose reads
            # fail as unavailable (or read a public repository anonymously); kept for
            # nothing, so the next read chooses again. Where the grants hold a link on a forge
            # organisation it carries that link's "no answer", so that §11.3 does not answer an
            # export such a link may have read from its cache meanwhile (review A2545 #5).
            organisation = any(link.organisation for link in facts.links)
            unanswered = errors.ORG_UNANSWERED if organisation else None
            return forge.Forge(None, project_id=project_id, owner_reason=unanswered)
        with self._lock:
            entry = (time.monotonic(), key, chosen, until)
            bounded.put(self._chosen, project_id, entry, CHOSEN_KEPT)
        self._note_via(project_id, chosen.via)
        return chosen

    def _note_via(self, project_id: str, via: str | None) -> None:
        """What the choice found, here and for the other replicas (83da2bfa). The row of a project
        may be locked by the very request that reads: then it is skipped, not waited for, and the
        next choice writes it. A value shown is not worth a request."""
        _note_via(project_id, via)
        if self.engine is None or self.engine.dialect.name != "postgresql":
            return
        p, stored = t.project.c, via or NO_SOURCE
        try:
            with self.engine.begin() as conn:
                write_guard.exempt(conn)
                free = (
                    select(p.id)
                    .where(p.id == project_id, p.probe_via.is_distinct_from(stored))
                    .with_for_update(skip_locked=True)
                )
                conn.execute(update(t.project).where(p.id.in_(free)).values(probe_via=stored))
        except Exception:
            log.warning("the probe's source could not be stored", exc_info=True)

    def not_covered(self, project_id: str) -> None:
        """The operator's token found the repository not public: nothing reads it now."""
        self._note_via(project_id, None)

    def refused(self, reader: forge.Forge, error: forge.ForgeUnavailableError | None) -> None:
        """A read with an owner's grant was refused: choose again on the next read."""
        if reader.project_id is None:
            return
        with self._lock:
            self._chosen.pop(reader.project_id, None)
        refused_token = error is not None and error.status == 401
        if reader.granted == "owner_token" and refused_token and reader.grant is not None:
            self._token_rejected_owner(*reader.grant)

    # --- the choice ----------------------------------------------------------------------

    def _facts(self, project_id: str) -> _Facts:
        with self.engine.connect() as conn:
            project = conn.execute(
                select(
                    t.project.c.repository_url,
                    t.project.c.owner_id,
                    t.project.c.owner_org_id,
                    t.project.c.repository_owner_confirmed,
                    t.project.c.repository_confirmed_by,
                ).where(t.project.c.id == project_id)
            ).one()
            handle = namespace.current_handle(conn, project.owner_id) or ""
            # The namespace owner's grants for a project of a human; for one of an organisation
            # the grants of the owner who confirmed it, and nobody's while none did.
            grants = project.repository_confirmed_by or (
                project.owner_id if project.owner_org_id is None else ""
            )
            links = tuple(forge_links.Link.of(row) for row in forge_links.rows(conn, grants))
            token = conn.execute(
                select(t.forge_token).where(t.forge_token.c.human_id == grants)
            ).first()
        return _Facts(
            project.repository_url,
            grants,
            bool(project.repository_owner_confirmed),
            links,
            None if token is None else (token.status, token.set_at, token.token_sealed),
            handle.lower(),
        )

    def _choose(
        self, project_id: str, facts: _Facts, base: forge.Forge
    ) -> tuple[forge.Forge, datetime | None]:
        """The reader, and until when it may be kept at most (None: KEEP_SECONDS only)."""
        if facts.repository_url is None:
            return base, None
        # Off GitHub the hub stores the URL and sends no token (§6.1, §11).
        if forge.kind_of(facts.repository_url) != "github":
            return self._refusing(base, project_id, "forge_not_github"), None
        repository = forge.repository_of(facts.repository_url).lower()
        owner_reason: str | None = None
        until: datetime | None = None
        has_grant = any(link.status != "removed" for link in facts.links) or (
            facts.token is not None and facts.token[0] == "active"
        )
        if facts.confirmed:
            via_app, owner_reason, until = self._by_app(facts, repository)
            if via_app is not None:
                bound = self._bound(base, project_id, repository, "app", via_app)
                # only a link on a forge organisation keeps its grant for a time (`_by_org_link`)
                return dataclasses.replace(bound, serves_until=until), until
            # A link that serves nothing is not the project's source: the choice goes on with
            # the owner's token, then the operator's where it may serve (§11.4).
            via_token, token_reason = self._by_token(facts, repository)
            if via_token is not None:
                grant = (facts.owner_id, _digest(facts.token[2])) if facts.token else None
                bound = self._bound(base, project_id, repository, "owner_token", via_token, grant)
                return bound, until
            owner_reason = owner_reason or token_reason
        elif has_grant:
            owner_reason = "unconfirmed"
        if base.token is None or facts.namespace not in self.instance_namespaces:
            # The operator's token serves the operator's own namespaces only (§11.4): any
            # other project is read through its owner's grant or not at all.
            return self._refusing(base, project_id, owner_reason or "no_grant"), until
        # The operator's token, which checks on every read that the repository is public;
        # when it is not, the owner's reason says more than "private".
        instance = forge.Forge(
            base.token, project_id=project_id, access=self, owner_reason=owner_reason
        )
        return instance, until

    def _by_app(
        self, facts: _Facts, repository: str
    ) -> tuple[str | None, str | None, datetime | None]:
        """An installation token when the owner's linked installation covers the
        repository; else None and the reason it no longer does, if it once did; and until
        when the answer may be kept, for a link whose state changes with time."""
        if self.app is None or not facts.links:
            return None, None, None
        installation_id = self.app.installation_of(repository)
        mine = [link for link in facts.links if link.installation_id == installation_id]
        if installation_id is None or not mine:
            return None, None, None  # any other installation of the App is never tried
        link = mine[0]
        if link.organisation:
            return self._by_org_link(link)
        if link.status == "removed":
            return None, "installation_removed", None
        if link.status == "suspended" and not forge_links.retry_due(link):
            # retried at most every 10 minutes (§11.4)
            return None, "installation_suspended", link.checked_at + forge_links.CHECK_EVERY
        if link.status != "active":  # only a new mint says it is back, not a token held before
            github_app.forget_token(self.app.app_id, installation_id)
        try:
            token = self.app.token(installation_id)
        except github_app.InstallationGoneError as gone:
            self._gone(link, gone.state)
            return None, f"installation_{gone.state}", None
        if link.status != "active":
            with self.engine.begin() as conn:
                forge_links.set_status(conn, link.id, "active")
        return token, None, None

    def _by_org_link(
        self, link: forge_links.Link
    ) -> tuple[str | None, str | None, datetime | None]:
        """A link on a forge organisation (§11.4): checked first when its owner check is due,
        then a token only while it serves, kept until 10 minutes after its last success; else
        the reason, kept for the project's readers apart from a user account's (`errors.ORG_*`),
        until its next check is due."""
        assert self.app is not None
        row = forge_links.refresh(self.engine, self.app, link)
        if row is None:
            return None, errors.ORG_REMOVED, None
        link = forge_links.Link.of(row)
        if forge_links.serves(link):
            try:
                token = self.app.token(link.installation_id)
            except github_app.InstallationGoneError as gone:
                self._gone(link, gone.state)
                return None, errors.ORG_REASONS_BY_STATUS[gone.state], None
            assert link.owner_ok_at is not None  # `serves` says so
            return token, None, link.owner_ok_at + forge_links.CHECK_EVERY
        reason = errors.ORG_REASONS_BY_STATUS.get(link.status, errors.ORG_UNANSWERED)
        if link.status == "removed":
            return None, reason, None  # never checked again: nothing to keep it until (A2545 #9)
        return None, reason, link.checked_at + forge_links.CHECK_EVERY

    def _gone(self, link: forge_links.Link, state: str) -> None:
        """A mint the forge refused: the link's status, and no token of it held anywhere. Exempt
        from the calling request's write guard, as `forge_links.refresh` is (review A2545 #2):
        the write is the link human's, whose `account_lock` `set_status` takes first."""
        assert self.app is not None
        with self.engine.begin() as conn:
            write_guard.exempt(conn)
            forge_links.set_status(conn, link.id, state)
            wakeups.forget_token_everywhere(conn, self.app, link.installation_id)

    def _by_token(self, facts: _Facts, repository: str) -> tuple[str | None, str | None]:
        """The owner's token when a read of the repository with it answers."""
        if facts.token is None or self.secret_key is None:
            return None, None
        status, _, sealed = facts.token
        if status != "active":
            return None, "token_rejected"
        try:
            token = secretbox.open_sealed(
                self.secret_key, f"forge_token:{facts.owner_id}", sealed
            ).decode()
        except secretbox.SealedError:
            return None, None
        probe = forge.Forge(token, granted="owner_token", repository=repository)
        try:
            found = probe._send(f"/repos/{repository}")
        except forge.ForgeUnavailableError as error:
            if error.status == 401:
                self._token_rejected_owner(facts.owner_id, _digest(sealed))
                return None, "token_rejected"
            if isinstance(error, forge.NotCoveredError) or (
                error.status == 403 and not error.rate_limited
            ):
                return None, None
            raise
        return (token, None) if found is not None else (None, None)

    def _bound(
        self,
        base: forge.Forge,
        project_id: str,
        repository: str,
        granted: str,
        token: str,
        grant: tuple[str, str] | None = None,
    ) -> forge.Forge:
        return forge.Forge(
            token,
            granted=granted,
            repository=repository,
            project_id=project_id,
            grant=grant,
            access=self,
        )

    def _refusing(self, base: forge.Forge, project_id: str, reason: str) -> forge.Forge:
        return forge.Forge(None, refused=reason, project_id=project_id, access=self)

    # --- a token the forge refused ---------------------------------------------------------

    def _token_rejected_owner(self, owner_id: str, sealed_digest: str) -> None:
        """The forge refused this owner's token: `rejected` until it is replaced, and the
        owner's account record once (§11.4). Only the very token that was refused: one
        replaced since, or the token of whoever owns the project now, stays as it is."""
        with self.engine.begin() as conn:
            # The owner's account lock first, shared, before the token's row: the record locks
            # the owner's row, and a deletion of the account takes the lock exclusively before
            # anything else, so the two run one after the other (`write_guard.share`).
            write_guard.share(conn, owner_id)
            row = conn.execute(
                select(t.forge_token).where(t.forge_token.c.human_id == owner_id).with_for_update()
            ).first()
            if row is None or row.status == "rejected":
                return
            if _digest(row.token_sealed) != sealed_digest:
                return  # replaced while the refused read was under way
            conn.execute(
                update(t.forge_token)
                .where(t.forge_token.c.human_id == owner_id)
                .values(status="rejected", checked_at=clock.now())
            )
            records.forge_access_changed(conn, owner_id, "owner_token", "token_rejected", row.login)


def _digest(sealed: bytes) -> str:
    """Names one stored token without holding it: a replacement is sealed anew."""
    return hashlib.sha256(sealed).hexdigest()


# `project.probe_via` when the last choice found no source; NULL there: no choice yet
NO_SOURCE = "none"
# project id -> the source the last choice found (§6.1 `probe_via`). The one process there is on
# SQLite and MariaDB reads it here, as replicas read `project.probe_via`; on PostgreSQL this
# stands in until that is written.
_last_via: OrderedDict[str, str | None] = OrderedDict()
_via_lock = threading.Lock()
# Projects whose source is known. One dropped shows the default below until its next
# read chooses again, which the probe does within its interval.
VIA_KEPT = 4096
CHOSEN_KEPT = 1024  # the readers kept per project; an older one is chosen anew


def _note_via(project_id: str, via: str | None) -> None:
    with _via_lock:
        bounded.put(_last_via, project_id, via, VIA_KEPT)


def is_confirmer(caller: Any, project: Any) -> bool:
    """Whether the caller is the human named in the project's `confirmed_by` (§11.4), who gets
    the specific reason of a link on a forge organisation that serves nothing: that human
    themselves, never one of their agents, a bridge or a proxy acting for them."""
    return (
        getattr(caller, "kind", None) == "human"
        and bool(project.repository_owner_confirmed)
        and project.repository_confirmed_by is not None
        and getattr(caller, "principal_id", None) == project.repository_confirmed_by
    )


def instance_serves(conn: Connection, fg: forge.Forge, owner_id: str) -> bool:
    """Whether `fg`'s operator token reads for a project of this namespace owner (§11.4). A
    reader that knows no grants (tests) reads for every project, as `for_project` does."""
    if fg.token is None:
        return False
    if fg.access is None:
        return True
    return serves(fg.access.instance_namespaces, namespace.current_handle(conn, owner_id))


def serves(namespaces: frozenset[str], handle: str | None) -> bool:
    """Whether the operator's token reads for a project of the namespace with this current
    handle: one of the operator's own (`MAITY_FORGE_INSTANCE_NAMESPACES`, §11.4)."""
    return handle is not None and handle.lower() in namespaces


def probe_via(project_id: str, url: str | None, stored: str | None, instance: bool) -> str | None:
    """`repository.probe_via` (§6.1): the source the project's last choice found; before
    any, the operator's token when it serves the project (`instance`: the hub holds one and
    the project is in one of the operator's own namespaces). `stored` is the project's
    `probe_via`, so this asks neither the forge nor the database, and a view can show it."""
    if forge.kind_of(url) != "github":
        return None
    if stored is not None:
        return None if stored == NO_SOURCE else stored
    return _last_via.get(project_id, "instance" if instance else None)
