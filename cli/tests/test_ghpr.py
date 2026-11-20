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

from maity import cli, clonecheck, ghpr, hub, state
from maity.runner import supervisor
from maity.runner.asuser import AsUser

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
    monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    monkeypatch.setenv("GIT_COMMON_DIR", str(clone / ".git"))
    # As the runner starts a session (#1683): the .git it recorded, git's own directory.
    monkeypatch.setenv(clonecheck.GIT_INODE_ENV, str(os.lstat(clone / ".git").st_ino))
    private = tmp_path / "agent" / "git"
    private.mkdir(parents=True)
    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, str(private))
    # The runner's records, in its directory for the agent, never in the clone.
    (private / clonecheck.GIT_PATH.name).write_text(git + "\n")
    (private / ghpr.PULL_REQUESTS).write_text(f"{REPOSITORY}\n{gh}\n")
    monkeypatch.chdir(clone)
    return {"clone": clone, "log": log, "gh": str(gh), "record": private / ghpr.PULL_REQUESTS}


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


@runs_gh
@walks
def test_a_body_file_in_the_recorded_scratch_is_sent_and_one_outside_both_names_both(
    placed: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    room = tmp_path / "ws" / "maity" / ".scratch" / "plc-0003"  # beside the clone (§15.5)
    room.mkdir(parents=True)
    private = Path(os.environ[clonecheck.GIT_PRIVATE_ENV])
    (private / clonecheck.SCRATCH_RECORD).write_text(f"{room}\n")
    (room / "body.md").write_text("Card tsk-x, from the scratch\n")
    create = ["gh", "pr", "create", "--title", "t", "--body-file"]
    assert cli.main([*create, str(room / "body.md")]) == 0
    call = ran(placed)
    assert call is not None and call["stdin"] == "Card tsk-x, from the scratch\n"
    placed["log"].unlink()
    err = refused([*create, str(login_file(tmp_path))], capsys)
    assert ran(placed) is None
    assert f"not a file in this clone ({placed['clone']})" in err
    assert f"or in the placement's scratch ({room})" in err
    assert f"this clone ({room})" not in err  # the scratch is never called the clone


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
    placed["record"].write_text("")
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
    placed["record"].write_text(record.format(gh=placed["gh"]))
    refused(["gh", "pr", "view"], capsys)
    assert ran(placed) is None


def test_a_linked_record_is_refused(
    placed: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "record"
    other.write_text(f"github.com/other/repo\n{placed['gh']}\n")
    record = placed["record"]
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
@pytest.mark.parametrize("argv", [[], ["1663"], [BRANCH], ["--comments"], ["1663", "--comments"]])
def test_view_never_runs_gh_without_json(placed: dict[str, Any], argv: list[str]) -> None:
    """gh's own text view asks for fields an older gh's query names and the forge refuses
    (`projectCards`, gh 2.46): maity always names the fields and prints them itself."""
    assert cli.main(["gh", "pr", "view", *argv]) == 0
    call = ran(placed)
    assert call is not None
    fields = [arg for arg in call["argv"] if arg.startswith("--json=")]
    expected = ",".join([*ghpr.VIEW_FIELDS, *(["comments"] if "--comments" in argv else [])])
    assert fields == [f"--json={expected}"]
    assert "--comments" not in call["argv"]  # comments come as a field
    assert "projectCards" not in expected


@runs_gh
def test_view_without_json_prints_the_pull_request_as_text(
    placed: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    answer = {
        "number": 1709, "title": "e2e (close me)", "state": "OPEN", "isDraft": True,
        "url": "https://github.com/o/r/pull/1709", "headRefName": "e2e-1663",
        "baseRefName": "main", "author": {"login": "agent"}, "body": "Card tsk-x\n",
        "comments": [{"author": {"login": "reviewer"}, "createdAt": "2026-11-12T20:00:00Z",
                      "body": "looks fine"}],
    }  # fmt: skip
    Path(placed["gh"]).write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdout.write({json.dumps(answer)!r})\n"
    )
    assert cli.main(["gh", "pr", "view", "1709", "--comments"]) == 0
    assert capsys.readouterr().out == (
        "#1709 e2e (close me)\n"
        "OPEN (draft)  e2e-1663 -> main  by agent\n"
        "https://github.com/o/r/pull/1709\n"
        "\n"
        "Card tsk-x\n"
        "\n"
        "--- reviewer, 2026-11-12T20:00:00Z\n"
        "looks fine\n"
    )


@runs_gh
def test_view_with_json_passes_gh_s_answer_through(
    placed: dict[str, Any], capfd: pytest.CaptureFixture[str]
) -> None:
    Path(placed["gh"]).write_text(f'#!{sys.executable}\nprint(\'{{"state":"OPEN"}}\')\n')
    assert cli.main(["gh", "pr", "view", "--json", "state"]) == 0
    assert capfd.readouterr().out == '{"state":"OPEN"}\n'


@runs_gh
def test_view_without_json_prints_what_is_not_gh_s_json_as_it_came(
    placed: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    Path(placed["gh"]).write_text(f"#!{sys.executable}\nprint('not json')\n")
    assert cli.main(["gh", "pr", "view"]) == 0
    assert capsys.readouterr().out == "not json\n"


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
    (placed["record"].parent / clonecheck.GIT_PATH.name).write_text(str(tmp_path / "no-git") + "\n")
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


@runs_gh
def test_a_record_in_the_clone_is_never_read(placed: dict[str, Any], tmp_path: Path) -> None:
    """A record at `.git/maity/pull_requests` in the clone naming another repository and
    another gh is not the runner's: maity reads only the runner's record in its own
    directory, so the real gh runs on the real repository."""
    decoy = tmp_path / "decoy-gh"
    decoy.write_text(f"#!{sys.executable}\nopen({str(tmp_path / 'decoy-ran')!r}, 'w')\n")
    decoy.chmod(0o755)
    (placed["clone"] / ghpr.PULL_REQUESTS_PATH).write_text(f"github.com/attacker/other\n{decoy}\n")
    assert cli.main(["gh", "pr", "view", "7"]) == 0
    assert not (tmp_path / "decoy-ran").exists()
    call = ran(placed)
    assert call is not None and f"--repo={REPOSITORY}" in call["argv"]
    placed["record"].unlink()  # without the runner's record: no grant, never the clone's
    assert cli.main(["gh", "pr", "view", "7"]) == 4
    assert not (tmp_path / "decoy-ran").exists()


@walks  # `opened_git` yields a descriptor only where maity walks
def test_a_body_under_the_checked_git_is_refused_after_a_rename(placed: dict[str, Any]) -> None:
    """The walk compares each directory with the `.git` `opened_git` checked, by its
    descriptor: renamed after the check, with a decoy under the old name, the real one is
    still no body's way."""
    clone: Path = placed["clone"]
    with clonecheck.opened_clone(clone) as opened:
        os.rename(clone / ".git", clone / ".git-moved")
        (clone / ".git").mkdir()
        with pytest.raises(ghpr.Refused, match="under the clone's .git"):
            ghpr.body_file(clone, ".git-moved/maity/pull_requests", opened)


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


@walks  # `opened_clone` yields descriptors only where maity walks
def test_a_body_is_read_from_the_checked_root_after_an_exchange(placed: dict[str, Any]) -> None:
    """The walk starts at the root `opened_clone` checked with `.git`, by its descriptor: a
    directory put at the clone's path after the check, with a body of its own, is not read."""
    clone: Path = placed["clone"]
    (clone / "body.md").write_text("real\n")
    moved = clone.parent / "moved"
    with clonecheck.opened_clone(clone) as opened:
        os.rename(clone, moved)
        clone.mkdir()
        (clone / "body.md").write_text("decoy\n")
        assert ghpr.body_file(clone, str(clone / "body.md"), opened) == b"real\n"


def renamed_after_the_check(monkeypatch: pytest.MonkeyPatch, clone: Path, decoy_gh: str) -> None:
    """`opened_clone` checks the real `.git`, then sandboxed code renames it and puts a decoy
    with its own record under the old name, before `maity gh` reads anything."""
    checked = clonecheck.opened_clone

    @contextlib.contextmanager
    def then_renamed(root: Path) -> Iterator[clonecheck.Opened | None]:
        with checked(root) as opened:
            os.rename(clone / ".git", clone / ".git-moved")
            (clone / ".git" / "maity").mkdir(parents=True)
            (clone / ghpr.PULL_REQUESTS_PATH).write_text(f"github.com/attacker/other\n{decoy_gh}\n")
            yield opened

    monkeypatch.setattr(clonecheck, "opened_clone", then_renamed)


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


# --- the lead commands (tsk-pvnj16k8d6m0) -----------------------------------------------------

SHA = "4a59187965ed2fca8c6ecb874d053823ba14ce91"
ROLE_READS: list[str] = []


def make_runner_layout(agent_files: Path, placement: str) -> Path:
    """`agents/<placement>/git` as the runner makes it (supervisor.agent_dir_for, then
    adapters.launch's `as_user.mkdir(records)`), under a umask of 002, the default of a manual
    `maity runner serve` or sudo on Debian and Ubuntu (review A1758 of #2054): no chmod here."""
    old = os.umask(0o002)
    try:
        agent_dir = supervisor.agent_dir_for(AsUser(), agent_files, placement)
        AsUser().mkdir(agent_dir / "git")
    finally:
        os.umask(old)
    return agent_dir / "git"


def runner_layout(tmp_path: Path, placed: dict[str, Any], placement: str) -> Path:
    """The runner's directory for the agent as the runner lays it out,
    `<agent files>/agents/<placement>/git`, holding `placed`'s records (git, pull_requests).
    Resolved (macOS's /var is a link): the lead commands refuse a link on the way."""
    where = make_runner_layout(tmp_path.resolve() / "agent-files", placement)
    for name in (clonecheck.GIT_PATH.name, ghpr.PULL_REQUESTS):
        (where / name).write_bytes((placed["record"].parent / name).read_bytes())
    return where


@pytest.fixture
def lead(placed: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`placed` with the runner's LEAD record in this placement's own directory of the
    runner's layout (`agents/plc-0003/git`), and a hub that names the member's role base
    manager; the role read is counted, so a test can see it happened at the call."""
    where = runner_layout(tmp_path, placed, "plc-0003")
    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, str(where))
    record = where / ghpr.LEAD
    # Written as the runner writes it (adapters.launch: AsUser.write, state.write_file, a text
    # file), so its line end is this system's (`\r\n` on Windows).
    state.write_file(record, "lead\n")
    ROLE_READS.clear()

    def manager(*_: Any) -> str:
        ROLE_READS.append("read")
        return "manager"

    monkeypatch.setattr(cli, "_hub_role", manager)
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"isMergeQueueEnabled": False, "isInMergeQueue": False}))
    lead_gh(Path(placed["gh"]), placed["log"], queue)
    return {**placed, "lead_record": record, "runner_dir": where, "queue": queue}


QUEUE_VIEW = "--json=" + ",".join(ghpr.QUEUE_FIELDS)


def lead_gh(gh: Path, log: Path, queue: Path, out: str = "", err: str = "") -> None:
    """A gh that answers the merge's queue read (`pr view --json=isMergeQueueEnabled,…`)
    with `queue`'s text and counts it in `<queue>.calls`, and otherwise writes down how it ran
    in `log` (argv, stdin, cwd) and prints `out` and `err`."""
    gh.write_text(
        f"#!{sys.executable}\nimport json, os, sys\n"
        f"if {QUEUE_VIEW!r} in sys.argv:\n"
        f"    open({str(queue) + '.calls'!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
        f"    sys.stdout.write(open({str(queue)!r}).read())\n"
        "    sys.exit(0)\n"
        "json.dump({'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'cwd': os.getcwd()},"
        f" open({str(log)!r}, 'w'))\n"
        f"sys.stdout.write({out!r})\nsys.stderr.write({err!r})\n"
    )
    gh.chmod(0o755)


@runs_gh
@pytest.mark.parametrize(
    "answer",
    [
        {"isMergeQueueEnabled": True, "isInMergeQueue": False},  # the base branch queues merges
        {"isMergeQueueEnabled": False, "isInMergeQueue": True},  # already in a queue
        {"isInMergeQueue": False},  # an older gh, or an answer without the field
        "not json",
    ],
)
def test_a_merge_that_would_not_be_direct_is_refused_before_gh_merges(
    lead: dict[str, Any], answer: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review A1804 of #2054, the lead's ruling: on a base branch with a merge queue
    `gh pr merge` hands the strategy to the queue, so `--squash` and the head named would no
    longer be the outcome. maity reads the queue state first and merges only directly; any
    answer but two `false`s refuses, and gh is never asked to merge."""
    lead["queue"].write_text(answer if isinstance(answer, str) else json.dumps(answer))
    err = refused(["gh", "pr", "merge", "2045", "--match-head-commit", SHA, "--subject", "s",
                   "--body", "b"], capsys)  # fmt: skip
    assert "does not merge directly" in err and ran(lead) is None
    calls = Path(str(lead["queue"]) + ".calls").read_text().splitlines()
    assert calls == [f"pr view --repo={REPOSITORY} {QUEUE_VIEW} -- 2045"]


@pytest.mark.parametrize("layout", ["another placement", "not the runner's layout"])
def test_the_lead_record_counts_only_in_this_placements_directory(
    lead: dict[str, Any], tmp_path: Path, layout: str, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    """Review A1721 of #2054: GIT_PRIVATE_ENV is taken as given, so the lead commands read
    their record only from `…/agents/<this placement>/git`. A directory with every record in
    place but of another placement, or outside the layout, is refused before any role read."""
    if layout == "another placement":
        where = runner_layout(tmp_path / "other", lead, "plc-0009")
    else:
        where = lead["record"].parent  # placed's own `agent/git`, which the runner never makes
    state.write_file(where / ghpr.LEAD, "lead\n")
    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, str(where))
    err = refused(["gh", "pr", "ready", "2045"], capsys)
    assert "this placement's directory" in err and ran(lead) is None and ROLE_READS == []


@runs_gh
def test_merge_squashes_the_named_head_with_the_footer_left_out(
    lead: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    body = (
        "Card tsk-x.\n\nSays co-authored-by: in a sentence, which stays.\n"
        "Co-Authored-By: Someone <a@example.org>\n"
        "\U0001f916 Generated with [A Tool](https://example.org/tool)\n"
        "Generated by [A Container](https://example.org/container)\n"  # the containers' form
    )
    (lead["clone"] / "body.md").write_text(body)
    argv = ["gh", "pr", "merge", "2045", "--match-head-commit", SHA, "--subject",
            "ci + context: #2025 follow-ups (tsk-x) (#2045)", "--body-file", "body.md"]  # fmt: skip
    assert cli.main(argv) == 0
    call = ran(lead)
    assert call is not None
    assert call["argv"] == ["pr", "merge", f"--repo={REPOSITORY}", "--squash",
                            f"--match-head-commit={SHA}",
                            "--subject=ci + context: #2025 follow-ups (tsk-x) (#2045)",
                            "--body-file=-", "--", "2045"]  # fmt: skip
    assert call["stdin"] == "Card tsk-x.\n\nSays co-authored-by: in a sentence, which stays.\n"
    assert "left out 3 footer line(s)" in capsys.readouterr().err
    assert ROLE_READS == ["read"]
    # The queue state was read first, and said the merge is direct (review A1804).
    calls = Path(str(lead["queue"]) + ".calls").read_text().splitlines()
    assert calls == [f"pr view --repo={REPOSITORY} {QUEUE_VIEW} -- 2045"]


@pytest.mark.parametrize(
    "argv",
    [
        # no --match-head-commit: argparse refuses before anything runs
        ["gh", "pr", "merge", "2045", "--subject", "s", "--body", "b"],
        # a short sha, a branch, a URL
        [
            "gh",
            "pr",
            "merge",
            "2045",
            "--match-head-commit",
            SHA[:8],
            "--subject",
            "s",
            "--body",
            "b",
        ],
        [
            "gh",
            "pr",
            "merge",
            "agent-x/branch",
            "--match-head-commit",
            SHA,
            "--subject",
            "s",
            "--body",
            "b",
        ],
        [
            "gh",
            "pr",
            "merge",
            "https://github.com/o/n/pull/1",
            "--match-head-commit",
            SHA,
            "--subject",
            "s",
            "--body",
            "b",
        ],
        # another method, an admin bypass, auto-merge, a branch deletion, another repository
        [
            "gh",
            "pr",
            "merge",
            "2045",
            "--match-head-commit",
            SHA,
            "--subject",
            "s",
            "--body",
            "b",
            "--merge",
        ],
        [
            "gh",
            "pr",
            "merge",
            "2045",
            "--match-head-commit",
            SHA,
            "--subject",
            "s",
            "--body",
            "b",
            "--admin",
        ],
        [
            "gh",
            "pr",
            "merge",
            "2045",
            "--match-head-commit",
            SHA,
            "--subject",
            "s",
            "--body",
            "b",
            "--auto",
        ],
        [
            "gh",
            "pr",
            "merge",
            "2045",
            "--match-head-commit",
            SHA,
            "--subject",
            "s",
            "--body",
            "b",
            "--delete-branch",
        ],
        [
            "gh",
            "pr",
            "merge",
            "2045",
            "--match-head-commit",
            SHA,
            "--subject",
            "s",
            "--body",
            "b",
            "-R",
            "other/repo",
        ],
        # a subject over two lines
        [
            "gh",
            "pr",
            "merge",
            "2045",
            "--match-head-commit",
            SHA,
            "--subject",
            "s\nCo-Authored-By: x",
            "--body",
            "b",
        ],
        # other gh commands and options
        ["gh", "pr", "close", "2045"],
        ["gh", "pr", "edit", "2045", "--body", "b", "--add-reviewer", "x"],
        ["gh", "pr", "edit", "2045", "--body", "b", "--base", "other"],
        ["gh", "pr", "ready", "2045", "--undo"],
        ["gh", "run", "rerun", "1"],
        ["gh", "run", "list"],
        ["gh", "run", "list", "--commit", "main"],
        ["gh", "run", "view", "x1"],
        ["gh", "run", "view", "1", "--job", "x"],
        ["gh", "run", "view", "1", "--log"],
        ["gh", "api", "repos/o/n"],
    ],
)
def test_a_lead_command_takes_only_its_shapes(
    lead: dict[str, Any], argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    refused(argv, capsys)
    assert ran(lead) is None


@runs_gh
def test_edit_sets_the_title_and_the_body_and_ready_marks_it(lead: dict[str, Any]) -> None:
    assert cli.main(["gh", "pr", "edit", "2045", "--title", "t", "--body", "b\n"]) == 0
    call = ran(lead)
    assert call is not None
    assert call["argv"] == ["pr", "edit", f"--repo={REPOSITORY}", "--title=t", "--body-file=-",
                            "--", "2045"]  # fmt: skip
    assert call["stdin"] == "b\n"
    assert cli.main(["gh", "pr", "ready"]) == 0
    call = ran(lead)
    assert call is not None
    assert call["argv"] == ["pr", "ready", f"--repo={REPOSITORY}", "--", BRANCH]


@runs_gh
def test_run_list_and_view_read_the_heads_runs_and_jobs(lead: dict[str, Any]) -> None:
    assert cli.main(["gh", "run", "list", "--commit", SHA]) == 0
    call = ran(lead)
    assert call is not None
    assert call["argv"] == ["run", "list", f"--repo={REPOSITORY}", f"--commit={SHA}",
                            f"--json={','.join(ghpr.RUN_FIELDS)}", "--limit=50"]  # fmt: skip
    assert cli.main(["gh", "run", "view", "44802593768"]) == 0
    call = ran(lead)
    assert call is not None
    assert call["argv"] == ["run", "view", f"--repo={REPOSITORY}",
                            f"--json={','.join(ghpr.RUN_VIEW_FIELDS)}", "--",
                            "44802593768"]  # fmt: skip
    assert "jobs" in ghpr.RUN_VIEW_FIELDS
    # Real ids: an 11-digit run and a 12-digit job (lotse#ajwe's run on #2054).
    argv = ["gh", "run", "view", "44802593768", "--job", "136531499858", "--log-failed"]
    assert cli.main(argv) == 0
    call = ran(lead)
    assert call is not None
    assert call["argv"] == ["run", "view", f"--repo={REPOSITORY}", "--job=136531499858",
                            "--log-failed", "--", "44802593768"]  # fmt: skip


def test_run_and_job_ids_take_up_to_nineteen_digits_and_pr_numbers_ten() -> None:
    """Run and job ids already pass 10 digits; 19 hold any positive 64-bit id; a pull
    request number keeps its cap."""
    assert ghpr.RUN_ID.fullmatch("44802593768") and ghpr.RUN_ID.fullmatch("136531499858")
    assert ghpr.RUN_ID.fullmatch("9" * 19) and not ghpr.RUN_ID.fullmatch("9" * 20)
    assert not ghpr.RUN_ID.fullmatch("0123") and not ghpr.RUN_ID.fullmatch("12a")
    assert ghpr.NUMBER.fullmatch("2054") and not ghpr.NUMBER.fullmatch("44802593768")


@runs_gh
def test_a_failed_log_is_cleaned_and_cut_to_its_last_lines(
    lead: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    lines = ghpr.LOG_TAIL + 5
    Path(lead["gh"]).write_text(
        f"#!{sys.executable}\nimport sys\n"
        f"sys.stdout.write(''.join(f'line {{n}}\\x1b[31m\\n' for n in range({lines})))\n"
    )
    assert cli.main(["gh", "run", "view", "4", "--log-failed"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"maity: cut to the last {ghpr.LOG_TAIL} of {lines} lines"
    assert len(out) == ghpr.LOG_TAIL + 1
    assert out[1].startswith("line 5") and out[-1].startswith(f"line {lines - 1}")
    assert "\x1b" not in "".join(out)


@pytest.mark.parametrize("role", ["coder", "reviewer", None])
def test_a_member_the_hub_does_not_name_a_manager_is_refused(
    lead: dict[str, Any], role: str | None, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    monkeypatch.setattr(cli, "_hub_role", lambda *_: role)
    err = refused(["gh", "pr", "ready", "2045"], capsys)
    assert "manager or built on it" in err and ran(lead) is None


def test_a_hub_that_does_not_answer_refuses(
    lead: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def down(*_: Any) -> str:
        raise ghpr.Refused("the hub did not say this member's role: unreachable")

    monkeypatch.setattr(cli, "_hub_role", down)
    err = refused(["gh", "pr", "merge", "2045", "--match-head-commit", SHA, "--subject", "s",
                   "--body", "b"], capsys)  # fmt: skip
    assert "unreachable" in err and ran(lead) is None


# The other system's line end: what the runner never writes here.
FOREIGN_LEAD = b"lead\n" if os.linesep == "\r\n" else b"lead\r\n"


@pytest.mark.parametrize("content", [b"", b"yes\n", b"lead", b"lead\nlead\n", FOREIGN_LEAD])
def test_without_the_runners_lead_record_the_lead_commands_are_refused(
    lead: dict[str, Any], content: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    lead["lead_record"].write_bytes(content)
    refused(["gh", "pr", "ready", "2045"], capsys)
    assert ran(lead) is None and ROLE_READS == []


def test_the_lead_record_is_the_runners_text_write_on_this_system() -> None:
    """lotse#ajwe's run of #2054 on Windows: the runner writes its records as text, so the
    record ends in `\\r\\n` there; maity takes exactly that, not a `\\n` the runner never
    writes on Windows (FOREIGN_LEAD above)."""
    assert ghpr.LEAD_RECORD == ("lead" + os.linesep).encode("ascii")


def test_a_missing_lead_record_names_the_grant_and_reads_no_role(
    lead: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    lead["lead_record"].unlink()
    err = refused(["gh", "run", "list", "--commit", SHA], capsys)
    assert "lead = true" in err and ran(lead) is None and ROLE_READS == []


@runs_gh
def test_create_and_view_need_no_lead_record_and_no_role(
    placed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_read(*_: Any) -> str:
        raise AssertionError("create and view read no role")

    monkeypatch.setattr(cli, "_hub_role", no_read)
    assert cli.main(["gh", "pr", "view", "7"]) == 0


def test_the_role_is_never_read_for_an_agent_served_with_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.Session, "for_target", "agt-other")
    with pytest.raises(ghpr.Refused, match="--for"):
        cli._hub_role(ROOT, OPENED)


ROOT = Path("/ws/maity/agent-3")
OPENED = clonecheck.Opened(top=-1, git=-1)  # never opened: Session.through is replaced
PROJECT = "oliver-zehentleitner/maity"
MEMBERS = "/projects/oliver-zehentleitner/maity/members/"


class _Client:
    """A hub that answers for the credential that signed the call: `/me` and the member views
    by path from `answers`, an exception raised as given; every call is recorded."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str]] = []

    def call(self, method: str, path: str, **_: Any) -> Any:
        self.calls.append((method, path))
        answer = self.answers.get(path, hub.HubError("not found", "not_found", 404))
        if isinstance(answer, Exception):
            raise answer
        return answer


def _session(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any], local_member: str = "agt-manager"
) -> _Client:
    """The placement's session as Session.through would read it, its state naming
    `local_member` (a manager's id, say) while the hub authenticates the credential as
    whoever `/me` in `answers` describes. Session.through itself is tested below on real
    files; here it is replaced, and records the descriptor it was handed."""
    client = _Client(answers)

    class FakeSession:
        def __init__(self) -> None:
            self.client = client
            self.data = {"member_id": local_member, "full_name": PROJECT}

        def project_path(self, *parts: str) -> str:
            return "/projects/" + PROJECT + "/" + "/".join(parts)

    def through(root: Path, top: int) -> FakeSession:
        client.calls.append(("through", f"{root}:{top}"))
        return FakeSession()

    monkeypatch.setattr(cli.Session, "through", through)
    monkeypatch.delenv("MAITY_PLACEMENT", raising=False)
    monkeypatch.delenv("MAITY_STATE_DIR", raising=False)
    return client


THROUGH = ("through", f"{ROOT}:-1")  # the session read through the checked .git, first


def _me(member: str, role: str = "coder", isolated: Any = None) -> dict[str, Any]:
    return {"member": {"id": member},
            "projects": [{"full_name": PROJECT, "role": role}],
            "membership": {"isolated": isolated}}  # fmt: skip


def test_the_role_is_the_authenticated_callers_not_the_local_member_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review A1720 of #2054: the local state may name a manager's id, but `/me` answers for
    the credential that signed the call; the member view read is that member's, never the
    local id's, and its role base decides."""
    client = _session(monkeypatch, {
        "/me": _me("agt-coder"),
        MEMBERS + "agt-coder": {"id": "agt-coder", "role": "coder", "role_base": "coder"},
        MEMBERS + "agt-manager": {"id": "agt-manager", "role": "manager", "role_base": "manager"},
    }, local_member="agt-manager")  # fmt: skip
    assert cli._hub_role(ROOT, OPENED) == "coder"
    assert client.calls == [THROUGH, ("GET", "/me"), ("GET", MEMBERS + "agt-coder")]


@pytest.mark.parametrize(("role", "base", "allowed"), [
    ("manager", "manager", True),
    ("release-lead", "manager", True),   # a project role built on manager counts as manager
    ("lead-coder", "coder", False),      # one built on coder does not, whatever its name says
])  # fmt: skip
def test_the_role_base_decides_not_the_roles_name(
    monkeypatch: pytest.MonkeyPatch, role: str, base: str, allowed: bool
) -> None:
    """The lead's decision on #2054: a project role grants no more than its base
    (context/trust.md), so `role_base == manager` lets a lead command run."""
    _session(monkeypatch, {
        "/me": _me("agt-l", role=role),
        MEMBERS + "agt-l": {"id": "agt-l", "role": role, "role_base": base},
    })  # fmt: skip
    if allowed:
        ghpr.check_role(cli._hub_role, ROOT, OPENED)
    else:
        with pytest.raises(ghpr.Refused, match="manager or built on it"):
            ghpr.check_role(cli._hub_role, ROOT, OPENED)


def test_an_isolated_member_is_refused_though_me_answers_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/me` answers an isolated agent (§6.2); the lead commands check its flag and refuse
    before any member read."""
    client = _session(monkeypatch, {
        "/me": _me("agt-l", role="manager", isolated={"by": "hum-x", "reason": "r"}),
        MEMBERS + "agt-l": {"id": "agt-l", "role": "manager", "role_base": "manager"},
    })  # fmt: skip
    with pytest.raises(ghpr.Refused, match="isolated"):
        cli._hub_role(ROOT, OPENED)
    assert client.calls == [THROUGH, ("GET", "/me")]


def test_a_member_view_of_another_member_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _session(monkeypatch, {
        "/me": _me("agt-l"),
        MEMBERS + "agt-l": {"id": "agt-other", "role": "manager", "role_base": "manager"},
    })  # fmt: skip
    with pytest.raises(ghpr.Refused, match="not the member"):
        cli._hub_role(ROOT, OPENED)


@pytest.mark.parametrize(
    "me",
    [
        {"member": {"id": "agt-x"}, "projects": []},  # not a member of this project
        {"member": {"id": "agt-x"}, "projects": [{"full_name": "o/elsewhere", "role": "manager"}]},
        {"member": {"id": "agt-x"}},  # no list at all
        {"projects": [{"full_name": PROJECT, "role": "manager"}]},  # no member named
        "not json",
    ],
)
def test_a_me_that_does_not_list_this_project_refuses(
    monkeypatch: pytest.MonkeyPatch, me: Any
) -> None:
    _session(monkeypatch, {"/me": me})
    with pytest.raises(ghpr.Refused, match="no membership"):
        cli._hub_role(ROOT, OPENED)


def test_a_hub_error_on_me_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    _session(monkeypatch, {"/me": hub.HubError("unreachable")})
    with pytest.raises(ghpr.Refused, match="did not say"):
        cli._hub_role(ROOT, OPENED)


@pytest.mark.skipif(
    os.name == "nt" or os.open not in os.supports_dir_fd,
    reason="no descriptor walk here; the lead commands refuse on such a system",
)
def test_a_malformed_credential_is_a_refusal_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review A1758 of #2054 (P3): a credential that is not `mty1.<id>.<secret>` makes
    Session.through raise CredentialFormatError; the role read turns it into a refusal like
    the others (exit 4), before any call."""
    monkeypatch.delenv("MAITY_PLACEMENT", raising=False)
    monkeypatch.delenv("MAITY_STATE_DIR", raising=False)
    git = tmp_path / "clone" / ".git"
    folder = git / "maity"
    folder.mkdir(parents=True)
    folder.chmod(0o700)
    state.save_state(folder, {"hub": "https://hub.example", "full_name": PROJECT})
    state.write_credential(folder, state.Secret("not-a-credential"))
    top = os.open(git, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ghpr.Refused, match="did not say"):
            cli._hub_role(tmp_path / "clone", clonecheck.Opened(top=-1, git=top))
    finally:
        os.close(top)


def test_a_state_dir_named_by_maity_state_dir_is_refused_under_a_placement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review A1721 of #2054: the runner never sets MAITY_STATE_DIR, so under a placement
    the lead commands refuse it before a session is built or the hub asked."""
    client = _session(monkeypatch, {"/me": _me("agt-l", role="manager")})
    monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    monkeypatch.setenv("MAITY_STATE_DIR", "/elsewhere/state")
    with pytest.raises(ghpr.Refused, match="MAITY_STATE_DIR"):
        cli._hub_role(ROOT, OPENED)
    assert client.calls == []


def test_without_the_checked_git_no_session_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """Where ghpr.run has no descriptor of the checked `.git` (Windows), the lead commands
    refuse before any state is read or the hub asked (review A1738 of #2054)."""
    client = _session(monkeypatch, {"/me": _me("agt-l", role="manager")})
    with pytest.raises(ghpr.Refused, match="checked .git"):
        cli._hub_role(ROOT, None)
    assert client.calls == []


# --- the placement's state read through the checked .git (state.read_placed) ---------------

needs_dir_fd = pytest.mark.skipif(
    os.name == "nt" or os.open not in os.supports_dir_fd,
    reason="no descriptor walk here; the lead commands refuse on such a system",
)


def _placed_state(tmp_path: Path) -> tuple[Path, int]:
    """A clone's `.git` with `maity/state.json` and `maity/credential` as maity writes them
    (0700 directory, 0600 files), and an open descriptor of that `.git`."""
    git = tmp_path / "clone" / ".git"
    folder = git / "maity"
    folder.mkdir(parents=True)
    folder.chmod(0o700)
    state.save_state(folder, {"hub": "https://hub.example", "full_name": PROJECT})
    state.write_credential(folder, state.Secret("mty1.a.b"))
    return folder, os.open(git, os.O_RDONLY | os.O_DIRECTORY)


@needs_dir_fd
def test_the_placements_state_is_read_through_the_checked_git(tmp_path: Path) -> None:
    folder, top = _placed_state(tmp_path)
    try:
        data, credential = state.read_placed(top)
    finally:
        os.close(top)
    assert data["full_name"] == PROJECT and credential.reveal() == "mty1.a.b"


@needs_dir_fd
def test_a_git_swapped_after_the_check_is_never_read(tmp_path: Path) -> None:
    """kduz's probe on #2054 (A1739): `.git` replaced by a decoy after `opened_clone`
    opened it and before the state is read. The read goes through the descriptor of the
    `.git` that was checked, so the decoy's hub and credential are never seen (a path read,
    as on ea5ca498, would take the decoy's)."""
    folder, top = _placed_state(tmp_path)
    clone = tmp_path / "clone"
    try:
        os.rename(clone / ".git", clone / ".git-moved")
        decoy = clone / ".git" / "maity"
        decoy.mkdir(parents=True, mode=0o700)
        decoy.chmod(0o700)
        state.save_state(decoy, {"hub": "https://attacker.example", "full_name": "o/decoy"})
        state.write_credential(decoy, state.Secret("mty1.x.y"))
        data, credential = state.read_placed(top)
    finally:
        os.close(top)
    assert data == {"hub": "https://hub.example", "full_name": PROJECT}
    assert credential.reveal() == "mty1.a.b"


@needs_dir_fd
@pytest.mark.parametrize(
    "spoil",
    ["maity is a link", "state.json is a link", "credential is a link",
     "credential hard-linked", "credential readable by others", "maity readable by group",
     "credential a directory", "state.json too large", "state.json a FIFO",
     "credential a FIFO"],
)  # fmt: skip
def test_a_spoiled_placement_state_is_refused_before_any_client(tmp_path: Path, spoil: str) -> None:
    """Review A1738 of #2054: the read boundary itself. Each step is opened from the one
    before without following a link, and each must be maity's own private file or directory;
    anything else is refused, so nothing a sandboxed session planted signs a call."""
    folder, top = _placed_state(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    try:
        if spoil == "maity is a link":
            folder.rename(elsewhere / "maity")
            folder.symlink_to(elsewhere / "maity")
        elif spoil in ("state.json is a link", "credential is a link"):
            name = spoil.split(" ")[0]
            (folder / name).rename(elsewhere / name)
            (folder / name).symlink_to(elsewhere / name)
        elif spoil == "credential hard-linked":
            os.link(folder / "credential", elsewhere / "credential")
        elif spoil == "credential readable by others":
            (folder / "credential").chmod(0o644)
        elif spoil == "maity readable by group":
            folder.chmod(0o750)
        elif spoil == "credential a directory":
            (folder / "credential").unlink()
            (folder / "credential").mkdir(mode=0o700)
        elif spoil.endswith("a FIFO"):
            # No writer: without O_NONBLOCK the open would wait forever (review A1758).
            name = spoil.split(" ")[0]
            (folder / name).unlink()
            os.mkfifo(folder / name, 0o600)
        else:
            (folder / "state.json").write_bytes(b" " * (state.PLACED_STATE_MAX + 1))
            (folder / "state.json").chmod(0o600)
        with pytest.raises(state.StateError):
            state.read_placed(top)
    finally:
        os.close(top)


@needs_dir_fd
def test_the_session_through_the_checked_git_signs_with_that_credential(
    tmp_path: Path,
) -> None:
    """Session.through builds the client from the bytes read through the descriptor alone:
    a state.json elsewhere that MAITY_STATE_DIR or a path would name plays no part."""
    folder, top = _placed_state(tmp_path)
    try:
        session = cli.Session.through(tmp_path / "clone", top)
    finally:
        os.close(top)
    assert session.data["full_name"] == PROJECT
    assert session.dir == tmp_path / "clone" / ".git" / "maity"
    assert session.client.base.startswith("https://hub.example")


# --- the runner's directory for the agent (ghpr.owned_layout) --------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes; the lead commands refuse on Windows")
@pytest.mark.parametrize(
    "spoil",
    ["a link on the way", "agents writable by group", "placement writable by others",
     "git of another kind"],
)  # fmt: skip
def test_the_runners_directory_must_be_real_and_closed_to_others(
    tmp_path: Path, spoil: str
) -> None:
    """The security leg's P3 on #2054, tightened by the lead: no link anywhere on the way to
    `agents/<placement>/git`, and none of the three writable by group or others."""
    base = tmp_path.resolve()
    where = base / "state" / "agents" / "plc-0003" / "git"
    where.mkdir(parents=True)
    for step in (where.parent.parent, where.parent, where):
        step.chmod(0o700)
    ghpr.owned_layout(where)  # as the runner makes it: passes
    if spoil == "a link on the way":
        (base / "link").symlink_to(base / "state")
        where = base / "link" / "agents" / "plc-0003" / "git"
    elif spoil == "agents writable by group":
        where.parent.parent.chmod(0o770)
    elif spoil == "placement writable by others":
        where.parent.chmod(0o703)
    else:
        where.rmdir()
        where.write_text("")
    with pytest.raises(ghpr.Refused):
        ghpr.owned_layout(where)


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes; the lead commands refuse on Windows")
def test_the_runner_makes_a_layout_the_lead_commands_take_under_a_loose_umask(
    tmp_path: Path,
) -> None:
    """Review A1758 of #2054: under a umask of 002 a mkdir with parents leaves `agents/` at
    0775, which owned_layout refuses; the runner makes and keeps it 0700 itself, and tightens
    one an older runner left at 0775."""
    base = tmp_path.resolve()
    where = make_runner_layout(base / "fresh", "plc-0003")
    assert stat.S_IMODE(os.stat(where.parent.parent).st_mode) == 0o700
    ghpr.owned_layout(where)
    older = base / "older" / "agents"
    older.mkdir(parents=True)
    older.chmod(0o775)  # what an older runner made under umask 002
    where = make_runner_layout(base / "older", "plc-0003")
    assert stat.S_IMODE(os.stat(older).st_mode) == 0o700
    ghpr.owned_layout(where)


@pytest.mark.skipif(os.name == "nt", reason="POSIX owners; the lead commands refuse on Windows")
@pytest.mark.parametrize("step", ["agents", "placement", "git"])
def test_a_runner_directory_of_another_user_is_refused(
    tmp_path: Path, step: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review A1758 of #2054: in every layout the runner makes all three as the agents' user,
    this session's uid, so one owned by anybody else is refused (a test cannot chown, so the
    owner lstat reports is replaced for that one directory)."""
    where = make_runner_layout(tmp_path.resolve(), "plc-0003")
    foreign = {"agents": where.parent.parent, "placement": where.parent, "git": where}[step]
    real_lstat = os.lstat

    def lstat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        info = real_lstat(path, *args, **kwargs)
        if Path(path) != foreign:
            return info
        fields = list(info)
        fields[stat.ST_UID] = os.getuid() + 1
        return os.stat_result(fields)

    monkeypatch.setattr(os, "lstat", lstat)
    with pytest.raises(ghpr.Refused, match="not a directory of this user's"):
        ghpr.owned_layout(where)


@runs_gh
def test_every_answer_of_gh_is_cleaned_on_both_streams(
    lead: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """Review A1721 of #2054: a confirmation can echo a title someone else wrote; neither
    stream reaches the terminal with an escape a terminal acts on."""
    out, err = "merged #2045 (\x1b]0;title\x07)\n", "✓ Squashed \x1b[2J and merged\n"
    lead_gh(Path(lead["gh"]), lead["log"], lead["queue"], out=out, err=err)
    argv = ["gh", "pr", "merge", "2045", "--match-head-commit", SHA, "--subject", "s",
            "--body", "b"]  # fmt: skip
    assert cli.main(argv) == 0
    seen = capsys.readouterr()
    assert "\x1b" not in seen.out and "\x07" not in seen.out and "\x1b" not in seen.err
    assert "merged #2045" in seen.out and "\\x1b" in seen.out and "Squashed" in seen.err


def test_the_footer_filter_drops_whole_lines_only() -> None:
    text = (
        "Title line\n"
        "  co-authored-by: Lower Case <x@example.org>\r\n"
        "Thanks; Co-Authored-By: is named here in a sentence\n"
        "Generated with [Tool](https://example.org)\n"
        "Generated with care by hand\n"
        "\U0001f916 Generated by [A Container](https://example.org/c)\n"
        "Generated by the team, see [notes](https://example.org/n)\n"
    )
    kept, dropped = ghpr.strip_footer(text)
    assert dropped == 3
    assert kept == (
        "Title line\n"
        "Thanks; Co-Authored-By: is named here in a sentence\n"
        "Generated with care by hand\n"
        "Generated by the team, see [notes](https://example.org/n)\n"
    )
    assert ghpr.strip_footer("no footer") == ("no footer", 0)


def test_check_role_fails_closed() -> None:
    with pytest.raises(ghpr.Refused):
        ghpr.check_role(None, ROOT)
    with pytest.raises(ghpr.Refused, match="no role"):
        ghpr.check_role(lambda *_: None, ROOT)
    ghpr.check_role(lambda *_: "manager", ROOT)
