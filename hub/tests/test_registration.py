"""docs/api.md §2.7 and §16.4, part 1: the registration settings and `POST /auth/register`
up to the pending registration. The mail and the completion come with the outbox."""

from __future__ import annotations

import base64
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select

from maity_hub import clock, registration, registration_mail
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from maity_hub.mail import address as addresses
from maity_hub.routes import registration as routes
from tests import factory, flow
from tests.conftest import ClientFactory

SIGNING = base64.b64encode(b"s" * 32).decode()
MAIL = {"MAITY_SMTP_HOST": "smtp.example.com", "MAITY_SMTP_FROM": "hub@example.com"}
SETTINGS = "/admin/settings/registration"
PASSWORD = "a good long passphrase"


def hub(**env: str) -> Settings:
    return Settings.from_env({"MAITY_DATABASE_URL": "sqlite://", **env})


@dataclass(frozen=True)
class Sent:
    kind: str
    to: str
    pending_id: str | None


SENT: list[Sent] = []


@pytest.fixture(autouse=True)
def _capture(monkeypatch: pytest.MonkeyPatch) -> None:
    """What registration would send, seen through a replaced `send`: production keeps
    nothing."""
    real = registration_mail.send

    def capture(
        conn: Any, *, kind: str, to: str, pending_id: str | None = None, **more: Any
    ) -> None:
        real(conn, kind=kind, to=to, pending_id=pending_id, **more)
        SENT.append(Sent(kind, to, pending_id))

    monkeypatch.setattr(registration_mail, "send", capture)


@pytest.fixture(autouse=True)
def _fresh() -> Iterator[None]:
    for limiter in (
        routes.BY_SOURCE,
        routes.BY_PAIR_SHORT,
        routes.BY_PAIR_DAY,
        routes.BY_ADDRESS_DAY,
    ):
        limiter._hits.clear()
    registration.BREAKER._at.clear()
    registration.BREAKER._open_until = 0.0
    SENT.clear()
    yield


def client_for(make_client: ClientFactory, settings: Settings) -> Any:
    return make_client(mail=settings.mail, registration=settings.registration)


def admin(make_client: ClientFactory, engine: Engine, settings: Settings) -> flow.Human:
    human_id = factory.human(engine, "maintainer")  # the first human: the instance admin
    client = client_for(make_client, settings)
    response = client.post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert response.status_code == 200, response.text
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    return flow.Human(client, csrf, human_id)


def register(client: Any, address: str = "ada@example.com", **body: Any) -> Any:
    return client.post(
        "/api/v1/auth/register", json={"address": address, "password": PASSWORD, **body}
    )


def pending(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.pending_registration).order_by(t.pending_registration.c.created_at)
            )
        )


def field(response: Any) -> Any:
    return response.json()["error"]["details"].get("fields")


# --- the settings (§16.4) ---------------------------------------------------------------


