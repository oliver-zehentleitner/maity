"""A human's notification settings (docs/api.md §18.4)."""

from __future__ import annotations

import base64
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import factory, flow
from tests.conftest import ClientFactory

S = "/me/notification-settings"


def signed_in(make_client: ClientFactory, engine: Engine, handle: str = "maintainer") -> flow.Human:
    with engine.begin() as conn:
        found = conn.execute(select(t.human.c.id).where(t.human.c.handle == handle)).scalar()
    human_id = found or factory.human(engine, handle)
    client = make_client()
    client.post("/api/v1/auth/login", json={"handle": handle, "password": factory.PASSWORD})
    return flow.Human(client, client.get("/api/v1/auth/session").json()["csrf_token"], human_id)


def test_the_defaults_and_who_reads_them(make_client: ClientFactory, migrated: Engine) -> None:
    owner = signed_in(make_client, migrated)
    got = owner.get(S).json()
    assert got["kinds"] == ["inbox", "chat", "mention", "security"]
    assert got["mail_available"] is False
    assert got["browser"] == {
        "enabled": False,
        "kinds": {"inbox": True, "chat": True, "mention": True, "security": True},
        "content": {"chat": False, "mention": False},
    }
    email = got["email"]
    assert email["address"] is None and email["address_status"] == "none"
    assert email["kinds"]["chat"] == {"mode": "hourly", "content": False}
    assert email["kinds"]["security"] == {"mode": "immediate"}
    assert (email["language"], email["timezone"], email["daily_at"]) == ("en", "UTC", "08:00")
    assert email["quiet_hours"] is None and email["sign_in_link"] is True
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    assert agent.get(S).json()["error"]["details"] == {"reason": "humans_only"}
    assert agent.patch(S, {}).json()["error"]["details"] == {"reason": "humans_only"}
    with migrated.begin() as conn:  # reading made no row
        assert conn.execute(select(t.notification_settings)).first() is None


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"kinds": []}, {"kinds": "read_only"}),
        ({"email": {"address_status": "verified"}}, {"email.address_status": "read_only"}),
        (
            {"email": {"kinds": {"security": {"mode": "daily"}}}},
            {"email.kinds.security": "invalid"},
        ),
        ({"email": {"kinds": {"inbox": {"content": True}}}}, {"email.kinds.inbox": "invalid"}),
        ({"email": {"kinds": {"security": {"mode": None}}}}, {"email.kinds.security": "invalid"}),
        ({"email": {"kinds": {"chat": {"mode": None}}}}, {"email.kinds.chat": "invalid"}),
        ({"email": {"kinds": {"mention": {"mode": 3}}}}, {"email.kinds.mention": "invalid"}),
        ({"email": {"timezone": "Mars/Base"}}, {"email.timezone": "invalid"}),
        ({"email": {"daily_at": "25:00"}}, {"email.daily_at": "invalid"}),
        ({"email": {"quiet_hours": {"from": "22:00"}}}, {"email.quiet_hours": "invalid"}),
        ({"email": {"language": "fr"}}, {"email.language": "invalid"}),
        ({"browser": {"kinds": {"inbox": "yes"}}}, {"browser.kinds.inbox": "invalid"}),
        ({"browser": {"content": {"inbox": True}}}, {"browser.content": "invalid"}),
        ({"browser": {"kinds": {"card": True}}}, {"browser.kinds.card": "removed_kind"}),
        ({"browser": {"kinds": {"nope": True}}}, {"browser.kinds.nope": "unknown"}),
        ({"email": {"kinds": {"ticker": {"mode": "off"}}}}, {"email.kinds.ticker": "removed_kind"}),
        ({"email": {"kinds": {"nope": {"mode": "off"}}}}, {"email.kinds.nope": "unknown"}),
        ({"push": True}, {"push": "extra_forbidden"}),
    ],
)
def test_a_refused_patch(
    make_client: ClientFactory, migrated: Engine, body: dict[str, Any], fields: dict[str, str]
) -> None:
    owner = signed_in(make_client, migrated)
    before = owner.get(S).json()
    response = owner.patch(S, body)
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == fields
    assert owner.get(S).json() == before  # nothing changed


