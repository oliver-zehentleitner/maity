"""docs/api.md §2.3 "The manager" and "Depth", §5.3, §6.2 and §6.4: the role manager,
its reach, `line:lead`, the pauses it sets, and how deep a chain may be."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, events, line
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_placements import Setup, place
from tests.test_placements import setup as setup  # noqa: F401 - the placement fixture

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
    return project_id


def _row(engine: Engine, principal: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.membership).where(
                (t.membership.c.agent_id == principal) | (t.membership.c.human_id == principal),
                t.membership.c.active.is_(True),
            )
        ).one()


def _mid(engine: Engine, principal: str) -> int:
    membership_id: int = _row(engine, principal).id
    return membership_id


def _set(engine: Engine, principal: str, **values: Any) -> None:
    """Write a membership's columns directly: `line_consent` has no API yet (the
    cross-owner consent flow is its own card), and long chains are quicker so."""
    if "reports_to" in values and isinstance(values["reports_to"], str):
        values["reports_to"] = _mid(engine, values["reports_to"])
    if "role" in values:  # a built-in role is its own base (§2.3)
        values["role_base"] = values["role"]
    membership_id = _mid(engine, principal)
    with engine.begin() as conn:
        conn.execute(update(t.membership).where(t.membership.c.id == membership_id).values(values))


def _reach(engine: Engine, principal: str) -> dict[str, str]:
    with engine.connect() as conn:
        found = line.reach(conn, _row(engine, principal))
        rows = conn.execute(
            select(t.membership.c.id, t.membership.c.agent_id, t.membership.c.human_id)
        ).all()
    names = {r.id: r.agent_id or r.human_id for r in rows}
    return {names[k]: v for k, v in found.items()}


def _other_owner_agent(engine: Engine, handle: str = "stranger") -> str:
    """An agent of another human, a member of the project."""
    other = factory.human(engine, handle)
    agent_id: str = factory.agent(engine, _project_id(engine), other).agent_id
    return agent_id


def member(who: Any, member_id: str, body: dict[str, Any]) -> Any:
    return who.patch(f"{PROJECT}/members/{member_id}", body)


def details(response: Any) -> Any:
    return response.json()["error"]["details"]


def _not_in_line(response: Any) -> None:
    assert response.status_code == 403, response.text
    assert details(response) == {"reason": "not_in_line"}


@pytest.fixture
def team(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> dict[str, Any]:
    """The owner's manager with a chain of two below it; a proxy, a human, an admin
    agent and another owner's agent reporting to it, each with one below."""
    manager = flow.agent(make_client, owner, role="manager", reports_to=owner.id)
    first = flow.agent(make_client, owner, reports_to=manager.id)
    second = flow.agent(make_client, owner, reports_to=first.id)
    proxy = flow.agent(make_client, owner, role="proxy", reports_to=manager.id)
    under_proxy = flow.agent(make_client, owner, reports_to=proxy.id)
    admin = flow.agent(make_client, owner, role="admin", reports_to=manager.id)
    under_admin = flow.agent(make_client, owner, reports_to=admin.id)
    colleague = factory.human(migrated, "colleague")
    factory.membership(migrated, _project_id(migrated), "member", human_id=colleague)
    _set(migrated, colleague, reports_to=manager.id)
    under_human = flow.agent(make_client, owner, reports_to=colleague)
    stranger = _other_owner_agent(migrated)
    _set(migrated, stranger, reports_to=manager.id)
    return {
        "manager": manager,
        "first": first,
        "second": second,
        "proxy": proxy,
        "under_proxy": under_proxy,
        "admin": admin,
        "under_admin": under_admin,
        "colleague": colleague,
        "under_human": under_human,
        "stranger": stranger,
    }


# --- the reach ------------------------------------------------------------------------


def test_the_reach_follows_the_owners_chain_and_stops_outside_it(
    team: dict[str, Any], migrated: Engine
) -> None:
    assert _reach(migrated, team["manager"].id) == {
        team["first"].id: "a",
        team["second"].id: "a",
    }


