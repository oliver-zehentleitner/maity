"""The reset of a second factor without a recovery code (docs/api.md §2.8.3, §18.6)."""

from __future__ import annotations

import base64
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import second_factor, second_factor_reset
from maity_hub.cli import main as cli_main
from maity_hub.notifications import tokens
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_notification_address import S, mail_env, outbox_rows
from tests.test_two_factor import KEY, Clock, code_now, login, signed_in
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

SIGNING = b"s" * 32


def hub(**more: object) -> dict[str, object]:
    return {"secret_key": KEY, "mail": mail_env().mail, **more}


def enrol(human: flow.Human, moment: Clock) -> tuple[bytes, list[str]]:
    """The enrolment of §2.8.1 for any human: (the secret, the recovery codes)."""
    started = human.post("/auth/second-factor/totp")
    assert started.status_code == 200, started.text
    encoded = started.json()["secret"]
    secret = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
    confirmed = human.post(
        "/auth/second-factor/totp/confirm", {"code": code_now(secret, moment.at)}
    )
    assert confirmed.status_code == 200, confirmed.text
    return secret, list(confirmed.json()["recovery_codes"])


def verify_address(person: flow.Human, migrated: Engine, address: str) -> None:
    person.patch(S, {"email": {"address": address}})
    mail = outbox_rows(migrated)[-1]
    found = re.search(r"https://hub\.example/mail/verify/(\S+)", mail.body)
    assert found, mail.body
    assert person.client.post(f"/mail/verify/{found.group(1)}").status_code == 200


