"""The tokens in mail links and the unsubscribe page (docs/api.md §18.6)."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.notifications import preferences, tokens
from tests import factory
from tests.conftest import ClientFactory
from tests.test_join_host import JOIN

SIGNING = b"s" * 32
OTHER = b"o" * 32


def mail_hub() -> Settings:
    return Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite://",
            "MAITY_SMTP_HOST": "127.0.0.1",
            "MAITY_SMTP_PORT": "25",
            "MAITY_SMTP_TLS": "none",
            "MAITY_SMTP_FROM": "Maity <maity@example.org>",
            "MAITY_MAIL_SIGNING_KEY": base64.b64encode(SIGNING).decode(),
        }
    )


def stored(engine: Engine, human_id: str, preferences_: dict[str, Any], epoch: int = 0) -> None:
    with engine.begin() as conn:
        conn.execute(
            t.notification_settings.insert().values(
                human_id=human_id,
                preferences=preferences_,
                address_status="none",
                epoch=epoch,
                hard_failures=0,
                updated_at=clock.now(),
            )
        )


def kind_mode(engine: Engine, human_id: str, kind: str) -> str:
    with engine.begin() as conn:
        view = preferences.view(conn, human_id, False)
    return str(view["email"]["kinds"][kind]["mode"])


def link(human_id: str, kind: str = "chat", epoch: int = 0, key: bytes = SIGNING) -> str:
    return preferences.unsubscribe_token(key, human_id, kind, epoch)


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client(mail=mail_hub().mail)


# --- the token ----------------------------------------------------------------------


def test_a_token_reads_back_what_was_signed() -> None:
    token = tokens.make(SIGNING, {"h": "hum-1", "p": "unsubscribe", "k": "chat", "e": 0})
    assert tokens.read(SIGNING, token) == {"h": "hum-1", "p": "unsubscribe", "k": "chat", "e": 0}


def test_a_token_is_one_form_whatever_the_order_of_its_keys() -> None:
    assert tokens.make(SIGNING, {"a": 1, "b": 2}) == tokens.make(SIGNING, {"b": 2, "a": 1})


def test_a_token_signed_with_another_key_is_nothing() -> None:
    token = tokens.make(OTHER, {"h": "hum-1", "p": "unsubscribe"})
    assert tokens.read(SIGNING, token) is None


def test_without_a_signing_key_no_token_is_read() -> None:
    token = tokens.make(SIGNING, {"h": "hum-1"})
    assert tokens.read(None, token) is None


def test_a_changed_payload_or_mac_is_nothing() -> None:
    token = tokens.make(SIGNING, {"h": "hum-1", "p": "unsubscribe", "k": "chat", "e": 0})
    body, mac = token.split(".")
    other = base64.urlsafe_b64encode(
        json.dumps({"h": "hum-2", "p": "unsubscribe", "k": "chat", "e": 0}).encode()
    )
    assert tokens.read(SIGNING, f"{other.decode().rstrip('=')}.{mac}") is None
    assert tokens.read(SIGNING, f"{body}.{mac[:-2]}AA") is None
    assert tokens.read(SIGNING, f"{body}.") is None
    assert tokens.read(SIGNING, f".{mac}") is None


@pytest.mark.parametrize(
    "token",
    ["", ".", "a", "a.b.c", "a.b", "!!!.???", "é.é", "a" * 2000 + ".b", "e30.e30", "bm90LWpzb24"],
)
def test_malformed_tokens_are_nothing(token: str) -> None:
    assert tokens.read(SIGNING, token) is None


def test_a_signed_value_that_is_not_an_object_is_nothing() -> None:
    import hashlib
    import hmac

    body = base64.urlsafe_b64encode(b"[1,2]").decode().rstrip("=")
    mac = base64.urlsafe_b64encode(
        hmac.new(SIGNING, body.encode(), hashlib.sha256).digest()
    ).decode()
    assert tokens.read(SIGNING, f"{body}.{mac.rstrip('=')}") is None


def test_a_token_over_the_length_limit_is_nothing() -> None:
    token = tokens.make(SIGNING, {"h": "x" * 2000})
    assert len(token) > tokens.MAX_LENGTH and tokens.read(SIGNING, token) is None


# --- the page -----------------------------------------------------------------------


def test_a_get_shows_the_page_and_changes_nothing(client: TestClient, migrated: Engine) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {})
    page = client.get(f"/mail/unsubscribe/{link(human_id, 'inbox')}")
    assert page.status_code == 200 and "Stop the inbox mails" in page.text
    assert '<form method="post">' in page.text
    assert kind_mode(migrated, human_id, "inbox") == "immediate"
    assert "set-cookie" not in page.headers


def test_a_post_switches_the_kind_off_and_only_that_kind(
    client: TestClient, migrated: Engine
) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {"email": {"language": "de", "kinds": {"chat": {"mode": "daily"}}}})
    done = client.post(f"/mail/unsubscribe/{link(human_id, 'chat')}")
    assert done.status_code == 200 and "keine chat-Mails mehr" in done.text
    assert kind_mode(migrated, human_id, "chat") == "off"
    assert kind_mode(migrated, human_id, "inbox") == "immediate"
    with migrated.begin() as conn:
        kept = preferences.view(conn, human_id, False)["email"]
    assert kept["language"] == "de" and kept["kinds"]["chat"]["content"] is False
    assert "set-cookie" not in done.headers


def test_the_one_click_post_of_rfc_8058_works(client: TestClient, migrated: Engine) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {})
    done = client.post(
        f"/mail/unsubscribe/{link(human_id, 'mention')}",
        content=b"List-Unsubscribe=One-Click",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert done.status_code == 200
    assert kind_mode(migrated, human_id, "mention") == "off"


def test_the_security_kind_can_be_switched_off(client: TestClient, migrated: Engine) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {})
    assert client.post(f"/mail/unsubscribe/{link(human_id, 'security')}").status_code == 200
    assert kind_mode(migrated, human_id, "security") == "off"


def test_a_repeated_post_is_the_same_answer(client: TestClient, migrated: Engine) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {})
    token = link(human_id, "chat")
    assert client.post(f"/mail/unsubscribe/{token}").status_code == 200
    assert client.post(f"/mail/unsubscribe/{token}").status_code == 200
    assert kind_mode(migrated, human_id, "chat") == "off"


def test_a_link_from_before_the_address_changed_is_dead(
    client: TestClient, migrated: Engine
) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {}, epoch=1)
    token = link(human_id, "chat", epoch=0)
    assert client.get(f"/mail/unsubscribe/{token}").status_code == 404
    assert client.post(f"/mail/unsubscribe/{token}").status_code == 404
    assert kind_mode(migrated, human_id, "chat") == "hourly"
    assert client.get(f"/mail/unsubscribe/{link(human_id, 'chat', epoch=1)}").status_code == 200


@pytest.mark.parametrize("kind", ["card", "ticker", "system", "nope", ""])
def test_a_link_for_a_removed_or_unknown_kind_is_dead(
    client: TestClient, migrated: Engine, kind: str
) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {})
    token = link(human_id, kind)
    assert client.get(f"/mail/unsubscribe/{token}").status_code == 404
    assert client.post(f"/mail/unsubscribe/{token}").status_code == 404


def test_a_link_of_a_human_without_settings_is_dead(client: TestClient, migrated: Engine) -> None:
    human_id = factory.human(migrated, "maintainer")
    assert client.post(f"/mail/unsubscribe/{link(human_id)}").status_code == 404
    with migrated.begin() as conn:  # and the attempt made no row
        assert conn.execute(select(t.notification_settings)).first() is None


def test_a_link_of_another_purpose_or_key_is_dead(client: TestClient, migrated: Engine) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {})
    verify = tokens.make(SIGNING, {"h": human_id, "p": "verify", "k": "chat", "e": 0})
    assert client.post(f"/mail/unsubscribe/{verify}").status_code == 404
    assert client.post(f"/mail/unsubscribe/{link(human_id, key=OTHER)}").status_code == 404
    assert kind_mode(migrated, human_id, "chat") == "hourly"


def test_every_dead_link_is_the_same_page(client: TestClient, migrated: Engine) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {}, epoch=1)
    answers = {
        client.get("/mail/unsubscribe/garbage").text,
        client.get(f"/mail/unsubscribe/{link(human_id, epoch=0)}").text,
        client.get(f"/mail/unsubscribe/{link(human_id, key=OTHER, epoch=1)}").text,
        client.get(f"/mail/unsubscribe/{link(human_id, 'ticker', epoch=1)}").text,
    }
    assert len(answers) == 1 and "no longer works" in answers.pop()


def test_the_dead_page_comes_in_the_language_of_the_token_only(
    client: TestClient, migrated: Engine
) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {"email": {"language": "de"}}, epoch=1)
    own = client.get(f"/mail/unsubscribe/{link(human_id, epoch=0)}")
    assert own.status_code == 404 and "funktioniert nicht mehr" in own.text
    forged = client.get(f"/mail/unsubscribe/{link(human_id, key=OTHER, epoch=0)}")
    assert "no longer works" in forged.text  # a forged token learns nothing of the account


def test_a_hub_without_a_signing_key_has_no_working_link(
    make_client: ClientFactory, migrated: Engine
) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {})
    bare = make_client()
    assert bare.post(f"/mail/unsubscribe/{link(human_id)}").status_code == 404
    assert kind_mode(migrated, human_id, "chat") == "hourly"


def test_the_page_is_escaped_and_carries_the_headers(client: TestClient, migrated: Engine) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {})
    page = client.get(f"/mail/unsubscribe/{link(human_id, 'inbox')}")
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["x-content-type-options"] == "nosniff"


def test_the_join_host_does_not_serve_the_page(
    make_client: ClientFactory, migrated: Engine
) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {})
    joined = make_client(base_url=JOIN, join_url=JOIN, mail=mail_hub().mail)
    token = link(human_id)
    moved = joined.get(f"/mail/unsubscribe/{token}", follow_redirects=False)
    assert moved.status_code == 302
    assert joined.post(f"/mail/unsubscribe/{token}").status_code == 404
    assert kind_mode(migrated, human_id, "chat") == "hourly"


def test_the_log_masks_the_token(
    client: TestClient, migrated: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {})
    token = link(human_id)
    with caplog.at_level(logging.INFO, logger="maity_hub.access"):
        client.get(f"/mail/unsubscribe/{token}")
        client.get("/mail/verify/secret-token-value")
        client.get("/mail/second-factor-reset/secret-token-value")
    lines = [r.getMessage() for r in caplog.records if r.name == "maity_hub.access"]
    assert lines and all(token not in line and "secret-token-value" not in line for line in lines)
    assert any("/mail/unsubscribe/…" in line for line in lines)
