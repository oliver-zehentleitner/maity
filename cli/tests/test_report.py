from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import fake_gh, git, posix

from maity import cli, gitfacts

# Absolute: the fixtures' PATH holds git alone.
TOOLS = {"sh": shutil.which("sh") or "/bin/sh", "touch": shutil.which("touch") or "/usr/bin/touch"}


def pr_json(head: str, number: int = 12, state: str = "OPEN") -> str:
    return json.dumps(
        [{"number": number, "headRefOid": head, "state": state, "url": f"https://x/pull/{number}"}]
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


def test_a_branch_deleted_after_its_merge_reports_the_merged_head(
    clone: Path, bin_dir: Path
) -> None:
    head = git(clone, "rev-parse", "HEAD")
    git(clone, "push", "--quiet", "origin", "--delete", "work")
    fake_gh(bin_dir, pr_json(head, state="MERGED"))
    facts = gitfacts.collect(clone)
    assert facts.branch_merged and facts.remote_head == head
    assert gitfacts.mismatches(facts) == []


@pytest.mark.parametrize(
    "state, other_head",
    [("OPEN", False), ("CLOSED", False), ("MERGED", True)],
)
def test_a_deleted_branch_without_a_matching_merge_is_refused(
    clone: Path, bin_dir: Path, state: str, other_head: bool
) -> None:
    head = git(clone, "rev-parse", "HEAD")
    git(clone, "push", "--quiet", "origin", "--delete", "work")
    fake_gh(bin_dir, pr_json("0" * 40 if other_head else head, state=state))
    facts = gitfacts.collect(clone)
    assert not facts.branch_merged and facts.remote_head is None
    assert any("--no-code" in p for p in gitfacts.mismatches(facts))


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
    """The failure is kept, never read as "no pull request"; `report` raises it unless the
    card's linked pull request, read by the hub's probe, stands in (test_report_card.py)."""
    fake_gh(bin_dir, "", exit_code=1, stderr="authentication required")
    facts = gitfacts.collect(clone)
    assert facts.pr is None and facts.forge_error is not None
    assert "authentication required" in facts.forge_error


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
        ("C:\\Users\\a\\b.git", None if os.name == "nt" else "C"),
        ("C:/Users/a/b.git", None if os.name == "nt" else "C"),
        ("https:///a/b.git", None),
        ("host-alias:b.git", "host-alias"),
    ],
)
def test_remote_host(url: str, host: str | None) -> None:
    assert gitfacts.remote_host(url) == host


@posix
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


@posix
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("remote", "--upload-pack={touch} {marker}"),
        ("remote", "ext::{sh} -c {touch}% {marker}"),
        ("merge", "--upload-pack={touch} {marker}"),
        ("merge", "refs/tags/v1"),
    ],
)
def test_an_upstream_git_would_read_as_more_is_refused(clone: Path, key: str, value: str) -> None:
    marker = clone.parent / "ran"
    git(clone, "config", f"branch.work.{key}", value.format(marker=marker, **TOOLS))
    with pytest.raises(gitfacts.FactsError, match="upstream"):
        gitfacts.collect(clone)
    assert not marker.exists()


@posix
def test_a_remote_url_naming_a_helper_is_refused(clone: Path) -> None:
    marker = clone.parent / "ran"
    git(
        clone,
        "remote",
        "set-url",
        "origin",
        "ext::{sh} -c {touch}% {marker}".format(marker=marker, **TOOLS),
    )
    git(clone, "config", "protocol.ext.allow", "always")
    with pytest.raises(gitfacts.FactsError, match="upstream"):
        gitfacts.collect(clone)
    assert not marker.exists()


def test_an_upstream_pushed_to_a_url_still_reads(clone: Path) -> None:
    git(clone, "config", "branch.work.remote", str(clone.parent / "remote.git"))
    facts = gitfacts.collect(clone)
    assert facts.remote_head == facts.head


