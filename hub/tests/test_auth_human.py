"""docs/api.md §2.1: the human's session cookie and CSRF header."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import factory
from tests.conftest import ClientFactory


@pytest.fixture
def owner(migrated: Engine) -> str:
    return factory.human(migrated, "maintainer")


def _login(client: TestClient, handle: str = "maintainer") -> str:
    response = factory.login_handle(client, handle)
    assert response.status_code == 200, response.text
    csrf: str = client.get("/api/v1/auth/session").json()["csrf_token"]
    return csrf


def test_login_answers_the_member_and_sets_both_cookies(
    make_client: ClientFactory, owner: str
) -> None:
    client = make_client()
    response = factory.login_handle(client, "maintainer")
    assert response.status_code == 200
    assert response.json() == {
        "member": {
            "id": owner,
            "kind": "human",
            "handle": "maintainer",
            "display_name": "Human maintainer",
            "avatar_url": None,
        },
        "next": "/",
    }
    cookies = response.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("maity_session="))
    csrf = next(c for c in cookies if c.startswith("maity_csrf="))
    for flag in ("Secure", "SameSite=lax", "Path=/"):
        assert flag in session and flag in csrf
    assert "HttpOnly" in session
    assert "HttpOnly" not in csrf


def test_plain_http_mode_drops_the_secure_flag(make_client: ClientFactory, owner: str) -> None:
    client = make_client(base_url="http://hub.local", allow_plain_http=True)
    response = factory.login_handle(client, "maintainer")
    assert all("Secure" not in c for c in response.headers.get_list("set-cookie"))


@pytest.mark.parametrize(
    ("handle", "password"), [("maintainer", "wrong"), ("nobody", factory.PASSWORD)]
)
def test_a_wrong_handle_or_password_is_unauthenticated(
    make_client: ClientFactory, owner: str, handle: str, password: str
) -> None:
    response = factory.login_handle(make_client(), handle, password)
    assert response.status_code == 401
    assert response.headers["Maity-Error"] == "unauthenticated"
    assert "set-cookie" not in response.headers


def test_login_is_limited_to_ten_per_minute(make_client: ClientFactory, owner: str) -> None:
    client = make_client()
    for _ in range(10):
        factory.login_handle(client, "maintainer", "wrong")
    response = factory.login_handle(client, "maintainer")
    assert response.status_code == 429
    assert response.headers["Maity-Error"] == "rate_limited"
    assert int(response.headers["Retry-After"]) >= 1


def _reason(response: Any) -> Any:
    return response.json()["error"]["details"].get("reason")


def test_five_wrong_passwords_pause_the_password_from_other_sources(
    make_client: ClientFactory, owner: str
) -> None:
    for i in range(5):
        wrong = factory.login_handle(make_client(peer=f"203.0.113.{i + 10}"), "maintainer", "wrong")
        assert (wrong.status_code, _reason(wrong)) == (401, None)
    # The right password from a source the account never signed in from: not even checked.
    paused = factory.login_handle(make_client(peer="198.51.100.1"), "maintainer")
    assert paused.status_code == 401 and paused.headers["Maity-Error"] == "unauthenticated"
    details = paused.json()["error"]["details"]
    assert details["reason"] == "password_paused"  # this hub offers no link by mail
    assert 1 <= details["retry_after"] <= 15 * 60
    assert "set-cookie" not in paused.headers


def test_a_known_source_keeps_the_password_until_its_own_five(
    make_client: ClientFactory, owner: str
) -> None:
    home = "198.51.100.7"
    assert factory.login_handle(make_client(peer=home), "maintainer").status_code == 200
    for i in range(5):
        factory.login_handle(make_client(peer=f"203.0.113.{i + 10}"), "maintainer", "wrong")
    assert factory.login_handle(make_client(peer=home), "maintainer").status_code == 200
    for _ in range(5):  # wrong passwords from the known source count like any
        wrong = factory.login_handle(make_client(peer=home), "maintainer", "wrong")
        assert (wrong.status_code, _reason(wrong)) == (401, None)
    paused = factory.login_handle(make_client(peer=home), "maintainer")
    assert _reason(paused) == "password_paused"


def test_a_completed_sign_in_keeps_a_fingerprint_of_its_source_not_the_address(
    make_client: ClientFactory, migrated: Engine, owner: str
) -> None:
    from maity_hub.auth import known_sources

    with migrated.begin() as conn:
        assert known_sources.known(conn, owner, "203.0.113.7") is False
    factory.login_handle(make_client(), "maintainer")  # the default peer, 203.0.113.7
    with migrated.begin() as conn:
        assert known_sources.known(conn, owner, "203.0.113.7") is True
        stored = conn.execute(select(t.known_source)).all()
    assert [row.human_id for row in stored] == [owner]
    assert all("203.0.113.7" not in row.fingerprint for row in stored)  # a fingerprint only


def test_the_fingerprints_take_the_first_use_pepper_and_a_key_change_forgets_them(
    migrated: Engine, owner: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No migration makes the key: the per-address lock's pepper, made at first use, is its
    base where no instance key is set; until it exists nothing is remembered (§2.1)."""
    from maity_hub.auth import known_sources
    from maity_hub.mail import address as addresses

    monkeypatch.setattr(known_sources, "_secret_key", [None])
    source = "203.0.113.7"
    with migrated.begin() as conn:
        known_sources.remember(conn, owner, source)
        assert conn.execute(select(t.known_source)).first() is None
    addresses.prepare(migrated, None)
    with migrated.begin() as conn:
        known_sources.remember(conn, owner, source)
        assert known_sources.known(conn, owner, source) is True
        fingerprint = known_sources.fingerprint(conn, source)
        assert fingerprint != addresses.lock_key(conn, None, source)  # a key of its own
    monkeypatch.setattr(known_sources, "_secret_key", [b"k" * 32])
    with migrated.begin() as conn:  # an instance key set: every fingerprint stops matching
        assert known_sources.known(conn, owner, source) is False


