"""Clearing a Claude Code subagent's leftover worktree from a placement's clone.

A subagent's worktree-isolation leaves a git worktree at `.claude/worktrees/agent-<id>` inside
the clone; `.git/worktrees` is then not empty and the clone reads as unsupported, so `maity
report` and the next start refuse. The one path that clears such a leftover is the supervisor's
git-free prune on every placement (re)start; there is no in-session remover. The prune touches
only worktrees under this clone's own `.claude/worktrees/`, follows no symlink at any level, and
leaves a worktree pointing elsewhere. The clone check stays strict: a present worktree is still
refused, and its refusal tells the operator a restart clears a subagent's leftover.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import pytest
from conftest import git

from maity import clonecheck
from maity.runner import commands, worktree

pytestmark = pytest.mark.skipif(
    not worktree.supported(), reason="no descriptor-relative, no-follow paths here"
)


@pytest.fixture
def placed(clone: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`clone` as the runner leaves a session: a plain clone, with `MAITY_PLACEMENT`,
    `GIT_COMMON_DIR`, the recorded `.git` inode and the recorded git set the way the runner
    sets them (test_clonecheck's `placed`). The refusal-hint tests run `placement_git` here."""
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


def _lists(result: dict[str, object]) -> tuple[list[str], list[str]]:
    """`prune_orphans`'s `removed` and `left`, narrowed to lists for the assertions."""
    removed, left = result["removed"], result["left"]
    assert isinstance(removed, list) and isinstance(left, list)
    return removed, left


# --- the start-prune: the only path that clears a leftover ------------------------------------


def test_prune_orphans_clears_a_registered_and_an_orphan_leftover(placed: Path) -> None:
    """The supervisor's hygiene run (no git): a registered worktree and a bare leftover
    directory under `.claude/worktrees/` both go, and the clone reads plain again."""
    _worktree(placed, "agent-registered")
    (placed / ".claude" / "worktrees" / "orphan").mkdir()  # a dir with no admin entry
    assert clonecheck.not_inspectable(placed) is not None  # unsupported while the worktree is here
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


def test_prune_orphans_leaves_a_worktree_pointing_elsewhere(clone: Path) -> None:
    """A planted redirect out of the clone is not a subagent's leftover: prune never forgets or
    follows it, so the clone stays unsupported until a person looks at it."""
    admin = clone / ".git" / "worktrees" / "elsewhere"
    admin.mkdir(parents=True)
    (admin / "gitdir").write_text("/somewhere/else/.git\n")
    result = worktree.prune_orphans(str(clone))
    assert result == {"result": "pruned", "removed": [], "left": [".git/worktrees/elsewhere"]}
    assert (admin / "gitdir").read_text() == "/somewhere/else/.git\n"  # untouched
    assert clonecheck.not_inspectable(clone) is not None  # still unsupported


def test_prune_orphans_leaves_a_symlink_under_claude_worktrees_and_never_its_target(
    clone: Path,
) -> None:
    """A link directly under `.claude/worktrees/` is not a directory the prune made: it is left
    (opened without following a link), and its target is never entered or removed."""
    victim = clone.parent / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("not the prune's to touch\n")
    (clone / ".claude" / "worktrees").mkdir(parents=True)
    (clone / ".claude" / "worktrees" / "evil").symlink_to(victim)
    removed, left = _lists(worktree.prune_orphans(str(clone)))
    assert removed == []
    assert ".claude/worktrees/evil" in left
    assert (clone / ".claude" / "worktrees" / "evil").is_symlink()  # the link is left for a person
    assert (victim / "keep.txt").exists()  # the target is never followed


def test_prune_orphans_touches_nothing_outside_claude_worktrees(clone: Path) -> None:
    """Removing a leftover worktree follows no link on the way down, so a link planted inside it
    pointing at a victim outside `.claude/worktrees/` is removed as the link, never entered: the
    victim's contents survive."""
    victim = clone.parent / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("outside the scope\n")
    leftover = clone / ".claude" / "worktrees" / "agent-x"
    leftover.mkdir(parents=True)
    (leftover / "inside").symlink_to(victim)  # a link out of scope, planted inside the leftover
    removed, _ = _lists(worktree.prune_orphans(str(clone)))
    assert ".claude/worktrees/agent-x" in removed
    assert not leftover.exists()
    assert (victim / "keep.txt").exists()  # the link was not followed, the victim untouched
    assert victim.is_dir()


def test_prune_orphans_blocked_by_a_symlinked_claude_leaves_the_registration(clone: Path) -> None:
    """`.claude` (or `.claude/worktrees`) reached through a link is not opened: the prune clears
    nothing and the registration stays, so the clone stays unsupported until a person looks at
    it — a planted redirect does not pass the clone check by way of the prune."""
    elsewhere = clone.parent / "elsewhere"
    (elsewhere / "worktrees" / "agent-x").mkdir(parents=True)
    (clone / ".claude").symlink_to(elsewhere)  # .claude is a link, not a real directory
    admin = clone / ".git" / "worktrees" / "agent-x"
    admin.mkdir(parents=True)
    (admin / "gitdir").write_text(f"{clone / '.claude' / 'worktrees' / 'agent-x' / '.git'}\n")
    removed, left = _lists(worktree.prune_orphans(str(clone)))
    assert removed == []
    assert ".git/worktrees/agent-x" in left
    assert admin.exists()
    assert clonecheck.not_inspectable(clone) is not None  # still unsupported


