"""The session list, login `next` and session fixation (docs/api.md §2.1, §2.6.5)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import sessions
from maity_hub.auth.caller import SESSION_COOKIE
from maity_hub.db import migrate
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_mentions import agent_named

FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:142.0) Gecko/20100101 Firefox/142.0"
SAFARI_IOS = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)


def sign_in(
    make_client: ClientFactory, handle: str = "maintainer", agent: str = FIREFOX, **body: Any
) -> flow.Human:
    client = make_client()
    response = client.post(
        "/api/v1/auth/login",
        json={"handle": handle, "password": factory.PASSWORD, **body},
        headers={"User-Agent": agent},
    )
    assert response.status_code == 200, response.text
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    return flow.Human(client, csrf, "")


@pytest.fixture
def human(migrated: Engine) -> str:
    return factory.human(migrated, "maintainer")


def test_a_login_records_what_the_list_shows(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    me = sign_in(make_client)
    current = me.get("/auth/session").json()
    assert current["session_id"].startswith("hss-")
    listed = me.get("/auth/sessions").json()["items"]
    assert len(listed) == 1
    item = listed[0]
    assert item["id"] == current["session_id"]
    assert (item["current"], item["method"], item["browser"], item["os"]) == (
        True,
        "password",
        "Firefox",
        "Linux",
    )
    assert (item["ip"], item["approved_by"], item["good_standing"]) == ("203.0.113.7", None, True)
    assert item["ended_at"] is None and item["ended_by"] is None
    with migrated.begin() as conn:
        row = conn.execute(select(t.human_session)).one()
    assert row.public_id == item["id"] and row.id_hash not in str(listed)


def test_the_latest_call_moves_the_address(make_client: ClientFactory, human: str) -> None:
    me = sign_in(make_client)
    elsewhere = make_client(peer="198.51.100.9")
    elsewhere.cookies.update(me.client.cookies)
    assert elsewhere.get("/api/v1/auth/sessions").json()["items"][0]["ip"] == "198.51.100.9"


def test_the_list_is_the_callers_own_newest_first(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    first = sign_in(make_client)
    second = sign_in(make_client, agent=SAFARI_IOS)
    factory.human(migrated, "someone")
    stranger = sign_in(make_client, "someone")
    listed = second.get("/auth/sessions").json()["items"]
    assert [i["current"] for i in listed] == [True, False]
    assert (listed[0]["browser"], listed[0]["os"]) == ("Safari", "iOS")
    assert listed[1]["id"] == first.get("/auth/session").json()["session_id"]
    theirs = stranger.get("/auth/session").json()["session_id"]
    assert theirs not in {i["id"] for i in listed}
    assert second.delete(f"/auth/sessions/{theirs}").status_code == 404
    assert stranger.get("/auth/session").status_code == 200


def test_ending_another_session_and_again(make_client: ClientFactory, human: str) -> None:
    phone = sign_in(make_client, agent=SAFARI_IOS)
    laptop = sign_in(make_client)
    target = phone.get("/auth/session").json()["session_id"]
    ended = laptop.delete(f"/auth/sessions/{target}")
    assert ended.status_code == 200
    body = ended.json()
    assert (body["id"], body["ended_by"], body["current"]) == (target, "revoked", False)
    assert body["ended_at"] is not None
    assert phone.get("/auth/session").status_code == 401
    again = laptop.delete(f"/auth/sessions/{target}")
    assert again.status_code == 200 and again.json() == body
    assert target not in {i["id"] for i in laptop.get("/auth/sessions").json()["items"]}
    with_ended = laptop.get("/auth/sessions?ended=true").json()["items"]
    assert [(i["id"], i["ended_by"]) for i in with_ended if i["id"] == target] == [
        (target, "revoked")
    ]


def test_ending_the_current_session_is_a_logout(make_client: ClientFactory, human: str) -> None:
    me = sign_in(make_client)
    mine = me.get("/auth/session").json()["session_id"]
    response = me.delete(f"/auth/sessions/{mine}")
    assert response.status_code == 200
    assert response.json()["ended_by"] == "logout"
    assert SESSION_COOKIE not in me.client.cookies
    assert me.get("/auth/session").status_code == 401


def test_end_others_keeps_the_current_one(make_client: ClientFactory, human: str) -> None:
    others = [sign_in(make_client) for _ in range(2)]
    me = sign_in(make_client)
    response = me.post("/auth/sessions/end-others", {})
    assert response.status_code == 200
    assert [i["current"] for i in response.json()["items"]] == [True]
    for other in others:
        assert other.get("/auth/session").status_code == 401
    ended = me.get("/auth/sessions?ended=true").json()["items"]
    assert sorted(i["ended_by"] or "-" for i in ended) == ["-", "end_others", "end_others"]


def test_logout_and_password_change_say_why(make_client: ClientFactory, human: str) -> None:
    gone = sign_in(make_client)
    changed = sign_in(make_client)
    me = sign_in(make_client)
    gone.post("/auth/logout")
    response = me.post(
        "/auth/password", {"current": factory.PASSWORD, "new": "another long password"}
    )
    assert response.status_code == 200
    why = {i["current"]: i["ended_by"] for i in me.get("/auth/sessions?ended=true").json()["items"]}
    assert why[True] is None
    reasons = sorted(i["ended_by"] for i in me.get("/auth/sessions?ended=true").json()["items"][1:])
    assert reasons == ["logout", "password_change"]
    assert changed.get("/auth/session").status_code == 401


def test_an_expired_session_is_listed_as_ended(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    old = sign_in(make_client)
    old_id = old.get("/auth/session").json()["session_id"]
    with migrated.begin() as conn:
        conn.execute(
            update(t.human_session)
            .where(t.human_session.c.public_id == old_id)
            .values(last_seen_at=clock.now() - timedelta(days=15))
        )
    me = sign_in(make_client)
    assert old_id not in {i["id"] for i in me.get("/auth/sessions").json()["items"]}
    expired = [i for i in me.get("/auth/sessions?ended=true").json()["items"] if i["id"] == old_id]
    assert expired[0]["ended_by"] == "expired"


def test_sessions_ended_over_30_days_ago_are_not_listed(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    old = sign_in(make_client)
    old_id = old.get("/auth/session").json()["session_id"]
    old.post("/auth/logout")
    with migrated.begin() as conn:
        conn.execute(
            update(t.human_session)
            .where(t.human_session.c.public_id == old_id)
            .values(ended_at=clock.now() - timedelta(days=31))
        )
    me = sign_in(make_client)
    assert old_id not in {i["id"] for i in me.get("/auth/sessions?ended=true").json()["items"]}


def test_no_agent_lists_or_ends_a_session(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = agent_named(make_client, owner, "agent-a")
    mine = owner.get("/auth/session").json()["session_id"]
    for response in (
        agent.get("/auth/sessions"),
        agent.client.delete(f"/api/v1/auth/sessions/{mine}", headers=agent.auth | agent.key()),
        agent.post("/auth/sessions/end-others", {}),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["details"] == {"reason": "humans_only"}
    assert owner.get("/auth/session").status_code == 200


def test_a_login_ends_the_session_the_browser_holds(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    factory.human(migrated, "someone")
    browser = make_client()
    first = browser.post(
        "/api/v1/auth/login", json={"handle": "someone", "password": factory.PASSWORD}
    )
    assert first.status_code == 200
    presented = browser.cookies[SESSION_COOKIE]
    second = browser.post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert second.status_code == 200
    assert browser.cookies[SESSION_COOKIE] != presented
    with migrated.begin() as conn:
        rows = conn.execute(select(t.human_session).order_by(t.human_session.c.created_at)).all()
    assert [(r.ended_by is not None) for r in rows] == [True, False]


@pytest.mark.parametrize(
    ("given", "answered"),
    [
        (None, "/"),
        ("/", "/"),
        ("/#/p/maity/board?task=tsk-1", "/#/p/maity/board?task=tsk-1"),
        ("https://evil.example/#/x", "/"),
        ("//evil.example/#/x", "/"),
        ("/#//evil.example", "/"),
        ("/#/a#b", "/"),
        ("/#/a b", "/"),
        ("/#/a\\b", "/"),
        ("/#/a\nb", "/"),
        ("/admin", "/"),
        ("/#/" + "x" * 510, "/"),
        ("/#/" + "x" * 509, "/#/" + "x" * 509),
    ],
)
def test_login_answers_a_safe_next(
    make_client: ClientFactory, human: str, given: str | None, answered: str
) -> None:
    body = {"handle": "maintainer", "password": factory.PASSWORD}
    if given is not None:
        body["next"] = given
    response = make_client().post("/api/v1/auth/login", json=body)
    assert response.status_code == 200
    assert response.json()["next"] == answered


# --- the rules for sessions not in good standing (device code and mail link) ---------


def row(name: str, method: str, minutes_old: float) -> Any:
    return SimpleNamespace(
        id_hash=name, method=method, created_at=clock.now() - timedelta(minutes=minutes_old)
    )


def test_who_may_end_which_session() -> None:
    now = clock.now()
    strong = row("strong", "password", 600)
    weak_young = row("weak-young", "email_link", 10)
    weak_old = row("weak-old", "device_code", 300)
    newer_weak = row("newer", "email_code", 5)
    assert sessions.refusal(strong, weak_young, now) is None
    assert sessions.refusal(strong, newer_weak, now) is None
    assert sessions.refusal(weak_young, strong, now) == "not_in_good_standing"
    assert sessions.refusal(weak_old, strong, now) == "not_in_good_standing"
    assert sessions.refusal(weak_young, weak_old, now) == "session_too_new"
    assert sessions.refusal(weak_young, newer_weak, now) is None
    assert sessions.refusal(weak_old, weak_young, now) is None
    assert sessions.refusal(weak_young, weak_young, now) is None  # a logout


def test_ending_a_session_ends_what_it_approved(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    me = sign_in(make_client)
    approver = sign_in(make_client)
    approver_id = approver.get("/auth/session").json()["session_id"]
    now = clock.now()
    with migrated.begin() as conn:
        for public_id, approved_by in (("hss-child", approver_id), ("hss-grandchild", "hss-child")):
            conn.execute(
                insert(t.human_session).values(
                    id_hash=public_id * 2,
                    human_id=human,
                    csrf_token="0" * 64,
                    created_at=now,
                    last_seen_at=now,
                    expires_at=now + timedelta(days=30),
                    public_id=public_id,
                    method="device_code",
                    approved_by=approved_by,
                )
            )
    assert me.delete(f"/auth/sessions/{approver_id}").json()["ended_by"] == "revoked"
    ended = {i["id"]: i["ended_by"] for i in me.get("/auth/sessions?ended=true").json()["items"]}
    assert ended["hss-child"] == ended["hss-grandchild"] == "revoked"


@pytest.mark.parametrize(
    ("agent", "expected"),
    [
        (FIREFOX, ("Firefox", "Linux")),
        (SAFARI_IOS, ("Safari", "iOS")),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0",
            ("Edge", "Windows"),
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            ("Chrome", "macOS"),
        ),
        (
            "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/141.0.0.0 Mobile Safari/537.36",
            ("Chrome", "Android"),
        ),
        ("curl/8.9.1", (None, None)),
        (None, (None, None)),
        ("<script>alert(1)</script> Firefox/1", ("Firefox", None)),
    ],
)
def test_the_browser_and_system_names(agent: str | None, expected: tuple[Any, Any]) -> None:
    assert sessions.describe(agent) == expected


def test_the_migration_gives_existing_sessions_an_id(engine: Engine) -> None:
    migrate(engine, "0026")
    human_id = factory.human(engine, "maintainer")
    now = clock.now()
    # The table as revision 0026 had it: no column of the session list yet.
    before = sa.table(
        "human_session",
        *(sa.column(c, sa.String) for c in ("id_hash", "human_id", "csrf_token", "source")),
        *(sa.column(c, sa.DateTime) for c in ("created_at", "last_seen_at", "expires_at")),
        sa.column("ended_at", sa.DateTime),
    )
    with engine.begin() as conn:
        for name, ended in (("a" * 64, None), ("b" * 64, now)):
            conn.execute(
                sa.insert(before).values(
                    id_hash=name,
                    human_id=human_id,
                    csrf_token="0" * 64,
                    source="192.0.2.1",
                    created_at=now.replace(tzinfo=None),
                    last_seen_at=now.replace(tzinfo=None),
                    expires_at=(now + timedelta(days=30)).replace(tzinfo=None),
                    ended_at=ended.replace(tzinfo=None) if ended else None,
                )
            )
    migrate(engine)
    with engine.begin() as conn:
        rows = conn.execute(select(t.human_session).order_by(t.human_session.c.id_hash)).all()
    assert all(r.public_id.startswith("hss-") and r.method == "password" for r in rows)
    assert rows[0].public_id != rows[1].public_id
    assert [(r.ip, r.ended_by) for r in rows] == [("192.0.2.1", None), ("192.0.2.1", "logout")]


def test_an_ended_session_keeps_no_address(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    gone = sign_in(make_client)
    gone_id = gone.get("/auth/session").json()["session_id"]
    expired = sign_in(make_client)
    expired_id = expired.get("/auth/session").json()["session_id"]
    gone.post("/auth/logout")
    with migrated.begin() as conn:
        conn.execute(
            update(t.human_session)
            .where(t.human_session.c.public_id == expired_id)
            .values(last_seen_at=clock.now() - timedelta(days=15))
        )
    me = sign_in(make_client)
    listed = {i["id"]: i for i in me.get("/auth/sessions?ended=true").json()["items"]}
    assert listed[gone_id]["ip"] is None and listed[expired_id]["ip"] is None
    with migrated.begin() as conn:
        rows = {
            r.public_id: r
            for r in conn.execute(select(t.human_session)).all()
            if r.public_id in (gone_id, expired_id)
        }
    assert all(r.ip is None and r.source is None for r in rows.values())


# --- the instance's sign-in methods (§2.6.6) ----------------------------------------

SIGN_IN = "/admin/settings/sign-in"


def test_sign_in_settings_defaults_and_who_reads_them(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    got = owner.get(SIGN_IN).json()
    assert got == {
        "password": {"value": True, "source": "fixed"},
        "device_code": {"value": True, "source": "default"},
        "email_link": {"value": True, "source": "default"},
        "email_link_available": False,
        "missing": ["mail", "not_implemented"],
    }
    other = flow.human(make_client, migrated, "someone")
    assert other.get(SIGN_IN).json()["error"]["details"] == {"scope": "instance:admin"}
    assert other.patch(SIGN_IN, {"device_code": False}).status_code == 403
    agent = agent_named(make_client, owner, "agent-a")
    assert agent.get(SIGN_IN).status_code == 403
    assert agent.patch(SIGN_IN, {"device_code": False}).status_code == 403


def test_the_admin_switches_a_method_and_the_environment_wins(
    make_client: ClientFactory, migrated: Engine
) -> None:
    flow.human(make_client, migrated)
    client = make_client(sign_in_device_code=False)
    client.post("/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD})
    owner = flow.Human(client, client.get("/api/v1/auth/session").json()["csrf_token"], "")
    assert owner.get(SIGN_IN).json()["device_code"] == {"value": False, "source": "env"}
    refused = owner.patch(SIGN_IN, {"device_code": True})
    assert refused.json()["error"]["details"]["fields"] == {"device_code": "set_by_environment"}
    changed = owner.patch(SIGN_IN, {"email_link": False}).json()
    assert changed["email_link"] == {"value": False, "source": "admin"}
    assert changed["missing"][0] == "switched_off"
    back = owner.patch(SIGN_IN, {"email_link": None}).json()
    assert back["email_link"] == {"value": True, "source": "default"}


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"password": False}, {"password": "fixed"}),
        ({"sms": True}, {"sms": "extra_forbidden"}),
        ({"device_code": "no"}, {"device_code": "invalid"}),
    ],
)
def test_a_refused_sign_in_patch_changes_nothing(
    make_client: ClientFactory, migrated: Engine, body: dict[str, Any], fields: dict[str, str]
) -> None:
    owner = flow.human(make_client, migrated)
    response = owner.patch(SIGN_IN, {**body, "email_link": False})
    assert response.json()["error"]["details"]["fields"] == fields
    with migrated.begin() as conn:
        assert conn.execute(select(t.instance_setting)).all() == []


def test_a_switch_in_the_environment_must_be_a_flag() -> None:
    from maity_hub.config import ConfigError, Settings

    with pytest.raises(ConfigError):
        Settings.from_env({"MAITY_SIGN_IN_EMAIL_LINK": "maybe"})
    assert Settings.from_env({"MAITY_SIGN_IN_EMAIL_LINK": "0"}).sign_in_email_link is False
    assert Settings.from_env({}).sign_in_email_link is None
