"""maity's own git in a session the runner started: only in the runner's clone, and only while
that clone is a plain one."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import git

from maity import clonecheck, gitfacts

# Where the runner records its git (adapters.launch), spelled out: the tests say where.
RECORDED_GIT = Path(".git", "maity", "git")


@pytest.fixture
def placed(clone: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`clone` as the runner leaves it: a plain clone, `MAITY_PLACEMENT` and `GIT_COMMON_DIR`
    set the way the runner sets them for a session."""
    remote = clone.parent / "remote.git"
    git(clone, "config", "--remove-section", f"url.{remote}")
    git(clone, "remote", "set-url", "origin", str(remote))
    (clone / ".git" / "maity").mkdir(exist_ok=True)  # the runner makes it (adapters)
    (clone / RECORDED_GIT).write_text(f"{shutil.which('git')}\n")  # and records git
    monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    monkeypatch.setenv("GIT_COMMON_DIR", str(clone / ".git"))
    monkeypatch.setenv(clonecheck.GIT_INODE_ENV, str(os.lstat(clone / ".git").st_ino))
    private = clone.parent / "agent-dir" / "git"  # the runner's, outside the clone
    private.mkdir(parents=True)
    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, str(private))
    return clone


def test_a_plain_clone_reads_as_before(placed: Path) -> None:
    facts = gitfacts.collect(placed)
    assert facts.remote_head == facts.head
    assert gitfacts.mismatches(facts) == []


def test_without_a_placement_nothing_is_checked(clone: Path) -> None:
    git(clone, "config", "core.pager", "cat")
    with clonecheck.placement_git(clone) as pinned:
        assert pinned is None
    assert gitfacts.collect(clone).branch == "work"


def test_a_key_a_plain_clone_has_not_is_refused(placed: Path) -> None:
    git(placed, "config", "core.pager", "cat")
    with pytest.raises(gitfacts.FactsError, match=r"not a plain clone: .*core\.pager"):
        gitfacts.collect(placed)


def _marking(marker: Path) -> str:
    """A command that creates `marker`, on any platform."""
    return f"\"{sys.executable}\" -c \"open(r'{marker}', 'w')\""


