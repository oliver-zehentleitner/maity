"""Claude Code's folder trust for a clone (runner/trust.py), checked against Claude Code 2.1.319:
`projects[<real path>].hasTrustDialogAccepted` in the global configuration file, written under
the `<file>.lock` directory its own saves take."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from maity.runner import trust

KEY = trust.KEY


def _config(home: Path, data: Any, name: str = ".claude.json") -> Path:
    path = home / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)
    return path


def _clone(tmp_path: Path) -> Path:
    clone = tmp_path / "ws" / "maity" / "agent-3"
    clone.mkdir(parents=True)
    return clone


def test_record_adds_the_clones_entry_and_changes_nothing_else(tmp_path: Path) -> None:
    home, clone = tmp_path / "h", _clone(tmp_path)
    other = {"hasTrustDialogAccepted": False, "allowedTools": ["Bash(ls)"]}
    before = {
        "numStartups": 51, "oauthAccount": {"emailAddress": "a@example.org"}, "ünicode": "ä",
        "projects": {"/elsewhere": other, str(clone): {"lastGracefulShutdown": True}},
    }  # fmt: skip
    path = _config(home, before)
    assert trust.record(home, clone) is True
    after = json.loads(path.read_text())
    assert after == {**before, "projects": {
        "/elsewhere": other,
        str(clone): {"lastGracefulShutdown": True, "hasTrustDialogAccepted": True},
    }}  # fmt: skip
    assert path.stat().st_mode & 0o777 == 0o600
    assert '"ä"' in path.read_text()  # kept as Claude Code writes it, not escaped
    assert not Path(f"{path}.lock").exists()
    assert sorted(p.name for p in home.iterdir()) == [".claude.json"]  # no temporary file left


def test_record_keys_the_clone_by_its_real_path(tmp_path: Path) -> None:
    """Claude Code looks up its working directory, which the kernel gives resolved."""
    home, clone = tmp_path / "h", _clone(tmp_path)
    (tmp_path / "link").symlink_to(clone.parent)
    path = _config(home, {})
    trust.record(home, tmp_path / "link" / clone.name)
    assert json.loads(path.read_text())["projects"] == {
        str(clone.resolve()): {"hasTrustDialogAccepted": True}
    }


def test_record_writes_nothing_when_the_clone_is_trusted_already(tmp_path: Path) -> None:
    home, clone = tmp_path / "h", _clone(tmp_path)
    path = _config(home, {"projects": {str(clone): {"hasTrustDialogAccepted": True}}})
    os.utime(path, (1, 1))
    assert trust.record(home, clone) is False
    assert path.stat().st_mtime == 1


def test_record_creates_the_file_when_claude_code_never_ran(tmp_path: Path) -> None:
    home, clone = tmp_path / "h", _clone(tmp_path)
    home.mkdir()
    trust.record(home, clone)
    path = home / ".claude.json"
    assert json.loads(path.read_text()) == {"projects": {str(clone): {KEY: True}}}
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("legacy", "current", "chosen"),
    [
        ('{"a": 1}', None, ".claude/.config.json"),  # the legacy file alone
        ('{"a": 1}', "{}", ".claude/.config.json"),  # a non-empty legacy file wins
        ("", None, ".claude/.config.json"),  # empty, but the only one
        ("", "{}", ".claude.json"),  # empty next to the current file
        (None, "{}", ".claude.json"),
        (None, None, ".claude.json"),
    ],
)
def test_config_file_is_the_one_claude_code_reads(
    tmp_path: Path, legacy: str | None, current: str | None, chosen: str
) -> None:
    home = tmp_path / "h"
    (home / ".claude").mkdir(parents=True)
    if legacy is not None:
        (home / ".claude" / ".config.json").write_text(legacy)
    if current is not None:
        (home / ".claude.json").write_text(current)
    assert trust.config_file(home) == home / chosen


def test_an_empty_read_only_legacy_file_is_not_the_one_claude_code_reads(tmp_path: Path) -> None:
    """2.1.319 takes the legacy file when `size > 0 || (mode & 0o222) != 0`: an empty file
    without a write bit is passed over, and Claude Code creates `~/.claude.json` (#1560 R2)."""
    home = tmp_path / "h"
    (home / ".claude").mkdir(parents=True)
    legacy = home / ".claude" / ".config.json"
    legacy.write_text("")
    legacy.chmod(0o444)
    assert trust.config_file(home) == home / ".claude.json"
    trust.record(home, _clone(tmp_path))
    assert legacy.read_text() == "" and (home / ".claude.json").exists()


def test_config_file_ignores_claude_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner's sessions start with a fixed environment, never CLAUDE_CONFIG_DIR."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "elsewhere"))
    assert trust.config_file(tmp_path / "h") == tmp_path / "h" / ".claude.json"


@pytest.mark.parametrize(
    "text", ["not json", "[]", '{"projects": []}', '{"projects": {"%s": "yes"}}']
)
def test_a_file_that_is_no_claude_code_configuration_is_left_as_it_is(
    tmp_path: Path, text: str
) -> None:
    home, clone = tmp_path / "h", _clone(tmp_path)
    home.mkdir()
    path = home / ".claude.json"
    path.write_text(text.replace("%s", str(clone)))
    with pytest.raises(trust.TrustError):
        trust.record(home, clone)
    assert path.read_text() == text.replace("%s", str(clone))
    assert not Path(f"{path}.lock").exists()


def test_a_linked_file_stays_a_link(tmp_path: Path) -> None:
    home, clone = tmp_path / "h", _clone(tmp_path)
    real = _config(tmp_path / "dotfiles", {}, "claude.json")
    home.mkdir()
    (home / ".claude.json").symlink_to(real)
    trust.record(home, clone)
    assert (home / ".claude.json").is_symlink()
    assert json.loads(real.read_text())["projects"] == {str(clone): {KEY: True}}


def test_record_waits_for_claude_codes_lock(tmp_path: Path) -> None:
    """A running Claude Code saves holding `<file>.lock`; the entry is written after it is
    given up, onto what that save left."""
    home, clone = tmp_path / "h", _clone(tmp_path)
    path = _config(home, {"projects": {}})
    lock = Path(f"{path}.lock")
    lock.mkdir()
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 3:  # the session's save lands, then it lets go
            _config(home, {"projects": {"/other": {"x": 1}}})
            lock.rmdir()

    assert trust.record(home, clone, sleep=sleep) is True
    assert len(slept) == 3
    assert json.loads(path.read_text())["projects"] == {
        "/other": {"x": 1}, str(clone): {KEY: True}
    }  # fmt: skip


def test_a_lock_held_too_long_fails_and_writes_nothing(tmp_path: Path) -> None:
    home, clone = tmp_path / "h", _clone(tmp_path)
    path = _config(home, {})
    Path(f"{path}.lock").mkdir()
    clock = iter(range(0, 100))
    with pytest.raises(trust.TrustError, match="held by another process"):
        trust.record(home, clone, now=lambda: float(next(clock)), sleep=lambda _: None)
    assert json.loads(path.read_text()) == {}
    assert Path(f"{path}.lock").is_dir()  # someone else's: never removed


def test_a_stale_lock_is_taken_over(tmp_path: Path) -> None:
    """proper-lockfile's rule, which Claude Code's lock keeps: a holder refreshes the lock's
    mtime, so one older than 10 s is left from a process that is gone."""
    home, clone = tmp_path / "h", _clone(tmp_path)
    path = _config(home, {})
    lock = Path(f"{path}.lock")
    lock.mkdir()
    old = time.time() - trust.STALE_SECONDS - 5
    os.utime(lock, (old, old))
    assert trust.record(home, clone, sleep=lambda _: pytest.fail("waited")) is True
    assert not lock.exists()


def test_main_takes_two_absolute_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home, clone = tmp_path / "h", _clone(tmp_path)
    _config(home, {})
    assert trust.main(["h", str(clone)]) == 2
    assert trust.main([str(home)]) == 2
    assert trust.main([str(home), str(clone)]) == 0
    (home / ".claude.json").write_text("not json")
    assert trust.main([str(home), str(clone)]) == 1
    assert "not JSON" in capsys.readouterr().err


def _context(tmp_path: Path, as_user: Any, agent_path: str = "") -> Any:
    from test_adapters import context

    return dataclasses.replace(context(tmp_path), as_user=as_user, agent_path=agent_path)


class _Remote:
    """An ssh host's side: records the command, answers as told."""

    direct, here = False, False

    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.calls: list[tuple[list[str], Any]] = []
        self.returncode, self.stderr = returncode, stderr

    def home(self) -> Path:
        return Path("/home/agents")

    def runner_module(self, name: str) -> list[str]:
        return ["maity", "runner", name]

    def run(self, argv: list[str], env: Any = None) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, env))
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


