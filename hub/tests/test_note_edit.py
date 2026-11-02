"""docs/api.md §6.16 editing a note: the author edits in place, the old text is gone from
everything the hub keeps (context/cards.md 0e6b3b31)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_board import events, fields_of, note, owner  # noqa: F401  (owner: fixture)
from tests.test_tasks import task

OLD = "the token is hunter2-old-text"


def edit(who: Any, card: dict[str, Any], posted: dict[str, Any], **body: Any) -> Any:
    return who.patch(f"/projects/maintainer/maity/tasks/{card['id']}/notes/{posted['id']}", body)


def everything_stored(engine: Engine) -> str:
    """Every event payload and every note row, as one text to search."""
    with engine.connect() as conn:
        payloads = [r.payload for r in conn.execute(select(t.event))]
        notes = [dict(r._mapping) for r in conn.execute(select(t.card_note))]
    return json.dumps([payloads, notes], default=str)


def test_the_author_edits_and_the_old_text_is_in_no_event(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    holder = flow.agent(make_client, owner)
    writer = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    card = task(owner)
    holder.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {})
    note(other, card, "an unrelated remark")
    posted = note(writer, card, OLD).json()
    first = edit(writer, card, posted, body="corrected, see @maintainer")
    assert first.status_code == 200, first.text
    again = edit(writer, card, posted, body="corrected twice, see @maintainer")
    assert again.status_code == 200, again.text
    shown = again.json()
    assert shown["body"] == "corrected twice, see @maintainer"
    assert [m["member_id"] for m in shown["mentions"]] == [owner.id]
    assert shown["edited"]["by"]["member_id"] == writer.id
    assert shown["edited"]["reason"] is None and shown["edited"]["at"]
    assert shown["state"] == "open" and shown["created_at"] == posted["created_at"]
    # The note's note_added and the first note_edited now carry the note as it is now.
    added = events(migrated, "note_added")[-1]
    edits = events(migrated, "note_edited")
    assert added.payload["note"] == shown
    assert [e.payload["note"] for e in edits] == [shown, shown]
    assert set(edits[-1].audience) == {
        f"member:{writer.id}",
        f"member:{holder.id}",
        f"member:{owner.id}",
        f"member:{other.id}",
    }
    assert edits[-1].payload["task"]["id"] == card["id"]
    # Nowhere the hub keeps or serves.
    assert OLD not in everything_stored(migrated)
    listed = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}/notes").json()
    assert OLD not in json.dumps(listed)
    stream = owner.get("/projects/maintainer/maity/events?after=0&limit=200").json()
    assert OLD not in json.dumps(stream)
    found = owner.get("/projects/maintainer/maity/tasks?q=hunter2").json()
    assert found["items"] == []


def test_an_agent_cannot_edit_anothers_note_whatever_its_role(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    writer = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    card = task(owner)
    posted = note(writer, card, OLD).json()
    refused = edit(admin, card, posted, body="rewritten", reason="cleanup")
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "not_your_note"
    by_owner = edit(owner, card, posted, body="rewritten")
    assert fields_of(by_owner) == {"reason": "required"}
    assert events(migrated, "note_edited") == []
    done = edit(owner, card, posted, body="rewritten", reason="a secret in it")
    assert done.status_code == 200, done.text
    assert done.json()["edited"]["by"]["member_id"] == owner.id
    assert done.json()["edited"]["reason"] == "a secret in it"
    assert done.json()["author"]["member_id"] == writer.id


def test_a_human_without_events_admin_edits_only_their_own(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    member = flow.human(make_client, migrated, "a-member")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, role="coder", human_id=member.id)
    card = task(owner)
    theirs = note(owner, card).json()
    mine = note(member, card, OLD).json()
    refused = edit(member, card, theirs, body="mine now", reason="because")
    assert refused.status_code == 403, refused.text
    assert edit(member, card, mine, body="fixed").status_code == 200


def test_a_redacted_note_is_not_edited_and_a_redaction_reaches_the_edits(
    owner: flow.Human, migrated: Engine  # noqa: F811
) -> None:
    card = task(owner)
    posted = note(owner, card, "first").json()
    assert edit(owner, card, posted, body=OLD).status_code == 200
    redacted = owner.post(
        f"/projects/maintainer/maity/tasks/{card['id']}/notes/{posted['id']}/redact",
        {"reason": "secret"},
    )
    assert redacted.status_code == 200, redacted.text
    assert redacted.json()["edited"] is None
    assert OLD not in everything_stored(migrated)
    assert events(migrated, "note_added")[-1].payload["note"]["edited"] is None
    assert events(migrated, "note_edited")[-1].payload["note"]["body"]["reason"] == "secret"
    refused = edit(owner, card, posted, body="again")
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["reason"] == "redacted"


def test_on_a_closed_card_the_edit_reaches_the_author_and_the_newly_mentioned(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    holder = flow.agent(make_client, owner)
    writer = flow.agent(make_client, owner)
    card = task(owner)
    holder.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {})
    posted = note(writer, card, "see @maintainer").json()
    handle = posted["author"]["handle"]
    owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "cancelled"})
    done = edit(writer, card, posted, body=f"see @maintainer and @{handle}")
    assert done.status_code == 200, done.text
    edited = events(migrated, "note_edited")[-1]
    assert edited.audience == [f"member:{writer.id}"]  # the owner was mentioned before
    assert edited.payload["task"]["status"] == "cancelled"
    assert edit(writer, card, posted, body="see nobody").status_code == 200
    assert events(migrated, "note_edited")[-1].audience == [f"member:{writer.id}"]


def test_a_closed_project_refuses_an_edit(owner: flow.Human) -> None:  # noqa: F811
    card = task(owner)
    posted = note(owner, card).json()
    owner.patch("/projects/maintainer/maity", {"state": "archived", "reason": "done"})
    refused = edit(owner, card, posted, body="changed")
    assert refused.json()["error"]["code"] == "project_closed"


def test_an_edit_keeps_the_body_rules(owner: flow.Human) -> None:  # noqa: F811
    card = task(owner)
    posted = note(owner, card).json()
    assert fields_of(edit(owner, card, posted, body="x" * 4097)) == {"body": "too_long"}
    assert fields_of(edit(owner, card, posted, body="x", mentions=[])) == {"mentions": "read_only"}
    assert edit(owner, card, posted, body="x", reason="r" * 501).status_code == 400


def test_a_redacted_notes_reason_reaches_only_owners_admins_and_the_redactor(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    agent = flow.agent(make_client, owner, role="admin")
    member = flow.human(make_client, migrated, "a-member")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, role="coder", human_id=member.id)
    card = task(owner)
    posted = note(agent, card, "contains hunter2 @maintainer").json()
    path = f"/projects/maintainer/maity/tasks/{card['id']}/notes"
    assert owner.post(f"{path}/{posted['id']}/redact", {"reason": "a password"}).status_code == 200

    def shown(who: Any) -> dict[str, Any]:
        items = who.get(f"{path}?state=all").json()["items"]
        body: dict[str, Any] = items[0]["body"]
        return body

    def in_events(who: Any) -> Any:
        listed = who.get("/projects/maintainer/maity/events?after=0&limit=200").json()
        added = [e for e in listed["items"] if e["kind"] == "note_added"]
        return added[-1]["payload"]["note"]["body"]

    assert shown(owner)["reason"] == "a password"  # the owner, who redacted
    assert in_events(owner)["reason"] == "a password"
    for reader in (agent, member):
        assert shown(reader)["reason"] is None and shown(reader)["redacted"] is True
        assert shown(reader)["by"] and shown(reader)["at"]
    assert in_events(agent)["reason"] is None
    assert "a password" not in json.dumps(agent.get(f"{path}?state=all").json())


def test_the_reason_stays_hidden_in_an_edit_event_and_in_a_replay(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    path = f"/projects/maintainer/maity/tasks/{card['id']}/notes"
    keyed = agent.auth | {"Idempotency-Key": "note-reason-replay-0001"}
    body = {"body": "first words"}
    posted = agent.client.post(f"/api/v1{path}", json=body, headers=keyed)
    assert posted.status_code == 201, posted.text
    note_id = posted.json()["id"]
    assert agent.patch(f"{path}/{note_id}", {"body": "hunter2 by mistake"}).status_code == 200
    assert owner.post(f"{path}/{note_id}/redact", {"reason": "a password"}).status_code == 200
    # The tombstone inside the edit event, as the agent and the owner read it (§6.16, §8.5).
    for who, seen in ((agent, None), (owner, "a password")):
        listed = who.get("/projects/maintainer/maity/events?after=0&limit=200").json()["items"]
        edited = [e for e in listed if e["kind"] == "note_edited"][-1]
        assert edited["payload"]["note"]["body"]["reason"] == seen
    # A replay of the agent's own post shows the note as the agent may read it now.
    again = agent.client.post(f"/api/v1{path}", json=body, headers=keyed)
    assert again.status_code == 201, again.text
    assert again.json()["body"]["redacted"] is True and again.json()["body"]["reason"] is None
    assert "a password" not in again.text
