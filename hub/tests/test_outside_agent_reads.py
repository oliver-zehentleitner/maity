"""docs/api.md §2.3 "Outside", §3.1 "An outsider's agent", §6.2, §6.3, §8.2: an agent with trust
`outside` reads the project as its owner reads it from outside, plus its own membership and
cards and the events of the cards it reads; a card that becomes one it does not read is taken
from it; an outsider's joins are limited; an isolated membership from outside keeps its
profile (tsk-n0ef3c9j4s6f)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import access, cards, clock, events
from maity_hub import tables as t
from maity_hub.ratelimit import Limiter
from maity_hub.routes import agents, joins
from maity_hub.routes.members import OUTSIDE_MEMBER_KEYS
from maity_hub.routes.projects import OUTSIDE_PROJECT_KEYS
from tests import flow
from tests.conftest import ClientFactory
from tests.test_outside_reads import _app_routes, _hold
from tests.test_outsider_join import (
    JOINS,
    NOT_FOUND,
    P,
    _exchange,
    _join,
    _opt_in,
    _outside_agent,
)
from tests.test_outsider_join import make_client as make_client  # noqa: F401  (fixtures)
from tests.test_outsider_join import on as on  # noqa: F401
from tests.test_outsider_join import outsider as outsider  # noqa: F401
from tests.test_outsider_join import owner as owner  # noqa: F401


class Team:
    """The owner, an outsider's agent (trust `outside`) and a member's agent of the same role
    (trust `member`), with a card each kind: an open one, a `security` one not done, a done
    `security` one and a held one."""

    def __init__(
        self, make_client: ClientFactory, owner: flow.Human, outsider: flow.Human, engine: Engine
    ) -> None:
        self.owner = owner
        self.outsider = outsider
        self.engine = engine
        self.agent = _outside_agent(make_client, owner, outsider)
        self.member = flow.agent(make_client, owner)
        self.open = self.card("Open work")
        self.secret = self.card("A hole", label="security")
        self.fixed = self.card("A fixed hole", label="security")
        with engine.begin() as conn:  # done, as a report and its review would leave it
            conn.execute(
                update(t.card)
                .where(t.card.c.id == self.fixed)
                .values(status="done", closed_at=clock.now())
            )
        self.held = self.card("Held")
        _hold(engine, owner.id, self.held)

    def card(self, title: str, **body: Any) -> str:
        made = self.owner.post(f"{P}/tasks", {"title": title, **body})
        assert made.status_code == 201, made.text
        card_id: str = made.json()["id"]
        return card_id

    @property
    def hidden(self) -> tuple[str, str]:
        return (self.secret, self.held)


@pytest.fixture
def labels(monkeypatch: pytest.MonkeyPatch) -> None:
    """The label `security` through the API. The labels §6.4 lists are `fix`, `feature` and
    `chore`; a card carries `security` from elsewhere (an older hub's data). Here a human sets
    it on a card as the decision describes, so the card's edit path is the one exercised."""
    monkeypatch.setattr(cards, "LABELS", (*cards.LABELS, "security"))


@pytest.fixture
def team(
    on: None,
    labels: None,
    make_client: ClientFactory,
    owner: flow.Human,
    outsider: flow.Human,
    migrated: Engine,
) -> Team:
    return Team(make_client, owner, outsider, migrated)


def _ids(answer: Any) -> set[str]:
    assert answer.status_code == 200, answer.text
    return {item["id"] for item in answer.json()["items"]}


def _gone(answer: Any) -> None:
    assert (answer.status_code, answer.json()) == (404, NOT_FOUND), answer.text


# --- the cards ----------------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["", "?order=updated", "?q=hole", "?order=board&status=open"])
def test_the_card_list_its_search_and_the_board_leave_out_what_the_agent_does_not_read(
    team: Team, query: str
) -> None:
    seen = _ids(team.agent.get(f"{P}/tasks{query}"))
    assert not seen & set(team.hidden), query
    everyone = _ids(team.member.get(f"{P}/tasks{query}"))
    if query == "?q=hole":
        assert team.secret in everyone and team.fixed in seen and team.fixed in everyone
    elif query.endswith("status=open"):
        assert {team.open, team.secret, team.held} <= everyone and team.open in seen
    else:
        assert set(team.hidden) | {team.open, team.fixed} <= everyone
        assert {team.open, team.fixed} <= seen


def test_a_hidden_card_its_history_and_notes_answer_not_found(team: Team) -> None:
    for card_id in team.hidden:
        for tail in ("", "/history", "/notes"):
            _gone(team.agent.get(f"{P}/tasks/{card_id}{tail}"))
            assert team.member.get(f"{P}/tasks/{card_id}{tail}").status_code == 200
    for tail in ("", "/history", "/notes"):
        assert team.agent.get(f"{P}/tasks/{team.fixed}{tail}").status_code == 200


def test_a_hidden_card_is_no_trace_in_another_cards_view(team: Team) -> None:
    parent = team.card("Parent", related=[team.secret], depends_on=[team.held])
    team.card("Child", parent=parent, label="security")
    seen = team.agent.get(f"{P}/tasks/{parent}").json()
    assert seen["related"] == [] and seen["depends_on"] == []
    assert seen["children"] == {"open": 0, "total": 0}
    full = team.member.get(f"{P}/tasks/{parent}").json()
    assert full["related"] == [team.secret] and full["depends_on"] == [team.held]
    assert full["children"]["total"] == 1


def test_a_write_on_a_hidden_card_answers_not_found(team: Team) -> None:
    for card_id in team.hidden:
        _gone(team.agent.post(f"{P}/tasks/{card_id}/notes", {"body": "a note"}))
        _gone(team.agent.patch(f"{P}/tasks/{card_id}", {"title": "Renamed"}))
    added = team.agent.post(f"{P}/tasks/{team.open}/notes", {"body": "a note"})
    assert added.status_code == 201, added.text


# --- the project, its members, and the reads closed to the agent ---------------------------------


def test_the_project_view_is_the_outsiders(team: Team) -> None:
    seen = team.agent.get(P).json()
    assert set(seen) <= set(OUTSIDE_PROJECT_KEYS)
    assert set(seen["settings"]) == {"language"}
    for key in ("repository", "memory", "setup", "policy"):
        assert key not in seen, key
    assert team.agent.get("/projects").json()["items"] == [{**seen, "isolated": False}]
    full = team.member.get(P).json()
    assert "repository" in full and set(full["settings"]) > {"language"}


def test_the_agent_reads_its_own_row_in_full_and_every_other_as_from_outside(team: Team) -> None:
    rows = {m["id"]: m for m in team.agent.get(f"{P}/members").json()["items"]}
    assert "presence" in rows[team.agent.id]  # its own row, as a member reads its own
    others = [row for member_id, row in rows.items() if member_id != team.agent.id]
    assert others
    for row in others:
        assert set(row) <= set(OUTSIDE_MEMBER_KEYS), row["id"]
    own = team.agent.get(f"{P}/members/{team.agent.id}").json()
    assert "presence" in own
    other = team.agent.get(f"{P}/members/{team.owner.id}").json()
    assert set(other) <= set(OUTSIDE_MEMBER_KEYS)
    assert "presence" in team.member.get(f"{P}/members/{team.owner.id}").json()


@pytest.mark.parametrize(
    "path",
    [
        "/messages",
        "/requests",
        "/requests/req-000000000000",
        "/jour-fixe",
        "/jour-fixe/series",
        "/jour-fixe/rounds",
        "/memory",
        "/memory?store=community",
        "/rules",
        "/overview",
        "/swarm",
        "/contract",
        "/ticker",
        "/conversations",
        "/attachments",
    ],
)
def test_the_reads_beyond_the_outsiders_answer_not_found(team: Team, path: str) -> None:
    _gone(team.agent.get(f"{P}{path}"))
    if "req-0" not in path:
        assert team.member.get(f"{P}{path}").status_code != 404, path


def test_every_read_of_the_project_off_the_list_answers_not_found_before_its_query(
    team: Team,
) -> None:
    """Closed by construction: every `GET` project route the app serves that is not in
    `OUTSIDE_AGENT_READS`, a route added later included, answers the agent as an outsider,
    before its query or its path's values are judged."""
    project = f"{access.API_PROJECT}"
    routes = sorted(
        path
        for method, path in _app_routes(team.agent.client.app)
        if method == "GET"
        and (path == project or path.startswith(project + "/"))
        and ("GET", path) not in access.OUTSIDE_AGENT_READS
    )
    assert len(routes) > 20
    for path in routes:
        filled = re.sub(
            r"{(\w+)(?::[^}]*)?}",
            lambda m: {"owner": "maintainer", "slug": "maity"}.get(m.group(1), "zz"),
            path,
        )
        answer = team.agent.client.get(f"{filled}?limit=bogus", headers=team.agent.auth)
        assert (answer.status_code, answer.json()) == (404, NOT_FOUND), path


def test_a_group_chat_it_was_added_to_is_closed_to_it_for_reads_and_writes(team: Team) -> None:
    made = team.owner.post(
        f"{P}/conversations", {"title": "Room", "participants": [team.agent.id, team.member.id]}
    )
    assert made.status_code == 201, made.text
    room = made.json()["id"]
    for path in (f"/conversations/{room}", f"/conversations/{room}/messages"):
        _gone(team.agent.get(f"{P}{path}"))
        assert team.member.get(f"{P}{path}").status_code == 200, path
    _gone(team.agent.post(f"{P}/conversations/{room}/messages", {"body": "hello"}))
    via_events = team.agent.post(
        f"{P}/events",
        {"kind": "message", "type": "chat", "conversation_id": room, "body": "hello"},
    )
    assert via_events.status_code == 400, via_events.text  # as for a chat it is not in
    said = team.member.post(f"{P}/conversations/{room}/messages", {"body": "hello"})
    assert said.status_code == 201, said.text
    assert "hello" not in _event_text(team.agent.get(f"{P}/events", params={"after": 0}))


# --- the events ---------------------------------------------------------------------------------


def _event_text(answer: Any) -> str:
    assert answer.status_code == 200, answer.text
    return str(answer.json()["items"])


def _kinds(answer: Any) -> set[str]:
    assert answer.status_code == 200, answer.text
    return {item["kind"] for item in answer.json()["items"]}


def _given(team: Team, who: flow.Agent, title: str) -> str:
    """A card a human of the project hands `who` (§6.5): its events name `who`."""
    card_id = team.card(title)
    given = team.owner.post(f"{P}/tasks/{card_id}/claim", {"holder": who.id})
    assert given.status_code == 200, given.text
    return card_id


def _seq(engine: Engine, card_id: str, kind: str) -> int:
    with engine.connect() as conn:
        seq: int = conn.execute(
            select(t.event.c.seq).where(t.event.c.subject_id == card_id, t.event.c.kind == kind)
        ).scalar_one()
    return seq


def test_the_events_of_a_card_it_does_not_read_never_reach_it(team: Team) -> None:
    shown, hidden = _given(team, team.agent, "Shown"), _given(team, team.agent, "Hidden")
    theirs = _given(team, team.member, "The member's")
    for card_id in (hidden, theirs):
        _hold(team.engine, team.owner.id, card_id)  # in the table: no release runs
    said = team.owner.post(
        f"{P}/events", {"kind": "message", "type": "notice", "to": "all", "body": "to all"}
    )
    assert said.status_code == 201, said.text
    seen = team.agent.get(f"{P}/events", params={"after": 0})
    assert shown in _event_text(seen) and hidden not in _event_text(seen)
    assert "message" not in _kinds(seen)
    everyone = team.member.get(f"{P}/events", params={"after": 0})
    assert theirs in _event_text(everyone) and "message" in _kinds(everyone)
    _gone(team.agent.get(f"{P}/events/{_seq(team.engine, hidden, 'task_claimed')}"))
    assert (
        team.agent.get(f"{P}/events/{_seq(team.engine, shown, 'task_claimed')}").status_code == 200
    )
    held = f"{P}/events/{_seq(team.engine, theirs, 'task_claimed')}"
    assert team.member.get(held).status_code == 200


def test_a_wait_is_not_woken_by_what_it_does_not_read(team: Team) -> None:
    cursor = team.agent.get(f"{P}/events", params={"after": "latest"}).json()["cursor"]
    hidden = team.card("Another hole", label="security")
    team.owner.patch(f"{P}/tasks/{hidden}", {"assigned_to": team.agent.id})
    team.owner.post(f"{P}/events", {"kind": "message", "type": "notice", "to": "all", "body": "x"})
    waited = team.agent.get(f"{P}/events", params={"after": cursor, "wait": 1})
    assert waited.status_code == 200, waited.text
    assert waited.json()["items"] == []
    shown = _given(team, team.agent, "Visible work")
    woke = team.agent.get(f"{P}/events", params={"after": cursor, "wait": 1})
    assert shown in _event_text(woke)


# The keys of the packet's `project` an agent with trust `outside` reads (§2.3 "What it reads").
PACKET_PROJECT_KEYS = {
    "language", "id", "full_name", "slug", "name", "state", "released_at", "state_changed_at",
    "rules_version",
}  # fmt: skip


def test_the_resume_packet_is_read_as_from_outside(team: Team) -> None:
    given = team.owner.post(f"{P}/tasks/{team.open}/claim", {"holder": team.agent.id})
    assert given.status_code == 200, given.text
    _hold(team.engine, team.owner.id, team.open)  # straight in the table: no release runs
    written = team.member.post(f"{P}/memory", {"store": "role", "text": "How coders work."})
    assert written.status_code == 201, written.text  # the same role as the agent's
    packet = team.agent.resume().json()
    assert packet["claims"] == []  # a card it holds but does not read now
    assert team.secret not in str(packet["events"]) and team.open not in str(packet["events"])
    assert set(packet["project"]) <= PACKET_PROJECT_KEYS
    assert "markdown" not in packet["rules"]
    assert {"setup", "onboarding", "keep_the_why"}.isdisjoint(packet)
    assert packet["membership"]["briefing_source"] != "project"
    for store in ("team", "role", "community"):
        assert packet["memory"][store]["items"] == [], store
    assert packet["requests"]["to_answer"] == [] and packet["ticker"]["items"] == []
    assert packet["conversations"] == []
    for peer in packet["peers"]:
        assert "presence" not in peer
    member = team.member.resume().json()
    assert member["memory"]["role"]["items"] and "repository" in member["project"]
    assert "markdown" in member["rules"]


# --- fail closed when a card is hidden ----------------------------------------------------------


def _card_row(engine: Engine, card_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.card).where(t.card.c.id == card_id)).one()