def _quoted(value: str) -> str:
    """`value` as a configuration file holds it: git drops unescaped double quotes."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@pytest.mark.parametrize(
    "key",
    ["remote.origin.uploadpack", "core.sshCommand", "core.gitProxy", "credential.helper"],
)
def test_a_key_naming_a_program_for_a_remote_is_refused_before_git_runs(
    placed: Path, key: str
) -> None:
    marker = placed.parent / "ran"
    git(placed, "config", key, _marking(marker))
    with pytest.raises(
        gitfacts.FactsError, match=rf"(?i)not a plain clone: .*{re.escape(key.split('.')[-1])}"
    ):
        gitfacts.collect(placed)
    assert not marker.exists()


def test_a_header_sharing_a_line_with_a_key_is_read_as_git_reads_it(placed: Path) -> None:
    marker = placed.parent / "ran"
    with (placed / ".git" / "config").open("a") as config:
        config.write(f'[remote]\n[x "a.url = "] [core] sshCommand = {_quoted(_marking(marker))}\n')
    with pytest.raises(gitfacts.FactsError, match=r"(?i)not a plain clone: .*core\.sshcommand"):
        gitfacts.collect(placed)
    assert not marker.exists()


def test_a_configuration_git_cannot_read_is_refused(placed: Path) -> None:
    with (placed / ".git" / "config").open("a") as config:
        config.write("[unclosed\n")
    with pytest.raises(gitfacts.FactsError, match="cannot be parsed"):
        gitfacts.collect(placed)


def test_a_branch_with_a_dot_in_its_name_reads_as_before(placed: Path) -> None:
    git(placed, "branch", "-m", "v1.0")
    git(placed, "push", "-q", "-u", "origin", "v1.0")
    facts = gitfacts.collect(placed)
    assert facts.branch == "v1.0"
    assert gitfacts.mismatches(facts) == []


def test_a_symlinked_git_dir_is_refused_not_followed(
    placed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other" / ".git"  # another clone's .git
    other.parent.mkdir()
    (placed / ".git").rename(other)
    (placed / ".git").symlink_to(other, target_is_directory=True)
    with pytest.raises(gitfacts.FactsError, match=r"\.git is not a plain directory"):
        gitfacts.collect(placed)


def test_an_entry_a_plain_clone_has_not_is_refused(placed: Path) -> None:
    (placed / ".git" / "commondir").write_text("../elsewhere\n")
    with pytest.raises(gitfacts.FactsError, match="commondir"):
        gitfacts.collect(placed)


# What one sandboxed Claude Code session left in a clone, and a plain clone has not: Claude
# Code 2.1.321, bubblewrap (cli/context/runner.md). A trailing `/` is an empty directory.
SANDBOX_LEFT = (
    "config.worktree",
    "objects/info/alternates",
    "remotes/",
    "info/.claude-sandbox-noreplace/",
    "objects/info/.claude-sandbox-noreplace/",
    "objects/info/commit-graphs/.claude-sandbox-noreplace/",
)


def _leave(clone: Path, entries: tuple[str, ...]) -> None:
    for entry in entries:
        path = clone / ".git" / entry
        if entry.endswith("/"):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()


def test_what_the_sandbox_leaves_empty_reads_as_before(placed: Path) -> None:
    """Empty, they change nothing git does; without this, the next start of a placement whose
    session ran sandboxed refused its own clone (tsk-2zz5tjpbt28n)."""
    _leave(placed, SANDBOX_LEFT)
    assert gitfacts.mismatches(gitfacts.collect(placed)) == []


@pytest.mark.parametrize(
    "entry",
    [
        "config.worktree",
        "objects/info/alternates",
        "objects/info/http-alternates",
        "remotes/origin",
        "info/.claude-sandbox-noreplace/hook",
        "objects/info/.claude-sandbox-noreplace/pack",
        "objects/info/commit-graphs/.claude-sandbox-noreplace/graph",
    ],
)
def test_a_sandbox_placeholder_with_anything_in_it_is_refused(placed: Path, entry: str) -> None:
    _leave(placed, SANDBOX_LEFT)
    path = placed / ".git" / entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[core]\n\tsparseCheckout = true\n")
    with pytest.raises(gitfacts.FactsError, match=r"not a plain clone's|exists|not supported"):
        gitfacts.collect(placed)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no FIFOs in a file system")
@pytest.mark.parametrize(
    "entry", ["config.worktree", "objects/info/alternates", "remotes", "commondir"]
)
def test_a_fifo_in_place_of_a_placeholder_is_refused(placed: Path, entry: str) -> None:
    """Empty means an empty regular file or directory: a FIFO (or a socket, a device) is
    neither, and a local read lists it with no type of its own (4hv7)."""
    _leave(placed, SANDBOX_LEFT)
    path = placed / ".git" / entry
    if path.is_dir():
        path.rmdir()
    elif path.exists():
        path.unlink()
    os.mkfifo(path)
    with pytest.raises(gitfacts.FactsError, match="not a regular file or directory"):
        gitfacts.collect(placed)


@pytest.mark.parametrize("entry", ["config.worktree", "remotes"])
def test_a_link_in_place_of_a_placeholder_is_refused(placed: Path, entry: str) -> None:
    _leave(placed, SANDBOX_LEFT)
    path = placed / ".git" / entry
    if path.is_dir():
        path.rmdir()
    else:
        path.unlink()
    path.symlink_to(placed / "elsewhere")
    with pytest.raises(gitfacts.FactsError, match="is a symlink"):
        gitfacts.collect(placed)


@pytest.mark.parametrize("entry", ["remotes/.hidden", "info/.claude-sandbox-noreplace/.hidden"])
def test_a_hidden_entry_in_a_placeholder_is_refused(placed: Path, entry: str) -> None:
    _leave(placed, SANDBOX_LEFT)
    (placed / ".git" / entry).touch()
    with pytest.raises(gitfacts.FactsError, match="not a plain clone's"):
        gitfacts.collect(placed)


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="POSIX modes; root lists any directory",
)
@pytest.mark.parametrize("entry", ["remotes", "info/.claude-sandbox-noreplace"])
def test_a_placeholder_that_cannot_be_listed_is_refused(placed: Path, entry: str) -> None:
    """Unlisted, a directory would look empty and pass as a placeholder, with a file in it
    git reads (gb8w: a `remotes/other` behind mode 0311). Both listings refuse it."""
    from maity.runner.asuser import RUNNER

    _leave(placed, SANDBOX_LEFT)
    here = placed / ".git" / entry
    (here / "other").write_text("URL: https://example.invalid/other.git\n")
    here.chmod(0o311)
    try:
        for files in (clonecheck.LOCAL, RUNNER):
            assert clonecheck.not_inspectable(placed, files) == "its .git cannot be listed in full"
    finally:
        here.chmod(0o755)


def test_without_git_common_dir_nothing_runs(placed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GIT_COMMON_DIR")
    with pytest.raises(gitfacts.FactsError, match="without GIT_COMMON_DIR"):
        gitfacts.collect(placed)


def test_an_unresolvable_git_common_dir_is_refused(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_COMMON_DIR", str(placed / "missing" / ".git"))
    with pytest.raises(gitfacts.FactsError, match="cannot be resolved"):
        gitfacts.collect(placed)


def test_a_directory_outside_the_clone_is_refused(
    placed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    with monkeypatch.context() as m:  # the helper's git would take the clone's otherwise
        m.delenv("GIT_COMMON_DIR")
        git(tmp_path, "init", "--quiet", str(other))
    with pytest.raises(gitfacts.FactsError, match="outside the clone"):
        gitfacts.position(other)


def test_a_repository_inside_the_clone_is_not_what_git_reads(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = placed / "nested"
    with monkeypatch.context() as m:
        m.delenv("GIT_COMMON_DIR")
        git(placed, "init", "--quiet", "--initial-branch=other", str(nested))
        (nested / "b.txt").write_text("b\n")
        git(nested, "add", "b.txt")
        git(nested, "commit", "--quiet", "-m", "b")
    head, branch = gitfacts.position(nested)
    assert (head, branch) == gitfacts.position(placed)
    assert branch == "work"


def test_the_runner_and_maity_read_a_clone_the_same_way(placed: Path) -> None:
    from maity.runner import operate

    assert operate.not_inspectable(placed) is None
    git(placed, "config", "alias.st", "status")
    assert operate.not_inspectable(placed) == clonecheck.not_inspectable(placed)
    assert "alias.st" in (clonecheck.not_inspectable(placed) or "")


def test_a_configuration_changed_after_the_check_is_not_what_git_reads(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The clone's configuration rewritten between maity's check and git's run, as an agent
    working in parallel could: that run reads only what maity checked (the next is refused)."""
    from maity import proc

    marker = placed.parent / "ran"
    read = clonecheck.Local.read
    rewritten: list[bool] = []

    def then_rewrite(self: clonecheck.Local, path: Path, offset: int = 0) -> bytes:
        data = read(self, path, offset)
        if path.name == "config" and not rewritten:  # once the check has its copy
            rewritten.append(True)
            with path.open("a") as config:
                config.write(f'[remote "origin"]\n\tuploadpack = {_quoted(_marking(marker))}\n')
        return data

    monkeypatch.setattr(clonecheck.Local, "read", then_rewrite)
    listed = proc.run([*proc.GIT, "ls-remote", "--heads", "--", "origin", "work"], placed)
    assert not marker.exists()
    assert listed.returncode == 0, listed.stderr
    assert "refs/heads/work" in listed.stdout
    with pytest.raises(proc.ToolError, match="uploadpack"):
        proc.run([*proc.GIT, "rev-parse", "HEAD"], placed)


