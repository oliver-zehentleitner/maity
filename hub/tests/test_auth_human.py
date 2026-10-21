"""docs/api.md §2.1: the human's session cookie and CSRF header."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from tests import factory
from tests.conftest import ClientFactory


@pytest.fixture
def owner(migrated: Engine) -> str:
    return factory.human(migrated, "maintainer")


def _login(client: TestClient, handle: str = "maintainer") -> str:
    response = client.post(
        "/api/v1/auth/login", json={"handle": handle, "password": factory.PASSWORD}
    )
    assert response.status_code == 200, response.text
    csrf: str = client.get("/api/v1/auth/session").json()["csrf_token"]
    return csrf


def test_login_answers_the_member_and_sets_both_cookies(
    make_client: ClientFactory, owner: str
) -> None:
    client = make_client()
    response = client.post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert response.status_code == 200
    assert response.json() == {
        "member": {
            "id": owner,
            "kind": "human",
            "handle": "maintainer",
            "display_name": "Human maintainer",
        }
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
    response = client.post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert all("Secure" not in c for c in response.headers.get_list("set-cookie"))


@pytest.mark.parametrize(
    ("handle", "password"), [("maintainer", "wrong"), ("nobody", factory.PASSWORD)]
)
def test_a_wrong_handle_or_password_is_unauthenticated(
    make_client: ClientFactory, owner: str, handle: str, password: str
) -> None:
    response = make_client().post(
        "/api/v1/auth/login", json={"handle": handle, "password": password}
    )
    assert response.status_code == 401
    assert response.headers["Maity-Error"] == "unauthenticated"
    assert "set-cookie" not in response.headers


def test_login_is_limited_to_ten_per_minute(make_client: ClientFactory, owner: str) -> None:
    client = make_client()
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"handle": "maintainer", "password": "wrong"})
    response = client.post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert response.status_code == 429
    assert response.headers["Maity-Error"] == "rate_limited"
    assert int(response.headers["Retry-After"]) >= 1


def test_the_handle_limit_holds_across_addresses(make_client: ClientFactory, owner: str) -> None:
    for i in range(10):
        make_client(peer=f"203.0.113.{i + 10}").post(
            "/api/v1/auth/login", json={"handle": "maintainer", "password": "wrong"}
        )
    response = make_client(peer="198.51.100.1").post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert response.headers["Maity-Error"] == "rate_limited"


def test_session_answers_member_csrf_token_and_expiry(
    make_client: ClientFactory, owner: str
) -> None:
    client = make_client()
    _login(client)
    body = client.get("/api/v1/auth/session").json()
    assert set(body) == {"member", "csrf_token", "expires_at"}
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
    ok = fresh.post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": "a new long password"}
    )
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


def test_a_wrong_current_password_counts_against_the_login_limit(
    make_client: ClientFactory, owner: str
) -> None:
    client = make_client()
    csrf = _login(client)  # one login attempt
    for _ in range(9):
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
    login = make_client(peer="198.51.100.2").post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert login.headers["Maity-Error"] == "rate_limited"  # the handle's limit is shared


def test_login_over_plain_http_off_loopback_is_insecure_transport(
    make_client: ClientFactory, owner: str
) -> None:
    response = make_client(base_url="http://hub.example").post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert response.status_code == 403
    assert response.headers["Maity-Error"] == "insecure_transport"


def test_login_over_plain_http_on_loopback_sets_cookies_without_secure(
    make_client: ClientFactory, owner: str
) -> None:
    response = make_client(base_url="http://localhost:8080", peer="127.0.0.1").post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
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
    response = make_client(allow_plain_http=True).post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert all("Secure" in c for c in response.headers.get_list("set-cookie"))


def test_an_agent_credential_on_login_is_forbidden(
    make_client: ClientFactory, migrated: Engine
) -> None:
    project_id = factory.project(migrated)
    agent = factory.agent(migrated, project_id, factory.human(migrated))
    response = make_client().post(
        "/api/v1/auth/login",
        json={"handle": "x", "password": "y"},
        headers={"Authorization": f"Bearer {agent.value}"},
    )
    assert response.status_code == 403
    assert response.headers["Maity-Error"] == "forbidden"
    assert "scope" not in response.json()["error"]["details"]
