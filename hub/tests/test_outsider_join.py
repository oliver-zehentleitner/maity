"""docs/api.md §3.1 "An outsider's agent", §6.1 "The outsiders' opt-in", §2.3 "Outside", §6.5
"Until the claim request is built": a signed-in outsider of a public project whose admins
opted in adds an agent of their own at trust `outside`; the join is behind one switch
(`outsiders.JOINS_ON`) and one predicate (`outsiders.joins_open`), and such an agent takes no
card itself (tsk-enfbkj0xqq5m)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import agent_owners, clock, events, outsiders, probe, public_pages, scopes
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

P = "/projects/maintainer/maity"
JOINS = f"{P}/joins"
NOT_FOUND = {"error": {"code": "not_found", "message": "no such resource", "details": {}}}


@pytest.fixture
def make_client(make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch) -> ClientFactory:
    """Every hub here serves public pages (§16.9), without its probe or public-pages worker
    (hub/context/testing.md, "Background workers in test clients")."""
    monkeypatch.setattr(probe.Worker, "start", lambda self: None)
    monkeypatch.setattr(public_pages.Worker, "start", lambda self: None)
    return lambda **kw: make_client(**{"public_pages": True, **kw})


@pytest.fixture
def on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The switch on, as the one-line change after the own-approvals gate will set it."""
    monkeypatch.setattr(outsiders, "JOINS_ON", True)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity", public_page="on")
    return human


@pytest.fixture
def outsider(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated, "stranger")


def _project(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.project).where(t.project.c.slug == "maity")).one()


def _policy(owner: flow.Human, **policy: Any) -> None:
    done = owner.patch(P, {"policy": policy, "reason": "open contribution"})
    assert done.status_code == 200, done.text


def _opt_in(owner: flow.Human) -> None:
    _policy(owner, agent_owners="anyone")


def _join(who: flow.Human, **body: Any) -> Any:
    body.setdefault("agent", {"handle": f"own-{who.handle}-{_n()}", "display_name": "Mine"})
    return who.post(JOINS, body)


_COUNT = [0]


def _n() -> int:
    _COUNT[0] += 1
    return _COUNT[0]


def _exchange(make_client: ClientFactory, created: dict[str, Any]) -> flow.Agent:
    client = make_client()
    answer = flow.exchange(client, created)
    assert answer.status_code == 201, answer.text
    return flow.Agent(
        client,
        answer.text,
        answer.headers["Maity-Credential-Id"],
        answer.headers["Maity-Member-Id"],
        answer.headers["Maity-Instance"],
    )


def _outside_agent(
    make_client: ClientFactory, owner: flow.Human, outsider: flow.Human
) -> flow.Agent:
    _opt_in(owner)
    created = _join(outsider)
    assert created.status_code == 201, created.text
    return _exchange(make_client, created.json())


def _row(engine: Engine, agent_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.membership).where(
                t.membership.c.agent_id == agent_id, t.membership.c.active.is_(True)
            )
        ).one()


def _reason(answer: Any) -> Any:
    return answer.json()["error"]["details"].get("reason")


def _card(owner: flow.Human, title: str = "A card") -> str:
    made = owner.post(f"{P}/tasks", {"title": title})
    assert made.status_code == 201, made.text
    card_id: str = made.json()["id"]
    return card_id


# --- the switch and the predicate ---------------------------------------------------------------


def test_the_switch_off_keeps_every_joins_route_not_found_to_an_outsider(
    owner: flow.Human, outsider: flow.Human
) -> None:
    """Off (the shipped value) the opt-in and the public page change nothing: the three joins
    routes answer an outsider exactly as an unknown project, a bad body included (§1.3)."""
    assert outsiders.JOINS_ON is False
    _opt_in(owner)
    for answer in (
        _join(outsider),
        outsider.post(JOINS, {"agent": 5}),
        outsider.get(JOINS),
        outsider.delete(f"{JOINS}/jn-none"),
    ):
        assert (answer.status_code, answer.json()) == (404, NOT_FOUND), answer.text


