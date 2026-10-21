from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from conftest import fake_gh, git

from maity import cli, gitfacts


def pr_json(head: str, number: int = 12) -> str:
    return json.dumps(
        [{"number": number, "headRefOid": head, "state": "OPEN", "url": f"https://x/pull/{number}"}]
    )


def test_matching_state_has_no_mismatches(clone: Path) -> None:
    facts = gitfacts.collect(clone)
    assert facts.branch == "work"
    assert facts.remote_head == facts.head
    assert facts.pr is None
    assert facts.pr_unknown_reason == "gh is not installed"
    assert gitfacts.mismatches(facts) == []


def test_unpushed_commit_is_refused(clone: Path) -> None:
    (clone / "a.txt").write_text("two\n")
    git(clone, "commit", "--quiet", "-am", "two")
    problems = gitfacts.mismatches(gitfacts.collect(clone))
    assert len(problems) == 1
    assert "push or pull" in problems[0]


def test_uncommitted_change_is_refused(clone: Path) -> None:
    (clone / "a.txt").write_text("dirty\n")
    assert any("uncommitted" in p for p in gitfacts.mismatches(gitfacts.collect(clone)))


def test_untracked_file_is_not_a_mismatch(clone: Path) -> None:
    (clone / "notes.txt").write_text("scratch\n")
    assert gitfacts.mismatches(gitfacts.collect(clone)) == []


def test_branch_without_upstream_is_refused(clone: Path) -> None:
    git(clone, "switch", "--quiet", "-c", "local-only")
    assert any("no upstream" in p for p in gitfacts.mismatches(gitfacts.collect(clone)))


def test_branch_deleted_on_remote_is_refused(clone: Path) -> None:
    git(clone, "push", "--quiet", "origin", "--delete", "work")
    assert any("does not exist" in p for p in gitfacts.mismatches(gitfacts.collect(clone)))


def test_detached_head_is_refused(clone: Path) -> None:
    git(clone, "switch", "--quiet", "--detach")
    assert any("detached" in p for p in gitfacts.mismatches(gitfacts.collect(clone)))


def test_pr_head_matching_is_accepted(clone: Path, bin_dir: Path) -> None:
    fake_gh(bin_dir, pr_json(git(clone, "rev-parse", "HEAD")))
    facts = gitfacts.collect(clone)
    assert facts.pr is not None and facts.pr.number == 12
    assert gitfacts.mismatches(facts) == []


def test_pr_head_mismatch_is_refused(clone: Path, bin_dir: Path) -> None:
    fake_gh(bin_dir, pr_json("0" * 40))
    head = git(clone, "rev-parse", "HEAD")
    problems = gitfacts.mismatches(gitfacts.collect(clone))
    assert problems == [f"pull request #12 has head {'0' * 12}, local HEAD is at {head[:12]}"]


def test_no_pr_for_branch(clone: Path, bin_dir: Path) -> None:
    fake_gh(bin_dir, "[]")
    facts = gitfacts.collect(clone)
    assert facts.pr is None and facts.pr_unknown_reason is None


def test_failing_gh_is_an_error_not_a_silent_none(clone: Path, bin_dir: Path) -> None:
    fake_gh(bin_dir, "", exit_code=1, stderr="authentication required")
    with pytest.raises(gitfacts.FactsError, match="authentication required"):
        gitfacts.collect(clone)


def test_report_command_refuses_with_exit_4(
    joined: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(bin_dir, pr_json("f" * 40, number=7))
    assert cli.main(["report", "--task", "T-1", "--summary", "s"]) == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "report refused" in err and "#7" in err


def test_remote_off_github_is_unknown_without_asking_gh(clone: Path, bin_dir: Path) -> None:
    fake_gh(bin_dir, "", exit_code=1, stderr="must not be called")
    gitlab = "git@gitlab.example:acme/widget.git"
    git(clone, "remote", "set-url", "origin", gitlab)
    git(clone, "config", "--add", f"url.{clone.parent / 'remote.git'}.insteadOf", gitlab)
    facts = gitfacts.collect(clone)
    assert facts.pr is None
    assert facts.pr_unknown_reason is not None and "gitlab.example" in facts.pr_unknown_reason
    assert gitfacts.mismatches(facts) == []


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://github.com/a/b", "github.com"),
        ("git@github.com:a/b.git", "github.com"),
        ("ssh://git@gitlab.example:2222/a/b", "gitlab.example"),
        ("/srv/git/b.git", None),
    ],
)
def test_remote_host(url: str, host: str | None) -> None:
    assert gitfacts.remote_host(url) == host


def test_a_failing_git_status_is_an_error_not_a_clean_tree(clone: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root reads an unreadable index")
    (clone / "a.txt").write_text("modified\n")
    index = clone / ".git" / "index"
    index.chmod(0)
    try:
        with pytest.raises(gitfacts.FactsError, match="git status failed"):
            gitfacts.collect(clone)
    finally:
        index.chmod(0o644)


def test_an_upstream_on_a_local_branch_is_no_upstream(clone: Path) -> None:
    git(clone, "branch", "--quiet", "base")
    git(clone, "switch", "--quiet", "-c", "feature", "--track", "base")
    facts = gitfacts.collect(clone)
    assert facts.remote is None
    assert any("no upstream" in p for p in gitfacts.mismatches(facts))


def test_detached_and_dirty_are_both_reported(clone: Path) -> None:
    git(clone, "switch", "--quiet", "--detach")
    (clone / "a.txt").write_text("dirty\n")
    problems = gitfacts.mismatches(gitfacts.collect(clone))
    assert any("uncommitted" in p for p in problems)
    assert any("detached" in p for p in problems)


def test_report_checks_the_join_before_asking_git_and_gh(
    clone: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(bin_dir, "", exit_code=1, stderr="must not be called")
    assert cli.main(["report", "--task", "T", "--summary", "s"]) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "maity join" in err and "must not be called" not in err
