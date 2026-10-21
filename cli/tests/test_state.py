from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from maity import state


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_state_dir_is_the_git_common_dir(clone: Path) -> None:
    assert state.resolve_state_dir() == (clone / ".git" / "maity").resolve()


def test_worktrees_share_the_state_dir(clone: Path, tmp_path: Path) -> None:
    from conftest import git

    other = tmp_path / "second-worktree"
    git(clone, "worktree", "add", "--quiet", str(other), "-b", "second")
    assert state.resolve_state_dir(other) == state.resolve_state_dir(clone)


def test_outside_a_clone_is_refused(tmp_path: Path, bin_dir: Path) -> None:
    lone = tmp_path / "lone"
    lone.mkdir()
    with pytest.raises(state.StateError, match="not inside a Git clone"):
        state.resolve_state_dir(lone)


def test_env_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(state.STATE_DIR_ENV, str(tmp_path / "custom"))
    assert state.resolve_state_dir() == (tmp_path / "custom").resolve()


def test_credential_is_written_private(tmp_path: Path) -> None:
    directory = tmp_path / "s"
    path = state.write_credential(directory, state.Secret("tok-123"))
    assert mode(directory) == 0o700
    assert mode(path) == 0o600
    assert state.read_credential(directory).reveal() == "tok-123"
    assert not list(directory.glob(".*.tmp"))


def test_credential_is_replaced_atomically(tmp_path: Path) -> None:
    state.write_credential(tmp_path, state.Secret("old"))
    state.write_credential(tmp_path, state.Secret("new"))
    assert state.read_credential(tmp_path).reveal() == "new"


def test_loose_credential_is_refused(tmp_path: Path) -> None:
    path = state.write_credential(tmp_path, state.Secret("tok-123"))
    os.chmod(path, 0o644)
    with pytest.raises(state.StateError, match="mode 0644") as info:
        state.read_credential(tmp_path)
    assert "tok-123" not in str(info.value)


@pytest.mark.parametrize("value", ["", "  ", "a\nb", "a b"])
def test_unusable_credential_values_are_refused(tmp_path: Path, value: str) -> None:
    with pytest.raises(state.StateError):
        state.write_credential(tmp_path, state.Secret(value))


def test_credential_is_stored_without_newline(tmp_path: Path) -> None:
    path = state.write_credential(tmp_path, state.Secret("mty1.a.b\n"))
    assert path.read_bytes() == b"mty1.a.b"


def test_missing_credential_names_the_fix(tmp_path: Path) -> None:
    with pytest.raises(state.StateError, match="maity join"):
        state.read_credential(tmp_path)


def test_secret_does_not_print() -> None:
    secret = state.Secret("tok-123")
    for shown in (str(secret), repr(secret), f"{secret}", f"{secret!r}", format(secret, "")):
        assert "tok-123" not in shown


def test_state_round_trip(tmp_path: Path) -> None:
    path = state.save_state(tmp_path, {"hub": "https://hub.example", "cursor": 7})
    assert mode(path) == 0o600
    assert state.load_state(tmp_path) == {"hub": "https://hub.example", "cursor": 7}


def test_missing_state_is_empty(tmp_path: Path) -> None:
    assert state.load_state(tmp_path) == {}


def test_broken_state_is_refused(tmp_path: Path) -> None:
    path = state.save_state(tmp_path, {})
    path.write_text("[1, 2]")
    with pytest.raises(state.StateError, match="JSON object"):
        state.load_state(tmp_path)


def test_a_loose_state_dir_is_refused_not_chmodded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = tmp_path / "named"
    named.mkdir()
    named.chmod(0o755)
    monkeypatch.setenv(state.STATE_DIR_ENV, str(named))
    directory = state.resolve_state_dir()
    with pytest.raises(state.StateError, match="chmod 700"):
        state.write_credential(directory, state.Secret("tok"))
    assert mode(named) == 0o755
    assert not (named / "credential").exists()


def test_reading_refuses_a_loose_state_dir(tmp_path: Path) -> None:
    directory = tmp_path / "s"
    state.write_credential(directory, state.Secret("tok"))
    directory.chmod(0o750)
    with pytest.raises(state.StateError, match="0750"):
        state.read_credential(directory)


def test_secret_cannot_be_pickled_or_copied() -> None:
    import copy
    import pickle

    secret = state.Secret("tok-123")
    with pytest.raises(TypeError):
        pickle.dumps(secret)
    with pytest.raises(TypeError):
        copy.copy(secret)
