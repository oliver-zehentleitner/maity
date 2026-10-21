"""docs/api.md §7: requests to humans, the inbox, answers, withdrawal, blocked cards."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_claims import _claim
from tests.test_tasks import _report, task

REQUEST_KEYS = {
    "id",
    "class",
    "title",
    "summary",
    "tried",
    "options",
    "replies",
    "priority",
    "to",
    "asked_by",
    "on_behalf_of",
    "task_id",
    "task",
    "while_open",
    "needs_in_session",
    "ktw_ref",
    "status",
    "answer",
    "created_at",
    "answered_at",
}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def ask(who: Any, slug: str = "maity", **body: Any) -> Any:
    return who.post(f"/projects/{slug}/requests", {"class": "decision", "title": "Which?", **body})


def asked(who: Any, slug: str = "maity", **body: Any) -> dict[str, Any]:
    response = ask(who, slug, **body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def answer(who: Any, request: dict[str, Any], slug: str = "maity", **body: Any) -> Any:
    return who.post(f"/projects/{slug}/requests/{request['id']}/answer", body)


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


# --- asking ---------------------------------------------------------------------------


def test_a_request_has_the_contract_shape_and_goes_to_the_agents_human(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner, agent={"handle": "agent-b", "display_name": "Agent B"})
    session = agent.resume().json()["session"]["id"]
    body = asked(
        agent,
        summary="context",
        tried="both",
        options=[
            {"id": "sha", "label": "SHA-256", "detail": "fast"},
            {"id": "argon", "label": "Argon2id"},
        ],
        priority="high",
    )
    assert set(body) == REQUEST_KEYS
    assert body["to"] == owner.id  # an agent's default addressee is its own human
    assert body["replies"] == [
        {"id": "sha", "label": "SHA-256"},
        {"id": "argon", "label": "Argon2id"},
    ]
    assert body["asked_by"] == {
        "member_id": agent.id,
        "display_name": "Agent B",
        "role": "member",
        "session_id": session,
    }
    assert (body["status"], body["answer"], body["while_open"]) == ("open", None, "wait")
    created = _events(migrated, "request_created")[-1]
    assert created.audience == [f"member:{owner.id}"]
    assert created.payload["id"] == body["id"] and created.payload["replies"] == body["replies"]


def test_a_bare_consent_answers_go_or_no(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    body = asked(agent, **{"class": "consent", "title": "Tag 0.2.0?"})
    assert body["replies"] == [{"id": "go", "label": "go"}, {"id": "no", "label": "no"}]


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"class": "question"}, {"class": "unknown"}),
        ({"priority": "now"}, {"priority": "unknown"}),
        ({"options": [{"id": "a", "label": "A"}]}, {"options": "none_or_two_or_more"}),
        (
            {"options": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]},
            {"options": "duplicate_id"},
        ),
        (
            {"class": "consent", "while_open": "proceed_provisionally"},
            {"while_open": "consent_waits"},
        ),
        ({"to": "agt-nobody"}, {"to": "not_a_member"}),
        ({"to": "role:boss"}, {"to": "unknown_role"}),
        ({"task_id": "tsk-nope"}, {"task_id": "unknown_task"}),
    ],
)
def test_requests_are_checked(
    owner: flow.Human, make_client: ClientFactory, body: dict[str, Any], fields: dict[str, str]
) -> None:
    agent = flow.agent(make_client, owner)
    assert ask(agent, **body).json()["error"]["details"]["fields"] == fields


def test_nine_options_are_too_many(owner: flow.Human) -> None:
    options = [{"id": f"o{i}", "label": f"Option {i}"} for i in range(9)]
    assert ask(owner, options=options).headers["Maity-Error"] == "invalid"


def test_urgent_is_for_answering_roles(owner: flow.Human, make_client: ClientFactory) -> None:
    worker = flow.agent(make_client, owner)
    refused = ask(worker, priority="urgent")
    assert refused.json()["error"]["details"]["fields"] == {
        "priority": "urgent_needs_requests_answer"
    }
    admin = flow.agent(make_client, owner, role="admin")
    assert ask(admin, priority="urgent").status_code == 201


def test_a_consent_goes_only_to_a_role_that_may_answer_it(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    worker = flow.agent(make_client, owner)
    reviewer = flow.agent(make_client, owner, role="reviewer")
    refused = ask(worker, **{"class": "consent", "to": reviewer.id})
    assert refused.json()["error"]["details"]["fields"] == {"to": "cannot_answer_consent"}
    assert ask(worker, **{"class": "consent", "to": "role:reviewer"}).status_code == 400
    for to in ("owner", "role:admin", "role:proxy", owner.id):
        assert ask(worker, **{"class": "consent", "to": to}).status_code == 201, to


def test_a_human_asks_the_owner_by_default(owner: flow.Human) -> None:
    assert asked(owner)["to"] == "owner"


def test_a_contract_request_goes_to_the_arbiter(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    assert asked(agent, **{"class": "contract"})["to"] == "role:admin"


def test_on_behalf_of_needs_requests_answer(owner: flow.Human, make_client: ClientFactory) -> None:
    worker = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    body = asked(admin, on_behalf_of=worker.id)
    assert body["on_behalf_of"]["member_id"] == worker.id
    assert ask(worker, on_behalf_of=admin.id).status_code == 403


def test_needs_in_session_names_the_member_and_its_session(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    session = agent.resume(harness="Claude Code").json()["session"]["id"]
    body = asked(agent, needs_in_session={"reason": "a production write", "member_id": agent.id})
    assert body["needs_in_session"] == {
        "reason": "a production write",
        "member_id": agent.id,
        "display_name": "An agent",
        "session_id": session,
        "harness": "Claude Code",
    }


# --- blocked cards ---------------------------------------------------------------------


def test_waiting_on_a_request_blocks_the_card_and_the_answer_restores_it(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    _claim(agent, card)
    request = asked(agent, task_id=card["id"])
    blocked = owner.get(f"/projects/maity/tasks/{card['id']}").json()
    assert (blocked["status"], blocked["blocked_by_request"]) == ("blocked", request["id"])
    assert request["task"] == {"id": card["id"], "title": "A card", "status": "blocked"}
    answer(owner, request, text="go ahead")
    restored = owner.get(f"/projects/maity/tasks/{card['id']}").json()
    assert (restored["status"], restored["blocked_by_request"]) == ("in_progress", None)


def test_a_request_after_the_report_restores_review(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    _claim(agent, card)
    agent.post(f"/projects/maity/tasks/{card['id']}/report", _report())
    request = asked(agent, task_id=card["id"])
    agent.post(f"/projects/maity/requests/{request['id']}/withdraw", {"reason": "found it"})
    assert owner.get(f"/projects/maity/tasks/{card['id']}").json()["status"] == "review"


def test_proceeding_provisionally_does_not_block(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    _claim(agent, card)
    asked(agent, task_id=card["id"], while_open="proceed_provisionally")
    assert owner.get(f"/projects/maity/tasks/{card['id']}").json()["status"] == "in_progress"


def test_cancel_and_release_clear_the_block(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    first, second = task(owner), task(owner)
    for card in (first, second):
        _claim(agent, card)
        asked(agent, task_id=card["id"])
    cancelled = owner.patch(f"/projects/maity/tasks/{first['id']}", {"status": "cancelled"}).json()
    assert (cancelled["status"], cancelled["blocked_by_request"]) == ("cancelled", None)
    released = agent.post(f"/projects/maity/tasks/{second['id']}/release", {}).json()
    assert (released["status"], released["blocked_by_request"]) == ("open", None)


# --- the inbox ---------------------------------------------------------------------------


def test_the_inbox_defaults_to_open_requests_addressed_to_me(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    mine = asked(agent)  # to the owner, its human
    asked(agent, to="role:admin")  # not mine
    done = asked(agent)
    answer(owner, done, text="x")
    items = owner.get("/projects/maity/requests").json()["items"]
    assert [r["id"] for r in items] == [mine["id"]]
    everything = owner.get("/projects/maity/requests?to=all&status=all").json()["items"]
    assert len(everything) == 3  # the owner answers every class


def test_without_requests_answer_to_all_is_mine_and_addressed(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    own = asked(a)
    to_a = asked(b, to=a.id)
    asked(b)  # to the owner: not a's business
    seen = {r["id"] for r in a.get("/projects/maity/requests?to=all").json()["items"]}
    assert seen == {own["id"], to_a["id"]}
    other = asked(b)
    assert a.get(f"/projects/maity/requests/{other['id']}").status_code == 403


def test_the_inbox_sorts_three_ways_and_pages(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    zed = flow.agent(make_client, owner, agent={"handle": "zed", "display_name": "Z"}, role="admin")
    abe = flow.agent(make_client, owner, agent={"handle": "abe", "display_name": "A"})
    low = asked(zed, priority="low")
    urgent = asked(zed, priority="urgent")
    normal = asked(abe)
    by_priority = [r["id"] for r in owner.get("/projects/maity/requests").json()["items"]]
    assert by_priority == [urgent["id"], normal["id"], low["id"]]
    by_date = [r["id"] for r in owner.get("/projects/maity/requests?sort=date").json()["items"]]
    assert by_date == [normal["id"], urgent["id"], low["id"]]
    by_agent = [r["id"] for r in owner.get("/projects/maity/requests?sort=agent").json()["items"]]
    assert by_agent == [normal["id"], low["id"], urgent["id"]]
    first = owner.get("/projects/maity/requests?limit=2").json()
    second = owner.get(f"/projects/maity/requests?limit=2&cursor={first['next_cursor']}").json()
    assert [r["id"] for r in first["items"] + second["items"]] == by_priority
    assert second["next_cursor"] is None
    assert owner.get("/projects/maity/requests?sort=loudest").headers["Maity-Error"] == "invalid"


def test_the_cross_project_inbox(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "sample")
    maity_agent = flow.agent(make_client, owner, "maity")
    sample_agent = flow.agent(make_client, owner, "sample")
    asked(maity_agent)
    asked(sample_agent, "sample", priority="high")
    stranger = flow.human(make_client, migrated, "stranger")
    flow.project(stranger, "elsewhere")
    asked(stranger, "elsewhere")
    for path in ("/requests", "/requests?scope=all"):
        items = owner.get(path).json()["items"]
        assert [(r["project"]["slug"], r["priority"]) for r in items] == [
            ("sample", "high"),
            ("maity", "normal"),
        ]
        assert items[0]["project"] == {"slug": "sample", "name": "Sample", "state": "build"}
        assert items[0]["asked_by"]["member_id"] == sample_agent.id
    counts = {p["slug"]: p["open_requests"] for p in owner.get("/me").json()["projects"]}
    assert counts == {"maity": 1, "sample": 1}
    assert maity_agent.get("/requests").headers["Maity-Error"] == "forbidden"


# --- answering --------------------------------------------------------------------------


def test_an_answer_is_recorded_and_delivered_with_the_whole_request(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    request = asked(agent, options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}])
    response = answer(owner, request, reply_id="b", text="b, because")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered" and body["answered_at"]
    assert body["answer"] | {"at": None} == {
        "reply_id": "b",
        "text": "b, because",
        "talk": False,
        "by": owner.id,
        "on_behalf_of": None,
        "at": None,
        "conversation_id": None,
    }
    event = _events(migrated, "request_answered")[-1]
    assert event.audience == [f"member:{agent.id}"]
    assert event.payload["answer"]["reply_id"] == "b" and event.payload["title"] == "Which?"
    again = answer(owner, request, text="again")
    assert again.status_code == 409 and again.headers["Maity-Error"] == "request_not_open"


def test_an_answer_names_one_reply_or_text_or_talk(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    request = asked(agent, options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}])
    assert answer(owner, request).json()["error"]["details"]["fields"] == {
        "answer": "reply_id_or_text_or_talk"
    }
    assert answer(owner, request, reply_id="c").json()["error"]["details"]["fields"] == {
        "reply_id": "not_a_reply"
    }
    both = answer(owner, request, talk=True, text="x")
    assert both.json()["error"]["details"]["fields"] == {"answer": "reply_id_or_text_or_talk"}


def test_a_consent_is_answered_only_by_requests_answer(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    worker = flow.agent(make_client, owner)
    reviewer = flow.agent(make_client, owner, role="reviewer")
    consent = asked(worker, **{"class": "consent", "to": "owner"})
    assert answer(reviewer, consent, reply_id="go").status_code == 403
    decision = asked(worker, to="role:reviewer")
    assert answer(reviewer, decision, text="mine to say").status_code == 200  # addressee, own right
    assert answer(owner, consent, reply_id="go").json()["answer"]["reply_id"] == "go"


def test_nobody_answers_its_own_request(owner: flow.Human, make_client: ClientFactory) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    own = asked(admin)
    assert answer(admin, own, text="yes").headers["Maity-Error"] == "self_answer"
    worker = flow.agent(make_client, owner)
    filed = asked(admin, on_behalf_of=worker.id, to=worker.id)
    assert answer(worker, filed, text="x").headers["Maity-Error"] == "self_answer"


def test_an_answer_for_someone_else_says_on_whose_behalf(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    proxy = flow.agent(make_client, owner, role="proxy")
    worker = flow.agent(make_client, owner)
    request = asked(worker, to="owner")
    body = answer(proxy, request, text="the owner is away; go").json()
    assert (body["answer"]["by"], body["answer"]["on_behalf_of"]) == (proxy.id, owner.id)


def test_talk_is_the_owning_humans_and_opens_the_conversation(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    request = asked(agent)
    admin = flow.agent(make_client, owner, role="admin")
    refused = answer(admin, request, talk=True)
    assert refused.json()["error"]["details"]["fields"] == {"talk": "only_the_owner_of_the_agent"}
    body = answer(owner, request, talk=True).json()
    assert body["answer"]["talk"] is True and body["answer"]["conversation_id"] == agent.id


def test_withdrawal_is_the_askers_or_an_answerers(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    request = asked(a)
    assert b.post(f"/projects/maity/requests/{request['id']}/withdraw", {}).status_code == 403
    body = a.post(f"/projects/maity/requests/{request['id']}/withdraw", {"reason": "solved"}).json()
    assert body["status"] == "withdrawn"
    event = _events(migrated, "request_withdrawn")[-1]
    assert event.audience == [f"member:{a.id}"] and event.payload["reason"] == "solved"
    assert answer(owner, request, text="late").headers["Maity-Error"] == "request_not_open"


def test_the_resume_packet_lists_requests(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    cursor = agent.resume().json()["events"]["cursor"]
    open_one = asked(agent)
    answered = asked(agent)
    answer(owner, answered, text="done")
    to_me = asked(admin, to=agent.id)
    packet = agent.resume(cursor=cursor).json()["requests"]
    assert [r["id"] for r in packet["mine_open"]] == [open_one["id"]]
    assert [r["id"] for r in packet["answered_since_cursor"]] == [answered["id"]]
    assert [r["id"] for r in packet["to_answer"]] == [to_me["id"]]
    assert packet["answered_since_cursor"][0]["answer"]["text"] == "done"


def test_a_card_stays_blocked_while_any_waiting_request_is_open(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    """PR #25: answering the first of two must not unblock work that waits on the second."""
    agent = flow.agent(make_client, owner)
    card = task(owner)
    _claim(agent, card)
    first = asked(agent, task_id=card["id"])
    second = asked(agent, task_id=card["id"])
    assert (
        owner.get(f"/projects/maity/tasks/{card['id']}").json()["blocked_by_request"] == first["id"]
    )
    answer(owner, first, text="yes")
    held = owner.get(f"/projects/maity/tasks/{card['id']}").json()
    assert (held["status"], held["blocked_by_request"]) == ("blocked", second["id"])
    agent.post(f"/projects/maity/requests/{second['id']}/withdraw", {})
    freed = owner.get(f"/projects/maity/tasks/{card['id']}").json()
    assert (freed["status"], freed["blocked_by_request"]) == ("in_progress", None)