def test_an_address_of_no_account_is_answered_as_an_account_is(
    make_client: ClientFactory, owner: str
) -> None:
    answers = [factory.login_handle(make_client(), "nobody", "wrong") for _ in range(6)]
    assert [(a.status_code, _reason(a)) for a in answers[:5]] == [(401, None)] * 5
    assert _reason(answers[5]) == "password_paused"


def test_past_the_limit_the_link_is_offered_where_the_hub_sends_it(
    make_client: ClientFactory, owner: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity_hub.auth import sign_in_settings

    monkeypatch.setattr(sign_in_settings, "view", lambda conn, hub: {"email_link_available": True})
    for i in range(5):
        factory.login_handle(make_client(peer=f"203.0.113.{i + 10}"), "maintainer", "wrong")
    paused = factory.login_handle(make_client(peer="198.51.100.1"), "maintainer")
    assert paused.json()["error"]["details"] == {"reason": "email_link"}


def test_a_right_password_gives_its_place_back(make_client: ClientFactory, owner: str) -> None:
    for i in range(4):
        factory.login_handle(make_client(peer=f"203.0.113.{i + 10}"), "maintainer", "wrong")
    for i in range(3):
        right = factory.login_handle(make_client(peer=f"203.0.113.{i + 30}"), "maintainer")
        assert right.status_code == 200
    # Four wrong, not seven: a new source still signs in.
    assert factory.login_handle(make_client(peer="198.51.100.9"), "maintainer").status_code == 200


def test_session_answers_member_csrf_token_and_expiry(
    make_client: ClientFactory, owner: str
) -> None:
    client = make_client()
    _login(client)
    body = client.get("/api/v1/auth/session").json()
    assert set(body) == {"member", "csrf_token", "expires_at", "join_url", "session_id"}
    assert body["session_id"].startswith("hss-")
    assert body["join_url"] is None
    assert body["member"]["id"] == owner
    assert body["csrf_token"] == client.cookies["maity_csrf"]
    assert factory.at(body["expires_at"]) > clock.now() + timedelta(days=13)


def test_a_state_changing_cookie_call_needs_the_csrf_token(
    make_client: ClientFactory, owner: str
) -> None:
    client = make_client()
    csrf = _login(client)
    missing = client.post("/api/v1/auth/logout")
    assert missing.status_code == 403
    assert missing.headers["Maity-Error"] == "csrf_mismatch"
    wrong = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "f" * 64})
    assert wrong.headers["Maity-Error"] == "csrf_mismatch"
    ok = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200
    assert ok.json()["member"]["id"] == owner


