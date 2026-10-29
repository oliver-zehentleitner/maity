"""The bell and the security mail of the second factor's account records (docs/api.md
§2.8.1, §18.1, §18.5)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub.notifications import records
from tests.conftest import ClientFactory
from tests.test_notification_address import S, outbox_rows
from tests.test_notification_mail import at as at  # noqa: F401  (the clock fixture)
from tests.test_notification_mail import notifications, run, setup

TITLES = [
    ({"change": "enrolled", "by": "maintainer"}, "Two-factor sign-in turned on"),
    ({"change": "disabled", "by": "maintainer"}, "Two-factor sign-in turned off"),
    ({"change": "recovery_codes", "by": "maintainer"}, "New recovery codes"),
    ({"change": "recovery_code_used", "by": "maintainer"}, "Recovery code used"),
    ({"change": "reset", "by": "grace"}, "Two-factor sign-in reset by grace"),
    ({"change": "reset", "by": "operator"}, "Two-factor sign-in reset by operator"),
    (
        {"change": "instance_off", "by": "environment"},
        "Two-factor sign-in turned off for this instance",
    ),
    ({"change": "something-new", "by": "x"}, "Two-factor sign-in changed"),
]
FAILED = {"method": "totp", "ip": "203.0.113.9", "browser": "Firefox", "os": "Linux"}


def write(engine: Engine, human_id: str, kind: str, data: dict[str, Any]) -> None:
    with engine.begin() as conn:
        records.write(conn, human_id, kind, data)


def bell(owner: Any) -> list[dict[str, Any]]:
    answer = owner.get("/me/notifications")
    assert answer.status_code == 200, answer.text
    return [i for i in answer.json()["items"] if i["kind"] == "security"]


@pytest.mark.parametrize(("data", "title"), TITLES)
def test_a_change_of_the_factor_is_a_security_item(
    make_client: ClientFactory, migrated: Engine, at: Any, data: dict[str, Any], title: str
) -> None:
    owner, _ = setup(make_client, migrated)
    write(migrated, owner.id, "second_factor_changed", data)
    shown = [i for i in bell(owner) if i["title"] == title]
    assert len(shown) == 1 and shown[0]["url"].endswith("/account/security")
    assert shown[0]["read"] is False


def test_wrong_codes_are_a_security_item_with_where_they_came_from(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, _ = setup(make_client, migrated)
    write(migrated, owner.id, "second_factor_failed", FAILED)
    [shown] = [i for i in bell(owner) if i["title"].startswith("Wrong second-factor codes")]
    assert shown["title"] == (
        "Wrong second-factor codes after a sign-in: Firefox on Linux, 203.0.113.9"
    )


def test_each_is_a_security_mail_of_its_own_and_goes_once(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, _ = setup(make_client, migrated)
    write(migrated, owner.id, "second_factor_changed", {"change": "reset", "by": "grace"})
    write(migrated, owner.id, "second_factor_changed", {"change": "enrolled", "by": "x"})
    write(migrated, owner.id, "second_factor_failed", FAILED)
    at(minutes=1)
    run(migrated)
    mails = [r for r in outbox_rows(migrated) if r.kind == "security" and r.status == "waiting"]
    subjects = sorted(
        m.subject for m in mails if "two-factor" in m.subject.lower() or "Wrong" in m.subject
    )
    assert subjects == [
        "[Maity] Two-factor sign-in reset by grace",
        "[Maity] Two-factor sign-in turned on",
        "[Maity] Wrong second-factor codes after a sign-in: Firefox on Linux, 203.0.113.9",
    ]
    reset = next(m for m in mails if "reset by grace" in m.subject)
    assert "/account/security" in reset.body and "List-Unsubscribe" in reset.headers
    assert "Maity only links to https://hub.example" in reset.body
    before = len(outbox_rows(migrated))
    at(minutes=3)
    run(migrated)
    assert len(outbox_rows(migrated)) == before  # each item was mailed once
    assert notifications(migrated) == []  # and none of them went into a digest


def test_the_security_switch_holds_these_mails_too(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, _ = setup(make_client, migrated)
    owner.patch(S, {"email": {"kinds": {"security": {"mode": "off"}}}})
    write(migrated, owner.id, "second_factor_changed", {"change": "reset", "by": "grace"})
    at(minutes=1)
    run(migrated)
    left = [r for r in outbox_rows(migrated) if "two-factor" in r.subject.lower()]
    assert left == []
    assert [i for i in bell(owner) if "reset by grace" in i["title"]]  # the bell still has it


def test_a_security_item_is_confirmed_from_a_session_older_than_it(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, _ = setup(make_client, migrated)
    at(minutes=1)
    write(migrated, owner.id, "second_factor_changed", {"change": "enrolled", "by": "x"})
    [item] = [i for i in bell(owner) if i["title"] == "Two-factor sign-in turned on"]
    owner.post("/me/notifications/read", {"ids": [item["id"]]})
    [after] = [i for i in bell(owner) if i["id"] == item["id"]]
    assert after["read"] is True
