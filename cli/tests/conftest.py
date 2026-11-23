from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import fakehub
import pytest

from maity import winacl
from maity.runner import capabilities as _capabilities

GIT = shutil.which("git")
REAL_SOCKET_PROBE = _capabilities.claude_socket_probe
REAL_AGY_SANDBOX = _capabilities.agy_sandbox
GITHUB_URL = "https://github.com/acme/widget"

# The runner does not run on Windows (context/credentials.md).
collect_ignore = (
    [
        "test_adapters.py",
        "test_agent_user.py",
        "test_antigravity.py",
        "test_availability.py",
        "test_claude_sandbox_probe.py",
        "test_confinement.py",
        "test_operate.py",
        "test_runner.py",
        "test_runner_install.py",
        "test_runner_installers.py",
        "test_runner_keeper.py",
        "test_runner_tools.py",
        "test_serve.py",
        "test_ssh.py",
        "test_supervisor.py",
        "test_supervisor_notes.py",
        "test_supervisor_pickup.py",
        "test_supervisor_watch.py",
        "test_watch.py",
    ]
    if sys.platform == "win32"
    else []
)
posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes; see test_winacl.py")


def git(cwd: Path, *args: str) -> str:
    assert GIT is not None
    proc = subprocess.run(
        [GIT, *args], cwd=cwd, capture_output=True, text=True, check=True, env=_git_env()
    )
    return proc.stdout.strip()


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME="test",
        GIT_AUTHOR_EMAIL="test@example.invalid",
        GIT_COMMITTER_NAME="test",
        GIT_COMMITTER_EMAIL="test@example.invalid",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
    )
    return env


def assert_private(path: Path) -> None:
    """Only this user can reach it: its mode on POSIX, its access list on Windows."""
    if sys.platform == "win32":
        assert winacl.reach(path) == winacl.Reach(None, ())
    else:
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)


def fake_maity(bin_dir: Path) -> None:
    """A `maity` that `shutil.which` finds; nothing runs it."""
    path = bin_dir / ("maity.exe" if sys.platform == "win32" else "maity")
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)


# OpenCode 2.3.0's flags, as ops read them on the host (note nte-22jpstv7c7x5 on
# tsk-kf2kp09d6qew, and their live check nte-mmnz3mk1247c on tsk-daa6e0gfncg0): the TUI (no
# subcommand) takes a directory and these, no `--model`; `opencode run [flags] [<message...>]`
# takes these, no `--dir`.
OPENCODE_23_TUI = ("--standalone", "--server", "--auto", "-c, --continue", "-s, --session",
                   "--prompt")  # fmt: skip
OPENCODE_23_RUN = ("-m, --model", "-c, --continue", "--session")


def opencode_23_flags(listed: tuple[str, ...]) -> set[str]:
    """The flags of OPENCODE_23_TUI or OPENCODE_23_RUN, one word each."""
    return {flag for entry in listed for flag in entry.split(", ")}


def fake_opencode(
    path: Path,
    version: str = "2.3.0",
    tui: tuple[str, ...] = OPENCODE_23_TUI,
    run: tuple[str, ...] = OPENCODE_23_RUN,
) -> None:
    """An opencode that prints `version`, and for `--help` and `run --help` the flags given;
    anything else fails, as 2.3's root command does on a flag it does not know."""
    path.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f"  --version) echo '{version}' ;;\n"
        "  --help) echo 'opencode [project]'\n"
        + "".join(f"    echo '  {flag}'\n" for flag in tui)
        + "    ;;\n"
        "  'run --help') echo 'opencode run [message..]'\n"
        + "".join(f"    echo '  {flag}'\n" for flag in run)
        + "    ;;\n"
        "  *) echo 'ERROR  Unrecognized flag' >&2; exit 1 ;;\n"
        "esac\n"
    )
    path.chmod(0o755)


def isolate_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every GIT_* of the shell, and the developer's global and system git config.

    A runner session's GIT_COMMON_DIR sends every test's git to the session's own clone, and
    its GIT_CONFIG_COUNT/KEY_n/VALUE_n add configuration there. Any other GIT_* does the same:
    GIT_DIR, GIT_WORK_TREE and GIT_INDEX_FILE redirect it, and GIT_CONFIG_PARAMETERS, which
    Claude Code's sandbox sets for its proxy, configures it. A test that needs one sets it
    itself (`placed` sets GIT_COMMON_DIR)."""
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test sees the developer's git config, the shell's git variables, a MAITY_STATE_DIR
    or a placement from the shell, and none writes into the developer's home: an interactive
    Claude Code launch records the clone's folder trust in ~/.claude.json (runner/trust.py)."""
    home = tmp_path / "isolated-home"  # not `home`: tests make their own
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("MAITY_STATE_DIR", raising=False)
    # Nor a placement of the shell's: a test that wants one sets it (`placed`).
    monkeypatch.delenv("MAITY_PLACEMENT", raising=False)
    monkeypatch.delenv("MAITY_GIT_PRIVATE", raising=False)
    isolate_git(monkeypatch)
    # Nor the host's managed Claude Code settings (runner/capabilities.claude_hooks_off).
    from maity.runner import capabilities

    managed = tmp_path / "managed-claude" / "managed-settings.json"
    monkeypatch.setattr(capabilities, "CLAUDE_MANAGED", {"linux": managed, "darwin": managed})
    # Nor a real headless Claude Code run from `check` (a prompt on a login); its own tests
    # take the function from `REAL_SOCKET_PROBE`.
    monkeypatch.setattr(
        capabilities, "claude_socket_probe", lambda *args: capabilities.SocketProbe("ok")
    )
    # Nor the host's own unshare and AppArmor profiles from an agy start or check (the review
    # of #2119); the probe's own tests take the function from `REAL_AGY_SANDBOX`.
    monkeypatch.setattr(capabilities, "agy_sandbox", lambda *args: capabilities.AGY_STARTS)


