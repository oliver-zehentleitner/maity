"""The bell and "This was me" (docs/api.md §2.6.5, §2.8.5, §18.2, §18.3; tsk-0kz8v1ff5sgf):
reading a security alert confirms nothing, a sign-in is confirmed by its own call, "mark all
read" takes security alerts on request, and the unread ones stand pinned on top."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import second_factor, sessions
from maity_hub.auth.caller import SESSION_COOKIE, session_id_hash
from maity_hub.db import migrate
from maity_hub.errors import ApiError
from maity_hub.notifications import records
from maity_hub.routes import auth
from tests import factory, flow
from tests.concurrency import finished, race, waiting
from tests.conftest import ClientFactory
from tests.test_sessions import sign_in

_PLANTED = [0]


@pytest.fixture
def human(migrated: Engine) -> str:
    return factory.human(migrated, "maintainer")


def plant(
    make_client: ClientFactory,
    engine: Engine,
    human_id: str,
    method: str,
    minutes_old: float,
    *,
    alert: bool = True,
) -> tuple[flow.Human, str]:
    """A live session made by `method`, with a cookie this test holds and, with `alert`, its
    `session_created` record as a sign-in writes it."""
    _PLANTED[0] += 1
    value, csrf = f"planted-bell-{_PLANTED[0]}", "c" * 64
    public_id = f"hss-bell{_PLANTED[0]:08d}"
    with engine.begin() as conn:
        conn.execute(
            insert(t.human_session).values(
                id_hash=session_id_hash(value),
                human_id=human_id,
                csrf_token=csrf,
                created_at=clock.now() - timedelta(minutes=minutes_old),
                last_seen_at=clock.now(),
                expires_at=clock.now() + timedelta(days=30),
                public_id=public_id,
                method=method,
            )
        )
        if alert:
            records.session_created(
                conn,
                human_id,
                {"session_id": public_id, "method": method, "browser": "Safari", "os": "iOS"},
            )
    client = make_client()
    client.cookies.set(SESSION_COOKIE, value)
    return flow.Human(client, csrf, human_id), public_id


def _session(engine: Engine, public_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.human_session).where(t.human_session.c.public_id == public_id)
        ).one()


def _listed(caller: flow.Human, public_id: str) -> dict[str, Any]:
    items = caller.get("/auth/sessions").json()["items"]
    return next(item for item in items if item["id"] == public_id)


def _alert(caller: flow.Human, public_id: str) -> dict[str, Any]:
    pinned = caller.get("/me/notifications").json()["pinned"]
    return next(i for i in pinned if i["target"] == {"type": "session", "id": public_id})


def _sign_in_alert_read(engine: Engine, public_id: str) -> bool:
    with engine.connect() as conn:
        return (
            records.sign_in_records(conn, _session(engine, public_id).human_id)[public_id].read_at
            is not None
        )


# --- "This was me" ------------------------------------------------------------------------


def test_this_was_me_confirms_and_marks_the_alert_read(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    strong = sign_in(make_client)
    strong_id = strong.get("/auth/session").json()["session_id"]
    _, weak_id = plant(make_client, migrated, human, "email_link", -1)  # after the sign-in
    assert _listed(strong, weak_id)["good_standing"] is False
    response = strong.post(f"/auth/sessions/{weak_id}/confirm", {})
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["id"] == weak_id and answer["good_standing"] is True
    assert answer["confirmed_by"] == strong_id and answer["confirmed_at"] is not None
    assert _listed(strong, weak_id)["confirmed_by"] == strong_id
    assert _sign_in_alert_read(migrated, weak_id)
    # Again: nothing changes, the first confirmation stays.
    again = strong.post(f"/auth/sessions/{weak_id}/confirm", {}).json()
    assert again["confirmed_at"] == answer["confirmed_at"]


def test_a_session_in_good_standing_already_only_gets_its_alert_read(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    older = sign_in(make_client)
    _, newer_id = plant(make_client, migrated, human, "password", -1)
    answer = older.post(f"/auth/sessions/{newer_id}/confirm", {}).json()
    assert answer["good_standing"] is True and answer["confirmed_at"] is None
    assert _sign_in_alert_read(migrated, newer_id)


@pytest.mark.parametrize("case", ["ended", "unknown", "another_human"])
def test_an_ended_or_foreign_session_is_not_found(
    make_client: ClientFactory, migrated: Engine, human: str, case: str
) -> None:
    strong = sign_in(make_client)
    if case == "another_human":
        other = factory.human(migrated, "someone")
        _, target = plant(make_client, migrated, other, "email_link", -1)
    elif case == "ended":
        _, target = plant(make_client, migrated, human, "email_link", -1)
        with migrated.begin() as conn:
            conn.execute(
                update(t.human_session)
                .where(t.human_session.c.public_id == target)
                .values(ended_at=clock.now(), ended_by="revoked")
            )
    else:
        target = "hss-nothing"
    response = strong.post(f"/auth/sessions/{target}/confirm", {})
    assert response.status_code == 404, response.text
    if case != "unknown":
        assert _session(migrated, target).confirmed_at is None


def test_the_checks_run_in_the_contracts_order(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    weak_old, weak_old_id = plant(make_client, migrated, human, "device_code", 300)
    weak_new, weak_new_id = plant(make_client, migrated, human, "email_link", 10)
    strong = sign_in(make_client)  # created now, after both
    for caller, target, reason in (
        (weak_new, weak_new_id, "not_earlier"),  # itself
        (strong, weak_new_id, "not_earlier"),  # created after it, though in good standing
        (weak_new, weak_old_id, "not_earlier"),
        (weak_old, weak_new_id, "not_in_good_standing"),  # earlier, but not in good standing
    ):
        response = caller.post(f"/auth/sessions/{target}/confirm", {})
        assert response.status_code == 403, response.text
        assert response.json()["error"]["details"] == {"reason": reason}
    assert _session(migrated, weak_new_id).confirmed_at is None
    assert not _sign_in_alert_read(migrated, weak_new_id)


def test_a_confirmed_session_confirms_and_ends_others(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    strong = sign_in(make_client)
    confirmed, confirmed_id = plant(make_client, migrated, human, "email_link", -1)
    _, later_id = plant(make_client, migrated, human, "email_code", -2)
    assert confirmed.post(f"/auth/sessions/{later_id}/confirm", {}).status_code == 403
    strong.post(f"/auth/sessions/{confirmed_id}/confirm", {})
    assert confirmed.post(f"/auth/sessions/{later_id}/confirm", {}).status_code == 200
    assert _session(migrated, later_id).confirmed_by == confirmed_id


# --- reading confirms nothing -------------------------------------------------------------


def test_reading_the_alert_by_id_confirms_nothing(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    strong = sign_in(make_client)
    _, weak_id = plant(make_client, migrated, human, "email_link", -1)
    alert = _alert(strong, weak_id)
    answer = strong.post("/me/notifications/read", {"ids": [alert["id"]]}).json()
    assert answer["skipped"] == []
    assert _sign_in_alert_read(migrated, weak_id)
    listed = _listed(strong, weak_id)
    assert (listed["good_standing"], listed["confirmed_at"], listed["confirmed_by"]) == (
        False,
        None,
        None,
    )
    pinned = strong.get("/me/notifications").json()["pinned"]
    assert [i for i in pinned if i["target"]["id"] == weak_id] == []


def test_a_session_that_may_not_mark_an_alert_is_told_why(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    weak_old, _ = plant(make_client, migrated, human, "device_code", 300)
    weak_new, weak_new_id = plant(make_client, migrated, human, "email_link", 10)
    alert = _alert(weak_old, weak_new_id)
    for caller, reason in ((weak_new, "not_earlier"), (weak_old, "not_in_good_standing")):
        answer = caller.post("/me/notifications/read", {"ids": [alert["id"]]}).json()
        assert answer["skipped"] == [{"id": alert["id"], "reason": reason}]
        assert answer["counts"]["security"] >= 1
    assert not _sign_in_alert_read(migrated, weak_new_id)


def test_mark_all_read_takes_security_alerts_only_when_asked(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    strong = sign_in(make_client)
    _, weak_id = plant(make_client, migrated, human, "email_link", -1)
    _, own_id = plant(make_client, migrated, human, "email_code", -2)
    with migrated.begin() as conn:  # a security kind any session may mark read
        records.write(conn, human, "second_factor_changed", {"change": "enabled"})
    strong_id = strong.get("/auth/session").json()["session_id"]
    own_alert = _alert(strong, strong_id)  # its own sign-in, which it may not mark
    head = strong.get("/me/notifications").json()
    assert head["counts"]["security"] == 4
    left = strong.post("/me/notifications/read", {"up_to": head["next_after"]}).json()
    assert left["counts"]["security"] == 4 and left["skipped"] == []
    marked = strong.post(
        "/me/notifications/read", {"up_to": head["next_after"], "include_security": True}
    ).json()
    assert marked["counts"]["security"] == 1
    assert marked["skipped"] == [{"id": own_alert["id"], "reason": "not_earlier"}]
    for public_id in (weak_id, own_id):
        assert _sign_in_alert_read(migrated, public_id)
        assert _listed(strong, public_id)["good_standing"] is False


def test_mark_all_read_from_a_weak_session_names_what_it_left(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    weak, weak_id = plant(make_client, migrated, human, "device_code", 300)
    _, other_id = plant(make_client, migrated, human, "email_link", 10)
    with migrated.begin() as conn:
        records.write(conn, human, "second_factor_changed", {"change": "enabled"})
    head = weak.get("/me/notifications").json()
    answer = weak.post(
        "/me/notifications/read", {"up_to": head["next_after"], "include_security": True}
    ).json()
    reasons = {item["reason"] for item in answer["skipped"]}
    assert len(answer["skipped"]) == 2 and reasons == {"not_earlier", "not_in_good_standing"}
    assert answer["counts"]["security"] == 2  # the second-factor alert went
    assert not _sign_in_alert_read(migrated, weak_id)
    assert not _sign_in_alert_read(migrated, other_id)


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_include_security_is_a_flag_for_up_to_only(
    make_client: ClientFactory, human: str, value: Any
) -> None:
    me = sign_in(make_client)
    head = me.get("/me/notifications").json()["next_after"]
    refused = me.post("/me/notifications/read", {"up_to": head, "include_security": value})
    assert refused.headers["Maity-Error"] == "invalid"
    with_ids = me.post("/me/notifications/read", {"ids": ["ntf-1"], "include_security": True})
    assert with_ids.headers["Maity-Error"] == "invalid"


def test_a_newer_session_not_in_good_standing_is_told_not_earlier(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    """Created after the sign-in, not the session it reports on, and not in good standing
    either: `not_earlier` comes first (§18.3), as it does for "This was me"."""
    old, old_id = plant(make_client, migrated, human, "email_link", 300)
    newer, _ = plant(make_client, migrated, human, "device_code", 10)
    alert = _alert(old, old_id)
    answer = newer.post("/me/notifications/read", {"ids": [alert["id"]]}).json()
    assert answer["skipped"] == [{"id": alert["id"], "reason": "not_earlier"}]
    assert not _sign_in_alert_read(migrated, old_id)


def test_a_newer_session_may_not_mark_an_older_sign_in_or_change(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    """Not the session it reports on, but created after it: `not_earlier`, checked before
    the standing, for a sign-in and for an address change alike (§18.3)."""
    _, old_id = plant(make_client, migrated, human, "email_link", 300)
    with migrated.begin() as conn:
        records.write(conn, human, "email_address_changed", {"address": "new@example.org"})
    strong = sign_in(make_client)  # in good standing, created after both
    pinned = strong.get("/me/notifications").json()["pinned"]
    sign_in_alert = _alert(strong, old_id)
    [change] = [i for i in pinned if i["target"] == {"type": "settings", "id": "notifications"}]
    answer = strong.post(
        "/me/notifications/read", {"ids": [sign_in_alert["id"], change["id"]]}
    ).json()
    assert sorted(answer["skipped"], key=lambda i: i["id"]) == sorted(
        [
            {"id": sign_in_alert["id"], "reason": "not_earlier"},
            {"id": change["id"], "reason": "not_earlier"},
        ],
        key=lambda i: i["id"],
    )
    assert not _sign_in_alert_read(migrated, old_id)


def test_an_earlier_session_in_good_standing_marks_an_address_change(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    strong = sign_in(make_client)
    with migrated.begin() as conn:
        conn.execute(  # signed in a minute before the change below
            update(t.human_session).values(created_at=clock.now() - timedelta(minutes=1))
        )
        records.write(conn, human, "email_address_changed", {"address": "new@example.org"})
    pinned = strong.get("/me/notifications").json()["pinned"]
    [change] = [i for i in pinned if i["target"] == {"type": "settings", "id": "notifications"}]
    answer = strong.post("/me/notifications/read", {"ids": [change["id"]]}).json()
    assert answer["skipped"] == []
    after = strong.get("/me/notifications").json()["pinned"]
    assert change["id"] not in [i["id"] for i in after]


# --- pinned -------------------------------------------------------------------------------


def test_pinned_holds_every_unread_security_alert_whatever_the_page(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    strong = sign_in(make_client)
    _, weak_id = plant(make_client, migrated, human, "email_link", -1)
    with migrated.begin() as conn:
        records.write(conn, human, "second_factor_changed", {"change": "enabled"})
        # Old, beyond any page, and beyond the 30 days that count other items as read.
        conn.execute(
            update(t.account_record)
            .where(t.account_record.c.type == "session_created")
            .values(at=clock.now() - timedelta(days=40))
        )
    for query in ("", "?limit=0", "?kind=chat", "?unread=true&kind=mention"):
        answer = strong.get(f"/me/notifications{query}").json()
        kinds = [i["kind"] for i in answer["pinned"]]
        assert kinds == ["security"] * 3, query  # its own sign-in, the planted one, the factor
        assert answer["pinned"][0]["target"] == {"type": "settings", "id": "security"}
        assert {"type": "session", "id": weak_id} in [i["target"] for i in answer["pinned"]]
    held = strong.get("/me/notifications").json()["next_after"]
    assert "pinned" not in strong.get(f"/me/notifications?after={held}").json()


def test_pinned_shows_the_newest_fifty(
    make_client: ClientFactory, migrated: Engine, human: str
) -> None:
    me = sign_in(make_client)
    with migrated.begin() as conn:
        for _ in range(52):
            records.write(conn, human, "second_factor_changed", {"change": "enabled"})
    answer = me.get("/me/notifications").json()
    assert len(answer["pinned"]) == 50 and answer["counts"]["security"] == 53  # and its own
    numbers = [int(i["id"].removeprefix("ntf-acr-")) for i in answer["pinned"]]
    assert numbers == sorted(numbers, reverse=True)


# --- a session moved into enrolment -------------------------------------------------------


def hold_at_enrolment(monkeypatch: pytest.MonkeyPatch) -> None:
    """From now on every full session of the human is held at enrolment, as when the policy
    came to ask for a second factor after its sign-in (§2.8.5)."""
    monkeypatch.setattr(second_factor, "must_enrol", lambda *args: True)


def test_a_moved_session_in_good_standing_reaches_the_confirm(
    make_client: ClientFactory, migrated: Engine, human: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    strong = sign_in(make_client)
    _, weak_id = plant(make_client, migrated, human, "email_link", -1)
    hold_at_enrolment(monkeypatch)
    assert strong.get("/auth/sessions").status_code == 403  # not one of the moved calls
    confirmed = strong.post(f"/auth/sessions/{weak_id}/confirm", {})
    assert confirmed.status_code == 200, confirmed.text
    assert strong.get("/me/notifications").status_code == 200


def test_a_moved_session_not_in_good_standing_keeps_nothing(
    make_client: ClientFactory, migrated: Engine, human: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    weak, _ = plant(make_client, migrated, human, "device_code", 300)
    _, newer_id = plant(make_client, migrated, human, "email_link", 10)
    hold_at_enrolment(monkeypatch)
    for refused in (
        weak.get("/me/notifications"),
        weak.post(f"/auth/sessions/{newer_id}/confirm", {}),
    ):
        assert refused.status_code == 403
        assert refused.json()["error"]["details"]["reason"] == "second_factor_enrolment_required"


# --- the migration ------------------------------------------------------------------------


def test_the_migration_carries_read_alerts_over_as_confirmations(engine: Engine) -> None:
    migrate(engine, "20261102230000_card_note_version")
    human_id = factory.human(engine, "maintainer")
    now = clock.now().replace(tzinfo=None)
    read_at = now - timedelta(hours=2)
    session = sa.table(
        "human_session",
        *(sa.column(c, sa.String) for c in ("id_hash", "human_id", "csrf_token")),
        *(sa.column(c, sa.String) for c in ("public_id", "method")),
        *(sa.column(c, sa.DateTime) for c in ("created_at", "last_seen_at", "expires_at")),
    )
    record = sa.table(
        "account_record",
        sa.column("human_id", sa.String),
        sa.column("type", sa.String),
        sa.column("data", sa.JSON),
        sa.column("at", sa.DateTime),
        sa.column("read_at", sa.DateTime),
        sa.column("read_by", sa.String),
    )
    with engine.begin() as conn:
        for name in ("read", "unread", "unattributed", "strong"):
            conn.execute(
                sa.insert(session).values(
                    id_hash=name.ljust(64, "0"),
                    human_id=human_id,
                    csrf_token="0" * 64,
                    public_id=f"hss-{name}",
                    method="email_link",
                    created_at=now,
                    last_seen_at=now,
                    expires_at=now + timedelta(days=14),
                )
            )
        for name, read, by in (
            ("read", read_at, "hss-strong"),
            ("unread", None, None),
            ("unattributed", read_at, None),
        ):
            conn.execute(
                sa.insert(record).values(
                    human_id=human_id,
                    type="session_created",
                    data={"session_id": f"hss-{name}"},
                    at=now,
                    read_at=read,
                    read_by=by,
                )
            )
    migrate(engine)
    with engine.connect() as conn:
        rows = {
            r.public_id: (r.confirmed_at, r.confirmed_by)
            for r in conn.execute(select(t.human_session))
        }
    assert rows["hss-read"][1] == "hss-strong"
    assert rows["hss-read"][0] is not None
    assert rows["hss-read"][0].replace(tzinfo=None) == read_at
    assert rows["hss-unread"] == (None, None)
    assert rows["hss-unattributed"] == (None, None)
    assert rows["hss-strong"] == (None, None)


def test_a_fresh_enrolment_sign_in_is_no_moved_session(
    make_client: ClientFactory, migrated: Engine, human: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, weak_id = plant(make_client, migrated, human, "email_link", 10)
    hold_at_enrolment(monkeypatch)
    fresh = sign_in(make_client)  # by password, but its sign-in waits for the enrolment
    for refused in (
        fresh.get("/me/notifications"),
        fresh.post(f"/auth/sessions/{weak_id}/confirm", {}),
    ):
        assert refused.json()["error"]["details"]["reason"] == "second_factor_enrolment_required"


@pytest.mark.parametrize("method", ["email_link", "password"])
def test_a_confirm_that_loses_to_an_end_is_not_found(
    make_client: ClientFactory,
    migrated: Engine,
    human: str,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    """The session ended between the confirm's look at it and its hold on it: whether it
    still needed confirming or already stood in good standing, the confirm answers as if it
    had come after the end."""
    strong = sign_in(make_client)
    _, weak_id = plant(make_client, migrated, human, method, -1)
    with migrated.begin() as conn:  # the DELETE that won the race
        conn.execute(
            update(t.human_session)
            .where(t.human_session.c.public_id == weak_id)
            .values(ended_at=clock.now(), ended_by="revoked")
        )
    real = sessions.ended
    looks = [0]

    def ended_meanwhile(row: Any, now: Any) -> Any:
        """The confirm's first look still saw the session alive; every later look is true."""
        if row.public_id == weak_id:
            looks[0] += 1
            if looks[0] == 1:
                return None
        return real(row, now)

    monkeypatch.setattr(sessions, "ended", ended_meanwhile)
    response = strong.post(f"/auth/sessions/{weak_id}/confirm", {})
    assert response.status_code == 404, response.text
    assert looks[0] == 2  # the first look, and the one on the held row
    assert _session(migrated, weak_id).confirmed_at is None
    assert not _sign_in_alert_read(migrated, weak_id)