def _released(engine: Engine, card_id: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.event.c.payload).where(
                    t.event.c.subject_id == card_id, t.event.c.kind == "task_released"
                )
            ).scalars()
        )


@pytest.mark.parametrize("hide", ["label", "hold"])
def test_hiding_a_card_takes_it_from_the_agent_and_lifting_gives_nothing_back(
    team: Team, hide: str
) -> None:
    held, assigned = team.card("Its work"), team.card("Its next work")
    given = team.owner.post(f"{P}/tasks/{held}/claim", {"holder": team.agent.id})
    assert given.status_code == 200, given.text
    to = team.owner.patch(f"{P}/tasks/{assigned}", {"assigned_to": team.agent.id})
    assert to.status_code == 200, to.text
    reports = []
    for card_id in (held, assigned):
        if hide == "label":
            hidden = team.owner.patch(f"{P}/tasks/{card_id}", {"label": "security"})
            assert hidden.status_code == 200, hidden.text
        else:
            made = team.outsider.post(
                "/reports",
                {"target": {"type": "card", "id": card_id, "project": "maintainer/maity"},
                 "reason": "spam"},
            )  # fmt: skip
            assert made.status_code == 201, made.text
            reports.append(made.json()["id"])
            done = team.owner.post(f"/admin/reports/{reports[-1]}/resolve", {"action": "hide"})
            assert done.status_code == 200, done.text
    row = _card_row(team.engine, held)
    assert row.claim_holder is None and row.status == "open"
    [released] = _released(team.engine, held)  # as any release: no reason says why
    assert released["holder"] is None and released["reason"] is None
    assert _card_row(team.engine, assigned).assigned_to is None
    _gone(team.agent.get(f"{P}/tasks/{held}"))
    for card_id, report_id in zip((held, assigned), reports or [None, None], strict=True):
        if report_id is None:
            assert team.owner.patch(f"{P}/tasks/{card_id}", {"label": None}).status_code == 200
        else:
            lifted = team.owner.post(f"/admin/reports/{report_id}/resolve", {"action": "dismiss"})
            assert lifted.status_code == 200, lifted.text
    assert _card_row(team.engine, held).claim_holder is None
    assert _card_row(team.engine, assigned).assigned_to is None
    assert team.agent.get(f"{P}/tasks/{held}").status_code == 200  # readable again, not its own


