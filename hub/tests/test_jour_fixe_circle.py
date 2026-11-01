"""docs/api.md §20.1, §20.2, §20.3, §20.5, §20.7, §20.9: a round of an owner's series stays with
its owner; every member opts out and back in; the report list."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, listening
from maity_hub import tables as t
from maity_hub.jourfixe import worker
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_jour_fixe import BASE, ensure_series, listen

STEP = timedelta(minutes=121)  # past the default window of 120 minutes


@pytest.fixture(autouse=True)
def _no_listeners() -> Iterator[None]:
    yield
    listening.reset()


@pytest.fixture
def now() -> list[datetime]:
    moment = [datetime.now(UTC).replace(microsecond=0)]
    clock.set_source(lambda: moment[0])
    return moment


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _kinds(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def _rounds(round_id: str = "", tail: str = "") -> str:
    return f"{BASE}/jour-fixe/rounds{'/' + round_id if round_id else ''}{tail}"


def _member(make_client: ClientFactory, engine: Engine, handle: str) -> flow.Human:
    human = flow.human(make_client, engine, handle)
    with engine.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(engine, project_id, "member", human_id=human.id)
    return human


class Circle:
    """`friend`'s own series: its admin agent `lead` moderates, `worker` answers by name and
    `friend` anonymously; the project's owner is a member who does not read it."""

    def __init__(
        self, owner: flow.Human, make_client: ClientFactory, engine: Engine, now: list[datetime]
    ) -> None:
        self.owner, self.engine, self.now = owner, engine, now
        self.friend = _member(make_client, engine, "friend")
        self.lead = flow.agent(make_client, self.friend)
        with engine.begin() as conn:  # an admin agent of `friend`'s, set by the project's owner
            conn.execute(
                update(t.membership)
                .where(t.membership.c.agent_id == self.lead.id)
                .values(trust="admin")
            )
        self.worker = flow.agent(make_client, self.friend)
        listen(self.lead)
        listen(self.worker)
        made = self.friend.post(
            f"{BASE}/jour-fixe/series",
            {
                "topic": "My agents",
                "circle": "owner",
                "circle_owner": self.friend.id,
                "reason": "t",
            },
        )
        assert made.status_code == 201, made.text
        self.series: str = made.json()["id"]
        granted = self.friend.post(
            f"{BASE}/jour-fixe/series/{self.series}/moderators",
            {"member_id": self.lead.id, "reason": "t"},
        )
        assert granted.status_code == 201, granted.text
        started = self.friend.post(
            f"{BASE}/jour-fixe/series/{self.series}/rounds", {"reason": "look back"}
        )
        assert started.status_code == 201, started.text
        self.id: str = started.json()["id"]
        self.thread: str = started.json()["conversation_id"]

    def tick(self) -> None:
        self.now[0] += STEP
        worker.sweep(self.engine)


