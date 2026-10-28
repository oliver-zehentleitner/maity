"""A human's address: verification, change, removal, held changes, hard failures and
one account per address (docs/api.md §18.4, §18.7)."""

from __future__ import annotations

import base64
import re
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.errors import ApiError
from maity_hub.mail import outbox
from maity_hub.notifications import preferences, tokens
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
    token = preferences.unsubscribe_token(b"s" * 32, owner.id, "chat", epoch)
    assert owner.client.get(f"/mail/unsubscribe/{token}").status_code == 200
    owner.patch(S, {"email": {"address": None}, "current_password": factory.PASSWORD})
    assert owner.get(S).json()["email"]["address_status"] == "none"
    assert owner.client.post(f"/mail/unsubscribe/{token}").status_code == 404
    assert outbox_rows(migrated)[-1].recipient == "me@example.org"  # the notice


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
            password_blocked=lambda: 0,
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


def test_three_hard_failures_disable_the_address(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = verified(make_client, migrated, "me@example.org")
    with migrated.begin() as conn:  # the verification mail is out of the way
        conn.execute(update(t.mail_outbox).values(status="sent"))
    server = FakeSmtp(Script(rcpt_reply="550 5.1.1 no such user"))
    try:
        hub = mail_env(server.port)
        for _ in range(3):
            with migrated.begin() as conn:
                outbox.enqueue(
                    conn, kind="security", human_id=owner.id, to="me@example.org",
                    subject="s", body="b\n",
                )  # fmt: skip
            server.close()
            server = FakeSmtp(Script(rcpt_reply="550 5.1.1 no such user"))
            hub = mail_env(server.port)
            outbox.send_due(migrated, hub.mail, None)
    finally:
        server.close()
    got = owner.get(S).json()["email"]
    assert (got["address_status"], got["hard_failures"]) == ("disabled", 3)
    assert got["disabled_at"] is not None
    waiting = [i for i in owner.get("/me/notifications").json()["items"] if i["kind"] == "inbox"]
    assert waiting and waiting[0]["title"] == "Mail to me@example.org disabled after 3 failures"


def test_a_delivery_resets_the_failures(make_client: ClientFactory, migrated: Engine) -> None:
    owner = verified(make_client, migrated, "me@example.org")
    with migrated.begin() as conn:
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == owner.id)
            .values(hard_failures=2)
        )
        outbox.enqueue(
            conn, kind="security", human_id=owner.id, to="me@example.org", subject="s", body="b\n"
        )
    server = FakeSmtp(Script())
    try:
        outbox.send_due(migrated, mail_env(server.port).mail, None)
    finally:
        server.close()
    assert owner.get(S).json()["email"]["hard_failures"] == 0


def test_a_verify_link_expires(make_client: ClientFactory, migrated: Engine) -> None:
    owner = with_mail(make_client, migrated)
    owner.patch(S, {"email": {"address": "me@example.org"}})
    token = link(outbox_rows(migrated)[-1], "verify")
    now = clock.now()
    clock.set_source(lambda: now + timedelta(hours=24, seconds=1))
    assert owner.client.post(f"/mail/verify/{token}").status_code == 404


