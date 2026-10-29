"""The mailed first factor, using the real outbox, cookies and HTTP endpoints."""

from __future__ import annotations

import base64
import logging
import re
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import email_links
from maity_hub.config import Settings
from maity_hub.notifications import preferences
from maity_hub.routes import email_sign_in
from tests import factory
from tests.conftest import ClientFactory

KEY = base64.b64encode(b"s" * 32).decode()


@pytest.fixture(autouse=True)
def limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_sign_in, "LIMITS", email_links.RequestLimits())


def setup(make_client: ClientFactory, engine: Engine, **env: str) -> tuple[Any, str]:
    hub = Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite://",
            "MAITY_SMTP_HOST": "smtp.example.com",
            "MAITY_SMTP_FROM": "hub@example.com",
            "MAITY_MAIL_SIGNING_KEY": KEY,
            **env,
        }
    )
    human = factory.human(engine, "ada")
    with engine.begin() as conn:
        assert preferences.claim_verified(conn, "ada@example.com", human, secret_key=None)
    return make_client(mail=hub.mail, secret_key=b"k" * 32), human


def ask(client: Any, address: str = "ada@example.com", **body: Any) -> Any:
    return client.post(
        "/api/v1/auth/email-link",
        json={"address": address, **body},
        headers={"x-csrf-token": client.cookies.get("maity_csrf", "")},
    )


def mail(engine: Engine) -> tuple[str, str]:
    with engine.connect() as conn:
        row = conn.execute(
            select(t.mail_outbox)
            .where(t.mail_outbox.c.kind == "sign_in")
            .order_by(t.mail_outbox.c.id.desc())
        ).first()
    assert row is not None
    token = re.search(r"/mail/sign-in/(\S+)", row.body)
    code = re.search(r"(\d{3}) (\d{3})", row.body)
    assert token and code
    return "/mail/sign-in/" + token[1], code[1] + code[2]