@pytest.fixture
def circle(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> Circle:
    return Circle(owner, make_client, migrated, now)


def test_a_round_of_an_owners_series_is_read_only_by_its_circle(circle: Circle) -> None:
    for reader in (circle.friend, circle.lead, circle.worker):
        assert reader.get(_rounds(circle.id)).status_code == 200
    assert circle.owner.get(_rounds(circle.id)).status_code == 404
    assert circle.owner.get(_rounds()).json()["items"] == []
    assert [r["id"] for r in circle.friend.get(_rounds()).json()["items"]] == [circle.id]
    [entry] = circle.owner.get(f"{BASE}/jour-fixe").json()["series"]
    assert "topic" not in entry and "current_round" not in entry
    [entry] = circle.friend.get(f"{BASE}/jour-fixe").json()["series"]
    assert entry["current_round"]["id"] == circle.id
    changed = _kinds(circle.engine, "jour_fixe_series_changed")
    assert changed and all("all" not in e.audience for e in changed)
    assert all(f"member:{circle.owner.id}" in e.audience for e in changed)  # sees it exists
    assert all("topic" not in e.payload for e in changed)
    [opened] = _kinds(circle.engine, "jour_fixe_opened")
    assert "all" not in opened.audience and "trust:owner" not in opened.audience
    [created] = [
        e
        for e in _kinds(circle.engine, "conversation_created")
        if e.conversation_id == circle.thread
    ]
    assert f"member:{circle.friend.id}" in created.audience
    assert "trust:owner" not in created.audience


def test_only_the_circle_owner_reads_the_thread_along(circle: Circle) -> None:
    """§20.5: the circle's owner reads along, not the project's owners."""
    path = f"{BASE}/conversations/{circle.thread}"
    assert circle.owner.get(path).status_code == 404
    seen = circle.friend.get(path)
    assert seen.status_code == 200, seen.text
    # `friend` is invited, so a participant, and the moderator's owner brings nobody in.
    assert seen.json()["access"] == "participant" and seen.json()["observers"] == []


def test_the_circle_owner_reads_the_answers_not_the_admins(circle: Circle) -> None:
    named = circle.worker.post(_rounds(circle.id, "/answers"), {"went_badly": "slow CI"})
    assert named.status_code == 201, named.text
    circle.tick()
    read = circle.friend.get(_rounds(circle.id, "/answers"))
    assert read.status_code == 200 and len(read.json()["items"]) == 1
    assert circle.owner.get(_rounds(circle.id, "/answers")).status_code == 404
    [closed] = _kinds(circle.engine, "jour_fixe_answers_closed")
    assert f"member:{circle.friend.id}" in closed.audience
    assert "trust:owner" not in closed.audience


def _report(circle: Circle) -> Any:
    statement = {
        "title": "CI is slow",
        "summary": "One says so.",
        "items": [{"text": "slow CI", "from": circle.worker.id}],
        "proposals": [{"title": "Cache the venv", "reason": "minutes per run"}],
    }
    stated = circle.lead.post(_rounds(circle.id, "/statement"), {"topics": [statement]})
    assert stated.status_code == 201, stated.text
    circle.tick()
    return circle.lead.post(
        _rounds(circle.id, "/report"),
        {
            "summary": "CI hurts.",
            "findings": [{"topic_id": "t1", "text": "CI is slow."}],
            "proposals": [
                {
                    "title": "Pin the runner image",
                    "reason": "Fewer surprises.",
                    "topic_id": "t1",
                    "triage": "decided",
                    "decision": {
                        "outcome": "reject",
                        "reason": "Not now.",
                        "basis": {
                            "rules_version": 1,
                            "human_id": circle.friend.id,
                            "preferences_version": 0,
                        },
                    },
                },
                {"title": "Cache the venv", "topic_id": "t1", "triage": "to_owner"},
            ],
        },
    )


def test_the_report_stays_with_the_circle_and_goes_to_its_owner(circle: Circle) -> None:
    """§20.6 (b), §20.9: `to_owner` is the circle owner's, the report reaches the circle's
    readers and its recipients, no ticker item."""
    circle.worker.post(_rounds(circle.id, "/answers"), {"went_badly": "slow CI"})
    circle.tick()
    done = _report(circle)
    assert done.status_code == 200, done.text
    [request_id] = done.json()["requests"]
    with circle.engine.connect() as conn:
        asked = conn.execute(select(t.request).where(t.request.c.id == request_id)).one()
        ticker = conn.execute(select(t.event).where(t.event.c.kind == "ticker")).all()
    assert (asked.to_kind, asked.personal) == ("member", False)
    assert circle.friend.get(f"{BASE}/requests/{request_id}").json()["to"] == circle.friend.id
    assert ticker == []
    [created] = [e for e in _kinds(circle.engine, "request_created") if e.subject_id == request_id]
    assert created.audience == [f"member:{circle.friend.id}"]
    [reported] = _kinds(circle.engine, "jour_fixe_reported")
    assert "all" not in reported.audience
    assert f"member:{circle.friend.id}" in reported.audience
    assert reported.payload["series_id"] == circle.series
    assert reported.payload["topic"] == "My agents"
    items = circle.friend.get("/me/notifications").json()["items"]
    [item] = [i for i in items if (i.get("target") or {}).get("type") == "jour_fixe_round"]
    assert item["kind"] == "inbox" and item["title"] == "Jour fixe report: My agents"
    off = _delete(circle.friend, f"{BASE}/jour-fixe/series/{circle.series}/report")
    assert off.json()["report_recipient"] is False
    items = circle.friend.get("/me/notifications").json()["items"]
    assert not [i for i in items if (i.get("target") or {}).get("type") == "jour_fixe_round"]


def test_only_the_circle_owner_decides_as_a_human_in_an_owners_round() -> None:
    from types import SimpleNamespace

    from maity_hub.jourfixe.triage import may_decide

    round_row = SimpleNamespace(config={"circle": "owner", "circle_owner": "hum-x"}, project_id="p")
    human = SimpleNamespace(kind="human", principal_id="hum-y", trust="owner", role="coder")
    assert not may_decide(None, round_row, human)  # type: ignore[arg-type]
    human.principal_id = "hum-x"
    assert may_decide(None, round_row, human)  # type: ignore[arg-type]


# --- opting out and the report list (§20.2) -----------------------------------------------------


def _headers(who: Any) -> dict[str, str]:
    return {"X-CSRF-Token": who.csrf} if isinstance(who, flow.Human) else who.auth


def _put(who: Any, path: str, member: str | None = None) -> Any:
    query = f"?member={member}" if member else ""
    return who.client.put(f"/api/v1{path}{query}", headers=_headers(who))


def _delete(who: Any, path: str, member: str | None = None) -> Any:
    query = f"?member={member}" if member else ""
    return who.client.delete(f"/api/v1{path}{query}", headers=_headers(who))


def test_a_member_opts_out_and_its_owner_for_its_agent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _member(make_client, migrated, "friend")
    agent = flow.agent(make_client, friend)
    sid = ensure_series(owner)
    path = f"{BASE}/jour-fixe/series/{sid}/opt-out"
    out = _put(friend, path)
    assert out.status_code == 200, out.text
    assert out.json()["opted_out"] is True
    assert out.json()["own_agents"] == [
        {"member_id": agent.id, "opted_out": False, "report_recipient": False}
    ]
    for_agent = _put(friend, path, agent.id)
    assert for_agent.json()["own_agents"][0]["opted_out"] is True
    assert _put(owner, path, agent.id).status_code == 403  # not the owner's agent
    seen = owner.get(f"{BASE}/jour-fixe/series").json()["items"][0]
    assert seen["opted_out"] is False and "own_agents" in seen  # nobody else sees it
    back = _delete(agent, path)
    assert back.status_code == 200 and back.json()["opted_out"] is False
    assert "own_agents" not in back.json()


def test_the_report_list_keepers_by_default_and_members_on_request(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _member(make_client, migrated, "friend")
    sid = ensure_series(owner)
    path = f"{BASE}/jour-fixe/series/{sid}/report"
    shown = owner.get(f"{BASE}/jour-fixe/series").json()["items"][0]
    assert shown["report_recipient"] is True
    assert shown["report_recipients"] == [{"member_id": owner.id}]
    on = _put(friend, path)
    assert on.status_code == 200 and on.json()["report_recipient"] is True
    assert "report_recipients" not in on.json()  # only the keepers see the list
    off = _delete(owner, path)
    assert off.json()["report_recipient"] is False
    assert off.json()["report_recipients"] == [{"member_id": friend.id}]
    assert _put(owner, path).json()["report_recipients"] == [
        {"member_id": owner.id},
        {"member_id": friend.id},
    ]


def test_only_a_reader_of_an_owners_rounds_goes_on_its_list(circle: Circle) -> None:
    path = f"{BASE}/jour-fixe/series/{circle.series}/report"
    assert _put(circle.owner, path).status_code == 404  # the admins see only that it exists
    on = _put(circle.friend, path, circle.worker.id)
    assert on.status_code == 200, on.text
    assert on.json()["report_recipients"] == [
        {"member_id": circle.friend.id},
        {"member_id": circle.worker.id},
    ]
    with circle.engine.connect() as conn:
        rows = conn.execute(select(t.jour_fixe_recipient)).all()
    assert [r.receives for r in rows] == [True]


def test_to_owner_is_personal_once_the_circle_owner_left(circle: Circle) -> None:
    """§20.6 (b): a round runs to its end after its owner left; their decision comes as a
    personal request."""
    circle.worker.post(_rounds(circle.id, "/answers"), {"went_badly": "slow CI"})
    circle.tick()
    with circle.engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.human_id == circle.friend.id)
            .values(active=None)
        )
    done = _report(circle)
    assert done.status_code == 200, done.text
    [request_id] = done.json()["requests"]
    with circle.engine.connect() as conn:
        asked = conn.execute(select(t.request).where(t.request.c.id == request_id)).one()
    assert (asked.to_kind, asked.to_human, asked.personal) == ("human", circle.friend.id, True)
    assert circle.friend.get(f"/requests/{request_id}").status_code == 200


