"""Clearing a Claude Code subagent's leftover worktree from a placement's clone.

A subagent's worktree-isolation leaves a git worktree at `.claude/worktrees/agent-<id>` inside
the clone; `.git/worktrees` is then not empty and the clone reads as unsupported, so `maity
report` and the next start refuse. The agent clears it with `maity runner worktree-clean`; the
supervisor clears a leftover on start. Both touch only worktrees under this clone's own
`.claude/worktrees/`, and never one that has uncommitted changes without `--force`.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from conftest import git

from maity import clonecheck, gitfacts
from maity.runner import worktree

pytestmark = pytest.mark.skipif(
    not worktree.supported(), reason="no descriptor-relative, no-follow paths here"
)


@pytest.fixture
def placed(clone: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`clone` as the runner leaves a session: a plain clone, with `MAITY_PLACEMENT`,
    `GIT_COMMON_DIR`, the recorded `.git` inode and the recorded git set the way the runner
    sets them (test_clonecheck's `placed`)."""
    remote = clone.parent / "remote.git"
    git(clone, "config", "--remove-section", f"url.{remote}")
    git(clone, "remote", "set-url", "origin", str(remote))
    (clone / ".git" / "maity").mkdir(exist_ok=True)
    monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    monkeypatch.setenv("GIT_COMMON_DIR", str(clone / ".git"))
    monkeypatch.setenv(clonecheck.GIT_INODE_ENV, str(os.lstat(clone / ".git").st_ino))
    private = clone.parent / "agent-dir" / "git"
    private.mkdir(parents=True)
    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, str(private))
    (private / "git").write_text(f"{shutil.which('git')}\n")
    return clone


def _worktree(root: Path, name: str) -> Path:
    """A subagent's worktree under `<root>/.claude/worktrees/<name>`."""
    (root / ".claude" / "worktrees").mkdir(parents=True, exist_ok=True)
    git(root, "worktree", "add", "--quiet", f".claude/worktrees/{name}")
    return root / ".claude" / "worktrees" / name


def test_clears_a_harness_worktree_and_the_clone_reads_plain(placed: Path) -> None:
    _worktree(placed, "agent-x")
    assert clonecheck.not_inspectable(placed) == ".git/worktrees is not a plain clone's"
    with clonecheck.worktree_git(placed) as pinned:
        result = worktree.clean(placed, pinned, force=False)
    removed = result["removed"]
    assert result["result"] == "cleared" and isinstance(removed, list) and len(removed) == 1
    # The clone check passes again, so `maity report`'s git runs where it refused before.
    assert clonecheck.not_inspectable(placed) is None
    assert gitfacts.collect(placed).head
    # A second run finds nothing to do and does not fail.
    with clonecheck.worktree_git(placed) as pinned:
        assert worktree.clean(placed, pinned, force=False) == {"result": "clean", "removed": []}


def test_refuses_a_worktree_whose_working_tree_is_outside_claude_worktrees(placed: Path) -> None:
    git(placed, "worktree", "add", "--quiet", str(placed.parent / "outside-wt"))
    with clonecheck.worktree_git(placed) as pinned:
        with pytest.raises(worktree.Refused) as exc:
            worktree.clean(placed, pinned, force=True)  # --force does not reach it either
    assert "does not resolve under .claude/worktrees/" in str(exc.value)
    assert clonecheck.not_inspectable(placed) is not None  # nothing removed; still unsupported
    assert (placed.parent / "outside-wt" / "a.txt").exists()  # the worktree is untouched


