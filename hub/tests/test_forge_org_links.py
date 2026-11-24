"""docs/api.md §11.4: an installation of the GitHub App on a forge organisation.

Linked by one of its owners, as that owner's grant; re-checked by polling at most every 10
minutes; serving a read only on an owner check that succeeded less than 10 minutes before;
replaced by another owner's link only after the existing link's own check. The App's reads are
faked at `GitHubApp` (`installation`, `user_of_code`, `token`, `user_login`, `org_membership`,
`installation_of`, `repositories`) and the forge's repository reads at `Forge._send`; the
GitHub API itself is never called. The reads against the forge's own answers are tested with a
fake opener at the end.
"""

from __future__ import annotations

import base64
import contextvars
import io
import json
import threading
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import (
    clock,
    errors,
    forge,
    forge_access,
    forge_links,
    github_app,
    ktw,
    probe,
    secretbox,
    wakeups,
    write_guard,
)
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.db import make_engine
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_forge_links import DONE, start
from tests.test_forge_links import setup as link_setup

URL = "https://github.com/acme/private-thing"
REPO = "acme/private-thing"
OPERATOR = "operator-token"
OWNER_TOKEN = "github_pat_owner_secret"
KEY = secretbox.parse_key(base64.b64encode(b"k" * 32).decode())
APP = github_app.GitHubApp("1", "maity-test", "unused", "client", "secret")
ORG_ID = 900
INSTALLATION = 7
TEN = timedelta(minutes=10)
# who each OAuth code belongs to: (forge user id, login)
USERS = {"c0de": (42, "maintainer-gh"), "anna": (43, "anna-gh")}


def owner_of(user_id: int, org_id: int = ORG_ID, **changed: Any) -> dict[str, Any]:
    """A membership as `github_app.membership_of` gives it: an active owner unless changed."""
    return {
        "state": "active",
        "role": "admin",
        "organization_id": org_id,
        "user_id": user_id,
        **changed,
    }


class FakeApp:
    """The App's reads, as the forge would answer them for one installation on `acme`."""

    def __init__(self) -> None:
        self.login = "acme"
        self.account_id = ORG_ID
        self.installation_state: Any = "active"  # "suspended", None (removed), or an exception
        # the user's own membership at linking, by forge user id (None: a 404)
        self.own: dict[int, Any] = {42: owner_of(42), 43: owner_of(43)}
        # the owner check: a user's current login by id, and memberships by (org, login)
        self.logins: dict[int, Any] = {42: "maintainer-gh", 43: "anna-gh"}
        self.memberships: dict[tuple[str, str], Any] = {
            ("acme", "maintainer-gh"): owner_of(42),
            ("acme", "anna-gh"): owner_of(43),
        }
        self.mint: Any = None  # a gone state, or an exception
        self.calls: list[str] = []
        self.kept: list[bool] = []  # `keep` of each mint
        self.during_check: Any = None  # called once while the owner check reads the membership
        self.during_own: Any = None  # called once while linking reads the user's own membership
        self.lookup: Any = None  # an exception the choice's installation lookup raises

    def installation(self, installation_id: int) -> dict[str, Any] | None:
        self.calls.append("installation")
        state = self.installation_state
        if isinstance(state, BaseException):
            raise state
        if state is None:
            return None
        return {
            "id": installation_id,
            "account": {"id": self.account_id, "login": self.login, "type": "Organization"},
            "repository_selection": "all",
            "suspended": state == "suspended",
        }

    def user_of_code(self, code: str, organisation: str | None = None) -> dict[str, Any]:
        self.calls.append("user_of_code")
        user_id, login = USERS[code]
        found: dict[str, Any] = {"id": user_id, "login": login}
        if organisation is not None:
            self.calls.append(f"own_membership:{organisation}")
            if self.during_own is not None:
                hook, self.during_own = self.during_own, None
                hook()
            answer = self.own.get(user_id)
            if isinstance(answer, BaseException):
                raise answer
            found["membership"] = answer
        return found

    def token(self, installation_id: int, keep: bool = True) -> str:
        self.calls.append("token")
        self.kept.append(keep)
        if isinstance(self.mint, BaseException):
            raise self.mint
        if self.mint is not None:
            raise github_app.InstallationGoneError(self.mint)
        return f"ghs_installation_{installation_id}"

    def user_login(self, token: str, user_id: int) -> str | None:
        self.calls.append(f"user:{user_id}")
        answer = self.logins.get(user_id)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def org_membership(self, token: str, org: str, username: str) -> dict[str, Any] | None:
        self.calls.append(f"membership:{org}/{username}")
        if self.during_check is not None:
            hook, self.during_check = self.during_check, None
            hook()
        answer = self.memberships.get((org, username))
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def owner_calls(self) -> list[str]:
        """The calls an owner check makes (steps 1 to 3 and its mint)."""
        steps = ("token", "user:", "membership:")
        return [c for c in self.calls if c == "installation" or c.startswith(steps)]


class FakeForge:
    """The repository reads: an installation token and the owner's token see the private
    repository, the operator's token sees it private."""

    def __init__(self) -> None:
        self.sent: list[tuple[str | None, str]] = []
        self.private = True
        self.down = False  # the operator's token gets no answer, its visibility read included
        self.moved = False  # the operator's token meets a redirect: the repository moved

    def send(self, fg: forge.Forge, path: str, query: Any = None) -> Any:
        self.sent.append((fg.token, path))
        if self.down and fg.token == OPERATOR:
            raise forge.ForgeUnavailableError("the forge did not answer: timeout")
        if self.moved and fg.token == OPERATOR:
            raise forge.NotCoveredError("repository_moved")  # the forge's redirect
        if path == f"/repos/{REPO}":
            if fg.token in (OPERATOR, None) and self.private:
                return {"private": True} if fg.token == OPERATOR else None
            return {"private": self.private, "full_name": REPO}
        if path.startswith(f"/repos/{REPO}/branches/"):
            if fg.token in (OPERATOR, None) and self.private:
                return None
            return {"commit": {"sha": "a" * 40}}
        return None


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FakeApp:
    fake = FakeApp()
    for name in ("installation", "user_of_code", "token", "user_login", "org_membership"):
        method = getattr(fake, name)
        monkeypatch.setattr(
            github_app.GitHubApp, name, lambda _app, *a, _m=method, **k: _m(*a, **k)
        )

    def installation_of(_app: Any, repository: str) -> int:
        fake.calls.append("installation_of")
        if fake.lookup is not None:
            raise fake.lookup
        return INSTALLATION

    def repositories(_app: Any, installation_id: int, limit: int = 100) -> list[str]:
        fake.calls.append("repositories")
        return [REPO]

    monkeypatch.setattr(github_app.GitHubApp, "installation_of", installation_of)
    monkeypatch.setattr(github_app.GitHubApp, "repositories", repositories)
    monkeypatch.setattr(github_app, "_tokens", {})
    monkeypatch.setattr(forge, "_public", {})
    monkeypatch.setattr(forge_access, "_last_via", OrderedDict())
    monkeypatch.setattr(probe.Worker, "start", lambda self: None)  # the tests read themselves
    return fake


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> FakeForge:
    fake = FakeForge()
    monkeypatch.setattr(
        forge.Forge, "_send", lambda self, path, query=None: fake.send(self, path, query)
    )
    return fake


@pytest.fixture
def settings(settings: Settings) -> Settings:
    # No instance namespaces: the operator's token serves none of these projects.
    return replace(settings, forge_github_token=OPERATOR, github_app=APP, secret_key=KEY)


class HeldClock:
    """The hub's clock, still unless a test moves it."""

    def __init__(self) -> None:
        self.moment = clock.now()

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, by: timedelta) -> None:
        self.moment += by


@pytest.fixture
def held_clock() -> Iterator[HeldClock]:
    held = HeldClock()
    clock.set_source(held)
    try:
        yield held
    finally:
        clock.reset()


def _own_read_takes(app: FakeApp, held: HeldClock, by: timedelta) -> list[datetime]:
    """Linking's read of the user's own membership takes `by` on the clock; the time it was
    made, once it was."""
    made: list[datetime] = []

    def reading() -> None:
        made.append(held())
        held.advance(by)

    app.during_own = reading
    return made


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity", repository={"url": URL})
    return human


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
    return project_id


def _org_link(
    engine: Engine,
    human_id: str,
    status: str = "active",
    checked: timedelta = timedelta(0),
    ok: timedelta | None = timedelta(0),
    forge_user_id: int = 42,
) -> str:
    """A link on the forge organisation `acme`, last checked `checked` ago, its last successful
    owner check `ok` ago (None: none)."""
    now = clock.now()
    link_id = f"fgl-{human_id[-6:]}org"
    with engine.begin() as conn:
        conn.execute(
            insert(t.forge_link).values(
                id=link_id,
                human_id=human_id,
                forge="github",
                installation_id=INSTALLATION,
                account_id=ORG_ID,
                account_login="acme",
                account_type="Organization",
                repository_selection="all",
                status=status,
                linked_at=now - max(checked, ok or timedelta(0)),
                checked_at=now - checked,
                forge_user_id=forge_user_id,
                owner_ok_at=None if ok is None else now - ok,
            )
        )
    return link_id


def _link_row(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.forge_link)).one()


def _token(engine: Engine, human_id: str) -> None:
    assert KEY is not None
    now = clock.now()
    with engine.begin() as conn:
        conn.execute(
            insert(t.forge_token).values(
                human_id=human_id,
                forge="github",
                login="maintainer-gh",
                token_sealed=secretbox.seal(KEY, f"forge_token:{human_id}", OWNER_TOKEN.encode()),
                status="active",
                set_at=now,
                checked_at=now,
            )
        )


def _access(engine: Engine, own: frozenset[str] = frozenset()) -> forge_access.ForgeAccess:
    return forge_access.ForgeAccess(engine, APP, KEY, own)


def _reader(engine: Engine, own: frozenset[str] = frozenset()) -> forge.Forge:
    return forge.Forge(OPERATOR, access=_access(engine, own)).for_project(_project_id(engine))


def _confirm(owner: flow.Human) -> None:
    confirmed = owner.post("/projects/maintainer/maity/repository/confirm", {"url": URL})
    assert confirmed.status_code == 200, confirmed.text


def _records(engine: Engine, human_id: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.account_record.c.data)
            .where(
                t.account_record.c.human_id == human_id,
                t.account_record.c.type == "forge_access_changed",
            )
            .order_by(t.account_record.c.n)
        ).scalars()
        return [str(data["change"]) for data in rows]


