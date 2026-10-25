from __future__ import annotations

import argparse
import json
import stat
import threading
import time
from pathlib import Path
from typing import Any

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
    assert cli.main(["join", "https://hub.example/j/abc"]) == cli.EXIT_USAGE


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
    "url",
    [
        "http://hub.example", "ftp://hub.example", "hub.example", "https://u:p@hub.example",
        "https://[x", "https://hub.example:abc", "https://hub.example:99999",
    ],
)  # fmt: skip
def test_hub_base_refuses(url: str) -> None:
    with pytest.raises(hub.HubError):
        hub.hub_base(url)


@pytest.mark.parametrize(
    ("url", "target"),
    [
        ("https://h/j/9fK2", "https://h/api/v1/join/9fK2"),
        ("https://h/join/9fK2", "https://h/api/v1/join/9fK2"),
        ("https://h/api/v1/join/9fK2/", "https://h/api/v1/join/9fK2"),
        ("https://join.h.example/9fK2", "https://join.h.example/9fK2"),
        ("https://join.h.example/9fK2/?x=1#y", "https://join.h.example/9fK2"),
    ],
)
def test_join_target(url: str, target: str) -> None:
    assert hub.join_target(url) == target


@pytest.mark.parametrize(
    "url",
    [
        "https://h/",
        "https://h",
        "https://h/j/",
        "https://h/join/",
        "https://h/j/a/b",
        "https://h/x/a",
    ],
)
def test_join_target_refuses(url: str) -> None:
    with pytest.raises(hub.HubError):
        hub.join_target(url)


@pytest.mark.parametrize(
    ("given", "header", "kept"),
    [
        ("https://join.maity.team/t", "https://maity.team", "https://maity.team"),
        ("https://maity.team/j/t", "https://maity.team/", "https://maity.team"),
        ("https://maity.team/j/t", None, "https://maity.team"),
        ("https://join.maity.team/t", "https://join.maity.team", "https://join.maity.team"),
        ("http://127.0.0.1:8/j/t", "http://127.0.0.1:9", "http://127.0.0.1:9"),
        ("https://maity.team./j/t", "https://maity.team", "https://maity.team"),
        (
            "https://join.bücher.example/t",
            "https://xn--bcher-kva.example",
            "https://xn--bcher-kva.example",
        ),
    ],
)
def test_accept_hub(given: str, header: str | None, kept: str) -> None:
    assert hub.accept_hub(given, header) == kept


@pytest.mark.parametrize(
    ("given", "header"),
    [
        ("https://join.maity.team/t", "https://evil.example"),
        ("https://join.maity.team/t", "http://maity.team"),  # plain HTTP off loopback
        ("https://join.maity.team/t", "https://u:p@maity.team"),
        ("https://join.maity.team/t", "https://team"),  # a parent without a dot
        ("https://a.join.maity.team/t", "https://maity.team"),  # grandparent
        ("https://maity.team/j/t", "https://join.maity.team"),  # a child, not a parent
        ("https://maity.team/j/t", "https://maity.team.evil.example"),
        ("https://maity.team/j/t", "not a url"),
        ("http://127.0.0.1:8/j/t", "https://0.0.1"),  # an address has no parent
        ("https://10.0.0.200/j/t", "https://0.0.200"),
        ("https://maity.team/j/t", "https://[x"),
        ("https://maity.team/j/t", "https://maity.team:abc"),
        ("https://maity.team/j/t", "https://maity.team.."),
        ("https://x\u3002join.maity.team/t", "https://maity.team"),  # 。 splits labels too
    ],
)
def test_accept_hub_refuses(given: str, header: str) -> None:
    with pytest.raises(hub.HubError, match="nothing was stored"):
        hub.accept_hub(given, header)


# --- join ---------------------------------------------------------------------------------


def test_join_stores_the_credential_and_never_prints_it(
    clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        ["join", f"{fake.url}/j/{fakehub.TOKEN}", "--code", fakehub.CODE, "--model", "m-1",
         "--pointer"]
    )  # fmt: skip
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


def test_join_on_a_join_host_posts_to_the_same_url(
    clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["join", f"{fake.url}/{fakehub.TOKEN}", "--code", fakehub.CODE])
    assert code == cli.EXIT_OK, output(capsys)
    assert [s.path for s in fake.seen if s.method == "POST"][0] == f"/{fakehub.TOKEN}"
    assert state.load_state(state.resolve_state_dir())["hub"] == fake.url


