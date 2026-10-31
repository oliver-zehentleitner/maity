"""docs/api.md §20.1–§20.4, §20.7, §20.9: the jour fixe's schedule, rounds, questions and
answers, named and anonymous."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, listening
from maity_hub import tables as t
from maity_hub.jourfixe import redaction, worker
from tests import factory, flow
from tests.conftest import ClientFactory

DAILY = {
    "enabled": True,
    "recurrence": {"freq": "daily"},
    "time": "10:00",
    "timezone": "Europe/Vienna",
}


@pytest.fixture(autouse=True)
def _no_listeners() -> Iterator[None]:
    yield
    listening.reset()


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def listen(agent: flow.Agent) -> str:
    """Resume and hold an events long-poll open: present for the jour fixe (§20.2)."""
    session: str = agent.resume().json()["session"]["id"]
    listening.opened(session)
    return session


def events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


BASE = "/projects/maintainer/maity"


def series_id(who: Any) -> str:
    """The first series the caller sees: the one `team` sets up."""
    items = who.get(f"{BASE}/jour-fixe/series").json()["items"]
    found: str = items[0]["id"]
    return found


def ensure_series(owner: flow.Human, **fields: Any) -> str:
    """A series with `circle: all` kept by the project's admins, made once (§20.1)."""
    items = owner.get(f"{BASE}/jour-fixe/series").json()["items"]
    if items:
        return str(items[0]["id"])
    body = {"topic": "How we work", "circle": "all", "reason": "t", **fields}
    made = owner.post(f"{BASE}/jour-fixe/series", body)
    assert made.status_code == 201, made.text
    return str(made.json()["id"])


def grant(owner: flow.Human, sid: str, member_id: str) -> Any:
    """The right to moderate the series (§20.2): the owner's own agent takes effect at once."""
    return owner.post(
        f"{BASE}/jour-fixe/series/{sid}/moderators", {"member_id": member_id, "reason": "t"}
    )


def start(who: Any, sid: str | None = None) -> Any:
    sid = sid or series_id(who)
    return who.post(f"{BASE}/jour-fixe/series/{sid}/rounds", {"reason": "let us look back"})


def team(owner: flow.Human, make_client: ClientFactory) -> tuple[flow.Agent, flow.Agent]:
    """A lead holding the moderator right of the series and a worker, both listening."""
    lead = flow.agent(make_client, owner, role="admin")
    worker_agent = flow.agent(make_client, owner)
    listen(lead)
    listen(worker_agent)
    sid = ensure_series(owner)
    assert grant(owner, sid, lead.id).status_code == 201
    return lead, worker_agent


def answer(who: Any, round_id: str, **body: Any) -> Any:
    return who.post(f"/projects/maintainer/maity/jour-fixe/rounds/{round_id}/answers", body)


