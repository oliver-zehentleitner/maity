"""docs/api.md §2.8.8: mail as the second factor, with the real outbox, cookies and endpoints
(tsk-qawqnetfhn6m, the first step: the sign-in with the mail, the verify, the resend)."""

from __future__ import annotations

import base64
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import mail_factor, second_factor, sessions
from maity_hub.config import ConfigError, Settings
from maity_hub.errors import ApiError
from maity_hub.mail import address as addresses
from maity_hub.notifications import preferences
from tests import factory, flow
from tests.conftest import ClientFactory

KEY = base64.b64encode(b"s" * 32).decode()
START = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fresh() -> Any:
    mail_factor.BY_HUMAN.reset()
    clock.set_source(lambda: START)
    yield
    clock.reset()


def hub_mail() -> Any:
    return Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite://",
            "MAITY_SMTP_HOST": "smtp.example.com",
            "MAITY_SMTP_FROM": "hub@example.com",
            "MAITY_MAIL_SIGNING_KEY": KEY,
        }
    ).mail


def browser(make_client: ClientFactory, *, mail: bool = True) -> Any:
    """A client of a hub whose second factor is the mail; `mail=False`: no mail settings."""
    extra = {"mail": hub_mail()} if mail else {}
    return make_client(secret_key=b"k" * 32, sign_in_second_factor="email", **extra)


def setup(
    make_client: ClientFactory,
    engine: Engine,
    *,
    verified: bool = True,
    mail: bool = True,
    stored: bool = False,
) -> tuple[Any, str]:
    """`stored`: the setting holds `email`, not the environment, which refuses to start without
    mail settings."""
    human = factory.human(engine, "ada")
    if verified:
        addresses.prepare(engine, None)
        with engine.begin() as conn:
            assert preferences.claim_verified(conn, "ada@example.com", human, secret_key=None)
    if not stored:
        return browser(make_client, mail=mail), human
    with engine.begin() as conn:
        conn.execute(
            t.instance_setting.insert().values(
                name="sign_in.second_factor", value="email", updated_at=clock.now()
            )
        )
    extra = {"mail": hub_mail()} if mail else {}
    return make_client(secret_key=b"k" * 32, **extra), human


def login(client: TestClient) -> Any:
    return client.post("/api/v1/auth/login", json={"handle": "ada", "password": factory.PASSWORD})


def mails(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.mail_outbox)
                .where(t.mail_outbox.c.kind == "sign_in")
                .order_by(t.mail_outbox.c.id)
            )
        )


def last_mail(engine: Engine) -> tuple[str | None, str, str]:
    """The newest mail's token (None when it has no link), its code and its text."""
    row = mails(engine)[-1]
    token = re.search(r"/sign-in/second-factor/email#(\S+)", row.body)
    code = re.search(r"(\d{3}) (\d{3})", row.body)
    assert code
    return (token[1] if token else None), code[1] + code[2], row.body


def verify(client: TestClient, **body: str) -> Any:
    csrf = client.cookies.get("maity_csrf") or ""
    return client.post(
        "/api/v1/auth/second-factor/verify", json=body, headers={"x-csrf-token": csrf}
    )


def resend(client: TestClient) -> Any:
    return client.post(
        "/api/v1/auth/second-factor/email",
        headers={"x-csrf-token": (client.cookies.get("maity_csrf") or "")},
    )


def session(client: TestClient) -> dict[str, Any]:
    answer: dict[str, Any] = client.get("/api/v1/auth/session").json()
    return answer


# --- the sign-in -------------------------------------------------------------------------------


def test_a_password_sign_in_ends_in_a_second_factor_session_by_mail(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    answer = login(client)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"second_factor": "required", "via": "email", "expires_in": 900}
    shown = session(client)
    assert shown["second_factor"] == "required" and shown["via"] == "email"
    assert shown["mail"] == "sent" and "member" not in shown
    token, code, body = last_mail(migrated)
    assert token is not None and len(code) == 6
    assert "Never give this code to anyone" in body and "someone has your password" in body
    # nothing but the second step is reachable
    assert client.get("/api/v1/me").status_code == 403


