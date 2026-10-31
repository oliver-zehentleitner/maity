"""docs/api.md §6.1 `agent_owners`, `outside_roles`; §6.2 "An agent whose owner is no member":
a private project's agent leaves with its owner, a public one may keep agents of owners from
outside within `outside_roles` (tsk-kkgk4cpksrvx)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
HUB = "hub"
LEFT = "The agent's owner is no longer a member of this project."


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _project(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def _friend(make_client: ClientFactory, engine: Engine, member: bool = True) -> flow.Human:
    friend = flow.human(make_client, engine, "friend")
    if member:
        factory.membership(engine, _project(engine), "member", human_id=friend.id)
    return friend


def _row(engine: Engine, principal: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.membership).where(
                (t.membership.c.agent_id == principal) | (t.membership.c.human_id == principal),
                t.membership.c.active.is_(True),
            )
        ).one()


def _set(owner: flow.Human, **policy: Any) -> Any:
    return owner.patch(PROJECT, {"policy": policy, "reason": "who may bring agents"})


def _remove(owner: flow.Human, engine: Engine, human_id: str) -> Any:
    return owner.delete(f"{PROJECT}/members/{human_id}")


def _isolated(engine: Engine, agent_id: str) -> bool:
    return bool(_row(engine, agent_id).isolated_since is not None)


def _fields(response: Any) -> dict[str, Any]:
    fields: dict[str, Any] = response.json()["error"]["details"]["fields"]
    return fields


# --- the two policy fields ----------------------------------------------------------------------


def test_the_fields_default_and_are_checked(owner: flow.Human, make_client: ClientFactory) -> None:
    shown = owner.get(PROJECT).json()["policy"]
    assert shown["agent_owners"] is None and shown["outside_roles"] == ["coder"]
    assert _fields(_set(owner, agent_owners="everyone")) == {"policy.agent_owners": "unknown"}
    assert _fields(_set(owner, outside_roles=["coder", "reviewer"])) == {
        "outside_roles": "role_not_allowed"
    }
    for forbidden in ("tester", "red-team", "purple-team", "manager", "ops", "proxy"):
        assert _fields(_set(owner, outside_roles=[forbidden])) == {
            "outside_roles": "role_not_allowed"
        }
    assert _fields(_set(owner, outside_roles=["nobody"])) == {"outside_roles": "unknown"}
    done = _set(owner, agent_owners="anyone", outside_roles=["coder", "designer", "coder"])
    assert done.status_code == 200, done.text
    shown = done.json()["policy"]
    assert shown["agent_owners"] == "anyone" and shown["outside_roles"] == ["coder", "designer"]
    lead = flow.agent(make_client, owner, role="admin")
    refused = lead.patch(PROJECT, {"policy": {"agent_owners": "members"}, "reason": "no"})
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "humans_only"


def _roles(owner: flow.Human, custom: list[dict[str, str]]) -> None:
    done = owner.client.put(
        f"/api/v1{PROJECT}/roles", json={"custom": custom}, headers={"X-CSRF-Token": owner.csrf}
    )
    assert done.status_code == 200, done.text


def test_a_project_role_on_a_working_base_may_be_named(owner: flow.Human) -> None:
    _roles(owner, [{"name": "doc-writer", "base": "writer"}, {"name": "qa", "base": "tester"}])
    assert _set(owner, outside_roles=["doc-writer"]).status_code == 200
    assert _fields(_set(owner, outside_roles=["qa"])) == {"outside_roles": "role_not_allowed"}


# --- members: an agent leaves with its owner ----------------------------------------------------


def test_the_agent_is_isolated_by_the_hub_when_its_owner_leaves(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated)
    mine = factory.agent(migrated, _project(migrated), friend.id).agent_id
    other = factory.agent(migrated, _project(migrated), owner.id).agent_id
    assert _set(owner, agent_owners="members").status_code == 200
    assert not _isolated(migrated, mine)  # its owner is a member
    assert _remove(owner, migrated, friend.id).status_code == 200
    row = _row(migrated, mine)
    assert row.isolated_by == HUB and row.isolated_reason == LEFT and row.isolated_since
    assert not _isolated(migrated, other)  # an owner who stays
    shown = owner.get(f"{PROJECT}/members/{mine}").json()
    assert shown["isolated"]["by"] == HUB and shown["isolated"]["reason"] == LEFT
    with migrated.connect() as conn:
        notice = conn.execute(
            select(t.request).where(
                t.request.c.filed_by == "hub", t.request.c.to_human == friend.id
            )
        ).all()
    assert any("isolated" in n.title for n in notice)


def test_an_isolation_in_place_is_never_overwritten(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated)
    mine = factory.agent(migrated, _project(migrated), friend.id).agent_id
    _set(owner, agent_owners="members")
    first = owner.post(f"{PROJECT}/members/{mine}/isolate", {"reason": "it did a thing"})
    assert first.status_code == 200
    since = _row(migrated, mine).isolated_since
    _remove(owner, migrated, friend.id)
    kept = _row(migrated, mine)
    assert (kept.isolated_reason, kept.isolated_by, kept.isolated_since) == (
        "it did a thing",
        owner.id,
        since,
    )


def test_no_lift_while_the_owner_is_no_member_and_the_setting_reads_members(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated)
    mine = factory.agent(migrated, _project(migrated), friend.id).agent_id
    _set(owner, agent_owners="members")
    _remove(owner, migrated, friend.id)
    path = f"{PROJECT}/members/{mine}/isolate"
    refused = owner.delete(path)
    assert refused.status_code == 400 and _fields(refused) == {"member": "owner_not_member"}
    assert _isolated(migrated, mine)
    # neither the owner's return nor a change to `anyone` lifts it by itself, but either allows it
    factory.membership(migrated, _project(migrated), "member", human_id=friend.id)
    assert _isolated(migrated, mine)
    assert owner.delete(path).status_code == 200
    assert not _isolated(migrated, mine)


def test_the_setting_coming_to_read_members_isolates_the_agents_of_outsiders(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated, member=False)
    lent = factory.agent(migrated, _project(migrated), friend.id).agent_id
    _set(owner, agent_owners="anyone")
    assert not _isolated(migrated, lent)
    _set(owner, agent_owners="members")
    assert _isolated(migrated, lent) and _row(migrated, lent).isolated_by == HUB


def test_an_unset_setting_follows_the_public_page(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated, member=False)
    lent = factory.agent(migrated, _project(migrated), friend.id).agent_id
    on = owner.patch(PROJECT, {"public_page": "on"})
    assert on.status_code == 200, on.text
    assert not _isolated(migrated, lent)  # `anyone` while the project has a page
    off = owner.patch(PROJECT, {"public_page": "off"})
    assert off.status_code == 200, off.text
    assert _isolated(migrated, lent)  # unset while the page turns off reads `members`


def test_a_set_value_keeps_whatever_the_public_page_does(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated, member=False)
    lent = factory.agent(migrated, _project(migrated), friend.id).agent_id
    _set(owner, agent_owners="anyone")
    owner.patch(PROJECT, {"public_page": "on"})
    owner.patch(PROJECT, {"public_page": "off"})
    assert not _isolated(migrated, lent)


# --- anyone: outsiders do the work, within outside_roles ----------------------------------------


def test_outsiders_within_the_limits_keep_working_the_others_are_isolated(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated)
    worker = factory.agent(migrated, _project(migrated), friend.id, "member").agent_id
    lead = factory.agent(migrated, _project(migrated), friend.id, "admin").agent_id
    guest = factory.agent(migrated, _project(migrated), friend.id, "coder", trust="guest").agent_id
    _set(owner, agent_owners="anyone")
    assert _remove(owner, migrated, friend.id).status_code == 200
    assert not _isolated(migrated, worker)  # trust member, role coder
    assert not _isolated(migrated, guest)  # trust guest, role coder
    assert _isolated(migrated, lead)  # trust admin
    assert _row(migrated, lead).isolated_by == HUB


def test_the_roles_not_on_the_list_isolate_when_the_owner_leaves(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated)
    designer = factory.agent(migrated, _project(migrated), friend.id, "designer").agent_id
    _set(owner, agent_owners="anyone")  # the default list is `coder` alone
    _remove(owner, migrated, friend.id)
    assert _isolated(migrated, designer)


def test_the_lift_of_an_agent_beyond_the_limits_waits_until_it_is_within_them(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated)
    lead = factory.agent(migrated, _project(migrated), friend.id, "admin").agent_id
    _set(owner, agent_owners="anyone")
    _remove(owner, migrated, friend.id)
    path = f"{PROJECT}/members/{lead}/isolate"
    refused = owner.delete(path)
    assert refused.status_code == 400 and _fields(refused) == {"member": "outside_owner"}
    # an admin may change the isolated member's trust and role: another owner's agent, so the
    # change waits for its owner's go
    asked = owner.patch(f"{PROJECT}/members/{lead}", {"trust": "member"})
    assert asked.status_code in (200, 202), asked.text
    with migrated.begin() as conn:  # as the owner's go would leave it
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == lead)
            .values(trust="member", role="coder", role_base="coder")
        )
    assert owner.delete(path).status_code == 200


def test_a_change_that_would_break_the_limits_is_invalid(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated)
    worker = factory.agent(migrated, _project(migrated), friend.id, "member").agent_id
    _set(owner, agent_owners="anyone")
    _remove(owner, migrated, friend.id)
    member_id = worker
    reviewer = owner.patch(f"{PROJECT}/members/{member_id}", {"role": "reviewer"})
    assert reviewer.status_code == 400 and _fields(reviewer) == {"role": "outside_owner"}
    admin = owner.patch(f"{PROJECT}/members/{member_id}", {"trust": "admin"})
    assert admin.status_code == 400 and _fields(admin) == {"trust": "outside_owner"}
    narrowed = _set(owner, outside_roles=["designer"])  # the worker is a coder
    assert narrowed.status_code == 400 and _fields(narrowed) == {"outside_roles": "outside_owner"}
    widened = _set(owner, outside_roles=["coder", "designer"])
    assert widened.status_code == 200
    assert (_row(migrated, worker).trust, _row(migrated, worker).role) == ("member", "coder")


def test_a_member_whose_owner_is_a_member_is_not_held_to_the_limits(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated)
    lead = factory.agent(migrated, _project(migrated), friend.id, "admin").agent_id
    _set(owner, agent_owners="anyone")
    assert not _isolated(migrated, lead)
    assert _set(owner, outside_roles=["designer"]).status_code == 200


# --- under both: what the leaving person created ------------------------------------------------


@pytest.mark.parametrize("setting", ["members", "anyone"])
def test_the_joins_a_leaving_human_created_are_revoked(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, setting: str
) -> None:
    friend = _friend(make_client, migrated)
    _set(owner, agent_owners=setting)
    made = flow.join(friend, "maity")
    mine = flow.join(owner, "maity")
    assert _remove(owner, migrated, friend.id).status_code == 200
    with migrated.connect() as conn:
        revoked = {r.id: r.revoked_at for r in conn.execute(select(t.join_link))}
    assert revoked[made["id"]] is not None  # the person who issued it is gone
    assert revoked[mine["id"]] is None  # another's stays


# --- the limits hold on every path ----------------------------------------------------------------


def _pending(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.request)
                .where(t.request.c.proposal.is_not(None), t.request.c.status == "open")
                .order_by(t.request.c.created_at, t.request.c.id)
            )
        )


def test_an_isolated_outsider_is_set_within_the_limits_never_beyond_them(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated)
    lead = factory.agent(migrated, _project(migrated), friend.id, "admin").agent_id
    _set(owner, agent_owners="anyone")
    _remove(owner, migrated, friend.id)
    assert _isolated(migrated, lead)
    path = f"{PROJECT}/members/{lead}"
    for body, field in (
        ({"trust": "admin"}, "trust"),
        ({"role": "reviewer"}, "role"),
        ({"role": "ops"}, "role"),
    ):
        refused = owner.patch(path, body)
        assert refused.status_code == 400 and _fields(refused) == {field: "outside_owner"}
    # one field after the other is a way within the limits: the owner's go follows
    assert owner.patch(path, {"trust": "member"}).status_code == 202


def test_the_go_checks_the_limits_as_they_are_then(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated)
    worker = factory.agent(migrated, _project(migrated), friend.id, "member").agent_id
    _set(owner, agent_owners="anyone", outside_roles=["coder", "designer"])
    asked = owner.patch(f"{PROJECT}/members/{worker}", {"role": "designer"})
    assert asked.status_code == 202, asked.text  # its owner is a member: the change waits
    [waiting] = _pending(migrated)
    _remove(owner, migrated, friend.id)  # the worker stays: a coder, within the limits
    assert not _isolated(migrated, worker)
    answered = friend.post(f"/requests/{waiting.id}/answer", {"reply_id": "go"})
    assert answered.status_code == 200, answered.text
    assert _row(migrated, worker).role == "designer"
    narrowed = _set(owner, outside_roles=["coder"])
    assert narrowed.status_code == 400 and _fields(narrowed) == {"outside_roles": "outside_owner"}


def test_the_go_after_the_list_narrowed_is_refused(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated)
    worker = factory.agent(migrated, _project(migrated), friend.id, "member").agent_id
    _set(owner, agent_owners="anyone", outside_roles=["coder", "designer"])
    asked = owner.patch(f"{PROJECT}/members/{worker}", {"role": "designer"})
    assert asked.status_code == 202, asked.text
    [waiting] = _pending(migrated)
    assert _set(owner, outside_roles=["coder"]).status_code == 200  # no outsider holds designer
    _remove(owner, migrated, friend.id)
    answered = friend.post(f"/requests/{waiting.id}/answer", {"reply_id": "go"})
    assert answered.status_code == 400 and _fields(answered) == {"role": "outside_owner"}
    assert _row(migrated, worker).role == "coder"


def test_a_project_role_in_outside_roles_keeps_a_working_base(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _roles(owner, [{"name": "doc-writer", "base": "writer"}])
    assert _set(owner, outside_roles=["doc-writer"]).status_code == 200
    rebased = owner.client.put(
        f"/api/v1{PROJECT}/roles",
        json={"custom": [{"name": "doc-writer", "base": "reviewer"}]},
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert rebased.status_code == 400
    assert _fields(rebased) == {"custom[0].base": "outside_roles"}
    removed = owner.client.put(
        f"/api/v1{PROJECT}/roles", json={"custom": []}, headers={"X-CSRF-Token": owner.csrf}
    )
    assert removed.status_code == 409
    assert removed.json()["error"]["details"]["uses"] == ["outside_roles"]
    other = owner.client.put(
        f"/api/v1{PROJECT}/roles",
        json={"custom": [{"name": "doc-writer", "base": "designer"}]},
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert other.status_code == 200, other.text  # another base that works


def test_a_narrower_list_in_the_call_that_switches_to_members_is_not_refused(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _friend(make_client, migrated)
    worker = factory.agent(migrated, _project(migrated), friend.id, "member").agent_id
    _set(owner, agent_owners="anyone", outside_roles=["coder", "designer"])
    _remove(owner, migrated, friend.id)
    owner.patch(f"{PROJECT}/members/{worker}", {"role": "designer"})  # waits for its owner
    with migrated.begin() as conn:  # as the owner's go would leave it
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == worker)
            .values(role="designer", role_base="designer")
        )
    assert _set(owner, outside_roles=["coder"]).status_code == 400
    both = _set(owner, agent_owners="members", outside_roles=["coder"])
    assert both.status_code == 200, both.text
    assert _isolated(migrated, worker)
