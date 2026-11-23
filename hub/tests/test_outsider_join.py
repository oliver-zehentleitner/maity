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

from maity_hub import agent_owners, clock, outsiders, probe, public_pages, scopes
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
    on: None, owner: flow.Human, outsider: flow.Human
) -> None:
    """B.1 of §6.30: the join takes the contract's list as well, so a list that still names
    `blue-team` lets no outsider's agent hold it; `coder` on the same list passes."""
    _policy(owner, agent_owners="anyone", outside_roles=["coder", "blue-team"])
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


def test_trust_outside_holds_a_members_scopes_for_its_role_and_never_more() -> None:
    admin_only = {"tasks:admin", "members:admin", "project:admin", "requests:answer", "line:lead"}
    for role in ("coder", "reviewer", "manager", "proxy", "ops"):
        # Less than trust `member` by exactly `line:lead` and a proxy's `requests:answer`.
        member = set(scopes.scopes_for("member", role, "agent")) - {"line:lead", "requests:answer"}
        held = set(scopes.scopes_for("outside", role, "agent"))
        assert held == member, role
        assert not held & admin_only, role
    assert "outside" not in scopes.TRUSTS  # no PATCH, invitation or other join sets it


# --- isolation (§6.2) ---------------------------------------------------------------------------


def test_the_agent_stays_while_the_opt_in_holds_and_is_isolated_under_members(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    project_id = _project(migrated).id
    with migrated.begin() as conn:
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
