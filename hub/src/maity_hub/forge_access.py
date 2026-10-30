"""Which source reads a project's repository (docs/api.md §11.4).

The first that covers it, decided per project:

1. the namespace owner's installation of the instance's GitHub App: the forge names an
   installation for the repository, and it is one of the owner's links;
2. the namespace owner's own token: a read of the repository with it answers;
3. the operator's token, only for a repository the forge reports public.

Only the namespace owner's grants count, and only while the owner has confirmed the URL
the project carries (`repository_owner_confirmed`): no co-admin can point a project at
another of the owner's private repositories and have it read with the owner's access.

The choice is kept per project for at most 10 minutes, keyed by everything it depends
on (the URL, the owner, the confirmation, the owner's links and token). A change of any
of them chooses again at once, and so does a refused read. Forge reads happen without
a database connection held.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, select, update

from maity_hub import bounded, clock, forge, forge_links, github_app, secretbox
from maity_hub import tables as t
from maity_hub.github_app import GitHubApp
from maity_hub.notifications import records

KEEP_SECONDS = forge.PUBLIC_SECONDS


@dataclass(frozen=True)
class _Facts:
    """What the choice depends on, read in one short transaction."""

    repository_url: str | None
    owner_id: str
    confirmed: bool
    links: tuple[tuple[str, int, str], ...]  # (id, installation id, status)
    token: tuple[str, Any, bytes] | None  # (status, set_at, sealed)

    def key(self, base: forge.Forge) -> tuple[Any, ...]:
        digest = hashlib.sha256((base.token or "").encode()).hexdigest()
        token = None if self.token is None else self.token[:2]
        return (self.repository_url, self.owner_id, self.confirmed, self.links, token, digest)


class ForgeAccess:
    """The grants the hub knows, for `Forge.for_project`."""

    def __init__(self, engine: Engine, app: GitHubApp | None, secret_key: bytes | None) -> None:
        self.engine = engine
        self.app = app
        self.secret_key = secret_key
        self._lock = threading.Lock()
        # project id -> (when chosen, what it depended on, the reader)
        self._chosen: OrderedDict[str, tuple[float, tuple[Any, ...], forge.Forge]] = OrderedDict()

    def reader(self, project_id: str, base: forge.Forge) -> forge.Forge:
        facts = self._facts(project_id)
        key = facts.key(base)
        with self._lock:
            kept = self._chosen.get(project_id)
        if kept is not None and kept[1] == key and time.monotonic() - kept[0] < KEEP_SECONDS:
            return kept[2]
        try:
            chosen = self._choose(project_id, facts, base)
        except forge.ForgeUnavailableError:
            # The forge did not answer the choice: a reader without a token, whose reads
            # fail as unavailable (or read a public repository anonymously); kept for
            # nothing, so the next read chooses again.
            return forge.Forge(None, project_id=project_id)
        with self._lock:
            bounded.put(self._chosen, project_id, (time.monotonic(), key, chosen), CHOSEN_KEPT)
        _note_via(project_id, chosen.via)
        return chosen

    def not_covered(self, project_id: str) -> None:
        """The operator's token found the repository not public: nothing reads it now."""
        _note_via(project_id, None)

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
                    t.project.c.repository_owner_confirmed,
                ).where(t.project.c.id == project_id)
            ).one()
            links = tuple(
                (row.id, row.installation_id, row.status)
                for row in forge_links.rows(conn, project.owner_id)
            )
            token = conn.execute(
                select(t.forge_token).where(t.forge_token.c.human_id == project.owner_id)
            ).first()
        return _Facts(
            project.repository_url,
            project.owner_id,
            bool(project.repository_owner_confirmed),
            links,
            None if token is None else (token.status, token.set_at, token.token_sealed),
        )

    def _choose(self, project_id: str, facts: _Facts, base: forge.Forge) -> forge.Forge:
        if forge.kind_of(facts.repository_url) != "github" or facts.repository_url is None:
            return base
        repository = forge.repository_of(facts.repository_url).lower()
        owner_reason: str | None = None
        has_grant = any(status != "removed" for _, _, status in facts.links) or (
            facts.token is not None and facts.token[0] == "active"
        )
        if facts.confirmed:
            via_app, owner_reason = self._by_app(facts, repository)
            if via_app is not None:
                return self._bound(base, project_id, repository, "app", via_app)
            via_token, token_reason = self._by_token(facts, repository)
            if via_token is not None:
                grant = (facts.owner_id, _digest(facts.token[2])) if facts.token else None
                return self._bound(base, project_id, repository, "owner_token", via_token, grant)
            owner_reason = owner_reason or token_reason
        elif has_grant:
            owner_reason = "unconfirmed"
        if base.token is None:
            return self._refusing(base, project_id, owner_reason or "no_grant")
        # The operator's token, which checks on every read that the repository is public;
        # when it is not, the owner's reason says more than "private".
        return forge.Forge(
            base.token, project_id=project_id, access=self, owner_reason=owner_reason
        )

    def _by_app(self, facts: _Facts, repository: str) -> tuple[str | None, str | None]:
        """An installation token when the owner's linked installation covers the
        repository; else None and the reason it no longer does, if it once did."""
        if self.app is None or not facts.links:
            return None, None
        installation_id = self.app.installation_of(repository)
        mine = [link for link in facts.links if link[1] == installation_id]
        if installation_id is None or not mine:
            return None, None  # any other installation of the App is never tried
        link_id, _, status = mine[0]
        if status == "removed":
            return None, "installation_removed"
        try:
            token = self.app.token(installation_id)
        except github_app.InstallationGoneError as gone:
            with self.engine.begin() as conn:
                forge_links.set_status(conn, link_id, gone.state)
            return None, f"installation_{gone.state}"
        if status != "active":
            with self.engine.begin() as conn:
                forge_links.set_status(conn, link_id, "active")
        return token, None

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


# project id -> the source the last choice found (§6.1 `probe_via`); a view reads it
# without asking the forge
_last_via: OrderedDict[str, str | None] = OrderedDict()
_via_lock = threading.Lock()
# Projects whose source is known. One dropped shows the default below until its next
# read chooses again, which the probe does within its interval.
VIA_KEPT = 4096
CHOSEN_KEPT = 1024  # the readers kept per project; an older one is chosen anew


def _note_via(project_id: str, via: str | None) -> None:
    with _via_lock:
        bounded.put(_last_via, project_id, via, VIA_KEPT)


def probe_via(project_id: str, url: str | None, instance_token: str | None) -> str | None:
    """`repository.probe_via` (§6.1): the source the project's last choice found; before
    any, the operator's token when the hub holds one. Asks neither the forge nor the
    database, so a view can show it."""
    if forge.kind_of(url) != "github":
        return None
    return _last_via.get(project_id, "instance" if instance_token is not None else None)