def test_the_switch_on_opens_the_join_to_an_outsider_where_the_admins_opted_in(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The counter-check of the switch: with it on, the same call makes a join with trust
    `outside`, and its exchange a membership with trust `outside`, role `coder`, no boss, no
    areas and no capabilities (§3.1)."""
    _opt_in(owner)
    created = _join(outsider)
    assert created.status_code == 201, created.text
    agent = _exchange(make_client, created.json())
    row = _row(migrated, agent.id)
    assert (row.trust, row.role, row.reports_to) == ("outside", "coder", None)
    assert (row.areas, row.capabilities) == ([], [])
    assert outsider.get(P).status_code == 200  # still an outsider: a reader, no member


@pytest.mark.parametrize("setting", [None, "members"])
def test_without_the_stored_anyone_no_outsider_joins(
    on: None, owner: flow.Human, outsider: flow.Human, migrated: Engine, setting: str | None
) -> None:
    """Unset (which reads `anyone` while the page is served) and `members` open no join: only
    the admins' stored `anyone` does (§6.1, "The outsiders' opt-in", req-gp8jzgr6zdvj)."""
    if setting is not None:
        _policy(owner, agent_owners=setting)
    with migrated.connect() as conn:
        assert agent_owners.effective(conn, _project(migrated)) == (setting or "anyone")
    answer = _join(outsider, agent={"handle": "nope", "display_name": "Nope"})
    assert (answer.status_code, answer.json()) == (404, NOT_FOUND), answer.text
    _opt_in(owner)  # the counter-check: the opt-in alone opens it
    assert _join(outsider).status_code == 201


def test_without_the_opt_in_a_bad_body_is_not_found_before_validation(
    on: None, owner: flow.Human, outsider: flow.Human
) -> None:
    """The gate answers before the body is read (§1.3): no validation answer tells an outsider
    what the route takes where it is closed to them. Opted in, the same body is the route's
    `invalid`."""
    bad = {"agent": 5, "ttl_seconds": "never"}
    closed = outsider.post(JOINS, bad)
    assert (closed.status_code, closed.json()) == (404, NOT_FOUND), closed.text
    _opt_in(owner)
    opened = outsider.post(JOINS, bad)
    assert (opened.status_code, opened.json()["error"]["code"]) == (400, "invalid"), opened.text


def test_a_private_project_takes_no_outsiders_agent_whatever_its_setting(
    on: None, owner: flow.Human, outsider: flow.Human
) -> None:
    _opt_in(owner)
    off = owner.patch(P, {"public_page": "off"})
    assert off.status_code == 200, off.text
    answer = _join(outsider)
    assert (answer.status_code, answer.json()) == (404, NOT_FOUND), answer.text


def test_joins_open_is_the_one_answer(on: None, owner: flow.Human, migrated: Engine) -> None:
    """The predicate itself: on, stored `anyone`, public; each one missing answers False."""
    with migrated.connect() as conn:
        assert outsiders.joins_open(conn, _project(migrated)) is False  # unset
    _opt_in(owner)
    with migrated.connect() as conn:
        assert outsiders.joins_open(conn, _project(migrated)) is True
    outsiders.JOINS_ON = False  # restored by the fixture's monkeypatch
    with migrated.connect() as conn:
        assert outsiders.joins_open(conn, _project(migrated)) is False


# --- what the project allows (§6.1, `…/contribution`) ------------------------------------------

CONTRIBUTION = f"{P}/contribution"


def test_contribution_tells_an_outsider_whether_they_may_add_an_agent(
    on: None, owner: flow.Human, outsider: flow.Human
) -> None:
    """Without the opt-in `members_only`, with `agent_owners` as stored (`null`); with it
    `can_join`; at the quota `limit`."""
    closed = outsider.get(CONTRIBUTION)
    assert closed.status_code == 200, closed.text
    assert closed.json() == {
        "agent_owners": None,
        "outside_roles": ["coder"],
        "open_cards": 0,
        "agents_max": 3,
        "can_join": False,
        "reason": "members_only",
    }
    _policy(owner, agent_owners="anyone", member_agents_max=1)
    opened = outsider.get(CONTRIBUTION).json()
    assert (opened["agent_owners"], opened["can_join"], opened["reason"]) == ("anyone", True, None)
    assert opened["agents_max"] == 1
    assert _join(outsider).status_code == 201
    full = outsider.get(CONTRIBUTION).json()
    assert (full["can_join"], full["reason"]) == (False, "limit")


def test_contribution_says_members_only_while_the_switch_is_off(
    owner: flow.Human, outsider: flow.Human
) -> None:
    _opt_in(owner)
    found = outsider.get(CONTRIBUTION)
    assert found.status_code == 200, found.text
    assert (found.json()["can_join"], found.json()["reason"]) == (False, "members_only")


def test_contribution_tells_a_member_to_bring_agents_as_a_member(
    on: None, owner: flow.Human
) -> None:
    _opt_in(owner)
    found = owner.get(CONTRIBUTION)
    assert found.status_code == 200, found.text
    assert (found.json()["can_join"], found.json()["reason"]) == (False, "member")


def test_contribution_to_an_agent_member_and_to_an_agent_of_another_project(
    on: None, owner: flow.Human, make_client: ClientFactory
) -> None:
    """An agent member reads it as a member (`member`); an agent of another project gets the
    `not_found` of any non-member read (§6.1)."""
    _opt_in(owner)
    member = flow.agent(make_client, owner)
    found = member.get(CONTRIBUTION)
    assert found.status_code == 200, found.text
    assert (found.json()["can_join"], found.json()["reason"]) == (False, "member")
    flow.project(owner, "other")
    stranger = flow.agent(make_client, owner, slug="other")
    assert stranger.get(CONTRIBUTION).status_code == 404


def test_contribution_of_a_project_that_is_not_public_is_not_found(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    _opt_in(owner)
    assert owner.patch(P, {"public_page": "off"}).status_code == 200
    for answer in (outsider.get(CONTRIBUTION), make_client().get(f"/api/v1{CONTRIBUTION}")):
        assert answer.status_code in (401, 404), answer.text
    hidden = outsider.get(CONTRIBUTION)
    assert (hidden.status_code, hidden.json()) == (404, NOT_FOUND)
    assert owner.get(CONTRIBUTION).status_code == 200  # a member still reads it


# --- the join's limits (§3.1) -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"trust": "member"}, "trust"),
        ({"role": "designer"}, "role"),  # not on `outside_roles` (`["coder"]`)
        ({"areas": ["hub/"]}, "areas"),
        ({"capabilities": ["deploy"]}, "capabilities"),
    ],
)
def test_the_join_stays_within_the_outsiders_limits(
    on: None, owner: flow.Human, outsider: flow.Human, body: dict[str, Any], field: str
) -> None:
    _opt_in(owner)
    answer = _join(outsider, **body)
    assert answer.status_code == 403, answer.text
    assert answer.json()["error"]["details"] == {"reason": "member_join_limit", "field": field}


def test_blue_team_stays_closed_even_on_a_stored_list(
    on: None, owner: flow.Human, outsider: flow.Human, migrated: Engine
) -> None:
    """B.1 of §6.30: the join takes the contract's list as well, so a list that still names
    `blue-team` lets no outsider's agent hold it; `coder` on the same list passes. The list is
    written as a project stored it while `blue-team` was allowed: a PATCH refuses it now."""
    _policy(owner, agent_owners="anyone")
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(outside_roles=["coder", "blue-team"]))
    refused = _join(outsider, role="blue-team")
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["field"] == "role"
    assert _join(outsider, role="coder").status_code == 201


