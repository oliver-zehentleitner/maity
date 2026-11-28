"""docs/api.md §2.3 "Outside", "What it writes": an agent with trust `outside` writes through a
closed list of the project's routes (`access.OUTSIDE_AGENT_WRITES`), as it reads through one
(`access.OUTSIDE_AGENT_READS`); every other write of the project answers it `not_found` before
its body is read. It links and imports nothing the forge must read for it, it mentions only the
members it reads, a round of the jour fixe never invites it, and no group chat it is put in
lets its owner read along (tsk-25wd170kbf12, the functional leg's findings on #2236)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from sqlalchemy import update

from maity_hub import access, listening, outsiders
from maity_hub import tables as t
from tests import flow
from tests.test_jour_fixe import listen
from tests.test_outside_agent_reads import Team
from tests.test_outside_agent_reads import labels as labels  # noqa: F401  (fixtures)
from tests.test_outside_agent_reads import team as team  # noqa: F401
from tests.test_outside_reads import _app_routes
from tests.test_outsider_join import NOT_FOUND, P
from tests.test_outsider_join import make_client as make_client  # noqa: F401
from tests.test_outsider_join import on as on  # noqa: F401
from tests.test_outsider_join import outsider as outsider  # noqa: F401
from tests.test_outsider_join import owner as owner  # noqa: F401
from tests.test_overview import ISSUE, REPOSITORY, IssueForge, issue
from tests.test_public_lists_cost import _hold as hold_profile


@pytest.fixture(params=["on", "off"])
def switch(request: pytest.FixtureRequest, team: Team, monkeypatch: pytest.MonkeyPatch) -> str:
    """The agent joined while the switch was on; turning it off later removes no membership
    (§3.1), so every refusal here holds in both states."""
    if request.param == "off":
        monkeypatch.setattr(outsiders, "JOINS_ON", False)
    return str(request.param)


@pytest.fixture(autouse=True)
def _no_listeners() -> Any:
    yield
    listening.reset()


def _gone(answer: Any) -> None:
    assert (answer.status_code, answer.json()) == (404, NOT_FOUND), answer.text


def _call(who: flow.Agent, method: str, path: str, body: Any = None) -> Any:
    return who.client.request(method, f"/api/v1{path}", json=body, headers=who.auth | who.key())


def _handle(team: Team, member_id: str) -> str:
    found: str = team.owner.get(f"{P}/members/{member_id}").json()["handle"]
    return found


# --- the closed list ----------------------------------------------------------------------------


def test_every_write_of_the_project_off_the_list_answers_not_found_before_its_body(
    team: Team, switch: str
) -> None:
    """Closed by construction: every project route the app serves that is no read and not in
    `OUTSIDE_AGENT_WRITES`, a route added later included, answers the agent as an outsider,
    before its body or its path's values are judged."""
    project = access.API_PROJECT
    routes = sorted(
        (method, path)
        for method, path in _app_routes(team.agent.client.app)
        if method not in ("GET", "HEAD")
        and (path == project or path.startswith(project + "/"))
        and (method, path) not in access.OUTSIDE_AGENT_WRITES
    )
    assert len(routes) > 60
    for method, path in routes:
        filled = re.sub(
            r"{(\w+)(?::[^}]*)?}",
            lambda m: {"owner": "maintainer", "slug": "maity"}.get(m.group(1), "zz"),
            path,
        )
        answer = team.agent.client.request(
            method, filled, json={"bogus": 1}, headers=team.agent.auth | team.agent.key()
        )
        assert (answer.status_code, answer.json()) == (404, NOT_FOUND), (method, path)


def test_the_list_names_only_writes_the_app_routes() -> None:
    """Every entry is a write of a project route; none is a read, a request write, a jour fixe
    or group chat route, an attachment, the ticker or a link."""
    for method, path in access.OUTSIDE_AGENT_WRITES:
        assert method in ("POST", "PUT", "PATCH", "DELETE"), path
        assert path.startswith(access.API_PROJECT + "/"), path
        for closed in (
            "/requests", "/jour-fixe", "/conversations", "/attachments", "/ticker",
            "/links", "/import", "/restricted",
        ):  # fmt: skip
            assert closed not in path, path


def test_a_member_agent_writes_off_the_list_as_before(team: Team) -> None:
    """The gate is the trust `outside`'s only: an agent with trust `member` of the same role
    reaches the same routes."""
    for method, path, body in (
        ("PATCH", f"{P}/ticker/subscription", {"add": {"follow": {"types": []}}}),
        ("POST", f"{P}/tasks/{team.open}/links", {"kind": "url", "url": "https://example.org/"}),
    ):
        answer = _call(team.member, method, path, body)
        assert answer.status_code in (200, 201), (path, answer.text)