def test_a_member_agent_keeps_a_card_that_becomes_security(team: Team) -> None:
    card_id = team.card("Member's work")
    given = team.owner.post(f"{P}/tasks/{card_id}/claim", {"holder": team.member.id})
    assert given.status_code == 200, given.text
    assert team.owner.patch(f"{P}/tasks/{card_id}", {"label": "security"}).status_code == 200
    assert _card_row(team.engine, card_id).claim_holder is not None
    assert _released(team.engine, card_id) == []


# --- an outsider's joins ------------------------------------------------------------------------


def _first(outsider: flow.Human) -> dict[str, Any]:
    made = _join(outsider)
    assert made.status_code == 201, made.text
    result: dict[str, Any] = made.json()
    return result


def _replacing(outsider: flow.Human, agent: flow.Agent) -> Any:
    """A join that replaces the agent's instance (§6.17): no slot, no instance quota."""
    return outsider.post(JOINS, {"agent": {"id": agent.id}, "replaces": agent.instance})


def _revoke(outsider: flow.Human, join_id: str) -> None:
    gone = outsider.delete(f"{JOINS}/{join_id}")
    assert gone.status_code == 200, gone.text


def _details(answer: Any) -> dict[str, Any]:
    assert answer.status_code == 403, answer.text
    assert answer.json()["error"]["code"] == "forbidden"
    found: dict[str, Any] = answer.json()["error"]["details"]
    return found