def test_a_consented_edge_adds_the_direct_report_and_nothing_below_it(
    team: dict[str, Any], migrated: Engine, owner: flow.Human
) -> None:
    stranger = team["stranger"]
    below = _other_owner_agent(migrated, "lender")
    _set(migrated, below, reports_to=stranger)
    _set(migrated, stranger, line_consent=True)
    reach = _reach(migrated, team["manager"].id)
    assert reach[stranger] == "b" and below not in reach
    view = owner.get(f"{PROJECT}/members/{stranger}").json()
    assert (view["cross_owner"], view["line_consent"]) == (True, True)
    own = owner.get(f"{PROJECT}/members/{team['first'].id}").json()
    assert (own["cross_owner"], own["line_consent"]) == (False, False)
    # A consented edge to a member of the reach, not to the manager itself, is no (b).
    _set(migrated, below, reports_to=team["first"].id, line_consent=True)
    assert below not in _reach(migrated, team["manager"].id)


def test_a_human_managers_reach_is_its_own_agents(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _set(migrated, owner.id, role="manager")  # an owner who also manages
    mine = flow.agent(make_client, owner, reports_to=owner.id)
    assert _reach(migrated, owner.id) == {mine.id: "a"}


def test_a_guest_manager_holds_nothing_of_the_role(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    manager = flow.agent(make_client, owner, role="manager", trust="guest")
    report = flow.agent(make_client, owner, reports_to=owner.id)
    _set(migrated, report.id, reports_to=manager.id)
    assert _reach(migrated, manager.id) == {}
    refused = member(manager, report.id, {"areas": ["x/"]})
    assert (refused.status_code, details(refused)) == (403, {"scope": "members:admin"})
    card = factory.card(migrated, _project_id(migrated), _mid(migrated, owner.id))
    assigned = manager.post(f"{PROJECT}/tasks/{card}/assign", {"assignee": report.id})
    assert (assigned.status_code, details(assigned)) == (403, {"scope": "tasks:admin"})


# --- cards ----------------------------------------------------------------------------


def test_assign_within_the_reach_and_not_outside(team: dict[str, Any], migrated: Engine) -> None:
    manager, first = team["manager"], team["first"]
    project_id = _project_id(migrated)
    card = factory.card(migrated, project_id, _mid(migrated, manager.id))
    done = manager.post(f"{PROJECT}/tasks/{card}/assign", {"assignee": first.id})
    assert done.status_code == 200, done.text
    assert done.json()["assigned_to"] == first.id
    moved = manager.post(f"{PROJECT}/tasks/{card}/assign", {"assignee": team["second"].id})
    assert moved.status_code == 200, moved.text
    _not_in_line(manager.post(f"{PROJECT}/tasks/{card}/assign", {"assignee": team["proxy"].id}))
    # A card assigned outside the reach is not the manager's to take back.
    outside = factory.card(
        migrated,
        project_id,
        _mid(migrated, manager.id),
        assigned_to=_mid(migrated, team["stranger"]),
    )
    _not_in_line(manager.post(f"{PROJECT}/tasks/{outside}/assign", {"assignee": first.id}))


def test_patch_assigned_to_alone_within_the_reach(team: dict[str, Any], migrated: Engine) -> None:
    manager, first = team["manager"], team["first"]
    card = factory.card(migrated, _project_id(migrated), _mid(migrated, first.id))
    path = f"{PROJECT}/tasks/{card}"
    assert manager.patch(path, {"assigned_to": first.id}).json()["assigned_to"] == first.id
    back = manager.patch(path, {"assigned_to": None})
    assert back.status_code == 200, back.text
    assert back.json()["assigned_to"] is None  # back to nobody
    _not_in_line(manager.patch(path, {"assigned_to": team["under_admin"].id}))
    refused = manager.patch(path, {"assigned_to": first.id, "title": "mine now"})
    assert (refused.status_code, details(refused)) == (403, {"scope": "tasks:admin"})


def test_a_card_it_creates_is_assigned_within_the_reach(team: dict[str, Any]) -> None:
    manager = team["manager"]
    made = manager.post(f"{PROJECT}/tasks", {"title": "x", "assigned_to": team["second"].id})
    assert made.status_code == 201, made.text
    assert made.json()["assigned_to"] == team["second"].id
    _not_in_line(
        manager.post(f"{PROJECT}/tasks", {"title": "y", "assigned_to": team["under_human"].id})
    )


def _claimed(engine: Engine, holder: str, created_by: int) -> str:
    past = clock.now() - timedelta(minutes=5)
    return factory.card(
        engine,
        _project_id(engine),
        created_by,
        status="in_progress",
        claim_holder=_mid(engine, holder),
        claim_instance=_row(engine, holder).lead_instance,
        claim_since=past - timedelta(hours=1),
        lease_until=past,
    )


def test_release_of_an_expired_claim_in_the_reach(team: dict[str, Any], migrated: Engine) -> None:
    manager = team["manager"]
    creator = _mid(migrated, manager.id)
    card = _claimed(migrated, team["second"].id, creator)
    released = manager.post(f"{PROJECT}/tasks/{card}/release")
    assert released.status_code == 200, released.text
    assert released.json()["status"] == "open"
    outside = _claimed(migrated, team["under_proxy"].id, creator)
    _not_in_line(manager.post(f"{PROJECT}/tasks/{outside}/release"))


# --- the membership -------------------------------------------------------------------


def test_areas_paused_and_reports_to_within_the_reach(
    team: dict[str, Any], migrated: Engine
) -> None:
    manager, first, second = team["manager"], team["first"], team["second"]
    changed = member(manager, second.id, {"areas": ["web/"], "reports_to": manager.id})
    assert changed.status_code == 200, changed.text
    assert (changed.json()["areas"], changed.json()["reports_to"]) == (["web/"], manager.id)
    assert member(manager, second.id, {"reports_to": first.id}).status_code == 200
    for field, value in (
        ("trust", "guest"),
        ("role", "reviewer"),
        ("briefing", "x"),
        ("capabilities", ["tag"]),
    ):
        refused = member(manager, first.id, {field: value})
        assert (refused.status_code, details(refused)) == (403, {"scope": "members:admin"}), field
    # The new boss stays in the reach: never above the manager, never outside it.
    _not_in_line(member(manager, second.id, {"reports_to": team["admin"].id}))
    _not_in_line(member(manager, second.id, {"reports_to": None}))
    _not_in_line(member(manager, team["proxy"].id, {"areas": ["x/"]}))
    _not_in_line(member(manager, team["under_human"].id, {"areas": ["x/"]}))
    _not_in_line(member(manager, manager.id, {"areas": ["x/"]}))
    # A (b) member: areas and pause, its edge stays the consented one.
    stranger = team["stranger"]
    _set(migrated, stranger, line_consent=True)
    assert member(manager, stranger, {"areas": ["docs/"]}).status_code == 200
    _not_in_line(member(manager, stranger, {"reports_to": first.id}))


def test_a_reviewers_pause_and_edge_wait_for_a_humans_go(
    owner: flow.Human, team: dict[str, Any], migrated: Engine
) -> None:
    manager = team["manager"]
    reviewer = factory.agent(migrated, _project_id(migrated), owner.id, "reviewer").agent_id
    _set(migrated, reviewer, reports_to=manager.id)
    waiting = member(manager, reviewer, {"paused": {"reason": "too many cards"}})
    assert waiting.status_code == 202, waiting.text
    request = waiting.json()
    assert (request["class"], request["status"]) == ("consent", "open")
    assert owner.get(f"{PROJECT}/members/{reviewer}").json()["paused"] is None
    go = owner.post(f"{PROJECT}/requests/{request['id']}/answer", {"reply_id": "go"})
    assert go.status_code == 200, go.text
    paused = owner.get(f"{PROJECT}/members/{reviewer}").json()["paused"]
    assert paused["by"] == manager.id
    assert _row(migrated, reviewer).paused_line is True
    moved = member(manager, reviewer, {"reports_to": team["first"].id})
    assert moved.status_code == 202, moved.text
    # The coordinator is a seat as well, whatever its role.
    owner.patch(PROJECT, {"policy": {"coordinator": team["first"].id}, "reason": "x"})
    seat = member(manager, team["first"].id, {"paused": {"reason": "x"}})
    assert seat.status_code == 202, seat.text


def test_a_managers_consented_line_change_never_makes_a_cross_owner_edge(
    owner: flow.Human, team: dict[str, Any], migrated: Engine
) -> None:
    """§2.3: a `line_change` stays inside the reach, so it has no cross-owner edge to ask
    for (§6.2): another owner's agent is refused when it is asked and when the go comes."""
    manager, first, stranger = team["manager"], team["first"], team["stranger"]
    reviewer = factory.agent(migrated, _project_id(migrated), owner.id, "reviewer").agent_id
    _set(migrated, reviewer, reports_to=manager.id)
    _set(migrated, stranger, line_consent=True)  # in the reach, as a (b) member
    _not_in_line(member(manager, reviewer, {"reports_to": stranger}))
    waiting = member(manager, reviewer, {"reports_to": first.id})
    assert waiting.status_code == 202, waiting.text
    # The new boss comes to report to the other owner's agent before the go.
    _set(migrated, first.id, reports_to=stranger)
    go = owner.post(f"{PROJECT}/requests/{waiting.json()['id']}/answer", {"reply_id": "go"})
    assert (go.status_code, go.json()["error"]["code"]) == (409, "not_in_line")
    assert _row(migrated, reviewer).reports_to == _mid(migrated, manager.id)


# --- pauses ---------------------------------------------------------------------------


def test_a_managers_pause_outlasts_resume_and_is_not_the_agents_to_lift(
    team: dict[str, Any], migrated: Engine
) -> None:
    manager, first = team["manager"], team["first"]
    paused = member(manager, first.id, {"paused": {"reason": "slow down"}})
    assert paused.status_code == 200, paused.text
    assert paused.json()["paused"]["by"] == manager.id
    first.resume()
    assert _row(migrated, first.id).paused_since is not None
    refused = first.patch("/me", {"paused": None})
    assert (refused.status_code, details(refused)) == (403, {"reason": "paused_by_manager"})
    # A pause gates new work like any other.
    blocked = first.post(f"{PROJECT}/tasks", {"title": "new"})
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (409, "paused")
    assert member(manager, first.id, {"paused": None}).json()["paused"] is None


def test_who_lifts_a_managers_pause(
    owner: flow.Human, team: dict[str, Any], migrated: Engine, make_client: ClientFactory
) -> None:
    manager, second = team["manager"], team["second"]
    above = flow.agent(make_client, owner, role="manager", reports_to=owner.id)
    _set(migrated, manager.id, reports_to=above.id)
    beside = flow.agent(make_client, owner, role="manager", reports_to=owner.id)

    def pause() -> None:
        assert member(manager, second.id, {"paused": {"reason": "x"}}).status_code == 200

    pause()
    refused = member(beside, second.id, {"paused": None})
    _not_in_line(refused)  # not in its reach at all
    assert member(above, second.id, {"paused": None}).status_code == 200  # a manager above
    pause()
    assert member(team["admin"], second.id, {"paused": None}).status_code == 200  # ᵃ lifts
    pause()
    replaced = member(team["admin"], second.id, {"paused": {"reason": "mine"}})
    assert replaced.status_code == 403  # but does not replace it
    assert member(owner, second.id, {"paused": None}).status_code == 200  # members:admin
    # The agent's owner without members:admin, here not even a member of the project.
    friend = flow.human(make_client, migrated, "friend")
    lent = factory.agent(migrated, _project_id(migrated), friend.id).agent_id
    _set(migrated, lent, reports_to=manager.id, line_consent=True)
    assert member(manager, lent, {"paused": {"reason": "x"}}).status_code == 200
    lifted = member(friend, lent, {"paused": None})
    assert lifted.status_code == 204, lifted.text
    assert _row(migrated, lent).paused_since is None


def test_an_admin_agent_never_touches_a_human_managers_pause(
    team: dict[str, Any], migrated: Engine, make_client: ClientFactory
) -> None:
    """A human manager's pause is a human's pause (§5.3), whatever right set it."""
    friend = flow.human(make_client, migrated, "friend")
    factory.membership(migrated, _project_id(migrated), "member", human_id=friend.id)
    _set(migrated, friend.id, role="manager")
    lent = factory.agent(migrated, _project_id(migrated), friend.id).agent_id
    _set(migrated, lent, reports_to=friend.id)
    paused = member(friend, lent, {"paused": {"reason": "x"}})
    assert paused.status_code == 200, paused.text
    assert _row(migrated, lent).paused_line is True
    for body in ({"paused": None}, {"paused": {"reason": "mine"}}):
        refused = member(team["admin"], lent, body)
        assert refused.status_code == 403, refused.text
    assert _row(migrated, lent).paused_by == friend.id


def test_the_line_path_decides_on_the_row_under_the_lock(
    owner: flow.Human, team: dict[str, Any], migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A human's pause written between the route's first read and the project lock is
    the one the manager meets: it is not the manager's to replace."""
    first = _mid(migrated, team["first"].id)
    original = events.lock_project

    def meanwhile(conn: Any, project_id: str) -> None:
        original(conn, project_id)
        paused = {"paused_since": clock.now(), "paused_by": owner.id, "paused_reason": "mine"}
        conn.execute(update(t.membership).where(t.membership.c.id == first).values(paused))

    monkeypatch.setattr("maity_hub.line.lock_project", meanwhile)
    refused = member(team["manager"], team["first"].id, {"paused": {"reason": "x"}})
    assert (refused.status_code, details(refused)) == (403, {"scope": "members:admin"})


def test_a_manager_never_lifts_a_humans_or_an_admins_pause(
    owner: flow.Human, team: dict[str, Any]
) -> None:
    manager, first = team["manager"], team["first"]
    assert member(owner, first.id, {"paused": {"reason": "mine"}}).status_code == 200
    for body in ({"paused": None}, {"paused": {"reason": "other"}}):
        refused = member(manager, first.id, body)
        assert (refused.status_code, details(refused)) == (403, {"scope": "members:admin"})
    assert member(owner, first.id, {"paused": None}).status_code == 200
    assert member(team["admin"], first.id, {"paused": {"reason": "admin's"}}).status_code == 200
    refused = member(manager, first.id, {"paused": None})
    assert (refused.status_code, details(refused)) == (403, {"scope": "members:admin"})


def test_losing_the_role_ends_the_consent_and_lifts_the_pause(
    owner: flow.Human, team: dict[str, Any], migrated: Engine
) -> None:
    manager, stranger = team["manager"], team["stranger"]
    _set(migrated, stranger, line_consent=True)
    assert member(manager, stranger, {"paused": {"reason": "x"}}).status_code == 200
    assert member(manager, team["first"].id, {"paused": {"reason": "x"}}).status_code == 200
    assert member(owner, manager.id, {"role": "coder"}).status_code == 200
    row = _row(migrated, stranger)
    assert (row.line_consent, row.paused_since) == (False, None)
    # Getting the role back does not bring the consent back (§6.2).
    assert member(owner, manager.id, {"role": "manager"}).status_code == 200
    assert _row(migrated, stranger).line_consent is False
    assert stranger not in _reach(migrated, manager.id)


def test_trust_guest_ends_the_consent_as_losing_the_role_does(
    owner: flow.Human, team: dict[str, Any], migrated: Engine
) -> None:
    manager, stranger = team["manager"], team["stranger"]
    _set(migrated, stranger, line_consent=True)
    assert member(manager, stranger, {"paused": {"reason": "x"}}).status_code == 200
    assert member(owner, manager.id, {"trust": "guest"}).status_code == 200
    row = _row(migrated, stranger)
    assert (row.line_consent, row.paused_since) == (False, None)
    # Back at trust member, the old consent stays gone (§6.2).
    assert member(owner, manager.id, {"trust": "member"}).status_code == 200
    assert stranger not in _reach(migrated, manager.id)


def test_only_a_human_lowers_a_manager_to_guest(team: dict[str, Any], migrated: Engine) -> None:
    """Guest ends the consents as the role removal does, so an admin agent may do
    neither (§2.3 ᵃ)."""
    manager, stranger = team["manager"], team["stranger"]
    _set(migrated, stranger, line_consent=True)
    assert member(manager, stranger, {"paused": {"reason": "x"}}).status_code == 200
    refused = member(team["admin"], manager.id, {"trust": "guest"})
    assert refused.status_code == 403, refused.text
    row = _row(migrated, stranger)
    assert row.line_consent is True and row.paused_since is not None
    assert _row(migrated, manager.id).trust == "member"


def test_ending_the_edge_ends_the_consent_and_lifts_the_pause(
    owner: flow.Human, team: dict[str, Any], migrated: Engine
) -> None:
    manager, stranger = team["manager"], team["stranger"]
    _set(migrated, stranger, line_consent=True)
    assert member(manager, stranger, {"paused": {"reason": "x"}}).status_code == 200
    ended = member(owner, stranger, {"reports_to": None})
    assert ended.status_code == 200, ended.text
    assert (ended.json()["line_consent"], ended.json()["paused"]) == (False, None)
    # Removing the boss ends the edge the same way.
    _set(migrated, stranger, reports_to=manager.id, line_consent=True)
    assert member(manager, stranger, {"paused": {"reason": "x"}}).status_code == 200
    assert owner.delete(f"{PROJECT}/members/{manager.id}").status_code == 200
    row = _row(migrated, stranger)
    assert (row.reports_to, row.line_consent, row.paused_since) == (None, False, None)


# --- who holds the role ---------------------------------------------------------------


def test_only_a_human_grants_or_removes_the_role(owner: flow.Human, team: dict[str, Any]) -> None:
    admin, manager, first = team["admin"], team["manager"], team["first"]
    for target, role in ((first.id, "manager"), (manager.id, "coder")):
        refused = member(admin, target, {"role": role})
        assert (refused.status_code, details(refused)) == (403, {"reason": "humans_only"})
    refused = member(manager, first.id, {"role": "manager"})
    assert (refused.status_code, details(refused)) == (403, {"scope": "members:admin"})
    granted = member(owner, first.id, {"role": "manager"})
    assert granted.status_code == 200, granted.text
    packet = first.resume().json()
    assert "line:lead" in packet["membership"]["scopes"]
    assert "POST /projects/maintainer/maity/tasks/{id}/assign" in packet["operations"]


def test_a_member_brings_a_manager_and_a_team_below_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    factory.membership(migrated, _project_id(migrated), "member", human_id=friend.id)
    joins = f"{PROJECT}/joins"
    agent = {"handle": "friend-manager", "display_name": "Lead"}
    created = friend.post(joins, {"agent": agent, "role": "manager"})
    assert created.status_code == 201, created.text
    manager = flow.exchange(make_client(), created.json()).headers["Maity-Member-Id"]
    below = {"agent": {"handle": "friend-coder", "display_name": "C"}, "reports_to": manager}
    joined = friend.post(joins, below)
    assert joined.status_code == 201, joined.text
    coder = flow.exchange(make_client(), joined.json()).headers["Maity-Member-Id"]
    assert _reach(migrated, manager) == {coder: "a"}
    # Someone else's manager is beyond the limits.
    owners = flow.agent(make_client, owner, role="manager")
    other = {"agent": {"handle": "friend-x", "display_name": "X"}, "reports_to": owners.id}
    refused = friend.post(joins, other)
    assert details(refused) == {"reason": "member_join_limit", "field": "reports_to"}


# --- depth ----------------------------------------------------------------------------


def _chain(engine: Engine, owner_id: str, length: int, top: str | None = None) -> list[str]:
    """`length` agents, each reporting to the one before; the first to `top`."""
    project_id = _project_id(engine)
    made: list[str] = []
    for _ in range(length):
        agent_id = factory.agent(engine, project_id, owner_id).agent_id
        boss = made[-1] if made else top
        if boss is not None:
            _set(engine, agent_id, reports_to=boss)
        made.append(agent_id)
    return made


def _too_deep(response: Any) -> None:
    assert response.status_code == 400, response.text
    assert details(response) == {"fields": {"reports_to": "too_deep"}}


def test_a_patch_counts_the_chain_above_and_the_deepest_below(
    owner: flow.Human, migrated: Engine
) -> None:
    upper = _chain(migrated, owner.id, 5)  # 5 long
    lower = _chain(migrated, owner.id, 3)  # 3 long below its top
    assert member(owner, lower[0], {"reports_to": upper[-1]}).status_code == 200  # 8
    loose = _chain(migrated, owner.id, 1)
    _too_deep(member(owner, loose[0], {"reports_to": lower[-1]}))  # 9
    # An existing longer chain stays, and naming the same boss again is no move.
    _set(migrated, loose[0], reports_to=lower[-1])
    assert member(owner, loose[0], {"reports_to": lower[-1]}).status_code == 200


def test_the_go_of_an_admin_agents_request_checks_the_depth(
    owner: flow.Human, team: dict[str, Any], migrated: Engine
) -> None:
    chain = _chain(migrated, owner.id, 7)
    boss = _chain(migrated, owner.id, 1)[0]
    reviewer = factory.agent(migrated, _project_id(migrated), owner.id, "reviewer").agent_id
    proposed = member(team["admin"], reviewer, {"role": "coder", "reports_to": boss})
    assert proposed.status_code == 202, proposed.text
    assert member(owner, boss, {"reports_to": chain[-1]}).status_code == 200  # boss at 8
    go = owner.post(f"{PROJECT}/requests/{proposed.json()['id']}/answer", {"reply_id": "go"})
    _too_deep(go)  # the reviewer would sit at 9
    assert _row(migrated, reviewer).reports_to is None


def test_a_join_checks_the_depth_and_its_exchange_drops_a_boss_too_deep(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    chain = _chain(migrated, owner.id, 8)
    refused = owner.post(
        f"{PROJECT}/joins",
        {"agent": {"handle": "deep", "display_name": "D"}, "reports_to": chain[-1]},
    )
    _too_deep(refused)
    fits = flow.join(owner, "maity", reports_to=chain[-2])  # the 8th member
    _set(migrated, chain[0], reports_to=_chain(migrated, owner.id, 1)[0])  # one more above
    joined = flow.exchange(make_client(), fits)
    assert joined.status_code == 201, joined.text
    assert _row(migrated, joined.headers["Maity-Member-Id"]).reports_to is None


def test_a_placement_that_creates_a_profile_checks_the_depth(setup: Setup) -> None:  # noqa: F811
    chain = _chain(setup.engine, setup.owner.id, 8)
    body = {"agent": {"handle": "deep", "display_name": "D"}, "reports_to": chain[-1]}
    _too_deep(place(setup, **body))
    body["reports_to"] = chain[-2]
    assert place(setup, **body).status_code == 201