def test_preferences_change_key_by_key(make_client: ClientFactory, migrated: Engine) -> None:
    owner = signed_in(make_client, migrated)
    got = owner.patch(
        S,
        {
            "browser": {"enabled": True, "kinds": {"chat": False}, "content": {"chat": True}},
            "email": {
                "kinds": {"chat": {"mode": "off"}},
                "timezone": "Europe/Vienna",
                "language": "de",
                "quiet_hours": {"from": "22:00", "to": "07:00"},
                "sign_in_link": False,
            },
        },
    ).json()
    assert got["browser"]["kinds"] == {
        "inbox": True,
        "chat": False,
        "mention": True,
        "security": True,
    }
    assert got["browser"]["enabled"] is True and got["browser"]["content"]["chat"] is True
    assert got["email"]["kinds"]["chat"] == {"mode": "off", "content": False}
    assert got["email"]["kinds"]["mention"] == {"mode": "immediate", "content": False}
    assert got["email"]["timezone"] == "Europe/Vienna" and got["email"]["language"] == "de"
    assert got["email"]["quiet_hours"] == {"from": "22:00", "to": "07:00"}
    assert got["email"]["sign_in_link"] is False
    assert owner.get(S).json() == got
    # A second change leaves the first alone.
    again = owner.patch(S, {"email": {"kinds": {"chat": {"content": True}}}}).json()
    assert again["email"]["kinds"]["chat"] == {"mode": "off", "content": True}
    assert again["email"]["language"] == "de"


def test_the_settings_are_per_human(make_client: ClientFactory, migrated: Engine) -> None:
    first = signed_in(make_client, migrated)
    second = signed_in(make_client, migrated, "someone")
    first.patch(S, {"email": {"language": "de"}})
    assert second.get(S).json()["email"]["language"] == "en"


def test_kinds_removed_on_2026_10_26_are_dropped_on_read_and_deleted_on_patch(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = signed_in(make_client, migrated)
    stored = {
        "browser": {"kinds": {"card": True, "chat": False}, "content": {"chat": True}},
        "email": {"kinds": {"ticker": {"mode": "off"}, "inbox": {"mode": "daily"}}},
    }
    with migrated.begin() as conn:
        conn.execute(
            t.notification_settings.insert().values(
                human_id=owner.id,
                preferences=stored,
                address_status="none",
                epoch=0,
                hard_failures=0,
                updated_at=clock.now(),
            )
        )
    got = owner.get(S).json()
    assert "card" not in got["browser"]["kinds"] and got["browser"]["kinds"]["chat"] is False
    assert (
        "ticker" not in got["email"]["kinds"] and got["email"]["kinds"]["inbox"]["mode"] == "daily"
    )
    assert got["kinds"] == ["inbox", "chat", "mention", "security"]
    with migrated.begin() as conn:  # a GET writes nothing
        kept = conn.execute(select(t.notification_settings.c.preferences)).scalar_one()
    assert "card" in kept["browser"]["kinds"] and "ticker" in kept["email"]["kinds"]
    owner.patch(S, {"email": {"language": "de"}})
    with migrated.begin() as conn:
        kept = conn.execute(select(t.notification_settings.c.preferences)).scalar_one()
    assert kept["browser"]["kinds"] == {"chat": False}
    assert kept["email"]["kinds"] == {"inbox": {"mode": "daily"}}
    assert kept["email"]["language"] == "de"


def test_mail_available_follows_the_instance_settings(
    make_client: ClientFactory, migrated: Engine
) -> None:
    hub = Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite://",
            "MAITY_SMTP_HOST": "127.0.0.1",
            "MAITY_SMTP_PORT": "25",
            "MAITY_SMTP_TLS": "none",
            "MAITY_SMTP_FROM": "Maity <maity@example.org>",
            "MAITY_MAIL_SIGNING_KEY": base64.b64encode(b"s" * 32).decode(),
        }
    )
    human_id = factory.human(migrated, "maintainer")
    client = make_client(mail=hub.mail)
    client.post("/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD})
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    owner = flow.Human(client, csrf, human_id)
    assert owner.get(S).json()["mail_available"] is True


def test_a_stored_content_of_another_kind_is_not_read() -> None:
    from maity_hub.notifications import preferences

    merged = preferences._merged({"browser": {"content": {"chat": True, "inbox": True}}})
    assert "inbox" not in merged["browser"]["content"]
    assert merged["browser"]["content"]["chat"] is True


def test_a_patch_hit_by_a_deadlock_runs_again(
    make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    from maity_hub.notifications import preferences

    class Deadlock(Exception):
        sqlstate = "40001"

    owner = flow.human(make_client, migrated)
    real = preferences.patch
    calls: list[int] = []

    def flaky(*args: Any, **kwargs: Any) -> int:
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError("stmt", {}, Deadlock())
        return real(*args, **kwargs)

    monkeypatch.setattr(preferences, "patch", flaky)
    answer = owner.patch(S, {"browser": {"enabled": True}})
    assert answer.status_code == 200 and answer.json()["browser"]["enabled"] is True
    assert len(calls) == 2
