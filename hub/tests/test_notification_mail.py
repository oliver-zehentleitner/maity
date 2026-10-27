"""Notification mail: when it goes out and what it says (docs/api.md §18.4, §18.5)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.notifications import mailer
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_notification_address import S, mail_env, outbox_rows, verified

PUBLIC = "https://hub.example"


@pytest.fixture
def at() -> Any:
    """Move the hub's clock: `at(minutes=3)` is three minutes after the test began."""
    start = clock.now().replace(minute=10, second=0, microsecond=0)
    clock.set_source(lambda: start)

    def move(**delta: float) -> datetime:
        moment = start + timedelta(**delta)
        clock.set_source(lambda: moment)
        return moment

    return move


def setup(make_client: ClientFactory, engine: Engine) -> tuple[flow.Human, flow.Agent]:
    owner = verified(make_client, engine, "me@example.org")
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    with engine.begin() as conn:  # the verification mail is out of the way
        conn.execute(update(t.mail_outbox).values(status="sent"))
    # What follows happens after joining: the clock moves on from the set-up.
    later = clock.now() + timedelta(seconds=30)
    clock.set_source(lambda: later)
    return owner, agent


def run(engine: Engine) -> int:
    return mailer.run(engine, mail_env().mail, None, PUBLIC)


def notifications(engine: Engine) -> list[Any]:
    return [r for r in outbox_rows(engine) if r.kind == "notification" and r.status == "waiting"]


def ask(agent: flow.Agent, title: str = "Which?") -> Any:
    asked = agent.post(
        "/projects/maity/requests", {"class": "decision", "title": title, "to": "owner"}
    )
    assert asked.status_code == 201, asked.text
    return asked.json()