def test_a_verify_token_binds_the_pending_address(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = with_mail(make_client, migrated)
    owner.patch(S, {"email": {"address": "me@example.org"}})
    with migrated.begin() as conn:
        row = preferences.row_of(conn, owner.id)
    other = tokens.make(
        b"s" * 32,
        {"h": owner.id, "p": "verify", "a": "attacker@example.org", "n": row.pending_nonce,
         "x": int((clock.now() + timedelta(hours=1)).timestamp())},
    )  # fmt: skip
    assert owner.client.post(f"/mail/verify/{other}").status_code == 404
    assert owner.get(S).json()["email"]["address"] is None


def test_only_a_session_in_good_standing_decides_or_replaces_a_held_change(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = verified(make_client, migrated, "old@example.org")
    hub = mail_env()
    human = SimpleNamespace(id=owner.id, handle="maintainer", password_hash=None)
    weak = SimpleNamespace(
        public_id="hss-weak",
        method="device_code",
        second_factor=None,  # a sign-in without the second factor (§2.8.2)
        created_at=clock.now() - timedelta(days=3),
    )
    with migrated.begin() as conn:
        strong = conn.execute(select(t.human_session)).first()
        kwargs: dict[str, Any] = dict(
            signing_key=hub.mail.signing_key, public_url="https://hub.example", mail_ready=True,
            wrong_password=lambda: None, password_blocked=lambda: 0,
        )  # fmt: skip
        assert preferences.patch(
            conn, human=human, session=strong, body={"email": {"address": "a@example.org"}},
            **kwargs,
        ) == 202  # fmt: skip
        change = preferences.view(conn, owner.id, True)["email"]["address_change"]
        with pytest.raises(ApiError) as replaced:
            preferences.patch(
                conn, human=human, session=weak, body={"email": {"address": "b@example.org"}},
                **kwargs,
            )  # fmt: skip
        assert replaced.value.details == {"reason": "not_in_good_standing"}
        with pytest.raises(ApiError) as decided:
            preferences.decide_held(
                conn, human=human, session=weak, change_id=change["id"],
                address=change["address"], approve=True, signing_key=None, public_url="",
            )  # fmt: skip
        assert decided.value.details == {"reason": "not_in_good_standing"}


def test_only_the_verified_address_in_use_counts_failures(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = verified(make_client, migrated, "me@example.org")
    owner.patch(S, {"email": {"address": "new@example.org"}, "current_password": factory.PASSWORD})
    with migrated.begin() as conn:  # only the verification mail to the new address waits
        conn.execute(
            update(t.mail_outbox)
            .where(t.mail_outbox.c.recipient != "new@example.org")
            .values(status="sent")
        )
    for _ in range(3):
        with migrated.begin() as conn:
            conn.execute(
                update(t.mail_outbox)
                .where(t.mail_outbox.c.recipient == "new@example.org")
                .values(status="waiting", not_before=clock.now())
            )
        server = FakeSmtp(Script(rcpt_reply="550 5.1.1 no such user"))
        try:
            outbox.send_due(migrated, mail_env(server.port).mail, None)
        finally:
            server.close()
    got = owner.get(S).json()["email"]
    assert (got["address_status"], got["hard_failures"]) == ("verified", 0)


def test_one_account_per_address(make_client: ClientFactory, migrated: Engine) -> None:
    first = with_mail(make_client, migrated)
    second = with_mail(make_client, migrated, "someone")
    first.patch(S, {"email": {"address": "Shared@Example.org"}})
    second.patch(S, {"email": {"address": "shared@example.org"}})
    first_link, second_link = (link(row, "verify") for row in outbox_rows(migrated)[-2:])
    assert first.client.post(f"/mail/verify/{first_link}").status_code == 200
    # The other account's link for the same address, any case, no longer works.
    assert second.client.post(f"/mail/verify/{second_link}").status_code == 404
    got = second.get(S).json()["email"]
    assert (got["address"], got["pending_address"]) == (None, "shared@example.org")
    with migrated.begin() as conn:
        normalized = conn.execute(
            select(t.notification_settings.c.address_normalized).where(
                t.notification_settings.c.human_id == first.id
            )
        ).scalar_one()
    assert normalized == "shared@example.org"
    # Removing it frees the address for the other account.
    first.patch(S, {"email": {"address": None}, "current_password": factory.PASSWORD})
    second.patch(S, {"email": {"address": "shared@example.org"}})
    assert (
        second.client.post(f"/mail/verify/{link(outbox_rows(migrated)[-1], 'verify')}").status_code
        == 200
    )


# --- a registration claims its address (§2.7.1) -----------------------------------------


def test_a_registration_claims_its_address_once(migrated: Engine) -> None:
    from maity_hub import registration_accounts

    first = factory.human(migrated, "first")
    second = factory.human(migrated, "second")
    with migrated.begin() as conn:
        assert registration_accounts.claim_address(conn, "ada@example.com", first) is True
        assert registration_accounts.claim_address(conn, "ada@example.com", second) is False
        assert preferences.has_verified_address(conn, "ada@example.com") is True
        assert preferences.has_verified_address(conn, "grace@example.com") is False
        view = preferences.view(conn, first, True)["email"]
    assert (view["address"], view["address_status"]) == ("ada@example.com", "verified")
    assert view["verified_at"] is not None and view["hard_failures"] == 0
    with migrated.begin() as conn:  # the loser has no settings row and no address
        assert (
            conn.execute(
                select(t.notification_settings).where(t.notification_settings.c.human_id == second)
            ).first()
            is None
        )


def test_a_claimed_address_blocks_a_verification_for_another_account(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub import registration_accounts

    holder = factory.human(migrated, "holder")
    with migrated.begin() as conn:
        assert registration_accounts.claim_address(conn, "shared@example.org", holder)
    owner = with_mail(make_client, migrated)
    owner.patch(S, {"email": {"address": "Shared@Example.org"}})
    token = link(outbox_rows(migrated)[-1], "verify")
    assert owner.client.post(f"/mail/verify/{token}").status_code == 404
    assert owner.get(S).json()["email"]["address"] is None


# --- what H found in #484 ----------------------------------------------------------------


def disabled(make_client: ClientFactory, engine: Engine) -> flow.Human:
    owner = verified(make_client, engine, "me@example.org")
    with engine.begin() as conn:
        conn.execute(update(t.mail_outbox).values(status="sent"))
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == owner.id)
            .values(address_status="disabled", hard_failures=3, disabled_at=clock.now())
        )
    return owner


def test_nothing_is_sent_to_a_disabled_address(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = disabled(make_client, migrated)
    server = FakeSmtp(Script())
    try:
        with migrated.begin() as conn:
            outbox.enqueue(
                conn, kind="security", human_id=owner.id, to="me@example.org", subject="s", body="b"
            )
        assert outbox.send_due(migrated, mail_env(server.port).mail, None) == 0
        assert server.record.commands == []  # nothing even connected
    finally:
        server.close()
    assert outbox_rows(migrated)[-1].status == "dropped"


def test_the_rest_of_a_batch_stops_after_the_third_failure(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = verified(make_client, migrated, "me@example.org")
    with migrated.begin() as conn:
        conn.execute(update(t.mail_outbox).values(status="sent"))
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == owner.id)
            .values(hard_failures=2)
        )
        for _ in range(3):
            outbox.enqueue(
                conn, kind="security", human_id=owner.id, to="me@example.org", subject="s", body="b"
            )
    server = FakeSmtp(Script(rcpt_reply="550 5.1.1 no such user"))
    try:
        outbox.send_due(migrated, mail_env(server.port).mail, None)
    finally:
        server.close()
    statuses = [r.status for r in outbox_rows(migrated)[-3:]]
    assert statuses == ["failed", "dropped", "dropped"]  # the first disabled it
    assert owner.get(S).json()["email"]["address_status"] == "disabled"


def test_mail_to_another_address_of_the_human_still_goes(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """The notice to the old address after a change is not mail to the disabled one."""
    owner = disabled(make_client, migrated)
    server = FakeSmtp(Script())
    try:
        with migrated.begin() as conn:
            outbox.enqueue(
                conn,
                kind="security",
                human_id=owner.id,
                to="old@example.org",
                subject="s",
                body="b",
            )
        assert outbox.send_due(migrated, mail_env(server.port).mail, None) == 1
    finally:
        server.close()


def test_setting_a_disabled_address_again_sends_its_link_and_enables_it(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = disabled(make_client, migrated)
    owner.patch(S, {"email": {"address": "me@example.org"}, "current_password": factory.PASSWORD})
    link_mail = outbox_rows(migrated)[-1]
    assert (link_mail.recipient, link_mail.status) == ("me@example.org", "waiting")
    server = FakeSmtp(Script())
    try:
        assert outbox.send_due(migrated, mail_env(server.port).mail, None) == 1
    finally:
        server.close()
    owner.client.post(f"/mail/verify/{link(link_mail, 'verify')}")
    got = owner.get(S).json()["email"]
    assert (got["address_status"], got["hard_failures"]) == ("verified", 0)


def test_setting_a_disabled_address_again_enables_no_ordinary_mail(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """Only the confirmation link goes to the address being set again; the address stays
    disabled, and nothing else reaches it, until the link is used (§18.7)."""
    owner = disabled(make_client, migrated)
    owner.patch(S, {"email": {"address": "me@example.org"}, "current_password": factory.PASSWORD})
    [link_mail] = [r for r in outbox_rows(migrated) if r.status == "waiting"]
    with migrated.begin() as conn:
        outbox.enqueue(
            conn, kind="security", human_id=owner.id, to="me@example.org", subject="s", body="b"
        )
    server = FakeSmtp(Script())
    try:
        assert outbox.send_due(migrated, mail_env(server.port).mail, None) == 1
        assert b"s" in server.record.data  # something was sent: the confirmation link
    finally:
        server.close()
    rows = outbox_rows(migrated)
    assert [r.status for r in rows[-2:]] == ["sent", "dropped"]
    assert rows[-2].id == link_mail.id
    assert owner.get(S).json()["email"]["address_status"] == "disabled"  # until the link is used
    assert "_purpose" not in server.record.data.decode(errors="replace")  # never a header
    owner.client.post(f"/mail/verify/{link(link_mail, 'verify')}")
    assert owner.get(S).json()["email"]["address_status"] == "verified"


def test_the_confirmation_link_is_marked_and_the_mark_is_never_a_header(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = with_mail(make_client, migrated)
    owner.patch(S, {"email": {"address": "new@example.org"}})
    [mail] = outbox_rows(migrated)
    assert (mail.recipient, mail.headers) == ("new@example.org", {"_purpose": "verify"})
    server = FakeSmtp(Script())
    try:
        assert outbox.send_due(migrated, mail_env(server.port).mail, None) == 1
    finally:
        server.close()
    assert "_purpose" not in server.record.data.decode(errors="replace")
