"""Signed request forwarding and claiming, with authority left to the hub."""

from __future__ import annotations

import json
from pathlib import Path

import fakehub
import pytest

from maity import cli

BASE = "/api/v1/projects/oliver/maity/requests/req-4"
REQUEST = {"id": "req-4", "status": "open", "title": "Review \u202ethis\x85 request"}


@pytest.mark.parametrize(
    ("target", "reason", "resolved"),
    [
        ("trust:admin", None, "trust:admin"),
        ("hum-1", "Needs a decision", "hum-1"),
        ("m", None, "hum-1"),
    ],
)
def test_forward_resolves_the_target_and_posts_once(
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    target: str,
    reason: str | None,
    resolved: str,
) -> None:
    fake.routes[("POST", f"{BASE}/forward")] = lambda s: (200, REQUEST)
    argv = ["request", "forward", "req-4", "--to", target]
    if reason is not None:
        argv += ["--reason", reason]
    assert cli.main(argv) == cli.EXIT_OK
    writes = [s for s in fake.signed() if s.method == "POST"]
    assert len(writes) == 1
    assert writes[0].json() == {"to": resolved, **({} if reason is None else {"reason": reason})}
    assert writes[0].headers.get("idempotency-key")
    assert capsys.readouterr().out == "forwarded req-4\n"


def test_claim_posts_an_empty_body_once(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", f"{BASE}/claim")] = lambda s: (200, REQUEST)
    assert cli.main(["request", "claim", "req-4"]) == cli.EXIT_OK
    assert len(fake.signed()) == 1
    assert fake.signed()[0].json() == {}
    assert fake.signed()[0].headers.get("idempotency-key")
    assert capsys.readouterr().out == "claimed req-4\n"


@pytest.mark.parametrize("action", ["forward", "claim"])
def test_json_preserves_the_answer_and_escapes_terminal_controls(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str], action: str
) -> None:
    fake.routes[("POST", f"{BASE}/{action}")] = lambda s: (200, REQUEST)
    argv = ["request", action, "req-4", "--json"]
    if action == "forward":
        argv += ["--to", "trust:admin"]
    assert cli.main(argv) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.isascii() and json.loads(out) == REQUEST


@pytest.mark.parametrize(
    ("action", "status", "code", "reason"),
    [
        ("forward", 403, "forbidden", "not_request_holder"),
        ("claim", 403, "forbidden", "humans_only"),
        ("claim", 409, "request_claimed", "already held"),
        ("forward", 404, "not_found", "no such request"),
        ("claim", 404, "not_found", "no such request"),
    ],
)
def test_hub_refusals_are_preserved_without_another_write(
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    action: str,
    status: int,
    code: str,
    reason: str,
) -> None:
    path = f"{BASE}/{action}"
    fake.routes[("POST", path)] = lambda s: (
        status,
        {"error": {"code": code, "message": reason, "details": {}}},
    )
    argv = ["request", action, "req-4"]
    if action == "forward":
        argv += ["--to", "trust:admin"]
    assert cli.main(argv) == cli.EXIT_ERROR
    assert f"{code}: {reason}" in capsys.readouterr().err
    assert [s.path for s in fake.signed() if s.method == "POST"] == [path]


@pytest.mark.parametrize(
    "argv",
    [
        ["forward", "req-4"],
        ["forward", "--to", "trust:admin"],
        ["claim"],
        ["claim", "req-4", "--to", "trust:admin"],
    ],
)
def test_missing_or_inapplicable_arguments_send_nothing(
    joined: Path, fake: fakehub.FakeHub, argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(["request", *argv])
    assert exited.value.code == cli.EXIT_USAGE
    assert fake.signed() == []


def test_an_empty_forwarding_reason_sends_nothing(joined: Path, fake: fakehub.FakeHub) -> None:
    argv = ["request", "forward", "req-4", "--to", "trust:admin", "--reason", " "]
    assert cli.main(argv) == cli.EXIT_USAGE
    assert fake.signed() == []