@pytest.mark.parametrize(
    "header", ["https://evil.example", "http://127.0.0.1.evil.example", "ftp://127.0.0.1"]
)
def test_join_refuses_a_hub_url_off_the_join_host_and_keeps_nothing(
    clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str], header: str
) -> None:
    fake.hub_header = header
    code = cli.main(["join", f"{fake.url}/j/{fakehub.TOKEN}", "--code", fakehub.CODE])
    assert code == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "nothing was stored" in err and fakehub.SECRET not in err
    directory = state.resolve_state_dir()
    assert not state.has_credential(directory)
    assert state.load_state(directory) == {}
    assert (
        not (clone / "AGENTS.md").exists() or pointer.BEGIN not in (clone / "AGENTS.md").read_text()
    )
    assert fake.signed() == []


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
    assert cli.main(["resume", "--json"]) == cli.EXIT_OK
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


def test_wait_ends_on_time_when_the_hub_stops_answering(
    joined: Path, fake: fakehub.FakeHub
) -> None:
    release = threading.Event()

    def hang(seen: fakehub.Seen) -> tuple[int, Any]:
        release.wait(30)
        return 200, {"items": [], "cursor": 0}

    fake.routes[("GET", "/api/v1/projects/maity/events")] = hang
    started = time.monotonic()
    try:
        assert cli.main(["wait", "--timeout", "3"]) == cli.EXIT_TIMEOUT
    finally:
        release.set()
    assert time.monotonic() - started < 4


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


