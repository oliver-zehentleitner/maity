"""docs/api.md §8.4, "A review result reaches the author and both leads" (tsk-w52ds51rpxs0): the
hub adds a review result's author, the reviewer's lead and the author's lead to its audience,
each once, a part that resolves to nobody dropped, `to` and mentions still adding; a lead of
another owner than its subordinate is left out (tsk-95kvvd03fgs4)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import chat_gate, clock, cross_owner, events, instances, review_delivery
from maity_hub import tables as t
from tests import factory, flow
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
    # `to: all` stands in for nobody: it leaves a supervised member asleep (§15.11).
    assert sent(migrated, post(reviewer, task_id=card["id"], to="all")) == [
        "all",
        f"member:{reviewer.id}",
        f"instance:{author.id}#{author.instance}",
        f"member:{lead.id}",
    ]


def test_a_to_naming_the_authors_member_id_reaches_its_instance_instead(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    card = task(owner)
    held(migrated, card, author, author.instance)
    # The member id would wake every instance under `wake: all`, another under `lead` or
    # `next_free`: the hub delivers it to the holding instance, and `to` stays as written.
    answer = post(reviewer, task_id=card["id"], to=author.id)
    assert sent(migrated, answer) == [
        f"instance:{author.id}#{author.instance}",
        f"member:{reviewer.id}",
    ]
    assert answer.json()["payload"]["to"] == author.id
    # A mention of the author's member is replaced the same way.
    with migrated.connect() as conn:
        handle = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == author.id)
        ).scalar_one()
    got = sent(migrated, post(reviewer, task_id=card["id"], to=owner.id, body=f"Done, @{handle}."))
    assert f"member:{author.id}" not in got
    assert got.count(f"instance:{author.id}#{author.instance}") == 1
    # The same instance address in `to` is not doubled.
    got = sent(migrated, post(reviewer, task_id=card["id"], to=f"{author.id}#{author.instance}"))
    assert got.count(f"instance:{author.id}#{author.instance}") == 1


def test_a_team_claimed_card_keeps_the_members_token(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    card = task(owner)
    held(migrated, card, author, None)
    got = sent(migrated, post(reviewer, task_id=card["id"], to=author.id))
    assert got == [f"member:{author.id}", f"member:{reviewer.id}"]


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


def isolate(engine: Engine, member: Any) -> None:
    row = membership_id(engine, member.id)
    with engine.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.id == row).values(isolated_since=clock.now())
        )


def test_an_isolated_author_or_lead_is_left_out(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    lead = flow.agent(make_client, owner, role="manager")
    reports_to(migrated, author, lead)
    card = task(owner)
    held(migrated, card, author, author.instance)
    # An isolated lead is routed past (§6.2), the author still reached.
    isolate(migrated, lead)
    got = sent(migrated, post(reviewer, task_id=card["id"]))
    assert got == [f"member:{reviewer.id}", f"instance:{author.id}#{author.instance}"]
    # A reporter isolated after its report, on a card nobody holds: nobody is left, so a
    # result without `to` is invalid rather than stored for no reader.
    other = task(owner)
    reported(migrated, other, author, 9)
    isolate(migrated, author)
    answer = post(reviewer, "#9")
    assert answer.status_code == 400, answer.text
    assert answer.json()["error"]["details"]["fields"] == {"to": "required"}


def test_another_instance_of_the_author_in_to_does_not_stand_in_for_the_holder(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    team = owner.patch(
        f"/projects/maintainer/maity/members/{author.id}", {"team": {"max_instances": 2}}
    )
    assert team.status_code == 200, team.text
    sibling = flow.agent(make_client, owner, agent={"id": author.id}, new_instance=True)
    for agent in (author, sibling):
        assert agent.resume().status_code == 200
    reviewer = flow.agent(make_client, owner, role="reviewer")
    card = task(owner)
    held(migrated, card, author, author.instance)
    got = sent(migrated, post(reviewer, task_id=card["id"], to=f"{author.id}#{sibling.instance}"))
    assert got == [
        f"instance:{author.id}#{sibling.instance}",
        f"member:{reviewer.id}",
        f"instance:{author.id}#{author.instance}",
    ]


def test_a_number_in_prose_names_no_pull_request(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    reported(migrated, task(owner), author, 7)
    got = sent(migrated, post(reviewer, "Fix for #7", to=owner.id))
    assert got == [f"member:{owner.id}", f"member:{reviewer.id}"]


def test_a_lead_reached_by_its_role_is_not_added(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    lead = flow.agent(make_client, owner, role="manager")
    reports_to(migrated, author, lead)
    card = task(owner)
    held(migrated, card, author, author.instance)
    got = sent(migrated, post(reviewer, task_id=card["id"], to="role:manager"))
    assert f"member:{lead.id}" not in got
    assert f"instance:{author.id}#{author.instance}" in got


def test_an_unheld_cards_reporter_who_left_or_never_had_the_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    card = task(owner)
    reported(migrated, card, author, 7)
    # An instance the member never had: the team is the author.
    with migrated.begin() as conn:
        report = conn.execute(select(t.card.c.report).where(t.card.c.id == card["id"])).scalar_one()
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card["id"])
            .values(report={**report, "reported_instance": "zz99"})
        )
    assert f"member:{author.id}" in sent(migrated, post(reviewer, "#7"))
    # A reporter who has left the project: nobody, so a result without `to` is invalid.
    row = membership_id(migrated, author.id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.id == row).values(removed_at=clock.now())
        )
    assert post(reviewer, "#7").status_code == 400


def test_an_isolated_holder_of_a_held_card_is_left_out(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The holder's isolation (§6.2) drops it from a review result on its held card."""
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    lead = flow.agent(make_client, owner, role="manager")
    reports_to(migrated, author, lead)
    card = task(owner)
    held(migrated, card, author, author.instance)
    isolate(migrated, author)
    # Its lead is reached through the holder, so without the holder nobody is left.
    answer = post(reviewer, task_id=card["id"])
    assert answer.status_code == 400, answer.text
    assert answer.json()["error"]["details"]["fields"] == {"to": "required"}