def test_git_runs_on_a_repository_maity_writes_in_the_runners_directory(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity import proc

    seen: list[tuple[dict[str, str], str]] = []
    start = proc._start

    def recording(
        cmd: list[str], cwd: Path, timeout: float, env: dict[str, str], path: str | None = None
    ) -> Any:
        seen.append((env, (Path(env["GIT_DIR"]) / "config").read_text()))
        return start(cmd, cwd, timeout, env, path)

    monkeypatch.setattr(proc, "_start", recording)
    git(placed, "config", "user.name", "Someone")
    gitfacts.collect(placed)
    assert seen
    for env, config in seen:
        private = Path(env["GIT_DIR"])
        # The runner's directory for the agent, which the sandbox hides (GIT_PRIVATE_ENV).
        assert private.parent == Path(os.environ[clonecheck.GIT_PRIVATE_ENV])
        assert not private.exists()  # removed after the run
        assert config == "[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
        keys = {env[k] for k in env if k.startswith("GIT_CONFIG_KEY_")}
        assert {"remote.origin.url", "branch.work.merge", "user.name"} <= keys
        assert env["GIT_OBJECT_DIRECTORY"] == str(placed / ".git" / "objects")
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"  # no system configuration either


def test_a_link_under_refs_is_refused_not_followed(placed: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_text("0" * 40 + "\n")
    (placed / ".git" / "refs" / "heads" / "elsewhere").symlink_to(outside)
    with pytest.raises(gitfacts.FactsError, match="symlink|cannot be copied"):
        gitfacts.collect(placed)


def test_status_writes_nothing_into_the_clone(placed: Path) -> None:
    index = placed / ".git" / "index"
    (placed / "a.txt").write_text("two\n")  # changed: a status with locks would refresh
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    assert gitfacts.collect(placed).dirty
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before
    assert not (placed / ".git" / "index.lock").exists()
    assert list((placed / ".git" / "maity").iterdir()) == [placed / RECORDED_GIT]


def test_the_state_directory_under_the_runner_is_the_clones(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity import proc, state

    monkeypatch.delenv(state.STATE_DIR_ENV, raising=False)

    def no_git(*_: Any, **__: Any) -> Any:
        raise AssertionError("no git for the state directory under the runner")

    monkeypatch.setattr(proc, "run", no_git)
    assert state.resolve_state_dir(placed / "sub") == placed / ".git" / "maity"


def test_a_clone_git_for_windows_made_reads_as_before(placed: Path) -> None:
    git(placed, "config", "core.symlinks", "false")
    facts = gitfacts.collect(placed)
    assert facts.remote_head == facts.head


def test_an_ordinary_setting_says_how_to_go_on_and_keeps_the_state(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity import state

    monkeypatch.delenv(state.STATE_DIR_ENV, raising=False)
    git(placed, "config", "pull.rebase", "true")
    with pytest.raises(gitfacts.FactsError, match=r"pull\.rebase.*git config --unset"):
        gitfacts.collect(placed)
    assert state.resolve_state_dir(placed) == placed / ".git" / "maity"


def test_the_copy_by_path_reads_the_same_refs_and_refuses_links(
    placed: Path, tmp_path: Path
) -> None:
    """The copy local mode uses on Windows, run here: the same files as the POSIX copy."""
    git(placed, "pack-refs", "--all")
    git(placed, "branch", "loose")
    by_fd, by_path = tmp_path / "fd", tmp_path / "path"
    for target in (by_fd, by_path):
        (target / "refs").mkdir(parents=True)
    if sys.platform != "win32":
        with clonecheck.opened_git(placed) as top:
            clonecheck._copy_refs(placed / ".git", by_fd, top)
        listed = {p.relative_to(by_fd): p.read_bytes() for p in by_fd.rglob("*") if p.is_file()}
    clonecheck._copy_refs_by_path(placed / ".git", by_path)
    copied = {p.relative_to(by_path): p.read_bytes() for p in by_path.rglob("*") if p.is_file()}
    assert Path("refs/heads/loose") in copied and Path("packed-refs") in copied
    if sys.platform != "win32":
        assert copied == listed
    outside = tmp_path / "outside"
    outside.write_text("0" * 40 + "\n")
    try:
        (placed / ".git" / "refs" / "heads" / "elsewhere").symlink_to(outside)
    except OSError:
        pytest.skip("no symlinks for this user")
    again = tmp_path / "again"
    (again / "refs").mkdir(parents=True)
    with pytest.raises(clonecheck.Refused, match="elsewhere"):
        clonecheck._copy_refs_by_path(placed / ".git", again)


def test_git_under_the_runner_gets_none_of_maitys_own_git_variables(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A variable set for maity, as an agent's command line can, does not reach git."""
    from maity import proc

    marker = placed.parent / "ran"
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "remote.origin.uploadpack")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", _marking(marker))
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", _marking(marker))
    listed = proc.run([*proc.GIT, "ls-remote", "--heads", "--", "origin", "work"], placed)
    assert not marker.exists()
    assert listed.returncode == 0, listed.stderr
    assert "refs/heads/work" in listed.stdout


def test_git_under_the_runner_reads_no_configuration_of_homes(
    placed: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """HOME reaches git, its configuration does not: maity's own and the checked entries
    are all git reads."""
    from maity import proc

    marker = placed.parent / "ran"
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        f'[remote "origin"]\n\tuploadpack = {_quoted(_marking(marker))}\n'
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # git for Windows' HOME fallback
    listed = proc.run([*proc.GIT, "ls-remote", "--heads", "--", "origin", "work"], placed)
    assert not marker.exists()
    assert listed.returncode == 0, listed.stderr
    assert "refs/heads/work" in listed.stdout


def test_git_under_the_runner_is_the_one_it_recorded_not_paths(
    placed: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A git first on the PATH of maity's command line is not the one maity starts."""
    from maity import proc

    marker = placed.parent / "ran"
    bin_dir = tmp_path / "first-on-path"
    bin_dir.mkdir()
    wrapper = bin_dir / ("git.cmd" if sys.platform == "win32" else "git")
    if sys.platform == "win32":
        wrapper.write_text(f'@{_marking(marker)}\r\n@"{shutil.which("git")}" %*\r\n')
    else:
        wrapper.write_text(f'#!/bin/sh\n{_marking(marker)}\nexec "{shutil.which("git")}" "$@"\n')
        wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert proc.program("git") == str(wrapper) or sys.platform == "win32"
    assert proc.run([*proc.GIT, "rev-parse", "HEAD"], placed).returncode == 0
    assert not marker.exists()


def test_git_under_the_runner_reads_no_ignore_or_attributes_file_of_homes(
    placed: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """HOME's own ignore and attributes files do not change what maity sees in the clone."""
    from maity import proc

    home = tmp_path / "home"
    (home / ".config" / "git").mkdir(parents=True)
    (home / ".config" / "git" / "ignore").write_text("*.secret\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    (home / ".config" / "git" / "attributes").write_text("*.secret probeattr=yes\n")
    (placed / "a.secret").write_text("x\n")
    status = proc.run([*proc.GIT, "status", "--porcelain"], placed)
    assert "a.secret" in status.stdout, status.stderr
    attr = proc.run([*proc.GIT, "check-attr", "probeattr", "--", "a.secret"], placed)
    assert attr.stdout.strip().endswith("unspecified"), attr.stdout + attr.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no execute bit")
def test_a_recorded_git_that_is_no_program_is_named_so(placed: Path, tmp_path: Path) -> None:
    from maity import proc

    plain = tmp_path / "git"
    plain.write_text("not a program\n")
    (placed / RECORDED_GIT).write_text(f"{plain}\n")
    with pytest.raises(proc.ToolError, match="is not a program here"):
        proc.run([*proc.GIT, "rev-parse", "HEAD"], placed)


def test_a_partial_clone_is_named_so(
    placed: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """What `git clone --filter` writes, with no `extensions.` line, is named a partial clone,
    without the unset hint that would leave the clone without its missing objects."""
    source = placed.parent / "remote.git"
    git(source, "config", "uploadpack.allowFilter", "true")
    partial = tmp_path / "partial"
    monkeypatch.delenv("GIT_COMMON_DIR")  # the session's, which would point the clone there
    git(tmp_path, "clone", "-q", "--filter=blob:none", f"file://{source.as_posix()}", str(partial))
    (partial / ".git" / "maity").mkdir()
    (partial / RECORDED_GIT).write_text(f"{shutil.which('git')}\n")
    monkeypatch.setenv("GIT_COMMON_DIR", str(partial / ".git"))
    monkeypatch.setenv(clonecheck.GIT_INODE_ENV, str(os.lstat(partial / ".git").st_ino))
    with pytest.raises(gitfacts.FactsError, match="Partial clones are not supported") as refused:
        gitfacts.collect(partial)
    assert "unset" not in str(refused.value)


def test_on_windows_git_gets_the_systems_systemroot_not_maitys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both git runs under the runner, the configuration parse and git itself: SYSTEMROOT and
    the PATH built from it are the system's, whatever maity's environment says."""
    seen: list[dict[str, str]] = []

    def recording(cmd: list[str], **kwargs: Any) -> Any:
        seen.append(kwargs["env"])
        raise OSError("not started")

    monkeypatch.setenv("SYSTEMROOT", "/chosen/by/the/command/line")
    monkeypatch.setenv("PATH", f"/chosen/path{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(clonecheck, "_windows_directory", lambda: "/the/system")
    monkeypatch.setattr(clonecheck, "_windows", lambda: True, raising=False)
    monkeypatch.setattr(subprocess, "run", recording)
    assert clonecheck.config_entries(b"", "/opt/git/cmd/git") is None
    pinned = clonecheck.git_path_env("/opt/git/cmd/git")
    monkeypatch.undo()
    assert seen[0]["SYSTEMROOT"] == "/the/system"
    assert pinned["SYSTEMROOT"] == "/the/system"
    assert "/chosen" not in pinned["PATH"] and "/chosen" not in seen[0]["PATH"]


def test_the_runners_values_win_over_maitys_environment(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What git under the runner gets: maity's kept variables first, the runner's own after
    them, so a kept SYSTEMROOT (Windows) or PATH from the command line never wins."""
    from maity import proc

    seen: list[dict[str, str]] = []

    def recording(
        cmd: list[str], cwd: Path, timeout: float, env: dict[str, str], path: str | None = None
    ) -> Any:
        seen.append(dict(env))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setenv("SYSTEMROOT", "/chosen/by/the/command/line")
    monkeypatch.setenv("PATH", f"/chosen/path{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(clonecheck, "_windows", lambda: True, raising=False)
    monkeypatch.setattr(clonecheck, "_windows_directory", lambda: "/the/system", raising=False)
    monkeypatch.setattr(proc, "_start", recording)
    proc.run([*proc.GIT, "status", "--porcelain"], placed)
    (env,) = seen
    assert env["SYSTEMROOT"] == "/the/system"
    assert "/chosen" not in env["PATH"]


def _decoy(placed: Path, marker: Path) -> Path:
    """What sandboxed code can do in the clone's root (ur6p's reproduction for
    tsk-er1nymh4te1h): move the real `.git` aside and put a copy of its own in its place,
    whose `maity/git` names a program of the session's own and whose HEAD names another
    branch, so what git then reads tells which `.git` it was."""
    if not git(placed, "branch", "--list", "decoy-branch"):
        git(placed, "branch", "decoy-branch")
    real = placed / ".git-real"
    (placed / ".git").rename(real)
    shutil.copytree(real, placed / ".git", symlinks=True, ignore=shutil.ignore_patterns("maity"))
    (placed / ".git" / "HEAD").write_text("ref: refs/heads/decoy-branch\n")
    (placed / ".git" / "maity").mkdir()
    (placed / ".git" / "maity" / "placement").write_text("plc-0003\n")
    program = placed / "marker.py"
    program.write_text(f"#!{sys.executable}\nopen({str(marker)!r}, 'a').write('ran\\n')\n")
    program.chmod(0o755)
    (placed / RECORDED_GIT).write_text(f"{program}\n")
    return real


@pytest.mark.skipif(sys.platform == "win32", reason="the decoy git is a shebang script")
def test_a_git_directory_put_in_place_of_the_runners_is_refused(
    placed: Path, tmp_path: Path
) -> None:
    """The sandbox does not keep the agent from renaming `.git` (Claude Code itself pins it
    with a mount today, nothing of ours does): maity takes only the `.git` whose inode the
    runner recorded, so the decoy's git never runs outside the sandbox."""
    from maity import proc

    marker = tmp_path / "pwned"
    _decoy(placed, marker)
    with pytest.raises(proc.ToolError, match="not the directory it was"):
        proc.run([*proc.GIT, "status"], placed)
    assert not marker.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the decoy git is a shebang script")
def test_a_git_directory_replaced_after_the_check_is_not_read(
    placed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The decoy lands right after maity checked `.git`'s inode: what maity reads next (the
    recorded git, the refs, the new directory) comes through the descriptor it checked, so
    the decoy's git still never runs."""
    from maity import proc

    marker = tmp_path / "pwned"
    real_fstat = os.fstat
    swapped: list[Path] = []

    def fstat_then_swap(fd: int) -> os.stat_result:
        result = real_fstat(fd)
        if (
            not swapped
            and stat.S_ISDIR(result.st_mode)
            and os.path.samestat(result, os.lstat(placed / ".git"))
        ):
            swapped.append(_decoy(placed, marker))
        return result

    git(placed, "branch", "decoy-branch")  # the decoy's HEAD: one commit behind the real one
    git(placed, "commit", "-q", "--allow-empty", "-m", "real only")
    head = git(placed, "rev-parse", "HEAD")
    monkeypatch.setattr(os, "fstat", fstat_then_swap)
    ran = proc.run([*proc.GIT, "rev-parse", "HEAD"], placed)
    # The real clone's HEAD (its refs came through the descriptor), not the decoy's branch.
    assert swapped and ran.stdout.strip() == head and not marker.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX: a link and the descriptor walk")
def test_a_link_put_in_place_of_git_after_the_session_check_is_refused(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.git` turned into a link to the real one between the session's check of its name
    (placement_root) and the open: it names the recorded directory, but no link is followed."""
    from maity import proc

    real_root = clonecheck.placement_root

    def root_then_link(cwd: Path | None = None) -> Path | None:
        found = real_root(cwd)
        real = placed / ".git-real"
        (placed / ".git").rename(real)
        (placed / ".git").symlink_to(real, target_is_directory=True)
        return found

    monkeypatch.setattr(clonecheck, "placement_root", root_then_link)
    with pytest.raises(proc.ToolError, match="not the directory it was"):
        proc.run([*proc.GIT, "status"], placed)


@pytest.mark.skipif(sys.platform == "win32", reason="the decoy git is a shebang script")
def test_where_no_directory_opens_the_inode_is_compared_by_name(
    placed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows (local mode) has no descriptor walk: the decoy is still refused by its inode."""
    from maity import proc

    monkeypatch.setattr(clonecheck, "_walks", lambda: False)
    marker = tmp_path / "pwned"
    _decoy(placed, marker)
    with pytest.raises(proc.ToolError, match="not the directory it was"):
        proc.run([*proc.GIT, "status"], placed)
    assert not marker.exists()


def test_gits_own_repository_is_outside_the_clone(placed: Path) -> None:
    """git opens its repository and configuration by path, after maity's check: none of them
    goes through the name `.git`, which sandboxed code can give another directory."""
    with clonecheck.placement_git(placed) as pinned:
        assert pinned is not None
        root = placed.resolve()
        for name in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_CONFIG_GLOBAL"):
            where = Path(pinned.env[name]).resolve()
            assert root not in where.parents, name
            assert Path(os.environ[clonecheck.GIT_PRIVATE_ENV]).resolve() in where.parents


def test_a_git_directory_that_is_a_link_is_refused(placed: Path, tmp_path: Path) -> None:
    """A link to the real `.git` is refused too, though it names the recorded directory."""
    from maity import proc

    real = placed / ".git-real"
    (placed / ".git").rename(real)
    (placed / ".git").symlink_to(real, target_is_directory=True)
    with pytest.raises(proc.ToolError, match="not a plain directory|not the directory it was"):
        proc.run([*proc.GIT, "status"], placed)


def test_without_the_recorded_inode_maity_runs_no_git_there(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session a runner without this check started: restart it, then the inode is set."""
    from maity import proc

    monkeypatch.delenv(clonecheck.GIT_INODE_ENV)
    with pytest.raises(proc.ToolError, match="restart the placement"):
        proc.run([*proc.GIT, "status"], placed)


def test_without_a_directory_outside_the_private_repository_is_made_through_the_git_fd(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex, whose maity runs in its sandbox, gets no directory outside the clone: the one in
    `.git/maity` is made through the descriptor of the recorded `.git`, never by name."""
    from maity import proc

    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, clonecheck.IN_CLONE)
    made: list[Any] = []
    real_mkdir = os.mkdir

    def mkdir(path: Any, mode: int = 0o777, *, dir_fd: int | None = None) -> None:
        made.append((str(path), dir_fd))
        real_mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "mkdir", mkdir)
    assert proc.run([*proc.GIT, "rev-parse", "HEAD"], placed).returncode == 0
    private = [where for name, where in made if name.startswith("git-")]
    if sys.platform != "win32":
        assert len(private) == 1 and private[0] is not None


def test_without_a_recorded_git_the_runners_clone_runs_none(placed: Path) -> None:
    from maity import proc

    (placed / RECORDED_GIT).unlink()
    with pytest.raises(proc.ToolError, match="no git the runner recorded"):
        proc.run([*proc.GIT, "rev-parse", "HEAD"], placed)


@pytest.mark.parametrize("how", ["gitfile", "GIT_DIR", "GIT_COMMON_DIR", "GIT_DIR=gitfile"])
def test_a_marked_clone_is_refused_from_outside_it_too(
    placed: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, how: str
) -> None:
    """Without the session, a directory outside that leads git to the marked clone's .git
    is refused like one inside it, the state lookup too."""
    from maity import proc, state

    ran = placed.parent / "ran"
    (placed / ".git" / "maity" / "placement").write_text("plc-0003\n")  # as adapters.launch
    git(placed, "config", "remote.origin.uploadpack", _marking(ran))  # the agent's own
    monkeypatch.delenv("MAITY_PLACEMENT")
    monkeypatch.delenv("GIT_COMMON_DIR")
    monkeypatch.delenv("MAITY_STATE_DIR", raising=False)
    outside = tmp_path / "outside"
    outside.mkdir()
    if how == "gitfile":
        (outside / ".git").write_text(f"gitdir: {placed / '.git'}\n")
    elif how == "GIT_DIR=gitfile":  # git follows a .git file GIT_DIR names
        (tmp_path / "pointer").write_text(f"gitdir: {placed / '.git'}\n")
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "pointer"))
    else:
        monkeypatch.setenv(how, str(placed / ".git"))
    with pytest.raises(proc.ToolError, match="the runner set up"):
        proc.run([*proc.GIT, "ls-remote", "--heads", "--", "origin"], outside)
    assert not ran.exists()
    with pytest.raises(state.StateError, match="the runner set up"):
        state.resolve_state_dir(outside)


def test_a_clone_the_runner_marked_runs_no_git_without_the_session(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity import proc

    marker = placed / ".git" / "maity" / "placement"  # as adapters.launch writes it
    marker.write_text("plc-0003\n")
    monkeypatch.delenv("MAITY_PLACEMENT")
    monkeypatch.delenv("GIT_COMMON_DIR")
    with pytest.raises(proc.ToolError, match="the runner set up"):
        proc.run([*proc.GIT, "rev-parse", "HEAD"], placed)
    marker.unlink()
    assert proc.run([*proc.GIT, "rev-parse", "HEAD"], placed).returncode == 0


def test_a_git_dir_with_too_many_entries_is_refused_without_listing_them_all(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(clonecheck, "TREE_MAX", 20, raising=False)
    listed = clonecheck.Local().tree(placed / ".git")
    total = sum(len(d) + len(f) for _, d, f in os.walk(placed / ".git"))
    assert 20 < len(listed) < total
    with pytest.raises(gitfacts.FactsError, match="more than 20 entries"):
        gitfacts.collect(placed)


def test_one_wide_directory_is_not_listed_past_the_cap(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(clonecheck, "TREE_MAX", 20, raising=False)
    wide = placed / ".git" / "objects" / "aa"
    wide.mkdir(exist_ok=True)
    for i in range(60):
        (wide / f"{i:038x}").write_bytes(b"")
    assert len(clonecheck.Local().tree(wide)) == 21  # one more than the cap, to refuse
    with pytest.raises(gitfacts.FactsError, match="more than 20 entries"):
        gitfacts.collect(placed)


@pytest.mark.parametrize("cone", ["--cone", "--no-cone"])
def test_a_sparse_checkout_set_up_by_git_is_named_so(placed: Path, cone: str) -> None:
    git(placed, "sparse-checkout", "set", cone, "x")
    with pytest.raises(gitfacts.FactsError, match="Sparse checkout is not supported") as refused:
        gitfacts.collect(placed)
    assert "unset" not in str(refused.value)


@pytest.mark.parametrize(
    ("key", "value", "feature"),
    [
        ("core.sparseCheckoutCone", "true", "Sparse checkout is"),
        ("extensions.partialClone", "origin", "Partial clones are"),
        ("extensions.objectFormat", "sha1", "Repository format extensions are"),
        ("extensions.worktreeConfig", "true", "Worktrees are"),
    ],
)
def test_each_unsupported_setting_is_named_for_its_feature(
    placed: Path, key: str, value: str, feature: str
) -> None:
    git(placed, "config", key, value)
    with pytest.raises(gitfacts.FactsError, match=f"{feature} not supported") as refused:
        gitfacts.collect(placed)
    assert "unset" not in str(refused.value)


def test_the_copy_by_path_refuses_refs_that_are_a_link(placed: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    shutil.copytree(placed / ".git" / "refs", elsewhere)
    shutil.rmtree(placed / ".git" / "refs")
    try:
        (placed / ".git" / "refs").symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip("no symlinks for this user")
    copy = tmp_path / "copy"
    copy.mkdir()
    with pytest.raises(clonecheck.Refused, match="refs is not a directory"):
        clonecheck._copy_refs_by_path(placed / ".git", copy)
    assert not (copy / "refs").exists()


@pytest.mark.parametrize(
    ("change", "feature"),
    [
        (lambda c: (c / ".git" / "modules").mkdir(), "Submodules are"),
        (lambda c: git(c, "config", "submodule.lib.url", "../lib.git"), "Submodules are"),
        (lambda c: (c / ".git" / "lfs").mkdir(), "Git LFS is"),
        (lambda c: git(c, "config", "filter.lfs.required", "true"), "Git LFS is"),
        (lambda c: (c / ".git" / "worktrees").mkdir(), "Worktrees are"),
        (lambda c: git(c, "config", "core.sparseCheckout", "true"), "Sparse checkout is"),
    ],
)
def test_what_the_runner_does_not_support_yet_is_named_so(
    placed: Path, change: Any, feature: str
) -> None:
    change(placed)
    with pytest.raises(gitfacts.FactsError, match=f"{feature} not supported") as refused:
        gitfacts.collect(placed)
    assert "unset" not in str(refused.value)


def test_a_private_directory_that_cannot_be_used_is_maitys_refusal(
    placed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not a directory, or one maity cannot write: refused with the reason, no traceback."""
    from maity import proc

    plain = tmp_path / "a-file"
    plain.write_text("")
    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, str(plain))
    with pytest.raises(proc.ToolError, match="names no directory"):
        proc.run([*proc.GIT, "status"], placed)
    if sys.platform != "win32" and os.geteuid() != 0:
        closed = tmp_path / "closed"
        closed.mkdir(mode=0o500)
        monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, str(closed))
        with pytest.raises(proc.ToolError, match="cannot be made"):
            proc.run([*proc.GIT, "status"], placed)


@pytest.mark.parametrize("how", ["unset", "empty"])
def test_without_a_private_directory_maity_runs_no_git(
    placed: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """A lost variable never puts git's repository back under `.git` (review of #1683)."""
    from maity import proc

    if how == "unset":
        monkeypatch.delenv(clonecheck.GIT_PRIVATE_ENV)
    else:
        monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, "")
    with pytest.raises(proc.ToolError, match="restart the placement"):
        proc.run([*proc.GIT, "status"], placed)


@pytest.mark.parametrize("how", ["in the clone", "the clone through a linked parent", "a link",
                                 "relative"])  # fmt: skip
def test_a_private_directory_that_is_not_the_runners_is_refused(
    placed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """Inside the clone the sandbox could write it; a link or a relative path could name
    anywhere."""
    from maity import proc

    if how == "in the clone":
        (placed / "work").mkdir()
        value = str(placed / "work")
    elif how == "the clone through a linked parent":  # only resolving the path finds the clone
        (placed / "work").mkdir()
        parent = tmp_path / "linked"
        parent.symlink_to(placed, target_is_directory=True)
        value = str(parent / "work")
    elif how == "a link":
        link = tmp_path / "link"
        link.symlink_to(Path(os.environ[clonecheck.GIT_PRIVATE_ENV]), target_is_directory=True)
        value = str(link)
    else:  # the runner's own directory, but named from wherever maity happens to run
        value = os.path.relpath(os.environ[clonecheck.GIT_PRIVATE_ENV])
    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, value)
    with pytest.raises(proc.ToolError, match="names no directory"):
        proc.run([*proc.GIT, "status"], placed)


def test_a_repository_that_cannot_be_filled_is_maitys_refusal(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity import proc

    def failing(*args: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(clonecheck, "_copy_refs", failing)
    with pytest.raises(proc.ToolError, match="cannot be made"):
        proc.run([*proc.GIT, "status"], placed)


def test_an_inode_in_other_digits_is_refused(placed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`str.isdigit` takes a superscript two, which `int` then refuses: ASCII digits only."""
    from maity import proc

    monkeypatch.setenv(clonecheck.GIT_INODE_ENV, "\u00b2")
    with pytest.raises(proc.ToolError, match="restart the placement"):
        proc.run([*proc.GIT, "status"], placed)
