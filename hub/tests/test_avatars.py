"""docs/api.md §6.10: a member's picture — upload, re-encoding, who reads it, avatar_url."""

from __future__ import annotations

import io
import subprocess
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
        (image("PNG", (5000, 20)), "image/png", "too_many_pixels"),
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
    assert answer.json()["error"]["details"]["fields"] == {"body": "text_too_large"}
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
    assert answer.json()["error"]["details"]["fields"] == {"body": "over_budget"}


def test_over_the_time_budget_is_refused(
    owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow(command: list[str], **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr("maity_hub.avatars.subprocess.run", slow)
    answer = put_human(owner, "/me/avatar", image())
    assert answer.json()["error"]["details"]["fields"] == {"body": "over_budget"}


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
