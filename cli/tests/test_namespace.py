"""The project namespace on the CLI (§6.25): routes as /projects/{owner}/{slug}/…, the full
name kept in state and refreshed by every resume, a state from before the namespace completed
from GET /me, and `client_outdated` (426) said as an upgrade line."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli, hub, state

P = "/api/v1/projects/oliver/maity"
CARD = {"id": "tsk-4", "status": "open", "title": "x"}


def _state(**data: Any) -> None:
    directory = state.resolve_state_dir()
    state.save_state(directory, {"hub": data.pop("hub"), "member_id": "agt-b", **data})


def test_project_routes_carry_owner_and_slug(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", f"{P}/tasks/tsk-4")] = lambda s: (200, CARD)
    assert cli.main(["task", "show", "tsk-4", "--json"]) == cli.EXIT_OK
    assert fake.signed()[0].path == f"{P}/tasks/tsk-4"


def test_a_state_with_the_slug_alone_reads_the_full_name_from_me(
    joined: Path, fake: fakehub.FakeHub
) -> None:
    _state(hub=fake.url, project="maity")
    me = {"projects": [{"slug": "maity", "full_name": "oliver/maity", "name": "Maity"}]}
    fake.routes[("GET", "/api/v1/me")] = lambda s: (200, me)
    fake.routes[("GET", f"{P}/tasks/tsk-4")] = lambda s: (200, CARD)
    assert cli.main(["task", "show", "tsk-4", "--json"]) == cli.EXIT_OK
    assert [s.path for s in fake.signed()] == ["/api/v1/me", f"{P}/tasks/tsk-4"]
    assert state.load_state(state.resolve_state_dir())["full_name"] == "oliver/maity"
    assert cli.main(["task", "show", "tsk-4", "--json"]) == cli.EXIT_OK  # kept: no second /me
    assert [s.path for s in fake.signed()].count("/api/v1/me") == 1


def test_me_without_the_project_is_an_error_not_a_guess(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _state(hub=fake.url, project="maity")
    me = {"projects": [{"slug": "other", "full_name": "oliver/other"}]}
    fake.routes[("GET", "/api/v1/me")] = lambda s: (200, me)
    assert cli.main(["task", "show", "tsk-4"]) == cli.EXIT_ERROR
    assert "does not name this clone's project maity with an owner" in capsys.readouterr().err
    assert [s.path for s in fake.signed()] == ["/api/v1/me"]


def test_a_join_answer_with_the_full_name_needs_no_lookup(
    joined: Path, fake: fakehub.FakeHub
) -> None:
    _state(hub=fake.url, project="oliver/maity")
    fake.routes[("GET", f"{P}/tasks/tsk-4")] = lambda s: (200, CARD)
    assert cli.main(["task", "show", "tsk-4", "--json"]) == cli.EXIT_OK
    assert [s.path for s in fake.signed()] == [f"{P}/tasks/tsk-4"]
    saved = state.load_state(state.resolve_state_dir())
    assert (saved["full_name"], saved["project"]) == ("oliver/maity", "maity")


def test_resume_refreshes_the_full_name_after_a_rename(joined: Path, fake: fakehub.FakeHub) -> None:
    packet = {
        "session": {"id": "ses-1"}, "events": {"items": [], "cursor": 9},
        "me": {"member_id": "agt-b"},
        "project": {"slug": "maity-hub", "full_name": "oliver/maity-hub", "name": "Maity"},
    }  # fmt: skip
    fake.routes[("POST", "/api/v1/me/resume")] = lambda s: (200, packet)
    assert cli.main(["resume"]) == cli.EXIT_OK
    saved = state.load_state(state.resolve_state_dir())
    assert (saved["full_name"], saved["project"]) == ("oliver/maity-hub", "maity-hub")
    route = "/api/v1/projects/oliver/maity-hub/tasks/tsk-4"
    fake.routes[("GET", route)] = lambda s: (200, CARD)
    assert cli.main(["task", "show", "tsk-4", "--json"]) == cli.EXIT_OK
    assert fake.signed()[-1].path == route


def test_client_outdated_says_how_to_upgrade(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    details = {"minimum": "0.2.0", "install": "pipx upgrade maity"}
    refusal = {"error": {"code": "client_outdated", "message": "client_outdated",
                         "details": details}}  # fmt: skip
    fake.routes[("GET", f"{P}/tasks/tsk-4")] = lambda s: (426, refusal)
    assert cli.main(["task", "show", "tsk-4"]) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "is older than the hub needs (0.2.0)" in err
    assert "Upgrade with: pipx upgrade maity" in err
    assert "openapi" not in err  # not taken for a missing route


@pytest.mark.parametrize("bad", ["oliver/", "/maity", "Oliver/maity", "a/b/c", "oliver maity"])
def test_a_malformed_full_name_is_not_used(joined: Path, fake: fakehub.FakeHub, bad: str) -> None:
    _state(hub=fake.url, project="maity", full_name=bad)
    me = {"projects": [{"slug": "maity", "full_name": "oliver/maity"}]}
    fake.routes[("GET", "/api/v1/me")] = lambda s: (200, me)
    fake.routes[("GET", f"{P}/tasks/tsk-4")] = lambda s: (200, CARD)
    assert cli.main(["task", "show", "tsk-4", "--json"]) == cli.EXIT_OK
    assert fake.signed()[-1].path == f"{P}/tasks/tsk-4"


# --- a project with a new full name is followed (§6.25) ----------------------------------------

NEW = "/api/v1/projects/oliver-zehentleitner/maity"
MOVED_ME = {"projects": [{"slug": "maity", "full_name": "oliver-zehentleitner/maity"}]}


def test_a_moved_project_is_followed_once_and_kept(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", "/api/v1/me")] = lambda s: (200, MOVED_ME)
    fake.routes[("GET", f"{NEW}/tasks/tsk-4")] = lambda s: (200, CARD)
    assert cli.main(["task", "show", "tsk-4", "--json"]) == cli.EXIT_OK
    assert [s.path for s in fake.signed()] == [
        f"{P}/tasks/tsk-4",
        "/api/v1/me",
        f"{NEW}/tasks/tsk-4",
    ]
    assert "project is now oliver-zehentleitner/maity; continuing there" in capsys.readouterr().err
    saved = state.load_state(state.resolve_state_dir())
    assert (saved["full_name"], saved["project"]) == ("oliver-zehentleitner/maity", "maity")
    assert cli.main(["task", "show", "tsk-4", "--json"]) == cli.EXIT_OK  # kept: straight there
    assert [s.path for s in fake.signed()][3:] == [f"{NEW}/tasks/tsk-4"]


def test_a_write_is_repeated_at_the_new_name(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", "/api/v1/me")] = lambda s: (200, MOVED_ME)
    fake.routes[("POST", f"{NEW}/tasks/tsk-4/claim")] = lambda s: (200, CARD)
    assert cli.main(["claim", "tsk-4", "--json"]) == cli.EXIT_OK
    writes = [s for s in fake.signed() if s.method == "POST"]
    assert [s.path for s in writes] == [f"{P}/tasks/tsk-4/claim", f"{NEW}/tasks/tsk-4/claim"]


def test_a_missing_card_under_an_unchanged_name_stays_not_found(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    me = {"projects": [{"slug": "maity", "full_name": "oliver/maity"}]}
    fake.routes[("GET", "/api/v1/me")] = lambda s: (200, me)
    assert cli.main(["task", "show", "tsk-4"]) == cli.EXIT_ERROR
    assert "GET /projects/oliver/maity/tasks/tsk-4" in capsys.readouterr().err
    assert [s.path for s in fake.signed()] == [f"{P}/tasks/tsk-4", "/api/v1/me"]
    assert state.load_state(state.resolve_state_dir())["full_name"] == "oliver/maity"


def test_a_me_with_several_projects_is_not_a_guess(joined: Path, fake: fakehub.FakeHub) -> None:
    me = {"projects": [MOVED_ME["projects"][0], {"slug": "x", "full_name": "oliver/x"}]}
    fake.routes[("GET", "/api/v1/me")] = lambda s: (200, me)
    assert cli.main(["task", "show", "tsk-4"]) == cli.EXIT_ERROR
    assert state.load_state(state.resolve_state_dir())["full_name"] == "oliver/maity"


def test_a_not_found_outside_the_project_asks_nothing(joined: Path, fake: fakehub.FakeHub) -> None:
    assert cli.main(["api", "GET", "/me/nothing"]) == cli.EXIT_ERROR
    assert [s.path for s in fake.signed()] == ["/api/v1/me/nothing"]


def test_wait_follows_the_move_and_keeps_its_loop_there(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    pages = iter([{"items": [], "cursor": 0}, {"items": [{"seq": 5, "kind": "message"}]}])
    fake.routes[("GET", "/api/v1/me")] = lambda s: (200, MOVED_ME)
    gone = {"error": {"code": "not_found", "message": "not_found"}}
    fake.routes[("GET", f"{P}/events")] = lambda s: (404, gone)
    fake.routes[("GET", f"{NEW}/events")] = lambda s: (200, next(pages))
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_OK
    assert [s.path for s in fake.signed()] == [
        f"{P}/events", "/api/v1/me", f"{NEW}/events", f"{NEW}/events"
    ]  # fmt: skip
    assert capsys.readouterr().err.count("project is now") == 1


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


@pytest.mark.parametrize(("timeout", "repeated"), [(20.0, 9.0), (10.0, None)])
def test_the_lookup_and_the_repeat_share_the_call_timeout(
    monkeypatch: pytest.MonkeyPatch, timeout: float, repeated: float | None
) -> None:
    clock = _Clock()
    monkeypatch.setattr(cli, "time", clock)
    sent: list[tuple[str, float | None]] = []

    def call(self: Any, method: str, path: str, *args: Any) -> Any:
        sent.append((path, args[2]))
        clock.now += 4
        if path.startswith("/projects/oliver/"):
            raise hub.HubError("gone", code="not_found", status=404)
        return {"items": []}

    def moved(path: str, left: float | None) -> str:
        sent.append(("moved", left))
        clock.now += 7
        return "/projects/oliver-zehentleitner/maity/events"

    monkeypatch.setattr(hub.Client, "call", call)
    client = cli.ProjectClient("https://hub.test", None, moved=moved)  # type: ignore[arg-type]
    path = "/projects/oliver/maity/events"
    if repeated is None:
        with pytest.raises(hub.HubError):
            client.call("GET", path, timeout=timeout)
        assert sent == [(path, timeout), ("moved", timeout - 4)]
    else:
        assert client.call("GET", path, timeout=timeout) == {"items": []}
        assert sent[1:] == [("moved", 16.0), ("/projects/oliver-zehentleitner/maity/events", 9.0)]
