"""`maity gh`: a placed agent's pull requests on its own clone's repository, nothing else.

One test per way around the pin that the review of #1663 named or the design ruled out:
bundled flags, another repository by option, URL or environment, a body file outside the
clone (a link, `..`, `.git`, the login file), gh's other file options, and a forged record
(cli/context/runner.md 9f43804d).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from maity import cli, clonecheck, ghpr

REPOSITORY = "github.com/oliver-zehentleitner/maity"
BRANCH = "agent-g/the-change"
# What gh must not see from maity's environment: another repository, host, configuration or
# login, or a program to start (ghpr.ENV_PASSED is what it does see).
DROPPED = (
    "GH_REPO", "GH_HOST", "GH_CONFIG_DIR", "XDG_CONFIG_HOME", "GH_TOKEN", "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_PAGER", "PAGER", "GH_BROWSER",
    "BROWSER", "GH_EDITOR", "EDITOR", "VISUAL", "GH_FORCE_TTY", "GH_DEBUG",
)  # fmt: skip
# The tests that start gh: a Python script with a shebang stands in for it, which Windows
# does not run (a real gh there is an .exe). Every refusal comes before gh starts and runs
# everywhere.
runs_gh = pytest.mark.skipif(
    os.name == "nt",
    reason="the stand-in for gh is a shebang script, which Windows cannot start;"
    " a real gh there is an .exe",
)
# The tests that read a body file: maity walks to it through descriptors (`dir_fd`,
# O_NOFOLLOW), which Windows lacks, so there it refuses `--body-file` (tested below).
walks = pytest.mark.skipif(
    not ghpr.WALKS,
    reason="no dir_fd or O_NOFOLLOW here, so maity refuses every --body-file",
)


@pytest.fixture
def placed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A runner's clone with a pull-request record and a gh that writes down how it ran."""
    clone = tmp_path / "ws" / "maity" / "agent-3"
    clone.mkdir(parents=True)
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "-q", "-b", BRANCH, str(clone)], check=True)
    (clone / ".git" / "maity").mkdir()
    (clone / clonecheck.GIT_PATH).write_text(git + "\n")
    log = tmp_path / "gh.json"
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'cwd': os.getcwd(),"
        f" 'env': {{k: os.environ.get(k) for k in {[*DROPPED, 'PATH', 'GH_PROMPT_DISABLED']!r}}}}},"
        f" open({str(log)!r}, 'w'))\n"
    )
    gh.chmod(0o755)
    (clone / ghpr.PULL_REQUESTS_PATH).write_text(f"{REPOSITORY}\n{gh}\n")
    monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    monkeypatch.setenv("GIT_COMMON_DIR", str(clone / ".git"))
    # As the runner starts a session (#1683): the .git it recorded, git's own directory.
    monkeypatch.setenv(clonecheck.GIT_INODE_ENV, str(os.lstat(clone / ".git").st_ino))
    private = tmp_path / "agent" / "git"
    private.mkdir(parents=True)
    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, str(private))
    monkeypatch.chdir(clone)
    return {"clone": clone, "log": log, "gh": str(gh)}


def ran(placed: dict[str, Any]) -> dict[str, Any] | None:
    log: Path = placed["log"]
    return json.loads(log.read_text()) if log.exists() else None


