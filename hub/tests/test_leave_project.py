"""A human leaves a project (§6.2), and a substitute whose membership ended takes no new card."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, cover
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_cover import events, limit, policy
from tests.test_orgs import team
from tests.test_tasks import task

PROJECT = "/projects/maintainer/maity"
LEFT = "The agent's owner is no longer a member of this project."


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


@pytest.fixture
def now() -> list[datetime]:
    moment = [datetime.now(UTC).replace(microsecond=0)]
    clock.set_source(lambda: moment[0])
    return moment


def _project(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def _person(
    make_client: ClientFactory, engine: Engine, handle: str, role: str = "member"
) -> flow.Human:
    who = flow.human(make_client, engine, handle)
    factory.membership(engine, _project(engine), role, human_id=who.id)
    return who


def _delete(who: flow.Human, member_id: str, key: str | None = None) -> Any:
    """The dashboard cookie session: no Authorization header, the session cookie and CSRF."""
    headers = {"X-CSRF-Token": who.csrf}
    if key is not None:
        headers["Idempotency-Key"] = key
    return who.client.delete(f"/api/v1{PROJECT}/members/{member_id}", headers=headers)


def _membership(engine: Engine, principal: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.membership).where(
                (t.membership.c.agent_id == principal) | (t.membership.c.human_id == principal)
            )
        ).one()


def _removed(engine: Engine, principal: str) -> Any:
    """The `member_updated` whose payload is that member with `removed_at` set."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.event).where(t.event.c.kind == "member_updated").order_by(t.event.c.seq)
        ).all()
    found = [
        row
        for row in rows
        if (row.payload or {}).get("id") == principal and row.payload.get("removed_at")
    ]
    assert len(found) == 1
    return found[0]


def _seen(engine: Engine, human_id: str) -> None:
    """A human substitute is `available` only once the membership has been seen (§6.12)."""
    with engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.human_id == human_id)
            .values(last_seen_at=clock.now())
        )


def _code(response: Any) -> str:
    code: str = response.json()["error"]["code"]
    return code


# --- who may leave ---------------------------------------------------------------------------


