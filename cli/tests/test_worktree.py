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
    monkeypatch.setenv(clonecheck.GIT_DEVICE_ENV, str(os.lstat(clone / ".git").st_dev))
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
        pytest.param("{root}/.claude/worktrees/../.git\n", id="dotdot-segment"),
        pytest.param("{root}/./.claude/worktrees/agent-x/.git\n", id="dot-segment"),
        pytest.param("{root}/.claude/worktrees/agent-x/evil\n", id="basename-not-git"),
        pytest.param("{root}/.claude/worktrees/agent-x/.git\nextra\n", id="second-line"),
        pytest.param("relative/.git\n", id="not-absolute"),
        pytest.param(
            "{root}/.claude/worktrees/agent-x/.git" + " " * 5000 + "\n", id="over-size-bound"
        ),
        pytest.param("{root}/.claude/worktrees/agent-x/.git\x00\n", id="embedded-nul"),
    ],
)
def test_prune_orphans_refuses_a_malformed_gitdir(clone: Path, gitdir: str) -> None:
    """Each gitdir guard is pinned as the one that refuses: a real `.claude/worktrees/agent-x`
    child is present, so were a guard dropped the admin entry would be cleared. A `.` or `..`
    segment (checked on the raw string, before a Path folds `.` away), a basename that is not
    `.git`, a second line, a relative path, an over-size-bound path, or an embedded NUL each
    leaves the registration, never acts on it."""
    (clone / ".claude" / "worktrees" / "agent-x").mkdir(parents=True)  # a real child: only a
    admin = clone / ".git" / "worktrees" / "agent-x"  # gitdir guard can refuse now
    admin.mkdir(parents=True)
    (admin / "gitdir").write_text(gitdir.format(root=clone))
    removed, _ = _lists(worktree.prune_orphans(str(clone)))
    assert ".git/worktrees/agent-x" not in removed
    assert admin.exists()


def test_prune_orphans_refuses_a_symlinked_gitdir(clone: Path) -> None:
    """The `gitdir` file is opened without following a link: a `gitdir` that is a symlink to a
    file naming this clone's own worktree is refused, not followed — the registration is left even
    though a real `.claude/worktrees/agent-x` child is present (pins the gitdir open's
    O_NOFOLLOW)."""
    (clone / ".claude" / "worktrees" / "agent-x").mkdir(parents=True)
    admin = clone / ".git" / "worktrees" / "agent-x"
    admin.mkdir(parents=True)
    target = clone.parent / "gitdir-target"
    target.write_text(f"{clone / '.claude' / 'worktrees' / 'agent-x' / '.git'}\n")
    (admin / "gitdir").symlink_to(target)  # the gitdir file is a link
    removed, _ = _lists(worktree.prune_orphans(str(clone)))
    assert ".git/worktrees/agent-x" not in removed
    assert admin.exists()


def test_prune_orphans_does_not_read_or_remove_through_a_symlinked_admin_dir(clone: Path) -> None:
    """`.git/worktrees` reached without following a link (pins `_descend`'s O_NOFOLLOW): when it is
    a symlink to a directory of registrations, the prune neither reads nor removes through it, so
    the external registration is left exactly where it is."""
    (clone / ".claude" / "worktrees" / "agent-x").mkdir(parents=True)
    external = clone.parent / "external-worktrees"
    (external / "agent-x").mkdir(parents=True)
    (external / "agent-x" / "gitdir").write_text(
        f"{clone / '.claude' / 'worktrees' / 'agent-x' / '.git'}\n"
    )
    (clone / ".git").mkdir(parents=True, exist_ok=True)
    (clone / ".git" / "worktrees").symlink_to(external)  # the admin dir itself is a link
    removed, _ = _lists(worktree.prune_orphans(str(clone)))
    assert ".git/worktrees/agent-x" not in removed
    assert (external / "agent-x").exists()  # never removed through the link


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


@pytest.mark.parametrize("sibling", [None, "agent-other"])
def test_prune_orphans_clears_a_dangling_registration_with_the_scope_present(
    placed: Path, sibling: str | None
) -> None:
    """`.claude/worktrees/` is present — empty, or holding another worktree — but the
    registration's own `<id>` working tree is gone: a dangling registration with no working tree
    to lose. The prune clears it rather than leaving the clone stuck, and it reads plain again."""
    (placed / ".claude" / "worktrees").mkdir(parents=True)
    if sibling is not None:
        _worktree(placed, sibling)  # another valid worktree keeps the scope non-empty
    admin = placed / ".git" / "worktrees" / "agent-x"  # its `<id>` working tree is absent
    admin.mkdir(parents=True)
    (admin / "gitdir").write_text(f"{placed / '.claude' / 'worktrees' / 'agent-x' / '.git'}\n")
    assert clonecheck.not_inspectable(placed) is not None
    removed, _ = _lists(worktree.prune_orphans(str(placed)))
    assert ".git/worktrees/agent-x" in removed
    assert not admin.exists()
    assert clonecheck.not_inspectable(placed) is None