def test_refuses_a_worktree_reached_through_a_symlink(placed: Path) -> None:
    """A registered worktree lexically under `.claude/worktrees/` but reached through a symlink
    at `.claude` is left: the op opens each level without following a link."""
    elsewhere = placed.parent / "elsewhere"
    (elsewhere / "worktrees" / "agent-x").mkdir(parents=True)
    (placed / ".claude").symlink_to(elsewhere)  # .claude is a link, not a real directory
    admin = placed / ".git" / "worktrees" / "agent-x"
    admin.mkdir(parents=True)
    (admin / "gitdir").write_text(f"{placed / '.claude' / 'worktrees' / 'agent-x' / '.git'}\n")
    with clonecheck.worktree_git(placed) as pinned:
        with pytest.raises(worktree.Refused) as exc:
            worktree.clean(placed, pinned, force=True)
    assert "does not resolve under .claude/worktrees/" in str(exc.value)
    assert (elsewhere / "worktrees" / "agent-x").is_dir()  # left where it is


def test_refuses_uncommitted_changes_and_succeeds_with_force(placed: Path) -> None:
    working = _worktree(placed, "agent-x")
    (working / "wip.txt").write_text("unmerged work\n")  # untracked: uncommitted
    with clonecheck.worktree_git(placed) as pinned:
        with pytest.raises(worktree.Refused) as exc:
            worktree.clean(placed, pinned, force=False)
    assert "--force" in str(exc.value) and "uncommitted changes" in str(exc.value)
    assert clonecheck.not_inspectable(placed) is not None  # the work is kept, clone unsupported
    assert working.exists()
    with clonecheck.worktree_git(placed) as pinned:
        assert worktree.clean(placed, pinned, force=True)["result"] == "cleared"
    assert clonecheck.not_inspectable(placed) is None


def test_the_refusal_hint_names_the_cleanup_op_for_a_claude_worktree(placed: Path) -> None:
    _worktree(placed, "agent-x")
    with pytest.raises(clonecheck.Refused) as exc:
        with clonecheck.placement_git(placed):
            pass
    message = str(exc.value)
    assert clonecheck.WORKTREE_CLEAN_OP in message and "--force" in message


def test_a_worktree_elsewhere_gets_no_cleanup_hint(placed: Path) -> None:
    """The hint is for a `.claude/worktrees/` leftover only; a worktree pointing elsewhere is
    genuinely unsupported and names no way out."""
    git(placed, "worktree", "add", "--quiet", str(placed.parent / "outside-wt"))
    with pytest.raises(clonecheck.Refused) as exc:
        with clonecheck.placement_git(placed):
            pass
    assert clonecheck.WORKTREE_CLEAN_OP not in str(exc.value)


def test_prune_orphans_clears_a_registered_and_an_orphan_leftover(placed: Path) -> None:
    """The supervisor's hygiene run (no git): a registered worktree and a bare leftover
    directory under `.claude/worktrees/` both go, and the clone reads plain again."""
    _worktree(placed, "agent-registered")
    (placed / ".claude" / "worktrees" / "orphan").mkdir()  # a dir with no admin entry
    result = worktree.prune_orphans(str(placed))
    removed = result["removed"]
    assert result["result"] == "pruned" and isinstance(removed, list)
    assert sorted(removed) == [
        ".claude/worktrees/agent-registered",
        ".claude/worktrees/orphan",
        ".git/worktrees/agent-registered",
    ]
    assert clonecheck.not_inspectable(placed) is None
    assert not (placed / ".claude" / "worktrees" / "agent-registered").exists()


def test_prune_orphans_leaves_a_worktree_pointing_elsewhere(placed: Path) -> None:
    """A planted redirect out of the clone is not a subagent's leftover: prune never forgets or
    follows it, so the clone stays unsupported until a person looks at it."""
    admin = placed / ".git" / "worktrees" / "elsewhere"
    admin.mkdir(parents=True)
    (admin / "gitdir").write_text("/somewhere/else/.git\n")
    result = worktree.prune_orphans(str(placed))
    assert result == {"result": "pruned", "removed": [], "left": [".git/worktrees/elsewhere"]}
    assert (admin / "gitdir").read_text() == "/somewhere/else/.git\n"  # untouched
    assert clonecheck.not_inspectable(placed) is not None  # still unsupported
