"""Changing or removing the verified address and approving a held change need the second
factor within the last ten minutes (docs/api.md §2.8.4)."""

from __future__ import annotations

import base64
import re
from typing import Any

from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_notification_address import S, mail_env, outbox_rows
from tests.test_two_factor import KEY, Clock, code_now, signed_in
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

NEW = {"email": {"address": "new@example.org"}, "current_password": factory.PASSWORD}


def enrol(human: flow.Human, moment: Clock) -> bytes:
    started = human.post("/auth/second-factor/totp")
    assert started.status_code == 200, started.text
    encoded = started.json()["secret"]
    secret = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
    done = human.post("/auth/second-factor/totp/confirm", {"code": code_now(secret, moment.at)})
    assert done.status_code == 200, done.text
    return secret


def confirm_link(person: flow.Human, migrated: Engine) -> None:
    mail = outbox_rows(migrated)[-1]
    found = re.search(r"https://hub\.example/mail/verify/(\S+)", mail.body)
    assert found, mail.body
    assert person.client.post(f"/mail/verify/{found.group(1)}").status_code == 200


def person(make_client: ClientFactory, migrated: Engine, moment: Clock) -> tuple[flow.Human, bytes]:
    """Enrolled, with a verified address, and the factor given a long time ago."""
    human = signed_in(make_client, migrated, secret_key=KEY, mail=mail_env().mail)
    human.patch(S, {"email": {"address": "old@example.org"}})
    confirm_link(human, migrated)
    secret = enrol(human, moment)
    moment.move(minutes=11)
    return human, secret


def given(human: flow.Human, secret: bytes, moment: Clock) -> None:
    assert human.post("/auth/second-factor/verify", {"code": code_now(secret, moment.at)})


def address_of(human: flow.Human) -> Any:
    return human.get(S).json()["email"]


def test_changing_the_verified_address_needs_a_recent_factor(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human, secret = person(make_client, migrated, moment)
    mails = len(outbox_rows(migrated))
    refused = human.patch(S, NEW)
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "step_up_required"
    assert address_of(human)["pending_address"] is None
    assert len(outbox_rows(migrated)) == mails  # nothing was sent
    given(human, secret, moment)
    ok = human.patch(S, NEW)
    assert ok.status_code == 200
    assert address_of(human)["pending_address"] == "new@example.org"


def test_removing_the_verified_address_needs_a_recent_factor(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human, secret = person(make_client, migrated, moment)
    refused = human.patch(S, {"email": {"address": None}, "current_password": factory.PASSWORD})
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "step_up_required"
    assert address_of(human)["address"] == "old@example.org"
    given(human, secret, moment)
    removed = human.patch(S, {"email": {"address": None}, "current_password": factory.PASSWORD})
    assert removed.status_code == 200 and address_of(human)["address"] is None


def test_what_is_not_a_change_of_the_verified_address_asks_for_nothing(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human, _ = person(make_client, migrated, moment)
    # The same address again only sends a new link.
    assert human.patch(S, {"email": {"address": "old@example.org"}}).status_code == 200
    # A human without a verified address sets the first one without the factor.
    other = factory.human(migrated, "grace")
    client = make_client(secret_key=KEY, mail=mail_env().mail)
    client.post("/api/v1/auth/login", json={"handle": "grace", "password": factory.PASSWORD})
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    grace = flow.Human(client, csrf, other)
    enrol(grace, moment)
    moment.move(minutes=11)
    assert grace.patch(S, {"email": {"address": "grace@example.org"}}).status_code == 200


def test_a_human_who_is_not_enrolled_is_not_asked(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human = signed_in(make_client, migrated, secret_key=KEY, mail=mail_env().mail)
    human.patch(S, {"email": {"address": "old@example.org"}})
    confirm_link(human, migrated)
    moment.move(minutes=11)
    assert human.patch(S, NEW).status_code == 200


def hold(migrated: Engine, human: flow.Human) -> dict[str, Any]:
    """A held change, as a session out of good standing would have left it."""
    with migrated.begin() as conn:
        session = conn.execute(select(t.human_session.c.public_id)).scalars().first()
        change = {
            "id": "adc-0123456789ab",
            "address": "new@example.org",
            "requested_at": clock.rfc3339(clock.now()),
            "session_id": session,
        }
        conn.execute(
            t.notification_settings.update()
            .where(t.notification_settings.c.human_id == human.id)
            .values(address_change=change)
        )
    return change


def decide(human: flow.Human, change: dict[str, Any], what: str) -> Any:
    return human.post(
        f"/me/notification-settings/email/address-change/{what}",
        {"id": change["id"], "address": change["address"]},
    )


def test_approving_a_held_change_needs_a_recent_factor_rejecting_does_not(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human, secret = person(make_client, migrated, moment)
    change = hold(migrated, human)
    moment.move(hours=25)  # the session is old enough to approve, the factor is long stale
    refused = decide(human, change, "approve")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "step_up_required"
    assert address_of(human)["pending_address"] is None
    given(human, secret, moment)
    approved = decide(human, change, "approve")
    assert approved.status_code == 200, approved.text
    assert address_of(human)["pending_address"] == "new@example.org"


def test_rejecting_a_held_change_needs_no_factor(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    human, _ = person(make_client, migrated, moment)
    change = hold(migrated, human)
    moment.move(hours=25)
    rejected = decide(human, change, "reject")
    assert rejected.status_code == 200, rejected.text
    assert address_of(human).get("address_change") is None
