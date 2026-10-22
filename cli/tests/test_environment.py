"""The session's declared environment (§5.2, §5.3): two ids, never a path."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli, environment, state

ID = re.compile(r"^[hw]-[0-9a-f]{12}$")


def test_ids_are_hashed_per_hub_and_stable(tmp_path: Path) -> None:
    first = environment.ids("https://maity.team", tmp_path / "st")
    assert first is not None
    assert ID.match(first["home"]) and first["home"].startswith("h-")
    assert ID.match(first["workspace"]) and first["workspace"].startswith("w-")
    assert environment.ids("https://maity.team", tmp_path / "st") == first
    other = environment.ids("https://hub.example", tmp_path / "st")
    assert other is not None and other["home"] != first["home"]  # unrelated on another hub
    assert environment.ids("https://maity.team", tmp_path / "other")["workspace"] != (  # type: ignore[index]
        first["workspace"]
    )


def test_the_secrets_are_private(tmp_path: Path) -> None:
    environment.ids("https://maity.team", tmp_path / "st")
    for path in (environment.HOME_SECRET, tmp_path / "st" / environment.SECRET_FILE):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_loose_secret_is_not_used(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    environment.ids("https://maity.team", tmp_path / "st")
    (tmp_path / "st" / environment.SECRET_FILE).chmod(0o644)
    assert environment.ids("https://maity.team", tmp_path / "st") is None
    assert "not declaring this session's environment" in capsys.readouterr().err


def test_two_processes_racing_keep_one_secret(tmp_path: Path) -> None:
    path = tmp_path / "s" / environment.SECRET_FILE
    first = state.secret_once(path)
    assert state.secret_once(path) == first and len(first) == 64


def test_resume_declares_the_environment_and_prints_no_id(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["resume"]) == cli.EXIT_OK
    body = fake.signed()[-1].json()
    declared = body["environment"]
    assert set(declared) == {"home", "workspace"} and all(ID.match(v) for v in declared.values())
    out = capsys.readouterr()
    assert declared["home"] not in out.out + out.err
    assert str(joined) not in str(declared)  # never a path


def test_an_older_hub_is_resumed_without_the_field(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    bodies: list[dict[str, Any]] = []

    def resume(seen: fakehub.Seen) -> tuple[Any, ...]:
        bodies.append(seen.json())
        if "environment" in seen.json():
            fields = {"environment": "extra_forbidden"}
            return 400, {"error": {"code": "invalid", "message": "invalid",
                                   "details": {"fields": fields}}}  # fmt: skip
        return 200, {"session": {"id": "ses-x"}, "me": {"member_id": "agt-b"}}

    fake.routes[("POST", "/api/v1/me/resume")] = resume
    assert cli.main(["resume", "--json"]) == cli.EXIT_OK
    assert "environment" in bodies[0] and "environment" not in bodies[1]
    assert "does not take the session's environment yet" in capsys.readouterr().err


def test_another_invalid_is_not_retried(joined: Path, fake: fakehub.FakeHub) -> None:
    calls = []

    def resume(seen: fakehub.Seen) -> tuple[Any, ...]:
        calls.append(seen)
        return 400, {"error": {"code": "invalid", "message": "invalid",
                               "details": {"fields": {"harness": "too_long"}}}}  # fmt: skip

    fake.routes[("POST", "/api/v1/me/resume")] = resume
    assert cli.main(["resume"]) != cli.EXIT_OK
    assert len(calls) == 1


def test_secret_files_are_never_a_path_the_hub_sees() -> None:
    assert os.sep not in environment.derive("h", "x" * 64, "https://maity.team")
