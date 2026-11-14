"""A password changed in the account is a security notice, mailed at once (docs/api.md §2.1,
§18.1, §18.4)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from maity_hub.notifications import mailer
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_email_sign_in import setup

PUBLIC = "https://hub.example"
NEW = "a brand new long password"
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def signed_in(make_client: ClientFactory, anonymous: Any, human_id: str) -> flow.Human:
    hub = anonymous.app.state.settings
    client = make_client(mail=hub.mail, secret_key=hub.secret_key)
    assert factory.login_handle(client, "ada").status_code == 200
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    return flow.Human(client, csrf, human_id)


def records(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.account_record).where(t.account_record.c.type == kind)).all()
        )


def change(ada: flow.Human, current: str = factory.PASSWORD) -> Any:
    return ada.client.post(
        "/api/v1/auth/password",
        json={"current": current, "new": NEW},
        headers={"X-CSRF-Token": ada.csrf, "User-Agent": FIREFOX},
    )


def test_a_changed_password_is_a_security_notice_mailed_at_once_whatever_the_mode(
    make_client: ClientFactory, migrated: Engine
) -> None:
    anonymous, human_id = setup(make_client, migrated)
    ada = signed_in(make_client, anonymous, human_id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == human_id)
            .values(preferences={"email": {"kinds": {"security": {"mode": "off"}}}})
        )
    assert change(ada).status_code == 200
    [record] = records(migrated, "password_changed")
    assert record.human_id == human_id
    assert record.data == {"ip": "203.0.113.7", "browser": "Firefox", "os": "Linux"}
    mailer.run(migrated, anonymous.app.state.settings.mail, None, PUBLIC)
    with migrated.connect() as conn:
        mails = conn.execute(select(t.mail_outbox).where(t.mail_outbox.c.kind == "security")).all()
    [mail] = [m for m in mails if "password was changed" in m.subject]
    assert mail.subject == "[Maity] Your password was changed"
    assert "Firefox on Linux, 203.0.113.7" in mail.body
    assert "Every other session has ended" in mail.body and f"{PUBLIC}/agents" in mail.body
    assert "List-Unsubscribe" not in (mail.headers or {})
    bell = ada.client.get("/api/v1/me/notifications").json()["items"]
    [item] = [i for i in bell if i["title"].startswith("Password changed")]
    assert item["kind"] == "security"
    assert item["title"] == "Password changed: Firefox on Linux, 203.0.113.7"


def test_a_refused_change_writes_no_notice(make_client: ClientFactory, migrated: Engine) -> None:
    anonymous, human_id = setup(make_client, migrated)
    ada = signed_in(make_client, anonymous, human_id)
    refused = change(ada, current="not the password at all")
    assert refused.status_code == 400
    assert records(migrated, "password_changed") == []
