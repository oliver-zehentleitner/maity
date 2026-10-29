"""The mail of a registration (docs/api.md §2.7.1): the confirmation link and the note to
an address that has an account already."""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock, registration_mail
from maity_hub import instance_settings as store
from maity_hub import tables as t
from maity_hub.mail import address as addresses
from maity_hub.mail import outbox
from maity_hub.mail import settings as mail_settings
from maity_hub.notifications import preferences, tokens
from tests import factory
from tests.conftest import ClientFactory
from tests.test_registration import SIGNING, open_hub, pending, register
from tests.test_registration import _fresh as _limits  # noqa: F401  (autouse: fresh limiters)

KEY = b"s" * 32


def mails(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(select(t.mail_outbox).order_by(t.mail_outbox.c.id)))


def test_the_confirmation_link_is_a_signed_token_with_a_nonce_kept_as_a_hash(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = open_hub(make_client, migrated)
    register(client, "Ada@Example.com", next="/#/projects")
    [row] = pending(migrated)
    [mail] = mails(migrated)
    assert (mail.kind, mail.recipient, mail.human_id) == ("registration", "Ada@Example.com", None)
    assert mail.subject == "[Maity] Confirm your address"
    found = re.search(r"https://hub\.example/mail/register/(\S+)", mail.body)
    assert found, mail.body
    payload = tokens.read(KEY, found.group(1))
    assert payload is not None
    assert (payload["p"], payload["i"]) == ("register", row.id)
    assert payload["x"] == int(row.expires_at.timestamp())
    assert hashlib.sha256(payload["n"].encode()).hexdigest() == row.nonce_hash
    assert payload["n"] not in row.nonce_hash  # the nonce itself is not stored
    # What the person needs to judge it, and nothing else: no handle, no project.
    assert "203.0.113.7" in mail.body and "24 hours" in mail.body
    assert "ignore this mail" in mail.body
    assert "Ada" not in mail.body.replace("Ada@Example.com", "")
    assert mail.headers == {}  # a reply to a request: no unsubscribe part


def test_each_request_gets_its_own_nonce(make_client: ClientFactory, migrated: Engine) -> None:
    client = open_hub(make_client, migrated)
    register(client, "ada@example.com")
    register(client, "grace@example.com")
    first, second = pending(migrated)
    assert first.nonce_hash != second.nonce_hash and first.nonce_hash and second.nonce_hash


def test_the_mail_is_in_the_language_the_request_names(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = open_hub(make_client, migrated)
    client.post(
        "/api/v1/auth/register",
        json={"address": "ada@example.com", "password": "a long enough password 1"},
        headers={"accept-language": "de-AT,de;q=0.9,en;q=0.5"},
    )
    [mail] = mails(migrated)
    assert mail.subject == "[Maity] Adresse bestätigen" and "Der Link gilt 24 Stunden" in mail.body


@pytest.mark.parametrize(
    ("header", "language"),
    [
        (None, "en"),
        ("", "en"),
        ("fr-FR,fr;q=0.9", "en"),
        ("fr, de;q=0.5", "de"),
        ("DE", "de"),
        ("en-US", "en"),
        ("*", "en"),
        ("xx; q=1, de", "de"),
    ],
)
def test_the_language_of_a_request(header: str | None, language: str) -> None:
    assert registration_mail.language_of(header) == language


def test_an_address_with_an_account_gets_a_note_and_no_link(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = open_hub(make_client, migrated)
    holder = factory.human(migrated, "holder")
    addresses.prepare(migrated, None)  # the claim below takes the lock without a route
    with migrated.begin() as conn:
        assert preferences.claim_verified(conn, "ada@example.com", holder, secret_key=None)
    client.post(
        "/api/v1/auth/register",
        json={"address": "Ada@Example.com", "password": "a long enough password 1"},
        headers={"accept-language": "de"},
    )
    assert pending(migrated) == []  # no pending registration for it
    [mail] = mails(migrated)
    assert mail.recipient == "Ada@Example.com" and mail.kind == "registration"
    assert "Du hast schon eins: melde dich an unter https://hub.example/#/login" in mail.body
    assert "mail/register" not in mail.body and "holder" not in mail.body  # no link, no handle


def test_over_its_budget_a_registration_mail_is_dropped_never_sent_late(
    make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_mail_outbox import mail_env

    client = open_hub(make_client, migrated)
    register(client, "ada@example.com")
    register(client, "grace@example.com")
    with migrated.begin() as conn:
        store.put(conn, "mail.registration_max_per_hour", 1, None)
    from maity_hub.mail import smtp

    monkeypatch.setattr(
        smtp,
        "send",
        lambda resolved, message: smtp.Outcome(
            ok=True, stage=None, smtp_code=None, detail=None, at=clock.now()
        ),
    )
    assert outbox.send_due(migrated, mail_env(1).mail, None) == 1
    statuses = [m.status for m in mails(migrated)]
    assert statuses == ["sent", "dropped"]
    with migrated.begin() as conn:
        counters = mail_settings.counters(conn)
    assert (
        counters["registration_sent_last_hour"],
        counters["registration_dropped_last_hour"],
    ) == (
        1,
        1,
    )


def test_the_registration_budget_is_a_setting_with_its_default(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from tests.test_mail_settings import PATH, admin, env_of

    hub = env_of(MAITY_MAIL_SIGNING_KEY=SIGNING, MAITY_SMTP_HOST="smtp.example.com",
                 MAITY_SMTP_FROM="hub@example.com")  # fmt: skip
    owner = admin(make_client, migrated, hub)
    got = owner.get(PATH).json()
    assert got["registration_max_per_hour"] == {"value": 30, "source": "default"}
    assert got["registration_sent_last_hour"] == 0 and got["registration_dropped_last_hour"] == 0
    changed = owner.patch(PATH, {"registration_max_per_hour": 5}).json()
    assert changed["registration_max_per_hour"] == {"value": 5, "source": "admin"}
    assert owner.patch(PATH, {"registration_max_per_hour": 0}).status_code == 400


def test_an_unknown_kind_is_refused(migrated: Engine) -> None:
    with migrated.begin() as conn, pytest.raises(ValueError):
        registration_mail.send(conn, kind="nope", to="ada@example.com")


def test_without_the_hub_nothing_is_sent(migrated: Engine) -> None:
    with migrated.begin() as conn:
        registration_mail.send(conn, kind="already_registered", to="ada@example.com")
    assert mails(migrated) == []