def _json_setup(who: flow.Human, code: str = "c0de") -> Any:
    return who.client.get(
        "/api/v1/forge/github/setup",
        params={"installation_id": INSTALLATION, "code": code, "state": start(who)},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


# --- linking ----------------------------------------------------------------------------------


def test_an_owner_links_the_installation_and_the_link_is_its_first_check(
    owner: flow.Human, app: FakeApp, migrated: Engine
) -> None:
    """The owner check at linking reads the user's own membership with the user token, and
    counts as the link's first check and first success (A2510 6); `forge_user_id` is kept and
    in no answer."""
    assert link_setup(owner, INSTALLATION, start(owner)) == DONE
    assert "own_membership:acme" in app.calls
    row = _link_row(migrated)
    assert (row.account_type, row.status, row.forge_user_id) == ("Organization", "active", 42)
    assert row.owner_ok_at == row.checked_at <= row.linked_at
    body = owner.get("/me/forge")
    [link] = body.json()["links"]
    assert link["account"] == {"login": "acme", "type": "Organization"}
    assert (link["status"], link["repositories_shown"]) == ("active", [REPO])
    assert "forge_user_id" not in body.text and "owner_ok_at" not in body.text
    assert _records(migrated, owner.id) == ["linked"]


def test_the_first_check_at_linking_counts_from_the_membership_read(
    owner: flow.Human, app: FakeApp, migrated: Engine, held_clock: HeldClock
) -> None:
    """Review A2544 P2-1: the link's first success is never later than the read it rests on,
    so it serves no longer than 10 minutes after that read."""
    made = _own_read_takes(app, held_clock, timedelta(minutes=1))
    assert link_setup(owner, INSTALLATION, start(owner)) == DONE
    [read] = made
    row = _link_row(migrated)
    assert row.owner_ok_at == row.checked_at <= read
    assert row.linked_at - row.owner_ok_at >= timedelta(minutes=1)
    assert not forge_links.serves(row, read + TEN)


@pytest.mark.parametrize(
    "membership",
    [
        owner_of(42, state="pending"),
        owner_of(42, role="member"),
        owner_of(42, role="billing_manager"),
        owner_of(42, org_id=901),  # a login another organisation took
        None,  # a 404: an outside collaborator, a stranger
    ],
)
def test_a_definite_no_refuses_the_link_as_not_an_owners(
    owner: flow.Human, app: FakeApp, migrated: Engine, membership: Any
) -> None:
    app.own[42] = membership
    assert link_setup(owner, INSTALLATION, start(owner)) == DONE + "?error=not_organisation_admin"
    answer = _json_setup(owner)
    assert answer.status_code == 403
    assert answer.json()["error"]["details"] == {"reason": "not_organisation_admin"}
    with migrated.connect() as conn:
        assert conn.execute(select(t.forge_link)).first() is None


@pytest.mark.parametrize(
    "refusal",
    [
        forge.ForgeUnavailableError("the forge answered 403", 403),  # a missing permission
        forge.ForgeUnavailableError("the forge answered 429", 429, rate_limited=True),
        forge.ForgeUnavailableError("the forge did not answer: timeout"),
    ],
)
def test_no_definite_answer_links_nothing_and_is_forge_unavailable(
    owner: flow.Human, app: FakeApp, migrated: Engine, refusal: Exception
) -> None:
    app.own[42] = refusal
    assert link_setup(owner, INSTALLATION, start(owner)) == DONE + "?error=forge_unavailable"
    answer = _json_setup(owner)
    assert (answer.status_code, answer.json()["error"]["code"]) == (503, "forge_unavailable")
    with migrated.connect() as conn:
        assert conn.execute(select(t.forge_link)).first() is None


def test_an_installation_the_forge_does_not_name_is_refused_before_the_code_is_used(
    owner: flow.Human, app: FakeApp
) -> None:
    """The order of §11.4: the installation's existence before the account check."""
    app.installation_state = None
    assert link_setup(owner, INSTALLATION, start(owner)) == DONE + "?error=installation_not_yours"
    assert "user_of_code" not in app.calls


def test_a_non_owner_never_learns_whether_the_installation_is_linked(
    owner: flow.Human, app: FakeApp, migrated: Engine, make_client: ClientFactory
) -> None:
    """The account check comes before `installation_linked`, and a human who fails it sets off
    no check of the existing link."""
    _org_link(migrated, owner.id)
    anna = flow.human(make_client, migrated, "anna")
    app.own[43] = owner_of(43, role="member")
    app.calls.clear()
    assert link_setup(anna, INSTALLATION, start(anna), "anna") == (
        DONE + "?error=not_organisation_admin"
    )
    assert app.owner_calls() == ["installation"]  # the new human's own read, no owner check


# --- when the hub checks ----------------------------------------------------------------------


def test_a_fresh_success_serves_with_no_check(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, checked=timedelta(minutes=9), ok=timedelta(minutes=9))
    _confirm(owner)
    reader = _reader(migrated)
    assert reader.via == "app"
    assert reader.branch(REPO, "main")["found"] is True
    assert app.owner_calls() == ["token"]  # the read's own mint, no owner check
    assert app.kept == [True]


def test_a_due_check_runs_first_and_its_success_serves(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    _confirm(owner)
    before = clock.now()
    assert _reader(migrated).via == "app"
    assert app.owner_calls()[:4] == [
        "installation",
        "token",
        "user:42",
        "membership:acme/maintainer-gh",
    ]
    row = _link_row(migrated)
    assert row.status == "active" and row.checked_at >= before and row.owner_ok_at >= before
    assert app.kept[0] is False  # a stale link's check mints for itself alone


def test_a_recent_check_that_did_not_succeed_serves_nothing_and_calls_nothing(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """Last checked 5 minutes ago without success, last success 15 minutes ago: no check, no
    call to the forge but the choice's own lookup, nothing served until the next check."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=5), ok=timedelta(minutes=15))
    _confirm(owner)
    reader = _reader(migrated)
    assert reader.via is None
    with pytest.raises(forge.NotCoveredError) as raised:
        reader.branch(REPO, "main")
    assert raised.value.reason == errors.ORG_UNANSWERED
    assert app.calls == ["installation_of"]
    assert [token for token, _ in repo.sent] == []


def test_the_success_ages_out_ten_minutes_after_it_even_for_a_kept_choice(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """A choice that rests on the link is kept no longer than its owner check: with one
    `ForgeAccess` kept across the reads, the success 10 minutes back serves no more."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=9), ok=timedelta(minutes=9))
    _confirm(owner)
    access = _access(migrated)
    base = forge.Forge(OPERATOR, access=access)
    assert base.for_project(_project_id(migrated)).via == "app"
    calls = len(app.calls)
    later = clock.now() + timedelta(minutes=1, seconds=1)
    clock.set_source(lambda: later)  # nothing stored changes: the kept choice's key holds
    try:
        app.memberships[("acme", "maintainer-gh")] = forge.ForgeUnavailableError("down", 502)
        assert base.for_project(_project_id(migrated)).via is None
        assert "membership:acme/maintainer-gh" in app.calls[calls:]  # chosen again, checked
    finally:
        clock.reset()


def test_two_engines_never_both_check(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """The lead's ruling (seq 214797): a due check is claimed by a conditional update of
    `checked_at`, committed before its forge reads; a second engine choosing while the first
    checks finds it claimed and calls the forge for no owner check."""
    _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    _confirm(owner)
    other = make_engine(migrated.url.render_as_string(hide_password=False))
    seen: list[str | None] = []
    try:

        def second_engine_chooses() -> None:
            calls = len(app.calls)
            seen.append(_reader(other).via)
            seen.append(",".join(app.calls[calls:]))

        app.during_check = second_engine_chooses
        assert _reader(migrated).via == "app"
    finally:
        other.dispose()
    # the second engine's choice: only its own lookup, no owner check, nothing served yet
    assert seen == [None, "installation_of"]
    assert app.owner_calls().count("installation") == 1


def test_two_connections_claim_a_due_check_once(owner: flow.Human, migrated: Engine) -> None:
    link_id = _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    at = clock.now()
    with migrated.begin() as conn:
        assert forge_links.claim(conn, link_id, at) is True
    with migrated.begin() as conn:
        assert forge_links.claim(conn, link_id, at) is False
        assert forge_links.claim(conn, link_id, at + timedelta(minutes=9)) is False


def test_a_link_on_a_user_account_is_never_owner_checked(
    owner: flow.Human, migrated: Engine
) -> None:
    now = clock.now()
    with migrated.begin() as conn:
        conn.execute(
            insert(t.forge_link).values(
                id="fgl-user", human_id=owner.id, forge="github", installation_id=8,
                account_id=42, account_login="maintainer-gh", account_type="User",
                repository_selection="all", status="active", linked_at=now - TEN,
                checked_at=now - TEN,
            )
        )  # fmt: skip
        assert forge_links.claim(conn, "fgl-user", now) is False
    row = _link_row(migrated)
    assert forge_links.serves(row) and not forge_links.due(row)
    assert row.forge_user_id is None and row.owner_ok_at is None


# --- how it checks ----------------------------------------------------------------------------


def _check(engine: Engine, app: FakeApp) -> str:
    """One due check through the source choice; the link's status after it."""
    _reader(engine)
    status: str = _link_row(engine).status
    return status


def test_a_renamed_organisation_and_user_keep_the_link(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """Step 1's login names the organisation, step 2's the user: never a stored login."""
    _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    _confirm(owner)
    app.login = "acme-renamed"
    app.logins[42] = "renamed-gh"
    app.memberships[("acme-renamed", "renamed-gh")] = owner_of(42)
    assert _check(migrated, app) == "active"
    assert "membership:acme-renamed/renamed-gh" in app.calls
    assert _link_row(migrated).account_login == "acme-renamed"


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"logins": None}, "the user by id is gone (404)"),
        ({"membership": None}, "no membership (404)"),
        ({"membership": owner_of(99)}, "the membership is another user's"),
        ({"membership": owner_of(42, org_id=901)}, "the login is another organisation's"),
        ({"membership": owner_of(42, role="member")}, "a member, no owner"),
        ({"membership": owner_of(42, state="pending")}, "not active"),
    ],
)
def test_a_definite_no_makes_the_link_not_admin_once(
    owner: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    change: dict[str, Any],
    why: str,
) -> None:
    _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    _confirm(owner)
    if "logins" in change:
        app.logins[42] = change["logins"]
    else:
        app.memberships[("acme", "maintainer-gh")] = change["membership"]
    github_app._tokens[(APP.app_id, INSTALLATION)] = ("held", 2**40)
    assert _check(migrated, app) == "not_admin", why
    assert (APP.app_id, INSTALLATION) not in github_app._tokens  # the tokens dropped
    assert _records(migrated, owner.id) == ["not_admin"]
    with migrated.begin() as conn:  # due again: still no owner, no second record
        conn.execute(update(t.forge_link).values(checked_at=clock.now() - TEN))
    assert _check(migrated, app) == "not_admin"
    assert _records(migrated, owner.id) == ["not_admin"]


@pytest.mark.parametrize(
    "refusal",
    [
        forge.ForgeUnavailableError("the forge answered 403", 403),
        forge.ForgeUnavailableError("the forge answered 429", 429, rate_limited=True),
        forge.ForgeUnavailableError("the forge did not answer: timeout"),
    ],
)
def test_no_answer_changes_no_status_and_keeps_the_last_success(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine, refusal: Exception
) -> None:
    _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    _confirm(owner)
    ok_before = _link_row(migrated).owner_ok_at
    app.memberships[("acme", "maintainer-gh")] = refusal
    with pytest.raises(forge.NotCoveredError) as raised:
        _reader(migrated).branch(REPO, "main")
    assert raised.value.reason == errors.ORG_UNANSWERED
    row = _link_row(migrated)
    assert (row.status, row.owner_ok_at) == ("active", ok_before)
    assert row.checked_at > ok_before  # the check counts as the last one
    assert _records(migrated, owner.id) == []


def test_a_not_admin_link_serves_nothing_mints_unkept_and_a_restored_role_restores_it(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, status="not_admin", checked=timedelta(minutes=5), ok=None)
    _confirm(owner)
    with pytest.raises(forge.NotCoveredError) as raised:
        _reader(migrated).branch(REPO, "main")
    assert raised.value.reason == errors.ORG_NOT_ADMIN
    assert app.owner_calls() == []  # not due: no check, no mint
    with migrated.begin() as conn:
        conn.execute(update(t.forge_link).values(checked_at=clock.now() - TEN))
    reader = _reader(migrated)
    assert app.kept[0] is False  # the re-check's own token, not kept
    assert reader.via == "app" and _link_row(migrated).status == "active"


def test_a_suspended_link_is_back_only_through_its_owner_check(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """A mint alone never sets it `active`: within the 10 minutes it serves nothing and no
    mint is made; the due check sets it `active` when step 1 finds it unsuspended."""
    _org_link(migrated, owner.id, status="suspended", checked=timedelta(minutes=5))
    _confirm(owner)
    with pytest.raises(forge.NotCoveredError) as raised:
        _reader(migrated).branch(REPO, "main")
    assert raised.value.reason == errors.ORG_SUSPENDED
    assert app.owner_calls() == []
    links = owner.get("/me/forge").json()["links"]
    assert [(link["status"], link["repositories_shown"]) for link in links] == [("suspended", [])]
    assert app.owner_calls() == []  # the listing minted nothing either
    with migrated.begin() as conn:
        conn.execute(update(t.forge_link).values(checked_at=clock.now() - TEN))
    app.installation_state = "suspended"
    assert _check(migrated, app) == "suspended"  # step 1 still finds it suspended
    assert "token" not in app.calls
    with migrated.begin() as conn:
        conn.execute(update(t.forge_link).values(checked_at=clock.now() - TEN))
    app.installation_state = "active"
    assert _check(migrated, app) == "active"


def test_a_mint_that_succeeds_never_sets_an_organisation_link_active(
    owner: flow.Human, migrated: Engine
) -> None:
    """`set_status` is what a mint found; for a link on a forge organisation only its owner
    check sets `active`, and a refused mint leaves the check's cadence alone."""
    link_id = _org_link(migrated, owner.id, status="suspended", checked=timedelta(minutes=3))
    checked = _link_row(migrated).checked_at
    with migrated.begin() as conn:
        forge_links.set_status(conn, link_id, "active")
    assert _link_row(migrated).status == "suspended"
    with migrated.begin() as conn:
        forge_links.set_status(conn, link_id, "removed")
    row = _link_row(migrated)
    assert (row.status, row.checked_at) == ("removed", checked)


def test_an_owner_who_lost_the_role_while_suspended_never_gets_it_back(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, status="suspended", checked=TEN)
    _confirm(owner)
    app.memberships[("acme", "maintainer-gh")] = None
    assert _check(migrated, app) == "not_admin"
    assert _records(migrated, owner.id) == ["not_admin"]


def test_the_listing_checks_a_due_link_and_shows_what_it_found(
    owner: flow.Human, app: FakeApp, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    app.memberships[("acme", "maintainer-gh")] = owner_of(42, role="member")
    [link] = owner.get("/me/forge").json()["links"]
    assert (link["status"], link["repositories_shown"]) == ("not_admin", [])
    assert "repositories" not in app.calls
    calls = len(app.calls)
    [link] = owner.get("/me/forge").json()["links"]  # within 10 minutes: no call at all
    assert link["status"] == "not_admin" and app.calls[calls:] == []


def test_a_stale_active_link_is_listed_active_with_no_repositories(
    owner: flow.Human, app: FakeApp, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, checked=timedelta(minutes=3), ok=timedelta(minutes=12))
    [link] = owner.get("/me/forge").json()["links"]
    assert (link["status"], link["repositories_shown"]) == ("active", [])
    assert app.calls == []


def test_the_not_admin_record_is_a_security_item(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    _confirm(owner)
    app.memberships[("acme", "maintainer-gh")] = None
    _check(migrated, app)
    items = owner.get("/me/notifications").json()["items"]
    titles = [i["title"] for i in items if i["kind"] == "security" and "Forge" in i["title"]]
    assert titles == ["Forge access stopped: no longer an owner of acme"]


def test_the_confirmation_calls_no_forge(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """`…/repository/confirm` is no caller: no owner check, nothing to the forge, even with
    the check due (A2509 2c)."""
    _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    _confirm(owner)
    assert app.calls == [] and repo.sent == []
    assert _link_row(migrated).checked_at < clock.now() - timedelta(minutes=9)


# --- what a project sees ----------------------------------------------------------------------


def test_a_link_that_serves_nothing_falls_through_to_the_owners_token(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, status="not_admin", checked=timedelta(minutes=1), ok=None)
    _token(migrated, owner.id)
    _confirm(owner)
    reader = _reader(migrated)
    assert (reader.via, reader.token) == ("owner_token", OWNER_TOKEN)
    repository = owner.get("/projects/maintainer/maity").json()["repository"]
    assert repository["probe_via"] == "owner_token"


def test_a_link_that_serves_nothing_falls_through_to_the_instance_where_it_may_serve(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=TEN)
    _confirm(owner)
    repo.private = False
    reader = _reader(migrated, own=frozenset({"maintainer"}))
    assert (reader.via, reader.token) == ("instance", OPERATOR)
    assert reader.branch(REPO, "main")["found"] is True
    repo.private = True
    forge._public.clear()  # the visibility kept for 10 minutes: asked again
    with pytest.raises(forge.NotCoveredError) as raised:
        _reader(migrated, own=frozenset({"maintainer"})).branch(REPO, "main")
    assert raised.value.reason == errors.ORG_UNANSWERED  # the owner's reason says more


def _readers(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> tuple[flow.Human, flow.Human]:
    """Another `project:admin` of the project and a guest."""
    project_id = _project_id(migrated)
    admin = flow.human(make_client, migrated, "anna")
    factory.membership(migrated, project_id, role="owner", human_id=admin.id)
    guest = flow.human(make_client, migrated, "bob")
    factory.membership(migrated, project_id, role="guest", human_id=guest.id)
    return admin, guest


PROBE = "/projects/maintainer/maity/probe?branch=main"
CONTRACT = "/projects/maintainer/maity/contract"
EXPORT = "/projects/maintainer/maity/keep-the-why/export"
WHY = "/projects/maintainer/maity/keep-the-why"


def _error(answer: Any) -> tuple[int, str, Any]:
    error = answer.json()["error"]
    return answer.status_code, error["code"], error.get("details")


@pytest.mark.parametrize(
    ("status", "checked", "ok", "specific"),
    [
        ("not_admin", timedelta(minutes=1), None, "installation_not_admin"),
        ("suspended", timedelta(minutes=1), timedelta(minutes=1), "installation_suspended"),
        ("removed", timedelta(minutes=1), timedelta(minutes=1), "installation_removed"),
    ],
)
def test_each_reader_gets_its_reason_for_a_link_that_serves_nothing(
    owner: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    make_client: ClientFactory,
    status: str,
    checked: timedelta,
    ok: timedelta | None,
    specific: str,
) -> None:
    _org_link(migrated, owner.id, status=status, checked=checked, ok=ok)
    _confirm(owner)
    admin, guest = _readers(owner, make_client, migrated)
    for path in (PROBE, CONTRACT, EXPORT, WHY):
        assert _error(owner.get(path)) == (409, "probe_not_configured", {"reason": specific}), path
        invalid = {"reason": "installation_link_invalid"}
        assert _error(admin.get(path)) == (409, "probe_not_configured", invalid), path
        assert _error(guest.get(path)) == (409, "probe_not_configured", {}), path


def test_each_reader_gets_its_answer_while_the_owner_check_has_no_answer(
    owner: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    make_client: ClientFactory,
) -> None:
    _org_link(migrated, owner.id, checked=timedelta(minutes=2), ok=timedelta(minutes=12))
    _confirm(owner)
    admin, guest = _readers(owner, make_client, migrated)
    assert _error(owner.get(PROBE))[:2] == (503, "probe_unavailable")
    assert _error(owner.get(CONTRACT))[:2] == (503, "probe_unavailable")
    for path in (EXPORT, WHY):  # the views: no `last`, as no export outlives the success
        unavailable = (503, "ktw_unavailable", {"reason": "forge_unavailable"})
        assert _error(owner.get(path)) == unavailable, path
    for path in (PROBE, CONTRACT, EXPORT, WHY):
        invalid = {"reason": "installation_link_invalid"}
        assert _error(admin.get(path)) == (409, "probe_not_configured", invalid), path
        assert _error(guest.get(path)) == (409, "probe_not_configured", {}), path


def test_the_probes_unavailable_answer_carries_the_last_observation(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, checked=timedelta(minutes=9), ok=timedelta(minutes=9))
    _confirm(owner)
    assert owner.get(PROBE).status_code == 200  # observed while the link served
    with migrated.begin() as conn:
        conn.execute(
            update(t.forge_link).values(
                checked_at=clock.now() - timedelta(minutes=1),
                owner_ok_at=clock.now() - timedelta(minutes=11),
            )
        )
    status, code, details = _error(owner.get(PROBE + "&max_age=0"))
    assert (status, code) == (503, "probe_unavailable")
    assert details["last"]["observed_at"]


def test_an_agent_of_the_confirming_owner_is_not_the_confirmer(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine, make_client: ClientFactory
) -> None:
    """The specific reason is the human's named in `confirmed_by`, never their agent's."""
    _org_link(migrated, owner.id, status="not_admin", checked=timedelta(minutes=1), ok=None)
    _confirm(owner)
    agent = flow.agent(make_client, owner)
    assert _error(agent.get(PROBE)) == (409, "probe_not_configured", {})


def test_a_link_on_a_user_account_keeps_its_reasons_for_every_admin(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine, make_client: ClientFactory
) -> None:
    now = clock.now()
    with migrated.begin() as conn:
        conn.execute(
            insert(t.forge_link).values(
                id="fgl-user", human_id=owner.id, forge="github", installation_id=INSTALLATION,
                account_id=42, account_login="maintainer-gh", account_type="User",
                repository_selection="all", status="removed", linked_at=now, checked_at=now,
            )
        )  # fmt: skip
    _confirm(owner)
    admin, _ = _readers(owner, make_client, migrated)
    for who in (owner, admin):
        removed = (409, "probe_not_configured", {"reason": "installation_removed"})
        assert _error(who.get(PROBE)) == removed


# --- review A2545 #5 and #6: no cache answers for a link that serves nothing ----------------------


def _cached_export(engine: Engine) -> str:
    """An export in §11.3's cache, as a read through the link left it: a private one."""
    project_id = _project_id(engine)
    snapshot = ktw.Snapshot(clock.rfc3339(clock.now()), [], False)
    with ktw.CACHE.guard:
        ktw.CACHE.entries[project_id] = ktw._Entry(snapshot, ktw.now(), URL)
    return project_id


def _operators(who: flow.Human) -> None:
    """The project's namespace is one of the operator's own (`MAITY_FORGE_INSTANCE_NAMESPACES`)."""
    who.client.app.state.forge_access.instance_namespaces = frozenset({"maintainer"})  # type: ignore[attr-defined]


def test_the_why_cache_is_not_answered_while_the_visibility_after_such_a_link_is_unread(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """In an operator's namespace the operator's token comes after a link that serves nothing,
    and only for a public repository; while the forge does not say whether it is, §11.3
    answers `forge_unavailable` without `details.last`, never the cached export."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=12))
    _confirm(owner)
    _operators(owner)
    _cached_export(migrated)
    repo.down = True
    assert _error(owner.get(WHY)) == (503, "ktw_unavailable", {"reason": "forge_unavailable"})


def test_the_why_cache_is_not_answered_while_the_choice_has_no_answer(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """The choice's own installation lookup gets no answer: the reader holds no token and no
    refusal, and with a link on a forge organisation among the grants §11.3 answers
    `forge_unavailable` without `details.last`, never the cached export."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    _cached_export(migrated)
    app.lookup = forge.ForgeUnavailableError("the forge did not answer: timeout")
    assert _error(owner.get(WHY)) == (503, "ktw_unavailable", {"reason": "forge_unavailable"})


def test_the_why_reads_with_the_reader_it_checked(
    owner: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The source §11.3 checked is the one its cache reads with: one choice per call, never a
    second one that could differ from the first."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    chosen: list[str] = []
    choose = forge_access.ForgeAccess.reader

    def counted(self: Any, project_id: str, base: forge.Forge) -> forge.Forge:
        chosen.append(project_id)
        return choose(self, project_id, base)

    monkeypatch.setattr(forge_access.ForgeAccess, "reader", counted)
    owner.get(WHY)  # a cold cache: the family is read
    assert len(chosen) == 1


def test_an_unlinked_link_leaves_no_cached_export(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """Without the link the choice refuses with `no_grant`, which §11.3 does not ask about: the
    unlink takes the project's reads from the cache, so none read through the link is answered."""
    link_id = _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    project_id = _cached_export(migrated)
    assert owner.get(WHY).status_code == 200  # served from the cache while the link serves
    assert owner.delete(f"/me/forge/github/links/{link_id}").status_code == 204
    assert ktw.CACHE.cached(project_id) is None
    assert owner.get(WHY).status_code != 200


def test_a_replaced_link_leaves_no_cached_export(
    owner: flow.Human, anna: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    project_id = _cached_export(migrated)
    app.memberships[("acme", "maintainer-gh")] = None
    assert _anna_links(anna) == DONE
    assert ktw.CACHE.cached(project_id) is None
    assert owner.get(WHY).status_code != 200


@pytest.mark.parametrize("how", ["unlinked", "replaced"])
def test_a_read_in_flight_when_the_link_goes_stores_nothing(
    owner: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    make_client: ClientFactory,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    """Review A2586 (22c5's P3 #4): a family read through the link that is still in flight when
    the link is unlinked or replaced, and finishes afterwards, puts nothing back into the cache
    (no export, no member's last good read). Otherwise the view, the list and §11.3 would answer
    it until the grant it was read with ends, as nothing asks the link again then: it is gone."""
    link_id = _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    anna = request.getfixturevalue("anna") if how == "replaced" else None
    project_id = _project_id(migrated)
    reading, release = threading.Event(), threading.Event()
    read_with: list[str | None] = []
    real_walk = ktw.walk

    def blocked_walk(reader: forge.Forge, repository: str, deadline: float | None = None) -> Any:
        read_with.append(reader.via)
        if len(read_with) > 1:  # the reads after the link went: the forge as it is
            return real_walk(reader, repository, deadline)
        reading.set()
        assert release.wait(10)
        summary = {
            "status": dict.fromkeys((*ktw.STATUSES, "other"), 0),
            "findings": {"errors": 0, "warnings": 0},
            "entries": 0,
            "attention": 0,
        }
        read = ktw.Read(summary, [], 0)
        return ktw.Family([ktw.Member(path=".", name="secret-plan", id="sid", read=read)], False)

    monkeypatch.setattr(ktw, "walk", blocked_walk)
    base = forge.Forge(OPERATOR, access=_access(migrated))
    errors_in_read: list[BaseException] = []

    def read() -> None:
        try:
            ktw.CACHE.get(base, project_id, URL)
        except BaseException as error:  # noqa: BLE001 - reported below
            errors_in_read.append(error)

    reader = threading.Thread(target=read)
    reader.start()
    try:
        assert reading.wait(10)
        if anna is None:
            assert owner.delete(f"/me/forge/github/links/{link_id}").status_code == 204
        else:
            app.memberships[("acme", "maintainer-gh")] = None
            assert _anna_links(anna) == DONE
    finally:
        release.set()
        reader.join(10)
    assert not reader.is_alive() and errors_in_read == []
    assert read_with == ["app"]  # it read through the link
    guest = flow.human(make_client, migrated, "bob")
    factory.membership(migrated, project_id, role="guest", human_id=guest.id)
    answered = []  # every reader that answers what the link read, so a failure names them all
    for name, who in (("owner", owner), ("guest", guest)):
        view = who.get(VIEW)
        assert view.status_code == 200, view.text
        # (an error answered after the link went is an export too, with no member in it)
        if "secret-plan" in str(view.json()["keep_the_why_export"]):
            answered.append(f"{name}: view")
        listed = who.get("/projects").json()["items"]
        if "secret-plan" in str([item.get("keep_the_why_export") for item in listed]):
            answered.append(f"{name}: list")
        why = who.get(WHY)
        if why.status_code == 200 or "secret-plan" in why.text:
            answered.append(f"{name}: §11.3")
    assert answered == []
    entry = ktw.CACHE.cached(project_id)
    assert entry is None or entry.snapshot is None or entry.snapshot.members == []
    assert not [key for key in ktw.CACHE.last_good if key[0] == project_id]


@pytest.mark.parametrize("forget", ["one", "all", "notice"])
def test_a_forget_during_a_read_keeps_nothing_it_read(
    monkeypatch: pytest.MonkeyPatch, forget: str
) -> None:
    """The cache alone (A2586): `forget` or `forget_all` while a family is read, or the
    `repository:` notice another replica's unlink sends, leaves neither the entry nor a
    member's last good read, and marks nothing read, so the next request reads again."""
    cache = ktw.Cache(bind=False) if forget != "notice" else ktw.CACHE
    summary = {
        "status": dict.fromkeys((*ktw.STATUSES, "other"), 0),
        "findings": {"errors": 0, "warnings": 0},
        "entries": 0,
        "attention": 0,
    }

    def walk(reader: forge.Forge, repository: str, deadline: float | None = None) -> Any:
        if forget == "one":
            cache.forget("prj-1")
        elif forget == "all":
            cache.forget_all()
        else:  # as the listener hands it over (`wakeups.Listener`)
            wakeups.forgotten("repository:prj-1")
        read = ktw.Read(summary, [], 0)
        return ktw.Family([ktw.Member(path=".", name="secret-plan", id="sid", read=read)], False)

    monkeypatch.setattr(ktw, "walk", walk)
    entry, fresh = cache.get(forge.Forge(OPERATOR), "prj-1", URL)
    assert fresh and entry.snapshot is not None  # its own request gets what it read
    assert cache.cached("prj-1") is None
    assert cache.last_good == {}
    assert cache.refresh.forgotten == {} and cache.refresh.users == {}  # nothing outlives it
    assert "prj-1" not in cache.refresh.last_read  # a forced read is not held back


LINK_TOKEN = f"ghs_installation_{INSTALLATION}"


@pytest.mark.parametrize("how", ["unlinked", "replaced"])
def test_a_link_that_goes_after_the_choice_read_it_serves_nothing(
    owner: flow.Human,
    anna: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    """Review A2585 P2-1 (jc4h): the link is unlinked or replaced after the choice read the
    grants and before it uses the link (here inside its installation lookup). Nothing is read
    with the link's token after that, and nothing such a read found is answered by §11.3 or
    the project view."""
    link_id = _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    reads: list[str | None] = []
    real_walk = ktw.walk

    def walk(reader: forge.Forge, repository: str, deadline: float | None = None) -> Any:
        reads.append(reader.token)
        if reader.token == LINK_TOKEN:  # one private member, as the link reads it
            return ktw.Family([ktw.Member(path=".", name="secret-plan", id="sid")], False)
        return real_walk(reader, repository, deadline)

    monkeypatch.setattr(ktw, "walk", walk)
    changed: list[bool] = []
    lookup = github_app.GitHubApp.installation_of

    def installation_of(self: Any, repository: str) -> int | None:
        if not changed:  # once, after the grants were read, before the link is used
            changed.append(True)
            if how == "unlinked":
                assert owner.delete(f"/me/forge/github/links/{link_id}").status_code == 204
            else:
                app.memberships[("acme", "maintainer-gh")] = None  # the check: no owner
                assert _anna_links(anna) == DONE
        return lookup(self, repository)

    monkeypatch.setattr(github_app.GitHubApp, "installation_of", installation_of)
    first = owner.get(WHY)
    assert changed, "the change did not run inside the choice"
    second = owner.get(WHY)
    view = owner.get(VIEW).json()["keep_the_why_export"]
    assert LINK_TOKEN not in reads, reads
    assert "secret-plan" not in first.text, first.text
    assert "secret-plan" not in second.text, second.text
    assert "secret-plan" not in str(view)


@pytest.mark.parametrize("how", ["unlinked", "replaced", "deleted", "before"])
def test_a_link_that_goes_during_the_read_keeps_nothing_of_it(
    owner: flow.Human,
    anna: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    """A2585 P2-1 and P2-2: the link is unlinked or replaced inside the family walk made with
    its token, or its row deleted with no `forget` at all; `before`: unlinked before the read,
    which must hold as well. Neither that call nor a later one (§11.3 twice and forced, the
    project view and the list, the owner's and a guest's) answers what the walk found."""
    link_id = _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    project_id = _project_id(migrated)
    guest = flow.human(make_client, migrated, "bob")
    factory.membership(migrated, project_id, role="guest", human_id=guest.id)
    reads: list[str | None] = []
    real_walk = ktw.walk

    def unlink() -> None:
        if how in ("unlinked", "before"):
            assert owner.delete(f"/me/forge/github/links/{link_id}").status_code == 204
        elif how == "replaced":
            app.memberships[("acme", "maintainer-gh")] = None  # the check: no owner
            assert _anna_links(anna) == DONE
        else:
            with migrated.begin() as conn:
                conn.execute(t.forge_link.delete().where(t.forge_link.c.id == link_id))

    def walk(reader: forge.Forge, repository: str, deadline: float | None = None) -> Any:
        reads.append(reader.token)
        if reader.token != LINK_TOKEN:
            return real_walk(reader, repository, deadline)
        if how != "before":
            unlink()
        return ktw.Family([ktw.Member(path=".", name="secret-plan", id="sid")], False)

    monkeypatch.setattr(ktw, "walk", walk)
    if how == "before":
        unlink()
    first = owner.get(WHY)
    assert "secret-plan" not in first.text, first.text
    if how != "before":  # the call that read through the link keeps nothing, not even its error
        assert LINK_TOKEN in reads, reads
        assert ktw.CACHE.cached(project_id) is None
    answered = []
    for name, who in (("owner", owner), ("guest", guest)):
        for path in (WHY, WHY, WHY + "?max_age=0", VIEW, "/projects"):
            answer = who.get(path)
            if "secret-plan" in answer.text:
                answered.append(f"{name}: {path}")
    assert answered == []
    assert (LINK_TOKEN in reads) == (how != "before"), reads
    assert reads.count(LINK_TOKEN) <= 1, reads  # never through the link again
    entry = ktw.CACHE.cached(project_id)
    assert entry is None or entry.snapshot is None or entry.snapshot.members == []


def _family(name: str) -> Any:
    """A family of one member called `name`, read."""
    summary = {
        "status": dict.fromkeys((*ktw.STATUSES, "other"), 0),
        "findings": {"errors": 0, "warnings": 0},
        "entries": 0,
        "attention": 0,
    }
    member = ktw.Member(path=".", name=name, id="sid", read=ktw.Read(summary, [], 0))
    return ktw.Family([member], False)


def test_a_read_across_the_end_of_the_grant_keeps_nothing_and_the_next_check_serves(
    held_clock: HeldClock,
    owner: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review A2592: a family read through the link that starts before the link's grant ends
    and finishes after it is answered to its own call as `forge_unavailable`, and kept for no
    other. Once the next owner check succeeds, §11.3, §11.5 and the project view answer from a
    new read through the link, not that call's error."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    project_id = _project_id(migrated)
    admin, _guest = _readers(owner, make_client, migrated)
    reads: list[str | None] = []

    def walk(reader: forge.Forge, repository: str, deadline: float | None = None) -> Any:
        reads.append(reader.token)
        if len(reads) == 1:  # the grant ends while this read is made
            held_clock.advance(timedelta(minutes=9, seconds=1))
        return _family("the-plan")

    monkeypatch.setattr(ktw, "walk", walk)
    first = owner.get(WHY)
    assert _error(first) == (503, "ktw_unavailable", {"reason": "forge_unavailable"})
    assert ktw.CACHE.cached(project_id) is None
    checked_before = _link_row(migrated).owner_ok_at
    why = owner.get(WHY)
    assert why.status_code == 200, why.text
    assert "the-plan" in why.text
    assert _link_row(migrated).owner_ok_at > checked_before  # the owner check ran and succeeded
    assert reads == [LINK_TOKEN, LINK_TOKEN]
    export = admin.get(EXPORT)
    assert export.status_code != 409 and export.status_code < 500, export.text
    view = owner.get(VIEW).json()["keep_the_why_export"]
    assert view["error"] is None and view["members"][0]["name"] == "the-plan"


def test_a_link_unlinked_before_the_cache_reads_keeps_nothing_and_the_next_call_falls_back(
    owner: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review A2592: the link is unlinked after §11.3 chose it and before the cache reads with
    it. That call keeps nothing, and the next one reads with the owner's own token."""
    link_id = _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _token(migrated, owner.id)
    _confirm(owner)
    project_id = _project_id(migrated)
    reads: list[str | None] = []

    def walk(reader: forge.Forge, repository: str, deadline: float | None = None) -> Any:
        reads.append(reader.token)
        return _family("secret-plan" if reader.token == LINK_TOKEN else "owner-read")

    monkeypatch.setattr(ktw, "walk", walk)
    get = ktw.Cache.get
    unlinked: list[bool] = []

    def unlink_first(self: ktw.Cache, reader: forge.Forge, *args: Any, **kwargs: Any) -> Any:
        if not unlinked:
            unlinked.append(True)
            assert reader.via == "app"  # §11.3 chose the link
            assert owner.delete(f"/me/forge/github/links/{link_id}").status_code == 204
        return get(self, reader, *args, **kwargs)

    monkeypatch.setattr(ktw.Cache, "get", unlink_first)
    first = owner.get(WHY)
    assert unlinked and "secret-plan" not in first.text, first.text
    assert ktw.CACHE.cached(project_id) is None
    second = owner.get(WHY)
    assert second.status_code == 200, second.text
    assert "owner-read" in second.text and "secret-plan" not in second.text
    assert reads[-1] == OWNER_TOKEN, reads


def _observed_then_not_admin(owner: flow.Human, migrated: Engine) -> None:
    """A probe observation read while the link served, then the link `not_admin`."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    _operators(owner)
    assert owner.get(PROBE).status_code == 200
    with migrated.begin() as conn:
        conn.execute(update(t.forge_link).values(status="not_admin"))


def test_the_probe_cache_is_not_answered_after_such_a_link_for_a_private_repository(
    owner: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    make_client: ClientFactory,
) -> None:
    """In an operator's namespace the operator's token comes after the link and finds the
    repository private: each reader gets their answer, never the observation the link read."""
    _observed_then_not_admin(owner, migrated)
    admin, guest = _readers(owner, make_client, migrated)
    for who in (admin, guest):
        _operators(who)
    specific = {"reason": "installation_not_admin"}
    assert _error(owner.get(PROBE)) == (409, "probe_not_configured", specific)
    invalid = {"reason": "installation_link_invalid"}
    assert _error(admin.get(PROBE)) == (409, "probe_not_configured", invalid)
    assert _error(guest.get(PROBE)) == (409, "probe_not_configured", {})


def test_the_probe_cache_is_not_answered_while_the_visibility_after_such_a_link_is_unread(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    _observed_then_not_admin(owner, migrated)
    repo.down = True
    status, code, details = _error(owner.get(PROBE))
    assert (status, code) == (503, "probe_unavailable") and not details


# --- review A2574: what a link that stopped serving read is answered nowhere ---------------------


def test_the_probe_cache_is_not_answered_after_the_link_is_unlinked(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """P2-1: an unlinked link leaves no reason behind; the operator's token is asked on every
    call whether it covers the repository, so the observation the link read is not answered."""
    link_id = _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    _operators(owner)
    assert owner.get(PROBE).status_code == 200
    assert owner.delete(f"/me/forge/github/links/{link_id}").status_code == 204
    private = (409, "probe_not_configured", {"reason": "private_without_grant"})
    assert _error(owner.get(PROBE)) == private


def test_the_probe_cache_is_not_answered_after_the_link_is_replaced(
    owner: flow.Human, anna: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    _operators(owner)
    assert owner.get(PROBE).status_code == 200
    app.memberships[("acme", "maintainer-gh")] = None
    assert _anna_links(anna) == DONE
    private = (409, "probe_not_configured", {"reason": "private_without_grant"})
    assert _error(owner.get(PROBE)) == private


def test_the_why_cache_is_not_answered_when_the_repository_moved_after_such_a_link(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """P2-2: `repository_moved` keeps its own reason, and is answered by reader too."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=12))
    _confirm(owner)
    _operators(owner)
    _cached_export(migrated)
    repo.moved = True
    moved = (409, "probe_not_configured", {"reason": "repository_moved"})
    assert _error(owner.get(WHY)) == moved


def _cached_until(engine: Engine, until: datetime) -> str:
    """An export in the cache read through a link whose grant ends at `until`."""
    project_id = _cached_export(engine)
    with ktw.CACHE.guard:
        ktw.CACHE.entries[project_id].until = until
    return project_id


def test_the_reader_of_such_a_link_carries_when_its_grant_ends(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """P2-3: the cache keeps an export with the time the grant it was read with ends."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    reader = _reader(migrated)
    assert reader.via == "app"
    assert reader.serves_until == _link_row(migrated).owner_ok_at + TEN


def test_the_project_view_shows_no_export_past_its_grant(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """P2-3: the project view answers from the cache only, and never an export past the grant
    it was read with, though no write ended the link (an `active` one ageing out)."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    _cached_until(migrated, clock.now() + TEN)
    view = owner.get("/projects/maintainer/maity").json()
    assert view["keep_the_why_export"] is not None  # within the grant
    _cached_until(migrated, clock.now() - timedelta(seconds=1))
    view = owner.get("/projects/maintainer/maity").json()
    assert view["keep_the_why_export"] is None


def test_the_why_cache_reads_anew_past_the_grant(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """Past its grant the entry is read anew, never answered (here the read finds no
    `.keep-the-why`)."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    _cached_until(migrated, clock.now() - timedelta(seconds=1))
    assert _error(owner.get(WHY))[:2] == (409, "ktw_not_configured")


def test_a_failed_read_after_such_a_link_keeps_none_of_what_it_read(
    owner: flow.Human, migrated: Engine
) -> None:
    """P2-3: the root read refused for a link that serves nothing keeps no member's last good
    read, so none is shown again."""
    project_id = _project_id(migrated)
    cache = ktw.Cache()
    cache.last_good[(project_id, REPO, "")] = (Any, None)  # type: ignore[assignment]
    refused = forge.Forge(None, refused=errors.ORG_NOT_ADMIN, project_id=project_id)
    entry, _ = cache.get(refused, project_id, URL, 0)
    assert entry.snapshot is not None and entry.snapshot.members == []
    assert cache.last_good == {}


def test_a_link_that_leaves_active_drops_the_cached_export(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """P2-3: a definite "no", and a refused mint, end what the link read in the cache at once."""
    link_id = _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    _confirm(owner)
    project_id = _cached_export(migrated)
    app.memberships[("acme", "maintainer-gh")] = None
    assert _check(migrated, app) == "not_admin"
    assert ktw.CACHE.cached(project_id) is None
    with migrated.begin() as conn:
        conn.execute(update(t.forge_link).values(status="active"))
    _cached_export(migrated)
    with migrated.begin() as conn:
        forge_links.set_status(conn, link_id, "suspended")
    assert ktw.CACHE.cached(project_id) is None


VIEW = "/projects/maintainer/maity"


def _cached_member(engine: Engine) -> str:
    """An export in the cache naming one member, as a read through the link left it, with no
    grant's end on it: what the view and §11.3 do must not rest on that mark alone."""
    project_id = _project_id(engine)
    member = ktw.Member(path=".", name="secret-plan", id="secret-id")
    snapshot = ktw.Snapshot(clock.rfc3339(clock.now()), [member], False)
    with ktw.CACHE.guard:
        ktw.CACHE.entries[project_id] = ktw._Entry(snapshot, ktw.now(), URL)
    return project_id


@pytest.mark.parametrize("state", ["not_admin", "stale", "suspended"])
def test_the_project_view_shows_no_export_while_such_a_link_serves_nothing(
    owner: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    make_client: ClientFactory,
    state: str,
) -> None:
    """A2573 F1: the project view and the list read the same cache as §11.3, and ask the
    stored link, never the forge, whether it serves."""
    ok = timedelta(minutes=12) if state == "stale" else timedelta(minutes=1)
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=ok)
    _confirm(owner)
    _cached_member(migrated)
    if state != "stale":
        with migrated.begin() as conn:
            conn.execute(update(t.forge_link).values(status=state))
    _admin, guest = _readers(owner, make_client, migrated)
    for who in (owner, guest):
        assert who.get(VIEW).json()["keep_the_why_export"] is None
    listed = guest.get("/projects").json()["items"]
    assert not any(item.get("keep_the_why_export") for item in listed)


def test_the_project_view_shows_the_export_while_such_a_link_serves(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    _cached_member(migrated)
    export = owner.get(VIEW).json()["keep_the_why_export"]
    assert export["members"][0]["name"] == "secret-plan"


def test_the_views_refresh_keeps_no_member_of_such_a_link_after_not_admin(
    owner: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2573 F1: the refresh a stale entry schedules reads with a refused reader, and keeps
    none of the members the link read."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    project_id = _cached_member(migrated)
    with migrated.begin() as conn:
        conn.execute(update(t.forge_link).values(status="not_admin"))
    later: list[Any] = []
    monkeypatch.setattr(
        ktw,
        "_refresh_later",
        lambda reader, pid, url, _s: ktw._refresh_in_background(reader, pid, url, later.append),
    )
    with ktw.CACHE.guard:
        ktw.CACHE.entries[project_id].at -= 660
    owner.get(VIEW)
    assert len(later) == 1
    later[0]()  # as the pool would, after the request
    entry = ktw.CACHE.cached(project_id)
    assert entry is not None and entry.snapshot is not None
    assert entry.snapshot.members == []


def test_the_why_cache_is_not_answered_when_the_forge_no_longer_names_the_installation(
    owner: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2573 F2: the forge names no installation for the repository (the App uninstalled, the
    repository out of its selection): the choice never reaches the link and refuses
    `no_grant`, answered by reader, never the export the link read, nor its members as
    `details.last` once the entry is old."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=12))
    _confirm(owner)
    project_id = _cached_member(migrated)
    monkeypatch.setattr(github_app.GitHubApp, "installation_of", lambda _a, _r: None)
    no_grant = (409, "probe_not_configured", {"reason": "no_grant"})
    assert _error(owner.get(WHY)) == no_grant
    with ktw.CACHE.guard:
        ktw.CACHE.entries[project_id].at -= 660
    assert _error(owner.get(WHY)) == no_grant


def test_the_probe_cache_is_answered_to_no_reader_after_the_link_is_unlinked(
    owner: flow.Human,
    app: FakeApp,
    repo: FakeForge,
    migrated: Engine,
    make_client: ClientFactory,
) -> None:
    """A2573 F3, for a guest too: the mapping, never the observation."""
    link_id = _org_link(migrated, owner.id, checked=timedelta(minutes=1), ok=timedelta(minutes=1))
    _confirm(owner)
    _operators(owner)
    assert owner.get(PROBE).status_code == 200
    assert owner.delete(f"/me/forge/github/links/{link_id}").status_code == 204
    _admin, guest = _readers(owner, make_client, migrated)
    _operators(guest)
    assert _error(guest.get(PROBE)) == (409, "probe_not_configured", {})


def test_step_one_on_another_account_changes_neither_status_nor_login(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """A2574 P3-4: the account check comes before the suspension, and keeps the login."""
    _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    _confirm(owner)
    app.account_id, app.login, app.installation_state = 901, "other-org", "suspended"
    assert _check(migrated, app) == "active"
    assert _link_row(migrated).account_login == "acme"
    assert _records(migrated, owner.id) == []


# --- review A2545 #4: an answer of no shape is never a "no" ---------------------------------------


def test_linking_compares_the_membership_with_the_linking_users_id(
    owner: flow.Human, app: FakeApp, migrated: Engine
) -> None:
    app.own[42] = owner_of(99)  # the user's own membership names another user
    assert _error(_json_setup(owner)) == (403, "forbidden", {"reason": "not_organisation_admin"})
    with migrated.connect() as conn:
        assert conn.execute(select(t.forge_link)).first() is None


def test_an_installation_now_on_another_account_is_no_answer(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """Step 1 names another account than the link's: no status changes, no membership read,
    and the link's last success stays as it was."""
    _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    _confirm(owner)
    ok_before = _link_row(migrated).owner_ok_at
    app.account_id = 901
    app.memberships[("acme", "maintainer-gh")] = owner_of(42, org_id=901)
    assert _check(migrated, app) == "active"
    row = _link_row(migrated)
    assert row.owner_ok_at == ok_before and not forge_links.serves(row)
    assert not any(call.startswith("membership:") for call in app.calls)


@pytest.mark.parametrize(
    ("account_id", "user_id"), [(None, None), (True, None), (ORG_ID, True), ("900", 42)]
)
def test_an_owner_check_with_no_id_to_compare_is_no_answer(account_id: Any, user_id: Any) -> None:
    with pytest.raises(forge.ForgeUnavailableError):
        forge_links.is_owner(owner_of(42, org_id=account_id), account_id, user_id)
    with pytest.raises(forge.ForgeUnavailableError):
        forge_links.is_owner(None, account_id, user_id)


# --- replacing another owner's link -----------------------------------------------------------


@pytest.fixture
def anna(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated, "anna")


def _anna_links(anna: flow.Human) -> Any:
    return link_setup(anna, INSTALLATION, start(anna), "anna")


@pytest.mark.parametrize(
    ("status", "records"),
    [
        ("active", ["not_admin", "unlinked"]),
        ("suspended", ["not_admin", "unlinked"]),
        ("not_admin", ["unlinked"]),  # it had its record then
    ],
)
def test_another_owner_replaces_a_link_whose_check_says_no_owner(
    owner: flow.Human,
    anna: flow.Human,
    app: FakeApp,
    migrated: Engine,
    status: str,
    records: list[str],
) -> None:
    """However recent the existing link's last check: checked at once."""
    _org_link(migrated, owner.id, status=status, checked=timedelta(0), ok=timedelta(0))
    app.memberships[("acme", "maintainer-gh")] = owner_of(42, role="member")
    assert _anna_links(anna) == DONE
    assert "membership:acme/maintainer-gh" in app.calls
    assert _records(migrated, owner.id) == records  # in that order
    assert _records(migrated, anna.id) == ["linked"]
    row = _link_row(migrated)
    assert (row.human_id, row.forge_user_id, row.status) == (anna.id, 43, "active")
    assert owner.get("/me/forge").json()["links"] == []


def test_a_replacements_first_check_counts_from_the_membership_read_not_after_the_other_check(
    owner: flow.Human, anna: flow.Human, app: FakeApp, migrated: Engine, held_clock: HeldClock
) -> None:
    """Review A2544 P2-1: the existing link's owner check runs between the new owner's
    membership read and the write of the new link; it takes 4 minutes here, and the new link's
    first success still counts from before the read."""
    _org_link(migrated, owner.id, checked=timedelta(0), ok=timedelta(0))
    app.memberships[("acme", "maintainer-gh")] = owner_of(42, role="member")
    made = _own_read_takes(app, held_clock, timedelta(seconds=1))
    app.during_check = lambda: held_clock.advance(timedelta(minutes=4))
    assert _anna_links(anna) == DONE
    [read] = made
    row = _link_row(migrated)
    assert (row.human_id, row.status) == (anna.id, "active")
    assert row.owner_ok_at == row.checked_at <= read
    assert row.linked_at - row.owner_ok_at >= timedelta(minutes=4)
    assert not forge_links.serves(row, read + TEN)


def test_a_removed_link_is_replaced_with_no_check(
    owner: flow.Human, anna: flow.Human, app: FakeApp, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, status="removed")
    assert _anna_links(anna) == DONE
    assert "user:42" not in app.calls
    assert _records(migrated, owner.id) == ["unlinked"]
    assert _link_row(migrated).human_id == anna.id


def test_a_check_that_succeeds_refuses_the_replacement_and_counts_as_the_check(
    owner: flow.Human, anna: flow.Human, app: FakeApp, migrated: Engine
) -> None:
    _org_link(migrated, owner.id, checked=timedelta(minutes=5), ok=timedelta(minutes=5))
    before = _link_row(migrated)
    assert _anna_links(anna) == DONE + "?error=installation_linked"
    row = _link_row(migrated)
    assert row.human_id == owner.id
    assert row.checked_at > before.checked_at and row.owner_ok_at > before.owner_ok_at
    assert _records(migrated, owner.id) == [] and _records(migrated, anna.id) == []
    answer = _json_setup(anna, "anna")
    assert _error(answer) == (409, "conflict", {"reason": "installation_linked"})


@pytest.mark.parametrize(
    "unanswered",
    [
        {"membership": forge.ForgeUnavailableError("the forge answered 403", 403)},
        {"membership": forge.ForgeUnavailableError("timeout")},
    ],
)
def test_a_check_without_an_answer_refuses_the_replacement_and_changes_nothing(
    owner: flow.Human,
    anna: flow.Human,
    app: FakeApp,
    migrated: Engine,
    unanswered: dict[str, Any],
) -> None:
    _org_link(migrated, owner.id, checked=timedelta(minutes=5), ok=timedelta(minutes=5))
    before = _link_row(migrated)
    app.memberships[("acme", "maintainer-gh")] = unanswered["membership"]
    assert _anna_links(anna) == DONE + "?error=forge_unavailable"
    assert _link_row(migrated) == before  # its `checked_at` included
    assert _records(migrated, owner.id) == [] and _records(migrated, anna.id) == []


def test_a_link_that_changes_during_the_replacements_check_is_forge_unavailable(
    owner: flow.Human, anna: flow.Human, app: FakeApp, migrated: Engine
) -> None:
    """The lead's ruling Q2 (seq 214797): no retry, nothing written."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=5), ok=timedelta(minutes=5))
    app.memberships[("acme", "maintainer-gh")] = None  # the check would say "no owner"

    def meanwhile() -> None:
        with migrated.begin() as conn:
            conn.execute(update(t.forge_link).values(status="suspended"))

    app.during_check = meanwhile
    assert _anna_links(anna) == DONE + "?error=forge_unavailable"
    row = _link_row(migrated)
    assert (row.human_id, row.status) == (owner.id, "suspended")
    assert _records(migrated, owner.id) == [] and _records(migrated, anna.id) == []
    assert app.calls.count("membership:acme/maintainer-gh") == 1  # no retry


@pytest.mark.parametrize(
    "change",
    [
        "unlinked",  # its human unlinked it, or their account went
        "removed",  # the forge reported it removed
        "linked_by_the_caller",  # the caller's own link of it, by another request, won
    ],
)
def test_any_change_of_the_link_during_the_replacements_check_is_forge_unavailable(
    owner: flow.Human, anna: flow.Human, app: FakeApp, migrated: Engine, change: str
) -> None:
    """Review A2545 #1: the replacement's link is compared before anything else, so no change
    of it lets the new link through on a check that did not decide it (Q2, seq 214797)."""
    _org_link(migrated, owner.id, checked=timedelta(minutes=5), ok=timedelta(minutes=5))
    app.memberships[("acme", "maintainer-gh")] = None  # the check would say "no owner"

    def meanwhile() -> None:
        with migrated.begin() as conn:
            if change == "unlinked":
                conn.execute(t.forge_link.delete())
            elif change == "removed":
                conn.execute(update(t.forge_link).values(status="removed"))
            else:
                conn.execute(update(t.forge_link).values(human_id=anna.id, forge_user_id=43))

    app.during_check = meanwhile
    with migrated.connect() as conn:
        before = list(conn.execute(select(t.forge_link)))
    assert _anna_links(anna) == DONE + "?error=forge_unavailable"
    with migrated.connect() as conn:
        after = list(conn.execute(select(t.forge_link)))
    assert len(after) == (0 if change == "unlinked" else 1)
    if after:
        assert after[0].id == before[0].id  # the row as `meanwhile` left it, not a new link
    assert _records(migrated, owner.id) == [] and _records(migrated, anna.id) == []


def _caller_ends(engine: Engine, project_id: str, how: str) -> tuple[Any, Any]:
    """A calling request's binding and what ends it during the owner check: a human the guard
    checks who is deleted or suspended meanwhile, or a bridged call whose connection is gone."""
    caller = factory.human(engine, "carol")

    def bind() -> None:
        if how == "bridge":
            write_guard.bind_bridge(project_id, "brg-ended")
        else:
            write_guard.bind(caller)

    def end() -> None:
        if how == "bridge":
            return  # no such connection: `bridges.still_live` refuses it
        column = "deleted_at" if how == "deleted" else "suspended_at"
        with engine.begin() as conn:
            conn.execute(
                update(t.human).where(t.human.c.id == caller).values({column: clock.now()})
            )

    return bind, end


@pytest.mark.parametrize("how", ["deleted", "suspended", "bridge"])
def test_a_definite_no_is_written_whatever_becomes_of_the_calling_request(
    owner: flow.Human, app: FakeApp, migrated: Engine, how: str
) -> None:
    """Review A2545 #2: the check's write is the link human's, not the caller's; a caller that
    ends while the check runs, after the claim moved `checked_at`, must not drop it."""
    _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    bind, end = _caller_ends(migrated, _project_id(migrated), how)
    app.memberships[("acme", "maintainer-gh")] = None
    app.during_check = end

    def as_the_caller() -> Any:
        bind()
        return forge_links.refresh(migrated, APP, _link_row(migrated))

    row = contextvars.copy_context().run(as_the_caller)
    assert row.status == "not_admin"
    assert _records(migrated, owner.id) == ["not_admin"]


@pytest.mark.parametrize("how", ["deleted", "suspended", "bridge"])
def test_a_refused_mint_is_written_whatever_becomes_of_the_calling_request(
    owner: flow.Human, migrated: Engine, how: str
) -> None:
    """`ForgeAccess._gone`, as `refresh` (A2545 #2)."""
    _org_link(migrated, owner.id)
    bind, end = _caller_ends(migrated, _project_id(migrated), how)

    def as_the_caller() -> None:
        bind()
        end()
        _access(migrated)._gone(forge_links.Link.of(_link_row(migrated)), "suspended")

    contextvars.copy_context().run(as_the_caller)
    assert _link_row(migrated).status == "suspended"


def test_a_replacement_drops_the_tokens_and_its_check_keeps_none(
    owner: flow.Human, anna: flow.Human, app: FakeApp, migrated: Engine
) -> None:
    """Review A2545 #7: the existing link served, so its own reads keep their token; the
    replacement's check mints one for itself alone, and the replacement drops what is held."""
    _org_link(migrated, owner.id)
    github_app._tokens[(APP.app_id, INSTALLATION)] = ("held", 2**40)
    app.memberships[("acme", "maintainer-gh")] = None
    assert _anna_links(anna) == DONE
    assert app.kept == [False]
    assert (APP.app_id, INSTALLATION) not in github_app._tokens


def test_a_replacements_unlinked_record_names_the_login_its_check_read(
    owner: flow.Human, anna: flow.Human, app: FakeApp, migrated: Engine
) -> None:
    _org_link(migrated, owner.id)
    app.login = "acme-renamed"
    app.memberships[("acme-renamed", "maintainer-gh")] = None
    assert _anna_links(anna) == DONE
    with migrated.connect() as conn:
        logins = conn.execute(
            select(t.account_record.c.data)
            .where(
                t.account_record.c.human_id == owner.id,
                t.account_record.c.type == "forge_access_changed",
            )
            .order_by(t.account_record.c.n)
        ).scalars()
        assert [(d["change"], d["login"]) for d in logins] == [
            ("not_admin", "acme-renamed"),
            ("unlinked", "acme-renamed"),
        ]


def test_a_check_overtaken_by_a_newer_one_writes_nothing(
    owner: flow.Human, app: FakeApp, migrated: Engine
) -> None:
    """Review A2545 #8: a replacement's check that kept the link, or a relink of its human,
    wrote a newer `checked_at` while this one ran: this one's "no" is not written over it, and
    no token is dropped for it."""
    _org_link(migrated, owner.id, checked=TEN, ok=TEN)
    app.memberships[("acme", "maintainer-gh")] = None
    github_app._tokens[(APP.app_id, INSTALLATION)] = ("held", 2**40)

    def newer() -> None:
        later = clock.now() + timedelta(seconds=1)
        with migrated.begin() as conn:
            conn.execute(update(t.forge_link).values(checked_at=later, owner_ok_at=later))

    app.during_check = newer
    row = forge_links.refresh(migrated, APP, _link_row(migrated))
    assert row is not None and row.status == "active" and _records(migrated, owner.id) == []
    assert (APP.app_id, INSTALLATION) in github_app._tokens


def test_a_relink_locks_the_callers_own_link(
    owner: flow.Human, app: FakeApp, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review A2545 #10: the caller's own link is read under its row lock too, so a concurrent
    relink or replacement waits for this one."""
    assert _json_setup(owner).status_code == 200
    locks: list[bool] = []
    existing = forge_links._existing

    def spied(conn: Any, installation_id: int, lock: bool = False) -> Any:
        locks.append(lock)
        return existing(conn, installation_id, lock)

    monkeypatch.setattr(forge_links, "_existing", spied)
    assert _json_setup(owner).status_code == 200
    assert locks == [False, True]


def test_a_relink_of_a_link_gone_meanwhile_is_forge_unavailable(
    owner: flow.Human, app: FakeApp, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    gone = forge_links.Link(
        "fgl-gone", owner.id, INSTALLATION, "active", "Organization", ORG_ID, "acme", 42,
        clock.now(), clock.now(),
    )  # fmt: skip
    monkeypatch.setattr(forge_links, "_existing", lambda conn, iid, lock=False: gone)
    assert _error(_json_setup(owner)) == (503, "forge_unavailable", {})
    assert _records(migrated, owner.id) == []


def test_a_first_link_that_loses_to_another_is_forge_unavailable(
    owner: flow.Human,
    anna: flow.Human,
    app: FakeApp,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two first links of one installation at once: the one whose insert meets the other's
    committed row answers `forge_unavailable` (the human links again), never a 500, and never
    `installation_linked`, which it could not tell from the caller's own."""
    _org_link(migrated, owner.id)  # the other request's link, committed after this one read
    monkeypatch.setattr(forge_links, "_existing", lambda conn, iid, lock=False: None)
    assert _error(_json_setup(anna, "anna")) == (503, "forge_unavailable", {})
    assert _link_row(migrated).human_id == owner.id
    assert _records(migrated, anna.id) == []


def test_a_removed_link_keeps_its_choice_no_longer_than_any_other(
    owner: flow.Human, app: FakeApp, repo: FakeForge, migrated: Engine
) -> None:
    """Review A2545 #9 (its second part): a `removed` link is never checked again, so the
    choice that rests on it has no check to end with."""
    _org_link(migrated, owner.id, status="removed")
    _confirm(owner)
    access = _access(migrated)
    forge.Forge(OPERATOR, access=access).for_project(_project_id(migrated))
    assert access._chosen[_project_id(migrated)][3] is None


def test_a_former_owner_cannot_take_the_link_back_while_the_new_owner_passes(
    owner: flow.Human, anna: flow.Human, app: FakeApp, migrated: Engine
) -> None:
    _org_link(migrated, owner.id)
    app.memberships[("acme", "maintainer-gh")] = None
    assert _anna_links(anna) == DONE
    app.memberships[("acme", "maintainer-gh")] = owner_of(42)  # an owner again
    assert link_setup(owner, INSTALLATION, start(owner)) == DONE + "?error=installation_linked"
    assert _link_row(migrated).human_id == anna.id


def test_a_replacement_of_a_link_on_a_user_account_stays_refused(
    owner: flow.Human, anna: flow.Human, app: FakeApp, migrated: Engine
) -> None:
    """Only an installation on a forge organisation is replaced; on a user account the one
    human at a time holds as before (installation_linked, no check)."""
    found = {
        "id": 8,
        "account": {"id": 42, "login": "maintainer-gh", "type": "User"},
        "repository_selection": "all",
        "suspended": False,
    }
    with migrated.begin() as conn:
        forge_links.link(conn, owner.id, found)
    with migrated.begin() as conn, pytest.raises(forge_links.LinkError) as raised:
        forge_links.link(conn, anna.id, {**found})
    assert raised.value.reason == "installation_linked"


# --- the App's own reads, against a fake opener -------------------------------------------------


class FakeOpener:
    def __init__(self) -> None:
        self.answers: dict[str, Any] = {}
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout: float) -> Any:
        self.requests.append(request)
        answer = self.answers.get(request.full_url.split("?")[0])
        if isinstance(answer, int):
            raise urllib.error.HTTPError(request.full_url, answer, "error", {}, None)  # type: ignore[arg-type]
        if answer is None:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return io.BytesIO(json.dumps(answer).encode())


@pytest.fixture
def opener(monkeypatch: pytest.MonkeyPatch) -> FakeOpener:
    fake = FakeOpener()
    monkeypatch.setattr(forge, "_opener", fake)
    return fake


API = "https://api.github.com"
EXCHANGE = "https://github.com/login/oauth/access_token"
MEMBERSHIP = {
    "state": "active",
    "role": "admin",
    "organization": {"id": ORG_ID, "login": "acme"},
    "user": {"id": 42, "login": "maintainer-gh"},
}


def test_the_users_own_membership_is_read_with_the_user_token(opener: FakeOpener) -> None:
    opener.answers[EXCHANGE] = {"access_token": "gho_user"}
    opener.answers[f"{API}/user"] = {"id": 42, "login": "maintainer-gh"}
    opener.answers[f"{API}/user/memberships/orgs/acme"] = MEMBERSHIP
    found = APP.user_of_code("c0de", "acme")
    assert found["membership"] == owner_of(42)
    read = opener.requests[-1]
    assert dict(read.header_items())["Authorization"] == "Bearer gho_user"
    opener.answers[f"{API}/user/memberships/orgs/acme"] = None
    assert APP.user_of_code("c0de", "acme")["membership"] is None  # a 404: a definite "no"
    opener.answers[f"{API}/user/memberships/orgs/acme"] = 403
    with pytest.raises(forge.ForgeUnavailableError):  # a refusal: no answer
        APP.user_of_code("c0de", "acme")


def test_the_owner_checks_reads_use_the_installation_token(opener: FakeOpener) -> None:
    opener.answers[f"{API}/user/42"] = {"id": 42, "login": "maintainer-gh"}
    opener.answers[f"{API}/orgs/acme/memberships/maintainer-gh"] = MEMBERSHIP
    assert APP.user_login("ghs_inst", 42) == "maintainer-gh"
    assert APP.org_membership("ghs_inst", "acme", "maintainer-gh") == owner_of(42)
    assert all(
        dict(r.header_items())["Authorization"] == "Bearer ghs_inst" for r in opener.requests
    )
    opener.answers[f"{API}/user/42"] = None
    assert APP.user_login("ghs_inst", 42) is None
    opener.answers[f"{API}/orgs/acme/memberships/maintainer-gh"] = {"state": "active"}
    with pytest.raises(forge.ForgeUnavailableError):  # no shape: no answer, never a "no"
        APP.org_membership("ghs_inst", "acme", "maintainer-gh")


def test_an_unkept_mint_is_neither_taken_from_nor_put_into_the_held_tokens(
    opener: FakeOpener, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(github_app, "_tokens", {})
    monkeypatch.setattr(github_app.GitHubApp, "jwt", lambda self, now=None: "jwt")
    opener.answers[f"{API}/app/installations/7/access_tokens"] = {
        "token": "ghs_new",
        "expires_at": "2999-01-01T00:00:00Z",
    }
    github_app._tokens[("1", 7)] = ("ghs_held", 2**40)
    assert APP.token(7, keep=False) == "ghs_new"
    assert github_app._tokens[("1", 7)] == ("ghs_held", 2**40)
    del github_app._tokens[("1", 7)]
    APP.token(7, keep=False)
    assert ("1", 7) not in github_app._tokens


INSTALLATION_ANSWER = {
    "id": 7,
    "account": {"id": ORG_ID, "login": "acme", "type": "Organization"},
    "repository_selection": "all",
    "suspended_at": None,
}


def _without(answer: dict[str, Any], where: str, key: str, value: Any = ...) -> dict[str, Any]:
    """The answer with `key` of its part `where` ("" for the top) set to `value`, or gone."""
    changed: dict[str, Any] = json.loads(json.dumps(answer))
    part = changed[where] if where else changed
    if value is ...:
        part.pop(key)
    else:
        part[key] = value
    return changed


@pytest.mark.parametrize(
    ("where", "key", "value"),
    [
        ("", "id", ...),
        ("", "id", True),
        ("account", "id", ...),
        ("account", "id", None),
        ("account", "id", True),
        ("account", "login", ...),
        ("account", "login", ""),
        ("account", "type", ...),
        ("account", "type", ""),
    ],
)
def test_an_installation_of_no_shape_is_no_answer(
    opener: FakeOpener, monkeypatch: pytest.MonkeyPatch, where: str, key: str, value: Any
) -> None:
    """Review A2545 #4: two missing account ids would match, an organisation without a login
    would read as another kind of account; neither is an answer."""
    monkeypatch.setattr(github_app.GitHubApp, "jwt", lambda self, now=None: "jwt")
    opener.answers[f"{API}/app/installations/7"] = INSTALLATION_ANSWER
    assert APP.installation(7) is not None
    opener.answers[f"{API}/app/installations/7"] = _without(INSTALLATION_ANSWER, where, key, value)
    with pytest.raises(forge.ForgeUnavailableError):
        APP.installation(7)


def test_a_repositorys_installation_of_no_shape_is_no_answer(
    opener: FakeOpener, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(github_app.GitHubApp, "jwt", lambda self, now=None: "jwt")
    opener.answers[f"{API}/repos/{REPO}/installation"] = {"id": 7}
    assert APP.installation_of(REPO) == 7
    opener.answers[f"{API}/repos/{REPO}/installation"] = {"id": True}
    with pytest.raises(forge.ForgeUnavailableError):
        APP.installation_of(REPO)


@pytest.mark.parametrize(
    ("where", "key", "value"),
    [
        ("", "role", ...),
        ("", "role", ""),
        ("", "state", ""),
        ("organization", "id", ...),
        ("organization", "id", True),
        ("user", "id", ...),
        ("user", "id", None),
        ("", "user", ...),
    ],
)
def test_a_membership_of_no_shape_is_no_answer(
    opener: FakeOpener, where: str, key: str, value: Any
) -> None:
    """A missing `role` or id would make a "no" (`not_admin`) of an answer that says nothing."""
    path = f"{API}/orgs/acme/memberships/maintainer-gh"
    opener.answers[path] = _without(MEMBERSHIP, where, key, value)
    with pytest.raises(forge.ForgeUnavailableError):
        APP.org_membership("ghs_inst", "acme", "maintainer-gh")


@pytest.mark.parametrize(
    "user", [{"id": True, "login": "maintainer-gh"}, {"id": 42, "login": ""}, {"id": 42}]
)
def test_a_user_of_no_shape_is_no_answer(opener: FakeOpener, user: dict[str, Any]) -> None:
    """At linking (the user token's `GET /user`) and at step 2 (`GET /user/{id}`): an empty login
    would cut the membership's path short, and its `404` would read as a "no"."""
    opener.answers[EXCHANGE] = {"access_token": "gho_user"}
    opener.answers[f"{API}/user"] = user
    with pytest.raises(forge.ForgeUnavailableError):
        APP.user_of_code("c0de", "acme")
    if user.get("login") != "maintainer-gh":  # step 2 reads the login alone
        opener.answers[f"{API}/user/42"] = user
        with pytest.raises(forge.ForgeUnavailableError):
            APP.user_login("ghs_inst", 42)
