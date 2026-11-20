"""`maity uuid`: a UUID v4 from the OS's randomness, with no hub, no state and no join."""

from __future__ import annotations

import re
import socket
import urllib.request
from pathlib import Path
from typing import Any, NoReturn

import pytest

from maity import cli, clonecheck, hub, state

V4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every way out to the network or to the clone's state fails the test: the HTTP layer
    the hub client uses, any socket connect, and the state directory lookup."""
    calls: list[str] = []

    def refuse(what: str) -> Any:
        def call(*args: object, **kwargs: object) -> NoReturn:
            calls.append(what)
            raise AssertionError(f"maity uuid called {what}")

        return call

    monkeypatch.setattr(hub, "opener", refuse("hub.opener"))
    monkeypatch.setattr(urllib.request, "urlopen", refuse("urlopen"))
    monkeypatch.setattr(socket.socket, "connect", refuse("socket.connect"))
    monkeypatch.setattr(state, "resolve_state_dir", refuse("state.resolve_state_dir"))
    monkeypatch.setattr(state, "load_state", refuse("state.load_state"))
    return calls


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, list[str], str]:
    code = cli.main(["uuid", *argv])
    out, err = capsys.readouterr()
    return code, out.splitlines(), err


def test_uuid_prints_one_lowercase_v4(
    capsys: pytest.CaptureFixture[str], offline: list[str]
) -> None:
    code = cli.main(["uuid"])
    out, err = capsys.readouterr()
    assert code == cli.EXIT_OK
    assert err == ""
    assert out.endswith("\n") and out.count("\n") == 1
    assert V4.fullmatch(out.rstrip("\n"))
    assert offline == []


def test_uuid_n_prints_that_many_distinct(
    capsys: pytest.CaptureFixture[str], offline: list[str]
) -> None:
    code, lines, _ = _run(capsys, "-n", "1000")
    assert code == cli.EXIT_OK
    assert len(lines) == 1000
    assert all(V4.fullmatch(line) for line in lines)
    assert len(set(lines)) == 1000
    assert offline == []


def test_uuid_is_unique_over_a_few_thousand(
    capsys: pytest.CaptureFixture[str], offline: list[str]
) -> None:
    seen: set[str] = set()
    for _ in range(5):
        code, lines, _ = _run(capsys, "-n", "1000")
        assert code == cli.EXIT_OK
        seen.update(lines)
    assert len(seen) == 5000


@pytest.mark.parametrize("n", ["0", "-1", "1001", "1000000", "x", "1.5", ""])
def test_uuid_refuses_a_count_out_of_range(
    capsys: pytest.CaptureFixture[str], offline: list[str], n: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["uuid", "-n", n])
    assert exc.value.code == cli.EXIT_USAGE
    out, err = capsys.readouterr()
    assert out == ""
    assert "-n" in err
    assert offline == []


def test_uuid_works_outside_a_joined_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plain directory, no git, no credential, no state file; nothing patched: the real
    state lookup would fail here, so the command must not reach it."""
    for name in (clonecheck.PLACEMENT_ENV, "GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE"):
        monkeypatch.delenv(name, raising=False)  # a placed session running these tests
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    with pytest.raises(state.StateError):
        state.load_state(state.resolve_state_dir())  # this directory is not joined
    code, lines, err = _run(capsys)
    assert code == cli.EXIT_OK
    assert err == ""
    assert len(lines) == 1 and V4.fullmatch(lines[0])
    assert sorted(p.name for p in plain.iterdir()) == []  # it wrote nothing either


def test_uuid_help_names_the_bound(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["uuid", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"1 to {cli.UUID_MAX}" in out
    assert "Keep the" in out