def test_the_code_completes_the_sign_in_once_and_the_session_is_fresh(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    login(client)
    before = client.cookies.get("maity_session")
    _, code, _ = last_mail(migrated)
    done = verify(client, email_code=f"{code[:3]} {code[3:]}")  # spaces are ignored
    assert done.status_code == 200, done.text
    assert done.json()["member"]["handle"] == "ada"
    assert client.cookies.get("maity_session") != before
    assert client.get("/api/v1/me").status_code == 200
    with migrated.connect() as conn:
        used = conn.execute(select(t.human_session.c.second_factor)).scalars().all()
    assert "email" in used
    assert verify(client, email_code=code).status_code in (400, 403)  # used up


def test_the_token_works_only_in_the_browser_that_signed_in(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    login(client)
    token, _, _ = last_mail(migrated)
    assert token is not None
    stranger = browser(make_client)
    wrong = verify(stranger, email_token=token)
    assert wrong.status_code in (401, 403)  # no session of its own: nothing to complete
    assert verify(client, email_token="not-the-token").status_code == 403
    right = verify(client, email_token=token)
    assert right.status_code == 200, right.text
    assert right.json()["member"]["handle"] == "ada"


def test_a_resend_voids_the_earlier_link_and_code_and_is_limited_to_three(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    login(client)
    first_token, first_code, _ = last_mail(migrated)
    assert resend(client).status_code == 200
    assert len(mails(migrated)) == 2
    assert verify(client, email_code=first_code).status_code == 403  # void
    assert first_token is not None and verify(client, email_token=first_token).status_code == 403
    assert resend(client).status_code == 200
    third = resend(client)
    assert third.status_code == 429, third.text  # the first mail counted as the first of three
    # the wait is what is left of the session, not a minute after which it is refused again
    assert 60 < int(third.headers["retry-after"]) <= 900
    assert session(client)["mail"] == "rate_limited" or session(client)["mail"] == "sent"
    _, code, _ = last_mail(migrated)
    assert verify(client, email_code=code).status_code == 200


def test_five_wrong_codes_end_the_session_and_write_the_record(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    login(client)
    for _ in range(5):
        assert verify(client, email_code="000000").status_code == 403
    assert client.get("/api/v1/auth/session").status_code == 401  # the session ended
    with migrated.connect() as conn:
        kinds = (
            conn.execute(
                select(t.account_record.c.type).where(t.account_record.c.human_id == human)
            )
            .scalars()
            .all()
        )
    assert "second_factor_failed" in kinds


# --- who is asked, and what with ------------------------------------------------------------------


def test_a_human_with_totp_is_asked_for_totp_never_for_mail(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    with migrated.begin() as conn:
        conn.execute(
            t.second_factor.insert().values(
                human_id=human, secret=b"sealed", generation=1, enrolled_at=clock.now()
            )
        )
    answer = login(client)
    assert answer.json() == {"second_factor": "required", "via": "totp", "expires_in": 300}
    assert mails(migrated) == []  # no mail for the stronger factor
    assert resend(client).status_code == 403
    assert verify(client, email_code="123456").status_code == 403


def test_an_account_that_never_had_an_address_enrols_instead(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated, verified=False)
    answer = login(client)
    assert answer.json() == {"second_factor": "enrolment_required"}
    assert mails(migrated) == []


def test_an_address_that_was_verified_and_is_lost_fails_closed(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    with migrated.begin() as conn:
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == human)
            .values(address_status="disabled")
        )
    answer = login(client)
    assert answer.json() == {"second_factor": "required", "via": "email", "expires_in": 900}
    assert mails(migrated) == []  # nothing could be sent
    assert session(client)["mail"] == "unavailable"
    refused = resend(client)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "address_unverified"
    with migrated.connect() as conn:
        records = conn.execute(
            select(t.account_record.c.type, t.account_record.c.data).where(
                t.account_record.c.human_id == human
            )
        ).all()
    failed = [r for r in records if r.type == "second_factor_failed"]
    assert failed and failed[0].data["method"] == "email_unavailable"


def test_mail_that_is_not_configured_fails_closed_for_a_human_without_totp(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated, mail=False, stored=True)
    answer = login(client)
    assert answer.json()["via"] == "email"
    assert session(client)["mail"] == "unavailable"
    refused = resend(client)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "mail_not_configured"


def test_switching_away_from_email_ends_the_open_second_step(
    make_client: ClientFactory, migrated: Engine
) -> None:
    human = factory.human(migrated, "ada")
    addresses.prepare(migrated, None)
    with migrated.begin() as conn:
        assert preferences.claim_verified(conn, "ada@example.com", human, secret_key=None)
        conn.execute(  # the admin's setting, with no environment value to win over it
            t.instance_setting.insert().values(
                name="sign_in.second_factor", value="email", updated_at=clock.now()
            )
        )
    client = make_client(mail=hub_mail(), secret_key=b"k" * 32)
    login(client)
    assert session(client)["via"] == "email"
    with migrated.begin() as conn:
        conn.execute(
            update(t.instance_setting)
            .where(t.instance_setting.c.name == "sign_in.second_factor")
            .values(value="optional")
        )
    assert client.get("/api/v1/auth/session").status_code == 401  # the first factor again


def test_a_step_up_by_mail_sends_a_code_only(make_client: ClientFactory, migrated: Engine) -> None:
    client, _ = setup(make_client, migrated)
    login(client)
    _, code, _ = last_mail(migrated)
    assert verify(client, email_code=code).status_code == 200
    clock.set_source(lambda: START.replace(hour=12, minute=30))  # past the ten minutes
    needed = client.get("/api/v1/me/export")
    assert needed.status_code == 403
    assert needed.json()["error"]["details"]["reason"] == "step_up_required"
    assert resend(client).status_code == 200
    token, step_code, body = last_mail(migrated)
    assert token is None and "Open this link" not in body  # a code only, no link
    assert verify(client, email_token="x" * 43).status_code == 403  # a step-up takes no token
    valid = verify(client, email_code=step_code)
    assert valid.status_code == 200 and "valid_until" in valid.json()
    assert client.get("/api/v1/me/export").status_code == 200


def test_the_view_says_what_the_next_sign_in_asks_for(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """`GET /auth/second-factor` carries `via`: the mail for a human with an address (`null`
    when nothing is asked, tests/test_two_factor.py; §2.8.8)."""
    client, _ = setup(make_client, migrated)
    login(client)
    _, code, _ = last_mail(migrated)
    assert verify(client, email_code=code).status_code == 200
    assert client.get("/api/v1/auth/second-factor").json()["via"] == "email"


def test_a_concurrent_send_cannot_take_the_third_mail_twice(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """The limit is in the statement: a send that read two while another took the third is
    refused, not sent (the P3 of #943)."""
    client, _ = setup(make_client, migrated)
    login(client)
    assert resend(client).status_code == 200  # two sent
    hub = Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite://",
            "MAITY_SECRET_KEY": base64.b64encode(b"k" * 32).decode(),
            "MAITY_SMTP_HOST": "smtp.example.com",
            "MAITY_SMTP_FROM": "hub@example.com",
            "MAITY_MAIL_SIGNING_KEY": KEY,
        }
    )
    with migrated.begin() as conn:
        stale = conn.execute(
            select(t.human_session).where(t.human_session.c.ended_at.is_(None))
        ).one()
        assert stale.mail_sent == 2
        conn.execute(update(t.human_session).values(mail_sent=3))  # the other send came first
        with pytest.raises(ApiError) as refused:
            mail_factor.send(conn, hub, stale)
    assert refused.value.status == 429
    assert len(mails(migrated)) == 2


def test_a_step_up_takes_no_token_even_when_the_session_still_holds_one(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """§2.8.8 rule 4: the link is for the sign-in only. A full session that carries a token MAC
    (a leftover, or a bug elsewhere) does not take a step-up by it: only the code counts."""
    client, _ = setup(make_client, migrated)
    login(client)
    _, code, _ = last_mail(migrated)
    assert verify(client, email_code=code).status_code == 200
    clock.set_source(lambda: START.replace(hour=12, minute=30))  # past the ten minutes
    key = b"s" * 32
    with migrated.begin() as conn:
        id_hash = conn.execute(
            select(t.human_session.c.id_hash).where(t.human_session.c.ended_at.is_(None))
        ).scalar_one()
        conn.execute(
            update(t.human_session)
            .where(t.human_session.c.id_hash == id_hash)
            .values(
                mail_token_mac=mail_factor._token_mac(key, id_hash, "t" * 43),
                mail_code_mac=mail_factor._code_mac(key, id_hash, "123456"),
                mail_sent_at=clock.now(),
            )
        )
    refused = verify(client, email_token="t" * 43)
    assert refused.status_code == 403, refused.text
    assert verify(client, email_code="123456").status_code == 200


def test_the_step_up_is_not_held_by_the_three_of_a_second_factor_session(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    login(client)
    _, code, _ = last_mail(migrated)
    assert verify(client, email_code=code).status_code == 200
    for _ in range(4):  # a long-lived session steps up more than three times
        assert resend(client).status_code == 200
    _, step_code, _ = last_mail(migrated)
    assert verify(client, email_code=step_code).status_code == 200


def test_the_environment_takes_email_only_with_mail_ready(
    make_client: ClientFactory, migrated: Engine
) -> None:
    assert (
        Settings.from_env(
            {"MAITY_DATABASE_URL": "sqlite://", "MAITY_SIGN_IN_SECOND_FACTOR": "email"}
        ).sign_in_second_factor
        == "email"
    )
    with pytest.raises(ConfigError, match="MAITY_SIGN_IN_SECOND_FACTOR=email"):
        make_client(sign_in_second_factor="email")


def test_only_totp_and_a_recovery_code_give_standing_the_mail_does_not() -> None:
    """§2.8.2: the mail is the mailbox and gives no standing of its own."""

    def standing(method: str, factor: str | None) -> bool:
        row = SimpleNamespace(method=method, public_id="ses-x", second_factor=factor)
        return sessions.good_standing(row)

    assert standing("device_code", "email") is False
    assert standing("device_code", "totp") is True
    assert standing("device_code", "recovery_code") is True
    assert standing("password", "email") is True  # by its own first factor


def test_after_a_reset_a_human_with_a_verified_address_gets_the_mail_again(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """§2.8.3, §2.8.8: the reset went through that mailbox, so the mail is the factor, not an
    enrolment on the password alone."""
    client, human = setup(make_client, migrated)
    with migrated.begin() as conn:
        conn.execute(
            t.second_factor.insert().values(
                human_id=human, secret=None, generation=2, reset_required=True
            )
        )
    answer = login(client)
    assert answer.json() == {"second_factor": "required", "via": "email", "expires_in": 900}
    assert len(mails(migrated)) == 1


def test_after_a_reset_without_a_verified_address_the_operator_sends_it_into_enrolment(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    with migrated.begin() as conn:
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == human)
            .values(address_status="disabled")
        )
        conn.execute(
            t.second_factor.insert().values(
                human_id=human, secret=None, generation=2, reset_required=True
            )
        )
    assert login(client).json() == {"second_factor": "enrolment_required"}


def test_an_open_enrolment_session_does_not_become_full_when_the_mail_now_asks(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """The policy came to `email` while a session waited at enrolment: it ends, it is not
    promoted without any second factor (the human has a verified address)."""
    _, human = setup(make_client, migrated)
    hub = replace(
        Settings.from_env({"MAITY_DATABASE_URL": "sqlite://"}), sign_in_second_factor="email"
    )
    with migrated.begin() as conn:
        _, _, public_id = sessions.create(
            conn,
            human,
            method="password",
            address="203.0.113.5",
            user_agent=None,
            state="enrolment",
        )
    with migrated.begin() as conn:
        row = conn.execute(
            select(t.human_session).where(t.human_session.c.public_id == public_id)
        ).one()
        assert second_factor.state(conn, hub, row) == "ended"


def test_a_step_up_code_lives_fifteen_minutes_in_a_session_that_lives_for_days(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    login(client)
    _, code, _ = last_mail(migrated)
    assert verify(client, email_code=code).status_code == 200
    clock.set_source(lambda: START + timedelta(hours=2))
    assert resend(client).status_code == 200
    _, stale, _ = last_mail(migrated)
    clock.set_source(lambda: START + timedelta(hours=2, minutes=16))
    assert verify(client, email_code=stale).status_code == 403  # the code's own 15 minutes
    assert resend(client).status_code == 200
    _, fresh, _ = last_mail(migrated)
    assert verify(client, email_code=fresh).status_code == 200


# --- turning it on (§2.8.8) --------------------------------------------------------------------

CONFIRM = "/api/v1/admin/settings/sign-in/second-factor-email/confirm"
SIGN_IN = "/api/v1/admin/settings/sign-in"


def _admin(make_client: ClientFactory, engine: Engine, *, verified: bool = True) -> Any:
    human = factory.human(engine, "ada")  # the first human is the instance admin
    if verified:
        addresses.prepare(engine, None)
        with engine.begin() as conn:
            assert preferences.claim_verified(conn, "ada@example.com", human, secret_key=None)
    client = make_client(mail=hub_mail(), secret_key=b"k" * 32)
    assert login(client).status_code == 200
    return client


def _csrf(client: TestClient) -> dict[str, str]:
    return {"x-csrf-token": client.cookies.get("maity_csrf") or ""}


def _turn_on(client: TestClient) -> Any:
    return client.patch(SIGN_IN, json={"second_factor": "email"}, headers=_csrf(client))


def _confirm(client: TestClient, code: str) -> Any:
    return client.post(CONFIRM, json={"code": code}, headers=_csrf(client))


def test_turning_it_on_takes_effect_only_with_the_mailed_code(
    make_client: ClientFactory, migrated: Engine
) -> None:
    admin = _admin(make_client, migrated)
    asked = _turn_on(admin)
    assert (asked.status_code, asked.json()) == (202, {"expires_in": 900})
    assert admin.get(SIGN_IN).json()["second_factor"]["value"] != "email"
    _, code, body = last_mail(migrated)
    assert "/sign-in/" not in body
    wrong = "000000" if code != "000000" else "111111"
    refused = _confirm(admin, wrong)
    assert refused.json()["error"]["code"] == "code_invalid"
    assert admin.get(SIGN_IN).json()["second_factor"]["value"] != "email"
    done = _confirm(admin, code)
    assert done.status_code == 200, done.text
    assert done.json()["second_factor"] == {"value": "email", "source": "admin"}
    assert "second_factor_email" in done.json()["missing"]
    assert done.json()["email_link_available"] is False
    assert _confirm(admin, code).json()["error"]["code"] == "code_invalid"  # single use


def test_a_new_patch_voids_an_open_confirmation(
    make_client: ClientFactory, migrated: Engine
) -> None:
    admin = _admin(make_client, migrated)
    _turn_on(admin)
    _, code, _ = last_mail(migrated)
    moved = admin.patch(SIGN_IN, json={"second_factor": "optional"}, headers=_csrf(admin))
    assert moved.status_code == 200, moved.text
    assert _confirm(admin, code).json()["error"]["code"] == "code_invalid"
    assert admin.get(SIGN_IN).json()["second_factor"]["value"] == "optional"


def test_a_step_up_code_does_not_turn_it_on(make_client: ClientFactory, migrated: Engine) -> None:
    admin = _admin(make_client, migrated)
    _turn_on(admin)
    with migrated.begin() as conn:
        row = conn.execute(select(t.human_session)).one()
        mail_factor.send(conn, _hub(), row, with_link=False)  # overwrites the open code
    _, step_up_code, _ = last_mail(migrated)
    assert _confirm(admin, step_up_code).json()["error"]["code"] == "code_invalid"
    assert admin.get(SIGN_IN).json()["second_factor"]["value"] != "email"


def _hub() -> Any:
    return replace(Settings.from_env({"MAITY_DATABASE_URL": "sqlite://"}), mail=hub_mail())


def test_turning_it_on_needs_the_admins_verified_address(
    make_client: ClientFactory, migrated: Engine
) -> None:
    admin = _admin(make_client, migrated, verified=False)
    refused = _turn_on(admin)
    assert refused.json()["error"]["details"]["fields"] == {"second_factor": "no_verified_address"}


def test_turning_it_on_needs_the_mail_settings(
    make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.human(make_client, migrated)
    refused = admin.patch("/admin/settings/sign-in", {"second_factor": "email"})
    assert refused.json()["error"]["details"]["fields"] == {"second_factor": "mail_not_ready"}


def test_under_email_the_sign_in_link_is_off_and_answers_as_if_sent(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated, stored=True)
    assert client.get("/api/v1/auth/methods").json()["email_link"] is False
    sent = client.post("/api/v1/auth/email-link", json={"address": "ada@example.com"})
    assert sent.status_code == 202, sent.text
    assert mails(migrated) == []


def test_the_second_step_shows_the_address_masked(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    login(client)
    assert session(client)["address_hint"] == "a***@example.com"


def test_a_human_without_totp_cannot_remove_the_address_under_email(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    login(client)
    _, code, _ = last_mail(migrated)
    assert verify(client, email_code=code).status_code == 200
    answer = client.patch(
        "/api/v1/me/notification-settings",
        json={"email": {"address": None}, "current_password": factory.PASSWORD},
        headers=_csrf(client),
    )
    assert answer.status_code == 403, answer.text
    assert answer.json()["error"]["details"]["reason"] == "second_factor_required"
    with migrated.connect() as conn:
        assert mail_factor.address_of(conn, human) is not None


def test_confirming_rechecks_the_address_and_the_mail(
    make_client: ClientFactory, migrated: Engine
) -> None:
    admin = _admin(make_client, migrated)
    assert _turn_on(admin).status_code == 202
    _, code, _ = last_mail(migrated)
    with migrated.begin() as conn:
        conn.execute(update(t.notification_settings).values(address_status="disabled"))
    refused = _confirm(admin, code)
    assert refused.json()["error"]["details"]["fields"] == {"second_factor": "no_verified_address"}
    assert admin.get(SIGN_IN).json()["second_factor"]["value"] != "email"


def _enrol(engine: Engine, human: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            t.second_factor.insert().values(
                human_id=human, secret=b"x", enrolled_at=clock.now(), generation=1
            )
        )


def test_totp_stays_while_it_is_the_only_way_in(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """Under `email` without a verified address, TOTP off would lock the human out (§2.8.8)."""
    client, human = setup(make_client, migrated, verified=False, stored=True)
    hub = replace(_hub(), secret_key=b"k" * 32)
    _enrol(migrated, human)
    with migrated.connect() as conn:
        assert second_factor.view(conn, hub, human)["required"] is True
    addresses.prepare(migrated, None)
    with migrated.begin() as conn:
        assert preferences.claim_verified(conn, "ada@example.com", human, secret_key=None)
    with migrated.connect() as conn:
        assert second_factor.view(conn, hub, human)["required"] is False
    with migrated.begin() as conn:
        conn.execute(update(t.notification_settings).values(address_status="disabled"))
        caller = SimpleNamespace(principal_id=human, human_session=None)
        with pytest.raises(ApiError) as refused, _no_proof():
            second_factor.disable(conn, hub, caller)  # type: ignore[arg-type]
    assert refused.value.details == {"reason": "second_factor_required"}


def _no_proof() -> Any:
    from unittest import mock

    return mock.patch.multiple(
        second_factor, require_proof=lambda *_: None, require_step_up=lambda *_: None
    )


def test_approving_a_held_removal_keeps_the_factor(
    make_client: ClientFactory, migrated: Engine
) -> None:
    called: list[bool] = []

    def keeps() -> None:
        called.append(True)
        raise ApiError(403, "forbidden", "kept", {"reason": "second_factor_required"})

    _, human = setup(make_client, migrated, stored=True)
    change = {"id": "adc-1", "address": None, "requested_at": "2026-10-31T12:00:00Z"}
    with migrated.begin() as conn:
        conn.execute(update(t.notification_settings).values(address_change=change))
        row = SimpleNamespace(id=human)
        session = SimpleNamespace(state="full", method="password", second_factor_via="totp")
        with (
            mock_good_standing(),
            pytest.raises(ApiError),
        ):
            preferences.decide_held(
                conn,
                human=row,
                session=session,
                change_id="adc-1",
                address=None,
                approve=True,
                signing_key=None,
                public_url="https://hub.example",
                step_up=lambda: None,
                keeps_factor=keeps,
            )
    assert called == [True]


def mock_good_standing() -> Any:
    from unittest import mock

    return mock.patch.object(sessions, "good_standing", lambda *_: True)
