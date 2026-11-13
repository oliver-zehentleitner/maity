"""The daily cap of wrong second-factor codes (docs/api.md §2.8.6) and the mailed link that lifts
it for the rest of the day (§18.6)."""

from __future__ import annotations

import dataclasses
import re
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from maity_hub.auth import password_resets, second_factor, totp
from maity_hub.config import ConfigError, Settings
from maity_hub.notifications import mailer, tokens
from maity_hub.routes import password_reset
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_email_sign_in import setup
from tests.test_password_reset import finish, mailed, refused
from tests.test_second_factor_reset import enrol
from tests.test_two_factor import Clock, code_now
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

CAP = 10
PUBLIC = "https://hub.example"


@pytest.fixture(autouse=True)
def roomy_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 15-minute limit out of the way: these tests count past it in one window."""
    monkeypatch.setattr(second_factor.WRONG_BY_HUMAN, "limit", 1000)


def enrolled(make_client: ClientFactory, migrated: Engine, moment: Clock) -> tuple[Any, bytes]:
    """Ada, signed in with a verified address and an enrolled app; a cap of `CAP`."""
    anonymous, human_id = setup(make_client, migrated)
    hub = anonymous.app.state.settings
    client = make_client(mail=hub.mail, secret_key=hub.secret_key, second_factor_wrong_per_day=CAP)
    assert factory.login_handle(client, "ada").status_code == 200
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    ada = flow.Human(client, csrf, human_id)
    secret, _ = enrol(ada, moment)
    return ada, secret


def hub_of(ada: flow.Human) -> Any:
    """The settings of the hub `ada`'s client talks to."""
    app: Any = ada.client.app
    return app.state.settings


def wrong_code(secret: bytes, moment: Clock) -> str:
    """A code no step near now accepts."""
    step = totp.step_of(moment.at.timestamp())
    near = {totp.code_at(secret, s) for s in range(step - 2, step + 3)}
    return next(c for c in ("000000", "111111", "222222", "333333") if c not in near)


def step_up(ada: flow.Human, code: str) -> Any:
    return ada.post("/auth/second-factor/verify", {"code": code})


def reach_the_cap(ada: flow.Human, secret: bytes, moment: Clock) -> None:
    for _ in range(CAP):
        moment.move(seconds=1)
        answer = step_up(ada, wrong_code(secret, moment))
        assert answer.json()["error"]["code"] == "code_invalid", answer.text


def alerts(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.account_record).where(t.account_record.c.type == "second_factor_failed")
            ).all()
        )


def security_mails(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.mail_outbox)
                .where(t.mail_outbox.c.kind == "security")
                .order_by(t.mail_outbox.c.id)
            ).all()
        )


def unlock_mail(engine: Engine, ada: flow.Human) -> Any:
    """The newest security mail with an unlock link, after a pass of the mailer."""
    assert mailer.run(engine, hub_of(ada).mail, None, PUBLIC) >= 1
    found = [m for m in security_mails(engine) if "/mail/second-factor-unlock/" in m.body]
    assert found, [m.subject for m in security_mails(engine)]
    return found[-1]


def link_of(mail: Any) -> str:
    found = re.search(r"https://hub\.example(/mail/second-factor-unlock/\S+)", mail.body)
    assert found, mail.body
    return found.group(1)


def unlock_link(engine: Engine, ada: flow.Human) -> str:
    return link_of(unlock_mail(engine, ada))