def _end_in(conn: Any, public_id: str) -> None:
    """What `DELETE /auth/sessions/{id}` writes, in a transaction the race holds open."""
    conn.execute(
        update(t.human_session)
        .where(t.human_session.c.public_id == public_id)
        .values(ended_at=clock.now(), ended_by="revoked")
    )


@pytest.mark.parametrize("method", ["email_link", "password"])
def test_a_confirm_waits_for_a_running_end_and_is_not_found(
    make_client: ClientFactory, migrated: Engine, human: str, method: str
) -> None:
    """An end holds the target and commits; the confirm that waited for it finds the session
    ended: nothing confirmed, the alert unread, whether the target needed confirming or was
    in good standing already (§2.6.5)."""
    strong = sign_in(make_client)
    _, target_id = plant(make_client, migrated, human, method, -1)
    current = session_id_hash(strong.client.cookies[SESSION_COOKIE])
    with race(migrated) as r:
        ender, confirmer = r.first, r.second
        _end_in(ender, target_id)
        step = r.run(confirmer, lambda: auth.confirm(confirmer, human, current, target_id))
        assert waiting(step)
        ender.commit()
        with pytest.raises(ApiError) as refused:
            finished(step)
        assert refused.value.status == 404
    assert _session(migrated, target_id).confirmed_at is None
    assert not _sign_in_alert_read(migrated, target_id)


@pytest.mark.parametrize("method", ["email_link", "password"])
def test_an_end_waits_for_a_running_confirm_and_ends_it(
    make_client: ClientFactory, migrated: Engine, human: str, method: str
) -> None:
    """The confirm holds the target first: the end waits for it and then ends the session,
    whose sign-in stays confirmed and its alert read."""
    strong = sign_in(make_client)
    _, target_id = plant(make_client, migrated, human, method, -1)
    current = session_id_hash(strong.client.cookies[SESSION_COOKIE])
    with race(migrated) as r:
        confirmer, ender = r.first, r.second
        auth.confirm(confirmer, human, current, target_id)
        step = r.run(ender, lambda: _end_in(ender, target_id))
        assert waiting(step)
        confirmer.commit()
        finished(step)
        ender.commit()
    row = _session(migrated, target_id)
    assert row.ended_at is not None
    assert (row.confirmed_at is not None) is (method == "email_link")
    assert _sign_in_alert_read(migrated, target_id)
