"""`maity gh`: a placed agent's pull requests on its own clone's repository, nothing else.

One test per way around the pin that the review of #1663 named or the design ruled out:
bundled flags, another repository by option, URL or environment, a body file outside the
clone (a link, `..`, `.git`, the login file), gh's other file options, and a forged record
(cli/context/runner.md 9f43804d).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from maity import cli, ghpr

REPOSITORY = "github.com/oliver-zehentleitner/maity"


@pytest.fixture
def placed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A runner's clone with a pull-request record and a gh that writes down how it ran."""
    clone = tmp_path / "ws" / "maity" / "agent-3"
    (clone / ".git" / "maity").mkdir(parents=True)
    log = tmp_path / "gh.json"
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'cwd': os.getcwd(),"
        f" 'env': {{k: os.environ.get(k) for k in {list(ghpr.DROPPED_ENV)!r}}}}},"
        f" open({str(log)!r}, 'w'))\n"
    )
    gh.chmod(0o755)
    (clone / ghpr.PULL_REQUESTS_PATH).write_text(f"{REPOSITORY}\n{gh}\n")
    monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    monkeypatch.setenv("GIT_COMMON_DIR", str(clone / ".git"))
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


def test_create_runs_gh_on_the_recorded_repository_with_the_body_on_stdin(
    placed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_REPO", "other/repo")
    monkeypatch.setenv("GH_HOST", "evil.example")
    monkeypatch.setenv("GH_CONFIG_DIR", "/srv/elsewhere")
    (placed["clone"] / "body.md").write_text("Card tsk-x\n")
    assert cli.main(["gh", "pr", "create", "--title", "-R x", "--body-file", "body.md",
                     "--base", "main", "--draft"]) == 0  # fmt: skip
    call = ran(placed)
    assert call is not None
    assert call["argv"] == ["pr", "create", f"--repo={REPOSITORY}", "--title=-R x",
                            "--body-file=-", "--base=main", "--draft"]  # fmt: skip
    assert call["stdin"] == "Card tsk-x\n"
    assert call["cwd"] == str(placed["clone"].resolve())
    assert call["env"] == {name: None for name in ghpr.DROPPED_ENV}


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


def test_a_link_in_the_clone_to_a_file_outside_is_refused(
    placed: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (placed["clone"] / "body.md").symlink_to(login_file(tmp_path))
    err = refused(["gh", "pr", "create", "--title", "t", "--body-file", "body.md"], capsys)
    assert "not a file in this clone" in err and ran(placed) is None


def test_dot_dot_out_of_the_clone_is_refused(
    placed: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    login_file(tmp_path)
    up = "../../../home/.config/gh/hosts.yml"
    assert (placed["clone"] / up).exists()
    err = refused(["gh", "pr", "create", "--title", "t", "--body-file", up], capsys)
    assert "not a file in this clone" in err and ran(placed) is None


def test_a_file_under_the_clones_git_is_refused(
    placed: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    (placed["clone"] / ".git" / "maity" / "credential").write_text("dummysecret\n")
    err = refused(["gh", "pr", "create", "--title", "t",
                   "--body-file", ".git/maity/credential"], capsys)  # fmt: skip
    assert "under the clone's .git" in err and ran(placed) is None


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


def test_gh_exit_code_is_maitys(placed: dict[str, Any]) -> None:
    gh = Path(placed["gh"])
    gh.write_text("#!/bin/sh\nexit 7\n")
    assert cli.main(["gh", "pr", "view"]) == 7


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


def test_every_dropped_variable_names_a_repository_host_or_login() -> None:
    assert set(ghpr.DROPPED_ENV) >= {"GH_REPO", "GH_HOST", "GH_CONFIG_DIR"}
