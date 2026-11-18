"""docs/api.md §8.7: uploading, reading, listing and deleting attachments."""

from __future__ import annotations

import io
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image, PngImagePlugin
from sqlalchemy import Engine, insert, select, text, update

from maity_hub import attachment_store, attachments, avatars, events, idempotency, middleware
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from maity_hub.ratelimit import Limiter
from tests import flow
from tests.conftest import ClientFactory
from tests.test_auth_agent import signed


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
    """Clients of a hub that has an attachment store."""

    def factory(**overrides: Any) -> Any:
        return make_client(attachment_dir=blobs, **overrides)

    return factory


@pytest.fixture
def owner(stored: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(stored, migrated)
    flow.project(owner, "maity")
    return owner


def put(
    who: Any, name: str | None, data: bytes, content_type: str = "text/plain", **more: Any
) -> Any:
    query = "" if name is None else f"?name={name}"
    if isinstance(who, flow.Human):
        return who.client.post(
            f"/api/v1/projects/maintainer/maity/attachments{query}",
            content=data,
            headers={"Content-Type": content_type, "X-CSRF-Token": who.csrf, **more},
        )
    return who.client.post(
        f"/api/v1/projects/maintainer/maity/attachments{query}",
        content=data,
        headers={"Content-Type": content_type, **who.auth, **who.key(), **more},
    )


def png(size: tuple[int, int] = (40, 30), **save: Any) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format="PNG", **save)
    return out.getvalue()


def test_a_file_is_stored_byte_for_byte_and_answers_with_its_metadata(
    owner: flow.Human, blobs: Path
) -> None:
    body = b"line one\nline two\n"
    done = put(owner, "build-log.txt", body)
    assert done.status_code == 201, done.text
    shown = done.json()
    assert set(shown) >= {
        "id", "name", "size", "type", "kind", "sha256", "width", "height",
        "uploaded_by", "uploaded_at", "message_seq", "deleted_at", "deleted_by",
        "deleted_reason", "expires_at",
    }  # fmt: skip
    assert (shown["name"], shown["size"], shown["type"], shown["kind"]) == (
        "build-log.txt", len(body), "text/plain", "file",
    )  # fmt: skip
    assert shown["uploaded_by"] == owner.id and shown["message_seq"] is None
    assert shown["width"] is None and shown["expires_at"]
    [project_dir] = [p for p in blobs.iterdir() if p.is_dir()]
    assert (project_dir / shown["id"]).read_bytes() == body  # never in the database
    assert (
        owner.get(f"/projects/maintainer/maity/attachments/{shown['id']}").json()["sha256"]
        == shown["sha256"]
    )


def test_a_file_is_served_as_a_download_with_the_hardening_headers(owner: flow.Human) -> None:
    shown = put(owner, "page.html", b"<script>alert(1)</script>", "text/html").json()
    served = owner.get(f"/projects/maintainer/maity/attachments/{shown['id']}/content")
    assert served.status_code == 200 and served.content == b"<script>alert(1)</script>"
    assert served.headers["content-type"] == "application/octet-stream"  # whatever `type` says
    assert served.headers["content-disposition"].startswith("attachment; filename=")
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert served.headers["cross-origin-resource-policy"] == "same-origin"
    assert served.headers["cache-control"] == "private, no-cache"
    assert served.headers["etag"] == f'"{shown["sha256"]}"'
    again = owner.get(
        f"/projects/maintainer/maity/attachments/{shown['id']}/content",
        headers={"If-None-Match": served.headers["etag"]},
    )
    assert again.status_code == 304


def test_an_image_is_reencoded_inline_and_download_overrides(owner: flow.Human) -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "secret place")
    shown = put(owner, "shot.png", png(pnginfo=info), "image/png").json()
    assert (shown["kind"], shown["type"], shown["width"], shown["height"]) == (
        "image", "image/png", 40, 30,
    )  # fmt: skip
    path = f"/projects/maintainer/maity/attachments/{shown['id']}/content"
    inline = owner.get(path)
    assert inline.headers["content-type"] == "image/png"
    assert inline.headers["content-disposition"] == "inline; filename*=UTF-8''shot.png"
    assert b"secret place" not in inline.content
    assert owner.get(f"{path}?download=1").headers["content-disposition"].startswith("attachment")
    assert shown["size"] == len(inline.content)  # counted after re-encoding


def test_a_gif_is_stored_as_png_and_its_name_follows(owner: flow.Human) -> None:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (0, 0, 255)).save(out, format="GIF")
    shown = put(owner, "anim.gif", out.getvalue(), "image/gif").json()
    assert (shown["type"], shown["name"]) == ("image/png", "anim.png")


def test_an_image_must_be_declared_as_what_it_is_and_an_unreadable_one_is_refused(
    owner: flow.Human,
) -> None:
    wrong = put(owner, "a.png", png(), "text/plain")
    assert wrong.status_code == 400 and wrong.json()["error"]["details"]["fields"] == {
        "body": "unsupported_type"
    }
    jpg = io.BytesIO()
    Image.new("RGB", (9, 9)).save(jpg, format="JPEG")
    assert put(owner, "a.jpg", jpg.getvalue(), "image/jpg").status_code == 201  # the one alias
    broken = put(owner, "b.png", png()[:40], "image/png")
    assert broken.status_code == 400
    assert broken.json()["error"]["details"]["fields"] == {"body": "undecodable"}


