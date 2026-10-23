"""Notification settings, verified addresses and the mail links (docs/api.md §18.4, §18.6),
and the mail outbox (§16.2)."""

from __future__ import annotations

import base64
import re
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import instance_settings as store
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.errors import ApiError
from maity_hub.mail import outbox
from maity_hub.notifications import preferences
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.smtpfake import FakeSmtp, Script

S = "/me/notification-settings"
SIGNING = base64.b64encode(b"s" * 32).decode()


def mail_env(port: int = 25) -> Settings:
    return Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite://",
            "MAITY_SMTP_HOST": "127.0.0.1",
            "MAITY_SMTP_PORT": str(port),
            "MAITY_SMTP_TLS": "none",
            "MAITY_SMTP_FROM": "Maity <maity@example.org>",
            "MAITY_MAIL_SIGNING_KEY": SIGNING,
        }
    )


def signed_in(
    make_client: ClientFactory, engine: Engine, handle: str = "maintainer", **overrides: Any
) -> flow.Human:
    with engine.begin() as conn:
        found = conn.execute(select(t.human.c.id).where(t.human.c.handle == handle)).scalar()
    human_id = found or factory.human(engine, handle)
    client = make_client(**overrides)
    client.post("/api/v1/auth/login", json={"handle": handle, "password": factory.PASSWORD})
    return flow.Human(client, client.get("/api/v1/auth/session").json()["csrf_token"], human_id)


def with_mail(make_client: ClientFactory, engine: Engine, handle: str = "maintainer") -> flow.Human:
    hub = mail_env()
    return signed_in(make_client, engine, handle, mail=hub.mail)


def outbox_rows(engine: Engine) -> list[Any]:
    with engine.begin() as conn:
        return list(conn.execute(select(t.mail_outbox).order_by(t.mail_outbox.c.id)).all())


def link(row: Any, kind: str) -> str:
    found = re.search(rf"https://hub\.example/mail/{kind}/(\S+)", row.body)
    assert found, row.body
    return found.group(1)


def test_the_defaults_and_who_reads_them(make_client: ClientFactory, migrated: Engine) -> None:
    owner = signed_in(make_client, migrated)
    got = owner.get(S).json()
    assert got["kinds"][-1] == "security" and got["mail_available"] is False
    assert got["browser"]["kinds"]["ticker"] is False
    assert got["email"]["address_status"] == "none"
    assert got["email"]["kinds"]["chat"] == {"mode": "hourly", "content": False}
    assert got["email"]["kinds"]["security"] == {"mode": "immediate"}
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    assert agent.get(S).json()["error"]["details"] == {"reason": "humans_only"}


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"kinds": []}, {"kinds": "read_only"}),
        ({"email": {"address_status": "verified"}}, {"email.address_status": "read_only"}),
        ({"email": {"kinds": {"security": {"mode": "daily"}}}}, {"email.kinds": "invalid"}),
        ({"email": {"kinds": {"card": {"content": True}}}}, {"email.kinds": "invalid"}),
        ({"email": {"timezone": "Mars/Base"}}, {"email.timezone": "invalid"}),
        ({"email": {"daily_at": "25:00"}}, {"email.daily_at": "invalid"}),
        ({"email": {"quiet_hours": {"from": "22:00"}}}, {"email.quiet_hours": "invalid"}),
        ({"email": {"language": "fr"}}, {"email.language": "invalid"}),
        ({"email": {"address": "a@b.co, c@d.co"}}, {"email.address": "invalid"}),
        ({"browser": {"kinds": {"card": "yes"}}}, {"browser.kinds": "invalid"}),
        ({"push": True}, {"push": "extra_forbidden"}),
    ],
)
def test_a_refused_patch(
    make_client: ClientFactory, migrated: Engine, body: dict[str, Any], fields: dict[str, str]
) -> None:
    owner = signed_in(make_client, migrated)
    response = owner.patch(S, body)
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == fields


def test_preferences_change_key_by_key(make_client: ClientFactory, migrated: Engine) -> None:
    owner = signed_in(make_client, migrated)
    got = owner.patch(
        S,
        {
            "browser": {"enabled": True, "kinds": {"card": True}, "content": {"chat": True}},
            "email": {
                "kinds": {"chat": {"mode": "off"}},
                "timezone": "Europe/Vienna",
                "language": "de",
                "quiet_hours": {"from": "22:00", "to": "07:00"},
            },
        },
    ).json()
    assert got["browser"]["kinds"]["card"] is True and got["browser"]["kinds"]["inbox"] is True
    assert got["email"]["kinds"]["chat"] == {"mode": "off", "content": False}
    assert got["email"]["timezone"] == "Europe/Vienna" and got["email"]["language"] == "de"
    assert owner.get(S).json() == got