def test_a_guest_leaves(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> None:
    guest = _person(make_client, migrated, "visitor", "guest")
    left = _delete(guest, guest.id)
    assert left.status_code == 200, left.text
    assert left.json()["removed_at"]
    assert _removed(migrated, guest.id).actor_via == "cookie"
    assert guest.get(f"{PROJECT}/members/{guest.id}").status_code == 404


def test_a_member_leaves(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> None:
    member = _person(make_client, migrated, "coder", "member")
    left = _delete(member, member.id)
    assert left.status_code == 200, left.text
    assert left.json()["id"] == member.id and left.json()["removed_at"]
    assert owner.get(f"{PROJECT}/members").json()["items"][0]["id"] == owner.id


def test_an_admin_leaves(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> None:
    admin = _person(make_client, migrated, "deputy", "admin")
    left = _delete(admin, admin.id)
    assert left.status_code == 200, left.text
    event = _removed(migrated, admin.id)
    assert event.audience == [
        "all",
        f"member:{owner.id}",
        f"member:{admin.id}",
        "trust:admin",
    ]
    assert event.actor_membership == _membership(migrated, admin.id).id


def test_an_owner_leaves_while_another_owner_remains(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """`owner_only` is removing another owner. This owner is not the namespace owner."""
    partner = _person(make_client, migrated, "partner", "owner")
    left = _delete(partner, partner.id)
    assert left.status_code == 200, left.text
    assert "owner_only" not in left.text
    event = _removed(migrated, partner.id)
    assert event.audience == [
        "all",
        f"member:{owner.id}",
        f"member:{partner.id}",
        "trust:admin",
    ]
    assert event.payload.get("leaving") is None and event.payload.get("left") is None


def test_the_last_owner_cannot_leave(owner: flow.Human) -> None:
    refused = _delete(owner, owner.id)
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"member": "last_owner"}


def test_the_namespace_owner_cannot_leave(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _person(make_client, migrated, "partner", "owner")  # so it is not `last_owner`
    refused = _delete(owner, owner.id)
    assert (refused.status_code, _code(refused)) == (409, "namespace_owner")
    assert refused.json()["error"]["details"]["projects"] == ["maintainer/maity"]


def test_an_organisation_owner_cannot_leave_its_project(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    _, people = team(make_client, migrated, owner)
    made = owner.post(
        "/projects", {"slug": "shop", "name": "Shop", "owner": "oz-team", "public_page": "off"}
    )
    assert made.status_code in (200, 201), made.text
    second = people["owner2"]
    refused = second.client.delete(
        f"/api/v1/projects/oz-team/shop/members/{second.id}",
        headers={"X-CSRF-Token": second.csrf},
    )
    assert (refused.status_code, _code(refused)) == (409, "namespace_owner")
    assert refused.json()["error"]["details"]["projects"] == ["oz-team/shop"]


def test_an_agent_naming_its_own_id_does_not_leave(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    """Unchanged: a member agent needs `members:admin`; an admin agent does not remove itself."""
    member = flow.agent(make_client, owner, role="member")
    refused = member.client.delete(f"/api/v1{PROJECT}/members/{member.id}", headers=member.auth)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"scope": "members:admin"}
    admin = flow.agent(make_client, owner, role="admin")
    itself = admin.client.delete(f"/api/v1{PROJECT}/members/{admin.id}", headers=admin.auth)
    assert itself.status_code == 403, itself.text
    assert itself.json()["error"]["details"]["scope"] == "members:admin"


def test_leaving_is_addressed_to_human_owners_and_admins_a_removal_is_not(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = _person(make_client, migrated, "deputy", "admin")
    plain = _person(make_client, migrated, "coder", "member")
    guest = _person(make_client, migrated, "visitor", "guest")
    assert _delete(guest, guest.id).status_code == 200
    leave = _removed(migrated, guest.id)
    assert leave.audience == [
        "all",
        f"member:{owner.id}",
        f"member:{admin.id}",
        f"member:{guest.id}",
        "trust:admin",
    ]
    assert f"member:{plain.id}" not in leave.audience
    assert leave.actor_membership == _membership(migrated, guest.id).id
    removed = owner.delete(f"{PROJECT}/members/{plain.id}")
    assert removed.status_code == 200, removed.text
    removal = _removed(migrated, plain.id)
    assert removal.audience == ["all", f"member:{plain.id}", "trust:admin"]
    assert removal.actor_membership == _membership(migrated, owner.id).id


def test_a_repeat_without_the_key_is_not_found_and_the_same_key_replays(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The human's calls here are the dashboard cookie session, the only human credential
    the hub authenticates and the one these tests use."""
    member = _person(make_client, migrated, "coder", "member")
    assert member.client.cookies.get("maity_session")
    key = "leave-replay-0001"
    path = f"{PROJECT}/members/{member.id}"
    first = _delete(member, member.id, key)
    assert first.status_code == 200, first.text
    assert "Idempotent-Replayed" not in first.headers
    again = _delete(member, member.id, key)
    assert again.status_code == 200, again.text
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["id"] == member.id
    assert again.json()["removed_at"] == first.json()["removed_at"]
    plain = member.client.delete(f"/api/v1{path}", headers={"X-CSRF-Token": member.csrf})
    assert plain.status_code == 404, plain.text
    assert _code(plain) == "not_found"


def test_leaving_releases_claims_and_returns_a_held_request(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    member = _person(make_client, migrated, "coder", "member")
    row = _membership(migrated, member.id)
    card = factory.card(
        migrated,
        _project(migrated),
        row.id,
        status="in_progress",
        claim_holder=row.id,
        lease_until=clock.now(),
    )
    asked = flow.agent(make_client, owner).post(
        f"{PROJECT}/requests", {"class": "decision", "title": "A decision", "to": owner.id}
    )
    assert asked.status_code == 201, asked.text
    with migrated.begin() as conn:
        conn.execute(
            update(t.request)
            .where(t.request.c.id == asked.json()["id"])
            .values(holder_member=row.id)
        )
    assert _delete(member, member.id).status_code == 200
    with migrated.connect() as conn:
        held = conn.execute(select(t.card).where(t.card.c.id == card)).one()
        request = conn.execute(select(t.request).where(t.request.c.id == asked.json()["id"])).one()
    assert (held.claim_holder, held.status) == (None, "open")
    assert request.holder_member is None and request.holder_pool is True


def test_owned_agents_are_isolated_under_members_and_kept_within_outside_roles(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _person(make_client, migrated, "friend", "member")
    project_id = _project(migrated)
    mine = factory.agent(migrated, project_id, friend.id).agent_id
    assert _delete(friend, friend.id).status_code == 200
    isolated = _membership(migrated, mine)
    assert isolated.isolated_by == "hub" and isolated.isolated_reason == LEFT

    outsider = _person(make_client, migrated, "outsider", "member")
    assert (
        owner.patch(
            PROJECT, {"policy": {"agent_owners": "anyone"}, "reason": "outsiders"}
        ).status_code
        == 200
    )
    worker = factory.agent(migrated, project_id, outsider.id, "member").agent_id
    lead = factory.agent(migrated, project_id, outsider.id, "admin").agent_id
    assert _delete(outsider, outsider.id).status_code == 200
    assert _membership(migrated, worker).isolated_since is None
    assert _membership(migrated, lead).isolated_by == "hub"


# --- a substitute whose membership ended -------------------------------------------------------


def _covered(make_client: ClientFactory, owner: flow.Human) -> tuple[flow.Agent, flow.Agent]:
    covered = flow.agent(make_client, owner, areas=["hub/"])
    nxt = flow.agent(make_client, owner)
    for agent in (covered, nxt):
        agent.resume()
    return covered, nxt


def test_a_removed_substitute_gets_no_new_covered_card(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    covered, nxt = _covered(make_client, owner)
    sub = flow.agent(make_client, owner)
    quiet = flow.agent(make_client, owner)  # never resumes: not `available`
    sub.resume()
    policy(
        owner,
        covered.id,
        on_unavailable="substitute",
        substitutes=[sub.id, quiet.id, nxt.id],
        grace_minutes=0,
    )
    limit(covered, now[0] + timedelta(hours=1))
    assert owner.get(f"{PROJECT}/members/{covered.id}").json()["covered_by"]["member_id"] == sub.id
    assert owner.delete(f"{PROJECT}/members/{sub.id}").status_code == 200
    shown = owner.get(f"{PROJECT}/members/{covered.id}").json()
    assert shown["covered_by"]["member_id"] == sub.id  # the cover still names who it started with
    card = task(owner, area="hub/")
    assert card["assigned_to"] == nxt.id
    assert card["cover"] == {"for": covered.id, "by": nxt.id, "since": shown["covered_by"]["since"]}
    assert card["assigned_to"] != quiet.id


def test_a_substitute_who_left_gets_no_new_covered_card(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    covered, nxt = _covered(make_client, owner)
    sub = _person(make_client, migrated, "stand-in", "member")
    _seen(migrated, sub.id)
    policy(
        owner,
        covered.id,
        on_unavailable="substitute",
        substitutes=[sub.id, nxt.id],
        grace_minutes=0,
    )
    limit(covered, now[0] + timedelta(hours=1))
    before = owner.get(f"{PROJECT}/members/{covered.id}").json()["covered_by"]
    assert before["member_id"] == sub.id
    assert _delete(sub, sub.id).status_code == 200
    assert owner.get(f"{PROJECT}/members/{covered.id}").json()["covered_by"]["member_id"] == sub.id
    card = task(owner, area="hub/")
    assert card["assigned_to"] == nxt.id
    assert card["cover"]["by"] == nxt.id and card["cover"]["since"] == before["since"]
    covered.resume()
    assert owner.get(f"{PROJECT}/members/{covered.id}").json()["covered_by"] is None
    ended = events(migrated, "cover_ended")
    assert [row.payload["substitute_id"] for row in ended] == [nxt.id]


def test_with_no_pickable_entry_the_card_goes_to_the_covered_member(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    covered = flow.agent(make_client, owner, areas=["hub/"])
    sub = flow.agent(make_client, owner)
    for agent in (covered, sub):
        agent.resume()
    policy(owner, covered.id, on_unavailable="substitute", substitutes=[sub.id], grace_minutes=0)
    limit(covered, now[0] + timedelta(hours=1))
    assert owner.delete(f"{PROJECT}/members/{sub.id}").status_code == 200
    card = task(owner, area="hub/")
    assert card["assigned_to"] == covered.id and card["cover"] is None
    assert owner.get(f"{PROJECT}/members/{covered.id}").json()["covered_by"]["member_id"] == sub.id


def test_an_entry_that_may_not_take_the_card_is_skipped(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    """An open card may go to a reviewer. A `review` card may not: that reviewer holds
    done authority (`may_take_card`), so the card goes to the next entry."""
    covered, coder = _covered(make_client, owner)
    starter = flow.agent(make_client, owner)
    reviewer = flow.agent(make_client, owner, role="reviewer")
    for agent in (starter, reviewer):
        agent.resume()
    policy(
        owner,
        covered.id,
        on_unavailable="substitute",
        substitutes=[starter.id, reviewer.id, coder.id],
        grace_minutes=0,
    )
    limit(covered, now[0] + timedelta(hours=1))
    assert owner.delete(f"{PROJECT}/members/{starter.id}").status_code == 200
    opened = task(owner, area="hub/")
    assert opened["assigned_to"] == reviewer.id and opened["cover"]["by"] == reviewer.id
    with migrated.begin() as conn:
        covered_id = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == covered.id)
        ).scalar_one()
        assignee, routed = cover.routed(
            conn, int(covered_id), SimpleNamespace(id="tsk-review-skip", status="review")
        )
    assert assignee == _membership(migrated, coder.id).id
    assert routed is not None and routed["by"] == coder.id