def test_report_after_the_merge_deleted_the_branch(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clone = joined.parent.parent
    head = git(clone, "rev-parse", "HEAD")
    git(clone, "push", "--quiet", "origin", "--delete", "work")
    fake_gh(
        bin_dir,
        json.dumps([{"number": 12, "headRefOid": head, "state": "MERGED", "url": "https://x/12"}]),
    )
    fake.routes[("POST", "/api/v1/projects/maity/tasks/T/report")] = lambda s: (200, {})
    assert cli.main(["report", "--task", "T", "--summary", "s"]) == cli.EXIT_OK
    body = fake.signed()[-1].json()
    assert body["remote_head"] == body["head"] == head  # the merged pull request's head
    assert body["pr"]["state"] == "merged" and body["pr"]["head"] == head


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
    for call in (hub.hub_base, hub.join_target):
        try:
            call(url)
        except hub.HubError as exc:
            assert "hunter2" not in str(exc)


def test_safe_url_drops_userinfo_and_query() -> None:
    assert hub.safe_url("https://u:p@h.example:8443/j/t?code=X") == "https://h.example:8443/j/t"


@pytest.mark.parametrize(
    ("given", "header"),
    [
        ("https://x.0.0.1/j/t", "https://0.0.1"),  # an address is never a parent
        ("https://maity.team/j/t", "https://maity.team:0"),
    ],
)
def test_accept_hub_refuses_more(given: str, header: str) -> None:
    with pytest.raises(hub.HubError):
        hub.accept_hub(given, header)


def test_accept_hub_stores_the_normalised_url() -> None:
    assert hub.accept_hub("https://join.maity.team/t", "https://MAITY.team./") == (
        "https://maity.team"
    )
    assert hub.accept_hub("http://[::1]:8/j/t", "http://[::1]:9") == "http://[::1]:9"


def test_join_reads_url_and_code_from_stdin_and_skips_the_resume(
    clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    import io

    line = f"{fake.url}/j/{fakehub.TOKEN}\n{fakehub.CODE}\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(line))
    code = cli.main(["join", "--join-file", "-", "--no-resume", "--client", "maity-runner/9.9"])
    assert code == cli.EXIT_OK, capsys.readouterr().err
    exchange = [s for s in fake.seen if s.method == "POST"][0]
    assert exchange.json() == {"code": fakehub.CODE, "client": "maity-runner/9.9"}
    assert fake.signed() == []  # no resume
    assert state.has_credential(state.resolve_state_dir())


@pytest.mark.parametrize(
    "argv",
    [
        ["join", "--join-file", "-", "https://h/j/x"],
        ["join", "--join-file", "-", "--code", "C"],
    ],
)
def test_join_takes_the_line_from_one_place_only(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("https://h/j/x\nC\n"))
    assert cli.main(argv) == cli.EXIT_USAGE


def test_a_join_file_with_the_wrong_shape_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "line").write_text("https://h/j/x\n")
    assert cli.main(["join", "--join-file", str(tmp_path / "line")]) == cli.EXIT_USAGE


def test_resume_sends_the_runners_supervisor(
    joined: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAITY_SUPERVISOR", "maity-runner/0.1.0")
    assert cli.main(["resume", "--json"]) == cli.EXIT_OK
    assert fake.signed()[-1].json()["supervisor"] == "maity-runner/0.1.0"
    monkeypatch.delenv("MAITY_SUPERVISOR")
    assert cli.main(["resume", "--json"]) == cli.EXIT_OK
    assert "supervisor" not in fake.signed()[-1].json()


def test_a_supervisor_that_is_no_runner_is_refused(
    joined: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    monkeypatch.setenv("MAITY_SUPERVISOR", "secret-ish value " * 700)
    assert cli.main(["resume"]) == cli.EXIT_USAGE
    assert not fake.signed()
    err = capsys.readouterr().err
    assert "secret-ish" not in err and "(11900 characters)" in err


def test_a_hub_without_supervised_sessions_resumes_without(
    joined: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    monkeypatch.setenv("MAITY_SUPERVISOR", "maity-runner/0.1.0")
    packet = {"session": {"id": "ses-b-0004"}, "events": {"after": 0, "items": [], "cursor": 1},
              "me": {"member_id": "agt-b"}}  # fmt: skip

    def resume(seen: fakehub.Seen) -> tuple[Any, ...]:
        if "supervisor" in seen.json():
            return 400, {
                "error": {
                    "code": "invalid",
                    "message": "x",
                    "details": {"fields": {"supervisor": "extra_forbidden"}},
                }
            }
        return 200, packet

    fake.routes[("POST", "/api/v1/me/resume")] = resume
    assert cli.main(["resume", "--json"]) == cli.EXIT_OK
    assert "does not take the session's supervisor yet" in capsys.readouterr().err


@pytest.mark.parametrize("write_pointer", [False, True])
@pytest.mark.parametrize("no_resume", [False, True])
def test_join_names_maity_as_the_work_channel_after_the_pointer(
    clone: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    write_pointer: bool,
    no_resume: bool,
) -> None:
    args = ["join", f"{fake.url}/j/{fakehub.TOKEN}", "--code", fakehub.CODE]
    if write_pointer:
        args.append("--pointer")
    if no_resume:
        args.append("--no-resume")
    assert cli.main(args) == cli.EXIT_OK
    out = capsys.readouterr()
    lines = out.err.splitlines()
    assert lines[-1] == pointer.PROJECT_CHANNEL
    assert "main channel" in lines[-1]
    assert all(command in lines[-1] for command in ["maity say", "maity ask", "maity report"])
    if write_pointer:
        assert "wrote the Maity pointer block" in out.err
        assert pointer.PROJECT_CHANNEL in (clone / "AGENTS.md").read_text()
    else:
        assert out.err.index(pointer.END) < out.err.rindex(pointer.PROJECT_CHANNEL)
        assert not (clone / "AGENTS.md").exists()
    assert fakehub.SECRET not in out.err + out.out
    assert fakehub.CODE not in out.err + out.out


# --- join outside a Git clone -------------------------------------------------------------------


@pytest.fixture
def no_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A plain directory, no MAITY_STATE_DIR, and a home of the test's own."""
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    monkeypatch.delenv("MAITY_STATE_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_join_outside_a_clone_derives_the_identity_directory(
    no_clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["join", f"{fake.url}/join/{fakehub.TOKEN}", "--code", fakehub.CODE])
    out = output(capsys)
    assert code == cli.EXIT_OK, out
    host = fake.url.removeprefix("http://")
    directory = no_clone / ".local" / "state" / "maity" / host / "agent-b"
    assert state.credential_path(directory).read_bytes() == fakehub.CREDENTIAL.encode()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert f"export MAITY_STATE_DIR={directory}" in out
    assert fakehub.SECRET not in out and fakehub.CODE not in out
    assert fake.signed()[0].path == "/api/v1/me/resume"  # the first resume found it


def test_a_second_identity_outside_a_clone_gets_its_own_directory(
    no_clone: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = ["join", f"{fake.url}/join/{fakehub.TOKEN}", "--code", fakehub.CODE, "--no-resume"]
    assert cli.main(line) == cli.EXIT_OK
    monkeypatch.delenv("MAITY_STATE_DIR")  # what the first join set for its own resume
    fake.join_used, fake.join_handle = False, "agent-c"
    assert cli.main(line) == cli.EXIT_OK
    base = no_clone / ".local" / "state" / "maity" / fake.url.removeprefix("http://")
    assert state.has_credential(base / "agent-b") and state.has_credential(base / "agent-c")


def test_the_same_identity_outside_a_clone_is_refused_as_in_a_clone(
    no_clone: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    line = ["join", f"{fake.url}/join/{fakehub.TOKEN}", "--code", fakehub.CODE, "--no-resume"]
    assert cli.main(line) == cli.EXIT_OK
    monkeypatch.delenv("MAITY_STATE_DIR")
    fake.join_used = False
    assert cli.main(line) == cli.EXIT_ERROR
    assert "this directory already holds a session credential" in capsys.readouterr().err


def test_a_join_page_without_a_handle_keeps_the_refusal(
    no_clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.join_handle = "Not A Handle/.."
    code = cli.main(["join", f"{fake.url}/join/{fakehub.TOKEN}", "--code", fakehub.CODE])
    assert code == cli.EXIT_ERROR
    assert "not inside a Git clone" in capsys.readouterr().err
    assert not (no_clone / ".local").exists()
    assert not [s for s in fake.seen if s.method == "POST"]  # the code was not spent


@pytest.mark.parametrize("derived", [False, True])
def test_join_tightens_an_empty_state_directory_it_owns(
    derived: bool,
    no_clone: Path,
    fake: fakehub.FakeHub,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if derived:
        directory = no_clone / ".local" / "state" / "maity" / fake.url.removeprefix("http://")
        directory = directory / "agent-b"
    else:
        directory = no_clone / "agent"
        monkeypatch.setenv("MAITY_STATE_DIR", str(directory))
    directory.mkdir(parents=True)
    directory.chmod(0o755)  # a plain mkdir under a usual umask
    line = ["join", f"{fake.url}/join/{fakehub.TOKEN}", "--code", fakehub.CODE, "--no-resume"]
    assert cli.main(line) == cli.EXIT_OK, output(capsys)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert f"set {directory} to mode 0700 (it was 0755)" in capsys.readouterr().err
    assert state.has_credential(directory)


def test_join_never_loosens_the_rule_for_a_directory_with_a_credential(tmp_path: Path) -> None:
    directory = tmp_path / "agent"
    state.write_credential(directory, state.Secret(fakehub.CREDENTIAL))
    directory.chmod(0o755)
    assert state.tighten_for_join(directory) is None
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755
    with pytest.raises(state.StateError, match="accessible by group or others"):
        state.check_private(directory)


def test_a_directory_join_cannot_write_never_reaches_the_exchange(
    no_clone: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    directory = no_clone / "agent"
    directory.mkdir(parents=True)
    directory.chmod(0o500)  # private, but not writable
    monkeypatch.setenv("MAITY_STATE_DIR", str(directory))
    line = ["join", f"{fake.url}/join/{fakehub.TOKEN}", "--code", fakehub.CODE]
    try:
        assert cli.main(line) == cli.EXIT_ERROR
    finally:
        directory.chmod(0o700)
    assert "not writable" in capsys.readouterr().err
    assert not fake.join_used and not [s for s in fake.seen if s.method == "POST"]


def test_a_credential_refused_after_the_exchange_is_kept_elsewhere(
    no_clone: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    directory = no_clone / "agent"
    monkeypatch.setenv("MAITY_STATE_DIR", str(directory))
    real = state.write_credential

    def refuse_once(where: Path, value: state.Secret) -> Path:
        if where == directory.resolve():
            raise state.StateError("the disk said no")
        return real(where, value)

    monkeypatch.setattr(state, "write_credential", refuse_once)
    line = ["join", f"{fake.url}/join/{fakehub.TOKEN}", "--code", fakehub.CODE, "--no-resume"]
    assert cli.main(line) == cli.EXIT_OK
    err = capsys.readouterr().err
    (rescued,) = (no_clone / ".local" / "state" / "maity").glob("rescued-*")
    assert state.credential_path(rescued).read_bytes() == fakehub.CREDENTIAL.encode()
    assert stat.S_IMODE(rescued.stat().st_mode) == 0o700
    assert f"export MAITY_STATE_DIR={rescued}" in err and fakehub.SECRET not in err
    assert state.load_state(rescued)["member_id"] == "agt-b"