# --- the schedule (§20.1) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "fields"),
    [
        (
            {
                "enabled": True,
                "time": "10:00",
                "timezone": "Europe/Vienna",
                "recurrence": {"freq": "weekly"},
            },
            {"policy.jour_fixe.recurrence.weekdays": "required"},
        ),
        ({**DAILY, "timezone": "Mars/Olympus"}, {"policy.jour_fixe.timezone": "unknown_timezone"}),
        (
            {"enabled": True, "timezone": "Europe/Vienna", "recurrence": {"freq": "daily"}},
            {"policy.jour_fixe.time": "required"},
        ),
        (
            {**DAILY, "recurrence": {"freq": "daily", "weekdays": ["mon"]}},
            {"policy.jour_fixe.recurrence.weekdays": "not_for_freq"},
        ),
        (
            {**DAILY, "recurrence": {"freq": "monthly"}},
            {"policy.jour_fixe.recurrence.month_day": "one_of"},
        ),
        (
            {**DAILY, "answer_window_minutes": 10},
            {"policy.jour_fixe.answer_window_minutes": "out_of_range"},
        ),
        ({**DAILY, "moderator": "agt-nobody"}, {"policy.jour_fixe.moderator": "not_a_member"}),
    ],
)
def test_the_schedule_the_contract_refuses_is_invalid(
    owner: flow.Human, change: dict[str, Any], fields: dict[str, str]
) -> None:
    response = owner.patch(
        "/projects/maintainer/maity", {"policy": {"jour_fixe": change}, "reason": "t"}
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == fields


def test_a_schedule_is_stored_whole_and_kept_by_a_preset(owner: flow.Human) -> None:
    response = owner.patch(
        "/projects/maintainer/maity", {"policy": {"jour_fixe": DAILY}, "reason": "t"}
    )
    assert response.status_code == 200, response.text
    stored = response.json()["policy"]["jour_fixe"]
    assert stored["answer_window_minutes"] == 120 and stored["moderator"] == "admin_agent"
    kept = owner.patch(
        "/projects/maintainer/maity", {"policy": {"preset": "solo"}, "reason": "t"}
    ).json()
    assert kept["policy"]["jour_fixe"] == stored
    overview = owner.get("/projects/maintainer/maity/jour-fixe").json()
    assert overview["policy"] == stored and overview["next_at"] is not None


# --- opening a round (§20.1–§20.3) ---------------------------------------------------------------


def test_a_manual_start_invites_the_present_and_asks_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    lead, member = team(owner, make_client)
    offline = flow.agent(make_client, owner)  # never resumed: offline, not available
    deaf = flow.agent(make_client, owner)
    deaf.resume()  # a session, but no long-poll: no listening instance
    owner.get("/me")  # the human is online
    response = start(lead)
    assert response.status_code == 201, response.text
    round_ = response.json()
    assert round_["status"] == "answering" and round_["trigger"] == "manual"
    assert round_["moderator"]["member_id"] == lead.id
    assert {i["member_id"] for i in round_["invited"]} == {lead.id, member.id, owner.id}
    reasons = {a["member_id"]: a["absent_reason"] for a in round_["absent"]}
    assert reasons == {offline.id: "not_available", deaf.id: "no_listening_instance"}
    [opened] = events(migrated, "jour_fixe_opened")
    assert f"instance:{member.id}#{member.instance}" in opened.audience
    assert f"member:{owner.id}" in opened.audience and "trust:owner" in opened.audience
    woken = member.get(f"/projects/maintainer/maity/events?after={opened.seq - 1}&wait=1").json()
    assert [e["kind"] for e in woken["items"]][:1] == ["jour_fixe_opened"]  # its instance
    assert "Your answer goes to the moderator only." in opened.payload["questions"]
    assert "3. What would help" in opened.payload["questions"]
    again = start(lead)
    assert again.status_code == 409 and again.json()["error"]["code"] == "jour_fixe_open"


def test_a_round_needs_a_moderator_and_two_present_members(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    member = flow.agent(make_client, owner)
    listen(member)
    owner.get("/me")
    nobody = start(owner)
    assert nobody.status_code == 409 and nobody.json()["error"]["code"] == "no_moderator"
    lead = flow.agent(make_client, owner, role="admin")
    listening.reset()
    listen(lead)  # the moderator alone: the human declares itself away
    owner.post("/me/limit", {"until": clock.rfc3339(clock.now() + timedelta(hours=1))})
    lonely = start(owner)
    assert lonely.json()["error"]["code"] == "too_few"


def test_only_owners_and_admins_start_and_at_most_two_a_day(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    lead, member = team(owner, make_client)
    refused = start(member)
    assert refused.status_code == 403
    with migrated.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        for n in range(2):
            conn.execute(
                insert(t.jour_fixe_round).values(
                    id=f"jfx-old{n}",
                    project_id=project_id,
                    status="reported",
                    trigger="manual",
                    mode="message",
                    scheduled_for=clock.now(),
                    steps=[],
                    invited=[],
                    absent=[],
                    answers_received=0,
                    posts=[],
                    created_at=clock.now(),
                )
            )
    assert start(lead).status_code == 429


# --- answers (§20.3, §20.4) ----------------------------------------------------------------------


def test_named_and_anonymous_answers_and_who_reads_them(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    lead, member = team(owner, make_client)
    third = flow.agent(make_client, owner)
    listen(third)
    owner.get("/me")
    round_id = start(lead).json()["id"]
    named = answer(member, round_id, went_well="Reviews were quick.")
    assert named.status_code == 201, named.text
    assert named.json()["anonymous"] is False and named.json()["id"].startswith("jfa-")
    anonymous = answer(third, round_id, went_badly="Too many wakes.", anonymous=True)
    assert anonymous.status_code == 201, anonymous.text
    assert anonymous.json() == {"round_id": round_id, "anonymous": True}
    with migrated.connect() as conn:
        stored = conn.execute(
            select(t.jour_fixe_answer).where(t.jour_fixe_answer.c.anonymous.is_(True))
        ).one()
    assert stored.author is None  # nothing names its author
    again = answer(member, round_id, would_help="more")
    assert again.status_code == 409 and again.json()["error"]["code"] == "jour_fixe_answered"
    empty = answer(lead, round_id, went_well="  ")
    assert empty.json()["error"]["details"]["fields"] == {"answer": "empty"}
    path = f"/projects/maintainer/maity/jour-fixe/rounds/{round_id}/answers"
    seen = lead.get(path).json()["items"]  # the moderator
    assert len(seen) == 2
    assert all("author" not in a for a in seen if a["anonymous"])
    assert owner.get(path).status_code == 200  # a human owner
    assert member.get(path).status_code == 404  # anyone else
    own = third.get(path + "?mine=true").json()["items"]
    assert [a["went_badly"] for a in own] == ["Too many wakes."]
    assert events(migrated, "jour_fixe_answer") == []  # no event per answer


def test_a_proxy_with_trust_admin_does_not_read_the_answers(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    lead, member = team(owner, make_client)
    owner.get("/me")
    round_id = start(lead).json()["id"]
    answer(member, round_id, went_well="named")
    answer(lead, round_id, went_badly="hidden", anonymous=True)
    admin = flow.human(make_client, migrated, "second-admin")
    proxy = flow.human(make_client, migrated, "the-proxy")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, role="admin", human_id=admin.id)
    factory.membership(migrated, project_id, role="proxy", human_id=proxy.id)
    path = f"/projects/maintainer/maity/jour-fixe/rounds/{round_id}/answers"
    assert admin.get(path).status_code == 200  # the admin team reads
    assert proxy.get(path).status_code == 404  # a proxy, though of trust admin, does not
    with migrated.connect() as conn:
        row = conn.execute(select(t.jour_fixe_round)).one()
        stored = conn.execute(select(t.jour_fixe_answer)).first()
        addressed = redaction._answer_readers(conn, row, stored)
    assert f"member:{admin.id}" in addressed
    assert f"member:{proxy.id}" not in addressed


def test_an_anonymous_answer_withdrawn_leaves_nothing_but_the_tag(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    lead, member = team(owner, make_client)
    round_id = start(lead).json()["id"]
    answer(member, round_id, went_badly="secret-ish", anonymous=True)
    gone = member.client.delete(
        f"/api/v1/projects/maintainer/maity/jour-fixe/rounds/{round_id}/answers/mine",
        headers=member.auth,
    )
    assert gone.status_code == 200 and gone.json() == {"round_id": round_id, "withdrawn": True}
    with migrated.connect() as conn:
        assert conn.execute(select(t.jour_fixe_answer)).first() is None
    again = answer(member, round_id, went_well="second try")
    assert again.json()["error"]["code"] == "jour_fixe_answered"


def test_a_stranger_to_the_round_answers_nothing(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    lead, member = team(owner, make_client)
    round_id = start(lead).json()["id"]
    late = flow.agent(make_client, owner)
    listen(late)
    refused = answer(late, round_id, went_well="hi")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "not_participant"


# --- the window closes, the clock runs (§20.1, §20.4) --------------------------------------------


@pytest.fixture
def now() -> list[datetime]:
    moment = [datetime.now(UTC).replace(microsecond=0)]
    clock.set_source(lambda: moment[0])
    return moment


def test_at_the_window_close_the_key_and_tags_die_and_the_moderator_is_woken(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    lead, member = team(owner, make_client)
    round_id = start(lead).json()["id"]
    answer(member, round_id, went_well="ok", anonymous=True)
    now[0] += timedelta(minutes=121)
    path = f"/projects/maintainer/maity/jour-fixe/rounds/{round_id}/answers?mine=true"
    assert member.get(path).json()["items"] == []  # past the deadline, before the sweep
    worker.sweep(migrated)
    with migrated.connect() as conn:
        row = conn.execute(select(t.jour_fixe_round)).one()
        assert row.status == "statement" and row.tag_key is None
        assert conn.execute(select(t.jour_fixe_tag)).first() is None
        assert conn.execute(select(t.jour_fixe_answer.c.tag)).scalar() is None
    [closed] = events(migrated, "jour_fixe_answers_closed")
    assert closed.audience == [f"instance:{lead.id}#{lead.instance}", "trust:owner"]
    assert closed.payload["answers_received"] == 1
    assert member.get(path).json()["items"] == []  # nothing links it to its author now
    late = answer(member, round_id, went_well="late")
    assert late.json()["error"]["code"] in ("jour_fixe_state", "jour_fixe_answered")


def test_the_close_wakes_the_moderator_where_it_listens_now_or_nobody(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    lead, member = team(owner, make_client)
    start(lead)
    listening.reset()  # the instance recorded at the opening stopped listening
    now[0] += timedelta(minutes=121)
    worker.sweep(migrated)
    [closed] = events(migrated, "jour_fixe_answers_closed")
    assert closed.audience == ["trust:owner"]  # no fallback to the stale instance


def test_minutes_online_count_working_calls_not_only_long_polls(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    from maity_hub.jourfixe import rounds

    working = flow.agent(make_client, owner, role="admin")
    working.resume()  # a call just now, no long-poll open: online (§5.3)
    idle = flow.agent(make_client, owner, role="admin")
    idle.resume()
    with migrated.begin() as conn:
        member_of = dict(conn.execute(select(t.membership.c.agent_id, t.membership.c.id)).all())
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.membership_id == member_of[idle.id])
            .values(last_seen_at=now[0] - timedelta(minutes=5))
        )
        rounds.record_presence(conn, now[0])
        counted = set(conn.execute(select(t.presence_minute.c.membership_id)).scalars())
    assert counted == {member_of[working.id]}


def test_the_schedule_opens_skips_and_records_a_missed_slot(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    lead, member = team(owner, make_client)
    # UTC: a day later is the same wall-clock time, whatever DST does in Vienna.
    daily_utc = {**DAILY, "timezone": "UTC"}
    owner.patch("/projects/maintainer/maity", {"policy": {"jour_fixe": daily_utc}, "reason": "t"})
    next_at = datetime.fromisoformat(
        owner.get("/projects/maintainer/maity/jour-fixe").json()["next_at"]
    )
    now[0] = next_at + timedelta(seconds=30)
    lead.get("/me")
    member.get("/me")
    worker.sweep(migrated)
    with migrated.connect() as conn:
        opened = conn.execute(select(t.jour_fixe_round)).all()
    assert [(r.status, r.trigger) for r in opened] == [("answering", "schedule")]
    # The next day the round is still open: skipped with round_open.
    now[0] = next_at + timedelta(days=1, seconds=30)
    worker.sweep(migrated)
    skipped = events(migrated, "jour_fixe_skipped")
    assert [e.payload["skip_reason"] for e in skipped] == ["round_open"]
    # The hub sleeps three days: one record with the slots it missed.
    with migrated.begin() as conn:
        conn.execute(update(t.jour_fixe_round).values(status="reported"))
    now[0] = next_at + timedelta(days=4, hours=2)
    worker.sweep(migrated)
    missed = events(migrated, "jour_fixe_skipped")[-1].payload
    assert (missed["status"], missed["skip_reason"], missed["missed_slots"]) == (
        "missed",
        "hub_down",
        3,
    )


# --- the moderator order and the observer (§20.2, §20.7) -----------------------------------------


def test_admin_agents_order_themselves(owner: flow.Human, make_client: ClientFactory) -> None:
    first = flow.agent(make_client, owner, role="admin")
    second = flow.agent(make_client, owner, role="admin")
    member = flow.agent(make_client, owner)
    path = "/projects/maintainer/maity/jour-fixe/moderators"
    set_ = second.client.put(
        f"/api/v1{path}",
        json={"order": [second.id], "reason": "I have time"},
        headers=second.auth | second.key(),
    )
    assert set_.status_code == 200, set_.text
    assert set_.json()["moderators"][0] == second.id and first.id in set_.json()["moderators"]
    wrong = second.client.put(
        f"/api/v1{path}",
        json={"order": [member.id], "reason": "x"},
        headers=second.auth | second.key(),
    )
    assert wrong.json()["error"]["details"]["fields"] == {"order": "not_admin_agent"}
    refused = member.client.put(
        f"/api/v1{path}", json={"order": None, "reason": "x"}, headers=member.auth | member.key()
    )
    assert refused.status_code == 403


def test_an_agents_owner_outside_the_project_reads_the_minimal_round(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    lead, member = team(owner, make_client)
    outsider = flow.human(make_client, migrated, handle="outsider")
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == member.id)
            .values(owner_id=outsider.id)
        )
    round_id = start(lead).json()["id"]
    seen = outsider.get(f"/projects/maintainer/maity/jour-fixe/rounds/{round_id}")
    assert seen.status_code == 200, seen.text
    shown = seen.json()
    for hidden in ("invited", "absent", "config", "moderator", "answers_received", "steps"):
        assert hidden not in shown
    assert outsider.get("/projects/maintainer/maity/jour-fixe").status_code == 404


# --- the series on the wall clock (§20.1) ------------------------------------------------------


def test_the_series_follows_the_wall_clock_through_dst_and_month_ends() -> None:
    from datetime import date

    from maity_hub.jourfixe import schedule

    vienna = {**DAILY, "time": "02:30"}
    gap = schedule.slots_between(
        schedule.filled(vienna),
        datetime(2027, 3, 27, 0, tzinfo=UTC),
        datetime(2027, 3, 29, 0, tzinfo=UTC),
        date(2027, 1, 1),
    )
    # 27 March 02:30 CET; 28 March has no 02:30 (the gap): the first minute after it.
    assert gap == [
        datetime(2027, 3, 27, 1, 30, tzinfo=UTC),
        datetime(2027, 3, 28, 1, 0, tzinfo=UTC),
    ]
    twice = schedule.slots_between(
        schedule.filled(vienna),
        datetime(2026, 10, 25, 0, 0, tzinfo=UTC),
        datetime(2026, 10, 25, 4, 0, tzinfo=UTC),
        date(2026, 1, 1),
    )
    assert twice == [datetime(2026, 10, 25, 0, 30, tzinfo=UTC)]  # its first occurrence
    month_end = schedule.filled(
        {**DAILY, "timezone": "UTC", "recurrence": {"freq": "monthly", "month_day": 31}}
    )
    feb = schedule.slots_between(
        month_end,
        datetime(2027, 2, 1, tzinfo=UTC),
        datetime(2027, 3, 1, tzinfo=UTC),
        date(2027, 1, 1),
    )
    assert feb == [datetime(2027, 2, 28, 10, 0, tzinfo=UTC)]  # the month's last day
    biweekly = schedule.filled(
        {
            **DAILY,
            "timezone": "UTC",
            "recurrence": {"freq": "weekly", "interval": 2, "weekdays": ["mon"]},
        }
    )
    mondays = schedule.slots_between(
        biweekly,
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 12, 1, tzinfo=UTC),
        date(2026, 11, 2),
    )
    assert [m.day for m in mondays] == [2, 16, 30]


def test_a_replay_answers_only_a_member(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from tests import factory

    lead, member = team(owner, make_client)
    other = flow.human(make_client, migrated, "other")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "admin", human_id=other.id)
    other.get("/me")
    headers = {"X-CSRF-Token": other.csrf, "Idempotency-Key": "jour-fixe-start-replay-1"}
    path = "/api/v1/projects/maintainer/maity/jour-fixe/rounds"
    first = other.client.post(path, json={"reason": "r"}, headers=headers)
    assert first.status_code == 201, first.text
    removed = owner.delete(f"/projects/maintainer/maity/members/{other.id}")
    assert removed.status_code == 200, removed.text
    replay = other.client.post(path, json={"reason": "r"}, headers=headers)
    assert replay.status_code == 404, replay.text  # no way around access (§1.5)