# A lead of another owner than its subordinate (§8.4, §6.2 "What the edge does",
# tsk-95kvvd03fgs4): not added for the sender's nor the author's `reports_to`, so it is
# neither in the audience nor named in `held`, does not read the result and is not woken.


def other_owner(make_client: ClientFactory, engine: Engine) -> flow.Human:
    """A second human, an admin of the project, who owns agents of their own."""
    other = flow.human(make_client, engine, "other")
    with engine.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(engine, project_id, "admin", human_id=other.id)
    return other


def seqs(who: Any) -> list[int]:
    got = who.get("/projects/maintainer/maity/events?after=0&limit=200")
    assert got.status_code == 200, got.text
    return [e["seq"] for e in got.json()["items"]]


def woken(engine: Engine, agent_id: str) -> list[int]:
    with engine.connect() as conn:
        row = conn.execute(select(t.membership).where(t.membership.c.agent_id == agent_id)).one()
        rows, _ = events.read_waking(conn, row.project_id, row, agent_id, 0, 200)
    return [r.seq for r in rows]


def assert_left_out(engine: Engine, answer: Any, boss: flow.Agent) -> None:
    assert answer.status_code == 201, answer.text
    seq = int(answer.json()["seq"])
    assert all(boss.id not in token for token in audience(engine, seq))
    assert answer.json()["payload"]["held"] == []
    assert seq not in seqs(boss)
    assert seq not in woken(engine, boss.id)


