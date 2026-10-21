from __future__ import annotations

import json
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
    assert not facts.gh_available
    assert facts.pr is None
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
    assert facts.gh_available and facts.pr is None


def test_failing_gh_is_an_error_not_a_silent_none(clone: Path, bin_dir: Path) -> None:
    fake_gh(bin_dir, "", exit_code=1, stderr="authentication required")
    with pytest.raises(gitfacts.FactsError, match="authentication required"):
        gitfacts.collect(clone)


def test_report_command_refuses_with_exit_4(
    clone: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(bin_dir, pr_json("f" * 40, number=7))
    assert cli.main(["report", "--task", "T-1"]) == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "report refused" in err and "#7" in err


def test_report_command_prints_facts_when_they_agree(
    clone: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = git(clone, "rev-parse", "HEAD")
    fake_gh(bin_dir, pr_json(head))
    code = cli.main(["report", "--task", "T-1"])
    out = capsys.readouterr().out
    assert head in out and "#12" in out
    assert code == cli.EXIT_ERROR  # facts agree, but this clone has not joined
