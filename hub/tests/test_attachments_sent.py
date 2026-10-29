"""docs/api.md §8.7: deleting an attachment a message carries, who reads it as an owner outside
the project, the sweep, and a removed member's pending uploads."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, delete, select, update

from maity_hub import attachment_store, attachments, clock, events
from maity_hub import tables as t
from maity_hub.errors import ApiError
from tests import flow
from tests.conftest import ClientFactory
from tests.test_attachments import put

BASE = "/projects/maintainer/maity/conversations"


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


def upload(who: Any, name: str = "f.txt", data: bytes = b"data") -> str:
    done = put(who, name, data)
    assert done.status_code == 201, done.text
    return str(done.json()["id"])


def send_raw(who: Any, to: str, ids: list[str]) -> Any:
    return who.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": to, "body": "files", "attachments": ids},
    )


def send(who: Any, to: str, ids: list[str]) -> dict[str, Any]:
    done = who.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": to, "body": "files", "attachments": ids},
    )
    assert done.status_code == 201, done.text
    shown: dict[str, Any] = done.json()
    return shown


def drop(who: Any, attachment_id: str) -> Any:
    path = f"/api/v1/projects/maintainer/maity/attachments/{attachment_id}"
    if isinstance(who, flow.Human):
        return who.client.delete(path, headers={"X-CSRF-Token": who.csrf})
    return who.client.delete(path, headers={**who.auth, **who.key()})


def events_of(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(select(t.event).where(t.event.c.kind == kind)))


def test_the_sender_deletes_what_it_sent_and_the_row_stays_as_a_tombstone(
    stored: ClientFactory, owner: flow.Human, blobs: Path, migrated: Engine
) -> None:
    agent, reader = flow.agent(stored, owner), flow.agent(stored, owner)
    named = upload(agent, "log.txt", b"the log")
    sent = send(agent, reader.id, [named])
    gone = drop(agent, named)
    assert gone.status_code == 200, gone.text
    body = gone.json()
    assert body["deleted_reason"] == "deleted" and body["deleted_by"] == agent.id
    assert body["deleted_at"] and body["name"] == "log.txt"  # the tombstone keeps the metadata
    assert not list(blobs.glob("*/*"))
    path = f"/projects/maintainer/maity/attachments/{named}"
    assert reader.get(path).json()["deleted_reason"] == "deleted"  # readers see the tombstone
    assert reader.get(f"{path}/content").status_code == 404
    [notice] = events_of(migrated, "attachment_deleted")
    assert notice.payload == {
        "attachment_id": named,
        "message_seq": sent["seq"],
        "reason": "deleted",
        "by": agent.id,
    }
    assert notice.audience == sent["audience"] and "attachment_deleted" in events.NON_WAKING
    again = drop(agent, named)  # deleting a deleted one answers with the tombstone (§1.5)
    assert again.status_code == 200 and again.json()["deleted_at"] == body["deleted_at"]
    assert len(events_of(migrated, "attachment_deleted")) == 1


def test_an_admin_human_deletes_a_project_messages_file_and_an_agent_never_another_s(
    stored: ClientFactory, owner: flow.Human
) -> None:
    sender, reader = flow.agent(stored, owner), flow.agent(stored, owner)
    named = upload(sender)
    send(sender, reader.id, [named])
    refused = drop(reader, named)  # the addressee reads it, and may not delete it
    assert (
        refused.status_code == 403 and refused.json()["error"]["details"]["reason"] == "humans_only"
    )
    assert drop(owner, named).status_code == 200


def test_a_stranger_cannot_even_tell_that_an_attachment_exists(
    stored: ClientFactory, owner: flow.Human
) -> None:
    sender, reader, stranger = (flow.agent(stored, owner) for _ in range(3))
    named = upload(sender)
    send(sender, reader.id, [named])
    assert drop(stranger, named).status_code == 404


def test_the_human_party_of_a_direct_chat_deletes_and_the_agent_party_does_not(
    stored: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(stored, owner)
    theirs = upload(agent, "from-agent.txt")
    sent = agent.post(f"{BASE}/{agent.id}/messages", {"body": "", "attachments": [theirs]})
    assert sent.status_code == 201, sent.text
    mine = upload(owner, "from-owner.txt")
    assert (
        owner.post(f"{BASE}/{agent.id}/messages", {"body": "", "attachments": [mine]}).status_code
        == 201
    )
    refused = drop(agent, mine)  # an agent never deletes what a human sent
    assert (
        refused.status_code == 403 and refused.json()["error"]["details"]["reason"] == "humans_only"
    )
    assert drop(owner, theirs).status_code == 200  # the human party deletes the agent's
    assert drop(owner, mine).status_code == 200


def test_in_a_group_chat_a_human_participant_deletes_and_an_observer_does_not(
    stored: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from tests.factory import membership
    from tests.test_group_chats import project_id

    agent = flow.agent(stored, owner)
    other = flow.human(stored, migrated, "colleague")
    membership(migrated, project_id(migrated), "member", human_id=other.id)
    chat = owner.post(BASE, {"title": "files", "participants": [agent.id, other.id]}).json()
    named = upload(agent, "shared.txt")
    posted = agent.post(f"{BASE}/{chat['id']}/messages", {"body": "see", "attachments": [named]})
    assert posted.status_code == 201, posted.text
    assert other.get(f"/projects/maintainer/maity/attachments/{named}").status_code == 200
    gone = drop(other, named)  # a human in the chat now
    assert gone.status_code == 200 and gone.json()["deleted_reason"] == "deleted"
    [notice] = events_of(migrated, "attachment_deleted")
    assert notice.conversation_id == chat["id"]


def test_an_owner_outside_the_project_never_reads_a_project_messages_file(
    stored: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    sender = flow.agent(stored, owner)
    named = upload(sender)
    sent = send(sender, "all", [named])
    with migrated.connect() as conn:
        project = conn.execute(select(t.project)).one()
        outside = SimpleNamespace(project=project, principal_id="hum-someone-else")
        assert attachments.message_readable(conn, outside, sent["seq"]) is False


def test_the_sweep_removes_expired_uploads_stale_bytes_and_stray_blobs_only(
    stored: ClientFactory, owner: flow.Human, blobs: Path, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    store = attachment_store.LocalStore(blobs)
    fresh, old, sent_one, deleted_one = (upload(agent, f"{n}.txt") for n in "abcd")
    send(agent, owner.id, [sent_one, deleted_one])
    assert drop(agent, deleted_one).status_code == 200
    with migrated.begin() as conn:
        conn.execute(
            update(t.attachment)
            .where(t.attachment.c.id == old)
            .values(uploaded_at=clock.now() - timedelta(hours=25))
        )
        project = conn.execute(select(t.project.c.id)).scalar_one()
    # A blob the tombstoned row still has (its removal failed), and two strays.
    store.put(attachment_store.key_of(project, deleted_one), b"left behind")
    store.put(attachment_store.key_of(project, "att-stray-young"), b"young")
    store.put(attachment_store.key_of(project, "att-stray-old"), b"old")
    long_ago = time.time() - attachments.BLOB_GRACE - 60
    os.utime(blobs / project / "att-stray-old", (long_ago, long_ago))
    done = attachments.sweep(migrated, store)
    assert done == {"expired": 1, "tombstoned": 1, "orphans": 1}
    left = sorted(p.name for p in (blobs / project).iterdir())
    assert left == sorted([fresh, sent_one, "att-stray-young"])  # a young stray may be in flight
    with migrated.connect() as conn:
        ids = set(conn.execute(select(t.attachment.c.id)).scalars())
    assert old not in ids and {fresh, sent_one, deleted_one} <= ids
    assert attachments.sweep(migrated, store) == {"expired": 0, "tombstoned": 0, "orphans": 0}


def test_removing_a_member_drops_its_pending_uploads_and_keeps_what_it_sent(
    stored: ClientFactory, owner: flow.Human, blobs: Path, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    pending, sent_one = upload(agent, "p.txt"), upload(agent, "s.txt")
    send(agent, owner.id, [sent_one])
    assert owner.delete(f"/projects/maintainer/maity/members/{agent.id}").status_code == 200
    with migrated.connect() as conn:
        rows = {r.id: r for r in conn.execute(select(t.attachment))}
    assert pending not in rows and sent_one in rows
    store = attachment_store.LocalStore(blobs)
    assert attachments.sweep(migrated, store)["orphans"] == 0  # too young to be sure it is a stray
    (stale,) = (p for p in blobs.glob("*/*") if p.name == pending)
    long_ago = time.time() - attachments.BLOB_GRACE - 60
    os.utime(stale, (long_ago, long_ago))
    assert attachments.sweep(migrated, store)["orphans"] == 1
    assert sorted(p.name for p in blobs.glob("*/*")) == [sent_one]  # the pending bytes went


def test_a_download_that_loses_the_race_with_a_redaction_is_not_found_not_a_failure(
    stored: ClientFactory, owner: flow.Human, monkeypatch: pytest.MonkeyPatch, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    named = upload(agent, "race.txt", b"bytes")
    sent = send(agent, owner.id, [named])
    real = attachment_store.LocalStore.get

    def redacted_meanwhile(self: Any, key: str) -> bytes | None:
        # The redaction commits between the read of the row and the read of the bytes.
        done = owner.post(
            f"/projects/maintainer/maity/events/{sent['seq']}/redact", {"reason": "x"}
        )
        assert done.status_code == 200, done.text
        return real(self, key)

    monkeypatch.setattr(attachment_store.LocalStore, "get", redacted_meanwhile)
    answer = owner.get(f"/projects/maintainer/maity/attachments/{named}/content")
    assert answer.status_code == 404, answer.text
    assert answer.json()["error"]["code"] == "not_found"


def test_a_missing_blob_of_a_live_attachment_is_still_a_failure(
    stored: ClientFactory, owner: flow.Human, blobs: Path
) -> None:
    named = upload(owner, "gone.txt", b"bytes")
    [blob] = blobs.glob("*/*")
    blob.unlink()  # the row says it is there; the bytes are not
    answer = owner.get(f"/projects/maintainer/maity/attachments/{named}/content")
    assert answer.status_code == 500 and answer.json()["error"]["code"] == "internal"


def test_redacting_a_group_chat_message_tombstones_its_attachments(
    stored: ClientFactory, owner: flow.Human, blobs: Path, migrated: Engine
) -> None:
    from tests.factory import membership
    from tests.test_group_chats import project_id

    agent = flow.agent(stored, owner)
    other = flow.human(stored, migrated, "colleague")
    membership(migrated, project_id(migrated), "member", human_id=other.id)
    chat = owner.post(BASE, {"title": "files", "participants": [agent.id, other.id]}).json()
    named = upload(agent, "shared.txt", b"shared")
    posted = agent.post(f"{BASE}/{chat['id']}/messages", {"body": "see", "attachments": [named]})
    assert posted.status_code == 201, posted.text
    done = other.post(
        f"/projects/maintainer/maity/events/{posted.json()['seq']}/redact", {"reason": "x"}
    )
    assert done.status_code == 200, done.text  # a human in the chat redacts there
    with migrated.connect() as conn:
        row = conn.execute(select(t.attachment)).one()
    assert row.deleted_reason == "redacted" and row.deleted_by == other.id
    assert not list(blobs.glob("*/*"))
    assert agent.get(f"/projects/maintainer/maity/attachments/{named}").status_code == 404


def test_naming_an_attachment_a_second_message_took_meanwhile_refuses_the_post(
    stored: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    named = upload(agent, "twice.txt")
    first = send(agent, owner.id, [named])
    with migrated.begin() as conn:  # the later of two posts that both passed the check
        row = conn.execute(select(t.attachment)).one()
        with pytest.raises(ApiError) as refused:
            attachments.attach(conn, [row], first["seq"] + 1)
    assert refused.value.details["fields"]["attachments"] == {named: "unknown"}
    with migrated.connect() as conn:
        assert conn.execute(select(t.attachment.c.message_seq)).scalar() == first["seq"]


def test_the_sweep_leaves_a_candidate_a_message_bound_since_it_was_chosen(
    stored: ClientFactory, owner: flow.Human, blobs: Path, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    store = attachment_store.LocalStore(blobs)
    taken, idle = upload(agent, "taken.txt", b"sent"), upload(agent, "idle.txt", b"idle")
    with migrated.begin() as conn:
        conn.execute(update(t.attachment).values(uploaded_at=clock.now() - timedelta(hours=25)))
        candidates = conn.execute(
            select(t.attachment.c.id, t.attachment.c.project_id)
        ).all()  # both look expired when the sweep chooses
    with migrated.begin() as conn:  # then a message names one of them, before the delete
        conn.execute(update(t.attachment).where(t.attachment.c.id == taken).values(message_seq=1))
    cutoff = clock.now() - timedelta(hours=24)
    assert attachments.expire(migrated, store, candidates, cutoff) == 1
    with migrated.connect() as conn:
        left = set(conn.execute(select(t.attachment.c.id)).scalars())
    assert left == {taken}  # the bound one kept its row ...
    assert sorted(p.name for p in blobs.glob("*/*")) == [taken]  # ... and its bytes
    assert idle not in left


def test_a_blob_whose_row_appeared_after_the_sweep_looked_is_kept(
    stored: ClientFactory, owner: flow.Human, blobs: Path, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    named = upload(agent, "late.txt", b"late")
    store = attachment_store.LocalStore(blobs)
    [blob] = blobs.glob("*/*")
    long_ago = time.time() - attachments.BLOB_GRACE - 60
    os.utime(blob, (long_ago, long_ago))  # old enough to be a stray, but a row names it
    key = f"{blob.parent.name}/{named}"
    assert attachments.remove_stray(migrated, store, key) is False
    assert blob.exists()
    with migrated.begin() as conn:
        conn.execute(delete(t.attachment))
    assert attachments.remove_stray(migrated, store, key) is True  # no row, old: a stray
    assert not blob.exists()


def test_an_upload_past_its_24_hours_cannot_be_named_any_more(
    stored: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    stale = upload(agent, "stale.txt")
    with migrated.begin() as conn:
        conn.execute(update(t.attachment).values(uploaded_at=clock.now() - timedelta(hours=25)))
    refused = send_raw(agent, owner.id, [stale])
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"]["attachments"] == {stale: "unknown"}
    with migrated.connect() as conn:
        assert conn.execute(select(t.attachment.c.message_seq)).scalar() is None


def test_a_stray_is_removed_under_the_project_lock_from_the_look_at_the_row_to_the_unlink(
    stored: ClientFactory,
    owner: flow.Human,
    blobs: Path,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = attachment_store.LocalStore(blobs)
    with migrated.connect() as conn:
        project = conn.execute(select(t.project.c.id)).scalar_one()
    key = attachment_store.key_of(project, "att-stray-locked")
    store.put(key, b"stray")
    long_ago = time.time() - attachments.BLOB_GRACE - 60
    os.utime(blobs / project / "att-stray-locked", (long_ago, long_ago))
    seen: list[str] = []
    real_lock, real_age, real_delete = events.lock_project, store.age, store.delete

    def lock(conn: Any, project_id: str) -> Any:
        seen.append(f"lock {project_id}")
        return real_lock(conn, project_id)

    def age(key_: str, now: float) -> float | None:
        seen.append("age")
        return real_age(key_, now)

    def delete_(key_: str) -> None:
        seen.append("delete")
        real_delete(key_)

    monkeypatch.setattr(events, "lock_project", lock)
    monkeypatch.setattr(store, "age", age)
    monkeypatch.setattr(store, "delete", delete_)
    assert attachments.remove_stray(migrated, store, key) is True
    assert seen == [f"lock {project}", "age", "delete"]  # the lock first, the unlink inside it