# --- P1a: nothing the forge must read for it ----------------------------------------------------


@pytest.fixture
def forged(team: Team, monkeypatch: pytest.MonkeyPatch) -> IssueForge:
    """The project's repository, private on the forge; its reader answers issue 41."""
    with team.engine.begin() as conn:
        conn.execute(update(t.project).values(repository_url=REPOSITORY))
    found = IssueForge(issue(title="A private plan"))
    monkeypatch.setattr("maity_hub.routes.board.reader_of", lambda _request: found)
    return found


def test_the_import_is_not_found_and_reads_no_issue(
    team: Team, forged: IssueForge, switch: str
) -> None:
    path = f"{P}/tasks/import"
    _gone(team.agent.post(path, {"issue_url": ISSUE}))
    assert forged.asked == []
    made = team.member.post(path, {"issue_url": ISSUE})  # the counter-check
    assert made.status_code == 201, made.text
    assert made.json()["title"] == "A private plan" and forged.asked


def test_a_link_is_not_found_on_its_route_and_a_forge_link_refused_on_a_new_card(
    team: Team, forged: IssueForge, switch: str
) -> None:
    link = {"kind": "issue", "forge_url": ISSUE}
    _gone(team.agent.post(f"{P}/tasks/{team.open}/links", link))
    _gone(team.agent.delete(f"{P}/tasks/{team.open}/links/link-000000000000"))
    refused = team.agent.post(f"{P}/tasks", {"title": "Mine", "links": [link]})
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"reason": "outside_trust", "field": "links"}
    plain = {"kind": "url", "url": "https://example.org/notes"}
    made = team.agent.post(f"{P}/tasks", {"title": "Mine", "links": [plain]})
    assert made.status_code == 201, made.text  # a plain URL is read by nobody
    member = team.member.post(f"{P}/tasks", {"title": "Theirs", "links": [link]})
    assert member.status_code == 201, member.text
    assert team.member.post(f"{P}/tasks/{team.open}/links", link).status_code == 201


# --- P1b: the jour fixe and the group chats -----------------------------------------------------


def _round(team: Team) -> dict[str, Any]:
    listen(team.agent)
    listen(team.member)
    made = team.owner.post(
        f"{P}/jour-fixe/series", {"topic": "How we work", "circle": "all", "reason": "t"}
    )
    assert made.status_code == 201, made.text
    sid = made.json()["id"]
    granted = team.owner.post(
        f"{P}/jour-fixe/series/{sid}/moderators", {"member_id": team.member.id, "reason": "t"}
    )
    assert granted.status_code == 201, granted.text
    started = team.owner.post(f"{P}/jour-fixe/series/{sid}/rounds", {"reason": "look back"})
    assert started.status_code == 201, started.text
    found: dict[str, Any] = started.json()
    return {"series": sid, **found}


def test_a_round_of_circle_all_invites_no_agent_with_trust_outside(team: Team, switch: str) -> None:
    started = _round(team)
    invited = {i["member_id"] for i in started["invited"]}
    assert team.agent.id not in invited
    assert {team.owner.id, team.member.id} <= invited  # the counter-check: the circle is `all`
    assert team.agent.id not in {a["member_id"] for a in started["absent"]}
    thread = team.owner.get(f"{P}/conversations/{started['conversation_id']}").json()
    assert team.agent.id not in {p["member_id"] for p in thread["participants"]}
    assert team.outsider.id not in thread["observers"]
    # Its owner, an outsider, reads neither the round nor its thread.
    _gone(team.outsider.get(f"{P}/jour-fixe/rounds/{started['id']}"))
    _gone(team.outsider.get(f"{P}/conversations/{started['conversation_id']}"))
    _gone(team.outsider.get(f"{P}/conversations/{started['conversation_id']}/messages"))