def test_an_immediate_item_waits_its_window_and_goes_once(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    ask(agent)
    run(migrated)
    assert notifications(migrated) == []  # inside the two-minute window
    at(minutes=3)
    run(migrated)
    [mail] = notifications(migrated)
    assert mail.recipient == "me@example.org"
    assert mail.subject.startswith("[Maity] Maity: ") and mail.subject.endswith("asks: Which?")
    assert "https://hub.example/#/p/maity/inbox" in mail.body
    assert "Maity only links to https://hub.example" in mail.body
    assert "Stop these mails (inbox): https://hub.example/mail/unsubscribe/" in mail.body
    assert mail.headers["List-Unsubscribe"].startswith("<https://hub.example/mail/unsubscribe/")
    assert mail.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    at(minutes=10)
    run(migrated)
    assert len(notifications(migrated)) == 1  # an item goes out once


def test_an_item_read_first_is_not_mailed(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    agent.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": "hi"})
    owner.patch(S, {"email": {"kinds": {"chat": {"mode": "immediate"}}}})
    chat = next(i for i in owner.get("/me/notifications").json()["items"] if i["kind"] == "chat")
    owner.post("/me/notifications/read", {"ids": [chat["id"]]})
    at(minutes=5)
    run(migrated)
    assert notifications(migrated) == []


def test_quiet_hours_hold_everything_but_security(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    now = clock.now()
    window = {"from": (now - timedelta(hours=1)).strftime("%H:%M"),
              "to": (now + timedelta(hours=2)).strftime("%H:%M")}  # fmt: skip
    owner.patch(S, {"email": {"quiet_hours": window}})
    ask(agent)
    client = make_client(peer="198.51.100.40")
    client.post("/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD})
    at(minutes=5)
    run(migrated)
    assert notifications(migrated) == []
    alerts = [
        r
        for r in outbox_rows(migrated)
        if r.kind == "security" and r.status == "waiting" and "198.51.100.40" in r.body
    ]
    assert len(alerts) == 1
    assert "hss-" not in alerts[0].body  # never a session id
    at(hours=3)
    run(migrated)
    assert len(notifications(migrated)) == 1  # sent when they end


def test_sign_in_alerts_follow_the_security_switch(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, _ = setup(make_client, migrated)
    owner.patch(S, {"email": {"kinds": {"security": {"mode": "off"}}}})
    make_client().post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    run(migrated)
    assert [
        r for r in outbox_rows(migrated) if r.kind == "security" and r.status == "waiting"
    ] == []


def test_hourly_items_wait_for_the_full_hour(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    run(migrated)  # starts the hourly clock
    for n in range(2):
        agent.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": f"m{n}"})
    at(minutes=20)
    run(migrated)
    assert notifications(migrated) == []
    at(minutes=55)
    run(migrated)
    [digest] = notifications(migrated)
    assert digest.subject == "[Maity] 2 updates"
    assert '"Maity"' in digest.body  # the project, quoted


def test_daily_items_wait_for_daily_at(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    owner.patch(
        S,
        {
            "email": {
                "daily_at": (clock.now() + timedelta(hours=2)).strftime("%H:%M"),
                "kinds": {"inbox": {"mode": "daily"}},
            }
        },
    )
    run(migrated)
    ask(agent, "Mine")
    at(hours=1)
    run(migrated)
    assert all("Mine" not in r.body for r in notifications(migrated))
    at(hours=2, minutes=5)
    run(migrated)
    assert any("Mine" in r.body for r in notifications(migrated))


def test_ten_immediate_mails_an_hour_then_the_hour_collects(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    run(migrated)
    with migrated.begin() as conn:
        for _ in range(10):
            conn.execute(
                insert(t.mail_outbox).values(
                    kind="notification", human_id=owner.id, recipient="me@example.org",
                    subject="s", body="b", headers={}, created_at=clock.now(),
                    not_before=clock.now(), attempts=0, status="sent",
                )
            )  # fmt: skip
    ask(agent)
    at(minutes=5)
    run(migrated)
    assert notifications(migrated) == []
    at(minutes=55)
    run(migrated)
    assert len(notifications(migrated)) == 1


def test_text_from_others_is_quoted_and_defanged(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    ask(agent, "Sign in at https://evil.example/login or www.evil.example now")
    at(minutes=3)
    run(migrated)
    [mail] = notifications(migrated)
    assert "https://evil" not in mail.body and "www.evil" not in mail.body
    assert "https[:]//evil[.]example/login" in mail.body
    assert "www[.]evil[.]example" in mail.body


def test_chat_text_only_when_asked(make_client: ClientFactory, migrated: Engine, at: Any) -> None:
    owner, agent = setup(make_client, migrated)
    owner.patch(S, {"email": {"kinds": {"chat": {"mode": "immediate", "content": True}}}})
    agent.post(
        f"/projects/maity/conversations/{agent.id}/messages", {"body": "the tests are green"}
    )
    at(minutes=3)
    run(migrated)
    [mail] = notifications(migrated)
    assert '(agent) wrote: "the tests are green"' in mail.body


def test_items_from_before_the_address_was_verified_stay_out(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    ask(agent)
    with migrated.begin() as conn:
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == owner.id)
            .values(verified_at=clock.now() + timedelta(minutes=1))
        )
    at(minutes=5)
    run(migrated)
    assert notifications(migrated) == []


def test_nothing_without_complete_mail_settings(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    ask(agent)
    at(minutes=5)
    assert mailer.run(migrated, mail_env().mail.__class__(), None, PUBLIC) == 0


def test_defang() -> None:
    assert mailer.defang("see http://x.io and me@example.org") == (
        "see http[:]//x[.]io and me@example[.]org"
    )
    assert mailer.defang("version 1.2 stays") == "version 1.2 stays"


def test_a_digest_lists_fifty_and_counts_the_rest(migrated: Engine) -> None:
    from zoneinfo import ZoneInfo

    from maity_hub.notifications.items import Item
    from maity_hub.notifications.preferences import DEFAULTS

    many = [
        Item(kind="inbox", at=clock.now(), title=f"t{n}", target=None, url=f"{PUBLIC}/#/x", seq=n)
        for n in range(53)
    ]
    with migrated.begin() as conn:
        subject, body, kinds = mailer.compose(
            conn, many, DEFAULTS["email"], PUBLIC, ZoneInfo("UTC")
        )
    assert subject == "[Maity] 53 updates" and kinds == ["inbox"]
    assert body.count("\n- ") + body.startswith("- ") == 50
    assert "and 3 more: https://hub.example/#/" in body


def test_over_the_instance_budget_mail_waits_and_merges_into_one(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    from maity_hub import instance_settings as store

    owner, agent = setup(make_client, migrated)
    run(migrated)  # starts the digest clocks
    with migrated.begin() as conn:
        store.put(conn, "mail.max_per_hour", 1, None)
        conn.execute(
            t.mail_delivery.insert().values(kind="notification", outcome="sent", at=clock.now())
        )
    ask(agent)  # immediate
    agent.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": "hourly"})
    at(minutes=5)
    run(migrated)
    assert notifications(migrated) == []  # held: the instance is at its budget
    at(minutes=75)  # the hour's sent mail has left the window
    run(migrated)
    [merged] = notifications(migrated)
    assert merged.subject == "[Maity] 2 updates"
    assert "asks: Which?" in merged.body and "/chat/" in merged.body
    at(minutes=140)
    run(migrated)
    assert len(notifications(migrated)) == 1  # nothing twice


def test_one_pass_sends_one_mail_and_stays_within_the_budget(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    from maity_hub import instance_settings as store

    owner, agent = setup(make_client, migrated)
    run(migrated)  # starts the digest clocks
    with migrated.begin() as conn:
        store.put(conn, "mail.max_per_hour", 1, None)
    agent.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": "hourly"})
    at(minutes=48)
    ask(agent)  # immediate, older than its window by the next pass
    at(minutes=53)
    # Both the immediate item and the hour's digest fall due in this one pass.
    run(migrated)
    assert len(notifications(migrated)) == 1
    [mail] = notifications(migrated)
    assert mail.subject == "[Maity] 2 updates"


def test_the_writers_name_is_defanged_too(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    other = flow.human(make_client, migrated, "someone")
    from tests.test_group_chats import create, say

    with migrated.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        conn.execute(
            update(t.human)
            .where(t.human.c.id == other.id)
            .values(display_name="https://evil.example/login\nclick")
        )
    factory.membership(migrated, project_id, "member", human_id=other.id)
    owner.patch(S, {"email": {"kinds": {"chat": {"mode": "immediate", "content": True}}}})
    chat = create(owner, other.id, title="Room").json()
    say(other, chat["id"], "hello")
    at(minutes=3)
    run(migrated)
    [mail] = notifications(migrated)
    assert "https://evil" not in mail.body and "\nclick wrote" not in mail.body
    assert 'https[:]//evil[.]example/login click wrote: "hello"' in mail.body


def test_two_passes_at_once_send_one_mail(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    import threading

    owner, agent = setup(make_client, migrated)
    ask(agent)
    at(minutes=3)
    barrier = threading.Barrier(2)

    def one_pass() -> None:
        barrier.wait()
        run(migrated)

    passes = [threading.Thread(target=one_pass) for _ in range(2)]
    for thread in passes:
        thread.start()
    for thread in passes:
        thread.join()
    assert len(notifications(migrated)) == 1


# --- what the narrowed §18 changes ----------------------------------------------------


def test_a_pass_over_a_quiet_human_derives_nothing(
    make_client: ClientFactory, migrated: Engine, at: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cost of a pass must not grow with the human's history (the incident of
    2026-10-26): with nothing moved and nothing waiting it reads a few aggregates."""
    from maity_hub.notifications import items

    owner, agent = setup(make_client, migrated)
    run(migrated)  # the first pass derives and stores the stamp
    calls: list[int] = []
    real = items.derive

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(items, "derive", counted)
    at(minutes=30)
    run(migrated)
    run(migrated)
    assert calls == []
    ask(agent)  # something moved: the next pass derives again
    at(minutes=35)
    run(migrated)
    assert calls != []


def test_an_item_waiting_for_its_hour_keeps_the_passes_deriving(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    run(migrated)
    agent.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": "later"})
    at(minutes=20)
    run(migrated)  # hourly chat: waits, nothing moves any more
    with migrated.begin() as conn:
        assert conn.execute(select(t.notification_mail_state.c.waiting)).scalar() is True
    at(minutes=55)
    run(migrated)
    assert len(notifications(migrated)) == 1  # it still went out at the hour
    with migrated.begin() as conn:
        assert conn.execute(select(t.notification_mail_state.c.waiting)).scalar() is False


def test_a_kind_switched_off_waits_for_nothing(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    owner.patch(S, {"email": {"kinds": {"chat": {"mode": "off"}}}})
    agent.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": "silent"})
    at(minutes=5)
    run(migrated)
    assert notifications(migrated) == []
    with migrated.begin() as conn:
        assert conn.execute(select(t.notification_mail_state.c.waiting)).scalar() is False


def test_the_open_matters_are_never_mailed(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    from maity_hub.notifications import records

    owner, _ = setup(make_client, migrated)
    with migrated.begin() as conn:
        records.write(conn, owner.id, "mail_disabled", {"address": "me@example.org"})
        records.write(conn, owner.id, "registration_pending", {"handle": "ada"})
    at(minutes=5)
    run(migrated)
    assert notifications(migrated) == []


def test_a_message_text_never_comes_from_a_redacted_event(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    owner.patch(S, {"email": {"kinds": {"chat": {"mode": "immediate", "content": True}}}})
    sent = agent.post(
        f"/projects/maity/conversations/{agent.id}/messages", {"body": "secret words"}
    ).json()
    with migrated.begin() as conn:
        conn.execute(update(t.event).where(t.event.c.seq == sent["seq"]).values(redacted=True))
    at(minutes=3)
    run(migrated)
    assert all("secret words" not in r.body for r in outbox_rows(migrated))
