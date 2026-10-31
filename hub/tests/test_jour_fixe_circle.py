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


def test_the_report_wakes_its_agent_recipients_and_a_change_nobody() -> None:
    """§20.9: the report wakes each agent recipient at its selected instance, nobody else; a
    skip and a series change wake nobody."""
    from types import SimpleNamespace

    from maity_hub.events import wakes

    agent = SimpleNamespace(id=7, agent_id="agt-r", trust="member", role="coder", role_base="coder")
    for kind in ("jour_fixe_series_changed", "jour_fixe_skipped"):
        row = SimpleNamespace(kind=kind, audience=["all", "member:agt-r"], actor_membership=1)
        assert not wakes(row, agent, "agt-r", "i1")
    row = SimpleNamespace(
        kind="jour_fixe_reported",
        audience=["all", "member:agt-r", "instance:agt-r#i1"],
        actor_membership=1,
        payload={},
    )
    assert wakes(row, agent, "agt-r", "i1")
    assert not wakes(row, agent, "agt-r", "i2")
    row.audience = ["all", "member:agt-r"]
    assert not wakes(row, agent, "agt-r", "i1")