def test_its_jour_fixe_writes_are_not_found(team: Team, switch: str) -> None:
    started = _round(team)
    series, round_id = started["series"], started["id"]
    for method, path, body in (
        ("PUT", f"{P}/jour-fixe/series/{series}/opt-out", None),
        ("PUT", f"{P}/jour-fixe/series/{series}/report", None),
        ("POST", f"{P}/jour-fixe/series", {"topic": "Mine", "circle": "all", "reason": "t"}),
        ("POST", f"{P}/jour-fixe/rounds/{round_id}/answers", {"went_badly": "nothing"}),
        ("POST", f"{P}/jour-fixe/rounds/{round_id}/posts", {"body": "hello"}),
    ):
        _gone(_call(team.agent, method, path, body))
    opted = _call(team.member, "PUT", f"{P}/jour-fixe/series/{series}/opt-out")
    assert opted.status_code == 200, opted.text  # the counter-check


def test_a_group_chat_it_was_put_in_does_not_open_to_its_owner(team: Team, switch: str) -> None:
    made = team.owner.post(
        f"{P}/conversations", {"title": "Room", "participants": [team.agent.id, team.member.id]}
    )
    assert made.status_code == 201, made.text
    room = made.json()["id"]
    said = team.member.post(f"{P}/conversations/{room}/messages", {"body": "internal"})
    assert said.status_code == 201, said.text
    for tail in ("", "/messages"):
        _gone(team.outsider.get(f"{P}/conversations/{room}{tail}"))
    seen = team.owner.get(f"{P}/conversations/{room}").json()
    assert team.outsider.id not in seen["observers"]
    listed = team.outsider.get(f"{P}/conversations")
    if listed.status_code == 200:
        assert room not in str(listed.json()), listed.text
    # The counter-check: the owner of an agent with trust `member` in it reads along.
    assert team.member.id in {p["member_id"] for p in seen["participants"]}


# --- P2a: mentions only of the members it reads -------------------------------------------------


def test_a_mention_names_only_a_member_it_reads(team: Team, switch: str) -> None:
    hold_profile(team.engine, team.owner.id, "profile", team.member.id)  # hidden from outside
    hidden = _handle(team, team.member.id)
    text = f"cc @{hidden} and @{team.owner.handle}"
    note = team.agent.post(f"{P}/tasks/{team.open}/notes", {"body": text})
    assert note.status_code == 201, note.text
    assert [m["member_id"] for m in note.json()["mentions"]] == [team.owner.id]
    card = team.agent.post(f"{P}/tasks", {"title": "Mine", "body": text})
    assert card.status_code == 201, card.text
    assert [m["member_id"] for m in card.json()["mentions"]] == [team.owner.id]
    said = team.agent.post(
        f"{P}/events", {"kind": "message", "type": "notice", "to": team.agent.id, "body": text}
    )
    assert said.status_code == 201, said.text
    assert [m["member_id"] for m in said.json()["payload"]["mentions"]] == [team.owner.id]
    # The counter-check: a member's agent resolves the same text to both.
    theirs = team.member.post(f"{P}/tasks/{team.open}/notes", {"body": text})
    assert {m["member_id"] for m in theirs.json()["mentions"]} == {team.member.id, team.owner.id}


# --- P2b: what a closed read leaves no write for ------------------------------------------------


def test_an_upload_and_the_ticker_subscription_are_not_found(team: Team, switch: str) -> None:
    upload = team.agent.client.post(
        f"/api/v1{P}/attachments?name=a.txt",
        content=b"hello",
        headers=team.agent.auth | team.agent.key() | {"Content-Type": "text/plain"},
    )
    _gone(upload)
    _gone(_call(team.agent, "PATCH", f"{P}/ticker/subscription", {"add": {}}))
    member = team.member.client.post(
        f"/api/v1{P}/attachments?name=a.txt",
        content=b"hello",
        headers=team.member.auth | team.member.key() | {"Content-Type": "text/plain"},
    )
    assert member.status_code != 404, member.text  # the route answers it (here: not configured)


def test_its_own_work_stays_open(team: Team, switch: str) -> None:
    """What the list keeps: its card's notes, its watch, a message, a release."""
    given = team.owner.post(f"{P}/tasks/{team.open}/claim", {"holder": team.agent.id})
    assert given.status_code == 200, given.text
    assert team.agent.post(f"{P}/tasks/{team.open}/notes", {"body": "on it"}).status_code == 201
    watched = _call(team.agent, "PUT", f"{P}/tasks/{team.open}/watch")
    assert watched.status_code == 200, watched.text
    said = team.agent.post(
        f"{P}/events", {"kind": "message", "type": "notice", "to": team.owner.id, "body": "hi"}
    )
    assert said.status_code == 201, said.text
    released = team.agent.post(f"{P}/tasks/{team.open}/release", {})
    assert released.status_code == 200, released.text
    assert outsiders.JOINS_ON is (switch == "on")
