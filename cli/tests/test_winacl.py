"""The Windows rule runs everywhere; the real access lists only on Windows."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from maity import state, winacl
from maity.winacl import ACCESS_ALLOWED, ACCESS_DENIED, ADMINISTRATORS, INHERIT_ONLY, SYSTEM, Entry

ME = "S-1-5-21-1-2-3-1001"
USERS = "S-1-5-11"
EVERYONE = "S-1-1-0"
FULL = 0x1F01FF


def allow(sid: str, flags: int = 0, mask: int = FULL) -> Entry:
    return Entry(ACCESS_ALLOWED, flags, mask, sid)


def test_the_user_system_and_administrators_are_private() -> None:
    entries = [allow(ME), allow(SYSTEM), allow(ADMINISTRATORS)]
    assert winacl.judge(ME, ME, entries) == winacl.Reach(None, ())


def test_an_elevated_shell_owning_its_file_is_this_user() -> None:
    """A file made in an elevated shell is often owned by Administrators."""
    assert winacl.judge(ME, ADMINISTRATORS, [allow(ME)]).foreign_owner is None


def test_anyone_else_on_the_list_is_named_once() -> None:
    entries = [allow(ME), allow(USERS), allow(EVERYONE), allow(USERS, mask=1)]
    assert winacl.judge(ME, ME, entries).others == (USERS, EVERYONE)


def test_a_read_only_entry_counts() -> None:
    assert winacl.judge(ME, ME, [allow(USERS, mask=0x120089)]).others == (USERS,)


def test_another_owner_is_named() -> None:
    assert winacl.judge(ME, USERS, [allow(ME)]).foreign_owner == USERS


def test_what_grants_nothing_here_does_not_count() -> None:
    entries = [
        Entry(ACCESS_DENIED, 0, FULL, EVERYONE),
        allow(USERS, flags=INHERIT_ONLY),
        allow(EVERYONE, mask=0),
    ]
    assert winacl.judge(ME, ME, entries).others == ()


def test_no_list_at_all_is_everyone() -> None:
    assert winacl.judge(ME, ME, None).others == ("everyone (no access list)",)


def test_an_entry_of_a_type_not_read_is_refused() -> None:
    callback_allowed = 9
    assert winacl.judge(ME, ME, [Entry(callback_allowed, 0, FULL, "")]).others


def test_the_private_list_names_the_user_and_passes_on() -> None:
    assert winacl.private_sddl(ME) == f"D:PAI(A;OICI;FA;;;{ME})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"


def test_maity_imports_without_the_posix_modules(tmp_path: Path) -> None:
    """Every command died here on Windows: `maity.cli` pulled in `pwd` through the runner."""
    code = (
        "import sys\n"
        "for name in ('pwd', 'grp', 'fcntl', 'termios', 'resource'):\n"
        "    sys.modules[name] = None\n"
        "import maity.cli\n"
        "print('imported')\n"
    )
    src = str(Path(state.__file__).parent.parent)
    done = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": src},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.stdout.strip() == "imported", done.stderr


def test_the_runner_refuses_on_windows(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from maity import cli

    monkeypatch.setattr(sys, "platform", "win32")
    assert cli.main(["runner", "check"]) == cli.EXIT_REFUSED
    assert "WSL" in capsys.readouterr().err


windows = pytest.mark.skipif(sys.platform != "win32", reason="real access lists")
real: Any = winacl  # its calls exist on Windows only


def _grant_users(path: Path) -> None:
    subprocess.run(
        ["icacls", str(path), "/grant", f"*{USERS}:(R)"], check=True, capture_output=True
    )


@windows
def test_a_new_state_dir_is_private_and_so_is_what_it_holds(tmp_path: Path) -> None:
    directory = tmp_path / "s"
    path = state.write_credential(directory, state.Secret("tok"))
    assert real.reach(directory) == winacl.Reach(None, ())
    assert real.reach(path) == winacl.Reach(None, ())
    assert state.read_credential(directory).reveal() == "tok"


@windows
def test_a_private_dir_keeps_out_what_its_parent_passes_down(tmp_path: Path) -> None:
    subprocess.run(
        ["icacls", str(tmp_path), "/grant", f"*{USERS}:(OI)(CI)(R)"],
        check=True,
        capture_output=True,
    )
    directory = tmp_path / "s"
    state.write_credential(directory, state.Secret("tok"))
    assert real.reach(directory).others == ()


@windows
def test_someone_else_on_the_credential_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "s"
    path = state.write_credential(directory, state.Secret("tok"))
    _grant_users(path)
    assert USERS in real.reach(path).others
    with pytest.raises(state.StateError, match="icacls"):
        state.read_credential(directory)


@windows
def test_someone_else_on_a_named_dir_is_refused_not_changed(tmp_path: Path) -> None:
    named = tmp_path / "named"
    named.mkdir()
    state._make_private(named)
    _grant_users(named)
    with pytest.raises(state.StateError, match="icacls"):
        state.write_credential(named, state.Secret("tok"))
    assert USERS in real.reach(named).others
    assert not (named / "credential").exists()


@windows
def test_the_way_out_a_refusal_names_works(tmp_path: Path) -> None:
    directory = tmp_path / "s"
    state.write_credential(directory, state.Secret("tok"))
    _grant_users(directory)
    command = winacl.fix_command(directory, real.current_user())
    subprocess.run(command, shell=True, check=True, capture_output=True)  # noqa: S602
    assert real.reach(directory).others == ()


@windows
def test_a_join_tightens_an_empty_dir_and_says_so(tmp_path: Path) -> None:
    empty = tmp_path / "e"
    empty.mkdir()
    state._make_private(empty)
    _grant_users(empty)
    assert "limited" in (state.prepare_for_join(empty) or "")
    assert real.reach(empty).others == ()


@windows
def test_a_join_leaves_a_dir_with_something_in_it(tmp_path: Path) -> None:
    full = tmp_path / "f"
    full.mkdir()
    (full / "x").write_text("x")
    state._make_private(full)
    _grant_users(full)
    with pytest.raises(state.StateError, match="accessible"):
        state.prepare_for_join(full)
    assert USERS in real.reach(full).others
