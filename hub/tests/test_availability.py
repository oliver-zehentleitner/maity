"""docs/api.md §6.12: availability per member, the limit, the policy; the coordinator
seats of §6.1 and their reset on removal (§6.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import availability, clock
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_tasks import task


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


@pytest.fixture
def now() -> list[datetime]:
    moment = [datetime.now(UTC).replace(microsecond=0)]
    clock.set_source(lambda: moment[0])
    return moment


def z(moment: datetime) -> str:
    return clock.rfc3339(moment)


def events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def member(who: Any, member_id: str) -> dict[str, Any]:
    response = who.get(f"/projects/maity/members/{member_id}")
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def other_human(make_client: ClientFactory, engine: Engine, role: str = "member") -> flow.Human:
    with engine.connect() as conn:
        project_id = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "maity")
        ).scalar_one()
    human = flow.human(make_client, engine, handle="second")
    factory.membership(engine, project_id, role=role, human_id=human.id)
    return human


# --- the view -----------------------------------------------------------------------------


def test_a_new_member_is_available_with_the_default_policy(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume(harness="Claude Code")
    view = member(owner, agent.id)
    assert view["availability"]["state"] == "available"
    assert set(view["availability"]) == {"state", "since"}
    assert view["availability_policy"] == {
        "on_unavailable": "wait",
        "substitutes": [],
        "grace_minutes": 15,
    }
    assert view["covered_by"] is None and view["covering"] == []


def test_first_resume_stores_a_silent_baseline_and_repeated_resume_keeps_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    agent = flow.agent(make_client, owner)

    def stored() -> Any:
        with migrated.connect() as conn:
            return conn.execute(
                select(t.membership).where(t.membership.c.agent_id == agent.id)
            ).one()

    assert stored().availability_state is None
    agent.resume()
    baseline = stored()
    assert baseline.availability_state == "available"
    assert baseline.availability_since == now[0]
    assert baseline.outage_since is None
    assert events(migrated, "member_availability_changed") == []
    now[0] += timedelta(seconds=1)
    agent.resume()
    assert stored().availability_since == baseline.availability_since
    assert events(migrated, "member_availability_changed") == []


def test_an_agent_without_a_session_is_offline_and_a_paused_one_paused(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    assert member(owner, agent.id)["availability"]["state"] == "offline"
    agent.resume()
    paused = owner.patch(f"/projects/maity/members/{agent.id}", {"paused": {"reason": "hold"}})
    assert paused.status_code == 200, paused.text
    assert paused.json()["availability"]["state"] == "paused"


# --- an agent's limit ------------------------------------------------------------------------


def test_an_agent_declares_its_limit_and_its_next_resume_clears_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    agent = flow.agent(make_client, owner, reports_to=owner.id)
    agent.resume(harness="Claude Code")
    until = now[0] + timedelta(hours=3)
    response = agent.post("/me/limit", {"until": z(until), "reason": "quota"})
    assert response.status_code == 200, response.text
    assert response.json()["availability"] == {
        "state": "limited",
        "since": z(now[0]),
        "until": z(until),
        "source": "self",
        "harness": "Claude Code",  # the session's, when the body names none
        "reason": "quota",
    }
    started = events(migrated, "member_availability_changed")
    assert len(started) == 1
    assert started[0].payload == {
        "member_id": agent.id,
        "state": "limited",
        "since": z(now[0]),
        "until": z(until),
        "source": "self",
        "cover": None,  # within the grace
    }
    # Its boss and its human (the same here), the admins, the coordinator (role:admin).
    assert started[0].audience == [f"member:{owner.id}", "role:admin"]

    now[0] += timedelta(minutes=5)
    agent.resume(harness="Claude Code")
    assert member(owner, agent.id)["availability"] == {"state": "available", "since": z(now[0])}
    ended = events(migrated, "member_availability_changed")
    assert len(ended) == 2 and ended[1].payload["state"] == "available"
    assert ended[1].payload["cover"] is None  # the outage ended within the grace


def test_until_is_rfc_3339_with_an_offset_within_seven_days(
    owner: flow.Human, make_client: ClientFactory, now: list[datetime]
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()

    def refused(until: Any) -> Any:
        response = agent.post("/me/limit", {"until": until})
        assert response.status_code == 400, response.text
        return response.json()["error"]["details"]["fields"]["until"]

    soon = now[0] + timedelta(hours=1)
    assert refused(soon.strftime("%Y-%m-%dT%H:%M:%S")) == "format"  # no offset
    assert refused("in an hour") == "format"
    assert refused(soon.strftime("%Y-%m-%d")) == "format"
    assert refused(z(now[0] - timedelta(minutes=1))) == "past"
    assert refused(z(now[0] + timedelta(days=7, seconds=1))) == "too_far"
    # Another offset is converted and stored in UTC.
    plus_two = (soon + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+02:00")
    response = agent.post("/me/limit", {"until": plus_two})
    assert response.status_code == 200, response.text
    assert response.json()["availability"]["until"] == z(soon)


def test_an_agent_names_no_show_reason_in_and_clears_with_null(
    owner: flow.Human, make_client: ClientFactory, now: list[datetime]
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    response = agent.post(
        "/me/limit", {"until": z(now[0] + timedelta(hours=1)), "show_reason_in": ["maity"]}
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"show_reason_in": "humans_only"}
    assert agent.post("/me/limit", {"until": z(now[0] + timedelta(hours=1))}).status_code == 200
    cleared = agent.post("/me/limit", {"until": None})
    assert cleared.status_code == 200
    assert cleared.json()["availability"]["state"] == "available"


def test_a_limit_holds_the_leases_to_until_plus_grace_for_at_most_a_day(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    card = task(owner)
    assert agent.post(f"/projects/maity/tasks/{card['id']}/claim", {}).status_code == 200

    def lease() -> datetime:
        with migrated.connect() as conn:
            found: datetime = conn.execute(
                select(t.card.c.lease_until).where(t.card.c.id == card["id"])
            ).scalar_one()
            return found

    until = now[0] + timedelta(hours=5)
    agent.post("/me/limit", {"until": z(until)})
    assert lease() == until + timedelta(minutes=15)
    # A new limit in the same outage: the bound counts from the outage's start.
    now[0] += timedelta(hours=1)
    agent.post("/me/limit", {"until": z(now[0] + timedelta(days=6))})
    assert lease() == now[0] - timedelta(hours=1) + availability.LEASE_HOLD


def test_a_limit_passes_and_the_coordinator_is_told(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    coordinator = flow.agent(make_client, owner, role="admin")
    coordinator.resume()
    agent = flow.agent(make_client, owner)
    agent.resume(harness="Claude Code")
    until = now[0] + timedelta(hours=2)
    agent.post("/me/limit", {"until": z(until)})
    # The agent's session goes away while it waits for its reset.
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.credential_id == agent.credential_id)
            .values(live=None, ended_at=now[0])
        )
    now[0] = until + timedelta(seconds=1)
    availability.sweep(migrated)
    ended = events(migrated, "member_limit_ended")
    assert len(ended) == 1
    assert ended[0].payload == {"member_id": agent.id, "until": z(until), "harness": "Claude Code"}
    assert ended[0].audience == ["role:admin", f"member:{owner.id}"]
    view = member(owner, agent.id)
    assert view["availability"]["state"] == "offline"  # still out: no new announcement
    about_it = [
        e
        for e in events(migrated, "member_availability_changed")
        if e.payload["member_id"] == agent.id
    ]
    assert len(about_it) == 1
    availability.sweep(migrated)  # a second sweep finds nothing to say
    assert len(events(migrated, "member_limit_ended")) == 1


# --- a human's limit and the owner's absence ------------------------------------------------


def test_a_humans_reason_shows_only_where_they_choose(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    flow.project(owner, slug="other")
    agent = flow.agent(make_client, owner)
    agent.resume()
    until = now[0] + timedelta(days=2)
    response = owner.post(
        "/me/limit", {"until": z(until), "reason": "dentist", "show_reason_in": ["other"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["member"]["limit"] == {
        "until": z(until),
        "since": z(now[0]),
        "reason": "dentist",
        "show_reason_in": ["other"],
    }
    shown = member(agent, owner.id)["availability"]
    assert shown == {"state": "limited", "since": z(now[0]), "until": z(until), "source": "self"}
    other = owner.get(f"/projects/other/members/{owner.id}").json()["availability"]
    assert other["reason"] == "dentist"
    # Every membership of the account had an outage.
    assert len(events(migrated, "member_availability_changed")) == 2
    assert owner.post("/me/limit", {"until": z(until), "harness": "x"}).status_code == 400
    refused = owner.post("/me/limit", {"until": z(until), "show_reason_in": ["nowhere"]})
    assert refused.json()["error"]["details"]["fields"] == {"show_reason_in": "not_a_member"}
    owner.post("/me/limit", {"until": None})
    assert member(agent, owner.id)["availability"]["state"] == "available"
    assert owner.get("/me").json()["member"]["limit"] is None


def test_the_owners_absence_makes_the_owner_limited_and_ends_within_90_days(
    owner: flow.Human, make_client: ClientFactory, now: list[datetime]
) -> None:
    until = now[0] + timedelta(days=10)
    too_far = owner.patch(
        "/projects/maity",
        {"absence": {"until": z(now[0] + timedelta(days=91)), "scope": "away"}},
    )
    assert too_far.status_code == 400
    assert too_far.json()["error"]["details"]["fields"] == {"absence": "too_far"}
    set_ = owner.patch("/projects/maity", {"absence": {"until": z(until), "scope": "away"}})
    assert set_.status_code == 200, set_.text
    shown = member(owner, owner.id)["availability"]
    assert shown == {"state": "limited", "since": z(now[0]), "until": z(until), "source": "absence"}
    # A stored limit wins over the absence.
    owner.post("/me/limit", {"until": z(now[0] + timedelta(hours=1))})
    assert member(owner, owner.id)["availability"]["source"] == "self"


# --- the policy -------------------------------------------------------------------------------


def test_an_admin_sets_a_members_policy(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    covered = flow.agent(make_client, owner)
    cover = flow.agent(make_client, owner)
    response = owner.patch(
        f"/projects/maity/members/{covered.id}",
        {
            "availability_policy": {
                "on_unavailable": "substitute",
                "substitutes": [cover.id, "role:reviewer", owner.id],
            }
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["availability_policy"] == {
        "on_unavailable": "substitute",
        "substitutes": [cover.id, "role:reviewer", owner.id],
        "grace_minutes": 15,
    }
    updated = events(migrated, "member_updated")[-1]
    assert updated.payload["changed"] == ["availability_policy"]
    # Fields not named keep their value.
    owner.patch(
        f"/projects/maity/members/{covered.id}", {"availability_policy": {"grace_minutes": 0}}
    )
    assert member(owner, covered.id)["availability_policy"]["on_unavailable"] == "substitute"


@pytest.mark.parametrize(
    ("policy", "field", "code"),
    [
        ({"on_unavailable": "panic"}, "on_unavailable", "unknown"),
        ({"on_unavailable": "substitute"}, "substitutes", "required"),
        ({"grace_minutes": 1441}, "grace_minutes", "out_of_range"),
        ({"substitutes": ["SELF"]}, "substitutes", "self"),
        ({"substitutes": ["agt-nobody"]}, "substitutes", "not_a_member"),
        ({"substitutes": ["role:boss"]}, "substitutes", "unknown_role"),
    ],
)
def test_a_bad_policy_is_invalid(
    owner: flow.Human,
    make_client: ClientFactory,
    policy: dict[str, Any],
    field: str,
    code: str,
) -> None:
    agent = flow.agent(make_client, owner)
    if policy.get("substitutes") == ["SELF"]:
        policy = {"substitutes": [agent.id]}
    response = owner.patch(f"/projects/maity/members/{agent.id}", {"availability_policy": policy})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == {f"availability_policy.{field}": code}


def test_a_human_sets_their_own_policy_and_no_agent_decides_for_a_human(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    second = other_human(make_client, migrated)
    agent = flow.agent(make_client, owner)
    agent.resume()
    own = second.patch(
        f"/projects/maity/members/{second.id}",
        {"availability_policy": {"on_unavailable": "substitute", "substitutes": [agent.id]}},
    )
    assert own.status_code == 200, own.text
    # members:admin for anything else, as before.
    assert (
        second.patch(f"/projects/maity/members/{second.id}", {"areas": ["web/"]}).status_code == 403
    )
    assert (
        second.patch(
            f"/projects/maity/members/{agent.id}", {"availability_policy": {"grace_minutes": 5}}
        ).status_code
        == 403
    )
    # An agent learns first that this is a human's call (§2.3).
    for target, body in (
        (second.id, {"grace_minutes": 5}),
        (agent.id, {"on_unavailable": "substitute", "substitutes": [owner.id]}),
    ):
        refused = agent.patch(f"/projects/maity/members/{target}", {"availability_policy": body})
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["details"]["reason"] == "humans_only"


def test_removing_a_substitute_takes_it_off_every_list(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    covered = flow.agent(make_client, owner)
    cover = flow.agent(make_client, owner)
    owner.patch(
        f"/projects/maity/members/{covered.id}",
        {"availability_policy": {"on_unavailable": "substitute", "substitutes": [cover.id]}},
    )
    assert owner.delete(f"/projects/maity/members/{cover.id}").status_code == 200
    assert member(owner, covered.id)["availability_policy"] == {
        "on_unavailable": "wait",  # an empty list with substitute is invalid
        "substitutes": [],
        "grace_minutes": 15,
    }
    assert events(migrated, "member_updated")[-1].payload["changed"] == ["availability_policy"]


# --- the coordinator seats (§6.1) -------------------------------------------------------------


def test_the_coordinator_seats_are_policy_fields_kept_by_a_preset(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    lead = flow.agent(make_client, owner, role="admin")
    worker = flow.agent(make_client, owner)
    policy = owner.get("/projects/maity").json()["policy"]
    assert policy["coordinator"] == "role:admin" and policy["coordinator_substitute"] is None

    def refused(change: dict[str, Any]) -> Any:
        response = owner.patch("/projects/maity", {"policy": change, "reason": "test"})
        assert response.status_code == 400, response.text
        return response.json()["error"]["details"]["fields"]

    assert refused({"coordinator": owner.id}) == {"policy.coordinator": "not_an_agent_member"}
    assert refused({"coordinator_substitute": worker.id}) == {
        "policy.coordinator_substitute": "not_an_agent_admin"
    }
    response = owner.patch(
        "/projects/maity",
        {"policy": {"coordinator": worker.id, "coordinator_substitute": lead.id}, "reason": "t"},
    )
    assert response.status_code == 200, response.text
    kept = owner.patch("/projects/maity", {"policy": {"preset": "solo"}, "reason": "t"}).json()
    assert kept["policy"]["coordinator"] == worker.id
    assert kept["policy"]["coordinator_substitute"] == lead.id
    # Removing them resets both seats in one policy_changed.
    owner.delete(f"/projects/maity/members/{worker.id}")
    owner.delete(f"/projects/maity/members/{lead.id}")
    policy = owner.get("/projects/maity").json()["policy"]
    assert policy["coordinator"] == "role:admin" and policy["coordinator_substitute"] is None
    reset = [
        e for e in events(migrated, "policy_changed") if e.payload["reason"] == "member_removed"
    ]
    assert [
        (e.payload["new"]["coordinator"], e.payload["new"]["coordinator_substitute"]) for e in reset
    ] == [("role:admin", lead.id), ("role:admin", None)]


def test_the_coordinator_going_out_also_tells_the_owners(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    lead = flow.agent(make_client, owner, role="admin")
    lead.resume()
    lead.post("/me/limit", {"until": z(now[0] + timedelta(hours=1))})
    changed = events(migrated, "member_availability_changed")[-1]
    assert changed.audience == [f"member:{owner.id}", "role:admin", "role:owner"]


# --- a runner's rate limit (§15.7) ------------------------------------------------------------


def test_a_runners_rate_limit_is_the_agents_limit_until_the_next_report(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from tests.test_placements import REPOSITORY, Setup, placed, report
    from tests.test_runner_stream import attach, hello
    from tests.test_runners import paired

    human = flow.human(make_client, migrated)
    flow.project(human, repository={"url": REPOSITORY})
    runner = paired(make_client, human)
    attach(human, runner)
    runner_client = make_client()
    assert hello(runner_client, runner).status_code == 200
    s = Setup(human, runner, runner_client, flow.agent(make_client, human), migrated)
    s.agent.resume()  # the run the runner started
    placement = placed(s)
    assert report(s, placement, 1).status_code == 200
    retry_at = clock.now().replace(microsecond=0) + timedelta(hours=4)
    missing = report(s, placement, 2, state="rate_limited", reason="quota")
    assert missing.json()["error"]["details"]["fields"] == {
        "retry_at": "required_with_rate_limited"
    }
    far = report(
        s,
        placement,
        2,
        state="rate_limited",
        reason="quota",
        retry_at=z(clock.now() + timedelta(days=8)),
    )
    assert far.json()["error"]["details"]["fields"] == {"retry_at": "too_far"}
    limited = report(
        s,
        placement,
        2,
        state="rate_limited",
        reason="quota",
        detail="reset_unknown",
        exit_code=1,
        retry_at=z(retry_at),
    )
    assert limited.status_code == 200, limited.text
    shown = member(s.owner, s.agent.id)["availability"]
    assert shown["state"] == "limited"
    assert (shown["until"], shown["source"], shown["harness"], shown["reason"]) == (
        z(retry_at),
        "runner",
        "claude-code",
        "quota",
    )
    changed = events(migrated, "member_availability_changed")
    assert changed[-1].actor_runner_id == s.runner.id
    assert report(s, placement, 3, state="starting").status_code == 200
    assert member(s.owner, s.agent.id)["availability"]["state"] != "limited"
    # The limit passing under a runner is the runner's restart: no member_limit_ended.
    report(s, placement, 4, state="rate_limited", reason="quota", retry_at=z(retry_at))
    clock.set_source(lambda: retry_at + timedelta(seconds=1))
    availability.sweep(migrated)
    assert events(migrated, "member_limit_ended") == []


# --- review of #262 -------------------------------------------------------------------------


def _lease(engine: Engine, card_id: str) -> datetime:
    with engine.connect() as conn:
        found: datetime = conn.execute(
            select(t.card.c.lease_until).where(t.card.c.id == card_id)
        ).scalar_one()
        return found


def test_an_ordinary_call_never_shortens_a_limits_hold(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    card = task(owner)
    agent.post(f"/projects/maity/tasks/{card['id']}/claim", {})
    until = now[0] + timedelta(hours=5)
    agent.post("/me/limit", {"until": z(until)})
    held = until + timedelta(minutes=15)
    assert _lease(migrated, card["id"]) == held
    assert agent.get("/me").status_code == 200  # a call that renews leases
    assert _lease(migrated, card["id"]) == held


def test_renewals_and_new_limits_never_pass_the_outages_24_hours(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    card = task(owner)
    agent.post(f"/projects/maity/tasks/{card['id']}/claim", {})
    start = now[0]
    agent.post("/me/limit", {"until": z(start + timedelta(days=6))})
    cap = start + availability.LEASE_HOLD
    assert _lease(migrated, card["id"]) == cap
    now[0] = start + timedelta(hours=23)
    agent.post("/me/limit", {"until": z(now[0] + timedelta(days=6))})  # renews, then holds
    assert _lease(migrated, card["id"]) == cap


def test_a_limit_renewed_after_the_expiry_read_it_is_not_cleared(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    agent.post("/me/limit", {"until": z(now[0] + timedelta(hours=1))})
    now[0] += timedelta(hours=1, seconds=1)
    later = now[0] + timedelta(hours=2)
    with migrated.begin() as conn:
        project = conn.execute(select(t.project)).one()
        [due] = availability.due_limits(conn, project.id)
        # A renewal lands between the read and the clearing.
        conn.execute(
            update(t.membership).where(t.membership.c.id == due.id).values(limit_until=later)
        )
        assert availability.end_limit(conn, project, due) is False
        stored = conn.execute(
            select(t.membership.c.limit_until).where(t.membership.c.id == due.id)
        ).scalar_one()
    assert stored == later
    assert events(migrated, "member_limit_ended") == []


def test_a_pause_on_top_of_a_limit_keeps_its_cap_and_a_pause_alone_holds_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    card = task(owner)
    agent.post(f"/projects/maity/tasks/{card['id']}/claim", {})
    start = now[0]
    agent.post("/me/limit", {"until": z(start + timedelta(days=6))})
    cap = start + availability.LEASE_HOLD
    owner.patch(f"/projects/maity/members/{agent.id}", {"paused": {"reason": "hold"}})
    now[0] = start + timedelta(hours=23)
    agent.post("/me/limit", {"until": z(now[0] + timedelta(days=6))})
    assert _lease(migrated, card["id"]) == cap
    # Without the limit, the pause alone: an ordinary renewal, no hold.
    agent.post("/me/limit", {"until": None})
    assert agent.get("/me").status_code == 200
    assert _lease(migrated, card["id"]) == now[0] + timedelta(seconds=7200)


def test_an_admin_agent_sets_a_members_policy_and_asks_for_a_reviewers(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    lead = flow.agent(make_client, owner, role="admin")
    worker = flow.agent(make_client, owner)
    reviewer = flow.agent(make_client, owner, role="reviewer")
    body = {"availability_policy": {"on_unavailable": "substitute", "substitutes": [lead.id]}}
    direct = lead.patch(f"/projects/maity/members/{worker.id}", body)
    assert direct.status_code == 200, direct.text
    assert direct.json()["availability_policy"]["substitutes"] == [lead.id]
    asked = lead.patch(f"/projects/maity/members/{reviewer.id}", body)
    assert asked.status_code == 202, asked.text
    assert asked.json()["title"] == f"Change cover for {asked.json()['title'].split()[-1]}"
    assert asked.json()["class"] == "consent"
    # Its own policy is not an admin agent's to set.
    assert lead.patch(f"/projects/maity/members/{lead.id}", body).status_code == 403


def test_a_cover_proposal_whose_substitute_left_does_not_apply_at_go(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    lead = flow.agent(make_client, owner, role="admin")
    reviewer = flow.agent(make_client, owner, role="reviewer")
    stand_in = flow.agent(make_client, owner)
    body = {"availability_policy": {"on_unavailable": "substitute", "substitutes": [stand_in.id]}}
    asked = lead.patch(f"/projects/maity/members/{reviewer.id}", body)
    assert asked.status_code == 202, asked.text
    assert owner.delete(f"/projects/maity/members/{stand_in.id}").status_code == 200
    go = owner.post(f"/projects/maity/requests/{asked.json()['id']}/answer", {"reply_id": "go"})
    assert go.status_code == 400, go.text
    assert go.json()["error"]["details"]["fields"] == {
        "availability_policy.substitutes": "not_a_member"
    }
    still = owner.get(f"/projects/maity/requests/{asked.json()['id']}").json()
    assert still["status"] == "open"
    assert member(owner, reviewer.id)["availability_policy"]["on_unavailable"] == "wait"


def test_seat_resets_name_the_humans_who_decide(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    covered = flow.agent(make_client, owner)
    cover = flow.agent(make_client, owner)
    owner.patch(
        f"/projects/maity/members/{covered.id}",
        {"availability_policy": {"on_unavailable": "substitute", "substitutes": [cover.id]}},
    )
    owner.delete(f"/projects/maity/members/{cover.id}")
    reset = [e for e in events(migrated, "member_updated") if e.payload.get("changed")][-1]
    assert reset.audience == ["all", f"member:{owner.id}"]


def test_a_state_never_stored_reads_the_same_since_on_every_read(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    """An agent that never resumed has no announced state; its `since` is its joining,
    never the time of the read, so two reads (and a repeated removal) agree."""
    agent = flow.agent(make_client, owner)
    with migrated.connect() as conn:
        joined = conn.execute(
            select(t.membership.c.joined_at).where(t.membership.c.agent_id == agent.id)
        ).scalar_one()
    first = member(owner, agent.id)["availability"]
    now[0] += timedelta(minutes=1)
    second = member(owner, agent.id)["availability"]
    assert first == second == {"state": "offline", "since": z(joined)}


def test_one_removal_resets_every_policy_seat_in_one_policy_changed(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The arbiter seat and the coordinator seat named the same agent: one event (§6.2)."""
    flow.agent(make_client, owner, role="admin")  # an admin stays: the arbiter goes to role
    worker = flow.agent(make_client, owner)
    response = owner.patch(
        "/projects/maity",
        {"policy": {"coordinator": worker.id, "contract_arbiter": worker.id}, "reason": "t"},
    )
    assert response.status_code == 200, response.text
    owner.delete(f"/projects/maity/members/{worker.id}")
    reset = [
        e for e in events(migrated, "policy_changed") if e.payload["reason"] == "member_removed"
    ]
    assert len(reset) == 1
    new = reset[0].payload["new"]
    assert (new["coordinator"], new["contract_arbiter"]) == ("role:admin", "role:admin")
    assert f"member:{owner.id}" in reset[0].audience