def _agent() -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(id=7, agent_id="agt-r", trust="member", role="coder", role_base="coder")


def _row(kind: str, audience: list[str]) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(kind=kind, audience=audience, actor_membership=1, payload={})


def test_the_report_wakes_only_its_agent_recipients() -> None:
    """§20.9: the report wakes each agent on the list at its selected instance, nobody else."""
    from maity_hub.events import wakes

    on_list = _row("jour_fixe_reported", ["all", "member:agt-r", "instance:agt-r#i1"])
    assert wakes(on_list, _agent(), "agt-r", "i1")
    assert not wakes(on_list, _agent(), "agt-r", "i2")
    assert not wakes(_row("jour_fixe_reported", ["all", "member:agt-r"]), _agent(), "agt-r", "i1")


def test_a_skip_wakes_nobody() -> None:
    from maity_hub.events import wakes

    row = _row("jour_fixe_skipped", ["member:agt-r", "instance:agt-r#i1"])
    assert not wakes(row, _agent(), "agt-r", "i1")


def test_a_series_change_wakes_nobody() -> None:
    from maity_hub.events import wakes

    row = _row("jour_fixe_series_changed", ["all", "member:agt-r"])
    assert not wakes(row, _agent(), "agt-r", "i1")


def test_an_owners_round_escapes_the_admins_see_all(circle: Circle) -> None:
    """§20.7: the project's owners read every event, but not an owner's round's: its events
    reach only its readers."""
    circle.worker.post(_rounds(circle.id, "/answers"), {"went_badly": "slow CI"})
    circle.tick()

    def kinds(who: Any) -> set[str]:
        found = who.get(f"{BASE}/events?after=0&limit=100").json()
        items = found.get("events", found.get("items", []))
        return {e["kind"] for e in items if (e.get("payload") or {}).get("round_id") == circle.id}

    assert {"jour_fixe_opened", "jour_fixe_answers_closed"} <= kinds(circle.friend)
    assert kinds(circle.owner) == set()


