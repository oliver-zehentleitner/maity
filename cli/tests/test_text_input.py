"""Free text from stdin (`-`) or a file, so the shell cannot run `code` spans in it, and a
warning where inline text looks like it already did."""

from __future__ import annotations

import io
from pathlib import Path

import fakehub
import pytest

from maity import cli

P = "/api/v1/projects/oliver/maity"
MARKDOWN = "Use `maity wait` and $(not run) here.\n\n```sh\nmaity resume\n```\n"


def _stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


@pytest.fixture
def events(fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", f"{P}/events")] = lambda s: (201, {"seq": 7})


def test_say_reads_the_message_from_stdin(
    joined: Path, fake: fakehub.FakeHub, events: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stdin(monkeypatch, MARKDOWN)
    assert cli.main(["say", "agt-a", "--type", "notice", "-"]) == cli.EXIT_OK
    assert fake.signed()[-1].json()["body"] == MARKDOWN.rstrip("\n")


def test_say_reads_the_message_from_a_file(
    joined: Path, fake: fakehub.FakeHub, events: None, tmp_path: Path
) -> None:
    (tmp_path / "m.md").write_text(MARKDOWN)
    argv = ["say", "agt-a", "--type", "notice", "--body-file", str(tmp_path / "m.md")]
    assert cli.main(argv) == cli.EXIT_OK
    assert fake.signed()[-1].json()["body"] == MARKDOWN


def test_a_chat_message_from_stdin(
    joined: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.routes[("POST", f"{P}/conversations/cnv-1/messages")] = lambda s: (201, {"seq": 8})
    _stdin(monkeypatch, "see `x`\n")
    assert cli.main(["say", "--chat", "cnv-1", "-"]) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"body": "see `x`"}


def test_ask_report_and_checkpoint_take_files_and_stdin(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.routes[("POST", f"{P}/requests")] = lambda s: (201, {"id": "req-1"})
    fake.routes[("POST", f"{P}/tasks/tsk-4/checkpoint")] = lambda s: (200, {})
    (tmp_path / "q.md").write_text("Use `a` or `b`?\nBoth work.\n")
    argv = ["ask", "--body-file", str(tmp_path / "q.md"), "--to", "human", "--class", "info"]
    assert cli.main(argv) == cli.EXIT_OK
    sent = fake.signed()[-1].json()
    assert (sent["title"], sent["summary"]) == ("Use `a` or `b`?", "Both work.")
    _stdin(monkeypatch, "ran `make check`\n")
    (tmp_path / "next.md").write_text("merge `main`")
    argv = ["checkpoint", "tsk-4", "-m", "-", "--next-file", str(tmp_path / "next.md"),
            "--no-code"]  # fmt: skip
    assert cli.main(argv) == cli.EXIT_OK
    sent = fake.signed()[-1].json()
    assert (sent["last_step"], sent["next_step"]) == ("ran `make check`", "merge `main`")


def test_report_summary_from_stdin(
    joined: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.routes[("POST", f"{P}/tasks/tsk-4/report")] = lambda s: (200, {"status": "review"})
    _stdin(monkeypatch, "Adds `--body-file`.\n")
    assert cli.main(["report", "--task", "tsk-4", "--summary", "-", "--no-code"]) == 0
    assert fake.signed()[-1].json()["summary"] == "Adds `--body-file`."


@pytest.mark.parametrize(
    "argv",
    [
        ["say", "agt-a", "hi", "--type", "notice", "--body-file", "m.md"],
        ["ask", "Go?", "--body-file", "m.md", "--to", "human", "--class", "info"],
        ["ask", "--to", "human", "--class", "info"],
        ["report", "--task", "tsk-4", "--no-code"],
        ["checkpoint", "tsk-4", "-m", "-", "--next", "-", "--no-code"],
        ["checkpoint", "tsk-4", "--next", "x", "--no-code"],
        ["say", "agt-a", "--type", "notice", "--body-file", "missing.md"],
    ],
)
def test_text_arguments_are_checked_before_sending(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:  # fmt: skip
    monkeypatch.chdir(tmp_path)
    (tmp_path / "m.md").write_text("x")
    _stdin(monkeypatch, "x")
    assert cli.main(argv) == cli.EXIT_USAGE
    assert fake.signed() == []


@pytest.mark.parametrize(
    ("text", "warned"),
    [
        ("call  now", True),  # `maity wait` between the words ran and printed nothing
        ("then run .", True),
        ("open `x", True),  # an odd backtick
        ("all good, `x` and `y`.", False),
        ("two lines\n\nare fine", False),
    ],
)
def test_inline_text_that_the_shell_ate_is_warned_about(
    joined: Path, fake: fakehub.FakeHub, events: None, capsys: pytest.CaptureFixture[str],
    text: str, warned: bool,
) -> None:  # fmt: skip
    assert cli.main(["say", "agt-a", text, "--type", "notice"]) == cli.EXIT_OK
    assert ("warning:" in capsys.readouterr().err) is warned
    assert fake.signed()[-1].json()["body"] == text