@pytest.fixture
def bin_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A PATH holding git and nothing else; tests add a fake gh to it when they need one."""
    assert GIT is not None, "the tests need git"
    path = tmp_path / "bin"
    path.mkdir()
    if sys.platform == "win32":  # git.exe finds its parts beside itself, and links need rights
        monkeypatch.setenv("PATH", os.pathsep.join([str(path), str(Path(GIT).parent)]))
        return path
    (path / "git").symlink_to(GIT)
    monkeypatch.setenv("PATH", str(path))
    return path


def fake_gh(bin_dir: Path, stdout: str, exit_code: int = 0, stderr: str = "") -> None:
    """A gh that answers every call with `stdout`; shell builtins only, PATH holds just git."""
    if sys.platform == "win32":
        pytest.skip("Windows starts only an .exe by a bare name, and this gh is a shell script")
    assert "'" not in stdout + stderr
    script = bin_dir / "gh"
    script.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' '{stdout}'\n"
        f"printf '%s\\n' '{stderr}' >&2\n"
        f"exit {exit_code}\n"
    )
    script.chmod(0o755)


@pytest.fixture
def clone(tmp_path: Path, bin_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A clone of a bare remote with one pushed commit on branch `work`, cwd set to it."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(remote))
    git(tmp_path, "clone", "--quiet", str(remote), str(work))
    # The remote reads as GitHub (what gh is asked about); git itself is sent to the bare repo.
    git(work, "remote", "set-url", "origin", GITHUB_URL)
    git(work, "config", f"url.{remote}.insteadOf", GITHUB_URL)
    git(work, "switch", "--quiet", "-c", "work")
    (work / "a.txt").write_text("one\n")
    git(work, "add", "a.txt")
    git(work, "commit", "--quiet", "-m", "one")
    git(work, "push", "--quiet", "-u", "origin", "work")
    monkeypatch.chdir(work)
    yield work


@pytest.fixture
def fake() -> Iterator[fakehub.FakeHub]:
    yield from fakehub.serve()


@pytest.fixture
def joined(clone: Path, fake: fakehub.FakeHub) -> Path:
    """`clone`, joined to the fake hub as agt-b in project maity."""
    from maity import state

    directory = state.resolve_state_dir()
    state.write_credential(directory, state.Secret(fakehub.CREDENTIAL))
    state.save_state(
        directory,
        {
            "hub": fake.url,
            "project": "oliver/maity",
            "project_id": "maity",
            "full_name": "oliver/maity",
            "member_id": "agt-b",
        },
    )
    return directory


@pytest.fixture
def placed(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """The joined clone (the working directory) under a placement, with the variables the
    runner sets for a session. A test file with a `placed` of its own uses that one."""
    from maity import clonecheck

    clone = Path.cwd()
    monkeypatch.setenv(clonecheck.PLACEMENT_ENV, "plc-0003")
    monkeypatch.setenv("GIT_COMMON_DIR", str(clone / ".git"))
    monkeypatch.setenv(clonecheck.GIT_INODE_ENV, str(os.lstat(clone / ".git").st_ino))
    private = tmp_path / "agent" / "git"
    private.mkdir(parents=True)
    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, str(private))
    return clone


@pytest.fixture(autouse=True)
def _shared_tmp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test makes a per-user scratch parent, an agy scratch or a placement's TMPDIR leaf in
    the host's real /tmp (workspace.TMP_SCRATCH_ROOT); a test that needs a short root sets its
    own."""
    from maity.runner import workspace

    root = tmp_path / "shared-tmp-root"
    root.mkdir()
    monkeypatch.setattr(workspace, "TMP_SCRATCH_ROOT", root)


@pytest.fixture(autouse=True)
def _home_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The environment secret of the home (§5.3) goes to the test's own directory, never to
    the real ~/.local/state/maity."""
    from maity import environment

    monkeypatch.setattr(environment, "HOME_SECRET", tmp_path / "home-state" / "env-secret")