def test_the_boss_is_the_outsider_or_nobody(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """`reports_to` the caller or omitted (§3.1); the caller is no member, so the agent reports
    to nobody here. Anyone else is beyond the limits."""
    _opt_in(owner)
    other = _join(outsider, reports_to=owner.id)
    assert other.status_code == 403 and other.json()["error"]["details"]["field"] == "reports_to"
    created = _join(outsider, reports_to=outsider.id)
    assert created.status_code == 201, created.text
    agent = _exchange(make_client, created.json())
    assert _row(migrated, agent.id).reports_to is None


def test_another_humans_agent_is_refused(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    _opt_in(owner)
    theirs = flow.agent(make_client, owner).id  # a profile the project's owner owns
    answer = _join(outsider, agent={"id": theirs})
    assert answer.status_code == 403, answer.text
    assert answer.json()["error"]["details"] == {"reason": "member_join_limit", "field": "agent"}


def test_the_count_is_member_agents_max(on: None, owner: flow.Human, outsider: flow.Human) -> None:
    _policy(owner, agent_owners="anyone", member_agents_max=1)
    assert _join(outsider).status_code == 201
    second = _join(outsider)
    assert second.status_code == 403, second.text
    details = second.json()["error"]["details"]
    assert details["reason"] == "member_agents_max" and details["max"] == 1


# --- the exchange checks again (§3.1) -----------------------------------------------------------


def _refused_at_exchange(make_client: ClientFactory, created: dict[str, Any]) -> None:
    answer = flow.exchange(make_client(), created)
    assert (answer.status_code, answer.json()) == (404, NOT_FOUND), answer.text


def test_the_exchange_voids_the_join_once_the_opt_in_is_gone(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    _opt_in(owner)
    created = _join(outsider).json()
    _policy(owner, agent_owners="members")
    _refused_at_exchange(make_client, created)


def test_the_exchange_voids_the_join_when_the_switch_is_off(
    on: None,
    owner: flow.Human,
    outsider: flow.Human,
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _opt_in(owner)
    created = _join(outsider).json()
    monkeypatch.setattr(outsiders, "JOINS_ON", False)
    _refused_at_exchange(make_client, created)


def test_the_exchange_voids_the_join_when_the_project_is_private_now(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    _opt_in(owner)
    created = _join(outsider).json()
    assert owner.patch(P, {"public_page": "off"}).status_code == 200
    _refused_at_exchange(make_client, created)


def test_the_exchange_voids_the_join_of_a_creator_who_is_a_member_now(
    on: None,
    owner: flow.Human,
    outsider: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
) -> None:
    _opt_in(owner)
    created = _join(outsider).json()
    factory.membership(migrated, _project(migrated).id, "member", human_id=outsider.id)
    _refused_at_exchange(make_client, created)


def test_the_exchange_voids_the_join_beyond_the_count_now(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    """One agent at work, a second join issued under a higher count, the count lowered again:
    the second is void at its exchange, as a member's join is (§3.1)."""
    _policy(owner, agent_owners="anyone", member_agents_max=1)
    _exchange(make_client, _join(outsider).json())
    _policy(owner, member_agents_max=2)
    second = _join(outsider).json()
    _policy(owner, member_agents_max=1)
    _refused_at_exchange(make_client, second)


def test_the_exchange_voids_a_role_taken_off_the_list(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    _policy(owner, agent_owners="anyone", outside_roles=["coder", "designer"])
    created = _join(outsider, role="designer").json()
    _policy(owner, outside_roles=["coder"])
    _refused_at_exchange(make_client, created)


# --- the outsider's own joins ---------------------------------------------------------------------


def test_an_outsider_lists_and_revokes_only_their_own_joins(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _opt_in(owner)
    mine = _join(outsider).json()
    theirs = flow.join(owner, "maity")
    other = flow.human(make_client, migrated, "other")
    other_join = _join(other).json()
    listed = outsider.get(JOINS)
    assert listed.status_code == 200, listed.text
    assert [j["id"] for j in listed.json()["items"]] == [mine["id"]]
    for foreign in (theirs["id"], other_join["id"]):
        answer = outsider.delete(f"{JOINS}/{foreign}")
        assert (answer.status_code, answer.json()) == (404, NOT_FOUND), answer.text
    revoked = outsider.delete(f"{JOINS}/{mine['id']}")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked_at"] is not None
    _refused_at_exchange(make_client, mine)


# --- trust `outside` comes only from the outsider's join (§2.3 "Outside") -----------------------


def test_trust_outside_is_never_set_or_changed_by_a_patch(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    member = flow.agent(make_client, owner)
    for target, trust in ((agent.id, "member"), (agent.id, "outside"), (member.id, "outside")):
        answer = owner.patch(f"{P}/members/{target}", {"trust": trust})
        assert answer.status_code == 400, (target, trust, answer.text)
        assert answer.json()["error"]["details"]["fields"] == {"trust": "outside"}


def test_no_other_join_and_no_invitation_names_trust_outside(owner: flow.Human) -> None:
    joined = owner.post(JOINS, {"agent": {"handle": "x1", "display_name": "X"}, "trust": "outside"})
    assert joined.status_code == 400, joined.text
    assert joined.json()["error"]["details"]["fields"] == {"trust": "outside"}
    invited = owner.post(f"{P}/invitations", {"trust": "outside", "address": "a@example.org"})
    assert invited.status_code == 400, invited.text
    assert invited.json()["error"]["details"]["fields"]["trust"] == "outside"


def test_the_role_of_an_outsiders_agent_stays_within_the_outside_roles(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    refused = owner.patch(f"{P}/members/{agent.id}", {"role": "manager"})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"role": "outside_owner"}
    _policy(owner, outside_roles=["coder", "designer"])
    # Within the list: another owner's agent, so it waits for that owner's consent (§6.2).
    assert owner.patch(f"{P}/members/{agent.id}", {"role": "designer"}).status_code == 202


# --- what it keeps holds after the join too (§2.3 "Outside", tsk-x028b4hk6r08) ----------------


def _kept(row: Any) -> tuple[Any, ...]:
    return (row.areas, row.capabilities, row.reports_to)


def _beyond(answer: Any, field: str) -> None:
    """The join's own refusal (`_outside_values`): `forbidden`, `member_join_limit`."""
    assert answer.status_code == 403, answer.text
    assert answer.json()["error"]["details"] == {"reason": "member_join_limit", "field": field}


def _open_requests(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(select(t.request.c.id).where(t.request.c.status == "open")))


def test_a_member_change_gives_an_outsiders_agent_no_areas(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    before = _kept(_row(migrated, agent.id))
    _beyond(owner.patch(f"{P}/members/{agent.id}", {"areas": ["web/"]}), "areas")
    assert _kept(_row(migrated, agent.id)) == before
    assert _open_requests(migrated) == []  # refused up front: no consent request waits


def test_a_member_change_gives_an_outsiders_agent_no_capabilities(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    before = _kept(_row(migrated, agent.id))
    _beyond(owner.patch(f"{P}/members/{agent.id}", {"capabilities": ["tag"]}), "capabilities")
    assert _kept(_row(migrated, agent.id)) == before
    assert _open_requests(migrated) == []


def test_a_member_change_has_an_outsiders_agent_report_to_no_other_member(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    third = flow.agent(make_client, owner, role="manager")
    sibling = _outside_agent(make_client, owner, outsider)  # another agent of the same owner
    before = _kept(_row(migrated, agent.id))
    for boss in (third.id, owner.id, sibling.id):
        _beyond(owner.patch(f"{P}/members/{agent.id}", {"reports_to": boss}), "reports_to")
    # Its owner, once a member, names another member for it: the same refusal.
    _member_now(migrated, outsider)
    _beyond(outsider.patch(f"{P}/members/{agent.id}", {"reports_to": third.id}), "reports_to")
    assert _kept(_row(migrated, agent.id)) == before
    assert _open_requests(migrated) == []


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"areas": ["web/"]}, "areas"),
        ({"capabilities": ["tag"]}, "capabilities"),
        ({"reports_to": "third"}, "reports_to"),  # a pair with the boss's owner (§6.2)
        ({"reports_to": "sibling"}, "reports_to"),  # inside its owner: the owner's consent
    ],
)
def test_the_owners_go_on_a_request_filed_before_is_refused_too(
    on: None,
    owner: flow.Human,
    outsider: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, Any],
    field: str,
) -> None:
    """The change is checked again as it is written: a consent request that waits, filed while
    the call did not check it, takes no effect on the owner's `go`, and stays open."""
    agent = _outside_agent(make_client, owner, outsider)
    if body.get("reports_to") == "third":
        body = {"reports_to": flow.agent(make_client, owner).id}
    elif body.get("reports_to") == "sibling":
        body = {"reports_to": _outside_agent(make_client, owner, outsider).id}
    before = _kept(_row(migrated, agent.id))
    with monkeypatch.context() as m:
        m.setattr(agent_owners, "check_outside_fields", lambda *_: None)
        filed = owner.patch(f"{P}/members/{agent.id}", body)
    assert filed.status_code == 202, filed.text
    waiting = [r.id for r in _open_requests(migrated)]
    assert waiting
    for request_id in waiting:
        _beyond(outsider.post(f"/requests/{request_id}/answer", {"reply_id": "go"}), field)
    assert _kept(_row(migrated, agent.id)) == before
    assert [r.id for r in _open_requests(migrated)] == waiting


def test_an_outsiders_agent_keeps_empty_fields_and_its_owner_as_its_boss(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    emptied = owner.patch(f"{P}/members/{agent.id}", {"areas": [], "capabilities": []})
    assert emptied.status_code in (200, 202), emptied.text
    if emptied.status_code == 202:  # another owner's agent: its owner consents (§6.2)
        done = outsider.post(f"/requests/{emptied.json()['id']}/answer", {"reply_id": "go"})
        assert done.status_code == 200, done.text
    row = _row(migrated, agent.id)
    assert (row.areas, row.capabilities) == ([], [])
    # Nobody, from its owner outside the project.
    assert outsider.patch(f"{P}/members/{agent.id}", {"reports_to": None}).status_code == 204
    assert _row(migrated, agent.id).reports_to is None
    # Its owner, once the owner is a member.
    _member_now(migrated, outsider)
    moved = outsider.patch(f"{P}/members/{agent.id}", {"reports_to": outsider.id})
    assert moved.status_code == 200, moved.text
    with migrated.connect() as conn:
        mine = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.human_id == outsider.id, t.membership.c.active.is_(True)
            )
        ).scalar_one()
    assert _row(migrated, agent.id).reports_to == mine


def test_trust_outside_holds_a_members_scopes_for_its_role_and_never_more() -> None:
    admin_only = {"tasks:admin", "members:admin", "project:admin", "requests:answer", "line:lead"}
    for role in ("coder", "reviewer", "manager", "proxy", "ops"):
        # Less than trust `member` by exactly `line:lead` and a proxy's `requests:answer`.
        member = set(scopes.scopes_for("member", role, "agent")) - {"line:lead", "requests:answer"}
        held = set(scopes.scopes_for("outside", role, "agent"))
        assert held == member, role
        assert not held & admin_only, role
    assert "outside" not in scopes.TRUSTS  # no PATCH, invitation or other join sets it


# --- role memory (§19.2) ------------------------------------------------------------------------

MEMORY = f"{P}/memory"


def _role_items(who: flow.Agent) -> list[str]:
    answer = who.get(MEMORY, params={"store": "role"})
    assert answer.status_code == 200, answer.text
    return [item["id"] for item in answer.json()["items"]]


def test_an_outsiders_agent_neither_reads_writes_nor_deletes_its_roles_memory(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    member = flow.agent(make_client, owner)  # a member's coder, the same role
    written = member.post(MEMORY, {"store": "role", "text": "How this project reviews."})
    assert written.status_code == 201, written.text  # a member's coder still writes
    entry = written.json()["id"]
    # It reads no memory of the project (§2.3 "Outside"): the read answers as an outsider's.
    read = agent.get(MEMORY, params={"store": "role"})
    assert read.status_code == 404, read.text
    assert read.json() == NOT_FOUND
    refused = agent.post(MEMORY, {"store": "role", "text": "Another way to review."})
    assert refused.status_code == 403, refused.text
    assert _reason(refused) == "outside_trust"
    refused = agent.delete(f"{MEMORY}/{entry}")
    assert refused.status_code == 403, refused.text
    assert _reason(refused) == "outside_trust"
    assert _role_items(member) == [entry]  # the entry stays, and nothing was added


def test_an_outsiders_agent_keeps_its_own_team_memory(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    written = agent.post(MEMORY, {"store": "team", "text": "What I learned here."})
    assert written.status_code == 201, written.text
    deleted = agent.delete(f"{MEMORY}/{written.json()['id']}")
    assert deleted.status_code == 200, deleted.text


# --- isolation (§6.2) ---------------------------------------------------------------------------


def test_the_agent_stays_while_the_opt_in_holds_and_is_isolated_under_members(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    project_id = _project(migrated).id
    with events.transaction(migrated) as conn:  # the pass emits what it isolates
        agent_owners.reconcile(conn, project_id)
    assert _row(migrated, agent.id).isolated_since is None
    _policy(owner, agent_owners="members")
    assert _row(migrated, agent.id).isolated_since is not None


# --- the interim of §6.5: a human gives it its card ------------------------------------------


def test_an_outsiders_agent_claims_nothing_itself(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    card = _card(owner)
    refused = agent.post(f"{P}/tasks/{card}/claim", {})
    assert refused.status_code == 403, refused.text
    assert _reason(refused) == "not_open_to_outsiders"
    member = flow.agent(make_client, owner)  # the counter-check: a member's agent claims it
    assert member.post(f"{P}/tasks/{card}/claim", {}).status_code == 200


def test_a_human_with_tasks_admin_hands_it_a_card(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    card = _card(owner)
    given = owner.post(f"{P}/tasks/{card}/claim", {"holder": agent.id})
    assert given.status_code == 200, given.text
    assert given.json()["claim"]["holder"] == agent.id


def test_no_agent_hands_it_a_card_an_admin_agent_included(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    admin = flow.agent(make_client, owner, trust="admin", role="coder")
    card = _card(owner)
    refused = admin.post(f"{P}/tasks/{card}/claim", {"holder": agent.id})
    assert refused.status_code == 403, refused.text
    assert _reason(refused) == "humans_only"
    member = flow.agent(make_client, owner)  # the counter-check: a member's agent it may
    assert admin.post(f"{P}/tasks/{card}/claim", {"holder": member.id}).status_code == 200


def test_an_agents_assign_moving_an_expired_claim_to_it_is_refused(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    admin = flow.agent(make_client, owner, trust="admin", role="coder")
    member = flow.agent(make_client, owner)
    card = _card(owner)
    assert member.post(f"{P}/tasks/{card}/claim", {}).status_code == 200
    with migrated.begin() as conn:  # the lease ran out
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card)
            .values(lease_until=clock.now() - timedelta(minutes=1))
        )
    refused = admin.post(f"{P}/tasks/{card}/assign", {"assignee": agent.id})
    assert refused.status_code == 403, refused.text
    # An agent moving a claim to another owner's agent is refused before this rule (§6.19);
    # `refuse_taking` stands behind it.
    assert _reason(refused) in ("cross_owner", "humans_only")
    assert owner.get(f"{P}/tasks/{card}").json()["claim"]["holder"] == member.id
    given = owner.post(f"{P}/tasks/{card}/assign", {"assignee": agent.id})
    assert given.status_code == 200, given.text
    assert given.json()["claim"]["holder"] == agent.id


def test_a_plain_assign_names_it_and_gives_no_claim(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    card = _card(owner)
    named = owner.post(f"{P}/tasks/{card}/assign", {"assignee": agent.id})
    assert named.status_code == 200, named.text
    assert named.json()["claim"] is None
    refused = agent.post(f"{P}/tasks/{card}/claim", {})
    assert _reason(refused) == "not_open_to_outsiders"


def _member_now(engine: Engine, human: flow.Human) -> None:
    factory.membership(engine, _project(engine).id, "member", human_id=human.id)


def _card_row(engine: Engine, card_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.card).where(t.card.c.id == card_id)).one()


def _outsiders_work(engine: Engine, card_id: str) -> bool:
    from maity_hub import merged

    with engine.connect() as conn:
        return merged.outsiders_work(conn, _card_row(engine, card_id), _project(engine))


def test_an_instance_join_rechecks_the_role_against_outside_roles_now(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§3.1: a new instance's join is within the same limits now. A role the admins took off
    `outside_roles` since the first join gets no new instance, at creation and, for a join
    issued before, at the exchange."""
    _policy(owner, agent_owners="anyone", outside_roles=["coder", "designer"])
    agent = _exchange(make_client, _join(outsider, role="designer").json())
    issued = _join(outsider, agent={"id": agent.id}, replaces=agent.instance)
    assert issued.status_code == 201, issued.text
    with migrated.begin() as conn:  # narrowed while the agent is at work (as after an isolation)
        conn.execute(
            update(t.project).where(t.project.c.slug == "maity").values(outside_roles=["coder"])
        )
    refused = _join(outsider, agent={"id": agent.id}, replaces=agent.instance)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"reason": "member_join_limit", "field": "role"}
    _refused_at_exchange(make_client, issued.json())


def test_the_route_reads_an_outsider_only_while_the_join_is_open(
    owner: flow.Human, outsider: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`outsiders.outsider` answers for itself, not only behind the gate: a signed-in human who
    is no member is an outsider of the joins routes only while `joins_open` holds."""
    from types import SimpleNamespace

    from maity_hub.errors import ApiError

    _opt_in(owner)
    caller = SimpleNamespace(kind="human", via="cookie", human_id=outsider.id, bridge=None)
    with migrated.connect() as conn, pytest.raises(ApiError) as closed:
        outsiders.outsider(conn, caller, "maintainer/maity")
    assert closed.value.code == "not_found"
    monkeypatch.setattr(outsiders, "JOINS_ON", True)
    with migrated.connect() as conn:
        found = outsiders.outsider(conn, caller, "maintainer/maity")
    assert found.principal_id == outsider.id


def test_opening_the_join_opens_no_other_route_to_an_outsider(
    on: None, owner: flow.Human, outsider: flow.Human
) -> None:
    """With the join open, only the joins routes pass the gate for an outsider: a write to
    any other project route still answers `not_found` before its body is read."""
    _opt_in(owner)
    assert _join(outsider).status_code == 201  # the joins routes are open
    for method, path, body in (
        ("POST", f"{P}/tasks", {"title": 5}),
        ("PATCH", P, {"name": 7}),
        ("POST", f"{P}/invitations", {"trust": 5}),
    ):
        answer = outsider.client.request(
            method,
            f"/api/v1{path}",
            json=body,
            headers={"X-CSRF-Token": outsider.csrf, "Content-Type": "application/json"},
        )
        assert (answer.status_code, answer.json()) == (404, NOT_FOUND), (method, path, answer.text)


def test_an_outsiders_agent_whose_owner_joined_keeps_to_outside_roles(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """`check_assignment` binds trust `outside` to `outside_roles` whoever its owner is now:
    with the owner a member, a role off the list is still `invalid` (`outside_owner`)."""
    agent = _outside_agent(make_client, owner, outsider)
    _member_now(migrated, outsider)
    refused = owner.patch(f"{P}/members/{agent.id}", {"role": "manager"})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"role": "outside_owner"}


def test_the_exchange_voids_a_join_whose_profile_changed_owner(
    on: None,
    owner: flow.Human,
    outsider: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
) -> None:
    _opt_in(owner)
    created = _join(outsider).json()
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == created["agent_id"])
            .values(owner_id=owner.id)
        )
    _refused_at_exchange(make_client, created)


def test_the_exchange_voids_an_instance_join_once_the_membership_is_not_outside(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    created = _join(outsider, agent={"id": agent.id}, replaces=agent.instance).json()
    _set_row(migrated, agent.id, trust="member")
    _refused_at_exchange(make_client, created)


def test_the_join_asks_the_opt_in_again_under_the_lock(
    on: None, owner: flow.Human, outsider: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The opt-in can close between the first reading and the project's lock: the join reads
    it again under the lock and answers `not_found` then, creating nothing."""
    _opt_in(owner)
    real = outsiders.joins_open
    calls = [0]

    def closes_after_two(conn: Any, project: Any) -> bool:
        calls[0] += 1  # the gate's and the route's readings see it open; the lock's sees it closed
        return calls[0] <= 2 and real(conn, project)

    monkeypatch.setattr(outsiders, "joins_open", closes_after_two)
    answer = _join(outsider)
    assert (answer.status_code, answer.json()) == (404, NOT_FOUND), answer.text
    monkeypatch.setattr(outsiders, "joins_open", real)
    assert outsider.get(JOINS).json()["items"] == []


def test_contribution_lists_only_the_roles_an_outsiders_agent_may_hold(
    on: None, owner: flow.Human, outsider: flow.Human, migrated: Engine
) -> None:
    """A stored `outside_roles` entry on a base the hub does not open is left out of
    `GET …/contribution`'s `outside_roles`."""
    _opt_in(owner)
    with migrated.begin() as conn:
        conn.execute(
            update(t.project)
            .where(t.project.c.slug == "maity")
            .values(outside_roles=["coder", "reviewer"])
        )
    assert outsider.get(CONTRIBUTION).json()["outside_roles"] == ["coder"]


def test_instance_join_for_own_member_trust_agent_is_refused(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§3.1: an instance join onto an agent the outsider owns adds an instance only to a
    membership with trust `outside`. One an admin's or a member's join made (trust `member`,
    here an agent whose owner is now the outsider) is beyond the limits: `member_join_limit`,
    `field: agent`."""
    _opt_in(owner)
    agent = flow.agent(make_client, owner)
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == agent.id)
            .values(owner_id=outsider.id)
        )
    assert _row(migrated, agent.id).trust == "member"
    refused = _join(outsider, agent={"id": agent.id}, replaces=agent.instance)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"reason": "member_join_limit", "field": "agent"}


def test_a_role_on_a_base_the_hub_does_not_open_is_refused_even_on_the_list(
    on: None, owner: flow.Human, outsider: flow.Human, migrated: Engine
) -> None:
    """`agent_owners.outside_role_allowed`: on the list, on a base `policy.OUTSIDE_BASES` opens
    (the hub's own list check), and on a base the contract opens. A stored list naming
    `reviewer`, which the contract opens and the hub does not yet (tsk-jf0m1t0fa6a9), lets no
    outsider's agent take it; `designer`, open on both, passes."""
    _opt_in(owner)
    with migrated.begin() as conn:  # stored as an older list could hold it
        conn.execute(
            update(t.project)
            .where(t.project.c.slug == "maity")
            .values(outside_roles=["coder", "designer", "reviewer"])
        )
    refused = _join(outsider, role="reviewer")
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"reason": "member_join_limit", "field": "role"}
    assert _join(outsider, role="designer").status_code == 201


def test_a_card_the_outsider_does_not_read_answers_as_a_missing_one(
    on: None, owner: flow.Human, outsider: flow.Human, migrated: Engine
) -> None:
    """An outsider's `handover` names a card it reads: one it does not read (a `security`
    card not done) answers exactly as one that does not exist, status, code and body."""
    _opt_in(owner)
    project_id = _project(migrated).id
    with migrated.connect() as conn:
        writer = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.project_id == project_id, t.membership.c.human_id == owner.id
            )
        ).scalar_one()
    hidden = factory.card(migrated, project_id, writer, title="Hidden", label="security")
    shown = _card(owner, "Shown")
    on_hidden = _join(outsider, handover=hidden)
    on_missing = _join(outsider, handover="tsk-000000000000")
    assert on_hidden.status_code == 400, on_hidden.text
    assert (on_hidden.status_code, on_hidden.json()) == (on_missing.status_code, on_missing.json())
    assert on_hidden.json()["error"]["details"]["fields"] == {"handover": "not_found"}
    assert _join(outsider, handover=shown).status_code == 201


def test_an_outsiders_join_hands_over_no_message(
    on: None, owner: flow.Human, outsider: flow.Human
) -> None:
    """A message `seq` is `invalid` (`card_only`) for an outsider, whatever the seq names."""
    _opt_in(owner)
    for seq in (1, 999999):
        refused = _join(outsider, handover=seq)
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"]["details"]["fields"] == {"handover": "card_only"}


def test_an_outsiders_agent_is_never_in_the_restricted_set(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The restricted set names its trusts (§6.1): an agent with trust `outside` is not in it,
    even under `all_except` with its owner a member by now."""
    from maity_hub import restricted

    agent = _outside_agent(make_client, owner, outsider)
    _member_now(migrated, outsider)
    project = _project(migrated)  # read before the write: SQLite has one writer
    settings = {**(project.settings or {}), "restricted_access": {"mode": "all_except"}}
    with migrated.begin() as conn:
        conn.execute(
            update(t.project).where(t.project.c.id == project.id).values(settings=settings)
        )
    with migrated.connect() as conn:
        found = restricted.resolve(conn, _project(migrated))
    assert _row(migrated, agent.id).id not in found
    assert found  # the counter-check of the setup: the set holds the project's own members


def test_listing_an_outsiders_agent_in_the_restricted_set_is_refused(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§6.1: `settings.restricted_access.members` naming an outsider's agent is `invalid` with
    `outside`, under either mode, its owner a member by now or not."""
    agent = _outside_agent(make_client, owner, outsider)
    field = f"settings.restricted_access.members.{agent.id}"
    for mode in ("nobody_except", "all_except"):
        refused = owner.patch(
            P, {"settings": {"restricted_access": {"mode": mode, "members": [agent.id]}}}
        )
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"]["details"]["fields"] == {field: "outside"}
    _member_now(migrated, outsider)
    refused = owner.patch(
        P, {"settings": {"restricted_access": {"mode": "nobody_except", "members": [agent.id]}}}
    )
    assert refused.json()["error"]["details"]["fields"] == {field: "outside"}


def test_merged_closes_counts_an_outsiders_agent_as_outside_after_its_owner_joins(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§2.3: trust `outside` stays outside when its owner becomes a member, so its card is
    still outsiders' work for `merged_closes` (merged.py)."""
    agent = _outside_agent(make_client, owner, outsider)
    card = _card(owner)
    assert owner.post(f"{P}/tasks/{card}/claim", {"holder": agent.id}).status_code == 200
    assert _outsiders_work(migrated, card) is True
    _member_now(migrated, outsider)
    assert _outsiders_work(migrated, card) is True


def _held_by(owner: flow.Human, agent_id: str) -> str:
    card = _card(owner)
    assert owner.post(f"{P}/tasks/{card}/claim", {"holder": agent_id}).status_code == 200
    return card


def _set_row(engine: Engine, agent_id: str, **values: Any) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == agent_id, t.membership.c.active.is_(True))
            .values(**values)
        )


def test_outsiders_work_by_the_trust_term_alone(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Trust `outside` on its current row: outside, with its owner a member and no
    `joined_outside` mark (cleared here so that only the trust decides)."""
    agent = _outside_agent(make_client, owner, outsider)
    card = _held_by(owner, agent.id)
    _member_now(migrated, outsider)
    _set_row(migrated, agent.id, joined_outside=False)
    assert _outsiders_work(migrated, card) is True


def test_outsiders_work_by_the_joined_outside_term_alone(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The `joined_outside` mark on its current row: outside, with trust `member` and its owner
    a member (the project's owner)."""
    agent = flow.agent(make_client, owner)
    card = _held_by(owner, agent.id)
    assert _outsiders_work(migrated, card) is False
    _set_row(migrated, agent.id, joined_outside=True)
    assert _outsiders_work(migrated, card) is True


def test_outsiders_work_by_the_owner_term_alone(
    owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Its owner holds no membership now: outside, with trust `member` and no mark."""
    agent = flow.agent(make_client, owner)
    card = _held_by(owner, agent.id)
    assert _outsiders_work(migrated, card) is False
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == agent.id)
            .values(owner_id=outsider.id)
        )
    assert _outsiders_work(migrated, card) is True


def test_a_rejoin_as_an_outsiders_agent_stays_outside(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    assert owner.delete(f"{P}/members/{agent.id}").status_code == 200
    again = _exchange(make_client, _join(outsider, agent={"id": agent.id}).json())
    assert _row(migrated, again.id).trust == "outside"
    card = _card(owner)
    assert _reason(again.post(f"{P}/tasks/{card}/claim", {})) == "not_open_to_outsiders"


def test_a_rejoin_as_a_members_agent_is_the_one_way_out(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§2.3: removed, then joined again by its owner, a member now, as a member's agent, it
    is a member's agent: trust `member`, its claim taken, its card not outsiders' work."""
    agent = _outside_agent(make_client, owner, outsider)
    _member_now(migrated, outsider)
    assert owner.delete(f"{P}/members/{agent.id}").status_code == 200
    again = _exchange(make_client, flow.join(outsider, "maity", agent={"id": agent.id}))
    assert _row(migrated, again.id).trust == "member"
    card = _card(owner)
    assert again.post(f"{P}/tasks/{card}/claim", {}).status_code == 200
    assert _outsiders_work(migrated, card) is False


def test_narrowing_outside_roles_counts_an_outsiders_agent_whose_owner_joined(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """One rule for check_assignment, check_policy and refuse_lift (§6.2): the membership's
    own trust `outside` binds it to `outside_roles` whoever its owner is now, so a list that
    leaves its role off is refused while it works."""
    _policy(owner, agent_owners="anyone", outside_roles=["coder", "designer"])
    _exchange(make_client, _join(outsider, role="designer").json())
    _member_now(migrated, outsider)
    narrowed = owner.patch(P, {"policy": {"outside_roles": ["coder"]}, "reason": "narrow"})
    assert narrowed.status_code == 400, narrowed.text
    assert narrowed.json()["error"]["details"]["fields"] == {"outside_roles": "outside_owner"}


def test_an_agents_assign_of_its_owners_expired_card_to_it_is_humans_only(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Same owner on every side, so §6.19's `cross_owner` does not answer first: the interim's
    `humans_only` does, before the holder's instance is chosen (§6.5)."""
    holder = _outside_agent(make_client, owner, outsider)
    receiver = _exchange(make_client, _join(outsider).json())
    admin = flow.agent(make_client, owner, trust="admin", role="coder")
    with migrated.begin() as conn:  # an admin agent of the same owner, as the setup needs
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == admin.id)
            .values(owner_id=outsider.id)
        )
    card = _card(owner)
    assert owner.post(f"{P}/tasks/{card}/claim", {"holder": holder.id}).status_code == 200
    with migrated.begin() as conn:
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card)
            .values(lease_until=clock.now() - timedelta(minutes=1))
        )
    refused = admin.post(f"{P}/tasks/{card}/assign", {"assignee": receiver.id})
    assert (refused.status_code, _reason(refused)) == (403, "humans_only"), refused.text


def test_its_own_claim_is_refused_before_the_cards_state(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    """§6.5's order: after the card's existence, before its state. A held card answers the
    outsider's agent `not_open_to_outsiders`, not `already_claimed`; an unknown card
    `not_found`."""
    agent = _outside_agent(make_client, owner, outsider)
    member = flow.agent(make_client, owner)
    card = _card(owner)
    assert member.post(f"{P}/tasks/{card}/claim", {}).status_code == 200
    held = agent.post(f"{P}/tasks/{card}/claim", {})
    assert (held.status_code, _reason(held)) == (403, "not_open_to_outsiders"), held.text
    unknown = agent.post(f"{P}/tasks/tsk-000000000000/claim", {})
    assert unknown.status_code == 404, unknown.text


def test_an_agents_hand_out_is_refused_before_the_holders_instance(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    """§6.5's order for a claim with `holder`: after the holder resolves to a member, before
    its instance, so an unknown instance answers `humans_only`, not `instance_required`."""
    agent = _outside_agent(make_client, owner, outsider)
    admin = flow.agent(make_client, owner, trust="admin", role="coder")
    card = _card(owner)
    refused = admin.post(f"{P}/tasks/{card}/claim", {"holder": f"{agent.id}#zzzz"})
    assert (refused.status_code, _reason(refused)) == (403, "humans_only"), refused.text


def test_a_human_without_tasks_admin_hands_it_nothing() -> None:
    """The scope branch of `refuse_taking`: a human who may move the card otherwise (a
    manager within its line) still needs `tasks:admin` (§6.5)."""
    from types import SimpleNamespace

    from maity_hub.errors import ApiError

    holder = SimpleNamespace(trust="outside", id=7)

    class Manager:
        kind, id = "human", 3

        def require(self, scope: str) -> None:
            raise ApiError(403, "forbidden", "no", {"scope": scope})

    with pytest.raises(ApiError) as refused:
        outsiders.refuse_taking(holder, Manager())
    assert refused.value.details == {"scope": "tasks:admin"}


def test_agent_owners_null_is_refused_once_set(owner: flow.Human) -> None:
    """§6.1: `null` would fall back to the unset reading quietly; `members` closes the joins."""
    _opt_in(owner)
    refused = owner.patch(P, {"policy": {"agent_owners": None}, "reason": "back to default"})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"policy.agent_owners": "unknown"}
    _policy(owner, agent_owners="members")


def test_cover_hands_it_no_card(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Cover (§6.12) is no way round the interim: `role:coder` reaches the outsider's coder,
    and the walk skips it, so with nobody else to take the card it stays with the covered
    member (§6.5, "Until the claim request is built")."""
    moment = [clock.now().replace(microsecond=0)]
    clock.set_source(lambda: moment[0])
    agent = _outside_agent(make_client, owner, outsider)
    covered = flow.agent(make_client, owner)
    for who in (agent, covered):
        who.resume()
    card = _card(owner)
    assert covered.post(f"{P}/tasks/{card}/claim", {}).status_code == 200
    set_policy = owner.patch(
        f"{P}/members/{covered.id}",
        {
            "availability_policy": {
                "on_unavailable": "substitute",
                "substitutes": ["role:coder"],
                "grace_minutes": 0,
            }
        },
    )
    assert set_policy.status_code == 200, set_policy.text
    limited = covered.post("/me/limit", {"until": clock.rfc3339(moment[0] + timedelta(hours=2))})
    assert limited.status_code == 200, limited.text
    assert owner.get(f"{P}/tasks/{card}").json()["claim"]["holder"] == covered.id
    with migrated.connect() as conn:
        started = conn.execute(select(t.event).where(t.event.c.kind == "cover_started")).all()
    assert started == []


def test_no_takeover_leaves_it_holding_a_card(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    member = flow.agent(make_client, owner)
    card = _card(owner)
    assert member.post(f"{P}/tasks/{card}/claim", {}).status_code == 200
    own = agent.post(f"{P}/tasks/{card}/takeover", {"reason": "mine now"})
    assert own.status_code == 403, own.text
    assert _reason(own) == "not_open_to_outsiders"
    other = flow.agent(make_client, owner)
    to_it = other.post(f"{P}/tasks/{card}/takeover", {"reason": "hand it over", "to": agent.id})
    assert to_it.status_code == 403, to_it.text
    assert _reason(to_it) == "not_open_to_outsiders"
