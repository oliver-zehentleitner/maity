"""maity's own git in a session the runner started: only in the runner's clone, and only while
that clone is a plain one."""

from __future__ import annotations

import re
import sys
from pathlib import Path

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
    monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    monkeypatch.setenv("GIT_COMMON_DIR", str(clone / ".git"))
    return clone


def test_a_plain_clone_reads_as_before(placed: Path) -> None:
    facts = gitfacts.collect(placed)
    assert facts.remote_head == facts.head
    assert gitfacts.mismatches(facts) == []


def test_without_a_placement_nothing_is_checked(clone: Path) -> None:
    git(clone, "config", "core.pager", "cat")
    assert clonecheck.placement_git(clone) is None
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
