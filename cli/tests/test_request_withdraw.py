"""Withdraw a request without changing the existing free-text ask grammar."""

from __future__ import annotations

import json
from pathlib import Path

import fakehub
import pytest

from maity import cli

BASE = "/api/v1/projects/oliver/maity/requests"
REQUEST = {"id": "req-4", "status": "withdrawn"}


@pytest.mark.parametrize("reason", [None, "Already settled — no answer needed."])
def test_withdraw_posts_once_with_an_optional_reason(
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    reason: str | None,
) -> None:
    fake.routes[("POST", f"{BASE}/req-4/withdraw")] = lambda s: (200, REQUEST)
    argv = ["request", "withdraw", "req-4"]
    if reason is not None:
        argv += ["--reason", reason]
    assert cli.main(argv) == cli.EXIT_OK
    assert len(fake.signed()) == 1
    assert fake.signed()[0].json() == ({} if reason is None else {"reason": reason})
    assert fake.signed()[0].headers.get("idempotency-key")
    assert capsys.readouterr().out == "withdrawn req-4\n"


def test_withdraw_json_prints_the_hubs_answer(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", f"{BASE}/req-4/withdraw")] = lambda s: (200, REQUEST)
    assert cli.main(["request", "withdraw", "req-4", "--json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == REQUEST


def test_withdraw_leaves_ownership_refusals_to_the_hub(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", f"{BASE}/req-4/withdraw")] = lambda s: (
        403,
        {"error": {"code": "forbidden", "message": "request withdrawal is forbidden"}},
    )
    assert cli.main(["request", "withdraw", "req-4"]) == cli.EXIT_ERROR
    assert len(fake.signed()) == 1
    assert "forbidden" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["req-4", "--to", "human"], ["req-4", "extra"]])
def test_withdraw_rejects_invalid_arguments_before_sending(
    joined: Path, fake: fakehub.FakeHub, argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(["request", "withdraw", *argv])
    assert exited.value.code == cli.EXIT_USAGE
    assert fake.signed() == []


def test_withdraw_rejects_an_empty_reason_before_sending(
    joined: Path, fake: fakehub.FakeHub
) -> None:
    assert cli.main(["request", "withdraw", "req-4", "--reason", " "]) == cli.EXIT_USAGE
    assert fake.signed() == []


@pytest.mark.parametrize("question", ["withdraw", "withdraw this request?"])
def test_a_question_can_start_with_withdraw(
    joined: Path, fake: fakehub.FakeHub, question: str
) -> None:
    fake.routes[("POST", BASE)] = lambda s: (201, {"id": "req-5", "status": "open"})
    assert cli.main(["ask", question, "--to", "human", "--class", "info"]) == cli.EXIT_OK
    assert fake.signed()[-1].json()["title"] == question


def test_withdraw_has_its_own_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(["request", "withdraw", "--help"])
    assert exited.value.code == 0
    help_text = capsys.readouterr().out
    assert "maity request withdraw" in help_text and "--reason" in help_text
    assert "--to" not in help_text and "--class" not in help_text


def test_personal_or_missing_request_keeps_the_hubs_not_found(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    path = f"{BASE}/req-4/withdraw"
    fake.routes[("POST", path)] = lambda s: (
        404,
        {"error": {"code": "not_found", "message": "no such request", "details": {}}},
    )
    assert cli.main(["request", "withdraw", "req-4"]) == cli.EXIT_ERROR
    assert "not_found: no such request" in capsys.readouterr().err
    assert [s.path for s in fake.signed() if s.method == "POST"] == [path]


def test_request_group_requires_an_action(joined: Path, fake: fakehub.FakeHub) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(["request"])
    assert exited.value.code == cli.EXIT_USAGE
    assert fake.signed() == []
