"""docs/api.md §6.22, §6.1, §8.2: the swarm page, its counters and the public projection."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, listening, swarm
from maity_hub import tables as t
from maity_hub.ids import new_id
from maity_hub.ratelimit import Limiter
from maity_hub.routes import badges as badge_routes
from tests import factory, flow
from tests.conftest import ClientFactory

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fresh() -> Iterator[None]:
    swarm.CACHE.clear()
    clock.set_source(lambda: NOW)
    yield
    listening._open.clear()
    swarm.CACHE.clear()


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


@pytest.fixture
def project_id(owner: flow.Human, migrated: Engine) -> str:
    with migrated.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def membership_of(engine: Engine, principal: str) -> int:
    with engine.connect() as conn:
        found: int = conn.execute(
            select(t.membership.c.id).where(
                (t.membership.c.agent_id == principal) | (t.membership.c.human_id == principal)
            )
        ).scalar_one()
    return found


def card(engine: Engine, project_id: str, creator: int, **values: Any) -> str:
    return factory.card(engine, project_id, creator, **values)


def done(engine: Engine, project_id: str, creator: int, holder: int | None, at: datetime) -> str:
    return card(
        engine, project_id, creator, status="done", claim_holder=holder, closed_at=at,
        updated_at=at,
    )  # fmt: skip


def event(
    engine: Engine, project_id: str, kind: str, at: datetime, task: str, payload: Any
) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(t.event).values(
                project_id=project_id,
                kind=kind,
                at=at,
                subject_type="task",
                subject_id=task,
                audience=["all"],
                payload=payload,
                redacted=False,
            )
        )


def history(
    engine: Engine, card_id: str, actor: int, before: str, after: str, at: datetime, **more: Any
) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(t.card_history).values(
                id=new_id("history"), card_id=card_id, at=at, actor_membership=actor,
                field="status", before=before, after=after, redacted=False, **more,
            )
        )  # fmt: skip


def page(who: Any, days: int = 30) -> dict[str, Any]:
    response = who.get(f"/projects/maintainer/maity/swarm?days={days}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def row(found: dict[str, Any], member_id: str) -> dict[str, Any]:
    return next(m for m in found["members"] if m["member_id"] == member_id)


def test_live_is_read_now_with_presence_and_holdings(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, project_id: str
) -> None:
    agent = flow.agent(make_client, owner)
    listening.opened(agent.resume().json()["session"]["id"])
    creator = membership_of(migrated, owner.id)
    held = card(
        migrated, project_id, creator, status="in_progress",
        claim_holder=membership_of(migrated, agent.id), claim_since=NOW - timedelta(hours=1),
    )  # fmt: skip
    found = page(owner)
    assert found["live_at"] == "2026-10-25T12:00:00Z" and found["window_days"] == 30
    shown = next(m for m in found["live"] if m["member_id"] == agent.id)
    assert shown["online"] is True and shown["instances_online"] == 1
    assert shown["holding"] == [
        {"task_id": held, "title": "A card", "since": "2026-10-25T11:00:00Z"}
    ]
    assert {m["member_id"] for m in found["live"]} == {owner.id, agent.id}  # humans too
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == held).values(status="done"))
    again = next(m for m in page(owner)["live"] if m["member_id"] == agent.id)
    assert again["holding"] == []  # never cached


def test_cards_done_go_to_the_last_holder_and_the_rest_to_the_totals(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, project_id: str
) -> None:
    agent = flow.agent(make_client, owner)
    gone = flow.agent(make_client, owner)
    creator = membership_of(migrated, owner.id)
    mine = membership_of(migrated, agent.id)
    done(migrated, project_id, creator, mine, NOW - timedelta(days=1))
    done(migrated, project_id, creator, None, NOW - timedelta(days=2))  # no holder
    done(migrated, project_id, creator, membership_of(migrated, gone.id), NOW)
    done(migrated, project_id, creator, mine, NOW - timedelta(days=40))  # before the window
    owner.delete(f"/projects/maintainer/maity/members/{gone.id}")
    found = page(owner)
    assert row(found, agent.id)["cards_done"] == 1
    assert found["totals"]["cards_done"] == 3
    per_day = found["totals"]["cards_done_per_day"]
    assert len(per_day) == 30 and per_day[-1] == {"date": "2026-10-25", "count": 1}
    assert sum(d["count"] for d in per_day) == 3 and per_day[0]["count"] == 0


def test_reviews_come_from_history_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, project_id: str
) -> None:
    agent = flow.agent(make_client, owner)
    creator = membership_of(migrated, owner.id)
    reviewer = membership_of(migrated, agent.id)
    reviewed = card(migrated, project_id, creator)
    history(migrated, reviewed, reviewer, "in_progress", "review", NOW - timedelta(days=9))
    history(migrated, reviewed, reviewer, "review", "done", NOW - timedelta(days=1))
    history(migrated, reviewed, reviewer, "review", "in_progress", NOW - timedelta(days=2))
    history(migrated, reviewed, reviewer, "review", "done", NOW, redaction={"x": 1})
    with migrated.begin() as conn:  # a redacted entry is not counted
        conn.execute(update(t.card_history).where(t.card_history.c.at == NOW).values(redacted=True))
    found = page(owner)
    assert row(found, agent.id)["reviews_given"] == 2
    assert found["totals"]["reviews_given"] == 2
    assert found["coverage"] == {"reviews_since": "2026-10-16"}


def test_without_any_history_the_reviews_are_unknown(owner: flow.Human) -> None:
    found = page(owner)
    assert found["totals"]["reviews_given"] is None and found["coverage"]["reviews_since"] is None


def test_a_pull_request_counts_once_by_its_first_merged_observation(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, project_id: str
) -> None:
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    creator = membership_of(migrated, owner.id)
    first = card(migrated, project_id, creator, claim_holder=membership_of(migrated, a.id))
    second = card(migrated, project_id, creator, claim_holder=membership_of(migrated, b.id))
    old = card(migrated, project_id, creator, claim_holder=membership_of(migrated, a.id))
    url = "https://github.com/oliver-zehentleitner/maity/pull/12"
    merged = {
        "new": {"found": True, "title": "x", "state": "merged"},
        "forge_url": url,
        "public": True,
    }
    for task, at in ((first, NOW - timedelta(days=3)), (second, NOW - timedelta(days=2))):
        event(migrated, project_id, "link_observed", at, task, {**merged, "task_id": task})
    early = "https://github.com/oliver-zehentleitner/maity/pull/3"
    event(migrated, project_id, "link_observed", NOW - timedelta(days=60), old,
          {**merged, "forge_url": early, "task_id": old})  # fmt: skip
    event(migrated, project_id, "link_observed", NOW - timedelta(days=1), old,
          {**merged, "forge_url": early, "task_id": old})  # fmt: skip
    found = page(owner)
    assert found["totals"]["prs_merged"] == 1  # #12 once; #3 was first merged before the window
    assert row(found, a.id)["prs_merged"] == 1 and row(found, b.id)["prs_merged"] == 1


@pytest.mark.parametrize("public", [False, None])
def test_a_merge_not_read_as_public_is_not_counted(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    project_id: str,
    public: bool | None,
) -> None:
    """§11.4: data read while the repository was private, or before the hub said, never
    reaches the page without sign-in, not even as a count."""
    a = flow.agent(make_client, owner)
    creator = membership_of(migrated, owner.id)
    task = card(migrated, project_id, creator, claim_holder=membership_of(migrated, a.id))
    payload: dict[str, Any] = {
        "new": {"found": True, "title": "secret", "state": "merged"},
        "forge_url": "https://github.com/oliver-zehentleitner/maity/pull/12",
        "task_id": task,
    }
    if public is not None:
        payload["public"] = public
    event(migrated, project_id, "link_observed", NOW - timedelta(days=1), task, payload)
    assert page(owner)["totals"]["prs_merged"] == 0


def test_the_medians_pool_durations_and_need_three_samples(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, project_id: str
) -> None:
    agent = flow.agent(make_client, owner)
    creator = membership_of(migrated, owner.id)
    mine = membership_of(migrated, agent.id)
    for minutes in (30, 60, 90):
        closed = NOW - timedelta(hours=1)
        task = done(migrated, project_id, creator, mine, closed)
        event(
            migrated, project_id, "task_claimed", closed - timedelta(minutes=minutes * 2), task, {}
        )
        event(migrated, project_id, "task_reported", closed - timedelta(minutes=minutes), task,
              {"status_before": "in_progress", "status_after": "review"})  # fmt: skip
    # Some card history exists, so the review numbers are known (the coverage rule, §16.6).
    history(migrated, card(migrated, project_id, creator), creator, "open", "open",
            NOW - timedelta(days=20))  # fmt: skip
    refresh = done(migrated, project_id, creator, mine, NOW - timedelta(hours=1))
    event(
        migrated,
        project_id,
        "task_reported",
        NOW - timedelta(hours=2),
        refresh,
        {"status_before": "review", "status_after": "review"},
    )  # a refresh: no entry
    legacy = done(migrated, project_id, creator, mine, NOW - timedelta(hours=1))
    event(migrated, project_id, "task_reported", NOW - timedelta(hours=2), legacy, {})
    found = page(owner)
    assert row(found, agent.id)["review_to_done_median_seconds"] == 3600
    assert row(found, agent.id)["claim_to_done_median_seconds"] == 7200
    assert found["totals"]["review_to_done_median_seconds"] == 3600
    owner_row = row(found, owner.id)
    assert owner_row["claim_to_done_median_seconds"] is None  # fewer than three samples


def test_the_window_part_is_kept_for_an_hour(
    owner: flow.Human, migrated: Engine, project_id: str
) -> None:
    creator = membership_of(migrated, owner.id)
    first = page(owner)
    done(migrated, project_id, creator, None, NOW)
    assert page(owner)["totals"]["cards_done"] == first["totals"]["cards_done"] == 0
    later = NOW + timedelta(hours=1, seconds=1)
    clock.set_source(lambda: later)
    assert page(owner)["totals"]["cards_done"] == 1


def test_task_reported_carries_the_persisted_status_on_both_sides(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    created = owner.post(
        "/projects/maintainer/maity/tasks", {"title": "x", "status": "open"}
    ).json()
    path = f"/projects/maintainer/maity/tasks/{created['id']}"
    assert agent.post(f"{path}/claim", {}).status_code == 200
    from tests.test_tasks import _report

    reported = agent.post(f"{path}/report", _report())
    assert reported.status_code == 200, reported.text
    with migrated.connect() as conn:
        payload = conn.execute(
            select(t.event.c.payload).where(t.event.c.kind == "task_reported")
        ).scalar_one()
    assert payload["status_before"] == "in_progress" and payload["status_after"] == "review"


# --- the public page -------------------------------------------------------------------------


def public(client: Any, slug: str = "maity", **headers: str) -> Any:
    return client.get(f"/api/v1/swarm/maintainer/{slug}", headers=headers)


def test_the_policy_is_checked_before_any_etag(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    visitor = make_client()
    off = public(visitor, **{"If-None-Match": "*"})
    assert off.status_code == 404 and "etag" not in off.headers
    assert public(visitor, "nope").status_code == 404
    switched = owner.patch(
        "/projects/maintainer/maity", {"policy": {"swarm_public": "on"}, "reason": "show"}
    )
    assert switched.status_code == 200, switched.text
    on = public(visitor)
    assert on.status_code == 200 and on.headers["cache-control"] == "public, max-age=60"
    assert "live_at" not in on.json() and on.json()["as_of"].endswith(":00Z")
    later = NOW + timedelta(seconds=30)
    clock.set_source(lambda: later)
    assert public(visitor).headers["etag"] == on.headers["etag"]  # stable within the minute
    assert public(visitor, **{"If-None-Match": on.headers["etag"]}).status_code == 304
    owner.patch("/projects/maintainer/maity", {"state": "archived", "reason": "done"})
    closed = public(visitor, **{"If-None-Match": on.headers["etag"]})
    assert closed.status_code == 404 and "etag" not in closed.headers


def test_the_public_page_shows_agents_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, project_id: str
) -> None:
    agent = flow.agent(make_client, owner)
    creator = membership_of(migrated, owner.id)
    done(migrated, project_id, creator, membership_of(migrated, agent.id), NOW)
    done(migrated, project_id, creator, creator, NOW)  # the human's: nowhere public
    done(migrated, project_id, creator, None, NOW)  # nobody's: not in the agents' totals
    owner.patch("/projects/maintainer/maity", {"policy": {"swarm_public": "on"}, "reason": "show"})
    handle = owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()["handle"]
    body = public(make_client()).json()
    assert [m["handle"] for m in body["live"]] == [handle]
    assert set(body["live"][0]) == {
        "handle", "name", "display_name", "online", "instances_online", "holding_count"
    }  # fmt: skip
    owner_handle = owner.get(f"/projects/maintainer/maity/members/{owner.id}").json()["handle"]
    assert body["live"][0]["name"] == f"{owner_handle}/{handle}"
    assert body["members"][0]["name"] == body["live"][0]["name"]
    assert len(body["members"]) == 1 and "member_id" not in body["members"][0]
    assert body["totals"]["cards_done"] == 1
    assert sum(d["count"] for d in body["totals"]["cards_done_per_day"]) == 1
    assert owner.id not in str(body) and agent.id not in str(body)


def test_swarm_public_is_set_by_a_human(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    refused = admin.patch(
        "/projects/maintainer/maity", {"policy": {"swarm_public": "on"}, "reason": "r"}
    )
    assert refused.status_code == 403
    assert owner.get("/projects/maintainer/maity").json()["policy"]["swarm_public"] == "off"


def test_the_badge_and_the_swarm_share_one_budget(
    owner: flow.Human, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(badge_routes, "BY_ADDRESS", Limiter(2, 60))
    monkeypatch.setattr(badge_routes, "NOT_SERVED", Limiter(1, 60))
    visitor = make_client()
    assert (
        visitor.get("/badge/maintainer/nope.svg").status_code == 404
    )  # takes the shared unknown budget
    assert public(visitor, "other").status_code == 429  # the same budget, another slug
    assert public(visitor).status_code == 429  # the source's two are spent


def test_a_history_entry_into_review_is_a_review_sample(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, project_id: str
) -> None:
    agent = flow.agent(make_client, owner)
    creator, mine = membership_of(migrated, owner.id), membership_of(migrated, agent.id)
    for hours in (1, 2, 3):
        closed = NOW - timedelta(minutes=10)
        task = done(migrated, project_id, creator, mine, closed)
        history(migrated, task, mine, "in_progress", "review", closed - timedelta(hours=hours))
    assert row(page(owner), agent.id)["review_to_done_median_seconds"] == 7200


def test_every_page_is_cut_from_one_window(
    owner: flow.Human, migrated: Engine, project_id: str
) -> None:
    creator = membership_of(migrated, owner.id)
    done(migrated, project_id, creator, None, NOW)
    done(migrated, project_id, creator, None, NOW - timedelta(days=10))
    one, thirty = page(owner, 1), page(owner, 30)
    assert (one["window_days"], one["totals"]["cards_done"]) == (1, 1)
    assert len(one["totals"]["cards_done_per_day"]) == 1
    assert (thirty["window_days"], thirty["totals"]["cards_done"]) == (30, 2)
    assert one["as_of"] == thirty["as_of"]  # the same gathering, cut twice


def test_a_new_day_starts_a_new_window(
    owner: flow.Human, migrated: Engine, project_id: str
) -> None:
    late = NOW.replace(hour=23, minute=30)
    clock.set_source(lambda: late)
    page(owner)
    after_midnight = late + timedelta(minutes=50)
    clock.set_source(lambda: after_midnight)
    days = page(owner)["totals"]["cards_done_per_day"]
    assert days[-1]["date"] == after_midnight.date().isoformat()


def test_one_pull_request_is_one_key_however_its_url_is_written() -> None:
    a = swarm.pull_key("https://github.com/Oliver-Zehentleitner/Maity/pull/12")
    b = swarm.pull_key("https://github.com/oliver-zehentleitner/maity/pulls/12")
    assert a == b == "github.com/oliver-zehentleitner/maity#12"


def test_the_three_not_served_answers_are_one(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    visitor = make_client()
    unknown = public(visitor, "nope")
    off = public(visitor)
    owner.post("/projects", {"slug": "closed", "name": "Closed"})
    owner.patch("/projects/maintainer/closed", {"policy": {"swarm_public": "on"}, "reason": "r"})
    owner.patch("/projects/maintainer/closed", {"state": "archived", "reason": "done"})
    closed = public(visitor, "closed")
    assert unknown.status_code == off.status_code == closed.status_code == 404
    assert unknown.content == off.content == closed.content
    assert set(unknown.headers) == set(off.headers) == set(closed.headers)


def test_nothing_of_a_human_or_a_card_reaches_the_public_page(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, project_id: str
) -> None:
    agent = flow.agent(make_client, owner)
    listening.opened(agent.resume().json()["session"]["id"])
    creator = membership_of(migrated, owner.id)
    secret = card(
        migrated, project_id, creator, title="SECRET TITLE 7731", status="in_progress",
        claim_holder=membership_of(migrated, agent.id), claim_since=NOW,
    )  # fmt: skip
    done(migrated, project_id, creator, creator, NOW)
    human = owner.get(f"/projects/maintainer/maity/members/{owner.id}").json()
    owner.patch("/projects/maintainer/maity", {"policy": {"swarm_public": "on"}, "reason": "show"})
    text = public(make_client()).text
    for leaked in (
        secret, "SECRET TITLE 7731", owner.id, agent.id, human["display_name"],
        '"avatar_url"', '"last_seen_at"', '"since"', '"task_id"', '"member_id"', '"live_at"',
        '"holding"', '"title"',
    ):  # fmt: skip
        assert leaked not in text, leaked
    # The owner's handle appears only inside its agents' global names, by design (§6.22).
    body = json.loads(text)
    assert all(e["handle"] != human["handle"] for e in body["live"] + body["members"])
    assert all(e["name"].endswith("/" + e["handle"]) for e in body["live"] + body["members"])


def test_the_one_segment_public_address_is_gone(
    owner: flow.Human, make_client: ClientFactory, project_id: str
) -> None:
    """`/swarm/<slug>` from before the namespace is not kept, not even as a redirect while the
    page is public (§16.11)."""
    owner.patch("/projects/maintainer/maity", {"policy": {"swarm_public": "on"}, "reason": "show"})
    visitor = make_client()
    assert visitor.get("/api/v1/swarm/maity", follow_redirects=False).status_code == 404
    assert visitor.get("/api/v1/swarm/maintainer/maity").status_code == 200