def test_pull_request_state_asks_gh_only_about_known_hosts(
    clone: Path, bin_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_gh(bin_dir, '{"state": "OPEN"}')
    monkeypatch.delenv("GH_HOST", raising=False)
    assert gitfacts.pull_request_state(clone, "https://github.com/a/b/pull/1") == "open"
    assert gitfacts.pull_request_state(clone, "https://evil.example/a/b/pull/1") is None
    assert gitfacts.pull_request_state(clone, "http://github.com/a/b/pull/1") is None
    assert gitfacts.pull_request_state(clone, "--repo=x") is None
    monkeypatch.setenv("GH_HOST", "git.corp.example")
    assert gitfacts.pull_request_state(clone, "https://git.corp.example/a/b/pull/1") == "open"


@pytest.mark.parametrize("form", ["relative path", "host:path", "configured name"])
def test_every_upstream_git_push_u_stores_still_reads(clone: Path, form: str) -> None:
    remote = clone.parent / "remote.git"
    if form == "relative path":
        git(clone, "config", "branch.work.remote", "../remote.git")
    elif form == "host:path":
        git(clone, "config", f"url.{remote}.insteadOf", "forge-alias:widget.git")
        git(clone, "config", "branch.work.remote", "forge-alias:widget.git")
    else:
        git(clone, "remote", "add", "r\u00e9seau", str(remote))
        git(clone, "config", "branch.work.remote", "r\u00e9seau")
    facts = gitfacts.collect(clone)
    assert facts.remote_head == facts.head
    assert gitfacts.mismatches(facts) == []


def test_a_malformed_pull_request_url_is_not_asked_about(clone: Path, bin_dir: Path) -> None:
    fake_gh(bin_dir, '{"state": "OPEN"}')
    assert gitfacts.pull_request_state(clone, "https://[invalid/a/b/pull/1") is None


def test_an_empty_gh_host_names_no_host(
    clone: Path, bin_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_gh(bin_dir, '{"state": "OPEN"}')
    monkeypatch.setenv("GH_HOST", "")
    assert gitfacts.gh_hosts() == {"github.com"}
    assert gitfacts.pull_request_state(clone, "https:///a/b/pull/1") is None
    git(clone, "remote", "set-url", "origin", str(clone.parent / "remote.git"))
    assert gitfacts.collect(clone).pr_unknown_reason is not None  # a path: gh is not asked


def test_a_windows_drive_path_upstream_passes_the_check(clone: Path) -> None:
    gitfacts._check_upstream(clone, "work", "C:\\Users\\a\\remote.git", "refs/heads/work")
    gitfacts._check_upstream(clone, "work", "C:/Users/a/remote.git", "refs/heads/work")


@posix
def test_every_configured_url_of_the_remote_is_checked(clone: Path) -> None:
    marker = clone.parent / "ran"
    helper = "ext::{sh} -c {touch}% {marker}".format(marker=marker, **TOOLS)
    git(clone, "config", "remote.origin.url", helper)
    git(clone, "config", "--add", "remote.origin.url", str(clone.parent / "remote.git"))
    with pytest.raises(gitfacts.FactsError, match="upstream"):
        gitfacts.collect(clone)
    assert not marker.exists()


@pytest.mark.parametrize(
    ("url", "named"), [("https:///a/b.git", "(no host)"), ("file:///srv/b.git", "(a local path)")]
)
def test_a_remote_url_without_a_host_is_named_so(
    clone: Path, bin_dir: Path, url: str, named: str
) -> None:
    fake_gh(bin_dir, "", exit_code=1, stderr="must not be called")  # found by proc.program
    git(clone, "remote", "set-url", "origin", url)
    reason = gitfacts._forge_unknown(clone, "origin")
    assert reason is not None and named in reason


# --- a branch cut from main tracks main (tsk-8qwmbw5xydpw) -----------------------------------


def _track_main(clone: Path, set_head: bool) -> None:
    """`work` as `git switch -c work origin/main` leaves it: its upstream is origin's main.
    With `set_head` the clone knows origin's default branch (`origin/HEAD`, as a clone of a
    repository with commits sets it); without, only the remote's HEAD says it."""
    git(clone, "push", "--quiet", "origin", "work:main")
    git(clone, "fetch", "--quiet", "origin")
    if set_head:
        git(clone, "remote", "set-head", "origin", "main")
    elif git(clone, "for-each-ref", "refs/remotes/origin/HEAD"):
        git(clone, "remote", "set-head", "origin", "--delete")  # a fetch of git 2.48+ sets it
    git(clone, "config", "branch.work.merge", "refs/heads/main")


@pytest.mark.parametrize("set_head", [True, False], ids=["origin-HEAD", "ls-remote"])
def test_a_branch_tracking_main_is_set_to_track_its_own_branch(clone: Path, set_head: bool) -> None:
    _track_main(clone, set_head)
    (clone / "a.txt").write_text("two\n")
    git(clone, "commit", "--quiet", "-am", "two")
    git(clone, "push", "--quiet", "origin", "work")  # pushed without -u: still tracks main
    assert git(clone, "config", "branch.work.merge") == "refs/heads/main"
    done = gitfacts.track_own_branch(clone)
    assert done.problem is None
    assert done.note == (
        "branch work tracked origin/main, the default branch; set branch.work.merge to "
        "refs/heads/work, its own branch on origin"
    )
    assert git(clone, "config", "branch.work.merge") == "refs/heads/work"
    assert git(clone, "config", "branch.work.remote") == "origin"
    facts = gitfacts.collect(clone)
    assert facts.remote_branch == "work" and facts.remote_head == facts.head
    assert gitfacts.mismatches(facts) == []


def test_a_branch_tracking_main_that_is_not_pushed_is_left_and_named(clone: Path) -> None:
    _track_main(clone, set_head=True)
    git(clone, "push", "--quiet", "origin", "--delete", "work")
    done = gitfacts.track_own_branch(clone)
    assert done.note is None
    assert done.problem == (
        "branch work tracks origin/main, the default branch, and origin has no branch work; "
        "push it with `git push -u origin work`"
    )
    assert git(clone, "config", "branch.work.merge") == "refs/heads/main"


def test_an_upstream_other_than_the_default_branch_is_left_as_it_is(clone: Path) -> None:
    """A stacked branch that tracks the branch below it, say: not main, not touched."""
    _track_main(clone, set_head=True)
    git(clone, "push", "--quiet", "origin", "work:base")
    git(clone, "config", "branch.work.merge", "refs/heads/base")
    assert gitfacts.track_own_branch(clone) == gitfacts.Retrack()
    assert git(clone, "config", "branch.work.merge") == "refs/heads/base"


def test_the_default_branch_itself_and_its_own_upstream_are_left(clone: Path) -> None:
    _track_main(clone, set_head=True)
    git(clone, "switch", "--quiet", "-c", "main", "--track", "origin/main")
    assert gitfacts.track_own_branch(clone) == gitfacts.Retrack()
    assert git(clone, "config", "branch.main.merge") == "refs/heads/main"
    git(clone, "switch", "--quiet", "work")
    git(clone, "config", "branch.work.merge", "refs/heads/work")
    assert gitfacts.track_own_branch(clone) == gitfacts.Retrack()


def test_a_tag_named_like_the_branch_does_not_change_whose_key_is_set(clone: Path) -> None:
    """`symbolic-ref --short` gives `heads/work` next to a tag `work`; the key is still work's."""
    _track_main(clone, set_head=True)
    git(clone, "tag", "work")
    git(clone, "update-ref", "refs/heads/heads/work", "HEAD")  # `git branch` refuses the name
    git(clone, "config", "branch.heads/work.remote", "origin")
    git(clone, "config", "branch.heads/work.merge", "refs/heads/main")
    git(clone, "push", "--quiet", "origin", "refs/heads/heads/work:refs/heads/heads/work")
    assert git(clone, "symbolic-ref", "--quiet", "--short", "HEAD") == "heads/work"
    done = gitfacts.track_own_branch(clone)
    assert done.problem is None and done.note is not None and "branch.work.merge" in done.note
    assert git(clone, "config", "branch.work.merge") == "refs/heads/work"
    assert git(clone, "config", "branch.heads/work.merge") == "refs/heads/main"
    assert gitfacts.collect(clone).branch == "work"


def test_a_remote_branch_whose_name_only_ends_in_the_branch_is_not_the_branch(
    clone: Path,
) -> None:
    """`ls-remote` takes `refs/heads/work` as a suffix and also lists
    `refs/heads/x/refs/heads/work`; that branch is not work, for the retrack or the facts."""
    _track_main(clone, set_head=True)
    git(clone, "push", "--quiet", "origin", "work:refs/heads/x/refs/heads/work")
    git(clone, "push", "--quiet", "origin", "--delete", "work")
    assert git(clone, "ls-remote", "--heads", "--", "origin", "refs/heads/work")  # the suffix
    done = gitfacts.track_own_branch(clone)
    assert done.note is None and done.problem is not None and "has no branch work" in done.problem
    assert git(clone, "config", "branch.work.merge") == "refs/heads/main"
    git(clone, "config", "branch.work.merge", "refs/heads/work")
    facts = gitfacts.collect(clone)
    assert facts.remote_branch == "work" and facts.remote_head is None
    assert any("does not exist" in p for p in gitfacts.mismatches(facts))


def _recording(
    calls: list[tuple[str, ...]], real: Callable[..., str | None]
) -> Callable[..., str | None]:
    """`real` (gitfacts' `_git` or `_git_required`), noting each call's arguments in `calls`."""

    def record(cwd: Path, *args: str) -> str | None:
        calls.append(args)
        return real(cwd, *args)

    return record


@posix
@pytest.mark.parametrize("set_head", [True, False], ids=["origin-HEAD", "ls-remote"])
def test_the_upstream_is_checked_before_the_retrack_asks_the_remote(
    clone: Path, monkeypatch: pytest.MonkeyPatch, set_head: bool
) -> None:
    """A second URL naming a helper: `ls-remote` would use the first, valid one and the retrack
    would go through; the check refuses before any question to the remote, nothing is set.
    Every git call is recorded: a refusal raised only after an `ls-remote` (the default branch's
    without origin/HEAD, the own branch's with it) fails here, not only one that never comes."""
    _track_main(clone, set_head=set_head)
    marker = clone.parent / "ran"
    helper = "ext::{sh} -c {touch}% {marker}".format(marker=marker, **TOOLS)
    git(clone, "config", "--add", "remote.origin.url", helper)
    before = git(clone, "config", "--list", "--local")
    calls: list[tuple[str, ...]] = []
    for name in ("_git", "_git_required"):
        monkeypatch.setattr(gitfacts, name, _recording(calls, getattr(gitfacts, name)))
    with pytest.raises(gitfacts.FactsError, match="upstream"):
        gitfacts.track_own_branch(clone)
    assert ("config", "--get-all", "remote.origin.url") in calls  # the recorder saw the check
    assert not [c for c in calls if c[0] in ("ls-remote", "fetch", "remote")], calls
    assert git(clone, "config", "--list", "--local") == before
    assert git(clone, "config", "branch.work.merge") == "refs/heads/main"
    assert not marker.exists()
