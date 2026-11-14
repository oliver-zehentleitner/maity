"""docs/api.md §20.8: redaction in a round, and every copy it reaches."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock, listening
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_jour_fixe_exchange import Round, kinds, rounds_path
from tests.test_jour_fixe_triage import TO_OWNER, decided, report


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
def round_(make_client: ClientFactory, migrated: Engine, now: list[datetime]) -> Round:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    found = Round(owner, make_client, migrated, now)
    assert found.statement().status_code == 201
    found.tick()
    return found


def redact(who: Any, round_: Round, target: str, reason: str = "a secret") -> Any:
    return who.post(rounds_path(round_.id, "/redact"), {"target": target, "reason": reason})


def answers_of(who: Any, round_: Round) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = who.get(rounds_path(round_.id, "/answers")).json()["items"]
    return found


def test_the_moderator_redacts_an_answer_and_its_readers_hear_of_it(round_: Round) -> None:
    named = next(a for a in answers_of(round_.lead, round_) if not a["anonymous"])
    done = redact(round_.lead, round_, f"answer:{named['id']}")
    assert done.status_code == 200, done.text
    by_lead = next(a for a in answers_of(round_.lead, round_) if a["id"] == named["id"])
    assert by_lead["went_badly"] is None and by_lead["redaction"]["by"] == round_.lead.id
    by_owner = next(a for a in answers_of(round_.owner, round_) if a["id"] == named["id"])
    assert by_owner["redaction"]["reason"] == "a secret"  # a human owner reads it
    [notice] = [e for e in kinds(round_.engine, "event_redacted") if e.payload.get("round_id")]
    assert notice.payload == {
        "round_id": round_.id,
        "target": f"answer:{named['id']}",
        "reason": "a secret",
    }
    assert {f"member:{round_.lead.id}", f"member:{round_.owner.id}"} <= set(notice.audience)
    assert f"member:{round_.member.id}" in notice.audience  # the named author
    again = redact(round_.lead, round_, f"answer:{named['id']}")
    assert (
        again.status_code == 200
        and len([e for e in kinds(round_.engine, "event_redacted") if e.payload.get("round_id")])
        == 1
    )


def test_who_may_redact_what(round_: Round) -> None:
    anonymous = next(a for a in answers_of(round_.owner, round_) if a["anonymous"])
    hidden = redact(round_.member, round_, f"answer:{anonymous['id']}")
    assert hidden.status_code == 404  # an agent that cannot read it: no such answer
    message = redact(round_.owner, round_, "post:p1")
    assert message.json()["error"]["details"]["fields"] == {"target": "redact_the_message"}
    assert redact(round_.owner, round_, "summary").status_code == 404  # no report yet
    owner_after = redact(round_.owner, round_, f"answer:{anonymous['id']}")
    assert owner_after.status_code == 200, owner_after.text  # after the window
    report(round_)
    agent = redact(round_.lead, round_, "summary")
    assert agent.json()["error"]["details"]["reason"] == "humans_only"


@pytest.mark.parametrize("anonymous", [False, True])
def test_a_proxy_cannot_redact_an_answer(
    round_: Round, make_client: ClientFactory, anonymous: bool
) -> None:
    # A human passes the humans-only gate; admin trust must still exclude the proxy role.
    proxy = flow.human(make_client, round_.engine, "the-proxy")
    with round_.engine.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(round_.engine, project_id, role="proxy", human_id=proxy.id)
    answer = next(a for a in answers_of(round_.owner, round_) if a["anonymous"] == anonymous)
    before = len(kinds(round_.engine, "event_redacted"))
    response = redact(proxy, round_, f"answer:{answer['id']}")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"
    assert next(a for a in answers_of(round_.owner, round_) if a["id"] == answer["id"]) == answer
    assert len(kinds(round_.engine, "event_redacted")) == before


def test_a_redacted_proposal_reaches_its_request_its_card_and_the_report_event(
    round_: Round,
) -> None:
    filed = report(round_, proposals=[decided(round_.owner), TO_OWNER]).json()
    [task_id], [request_id] = filed["tasks"], filed["requests"]
    for target in ("proposal:r1", "proposal:r2", "summary", "finding:f1"):
        done = redact(round_.owner, round_, target)
        assert done.status_code == 200, done.text
    shown = done.json()["report"]
    assert shown["summary"] is None and shown["summary_redaction"]["reason"] == "a secret"
    assert shown["findings"][0]["text"] is None
    assert all(p["title"] is None and p["redaction"] for p in shown["proposals"])
    by_agent = round_.lead.get(rounds_path(round_.id)).json()["report"]
    assert by_agent["summary_redaction"]["reason"] is None  # §8.5: not for an agent
    assert by_agent["proposals"][0]["redaction"]["reason"] is None
    card = round_.owner.get(f"/projects/maintainer/maity/tasks/{task_id}").json()
    assert card["title"] == "[redacted jour fixe proposal]"
    assert card["body"].startswith("[redacted]") and "Fewer surprises" not in card["body"]
    asked = round_.owner.get(f"/projects/maintainer/maity/requests/{request_id}").json()
    assert asked["title"] == "[redacted jour fixe proposal]" and asked["summary"] is None
    with round_.engine.connect() as conn:
        rows = conn.execute(select(t.event)).all()
        entries = conn.execute(
            select(t.card_history).where(t.card_history.c.card_id == task_id)
        ).all()
    # The moderator's own proposal lives nowhere else: no event carries its text now.
    text = " ".join(str(r.payload) for r in rows)
    assert "Pin the runner image" not in text and "Fewer surprises" not in text
    created = next(r for r in rows if r.kind == "request_created" and r.subject_id == request_id)
    assert created.redacted and created.payload["reason"] == "a secret"
    [reported] = [r for r in rows if r.kind == "jour_fixe_reported"]
    assert reported.redacted
    task_created = next(r for r in rows if r.kind == "task_created" and r.subject_id == task_id)
    assert task_created.payload["title"]["redacted"] is True
    assert all(e.redacted for e in entries if e.field == "created")


def test_a_redacted_statement_reaches_the_report_the_hub_built(round_: Round) -> None:
    round_.tick(timedelta(hours=13))  # no report in time: the hub builds one
    built = round_.get()["report"]
    [request_id] = [p["request_id"] for p in built["proposals"]]
    seq = round_.get()["statement"]["message_seq"]
    done = round_.owner.post(
        f"/projects/maintainer/maity/events/{seq}/redact", {"reason": "a secret"}
    )
    assert done.status_code == 200, done.text
    after = round_.get()["report"]
    assert after["findings"][0]["text"] is None and after["findings"][0]["redaction"]
    assert after["proposals"][0]["title"] is None
    asked = round_.owner.get(f"/projects/maintainer/maity/requests/{request_id}").json()
    assert asked["title"] == "[redacted jour fixe proposal]"


def test_a_proposal_drawn_from_a_statement_redacted_before_the_report_is_refused(
    round_: Round,
) -> None:
    seq = round_.get()["statement"]["message_seq"]
    done = round_.owner.post(
        f"/projects/maintainer/maity/events/{seq}/redact", {"reason": "a secret"}
    )
    assert done.status_code == 200, done.text
    refused = report(round_, proposals=[TO_OWNER])
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {
        "proposals": "redacted_statement_proposal"
    }
    with round_.engine.connect() as conn:
        assert (
            conn.execute(select(t.request).where(t.request.c.jour_fixe.isnot(None))).first() is None
        )
    assert round_.get()["status"] == "reporting"  # nothing was filed, the report is still due
    own = {**TO_OWNER, "statement_proposal_id": None}
    assert report(round_, proposals=[own]).status_code == 200  # the moderator's own text stands


def test_a_multiline_reason_is_found_in_every_history_entry(round_: Round) -> None:
    reason = "SECRET-LINE-ONE\nSECRET-LINE-TWO \\ and a backslash"
    proposal = {**decided(round_.owner), "reason": reason}
    [task_id] = report(round_, proposals=[proposal]).json()["tasks"]
    path = f"/projects/maintainer/maity/tasks/{task_id}"
    edited = round_.owner.patch(path, {"title": "Pinned by hand", "body": "rewritten"})
    assert edited.status_code == 200, edited.text
    assert redact(round_.owner, round_, "proposal:r1").status_code == 200
    with round_.engine.connect() as conn:
        entries = conn.execute(
            select(t.card_history).where(t.card_history.c.card_id == task_id)
        ).all()
    holding = [e for e in entries if e.field in ("created", "body")]
    assert holding and all(e.redacted for e in holding)
    assert "SECRET-LINE" not in " ".join(str((e.before, e.after)) for e in entries)
    card = round_.owner.get(path).json()
    assert card["title"] == "Pinned by hand"  # edited by a person: left as it is


def test_adopting_a_proposal_redacted_before_opens_a_placeholder_card(round_: Round) -> None:
    [request_id] = report(round_, proposals=[TO_OWNER]).json()["requests"]
    assert redact(round_.owner, round_, "proposal:r1").status_code == 200
    adopted = round_.owner.post(
        f"/projects/maintainer/maity/requests/{request_id}/answer", {"reply_id": "adopt"}
    )
    assert adopted.status_code == 200, adopted.text
    with round_.engine.connect() as conn:
        [card] = conn.execute(select(t.card).where(t.card.c.jour_fixe.isnot(None))).all()
    assert card.title == "[redacted jour fixe proposal]"
    assert card.body.startswith("[redacted]") and "minutes per run" not in card.body


def test_a_body_a_person_extended_is_left_and_every_rewritten_event_is_announced(
    round_: Round,
) -> None:
    [task_id] = report(round_, proposals=[decided(round_.owner)]).json()["tasks"]
    path = f"/projects/maintainer/maity/tasks/{task_id}"
    hub_body = round_.owner.get(path).json()["body"]
    extended = hub_body + "\nHuman clarification"
    assert round_.owner.patch(path, {"body": extended}).status_code == 200
    assert round_.owner.post(f"{path}/notes", {"body": "a note"}).status_code == 201
    assert redact(round_.owner, round_, "proposal:r1").status_code == 200
    card = round_.owner.get(path).json()
    assert card["body"] == extended  # a person's edit is left as it is
    assert card["title"] == "[redacted jour fixe proposal]"  # the title is still the hub's
    with round_.engine.connect() as conn:
        rows = conn.execute(select(t.event).order_by(t.event.c.seq)).all()
    notices = [r.payload.get("seq") for r in rows if r.kind == "event_redacted"]
    for kind in ("note_added", "task_created", "task_updated"):
        rewritten = [
            r.seq
            for r in rows
            if r.kind == kind
            and r.subject_id == task_id
            and "redacted" in str(r.payload)
            and not r.redacted
        ]
        assert all(seq in notices for seq in rewritten), (kind, rewritten, notices)
        assert len(set(notices)) == len(notices)  # each event announced once
    [note] = [r for r in rows if r.kind == "note_added"]
    assert note.payload["task"]["title"]["redacted"] is True and note.seq in notices


def _title_copies(who: Any) -> list[dict[str, Any]]:
    """The redacted `task.title` copies in the events `who` reads on `GET /events`."""
    listed = who.get("/projects/maintainer/maity/events?after=0&limit=200")
    assert listed.status_code == 200, listed.text
    titles = [(e["payload"] or {}).get("task", {}).get("title") for e in listed.json()["items"]]
    return [v for v in titles if isinstance(v, dict) and v.get("redacted") is True]


def test_a_redacted_title_copied_into_events_shows_its_reason_per_reader(
    round_: Round, make_client: ClientFactory
) -> None:
    """§20.8, §8.5: the `task.title` a redaction rewrites in `note_added`, `note_edited` and
    `mentioned` shows its reason as the card's history does: to the human owners and admins
    and the redactor, `null` to agents and every other reader."""
    with round_.engine.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    ada = flow.human(make_client, round_.engine, "ada")  # a human admin: she redacts
    factory.membership(round_.engine, project_id, "admin", human_id=ada.id)
    bo = flow.human(make_client, round_.engine, "bo")  # a plain member, mentioned on the card
    factory.membership(round_.engine, project_id, "member", human_id=bo.id)
    [task_id] = report(round_, proposals=[decided(round_.owner)]).json()["tasks"]
    path = f"/projects/maintainer/maity/tasks/{task_id}"
    body = round_.owner.get(path).json()["body"] + "\n@bo"
    assert round_.owner.patch(path, {"body": body}).status_code == 200
    note = round_.owner.post(f"{path}/notes", {"body": "a note"})
    assert note.status_code == 201, note.text
    edited = round_.owner.patch(
        f"{path}/notes/{note.json()['id']}", {"body": "an edited note", "base_version": 1}
    )
    assert edited.status_code == 200, edited.text
    assert redact(ada, round_, "proposal:r1").status_code == 200
    with round_.engine.connect() as conn:
        rewritten = {
            r.kind
            for r in conn.execute(select(t.event)).all()
            if isinstance((r.payload or {}).get("task"), dict)
            and isinstance(r.payload["task"].get("title"), dict)
        }
    assert rewritten == {"mentioned", "note_added", "note_edited"}
    readers: list[tuple[Any, str | None]] = [
        (round_.owner, "a secret"),
        (ada, "a secret"),  # an admin, and the redactor
        (round_.lead, None),  # an agent with admin trust
        (round_.member, None),
        (bo, None),
    ]
    for who, seen in readers:
        marks = _title_copies(who)
        assert {m["reason"] for m in marks} <= {seen}, who
        assert all(m["by"] == ada.id and m["at"] for m in marks), who
    for who in (round_.owner, ada, bo):  # each reads at least one copy
        assert _title_copies(who), who
    assert any(_title_copies(who) for who in (round_.lead, round_.member))  # an agent reads one
    for who in (round_.lead, round_.member, bo):
        listed = who.get("/projects/maintainer/maity/events?after=0&limit=200").text
        assert "a secret" not in listed


def test_a_mention_of_a_redacted_title_reaches_a_plain_member_without_the_reason(
    round_: Round, make_client: ClientFactory
) -> None:
    """§20.8: `mentioned` keeps a copy of the card's title; once redacted, the mentioned
    member reads its tombstone without the reason, in the event and in the bell."""
    with round_.engine.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    bo = flow.human(make_client, round_.engine, "bo")
    factory.membership(round_.engine, project_id, "member", human_id=bo.id)
    [task_id] = report(round_, proposals=[decided(round_.owner)]).json()["tasks"]
    path = f"/projects/maintainer/maity/tasks/{task_id}"
    body = round_.owner.get(path).json()["body"] + "\n@bo"
    assert round_.owner.patch(path, {"body": body}).status_code == 200
    assert redact(round_.owner, round_, "proposal:r1").status_code == 200
    listed = bo.get("/projects/maintainer/maity/events?after=0&limit=200")
    [mentioned] = [e for e in listed.json()["items"] if e["kind"] == "mentioned"]
    title = mentioned["payload"]["task"]["title"]
    assert title["redacted"] is True and title["by"] == round_.owner.id
    assert title["reason"] is None and "a secret" not in listed.text
    owners = round_.owner.get("/projects/maintainer/maity/events?after=0&limit=200").json()
    copies = [e["payload"]["task"]["title"] for e in owners["items"] if e["kind"] == "mentioned"]
    assert all(c["reason"] == "a secret" for c in copies)  # empty when not in its audience
    bell = bo.get("/me/notifications")
    assert bell.status_code == 200, bell.text
    assert "mention" in [i["kind"] for i in bell.json()["items"]]
    assert "a secret" not in bell.text and "'redacted'" not in bell.text