def test_the_token_is_compared_with_the_session_not_the_cookie(
    make_client: ClientFactory, owner: str
) -> None:
    client = make_client()
    _login(client)
    client.cookies.set("maity_csrf", "a" * 64, domain="hub.example")
    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "a" * 64})
    assert response.headers["Maity-Error"] == "csrf_mismatch"


def test_cross_site_requests_with_the_cookie_are_refused(
    make_client: ClientFactory, owner: str
) -> None:
    client = make_client()
    _login(client)
    response = client.get("/api/v1/me", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.headers["Maity-Error"] == "csrf_mismatch"
    assert client.get("/api/v1/me", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_logout_ends_the_session(make_client: ClientFactory, owner: str) -> None:
    client = make_client()
    csrf = _login(client)
    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert any(c.startswith("maity_session=") for c in response.headers.get_list("set-cookie"))
    client.cookies.clear()
    stolen = make_client()
    stolen.cookies.set("maity_session", "replayed", domain="hub.example")
    assert stolen.get("/api/v1/me").headers["Maity-Error"] == "unauthenticated"


def test_a_session_expires_after_14_idle_days(make_client: ClientFactory, owner: str) -> None:
    client = make_client()
    _login(client)
    start = clock.now()
    clock.set_source(lambda: start + timedelta(days=13))
    assert client.get("/api/v1/me").status_code == 200  # and renews last_seen
    clock.set_source(lambda: start + timedelta(days=13 + 14, seconds=1))
    assert client.get("/api/v1/me").headers["Maity-Error"] == "unauthenticated"


def test_a_session_expires_30_days_after_login_whatever_the_activity(
    make_client: ClientFactory, owner: str
) -> None:
    client = make_client()
    _login(client)
    start = clock.now()
    for day in range(1, 30):
        clock.set_source(lambda day=day: start + timedelta(days=day))  # type: ignore[misc]
        assert client.get("/api/v1/me").status_code == 200
    clock.set_source(lambda: start + timedelta(days=30, seconds=1))
    assert client.get("/api/v1/me").headers["Maity-Error"] == "unauthenticated"


def test_every_login_issues_a_fresh_session(make_client: ClientFactory, owner: str) -> None:
    client = make_client()
    _login(client)
    first = client.cookies["maity_session"]
    _login(client)
    assert client.cookies["maity_session"] != first


def test_a_password_change_ends_every_other_session(
    make_client: ClientFactory, owner: str, migrated: Engine
) -> None:
    laptop, phone = make_client(), make_client()
    csrf = _login(laptop)
    _login(phone)
    wrong = laptop.post(
        "/api/v1/auth/password",
        json={"current": "nope", "new": "a new long password"},
        headers={"X-CSRF-Token": csrf},
    )
    assert wrong.headers["Maity-Error"] == "invalid"
    assert wrong.json()["error"]["details"]["fields"] == {"current": "mismatch"}
    response = laptop.post(
        "/api/v1/auth/password",
        json={"current": factory.PASSWORD, "new": "a new long password"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert laptop.get("/api/v1/me").status_code == 200
    assert phone.get("/api/v1/me").headers["Maity-Error"] == "unauthenticated"
    fresh = make_client()
    ok = factory.login_handle(fresh, "maintainer", "a new long password")
    assert ok.status_code == 200


def test_every_call_renews_the_humans_last_seen(
    make_client: ClientFactory, owner: str, migrated: Engine
) -> None:
    client = make_client()
    _login(client)
    later = clock.now() + timedelta(hours=1)
    clock.set_source(lambda: later)
    client.get("/api/v1/me")
    with migrated.connect() as conn:
        seen = conn.execute(select(t.human.c.last_seen_at).where(t.human.c.id == owner)).scalar()
    assert seen == later


def test_agent_endpoints_and_auth_endpoints_are_separate(
    make_client: ClientFactory, migrated: Engine
) -> None:
    project_id = factory.project(migrated)
    owner = factory.human(migrated)
    agent = factory.agent(migrated, project_id, owner)
    response = make_client().get(
        "/api/v1/auth/session", headers={"Authorization": f"Bearer {agent.value}"}
    )
    assert response.status_code == 403
    assert response.headers["Maity-Error"] == "forbidden"


def test_a_new_password_has_at_least_twelve_characters(
    make_client: ClientFactory, owner: str
) -> None:
    client = make_client()
    csrf = _login(client)
    response = client.post(
        "/api/v1/auth/password",
        json={"current": factory.PASSWORD, "new": "eleven char"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"new": "too_short"}
    twelve = client.post(
        "/api/v1/auth/password",
        json={"current": factory.PASSWORD, "new": "twelve chars"},
        headers={"X-CSRF-Token": csrf},
    )
    assert twelve.status_code == 200


def test_a_wrong_current_password_counts_in_its_own_bucket(
    make_client: ClientFactory, owner: str
) -> None:
    client = make_client()
    csrf = _login(client)
    for _ in range(5):
        wrong = client.post(
            "/api/v1/auth/password",
            json={"current": "guess", "new": "a new long password"},
            headers={"X-CSRF-Token": csrf},
        )
        assert wrong.headers["Maity-Error"] == "invalid"
    limited = client.post(
        "/api/v1/auth/password",
        json={"current": factory.PASSWORD, "new": "a new long password"},
        headers={"X-CSRF-Token": csrf},
    )
    assert limited.status_code == 429
    assert limited.headers["Maity-Error"] == "rate_limited"
    # The session's own wrong attempts pause nobody's sign-in (§2.1).
    login = factory.login_handle(make_client(peer="198.51.100.2"), "maintainer")
    assert login.status_code == 200


def test_login_over_plain_http_off_loopback_is_insecure_transport(
    make_client: ClientFactory, owner: str
) -> None:
    response = factory.login_handle(make_client(base_url="http://hub.example"), "maintainer")
    assert response.status_code == 403
    assert response.headers["Maity-Error"] == "insecure_transport"


def test_login_over_plain_http_on_loopback_sets_cookies_without_secure(
    make_client: ClientFactory, owner: str
) -> None:
    response = factory.login_handle(
        make_client(base_url="http://localhost:8080", peer="127.0.0.1"), "maintainer"
    )
    assert response.status_code == 200
    assert all("Secure" not in c for c in response.headers.get_list("set-cookie"))


def test_a_cookie_sent_over_plain_http_off_loopback_is_refused(
    make_client: ClientFactory, owner: str
) -> None:
    client = make_client()
    _login(client)
    plain = make_client(base_url="http://hub.example")
    plain.cookies.set("maity_session", client.cookies["maity_session"], domain="hub.example")
    assert plain.get("/api/v1/me").headers["Maity-Error"] == "insecure_transport"


def test_secure_follows_the_scheme_even_with_the_plain_http_flag(
    make_client: ClientFactory, owner: str
) -> None:
    response = factory.login_handle(make_client(allow_plain_http=True), "maintainer")
    assert all("Secure" in c for c in response.headers.get_list("set-cookie"))


def test_an_agent_credential_on_login_is_forbidden(
    make_client: ClientFactory, migrated: Engine
) -> None:
    project_id = factory.project(migrated)
    agent = factory.agent(migrated, project_id, factory.human(migrated))
    response = make_client().post(
        "/api/v1/auth/login",
        json={"email": "x", "password": "y"},
        headers={"Authorization": f"Bearer {agent.value}"},
    )
    assert response.status_code == 403
    assert response.headers["Maity-Error"] == "forbidden"
    assert "scope" not in response.json()["error"]["details"]


def test_a_wrong_password_an_address_of_no_account_and_a_suspended_account_are_answered_alike(
    make_client: ClientFactory, migrated: Engine, owner: str
) -> None:
    """§2.1: an address of no account and a suspended account learn nothing a wrong password
    does not tell; the whole answer is the same, body and headers."""
    from maity_hub import moderation

    suspended = factory.human(migrated, "suspended")
    with migrated.begin() as conn:
        moderation.suspend(conn, suspended, "rpt-000000000000")

    def answer(response: Any) -> tuple[Any, ...]:
        headers = response.headers
        return (
            response.status_code,
            response.json(),
            headers.get("Maity-Error"),
            headers.get("Retry-After"),
        )

    wrong = factory.login_handle(make_client(peer="203.0.113.21"), "maintainer", "wrong")
    nobody = factory.login_handle(make_client(peer="203.0.113.22"), "nobody", "wrong")
    right_but_suspended = factory.login_handle(make_client(peer="203.0.113.23"), "suspended")
    assert wrong.status_code == 401
    assert answer(nobody) == answer(wrong)
    assert answer(right_but_suspended) == answer(wrong)


def _seen_while_comparing(monkeypatch: pytest.MonkeyPatch, bucket: Any, key: str) -> list[int]:
    """What `bucket` says about `key` while a password is being compared."""
    from maity_hub.auth import passwords

    seen: list[int] = []
    verify = passwords.verify_password

    def comparing(*args: Any) -> bool:
        seen.append(bucket.blocked(key))
        return verify(*args)

    monkeypatch.setattr(passwords, "verify_password", comparing)
    return seen


def test_a_login_holds_its_place_in_the_count_while_it_compares(
    make_client: ClientFactory, owner: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Four wrong; while the fifth is compared the count already holds it, so a login running
    # at the same time from an unknown source is refused instead of getting past the limit.
    from maity_hub.auth import password_limits

    for i in range(4):
        factory.login_handle(make_client(peer=f"203.0.113.{i + 10}"), "maintainer", "wrong")
    seen = _seen_while_comparing(monkeypatch, password_limits.LOGIN, owner)
    factory.login_handle(make_client(peer="203.0.113.20"), "maintainer", "wrong")
    assert len(seen) == 1 and seen[0] > 0  # the fifth place was taken before the comparison


def _signed_in_with_four_wrong(
    make_client: ClientFactory, path: str, method: str, body: dict[str, Any]
) -> tuple[TestClient, str]:
    client = make_client()
    csrf = _login(client)
    for _ in range(4):
        client.request(method, path, json=body, headers={"X-CSRF-Token": csrf})
    return client, csrf


@pytest.mark.parametrize(
    ("bucket", "method", "path", "body"),
    [
        ("CHANGE", "POST", "/api/v1/auth/password", {"current": "nope", "new": "a new long one"}),
        ("REAUTHENTICATE", "POST", "/api/v1/auth/reauthenticate", {"password": "nope"}),
    ],
)
def test_the_other_password_checks_hold_their_place_while_they_compare(
    make_client: ClientFactory,
    owner: str,
    monkeypatch: pytest.MonkeyPatch,
    bucket: str,
    method: str,
    path: str,
    body: dict[str, Any],
) -> None:
    from maity_hub.auth import password_limits

    client, csrf = _signed_in_with_four_wrong(make_client, path, method, body)
    seen = _seen_while_comparing(monkeypatch, getattr(password_limits, bucket), owner)
    client.request(method, path, json=body, headers={"X-CSRF-Token": csrf})
    assert len(seen) == 1 and seen[0] > 0


def test_a_fingerprint_goes_30_days_after_its_last_sign_in_without_another_sign_in(
    migrated: Engine, owner: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2.1: the 30 days hold on a hub where nobody signs in; the sweep deletes the row."""
    from maity_hub.auth import known_sources

    monkeypatch.setattr(known_sources, "_secret_key", [b"k" * 32])
    source = "203.0.113.7"
    start = clock.now()
    with migrated.begin() as conn:
        known_sources.remember(conn, owner, source)

    def rows() -> int:
        with migrated.connect() as conn:
            return len(conn.execute(select(t.known_source)).all())

    clock.set_source(lambda: start + timedelta(days=29, hours=23))
    with migrated.begin() as conn:
        known_sources.forget_old(conn)
        assert known_sources.known(conn, owner, source) is True
    assert rows() == 1
    clock.set_source(lambda: start + timedelta(days=30, seconds=1))
    sweep = known_sources.Worker(migrated, interval=0.05)
    sweep.start()
    try:
        deadline = time.monotonic() + 10
        while rows() and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        sweep.stop()
    assert rows() == 0


def test_the_start_warns_while_the_instance_admin_has_no_verified_address(
    migrated: Engine, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    from maity_hub.app import check_startup

    def warned() -> bool:
        return any(
            "instance admin has no verified address" in r.getMessage() for r in caplog.records
        )

    caplog.set_level(logging.WARNING)
    check_startup(migrated, settings)
    assert not warned()  # no human yet, no admin
    admin = factory.human(migrated, "maintainer")
    check_startup(migrated, settings)
    assert warned()
    caplog.clear()
    with factory.sign_in_address(migrated, admin):
        check_startup(migrated, settings)
    assert not warned()
