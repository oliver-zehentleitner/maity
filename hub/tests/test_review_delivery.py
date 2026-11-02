"""docs/api.md §8.4, "A review result reaches the author and both leads" (tsk-w52ds51rpxs0): the
hub adds a review result's author, the reviewer's lead and the author's lead to its audience,
each once, a part that resolves to nobody dropped, `to` and mentions still adding."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

HEAD = "7039a4b6fd8b988d71a63338711da188fcd95fba"
CITE = {"path": "docs/api.md", "line": 1, "quote": "a line"}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def review(subject: str = "#7") -> dict[str, Any]:
    return {"subject": subject, "head": HEAD, "verdict": "approve", "cites": [dict(CITE)]}


def post(who: Any, subject: str = "#7", **more: Any) -> Any:
    body: dict[str, Any] = {
        "kind": "message",
        "type": "review_result",
        "body": "Approved.",
        "review": review(subject),
        **more,
    }
    return who.post("/projects/maintainer/maity/events", body)


def audience(engine: Engine, seq: int) -> list[str]:
    with engine.connect() as conn:
        found: list[str] = conn.execute(
            select(t.event.c.audience).where(t.event.c.seq == seq)
        ).scalar_one()
    return found


def sent(engine: Engine, answer: Any) -> list[str]:
    assert answer.status_code == 201, answer.text
    return audience(engine, int(answer.json()["seq"]))


def task(owner: flow.Human) -> dict[str, Any]:
    response = owner.post("/projects/maintainer/maity/tasks", {"title": "A card"})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def membership_id(engine: Engine, member_id: str) -> int:
    column = t.membership.c.agent_id if member_id.startswith("agt-") else t.membership.c.human_id
    with engine.connect() as conn:
        found: int = conn.execute(
            select(t.membership.c.id).where(column == member_id, t.membership.c.active.is_(True))
        ).scalar_one()
    return found


def reports_to(engine: Engine, member: Any, lead: Any) -> None:
    row, boss = membership_id(engine, member.id), membership_id(engine, lead.id)
    with engine.begin() as conn:
        conn.execute(update(t.membership).where(t.membership.c.id == row).values(reports_to=boss))


def held(engine: Engine, card: dict[str, Any], holder: flow.Agent, instance: str | None) -> None:
    row = membership_id(engine, holder.id)
    with engine.begin() as conn:
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card["id"])
            .values(claim_holder=row, claim_instance=instance)
        )


def reported(
    engine: Engine,
    card: dict[str, Any],
    by: flow.Agent,
    number: int,
    at: str = "2026-11-02T10:00:00Z",
) -> None:
    report = {
        "pr": {"number": number, "url": f"https://github.com/a/b/pull/{number}"},
        "pr_status": "found",
        "reported_by": by.id,
        "reported_instance": by.instance,
        "reported_at": at,
    }
    with engine.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card["id"]).values(report=report))


def test_the_card_holder_and_both_leads_are_added_without_a_to(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    author_lead = flow.agent(make_client, owner, role="manager")
    reviewer_lead = flow.agent(make_client, owner, role="manager")
    reports_to(migrated, author, author_lead)
    reports_to(migrated, reviewer, reviewer_lead)
    card = task(owner)
    held(migrated, card, author, author.instance)
    answer = post(reviewer, task_id=card["id"])
    assert sent(migrated, answer) == [
        f"member:{reviewer.id}",
        f"instance:{author.id}#{author.instance}",
        f"member:{reviewer_lead.id}",
        f"member:{author_lead.id}",
    ]
    assert answer.json()["payload"]["to"] is None


def test_without_a_task_the_card_whose_latest_report_names_the_pr_is_found(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    older = flow.agent(make_client, owner)
    newer = flow.agent(make_client, owner)
    older.resume()
    newer.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    reported(migrated, task(owner), older, 7, at="2026-11-01T10:00:00Z")
    reported(migrated, task(owner), newer, 7, at="2026-11-02T10:00:00Z")
    reported(migrated, task(owner), older, 8)
    # Nobody holds the cards: the instance that sent the latest report is the author.
    assert f"instance:{newer.id}#{newer.instance}" in sent(migrated, post(reviewer, "#7"))
    assert f"instance:{older.id}#{older.instance}" in sent(migrated, post(reviewer, "#8"))


def test_a_subject_that_is_no_pull_request_number_finds_no_author(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    reported(migrated, task(owner), author, 7)
    answer = post(reviewer, "PR 7", to=owner.id)
    assert sent(migrated, answer) == [f"member:{owner.id}", f"member:{reviewer.id}"]


def test_each_member_is_added_once_and_the_sender_never(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    lead = flow.agent(make_client, owner, role="manager")
    # One lead for both, and the author reports to the reviewer's lead as well.
    reports_to(migrated, author, lead)
    reports_to(migrated, reviewer, lead)
    card = task(owner)
    held(migrated, card, author, author.instance)
    got = sent(migrated, post(reviewer, task_id=card["id"]))
    assert got == [
        f"member:{reviewer.id}",
        f"instance:{author.id}#{author.instance}",
        f"member:{lead.id}",
    ]
    # A reviewer that is the author's lead is not added a second time.
    reports_to(migrated, author, reviewer)
    got = sent(migrated, post(reviewer, task_id=card["id"]))
    assert got.count(f"member:{reviewer.id}") == 1


def test_a_part_with_nobody_above_it_is_dropped(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    card = task(owner)
    held(migrated, card, author, author.instance)
    got = sent(migrated, post(reviewer, task_id=card["id"]))
    assert got == [f"member:{reviewer.id}", f"instance:{author.id}#{author.instance}"]


def test_a_reviewer_from_another_team_reaches_both_leads(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    web_lead = flow.agent(make_client, owner, role="manager")
    review_lead = flow.agent(make_client, owner, role="manager")
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    reports_to(migrated, author, web_lead)
    reports_to(migrated, reviewer, review_lead)
    card = task(owner)
    held(migrated, card, author, None)  # a claim made on the team's behalf: the team
    got = sent(migrated, post(reviewer, task_id=card["id"]))
    assert got == [
        f"member:{reviewer.id}",
        f"member:{author.id}",
        f"member:{review_lead.id}",
        f"member:{web_lead.id}",
    ]


def test_to_and_mentions_still_add_and_are_not_doubled(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    lead = flow.agent(make_client, owner, role="manager")
    reports_to(migrated, author, lead)
    card = task(owner)
    held(migrated, card, author, author.instance)
    got = sent(
        migrated,
        post(reviewer, task_id=card["id"], to=lead.id, body="Approved, @maintainer please look."),
    )
    # `to` already reaches the lead, so it is not added again; the mention keeps its ping.
    assert got == [
        f"member:{lead.id}",
        f"member:{reviewer.id}",
        f"member:{owner.id}",
        f"instance:{author.id}#{author.instance}",
    ]
    # `to: all` reaches everyone: nothing is added.
    assert sent(migrated, post(reviewer, task_id=card["id"], to="all")) == [
        "all",
        f"member:{reviewer.id}",
    ]


def test_a_review_result_that_reaches_nobody_but_its_sender_is_invalid(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    reviewer = flow.agent(make_client, owner, role="reviewer")
    answer = post(reviewer, "#99")
    assert answer.status_code == 400, answer.text
    assert answer.json()["error"]["details"]["fields"] == {"to": "required"}
    # Any other type still needs its `to`.
    plain = reviewer.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "body": "Hi."},
    )
    assert plain.json()["error"]["details"]["fields"] == {"to": "required"}


def test_a_lead_who_left_the_project_is_dropped(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    lead = flow.agent(make_client, owner, role="manager")
    reports_to(migrated, author, lead)
    card = task(owner)
    held(migrated, card, author, author.instance)
    row = membership_id(migrated, lead.id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.id == row).values(removed_at=clock.now())
        )
    got = sent(migrated, post(reviewer, task_id=card["id"]))
    assert f"member:{lead.id}" not in got
