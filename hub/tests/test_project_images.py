"""docs/api.md §11.2: a project's logo and banner — uploaded, from the forge, or none."""

from __future__ import annotations

import threading
import urllib.parse
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import events, forge, images, outbound
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\1" * 64
WEBP = b"RIFF\x10\0\0\0WEBPVP8 " + b"\2" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
REPO = "https://github.com/acme/widget"
AVATAR = "https://avatars.githubusercontent.com/u/1?v=4"
PREVIEW = "https://repository-images.githubusercontent.com/1/banner"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def put(human: flow.Human, path: str, data: bytes, content_type: str, **headers: str) -> Any:
    return human.client.put(
        f"/api/v1{path}",
        content=data,
        headers={"Content-Type": content_type, "X-CSRF-Token": human.csrf, **headers},
    )


class FakeForge:
    """The forge's answers about images, and the image hosts' answers."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.avatar: str | None = AVATAR
        self.preview: str | None = PREVIEW
        self.bodies: dict[str, Any] = {AVATAR: PNG, PREVIEW: JPEG}
        self.forge_down = False
        self.reads: list[str] = []
        fake = self

        def owner_avatar(self: forge.Forge, repository: str) -> str | None:
            fake.reads.append(f"avatar {repository}")
            if fake.forge_down:
                raise forge.ForgeUnavailableError("down")
            return fake.avatar

        def social_preview(self: forge.Forge, repository: str) -> str | None:
            fake.reads.append(f"preview {repository}")
            if fake.forge_down:
                raise forge.ForgeUnavailableError("down")
            return fake.preview if self.token is not None else None

        def read(url: str, *, cap: int, host: str | None = None, **kwargs: Any) -> outbound.Answer:
            if host is not None and urllib.parse.urlsplit(url).hostname != host:
                raise outbound.Refused("url_invalid")  # what the real read does
            fake.reads.append(f"image {url}")
            body = fake.bodies.get(url)
            if isinstance(body, outbound.Refused):
                raise body
            if body is None:
                return outbound.Answer(404, {}, b"")
            if len(body) > cap:
                raise outbound.Refused("too_large")
            return outbound.Answer(200, {}, body)

        monkeypatch.setattr(forge.Forge, "owner_avatar", owner_avatar)
        monkeypatch.setattr(forge.Forge, "social_preview", social_preview)
        monkeypatch.setattr(outbound, "read", read)


@pytest.fixture
def fake_forge(monkeypatch: pytest.MonkeyPatch) -> FakeForge:
    return FakeForge(monkeypatch)


def events_of(engine: Engine, kind: str) -> list[Any]:
    with engine.begin() as conn:
        return list(conn.execute(select(t.event).where(t.event.c.kind == kind)).all())


# --- what the hub accepts ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "kind"),
    [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp"), (SVG, None),
     (b"GIF89a....", None), (b"<html>", None), (b"RIFF\0\0\0\0WAVE", None), (b"", None)],
)  # fmt: skip
def test_the_type_comes_from_the_magic_bytes(data: bytes, kind: str | None) -> None:
    assert images.sniff(data) == kind


# --- uploads ----------------------------------------------------------------------------------


def test_an_upload_is_served_with_the_image_headers(owner: flow.Human, migrated: Engine) -> None:
    flow.project(owner, "maity")
    answer = put(owner, "/projects/maity/logo", PNG, "image/png")
    assert answer.status_code == 200, answer.text
    state = answer.json()["logo"]
    assert state["available"] is True and state["source"] == "uploaded"
    got = owner.get("/projects/maity/logo")
    assert got.status_code == 200
    assert got.content == PNG
    assert got.headers["content-type"] == "image/png"
    assert got.headers["etag"] == state["etag"]
    assert got.headers["cache-control"] == "private, max-age=21600"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert got.headers["cross-origin-resource-policy"] == "same-origin"
    view = owner.get("/projects/maity").json()
    assert view["logo"] == state
    assert view["banner"] == {"available": False, "source": None}
    assert owner.get("/projects/maity").headers["cache-control"] == "no-store"


def test_me_carries_each_projects_logo(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    flow.project(owner, "other")
    tag = put(owner, "/projects/maity/logo", PNG, "image/png").json()["logo"]["etag"]
    logos = {p["slug"]: p["logo"] for p in owner.get("/me").json()["projects"]}
    assert logos == {
        "maity": {"available": True, "etag": tag},
        "other": {"available": False, "etag": None},
    }


def test_a_matching_etag_is_304_without_a_body(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    tag = put(owner, "/projects/maity/banner", WEBP, "image/webp").json()["banner"]["etag"]
    again = owner.get("/projects/maity/banner", headers={"If-None-Match": f'W/{tag}, "other"'})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == tag
    assert again.headers["cache-control"] == "private, max-age=21600"


@pytest.mark.parametrize(
    ("data", "declared"),
    [(SVG, "image/svg+xml"), (PNG, "image/jpeg"), (b"plain", "image/png"), (PNG, "")],
)
def test_anything_but_a_sniffed_and_declared_image_is_refused(
    owner: flow.Human, data: bytes, declared: str
) -> None:
    flow.project(owner, "maity")
    answer = put(owner, "/projects/maity/logo", data, declared)
    assert answer.status_code == 400
    assert answer.json()["error"]["details"]["fields"] == {"body": "unsupported_type"}


def test_one_mebibyte_is_accepted_one_byte_more_is_too_large(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    exact = PNG + b"\0" * (images.CAP - len(PNG))
    assert put(owner, "/projects/maity/logo", exact, "image/png").status_code == 200
    over = put(owner, "/projects/maity/logo", exact + b"\0", "image/png")
    assert over.status_code == 400
    assert over.json()["error"]["details"]["fields"] == {"body": "too_large"}


def test_the_64_kib_cap_still_holds_elsewhere(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    big = owner.patch("/projects/maity", {"name": "x" * (70 * 1024)})
    assert big.status_code == 413


def test_an_agent_may_not_upload_whatever_its_scopes(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    flow.project(owner, "maity")
    agent = flow.agent(make_client, owner, "maity", role="admin")
    answer = agent.client.put(
        "/api/v1/projects/maity/logo",
        content=PNG,
        headers=agent.auth | agent.key() | {"Content-Type": "image/png"},
    )
    assert answer.status_code == 403
    assert answer.json()["error"]["code"] == "forbidden"
    assert agent.get("/projects/maity/logo").status_code == 404  # reading is project:read


def test_a_human_member_without_project_admin_may_not_upload(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "maity")
    other = flow.human(make_client, migrated, "reviewer")
    with migrated.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, role="member", human_id=other.id)
    assert put(other, "/projects/maity/logo", PNG, "image/png").status_code == 403
    assert other.get("/projects/maity/logo").status_code == 404  # may read: there is none


def test_an_upload_needs_the_csrf_token(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    answer = owner.client.put(
        "/api/v1/projects/maity/logo", content=PNG, headers={"Content-Type": "image/png"}
    )
    assert answer.status_code == 403
    assert answer.json()["error"]["code"] == "csrf_mismatch"


def test_an_upload_replaces_the_last_and_announces_without_bytes(
    owner: flow.Human, migrated: Engine
) -> None:
    flow.project(owner, "maity")
    first = put(owner, "/projects/maity/logo", PNG, "image/png").json()["logo"]
    second = put(owner, "/projects/maity/logo", JPEG, "image/jpeg").json()["logo"]
    assert first["etag"] != second["etag"]
    assert owner.get("/projects/maity/logo").content == JPEG
    announced = events_of(migrated, "project_updated")
    assert [e.payload for e in announced] == [
        {"fields": {"logo": first}},
        {"fields": {"logo": second}},
    ]
    assert all(e.audience == ["all"] for e in announced)


def test_the_same_upload_twice_announces_once(owner: flow.Human, migrated: Engine) -> None:
    flow.project(owner, "maity")
    put(owner, "/projects/maity/logo", PNG, "image/png")
    put(owner, "/projects/maity/logo", PNG, "image/png")
    assert len(events_of(migrated, "project_updated")) == 1


def test_project_updated_wakes_nobody(owner: flow.Human, migrated: Engine) -> None:
    flow.project(owner, "maity")
    put(owner, "/projects/maity/logo", PNG, "image/png")
    [event] = events_of(migrated, "project_updated")

    class Reader:
        id = -1
        role = "member"

    assert events.readable_by(event, Reader(), "agt-x")
    assert not events.wakes(event, Reader(), "agt-x")


def test_delete_removes_the_upload_and_is_idempotent(owner: flow.Human, migrated: Engine) -> None:
    flow.project(owner, "maity")
    put(owner, "/projects/maity/logo", PNG, "image/png")
    gone = owner.delete("/projects/maity/logo")
    assert gone.status_code == 200
    assert gone.json() == {"logo": {"available": False, "source": None}}
    assert owner.delete("/projects/maity/logo").status_code == 200
    assert owner.get("/projects/maity/logo").status_code == 404
    assert len(events_of(migrated, "project_updated")) == 2  # the upload and the delete


def test_an_idempotent_replay_answers_the_state(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    key = {"Idempotency-Key": "logo-upload-key-0001"}
    first = put(owner, "/projects/maity/logo", PNG, "image/png", **key)
    again = put(owner, "/projects/maity/logo", PNG, "image/png", **key)
    assert again.headers.get("idempotent-replayed") == "true"
    assert again.json() == first.json()
    other = put(owner, "/projects/maity/logo", JPEG, "image/jpeg", **key)
    assert other.status_code == 409


def test_no_repository_and_no_upload_is_not_found(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    answer = owner.get("/projects/maity/banner")
    assert answer.status_code == 404
    assert answer.headers["cache-control"] == "no-store"


# --- the forge --------------------------------------------------------------------------------


def test_the_forge_logo_is_read_once_and_then_served_from_the_hub(
    owner: flow.Human, fake_forge: FakeForge, migrated: Engine
) -> None:
    flow.project(owner, "maity", repository={"url": REPO})
    got = owner.get("/projects/maity/logo")
    assert got.status_code == 200 and got.content == PNG
    assert fake_forge.reads == ["avatar acme/widget", f"image {AVATAR}"]
    assert owner.get("/projects/maity/logo").content == PNG
    assert len(fake_forge.reads) == 2  # stored: no second read
    view = owner.get("/projects/maity").json()["logo"]
    assert view["source"] == "forge" and view["available"] is True
    [event] = events_of(migrated, "project_updated")
    assert event.payload == {"fields": {"logo": view}}


def test_without_a_token_there_is_no_banner(owner: flow.Human, fake_forge: FakeForge) -> None:
    flow.project(owner, "maity", repository={"url": REPO})
    assert owner.get("/projects/maity/banner").status_code == 404
    assert owner.get("/projects/maity/banner").status_code == 404
    assert fake_forge.reads == ["preview acme/widget"]  # the "none" is stored, read once


def test_with_a_token_the_custom_social_preview_is_the_banner(
    make_client: ClientFactory, migrated: Engine, fake_forge: FakeForge
) -> None:
    human_id = factory.human(migrated, "maintainer")
    client = make_client(forge_github_token="ghp_test_token")
    login = client.post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert login.status_code == 200, login.text
    human = flow.Human(client, client.get("/api/v1/auth/session").json()["csrf_token"], human_id)
    flow.project(human, "maity", repository={"url": REPO})
    got = human.get("/projects/maity/banner")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/jpeg"
    fake_forge.preview = None  # GitHub's generated card: no banner
    assert human.get("/projects/maity").json()["banner"]["source"] == "forge"


@pytest.mark.parametrize(
    "body",
    [SVG, b"x" * (images.CAP + 1), None, outbound.Refused("too_large")],
    ids=["svg", "too-large", "404", "refused-too-large"],
)
def test_a_forge_image_the_rules_refuse_is_no_image(
    owner: flow.Human, fake_forge: FakeForge, body: Any
) -> None:
    fake_forge.bodies[AVATAR] = body
    flow.project(owner, "maity", repository={"url": REPO})
    assert owner.get("/projects/maity/logo").status_code == 404


def test_an_image_on_another_host_is_no_image(owner: flow.Human, fake_forge: FakeForge) -> None:
    fake_forge.avatar = "https://www.gravatar.com/avatar/1"
    flow.project(owner, "maity", repository={"url": REPO})
    assert owner.get("/projects/maity/logo").status_code == 404
    assert not any(r.startswith("image ") for r in fake_forge.reads)


def test_a_forge_that_does_not_answer_with_nothing_stored_is_probe_unavailable(
    owner: flow.Human, fake_forge: FakeForge
) -> None:
    fake_forge.forge_down = True
    flow.project(owner, "maity", repository={"url": REPO})
    answer = owner.get("/projects/maity/logo")
    assert answer.status_code == 503
    assert answer.json()["error"]["code"] == "probe_unavailable"


def test_an_unreachable_image_host_is_probe_unavailable_too(
    owner: flow.Human, fake_forge: FakeForge
) -> None:
    fake_forge.bodies[AVATAR] = outbound.Refused("timeout")
    flow.project(owner, "maity", repository={"url": REPO})
    assert owner.get("/projects/maity/logo").status_code == 503


def test_an_upload_wins_over_the_forge_and_its_delete_brings_the_forge_back(
    owner: flow.Human, fake_forge: FakeForge
) -> None:
    flow.project(owner, "maity", repository={"url": REPO})
    assert owner.get("/projects/maity/logo").content == PNG  # the forge's
    put(owner, "/projects/maity/logo", JPEG, "image/jpeg")
    assert owner.get("/projects/maity/logo").content == JPEG
    back = owner.delete("/projects/maity/logo").json()["logo"]
    assert back["source"] == "forge"
    assert owner.get("/projects/maity/logo").content == PNG


def test_a_refresh_that_fails_keeps_the_image_and_one_that_changes_it_announces(
    owner: flow.Human, fake_forge: FakeForge, migrated: Engine
) -> None:
    flow.project(owner, "maity", repository={"url": REPO})
    owner.get("/projects/maity/logo")
    with migrated.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    fake_forge.forge_down = True
    assert images.refresh(migrated, forge.Forge(None), project_id, "logo") is False
    assert owner.get("/projects/maity/logo").content == PNG
    fake_forge.forge_down = False
    fake_forge.bodies[AVATAR] = WEBP
    assert images.refresh(migrated, forge.Forge(None), project_id, "logo") is True
    assert owner.get("/projects/maity/logo").content == WEBP
    assert len(events_of(migrated, "project_updated")) == 2
    fake_forge.avatar = None  # the forge now has none: the image is dropped
    images.refresh(migrated, forge.Forge(None), project_id, "logo")
    assert owner.get("/projects/maity/logo").status_code == 404
    assert owner.get("/projects/maity").json()["logo"] == {"available": False, "source": None}


def test_the_worker_finds_what_is_stale(
    owner: flow.Human, fake_forge: FakeForge, migrated: Engine
) -> None:
    flow.project(owner, "maity", repository={"url": REPO})
    flow.project(owner, "local")
    with migrated.begin() as conn:
        project_id = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "maity")
        ).scalar_one()
        assert sorted(images.stale(conn)) == [(project_id, "banner"), (project_id, "logo")]
    images.Worker(migrated, forge.Forge(None)).sweep()
    with migrated.begin() as conn:
        assert images.stale(conn) == []
    assert owner.get("/projects/maity").json()["logo"]["source"] == "forge"


def test_a_new_repository_drops_the_old_forge_images(
    owner: flow.Human, fake_forge: FakeForge
) -> None:
    flow.project(owner, "maity", repository={"url": REPO})
    owner.get("/projects/maity/logo")
    owner.patch("/projects/maity", {"repository": {"url": "https://github.com/acme/other"}})
    assert owner.get("/projects/maity").json()["logo"] == {"available": False, "source": None}
    owner.get("/projects/maity/logo")
    assert fake_forge.reads[-2] == "avatar acme/other"


# --- a forge that does not answer --------------------------------------------------------------


def test_after_a_failed_read_through_gets_answer_503_without_reading_for_a_minute(
    owner: flow.Human, fake_forge: FakeForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock_now = [1000.0]
    monkeypatch.setattr(images, "_now", lambda: clock_now[0])
    fake_forge.forge_down = True
    flow.project(owner, "maity", repository={"url": REPO})
    assert owner.get("/projects/maity/logo").status_code == 503
    reads = len(fake_forge.reads)
    assert owner.get("/projects/maity/logo").status_code == 503
    assert len(fake_forge.reads) == reads  # no second read inside the minute
    clock_now[0] += images.NEGATIVE + 1
    fake_forge.forge_down = False
    assert owner.get("/projects/maity/logo").content == PNG


def test_concurrent_read_throughs_read_the_forge_once(
    owner: flow.Human, fake_forge: FakeForge, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow.project(owner, "maity", repository={"url": REPO})
    with migrated.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    slow = threading.Event()
    original = forge.Forge.owner_avatar

    def owner_avatar(self: forge.Forge, repository: str) -> str | None:
        slow.wait(0.3)
        return original(self, repository)

    monkeypatch.setattr(forge.Forge, "owner_avatar", owner_avatar)
    results: list[bool] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(
                images.read_through(migrated, forge.Forge(None), project_id, "logo")
            )
        )
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [True] * 4
    assert fake_forge.reads.count("avatar acme/widget") == 1


def test_the_worker_backs_off_after_failures(
    owner: flow.Human, fake_forge: FakeForge, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock_now = [1000.0]
    monkeypatch.setattr(images, "_now", lambda: clock_now[0])
    flow.project(owner, "maity", repository={"url": REPO})
    fake_forge.forge_down = True
    worker = images.Worker(migrated, forge.Forge(None))
    worker.sweep()
    first = len(fake_forge.reads)
    worker.sweep()
    assert len(fake_forge.reads) == first  # backing off
    clock_now[0] += images.INTERVAL + 1
    worker.sweep()
    assert len(fake_forge.reads) > first
    second = len(fake_forge.reads)
    clock_now[0] += images.INTERVAL + 1  # the second failure doubled the wait
    worker.sweep()
    assert len(fake_forge.reads) == second
    clock_now[0] += images.INTERVAL
    fake_forge.forge_down = False
    worker.sweep()
    with migrated.begin() as conn:
        assert images.stale(conn) == []


def test_every_other_answer_is_still_no_store(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    put(owner, "/projects/maity/logo", PNG, "image/png")
    for path in ("/api/v1/health", "/api/v1/projects/maity", "/api/v1/me", "/"):
        answer = owner.client.get(path)
        assert answer.headers["cache-control"] == "no-store", path
