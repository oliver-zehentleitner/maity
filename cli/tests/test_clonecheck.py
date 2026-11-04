"""maity's own git in a session the runner started: only in the runner's clone, and only while
that clone is a plain one."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import git

from maity import clonecheck, gitfacts


@pytest.fixture
def placed(clone: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`clone` as the runner leaves it: a plain clone, `MAITY_PLACEMENT` and `GIT_COMMON_DIR`
    set the way the runner sets them for a session."""
    remote = clone.parent / "remote.git"
    git(clone, "config", "--remove-section", f"url.{remote}")
    git(clone, "remote", "set-url", "origin", str(remote))
    (clone / ".git" / "maity").mkdir(exist_ok=True)  # the runner makes it (adapters)
    monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    monkeypatch.setenv("GIT_COMMON_DIR", str(clone / ".git"))
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


def test_git_runs_on_a_repository_maity_writes_under_git_maity(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity import proc

    seen: list[tuple[dict[str, str], str]] = []
    start = proc._start

    def recording(cmd: list[str], cwd: Path, timeout: float, env: dict[str, str]) -> Any:
        seen.append((env, (Path(env["GIT_DIR"]) / "config").read_text()))
        return start(cmd, cwd, timeout, env)

    monkeypatch.setattr(proc, "_start", recording)
    git(placed, "config", "user.name", "Someone")
    gitfacts.collect(placed)
    assert seen
    for env, config in seen:
        private = Path(env["GIT_DIR"])
        assert private.parent == placed / ".git" / "maity"  # where the sandbox denies writes
        assert not private.exists()  # removed after the run
        assert config == "[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
        keys = {env[k] for k in env if k.startswith("GIT_CONFIG_KEY_")}
        assert {"remote.origin.url", "branch.work.merge", "user.name"} <= keys
        assert env["GIT_OBJECT_DIRECTORY"] == str(placed / ".git" / "objects")


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
    assert list((placed / ".git" / "maity").iterdir()) == []


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
        clonecheck._copy_refs(placed / ".git", by_fd)
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
