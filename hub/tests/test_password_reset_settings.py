"""docs/api.md §2.10, the settings of the reset: the instance's switch and the human's, the
reset mails' own budget, and the password generation with what a new password voids. The
routes and the mail are tests/test_password_reset.py."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import password_resets, sign_in_settings
from maity_hub.config import ConfigError, Settings
from maity_hub.instance_settings import put
from maity_hub.mail import outbox
from maity_hub.mail import settings as mail_settings
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_email_sign_in import setup

SIGN_IN = "/admin/settings/sign-in"
SETTINGS = "/api/v1/me/notification-settings"


def open_link(engine: Engine, human_id: str, nonce_hash: str = "a" * 64) -> None:
    now = clock.now()
    with engine.begin() as conn:
        conn.execute(
            insert(t.password_reset).values(
                nonce_hash=nonce_hash, human_id=human_id, source="198.51.100.7",
                created_at=now, expires_at=now + timedelta(minutes=30),
            )
        )  # fmt: skip


def is_open(engine: Engine, nonce_hash: str = "a" * 64) -> bool:
    with engine.connect() as conn:
        used = conn.execute(
            select(t.password_reset.c.used_at).where(t.password_reset.c.nonce_hash == nonce_hash)
        ).one()[0]
    return used is None


def generation(engine: Engine, human_id: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                select(t.human.c.password_generation).where(t.human.c.id == human_id)
            ).scalar_one()
        )


def signed_in(client: Any, handle: str = "ada") -> dict[str, str]:
    factory.login_handle(client, handle)
    return {"x-csrf-token": client.get("/api/v1/auth/session").json()["csrf_token"]}


# --- the instance's switch (§2.6.6) ------------------------------------------------------


def test_the_methods_offer_the_reset_as_the_settings_say(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    methods = client.get("/api/v1/auth/methods").json()
    assert methods["password_reset"] is True
    # Offered under `second_factor: email` too, unlike the sign-in link (§2.10).
    with migrated.begin() as conn:
        put(conn, "sign_in.second_factor", "email", None)
    methods = client.get("/api/v1/auth/methods").json()
    assert (methods["email_link"], methods["password_reset"]) == (False, True)
    with migrated.begin() as conn:
        sign_in_settings.patch(conn, client.app.state.settings, {"password_reset": False}, human)
        got = sign_in_settings.view(conn, client.app.state.settings)
    assert got["password_reset_missing"] == ["switched_off"]
    assert client.get("/api/v1/auth/methods").json()["password_reset"] is False


def test_the_admin_switches_the_reset_and_the_environment_wins(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    changed = owner.patch(SIGN_IN, {"password_reset": False}).json()
    assert changed["password_reset"] == {"value": False, "source": "admin"}
    assert changed["password_reset_missing"][0] == "switched_off"
    assert owner.patch(SIGN_IN, {"password_reset": "no"}).json()["error"]["details"]["fields"] == {
        "password_reset": "invalid"
    }
    back = owner.patch(SIGN_IN, {"password_reset": None}).json()
    assert back["password_reset"] == {"value": True, "source": "default"}
    client = make_client(sign_in_password_reset=False)
    factory.login_handle(client, "maintainer")
    by_env = flow.Human(client, client.get("/api/v1/auth/session").json()["csrf_token"], "")
    assert by_env.get(SIGN_IN).json()["password_reset"] == {"value": False, "source": "env"}
    refused = by_env.patch(SIGN_IN, {"password_reset": True})
    assert refused.json()["error"]["details"]["fields"] == {"password_reset": "set_by_environment"}


def test_the_reset_switch_in_the_environment_must_be_a_flag() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"MAITY_SIGN_IN_PASSWORD_RESET": "maybe"})
    assert Settings.from_env({"MAITY_SIGN_IN_PASSWORD_RESET": "0"}).sign_in_password_reset is False
    assert Settings.from_env({}).sign_in_password_reset is None


def test_turning_the_reset_off_voids_every_open_link_and_on_again_revives_none(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    other = factory.human(migrated, "other")
    open_link(migrated, other)
    assert owner.patch(SIGN_IN, {"device_code": False}).status_code == 200
    assert is_open(migrated)  # another switch leaves the links alone
    assert owner.patch(SIGN_IN, {"password_reset": False}).status_code == 200
    assert not is_open(migrated)
    assert owner.patch(SIGN_IN, {"password_reset": True}).status_code == 200
    assert not is_open(migrated)


def test_a_reset_the_environment_switched_off_voids_the_open_links_at_start(
    make_client: ClientFactory, migrated: Engine
) -> None:
    human = factory.human(migrated, "ada")
    open_link(migrated, human)
    make_client()
    assert is_open(migrated)
    make_client(sign_in_password_reset=False)
    assert not is_open(migrated)


# --- the human's switch (§18.4) ----------------------------------------------------------


def test_the_humans_switch_is_on_by_default_and_off_voids_their_open_link(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    other = factory.human(migrated, "other")
    open_link(migrated, human)
    open_link(migrated, other, "b" * 64)
    headers = signed_in(client)
    assert client.get(SETTINGS).json()["email"]["password_reset"] is True
    refused = client.patch(SETTINGS, json={"email": {"password_reset": "no"}}, headers=headers)
    assert refused.json()["error"]["details"]["fields"] == {"email.password_reset": "invalid"}
    assert is_open(migrated)
    # The sign-in link's switch is its own and leaves the reset alone.
    off = client.patch(SETTINGS, json={"email": {"sign_in_link": False}}, headers=headers)
    assert off.status_code == 200, off.text
    assert is_open(migrated)
    off = client.patch(SETTINGS, json={"email": {"password_reset": False}}, headers=headers)
    assert off.status_code == 200, off.text
    assert off.json()["email"]["password_reset"] is False
    assert not is_open(migrated) and is_open(migrated, "b" * 64)
    on = client.patch(SETTINGS, json={"email": {"password_reset": True}}, headers=headers)
    assert on.json()["email"]["password_reset"] is True
    assert not is_open(migrated)


def test_removing_the_address_voids_the_open_reset_links(
    make_client: ClientFactory, migrated: Engine
) -> None:
    factory.human(migrated, "maintainer")  # the instance admin, whose address cannot go
    client, human = setup(make_client, migrated)
    open_link(migrated, human)
    headers = signed_in(client)
    removed = client.patch(
        SETTINGS,
        json={"email": {"address": None}, "current_password": factory.PASSWORD},
        headers=headers,
    )
    assert removed.status_code == 200, removed.text
    assert not is_open(migrated)


# --- the password generation (§2.10) -----------------------------------------------------


def test_a_password_change_moves_the_generation_and_voids_links_and_a_new_address(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    other = factory.human(migrated, "other")
    open_link(migrated, human)
    open_link(migrated, other, "b" * 64)
    with migrated.begin() as conn:
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == human)
            .values(
                pending_address="next@example.com", pending_nonce="n" * 32,
                pending_expires_at=clock.now() + timedelta(hours=1),
            )
        )  # fmt: skip
    assert generation(migrated, human) == 0
    headers = signed_in(client)
    changed = client.post(
        "/api/v1/auth/password",
        json={"current": factory.PASSWORD, "new": "a new long password"},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text
    assert generation(migrated, human) == 1 and generation(migrated, other) == 0
    assert not is_open(migrated) and is_open(migrated, "b" * 64)
    with migrated.connect() as conn:
        row = conn.execute(
            select(t.notification_settings).where(t.notification_settings.c.human_id == human)
        ).one()
    assert (row.pending_address, row.pending_nonce, row.pending_expires_at) == (None, None, None)
    assert (row.address, row.address_status) == ("ada@example.com", "verified")


def test_a_refused_password_change_moves_nothing(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    open_link(migrated, human)
    headers = signed_in(client)
    wrong = client.post(
        "/api/v1/auth/password",
        json={"current": "not the password", "new": "a new long password"},
        headers=headers,
    )
    assert wrong.status_code == 400
    assert generation(migrated, human) == 0 and is_open(migrated)


def test_password_changed_moves_only_that_humans_generation(migrated: Engine) -> None:
    ada, other = factory.human(migrated, "ada"), factory.human(migrated, "other")
    with migrated.begin() as conn:
        password_resets.password_changed(conn, ada)
        password_resets.password_changed(conn, ada)
    assert (generation(migrated, ada), generation(migrated, other)) == (2, 0)


# --- the reset mails' budget (§16.2) -----------------------------------------------------


def test_the_reset_budget_is_a_setting_with_its_default_and_its_environment(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from tests.test_mail_outbox import SIGNING
    from tests.test_mail_settings import PATH, admin, env_of

    hub = env_of(MAITY_MAIL_SIGNING_KEY=SIGNING, MAITY_SMTP_HOST="smtp.example.com",
                 MAITY_SMTP_FROM="hub@example.com")  # fmt: skip
    owner = admin(make_client, migrated, hub)
    got = owner.get(PATH).json()
    assert got["password_reset_max_per_hour"] == {"value": 30, "source": "default"}
    assert got["password_reset_sent_last_hour"] == got["password_reset_dropped_last_hour"] == 0
    changed = owner.patch(PATH, {"password_reset_max_per_hour": 5}).json()
    assert changed["password_reset_max_per_hour"] == {"value": 5, "source": "admin"}
    assert owner.patch(PATH, {"password_reset_max_per_hour": 0}).status_code == 400
    by_env = env_of(MAITY_MAIL_PASSWORD_RESET_MAX_PER_HOUR="7")
    assert by_env.mail.password_reset_max_per_hour == 7
    with pytest.raises(ConfigError):
        env_of(MAITY_MAIL_PASSWORD_RESET_MAX_PER_HOUR="0")


def test_over_its_budget_a_reset_mail_is_dropped_and_no_other_kind_is(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity_hub.mail import smtp
    from tests.test_mail_outbox import mail_env

    with migrated.begin() as conn:
        put(conn, "mail.password_reset_max_per_hour", 1, None)
        for to in ("ada@example.com", "grace@example.com"):
            outbox.enqueue(conn, kind="password_reset", to=to, subject="Reset", body="link")
        outbox.enqueue(conn, kind="sign_in", to="ada@example.com", subject="Sign in", body="l")
    monkeypatch.setattr(
        smtp,
        "send",
        lambda resolved, message: smtp.Outcome(
            ok=True, stage=None, smtp_code=None, detail=None, at=clock.now()
        ),
    )
    assert outbox.send_due(migrated, mail_env(1).mail, None) == 2
    with migrated.connect() as conn:
        statuses = [
            (r.kind, r.status)
            for r in conn.execute(select(t.mail_outbox).order_by(t.mail_outbox.c.id))
        ]
        counters = mail_settings.counters(conn)
    assert statuses == [
        ("password_reset", "sent"),
        ("password_reset", "dropped"),
        ("sign_in", "sent"),
    ]
    assert (
        counters["password_reset_sent_last_hour"],
        counters["password_reset_dropped_last_hour"],
        counters["sign_in_sent_last_hour"],
        counters["sign_in_dropped_last_hour"],
    ) == (1, 1, 1, 0)