def world(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> tuple[flow.Human, flow.Human, list[str]]:
    """The instance admin, and an enrolled human with a verified address (and their codes)."""
    admin = signed_in(make_client, migrated, **hub())
    moment.move(seconds=1)  # the admin is the earliest account (§16)
    grace_id = factory.human(migrated, "grace")
    client = make_client(**hub())
    assert login(client, "grace").status_code == 200
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    grace = flow.Human(client, csrf, grace_id)
    verify_address(grace, migrated, "grace@example.org")
    _, codes = enrol(grace, moment)
    return admin, grace, codes


def ask(admin: flow.Human, grace: flow.Human, reason: str = "She lost her phone.") -> Any:
    return admin.post(f"/admin/users/{grace.id}/second-factor/reset", {"reason": reason})


def reset_mail(migrated: Engine) -> Any:
    return [r for r in outbox_rows(migrated) if "two-factor" in r.subject.lower()][-1]


def token_of(mail: Any) -> str:
    found = re.search(r"https://hub\.example/mail/second-factor-reset/(\S+)", mail.body)
    assert found, mail.body
    return found.group(1)


def factor(migrated: Engine, human_id: str) -> Any:
    with migrated.connect() as conn:
        return second_factor.factor_of(conn, human_id)


def sessions_of(migrated: Engine, human_id: str) -> list[Any]:
    with migrated.connect() as conn:
        return list(
            conn.execute(select(t.human_session).where(t.human_session.c.human_id == human_id))
        )


def test_the_request_mails_a_link_and_changes_nothing(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin, grace, _ = world(make_client, migrated, moment)
    before = factor(migrated, grace.id)
    asked = ask(admin, grace, "She lost her phone, https://evil.example/x said so.")
    assert asked.status_code == 202, asked.text
    mail = reset_mail(migrated)
    assert (mail.kind, mail.recipient, mail.human_id) == (
        "security",
        "grace@example.org",
        grace.id,
    )
    assert "maintainer" in mail.body and "24 hours" in mail.body
    assert "https[:]//evil[.]example" in mail.body  # the admin's words are quoted, defanged
    payload = tokens.read(SIGNING, token_of(mail))
    assert payload is not None
    assert (payload["p"], payload["h"], payload["g"]) == (
        "second_factor_reset",
        grace.id,
        before.generation,
    )
    with migrated.connect() as conn:
        row = conn.execute(select(t.second_factor_reset)).one()
    assert row.used_at is None and row.requested_by == admin.id
    assert row.id != payload["n"]  # the table holds the hash, not what opens the link
    after = factor(migrated, grace.id)
    assert (after.secret, after.generation) == (before.secret, before.generation)
    assert all(s.ended_at is None for s in sessions_of(migrated, grace.id))


@pytest.mark.parametrize(
    ("who", "status", "reason"),
    [("self", 403, "own_account"), ("other", 403, None)],
)
def test_only_the_admin_asks_and_never_for_their_own_account(
    make_client: ClientFactory, migrated: Engine, moment: Clock, who: str, status: int, reason: Any
) -> None:
    admin, grace, _ = world(make_client, migrated, moment)
    if who == "self":
        refused = admin.post(f"/admin/users/{admin.id}/second-factor/reset", {"reason": "x"})
    else:
        refused = grace.post(f"/admin/users/{admin.id}/second-factor/reset", {"reason": "x"})
    assert refused.status_code == status
    if reason:
        assert refused.json()["error"]["details"]["reason"] == reason
    assert not [r for r in outbox_rows(migrated) if "two-factor" in r.subject.lower()]


def test_what_the_request_needs(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin, grace, _ = world(make_client, migrated, moment)
    assert (
        admin.post("/admin/users/hum-nobody/second-factor/reset", {"reason": "x"}).status_code
        == 404
    )
    assert ask(admin, grace, "").status_code == 400
    assert ask(admin, grace, "x" * 2000).status_code == 400
    # No verified address: the mail cannot reach them.
    nobody = factory.human(migrated, "ada")
    with migrated.begin() as conn:
        conn.execute(
            t.second_factor.insert().values(
                human_id=nobody, secret=b"s", enrolled_at=clock.now(), generation=0
            )
        )
    refused = admin.post(f"/admin/users/{nobody}/second-factor/reset", {"reason": "x"})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "address_unverified"
    # No mail: no reset by this way.
    bare = signed_in_admin_without_mail(make_client, migrated)
    refused = bare.post(f"/admin/users/{grace.id}/second-factor/reset", {"reason": "x"})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "mail_not_configured"


def signed_in_admin_without_mail(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    client = make_client(secret_key=KEY)
    assert login(client).status_code == 200
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    with migrated.connect() as conn:
        admin_id = conn.execute(
            select(t.human.c.id).where(t.human.c.handle == "maintainer")
        ).scalar()
    return flow.Human(client, csrf, str(admin_id))


def test_an_enrolled_admin_needs_the_factor_for_the_request(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin, grace, _ = world(make_client, migrated, moment)
    secret, _ = enrol(admin, moment)
    moment.move(minutes=11)
    refused = ask(admin, grace)
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "step_up_required"
    assert admin.post("/auth/second-factor/verify", {"code": code_now(secret, moment.at)})
    assert ask(admin, grace).status_code == 202


def test_a_get_changes_nothing_and_the_button_resets(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin, grace, codes = world(make_client, migrated, moment)
    before = factor(migrated, grace.id)
    ask(admin, grace, "She lost her phone.")
    link = f"/mail/second-factor-reset/{token_of(reset_mail(migrated))}"
    page = grace.client.get(link)
    assert page.status_code == 200 and "set-cookie" not in page.headers
    assert "maintainer" in page.text and "She lost her phone." in page.text
    assert "<blockquote>" in page.text and page.headers["referrer-policy"] == "no-referrer"
    assert factor(migrated, grace.id).secret == before.secret  # a GET changes nothing
    done = grace.client.post(link)
    assert done.status_code == 200 and "every session has ended" in done.text
    after = factor(migrated, grace.id)
    assert after.secret is None and after.reset_required is True
    assert after.generation == before.generation + 1
    assert grace.get("/auth/second-factor").status_code == 401  # her sessions ended
    ended = sessions_of(migrated, grace.id)
    assert ended and all(s.ended_at is not None for s in ended)
    assert {s.ended_by for s in ended} == {"second_factor_reset"}
    with migrated.connect() as conn:
        left = conn.execute(select(t.recovery_code).where(t.recovery_code.c.human_id == grace.id))
        record = conn.execute(
            select(t.account_record)
            .where(
                t.account_record.c.human_id == grace.id,
                t.account_record.c.type == "second_factor_changed",
            )
            .order_by(t.account_record.c.n.desc())
        ).first()
    assert left.all() == [] and codes
    assert record is not None and record.data == {"change": "reset", "by": "maintainer"}
    # The next sign-in goes into enrolment, whatever the policy says (§2.8.5).
    again = make_client(**hub())
    assert login(again, "grace").status_code == 200
    held = again.get("/api/v1/me")
    assert held.status_code == 403
    assert held.json()["error"]["details"]["reason"] == "second_factor_enrolment_required"


def test_the_link_works_once_and_two_racing_links_one_wins(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin, grace, _ = world(make_client, migrated, moment)
    ask(admin, grace)
    moment.move(minutes=1)
    ask(admin, grace, "Again.")
    first, second = [
        token_of(m) for m in outbox_rows(migrated) if "two-factor" in m.subject.lower()
    ]
    assert grace.client.post(f"/mail/second-factor-reset/{first}").status_code == 200
    # The factor's generation moved with the first: every other link is dead (§2.8.3).
    assert grace.client.post(f"/mail/second-factor-reset/{second}").status_code == 404
    assert grace.client.post(f"/mail/second-factor-reset/{first}").status_code == 404
    assert grace.client.get(f"/mail/second-factor-reset/{second}").status_code == 404


@pytest.mark.parametrize("how", ["recovered", "enrolled_anew", "turned_off", "expired", "forged"])
def test_a_link_that_does_not_work_is_one_page(
    make_client: ClientFactory, migrated: Engine, moment: Clock, how: str
) -> None:
    admin, grace, codes = world(make_client, migrated, moment)
    ask(admin, grace)
    token = token_of(reset_mail(migrated))
    link = f"/mail/second-factor-reset/{token}"
    if how == "recovered":
        used = grace.post("/auth/second-factor/verify", {"recovery_code": codes[0]})
        assert used.status_code == 200
        with migrated.begin() as conn:  # the recovery code does not move the factor itself
            conn.execute(
                t.second_factor.update()
                .where(t.second_factor.c.human_id == grace.id)
                .values(generation=t.second_factor.c.generation + 1)
            )
    elif how == "turned_off":
        with migrated.begin() as conn:
            second_factor.remove(conn, grace.id)
    elif how == "enrolled_anew":
        with migrated.begin() as conn:
            second_factor.remove(conn, grace.id)
            conn.execute(
                t.second_factor.update()
                .where(t.second_factor.c.human_id == grace.id)
                .values(secret=b"new", enrolled_at=clock.now())
            )
    elif how == "expired":
        moment.move(hours=25)
    else:
        link = "/mail/second-factor-reset/" + tokens.make(
            b"o" * 32, tokens.read(SIGNING, token) or {}
        )
    page = grace.client.post(link)
    assert page.status_code == 404
    assert "no longer works" in page.text
    assert grace.client.get(link).status_code == 404
    assert factor(migrated, grace.id).reset_required is False


def test_the_log_masks_the_token(
    make_client: ClientFactory, migrated: Engine, moment: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    admin, grace, _ = world(make_client, migrated, moment)
    ask(admin, grace)
    token = token_of(reset_mail(migrated))
    with caplog.at_level(logging.INFO, logger="maity_hub.access"):
        grace.client.get(f"/mail/second-factor-reset/{token}")
    lines = [r.getMessage() for r in caplog.records if r.name == "maity_hub.access"]
    assert lines and all(token not in line for line in lines)
    assert any("/mail/second-factor-reset/…" in line for line in lines)


def test_requests_for_one_human_are_limited(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    second_factor_reset.BY_HUMAN._hits.clear()
    admin, grace, _ = world(make_client, migrated, moment)
    answers = [ask(admin, grace).status_code for _ in range(4)]
    assert answers == [202, 202, 202, 429]
    second_factor_reset.BY_HUMAN._hits.clear()


def test_the_operator_resets_at_once(
    make_client: ClientFactory,
    migrated: Engine,
    moment: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin, grace, _ = world(make_client, migrated, moment)
    before = factor(migrated, grace.id)
    monkeypatch.setenv("MAITY_DATABASE_URL", migrated.url.render_as_string(hide_password=False))
    assert cli_main(["second-factor", "reset", "--handle", "grace"]) == 0
    assert "reset the second factor of grace" in capsys.readouterr().out
    after = factor(migrated, grace.id)
    assert after.secret is None and after.reset_required is True
    assert after.generation == before.generation + 1
    assert all(s.ended_at is not None for s in sessions_of(migrated, grace.id))
    with migrated.connect() as conn:
        record = conn.execute(
            select(t.account_record.c.data)
            .where(
                t.account_record.c.human_id == grace.id,
                t.account_record.c.type == "second_factor_changed",
            )
            .order_by(t.account_record.c.n.desc())
        ).first()
    assert record is not None and record.data == {"change": "reset", "by": "operator"}
    assert cli_main(["second-factor", "reset", "--handle", "grace"]) == 1  # nothing enrolled now
    assert cli_main(["second-factor", "reset", "--handle", "nobody"]) == 1
    assert admin and isinstance(grace.client, TestClient)
