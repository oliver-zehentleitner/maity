"""docs/api.md §6.10: a member's picture — upload, re-encoding, who reads it, avatar_url."""

from __future__ import annotations

import io
import subprocess
import typing
from typing import Any

import pytest
from PIL import Image, PngImagePlugin
from sqlalchemy import Engine, select

from maity_hub import avatars
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture(autouse=True)
def _fresh_changes() -> None:
    avatars.CHANGES.reset()


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def image(kind: str = "PNG", size: tuple[int, int] = (300, 200), **save: Any) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format=kind, **save)
    return out.getvalue()


def put_human(human: flow.Human, path: str, data: bytes, content_type: str = "image/png") -> Any:
    return human.client.put(
        f"/api/v1{path}",
        content=data,
        headers={"Content-Type": content_type, "X-CSRF-Token": human.csrf},
    )


def put_agent(agent: flow.Agent, data: bytes, content_type: str = "image/png") -> Any:
    return agent.client.put(
        "/api/v1/me/avatar", content=data, headers={**agent.auth, "Content-Type": content_type}
    )


def test_an_upload_is_reencoded_and_served(owner: flow.Human) -> None:
    jpeg = image("JPEG", (640, 480), exif=Image.Exif().tobytes(), comment=b"secret place")
    answer = put_human(owner, "/me/avatar", jpeg, "image/jpeg")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["avatar_source"] == "uploaded"
    assert body["avatar_url"].startswith(f"/api/v1/avatars/{owner.id}?v=")
    served = owner.client.get(body["avatar_url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.headers["cache-control"] == "private, no-cache"
    assert served.headers["content-security-policy"] == "default-src 'none'; sandbox"
    picture = Image.open(io.BytesIO(served.content))
    assert (picture.format, picture.size, picture.mode) == ("PNG", (256, 256), "RGBA")
    assert picture.info == {} and b"secret place" not in served.content
    again = owner.client.get(body["avatar_url"], headers={"If-None-Match": served.headers["etag"]})
    assert again.status_code == 304 and again.content == b""


def test_avatar_url_follows_the_member_everywhere(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    assert owner.get("/me").json()["member"]["avatar_url"] is None
    url = put_human(owner, "/me/avatar", image()).json()["avatar_url"]
    agent_url = put_agent(agent, image("WEBP"), "image/webp").json()["avatar_url"]
    me = owner.get("/me").json()["member"]
    assert (me["avatar_url"], me["avatar_source"]) == (url, "uploaded")
    members = {m["id"]: m for m in owner.get("/projects/maity/members").json()["items"]}
    assert members[owner.id]["avatar_url"] == url
    assert members[agent.id]["avatar_url"] == agent_url
    assert members[agent.id]["owner"]["avatar_url"] == url  # the admin's owner object
    profile = owner.get(f"/agents/{agent.id}").json()
    assert (profile["avatar_url"], profile["avatar_source"]) == (agent_url, "uploaded")
    assert agent.resume().json()["me"]["avatar_url"] == agent_url
    assert agent.get("/me").json()["member"]["avatar_url"] == agent_url
    assert owner.get("/admin/users").json()["items"][0]["avatar_url"] == url
    asked = agent.post(
        "/projects/maity/requests",
        {"class": "info", "title": "a question", "summary": "x", "to": "owner"},
    ).json()
    assert asked["asked_by"]["avatar_url"] == agent_url
    assert owner.delete("/me/avatar").json() == {"avatar_url": None, "avatar_source": None}
    assert owner.get("/me").json()["member"]["avatar_url"] is None
    assert owner.client.get(url).status_code == 404


@pytest.mark.parametrize(
    ("data", "content_type", "reason"),
    [
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml", "unsupported_type"),
        (image("PNG"), "image/jpeg", "unsupported_type"),
        (image("PNG", (5000, 20)), "image/png", "dimensions"),
        (b"\x89PNG\r\n\x1a\n" + b"x" * 100, "image/png", "undecodable"),
    ],
)
def test_a_refused_image_changes_nothing(
    owner: flow.Human, data: bytes, content_type: str, reason: str
) -> None:
    before = put_human(owner, "/me/avatar", image()).json()
    answer = put_human(owner, "/me/avatar", data, content_type)
    assert answer.status_code == 400
    assert answer.json()["error"]["details"]["fields"] == {"body": reason}
    assert owner.get("/me").json()["member"]["avatar_url"] == before["avatar_url"]


def test_png_text_chunks_are_capped(owner: flow.Human) -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("big", "x" * (70 * 1024))
    answer = put_human(owner, "/me/avatar", image(pnginfo=info))
    assert answer.json()["error"]["details"]["fields"] == {"body": "undecodable"}
    bomb = PngImagePlugin.PngInfo()
    bomb.add_text("bomb", "x" * (2 * 1024 * 1024), zip=True)
    answer = put_human(owner, "/me/avatar", image(pnginfo=bomb))
    assert answer.json()["error"]["details"]["fields"] == {"body": "undecodable"}


def test_over_the_memory_budget_is_refused(make_client: ClientFactory, migrated: Engine) -> None:
    factory.human(migrated, "tight")
    client = make_client(avatar_decode_memory_mb=128)  # a 4096 × 4096 decode needs more
    csrf = _login(client, "tight")
    answer = client.put(
        "/api/v1/me/avatar",
        content=image("PNG", (4096, 4096)),
        headers={"Content-Type": "image/png", "X-CSRF-Token": csrf},
    )
    assert answer.json()["error"]["details"]["fields"] == {"body": "undecodable"}


def test_over_the_time_budget_is_refused(
    owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow(command: list[str], **kwargs: Any) -> Any:  # the deadline passed
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr("maity_hub.avatars.subprocess.run", slow)
    answer = put_human(owner, "/me/avatar", image())
    assert answer.json()["error"]["details"]["fields"] == {"body": "undecodable"}


def test_every_decode_slot_taken_is_rate_limited(
    make_client: ClientFactory, migrated: Engine
) -> None:
    factory.human(migrated, "busy")
    client = make_client(avatar_decodes=1)
    csrf = _login(client, "busy")
    slot = avatars._slots_for(1)
    assert slot.acquire(blocking=False)
    try:
        answer = client.put(
            "/api/v1/me/avatar",
            content=image(),
            headers={"Content-Type": "image/png", "X-CSRF-Token": csrf},
        )
    finally:
        slot.release()
    assert answer.status_code == 429 and int(answer.headers["Retry-After"]) >= 1


def _login(client: Any, handle: str) -> str:
    response = client.post(
        "/api/v1/auth/login", json={"handle": handle, "password": factory.PASSWORD}
    )
    assert response.status_code == 200, response.text
    csrf: str = client.get("/api/v1/auth/session").json()["csrf_token"]
    return csrf


def test_ten_changes_an_hour_per_avatar(owner: flow.Human) -> None:
    for _ in range(10):
        assert put_human(owner, "/me/avatar", image()).status_code == 200
    limited = put_human(owner, "/me/avatar", image())
    assert limited.status_code == 429 and int(limited.headers["Retry-After"]) > 0
    assert owner.delete("/me/avatar").status_code == 429


def test_a_replay_counts_nothing(owner: flow.Human) -> None:
    key = {"Idempotency-Key": "avatar-replay-0001"}
    for _ in range(12):
        answer = owner.client.put(
            "/api/v1/me/avatar",
            content=image(),
            headers={"Content-Type": "image/png", "X-CSRF-Token": owner.csrf, **key},
        )
        assert answer.status_code == 200, answer.text


def test_an_owner_sets_its_agents_picture(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    answer = put_human(owner, f"/agents/{agent.id}/avatar", image())
    assert answer.status_code == 200, answer.text
    assert answer.json()["avatar_url"].startswith(f"/api/v1/avatars/{agent.id}?v=")
    assert owner.delete(f"/agents/{agent.id}/avatar").json()["avatar_source"] is None
    stranger = flow.human(make_client, migrated, "stranger")
    refused = put_human(stranger, f"/agents/{agent.id}/avatar", image())
    assert refused.status_code == 404


def test_who_may_read_a_picture(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    agent_url = put_agent(agent, image()).json()["avatar_url"]
    owner_url = put_human(owner, "/me/avatar", image()).json()["avatar_url"]
    stranger = flow.human(make_client, migrated, "stranger")
    flow.project(stranger, "elsewhere")
    elsewhere = flow.agent(make_client, stranger, "elsewhere")
    assert owner.client.get(agent_url).status_code == 200  # the agent's owner, a member too
    assert agent.client.get(owner_url, headers=agent.auth).status_code == 200  # shares a project
    for who in (stranger, elsewhere):
        client, headers = (who.client, getattr(who, "auth", {}))
        for url in (agent_url, owner_url):
            answer = client.get(url, headers=headers)
            assert answer.status_code == 404, url
            # Authorized first: no 304 for a caller who may not see it.
            tag = owner.client.get(url).headers["etag"]
            assert client.get(url, headers={**headers, "If-None-Match": tag}).status_code == 404
    assert stranger.client.get("/api/v1/avatars/hum-nobody").status_code == 404


def test_the_picture_is_stored_once_per_owner(owner: flow.Human, migrated: Engine) -> None:
    put_human(owner, "/me/avatar", image())
    put_human(owner, "/me/avatar", image("JPEG"), "image/jpeg")
    with migrated.connect() as conn:
        rows = conn.execute(select(t.avatar_image)).all()
    assert [(r.owner_id, r.source) for r in rows] == [(owner.id, "uploaded")]


def test_a_paused_agent_still_sets_its_picture(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    owner.patch(f"/projects/maity/members/{agent.id}", {"paused": {"reason": "quota"}})
    assert put_agent(agent, image()).status_code == 200  # the avatar is not work


def test_the_instance_admin_reads_a_humans_picture(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    stranger = flow.human(make_client, migrated, "stranger")  # no project shared
    url = put_human(stranger, "/me/avatar", image()).json()["avatar_url"]
    assert owner.client.get(url).status_code == 200  # the earliest human (§16)


def _changed(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.event).where(t.event.c.kind == "avatar_changed").order_by(t.event.c.seq)
            )
        )


def test_avatar_changed_only_when_the_picture_changes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "second")
    agent = flow.agent(make_client, owner)
    url = put_human(owner, "/me/avatar", image()).json()["avatar_url"]
    events = _changed(migrated)
    assert len(events) == 2  # one per project the member is in
    assert {e.payload["avatar_url"] for e in events} == {url}
    assert all(e.audience == ["all"] and e.subject_id == owner.id for e in events)
    assert all(e.actor_membership is not None for e in events)  # its own change
    put_human(owner, "/me/avatar", image())  # the same bytes: the same picture
    assert len(_changed(migrated)) == 2
    owner.delete(f"/agents/{agent.id}/avatar")  # nothing uploaded: nothing changes
    assert len(_changed(migrated)) == 2
    put_human(owner, f"/agents/{agent.id}/avatar", image("JPEG"), "image/jpeg")
    [by_owner] = _changed(migrated)[2:]
    assert by_owner.payload["member_id"] == agent.id
    assert by_owner.actor_membership is None  # an owner's change names nobody
    put_agent(agent, image("PNG", (90, 90)))
    [own] = _changed(migrated)[3:]
    assert own.actor_membership is not None
    owner.delete("/me/avatar")
    assert [e.payload["avatar_url"] for e in _changed(migrated)[4:]] == [None, None]


def test_avatar_changed_wakes_nobody(owner: flow.Human, make_client: ClientFactory) -> None:
    from maity_hub import events

    assert "avatar_changed" in events.NON_WAKING


# --- the decoder's own defences (review of #218) ---------------------------------------


def _apng_claiming(width: int, height: int) -> bytes:
    """A tiny APNG whose header claims a huge canvas (GHSA-5xm2)."""
    import struct
    import zlib

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    actl = struct.pack(">II", 1, 0)
    fctl = struct.pack(">IIIIIHHBB", 0, 1, 1, 0, 0, 1, 1, 1, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"acTL", actl)
        + chunk(b"fcTL", fctl)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (_apng_claiming(22000, 22000), "image/png"),
        (image("JPEG", (4097, 8)), "image/jpeg"),
        (image("WEBP", (8, 4097)), "image/webp"),
        (image("WEBP", (4097, 8), lossless=True), "image/webp"),
    ],
)
def test_a_size_past_4096_is_refused_from_the_header(
    owner: flow.Human, monkeypatch: pytest.MonkeyPatch, data: bytes, content_type: str
) -> None:
    from maity_hub import avatar_decode

    with pytest.raises(avatar_decode.Refused) as refused:
        avatar_decode.dimensions(data, content_type) and avatar_decode.process(data, content_type)
    assert refused.value.reason == "dimensions"
    answer = put_human(owner, "/me/avatar", data, content_type)
    assert answer.json()["error"]["details"]["fields"] == {"body": "dimensions"}


def test_the_decoder_runs_isolated(owner: flow.Human, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    real = subprocess.run

    def spy(command: list[str], **kwargs: Any) -> Any:
        seen.update(command=command, env=kwargs.get("env"))
        return real(command, **kwargs)

    monkeypatch.setattr("maity_hub.avatars.subprocess.run", spy)
    assert put_human(owner, "/me/avatar", image()).status_code == 200
    assert seen["env"] == {}  # no database URL, no forge token in the child
    assert seen["command"][1] == "-I" and seen["command"][2].endswith("avatar_decode.py")


def test_a_crash_is_undecodable_and_logged(
    owner: flow.Human, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def crashed(command: list[str], **kwargs: Any) -> Any:
        return subprocess.CompletedProcess(command, -11, b"", b"Segmentation fault")

    monkeypatch.setattr("maity_hub.avatars.subprocess.run", crashed)
    with caplog.at_level("WARNING", logger="maity_hub.avatars"):
        answer = put_human(owner, "/me/avatar", image())
    assert answer.json()["error"]["details"]["fields"] == {"body": "undecodable"}
    assert any("signal 11" in r.getMessage() for r in caplog.records)


def test_a_replay_past_the_limit_is_the_stored_answer(owner: flow.Human) -> None:
    key = {"Idempotency-Key": "avatar-replay-limit-1"}
    headers = {"Content-Type": "image/png", "X-CSRF-Token": owner.csrf}
    first = owner.client.put("/api/v1/me/avatar", content=image(), headers={**headers, **key})
    assert first.status_code == 200
    for _ in range(9):
        assert put_human(owner, "/me/avatar", image("PNG", (90, 90))).status_code == 200
    replay = owner.client.put("/api/v1/me/avatar", content=image(), headers={**headers, **key})
    assert replay.status_code == 200 and replay.headers["Idempotent-Replayed"] == "true"


def test_a_jpegs_orientation_is_applied(owner: flow.Human) -> None:
    picture = Image.new("RGB", (40, 20), (255, 0, 0))
    picture.paste((0, 0, 255), (20, 0, 40, 20))  # left red, right blue
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise to view
    out = io.BytesIO()
    picture.save(out, format="JPEG", exif=exif.tobytes(), quality=95)
    url = put_human(owner, "/me/avatar", out.getvalue(), "image/jpeg").json()["avatar_url"]
    stored = Image.open(io.BytesIO(owner.client.get(url).content)).convert("RGB")
    top = typing.cast(tuple[int, ...], stored.getpixel((10, 2)))
    bottom = typing.cast(tuple[int, ...], stored.getpixel((10, 17)))
    assert top[0] > 200 and bottom[2] > 200  # red on top once turned as seen


def test_sixteen_bit_grey_is_scaled_not_clipped(owner: flow.Human) -> None:
    grey = Image.new("I;16", (32, 32), 1000)
    out = io.BytesIO()
    grey.save(out, format="PNG")
    url = put_human(owner, "/me/avatar", out.getvalue()).json()["avatar_url"]
    stored = Image.open(io.BytesIO(owner.client.get(url).content))
    assert typing.cast(tuple[int, ...], stored.getpixel((5, 5)))[0] < 10  # 1000/65535: near black


def test_a_project_admin_sees_the_owner_of_an_agent_in_its_project(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    stranger = flow.human(make_client, migrated, "stranger")  # in no project of owner's
    factory.agent(migrated, project_id, stranger.id)  # but its agent is
    url = put_human(stranger, "/me/avatar", image()).json()["avatar_url"]
    admin = flow.human(make_client, migrated, "project-admin")
    factory.membership(migrated, project_id, "admin", human_id=admin.id)
    member = flow.human(make_client, migrated, "plain-member")
    factory.membership(migrated, project_id, "member", human_id=member.id)
    assert admin.client.get(url).status_code == 200
    assert member.client.get(url).status_code == 404


def test_the_instance_admin_does_not_read_an_agents_picture_elsewhere(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    stranger = flow.human(make_client, migrated, "stranger")
    flow.project(stranger, "elsewhere")
    theirs = flow.agent(make_client, stranger, "elsewhere")
    url = put_agent(theirs, image()).json()["avatar_url"]
    assert owner.client.get(url).status_code == 404  # instance admin: humans' pictures only


def test_a_runner_and_a_stranger_change_no_picture(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from tests.test_runners import call, paired

    runner = paired(make_client, owner)
    refused = call(make_client(), runner, "PUT", "/api/v1/me/avatar")
    assert refused.status_code == 403
    agent = flow.agent(make_client, owner)
    put_human(owner, f"/agents/{agent.id}/avatar", image())
    stranger = flow.human(make_client, migrated, "stranger")
    assert stranger.delete(f"/agents/{agent.id}/avatar").status_code == 404
    assert owner.get(f"/agents/{agent.id}").json()["avatar_source"] == "uploaded"
