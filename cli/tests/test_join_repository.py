"""A clone mismatch is advisory; an empty board is the admin's responsibility."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fakehub
import pytest
from conftest import git
from test_onboarding import packet

from maity import cli, gitfacts, onboarding

EXPECTED = "https://github.com/acme/widget"


@pytest.mark.parametrize(
    "remote",
    [
        EXPECTED,
        EXPECTED + ".git/",
        "git@github.com:acme/widget.git",
        "ssh://git@GitHub.com/acme/widget.git",
        EXPECTED + "/",
    ],
)
def test_transport_forms_match(clone: Path, remote: str) -> None:
    git(clone, "config", "--unset-all", f"url.{clone.parent / 'remote.git'}.insteadOf")
    git(clone, "remote", "set-url", "origin", remote)
    assert gitfacts.repository_mismatch(clone, EXPECTED) is None


def test_upstream_preferred_over_fork_origin(clone: Path) -> None:
    git(clone, "remote", "set-url", "origin", "git@github.com:fork/widget.git")
    assert gitfacts.repository_mismatch(clone, EXPECTED) == "origin"
    git(clone, "remote", "add", "upstream", "git@github.com:acme/widget.git")
    assert gitfacts.repository_mismatch(clone, EXPECTED) is None
    git(clone, "remote", "set-url", "upstream", "https://github.com/acme/other")
    assert gitfacts.repository_mismatch(clone, EXPECTED) == "upstream"


def test_no_remote_and_no_clone_do_not_block(clone: Path, tmp_path: Path) -> None:
    git(clone, "remote", "remove", "origin")
    assert gitfacts.repository_mismatch(clone, EXPECTED) is None
    assert gitfacts.repository_mismatch(tmp_path, EXPECTED) is None


def _packet(role: str = "member") -> dict[str, Any]:
    return packet(
        membership={"role": role, "briefing": None},
        project={"slug": "maity", "name": "Maity", "repository": {"url": EXPECTED}},
    )


def test_join_warns_but_keeps_credential(
    clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    git(clone, "remote", "set-url", "origin", "https://secret:password@example.com/wrong")
    fake.routes[("POST", "/api/v1/me/resume")] = lambda _: (200, _packet())
    assert cli.main(["join", f"{fake.url}/j/{fakehub.TOKEN}", "--code", fakehub.CODE]) == 0
    out = capsys.readouterr()
    assert f"Expected repository: {EXPECTED}" in out.out
    assert "WARNING" in out.err and "join is kept" in out.err
    assert "secret" not in out.err and "password" not in out.err
    assert cli.main(["resume"]) == 0
    out = capsys.readouterr()
    assert "WARNING" not in out.err
    assert f"Expected repository: {EXPECTED}" in out.out


@pytest.mark.parametrize(
    "items,role,hint",
    [([], "admin", True), ([{"id": "tsk-a"}], "admin", False), ([], "member", False)],
)
def test_empty_board_hint_only_for_admins(
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    items: list[dict[str, str]],
    role: str,
    hint: bool,
) -> None:
    fake.routes[("POST", "/api/v1/me/resume")] = lambda _: (200, _packet(role))
    fake.routes[("GET", "/api/v1/projects/maity/tasks")] = lambda _: (200, {"items": items})
    assert cli.main(["resume"]) == 0
    out = capsys.readouterr().out
    assert ("As an admin you run the board" in out) is hint
    if hint:
        assert "ask your human" in out
        request = fake.signed()[-1]
        assert request.path.endswith("/tasks") and request.query == "limit=1"


@pytest.mark.parametrize("body,status", [({}, 200), ({"error": {"code": "unavailable"}}, 503)])
def test_unknown_board_does_not_claim_empty(
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    body: dict[str, Any],
    status: int,
) -> None:
    fake.routes[("POST", "/api/v1/me/resume")] = lambda _: (200, _packet("admin"))
    fake.routes[("GET", "/api/v1/projects/maity/tasks")] = lambda _: (status, body)
    assert cli.main(["resume"]) == 0
    assert "board is empty" not in capsys.readouterr().out


def test_admin_pause_and_work_take_priority() -> None:
    p = _packet("admin")
    p["claims"] = [{"id": "tsk-a", "title": "work"}]
    assert "Continue tsk-a" in onboarding.render(p, board_empty=True)
    p["membership"]["paused"] = {"reason": "hold"}
    assert "Next: You are paused" in onboarding.render(p, board_empty=True)


@pytest.mark.parametrize("json_mode", [False, True])
def test_admin_briefing_and_json_need_no_board_read(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str], json_mode: bool
) -> None:
    p = _packet("admin")
    if not json_mode:
        p["membership"]["briefing"] = "Review the plan first."
    fake.routes[("POST", "/api/v1/me/resume")] = lambda _: (200, p)
    assert cli.main(["resume", *(["--json"] if json_mode else [])]) == 0
    assert not any(request.path.endswith("/tasks") for request in fake.signed())
    if json_mode:
        import json

        assert json.loads(capsys.readouterr().out) == p


@pytest.mark.parametrize("state", ["accepted", "archived"])
def test_closed_empty_board_asks_about_reopening(
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    state: str,
) -> None:
    p = _packet("admin")
    p["project"]["state"] = state
    fake.routes[("POST", "/api/v1/me/resume")] = lambda _: (200, p)
    fake.routes[("GET", "/api/v1/projects/maity/tasks")] = lambda _: (200, {"items": []})
    assert cli.main(["resume"]) == 0
    text = capsys.readouterr().out
    assert f"project is {state}" in text
    assert "Ask your human whether to reopen" in text
    assert "create cards" not in text
