"""docs/api.md §3.4, an invitation by handle: bound to one approved, active person at issue,
answered in that person's inbox as a personal consent request (§7), `go` accepting with the
checks of accept and `no` declining; every other handle refused, nothing stored."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, insert, select, update

from maity_hub import clock, events, invitations
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_invitations import PATH, accept, issue, kinds, member, project_id, reason, token_of
from tests.test_orgs import make_org


@pytest.fixture(autouse=True)
def _fresh() -> Iterator[None]:
    invitations.PER_PROJECT.reset()
    yield


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def invite(by: flow.Human, handle: str, **body: Any) -> Any:
    return by.post(PATH, {"handle": handle, **body})


def requests_of(who: flow.Human, status: str = "open") -> list[dict[str, Any]]:
    got = who.get("/requests", params={"status": status})
    assert got.status_code == 200, got.text
    items: list[dict[str, Any]] = got.json()["items"]
    return items


def answer(who: flow.Human, request_id: str, reply: str) -> Any:
    return who.post(f"/requests/{request_id}/answer", {"reply_id": reply})


def row_of(engine: Engine, invitation_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.invitation).where(t.invitation.c.id == invitation_id)).one()


def request_status(engine: Engine, request_id: str) -> str:
    with engine.connect() as conn:
        found = conn.execute(select(t.request.c.status).where(t.request.c.id == request_id))
        return str(found.scalar_one())


def is_member(engine: Engine, human_id: str) -> bool:
    with engine.connect() as conn:
        found = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.human_id == human_id, t.membership.c.active.is_(True)
            )
        ).first()
    return found is not None


def test_an_invitation_by_handle_reaches_the_person_in_their_inbox(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    made = invite(owner, "anna", trust="guest", role="reviewer", note="The web side.")
    assert made.status_code == 201, made.text
    body = made.json()
    with migrated.connect() as conn:
        shown = conn.execute(select(t.human.c.display_name).where(t.human.c.id == anna.id))
        display_name = shown.scalar_one()
    assert body["handle"] == "anna" and body["address"] is None
    assert body["invitee"] == {"handle": "anna", "display_name": display_name}
    assert "url" not in body  # answered in the inbox, never by link
    [pending] = requests_of(anna)
    assert pending["personal"] is True and pending["class"] == "consent"
    assert "reviewer" in pending["title"] and "guest" in pending["title"]
    row = row_of(migrated, body["id"])
    assert (row.invitee_id, row.request_id) == (anna.id, pending["id"])
    created = kinds(migrated)[-1]
    assert created.kind == "invitation_created"
    assert created.payload["handle_bound"] is True and created.payload["address_bound"] is False
    assert "anna" not in str(created.payload)
    # nobody but the person answers it
    stranger = flow.human(make_client, migrated, "stranger")
    assert answer(stranger, pending["id"], "go").status_code == 404
    # a replay of the same issue answers the same item
    listed = owner.get(PATH).json()["items"][0]
    assert listed["handle"] == "anna" and listed["declined_at"] is None


def test_go_makes_the_person_a_member_with_the_invited_trust_and_role(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    made = invite(owner, "anna", trust="guest", role="reviewer").json()
    [pending] = requests_of(anna)
    answered = answer(anna, pending["id"], "go")
    assert answered.status_code == 200, answered.text
    with migrated.connect() as conn:
        seat = conn.execute(
            select(t.membership.c.trust, t.membership.c.role).where(
                t.membership.c.human_id == anna.id
            )
        ).one()
    assert tuple(seat) == ("guest", "reviewer")
    row = row_of(migrated, made["id"])
    assert row.used_by == anna.id and row.used_at is not None
    assert [e.kind for e in kinds(migrated)][-1] == "invitation_used"
    assert answer(anna, pending["id"], "go").status_code == 409  # answered already


@pytest.mark.parametrize("way", ["no", "withdraw"])
def test_no_and_the_persons_own_withdrawal_decline_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, way: str
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    made = invite(owner, "anna").json()
    [pending] = requests_of(anna)
    if way == "no":
        done = answer(anna, pending["id"], "no")
    else:
        done = anna.post(f"/requests/{pending['id']}/withdraw", {})
    assert done.status_code == 200, done.text
    row = row_of(migrated, made["id"])
    assert row.declined_at is not None and row.used_at is None
    assert not is_member(migrated, anna.id)
    declined = kinds(migrated)[-1]
    assert declined.kind == "invitation_declined"
    assert f"member:{owner.id}" in declined.audience
    assert declined.payload["handle_bound"] is True
    assert owner.get(PATH).json()["items"][0]["declined_at"] is not None
    # declined is an end: the person may be invited again
    assert invite(owner, "anna").status_code == 201


def test_every_handle_but_an_active_persons_is_refused_and_nothing_is_stored(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    for handle in ("pending-one", "suspended-one", "deleted-one", "member-one", "invited-one"):
        flow.human(make_client, migrated, handle)
    with migrated.begin() as conn:
        human = t.human.c
        conn.execute(
            update(t.human).where(human.handle == "pending-one").values(account_status="pending")
        )
        conn.execute(
            update(t.human).where(human.handle == "suspended-one").values(suspended_at=clock.now())
        )
        conn.execute(
            update(t.human).where(human.handle == "deleted-one").values(deleted_at=clock.now())
        )
        member_id = conn.execute(select(human.id).where(human.handle == "member-one")).scalar_one()
    factory.membership(migrated, project_id(migrated), "member", human_id=member_id)
    make_org(owner)  # oz-team
    assert invite(owner, "invited-one").status_code == 201
    with migrated.connect() as conn:
        before = conn.execute(select(func.count()).select_from(t.invitation)).scalar_one()
        requests_before = conn.execute(select(func.count()).select_from(t.request)).scalar_one()
    cases = {
        "nobody-here": "unknown",
        "pending-one": "unknown",
        "suspended-one": "unknown",
        "deleted-one": "unknown",
        "oz-team": "not_a_person",
        "member-one": "member",
        "maintainer": "member",
        "invited-one": "invited",
        "Not_A_Handle": "format",
    }
    for handle, expected in cases.items():
        refused = invite(owner, handle)
        assert refused.status_code == 400, (handle, refused.text)
        assert refused.json()["error"]["details"]["fields"] == {"handle": expected}, handle
    both = owner.post(PATH, {"handle": "anna", "address": "anna@example.org"})
    assert both.status_code == 400
    assert both.json()["error"]["details"]["fields"]["handle"] == "with_address"
    with migrated.connect() as conn:
        assert conn.execute(select(func.count()).select_from(t.invitation)).scalar_one() == before
        after = conn.execute(select(func.count()).select_from(t.request)).scalar_one()
    assert after == requests_before


def test_an_agents_handle_is_not_a_person(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = factory.agent(migrated, project_id(migrated), owner.id)
    with migrated.connect() as conn:
        handle = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == agent.agent_id)
        ).scalar_one()
    refused = invite(owner, handle)
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"handle": "not_a_person"}


def test_an_alias_binds_the_account_and_the_list_shows_the_handle_as_it_is_now(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    with migrated.begin() as conn:
        conn.execute(
            insert(t.handle_alias).values(
                human_id=anna.id, scope="human", handle="anna-old", created_at=clock.now()
            )
        )
    made = invite(owner, "anna-old")
    assert made.status_code == 201, made.text
    assert made.json()["handle"] == "anna" and made.json()["invitee"]["handle"] == "anna"
    with migrated.begin() as conn:  # renamed after issue
        conn.execute(update(t.human).where(t.human.c.id == anna.id).values(handle="anna-new"))
    assert owner.get(PATH).json()["items"][0]["handle"] == "anna-new"
    [pending] = requests_of(anna)
    assert answer(anna, pending["id"], "go").status_code == 200  # the rename keeps it


def test_ten_invitations_by_handle_a_day_to_one_person(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.human(make_client, migrated, "anna")
    for _ in range(invitations.INVITATIONS_PER_INVITEE_PER_DAY):
        made = invite(owner, "anna")
        assert made.status_code == 201, made.text
        assert owner.delete(f"{PATH}/{made.json()['id']}").status_code == 200
    limited = invite(owner, "anna")
    assert limited.status_code == 429, limited.text
    assert int(limited.headers["Retry-After"]) > 0


def test_a_revocation_withdraws_the_request(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    made = invite(owner, "anna").json()
    [pending] = requests_of(anna)
    assert owner.delete(f"{PATH}/{made['id']}").status_code == 200
    assert request_status(migrated, pending["id"]) == "withdrawn"
    assert row_of(migrated, made["id"]).declined_at is None  # revoked, not declined
    assert requests_of(anna) == []


def test_an_expired_invitation_by_handle_is_withdrawn_by_the_sweep(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    made = invite(owner, "anna", ttl_seconds=60).json()
    [pending] = requests_of(anna)
    start = clock.now()
    clock.set_source(lambda: start + timedelta(seconds=61))
    invitations.sweep(migrated)
    assert request_status(migrated, pending["id"]) == "withdrawn"
    row = row_of(migrated, made["id"])
    assert invitations.state(row) == "expired" and row.declined_at is None


def test_a_go_after_the_expiry_withdraws_it_as_expired(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    made = invite(owner, "anna").json()
    [pending] = requests_of(anna)
    with migrated.begin() as conn:
        conn.execute(update(t.invitation).values(expires_at=clock.now() - timedelta(seconds=1)))
    stale = answer(anna, pending["id"], "go")
    assert stale.status_code == 409, stale.text
    assert request_status(migrated, pending["id"]) == "withdrawn"
    row = row_of(migrated, made["id"])
    assert invitations.state(row) == "expired" and row.declined_at is None
    assert not is_member(migrated, anna.id)


def test_a_go_after_the_issuer_lost_the_authority_voids_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = member(make_client, migrated, "an-admin", "admin")
    anna = flow.human(make_client, migrated, "anna")
    made = invite(admin, "anna").json()
    [pending] = requests_of(anna)
    with migrated.begin() as conn:  # demoted between issue and answer
        conn.execute(
            update(t.membership).where(t.membership.c.human_id == admin.id).values(trust="member")
        )
    void = answer(anna, pending["id"], "go")
    assert (void.status_code, reason(void)) == (403, "invitation_void")
    row = row_of(migrated, made["id"])
    assert row.voided_at is not None and row.void_reason == "issuer"
    assert request_status(migrated, pending["id"]) == "withdrawn"
    assert not is_member(migrated, anna.id)
    voided = kinds(migrated)[-1]
    assert voided.kind == "invitation_voided" and f"member:{admin.id}" in voided.audience


def test_the_invited_persons_deletion_voids_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    made = invite(owner, "anna").json()
    [pending] = requests_of(anna)
    with events.transaction(migrated) as conn:
        invitations.invitee_deleted(conn, anna.id)
    row = row_of(migrated, made["id"])
    assert row.voided_at is not None and row.void_reason == "invitee"
    assert request_status(migrated, pending["id"]) == "withdrawn"


def test_joining_by_another_invitation_uses_up_the_one_by_handle(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    by_handle = invite(owner, "anna").json()
    [pending] = requests_of(anna)
    link = issue(owner)
    assert accept(anna, token_of(link)).status_code == 201
    row = row_of(migrated, by_handle["id"])
    assert row.used_by == anna.id
    assert request_status(migrated, pending["id"]) == "withdrawn"


def test_an_invitation_by_handle_has_no_page_and_no_accept_by_token(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Its token was never given out; even someone who had it gets the uniform `not_found`."""
    anna = flow.human(make_client, migrated, "anna")
    made = invite(owner, "anna").json()
    token = "x" * 22
    with migrated.begin() as conn:
        from maity_hub.codes import digest

        conn.execute(
            update(t.invitation)
            .where(t.invitation.c.id == made["id"])
            .values(token_hash=digest(token))
        )
    assert anna.client.get(f"/api/v1/invitations/{token}").status_code == 404
    assert accept(anna, token).status_code == 404


def test_every_invitation_event_is_for_humans_only() -> None:
    """§3.4: invitations never wake an agent, the decline included."""
    assert set(invitations.KINDS) <= events.HUMANS_ONLY_KINDS
