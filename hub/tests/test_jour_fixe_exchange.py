"""docs/api.md §20.5, §20.7, §20.9: the statement, the exchange and the round's thread."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock, events, listening
from maity_hub import tables as t
from maity_hub.jourfixe import worker
from tests import factory, flow
from tests.conftest import ClientFactory

STEP = timedelta(minutes=121)  # past the default window of 120 minutes


@pytest.fixture(autouse=True)
def _no_listeners() -> Iterator[None]:
    yield
    listening._open.clear()


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


def listen(agent: flow.Agent) -> None:
    listening.opened(agent.resume().json()["session"]["id"])


def kinds(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def rounds_path(round_id: str, tail: str = "") -> str:
    return f"/projects/maity/jour-fixe/rounds/{round_id}{tail}"


class Round:
    """A round in its statement step: lead moderates, member answered by name, the
    owner anonymously."""

    def __init__(
        self, owner: flow.Human, make_client: ClientFactory, engine: Engine, now: list[datetime]
    ) -> None:
        self.owner, self.engine, self.now = owner, engine, now
        self.lead = flow.agent(make_client, owner, role="admin")
        self.member = flow.agent(make_client, owner)
        listen(self.lead)
        listen(self.member)
        owner.get("/me")
        started = self.lead.post("/projects/maity/jour-fixe/rounds", {"reason": "look back"})
        assert started.status_code == 201, started.text
        self.id: str = started.json()["id"]
        self.thread: str = started.json()["conversation_id"]
        answered = self.member.post(rounds_path(self.id, "/answers"), {"went_badly": "slow CI"})
        assert answered.status_code == 201, answered.text
        anon = owner.post(rounds_path(self.id, "/answers"), {"would_help": "x", "anonymous": True})
        assert anon.status_code == 201, anon.text
        self.tick()

    def tick(self, by: timedelta = STEP) -> None:
        self.now[0] += by
        worker.sweep(self.engine)

    def get(self) -> dict[str, Any]:
        found: dict[str, Any] = self.owner.get(rounds_path(self.id)).json()
        return found

    def statement(self, who: Any = None, **topic: Any) -> Any:
        body = {
            "title": "CI is slow",
            "summary": "Two say so.",
            "items": [
                {"text": "slow CI", "from": self.member.id},
                {"text": "x", "from": "anonymous"},
            ],
            "proposals": [{"title": "Cache the venv", "reason": "minutes per run"}],
        }
        return (who or self.lead).post(
            rounds_path(self.id, "/statement"), {"topics": [{**body, **topic}]}
        )

    def post(self, who: Any, step: str, **body: Any) -> Any:
        return who.post(
            rounds_path(self.id, "/posts"), {"step": step, "topic_id": "t1", "body": "b", **body}
        )


@pytest.fixture
def round_(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> Round:
    return Round(owner, make_client, migrated, now)


def test_the_round_runs_in_its_own_thread_that_wakes_nobody(round_: Round) -> None:
    thread = round_.owner.get(f"/projects/maity/conversations/{round_.thread}").json()
    assert thread["kind"] == "group" and thread["created_by"] is None
    assert thread["jour_fixe"] == {"round_id": round_.id}
    assert {p["member_id"] for p in thread["participants"]} == {
        round_.lead.id,
        round_.member.id,
        round_.owner.id,
    }
    assert round_.get()["mode"] == "chat"
    direct = round_.owner.post(
        f"/projects/maity/conversations/{round_.thread}/messages", {"body": "hi"}
    )
    assert direct.status_code == 403 and direct.json()["error"]["details"]["reason"] == (
        "round_thread"
    )
    [created] = kinds(round_.engine, "conversation_created")
    with round_.engine.connect() as conn:
        member = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == round_.member.id)
        ).one()
    assert not events.wakes(created, member, round_.member.id)


def test_the_statement_numbers_its_parts_and_opens_the_responses(round_: Round) -> None:
    made = round_.statement()
    assert made.status_code == 201, made.text
    view = made.json()
    [topic] = view["statement"]["topics"]
    assert topic["id"] == "t1" and [i["id"] for i in topic["items"]] == ["t1.i1", "t1.i2"]
    assert topic["proposals"][0]["id"] == "t1.s1" and topic["redaction"] is None
    assert view["status"] == "exchange"
    first, second = view["steps"]
    assert first["kind"] == "statement" and first["closed_at"] is not None
    assert second["kind"] == "response" and second["topics"] == ["t1"]
    assert set(second["eligible"]) == {round_.lead.id, round_.member.id, round_.owner.id}
    [message] = [
        m for m in kinds(round_.engine, "message") if m.payload["jour_fixe"]["step"] == "statement"
    ]
    assert message.conversation_id == round_.thread and view["statement"]["message_seq"] == (
        message.seq
    )
    assert "Cache the venv" in message.payload["body"]
    [opened] = kinds(round_.engine, "jour_fixe_step_opened")
    assert opened.payload["kind"] == "response" and opened.payload["step"] == 2
    assert f"member:{round_.owner.id}" in opened.audience
    assert f"instance:{round_.member.id}#{round_.member.instance}" in opened.audience


def test_only_the_moderator_states_citing_named_answerers_within_the_caps(
    round_: Round,
) -> None:
    other = round_.statement(round_.member)
    assert other.status_code == 403
    assert other.json()["error"]["details"]["reason"] == "not_moderator"
    stranger = round_.statement(items=[{"text": "t", "from": round_.lead.id}])
    assert stranger.json()["error"]["details"]["fields"] == {"items": "not_an_answerer"}
    many = round_.statement(proposals=[{"title": f"p{i}"} for i in range(6)])
    assert many.json()["error"]["details"]["fields"] == {"topics": "too_many_proposals"}
    assert round_.statement().status_code == 201
    again = round_.statement()
    assert again.status_code == 409 and again.json()["error"]["code"] == "jour_fixe_state"


def test_responses_replies_and_the_last_word(round_: Round) -> None:
    round_.statement()
    asked = round_.post(round_.lead, "response", to=[round_.member.id])
    assert asked.status_code == 201, asked.text
    assert asked.json()["id"] == "p1" and asked.json()["to"] == [round_.member.id]
    twice = round_.post(round_.lead, "response")
    assert twice.status_code == 409 and twice.json()["error"]["details"]["step"] == "response"
    early = round_.post(round_.member, "reply", in_reply_to=["p1"])
    assert early.json()["error"]["code"] == "jour_fixe_state"
    round_.tick()
    view = round_.get()
    reply_step = view["steps"][-1]
    assert reply_step["kind"] == "reply" and reply_step["eligible"] == [round_.member.id]
    outsider = round_.post(round_.owner, "reply", in_reply_to=["p1"])
    assert outsider.json()["error"]["details"]["reason"] == "not_eligible"
    blind = round_.post(round_.member, "reply")
    assert blind.json()["error"]["details"]["fields"] == {"in_reply_to": "not_addressed"}
    assert round_.post(round_.member, "reply", in_reply_to=["p1"]).status_code == 201
    round_.tick()
    rejoinder = round_.get()["steps"][-1]
    assert rejoinder["kind"] == "rejoinder" and rejoinder["eligible"] == [round_.lead.id]
    assert round_.post(round_.lead, "rejoinder").status_code == 201
    round_.tick()
    closed = round_.get()
    assert closed["status"] == "reporting" and closed["exchange_closed_at"] is not None
    assert [p["step"] for p in closed["posts"]] == ["response", "reply", "rejoinder"]
    assert "step_n" not in closed["posts"][0]
    [done] = kinds(round_.engine, "jour_fixe_exchange_closed")
    assert f"instance:{round_.lead.id}#{round_.lead.instance}" in done.audience
    thread = round_.owner.get(f"/projects/maity/conversations/{round_.thread}").json()
    assert thread["closed_reason"] == "round_closed"


def test_a_further_step_follows_the_last_one_for_the_members_it_names(round_: Round) -> None:
    round_.statement()
    reason = {"reason": "one more round on CI"}
    early = round_.lead.post(rounds_path(round_.id, "/steps"), reason)
    assert early.status_code == 201, early.text  # step 2 is open: allowed
    pending = round_.lead.post(rounds_path(round_.id, "/steps"), reason)
    assert pending.json()["error"]["code"] == "jour_fixe_state"  # one at a time
    by_member = round_.member.post(rounds_path(round_.id, "/steps"), reason)
    assert by_member.json()["error"]["details"]["reason"] == "not_moderator"
    round_.tick()  # no response addressed anyone: no reply step, the further one opens
    further = round_.get()["steps"][-1]
    assert further["kind"] == "further" and further["reason"] == "one more round on CI"
    assert further["opened_at"] is not None
    assert round_.post(round_.member, "further", to=[round_.lead.id]).status_code == 201
    round_.tick()
    assert round_.get()["status"] == "reporting"
    late = round_.lead.post(rounds_path(round_.id, "/steps"), reason)
    assert late.json()["error"]["code"] == "jour_fixe_state"  # the exchange never reopens


def test_no_statement_in_time_means_no_exchange(round_: Round) -> None:
    round_.tick()
    view = round_.get()
    assert view["status"] == "reporting" and view["statement"] is None
    assert [s["kind"] for s in view["steps"]] == ["statement"]
    assert kinds(round_.engine, "jour_fixe_step_opened") == []
    assert len(kinds(round_.engine, "jour_fixe_exchange_closed")) == 1


def test_a_member_who_left_the_thread_is_no_participant_any_more(round_: Round) -> None:
    left = round_.member.client.delete(
        f"/api/v1/projects/maity/conversations/{round_.thread}/participants/{round_.member.id}",
        headers=round_.member.auth,
    )
    assert left.status_code == 200, left.text
    round_.statement()
    view = round_.get()
    assert round_.member.id not in {p["member_id"] for p in view["participants"]}
    assert round_.member.id not in view["steps"][-1]["eligible"]
    gone = round_.post(round_.member, "response")
    assert gone.json()["error"]["details"]["reason"] == "not_eligible"


def test_an_owner_outside_the_thread_reads_it_along_in_the_events(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    # The agents are another human's: the owner reads along as owner, not as their owner.
    other = flow.human(make_client, migrated, "other")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "admin", human_id=other.id)
    lead = flow.agent(make_client, other, role="admin")
    member = flow.agent(make_client, other)
    now[0] += timedelta(minutes=5)  # the owner's own calls are long past: not online
    listen(lead)
    listen(member)
    round_id = lead.post("/projects/maity/jour-fixe/rounds", {"reason": "r"}).json()["id"]
    member.post(rounds_path(round_id, "/answers"), {"went_well": "ok"})
    now[0] += STEP
    worker.sweep(migrated)
    statement = {"topics": [{"title": "T", "items": [{"text": "ok", "from": member.id}]}]}
    assert lead.post(rounds_path(round_id, "/statement"), statement).status_code == 201
    round_ = owner.get(rounds_path(round_id)).json()
    assert owner.id not in {p["member_id"] for p in round_["participants"]}
    seen = owner.get("/projects/maity/events?after=0&limit=200").json()["items"]
    jour_fixe = [e for e in seen if (e.get("payload") or {}).get("jour_fixe")]
    assert {e["kind"] for e in jour_fixe} >= {"conversation_created", "message"}


def test_redacting_a_round_message_tombstones_the_round_copy(round_: Round) -> None:
    round_.statement()
    post = round_.post(round_.lead, "response", body="the token is s3cret").json()
    for seq in (round_.get()["statement"]["message_seq"], post["message_seq"]):
        done = round_.owner.post(f"/projects/maity/events/{seq}/redact", {"reason": "secret"})
        assert done.status_code == 200, done.text
    view = round_.get()
    [shown] = view["posts"]
    assert shown["body"] is None and shown["redaction"]["reason"] == "secret"
    assert shown["redaction"]["by"] == round_.owner.id
    [topic] = view["statement"]["topics"]
    assert topic["title"] is None and topic["summary"] is None and topic["redaction"]
    assert all(i["text"] is None for i in topic["items"])
    assert topic["proposals"][0]["title"] is None
    assert "s3cret" not in str(view) and "slow CI" not in str(view)
    # The reason as the message's tombstone shows it (§8.5): an agent never reads it.
    for seen in (
        round_.lead.get(rounds_path(round_.id)).json(),
        round_.lead.get("/projects/maity/jour-fixe/rounds").json()["items"][0],
        round_.lead.get("/projects/maity/jour-fixe").json()["current_round"],
    ):
        assert seen["posts"][0]["redaction"]["reason"] is None
        assert seen["posts"][0]["redaction"]["by"] == round_.owner.id
        assert seen["statement"]["topics"][0]["redaction"]["reason"] is None
        assert seen["statement"]["topics"][0]["proposals"][0]["redaction"]["reason"] is None


def test_a_replayed_post_shows_no_redaction_reason(round_: Round) -> None:
    round_.statement()
    path = f"/api/v1{rounds_path(round_.id, '/posts')}"
    body = {"step": "response", "topic_id": "t1", "body": "the token is s3cret"}
    headers = round_.lead.auth | {"Idempotency-Key": "jour-fixe-replay-0001"}
    first = round_.lead.client.post(path, json=body, headers=headers)
    assert first.status_code == 201, first.text
    seq = first.json()["message_seq"]
    round_.owner.post(f"/projects/maity/events/{seq}/redact", {"reason": "private reason"})
    replay = round_.lead.client.post(path, json=body, headers=headers)
    assert replay.status_code == 201, replay.text
    shown = replay.json()
    assert shown["body"] is None and shown["redaction"]["reason"] is None
    assert "private reason" not in replay.text


def test_the_statement_and_posts_keep_their_byte_caps(round_: Round) -> None:
    long_summary = round_.statement(summary="ä" * 1025)  # 2050 bytes, 1025 characters
    assert long_summary.json()["error"]["details"]["fields"] == {"summary": "too_long"}
    long_item = round_.statement(items=[{"text": "ä" * 513, "from": "anonymous"}])
    assert long_item.json()["error"]["details"]["fields"] == {"items": "too_long"}
    assert round_.statement(summary="ä" * 1024).status_code == 201  # 2048 bytes: in
    long_post = round_.post(round_.lead, "response", body="ä" * 2049)
    assert long_post.json()["error"]["details"]["fields"] == {"body": "too_long"}
    assert round_.post(round_.lead, "response", body="ä" * 2048).status_code == 201
