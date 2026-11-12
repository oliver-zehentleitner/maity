"""A forgotten password reset by mail (docs/api.md §2.10): the anonymous request and its mail,
the reset page's `check` and `complete`, the dead links, the second factor at a reset and the
alarm after five wrong codes in a day, and what a reset ends."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, middleware
from maity_hub import tables as t
from maity_hub.auth import password_resets
from maity_hub.instance_settings import put
from maity_hub.notifications import mailer
from maity_hub.routes import password_reset
from tests import factory, flow
from tests.concurrency import finished, race, waiting
from tests.conftest import ClientFactory
from tests.test_email_sign_in import setup
from tests.test_second_factor_reset import enrol
from tests.test_two_factor import Clock, code_now
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

ASK = "/api/v1/auth/password-reset"
CHECK = f"{ASK}/check"
COMPLETE = f"{ASK}/complete"
NEW = "a brand new long password"


@pytest.fixture(autouse=True)
def limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(password_reset, "LIMITS", password_resets.RequestLimits())


def ask(client: Any, address: str = "ada@example.com", **headers: str) -> Any:
    return client.post(ASK, json={"address": address}, headers=headers)


def resets(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.mail_outbox)
                .where(t.mail_outbox.c.kind == "password_reset")
                .order_by(t.mail_outbox.c.id)
            ).all()
        )


def token_of(row: Any) -> str:
    found = re.search(r"/sign-in/reset#(\S+)", row.body)
    assert found, row.body
    return found.group(1)


def mailed(client: Any, engine: Engine) -> str:
    assert ask(client).status_code == 202
    return token_of(resets(engine)[-1])


def finish(client: Any, token: str, new: str = NEW, **more: str) -> Any:
    return client.post(COMPLETE, json={"token": token, "new": new, **more})


def refused(response: Any) -> bool:
    return bool(response.status_code == 403 and response.json()["error"]["code"] == "code_invalid")


def signed_in(make_client: ClientFactory, anonymous: Any, handle: str = "ada") -> flow.Human:
    """`handle` signed in on a client of its own, on the hub `anonymous` was made for."""
    hub = anonymous.app.state.settings
    client = make_client(mail=hub.mail, secret_key=hub.secret_key)
    assert factory.login_handle(client, handle).status_code == 200
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    return flow.Human(client, csrf, "")


def records(engine: Engine, human_id: str, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.account_record).where(
                    t.account_record.c.human_id == human_id, t.account_record.c.type == kind
                )
            ).all()
        )


# --- asking ------------------------------------------------------------------------------


def test_every_request_answers_alike_and_only_a_known_address_gets_the_mail(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    client, human = setup(make_client, migrated)
    unknown = ask(client, "nobody@example.com")
    known = ask(client, "  ADA@example.com  ")
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json() == {"expires_in": 1800}
    assert "set-cookie" not in unknown.headers and "set-cookie" not in known.headers
    [row] = resets(migrated)
    assert row.recipient == "ada@example.com" and row.human_id == human
    assert row.subject == "[Maity] Reset your password"
    assert "valid for 30 minutes" in row.body and "your password stays as it is" in row.body
    assert "second factor too" not in row.body  # only where the mail is the factor
    payload = password_resets.read(client.app.state.settings.mail.signing_key, token_of(row))
    assert payload is not None
    assert (payload["h"], payload["p"], payload["g"], payload["e"]) == (
        human,
        "password_reset",
        0,
        0,
    )


def test_under_mail_as_the_factor_the_mail_says_the_mailbox_is_both(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    client, human = setup(make_client, migrated)
    with migrated.begin() as conn:
        put(conn, "sign_in.second_factor", "email", None)
    token = mailed(client, migrated)
    assert "This mailbox is your second factor too" in resets(migrated)[-1].body
    assert client.post(CHECK, json={"token": token}).json()["factor"] == "email"


@pytest.mark.parametrize("why", ["switched_off", "no_password", "suspended", "unverified"])
def test_no_mail_is_sent_where_none_may_go_and_the_answer_is_the_same(
    make_client: ClientFactory, migrated: Engine, moment: Clock, why: str
) -> None:
    client, human = setup(make_client, migrated)
    with migrated.begin() as conn:
        if why == "switched_off":
            conn.execute(
                update(t.notification_settings)
                .where(t.notification_settings.c.human_id == human)
                .values(preferences={"email": {"password_reset": False}})
            )
        elif why == "no_password":
            from maity_hub.auth import passwords

            conn.execute(
                update(t.human)
                .where(t.human.c.id == human)
                .values(password_hash=passwords.DUMMY_HASH)
            )
        elif why == "suspended":
            conn.execute(
                update(t.human).where(t.human.c.id == human).values(suspended_at=clock.now())
            )
        else:
            conn.execute(
                update(t.notification_settings)
                .where(t.notification_settings.c.human_id == human)
                .values(address_status="pending")
            )
    answer = ask(client)
    assert (answer.status_code, answer.json()) == (202, {"expires_in": 1800})
    assert resets(migrated) == []


def test_the_instance_switch_off_refuses_the_three_calls(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    client, human = setup(make_client, migrated)
    token = mailed(client, migrated)
    with migrated.begin() as conn:
        put(conn, "sign_in.password_reset", False, None)
    for response in (
        ask(client),
        client.post(CHECK, json={"token": token}),
        finish(client, token),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["details"] == {"reason": "method_disabled"}


def test_without_mail_settings_the_request_answers_and_sends_nothing(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = factory.human(migrated, "ada")
    client = make_client()
    assert ask(client).status_code == 202
    assert resets(migrated) == []
    assert client.get("/api/v1/auth/methods").json()["password_reset"] is False
    assert human


def test_a_new_request_voids_only_the_earlier_link_from_the_same_source(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    client, human = setup(make_client, migrated)
    first = mailed(client, migrated)
    # A link asked from elsewhere stays: nobody elsewhere can void the human's link.
    with migrated.begin() as conn:
        conn.execute(
            insert(t.password_reset).values(
                nonce_hash="e" * 64, human_id=human, source="203.0.113.9",
                created_at=clock.now(), expires_at=clock.now() + timedelta(minutes=30),
            )
        )  # fmt: skip
    moment.move(seconds=1)
    second = mailed(client, migrated)
    assert refused(client.post(CHECK, json={"token": first}))
    assert client.post(CHECK, json={"token": second}).status_code == 200
    with migrated.connect() as conn:
        other = conn.execute(
            select(t.password_reset.c.used_at).where(t.password_reset.c.nonce_hash == "e" * 64)
        ).scalar_one_or_none()
    assert other is None


def test_the_source_limit_answers_429_and_the_pair_limit_stays_silent(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    client, _ = setup(make_client, migrated)
    for _ in range(3):
        assert ask(client).status_code == 202
    assert ask(client).status_code == 202  # the fourth for this pair in 15 minutes
    assert len(resets(migrated)) == 3
    for n in range(6):
        assert ask(client, f"other{n}@example.com").status_code == 202
    assert ask(client, "more@example.com").status_code == 429


def test_the_rules_every_method_keeps(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    client, _ = setup(make_client, migrated)
    for path, body in ((ASK, {"address": "a@example.com"}), (CHECK, {"token": "x"})):
        cross = client.post(path, json=body, headers={"sec-fetch-site": "cross-site"})
        assert cross.status_code == 403
        agent = client.post(path, json=body, headers={"authorization": "Bearer mty_x"})
        assert agent.json()["error"]["details"].get("reason") == "humans_only", agent.text
    # A maintenance window refuses the reset like any other call (§16.12).
    assert not middleware.MAINTENANCE_OPEN.match(ASK)
    assert not middleware.MAINTENANCE_OPEN.match(COMPLETE)


# --- the reset page ------------------------------------------------------------------------


def test_check_names_the_account_and_changes_nothing(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    client, human = setup(make_client, migrated)
    token = mailed(client, migrated)
    for _ in range(2):
        got = client.post(CHECK, json={"token": token})
        assert got.status_code == 200, got.text
        assert got.json() == {"display_name": "Human ada", "handle": "ada", "factor": None}


def test_complete_sets_the_password_ends_everything_and_signs_nobody_in(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    client, human = setup(make_client, migrated)
    laptop = signed_in(make_client, client)
    # What a reset ends besides the sessions: a sign-in link, an address change waiting for its
    # link, a pending account deletion.
    assert client.post("/api/v1/auth/email-link", json={"address": "ada@example.com"}).status_code
    with migrated.begin() as conn:
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == human)
            .values(
                pending_address="next@example.com", pending_nonce="n" * 32,
                pending_expires_at=clock.now() + timedelta(hours=1),
            )
        )  # fmt: skip
        conn.execute(
            insert(t.account_deletion).values(
                id="d" * 64, human_id=human, live=True, requested_at=clock.now(),
                expires_at=clock.now() + timedelta(hours=1),
            )
        )  # fmt: skip
    token = mailed(client, migrated)
    short = finish(client, token, "short")
    assert short.json()["error"]["details"]["fields"] == {"new": "too_short"}
    done = finish(client, token)
    assert (done.status_code, done.json()) == (200, {})
    assert "maity_session" not in done.cookies
    assert laptop.client.get("/api/v1/me").headers["Maity-Error"] == "unauthenticated"
    with migrated.connect() as conn:
        ended = conn.execute(
            select(t.human_session.c.ended_by).where(t.human_session.c.human_id == human)
        ).scalars()
        assert set(ended) == {"password_reset"}
        open_links = conn.execute(
            select(t.email_sign_in).where(
                t.email_sign_in.c.human_id == human, t.email_sign_in.c.used_at.is_(None)
            )
        ).all()
        settings_row = conn.execute(
            select(t.notification_settings).where(t.notification_settings.c.human_id == human)
        ).one()
        deletion = conn.execute(
            select(t.account_deletion).where(t.account_deletion.c.human_id == human)
        ).one()
        generation = conn.execute(
            select(t.human.c.password_generation).where(t.human.c.id == human)
        ).scalar_one()
    assert open_links == [] and settings_row.pending_address is None
    assert (deletion.live, deletion.withdrawn_by) == (None, "password_reset")
    assert generation == 1
    # The link worked once; the old password no longer signs in, the new one does.
    assert refused(finish(client, token))
    assert factory.login_handle(make_client(), "ada").status_code != 200
    assert factory.login_handle(make_client(), "ada", NEW).status_code == 200
    [record] = records(migrated, human, "password_reset")
    assert set(record.data) == {"ip", "browser", "os"}


def test_the_completed_reset_is_told_at_once_whatever_the_mode(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    from tests.test_notification_mail import PUBLIC

    client, human = setup(make_client, migrated)
    with migrated.begin() as conn:
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == human)
            .values(preferences={"email": {"kinds": {"security": {"mode": "off"}}}})
        )
    assert finish(client, mailed(client, migrated)).status_code == 200
    assert mailer.run(migrated, client.app.state.settings.mail, None, PUBLIC) == 1
    with migrated.connect() as conn:
        [mail] = conn.execute(select(t.mail_outbox).where(t.mail_outbox.c.kind == "security")).all()
    assert mail.subject == "[Maity] Your password was reset"
    assert "Every session has ended" in mail.body and f"{PUBLIC}/agents" in mail.body
    assert "List-Unsubscribe" not in (mail.headers or {})
    bell = laptop_bell(make_client, client)
    assert bell[0]["kind"] == "security" and bell[0]["title"].startswith("Password reset by mail")


def laptop_bell(make_client: ClientFactory, anonymous: Any) -> list[dict[str, Any]]:
    hub = anonymous.app.state.settings
    client = make_client(mail=hub.mail, secret_key=hub.secret_key)
    assert factory.login_handle(client, "ada", NEW).status_code == 200
    return list(client.get("/api/v1/me/notifications").json()["items"])


@pytest.mark.parametrize(
    "why", ["forged", "expired", "password_changed", "address_changed", "suspended"]
)
def test_a_dead_link_is_refused_alike_and_changes_nothing(
    make_client: ClientFactory, migrated: Engine, moment: Clock, why: str
) -> None:
    client, human = setup(make_client, migrated)
    token = mailed(client, migrated)
    if why == "forged":
        body, _ = token.split(".")
        token = f"{body}.{'A' * 43}"
    elif why == "expired":
        moment.move(minutes=31)
    elif why == "password_changed":
        with migrated.begin() as conn:
            conn.execute(update(t.human).where(t.human.c.id == human).values(password_generation=1))
    elif why == "address_changed":
        with migrated.begin() as conn:
            conn.execute(
                update(t.notification_settings)
                .where(t.notification_settings.c.human_id == human)
                .values(epoch=1)
            )
    else:
        with migrated.begin() as conn:
            conn.execute(
                update(t.human).where(t.human.c.id == human).values(suspended_at=clock.now())
            )
    assert refused(client.post(CHECK, json={"token": token}))
    assert refused(finish(client, token))
    assert records(migrated, human, "password_reset") == []
    with migrated.connect() as conn:
        live = conn.execute(
            select(t.human_session).where(
                t.human_session.c.human_id == human, t.human_session.c.ended_at.is_not(None)
            )
        ).all()
    assert live == []  # nothing ended


# --- the second factor at a reset ----------------------------------------------------------


def enrolled_ada(make_client: ClientFactory, migrated: Engine, moment: Clock) -> Any:
    client, human = setup(make_client, migrated)
    ada = signed_in(make_client, client)
    secret, codes = enrol(ada, moment)
    return client, human, secret, codes


def test_an_enrolled_human_needs_the_code_and_one_code_serves_once(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    client, human, secret, _ = enrolled_ada(make_client, migrated, moment)
    moment.move(seconds=30)
    token = mailed(client, migrated)
    assert client.post(CHECK, json={"token": token}).json()["factor"] == "totp"
    assert refused(finish(client, token))  # the mailbox alone changes nothing
    with migrated.connect() as conn:
        assert conn.execute(select(t.password_reset_wrong)).all() == []  # and is no guess
    assert refused(finish(client, token, code="000000"))
    with migrated.connect() as conn:
        assert len(conn.execute(select(t.password_reset_wrong)).all()) == 1
    code = code_now(secret, moment.at)
    assert finish(client, token, code=code).status_code == 200
    # The step is used: the same code cannot serve the sign-in after it (§2.8.2).
    with migrated.connect() as conn:
        factor = conn.execute(
            select(t.second_factor).where(t.second_factor.c.human_id == human)
        ).one()
    assert factor.last_step is not None


def test_a_recovery_code_resets_and_is_told(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    client, human, _, codes = enrolled_ada(make_client, migrated, moment)
    token = mailed(client, migrated)
    assert finish(client, token, recovery_code=codes[0]).status_code == 200
    changed = [r.data.get("change") for r in records(migrated, human, "second_factor_changed")]
    assert "recovery_code_used" in changed


def test_under_off_a_stored_enrolment_still_counts(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    client, human, secret, _ = enrolled_ada(make_client, migrated, moment)
    with migrated.begin() as conn:
        put(conn, "sign_in.second_factor", "off", None)
    token = mailed(client, migrated)
    assert client.post(CHECK, json={"token": token}).json()["factor"] == "totp"
    assert refused(finish(client, token))


def test_without_the_instance_key_an_enrolled_reset_fails_closed(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    client, human, secret, _ = enrolled_ada(make_client, migrated, moment)
    token = mailed(client, migrated)
    keyless = make_client(mail=client.app.state.settings.mail, secret_key=None)
    answer = finish(keyless, token, code=code_now(secret, moment.at))
    assert answer.status_code == 409 and answer.json()["error"]["code"] == "secret_key_missing"
    assert client.post(CHECK, json={"token": token}).status_code == 200  # nothing consumed


def test_the_fifth_wrong_code_in_a_day_voids_every_link_and_alarms(
    make_client: ClientFactory, migrated: Engine, moment: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The request limits count real seconds, not this clock: out of the way here.
    monkeypatch.setattr(password_reset.LIMITS, "take", lambda address, source: (0, True))
    client, human = setup(make_client, migrated)
    ada = signed_in(make_client, client)  # her session lives until a reset succeeds
    secret, _ = enrol(ada, moment)
    # Four wrong codes spread over fresh links: no alarm yet.
    for _ in range(4):
        token = mailed(client, migrated)
        assert refused(finish(client, token, code="000000"))
        moment.move(minutes=20)
    assert records(migrated, human, "second_factor_failed") == []
    # A code under a dead link is neither compared nor counted.
    moment.move(minutes=31)
    assert refused(finish(client, token, code="000000"))
    assert records(migrated, human, "second_factor_failed") == []
    first = mailed(client, migrated)
    with migrated.begin() as conn:
        conn.execute(
            insert(t.password_reset).values(
                nonce_hash="f" * 64, human_id=human, source="203.0.113.9",
                created_at=clock.now(), expires_at=clock.now() + timedelta(minutes=30),
            )
        )  # fmt: skip
    assert refused(finish(client, first, code="000000"))
    [alarm] = records(migrated, human, "second_factor_failed")
    assert alarm.data["method"] == "password_reset"
    # Titled as the reset's alarm, not a sign-in's: the bell item and so the mail (§18.1).
    from tests.test_notification_mail import PUBLIC

    mailer.run(migrated, client.app.state.settings.mail, None, PUBLIC)
    with migrated.connect() as conn:
        subjects = (
            conn.execute(select(t.mail_outbox.c.subject).where(t.mail_outbox.c.kind == "security"))
            .scalars()
            .all()
        )
    [wrong] = [s for s in subjects if "Wrong second-factor codes" in s]
    assert wrong.startswith("[Maity] Wrong second-factor codes at a password reset: ")
    bell = ada.client.get("/api/v1/me/notifications").json()["items"]
    [item] = [i for i in bell if i["title"].startswith("Wrong second-factor codes")]
    assert item["title"].startswith("Wrong second-factor codes at a password reset: ")
    with migrated.connect() as conn:
        still_open = conn.execute(
            select(t.password_reset).where(
                t.password_reset.c.human_id == human, t.password_reset.c.used_at.is_(None)
            )
        ).all()
    assert still_open == []
    # The count does not restart: the next wrong code in the window alarms again, and a right
    # code under a fresh link still works.
    moment.move(minutes=1)
    second = mailed(client, migrated)
    assert refused(finish(client, second, code="000000"))
    assert len(records(migrated, human, "second_factor_failed")) == 2
    moment.move(minutes=1)
    third = mailed(client, migrated)
    assert finish(client, third, code=code_now(secret, moment.at)).status_code == 200


def test_wrong_codes_older_than_a_day_count_for_nothing(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    ada = factory.human(migrated, "ada")
    with migrated.begin() as conn:
        for _ in range(4):
            password_resets.wrong_code(conn, ada)
    moment.move(hours=24, seconds=1)
    with migrated.begin() as conn:
        assert password_resets.wrong_code(conn, ada) == 1


def test_under_mail_as_the_factor_the_reset_works_without_the_sign_in_link(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    """Under `email` the sign-in link is off (§2.8.8); the reset is the way back in."""
    client, human = setup(make_client, migrated)
    with migrated.begin() as conn:
        put(conn, "sign_in.second_factor", "email", None)
    assert client.get("/api/v1/auth/methods").json()["email_link"] is False
    assert finish(client, mailed(client, migrated)).status_code == 200


def test_two_completes_of_one_link_have_one_winner(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """The second waits for the first (the human's lock, and the row `use` writes); once the
    first commits, the used row refuses it. Only a server database shows this (`race` skips
    on SQLite)."""
    client, human = setup(make_client, migrated)
    token = mailed(client, migrated)
    hub = client.app.state.settings
    body = password_reset.ResetComplete(token=token, new=NEW)

    def complete(conn: Any) -> bool:
        return password_reset._complete(conn, hub, body, "203.0.113.7", None, None)

    with race(migrated) as two:
        assert complete(two.first)
        second = two.run(two.second, lambda: complete(two.second))
        assert waiting(second)
        two.first.commit()
        assert finished(second) is False
        two.second.commit()
    assert len(records(migrated, human, "password_reset")) == 1