def test_the_senders_lead_of_another_owner_is_left_out(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_owner(make_client, migrated)
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    boss = flow.agent(make_client, other, role="manager")
    boss.resume()
    author_lead = flow.agent(make_client, owner, role="manager")
    reports_to(migrated, reviewer, boss)
    reports_to(migrated, author, author_lead)
    card = task(owner)
    held(migrated, card, author, author.instance)
    answer = post(reviewer, task_id=card["id"])
    assert_left_out(migrated, answer, boss)
    # The author's lead, of the author's own owner, is still added.
    assert sent(migrated, answer) == [
        f"member:{reviewer.id}",
        f"instance:{author.id}#{author.instance}",
        f"member:{author_lead.id}",
    ]


def test_the_authors_lead_of_another_owner_is_left_out(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_owner(make_client, migrated)
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    boss = flow.agent(make_client, other, role="manager")
    boss.resume()
    reviewer_lead = flow.agent(make_client, owner, role="manager")
    reports_to(migrated, author, boss)
    reports_to(migrated, reviewer, reviewer_lead)
    card = task(owner)
    held(migrated, card, author, author.instance)
    answer = post(reviewer, task_id=card["id"])
    assert_left_out(migrated, answer, boss)
    assert sent(migrated, answer) == [
        f"member:{reviewer.id}",
        f"instance:{author.id}#{author.instance}",
        f"member:{reviewer_lead.id}",
    ]
    # An author of the other owner keeps its own owner's lead: the edge is not cross-owner.
    theirs = flow.agent(make_client, other)
    theirs.resume()
    reports_to(migrated, theirs, boss)
    other_card = task(owner)
    held(migrated, other_card, theirs, theirs.instance)
    got = sent(migrated, post(reviewer, task_id=other_card["id"]))
    assert f"member:{boss.id}" in got


def test_a_lead_of_another_owner_is_left_out_with_the_firewall_off(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Leaving the lead out is §8.4's rule, not the gate's: it holds with the gate off."""
    other = other_owner(make_client, migrated)
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    boss = flow.agent(make_client, other, role="manager")
    boss.resume()
    author_boss = flow.agent(make_client, other, role="manager")
    author_boss.resume()
    reports_to(migrated, reviewer, boss)
    reports_to(migrated, author, author_boss)
    card = task(owner)
    held(migrated, card, author, author.instance)
    chat_gate.configure(False)
    try:
        answer = post(reviewer, task_id=card["id"])
        assert_left_out(migrated, answer, boss)
        assert_left_out(migrated, answer, author_boss)
        assert sent(migrated, answer) == [
            f"member:{reviewer.id}",
            f"instance:{author.id}#{author.instance}",
        ]
    finally:
        chat_gate.configure(True)


def test_a_human_senders_human_lead_is_still_added(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A human's `reports_to` is never cross-owner (§6.2 "Across owners")."""
    other = other_owner(make_client, migrated)
    writer = flow.human(make_client, migrated, "writer")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "member", human_id=writer.id)
    reports_to(migrated, writer, other)
    author = flow.agent(make_client, owner)
    author.resume()
    card = task(owner)
    held(migrated, card, author, author.instance)
    got = sent(migrated, post(writer, task_id=card["id"]))
    assert got == [
        f"member:{writer.id}",
        f"instance:{author.id}#{author.instance}",
        f"member:{other.id}",
    ]


@pytest.mark.parametrize("unresolved", ["lead", "led"])
def test_a_lead_whose_or_whose_subordinates_owner_cannot_be_resolved_is_left_out(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    unresolved: str,
) -> None:
    """Fail closed (§8.4, tsk-9sjg106s9wdc): a lead is added only when both its owner and the
    owner of the agent it leads resolve and are the same. Each side is made unresolvable in
    turn; the other path's lead, both owners resolved, is still added."""
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    reviewer_lead = flow.agent(make_client, owner, role="manager")
    reviewer_lead.resume()
    author_lead = flow.agent(make_client, owner, role="manager")
    author_lead.resume()
    reports_to(migrated, reviewer, reviewer_lead)
    reports_to(migrated, author, author_lead)
    card = task(owner)
    held(migrated, card, author, author.instance)
    # The sender's lead itself, or the author the other lead leads, has no owner to resolve.
    hidden, dropped, kept = (
        (reviewer_lead.id, reviewer_lead, author_lead)
        if unresolved == "lead"
        else (author.id, author_lead, reviewer_lead)
    )
    resolve = cross_owner.owner_of

    def owner_of(conn: Any, row: Any) -> str | None:
        return None if row.agent_id == hidden else resolve(conn, row)

    monkeypatch.setattr(cross_owner, "owner_of", owner_of)
    answer = post(reviewer, task_id=card["id"])
    assert_left_out(migrated, answer, dropped)
    assert sent(migrated, answer) == [
        f"member:{reviewer.id}",
        f"instance:{author.id}#{author.instance}",
        f"member:{kept.id}",
    ]


# A review result reaches the instance whose message it answers (§8.4, `in_reply_to`,
# tsk-9ytv9jmscmdr): the answered message's author, the orderer, is added as the author is.


def woken_as(engine: Engine, agent: flow.Agent) -> list[int]:
    """What wakes this one instance, as its own credential reads (a dormant one included)."""
    with engine.connect() as conn:
        row = conn.execute(select(t.membership).where(t.membership.c.agent_id == agent.id)).one()
        rows, _ = events.read_waking(
            conn,
            row.project_id,
            row,
            agent.id,
            0,
            200,
            instance=agent.instance,
            credential_id=agent.credential_id,
        )
    return [r.seq for r in rows]


def order(who: Any, to: str, body: str = "Please review #7.") -> int:
    """A review order: a plain message, whose author instance the hub records."""
    answer = who.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": to, "body": body},
    )
    assert answer.status_code == 201, answer.text
    return int(answer.json()["seq"])


def test_the_instance_that_ordered_the_review_is_added_and_woken(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    lead = flow.agent(make_client, owner, role="manager")
    lead.resume()
    card = task(owner)
    held(migrated, card, author, author.instance)
    asked = order(lead, reviewer.id)
    answer = post(reviewer, task_id=card["id"], in_reply_to=asked)
    assert sent(migrated, answer) == [
        f"member:{reviewer.id}",
        f"instance:{author.id}#{author.instance}",
        f"instance:{lead.id}#{lead.instance}",
    ]
    assert answer.json()["payload"]["in_reply_to"] == asked
    assert int(answer.json()["seq"]) in woken_as(migrated, lead)
    # The project's messages carry it (§8.8); without `in_reply_to` it is null there.
    listed = reviewer.get("/projects/maintainer/maity/messages?type=review_result")
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["in_reply_to"] == asked
    assert post(reviewer, task_id=card["id"]).json()["payload"]["in_reply_to"] is None


def test_the_orderers_instance_replaces_its_member_id_and_its_lead_token(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The bug of the jour fixe: results to the review lead's member id woke whatever instance
    its `wake` rule chose. The ordering instance takes the place of that `member:` token, from
    `to` and from the reviewer's `reports_to` alike."""
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    lead = flow.agent(make_client, owner, role="manager")
    lead.resume()
    reports_to(migrated, reviewer, lead)
    card = task(owner)
    held(migrated, card, author, author.instance)
    asked = order(lead, reviewer.id)
    answer = post(reviewer, task_id=card["id"], to=lead.id, in_reply_to=asked)
    got = sent(migrated, answer)
    assert f"member:{lead.id}" not in got
    assert got == [
        f"instance:{lead.id}#{lead.instance}",
        f"member:{reviewer.id}",
        f"instance:{author.id}#{author.instance}",
    ]
    assert answer.json()["payload"]["to"] == lead.id
    # Without `to` the lead is not added as its member either: the instance stands for it.
    got = sent(migrated, post(reviewer, task_id=card["id"], in_reply_to=asked))
    assert got == [
        f"member:{reviewer.id}",
        f"instance:{author.id}#{author.instance}",
        f"instance:{lead.id}#{lead.instance}",
    ]


def test_a_human_orderer_is_its_member_and_added_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    reports_to(migrated, reviewer, owner)
    card = task(owner)
    held(migrated, card, author, author.instance)
    asked = order(owner, reviewer.id)
    got = sent(migrated, post(reviewer, task_id=card["id"], in_reply_to=asked))
    assert got == [
        f"member:{reviewer.id}",
        f"instance:{author.id}#{author.instance}",
        f"member:{owner.id}",
    ]


def test_the_orderer_is_found_without_a_card(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    reviewer = flow.agent(make_client, owner, role="reviewer")
    lead = flow.agent(make_client, owner, role="manager")
    lead.resume()
    asked = order(lead, reviewer.id)
    # No card resolves from the subject, so the orderer alone is added and the result is valid.
    got = sent(migrated, post(reviewer, "#99", in_reply_to=asked))
    assert got == [f"member:{reviewer.id}", f"instance:{lead.id}#{lead.instance}"]


def test_an_orderer_who_left_is_isolated_or_is_the_sender_is_left_out(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    reviewer.resume()
    lead = flow.agent(make_client, owner, role="manager")
    lead.resume()
    card = task(owner)
    held(migrated, card, author, author.instance)
    own = order(reviewer, lead.id)
    got = sent(migrated, post(reviewer, task_id=card["id"], in_reply_to=own))
    assert got == [f"member:{reviewer.id}", f"instance:{author.id}#{author.instance}"]
    asked = order(lead, reviewer.id)
    isolate(migrated, lead)
    got = sent(migrated, post(reviewer, task_id=card["id"], in_reply_to=asked))
    assert all(lead.id not in token for token in got)
    row = membership_id(migrated, lead.id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == row)
            .values(isolated_since=None, removed_at=clock.now())
        )
    got = sent(migrated, post(reviewer, task_id=card["id"], in_reply_to=asked))
    assert all(lead.id not in token for token in got)


def test_the_sender_is_the_sending_instance_not_its_whole_member(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """KtW 1d17b2d5 and review A1883, finding 3: "the sender" is the sending instance. Another
    instance of the sender's own member that ordered the review is added like any orderer;
    an order addressed only to that other instance does not count as addressed to the sender,
    so its orderer is not exempt from the gate (probe P1g)."""
    reviewer = flow.agent(make_client, owner, role="reviewer")
    team = owner.patch(
        f"/projects/maintainer/maity/members/{reviewer.id}", {"team": {"max_instances": 2}}
    )
    assert team.status_code == 200, team.text
    twin = flow.agent(make_client, owner, agent={"id": reviewer.id}, new_instance=True)
    for agent in (reviewer, twin):
        assert agent.resume().status_code == 200
    lead = flow.agent(make_client, owner, role="manager")
    lead.resume()
    by_twin = order(twin, lead.id)
    got = sent(migrated, post(reviewer, "#99", in_reply_to=by_twin))
    assert f"instance:{reviewer.id}#{twin.instance}" in got
    # Whether the orderer is exempt from the gate, judged where the gate would hold everyone.
    to_twin = order(lead, f"{reviewer.id}#{twin.instance}")
    to_sender = order(lead, f"{reviewer.id}#{reviewer.instance}")
    row = membership_id(migrated, reviewer.id)
    with migrated.connect() as conn:
        project = conn.execute(select(t.project)).one()
        sender = conn.execute(select(t.membership).where(t.membership.c.id == row)).one()

        def orderers(seq: int) -> list[review_delivery.Recipient]:
            answered = conn.execute(select(t.event).where(t.event.c.seq == seq)).one()
            return review_delivery.recipients(
                conn,
                project,
                sender,
                None,
                review("#99"),
                answered,
                reviewer.instance,
                admits=lambda _: False,
            )

        assert orderers(to_twin) == []
        assert [r.token for r in orderers(to_sender)] == [f"instance:{lead.id}#{lead.instance}"]


def test_a_redacted_order_can_still_be_answered(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    reviewer = flow.agent(make_client, owner, role="reviewer")
    lead = flow.agent(make_client, owner, role="manager")
    lead.resume()
    asked = order(lead, reviewer.id)
    redacted = owner.post(f"/projects/maintainer/maity/events/{asked}/redact", {"reason": "x"})
    assert redacted.status_code == 200, redacted.text
    got = sent(migrated, post(reviewer, "#99", in_reply_to=asked))
    assert f"instance:{lead.id}#{lead.instance}" in got


def test_an_orderer_who_cannot_read_the_restricted_card_is_left_out(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The lead's change to the request: on a card with a restricted text (§6.4), an orderer
    outside the restricted-access set (§6.1) gets no event; the author and the leads still do,
    and the hub says nothing of the omission."""
    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    reviewer_lead = flow.agent(make_client, owner, role="manager")
    author_lead = flow.agent(make_client, owner, role="manager")
    reports_to(migrated, reviewer, reviewer_lead)
    reports_to(migrated, author, author_lead)
    orderer = flow.agent(make_client, owner, role="manager")
    orderer.resume()
    card = task(owner)
    held(migrated, card, author, author.instance)
    listed = [owner.id, author.id, reviewer.id, reviewer_lead.id, author_lead.id]
    writer = membership_id(migrated, owner.id)
    with migrated.begin() as conn:
        project = conn.execute(select(t.project)).one()
        settings = {
            **(project.settings or {}),
            "restricted_access": {"mode": "nobody_except", "members": listed},
        }
        conn.execute(
            update(t.project).where(t.project.c.id == project.id).values(settings=settings)
        )
        conn.execute(
            t.task_restricted.insert().values(
                task_id=card["id"],
                project_id=project.id,
                text="secret",
                version=1,
                updated_by=writer,
                updated_at=clock.now(),
            )
        )
    asked = order(orderer, reviewer.id)
    answer = post(reviewer, task_id=card["id"], in_reply_to=asked)
    assert answer.status_code == 201, answer.text
    seq = int(answer.json()["seq"])
    assert sent(migrated, answer) == [
        f"member:{reviewer.id}",
        f"instance:{author.id}#{author.instance}",
        f"member:{reviewer_lead.id}",
        f"member:{author_lead.id}",
    ]
    assert answer.json()["payload"]["held"] == []
    assert seq not in seqs(orderer)
    assert seq not in woken_as(migrated, orderer)
    for reached in (reviewer_lead, author_lead):
        assert seq in seqs(reached)
    assert seq in woken_as(migrated, author)
    # In the set, the same orderer is added.
    with migrated.begin() as conn:
        project = conn.execute(select(t.project)).one()
        settings = {
            **project.settings,
            "restricted_access": {"mode": "nobody_except", "members": [*listed, orderer.id]},
        }
        conn.execute(
            update(t.project).where(t.project.c.id == project.id).values(settings=settings)
        )
    got = sent(migrated, post(reviewer, task_id=card["id"], in_reply_to=asked))
    assert f"instance:{orderer.id}#{orderer.instance}" in got


def refused(answer: Any) -> Any:
    assert answer.status_code == 400, answer.text
    return answer.json()["error"]["details"]["fields"]["in_reply_to"]


def test_in_reply_to_is_checked(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    reviewer = flow.agent(make_client, owner, role="reviewer")
    lead = flow.agent(make_client, owner, role="manager")
    lead.resume()
    asked = order(lead, reviewer.id)
    # Only a review result takes it today.
    notice = reviewer.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": "all", "body": "x", "in_reply_to": asked},
    )
    assert refused(notice) == "not_allowed"
    for value in (0, -3, "7", True, 1.5):
        assert refused(post(reviewer, "#99", to=owner.id, in_reply_to=value)) == "format"
    assert refused(post(reviewer, "#99", to=owner.id, in_reply_to=10**6)) == "unknown_event"
    assert refused(post(reviewer, "#99", to=owner.id, in_reply_to=2**70)) == "unknown_event"
    # A message the sender cannot read answers as one that does not exist.
    private = order(lead, owner.id, "Not for the reviewer.")
    assert refused(post(reviewer, "#99", to=owner.id, in_reply_to=private)) == "unknown_event"
    # An event the sender reads that is no project message, and a chat message.
    task(owner)
    other = [
        e["seq"]
        for e in reviewer.get("/projects/maintainer/maity/events?after=0&limit=200").json()["items"]
        if e["kind"] != "message"
    ]
    assert other
    assert refused(post(reviewer, "#99", to=owner.id, in_reply_to=other[-1])) == "not_a_message"
    chat = owner.post(
        f"/projects/maintainer/maity/conversations/{reviewer.id}/messages", {"body": "Hello."}
    )
    assert chat.status_code == 201, chat.text
    said = int(chat.json()["seq"])
    assert refused(post(reviewer, "#99", to=owner.id, in_reply_to=said)) == "not_a_message"


def test_a_dormant_orderer_is_woken_by_its_own_token(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    reviewer = flow.agent(make_client, owner, role="reviewer")
    lead = flow.agent(make_client, owner, role="manager")
    lead.resume()
    asked = order(lead, reviewer.id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.instance_attachment)
            .where(instances.attachment_of(lead.credential_id))
            .values(dormant_since=clock.now())
        )
    answer = post(reviewer, "#99", to=lead.id, in_reply_to=asked)
    assert sent(migrated, answer) == [
        f"instance:{lead.id}#{lead.instance}",
        f"member:{reviewer.id}",
    ]
    assert int(answer.json()["seq"]) in woken_as(migrated, lead)


def test_a_replaced_orderer_resolves_to_its_successor(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    reviewer = flow.agent(make_client, owner, role="reviewer")
    old = flow.agent(make_client, owner, role="manager")
    old.resume()
    asked = order(old, reviewer.id)
    new = flow.agent(make_client, owner, agent={"id": old.id}, replaces=old.instance)
    got = sent(migrated, post(reviewer, "#99", in_reply_to=asked))
    assert got == [f"member:{reviewer.id}", f"instance:{old.id}#{new.instance}"]


def test_in_reply_to_reads_as_the_single_event_route_does(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A group chat message the sender sees only in the chat's history, added after it was
    written, is not served by `GET …/events/{seq}` (§8.9): it answers as an unknown event, not
    as a message of the wrong kind (review A1858, point 3)."""
    reviewer = flow.agent(make_client, owner, role="reviewer")
    other = flow.agent(make_client, owner)
    third = flow.agent(make_client, owner)
    chats = "/projects/maintainer/maity/conversations"
    group = owner.post(chats, {"title": "room", "participants": [other.id, third.id]})
    assert group.status_code == 201, group.text
    chat = group.json()["id"]
    said = owner.post(f"{chats}/{chat}/messages", {"body": "in the room"})
    assert said.status_code == 201, said.text
    in_room = int(said.json()["seq"])
    added = owner.post(f"{chats}/{chat}/participants", {"member_id": reviewer.id})
    assert added.status_code == 200, added.text
    history = reviewer.get(f"{chats}/{chat}/messages?before={in_room + 1}")
    assert in_room in [m["seq"] for m in history.json()["items"]]
    assert reviewer.get(f"/projects/maintainer/maity/events/{in_room}").status_code == 404
    assert refused(post(reviewer, "#99", to=owner.id, in_reply_to=in_room)) == "unknown_event"


def test_an_explicit_null_in_reply_to_is_refused_and_omission_is_not(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Presence, not value (§8.4; review A1858, point 4): supplied, it is a positive integer on
    a review result and refused on any other type, null included; omitted, it is fine."""
    reviewer = flow.agent(make_client, owner, role="reviewer")
    assert refused(post(reviewer, "#99", to=owner.id, in_reply_to=None)) == "format"
    notice = reviewer.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": "all", "body": "x", "in_reply_to": None},
    )
    assert refused(notice) == "not_allowed"
    omitted = post(reviewer, "#99", to=owner.id)
    assert omitted.status_code == 201, omitted.text
    assert omitted.json()["payload"]["in_reply_to"] is None


def test_the_orderer_is_judged_on_the_project_row_read_under_the_lock(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restricted-access change that commits after the sender's membership was looked up
    but before the event takes the project's lock decides the audience (review A1858, point 2).
    Simulated in the request's own transaction: the orderer is in the set when the membership
    is read and out of it right after; the result must not reach it."""
    from maity_hub.routes import events as event_routes

    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    orderer = flow.agent(make_client, owner, role="manager")
    orderer.resume()
    card = task(owner)
    held(migrated, card, author, author.instance)
    listed = [owner.id, author.id, reviewer.id]
    writer = membership_id(migrated, owner.id)

    def restrict(conn: Any, members: list[str]) -> None:
        project = conn.execute(select(t.project)).one()
        settings = {
            **(project.settings or {}),
            "restricted_access": {"mode": "nobody_except", "members": members},
        }
        conn.execute(
            update(t.project).where(t.project.c.id == project.id).values(settings=settings)
        )

    with migrated.begin() as conn:
        restrict(conn, [*listed, orderer.id])
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        conn.execute(
            t.task_restricted.insert().values(
                task_id=card["id"],
                project_id=project_id,
                text="secret",
                version=1,
                updated_by=writer,
                updated_at=clock.now(),
            )
        )
    asked = order(orderer, reviewer.id)
    looked_up = getattr(event_routes, "membership")  # noqa: B009 - imported, not exported

    def then_changed(conn: Any, caller: Any, slug: str, *args: Any, **kwargs: Any) -> Any:
        mine = looked_up(conn, caller, slug, *args, **kwargs)
        restrict(conn, listed)  # the orderer leaves the set after the lookup
        return mine

    monkeypatch.setattr(event_routes, "membership", then_changed)
    got = sent(migrated, post(reviewer, task_id=card["id"], in_reply_to=asked))
    assert all(orderer.id not in token for token in got)
    assert f"instance:{author.id}#{author.instance}" in got


def test_a_review_result_is_authorized_on_the_senders_row_read_under_the_lock(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A trust change that commits after the sender's membership was looked up but before the
    event takes the project's lock decides whether it may post (review A1882, point 2).
    Simulated in the request's own transaction: the reviewer is a member when its membership is
    read and a guest, who holds no `events:post`, right after; the result is refused and no
    event is written."""
    from maity_hub.routes import events as event_routes

    author = flow.agent(make_client, owner)
    author.resume()
    reviewer = flow.agent(make_client, owner, role="reviewer")
    card = task(owner)
    held(migrated, card, author, author.instance)
    row = membership_id(migrated, reviewer.id)
    with migrated.connect() as conn:
        before = conn.execute(select(t.event.c.seq).order_by(t.event.c.seq.desc())).scalar()
    looked_up = getattr(event_routes, "membership")  # noqa: B009 - imported, not exported

    def then_demoted(conn: Any, caller: Any, slug: str, *args: Any, **kwargs: Any) -> Any:
        mine = looked_up(conn, caller, slug, *args, **kwargs)
        if mine.id == row:  # the sender becomes a guest after the lookup
            conn.execute(update(t.membership).where(t.membership.c.id == row).values(trust="guest"))
        return mine

    monkeypatch.setattr(event_routes, "membership", then_demoted)
    refused = post(reviewer, task_id=card["id"])
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["scope"] == "events:post"
    with migrated.connect() as conn:
        after = conn.execute(select(t.event.c.seq).order_by(t.event.c.seq.desc())).scalar()
    assert after == before
