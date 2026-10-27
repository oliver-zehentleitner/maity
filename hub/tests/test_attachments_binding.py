"""docs/api.md §8.7: naming attachments in a message, who reads them then, redaction, and the
project view's quota."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import attachments
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_attachments import put


@pytest.fixture(autouse=True)
def _fresh_limits() -> Iterator[None]:
    attachments.UPLOADS.reset()
    attachments.VOLUME.reset()
    yield
    attachments.UPLOADS.reset()
    attachments.VOLUME.reset()


@pytest.fixture
def blobs(tmp_path: Path) -> Path:
    folder = tmp_path / "blobs"
    folder.mkdir()
    return folder


@pytest.fixture
def stored(make_client: ClientFactory, blobs: Path) -> ClientFactory:
    def factory(**overrides: Any) -> Any:
        return make_client(attachment_dir=blobs, **overrides)

    return factory


@pytest.fixture
def owner(stored: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(stored, migrated)
    flow.project(owner, "maity")
    return owner


def say(who: Any, to: str, body: str, ids: list[str] | None = None, type_: str = "notice") -> Any:
    message: dict[str, Any] = {"kind": "message", "type": type_, "to": to, "body": body}
    if ids is not None:
        message["attachments"] = ids
    return who.post("/projects/maity/events", message)


def upload(who: Any, name: str = "log.txt", data: bytes = b"line") -> str:
    done = put(who, name, data)
    assert done.status_code == 201, done.text
    return str(done.json()["id"])


def test_a_message_names_attachments_in_order_and_carries_their_metadata(
    stored: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    first, second = upload(agent, "one.txt", b"1"), upload(agent, "two.txt", b"22")
    sent = say(agent, owner.id, "see files", [second, first])
    assert sent.status_code == 201, sent.text
    shown = sent.json()["payload"]["attachments"]
    assert [a["id"] for a in shown] == [second, first]  # in the order named
    assert set(shown[0]) == {"id", "name", "size", "type", "kind", "width", "height"}
    assert shown[0]["name"] == "two.txt" and shown[0]["size"] == 2
    with migrated.connect() as conn:
        rows = conn.execute(select(t.attachment)).all()
    assert {r.message_seq for r in rows} == {sent.json()["seq"]}
    # The owner reads the message, so reads the attachment; the sender too.
    path = f"/projects/maity/attachments/{first}"
    assert owner.get(path).json()["message_seq"] == sent.json()["seq"]
    assert owner.get(f"{path}/content").content == b"1"
    assert agent.get(f"{path}/content").content == b"1"
    # It is no longer pending.
    assert owner.get("/projects/maity/attachments?status=pending").json()["items"] == []


def test_only_those_who_read_the_message_read_its_attachments(
    stored: ClientFactory, owner: flow.Human
) -> None:
    sender, addressee, bystander = (flow.agent(stored, owner) for _ in range(3))
    named = upload(sender)
    assert say(sender, addressee.id, "for you", [named]).status_code == 201
    path = f"/projects/maity/attachments/{named}"
    assert addressee.get(f"{path}/content").status_code == 200
    assert owner.get(path).status_code == 200  # an owner reads every project message
    assert bystander.get(path).status_code == 404
    assert bystander.get(f"{path}/content").status_code == 404


def test_a_message_may_be_attachments_alone_and_still_needs_text_or_files(
    stored: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(stored, owner)
    named = upload(agent)
    assert say(agent, owner.id, "", [named]).status_code == 201
    bare = say(agent, owner.id, "")
    assert bare.status_code == 400
    assert "body" in bare.json()["error"]["details"]["fields"]
    assert say(agent, owner.id, "", []).status_code == 400


def test_an_attachment_that_cannot_be_named_refuses_the_post_and_stays_pending(
    stored: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    mine, other = flow.agent(stored, owner), flow.agent(stored, owner)
    own, theirs = upload(mine), upload(other)
    refused = say(mine, owner.id, "x", [own, theirs, "att-doesnotexist"])
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"]["attachments"] == {
        theirs: "unknown",
        "att-doesnotexist": "unknown",
    }
    with migrated.connect() as conn:
        assert {r.message_seq for r in conn.execute(select(t.attachment)).all()} == {None}
    assert say(mine, owner.id, "ok", [own]).status_code == 201
    again = say(mine, owner.id, "twice", [own])
    assert again.json()["error"]["details"]["fields"]["attachments"] == {own: "already_attached"}
    other_one = upload(mine, "o.txt")
    twice = say(mine, owner.id, "dup", [other_one, other_one])
    assert twice.json()["error"]["details"]["fields"]["attachments"] == {
        other_one: "already_attached"
    }


def test_a_post_that_fails_for_another_reason_leaves_the_uploads_pending(
    stored: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(stored, owner)
    named = upload(agent)
    assert say(agent, "role:nonsense", "x", [named]).status_code == 400
    assert agent.get("/projects/maity/attachments?status=pending").json()["items"][0]["id"] == named


def test_at_most_ten_attachments_a_message(stored: ClientFactory, owner: flow.Human) -> None:
    agent = flow.agent(stored, owner)
    ids = [f"att-{n:012d}" for n in range(11)]
    refused = say(agent, owner.id, "x", ids)
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {"attachments": "too_many"}


def test_naming_attachments_in_a_closed_project_or_without_a_store_is_refused(
    stored: ClientFactory, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    named = upload(agent)
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(state="archived"))
    closed = say(agent, owner.id, "x", [named])
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "project_closed"
    assert say(agent, owner.id, "plain text").status_code == 201  # text alone still goes
    # A hub with the store off refuses a message that names one, whatever the id.
    bare = make_client()
    again = bare.post(
        "/api/v1/projects/maity/events",
        json={"kind": "message", "type": "notice", "to": "all", "body": "x", "attachments": ["a"]},
        headers={**agent.auth, **agent.key()},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "attachments_not_configured"


def test_a_chat_message_carries_attachments_to_its_two_parties_only(
    stored: ClientFactory, owner: flow.Human
) -> None:
    agent, stranger = flow.agent(stored, owner), flow.agent(stored, owner)
    named = upload(owner, "plan.txt", b"plan")
    sent = owner.post(
        f"/projects/maity/conversations/{agent.id}/messages",
        {"body": "", "attachments": [named]},
    )
    assert sent.status_code == 201, sent.text
    assert [a["id"] for a in sent.json()["attachments"]] == [named]
    path = f"/projects/maity/attachments/{named}"
    assert agent.get(f"{path}/content").content == b"plan"  # the other party
    assert owner.get(path).status_code == 200
    assert stranger.get(path).status_code == 404
    listed = owner.get(f"/projects/maity/conversations/{agent.id}/messages").json()["items"]
    assert [a["id"] for a in listed[-1]["attachments"]] == [named]


def test_redacting_a_message_tombstones_its_attachments_and_removes_their_bytes(
    stored: ClientFactory, owner: flow.Human, blobs: Path, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    named = upload(agent, "secret.txt", b"top secret")
    sent = say(agent, owner.id, "oops", [named]).json()
    assert (
        owner.post(f"/projects/maity/events/{sent['seq']}/redact", {"reason": "x"}).status_code
        == 200
    )
    with migrated.connect() as conn:
        row = conn.execute(select(t.attachment)).one()
        kinds = conn.execute(select(t.event.c.kind)).scalars().all()
    assert row.deleted_reason == "redacted" and row.deleted_by == owner.id and row.deleted_at
    assert row.message_seq == sent["seq"]
    assert not list(blobs.glob("*/*"))  # the bytes went with the commit
    path = f"/projects/maity/attachments/{named}"
    for who in (owner, agent):
        assert who.get(path).status_code == 404  # a redacted message has none readable
        assert who.get(f"{path}/content").status_code == 404
    assert "attachment_deleted" not in kinds  # `event_redacted` covers them


def test_the_project_view_shows_the_quota_to_a_project_admin_only(
    stored: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    upload(owner, "a.bin", b"x" * 100)
    upload(agent, "b.bin", b"y" * 50)
    view = owner.get("/projects/maity").json()
    assert view["attachments"] == {"used": 150, "quota": 1024**3}
    assert agent.get("/projects/maity").json()["attachments"] is None
    listing = owner.get("/projects").json()["items"][0]
    assert listing["attachments"]["used"] == 150
