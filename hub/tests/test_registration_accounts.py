"""docs/api.md §2.7.1 step 6, §2.7.5, §16.4: completing a pending registration, the
pending account and its restricted sessions, and the instance admin's decision."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, events, paths, registration, registration_accounts, registration_mail
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.routes import registration as routes
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_registration import MAIL, PASSWORD, SIGNING, hub, pending

ADMIN = "/admin/registrations"
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for limiter in (
        routes.BY_SOURCE,
        routes.BY_PAIR_SHORT,
        routes.BY_PAIR_DAY,
        routes.BY_ADDRESS_DAY,
    ):
        limiter._hits.clear()
    registration.BREAKER._at.clear()
    registration.BREAKER._open_until = 0.0
    monkeypatch.setattr(registration_mail, "send", lambda conn, **kwargs: None)
    yield


@pytest.fixture
def claims(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The verified-address store (#280) as a dict: one address, one account."""
    held: dict[str, str] = {}

    def claim(conn: Any, normalized: str, human_id: str, *, secret_key: bytes | None) -> bool:
        if normalized in held:
            return False
        held[normalized] = human_id
        return True

    monkeypatch.setattr(registration_accounts, "claim_address", claim)
    return held


def settings_for(**env: str) -> Settings:
    return hub(MAITY_MAIL_SIGNING_KEY=SIGNING, MAITY_REGISTRATION="open", **MAIL, **env)


@pytest.fixture
def admin(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)  # the first human: the instance admin


def requested(
    make_client: ClientFactory,
    engine: Engine,
    settings: Settings,
    address: str = "ada@example.com",
    peer: str = "203.0.113.7",
) -> Any:
    """A pending registration, made the way §2.7.1 makes one."""
    client = make_client(peer=peer, mail=settings.mail, registration=settings.registration)
    answer = client.post("/api/v1/auth/register", json={"address": address, "password": PASSWORD})
    assert answer.status_code == 202, answer.text
    return [r for r in pending(engine) if r.address == address][-1]


def complete(engine: Engine, settings: Settings, pending_id: str, **given: Any) -> Any:
    body = {
        "password": PASSWORD,
        "handle": "ada",
        "display_name": "Ada",
        "terms_seen": None,
        "terms_accepted": False,
        "source": "203.0.113.7",
        "secret_key": settings.secret_key,
        **given,
    }
    with engine.begin() as conn:
        return registration_accounts.complete(conn, resolver(settings), pending_id, **body)


def resolver(settings: Settings) -> Any:
    return lambda conn: routes._resolved(conn, settings)


def human(engine: Engine, human_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.human).where(t.human.c.id == human_id)).first()


def signed_in(make_client: ClientFactory, done: Any) -> flow.Human:
    """The browser the completion signed in (§2.7.1), as the link page will set it."""
    client = make_client()
    client.cookies.set("maity_session", done.session_id)
    return flow.Human(client, done.csrf, done.human_id)


# --- completion -------------------------------------------------------------------------