def refused(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    code: int | str | None
    try:
        code = cli.main(argv)
    except SystemExit as exc:  # argparse's own refusal of an option or command it lacks
        code = exc.code
    assert code in (cli.EXIT_USAGE, cli.EXIT_REFUSED), code
    return capsys.readouterr().err


@runs_gh
def test_create_runs_gh_on_the_recorded_repository_with_the_body_on_stdin(
    placed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in DROPPED:
        monkeypatch.setenv(name, "set-by-the-session")
    (placed["clone"] / "body.md").write_text("Card tsk-x\n")
    assert cli.main(["gh", "pr", "create", "--title", "-R x", "--body-file", "body.md",
                     "--base", "main", "--draft"]) == 0  # fmt: skip
    call = ran(placed)
    assert call is not None
    assert call["argv"] == ["pr", "create", f"--repo={REPOSITORY}", "--title=-R x",
                            "--body-file=-", "--base=main", f"--head={BRANCH}",
                            "--draft"]  # fmt: skip
    assert call["stdin"] == "Card tsk-x\n"
    # gh runs in an empty directory of its own: it reads nothing from the clone's .git.
    assert Path(call["cwd"]).resolve() != placed["clone"].resolve()
    assert placed["clone"].resolve() not in Path(call["cwd"]).resolve().parents
    assert call["env"]["GH_PROMPT_DISABLED"] == "1"
    assert call["env"]["PATH"].split(os.pathsep)[0] == str(Path(placed["gh"]).parent)
    assert {name: call["env"][name] for name in DROPPED} == {name: None for name in DROPPED}


@runs_gh
def test_view_takes_a_number_or_branch_after_the_options_end(placed: dict[str, Any]) -> None:
    assert cli.main(["gh", "pr", "view", "1663", "--json", "state,headRefOid", "--comments"]) == 0
    call = ran(placed)
    assert call is not None
    assert call["argv"] == ["pr", "view", f"--repo={REPOSITORY}", "--json=state,headRefOid",
                            "--comments", "--", "1663"]  # fmt: skip


@pytest.mark.parametrize(
    "argv",
    [
        ["gh", "pr", "create", "-dR", "other/repo", "--title", "t", "--body", "b"],  # bundle
        ["gh", "pr", "create", "--repo", "other/repo", "--title", "t", "--body", "b"],
        ["gh", "pr", "create", "-R", "other/repo", "--title", "t", "--body", "b"],
        ["gh", "pr", "view", "--hostname", "evil.example"],
        ["gh", "pr", "create", "-T", "x", "--title", "t", "--body", "b"],  # a template file
        ["gh", "pr", "create", "--template", "x", "--title", "t", "--body", "b"],
        ["gh", "pr", "create", "-F", "x", "--title", "t"],  # gh's short body file
        ["gh", "pr", "create", "--titl", "t", "--body", "b"],  # no abbreviations
        ["gh", "pr", "creat", "--title", "t", "--body", "b"],
        ["gh", "pr", "merge", "1"],
        ["gh", "api", "repos/other/repo"],
        ["gh", "pr", "create", "--title", "t"],  # a body is required
    ],
)
def test_options_it_does_not_know_are_refused_before_gh_runs(
    placed: dict[str, Any], argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    refused(argv, capsys)
    assert ran(placed) is None


@pytest.mark.parametrize(
    "selector",
    ["https://github.com/other/repo/pull/1", "other/repo#1", "owner:branch", "-R", "a b"],
)
def test_a_url_or_another_repositorys_selector_is_refused(
    placed: dict[str, Any], selector: str, capsys: pytest.CaptureFixture[str]
) -> None:
    err = refused(["gh", "pr", "view", "--", selector], capsys)
    assert ran(placed) is None
    assert "maity gh pr view" in err or "invalid" in err  # what is allowed, or argparse's own


def test_a_refusal_names_what_is_allowed(
    placed: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    err = refused(["gh", "pr", "view", "https://github.com/other/repo/pull/1"], capsys)
    assert "maity gh pr create --title" in err and "maity gh pr view" in err


@pytest.mark.parametrize("name", ["base", "head"])
def test_a_branch_option_that_is_not_a_branch_is_refused(
    placed: dict[str, Any], name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    refused(["gh", "pr", "create", "--title", "t", "--body", "b", f"--{name}", "other:x"], capsys)
    assert ran(placed) is None


def test_json_fields_are_names_and_commas_only(
    placed: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    refused(["gh", "pr", "view", "--json", "state --jq .x"], capsys)
    assert ran(placed) is None


def login_file(tmp_path: Path) -> Path:
    hosts = tmp_path / "home" / ".config" / "gh" / "hosts.yml"
    hosts.parent.mkdir(parents=True)
    hosts.write_text("github.com:\n  oauth_token: dummysecret\n")
    return hosts


def test_a_body_file_outside_the_clone_is_refused(
    placed: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hosts = login_file(tmp_path)
    err = refused(["gh", "pr", "create", "--title", "t", "--body-file", str(hosts)], capsys)
    assert "not a file in this clone" in err and ran(placed) is None


@walks
def test_a_link_in_the_clone_to_a_file_outside_is_refused(
    placed: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (placed["clone"] / "body.md").symlink_to(login_file(tmp_path))
    err = refused(["gh", "pr", "create", "--title", "t", "--body-file", "body.md"], capsys)
    assert "a link; name the file itself" in err and ran(placed) is None


def test_dot_dot_out_of_the_clone_is_refused(
    placed: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    login_file(tmp_path)
    up = "../../../home/.config/gh/hosts.yml"
    assert (placed["clone"] / up).exists()
    err = refused(["gh", "pr", "create", "--title", "t", "--body-file", up], capsys)
    assert "not a file in this clone" in err and ran(placed) is None


@walks
def test_a_file_under_the_clones_git_is_refused(
    placed: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    (placed["clone"] / ".git" / "maity" / "credential").write_text("dummysecret\n")
    err = refused(["gh", "pr", "create", "--title", "t",
                   "--body-file", ".git/maity/credential"], capsys)  # fmt: skip
    assert "under the clone's .git" in err and ran(placed) is None


@walks
def test_a_body_over_the_limit_is_refused(
    placed: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    (placed["clone"] / "body.md").write_bytes(b"x" * (ghpr.BODY_MAX + 1))
    err = refused(["gh", "pr", "create", "--title", "t", "--body-file", "body.md"], capsys)
    assert "over" in err and ran(placed) is None


def test_without_a_record_the_grant_is_named(
    placed: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    (placed["clone"] / ghpr.PULL_REQUESTS_PATH).write_text("")
    err = refused(["gh", "pr", "view"], capsys)
    assert "pull_requests = true" in err and ran(placed) is None


@pytest.mark.parametrize(
    "record",
    [
        "github.com/o/n\n",  # no gh line
        "https://github.com/o/n\n{gh}\n",  # not the runner's form
        "github.com/o/n\n{gh}\nextra\n",
        "github.com/o/n\nrelative/gh\n",
    ],
)
def test_a_record_the_runner_does_not_write_is_refused(
    placed: dict[str, Any], record: str, capsys: pytest.CaptureFixture[str]
) -> None:
    (placed["clone"] / ghpr.PULL_REQUESTS_PATH).write_text(record.format(gh=placed["gh"]))
    refused(["gh", "pr", "view"], capsys)
    assert ran(placed) is None


def test_a_linked_record_is_refused(
    placed: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "record"
    other.write_text(f"github.com/other/repo\n{placed['gh']}\n")
    record = placed["clone"] / ghpr.PULL_REQUESTS_PATH
    record.unlink()
    record.symlink_to(other)
    err = refused(["gh", "pr", "view"], capsys)
    assert "not readable" in err and ran(placed) is None


def test_outside_a_runners_placement_it_refuses(
    placed: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    monkeypatch.delenv("MAITY_PLACEMENT")
    monkeypatch.delenv("GIT_COMMON_DIR")
    monkeypatch.chdir(tmp_path)
    err = refused(["gh", "pr", "view"], capsys)
    assert "a session a runner placed" in err and ran(placed) is None


@runs_gh
def test_gh_exit_code_is_maitys(placed: dict[str, Any]) -> None:
    gh = Path(placed["gh"])
    gh.write_text("#!/bin/sh\nexit 7\n")
    assert cli.main(["gh", "pr", "view"]) == 7


@runs_gh
def test_the_body_file_is_read_from_where_the_agent_is(
    placed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative path is the agent's, from its current directory in the clone."""
    sub = placed["clone"] / "docs"
    sub.mkdir()
    (sub / "body.md").write_text("from docs\n")
    monkeypatch.chdir(sub)
    assert cli.main(["gh", "pr", "create", "--title", "t", "--body-file", "body.md"]) == 0
    call = ran(placed)
    assert call is not None and call["stdin"] == "from docs\n"


def test_no_dropped_variable_is_passed() -> None:
    assert not set(DROPPED) & set(ghpr.ENV_PASSED)
    assert "PATH" not in ghpr.ENV_PASSED  # gh's own directory and the system's, set by maity


@runs_gh
def test_view_without_a_selector_names_the_current_branch(placed: dict[str, Any]) -> None:
    """gh does not read the branch from git: maity names it, read with its own pinned git."""
    assert cli.main(["gh", "pr", "view"]) == 0
    call = ran(placed)
    assert call is not None and call["argv"][-2:] == ["--", BRANCH]


def test_a_detached_head_without_head_is_refused(
    placed: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    git = str(shutil.which("git"))
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}  # fmt: skip
    env.pop("GIT_COMMON_DIR", None)
    clone = placed["clone"]
    subprocess.run([git, "-C", str(clone), "commit", "-q", "--allow-empty", "-m", "x"],
                   check=True, env=env)  # fmt: skip
    subprocess.run([git, "-C", str(clone), "checkout", "-q", "--detach"], check=True, env=env)
    err = refused(["gh", "pr", "create", "--title", "t", "--body", "b"], capsys)
    assert "detached HEAD" in err and ran(placed) is None


@walks
@pytest.mark.parametrize("every", [1, 2, 3])
@pytest.mark.parametrize("starts_as_link", [True, False])
def test_a_directory_exchanged_with_a_link_on_every_lookup_never_yields_the_secret(
    placed: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    every: int, starts_as_link: bool,
) -> None:  # fmt: skip
    """spq4's races (review of #1663 rounds 3 and 4): sandboxed code exchanges a directory
    in the clone with a link to a secret directory while maity, outside the sandbox, reads
    the body. Here it flips on every `every`-th name lookup maity makes, from either side,
    so a check made by name and a read made through a descriptor can see two different
    directories. maity names each file once, so it reads the harmless body or refuses."""
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "body.md").write_text("dummysecret\n")
    clone: Path = placed["clone"]
    swapped, spare = clone / "d", clone / "spare"
    swapped.mkdir()
    (swapped / "body.md").write_text("harmless\n")
    real_open, real_stat, real_lstat = os.open, os.stat, os.lstat
    real_rename, real_unlink, real_symlink = os.rename, os.unlink, os.symlink

    def flip() -> None:  # the real directory and the link trade places under the name d
        if stat.S_ISLNK(real_lstat(swapped).st_mode):
            real_unlink(swapped)
            real_rename(spare, swapped)
        else:
            real_rename(swapped, spare)
            real_symlink(secret, swapped, target_is_directory=True)

    if starts_as_link:
        flip()
    calls = 0

    def flipping(real: Any) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls % every == 0:
                flip()
            return real(*args, **kwargs)

        return call

    for name, real in (("open", real_open), ("stat", real_stat), ("lstat", real_lstat)):
        monkeypatch.setattr(os, name, flipping(real))
    for _ in range(20):
        try:
            assert ghpr.body_file(clone.resolve(), "d/body.md") == b"harmless\n"
        except ghpr.Refused as exc:
            assert "a link" in str(exc) or "not a directory" in str(exc), exc  # the walk's own
    assert calls > 0  # the walk ran: its lookups went through the flipping wrappers


@walks
def test_a_directory_link_into_the_clones_git_is_refused(
    placed: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """The final name is no link, a directory on the way is: no directory is entered
    through a link."""
    (placed["clone"] / ".git" / "maity" / "credential").write_text("dummysecret\n")
    (placed["clone"] / "G").symlink_to(placed["clone"] / ".git", target_is_directory=True)
    err = refused(["gh", "pr", "create", "--title", "t", "--body-file", "G/maity/credential"],
                  capsys)  # fmt: skip
    assert "a link; name the file itself (G is one)" in err and ran(placed) is None


@walks
@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs here")
def test_a_fifo_is_refused_without_blocking(
    placed: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    os.mkfifo(placed["clone"] / "body.md")
    err = refused(["gh", "pr", "create", "--title", "t", "--body-file", "body.md"], capsys)
    assert "not a plain file" in err and ran(placed) is None


@walks
def test_a_hard_link_is_refused(
    placed: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second name for a file: its other name may be anywhere on the volume."""
    other = tmp_path / "ws" / "elsewhere.md"
    other.write_text("dummysecret\n")
    os.link(other, placed["clone"] / "body.md")
    err = refused(["gh", "pr", "create", "--title", "t", "--body-file", "body.md"], capsys)
    assert "other hard links" in err and ran(placed) is None


def test_without_a_descriptor_walk_a_body_file_is_refused(
    placed: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    """Windows has no `dir_fd`: maity cannot walk to the file without following a link, so it
    takes no body file there; `--body` still works."""
    (placed["clone"] / "body.md").write_text("Card tsk-x\n")
    monkeypatch.setattr(ghpr, "WALKS", False)
    err = refused(["gh", "pr", "create", "--title", "t", "--body-file", "body.md"], capsys)
    assert "give the text with --body" in err and ran(placed) is None


def test_a_recorded_git_that_does_not_run_is_maitys_refusal(
    placed: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The branch is read with the git the runner recorded; when that is no program, maity
    refuses (exit 4) and names why, instead of failing as a general error."""
    (placed["clone"] / clonecheck.GIT_PATH).write_text(str(tmp_path / "no-git") + "\n")
    code = cli.main(["gh", "pr", "create", "--title", "t", "--body", "b"])
    assert code == cli.EXIT_REFUSED
    assert "maity runs no git here" in capsys.readouterr().err and ran(placed) is None


# A selector and a head, so no git runs: the record alone decides (maity's own git would
# refuse the decoy too, and hide whether the record was read from it).
@pytest.mark.parametrize(
    "subcommand",
    [["pr", "view", "7"], ["pr", "create", "--title", "t", "--body", "b", "--head", "x"]],
)
def test_a_git_exchanged_for_a_decoy_is_refused_before_its_record_is_read(
    placed: dict[str, Any], tmp_path: Path, subcommand: list[str]
) -> None:
    """Sandboxed code renames the clone's `.git` and puts a directory of its own there, with
    a record naming another repository and another gh. maity reads the record only from the
    `.git` the runner recorded at the start (`clonecheck.opened_git`), so it runs nothing."""
    clone: Path = placed["clone"]
    os.rename(clone / ".git", clone / ".git-moved")
    decoy = tmp_path / "decoy-gh"
    decoy.write_text(f"#!{sys.executable}\nopen({str(tmp_path / 'decoy-ran')!r}, 'w')\n")
    decoy.chmod(0o755)
    (clone / ".git" / "maity").mkdir(parents=True)
    (clone / ghpr.PULL_REQUESTS_PATH).write_text(f"github.com/attacker/other\n{decoy}\n")
    assert cli.main(["gh", *subcommand]) == 4
    assert ran(placed) is None and not (tmp_path / "decoy-ran").exists()


def test_the_record_is_read_through_the_checked_git(placed: dict[str, Any]) -> None:
    """With the `.git` the runner recorded in place, the record is read from its descriptor:
    a record that is a link is refused even though the name would resolve."""
    clone: Path = placed["clone"]
    record = clone / ghpr.PULL_REQUESTS_PATH
    elsewhere = clone.parent / "record"
    elsewhere.write_text(record.read_text())
    record.unlink()
    record.symlink_to(elsewhere)
    assert cli.main(["gh", "pr", "view"]) == 4
    assert ran(placed) is None


@walks  # `opened_git` yields a descriptor only where maity walks
def test_a_body_under_the_checked_git_is_refused_after_a_rename(placed: dict[str, Any]) -> None:
    """The walk compares each directory with the `.git` `opened_git` checked, by its
    descriptor: renamed after the check, with a decoy under the old name, the real one is
    still no body's way."""
    clone: Path = placed["clone"]
    with clonecheck.opened_git(clone) as dot_git:
        os.rename(clone / ".git", clone / ".git-moved")
        (clone / ".git").mkdir()
        with pytest.raises(ghpr.Refused, match="under the clone's .git"):
            ghpr.body_file(clone, ".git-moved/maity/pull_requests", dot_git)


@walks  # `opened_git` yields a descriptor only where maity walks
def test_the_record_comes_from_the_checked_git_after_a_rename(
    placed: dict[str, Any], tmp_path: Path
) -> None:
    """Renamed after `opened_git`'s check, with a decoy `.git` under the old name, the record
    is still the runner's: it is read through the checked descriptor, not by name."""
    clone: Path = placed["clone"]
    with clonecheck.opened_git(clone) as dot_git:
        os.rename(clone / ".git", clone / ".git-moved")
        (clone / ".git" / "maity").mkdir(parents=True)
        (clone / ghpr.PULL_REQUESTS_PATH).write_text(
            f"github.com/attacker/other\n{sys.executable}\n"
        )
        assert ghpr.granted(clone, dot_git) == (REPOSITORY, placed["gh"])


def renamed_after_the_check(monkeypatch: pytest.MonkeyPatch, clone: Path, decoy_gh: str) -> None:
    """`opened_git` checks the real `.git`, then sandboxed code renames it and puts a decoy
    with its own record under the old name, before `maity gh` reads anything."""
    checked = clonecheck.opened_git

    @contextlib.contextmanager
    def then_renamed(root: Path) -> Iterator[int | None]:
        with checked(root) as dot_git:
            os.rename(clone / ".git", clone / ".git-moved")
            (clone / ".git" / "maity").mkdir(parents=True)
            (clone / ghpr.PULL_REQUESTS_PATH).write_text(f"github.com/attacker/other\n{decoy_gh}\n")
            yield dot_git

    monkeypatch.setattr(clonecheck, "opened_git", then_renamed)


@walks
def test_maity_gh_reads_the_record_through_the_checked_git(
    placed: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run` hands the checked descriptor to `granted`: the record read after the rename is
    the runner's, so the real gh runs, on the real repository."""
    decoy = tmp_path / "decoy-gh"
    decoy.write_text(f"#!{sys.executable}\nopen({str(tmp_path / 'decoy-ran')!r}, 'w')\n")
    decoy.chmod(0o755)
    renamed_after_the_check(monkeypatch, placed["clone"], str(decoy))
    assert cli.main(["gh", "pr", "view", "7"]) == 0
    assert not (tmp_path / "decoy-ran").exists()
    call = ran(placed)
    assert call is not None and f"--repo={REPOSITORY}" in call["argv"]


@walks
def test_maity_gh_walks_the_body_file_against_the_checked_git(
    placed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`command` hands the checked descriptor to `body_file`: the real `.git`, renamed after
    the check, is still no body's way."""
    renamed_after_the_check(monkeypatch, placed["clone"], placed["gh"])
    argv = ["gh", "pr", "create", "--title", "t", "--head", "x"]
    assert cli.main([*argv, "--body-file", ".git-moved/maity/pull_requests"]) == 4
    assert ran(placed) is None