def test_at_the_cap_even_a_right_code_is_refused_until_the_day_ends(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    ada, secret = enrolled(make_client, migrated, moment)
    reach_the_cap(ada, secret, moment)
    [alert] = [a for a in alerts(migrated) if a.data["method"] == "daily_limit"]
    assert alert.data["day"] == "2026-10-25" and alert.data["unlocks"] == 0
    moment.move(seconds=31)
    refused = step_up(ada, code_now(secret, moment.at))
    assert refused.status_code == 429
    assert refused.json()["error"]["details"] == {"reason": "daily_limit"}
    # 12:00:41 UTC: the rest of the day, and a second.
    assert int(refused.headers["Retry-After"]) == 12 * 3600 - 41 + 1
    assert len(alerts(migrated)) == 1  # the refusals compare nothing and count nothing
    moment.move(hours=12)  # the next UTC day
    assert step_up(ada, code_now(secret, moment.at)).status_code == 200


def test_below_the_cap_a_right_code_still_passes(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    ada, secret = enrolled(make_client, migrated, moment)
    for _ in range(CAP - 1):
        moment.move(seconds=1)
        step_up(ada, wrong_code(secret, moment))
    moment.move(seconds=31)
    assert step_up(ada, code_now(secret, moment.at)).status_code == 200
    assert alerts(migrated) == []


def test_the_alert_mail_carries_a_link_that_lifts_the_cap_once(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    ada, secret = enrolled(make_client, migrated, moment)
    reach_the_cap(ada, secret, moment)
    mail = unlock_mail(migrated, ada)
    assert mail.subject.startswith("[Maity] Second-factor codes refused for today")
    assert "List-Unsubscribe" not in (mail.headers or {})
    link = link_of(mail)
    page = ada.client.get(link)
    assert page.status_code == 200 and "Let me try again today" in page.text
    moment.move(seconds=31)
    assert step_up(ada, code_now(secret, moment.at)).status_code == 429  # the GET changed nothing
    assert ada.client.post(link).status_code == 200
    assert step_up(ada, code_now(secret, moment.at)).status_code == 200
    assert ada.client.post(link).status_code == 404  # once
    assert ada.client.get(link).status_code == 404


def test_the_cap_counts_again_after_a_lift_and_a_new_link_is_mailed(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    ada, secret = enrolled(make_client, migrated, moment)
    reach_the_cap(ada, secret, moment)
    first = unlock_link(migrated, ada)
    assert ada.client.post(first).status_code == 200
    reach_the_cap(ada, secret, moment)
    second = unlock_link(migrated, ada)
    assert second != first
    assert [a.data["unlocks"] for a in alerts(migrated)] == [0, 1]
    assert ada.client.post(first).status_code == 404
    assert ada.client.post(second).status_code == 200


def test_a_link_of_another_day_or_purpose_does_not_work(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    ada, secret = enrolled(make_client, migrated, moment)
    reach_the_cap(ada, secret, moment)
    link = unlock_link(migrated, ada)
    key = hub_of(ada).mail.signing_key
    payload = tokens.read(key, link.rsplit("/", 1)[1])
    assert payload is not None
    other = tokens.make(key, {**payload, "p": "second_factor_reset"})
    assert ada.client.post(f"/mail/second-factor-unlock/{other}").status_code == 404
    moment.move(hours=12)  # the cap of that day is gone, and the link with it
    assert ada.client.post(link).status_code == 404


def test_a_password_change_kills_the_link_and_the_next_wrong_code_mails_a_new_one(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    ada, secret = enrolled(make_client, migrated, moment)
    reach_the_cap(ada, secret, moment)
    old = unlock_link(migrated, ada)
    changed = ada.post(
        "/auth/password", {"current": factory.PASSWORD, "new": "a brand new long password"}
    )
    assert changed.status_code == 200, changed.text
    assert ada.client.get(old).status_code == 404
    assert ada.client.post(old).status_code == 404
    # The cap stands, but its alert counts as not written: one more code is compared, and a
    # wrong one mails a link of the new password.
    moment.move(seconds=1)
    assert step_up(ada, wrong_code(secret, moment)).json()["error"]["code"] == "code_invalid"
    [_, again] = [a for a in alerts(migrated) if a.data["method"] == "daily_limit"]
    assert again.data["password_generation"] == 1
    moment.move(seconds=31)
    assert step_up(ada, code_now(secret, moment.at)).status_code == 429
    new = unlock_link(migrated, ada)
    assert new != old and ada.client.post(new).status_code == 200
    assert step_up(ada, code_now(secret, moment.at)).status_code == 200


def lower_the_cap(ada: flow.Human, cap: int) -> None:
    app: Any = ada.client.app
    app.state.settings = dataclasses.replace(app.state.settings, second_factor_wrong_per_day=cap)


def test_a_cap_lowered_during_the_day_alerts_before_it_refuses(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    ada, secret = enrolled(make_client, migrated, moment)
    for _ in range(CAP - 2):
        moment.move(seconds=1)
        step_up(ada, wrong_code(secret, moment))
    lower_the_cap(ada, CAP - 4)  # already over it, and nobody was told
    moment.move(seconds=31)
    assert step_up(ada, code_now(secret, moment.at)).status_code == 200  # still compared
    assert alerts(migrated) == []
    moment.move(seconds=1)
    assert step_up(ada, wrong_code(secret, moment)).json()["error"]["code"] == "code_invalid"
    [alert] = alerts(migrated)
    assert alert.data["method"] == "daily_limit"
    moment.move(seconds=31)
    assert step_up(ada, code_now(secret, moment.at)).status_code == 429
    assert ada.client.post(unlock_link(migrated, ada)).status_code == 200
    assert step_up(ada, code_now(secret, moment.at)).status_code == 200


def sign_in_step(make_client: ClientFactory, ada: flow.Human) -> tuple[Any, str]:
    """A fresh sign-in of Ada that owes the second step, and its CSRF token."""
    hub = hub_of(ada)
    client = make_client(mail=hub.mail, secret_key=hub.secret_key, second_factor_wrong_per_day=CAP)
    answer = factory.login_handle(client, "ada")
    assert answer.json()["second_factor"] == "required", answer.text
    return client, str(client.get("/api/v1/auth/session").json()["csrf_token"])


def at_sign_in(client: Any, csrf: str, **body: str) -> Any:
    return client.post(
        "/api/v1/auth/second-factor/verify", json=body, headers={"X-CSRF-Token": csrf}
    )


def test_the_sign_in_step_counts_toward_the_cap_and_is_refused_at_it(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    ada, secret = enrolled(make_client, migrated, moment)
    # Five wrong codes end a sign-in's step (§2.8.2): two sign-ins reach the cap.
    for _ in range(CAP // 5):
        client, csrf = sign_in_step(make_client, ada)
        for _ in range(5):
            moment.move(seconds=1)
            wrong = at_sign_in(client, csrf, code=wrong_code(secret, moment))
            assert wrong.json()["error"]["code"] == "code_invalid", wrong.text
    [alert] = [a for a in alerts(migrated) if a.data["method"] == "daily_limit"]
    assert alert.data["unlocks"] == 0
    client, csrf = sign_in_step(make_client, ada)
    moment.move(seconds=31)
    refused_now = at_sign_in(client, csrf, code=code_now(secret, moment.at))
    assert refused_now.status_code == 429
    assert refused_now.json()["error"]["details"] == {"reason": "daily_limit"}
    assert ada.client.post(unlock_link(migrated, ada)).status_code == 200
    assert at_sign_in(client, csrf, code=code_now(secret, moment.at)).status_code == 200


def test_wrong_recovery_codes_count_toward_the_cap(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    ada, secret = enrolled(make_client, migrated, moment)
    for _ in range(CAP // 5):
        client, csrf = sign_in_step(make_client, ada)
        for _ in range(5):
            wrong = at_sign_in(client, csrf, recovery_code="aaaaa-bbbbb")
            assert wrong.json()["error"]["code"] == "code_invalid", wrong.text
    assert [a.data["method"] for a in alerts(migrated)].count("daily_limit") == 1
    moment.move(seconds=31)
    assert step_up(ada, code_now(secret, moment.at)).status_code == 429


def test_the_password_reset_counts_toward_the_cap_and_is_refused_at_it(
    make_client: ClientFactory, migrated: Engine, moment: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(password_reset, "LIMITS", password_resets.RequestLimits())
    ada, secret = enrolled(make_client, migrated, moment)
    anonymous = make_client(
        mail=hub_of(ada).mail, secret_key=hub_of(ada).secret_key, second_factor_wrong_per_day=CAP
    )
    token = mailed(anonymous, migrated)
    assert refused(finish(anonymous, token, code=wrong_code(secret, moment)))
    for _ in range(CAP - 1):  # the rest by step-up: one count for both
        moment.move(seconds=1)
        step_up(ada, wrong_code(secret, moment))
    [alert] = [a for a in alerts(migrated) if a.data["method"] == "daily_limit"]
    assert alert.data["day"] == "2026-10-25"
    moment.move(seconds=31)
    token = mailed(anonymous, migrated)
    answer = finish(anonymous, token, code=code_now(secret, moment.at))
    assert answer.status_code == 429
    assert answer.json()["error"]["details"] == {"reason": "daily_limit"}
    assert ada.client.post(unlock_link(migrated, ada)).status_code == 200
    assert finish(anonymous, token, code=code_now(secret, moment.at)).status_code == 200


def test_the_setting_has_its_range() -> None:
    base = {"MAITY_DATABASE_URL": "sqlite://"}
    assert Settings.from_env(base).second_factor_wrong_per_day == 50
    assert (
        Settings.from_env(
            {**base, "MAITY_SECOND_FACTOR_WRONG_PER_DAY": "200"}
        ).second_factor_wrong_per_day
        == 200
    )
    for bad in ("9", "10001", "many"):
        with pytest.raises(ConfigError):
            Settings.from_env({**base, "MAITY_SECOND_FACTOR_WRONG_PER_DAY": bad})
