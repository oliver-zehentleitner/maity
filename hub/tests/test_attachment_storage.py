"""docs/api.md §8.7 and §16.5: the limit on the attachments the whole instance stores."""

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
    who = flow.human(lambda **kw: stored(attachment_quota=2048, **kw), migrated)
    flow.project(who, "maity")
    assert who.patch(PATH, {"max_attachment_storage": GIB}).status_code == 200
    room_of(monkeypatch, 100)
    over = put(who, "a.bin", b"x" * 3000, "application/octet-stream")
    assert over.json()["error"]["details"]["scope"] == "project"


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
