"""docs/api.md §8.7: uploading, reading, listing and deleting attachments."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, PngImagePlugin
from sqlalchemy import Engine, select, update

from maity_hub import attachment_store, attachments, avatars, middleware
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from maity_hub.ratelimit import Limiter
from tests import flow
from tests.conftest import ClientFactory


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


def test_the_project_quota_counts_pending_uploads_and_deleting_frees_it(
    stored: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(lambda **kw: stored(attachment_quota=2048, **kw), migrated)
    flow.project(owner, "maity")
    first = put(owner, "a.bin", b"x" * 1500, "application/octet-stream").json()
    over = put(owner, "b.bin", b"x" * 1000, "application/octet-stream")
    assert over.status_code == 409 and over.json()["error"]["code"] == "attachment_quota"
    assert over.json()["error"]["details"] == {"scope": "project", "used": 1500, "quota": 2048}
    assert owner.delete(f"/projects/maintainer/maity/attachments/{first['id']}").status_code == 200
    assert put(owner, "b.bin", b"x" * 1000, "application/octet-stream").status_code == 201


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
        {"MAITY_ATTACHMENT_QUOTA": "lots"},
    ):
        with pytest.raises(ConfigError):
            Settings.from_env({**base, **bad})
    ok = Settings.from_env({**base, "MAITY_ATTACHMENT_DIR": str(tmp_path)})
    assert ok.attachment_dir == tmp_path and ok.attachment_quota == 1024**3


def _membership_key(migrated: Engine, who: str) -> str:
    with migrated.connect() as conn:
        row = conn.execute(
            select(t.membership.c.id).where(
                (t.membership.c.human_id == who) | (t.membership.c.agent_id == who)
            )
        ).one()
    return str(row.id)


def test_a_refused_reencoded_image_gives_back_what_it_was_charged(
    owner: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    big = png((200, 200), compress_level=0)  # far larger than its re-encoded form
    assert len(big) > 100_000
    monkeypatch.setattr(attachments, "PENDING_BYTES", 10)
    refused = put(owner, "big.png", big, "image/png")
    assert refused.status_code == 409 and refused.json()["error"]["details"]["scope"] == "pending"
    key = _membership_key(migrated, owner.id)
    assert _counted(attachments.UPLOADS, key) == 0
    assert _counted(attachments.VOLUME, key) == 0  # not the re-encoded size's share


def test_a_project_closed_during_the_decode_refuses_the_upload(
    owner: flow.Human, blobs: Path, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = avatars.decode_attachment

    def closing(settings: Settings, data: bytes, content_type: str) -> Any:
        found = real(settings, data, content_type)
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
        window = shared_counts.read(limiter.name, key, limiter.window)
        return window.current + window.previous
    return len(limiter._hits.get(key, ()))