@pytest.mark.parametrize(
    "gitdir",
    [
        "{root}/.claude/worktrees/../.git\n",  # a `..` segment
        "{root}/.claude/worktrees/agent-x/evil\n",  # the basename is not `.git`
        "{root}/.claude/worktrees/agent-x/.git\nextra\n",  # a second line
        "relative/.git\n",  # not absolute
    ],
)
def test_prune_orphans_refuses_a_malformed_gitdir(clone: Path, gitdir: str) -> None:
    """A `gitdir` with a `..` segment, a basename that is not `.git`, a second line, or a
    relative path is refused: the registration is left, never acted on."""
    (clone / ".claude" / "worktrees").mkdir(parents=True)
    admin = clone / ".git" / "worktrees" / "agent-x"
    admin.mkdir(parents=True)
    (admin / "gitdir").write_text(gitdir.format(root=clone))
    removed, _ = _lists(worktree.prune_orphans(str(clone)))
    assert ".git/worktrees/agent-x" not in removed
    assert admin.exists()


def test_prune_orphans_does_not_report_a_symlinked_admin_as_removed(clone: Path) -> None:
    """A `.git/worktrees/<name>` that is itself a link is not removed (opened without following a
    link) and so is not reported as removed."""
    (clone / ".claude" / "worktrees" / "agent-x").mkdir(parents=True)
    target = clone.parent / "admintarget"
    target.mkdir()
    (target / "gitdir").write_text(f"{clone / '.claude' / 'worktrees' / 'agent-x' / '.git'}\n")
    (clone / ".git" / "worktrees").mkdir(parents=True)
    os.symlink(target, clone / ".git" / "worktrees" / "agent-x")  # the admin entry is a link
    removed, left = _lists(worktree.prune_orphans(str(clone)))
    assert ".git/worktrees/agent-x" not in removed
    assert ".git/worktrees/agent-x" in left
    assert (clone / ".git" / "worktrees" / "agent-x").is_symlink()  # left, not removed


def test_prune_orphans_refuses_a_fifo_gitdir_without_hanging(clone: Path) -> None:
    """A `gitdir` that is a FIFO (which a naive blocking read would wait on) is opened non-blocking
    and refused as not a regular file: the prune returns promptly and removes nothing."""
    (clone / ".claude" / "worktrees").mkdir(parents=True)
    admin = clone / ".git" / "worktrees" / "agent-x"
    admin.mkdir(parents=True)
    os.mkfifo(admin / "gitdir")
    removed, _ = _lists(worktree.prune_orphans(str(clone)))  # must not hang
    assert ".git/worktrees/agent-x" not in removed
    assert admin.exists()


def test_prune_orphans_clears_a_stale_registration_without_a_working_tree(placed: Path) -> None:
    """A `.git/worktrees/<name>` left without its `.claude/worktrees/` working tree is a dangling
    registration: the prune clears it so the clone reads plain again."""
    admin = placed / ".git" / "worktrees" / "agent-x"
    admin.mkdir(parents=True)
    (admin / "gitdir").write_text(f"{placed / '.claude' / 'worktrees' / 'agent-x' / '.git'}\n")
    assert clonecheck.not_inspectable(placed) is not None
    removed, _ = _lists(worktree.prune_orphans(str(placed)))
    assert ".git/worktrees/agent-x" in removed
    assert not admin.exists()
    assert clonecheck.not_inspectable(placed) is None


# --- the refusal hint: a restart clears a `.claude/worktrees/` leftover, named only for one ----


def test_the_refusal_hint_names_a_restart_for_a_claude_worktree(placed: Path) -> None:
    _worktree(placed, "agent-x")
    with pytest.raises(clonecheck.Refused) as exc:
        with clonecheck.placement_git(placed):
            pass
    message = str(exc.value)
    assert "restart" in message.lower() and ".claude/worktrees/" in message
    assert "--force" not in message and "worktree-clean" not in message  # no op, no force


def test_a_worktree_elsewhere_gets_no_restart_hint(placed: Path) -> None:
    """The hint is for a `.claude/worktrees/` leftover only; a worktree pointing elsewhere is
    genuinely unsupported and names no way out."""
    git(placed, "worktree", "add", "--quiet", str(placed.parent / "outside-wt"))
    with pytest.raises(clonecheck.Refused) as exc:
        with clonecheck.placement_git(placed):
            pass
    assert "restart" not in str(exc.value).lower()


# --- the supervisor's internal CLI surface (no agent-callable op) ------------------------------


def test_worktree_prune_cli_is_refused_for_a_placed_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`maity runner worktree-prune` is the runner's placement-start hygiene, not a placed
    agent's to call: a placed session cannot redirect it at a path of its own."""
    monkeypatch.setenv(clonecheck.PLACEMENT_ENV, "plc-0003")
    with pytest.raises(commands.Refused):
        commands.cmd_worktree_prune(argparse.Namespace(repo="/some/clone"))


def test_worktree_prune_cli_needs_a_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(clonecheck.PLACEMENT_ENV, raising=False)
    with pytest.raises(commands.Refused):
        commands.cmd_worktree_prune(argparse.Namespace(repo=None))
