from __future__ import annotations

from pathlib import Path

import pytest

from maity import cli, hub, state


def parse(*argv: str) -> object:
    return cli.build_parser().parse_args(list(argv))


def test_every_command_has_help(capsys: pytest.CaptureFixture[str]) -> None:
    for command in ("join", "resume", "wait", "report", "ask", "help"):
        with pytest.raises(SystemExit) as exit_info:
            cli.main([command, "--help"])
        assert exit_info.value.code == 0
        assert command in capsys.readouterr().out


def test_help_states_the_output_discipline(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "never a credential" in out
    assert "exit codes" in out


def test_join_requires_a_code() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["join", "https://hub.example/j/abc"])
    assert exit_info.value.code == cli.EXIT_USAGE


def test_wait_parses_timeout() -> None:
    args = parse("wait", "--timeout", "30")
    assert args.timeout == 30
    assert parse("wait").timeout == 600


def test_ask_collects_options() -> None:
    args = parse(
        "ask",
        "Tag 0.1.0?",
        "--to",
        "human",
        "--class",
        "consent",
        "--option",
        "yes",
        "--option",
        "no",
    )
    assert args.option == ["yes", "no"]
    assert args.request_class == "consent"
    assert args.priority == "normal"


def test_ask_rejects_unknown_class() -> None:
    with pytest.raises(SystemExit):
        parse("ask", "x", "--to", "human", "--class", "order")


def test_ask_with_a_single_option_is_a_usage_error(clone: Path) -> None:
    code = cli.main(["ask", "x", "--to", "human", "--class", "decision", "--option", "yes"])
    assert code == cli.EXIT_USAGE


def test_join_never_echoes_the_code(clone: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["join", "https://hub.example/j/abc", "--code", "SECRET-CODE"])
    assert code == cli.EXIT_NOT_IMPLEMENTED
    captured = capsys.readouterr()
    assert "SECRET-CODE" not in captured.out + captured.err


def test_join_refuses_when_already_joined(clone: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state.write_credential(state.resolve_state_dir(), "tok-123")
    assert cli.main(["join", "https://hub.example/j/abc", "--code", "C"]) == cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert "already holds" in captured.err
    assert "tok-123" not in captured.out + captured.err


def test_join_refuses_plain_http(clone: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["join", "http://hub.example/j/abc", "--code", "C"]) == cli.EXIT_ERROR
    assert "TLS" in capsys.readouterr().err


@pytest.mark.parametrize("command", [["resume"], ["wait"]])
def test_commands_need_a_joined_clone(
    clone: Path, command: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(command) == cli.EXIT_ERROR
    assert "maity join" in capsys.readouterr().err


def test_no_command_prints_the_credential(clone: Path, capsys: pytest.CaptureFixture[str]) -> None:
    directory = state.resolve_state_dir()
    state.write_credential(directory, "tok-very-secret")
    state.save_state(directory, {"hub": "https://hub.example"})
    for argv in (
        ["resume"],
        ["wait", "--timeout", "1"],
        ["ask", "q", "--to", "human", "--class", "info"],
        ["report", "--task", "T"],
    ):
        cli.main(argv)
        captured = capsys.readouterr()
        assert "tok-very-secret" not in captured.out + captured.err, argv


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