def test_an_outside_moderators_owner_does_not_read_the_round(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    """§20.5: in an owner's series the owner of a moderator agent from outside the circle
    does not read along; the thread's creation names its round (#975 review)."""
    from tests.test_jour_fixe_moderators import answer as consent

    friend = _member(make_client, migrated, "friend")
    other = _member(make_client, migrated, "other")
    mine, outside = flow.agent(make_client, friend), flow.agent(make_client, other)
    second = flow.agent(make_client, friend)
    for agent in (mine, outside, second):
        listen(agent)
    made = friend.post(
        f"{BASE}/jour-fixe/series",
        {"topic": "Mine", "circle": "owner", "circle_owner": friend.id, "reason": "t"},
    )
    sid = made.json()["id"]
    pending = friend.post(
        f"{BASE}/jour-fixe/series/{sid}/moderators", {"member_id": outside.id, "reason": "t"}
    )
    assert pending.status_code == 202, pending.text
    [request_id] = pending.json()["requests"]
    assert consent(other, request_id, "go").status_code == 200
    started = friend.post(f"{BASE}/jour-fixe/series/{sid}/rounds", {"reason": "look back"})
    assert started.status_code == 201, started.text
    round_id, thread = started.json()["id"], started.json()["conversation_id"]
    assert started.json()["moderator"]["member_id"] == outside.id
    # A message in the thread: the moderator's statement after the answers (dzse at #975).
    assert mine.post(_rounds(round_id, "/answers"), {"went_badly": "slow CI"}).status_code == 201
    now[0] += STEP
    worker.sweep(migrated)
    statement = {"topics": [{"title": "CI", "items": [{"text": "slow CI", "from": mine.id}]}]}
    stated = outside.post(_rounds(round_id, "/statement"), statement)
    assert stated.status_code == 201, stated.text
    assert [e for e in _kinds(migrated, "message") if e.conversation_id == thread]
    assert other.get(f"{BASE}/conversations/{thread}").status_code == 404
    found = other.get(f"{BASE}/events?after=0&limit=100").json()
    items = found.get("events", found.get("items", []))
    payloads = [e.get("payload") or {} for e in items]
    assert not [p for p in payloads if thread in (p.get("id"), p.get("conversation_id"))]
    [created] = [e for e in _kinds(migrated, "conversation_created") if e.conversation_id == thread]
    assert created.payload["jour_fixe"] == {"round_id": round_id}
    assert created.payload["observers"] in ([], [friend.id])
    assert other.id not in created.payload["observers"]


def test_a_round_thread_read_along_without_an_own_agent_has_a_window() -> None:
    """§9.2, §20.5: an observer's window is its agents' earliest join; reading a round's
    thread along without one, the earliest join of anyone in it (#975 review)."""
    from types import SimpleNamespace

    from maity_hub.group_chats import observer_window

    current = [
        SimpleNamespace(agent_id="agt-x", window_after=7),
        SimpleNamespace(agent_id=None, window_after=5),
    ]
    assert observer_window(current, {"agt-x"}) == 7
    assert observer_window(current, set()) == 5
    assert observer_window([], set()) == 0


def test_redacting_an_owners_report_stays_with_the_circle(circle: Circle) -> None:
    """§20.8: the report event's tombstone notice is as private as the report (#975 review)."""
    circle.worker.post(_rounds(circle.id, "/answers"), {"went_badly": "slow CI"})
    circle.tick()
    assert _report(circle).status_code == 200
    redacted = circle.friend.post(
        _rounds(circle.id, "/redact"), {"target": "proposal:r1", "reason": "a secret"}
    )
    assert redacted.status_code == 200, redacted.text
    [reported] = _kinds(circle.engine, "jour_fixe_reported")

    def notices(who: Any) -> list[Any]:
        found = who.get(f"{BASE}/events?after=0&limit=100").json()
        items = found.get("events", found.get("items", []))
        return [
            e
            for e in items
            if e["kind"] == "event_redacted" and (e.get("payload") or {}).get("seq") == reported.seq
        ]

    assert notices(circle.friend)
    assert notices(circle.owner) == []


def test_a_series_moderator_gets_only_the_reports_of_rounds_it_moderated(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    """§20.2, §20.7: the list may hold a moderator of an owner's series; a round's report
    goes to it only when it read that round, as its moderator (#975 review)."""
    from tests.test_jour_fixe_moderators import answer as consent

    other = _member(make_client, migrated, "other")
    outside = flow.agent(make_client, other)
    circle = Circle(owner, make_client, migrated, now)  # the round opens, `lead` moderates
    listen(outside)  # present, so a recipient it would wake
    pending = circle.friend.post(
        f"{BASE}/jour-fixe/series/{circle.series}/moderators",
        {"member_id": outside.id, "reason": "t"},
    )
    [request_id] = pending.json()["requests"]
    assert consent(other, request_id, "go").status_code == 200
    on = _put(outside, f"{BASE}/jour-fixe/series/{circle.series}/report")
    assert on.status_code == 200, on.text
    circle.worker.post(_rounds(circle.id, "/answers"), {"went_badly": "slow CI"})
    circle.tick()
    assert _report(circle).status_code == 200
    [reported] = _kinds(migrated, "jour_fixe_reported")
    assert not [token for token in reported.audience if outside.id in token]


def test_an_owners_round_thread_shows_a_bridge_across_owners_as_observer(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    """§2.3, §20.5: the round's owners are its `circle_owner` alone, and an agent that serves
    a participant across owners reads what it reads, so the thread shows it too (dzse at
    #975). The bridge's connection is written directly: its flow has its own tests."""
    from sqlalchemy import insert

    from maity_hub.ids import new_id

    circle = Circle(owner, make_client, migrated, now)
    other = _member(make_client, migrated, "other")
    helper = flow.agent(make_client, other)
    with circle.engine.begin() as conn:
        ids = dict(
            conn.execute(
                select(t.membership.c.agent_id, t.membership.c.id).where(
                    t.membership.c.agent_id.in_([circle.worker.id, helper.id])
                )
            ).all()
        )
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        conn.execute(
            insert(t.bridge).values(
                id=new_id("bridge"),
                project_id=project_id,
                served=ids[circle.worker.id],
                bridge=ids[helper.id],
                purpose="t",
                cross_owner=True,
                created_by=circle.friend.id,
                created_at=datetime.now(UTC),
            )
        )
    shown = circle.friend.get(f"{BASE}/conversations/{circle.thread}").json()
    assert shown["observers"] == [helper.id]  # `friend` takes part: no owner beside it
    listed = circle.friend.get(f"{BASE}/conversations", params={"observed": True}).json()
    [entry] = [c for c in listed["items"] if c["id"] == circle.thread]
    assert entry["observers"] == [helper.id]
    assert other.get(f"{BASE}/conversations/{circle.thread}").status_code == 404