def test_unknown_and_known_requests_have_same_response_and_fresh_cookie(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    first = ask(client, "missing@example.com")
    cookie = client.cookies.get("maity_pending")
    second = ask(client, "  ADA@example.com  ", next="/#/projects")
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json() == {"expires_in": 900}
    assert cookie != client.cookies.get("maity_pending")
    _, code = mail(migrated)
    answer = client.post("/api/v1/auth/email-code", json={"code": code})
    assert answer.status_code == 200, answer.text
    assert answer.json()["next"] == "/#/projects"
    assert answer.json()["member"]["handle"] == "ada"
    assert client.cookies.get("maity_pending") is None


def test_get_is_harmless_and_form_requires_same_origin_then_single_use(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    ask(client)
    url, code = mail(migrated)
    got = client.get(url, headers={"sec-fetch-site": "cross-site"})
    assert got.status_code == 200, got.text
    assert "ada" in got.text
    assert client.cookies.get("maity_session") is None
    form = client.cookies.get("maity_form")
    assert client.post(url, data={"form": form}).status_code == 403
    assert (
        client.post(
            url, data={"form": "wrong"}, headers={"sec-fetch-site": "same-origin"}
        ).status_code
        == 403
    )
    done = client.post(
        url, data={"form": form}, headers={"sec-fetch-site": "same-origin"}, follow_redirects=False
    )
    assert done.status_code == 303, done.text
    assert done.headers["location"] == "/"
    assert client.get(url).status_code == 404
    assert (
        client.post(
            "/api/v1/auth/email-code",
            json={"code": code},
            headers={"x-csrf-token": client.cookies.get("maity_csrf", "")},
        ).status_code
        == 403
    )
    assert client.get("/api/v1/auth/session").status_code == 200


def test_code_cannot_be_used_from_another_browser_and_wrong_guesses_commit(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    ask(client)
    url, code = mail(migrated)
    stranger = make_client()
    assert (
        stranger.post(
            "/api/v1/auth/email-code",
            json={"code": code},
            headers={"x-csrf-token": client.cookies.get("maity_csrf", "")},
        ).status_code
        == 403
    )
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert client.post("/api/v1/auth/email-code", json={"code": wrong}).status_code == 403
    assert (
        client.post(
            "/api/v1/auth/email-code",
            json={"code": code},
            headers={"x-csrf-token": client.cookies.get("maity_csrf", "")},
        ).status_code
        == 403
    )
    assert client.get(url).status_code == 200


@pytest.mark.parametrize("change", ["disabled", "optout", "epoch"])
def test_eligibility_is_rechecked_at_redemption(
    make_client: ClientFactory, migrated: Engine, change: str
) -> None:
    client, human = setup(make_client, migrated)
    ask(client)
    url, code = mail(migrated)
    with migrated.begin() as conn:
        if change == "disabled":
            conn.execute(
                update(t.human).where(t.human.c.id == human).values(account_status="disabled")
            )
        elif change == "epoch":
            conn.execute(
                update(t.notification_settings)
                .where(t.notification_settings.c.human_id == human)
                .values(epoch=1)
            )
        else:
            conn.execute(
                update(t.notification_settings)
                .where(t.notification_settings.c.human_id == human)
                .values(preferences={"email": {"sign_in_link": False}})
            )
    assert client.get(url).status_code == 404
    assert (
        client.post(
            "/api/v1/auth/email-code",
            json={"code": code},
            headers={"x-csrf-token": client.cookies.get("maity_csrf", "")},
        ).status_code
        == 403
    )


def test_response_sent_before_lookup(
    make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    client, _ = setup(make_client, migrated)
    seen: list[str] = []
    real = email_sign_in.deliver

    def deliver(*args: Any) -> None:
        assert seen == ["response_sent"]
        seen.append("lookup")
        real(*args)

    async def wrapped(scope: Any, receive: Any, send: Any) -> None:
        async def sent(message: Any) -> None:
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                seen.append("response_sent")
            await send(message)

        await client.app(scope, receive, sent)

    monkeypatch.setattr(email_sign_in, "deliver", deliver)
    response = TestClient(wrapped, base_url="https://hub.example").post(
        "/api/v1/auth/email-link", json={"address": "ada@example.com"}
    )
    assert response.status_code == 202
    assert seen == ["response_sent", "lookup"]
    mail(migrated)


def test_older_background_job_does_not_replace_newer_used_flow(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    hub = client.app.state.settings
    now = clock.now()
    email_sign_in.deliver(migrated, hub, "ada@example.com", "new", "203.0.113.7", "/", None, now)
    with migrated.begin() as conn:
        row = email_links.live(conn, pending="new")
        assert email_links.use(conn, row)
    email_sign_in.deliver(
        migrated,
        hub,
        "ada@example.com",
        "old",
        "203.0.113.7",
        "/",
        None,
        now - timedelta(seconds=1),
    )
    with migrated.connect() as conn:
        assert email_links.live(conn, pending="old") is None
        assert len(conn.execute(select(t.mail_outbox)).all()) == 1


def test_method_advertising_and_disabled_mail(make_client: ClientFactory, migrated: Engine) -> None:
    from maity_hub import instance_settings

    client, _ = setup(make_client, migrated)
    with migrated.begin() as conn:
        instance_settings.put(conn, "mail.enabled", False, None)
    assert client.get("/api/v1/auth/methods").json()["email_link"] is False
    assert ask(client).status_code == 202
    with migrated.connect() as conn:
        assert conn.execute(select(t.mail_outbox)).first() is None


@pytest.mark.parametrize("site", ["same-site", "cross-site"])
def test_other_sites_cannot_start_or_redeem(
    make_client: ClientFactory, migrated: Engine, site: str
) -> None:
    client, _ = setup(make_client, migrated)
    for path, body in (
        ("email-link", {"address": "ada@example.com"}),
        ("email-code", {"code": "123456"}),
    ):
        assert (
            client.post(
                "/api/v1/auth/" + path, json=body, headers={"sec-fetch-site": site}
            ).status_code
            == 403
        )


def test_password_change_voids_flow(make_client: ClientFactory, migrated: Engine) -> None:
    client, _ = setup(make_client, migrated)
    ask(client)
    url, code = mail(migrated)
    assert (
        client.post(
            "/api/v1/auth/login", json={"handle": "ada", "password": factory.PASSWORD}
        ).status_code
        == 200
    )
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    changed = client.post(
        "/api/v1/auth/password",
        json={"current": factory.PASSWORD, "new": "another long password"},
        headers={"x-csrf-token": csrf},
    )
    assert changed.status_code == 200, changed.text
    assert client.get(url).status_code == 404


def test_opt_out_then_back_in_does_not_revive_link(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    ask(client)
    url, _ = mail(migrated)
    client.post("/api/v1/auth/login", json={"handle": "ada", "password": factory.PASSWORD})
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    for on in (False, True):
        result = client.patch(
            "/api/v1/me/notification-settings",
            json={"email": {"sign_in_link": on}},
            headers={"x-csrf-token": csrf},
        )
        assert result.status_code == 200, result.text
    assert client.get(url).status_code == 404


def test_mail_factor_does_not_bypass_totp(make_client: ClientFactory, migrated: Engine) -> None:
    from datetime import UTC, datetime

    from maity_hub.auth import totp

    client, _ = setup(make_client, migrated)
    clock.set_source(lambda: datetime(2026, 10, 28, 12, 0, tzinfo=UTC))
    client.post("/api/v1/auth/login", json={"handle": "ada", "password": factory.PASSWORD})
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    headers = {"x-csrf-token": csrf}
    start = client.post("/api/v1/auth/second-factor/totp", headers=headers).json()
    secret = base64.b32decode(start["secret"] + "=" * (-len(start["secret"]) % 8))
    code = totp.code_at(secret, totp.step_of(clock.now().timestamp()))
    assert (
        client.post(
            "/api/v1/auth/second-factor/totp/confirm", json={"code": code}, headers=headers
        ).status_code
        == 200
    )
    ask(client)
    _, mailed = mail(migrated)
    result = client.post(
        "/api/v1/auth/email-code",
        json={"code": mailed},
        headers={"x-csrf-token": client.cookies.get("maity_csrf", "")},
    )
    assert result.status_code == 200, result.text
    assert result.json() == {"second_factor": "required", "expires_in": 300}
    assert "member" not in client.get("/api/v1/auth/session").json()


def test_method_off_and_on_never_revives_existing_link(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub.auth import sign_in_settings

    client, human = setup(make_client, migrated)
    assert client.get("/api/v1/auth/methods").json()["email_link"] is True
    ask(client)
    url, _ = mail(migrated)
    with migrated.begin() as conn:
        sign_in_settings.patch(conn, client.app.state.settings, {"email_link": False}, human)
    assert ask(client).status_code == 403
    with migrated.begin() as conn:
        sign_in_settings.patch(conn, client.app.state.settings, {"email_link": True}, human)
    assert client.get(url).status_code == 404


def test_existing_session_requires_csrf_but_expired_cookie_can_sign_in(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub.auth.caller import SESSION_COOKIE

    client, _ = setup(make_client, migrated)
    client.post("/api/v1/auth/login", json={"handle": "ada", "password": factory.PASSWORD})
    assert (
        client.post("/api/v1/auth/email-link", json={"address": "ada@example.com"}).status_code
        == 403
    )
    assert ask(client).status_code == 202
    _, code = mail(migrated)
    assert client.post("/api/v1/auth/email-code", json={"code": code}).status_code == 403
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE, "expired")
    assert ask(client).status_code == 202
    _, code = mail(migrated)
    assert client.post("/api/v1/auth/email-code", json={"code": code}).status_code == 200


def test_request_expiry_is_not_extended_by_delayed_background_job(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    email_sign_in.deliver(
        migrated,
        client.app.state.settings,
        "ada@example.com",
        "late",
        "203.0.113.7",
        "/",
        None,
        clock.now() - timedelta(minutes=16),
    )
    with migrated.connect() as conn:
        assert conn.execute(select(t.mail_outbox)).first() is None


def test_the_session_names_the_link_or_the_code(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """§2.6.5 tells the two apart: `email_link` for the link, `email_code` for the code."""
    client, human = setup(make_client, migrated)
    ask(client)
    url, _ = mail(migrated)
    assert client.get(url).status_code == 200  # the page sets the form cookie
    form = client.cookies.get("maity_form")
    done = client.post(
        url, data={"form": form}, headers={"sec-fetch-site": "same-origin"}, follow_redirects=False
    )
    assert done.status_code == 303, done.text
    other: Any = make_client(mail=client.app.state.settings.mail, secret_key=b"k" * 32)
    ask(other)
    _, code = mail(migrated)
    signed = other.post(
        "/api/v1/auth/email-code",
        json={"code": code},
        headers={"x-csrf-token": other.cookies.get("maity_csrf", "")},
    )
    assert signed.status_code == 200, signed.text
    with migrated.connect() as conn:
        methods = conn.execute(
            select(t.human_session.c.method).where(t.human_session.c.human_id == human)
        ).scalars()
        assert sorted(methods) == ["email_code", "email_link"]


def test_the_access_log_masks_the_sign_in_token(
    make_client: ClientFactory, migrated: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = setup(make_client, migrated)
    ask(client)
    url, _ = mail(migrated)
    token = url.removeprefix("/mail/sign-in/")
    with caplog.at_level(logging.INFO, logger="maity_hub.access"):
        assert client.get(url).status_code == 200
    lines = [r.getMessage() for r in caplog.records if r.name == "maity_hub.access"]
    assert lines and all(token not in line for line in lines)
    assert any("/mail/sign-in/…" in line for line in lines)