@pytest.mark.parametrize("child", ["symlink", "file"])
def test_prune_orphans_leaves_a_registration_whose_child_is_not_a_plain_dir(
    clone: Path, child: str
) -> None:
    """With the scope present, a registered `<id>` that is a link or a non-directory (not a real
    directory, and not simply gone) is left untouched: the prune never follows it or clears the
    registration, so a planted child cannot pass the clone check by way of the prune."""
    (clone / ".claude" / "worktrees").mkdir(parents=True)
    child_path = clone / ".claude" / "worktrees" / "agent-x"
    if child == "symlink":
        victim = clone.parent / "victim"
        victim.mkdir()
        (victim / "keep.txt").write_text("not the prune's to touch\n")
        child_path.symlink_to(victim)
    else:
        child_path.write_text("not a directory\n")  # ENOTDIR when opened as a directory
    admin = clone / ".git" / "worktrees" / "agent-x"
    admin.mkdir(parents=True)
    (admin / "gitdir").write_text(f"{clone / '.claude' / 'worktrees' / 'agent-x' / '.git'}\n")
    removed, left = _lists(worktree.prune_orphans(str(clone)))
    assert ".git/worktrees/agent-x" not in removed
    assert ".git/worktrees/agent-x" in left
    assert admin.exists()
    if child == "symlink":
        assert (clone.parent / "victim" / "keep.txt").exists()  # the link was never followed


# --- the refusal hint: a restart clears a `.claude/worktrees/` leftover, named only for one ----


def test_the_refusal_hint_names_a_restart_for_a_claude_worktree(placed: Path) -> None:
    _worktree(placed, "agent-x")
    with pytest.raises(clonecheck.Refused) as exc:
        with clonecheck.placement_git(placed):
            pass
    message = str(exc.value)
    assert "stop and start the placement" in message and ".claude/worktrees/" in message
    assert "next start" in message and "uncommitted work" in message
    assert "--force" not in message and "worktree-clean" not in message  # no op, no force


def test_a_worktree_elsewhere_gets_no_restart_hint(placed: Path) -> None:
    """The hint is for a `.claude/worktrees/` leftover only; a worktree pointing elsewhere is
    genuinely unsupported and names no way out."""
    git(placed, "worktree", "add", "--quiet", str(placed.parent / "outside-wt"))
    with pytest.raises(clonecheck.Refused) as exc:
        with clonecheck.placement_git(placed):
            pass
    assert "stop and start" not in str(exc.value)


def test_another_feature_beside_a_claude_worktree_gets_no_restart_hint(placed: Path) -> None:
    """The restart hint belongs to the worktrees refusal itself. When the real blocker is another
    unsupported feature (a submodule), a `.claude/worktrees/` registration beside it does not earn
    a hint that a restart clears the block — the submodule, not the leftover, is what refuses."""
    _worktree(placed, "agent-x")  # a real leftover a restart's prune could clear on its own
    (placed / ".git" / "modules" / "sub").mkdir(parents=True)  # but a submodule is the blocker
    with pytest.raises(clonecheck.Refused) as exc:
        with clonecheck.placement_git(placed):
            pass
    message = str(exc.value)
    assert "Submodules are" in message  # the refusal is for the submodule
    assert "stop and start" not in message  # and names no false way out


def test_a_blocked_scope_gets_no_restart_hint(placed: Path) -> None:
    """When `.claude` is reached through a link, the placement-start prune clears nothing — so the
    worktrees refusal names no restart, which would not return the clone to a plain state."""
    (placed / ".claude").symlink_to(placed.parent / "nowhere")  # the scope is behind a link
    admin = placed / ".git" / "worktrees" / "agent-x"
    admin.mkdir(parents=True)
    (admin / "gitdir").write_text(f"{placed / '.claude' / 'worktrees' / 'agent-x' / '.git'}\n")
    with pytest.raises(clonecheck.Refused) as exc:
        with clonecheck.placement_git(placed):
            pass
    message = str(exc.value)
    assert "Worktrees are" in message  # still the worktrees refusal
    assert "stop and start" not in message  # but no misleading way out


# --- the supervisor's internal CLI surface (no agent-callable op) ------------------------------


@pytest.mark.parametrize("value", ["", " ", "plc-0003", "plc-0003\n", "PLC-0003", "../plc-0003"])
def test_worktree_prune_cli_is_refused_for_a_placed_agent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    """`maity runner worktree-prune` is the runner's placement-start hygiene, not a placed
    agent's to call: a placed session cannot redirect it at a path of its own. The refusal is
    cli.main's gate (worktree-prune is not in IN_SESSION), for any value of MAITY_PLACEMENT,
    empty included, before the handler runs."""
    from maity import cli

    assert "worktree-prune" not in commands.IN_SESSION
    pruned: list[str] = []

    def prune(repo: str) -> list[str]:
        pruned.append(repo)
        return []

    monkeypatch.setattr(worktree, "prune_orphans", prune)
    monkeypatch.setenv(clonecheck.PLACEMENT_ENV, value)
    assert cli.main(["runner", "worktree-prune", "--repo", "/some/clone"]) == cli.EXIT_REFUSED
    assert "does not run for a placed agent" in capsys.readouterr().err
    assert pruned == []


def test_worktree_prune_cli_needs_a_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(clonecheck.PLACEMENT_ENV, raising=False)
    with pytest.raises(commands.Refused):
        commands.cmd_worktree_prune(argparse.Namespace(repo=None))
