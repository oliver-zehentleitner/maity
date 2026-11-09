"""docs/api.md §8.7 and §16.5: the limits on the attachments one project and the whole
instance store."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Connection, Engine

from maity_hub import attachments
from maity_hub.config import ConfigError, Settings
from tests import flow
from tests.conftest import ClientFactory
from tests.test_attachments import put

PATH = "/admin/settings/limits"
MIB = 1024**2
GIB = 1024**3
PIB = 1024**5


@pytest.fixture(autouse=True)
def _fresh_limits() -> Iterator[None]:
    attachments.UPLOADS.reset()
    attachments.VOLUME.reset()
    yield
    attachments.UPLOADS.reset()
    attachments.VOLUME.reset()


@pytest.fixture
def stored(make_client: ClientFactory, tmp_path: Path) -> ClientFactory:
    blobs = tmp_path / "blobs"
    blobs.mkdir()

    def factory(**overrides: Any) -> Any:
        return make_client(attachment_dir=blobs, **overrides)

    return factory


@pytest.fixture
def admin(stored: ClientFactory, migrated: Engine) -> flow.Human:
    """The instance admin, owner of `maintainer/maity`."""
    who = flow.human(stored, migrated)
    flow.project(who, "maity")
    return who


def put_in(who: flow.Human, slug: str, name: str, size: int) -> Any:
    return who.client.post(
        f"/api/v1/projects/maintainer/{slug}/attachments?name={name}",
        content=b"x" * size,
        headers={"Content-Type": "application/octet-stream", "X-CSRF-Token": who.csrf},
    )


def room_of(monkeypatch: pytest.MonkeyPatch, room: int) -> None:
    """The smallest limit is 1 GiB: the instance's total is raised so that `room` bytes are
    left under it, whatever the uploads add."""
    real = attachments.used_total
    monkeypatch.setattr(attachments, "used_total", lambda conn: real(conn) + GIB - room)


def test_the_default_is_unlimited_and_the_total_counts_every_project_and_pending_uploads(
    admin: flow.Human,
) -> None:
    got = admin.get(PATH).json()
    assert got["max_attachment_storage"] == {"value": "unlimited", "source": "default"}
    assert got["attachment_storage_used"] == 0
    flow.project(admin, "other")
    first = put_in(admin, "maity", "a.bin", 1500).json()  # pending: no message names it
    assert put_in(admin, "other", "b.bin", 700).status_code == 201
    assert admin.get(PATH).json()["attachment_storage_used"] == 2200
    deleted = admin.delete(f"/projects/maintainer/maity/attachments/{first['id']}")
    assert deleted.status_code == 200
    assert admin.get(PATH).json()["attachment_storage_used"] == 700


def test_the_value_is_bytes_from_one_gib_to_one_pib_or_unlimited(admin: flow.Human) -> None:
    for good in (GIB, PIB, "unlimited"):
        got = admin.patch(PATH, {"max_attachment_storage": good})
        assert got.status_code == 200, got.text
        assert got.json()["max_attachment_storage"] == {"value": good, "source": "admin"}
    for bad in (GIB - 1, PIB + 1, 0, True, 1.5, "lots", [GIB]):
        refused = admin.patch(PATH, {"max_attachment_storage": bad})
        assert refused.status_code == 400, bad
        assert refused.json()["error"]["details"]["fields"] == {"max_attachment_storage": "invalid"}
    read_only = admin.patch(PATH, {"attachment_storage_used": 1})
    assert read_only.json()["error"]["details"]["fields"] == {
        "attachment_storage_used": "read_only"
    }
    back = admin.patch(PATH, {"max_attachment_storage": None}).json()
    assert back["max_attachment_storage"] == {"value": "unlimited", "source": "default"}


def test_the_environment_sets_it_and_a_bad_value_stops_the_hub(
    stored: ClientFactory, migrated: Engine, tmp_path: Path
) -> None:
    base = {"MAITY_DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}"}
    assert Settings.from_env(base).max_attachment_storage is None
    assert (
        Settings.from_env({**base, "MAITY_MAX_ATTACHMENT_STORAGE": ""}).max_attachment_storage
        is None
    )
    for good, value in ((str(GIB), GIB), ("unlimited", "unlimited")):
        env = {**base, "MAITY_MAX_ATTACHMENT_STORAGE": good}
        assert Settings.from_env(env).max_attachment_storage == value
    for bad in (str(GIB - 1), str(PIB + 1), "1GiB", "-5"):
        with pytest.raises(ConfigError, match="MAITY_MAX_ATTACHMENT_STORAGE"):
            Settings.from_env({**base, "MAITY_MAX_ATTACHMENT_STORAGE": bad})
    who = flow.human(lambda **kw: stored(max_attachment_storage=2 * GIB, **kw), migrated)
    assert who.get(PATH).json()["max_attachment_storage"] == {"value": 2 * GIB, "source": "env"}
    refused = who.patch(PATH, {"max_attachment_storage": GIB})
    assert refused.json()["error"]["details"]["fields"] == {
        "max_attachment_storage": "set_by_environment"
    }


def test_an_upload_over_the_limit_is_refused_in_any_project_without_numbers(
    admin: flow.Human, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert admin.patch(PATH, {"max_attachment_storage": GIB}).status_code == 200
    room_of(monkeypatch, 2000)
    flow.project(admin, "other")
    first = put_in(admin, "maity", "a.bin", 1500)
    assert first.status_code == 201, first.text
    over = put_in(admin, "other", "b.bin", 1000)  # the other project's quota has room
    assert over.status_code == 409, over.text
    assert over.json()["error"]["code"] == "attachment_quota"
    assert over.json()["error"]["details"] == {"scope": "instance"}
    assert [p.name for p in (tmp_path / "blobs").glob("*/*")] == [first.json()["id"]]
    assert put_in(admin, "other", "c.bin", 500).status_code == 201  # exactly at the limit
    deleted = admin.delete(f"/projects/maintainer/maity/attachments/{first.json()['id']}")
    assert deleted.status_code == 200
    assert put_in(admin, "other", "b.bin", 1000).status_code == 201  # deleting frees it


def test_the_project_quota_and_the_pending_cap_are_checked_first(
    stored: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    who = flow.human(lambda **kw: stored(max_attachment_storage_per_project=2048, **kw), migrated)
    flow.project(who, "maity")
    assert who.patch(PATH, {"max_attachment_storage": GIB}).status_code == 200
    room_of(monkeypatch, 100)
    over = put(who, "a.bin", b"x" * 3000, "application/octet-stream")
    assert over.json()["error"]["details"]["scope"] == "project"


def test_the_pending_cap_is_checked_before_the_instance(
    admin: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(attachments, "PENDING_COUNT", 1)
    assert put_in(admin, "maity", "a.bin", 100).status_code == 201  # pending: the cap is full
    assert admin.patch(PATH, {"max_attachment_storage": GIB}).status_code == 200
    room_of(monkeypatch, 0)  # the instance is full too
    over = put_in(admin, "maity", "b.bin", 10)
    assert over.json()["error"]["details"]["scope"] == "pending", over.text


def test_lowering_the_limit_deletes_nothing(
    admin: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = put_in(admin, "maity", "a.bin", 1500).json()
    assert admin.patch(PATH, {"max_attachment_storage": GIB}).status_code == 200
    room_of(monkeypatch, 0)  # the instance is over its new limit
    assert put_in(admin, "maity", "b.bin", 10).json()["error"]["details"] == {"scope": "instance"}
    got = admin.get(f"/projects/maintainer/maity/attachments/{shown['id']}")
    assert got.status_code == 200


def test_unlimited_reads_no_total(admin: flow.Human, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_read(conn: Connection) -> int:
        raise AssertionError("the total is read only under a limit")

    monkeypatch.setattr(attachments, "used_total", no_read)
    assert put_in(admin, "maity", "a.bin", 1500).status_code == 201


PER_PROJECT = "max_attachment_storage_per_project"
PROJECT = "/projects/maintainer/maity"


def project_used_of(monkeypatch: pytest.MonkeyPatch, extra: int) -> None:
    """The project's own total is raised by `extra` bytes, so that a limit of 1 MiB or more
    is reached without uploading a MiB."""
    real = attachments.used
    monkeypatch.setattr(
        attachments, "used", lambda conn, project_id: real(conn, project_id) + extra
    )


def test_the_project_limit_defaults_to_one_gib_and_the_admin_sets_it(admin: flow.Human) -> None:
    got = admin.get(PATH).json()
    assert got[PER_PROJECT] == {"value": GIB, "source": "default"}
    assert admin.get(PROJECT).json()["attachments"]["quota"] == GIB
    for good in (MIB, 5 * GIB, PIB, "unlimited"):
        changed = admin.patch(PATH, {PER_PROJECT: good})
        assert changed.status_code == 200, changed.text
        assert changed.json()[PER_PROJECT] == {"value": good, "source": "admin"}
    for bad in (MIB - 1, PIB + 1, 0, -1, "1GiB", "1048576", True, 1.5):
        refused = admin.patch(PATH, {PER_PROJECT: bad})
        assert refused.status_code == 400, (bad, refused.text)
        assert refused.json()["error"]["details"]["fields"] == {PER_PROJECT: "invalid"}
    back = admin.patch(PATH, {PER_PROJECT: None}).json()
    assert back[PER_PROJECT] == {"value": GIB, "source": "default"}


def test_the_environment_sets_the_project_limit_and_a_bad_value_stops_the_hub(
    stored: ClientFactory, migrated: Engine, tmp_path: Path
) -> None:
    name = "MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT"
    base = {"MAITY_DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}"}
    assert Settings.from_env(base).max_attachment_storage_per_project is None
    assert Settings.from_env({**base, name: ""}).max_attachment_storage_per_project is None
    for good, value in ((str(MIB), MIB), (str(PIB), PIB), ("unlimited", "unlimited")):
        assert Settings.from_env({**base, name: good}).max_attachment_storage_per_project == value
    for bad in (str(MIB - 1), str(PIB + 1), "1GiB", "-5", "lots"):
        with pytest.raises(ConfigError, match=name):
            Settings.from_env({**base, name: bad})
    who = flow.human(
        lambda **kw: stored(max_attachment_storage_per_project=2 * MIB, **kw), migrated
    )
    flow.project(who, "maity")
    assert who.get(PATH).json()[PER_PROJECT] == {"value": 2 * MIB, "source": "env"}
    assert who.get(PROJECT).json()["attachments"]["quota"] == 2 * MIB
    refused = who.patch(PATH, {PER_PROJECT: GIB})
    assert refused.json()["error"]["details"]["fields"] == {PER_PROJECT: "set_by_environment"}


def test_the_old_quota_variable_is_not_read(stored: ClientFactory, tmp_path: Path) -> None:
    """No legacy (context/attachments.md 24123f11): `MAITY_ATTACHMENT_QUOTA` sets nothing."""
    base = {"MAITY_DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}"}
    hub = Settings.from_env({**base, "MAITY_ATTACHMENT_QUOTA": "2048"})
    assert hub.max_attachment_storage_per_project is None
    assert not hasattr(hub, "attachment_quota")


def test_an_upload_over_the_admins_project_limit_is_refused_with_its_numbers(
    admin: flow.Human, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = put(admin, "a.bin", b"x" * 1500, "application/octet-stream")
    assert first.status_code == 201, first.text
    assert admin.patch(PATH, {PER_PROJECT: MIB}).status_code == 200
    project_used_of(monkeypatch, MIB - 2000)  # 1500 stored: 500 bytes left
    over = put(admin, "b.bin", b"x" * 501, "application/octet-stream")
    assert over.status_code == 409, over.text
    assert over.json()["error"]["code"] == "attachment_quota"
    assert over.json()["error"]["details"] == {
        "scope": "project",
        "used": MIB - 500,
        "quota": MIB,
    }
    assert [p.name for p in (tmp_path / "blobs").glob("*/*")] == [first.json()["id"]]
    assert put(admin, "c.bin", b"x" * 500, "application/octet-stream").status_code == 201
    shown = admin.get(PROJECT).json()["attachments"]
    assert shown == {"used": MIB, "quota": MIB}


def test_lowering_the_project_limit_deletes_nothing_and_refuses_until_under_it(
    admin: flow.Human, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    kept = [put(admin, f"{n}.bin", b"x" * 1000, "application/octet-stream") for n in "ab"]
    assert all(r.status_code == 201 for r in kept)
    project_used_of(monkeypatch, MIB - 1500)  # 2000 stored: 500 over the lowered limit
    assert admin.patch(PATH, {PER_PROJECT: MIB}).status_code == 200
    assert admin.get(PROJECT).json()["attachments"] == {"used": MIB + 500, "quota": MIB}
    assert len(list((tmp_path / "blobs").glob("*/*"))) == 2
    for r in kept:
        got = admin.get(f"{PROJECT}/attachments/{r.json()['id']}")
        assert got.status_code == 200, got.text
    over = put(admin, "c.bin", b"x", "application/octet-stream")
    assert over.json()["error"]["details"]["scope"] == "project"
    gone = admin.delete(f"{PROJECT}/attachments/{kept[0].json()['id']}")
    assert gone.status_code == 200
    assert put(admin, "c.bin", b"x" * 500, "application/octet-stream").status_code == 201


def test_unlimited_refuses_nothing_in_the_project_and_shows_no_quota(
    admin: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert admin.patch(PATH, {PER_PROJECT: "unlimited"}).status_code == 200
    project_used_of(monkeypatch, 2 * PIB)
    assert put(admin, "a.bin", b"x" * 100, "application/octet-stream").status_code == 201
    assert admin.get(PROJECT).json()["attachments"] == {"used": 2 * PIB + 100, "quota": None}
    assert admin.get(PATH).json()[PER_PROJECT] == {"value": "unlimited", "source": "admin"}