def test_an_address_needs_mail(make_client: ClientFactory, migrated: Engine) -> None:
    owner = signed_in(make_client, migrated)
    refused = owner.patch(S, {"email": {"address": "me@example.org"}})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "mail_not_configured"


def test_an_address_is_verified_by_its_link(make_client: ClientFactory, migrated: Engine) -> None:
    owner = with_mail(make_client, migrated)
    got = owner.patch(S, {"email": {"address": "me@example.org"}}).json()
    assert got["mail_available"] is True
    assert (got["email"]["address"], got["email"]["pending_address"]) == (None, "me@example.org")
    assert got["email"]["address_status"] == "pending"
    [mail] = outbox_rows(migrated)
    assert (mail.kind, mail.recipient) == ("security", "me@example.org")
    assert "maintainer" not in mail.body and "ignore this mail" in mail.body
    token = link(mail, "verify")
    page = owner.client.get(f"/mail/verify/{token}")
    assert page.status_code == 200 and "me@example.org" in page.text
    assert "set-cookie" not in page.headers
    assert owner.get(S).json()["email"]["address_status"] == "pending"  # a GET changes nothing
    confirmed = owner.client.post(f"/mail/verify/{token}")
    assert confirmed.status_code == 200
    got = owner.get(S).json()["email"]
    assert (got["address"], got["address_status"], got["pending_address"]) == (
        "me@example.org",
        "verified",
        None,
    )
    used = owner.client.post(f"/mail/verify/{token}")
    assert used.status_code == 404


def test_a_newer_link_voids_the_older(make_client: ClientFactory, migrated: Engine) -> None:
    owner = with_mail(make_client, migrated)
    owner.patch(S, {"email": {"address": "me@example.org"}})
    owner.patch(S, {"email": {"address": "me@example.org"}})
    first, second = outbox_rows(migrated)
    assert owner.client.post(f"/mail/verify/{link(first, 'verify')}").status_code == 404
    assert owner.client.post(f"/mail/verify/{link(second, 'verify')}").status_code == 200