def test_a_name_is_required_and_rewritten_never_refused(owner: flow.Human) -> None:
    missing = put(owner, None, b"x")
    assert missing.status_code == 400
    assert missing.json()["error"]["details"]["fields"] == {"name": "required"}
    odd = put(owner, "%2E%2E%2Fetc%2Fpasswd%3A%E2%80%AEgnp.txt", b"x").json()
    assert odd["name"] == "_etc_passwdgnp.txt"  # separators, ':' and the override removed
    assert put(owner, "%2E%2E", b"x").json()["name"] == "attachment"


def test_without_a_configured_store_uploads_say_so(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    refused = put(owner, "a.txt", b"x")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "attachments_not_configured"


def test_without_a_configured_store_every_attachment_call_says_so(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    calls = (
        owner.get("/projects/maintainer/maity/attachments/att-anything0000"),
        owner.get("/projects/maintainer/maity/attachments/att-anything0000/content"),
        owner.get(
            "/projects/maintainer/maity/attachments/att-anything0000/content",
            headers={"If-None-Match": '"abc"'},
        ),
        owner.get("/projects/maintainer/maity/attachments?status=pending"),
        owner.get("/projects/maintainer/maity/attachments"),
        owner.delete("/projects/maintainer/maity/attachments/att-anything0000"),
    )
    for answer in calls:
        assert answer.status_code == 409, answer.text
        assert answer.json()["error"]["code"] == "attachments_not_configured"


def test_a_file_over_the_cap_is_payload_too_large_before_it_is_read(
    owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(middleware, "ATTACHMENT_CAP", 1024)
    refused = put(owner, "big.bin", b"x" * 2048, "application/octet-stream")
    assert refused.status_code == 413
    assert refused.json()["error"]["code"] == "payload_too_large"
    assert put(owner, "ok.bin", b"x" * 1024, "application/octet-stream").status_code == 201


def _unread_upload(client: Any, headers: list[tuple[bytes, bytes]]) -> dict[str, Any]:
    """An upload of 9 MiB driven at the hub itself: its body is never handed over."""

    async def never_read() -> dict[str, object]:
        raise AssertionError("the body was read before the caller was known")

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    path = "/api/v1/projects/maintainer/maity/attachments"
    scope = {
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "https",
        "path": path, "raw_path": path.encode(), "root_path": "",
        "query_string": b"name=big.bin", "server": ("hub.example", 443),
        "client": ("203.0.113.7", 1),
        "headers": [
            (b"host", b"hub.example"),
            (b"content-type", b"application/octet-stream"),
            (b"content-length", str(9 * 1024 * 1024).encode()),
            *headers,
        ],
    }  # fmt: skip
    flow.drive(client, scope, never_read, send)
    start = sent[0]
    error = dict(start["headers"])[b"maity-error"].decode()
    return {"status": start["status"], "code": error}


def test_an_upload_no_body_could_authenticate_is_refused_before_it_is_read(
    owner: flow.Human, stored: ClientFactory
) -> None:
    agent = flow.agent(stored, owner)
    stale = int(time.time()) - 3600
    for headers, code in [
        ([], "unauthenticated"),
        ([(b"authorization", b"Bearer mty1.crd-nobody.AAAA")], "unauthenticated"),
        ([(b"authorization", f"Bearer {agent.credential}x".encode())], "unauthenticated"),
        ([(b"authorization", b"Basic eDp5")], "unauthenticated"),
        ([(b"cookie", b"maity_session=ended")], "unauthenticated"),
        ([(b"authorization", f"Maity-HMAC {agent.credential_id}".encode())], "signature_invalid"),
        (
            [
                (b"authorization", b"Maity-HMAC crd-nobody"),
                (b"maity-timestamp", str(int(time.time())).encode()),
                (b"maity-nonce", b"n" * 22),
                (b"maity-signature", b"0" * 64),
            ],
            "unauthenticated",
        ),
        (
            [
                (b"authorization", f"Maity-HMAC {agent.credential_id}".encode()),
                (b"maity-timestamp", str(stale).encode()),
                (b"maity-nonce", b"n" * 22),
                (b"maity-signature", b"0" * 64),
            ],
            "timestamp_skew",
        ),
    ]:
        assert _unread_upload(owner.client, headers) == {"status": 401, "code": code}, headers


def test_a_credential_leaked_in_the_query_is_revoked_before_the_pre_check(
    owner: flow.Human, stored: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    query = f"name={agent.credential}".encode()

    async def never_read() -> dict[str, object]:
        raise AssertionError("the body was read")

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    path = "/api/v1/projects/maintainer/maity/attachments"
    scope = {
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "https",
        "path": path, "raw_path": path.encode(), "root_path": "", "query_string": query,
        "server": ("hub.example", 443), "client": ("203.0.113.7", 1),
        "headers": [(b"host", b"hub.example"), (b"content-length", b"9")],
    }  # fmt: skip
    flow.drive(owner.client, scope, never_read, send)
    error = dict(sent[0]["headers"])[b"maity-error"]
    assert (sent[0]["status"], error) == (400, b"credential_in_payload")
    with migrated.connect() as conn:
        reason = conn.execute(
            select(t.credential.c.revoked_reason).where(t.credential.c.id == agent.credential_id)
        ).scalar()
    assert reason == "leaked_in_payload"


def test_a_signed_upload_is_read_and_its_signature_checked_after(
    owner: flow.Human, stored: ClientFactory
) -> None:
    agent = flow.agent(stored, owner)
    holder = SimpleNamespace(value=agent.credential, credential_id=agent.credential_id)
    path = "/api/v1/projects/maintainer/maity/attachments"

    def upload(data: bytes, signed_over: bytes) -> Any:
        return agent.client.post(
            f"{path}?name=s.bin",
            content=data,
            headers={
                "Content-Type": "application/octet-stream",
                **signed(holder, "POST", path, "name=s.bin", signed_over),
                **agent.key(),
            },
        )

    assert upload(b"x" * 2048, b"x" * 2048).status_code == 201
    forged = upload(b"x" * 2048, b"y" * 2048)  # the headers pass; the body does not verify
    assert (forged.status_code, forged.json()["error"]["code"]) == (401, "signature_invalid")


def test_the_project_quota_counts_pending_uploads_and_deleting_frees_it(
    stored: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(lambda **kw: stored(max_attachment_storage_per_project=2048, **kw), migrated)
    flow.project(owner, "maity")
    first = put(owner, "a.bin", b"x" * 1500, "application/octet-stream").json()
    over = put(owner, "b.bin", b"x" * 1000, "application/octet-stream")
    assert over.status_code == 409 and over.json()["error"]["code"] == "attachment_quota"
    assert over.json()["error"]["details"] == {"scope": "project", "used": 1500, "quota": 2048}
    assert owner.delete(f"/projects/maintainer/maity/attachments/{first['id']}").status_code == 200
    assert put(owner, "b.bin", b"x" * 1000, "application/octet-stream").status_code == 201


def test_the_blob_is_written_outside_the_projects_lock(
    owner: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For `s3` the write is a network call: it must not wait under the project's lock."""
    real = attachment_store.LocalStore.put
    taken: list[str] = []

    def put_while_free(self: Any, key: str, data: bytes) -> None:
        project_id = key.partition("/")[0]
        # Another transaction takes the project's lock: it would wait (and fail on the
        # timeout) if the upload held the lock or, on SQLite, the write lock.
        with migrated.begin() as conn:
            if migrated.dialect.name == "postgresql":
                conn.execute(text("SET LOCAL lock_timeout = '2s'"))
            events.lock_project(conn, project_id)
        taken.append(key)
        real(self, key, data)

    monkeypatch.setattr(attachment_store.LocalStore, "put", put_while_free)
    shown = put(owner, "a.txt", b"free")
    assert shown.status_code == 201, shown.text
    assert taken == [f"{taken[0].partition('/')[0]}/{shown.json()['id']}"]


def test_a_refused_upload_leaves_no_blob(
    stored: ClientFactory, migrated: Engine, blobs: Path
) -> None:
    """The blob is written before the transaction; a refusal in it removes the blob again."""
    owner = flow.human(lambda **kw: stored(max_attachment_storage_per_project=2048, **kw), migrated)
    flow.project(owner, "maity")
    first = put(owner, "a.bin", b"x" * 1500, "application/octet-stream").json()
    over = put(owner, "b.bin", b"x" * 1000, "application/octet-stream")
    assert over.status_code == 409 and over.json()["error"]["code"] == "attachment_quota"
    assert [p.name for p in blobs.glob("*/*")] == [first["id"]]


def test_a_refusal_after_the_write_keeps_the_rate_charged_and_the_quota_is_checked_before_it(
    stored: ClientFactory, migrated: Engine, blobs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal before the store is written costs no write; after it, the write happened, and
    the rate stays charged (a refusal cannot buy writes past the rate)."""
    owner = flow.human(lambda **kw: stored(max_attachment_storage_per_project=1024, **kw), migrated)
    flow.project(owner, "maity")
    writes: list[str] = []
    real = attachment_store.LocalStore.put

    def counted(self: Any, key: str, data: bytes) -> None:
        writes.append(key)
        real(self, key, data)

    monkeypatch.setattr(attachment_store.LocalStore, "put", counted)
    given_back: list[Any] = []
    real_give_back = attachments.give_back

    def give_back(key: str, charged: Any) -> None:
        given_back.append(charged)
        real_give_back(key, charged)

    monkeypatch.setattr(attachments, "give_back", give_back)
    for _ in range(attachments.RATE_UPLOADS + 5):  # past the rate, were the refusals counted
        over = put(owner, "big.bin", b"x" * 2048, "application/octet-stream")
        assert over.status_code == 409 and over.json()["error"]["code"] == "attachment_quota"
    assert writes == []  # refused before the store was written
    assert len(given_back) == attachments.RATE_UPLOADS + 5  # and given back: nothing was written
    assert put(owner, "ok.txt", b"x").status_code == 201
    # A refusal only the second look finds (here: past the bound for its row) comes after the
    # write: the charge stays, and the blob goes again.
    from maity_hub.routes import attachments as route

    now = [0.0]
    monkeypatch.setattr(attachments, "upload_clock", lambda: now[0])
    real_lock = events.lock_project

    def slow_lock(conn: Any, project_id: str) -> Any:
        now[0] += attachments.UPLOAD_FRESH + 1  # the lock wait outlasts the bound
        return real_lock(conn, project_id)

    monkeypatch.setattr(route, "lock_project", slow_lock)
    late = put(owner, "late.txt", b"y")
    assert late.status_code == 503 and late.json()["error"]["code"] == "upload_expired"
    assert len(writes) == 2 and not (blobs / writes[1]).exists()
    assert len(given_back) == attachments.RATE_UPLOADS + 5


def test_a_write_that_fails_or_outlasts_the_bound_keeps_the_rate_charged_and_leaves_no_blob(
    owner: flow.Human, blobs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed write may still have stored the bytes (its answer lost): the charge stays, and
    the blob is removed. A write that took longer than `UPLOAD_FRESH` gets no row: the sweep
    may already count its blob as a stray."""
    given_back: list[Any] = []
    monkeypatch.setattr(attachments, "give_back", lambda key, charged: given_back.append(1))
    real = attachment_store.LocalStore.put

    def lost(self: Any, key: str, data: bytes) -> None:
        real(self, key, data)
        raise attachment_store.StoreError("the attachment store could not store a blob (x)")

    monkeypatch.setattr(attachment_store.LocalStore, "put", lost)
    assert put(owner, "a.txt", b"lost").status_code == 500
    assert list(blobs.glob("*/*")) == [] and given_back == []
    now = [0.0]
    monkeypatch.setattr(attachments, "upload_clock", lambda: now[0])

    def slow(self: Any, key: str, data: bytes) -> None:
        real(self, key, data)
        now[0] += attachments.UPLOAD_FRESH + 1

    monkeypatch.setattr(attachment_store.LocalStore, "put", slow)
    from maity_hub.routes import attachments as route

    locked: list[str] = []
    monkeypatch.setattr(route, "lock_project", lambda conn, project_id: locked.append(project_id))
    slow_answer = put(owner, "b.txt", b"slow")
    assert (
        slow_answer.status_code == 503 and slow_answer.json()["error"]["code"] == "upload_expired"
    )
    assert list(blobs.glob("*/*")) == [] and given_back == [] and locked == []  # no lock taken


def test_an_upload_whose_commit_answer_is_lost_keeps_the_blob_its_row_names(
    owner: flow.Human, migrated: Engine, blobs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error after the COMMIT (its answer lost, or a retry refused after an attempt that
    did commit) does not prove the row is absent: the blob stays when a fresh read finds the
    row, goes when it finds none, and stays for the sweep when the read itself fails."""
    from sqlalchemy.exc import OperationalError

    from maity_hub.routes import attachments as route

    real_run = idempotency.run
    lost = OperationalError("COMMIT", {}, Exception("server closed the connection"))

    def unavailable(answer: Any) -> bool:
        return bool(
            answer.status_code == 503 and answer.json()["error"]["code"] == "database_unavailable"
        )

    def committed_then_lost(*args: Any) -> Any:
        real_run(*args)
        raise lost

    monkeypatch.setattr(idempotency, "run", committed_then_lost)
    assert unavailable(put(owner, "kept.txt", b"kept"))
    with migrated.connect() as conn:
        rows = conn.execute(select(t.attachment.c.id, t.attachment.c.project_id)).all()
    assert len(rows) == 1
    kept = blobs / rows[0].project_id / rows[0].id
    assert kept.read_bytes() == b"kept"  # the committed row still has its bytes

    def failed_before(*args: Any) -> Any:
        raise lost

    monkeypatch.setattr(idempotency, "run", failed_before)
    assert unavailable(put(owner, "gone.txt", b"gone"))
    assert [p.name for p in blobs.glob("*/*")] == [rows[0].id]  # no row: its blob removed

    def unreadable(*args: Any, **kwargs: Any) -> Any:
        raise lost

    monkeypatch.setattr(route, "select", unreadable)  # the fresh read fails too
    assert unavailable(put(owner, "unknown.txt", b"unknown"))
    assert len(list(blobs.glob("*/*"))) == 2  # left to the sweep, not removed blindly


def test_the_read_before_the_removal_waits_for_a_commit_still_running(
    owner: flow.Human, migrated: Engine, blobs: Path
) -> None:
    """The client may have given up on a COMMIT the server still runs: the read waits for the
    project's lock, which that transaction holds until it ends, and then finds the row."""
    import threading

    from maity_hub.ids import new_id
    from maity_hub.routes import attachments as route

    first = put(owner, "first.txt", b"first").json()["id"]
    with migrated.connect() as conn:
        row = conn.execute(select(t.attachment).where(t.attachment.c.id == first)).one()
    late = new_id("attachment")
    key = attachment_store.key_of(row.project_id, late)
    store = attachment_store.LocalStore(blobs)
    store.put(key, b"late")
    done = threading.Event()

    def discard() -> None:
        route._discard_unless_committed(migrated, store, key, late)
        done.set()

    with migrated.begin() as conn:  # the upload's transaction, its COMMIT not through yet
        events.lock_project(conn, row.project_id)
        conn.execute(insert(t.attachment).values({**row._asdict(), "id": late}))
        worker = threading.Thread(target=discard)
        worker.start()
        assert not done.wait(0.5)  # the read waits for the lock
    worker.join(timeout=30)
    assert done.is_set()
    assert store.get(key) == b"late"  # the row committed: its bytes stay


def test_the_sweeps_grace_outlasts_the_upload_bound_by_the_clock_skew() -> None:
    """A blob the sweep sees older than `BLOB_GRACE` is, with the clocks up to `CLOCK_SKEW`
    apart, older than `UPLOAD_FRESH`: its upload can no longer insert the row."""
    assert attachments.BLOB_GRACE - attachments.CLOCK_SKEW > attachments.UPLOAD_FRESH
    assert attachments.upload_clock() <= attachments.upload_clock()


def test_an_upload_whose_slug_names_another_project_under_the_lock_is_refused(
    owner: flow.Human, blobs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The blob's key names the project the upload started for; when the slug resolves to
    another project by the time the row is inserted, no row names that key, and it goes."""
    import dataclasses
    import types

    from maity_hub import access
    from maity_hub.routes import attachments as route

    real = access.membership
    real_lock = events.lock_project
    locked: list[str] = []

    def lock(conn: Any, project_id: str) -> Any:
        found = real_lock(conn, project_id)
        locked.append(project_id)
        return found

    def moved(conn: Any, caller: Any, slug: str) -> Any:
        found = real(conn, caller, slug)
        if not locked:  # every look before the lock sees the project the upload is for
            return found
        other = types.SimpleNamespace(**{**found.project._mapping, "id": "prj-another"})
        return dataclasses.replace(found, project=other)

    monkeypatch.setattr(route, "membership", moved)
    monkeypatch.setattr(route, "lock_project", lock)
    refused = put(owner, "a.txt", b"moved")
    assert refused.status_code == 404 and refused.json()["error"]["code"] == "not_found"
    assert list(blobs.glob("*/*")) == [] and len(locked) >= 1


def test_a_membership_holds_a_bounded_number_of_pending_uploads(
    owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(attachments, "PENDING_COUNT", 2)
    assert put(owner, "1.txt", b"1").status_code == 201
    assert put(owner, "2.txt", b"2").status_code == 201
    over = put(owner, "3.txt", b"3")
    assert over.status_code == 409 and over.json()["error"]["details"]["scope"] == "pending"
    assert over.json()["error"]["details"]["count"] == 2
    assert over.json()["error"]["details"]["max"] == 2
    decoded: list[int] = []
    real = avatars.decode_attachment

    def counted(*args: Any, **kw: Any) -> Any:
        decoded.append(1)
        return real(*args, **kw)

    monkeypatch.setattr(avatars, "decode_attachment", counted)
    image = put(owner, "4.png", png(), "image/png")
    assert image.status_code == 409 and image.json()["error"]["details"]["scope"] == "pending"
    assert decoded == []  # an image past the count bound is refused before its decode


def test_a_failed_read_before_the_decode_gives_the_rate_back(
    owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing was decoded or stored: a database error in the count bound costs no upload."""
    from sqlalchemy.exc import OperationalError

    given_back: list[Any] = []
    monkeypatch.setattr(attachments, "give_back", lambda key, charged: given_back.append(1))

    def unreadable(*args: Any) -> Any:
        raise OperationalError("SELECT", {}, Exception("server closed the connection"))

    monkeypatch.setattr(attachments, "pending_of", unreadable)
    answer = put(owner, "a.png", png(), "image/png")
    assert answer.status_code == 503 and answer.json()["error"]["code"] == "database_unavailable"
    assert given_back == [1]


def test_an_upload_that_loses_to_the_same_key_leaves_no_blob(
    owner: flow.Human, blobs: Path, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent call with the same idempotency key won: this upload's blob has no row and
    goes at once; the answer is the winner's."""
    first = put(owner, "first.txt", b"first")
    assert first.status_code == 201

    def the_other_won(engine: Any, request: Any, caller: Any, action: Any) -> Any:
        return idempotency.respond(first.json(), 201)

    monkeypatch.setattr(idempotency, "run", the_other_won)
    lost = put(owner, "second.txt", b"second")
    assert lost.status_code == 201 and lost.json()["id"] == first.json()["id"]
    assert [p.name for p in blobs.glob("*/*")] == [first.json()["id"]]


def test_uploads_are_rate_limited_per_membership_and_a_refusal_counts_nothing(
    owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(attachments, "UPLOADS", Limiter(2, 600, name="attachments.UPLOADS"))
    assert put(owner, None, b"x").status_code == 400  # refused before counting
    assert put(owner, "a.txt", b"a").status_code == 201
    assert put(owner, "b.txt", b"b").status_code == 201
    slow = put(owner, "c.txt", b"c")
    assert slow.status_code == 429 and int(slow.headers["retry-after"]) >= 1


def test_a_replayed_upload_answers_the_first_and_stores_nothing_twice(
    stored: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    headers = {"Idempotency-Key": "same-upload-0001"}
    first = agent.client.post(
        "/api/v1/projects/maintainer/maity/attachments?name=a.txt",
        content=b"abc",
        headers={"Content-Type": "text/plain", **agent.auth, **headers},
    )
    again = agent.client.post(
        "/api/v1/projects/maintainer/maity/attachments?name=a.txt",
        content=b"abc",
        headers={"Content-Type": "text/plain", **agent.auth, **headers},
    )
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    with migrated.connect() as conn:
        assert len(conn.execute(select(t.attachment)).all()) == 1


def test_a_pending_upload_is_its_uploaders_alone(stored: ClientFactory, owner: flow.Human) -> None:
    agent, other = flow.agent(stored, owner), flow.agent(stored, owner)
    shown = put(agent, "mine.txt", b"secret").json()
    path = f"/projects/maintainer/maity/attachments/{shown['id']}"
    assert agent.get(path).status_code == 200 and agent.get(f"{path}/content").content == b"secret"
    for stranger in (other, owner):  # not even a human owner reads another's pending upload
        assert stranger.get(path).status_code == 404
        assert stranger.get(f"{path}/content").status_code == 404
    assert agent.get("/projects/maintainer/maity/attachments/att-nonexistent00").status_code == 404


def test_the_pending_listing_shows_a_member_its_own_and_an_admin_the_rest_in_part(
    stored: ClientFactory, owner: flow.Human
) -> None:
    agent, other = flow.agent(stored, owner), flow.agent(stored, owner)
    mine = put(agent, "mine.txt", b"1").json()
    theirs = put(other, "theirs.txt", b"22").json()
    own = agent.get("/projects/maintainer/maity/attachments?status=pending").json()
    assert [i["id"] for i in own["items"]] == [mine["id"]] and own["items"][0]["name"] == "mine.txt"
    everyone = owner.get("/projects/maintainer/maity/attachments?status=pending").json()["items"]
    assert [i["id"] for i in everyone] == [mine["id"], theirs["id"]]
    for item in everyone:
        assert item["name"] is None and item["type"] is None and item["sha256"] is None
        assert item["size"] and item["uploaded_by"] and item["expires_at"]
    narrowed = owner.get(
        f"/projects/maintainer/maity/attachments?status=pending&uploaded_by={other.id}"
    ).json()["items"]
    assert [i["id"] for i in narrowed] == [theirs["id"]]
    assert (
        agent.get(
            f"/projects/maintainer/maity/attachments?status=pending&uploaded_by={other.id}"
        ).status_code
        == 403
    )
    assert owner.get("/projects/maintainer/maity/attachments?status=sent").status_code == 400
    assert owner.get("/projects/maintainer/maity/attachments").status_code == 400


def test_the_pending_listing_pages_oldest_first(owner: flow.Human) -> None:
    made = [put(owner, f"{n}.txt", b"x").json()["id"] for n in range(3)]
    page = owner.get("/projects/maintainer/maity/attachments?status=pending&limit=2").json()
    assert [i["id"] for i in page["items"]] == made[:2] and page["next_cursor"]
    rest = owner.get(
        f"/projects/maintainer/maity/attachments?status=pending&limit=2&cursor={page['next_cursor']}"
    ).json()
    assert [i["id"] for i in rest["items"]] == made[2:] and rest["next_cursor"] is None
    other = owner.get(
        f"/projects/maintainer/maity/attachments?status=pending&limit=2&uploaded_by={owner.id}"
        f"&cursor={page['next_cursor']}"
    )
    assert other.status_code == 400  # a cursor belongs to its own query


def test_deleting_a_pending_upload_removes_it_with_its_bytes_and_leaves_nothing(
    stored: ClientFactory, owner: flow.Human, blobs: Path, migrated: Engine
) -> None:
    agent = flow.agent(stored, owner)
    shown = put(agent, "gone.txt", b"bye").json()
    path = f"/projects/maintainer/maity/attachments/{shown['id']}"
    deleted = agent.client.delete(f"/api/v1{path}", headers={**agent.auth, **agent.key()})
    assert deleted.status_code == 200 and deleted.json()["name"] == "gone.txt"
    assert agent.get(path).status_code == 404
    assert not list(blobs.glob("*/*"))
    with migrated.connect() as conn:
        assert conn.execute(select(t.attachment)).all() == []
        kinds = conn.execute(select(t.event.c.kind)).scalars().all()
    assert "attachment_deleted" not in kinds


def test_an_admin_deletes_another_members_pending_upload_and_sees_no_more_than_the_listing(
    stored: ClientFactory, owner: flow.Human
) -> None:
    agent, other = flow.agent(stored, owner), flow.agent(stored, owner)
    shown = put(agent, "private-name.txt", b"x").json()
    path = f"/projects/maintainer/maity/attachments/{shown['id']}"
    refused = other.client.delete(f"/api/v1{path}", headers={**other.auth, **other.key()})
    assert refused.status_code == 404  # it does not exist for another member
    deleted = owner.delete(path)
    assert deleted.status_code == 200
    body = deleted.json()
    assert body["name"] is None and body["type"] is None and body["sha256"] is None
    assert body["size"] == 1 and body["uploaded_by"] == agent.id
    assert agent.get(path).status_code == 404


def test_an_admin_agent_never_deletes_what_it_did_not_send(
    stored: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent, boss = flow.agent(stored, owner), flow.agent(stored, owner)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.agent_id == boss.id).values(trust="admin")
        )
    shown = put(agent, "x.txt", b"x").json()
    path = f"/projects/maintainer/maity/attachments/{shown['id']}"
    refused = boss.client.delete(f"/api/v1{path}", headers={**boss.auth, **boss.key()})
    assert (
        refused.status_code == 403 and refused.json()["error"]["details"]["reason"] == "humans_only"
    )
    other = boss.get(
        f"/projects/maintainer/maity/attachments?status=pending&uploaded_by={agent.id}"
    )
    assert other.status_code == 403 and other.json()["error"]["details"]["reason"] == "humans_only"
    assert agent.get(path).status_code == 200  # still there


def test_a_closed_project_takes_no_upload_and_still_lets_one_go(owner: flow.Human) -> None:
    shown = put(owner, "a.txt", b"x").json()
    assert (
        owner.patch(
            "/projects/maintainer/maity", {"state": "archived", "reason": "done"}
        ).status_code
        == 200
    )
    closed = put(owner, "b.txt", b"x")
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "project_closed"
    assert owner.delete(f"/projects/maintainer/maity/attachments/{shown['id']}").status_code == 200


def test_bytes_that_do_not_match_their_digest_are_never_served(
    owner: flow.Human, blobs: Path
) -> None:
    shown = put(owner, "a.txt", b"original").json()
    [folder] = [p for p in blobs.iterdir() if p.is_dir()]
    (folder / shown["id"]).write_bytes(b"swapped!")
    broken = owner.get(f"/projects/maintainer/maity/attachments/{shown['id']}/content")
    assert broken.status_code == 500 and broken.json()["error"]["code"] == "internal"


def test_a_name_is_cleaned_once_at_upload() -> None:
    clean = attachments.clean_name
    assert clean("  ..hidden.txt ") == "hidden.txt"
    assert clean("a/b\\c.txt") == "a_b_c.txt"
    assert clean("tab\there:colon‮.txt") == "tabherecolon.txt"
    assert clean("") == "attachment" and clean("...") == "attachment"
    assert clean("", image_type="image/webp") == "attachment.webp"
    assert clean("..", image_type="image/gif") == "attachment.png"  # stored as PNG
    assert clean("é.txt") == "é.txt"  # NFC
    long = clean("x" * 400 + ".log")
    assert len(long) <= 200 and long.endswith(".log")
    wide = clean("é" * 200 + ".txt")
    assert len(wide.encode()) <= 255 and wide.endswith(".txt")


def test_the_local_store_keeps_blobs_whole_and_refuses_odd_keys(tmp_path: Path) -> None:
    store = attachment_store.LocalStore(tmp_path)
    store.put("prj-1/att-1", b"one")
    store.put("prj-1/att-1", b"two")  # replaced whole
    assert store.get("prj-1/att-1") == b"two" and store.keys("prj-1") == ["prj-1/att-1"]
    assert not [p for p in (tmp_path / "prj-1").iterdir() if p.name.startswith(".")]
    store.delete("prj-1/att-1")
    store.delete("prj-1/att-1")  # a removal that finds nothing is done
    assert store.get("prj-1/att-1") is None
    for key in ("../x", "prj-1/../x", "prj-1/a/b", "/abs", "prj-1/", ""):
        with pytest.raises(ValueError):
            store.put(key, b"x")


def test_the_settings_stop_the_hub_for_an_unusable_store(tmp_path: Path) -> None:
    base = {"MAITY_DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}"}
    for bad in (
        {"MAITY_ATTACHMENT_STORE": "s3"},
        {"MAITY_ATTACHMENT_STORE": "tape"},
        {"MAITY_ATTACHMENT_DIR": "relative/dir"},
        {"MAITY_ATTACHMENT_DIR": str(tmp_path / "missing")},
    ):
        with pytest.raises(ConfigError):
            Settings.from_env({**base, **bad})
    ok = Settings.from_env({**base, "MAITY_ATTACHMENT_DIR": str(tmp_path)})
    assert ok.attachment_dir == tmp_path


def _membership_key(migrated: Engine, who: str) -> str:
    with migrated.connect() as conn:
        row = conn.execute(
            select(t.membership.c.id).where(
                (t.membership.c.human_id == who) | (t.membership.c.agent_id == who)
            )
        ).one()
    return str(row.id)


def test_a_decoded_image_refused_for_its_room_keeps_what_it_was_charged(
    owner: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The image was decoded before the byte bound refused it: the decode counts, at the
    size that was sent, not the re-encoded size's share. A file refused there is given back."""
    big = png((200, 200), compress_level=0)  # far larger than its re-encoded form
    assert len(big) > 100_000
    monkeypatch.setattr(attachments, "PENDING_BYTES", 10)
    refused = put(owner, "big.png", big, "image/png")
    assert refused.status_code == 409 and refused.json()["error"]["details"]["scope"] == "pending"
    key = _membership_key(migrated, owner.id)
    assert _counted(attachments.UPLOADS, key) == 1
    assert _counted(attachments.VOLUME, key) == -(-len(big) // attachments.RATE_UNIT)
    file = put(owner, "big.bin", b"x" * 2048, "application/octet-stream")
    assert file.status_code == 409 and file.json()["error"]["details"]["scope"] == "pending"
    assert _counted(attachments.UPLOADS, key) == 1  # a file was neither decoded nor stored


def test_refused_images_count_against_the_upload_limit(
    owner: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An image the decoder refuses was decoded: it counts, as a refused avatar does, so a
    stream of malformed images runs into the limit instead of decoding for free."""
    monkeypatch.setattr(attachments, "UPLOADS", Limiter(3, 600, name="attachments.UPLOADS"))
    broken = png()[:40]
    for _ in range(3):
        refused = put(owner, "b.png", broken, "image/png")
        assert refused.status_code == 400
        assert refused.json()["error"]["details"]["fields"] == {"body": "undecodable"}
    over = put(owner, "b.png", broken, "image/png")
    assert over.status_code == 429 and int(over.headers["retry-after"]) >= 1
    assert put(owner, "ok.txt", b"x").status_code == 429  # the limit is the membership's
    key = _membership_key(migrated, owner.id)
    assert _counted(attachments.UPLOADS, key) == 3


def test_refused_images_count_their_bytes_too(
    owner: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused image's size counts against the byte limit as a stored file's does."""
    monkeypatch.setattr(attachments, "VOLUME", Limiter(4, 600, name="attachments.VOLUME"))
    broken = png()[:40] + b"\0" * (2 * attachments.RATE_UNIT - 40)  # two units
    assert put(owner, "a.png", broken, "image/png").status_code == 400
    assert put(owner, "b.png", broken, "image/png").status_code == 400
    over = put(owner, "c.png", broken, "image/png")
    assert over.status_code == 429


def test_a_slot_busy_refusal_gives_the_upload_back(
    owner: flow.Human, migrated: Engine, settings: Settings
) -> None:
    """Nothing was decoded when every decode slot was taken: the call is not counted."""
    slots = avatars._slots_for(settings.avatar_decodes)
    taken = 0
    try:
        while slots.acquire(blocking=False):
            taken += 1
        busy = put(owner, "a.png", png(), "image/png")
        assert busy.status_code == 429 and busy.json()["error"]["code"] == "rate_limited"
    finally:
        for _ in range(taken):
            slots.release()
    key = _membership_key(migrated, owner.id)
    assert _counted(attachments.UPLOADS, key) == 0
    assert _counted(attachments.VOLUME, key) == 0
    assert put(owner, "a.png", png(), "image/png").status_code == 201


def test_one_human_takes_at_most_all_but_one_decode_slot(
    stored: ClientFactory, owner: flow.Human, migrated: Engine, settings: Settings
) -> None:
    """The human behind a call, an agent's owner for an agent, holds its share of the slots;
    the slot left is another human's, and a call refused for its share is not counted."""
    agent = flow.agent(stored, owner)
    slots = avatars._slots_for(settings.avatar_decodes)
    assert settings.avatar_decodes == 2 and slots.share == 1
    assert slots.acquire(blocking=False, holder=owner.id)  # the owner's one decode running
    try:
        mine = put(owner, "a.png", png(), "image/png")
        assert mine.status_code == 429 and mine.json()["error"]["code"] == "rate_limited"
        theirs = put(agent, "a.png", png(), "image/png")  # the owner's agent shares the share
        assert theirs.status_code == 429
        assert _counted(attachments.UPLOADS, _membership_key(migrated, owner.id)) == 0
    finally:
        slots.release(owner.id)
    assert put(owner, "a.png", png(), "image/png").status_code == 201


def test_a_project_closed_during_the_decode_refuses_the_upload(
    owner: flow.Human, blobs: Path, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = avatars.decode_attachment

    def closing(settings: Settings, data: bytes, content_type: str, **kw: Any) -> Any:
        found = real(settings, data, content_type, **kw)
        with migrated.begin() as conn:  # the project is archived while the image decodes
            conn.execute(update(t.project).values(state="archived"))
        return found

    monkeypatch.setattr(avatars, "decode_attachment", closing)
    refused = put(owner, "late.png", png(), "image/png")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "project_closed"
    with migrated.connect() as conn:
        assert conn.execute(select(t.attachment)).all() == []
    assert not list(blobs.glob("*/*"))


def _counted(limiter: Any, key: str) -> int:
    """What a limit holds for `key`: in the process, or in the shared counts on PostgreSQL."""
    from maity_hub import shared_counts

    if shared_counts.active():
        if limiter.exact:  # a small limit keeps a row per attempt, not two windows
            return shared_counts.log_read(limiter.name, key, limiter.window).total
        window = shared_counts.read(limiter.name, key, limiter.window)
        return window.current + window.previous
    return len(limiter._hits.get(key, ()))