def test_a_fresh_instance_is_closed_and_mail_is_required_to_open_it(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = admin(make_client, migrated, hub())
    got = owner.get(SETTINGS).json()
    assert (got["mode"], got["effective_mode"]) == (
        {"value": "closed", "source": "default"},
        "closed",
    )
    assert got["approval"] == {"value": "operator", "source": "default"}
    assert got["max_new_accounts_per_hour"] == {"value": 20, "source": "default"}
    assert (got["missing"], got["pending"], got["terms"]["value"]) == ([], 0, None)
    refused = owner.patch(SETTINGS, {"mode": "open"})
    assert field(refused) == {"mode": "mail_required"}
    assert owner.get(SETTINGS).json()["mode"]["value"] == "closed"  # nothing stored


def test_the_admin_sets_lists_terms_and_approval(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = admin(make_client, migrated, hub(MAITY_MAIL_SIGNING_KEY=SIGNING, **MAIL))
    changed = owner.patch(
        SETTINGS,
        {
            "mode": "allowlist",
            "domains": ["@Example.COM", "@example.com"],
            "addresses": ["Guest@Example.net"],
            "approval": "automatic",
            "terms": {"url": "https://example.com/terms", "version": "2026-10"},
        },
    )
    assert changed.status_code == 200, changed.text
    got = changed.json()
    assert got["effective_mode"] == "allowlist" and got["missing"] == []
    assert got["domains"]["value"] == ["@example.com"]  # lower case, no duplicates
    assert got["addresses"]["value"] == ["guest@example.net"]
    assert got["terms"] == {
        "value": {"url": "https://example.com/terms", "version": "2026-10"},
        "source": "admin",
    }
    assert field(owner.patch(SETTINGS, {"domains": ["@ok.com", "nodomain"]})) == {
        "domains.1": "invalid"
    }
    assert field(owner.patch(SETTINGS, {"terms": {"url": "http://x.com", "version": "1"}})) == {
        "terms": "invalid"
    }
    assert field(owner.patch(SETTINGS, {"terms": {"url": "https://x.com/t"}})) == {
        "terms": "invalid"
    }
    assert field(owner.patch(SETTINGS, {"colour": "red"})) == {"colour": "extra_forbidden"}
    emptied = owner.patch(SETTINGS, {"domains": [], "addresses": []}).json()
    assert emptied["missing"] == ["allowlist"]


def test_the_terms_come_from_the_environment_then_the_admin_then_the_legal_pages(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """§16.7.1: while the `terms` page is set and neither the environment nor the admin gave
    the terms, they are the page and its version, `source: legal_pages`."""
    owner = admin(make_client, migrated, hub(MAITY_MAIL_SIGNING_KEY=SIGNING, **MAIL))
    assert owner.get(SETTINGS).json()["terms"] == {"value": None, "source": "default"}
    page = {"en": {"title": "Terms", "markdown": "Be kind."}}
    saved = owner.patch("/admin/settings/legal", {"terms": page}).json()
    version = saved["pages"]["terms"]["version"]
    assert owner.get(SETTINGS).json()["terms"] == {
        "value": {"url": "https://hub.example/terms", "version": version},
        "source": "legal_pages",
    }
    shown = owner.client.get("/api/v1/auth/methods").json()["terms"]  # the login page's too
    assert shown == {"url": "https://hub.example/terms", "version": version}
    owner.patch(SETTINGS, {"terms": {"url": "https://example.com/terms", "version": "2026-10"}})
    assert owner.get(SETTINGS).json()["terms"]["source"] == "admin"
    owner.patch(SETTINGS, {"terms": None})
    owner.patch("/admin/settings/legal", {"terms": None})  # unset: no terms again
    assert owner.get(SETTINGS).json()["terms"] == {"value": None, "source": "default"}


def test_the_environment_terms_win_over_the_legal_pages(
    make_client: ClientFactory, migrated: Engine
) -> None:
    settings = hub(
        MAITY_TERMS_URL="https://example.com/t",
        MAITY_TERMS_VERSION="v9",
        **MAIL,
        MAITY_MAIL_SIGNING_KEY=SIGNING,
    )
    owner = admin(make_client, migrated, settings)
    owner.patch("/admin/settings/legal", {"terms": {"en": {"title": "T", "markdown": "x"}}})
    assert owner.get(SETTINGS).json()["terms"] == {
        "value": {"url": "https://example.com/t", "version": "v9"},
        "source": "env",
    }


def test_the_environment_wins_and_cannot_be_patched(
    make_client: ClientFactory, migrated: Engine
) -> None:
    settings = hub(MAITY_REGISTRATION="open", MAITY_REGISTRATION_APPROVAL="automatic")
    owner = admin(make_client, migrated, settings)
    got = owner.get(SETTINGS).json()
    assert got["mode"] == {"value": "open", "source": "env"}
    assert (got["effective_mode"], got["missing"]) == ("closed", ["mail"])  # no mail yet
    assert field(owner.patch(SETTINGS, {"approval": "operator"})) == {
        "approval": "set_by_environment"
    }


def test_the_environment_is_checked_at_startup() -> None:
    for env in (
        {"MAITY_REGISTRATION": "wide"},
        {"MAITY_REGISTRATION_DOMAINS": "@ok.com,bad"},
        {"MAITY_TERMS_URL": "https://example.com/terms"},  # without a version
        {"MAITY_REGISTRATION_BREAKER": "0"},
    ):
        with pytest.raises(ConfigError):
            hub(**env)
    assert hub(MAITY_REGISTRATION_BREAKER="5").registration.breaker == 5


def test_only_the_instance_admin_reads_the_settings(
    make_client: ClientFactory, migrated: Engine
) -> None:
    admin(make_client, migrated, hub())
    other = flow.human(make_client, migrated, "someone")
    assert other.get(SETTINGS).status_code == 403
    assert other.patch(SETTINGS, {"mode": "closed"}).status_code == 403


# --- GET /auth/methods: what the login page learns (§2.6.1, §2.7) -------------------------


@pytest.mark.parametrize(
    ("mode", "mail", "offered"),
    [
        ("closed", True, False),
        ("closed", False, False),
        ("allowlist", True, True),
        ("allowlist", False, False),
        ("open", True, True),
        ("open", False, False),
    ],
)
def test_the_login_page_learns_whether_it_offers_registration(
    make_client: ClientFactory, migrated: Engine, mode: str, mail: bool, offered: bool
) -> None:
    """`registration` is true only for `allowlist` or `open` with complete, enabled mail;
    nothing about the lists' entries or any account."""
    env = {"MAITY_REGISTRATION": mode, "MAITY_REGISTRATION_DOMAINS": "@example.com"}
    if mail:
        env.update(MAITY_MAIL_SIGNING_KEY=SIGNING, **MAIL)
    answer = client_for(make_client, hub(**env)).get("/api/v1/auth/methods").json()
    assert answer["registration"] is offered
    assert answer["terms"] is None
    assert set(answer) == {"password", "device_code", "email_link", "registration", "terms"}


def test_an_empty_allowlist_offers_no_registration(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """§2.7: under `allowlist` with both lists empty nobody may register, so the login
    page is not offered a way that ends nowhere; the admin sees `missing`."""
    settings = hub(MAITY_MAIL_SIGNING_KEY=SIGNING, MAITY_REGISTRATION="allowlist", **MAIL)
    client = client_for(make_client, settings)
    assert client.get("/api/v1/auth/methods").json()["registration"] is False
    by = factory.human(migrated, "maintainer")
    env = settings.registration or registration.RegistrationEnvironment()
    with migrated.begin() as conn:
        registration.patch(conn, env, True, {"addresses": ["ada@example.com"]}, by)
    assert client.get("/api/v1/auth/methods").json()["registration"] is True


def test_the_login_page_learns_the_terms(make_client: ClientFactory, migrated: Engine) -> None:
    settings = hub(
        MAITY_MAIL_SIGNING_KEY=SIGNING,
        MAITY_REGISTRATION="open",
        MAITY_TERMS_URL="https://example.com/terms",
        MAITY_TERMS_VERSION="2026-10",
        **MAIL,
    )
    answer = client_for(make_client, settings).get("/api/v1/auth/methods").json()
    assert answer["registration"] is True
    assert answer["terms"] == {"url": "https://example.com/terms", "version": "2026-10"}


def test_the_admins_mode_shows_at_once(make_client: ClientFactory, migrated: Engine) -> None:
    """A mode set in the admin settings (§16.4), not only the environment, is what the
    login page learns, on the next read."""
    settings = hub(MAITY_MAIL_SIGNING_KEY=SIGNING, **MAIL)
    client = client_for(make_client, settings)
    assert client.get("/api/v1/auth/methods").json()["registration"] is False
    by = factory.human(migrated, "maintainer")
    env = settings.registration or registration.RegistrationEnvironment()
    with migrated.begin() as conn:
        registration.patch(conn, env, True, {"mode": "open"}, by)
    assert client.get("/api/v1/auth/methods").json()["registration"] is True


# --- POST /auth/register (§2.7.1, §2.7.3) -----------------------------------------------


def open_hub(make_client: ClientFactory, migrated: Engine, **env: str) -> Any:
    settings = hub(MAITY_MAIL_SIGNING_KEY=SIGNING, MAITY_REGISTRATION="open", **MAIL, **env)
    return client_for(make_client, settings)


def test_without_mail_it_answers_before_the_body_is_read(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = client_for(make_client, hub())
    refused = client.post("/api/v1/auth/register", content=b"not json at all")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"reason": "registration_closed"}
    no_mail = client_for(make_client, hub(MAITY_REGISTRATION="open"))  # open, but no mail
    assert register(no_mail).json()["error"]["details"]["reason"] == "registration_closed"


def test_closed_with_mail_answers_as_every_mode_and_stores_nothing(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """§2.7.1 step 1: the mode never shows in the answer; an uninvited address under
    `closed` is dropped after it."""
    client = client_for(make_client, hub(MAITY_MAIL_SIGNING_KEY=SIGNING, **MAIL))
    assert field(register(client, "not an address")) == {"address": "invalid"}
    answer = register(client)
    assert (answer.status_code, answer.json()) == (202, {"expires_in": 86400})
    assert pending(migrated) == [] and SENT == []


def test_a_registration_answers_202_and_waits_as_pending(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = open_hub(make_client, migrated)
    answer = register(client, " Ada@Example.com ", next="/projects")
    assert (answer.status_code, answer.json()) == (202, {"expires_in": 86400})
    [row] = pending(migrated)
    assert (row.address, row.address_normalized, row.next) == (
        "Ada@Example.com",
        "ada@example.com",
        "/projects",
    )
    assert row.password_hash != PASSWORD and row.expires_at - row.created_at == timedelta(hours=24)
    assert [(s.kind, s.pending_id) for s in SENT] == [("register_link", row.id)]


def test_the_body_is_checked_after_the_mode(make_client: ClientFactory, migrated: Engine) -> None:
    client = open_hub(make_client, migrated)
    assert field(register(client, "not an address")) == {"address": "invalid"}
    assert "password" in field(
        client.post(
            "/api/v1/auth/register", json={"address": "ada@example.com", "password": "short"}
        )
    )
    assert pending(migrated) == []
    assert register(client, next="https://evil.example/").status_code == 202
    assert [row.next for row in pending(migrated)] == ["/"]  # replaced silently (§2.6.5)


def test_an_agent_credential_is_refused(make_client: ClientFactory, migrated: Engine) -> None:
    client = open_hub(make_client, migrated)
    refused = client.post(
        "/api/v1/auth/register",
        json={"address": "bot@example.com", "password": PASSWORD},
        headers={"Authorization": "Bearer something"},
    )
    assert (refused.status_code, refused.json()["error"]["details"]) == (
        403,
        {"reason": "humans_only"},
    )


def test_an_allowlist_miss_and_a_block_answer_alike_and_store_nothing(
    make_client: ClientFactory, migrated: Engine
) -> None:
    settings = hub(
        MAITY_MAIL_SIGNING_KEY=SIGNING,
        MAITY_REGISTRATION="allowlist",
        MAITY_REGISTRATION_DOMAINS="@example.com",
        **MAIL,
    )
    client = client_for(make_client, settings)
    miss = register(client, "eve@elsewhere.org")
    assert (miss.status_code, miss.json()) == (202, {"expires_in": 86400})
    with migrated.begin() as conn:
        conn.execute(
            insert(t.registration_block).values(
                address_normalized="bob@example.com",
                until=clock.now() + timedelta(days=30),
                created_at=clock.now(),
            )
        )
    blocked = register(client, "Bob@example.com")
    assert (blocked.status_code, blocked.json()) == (202, {"expires_in": 86400})
    assert pending(migrated) == [] and SENT == []
    assert register(client, "ann@example.com").status_code == 202
    assert [r.address_normalized for r in pending(migrated)] == ["ann@example.com"]


def test_a_new_request_voids_the_same_sources_earlier_one_and_five_is_the_cap(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = open_hub(make_client, migrated)
    register(client)
    register(client)
    rows = pending(migrated)
    assert [r.voided_at is None for r in rows] == [False, True]
    settings = client.app.state.settings
    for n in range(5):  # five other sources
        other = make_client(
            peer=f"198.51.100.{n + 1}", mail=settings.mail, registration=settings.registration
        )
        assert register(other).status_code == 202
    live = [r for r in pending(migrated) if r.voided_at is None]
    assert len(live) == registration.PENDING_PER_ADDRESS


def test_the_per_source_limit_answers_429_and_the_pair_limit_stays_silent(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = open_hub(make_client, migrated)
    for n in range(10):
        assert register(client, f"p{n}@example.com").status_code == 202
    assert register(client, "p10@example.com").status_code == 429
    routes.BY_SOURCE._hits.clear()
    SENT.clear()
    for _ in range(4):
        assert register(client, "same@example.com").status_code == 202
    assert len(SENT) == 3  # the fourth within 15 minutes sends nothing


def test_the_breaker_stops_every_request_for_a_minute(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = open_hub(make_client, migrated, MAITY_REGISTRATION_BREAKER="3")
    answers = [register(client, f"b{n}@example.com").status_code for n in range(5)]
    assert answers == [202, 202, 202, 429, 429]


def test_the_admin_lifts_a_block(make_client: ClientFactory, migrated: Engine) -> None:
    owner = admin(make_client, migrated, hub())
    with migrated.begin() as conn:
        conn.execute(
            insert(t.registration_block).values(
                address_normalized="bob@example.com",
                until=clock.now() + timedelta(days=30),
                created_at=clock.now(),
            )
        )
    for _ in range(2):  # idempotent
        lifted = owner.delete("/admin/registrations/blocks/Bob@Example.com")
        assert lifted.status_code == 204
    with migrated.connect() as conn:
        assert conn.execute(select(t.registration_block)).all() == []
    other = flow.human(make_client, migrated, "someone")
    assert other.delete("/admin/registrations/blocks/x@example.com").status_code == 403


def test_every_request_counts_for_the_breaker_even_a_source_limited_one(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """The reviewer's probe: 13 requests from one source with a breaker of 12; the last
    three are over the per-source limit, and the breaker still trips for the next source."""
    settings = hub(
        MAITY_MAIL_SIGNING_KEY=SIGNING,
        MAITY_REGISTRATION="open",
        MAITY_REGISTRATION_BREAKER="12",
        **MAIL,
    )
    client = client_for(make_client, settings)
    answers = [register(client, f"s{n}@example.com").status_code for n in range(13)]
    assert answers == [202] * 10 + [429] * 3
    fresh = make_client(peer="198.51.100.9", mail=settings.mail, registration=settings.registration)
    assert register(fresh, "fresh@example.com").status_code == 429


def test_an_addresses_pending_registrations_change_one_at_a_time(migrated: Engine) -> None:
    """Two transactions for one address: the second waits for the first's lock (§2.7.1).
    SQLite serialises every writer anyway, so this runs on PostgreSQL and MariaDB. The
    first transaction is released on every exit before the worker is joined, so a failing
    assertion cannot leave CI waiting on a blocked thread."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises writers; the row lock is for the server databases")
    addresses.prepare(migrated, None)  # the locks below are taken without a route
    first, second = migrated.connect(), migrated.connect()
    started, locked = threading.Event(), threading.Event()

    def take() -> None:
        with second.begin():
            started.set()
            routes.lock_address(second, None, "race@example.com")
            locked.set()

    pool = ThreadPoolExecutor(max_workers=1)
    first_tx = first.begin()
    try:
        routes.lock_address(first, None, "race@example.com")
        waiting = pool.submit(take)
        assert started.wait(timeout=10)  # the worker runs and is about to take the lock
        assert not locked.wait(timeout=0.5)  # held by the first transaction
        first_tx.commit()
        assert locked.wait(timeout=10)  # released: the second goes through
        waiting.result(timeout=10)
    finally:
        if first_tx.is_active:
            first_tx.rollback()
        first.close()
        pool.shutdown(wait=True, cancel_futures=True)
        second.close()


def test_the_production_sender_keeps_nothing() -> None:
    """No address outlives its pending registration in the process (§2.7.1)."""
    from maity_hub import registration_mail as module

    assert not hasattr(module, "SENT")


def test_the_dropped_count_forgets_the_hour_before_while_nobody_reads_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`add` drops what is past the hour too: the count is read only when an admin
    looks, and the list must not grow for as long as nobody does."""
    from types import SimpleNamespace

    dropped = registration.Dropped()
    now = [1000.0]
    monkeypatch.setattr(registration, "time", SimpleNamespace(monotonic=lambda: now[0]))
    for _ in range(50):
        dropped.add()
        now[0] += 600  # one every ten minutes, for over eight hours
    assert len(dropped._at) == 7  # the last add kept its own hour, both ends included
    assert dropped.last_hour() == 6