def test_the_dashboard_confirms_only_its_own_token(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = with_mail(make_client, migrated)
    other = with_mail(make_client, migrated, "someone")
    owner.patch(S, {"email": {"address": "me@example.org"}})
    token = link(outbox_rows(migrated)[0], "verify")
    assert other.post(f"{S}/email/verify", {"token": token}).status_code == 404
    assert owner.post(f"{S}/email/verify", {"token": token}).status_code == 200


def verified(make_client: ClientFactory, engine: Engine, address: str) -> flow.Human:
    owner = with_mail(make_client, engine)
    owner.patch(S, {"email": {"address": address}})
    owner.client.post(f"/mail/verify/{link(outbox_rows(engine)[-1], 'verify')}")
    return owner


def test_changing_a_verified_address_needs_the_password(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = verified(make_client, migrated, "old@example.org")
    missing = owner.patch(S, {"email": {"address": "new@example.org"}})
    assert missing.json()["error"]["details"]["fields"] == {"current_password": "required"}
    wrong = owner.patch(
        S, {"email": {"address": "new@example.org"}, "current_password": "not it at all"}
    )
    assert wrong.json()["error"]["details"]["fields"] == {"current_password": "mismatch"}
    ok = owner.patch(
        S, {"email": {"address": "new@example.org"}, "current_password": factory.PASSWORD}
    )
    assert ok.status_code == 200
    assert ok.json()["email"]["address"] == "old@example.org"  # keeps receiving until verified
    owner.client.post(f"/mail/verify/{link(outbox_rows(migrated)[-1], 'verify')}")
    notice = outbox_rows(migrated)[-1]
    assert notice.recipient == "old@example.org" and "n…@example.org" in notice.body
    alerts = [i for i in owner.get("/me/notifications").json()["items"] if i["kind"] == "security"]
    assert any(i["title"] == "Sign-in address changed" for i in alerts)


def test_removing_the_address_voids_unsubscribe_links(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = verified(make_client, migrated, "me@example.org")
    with migrated.begin() as conn:
        epoch = preferences.row_of(conn, owner.id).epoch
    token = preferences.unsubscribe_token(b"s" * 32, owner.id, "card", epoch)
    assert owner.client.get(f"/mail/unsubscribe/{token}").status_code == 200
    owner.patch(S, {"email": {"address": None}, "current_password": factory.PASSWORD})
    assert owner.get(S).json()["email"]["address_status"] == "none"
    assert owner.client.post(f"/mail/unsubscribe/{token}").status_code == 404
    assert outbox_rows(migrated)[-1].recipient == "me@example.org"  # the notice


def test_one_click_unsubscribe(make_client: ClientFactory, migrated: Engine) -> None:
    owner = verified(make_client, migrated, "me@example.org")
    with migrated.begin() as conn:
        epoch = preferences.row_of(conn, owner.id).epoch
    token = preferences.unsubscribe_token(b"s" * 32, owner.id, "ticker", epoch)
    page = owner.client.get(f"/mail/unsubscribe/{token}")
    assert "ticker" in page.text
    assert owner.get(S).json()["email"]["kinds"]["ticker"]["mode"] == "daily"
    done = owner.client.post(
        f"/mail/unsubscribe/{token}",
        content="List-Unsubscribe=One-Click",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert done.status_code == 200
    assert owner.get(S).json()["email"]["kinds"]["ticker"]["mode"] == "off"
    assert owner.client.get("/mail/unsubscribe/forged.token").status_code == 404


def test_a_human_without_a_password_needs_an_old_session(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """No account has no password yet (the accounts design adds them); the rule is
    there for when one does, and is driven here directly."""
    owner = verified(make_client, migrated, "old@example.org")
    hub = mail_env()

    with migrated.begin() as conn:
        session = conn.execute(
            select(t.human_session).order_by(t.human_session.c.created_at)
        ).all()[-1]
        human = SimpleNamespace(id=owner.id, handle="maintainer", password_hash=None)
        status = preferences.patch(
            conn,
            human=human,
            session=session,
            body={"email": {"address": "new@example.org"}},
            signing_key=hub.mail.signing_key,
            public_url="https://hub.example",
            mail_ready=True,
            wrong_password=lambda: None,
        )
        assert status == 202
        change = preferences.view(conn, owner.id, True)["email"]["address_change"]
        assert change["address"] == "new@example.org" and change["id"].startswith("adc-")
        with pytest.raises(ApiError) as too_new:
            preferences.decide_held(
                conn, human=human, session=session, change_id=change["id"],
                address=change["address"], approve=True, signing_key=None, public_url="",
            )  # fmt: skip
        assert too_new.value.details == {"reason": "session_too_new"}
        with pytest.raises(ApiError) as wrong:
            preferences.decide_held(
                conn, human=human, session=session, change_id="adc-other",
                address=change["address"], approve=False, signing_key=None, public_url="",
            )  # fmt: skip
        assert wrong.value.code == "conflict"
        preferences.decide_held(
            conn, human=human, session=session, change_id=change["id"],
            address=change["address"], approve=False, signing_key=None, public_url="",
        )  # fmt: skip
        assert "address_change" not in preferences.view(conn, owner.id, True)["email"]


def test_content_reaches_the_bell_only_when_asked(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = signed_in(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    agent.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": "line one\nline two"})
    chat = next(i for i in owner.get("/me/notifications").json()["items"] if i["kind"] == "chat")
    assert "content" not in chat
    owner.patch(S, {"browser": {"content": {"chat": True}}})
    chat = next(i for i in owner.get("/me/notifications").json()["items"] if i["kind"] == "chat")
    assert chat["content"] == "line one line two"


def test_the_log_masks_mail_tokens(
    make_client: ClientFactory, migrated: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    with caplog.at_level("INFO", logger="maity_hub.access"):
        client.get("/mail/verify/secret-token-value")
    assert all("secret-token-value" not in r.getMessage() for r in caplog.records)


# --- the outbox ----------------------------------------------------------------------


def test_the_outbox_sends_and_counts(migrated: Engine) -> None:
    server = FakeSmtp(Script())
    try:
        hub = mail_env(server.port)
        with migrated.begin() as conn:
            outbox.enqueue(conn, kind="security", to="me@example.org", subject="s", body="b\n")
        assert outbox.send_due(migrated, hub.mail, None) == 1
        assert server.record.commands[-2] == "DATA"
        with migrated.begin() as conn:
            assert conn.execute(select(t.mail_outbox.c.status)).scalar() == "sent"
            delivery = conn.execute(select(t.mail_delivery)).one()
        assert (delivery.kind, delivery.outcome) == ("security", "sent")
    finally:
        server.close()


def test_security_mail_over_its_budget_waits(migrated: Engine) -> None:
    hub = mail_env(1)  # nothing listens: nothing may be tried either
    with migrated.begin() as conn:
        store.put(conn, "mail.security_max_per_hour", 1, None)
        conn.execute(
            t.mail_delivery.insert().values(kind="security", outcome="sent", at=clock.now())
        )
        outbox.enqueue(conn, kind="security", to="me@example.org", subject="s", body="b\n")
    assert outbox.send_due(migrated, hub.mail, None) == 0
    with migrated.begin() as conn:
        row = conn.execute(select(t.mail_outbox)).one()
    assert row.status == "waiting" and row.attempts == 0


def test_disabled_mail_holds_the_outbox(migrated: Engine) -> None:
    hub = mail_env(1)
    with migrated.begin() as conn:
        store.put(conn, "mail.enabled", False, None)
        outbox.enqueue(conn, kind="security", to="me@example.org", subject="s", body="b\n")
    assert outbox.send_due(migrated, hub.mail, None) == 0
