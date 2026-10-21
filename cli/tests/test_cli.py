from __future__ import annotations

import argparse
import json
from pathlib import Path

import fakehub
import pytest
from conftest import fake_gh, git

from maity import cli, hub, pointer, state

COMMANDS = ("join", "resume", "wait", "report", "ask", "api", "help")


def parse(*argv: str) -> argparse.Namespace:
    return cli.build_parser().parse_args(list(argv))


def output(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


# --- parsing and help ---------------------------------------------------------------------


def test_every_command_has_help(capsys: pytest.CaptureFixture[str]) -> None:
    for command in COMMANDS:
        with pytest.raises(SystemExit) as exit_info:
            cli.main([command, "--help"])
        assert exit_info.value.code == 0
        assert command in capsys.readouterr().out


def test_help_states_the_output_discipline(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "never a credential" in out
    assert "6 wait superseded" in out


def test_join_requires_a_code() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["join", "https://hub.example/j/abc"])
    assert exit_info.value.code == cli.EXIT_USAGE


def test_wait_timeout_defaults_to_the_hint() -> None:
    assert parse("wait", "--timeout", "30").timeout == 30
    assert parse("wait").timeout is None


def test_ask_collects_options_and_tried() -> None:
    args = parse(
        "ask", "Tag 0.1.0?", "--to", "human", "--class", "consent", "--option", "yes",
        "--option", "no", "--tried", "checked the release list",
    )  # fmt: skip
    assert args.option == ["yes", "no"]
    assert args.request_class == "consent"
    assert args.priority == "normal"
    assert args.tried == "checked the release list"


def test_ask_rejects_unknown_class() -> None:
    with pytest.raises(SystemExit):
        parse("ask", "x", "--to", "human", "--class", "order")


def test_api_uppercases_the_method() -> None:
    assert parse("api", "post", "/projects/maity/tasks").method == "POST"


@pytest.mark.parametrize(
    ("url", "base"),
    [
        ("https://maity.team/j/abc?x=1", "https://maity.team"),
        ("https://hub.example:8443/", "https://hub.example:8443"),
        ("http://localhost:8000/j/abc", "http://localhost:8000"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
    ],
)
def test_hub_base(url: str, base: str) -> None:
    assert hub.hub_base(url) == base


@pytest.mark.parametrize(
    "url", ["http://hub.example", "ftp://hub.example", "hub.example", "https://u:p@hub.example"]
)
def test_hub_base_refuses(url: str) -> None:
    with pytest.raises(hub.HubError):
        hub.hub_base(url)


@pytest.mark.parametrize(
    ("url", "token"),
    [("https://h/j/9fK2", "9fK2"), ("https://h/api/v1/join/9fK2/", "9fK2")],
)
def test_join_token(url: str, token: str) -> None:
    assert hub.join_token(url) == token


@pytest.mark.parametrize("url", ["https://h/", "https://h/j/", "https://h/j/a/b", "https://h/x/a"])
def test_join_token_refuses(url: str) -> None:
    with pytest.raises(hub.HubError):
        hub.join_token(url)


# --- join ---------------------------------------------------------------------------------


def test_join_stores_the_credential_and_never_prints_it(
    clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        ["join", f"{fake.url}/j/{fakehub.TOKEN}", "--code", fakehub.CODE, "--model", "m-1"]
    )
    out = output(capsys)
    assert code == cli.EXIT_OK, out
    assert fakehub.SECRET not in out
    assert fakehub.CODE not in out
    directory = state.resolve_state_dir()
    assert state.credential_path(directory).read_bytes() == fakehub.CREDENTIAL.encode()
    data = state.load_state(directory)
    assert data["project"] == "maity" and data["member_id"] == "agt-b"
    assert data["session_id"] == "ses-b-0004" and data["cursor"] == 4231
    assert data["wait_timeout"] == 120 and data["model"] == "m-1"
    resume = fake.signed()[0]
    assert resume.path == "/api/v1/me/resume"
    assert resume.json()["model"] == "m-1"
    assert "idempotency-key" not in resume.headers
    assert pointer.BEGIN in (clone / "AGENTS.md").read_text()


def test_join_with_a_wrong_code_writes_nothing(
    clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["join", f"{fake.url}/j/{fakehub.TOKEN}", "--code", "WRONG"]) == 1
    assert "code_invalid" in capsys.readouterr().err
    assert not state.has_credential(state.resolve_state_dir())


def test_join_refuses_when_already_joined(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["join", f"{fake.url}/j/{fakehub.TOKEN}", "--code", "C"]) == cli.EXIT_ERROR
    out = output(capsys)
    assert "already holds" in out and fakehub.SECRET not in out
    assert not fake.seen


def test_join_refuses_plain_http(clone: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["join", "http://hub.example/j/abc", "--code", "C"]) == cli.EXIT_ERROR
    assert "TLS" in capsys.readouterr().err


def test_join_without_pointer(clone: Path, fake: fakehub.FakeHub) -> None:
    args = ["join", f"{fake.url}/j/{fakehub.TOKEN}", "--code", fakehub.CODE, "--no-pointer"]
    assert cli.main(args) == cli.EXIT_OK
    assert not (clone / "AGENTS.md").exists()


# --- resume, wait -------------------------------------------------------------------------


@pytest.mark.parametrize("command", [["resume"], ["wait"], ["api", "GET", "/me"]])
def test_commands_need_a_joined_clone(
    clone: Path, command: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(command) == cli.EXIT_ERROR
    assert "maity join" in capsys.readouterr().err


def test_resume_sends_the_cursor_and_prints_the_packet(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    data = state.load_state(joined)
    state.save_state(joined, {**data, "cursor": 17, "harness": "pi"})
    assert cli.main(["resume"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["session"]["id"] == "ses-b-0004"
    body = fake.signed()[-1].json()
    assert body["cursor"] == 17 and body["harness"] == "pi"
    assert body["client"].startswith("maity-cli/")


def test_wait_prints_the_first_event_and_advances_the_cursor(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.events = [{"seq": 5, "kind": "message"}, {"seq": 9, "kind": "task_claimed"}]
    assert cli.main(["wait", "--timeout", "5"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["seq"] == 5
    assert state.load_state(joined)["cursor"] == 5
    assert cli.main(["wait", "--timeout", "5"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["seq"] == 9
    query = fake.signed()[-1].query
    assert "after=5" in query and "wait=" in query


def test_wait_times_out_with_exit_3(joined: Path, fake: fakehub.FakeHub) -> None:
    assert cli.main(["wait", "--timeout", "1"]) == cli.EXIT_TIMEOUT


def test_wait_exits_6_when_superseded(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", "/api/v1/projects/maity/events")] = lambda s: (
        200,
        {"items": [], "cursor": 0, "superseded": True},
    )
    assert cli.main(["wait", "--timeout", "5"]) == cli.EXIT_SUPERSEDED
    assert "took over" in capsys.readouterr().err


def test_a_clock_skew_is_corrected_once(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.skew_once = True
    assert cli.main(["resume"]) == cli.EXIT_OK
    first, second = fake.signed()
    assert int(second.headers["maity-timestamp"]) > int(first.headers["maity-timestamp"]) + 10**9


# --- report, ask, api ---------------------------------------------------------------------


def test_report_sends_the_facts(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = git(joined.parent.parent, "rev-parse", "HEAD")
    fake_gh(
        bin_dir,
        json.dumps([{"number": 12, "headRefOid": head, "state": "OPEN", "url": "https://x/12"}]),
    )
    fake.routes[("POST", "/api/v1/projects/maity/tasks/tsk-0004/report")] = lambda s: (
        200,
        {"id": "tsk-0004", "status": "review"},
    )
    assert cli.main(["report", "--task", "tsk-0004", "--summary", "Adds leases."]) == cli.EXIT_OK
    assert "task is now review" in capsys.readouterr().out
    body = fake.signed()[-1].json()
    assert body == {
        "summary": "Adds leases.",
        "head": head,
        "branch": "work",
        "upstream": "origin/work",
        "remote_head": head,
        "pr": {"number": 12, "url": "https://x/12", "head": head, "state": "open"},
        "pr_status": "found",
        "pr_unknown_reason": None,
        "done": False,
    }


def test_report_without_gh_says_unknown(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", "/api/v1/projects/maity/tasks/T/report")] = lambda s: (200, {})
    assert cli.main(["report", "--task", "T", "--summary", "s"]) == cli.EXIT_OK
    body = fake.signed()[-1].json()
    assert body["pr"] is None and body["pr_status"] == "unknown"
    assert body["pr_unknown_reason"] == "gh is not installed"


def test_report_refuses_before_sending(joined: Path, fake: fakehub.FakeHub) -> None:
    (joined.parent.parent / "a.txt").write_text("dirty\n")
    assert cli.main(["report", "--task", "T", "--summary", "s"]) == cli.EXIT_REFUSED
    assert not fake.seen


def test_ask_builds_the_request(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", "/api/v1/projects/maity/requests")] = lambda s: (
        201,
        {"id": "req-0012", "class": "decision", "status": "open"},
    )
    question = "Merge #12 before tagging?\nThe release needs both."
    args = ["ask", question, "--to", "human", "--class", "decision", "--option", "yes",
            "--option", "no", "--tried", "read the list", "--task", "tsk-1"]  # fmt: skip
    assert cli.main(args) == cli.EXIT_OK
    assert "req-0012" in capsys.readouterr().out
    assert fake.signed()[-1].json() == {
        "class": "decision",
        "title": "Merge #12 before tagging?",
        "summary": "The release needs both.",
        "tried": "read the list",
        "options": [{"id": "o1", "label": "yes"}, {"id": "o2", "label": "no"}],
        "priority": "normal",
        "task_id": "tsk-1",
    }


def test_ask_to_a_role_sets_to(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", "/api/v1/projects/maity/requests")] = lambda s: (201, {"id": "r"})
    assert cli.main(["ask", "Which port?", "--to", "role:admin", "--class", "info"]) == 0
    assert fake.signed()[-1].json()["to"] == "role:admin"


@pytest.mark.parametrize(
    ("question", "extra"),
    [
        ("q", ["--class", "decision", "--option", "only-one"]),
        ("q", ["--class", "info", *[a for i in range(9) for a in ("--option", str(i))]]),
        ("x" * 201, ["--class", "info"]),
        ("  ", ["--class", "info"]),
    ],
)
def test_ask_usage_errors(
    joined: Path, fake: fakehub.FakeHub, question: str, extra: list[str]
) -> None:
    assert cli.main(["ask", question, "--to", "human", *extra]) == cli.EXIT_USAGE
    assert not fake.seen


def test_a_credential_in_a_body_is_refused_locally(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    leak = "mty1.crd-x-0001.abcdefABCDEF0123456789"
    assert cli.main(["ask", f"Is {leak} valid?", "--to", "human", "--class", "info"]) == 1
    out = output(capsys)
    assert "credential format" in out and leak not in out
    assert not fake.seen


def test_api_passthrough_is_signed_and_idempotent(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", "/api/v1/projects/maity/tasks/tsk-1/claim")] = lambda s: (
        200,
        {"id": "tsk-1", "status": "in_progress", "echo": s.json()},
    )
    body = tmp_path / "claim.json"
    body.write_text('{"reason": "fix"}')
    args = ["api", "POST", "/projects/maity/tasks/tsk-1/claim", "--json", str(body)]
    assert cli.main(args) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["echo"] == {"reason": "fix"}
    assert len(fake.signed()[-1].headers["idempotency-key"]) >= 16


def test_api_query_is_signed(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", "/api/v1/projects/maity/tasks")] = lambda s: (200, {"items": []})
    args = ["api", "GET", "/projects/maity/tasks", "--query", "status=open,review",
            "--query", "limit=200"]  # fmt: skip
    assert cli.main(args) == cli.EXIT_OK
    assert fake.signed()[-1].query == "limit=200&status=open%2Creview"


def test_help_fetches_the_hub_help(
    fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["help", "--hub", fake.url]) == cli.EXIT_OK
    assert capsys.readouterr().out == "# Maity help\n"


def test_no_command_prints_the_credential(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    for argv in (
        ["resume"],
        ["wait", "--timeout", "1"],
        ["ask", "q", "--to", "human", "--class", "info"],
        ["report", "--task", "T", "--summary", "s"],
        ["api", "GET", "/projects/maity/nothing"],
    ):
        cli.main(argv)
        assert fakehub.SECRET not in output(capsys), argv


def test_resume_adopts_a_credential_from_the_page_driven_join(
    clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", "/api/v1/me/resume")] = lambda s: (
        200,
        {"session": {"id": "s1"}, "project": {"slug": "maity"}, "me": {"member_id": "agt-b"}},
    )
    directory = state.resolve_state_dir()
    directory.mkdir(mode=0o700)
    (directory / "credential").write_text(fakehub.CREDENTIAL)  # what `curl -o` leaves behind
    (directory / "credential").chmod(0o600)
    assert cli.main(["resume"]) == cli.EXIT_ERROR
    assert "--hub" in capsys.readouterr().err
    assert cli.main(["resume", "--hub", fake.url]) == cli.EXIT_OK
    data = state.load_state(directory)
    assert data["hub"] == fake.url and data["project"] == "maity" and data["member_id"] == "agt-b"


def test_a_redirect_is_refused_not_followed(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.redirects["/api/v1/me/resume"] = "http://elsewhere.example/steal"
    assert cli.main(["resume"]) == cli.EXIT_ERROR
    assert "redirect" in capsys.readouterr().err
    assert [s.path for s in fake.seen] == ["/api/v1/me/resume"]


def test_help_refuses_a_redirect(fake: fakehub.FakeHub) -> None:
    fake.redirects["/api/v1/help"] = f"{fake.url}/elsewhere"
    with pytest.raises(hub.HubError, match="redirect"):
        hub.get_text(f"{fake.url}/api/v1/help")


@pytest.mark.parametrize(
    "url", ["ftp://user:hunter2@hub.example/x", "https://user:hunter2@hub.example/j/t"]
)
def test_userinfo_is_never_echoed(url: str) -> None:
    for call in (hub.hub_base, hub.join_token):
        try:
            call(url)
        except hub.HubError as exc:
            assert "hunter2" not in str(exc)


def test_safe_url_drops_userinfo_and_query() -> None:
    assert hub.safe_url("https://u:p@h.example:8443/j/t?code=X") == "https://h.example:8443/j/t"
