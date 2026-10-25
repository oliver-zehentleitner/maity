"""Two-factor sign-in for humans (docs/api.md §2.8): enrolment and its proof, the second
step of a sign-in, replay, the lockout, recovery codes, step-up, and the policy."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import second_factor, totp
from maity_hub.config import ConfigError, Settings
from tests import factory, flow
from tests.conftest import ClientFactory

KEY = b"k" * 32
START = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.at = START
        clock.set_source(lambda: self.at)

    def move(self, **delta: float) -> None:
        self.at += timedelta(**delta)


@pytest.fixture
def moment() -> Clock:
    return Clock()


def login(client: TestClient, handle: str = "maintainer") -> Any:
    return client.post("/api/v1/auth/login", json={"handle": handle, "password": factory.PASSWORD})


def signed_in(make_client: ClientFactory, migrated: Engine, **overrides: object) -> flow.Human:
    human_id = factory.human(migrated, "maintainer")
    client = make_client(**{"secret_key": KEY, **overrides})
    assert login(client).status_code == 200
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    return flow.Human(client, csrf, human_id)


def code_now(secret: bytes, at: datetime) -> str:
    return totp.code_at(secret, totp.step_of(at.timestamp()))


def enrol(human: flow.Human, moment: Clock) -> tuple[bytes, list[str]]:
    started = human.post("/auth/second-factor/totp")
    assert started.status_code == 200, started.text
    body = started.json()
    secret = base64.b32decode(body["secret"] + "=" * (-len(body["secret"]) % 8))
    assert body["otpauth_uri"].startswith("otpauth://totp/hub.example:maintainer?")
    assert body["expires_in"] == 600
    code = code_now(secret, moment.at)
    confirmed = human.post("/auth/second-factor/totp/confirm", {"code": code})
    assert confirmed.status_code == 200, confirmed.text
    codes = confirmed.json()["recovery_codes"]
    assert len(codes) == 10 and all(len(c) == 11 and c[5] == "-" for c in codes)
    return secret, codes


def second_step(client: TestClient) -> str:
    """Log in again: the answer owes the second step; returns its CSRF token."""
    answer = login(client)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"second_factor": "required", "expires_in": 300}
    session = client.get("/api/v1/auth/session").json()
    assert session["second_factor"] == "required" and "member" not in session
    return str(session["csrf_token"])


def records_of(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.account_record).where(t.account_record.c.type == kind)).all()
        )


# --- enrolment -----------------------------------------------------------------------


def test_enrolment_needs_a_fresh_password_and_turns_on_with_a_code(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    assert human.get("/auth/second-factor").json() == {
        "instance_off": False,
        "enrolled": False,
        "enrolled_at": None,
        "recovery_codes_left": 0,
        "last_used_at": None,
        "required": False,
    }
    moment.move(minutes=11)  # the login's password is no longer fresh
    stale = human.post("/auth/second-factor/totp")
    assert stale.status_code == 403
    assert stale.json()["error"]["details"]["reason"] == "reauthentication_required"
    wrong = human.post("/auth/reauthenticate", {"password": "not the password at all"})
    assert wrong.json()["error"]["details"]["fields"] == {"password": "mismatch"}
    assert human.post("/auth/reauthenticate", {"password": factory.PASSWORD}).status_code == 200
    started = human.post("/auth/second-factor/totp").json()
    secret = base64.b32decode(started["secret"] + "=" * (-len(started["secret"]) % 8))
    bad = human.post("/auth/second-factor/totp/confirm", {"code": "000000"})
    assert bad.json()["error"]["code"] == "code_invalid"
    assert human.get("/auth/second-factor").json()["enrolled"] is False
    good = human.post("/auth/second-factor/totp/confirm", {"code": code_now(secret, moment.at)})
    assert good.status_code == 200 and len(good.json()["recovery_codes"]) == 10
    state = human.get("/auth/second-factor").json()
    assert state["enrolled"] is True and state["recovery_codes_left"] == 10
    [record] = records_of(migrated, "second_factor_changed")
    assert record.data == {"change": "enrolled", "by": "maintainer"}
    with migrated.connect() as conn:
        factor = conn.execute(select(t.second_factor)).one()
        stored = conn.execute(select(t.recovery_code.c.code_hash)).scalars().all()
    # Sealed, never the secret in clear; recovery codes as HMACs only.
    assert secret not in factor.secret and len(stored) == 10
    assert not set(stored) & {c.replace("-", "") for c in good.json()["recovery_codes"]}


def test_enrolment_needs_the_instance_key(make_client: ClientFactory, migrated: Engine) -> None:
    human = signed_in(make_client, migrated, secret_key=None)
    refused = human.post("/auth/second-factor/totp")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "secret_key_missing"


# --- the sign-in step ------------------------------------------------------------------


def test_an_enrolled_sign_in_owes_the_code_and_reaches_nothing_else(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    secret, _ = enrol(human, moment)
    client = make_client(secret_key=KEY)
    csrf = second_step(client)
    me = client.get("/api/v1/me")
    assert me.status_code == 403
    assert me.json()["error"]["details"]["reason"] == "second_factor_required"
    assert client.get("/api/v1/auth/sessions").status_code == 403
    old_cookie = client.cookies.get("maity_session")
    moment.move(seconds=30)  # the next step: the enrolment's code is used already
    done = client.post(
        "/api/v1/auth/second-factor/verify",
        json={"code": code_now(secret, moment.at)},
        headers={"X-CSRF-Token": csrf},
    )
    assert done.status_code == 200, done.text
    assert done.json()["member"]["handle"] == "maintainer" and done.json()["next"] == "/"
    # A fresh session id at the second step, not at the first (fixation, §2.6.5).
    assert client.cookies.get("maity_session") != old_cookie
    assert client.get("/api/v1/me").status_code == 200
    created = records_of(migrated, "session_created")
    assert created[-1].data["second_factor"] == "totp"
    listed = client.get("/api/v1/auth/sessions").json()["items"]
    mine = next(item for item in listed if item["current"])
    assert mine["second_factor"] is True and mine["good_standing"] is True


def test_a_code_is_accepted_once(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    secret, _ = enrol(human, moment)
    client = make_client(secret_key=KEY)
    csrf = second_step(client)
    replayed = client.post(
        "/api/v1/auth/second-factor/verify",
        json={"code": code_now(secret, moment.at)},  # the step the enrolment used
        headers={"X-CSRF-Token": csrf},
    )
    assert replayed.json()["error"]["code"] == "code_invalid"
    with migrated.begin() as conn:
        factor = second_factor.factor_of(conn, human.id)
        hub: Any = SimpleNamespace(secret_key=KEY)
        moment.move(seconds=30)
        code = code_now(secret, moment.at)
        # Two checks with one code: one wins, by the conditional update (§2.8.2).
        assert second_factor._consume_totp(conn, hub, factor, code) is True
        assert second_factor._consume_totp(conn, hub, factor, code) is False


def test_five_wrong_codes_end_the_second_step_and_tell_the_human(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    enrol(human, moment)
    client = make_client(secret_key=KEY)
    csrf = second_step(client)
    for _ in range(5):
        wrong = client.post(
            "/api/v1/auth/second-factor/verify",
            json={"code": "123456"},
            headers={"X-CSRF-Token": csrf},
        )
        assert wrong.json()["error"]["code"] == "code_invalid"
    assert client.get("/api/v1/auth/session").status_code == 401  # the session ended
    [alert] = records_of(migrated, "second_factor_failed")
    assert alert.data["method"] == "password"


def test_ten_wrong_codes_lock_the_human_out_for_the_window(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    secret, _ = enrol(human, moment)
    for _ in range(2):
        client = make_client(secret_key=KEY)
        csrf = second_step(client)
        for _ in range(5):
            client.post(
                "/api/v1/auth/second-factor/verify",
                json={"code": "123456"},
                headers={"X-CSRF-Token": csrf},
            )
    client = make_client(secret_key=KEY)
    csrf = second_step(client)
    moment.move(seconds=30)
    locked = client.post(
        "/api/v1/auth/second-factor/verify",
        json={"code": code_now(secret, moment.at)},
        headers={"X-CSRF-Token": csrf},
    )
    assert locked.status_code == 429  # even the right code, until the window passes


def test_a_recovery_code_signs_in_once(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    _, codes = enrol(human, moment)
    typed = " " + codes[0].upper().replace("0", "o") + " "  # case, spaces, o for 0
    client = make_client(secret_key=KEY)
    csrf = second_step(client)
    done = client.post(
        "/api/v1/auth/second-factor/verify",
        json={"recovery_code": typed},
        headers={"X-CSRF-Token": csrf},
    )
    assert done.status_code == 200, done.text
    used = records_of(migrated, "second_factor_changed")[-1]
    assert used.data["change"] == "recovery_code_used" and used.data["recovery_codes_left"] == 9
    again = make_client(secret_key=KEY)
    csrf = second_step(again)
    reused = again.post(
        "/api/v1/auth/second-factor/verify",
        json={"recovery_code": codes[0]},
        headers={"X-CSRF-Token": csrf},
    )
    assert reused.json()["error"]["code"] == "code_invalid"


def test_the_second_step_expires(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    enrol(human, moment)
    client = make_client(secret_key=KEY)
    second_step(client)
    moment.move(minutes=5)
    assert client.get("/api/v1/auth/session").status_code == 401


# --- step-up ---------------------------------------------------------------------------


def test_a_sensitive_call_needs_a_recent_factor(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    secret, _ = enrol(human, moment)
    change = {"current": factory.PASSWORD, "new": "another long password"}
    moment.move(minutes=11)
    refused = human.post("/auth/password", change)
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "step_up_required"
    stepped = human.post("/auth/second-factor/verify", {"code": code_now(secret, moment.at)})
    assert stepped.status_code == 200 and "valid_until" in stepped.json()
    assert human.post("/auth/password", change).status_code == 200


def test_a_join_needs_a_recent_factor(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    flow.project(human)
    enrol(human, moment)
    moment.move(minutes=11)
    refused = human.post("/projects/maity/joins", {"agent": {"handle": "agent-a"}})
    assert refused.json()["error"]["details"]["reason"] == "step_up_required"


# --- turning it off ----------------------------------------------------------------------


def test_turning_it_off_needs_proof_and_step_up_and_ends_other_sessions(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    secret, _ = enrol(human, moment)
    other = make_client(secret_key=KEY)
    csrf = second_step(other)
    moment.move(seconds=30)
    assert (
        other.post(
            "/api/v1/auth/second-factor/verify",
            json={"code": code_now(secret, moment.at)},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 200
    )
    moment.move(seconds=30)
    assert human.delete("/auth/second-factor").status_code == 200
    assert other.get("/api/v1/me").status_code == 401
    with migrated.connect() as conn:
        ended = conn.execute(
            select(t.human_session.c.ended_by).where(t.human_session.c.ended_by.is_not(None))
        ).scalars()
        assert "second_factor_disabled" in set(ended)
    assert records_of(migrated, "second_factor_changed")[-1].data["change"] == "disabled"
    assert login(make_client(secret_key=KEY)).json()["member"]["handle"] == "maintainer"


# --- the policy ----------------------------------------------------------------------------


def test_off_skips_the_second_step_and_ends_open_ones(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    enrol(human, moment)
    pending = make_client(secret_key=KEY)
    second_step(pending)
    moment.move(seconds=30)
    with migrated.begin() as conn:
        from maity_hub import instance_settings as store

        store.put(conn, "sign_in.second_factor", "off", human.id)
    assert pending.get("/api/v1/auth/session").status_code == 401
    assert "member" in login(make_client(secret_key=KEY)).json()
    off = human.post("/auth/second-factor/verify", {"code": "123456"})
    assert off.json()["error"]["details"]["reason"] == "method_disabled"


def test_required_admins_needs_the_key_and_holds_an_admin_at_enrolment(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    keyless = signed_in(make_client, migrated, secret_key=None)
    refused = keyless.patch("/admin/settings/sign-in", {"second_factor": "required_admins"})
    assert refused.json()["error"]["details"]["fields"] == {"second_factor": "secret_key_missing"}
    admin = flow.Human(make_client(secret_key=KEY), "", keyless.id)
    assert login(admin.client).status_code == 200
    admin.csrf = admin.client.get("/api/v1/auth/session").json()["csrf_token"]
    switched = admin.patch("/admin/settings/sign-in", {"second_factor": "required_admins"})
    assert switched.status_code == 200, switched.text
    held = admin.get("/me")
    assert held.json()["error"]["details"]["reason"] == "second_factor_enrolment_required"
    fresh = make_client(secret_key=KEY)
    assert login(fresh).json() == {"second_factor": "enrolment_required"}
    csrf = fresh.get("/api/v1/auth/session").json()["csrf_token"]
    before = fresh.cookies.get("maity_session")
    started = fresh.post("/api/v1/auth/second-factor/totp", headers={"X-CSRF-Token": csrf})
    text = started.json()["secret"]
    secret = base64.b32decode(text + "=" * (-len(text) % 8))
    confirmed = fresh.post(
        "/api/v1/auth/second-factor/totp/confirm",
        json={"code": code_now(secret, moment.at)},
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200
    assert fresh.cookies.get("maity_session") != before  # the sign-in completed now
    assert fresh.get("/api/v1/me").status_code == 200


def test_required_admins_in_the_environment_without_a_key_stops_the_hub() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"MAITY_SIGN_IN_SECOND_FACTOR": "required_admins"})


def test_a_device_code_sign_in_owes_the_second_step_too(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    desk = signed_in(make_client, migrated)
    secret, _ = enrol(desk, moment)  # the enrolment's code is a step-up for the approval
    code = desk.post("/auth/device-codes").json()
    new = make_client(secret_key=KEY, peer="198.51.100.24")
    redeemed = new.post("/api/v1/auth/device-login", json={"code": code["code"]}).json()
    approved = desk.post(
        f"/auth/device-codes/{code['id']}/approve", {"number": redeemed["match_number"]}
    )
    assert approved.status_code == 200, approved.text
    completed = new.post("/api/v1/auth/device-login/complete")
    assert completed.json() == {"second_factor": "required", "expires_in": 300}
    csrf = new.get("/api/v1/auth/session").json()["csrf_token"]
    moment.move(seconds=30)
    done = new.post(
        "/api/v1/auth/second-factor/verify",
        json={"code": code_now(secret, moment.at)},
        headers={"X-CSRF-Token": csrf},
    )
    assert done.status_code == 200, done.text
    mine = next(i for i in new.get("/api/v1/auth/sessions").json()["items"] if i["current"])
    # The first factor's method and lineage are kept through the second step (§2.8.2).
    assert mine["method"] == "device_code" and mine["approved_by"] is not None
    assert mine["second_factor"] is True


# --- review round 1 --------------------------------------------------------------------------


def parked_enrolment(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> tuple[flow.Human, TestClient]:
    """An admin under `required_admins` with an enrolment session parked in a second
    browser, before enrolling anywhere."""
    admin = signed_in(make_client, migrated)
    assert (
        admin.patch("/admin/settings/sign-in", {"second_factor": "required_admins"}).status_code
        == 200
    )
    parked = make_client(secret_key=KEY)
    assert login(parked).json() == {"second_factor": "enrolment_required"}
    return admin, parked


def test_a_parked_enrolment_session_ends_once_the_human_enrolled_elsewhere(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin, parked = parked_enrolment(make_client, migrated, moment)
    enrol(admin, moment)  # from the first session, which is held at enrolment too
    assert parked.get("/api/v1/me").status_code == 401  # never full without a code
    with migrated.connect() as conn:
        ended = (
            conn.execute(
                select(t.human_session.c.ended_by).where(
                    t.human_session.c.sign_in_complete.is_(False)
                )
            )
            .scalars()
            .all()
        )
    assert ended == ["second_factor_disabled"]  # the end committed


def test_a_parked_enrolment_session_completes_when_the_policy_no_longer_asks(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin, parked = parked_enrolment(make_client, migrated, moment)
    assert admin.patch("/admin/settings/sign-in", {"second_factor": "optional"}).status_code == 403
    with migrated.begin() as conn:
        from maity_hub import instance_settings as store

        store.put(conn, "sign_in.second_factor", "optional", admin.id)
    assert parked.get("/api/v1/me").status_code == 200  # no factor exists: it completes


def test_an_ended_second_step_stays_ended_when_the_policy_returns(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    from maity_hub import instance_settings as store

    human = signed_in(make_client, migrated)
    enrol(human, moment)
    pending = make_client(secret_key=KEY)
    second_step(pending)
    with migrated.begin() as conn:
        store.put(conn, "sign_in.second_factor", "off", human.id)
    assert pending.get("/api/v1/auth/session").status_code == 401
    with migrated.begin() as conn:
        store.put(conn, "sign_in.second_factor", "optional", human.id)
    assert pending.get("/api/v1/auth/session").status_code == 401  # not revived


def test_under_off_the_factor_calls_refuse_and_the_state_says_so(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    from maity_hub import instance_settings as store

    human = signed_in(make_client, migrated)
    enrol(human, moment)
    with migrated.begin() as conn:
        store.put(conn, "sign_in.second_factor", "off", human.id)
    assert human.get("/auth/second-factor").json()["instance_off"] is True
    for call in (
        human.post("/auth/second-factor/totp/confirm", {"code": "123456"}),
        human.post("/auth/second-factor/recovery-codes"),
        human.post("/auth/second-factor/totp"),
        human.delete("/auth/second-factor"),
    ):
        assert call.json()["error"]["details"]["reason"] == "method_disabled"


def test_off_in_the_environment_is_told_once_at_startup(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    enrol(human, moment)
    for _ in range(2):  # two starts with the environment's `off`: one notice
        make_client(secret_key=KEY, sign_in_second_factor="off")
    told = [
        r.data
        for r in records_of(migrated, "second_factor_changed")
        if r.data["change"] == "instance_off"
    ]
    assert told == [{"change": "instance_off", "by": "environment"}]


def test_one_second_step_completes_once(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    from maity_hub.auth import sessions

    human = signed_in(make_client, migrated)
    enrol(human, moment)
    second_step(make_client(secret_key=KEY))
    with migrated.begin() as conn:
        row = conn.execute(
            select(t.human_session).where(t.human_session.c.sign_in_complete.is_(False))
        ).one()
        sessions.complete_sign_in(conn, row, "totp")
        with pytest.raises(LookupError):  # the row no longer owes the step
            sessions.complete_sign_in(conn, row, "totp")


def test_logging_out_of_a_second_step_names_nobody(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated)
    enrol(human, moment)
    pending = make_client(secret_key=KEY)
    csrf = second_step(pending)
    out = pending.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 200 and out.json() == {}
