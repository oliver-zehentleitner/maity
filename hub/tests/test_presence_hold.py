"""No notification mail while the human is present in the web app (docs/api.md §18.4, §18.5).

A tab's `POST /me/presence` moves the session's `present_until` two minutes ahead, at most
once a minute; the mail of an immediate item waits while it is in the future and for
`online_grace_minutes` after it, then goes if the item is still unread.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.mail.environment import parse
from maity_hub.notifications import presence
from tests import flow
from tests.conftest import ClientFactory
from tests.test_mail_settings import PATH as MAIL_SETTINGS
from tests.test_mail_settings import admin, env_of
from tests.test_notification_address import S
from tests.test_notification_mail import ask, notifications, run, setup
from tests.test_notification_mail import at as at  # noqa: F401  (the clock fixture)


def present(owner: flow.Human) -> None:
    response = owner.post("/me/presence")
    assert response.status_code == 204, response.text


def present_until(engine: Engine, owner: flow.Human) -> Any:
    with engine.begin() as conn:
        return conn.execute(
            select(t.human_session.c.present_until).where(
                t.human_session.c.human_id == owner.id, t.human_session.c.ended_at.is_(None)
            )
        ).scalar_one()


def test_an_immediate_item_waits_while_present_and_for_the_grace(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)  # at 00:30 of the test
    present(owner)  # present until 02:30
    ask(agent)
    at(minutes=3)
    run(migrated)
    assert notifications(migrated) == []  # its window has passed, but the human is present
    at(minutes=7, seconds=29)
    run(migrated)
    assert notifications(migrated) == []  # within the five minutes of grace
    at(minutes=7, seconds=31)
    run(migrated)
    [mail] = notifications(migrated)
    assert mail.subject.endswith("asks: Which?")


def test_an_item_read_while_held_is_not_mailed(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    present(owner)
    ask(agent)
    at(minutes=3)
    run(migrated)
    [item] = [i for i in owner.get("/me/notifications").json()["items"] if i["kind"] == "inbox"]
    assert owner.post("/me/notifications/read", {"ids": [item["id"]]}).status_code == 200
    at(minutes=30)
    run(migrated)
    assert notifications(migrated) == []


def test_without_the_setting_the_item_is_mailed_after_its_window(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    assert owner.get(S).json()["email"]["hold_while_online"] is True
    assert owner.patch(S, {"email": {"hold_while_online": False}}).status_code == 200
    present(owner)
    ask(agent)
    at(minutes=3)
    run(migrated)
    assert len(notifications(migrated)) == 1


def test_a_session_that_ends_stops_counting_at_once(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    present(owner)
    ask(agent)
    mine = owner.get("/auth/session").json()["session_id"]
    assert owner.delete(f"/auth/sessions/{mine}").status_code == 200
    at(minutes=3)
    run(migrated)
    assert len(notifications(migrated)) == 1  # its present_until is still in the future


def test_a_digest_is_built_at_its_moment_while_present(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    assert owner.patch(S, {"email": {"kinds": {"inbox": {"mode": "hourly"}}}}).status_code == 200
    run(migrated)  # the hour's clock starts
    present(owner)
    ask(agent)
    at(minutes=51)  # 13:01, past the full hour
    present(owner)
    run(migrated)
    assert len(notifications(migrated)) == 1


def test_the_suspension_mail_is_never_held(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    """The one `urgent` item (§18.5): mailed after its window even while the human is present."""
    owner, agent = setup(make_client, migrated)
    present(owner)
    seq = agent.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": "all", "body": "spam"},
    ).json()["seq"]
    made = owner.post(
        "/reports",
        {
            "target": {"type": "message", "id": str(seq), "project": "maintainer/maity"},
            "reason": "spam",
        },
    ).json()
    resolved = owner.post(
        f"/admin/reports/{made['id']}/resolve", {"action": "suspend", "note": "spam run"}
    )
    assert resolved.status_code == 200, resolved.text
    at(minutes=3)
    with migrated.begin() as conn:
        # A suspension ends the account's sessions (§16.8), so no hold could reach the mail.
        # Live again and present, the session tests the exclusion itself.
        conn.execute(
            update(t.human_session)
            .where(t.human_session.c.human_id == owner.id)
            .values(ended_at=None, last_seen_at=clock.now(), present_until=clock.now())
        )
        assert presence.held(conn, owner.id, clock.now(), timedelta(minutes=5))
    run(migrated)
    [mail] = notifications(migrated)
    assert "Moderation: suspend" in mail.subject + mail.body


def test_the_write_moves_present_until_at_most_once_a_minute(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, _ = setup(make_client, migrated)  # 00:30
    present(owner)
    first = present_until(migrated, owner)
    assert first == clock.now() + presence.PRESENT_FOR
    at(minutes=1, seconds=29)  # it would move by 59 s: no write
    present(owner)
    assert present_until(migrated, owner) == first
    at(minutes=1, seconds=30)  # by a minute: written
    present(owner)
    assert present_until(migrated, owner) == first + timedelta(minutes=1)


def test_the_call_writes_no_last_seen(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, _ = setup(make_client, migrated)
    with migrated.begin() as conn:
        conn.execute(update(t.human_session).values(last_seen_at=clock.now()))

    def seen() -> tuple[Any, ...]:
        with migrated.begin() as conn:
            return (
                conn.execute(
                    select(t.human_session.c.last_seen_at, t.human_session.c.ip).where(
                        t.human_session.c.human_id == owner.id
                    )
                ).all(),
                conn.execute(
                    select(t.human.c.last_seen_at).where(t.human.c.id == owner.id)
                ).scalar_one(),
                conn.execute(
                    select(t.membership.c.last_seen_at).where(t.membership.c.human_id == owner.id)
                ).all(),
            )

    before = seen()
    at(minutes=5)
    present(owner)
    assert seen() == before


def test_only_a_human_cookie_session_with_its_csrf_token_may_call(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    refused = agent.post("/me/presence")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"reason": "humans_only"}
    bridged = owner.client.post(
        "/api/v1/me/presence", headers={"X-CSRF-Token": owner.csrf, "Maity-For": agent.id}
    )
    assert bridged.status_code == 403
    assert bridged.json()["error"]["details"] == {"reason": "humans_only"}
    no_token = owner.client.post("/api/v1/me/presence")
    assert (no_token.status_code, no_token.json()["error"]["code"]) == (403, "csrf_mismatch")
    assert present_until(migrated, owner) is None
    anonymous = make_client().post("/api/v1/me/presence")
    assert anonymous.status_code == 401


def test_more_than_ten_calls_a_minute_are_rate_limited(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, _ = setup(make_client, migrated)
    for _ in range(10):
        present(owner)
    refused = owner.post("/me/presence")
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) > 0


def test_the_setting_is_a_boolean(make_client: ClientFactory, migrated: Engine, at: Any) -> None:
    owner, _ = setup(make_client, migrated)
    refused = owner.patch(S, {"email": {"hold_while_online": "yes"}})
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {"email.hold_while_online": "invalid"}


def test_the_grace_is_an_instance_mail_setting(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = admin(make_client, migrated, env_of())
    flow.project(owner)
    assert owner.get(MAIL_SETTINGS).json()["online_grace_minutes"] == {
        "value": 5,
        "source": "default",
    }
    assert owner.patch(MAIL_SETTINGS, {"online_grace_minutes": 0}).status_code == 200
    assert owner.get(MAIL_SETTINGS).json()["online_grace_minutes"]["value"] == 0
    refused = owner.patch(MAIL_SETTINGS, {"online_grace_minutes": 61})
    assert refused.json()["error"]["details"]["fields"] == {"online_grace_minutes": "invalid"}
    assert parse({"MAITY_MAIL_ONLINE_GRACE_MINUTES": "12"}).online_grace_minutes == 12