def test_completion_makes_an_active_account_and_signs_it_in(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    settings = settings_for(MAITY_REGISTRATION_APPROVAL="automatic")
    other = requested(make_client, migrated, settings, peer="198.51.100.4")  # another source
    row = requested(make_client, migrated, settings)
    done = complete(migrated, settings, row.id)
    assert (done.kind, done.account_status, done.next) == ("created", "active", "/")
    made = human(migrated, done.human_id)
    assert (made.handle, made.display_name, made.account_status) == ("ada", "Ada", "active")
    assert made.registered_at is not None and made.password_hash == row.password_hash
    assert claims == {"ada@example.com": done.human_id}
    assert all(r.voided_at is not None for r in pending(migrated) if r.id in (row.id, other.id))
    person = signed_in(make_client, done)
    me = person.get("/me").json()["member"]
    assert (me["id"], me["account_status"], me["terms"]) == (done.human_id, "active", None)
    assert complete(migrated, settings, row.id).kind == "gone"  # used: as if it never was


def test_the_account_holds_its_address_as_verified(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The completion writes the address through the notification settings' store
    (§18.4), not through a stand-in."""
    from maity_hub.notifications import preferences

    settings = settings_for(MAITY_REGISTRATION_APPROVAL="automatic")
    row = requested(make_client, migrated, settings)
    done = complete(migrated, settings, row.id)
    assert done.kind == "created"
    with migrated.begin() as conn:
        view = preferences.view(conn, done.human_id, True)["email"]
        assert preferences.has_verified_address(conn, "ada@example.com") is True
    assert (view["address"], view["address_status"]) == ("ada@example.com", "verified")


def test_a_taken_address_makes_no_account(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub.notifications import preferences

    settings = settings_for(MAITY_REGISTRATION_APPROVAL="automatic")
    row = requested(make_client, migrated, settings)
    holder = flow.human(make_client, migrated, "holder")
    with migrated.begin() as conn:
        assert preferences.claim_verified(conn, "ada@example.com", holder.id, secret_key=None)
    assert complete(migrated, settings, row.id).kind == "gone"
    with migrated.connect() as conn:
        assert conn.execute(select(t.human).where(t.human.c.handle == "ada")).first() is None
    assert pending(migrated)[0].voided_at is not None


def test_a_second_account_never_gets_the_same_address(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    settings = settings_for(MAITY_REGISTRATION_APPROVAL="automatic")
    claims["ada@example.com"] = "hum-someone"  # verified on an account meanwhile
    row = requested(make_client, migrated, settings)
    assert complete(migrated, settings, row.id).kind == "gone"


def test_the_admission_is_checked_again_at_completion(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    opened = settings_for()
    row = requested(make_client, migrated, opened)
    closed = hub(MAITY_MAIL_SIGNING_KEY=SIGNING, **MAIL)  # the mode changed since the mail
    assert complete(migrated, closed, row.id).kind == "closed"
    assert pending(migrated)[0].voided_at is not None
    blocked = requested(make_client, migrated, opened, "bob@example.com")
    with migrated.begin() as conn:
        registration_accounts.block(conn, "bob@example.com", clock.now() + timedelta(days=1))
    assert complete(migrated, opened, blocked.id, handle="bob").kind == "closed"
    assert claims == {}


def test_an_invitation_that_stops_admitting_ends_the_registration(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    """§3.4: under `closed` the admitting invitation is read again at completion."""
    flow.project(admin)
    closed = hub(MAITY_MAIL_SIGNING_KEY=SIGNING, **MAIL)
    invited = admin.post(
        "/projects/maintainer/maity/invitations", {"address": "ada@example.com"}
    ).json()
    row = requested(make_client, migrated, closed)
    admin.delete(f"/projects/maintainer/maity/invitations/{invited['id']}")
    assert complete(migrated, closed, row.id).kind == "closed"
    again = admin.post("/projects/maintainer/maity/invitations", {"address": "ada@example.com"})
    assert again.status_code == 201
    second = requested(make_client, migrated, closed)
    assert complete(migrated, closed, second.id).kind == "created"


def test_five_wrong_passwords_void_it(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    settings = settings_for()
    row = requested(make_client, migrated, settings)
    kinds = [
        complete(migrated, settings, row.id, password="wrong password!").kind for _ in range(5)
    ]
    assert kinds == ["wrong_password"] * 5
    assert complete(migrated, settings, row.id).kind == "gone"


def test_the_names_and_the_terms(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    settings = settings_for(
        MAITY_TERMS_URL="https://example.com/terms",
        MAITY_TERMS_VERSION="2026-10",
        MAITY_REGISTRATION_APPROVAL="automatic",
    )
    row = requested(make_client, migrated, settings)
    taken = complete(migrated, settings, row.id, handle="maintainer", terms_seen="2026-10")
    assert (taken.kind, taken.fields) == ("invalid", {"handle": "taken", "terms": "required"})
    bad = complete(migrated, settings, row.id, handle="A", display_name="", terms_seen="2026-10")
    assert bad.fields == {"handle": "invalid", "display_name": "invalid", "terms": "required"}
    changed = complete(migrated, settings, row.id, terms_seen="2026-09", terms_accepted=True)
    assert changed.kind == "terms_changed" and claims == {}
    # Terms set while the page was open (it showed none): the version asks first, ahead of
    # what the form got wrong.
    newly = complete(migrated, settings, row.id, handle="A", terms_seen=None)
    assert newly.kind == "terms_changed" and claims == {}
    done = complete(migrated, settings, row.id, terms_seen="2026-10", terms_accepted=True)
    made = human(migrated, done.human_id)
    assert made.terms_version == "2026-10" and made.terms_accepted_at is not None


def test_the_hourly_cap_keeps_the_pending_registration(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    settings = settings_for(MAITY_REGISTRATION_MAX_NEW_PER_HOUR="1")
    first = requested(make_client, migrated, settings)
    assert complete(migrated, settings, first.id).kind == "created"
    second = requested(make_client, migrated, settings, "bob@example.com")
    assert complete(migrated, settings, second.id, handle="bob").kind == "later"
    assert [r.voided_at for r in pending(migrated) if r.id == second.id] == [None]


def test_two_completions_at_once_create_one_account(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    """Two links of one address completed at once: the second waits for the address's
    lock and then finds its link voided. SQLite serialises every writer anyway, so
    this runs on PostgreSQL and MariaDB; released before the worker is joined."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises writers; the lock is for the server databases")
    settings = settings_for(MAITY_REGISTRATION_APPROVAL="automatic")
    one = requested(make_client, migrated, settings)
    two = requested(make_client, migrated, settings, peer="198.51.100.4")  # both stay usable
    first, second = migrated.connect(), migrated.connect()
    started, finished = threading.Event(), threading.Event()

    def other() -> str:
        with second.begin():
            started.set()
            done = registration_accounts.complete(
                second, resolver(settings), two.id, password=PASSWORD, handle="ada2",
                display_name="Ada", terms_seen=None, terms_accepted=False, source="203.0.113.8",
                secret_key=settings.secret_key,
            )  # fmt: skip
            finished.set()
            return str(done.kind)

    pool = ThreadPoolExecutor(max_workers=1)
    first_tx = first.begin()
    try:
        done = registration_accounts.complete(
            first, resolver(settings), one.id, password=PASSWORD, handle="ada", display_name="Ada",
            terms_seen=None, terms_accepted=False, source="203.0.113.7",
            secret_key=settings.secret_key,
        )  # fmt: skip
        assert done.kind == "created"
        waiting = pool.submit(other)
        assert started.wait(timeout=10)
        assert not finished.wait(timeout=0.5)  # held by the first
        first_tx.commit()
        assert waiting.result(timeout=10) == "gone"
    finally:
        if first_tx.is_active:
            first_tx.rollback()
        first.close()
        pool.shutdown(wait=True, cancel_futures=True)
        second.close()


def test_nobody_registers_before_the_operators_account_exists(
    make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    """The earliest human is the instance admin (§16): a registration must never be it."""
    settings = settings_for(MAITY_REGISTRATION_APPROVAL="automatic")
    row = requested(make_client, migrated, settings)
    assert complete(migrated, settings, row.id).kind == "closed" and claims == {}


def test_the_next_path_follows_the_dashboard_rule(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    """§2.6.5: anything but a dashboard path becomes `/`, silently."""
    for bad in (
        "https://evil.example/",
        "/\t//evil.example",
        "/a//b",
        "/x#y",
        "/a b",
        "/api/v1/me",
    ):
        assert paths.safe_next(bad) == "/", bad
    assert paths.safe_next("/maintainer/maity/board") == "/maintainer/maity/board"
    settings = settings_for(MAITY_REGISTRATION_APPROVAL="automatic")
    client = make_client(mail=settings.mail, registration=settings.registration)
    answer = client.post(
        "/api/v1/auth/register",
        json={"address": "ada@example.com", "password": PASSWORD, "next": "/\t//evil.example"},
    )
    assert answer.status_code == 202
    [row] = pending(migrated)
    assert row.next == "/"
    with migrated.begin() as conn:  # a value stored before the rule tightened
        conn.execute(update(t.pending_registration).values(next="//evil.example"))
    assert complete(migrated, settings, row.id).next == "/"


def test_a_handle_taken_at_the_last_moment_is_the_pages_error(
    admin: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    claims: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check and the insert race (§2.7.4): the unique handle decides, never a 500."""
    settings = settings_for(MAITY_REGISTRATION_APPROVAL="automatic")
    row = requested(make_client, migrated, settings)
    monkeypatch.setattr(registration_accounts, "check_names", lambda conn, h, d: {})
    taken = complete(migrated, settings, row.id, handle="maintainer")
    assert (taken.kind, taken.fields) == ("invalid", {"handle": "taken"}) and claims == {}
    assert complete(migrated, settings, row.id).kind == "created"  # the link still works


def test_a_revocation_racing_the_completion_waits_for_it(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    """Completion reads the admitting invitation `FOR UPDATE`: a revocation in flight
    holds it, and the completion then sees it revoked. SQLite serialises every writer
    anyway, so this runs on PostgreSQL and MariaDB; released before the worker is joined."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises writers; the lock is for the server databases")
    flow.project(admin)
    closed = hub(MAITY_MAIL_SIGNING_KEY=SIGNING, **MAIL)
    invited = admin.post(
        "/projects/maintainer/maity/invitations", {"address": "ada@example.com"}
    ).json()
    row = requested(make_client, migrated, closed)
    first = migrated.connect()
    started, finished = threading.Event(), threading.Event()

    def completing() -> str:
        started.set()
        kind = str(complete(migrated, closed, row.id).kind)
        finished.set()
        return kind

    pool = ThreadPoolExecutor(max_workers=1)
    first_tx = first.begin()
    try:
        first.execute(
            update(t.invitation)
            .where(t.invitation.c.id == invited["id"])
            .values(revoked_at=clock.now())
        )
        waiting = pool.submit(completing)
        assert started.wait(timeout=10)
        assert not finished.wait(timeout=0.5)  # held by the revocation
        first_tx.commit()
        assert waiting.result(timeout=10) == "closed"
    finally:
        if first_tx.is_active:
            first_tx.rollback()
        first.close()
        pool.shutdown(wait=True, cancel_futures=True)


def _held(migrated: Engine, change: Any, call: Any) -> Any:
    """`change` runs in a transaction that is held while `call` starts and must wait;
    then it commits and `call`'s answer is returned. Released before the join."""
    first = migrated.connect()
    started, answered = threading.Event(), threading.Event()

    def other() -> Any:
        started.set()
        found = call()
        answered.set()
        return found

    pool = ThreadPoolExecutor(max_workers=1)
    first_tx = first.begin()
    try:
        change(first)
        waiting = pool.submit(other)
        assert started.wait(timeout=10)
        assert not answered.wait(timeout=0.5)  # held by the first
        first_tx.commit()
        return waiting.result(timeout=10)
    finally:
        if first_tx.is_active:
            first_tx.rollback()
        first.close()
        pool.shutdown(wait=True, cancel_futures=True)


def _server_only(migrated: Engine) -> None:
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises writers; the locks are for the server databases")


def test_two_addresses_never_both_take_the_last_place_of_the_hour(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    _server_only(migrated)
    settings = settings_for(MAITY_REGISTRATION_MAX_NEW_PER_HOUR="1")
    ada = requested(make_client, migrated, settings)
    bob = requested(make_client, migrated, settings, "bob@example.com", peer="198.51.100.4")

    def first(conn: Any) -> None:
        assert registration_accounts.complete(
            conn, resolver(settings), ada.id, password=PASSWORD, handle="ada",
            display_name="Ada", terms_seen=None, terms_accepted=False, source="203.0.113.7",
            secret_key=settings.secret_key,
        ).kind == "created"  # fmt: skip

    answer = _held(migrated, first, lambda: complete(migrated, settings, bob.id, handle="bob"))
    assert answer.kind == "later"
    assert [r.voided_at for r in pending(migrated) if r.id == bob.id] == [None]  # kept


def _invited_by_admin(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine
) -> tuple[Settings, Any, flow.Human]:
    flow.project(admin)
    issuer = flow.human(make_client, migrated, "an-admin")
    with migrated.connect() as conn:
        project = str(conn.execute(select(t.project.c.id)).scalar_one())
    factory.membership(migrated, project, "admin", human_id=issuer.id)
    made = issuer.post("/projects/maintainer/maity/invitations", {"address": "ada@example.com"})
    assert made.status_code == 201, made.text
    closed = hub(MAITY_MAIL_SIGNING_KEY=SIGNING, **MAIL)
    return closed, requested(make_client, migrated, closed), issuer


def test_a_project_closing_during_completion_ends_the_registration(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    """§2.7.1 step 6: the invitation's project is read under its lock."""
    _server_only(migrated)
    closed, row, _ = _invited_by_admin(admin, make_client, migrated)

    def archive(conn: Any) -> None:
        events.lock_project(conn, project_id(migrated))  # as a state change takes it
        conn.execute(update(t.project).values(state="archived"))

    assert _held(migrated, archive, lambda: complete(migrated, closed, row.id).kind) == "closed"
    assert claims == {}


def test_an_issuer_demoted_during_completion_ends_the_registration(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    _server_only(migrated)
    closed, row, issuer = _invited_by_admin(admin, make_client, migrated)

    def demote(conn: Any) -> None:
        events.lock_project(conn, project_id(migrated))  # as a member change takes it
        conn.execute(
            update(t.membership).where(t.membership.c.human_id == issuer.id).values(trust="member")
        )

    assert _held(migrated, demote, lambda: complete(migrated, closed, row.id).kind) == "closed"
    assert claims == {}


# --- the pending account (§2.7.5) -------------------------------------------------------


def pending_account(
    make_client: ClientFactory,
    engine: Engine,
    address: str = "ada@example.com",
    handle: str = "ada",
) -> tuple[Any, flow.Human]:
    settings = settings_for()  # approval: operator, the default
    row = requested(make_client, engine, settings, address)
    done = complete(engine, settings, row.id, handle=handle, user_agent=FIREFOX)
    assert (done.kind, done.account_status, done.next) == ("created", "pending", "/account/pending")
    return done, signed_in(make_client, done)


def test_a_pending_account_reaches_only_its_own_account(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    flow.project(admin)
    _, person = pending_account(make_client, migrated)
    me = person.get("/me").json()
    assert (me["member"]["account_status"], me["projects"]) == ("pending", [])
    assert person.get("/auth/session").status_code == 200
    listed = person.get("/auth/sessions")  # its own sessions, as §2.7.5 allows (#268)
    assert listed.status_code == 200, listed.text
    assert [(s["method"], s["browser"], s["os"]) for s in listed.json()["items"]] == [
        ("register", "Firefox", "Linux")  # the browser that completed (§2.6.5)
    ]
    for refused in (
        person.get("/projects"),
        person.get("/agents"),
        person.post("/projects", {"slug": "mine", "name": "Mine"}),
        person.get("/projects/maintainer/maity"),
        person.get(ADMIN),
    ):
        assert refused.status_code == 403
        assert refused.json()["error"]["details"] == {"reason": "account_pending"}, refused.text
    assert person.post("/auth/logout").status_code in (200, 204)


def project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(select(t.project.c.id)).scalar_one())


# --- the instance admin's decision (§16.4) ----------------------------------------------


def test_the_admin_lists_and_approves(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    first, person = pending_account(make_client, migrated)
    second, _ = pending_account(make_client, migrated, "bob@example.com", "bob")
    listed = admin.get(ADMIN).json()
    assert [i["id"] for i in listed["items"]] == [first.human_id, second.human_id]
    item = listed["items"][0]
    assert (item["handle"], item["address"], item["source_ip"]) == (
        "ada",
        "ada@example.com",
        "203.0.113.7",
    )
    paged = admin.get(f"{ADMIN}?limit=1").json()
    rest = admin.get(f"{ADMIN}?limit=1&cursor={paged['next_cursor']}").json()
    assert [i["id"] for i in paged["items"] + rest["items"]] == [first.human_id, second.human_id]
    approved = admin.post(f"{ADMIN}/{first.human_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["account_status"] == "active" and approved.json()["handle"] == "ada"
    assert person.get("/projects").status_code == 200  # the same session, now in standing
    late = admin.post(f"{ADMIN}/{first.human_id}/approve")
    assert late.status_code == 409 and late.json()["error"]["details"]["from"] == "active"
    assert [i["id"] for i in admin.get(ADMIN).json()["items"]] == [second.human_id]


def test_a_really_completed_account_is_rejected_with_everything_it_made(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """No `claims` stand-in: the completion claims the address in `notification_settings`
    as it does for real, the account's mail state exists, and the rejection removes all
    of it and frees the address."""
    from maity_hub.mail import outbox

    done, _ = pending_account(make_client, migrated)
    with migrated.begin() as conn:
        held = conn.execute(
            select(t.notification_settings.c.address_normalized).where(
                t.notification_settings.c.human_id == done.human_id
            )
        ).scalar_one()
        assert held == "ada@example.com"
        conn.execute(
            t.notification_mail_state.insert().values(
                human_id=done.human_id, stamp="x", waiting=False
            )
        )
        conn.execute(
            t.mail_item_sent.insert().values(
                human_id=done.human_id, item="e:1", mailed_at=clock.now()
            )
        )
        outbox.enqueue(
            conn, kind="security", to="ada@example.com", subject="s", body="b\n",
            human_id=done.human_id,
        )  # fmt: skip
    rejected = admin.post(f"{ADMIN}/{done.human_id}/reject", {"reason": "No."})
    assert rejected.status_code == 200, rejected.text
    assert human(migrated, done.human_id) is None
    with migrated.connect() as conn:
        for table in (
            t.notification_settings,
            t.notification_mail_state,
            t.mail_item_sent,
            t.mail_outbox,
            t.account_record,
            t.human_session,
        ):
            left = conn.execute(select(table).where(table.c.human_id == done.human_id)).all()
            assert left == [], table.name
        decision = conn.execute(
            select(t.account_registration.c.status).where(
                t.account_registration.c.human_id == done.human_id
            )
        ).scalar_one()
    assert decision == "rejected"


def test_the_admin_rejects_with_a_reason(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    done, person = pending_account(make_client, migrated)
    assert admin.post(f"{ADMIN}/{done.human_id}/reject", {}).status_code == 400
    assert admin.post(f"{ADMIN}/{done.human_id}/reject", {"reason": "x" * 1025}).status_code == 400
    rejected = admin.post(f"{ADMIN}/{done.human_id}/reject", {"reason": "Not a team member."})
    assert rejected.json() == {"id": done.human_id, "status": "rejected"}
    assert human(migrated, done.human_id) is None
    assert person.get("/me").status_code == 401  # its sessions went with it
    with migrated.connect() as conn:
        kept = conn.execute(
            select(t.account_registration).where(t.account_registration.c.human_id == done.human_id)
        ).one()
    assert (kept.reason, kept.address, kept.address_normalized, kept.source_ip) == (
        "Not a team member.",
        None,
        None,
        None,
    )
    with migrated.connect() as conn:
        until = conn.execute(
            select(t.registration_block.c.until).where(
                t.registration_block.c.address_normalized == "ada@example.com"
            )
        ).scalar_one()
    assert until - clock.now() > timedelta(days=29)
    late = admin.post(f"{ADMIN}/{done.human_id}/approve")
    assert late.status_code == 409 and late.json()["error"]["details"]["from"] == "rejected"
    assert admin.post(f"{ADMIN}/hum-unknown/approve").status_code == 404


def test_only_the_instance_admin_decides(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    done, _ = pending_account(make_client, migrated)
    other = flow.human(make_client, migrated, "someone")
    assert other.get(ADMIN).status_code == 403
    assert other.post(f"{ADMIN}/{done.human_id}/approve").status_code == 403


def test_an_undecided_account_goes_after_thirty_days(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    done, _ = pending_account(make_client, migrated)
    with migrated.begin() as conn:
        conn.execute(
            update(t.account_registration).values(expires_at=clock.now() - timedelta(seconds=1))
        )
    worker = registration_accounts.Worker(migrated, settings_for(), interval=0.05)
    worker.start()
    try:
        for _ in range(100):
            if human(migrated, done.human_id) is None:
                break
            threading.Event().wait(0.05)
    finally:
        worker.stop()
    assert human(migrated, done.human_id) is None
    assert admin.get(ADMIN).json()["items"] == []
    late = admin.post(f"{ADMIN}/{done.human_id}/approve")
    assert late.json()["error"]["details"]["from"] == "expired"


def test_a_waiting_registration_is_the_admins_inbox_item_until_decided(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    """§18.1, §18.3: `registration_pending` counts in `inbox` and stays unread until the
    registration is decided — neither `ids` nor "mark all read" marks it — then it reads
    as read."""
    done, _ = pending_account(make_client, migrated)
    bell = admin.get("/me/notifications").json()
    [item] = [i for i in bell["items"] if i["kind"] == "inbox"]
    assert item["title"] == "ada waits for approval"
    assert item["target"] == {"type": "registration", "id": done.human_id}
    assert (item["read"], item["project"]) == (False, None)
    assert bell["counts"]["inbox"] == 1 and bell["by_project"] == {}
    for body in ({"ids": [item["id"]]}, {"up_to": bell["next_after"]}):  # "mark all read"
        assert admin.post("/me/notifications/read", body).json()["counts"]["inbox"] == 1, body
        marked = admin.get("/me/notifications").json()
        assert [i["read"] for i in marked["items"] if i["id"] == item["id"]] == [False], body
    assert admin.post(f"{ADMIN}/{done.human_id}/approve").status_code == 200
    decided = admin.get("/me/notifications").json()
    assert decided["counts"]["inbox"] == 0
    assert [i["read"] for i in decided["items"] if i["id"] == item["id"]] == [True]


# --- the mails of a decision (§2.7.5, §16.2) --------------------------------------------------


def _with_mail(make_client: ClientFactory, admin: flow.Human) -> flow.Human:
    """The instance admin on a hub whose mail is complete and enabled."""
    client = make_client(mail=settings_for().mail)
    client.post("/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD})
    return flow.Human(client, client.get("/api/v1/auth/session").json()["csrf_token"], admin.id)


def _mailed(engine: Engine, address: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.mail_outbox)
                .where(t.mail_outbox.c.recipient == address)
                .order_by(t.mail_outbox.c.id)
            ).all()
        )


def test_an_approval_mails_the_login_link_and_writes_the_record(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    done, _ = pending_account(make_client, migrated)
    before = len(_mailed(migrated, "ada@example.com"))
    assert (
        _with_mail(make_client, admin).post(f"{ADMIN}/{done.human_id}/approve").status_code == 200
    )
    [mail] = _mailed(migrated, "ada@example.com")[before:]
    assert (mail.kind, mail.human_id) == ("security", done.human_id)
    assert mail.subject == "[Maity] Your Maity account is approved"
    assert "https://hub.example/login" in mail.body
    with migrated.connect() as conn:
        [record] = conn.execute(
            select(t.account_record).where(
                t.account_record.c.human_id == done.human_id,
                t.account_record.c.type == "registration_approved",
            )
        ).all()
    assert record.data == {"human": done.human_id, "by": admin.id}


def test_a_rejection_mails_the_reason_to_an_account_that_is_gone(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    done, _ = pending_account(make_client, migrated)
    before = len(_mailed(migrated, "ada@example.com"))
    rejected = _with_mail(make_client, admin).post(
        f"{ADMIN}/{done.human_id}/reject", {"reason": "Not a team member, see www.x.org"}
    )
    assert rejected.status_code == 200, rejected.text
    [mail] = _mailed(migrated, "ada@example.com")[before:]
    assert (mail.kind, mail.human_id) == ("security", None)  # the account is deleted
    assert mail.subject == "[Maity] Your Maity account was not approved"
    assert "Not a team member" in mail.body and "30 days" in mail.body
    assert "www.x.org" not in mail.body  # the operator's words make no link (§18.5)
    assert "https://hub.example" in mail.body


def test_an_expiry_mails_that_it_was_not_approved_in_time(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    done, _ = pending_account(make_client, migrated)
    before = len(_mailed(migrated, "ada@example.com"))
    with migrated.begin() as conn:
        conn.execute(
            update(t.account_registration).values(expires_at=clock.now() - timedelta(seconds=1))
        )
        assert registration_accounts.expire(conn, settings_for()) == 1
    [mail] = _mailed(migrated, "ada@example.com")[before:]
    assert mail.subject == "[Maity] Your Maity account was not approved in time"
    assert "not approved in time" in mail.body and "reason" not in mail.body


def test_without_mail_a_decision_queues_no_mail(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, claims: dict[str, str]
) -> None:
    """A mail held until mail is switched on could arrive weeks after the decision."""
    first, _ = pending_account(make_client, migrated)
    second, _ = pending_account(make_client, migrated, "bob@example.com", "bob")
    before = len(_mailed(migrated, "ada@example.com")), len(_mailed(migrated, "bob@example.com"))
    assert admin.post(f"{ADMIN}/{first.human_id}/approve").status_code == 200  # a hub without mail
    assert admin.post(f"{ADMIN}/{second.human_id}/reject", {"reason": "No."}).status_code == 200
    after = len(_mailed(migrated, "ada@example.com")), len(_mailed(migrated, "bob@example.com"))
    assert after == before
