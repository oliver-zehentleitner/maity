"""docs/api.md §18.1, §18.4: the consent request an invitation by handle files (§3.4) reaches the
person under the notification kind `invitation`, with its own browser switch and mail mode
(`immediate` by default; `daily` or `off` keeps it on the platform only). Every other personal
request stays `inbox`, and the counts stay as they are: open requests count in `inbox`."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, update

from maity_hub import clock, invitations
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_notification_address import S, verified
from tests.test_notification_mail import at as at  # noqa: F401  (the clock fixture)
from tests.test_notification_mail import notifications, run

LAB = "/projects/olga/lab/invitations"


@pytest.fixture(autouse=True)
def _fresh() -> None:
    invitations.PER_PROJECT.reset()


def setup(make_client: ClientFactory, engine: Engine) -> tuple[flow.Human, flow.Human]:
    """`maintainer` with a verified address is invited; `olga` invites to her project `lab`."""
    anna = verified(make_client, engine, "me@example.org")
    olga = flow.human(make_client, engine, "olga")
    flow.project(olga, "lab")
    with engine.begin() as conn:  # the verification mail is out of the way
        conn.execute(update(t.mail_outbox).values(status="sent"))
    later = clock.now() + timedelta(seconds=30)
    clock.set_source(lambda: later)
    return anna, olga


def invite(olga: flow.Human) -> dict[str, Any]:
    made = olga.post(LAB, {"handle": "maintainer"})
    assert made.status_code == 201, made.text
    body: dict[str, Any] = made.json()
    return body


def items(who: flow.Human, **params: str) -> list[dict[str, Any]]:
    got = who.get("/me/notifications", params=params)
    assert got.status_code == 200, got.text
    found: list[dict[str, Any]] = got.json()["items"]
    return found


def test_the_request_of_an_invitation_by_handle_is_an_invitation_item(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    anna, olga = setup(make_client, migrated)
    invite(olga)
    [item] = [i for i in items(anna) if i["target"]["type"] == "request"]
    assert item["kind"] == "invitation"
    assert item["project"]["full_name"] == "olga/lab" and item["project"]["member"] is False
    assert [i["id"] for i in items(anna, kind="invitation")] == [item["id"]]
    assert [i for i in items(anna, kind="inbox") if i["id"] == item["id"]] == []
    counts = anna.get("/me/notifications").json()["counts"]
    assert counts["inbox"] == 1  # an open request, whatever its item's kind
    assert set(counts) == {"inbox", "chat", "mention", "security", "total"}


def test_an_invitation_mail_follows_its_own_kind_not_the_inbox(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    anna, olga = setup(make_client, migrated)
    assert anna.patch(S, {"email": {"kinds": {"inbox": {"mode": "off"}}}}).status_code == 200
    invite(olga)
    at(minutes=5)
    run(migrated)
    [mail] = notifications(migrated)
    assert mail.recipient == "me@example.org"
    assert "Stop these mails (invitation): https://hub.example/mail/unsubscribe/" in mail.body


def test_switched_off_the_invitation_stays_on_the_platform_only(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    anna, olga = setup(make_client, migrated)
    changed = anna.patch(S, {"email": {"kinds": {"invitation": {"mode": "off"}}}})
    assert changed.status_code == 200, changed.text
    invite(olga)
    at(minutes=5)
    run(migrated)
    assert notifications(migrated) == []  # the inbox mode, immediate, does not carry it
    assert [i["kind"] for i in items(anna, kind="invitation")] == ["invitation"]


def test_every_other_personal_request_stays_an_inbox_item(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    """An organisation's invitation is a personal request too, and not of this kind."""
    from tests.test_orgs import make_org

    anna, olga = setup(make_client, migrated)
    make_org(olga, "olga-team", "Olga Team")
    asked = olga.post(
        "/orgs/olga-team/members/invitations", {"handle": "maintainer", "role": "member"}
    )
    assert asked.status_code == 202, asked.text
    requested = [i for i in items(anna) if i["target"]["type"] == "request"]
    assert requested and {i["kind"] for i in requested} == {"inbox"}