def test_an_outsider_creates_at_most_ten_joins_an_hour(
    on: None, make_client: ClientFactory, owner: flow.Human, outsider: flow.Human
) -> None:
    agent = _outside_agent(make_client, owner, outsider)  # the first of the hour
    for _ in range(9):
        made = _replacing(outsider, agent)
        assert made.status_code == 201, made.text
        _revoke(outsider, made.json()["id"])
    refused = _replacing(outsider, agent)
    assert refused.status_code == 429, refused.text
    assert refused.json()["error"]["code"] == "rate_limited"
    assert int(refused.headers["Retry-After"]) > 0


def test_an_outsider_creates_at_most_thirty_joins_a_day(
    on: None,
    make_client: ClientFactory,
    owner: flow.Human,
    outsider: flow.Human,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(joins, "OUTSIDER_JOINS_HOUR", Limiter(1000, 3600, name="test.hour"))
    agent = _outside_agent(make_client, owner, outsider)
    for _ in range(29):
        made = _replacing(outsider, agent)
        assert made.status_code == 201, made.text
        _revoke(outsider, made.json()["id"])
    refused = _replacing(outsider, agent)
    assert refused.status_code == 429, refused.text
    assert int(refused.headers["Retry-After"]) > 0


def test_an_outsider_makes_at_most_five_first_joins_a_day_in_a_project(
    on: None, owner: flow.Human, outsider: flow.Human
) -> None:
    _opt_in(owner)
    for _ in range(5):
        _revoke(outsider, _first(outsider)["id"])
    refused = _join(outsider)
    assert refused.status_code == 429, refused.text
    assert int(refused.headers["Retry-After"]) > 0


def test_an_agent_has_at_most_two_open_joins_also_past_the_slot_check(
    on: None, make_client: ClientFactory, owner: flow.Human, outsider: flow.Human
) -> None:
    agent = _outside_agent(make_client, owner, outsider)  # a member: no slot check
    for _ in range(2):
        assert _replacing(outsider, agent).status_code == 201
    details = _details(_replacing(outsider, agent))
    assert details == {
        "reason": "open_joins_max", "name": "open_joins_max", "limit": 2, "count": 2, "max": 2,
        "scope": "agent", "agent": agent.id, "source": "default",
    }  # fmt: skip
    # A profile with an open first join passes the slot check again: the cap holds there too.
    first = _first(outsider)
    again = outsider.post(JOINS, {"agent": {"id": first["agent_id"]}})
    assert again.status_code == 201, again.text
    details = _details(outsider.post(JOINS, {"agent": {"id": first["agent_id"]}}))
    assert details["scope"] == "agent" and details["agent"] == first["agent_id"]


def test_an_outsider_has_at_most_member_agents_max_plus_two_open_joins(
    on: None, make_client: ClientFactory, owner: flow.Human, outsider: flow.Human
) -> None:
    agent = _outside_agent(make_client, owner, outsider)
    for _ in range(2):
        assert _replacing(outsider, agent).status_code == 201
    second, third = _first(outsider), _first(outsider)  # 3 agents: member_agents_max
    again = outsider.post(JOINS, {"agent": {"id": second["agent_id"]}})
    assert again.status_code == 201, again.text  # 5 open joins
    details = _details(outsider.post(JOINS, {"agent": {"id": third["agent_id"]}}))
    assert details == {
        "reason": "open_joins_max", "name": "open_joins_max", "limit": 5, "count": 5, "max": 5,
        "scope": "member", "member": outsider.id, "source": "default",
    }  # fmt: skip


def test_an_outsiders_join_list_is_its_open_joins_and_the_newest_others(
    on: None, owner: flow.Human, outsider: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(joins, "OUTSIDER_JOINS_LISTED", 2)
    _opt_in(owner)
    closed = []
    for _ in range(3):
        closed.append(_first(outsider)["id"])
        _revoke(outsider, closed[-1])
    still = _first(outsider)["id"]
    listed = [item["id"] for item in outsider.get(JOINS).json()["items"]]
    assert len(listed) == 3 and still in listed  # the open one, and two of the others
    assert set(listed) - {still} < set(closed)
    everything = {item["id"] for item in owner.get(JOINS).json()["items"]}
    assert {still, *closed} <= everything  # an admin's list is not bounded


# --- profiles -----------------------------------------------------------------------------------


def _isolate(owner: flow.Human, agent_id: str) -> None:
    done = owner.post(f"{P}/members/{agent_id}/isolate", {"reason": "checking"})
    assert done.status_code == 200, done.text


def test_the_cascade_keeps_a_profile_with_an_isolated_membership_from_outside(
    team: Team,
) -> None:
    _isolate(team.owner, team.agent.id)
    refused = team.outsider.delete(f"/agents/{team.agent.id}?cascade=true")
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "profile_in_use"
    assert error["details"]["memberships"] == [
        {"project": "maintainer/maity", "member_id": team.agent.id, "trust": "outside",
         "role": "coder", "isolated": True},
    ]  # fmt: skip
    lifted = team.owner.delete(f"{P}/members/{team.agent.id}/isolate")
    assert lifted.status_code == 200, lifted.text
    gone = team.outsider.delete(f"/agents/{team.agent.id}?cascade=true")
    assert gone.status_code == 200, gone.text


def test_the_cascade_removes_a_membership_from_outside_that_is_not_isolated(team: Team) -> None:
    gone = team.outsider.delete(f"/agents/{team.agent.id}?cascade=true")
    assert gone.status_code == 200, gone.text


def test_the_owners_account_deletion_still_removes_an_isolated_membership(team: Team) -> None:
    """The deletion of the owner's account removes the profile as `delete_profile` does,
    the one function `DELETE /agents` and the account's deletion share (§2.9): the cascade's
    refusal is `DELETE /agents`' own."""
    _isolate(team.owner, team.agent.id)
    with events.transaction(team.engine) as conn:
        conn.execute(
            select(t.agent_profile.c.id)
            .where(t.agent_profile.c.id == team.agent.id)
            .with_for_update()
        )
        agents.delete_profile(
            conn,
            team.agent.id,
            actor_in=lambda _project_id: events.Actor(None),
            by=team.outsider.id,
            credential_id=None,
            via=None,
        )
    with team.engine.connect() as conn:
        row = conn.execute(
            select(t.membership.c.active).where(t.membership.c.agent_id == team.agent.id)
        ).one()
    assert row.active is not True


def test_a_human_deletes_at_most_ten_profiles_a_day(
    make_client: ClientFactory, migrated: Engine
) -> None:
    human = flow.human(make_client, migrated, "deleter")
    for n in range(11):
        made = human.post("/agents", {"handle": f"spare-{n}", "display_name": "Spare"})
        assert made.status_code == 201, made.text
        gone = human.delete(f"/agents/{made.json()['id']}")
        if n < 10:
            assert gone.status_code == 200, gone.text
        else:
            assert gone.status_code == 429, gone.text
            assert int(gone.headers["Retry-After"]) > 0


def test_an_exchanged_agent_is_the_outsiders(
    on: None, make_client: ClientFactory, owner: flow.Human, outsider: flow.Human
) -> None:
    """The fixture's agent is one with trust `outside`, which every test above reads as."""
    _opt_in(owner)
    agent = _exchange(make_client, _first(outsider))
    assert owner.get(f"{P}/members/{agent.id}").json()["trust"] == "outside"


def test_credentials_follow_the_project_membership(team: Team) -> None:
    path = f"{P}/members/{team.agent.id}/credentials"
    listed = team.agent.get(path)
    assert listed.status_code == 200
    assert {row["id"] for row in listed.json()["items"]} == {team.agent.credential_id}
    assert team.owner.get(path).status_code == 200
    assert team.member.get(path).status_code == 403
    for principal in (team.member.id, "agt-unlisted"):
        _gone(team.agent.get(f"{P}/members/{principal}/credentials"))


def test_private_avatar_requires_an_ordinary_shared_membership(team: Team) -> None:
    from tests.test_avatars import image, put_agent

    assert put_agent(team.member, image()).status_code == 200
    assert put_agent(team.agent, image()).status_code == 200
    assert team.agent.get(f"/avatars/{team.agent.id}").status_code == 200
    assert team.owner.get(f"/avatars/{team.member.id}").status_code == 200
    assert team.agent.get(f"/avatars/{team.member.id}").status_code == 404
    assert team.member.get(f"/avatars/{team.agent.id}").status_code == 200


def test_outside_policy_closes_request_writes() -> None:
    for path in ("requests", "requests/{request_id}/answer", "requests/{request_id}/claim"):
        assert not access.outside_agent_may_read("POST", f"{access.API_PROJECT}/{path}")
    assert access.outside_agent_may_read("POST", f"{access.API_PROJECT}/tasks")


def test_hour_and_day_quotas_use_exact_windows() -> None:
    assert joins.OUTSIDER_JOINS_HOUR.exact
    assert joins.OUTSIDER_JOINS_DAY.exact
    assert joins.OUTSIDER_FIRST_JOINS_DAY.exact
    assert agents.PROFILE_DELETIONS_DAY.exact


def test_visible_card_events_use_the_readers_current_projected_edges(team: Team) -> None:
    card_id = team.card("Milestone", related=[team.fixed, team.secret])
    assigned = team.owner.post(f"{P}/tasks/{card_id}/claim", {"holder": team.agent.id})
    assert assigned.status_code == 200
    # A public change on a card the agent holds creates an event addressed to it.
    change = team.owner.patch(f"{P}/tasks/{card_id}", {"related": [team.open, team.secret]})
    assert change.status_code == 200
    team.card("Visible child", parent=card_id)
    team.card("Private child", parent=card_id, label="security")
    items = team.agent.get(f"{P}/events", params={"after": 0}).json()["items"]
    payloads = [e["payload"] for e in items if e["subject"] == {"type": "task", "id": card_id}]
    assert any(p.get("related") == [team.open] for p in payloads)
    assert any(p.get("children") == {"open": 1, "total": 1} for p in payloads)
    assert all(team.secret not in (p.get("related") or []) for p in payloads)
    assert team.member.get(f"{P}/tasks/{card_id}").json()["children"]["total"] == 2


def test_authorized_self_hiding_edit_commits_once(team: Team) -> None:
    card_id = _given(team, team.agent, "Assigned work")
    path = f"/api/v1{P}/tasks/{card_id}"
    headers = team.agent.auth | team.agent.key()
    for _ in range(2):
        changed = team.agent.client.patch(path, json={"label": "security"}, headers=headers)
        assert changed.status_code == 204
        assert changed.content == b""
    assert len(_released(team.engine, card_id)) == 1
    current = team.owner.get(f"{P}/tasks/{card_id}").json()
    assert current["label"] == "security"
    assert current["claim"] is None
    assert current["assigned_to"] is None


def test_join_reservations_are_returned_on_rollback(
    on: None, owner: flow.Human, outsider: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity_hub.errors import ApiError

    _opt_in(owner)
    hour = Limiter(1, 3600, name="test.join.rollback", local=True)
    monkeypatch.setattr(joins, "OUTSIDER_JOINS_HOUR", hour)

    def cancelled(*args: Any, **kwargs: Any) -> Any:
        raise ApiError(409, "cancelled", "transaction cancelled")

    with monkeypatch.context() as change:
        change.setattr(joins, "_issue", cancelled)
        assert _join(outsider).status_code == 409
    assert _join(outsider).status_code == 201
    assert hour.blocked(outsider.id) > 0


def test_hidden_card_assignments_are_refused_and_visible_assignments_succeed(team: Team) -> None:
    for card_id in team.hidden:
        _gone(team.owner.post(f"{P}/tasks/{card_id}/assign", {"assignee": team.agent.id}))
        _gone(team.owner.post(f"{P}/tasks/{card_id}/claim", {"holder": team.agent.id}))
        assert _card_row(team.engine, card_id).assigned_to is None
        assert _card_row(team.engine, card_id).claim_holder is None
    good = team.owner.post(f"{P}/tasks/{team.open}/assign", {"assignee": team.agent.id})
    assert good.status_code == 200
    assert good.json()["assigned_to"] == team.agent.id


def test_visible_edge_edit_preserves_other_relations(team: Team) -> None:
    card_id = team.card("Shared work", related=[team.secret])
    assert (
        team.owner.post(f"{P}/tasks/{card_id}/claim", {"holder": team.agent.id}).status_code == 200
    )
    updated = team.agent.patch(f"{P}/tasks/{card_id}", {"related": [team.open]})
    assert updated.status_code == 200
    assert updated.json()["related"] == [team.open]
    assert set(team.owner.get(f"{P}/tasks/{card_id}").json()["related"]) == {team.secret, team.open}


def test_history_fields_follow_the_same_view_as_the_card(team: Team) -> None:
    card_id = team.card("Milestone", parent=team.secret, related=[team.open, team.held])
    assert team.owner.patch(f"{P}/tasks/{card_id}", {"related": [team.fixed]}).status_code == 200

    def entries(reader: Any) -> dict[str, Any]:
        result = reader.get(f"{P}/tasks/{card_id}/history")
        assert result.status_code == 200
        return {item["field"]: item for item in result.json()["items"]}

    outside, ordinary = entries(team.agent), entries(team.member)
    assert outside["created"]["after"]["parent"] is None
    assert outside["created"]["after"]["related"] == [team.open]
    assert outside["related"]["before"] == [team.open]
    assert outside["related"]["after"] == [team.fixed]
    assert ordinary["created"]["after"]["parent"] == team.secret
    assert set(ordinary["related"]["before"]) == {team.open, team.held}


def test_watches_follow_card_visibility(team: Team) -> None:
    watched = team.agent.client.put(f"/api/v1{P}/tasks/{team.open}/watch", headers=team.agent.auth)
    assert watched.status_code == 200
    assert team.agent.delete(f"{P}/tasks/{team.open}/watch").status_code == 200
    for card_id in team.hidden:
        _gone(team.agent.delete(f"{P}/tasks/{card_id}/watch"))
        assert team.member.delete(f"{P}/tasks/{card_id}/watch").status_code == 200


def test_dependency_errors_include_only_visible_card_ids(team: Team) -> None:
    from maity_hub.auth.caller import Caller
    from maity_hub.errors import ApiError

    card_id = team.card("Milestone", depends_on=[team.open, team.secret])
    for who, expected in (
        (team.agent, [team.open]),
        (team.member, sorted([team.open, team.secret])),
    ):
        caller = Caller("agent", "bearer", agent_id=who.id, credential_id=who.credential_id)
        with team.engine.connect() as conn, pytest.raises(ApiError) as refusal:
            mine = access.membership(conn, caller, "maintainer/maity")
            cards.refuse_open_dependencies(conn, card_id, mine)
        assert refusal.value.code == "dependencies_open"
        assert refusal.value.details == {"open": expected}


def test_report_reopening_a_card_uses_the_post_write_visibility(team: Team) -> None:
    from tests.test_own_approvals_gate import OTHER, _done, _policy
    from tests.test_probe import _report

    _policy(team.owner, done_authority="admin")
    card_id = _given(team, team.agent, "Reported work")
    path = f"{P}/tasks/{card_id}"
    assert team.agent.post(path + "/report", _report()).status_code == 200
    assert _done(team.owner, card_id).status_code == 200
    assert team.owner.patch(path, {"label": "security"}).status_code == 200
    body = _report(
        head=OTHER,
        remote_head=OTHER,
        pr={
            "number": 7,
            "url": "https://github.com/acme/maity/pull/7",
            "head": OTHER,
            "state": "open",
        },
    )
    answer = team.agent.post(path + "/report", body)
    assert answer.status_code == 204 and answer.content == b""
    after = team.owner.get(path).json()
    assert after["claim"] is None and after["assigned_to"] is None
    assert after["report"]["head"] == OTHER


def test_takeover_card_read_policy_applies_to_lookups_and_replay(
    team: Team, make_client: ClientFactory
) -> None:
    from maity_hub.auth.caller import Caller
    from maity_hub.routes import takeovers
    from tests.test_takeovers import _held, _open

    card_id = _held(team.owner, team.member)
    other = flow.agent(make_client, team.owner)
    created = _open(other, card_id)
    assert created.status_code == 201
    takeover_id = created.json()["id"]
    _hold(team.engine, team.owner.id, card_id)
    with team.engine.begin() as conn:
        for who, visible in ((team.agent, False), (team.member, True)):
            caller = Caller("agent", "bearer", agent_id=who.id, credential_id=who.credential_id)
            mine = access.membership(conn, caller, "maintainer/maity")
            assert (takeovers._visible_takeover(conn, mine, takeover_id) is not None) == visible
            assert takeovers._may_replay(conn, mine, takeover_id) == visible


@pytest.mark.parametrize("state", ["isolated", "held", "suspended_owner"])
def test_outside_direct_recipients_follow_the_public_member_view(team: Team, state: str) -> None:
    from tests.test_public_lists_cost import _hold as hold_profile

    if state == "held":
        hold_profile(team.engine, team.owner.id, "profile", team.member.id)
    else:
        with team.engine.begin() as conn:
            if state == "isolated":
                conn.execute(
                    update(t.membership)
                    .where(t.membership.c.agent_id == team.member.id)
                    .values(isolated_since=clock.now())
                )
            else:
                conn.execute(
                    update(t.human)
                    .where(t.human.c.id == team.owner.id)
                    .values(suspended_at=clock.now())
                )
    message = {"kind": "message", "type": "notice", "body": "Policy fixture"}
    for recipient in (team.member.id, "agt-000000000000"):
        for suffix in ("", "#aaaa"):
            sent = team.agent.post(f"{P}/events", {**message, "to": recipient + suffix})
            assert sent.status_code == 400
            assert sent.json()["error"]["details"]["fields"] == {"to": "not_a_member"}
    assert team.agent.post(f"{P}/events", {**message, "to": team.agent.id}).status_code == 201
