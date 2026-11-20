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

from maity import cli, clonecheck, ghpr, hub

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


@pytest.fixture
def lead(placed: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`placed` with the runner's LEAD record and a hub that names the member a manager; the
    role read is counted, so a test can see it happened at the call."""
    record = placed["record"].parent / ghpr.LEAD
    record.write_text("lead\n")
    ROLE_READS.clear()

    def manager() -> str:
        ROLE_READS.append("read")
        return "manager"

    monkeypatch.setattr(cli, "_hub_role", manager)
    return {**placed, "lead_record": record}


@runs_gh
def test_merge_squashes_the_named_head_with_the_footer_left_out(
    lead: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    body = (
        "Card tsk-x.\n\nSays co-authored-by: in a sentence, which stays.\n"
        "Co-Authored-By: Someone <a@example.org>\n"
        "\U0001f916 Generated with [A Tool](https://example.org/tool)\n"
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
    assert "left out 2 footer line(s)" in capsys.readouterr().err
    assert ROLE_READS == ["read"]


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


def test_run_and_job_ids_take_up_to_twenty_digits_and_pr_numbers_ten() -> None:
    """Run and job ids already pass 10 digits; a pull request number keeps its cap."""
    assert ghpr.RUN_ID.fullmatch("44802593768") and ghpr.RUN_ID.fullmatch("136531499858")
    assert ghpr.RUN_ID.fullmatch("9" * 20) and not ghpr.RUN_ID.fullmatch("9" * 21)
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
    monkeypatch.setattr(cli, "_hub_role", lambda: role)
    err = refused(["gh", "pr", "ready", "2045"], capsys)
    assert "role manager" in err and ran(lead) is None


def test_a_hub_that_does_not_answer_refuses(
    lead: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def down() -> str:
        raise ghpr.Refused("the hub did not say this member's role: unreachable")

    monkeypatch.setattr(cli, "_hub_role", down)
    err = refused(["gh", "pr", "merge", "2045", "--match-head-commit", SHA, "--subject", "s",
                   "--body", "b"], capsys)  # fmt: skip
    assert "unreachable" in err and ran(lead) is None


@pytest.mark.parametrize("content", ["", "yes\n", "lead", "lead\nlead\n"])
def test_without_the_runners_lead_record_the_lead_commands_are_refused(
    lead: dict[str, Any], content: str, capsys: pytest.CaptureFixture[str]
) -> None:
    lead["lead_record"].write_text(content)
    refused(["gh", "pr", "ready", "2045"], capsys)
    assert ran(lead) is None and ROLE_READS == []


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
    def no_read() -> str:
        raise AssertionError("create and view read no role")

    monkeypatch.setattr(cli, "_hub_role", no_read)
    assert cli.main(["gh", "pr", "view", "7"]) == 0


def test_the_role_is_never_read_for_an_agent_served_with_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.Session, "for_target", "agt-other")
    with pytest.raises(ghpr.Refused, match="--for"):
        cli._hub_role()


class _Client:
    """A hub that answers `GET /me` for the credential that signed it, and records every call."""

    def __init__(self, me: Any) -> None:
        self.me = me
        self.calls: list[tuple[str, str]] = []

    def call(self, method: str, path: str, **_: Any) -> Any:
        self.calls.append((method, path))
        if isinstance(self.me, Exception):
            raise self.me
        return self.me


def _session(
    monkeypatch: pytest.MonkeyPatch, me: Any, local_member: str = "agt-manager"
) -> _Client:
    """A Session whose local state names `local_member` (a manager's id, say) while the hub
    authenticates the credential as whoever `me` describes."""
    client = _Client(me)

    class FakeSession:
        project = "oliver-zehentleitner/maity"

        def __init__(self) -> None:
            self.client = client
            self.data = {"member_id": local_member}

        @property
        def me(self) -> str:
            return local_member

    monkeypatch.setattr(cli, "Session", FakeSession)
    monkeypatch.setattr(FakeSession, "for_target", None, raising=False)
    return client


def test_the_role_is_the_authenticated_callers_not_the_local_member_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review A1720 of #2054: the local state may name a manager's id, but the hub answers
    `/me` for the credential that signed the call; that answer's role decides, and no
    member read by id is made."""
    me = {"member": {"id": "agt-coder"},
          "projects": [{"full_name": "oliver-zehentleitner/other", "role": "manager"},
                       {"full_name": "oliver-zehentleitner/maity", "role": "coder"}]}  # fmt: skip
    client = _session(monkeypatch, me, local_member="agt-manager")
    assert cli._hub_role() == "coder"
    assert client.calls == [("GET", "/me")]


@pytest.mark.parametrize(
    "me",
    [
        {"member": {"id": "agt-x"}, "projects": []},  # not a member of this project
        {"member": {"id": "agt-x"}, "projects": [{"full_name": "o/elsewhere", "role": "manager"}]},
        {"member": {"id": "agt-x"}},  # no list at all
        "not json",
    ],
)
def test_a_me_that_does_not_list_this_project_refuses(
    monkeypatch: pytest.MonkeyPatch, me: Any
) -> None:
    _session(monkeypatch, me)
    with pytest.raises(ghpr.Refused, match="no membership"):
        cli._hub_role()


def test_a_hub_error_on_me_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    _session(monkeypatch, hub.HubError("unreachable"))
    with pytest.raises(ghpr.Refused, match="did not say"):
        cli._hub_role()


def test_the_footer_filter_drops_whole_lines_only() -> None:
    text = (
        "Title line\n"
        "  co-authored-by: Lower Case <x@example.org>\r\n"
        "Thanks; Co-Authored-By: is named here in a sentence\n"
        "Generated with [Tool](https://example.org)\n"
        "Generated with care by hand\n"
    )
    kept, dropped = ghpr.strip_footer(text)
    assert dropped == 2
    assert kept == (
        "Title line\n"
        "Thanks; Co-Authored-By: is named here in a sentence\n"
        "Generated with care by hand\n"
    )
    assert ghpr.strip_footer("no footer") == ("no footer", 0)


def test_check_role_fails_closed() -> None:
    with pytest.raises(ghpr.Refused):
        ghpr.check_role(None)
    with pytest.raises(ghpr.Refused, match="no role"):
        ghpr.check_role(lambda: None)
    ghpr.check_role(lambda: "manager")
