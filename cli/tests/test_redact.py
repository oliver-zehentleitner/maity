"""No credential in a URL reaches what maity prints or sends (§13, tsk-r31sb7ag0spv)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import fakehub
import pytest
from conftest import fake_gh, git

from maity import cli, gitfacts
from maity.redact import without_userinfo
from maity.runner import config

SECRET = "ghs_s3cret"
TOKEN_URL = f"https://x-access-token:{SECRET}@github.com/acme/widget.git"


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (TOKEN_URL, "https://github.com/acme/widget.git"),
        ("https://tok@github.com/a/b", "https://github.com/a/b"),
        ("ssh://git@host.example:22/a/b", "ssh://host.example:22/a/b"),
        (
            f"fatal: unable to access '{TOKEN_URL}/': 403",
            "fatal: unable to access 'https://github.com/acme/widget.git/': 403",
        ),
        # An `@` in the user or the password: up to the last `@` before the path (#789).
        ("https://user@example.com:secret@github.com/a.git", "https://github.com/a.git"),
        ("https://user:p@ss@github.com/o/r", "https://github.com/o/r"),
        ("https://u:p#@h/r", "https://h/r"),
        ("https://u:p?x@h/r", "https://h/r"),
        ("https://u%40x:p%23@h/r", "https://h/r"),
        ("https://tok@[::1]:8080/r", "https://[::1]:8080/r"),
        ("https://user@h/a@b", "https://h/a@b"),  # an `@` in the path stays
        ("git+https://tok@github.com/o/r", "git+https://github.com/o/r"),
        ("HTTPS://TOK@H/r", "HTTPS://H/r"),
        ("'https://a:b@h/x' and 'https://c:d@g/y'", "'https://h/x' and 'https://g/y'"),
        ("<https://a:b@h/x> (https://c:d@g/y)", "<https://h/x> (https://g/y)"),
        ("`https://tok@h/r`", "`https://h/r`"),
        ("`https://h` and me@x.com", "`https://h` and me@x.com"),  # whitespace ends a URL
        # A quote, backtick or bracket does not end the userinfo when an `@` follows before the
        # path: it may stand unencoded in a password (#792). A URL without a path that runs
        # into text with an `@` then shows the wrong host, which leaks nothing.
        ("`https://h`,me@x.com", "`https://x.com"),
        ("git@github.com:acme/widget.git", "git@github.com:acme/widget.git"),
        ("https://github.com/a/b", "https://github.com/a/b"),
        ("origin", "origin"),
    ],
)
def test_userinfo_is_taken_out_of_every_url(text: str, shown: str) -> None:
    assert without_userinfo(text) == shown


@pytest.mark.parametrize("char", ["`", "'", '"', "(", ")", "<", ">"])
def test_a_password_with_a_quote_or_bracket_goes_entirely(char: str) -> None:
    assert (
        without_userinfo(f"push to https://u:pa{char}ss@h/r failed") == "push to https://h/r failed"
    )
    assert without_userinfo(f"'https://u:pa{char}ss@h'") == "'https://h'"


def _upstream_is_the_token_url(clone: Path) -> None:
    """`git push -u <url> work`: the branch's remote is the URL itself, token included;
    git is sent to the bare repository the clone came from."""
    bare = clone.parent / "remote.git"
    git(clone, "config", "--add", f"url.{bare}.insteadOf", TOKEN_URL)
    git(clone, "config", "branch.work.remote", TOKEN_URL)


def test_a_deleted_branch_names_its_upstream_without_the_token(clone: Path) -> None:
    _upstream_is_the_token_url(clone)
    git(clone, "push", "--quiet", "origin", "--delete", "work")
    problems = gitfacts.mismatches(gitfacts.collect(clone))
    assert any("does not exist on https://github.com/acme/widget.git" in p for p in problems)
    assert SECRET not in json.dumps(problems)


def test_report_refused_on_a_deleted_branch_prints_no_token(
    joined: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clone = joined.parent.parent
    _upstream_is_the_token_url(clone)
    git(clone, "push", "--quiet", "origin", "--delete", "work")
    assert cli.main(["report", "--task", "tsk-0004", "--summary", "s"]) == cli.EXIT_REFUSED
    captured = capsys.readouterr()
    assert "report refused" in captured.err
    assert SECRET not in captured.out + captured.err


def test_report_sends_the_upstream_without_the_token(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _upstream_is_the_token_url(joined.parent.parent)
    fake.routes[("POST", "/api/v1/projects/oliver/maity/tasks/tsk-0004/report")] = lambda s: (
        200,
        {"id": "tsk-0004", "status": "review"},
    )
    assert cli.main(["report", "--task", "tsk-0004", "--summary", "s"]) == cli.EXIT_OK
    body = fake.signed()[-1].json()
    assert body["upstream"] == "https://github.com/acme/widget.git/work"
    assert SECRET not in json.dumps(body) + capsys.readouterr().out


def test_a_gh_error_that_repeats_the_url_loses_the_token(clone: Path, bin_dir: Path) -> None:
    fake_gh(bin_dir, "", exit_code=1, stderr=f"could not read {TOKEN_URL}")
    with pytest.raises(gitfacts.FactsError) as raised:
        gitfacts.collect(clone)
    assert "could not read https://github.com/acme/widget.git" in str(raised.value)
    assert SECRET not in str(raised.value)


def test_a_git_error_that_repeats_the_url_loses_the_token(clone: Path) -> None:
    git(clone, "config", "branch.work.remote", TOKEN_URL)  # no insteadOf: ls-remote fails
    git(clone, "config", "protocol.https.allow", "never")  # without touching the network
    with pytest.raises(gitfacts.FactsError) as raised:
        gitfacts.collect(clone)
    assert str(raised.value).startswith("git ls-remote failed:")
    assert SECRET not in str(raised.value)


def test_the_runner_prints_a_claimed_clones_origin_without_the_token(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_operate import setup

    path = setup(tmp_path)
    cfg = config.load(path)
    assert cfg.local is not None
    clone = cfg.local.workspaces / "maity" / "agent-h"
    clone.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "remote", "add", "origin", TOKEN_URL], check=True)
    claim = ["runner", "workspace", "claim", "maity/agent-h", "--agent", "agt-h"]
    assert cli.main([*claim, "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert "(origin https://github.com/acme/widget.git)" in out
    assert SECRET not in out


def test_an_unreachable_url_is_named_without_its_userinfo() -> None:
    from maity import hub

    with pytest.raises(hub.HubError) as raised:
        hub.get_text(f"http://user:{SECRET}@127.0.0.1:9/skill", timeout=2)  # port 9: discard
    assert "cannot reach http://127.0.0.1:9/skill" in str(raised.value)
    assert SECRET not in str(raised.value)


def test_a_url_remote_on_github_is_asked_about_its_pull_request(clone: Path, bin_dir: Path) -> None:
    """A branch pushed with `-u <url>`: its host is read from the URL itself."""
    _upstream_is_the_token_url(clone)
    head = git(clone, "rev-parse", "HEAD")
    fake_gh(bin_dir, json.dumps([{"number": 3, "headRefOid": head, "state": "OPEN", "url": "u"}]))
    facts = gitfacts.collect(clone)
    assert facts.pr_unknown_reason is None and facts.pr is not None and facts.pr.number == 3


def test_runner_gc_names_a_config_section_without_its_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_operate import revoked_clone

    path, place = revoked_clone(tmp_path, monkeypatch)
    with (place.path / ".git" / "config").open("a") as fh:
        fh.write(f'[http "{TOKEN_URL}"]\n\textraHeader = x\n')
    assert cli.main(["runner", "gc", "--revoked", "--yes", "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert "not inspected" in out and "http.https://github.com/acme/widget.git" in out
    assert SECRET not in out
