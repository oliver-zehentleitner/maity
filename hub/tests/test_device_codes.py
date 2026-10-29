"""Device codes: a signed-in device approves a new one (docs/api.md §2.6.1, §2.6.2, §2.6.4)."""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import device_codes
from maity_hub.auth.caller import SESSION_COOKIE
from maity_hub.routes import device_codes as routes
from maity_hub.routes.device_codes import PENDING_COOKIE
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_mentions import agent_named

PHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)


@pytest.fixture
def desk(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def phone(make_client: ClientFactory) -> TestClient:
    return make_client(peer="198.51.100.24")


def redeem(client: TestClient, code: str, **body: Any) -> Any:
    return client.post(
        "/api/v1/auth/device-login", json={"code": code, **body}, headers={"User-Agent": PHONE}
    )


def started(desk: flow.Human) -> dict[str, Any]:
    response = desk.post("/auth/device-codes")
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_a_device_signs_in_by_code_and_number(
    make_client: ClientFactory, migrated: Engine, desk: flow.Human
) -> None:
    code = started(desk)
    assert len(code["code"]) == 14 and code["code"][4] == "-" and code["code"][9] == "-"
    assert code["url"] == f"https://hub.example/sign-in/code#c={code['code'].replace('-', '')}"
    assert desk.get(f"/auth/device-codes/{code['id']}").json()["status"] == "waiting"

    new = phone(make_client)
    redeemed = redeem(new, code["code"].lower(), next="/maintainer/maity/board")
    assert redeemed.status_code == 200
    body = redeemed.json()
    assert set(body) == {"status", "expires_at", "match_number"}
    assert body["status"] == "redeemed" and 10 <= body["match_number"] <= 99
    pending = next(c for c in redeemed.headers.get_list("set-cookie") if PENDING_COOKIE in c)
    assert "Path=/api/v1/auth" in pending and "HttpOnly" in pending
    assert "samesite=strict" in pending.lower() and "Secure" in pending
    assert "account" not in new.get("/api/v1/auth/device-login").json()

    seen = desk.get(f"/auth/device-codes/{code['id']}").json()
    assert seen["status"] == "redeemed"
    assert seen["device"]["ip"] == "198.51.100.24"
    assert (seen["device"]["browser"], seen["device"]["os"]) == ("Safari", "iOS")
    assert seen["device"]["user_agent"] == PHONE and seen["device"]["new_device"] is True
    choices = seen["choices"]
    assert len(set(choices)) == 3 and choices == sorted(choices)
    assert body["match_number"] in choices

    approved = desk.post(
        f"/auth/device-codes/{code['id']}/approve", {"number": body["match_number"]}
    )
    assert approved.json()["status"] == "approved"
    account = new.get("/api/v1/auth/device-login").json()["account"]
    assert account["handle"] == "maintainer"

    done = new.post("/api/v1/auth/device-login/complete")
    assert done.status_code == 200
    assert done.json()["member"]["handle"] == "maintainer"
    assert done.json()["next"] == "/maintainer/maity/board"
    assert SESSION_COOKIE in new.cookies and PENDING_COOKIE not in new.cookies
    assert "maity_device" in new.cookies
    csrf = new.get("/api/v1/auth/session").json()
    mine = desk.get("/auth/session").json()["session_id"]
    listed = {i["id"]: i for i in desk.get("/auth/sessions").json()["items"]}
    assert listed[csrf["session_id"]]["method"] == "device_code"
    assert listed[csrf["session_id"]]["approved_by"] == mine
    # One code, one session: nothing more comes out of it.
    assert new.post("/api/v1/auth/device-login/complete").status_code == 404
    assert desk.get(f"/auth/device-codes/{code['id']}").json()["status"] == "used"


def test_the_first_redemption_wins_and_every_other_fails_alike(
    make_client: ClientFactory, desk: flow.Human
) -> None:
    code = started(desk)["code"]
    assert redeem(phone(make_client), code).status_code == 200
    for attempt in (code, "ZZZZ-ZZZZ-ZZZZ", "short", "I0L0-0000-0000", code[:9]):
        second = redeem(make_client(peer="192.0.2.9"), attempt)
        assert (second.status_code, second.json()["error"]["code"]) == (403, "code_invalid")


def test_input_is_read_loosely(make_client: ClientFactory) -> None:
    assert device_codes.normalise("k7qm-4xpr-9d2f") == "K7QM4XPR9D2F"
    assert device_codes.normalise(" K7QM 4XPR 9D2F ") == "K7QM4XPR9D2F"
    assert device_codes.normalise("iLoO-0000-0000") == "1100" + "0000" + "0000"
    assert device_codes.normalise("K7QM-4XPR-9D2U") is None  # U is not Crockford
    assert device_codes.normalise("K7QM-4XPR") is None  # the eight of before, no longer
    assert device_codes.normalise("K7QM") is None


def test_a_wrong_pick_denies_the_code(make_client: ClientFactory, desk: flow.Human) -> None:
    code = started(desk)
    new = phone(make_client)
    match = redeem(new, code["code"]).json()["match_number"]
    choices = desk.get(f"/auth/device-codes/{code['id']}").json()["choices"]
    wrong = next(n for n in choices if n != match)
    picked = desk.post(f"/auth/device-codes/{code['id']}/approve", {"number": wrong})
    assert (picked.status_code, picked.json()["error"]["code"]) == (403, "code_invalid")
    assert new.get("/api/v1/auth/device-login").json()["status"] == "denied"
    again = desk.post(f"/auth/device-codes/{code['id']}/approve", {"number": match})
    assert again.status_code == 409
    assert new.post("/api/v1/auth/device-login/complete").status_code == 409


def test_only_the_session_that_made_it_sees_it(
    make_client: ClientFactory, migrated: Engine, desk: flow.Human
) -> None:
    code = started(desk)
    other = make_client()
    other.post("/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD})
    csrf = other.get("/api/v1/auth/session").json()["csrf_token"]
    same_human = flow.Human(other, csrf, desk.id)
    for response in (
        same_human.get(f"/auth/device-codes/{code['id']}"),
        same_human.post(f"/auth/device-codes/{code['id']}/approve", {"number": 50}),
        same_human.post(f"/auth/device-codes/{code['id']}/deny"),
        same_human.delete(f"/auth/device-codes/{code['id']}"),
    ):
        assert response.status_code == 404
    flow.project(desk)
    agent = agent_named(make_client, desk, "agent-a")
    for response in (
        agent.post("/auth/device-codes"),
        agent.get(f"/auth/device-codes/{code['id']}"),
    ):
        assert response.json()["error"]["details"] == {"reason": "humans_only"}
    with_credential = make_client().post(
        "/api/v1/auth/device-login", json={"code": code["code"]}, headers=agent.auth
    )
    assert with_credential.json()["error"]["details"] == {"reason": "humans_only"}


def test_deny_and_cancel(make_client: ClientFactory, desk: flow.Human) -> None:
    first = started(desk)
    assert desk.post(f"/auth/device-codes/{first['id']}/deny").json()["status"] == "denied"
    assert redeem(phone(make_client), first["code"]).status_code == 403
    second = started(desk)
    new = phone(make_client)
    redeem(new, second["code"])
    assert desk.delete(f"/auth/device-codes/{second['id']}").json()["status"] == "denied"
    assert new.get("/api/v1/auth/device-login").json()["status"] == "denied"


def test_a_new_code_voids_the_sessions_earlier_one(
    make_client: ClientFactory, desk: flow.Human
) -> None:
    first = started(desk)
    started(desk)
    assert desk.get(f"/auth/device-codes/{first['id']}").json()["status"] == "denied"


def test_codes_expire(make_client: ClientFactory, desk: flow.Human) -> None:
    now = clock.now()
    code = started(desk)
    clock.set_source(lambda: now + timedelta(minutes=5, seconds=1))
    assert desk.get(f"/auth/device-codes/{code['id']}").json()["status"] == "expired"
    assert redeem(phone(make_client), code["code"]).status_code == 403

    clock.set_source(lambda: now + timedelta(minutes=10))
    code = started(desk)
    new = phone(make_client)
    match = redeem(new, code["code"]).json()["match_number"]
    desk.post(f"/auth/device-codes/{code['id']}/approve", {"number": match})
    clock.set_source(lambda: now + timedelta(minutes=11, seconds=1))
    assert new.get("/api/v1/auth/device-login").json()["status"] == "expired"
    assert new.post("/api/v1/auth/device-login/complete").status_code == 409


def test_ending_the_session_kills_its_codes(make_client: ClientFactory, desk: flow.Human) -> None:
    code = started(desk)
    new = phone(make_client)
    redeem(new, code["code"])
    desk.post("/auth/logout")
    assert new.get("/api/v1/auth/device-login").json()["status"] == "denied"


def test_switched_off_voids_and_refuses(
    make_client: ClientFactory, migrated: Engine, desk: flow.Human
) -> None:
    code = started(desk)
    assert desk.patch("/admin/settings/sign-in", {"device_code": False}).status_code == 200
    with migrated.begin() as conn:
        assert conn.execute(select(t.device_code.c.status)).scalar() == "denied"
    refused = desk.post("/auth/device-codes")
    assert refused.json()["error"]["details"] == {"reason": "method_disabled"}
    assert redeem(phone(make_client), code["code"]).json()["error"]["details"] == {
        "reason": "method_disabled"
    }
    assert make_client().get("/api/v1/auth/methods").json() == {
        "password": True,
        "device_code": False,
        "email_link": False,
    }


def test_the_methods_the_login_page_offers(make_client: ClientFactory, migrated: Engine) -> None:
    assert make_client().get("/api/v1/auth/methods").json() == {
        "password": True,
        "device_code": True,
        "email_link": False,
    }


def test_rate_limits(make_client: ClientFactory, desk: flow.Human) -> None:
    for _ in range(5):
        started(desk)
    assert desk.post("/auth/device-codes").status_code == 429

    guesser = make_client(peer="192.0.2.50")
    for _ in range(10):
        assert redeem(guesser, "ZZZZ-ZZZZ").status_code == 403
    assert redeem(guesser, "ZZZZ-ZZZZ").status_code == 429


@pytest.fixture
def frozen_monotonic(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wrong-code window is 60 s of the monotonic clock. Sixty requests on a slow or busy
    runner can take longer than that, and the window drains before the breaker trips; the
    clock the limiter and the breaker read stands still instead."""
    import time
    import types

    from maity_hub import ratelimit

    frozen = time.monotonic()
    stub = types.SimpleNamespace(monotonic=lambda: frozen)
    monkeypatch.setattr(ratelimit, "time", stub)
    monkeypatch.setattr(routes, "time", stub)


@pytest.mark.usefixtures("frozen_monotonic")
def test_the_wrong_code_breaker_stops_every_redemption(
    make_client: ClientFactory, desk: flow.Human
) -> None:
    for n in range(60):
        assert redeem(make_client(peer=f"192.0.2.{n + 1}"), "ZZZZ-ZZZZ").status_code == 403
    code = started(desk)["code"]
    assert redeem(make_client(peer="198.51.100.1"), code).status_code == 429


def test_no_other_site_starts_a_sign_in(make_client: ClientFactory, desk: flow.Human) -> None:
    code = started(desk)["code"]
    for site in ("cross-site", "same-site"):
        response = make_client().post(
            "/api/v1/auth/device-login", json={"code": code}, headers={"Sec-Fetch-Site": site}
        )
        assert response.status_code == 403
    assert redeem(phone(make_client), code).status_code == 200


def test_a_browser_that_signed_in_before_is_not_new(
    make_client: ClientFactory, desk: flow.Human
) -> None:
    known = phone(make_client)
    known.post("/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD})
    csrf = known.get("/api/v1/auth/session").json()["csrf_token"]
    known.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert "maity_device" in known.cookies  # kept on logout
    code = started(desk)
    redeem(known, code["code"])
    assert desk.get(f"/auth/device-codes/{code['id']}").json()["device"]["new_device"] is False


def test_the_long_poll_returns_on_the_redemption(
    make_client: ClientFactory, desk: flow.Human
) -> None:
    code = started(desk)
    answers: list[dict[str, Any]] = []
    waiter = threading.Thread(
        target=lambda: answers.append(desk.get(f"/auth/device-codes/{code['id']}?wait=10").json())
    )
    begun = time.monotonic()
    waiter.start()
    time.sleep(0.5)
    redeem(phone(make_client), code["code"])
    waiter.join(timeout=15)
    assert answers and answers[0]["status"] == "redeemed"
    assert time.monotonic() - begun < 8


def test_a_second_long_poll_supersedes_the_first(
    make_client: ClientFactory, desk: flow.Human
) -> None:
    code = started(desk)
    answers: list[dict[str, Any]] = []
    first = threading.Thread(
        target=lambda: answers.append(desk.get(f"/auth/device-codes/{code['id']}?wait=10").json())
    )
    first.start()
    time.sleep(0.5)
    second = desk.get(f"/auth/device-codes/{code['id']}?wait=1").json()
    first.join(timeout=15)
    assert answers[0].get("superseded") is True
    assert second["status"] == "waiting"


def signed_in_by_code(make_client: ClientFactory, desk: flow.Human) -> flow.Human:
    """B, a browser signed in by a code that A approved."""
    code = started(desk)
    new = phone(make_client)
    match = redeem(new, code["code"]).json()["match_number"]
    desk.post(f"/auth/device-codes/{code['id']}/approve", {"number": match})
    assert new.post("/api/v1/auth/device-login/complete").status_code == 200
    return flow.Human(new, new.get("/api/v1/auth/session").json()["csrf_token"], desk.id)


def test_a_device_code_session_cannot_end_the_one_that_approved_it(
    make_client: ClientFactory, desk: flow.Human
) -> None:
    b = signed_in_by_code(make_client, desk)
    a_id = desk.get("/auth/session").json()["session_id"]
    refused = b.delete(f"/auth/sessions/{a_id}")
    assert refused.json()["error"]["details"] == {"reason": "not_in_good_standing"}
    live = {i["id"] for i in b.post("/auth/sessions/end-others", {}).json()["items"]}
    assert a_id in live
    assert desk.get("/auth/session").status_code == 200


def test_completing_ends_the_session_the_browser_held(
    make_client: ClientFactory, migrated: Engine, desk: flow.Human
) -> None:
    factory.human(migrated, "someone")
    new = phone(make_client)
    new.post("/api/v1/auth/login", json={"handle": "someone", "password": factory.PASSWORD})
    held = new.cookies[SESSION_COOKIE]
    code = started(desk)
    match = redeem(new, code["code"]).json()["match_number"]
    desk.post(f"/auth/device-codes/{code['id']}/approve", {"number": match})
    assert new.post("/api/v1/auth/device-login/complete").status_code == 200
    assert new.cookies[SESSION_COOKIE] != held
    with migrated.begin() as conn:
        rows = conn.execute(select(t.human_session).order_by(t.human_session.c.created_at)).all()
    someone = [r for r in rows if r.human_id != desk.id]
    assert someone and someone[0].ended_by == "logout"


def test_switched_off_in_the_environment_stops_every_step(
    make_client: ClientFactory, migrated: Engine, desk: flow.Human
) -> None:
    code = started(desk)
    new = phone(make_client)
    match = redeem(new, code["code"]).json()["match_number"]
    off = make_client(sign_in_device_code=False)  # a restart with the method off
    off.cookies.update(desk.client.cookies)
    a = flow.Human(off, desk.csrf, desk.id)
    for response in (
        a.get(f"/auth/device-codes/{code['id']}"),
        a.post(f"/auth/device-codes/{code['id']}/approve", {"number": match}),
        a.post(f"/auth/device-codes/{code['id']}/deny"),
    ):
        assert response.json()["error"]["details"] == {"reason": "method_disabled"}
    with migrated.begin() as conn:
        assert conn.execute(select(t.device_code.c.status)).scalar() == "denied"
    b = make_client(sign_in_device_code=False, peer="198.51.100.24")
    b.cookies.update(new.cookies)
    for response in (
        b.get("/api/v1/auth/device-login"),
        b.post("/api/v1/auth/device-login/complete"),
    ):
        assert response.json()["error"]["details"] == {"reason": "method_disabled"}


@pytest.mark.usefixtures("frozen_monotonic")
def test_the_breaker_holds_for_a_minute(make_client: ClientFactory, desk: flow.Human) -> None:
    for n in range(60):
        redeem(make_client(peer=f"192.0.2.{n + 1}"), "ZZZZ-ZZZZ")
    code = started(desk)["code"]
    tripped = routes._breaker["until"]
    assert redeem(make_client(peer="198.51.100.1"), code).status_code == 429
    routes.WRONG_CODES.reset()  # the window has emptied, the breaker still holds
    assert redeem(make_client(peer="198.51.100.2"), code).status_code == 429
    routes._breaker["until"] = tripped - routes.BREAKER_SECONDS - 1  # the minute is over
    assert redeem(make_client(peer="198.51.100.3"), code).status_code == 200


def test_a_waiting_poll_answers_when_the_hub_stops(desk: flow.Human) -> None:
    from maity_hub import longpoll

    code = started(desk)
    answers: list[Any] = []
    begun = time.monotonic()
    waiter = threading.Thread(
        target=lambda: answers.append(desk.get(f"/auth/device-codes/{code['id']}?wait=30"))
    )
    waiter.start()
    time.sleep(0.5)
    longpoll.begin_shutdown()
    waiter.join(timeout=10)
    assert answers and answers[0].json()["status"] == "waiting"
    assert time.monotonic() - begun < 5  # not the 30 seconds it asked for