def test_an_ssh_host_records_it_with_its_own_maity(tmp_path: Path) -> None:
    from maity.runner import adapters

    remote = _Remote()
    ctx = _context(tmp_path, remote, agent_path="/opt/maity/bin:/usr/bin")
    adapters.trust_clone(ctx)
    assert remote.calls == [(
        ["maity", "runner", "trust", "/home/agents", str(ctx.clone)],
        {"PATH": "/opt/maity/bin:/usr/bin"},
    )]  # fmt: skip


def test_a_host_that_cannot_record_it_fails_the_start(tmp_path: Path) -> None:
    """A host's `maity` without `runner trust` (older than this) or a file it refuses: the
    start fails with the cause, instead of a session that waits at the question."""
    from maity.runner import adapters

    ctx = _context(tmp_path, _Remote(2, "maity: error: argument <action>: invalid choice: 'trust'"))
    with pytest.raises(trust.TrustError, match="invalid choice: 'trust'"):
        adapters.trust_clone(ctx)
    with pytest.raises(trust.TrustError, match="exit 1"):
        adapters.trust_clone(_context(tmp_path / "b", _Remote(1)))


def test_maity_runner_trust_runs_the_module(tmp_path: Path) -> None:
    """What an ssh host runs: `maity runner trust HOME CLONE`."""
    home, clone = tmp_path / "h", _clone(tmp_path)
    home.mkdir()
    done = subprocess.run(
        [sys.executable, "-m", "maity", "runner", "trust", str(home), str(clone)],
        capture_output=True, text=True, check=False, env={**os.environ, "PYTHONPATH": "src"},
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert json.loads((home / ".claude.json").read_text()) == {
        "projects": {str(clone): {KEY: True}}
    }


@pytest.mark.parametrize("kind", ["file", "full directory"])
def test_a_stale_lock_that_cannot_be_removed_fails_at_once(tmp_path: Path, kind: str) -> None:
    """A regular file at the lock path, or a lock directory with something in it, is no lock
    a holder renews and none `rmdir` removes: the start fails with the cause instead of
    waiting forever (#1560 R1)."""
    home, clone = tmp_path / "h", _clone(tmp_path)
    path = _config(home, {})
    lock = Path(f"{path}.lock")
    if kind == "file":
        lock.write_text("")
    else:
        lock.mkdir()
        (lock / "left").write_text("")
    old = time.time() - trust.STALE_SECONDS - 5
    os.utime(lock, (old, old))
    with pytest.raises(trust.TrustError, match="stale and cannot be removed"):
        trust.record(home, clone, sleep=lambda _: pytest.fail("waited"))
    assert json.loads(path.read_text()) == {}


def test_a_lock_path_held_by_a_fresh_file_fails_at_the_deadline(tmp_path: Path) -> None:
    home, clone = tmp_path / "h", _clone(tmp_path)
    path = _config(home, {})
    Path(f"{path}.lock").write_text("")
    clock = iter(range(0, 100))
    with pytest.raises(trust.TrustError, match="held by another process"):
        trust.record(home, clone, now=lambda: float(next(clock)), sleep=lambda _: None)


def _slow_fsync(monkeypatch: pytest.MonkeyPatch, seconds: float, then: Any = None) -> None:
    real = os.fsync
    done = [False]

    def slow(fd: int) -> None:
        real(fd)
        if not done[0]:
            done[0] = True
            time.sleep(seconds)
            if then is not None:
                then()

    monkeypatch.setattr(os, "fsync", slow)


def test_a_slow_holder_keeps_its_lock_and_the_other_writer_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The holder renews the lock's mtime while it writes, so another writer does not take
    it over as stale and waits instead; both entries are in the file (#1560 R1: without the
    renewal the second writer took the lock and the first replaced its entry)."""
    import threading

    # raising=False: the counter-check runs this against a module without renewal
    monkeypatch.setattr(trust, "STALE_SECONDS", 0.3)
    monkeypatch.setattr(trust, "RENEW_SECONDS", 0.05, raising=False)
    home = tmp_path / "h"
    first, second = _clone(tmp_path), tmp_path / "other"
    second.mkdir()
    path = _config(home, {"projects": {}})
    _slow_fsync(monkeypatch, 1.0)  # the first writer's fsync, past three stale periods
    results: dict[str, Any] = {}
    writer = threading.Thread(target=lambda: results.update(a=trust.record(home, first)))
    writer.start()
    deadline = time.monotonic() + 5
    while not Path(f"{path}.lock").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert trust.record(home, second) is True
    writer.join(5)
    assert results == {"a": True}
    assert set(json.loads(path.read_text())["projects"]) == {
        os.path.realpath(first),
        os.path.realpath(second),
    }


def test_a_holder_whose_lock_was_taken_over_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another process took the lock while this one wrote (removed it and made its own): the
    replace does not happen, the call fails, and the other process's lock stays."""
    home, clone = tmp_path / "h", _clone(tmp_path)
    path = _config(home, {"projects": {"/b": {KEY: True}}})
    lock = Path(f"{path}.lock")

    def taken_over() -> None:
        lock.rmdir()
        lock.mkdir()
        os.utime(lock, (1, 1))

    _slow_fsync(monkeypatch, 0, taken_over)
    with pytest.raises(trust.TrustError, match="lost .* to another process"):
        trust.record(home, clone)
    assert json.loads(path.read_text()) == {"projects": {"/b": {KEY: True}}}
    assert lock.is_dir()  # the other process's: never removed by this one
    assert [p.name for p in home.iterdir() if p.name.startswith(".claude.json.")] == [
        ".claude.json.lock"
    ]  # no temporary file left


@pytest.mark.parametrize("step", ["fsync", "utime"])
def test_a_failing_write_is_a_trust_error_with_its_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """Every failure is a TrustError naming the cause (#1560 R2: a PermissionError from the
    fsync, or from the first renewal of the lock, came out as itself); the file and the lock
    are left as they were."""
    home, clone = tmp_path / "h", _clone(tmp_path)
    path = _config(home, {"projects": {}})

    def refused(*args: Any, **kwargs: Any) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, step, refused)
    with pytest.raises(trust.TrustError, match="Permission denied"):
        trust.record(home, clone)
    assert json.loads(path.read_text()) == {"projects": {}}
    assert sorted(p.name for p in home.iterdir()) == [".claude.json"]  # no lock, no temp


def test_a_file_that_is_not_utf8_is_a_trust_error_and_left_as_it_is(tmp_path: Path) -> None:
    """A decode error is no OSError: it came out as a UnicodeDecodeError (#1560 R3)."""
    home, clone = tmp_path / "h", _clone(tmp_path)
    home.mkdir()
    path = home / ".claude.json"
    path.write_bytes(b"\xff")
    with pytest.raises(trust.TrustError, match="not UTF-8"):
        trust.record(home, clone)
    assert path.read_bytes() == b"\xff"
    assert sorted(p.name for p in home.iterdir()) == [".claude.json"]
