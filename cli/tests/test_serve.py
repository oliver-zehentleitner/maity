from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli, hub, state
from maity.runner import capabilities, config, serve

CONFIG = """\
[hub]
url = "{url}"
state_dir = "{state_dir}"

[limits]
projects = ["maity"]
repositories = ["github.com/oliver-zehentleitner/maity"]

[harness.stub]
"""

PLACEMENT = {"id": "plc-0003", "project": "maity", "generation": 4, "desired": "running"}


def load(tmp_path: Path, url: str = "https://hub.example") -> config.Config:
    path = tmp_path / "runner.toml"
    path.write_text(CONFIG.format(url=url, state_dir=tmp_path / "st"))
    return config.load(path)


def err(status: int | None, code: str | None = None, retry_after: float | None = None) -> Any:
    error = hub.HubError(f"{status} {code}", code=code, status=status)
    error.retry_after = retry_after
    return error


class Script:
    """A client answering each call from a list: (method path, answer or exception)."""

    def __init__(self, *steps: tuple[str, Any]) -> None:
        self.steps = list(steps)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        self.calls.append((f"{method} {path}", kwargs))
        if not self.steps:
            raise serve.Stop
        expected, answer = self.steps.pop(0)
        assert expected == f"{method} {path}", (expected, method, path)
        if isinstance(answer, BaseException):
            raise answer
        return answer


RUNNER = {"id": "rnr-0002", "name": "home", "session_id": "rses-1"}
HELLO = ("POST /runner/hello", {"runner": RUNNER, "placements": [PLACEMENT], "cursor": 5120})


def events(*items: Any, cursor: int = 5121, superseded: bool = False) -> tuple[str, Any]:
    return (
        "GET /runner/events",
        {"items": list(items), "cursor": cursor, "superseded": superseded},
    )


def placements(*items: Any) -> tuple[str, Any]:
    return ("GET /runner/placements", {"items": list(items)})


class Clock:
    def __init__(self, poll_seconds: float = 1.0) -> None:
        self.now = 1000.0
        self.poll_seconds = poll_seconds
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def service(tmp_path: Path, script: Script, clock: Clock | None = None, **kwargs: Any) -> Any:
    cfg = load(tmp_path)
    clock = clock or Clock()
    seen: list[list[dict[str, Any]]] = []

    def call(method: str, path: str, **kw: Any) -> Any:
        if path == "/runner/events":
            clock.now += clock.poll_seconds
        return script.call(method, path, **kw)

    client: Any = type("C", (), {"call": staticmethod(call)})()
    svc = serve.Service(
        cfg, client, {"backend": "local"}, reconcile=seen.append,
        sleep=clock.sleep, monotonic=clock.monotonic, rand=lambda: 0.5, **kwargs,
    )  # fmt: skip
    return svc, seen, clock


def run(svc: serve.Service) -> int | None:
    try:
        return svc.run()
    except serve.Stop:
        return None


# --- the loop --------------------------------------------------------------------------------


def test_hello_then_a_wake_rereads_the_placements(tmp_path: Path) -> None:
    other = {**PLACEMENT, "id": "plc-0004"}
    script = Script(HELLO, events({"seq": 5121}), placements(PLACEMENT, other), events())
    svc, seen, _ = service(tmp_path, script)
    assert run(svc) is None
    hello = script.calls[0][1]["body"]
    assert hello["client"] == hub.CLIENT and hello["actual"] == []
    assert script.calls[1][1]["query"] == [("after", "5120"), ("wait", "55")]
    assert script.calls[1][1]["timeout"] == serve.POLL_WAIT + serve.POLL_SLACK
    assert script.calls[3][1]["query"][0] == ("after", "5121")
    assert [len(p) for p in seen] == [1, 2]


def test_an_empty_poll_does_not_reread_until_the_interval(tmp_path: Path) -> None:
    script = Script(HELLO, events(), events(), placements(), events())
    clock = Clock(poll_seconds=serve.REREAD_INTERVAL / 2)
    svc, seen, _ = service(tmp_path, script, clock)
    run(svc)
    paths = [c[0] for c in script.calls]
    assert paths[:4] == [
        "POST /runner/hello", "GET /runner/events", "GET /runner/events", "GET /runner/placements"
    ]  # fmt: skip
    assert len(seen) == 2


def test_a_lost_connection_backs_off_with_jitter_and_says_hello_again(tmp_path: Path) -> None:
    script = Script(
        HELLO, ("GET /runner/events", err(None)),
        ("POST /runner/hello", err(503)),
        HELLO, events(),
    )  # fmt: skip
    svc, _, clock = service(tmp_path, script)
    run(svc)
    assert clock.slept == [0.5 * 2, 0.5 * 4]  # rand 0.5 × min(60, 2^attempt)
    assert [c[0] for c in script.calls].count("POST /runner/hello") == 3


def test_the_backoff_is_capped_and_reset_by_a_long_poll(tmp_path: Path) -> None:
    failures = [("POST /runner/hello", err(None))] * 8
    script = Script(*failures, HELLO, events(), ("GET /runner/events", err(502)), HELLO)
    clock = Clock(poll_seconds=serve.BACKOFF_RESET)
    svc, _, _ = service(tmp_path, script, clock)
    run(svc)
    assert clock.slept[:8] == [0.5 * min(60, 2**n) for n in range(1, 9)]
    assert clock.slept[8] == 0.5 * 2  # after a 30 s long-poll the count starts again


def test_retry_after_is_honoured(tmp_path: Path) -> None:
    script = Script(("POST /runner/hello", err(429, "rate_limited", retry_after=42)), HELLO)
    svc, _, clock = service(tmp_path, script)
    run(svc)
    assert clock.slept == [42]


def test_a_clock_skew_backs_off_instead_of_ending(tmp_path: Path) -> None:
    script = Script(("POST /runner/hello", err(401, "timestamp_skew")), HELLO)
    svc, _, clock = service(tmp_path, script)
    run(svc)
    assert len(clock.slept) == 1


@pytest.mark.parametrize(
    ("failure", "words"),
    [
        (err(401, "credential_revoked"), "revoked"),
        (err(401, "unauthenticated"), "refuses"),
        (err(404, "not_found"), "refuses"),
        (err(400, "invalid"), "refuses"),
    ],
)
def test_answers_retrying_cannot_fix_end_with_78(
    tmp_path: Path, failure: Any, words: str, capsys: pytest.CaptureFixture[str]
) -> None:
    script = Script(HELLO, ("GET /runner/events", failure))
    svc, _, clock = service(tmp_path, script)
    assert run(svc) == serve.EXIT_CONFIG
    assert clock.slept == []
    assert words in capsys.readouterr().err
    status = state.load_state(tmp_path / "st", name=serve.STATUS_FILE)
    assert status["connected"] is False and words in status["error"]


def test_a_second_service_taking_the_stream_ends_this_one(tmp_path: Path) -> None:
    script = Script(HELLO, events(superseded=True))
    svc, _, _ = service(tmp_path, script)
    assert run(svc) == serve.EXIT_CONFIG


def test_status_file_after_hello(tmp_path: Path) -> None:
    script = Script(HELLO)
    svc, _, _ = service(tmp_path, script)
    run(svc)
    status = state.load_state(tmp_path / "st", name=serve.STATUS_FILE)
    assert status["connected"] is True and status["session_id"] == "rses-1"
    assert status["pid"] == os.getpid() and status["cursor"] == 5120
    assert status["placements"] == [PLACEMENT]


# --- capabilities ----------------------------------------------------------------------------


def fake_tool(bin_dir: Path, name: str, output: str, code: int = 0) -> None:
    script = bin_dir / name
    script.write_text(f"#!/bin/sh\necho '{output}'\nexit {code}\n")
    script.chmod(0o755)


def test_capabilities(tmp_path: Path, bin_dir: Path) -> None:
    fake_tool(bin_dir, "claude", "2.1.308 (Claude Code)")
    fake_tool(bin_dir, "codex", "broken", code=1)
    path = tmp_path / "runner.toml"
    path.write_text(
        CONFIG.format(url="https://hub.example", state_dir=tmp_path / "st")
        + '\n[harness.claude-code]\nmodes = ["interactive", "supervised"]\nmodels = ["opus"]\n'
        + "\n[harness.codex]\n"
    )
    cfg = config.load(path)
    probes = {h.id: capabilities.probe(h, str(bin_dir)) for h in cfg.harnesses.values()}
    caps = capabilities.build(cfg, probes)
    by_id = {h["id"]: h for h in caps["harnesses"]}
    assert by_id["claude-code"] == {
        "id": "claude-code", "version": "2.1.308", "available": True, "reason": None,
        "modes": ["interactive", "supervised"], "default_mode": "interactive",
        "models": ["opus"], "targets": ["local"], "confinement": "allowlist", "sandbox": "off",
    }  # fmt: skip
    assert by_id["codex"]["available"] is False and by_id["codex"]["reason"] == "version_failed"
    missing = config.Harness("codex", ("supervised",), "supervised", binary="no-such-codex")
    assert capabilities.probe(missing, str(bin_dir)).reason == "binary_not_found"
    assert by_id["stub"]["confinement"] == "none" and by_id["stub"]["sandbox"] == "n/a"
    assert caps["projects"] == ["maity"] and caps["backend"] == "local"
    assert caps["targets"][0]["isolation"]["kind"] == "shared_user"
    text = json.dumps(caps)
    assert all(32 <= ord(c) < 127 for c in text)


def test_ascii_text() -> None:
    assert capabilities.ascii_text("a‮b\x01c" + "x" * 300) == "abc" + "x" * 197


# --- end to end against the fake hub, signed -------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


def paired(tmp_path: Path, fake: fakehub.FakeHub) -> Path:
    path = tmp_path / "runner.toml"
    path.write_text(CONFIG.format(url=fake.url, state_dir=tmp_path / "st"))
    path.chmod(0o600)
    code = cli.main(
        ["runner", "pair", f"{fake.url}/r/{fakehub.PAIR_TOKEN}", "--code", fakehub.PAIR_CODE,
         "--config", str(path)]
    )  # fmt: skip
    assert code == 0
    return path


def route(answers: list[Any]) -> Callable[[fakehub.Seen], tuple[Any, ...]]:
    def answer(seen: fakehub.Seen) -> tuple[Any, ...]:
        result: tuple[Any, ...] = answers.pop(0) if len(answers) > 1 else answers[0]
        return result

    return answer


def test_serve_end_to_end_signed_with_the_runner_credential(
    tmp_path: Path, home: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    path = paired(tmp_path, fake)
    fake.routes[("POST", "/api/v1/runner/hello")] = route(
        [(200, {"runner": {"id": "rnr-0002", "name": "home", "session_id": "rses-1"},
                "placements": [], "cursor": 7})]
    )  # fmt: skip
    fake.routes[("GET", "/api/v1/runner/events")] = route(
        [(200, {"items": [{"seq": 8}], "cursor": 8, "superseded": False}),
         (200, {"items": [], "cursor": 8, "superseded": True})]
    )  # fmt: skip
    fake.routes[("GET", "/api/v1/runner/placements")] = route([(200, {"items": [PLACEMENT]})])
    assert cli.main(["runner", "serve", "--config", str(path)]) == serve.EXIT_CONFIG
    runner_calls = [s for s in fake.signed() if s.path.startswith("/api/v1/runner/")]
    assert [s.path for s in runner_calls] == [
        "/api/v1/runner/hello", "/api/v1/runner/events", "/api/v1/runner/placements",
        "/api/v1/runner/events",
    ]  # fmt: skip
    assert all(
        s.headers["authorization"] == f"Maity-HMAC {fakehub.RUNNER_CREDENTIAL_ID}"
        for s in runner_calls
    )
    assert "idempotency-key" not in runner_calls[0].headers
    assert runner_calls[0].json()["capabilities"]["harnesses"][0]["id"] == "stub"
    err = capsys.readouterr().err
    assert fakehub.SECRET not in err and "took over the event stream" in err
    capsys.readouterr()
    assert cli.main(["runner", "status", "--config", str(path), "--json"]) == 0
    view = json.loads(capsys.readouterr().out)
    assert view["runner_id"] == "rnr-0002" and view["placements"] == [PLACEMENT]


def test_serve_refuses_to_start_without_a_credential(
    tmp_path: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "runner.toml"
    path.write_text(CONFIG.format(url="https://hub.example", state_dir=tmp_path / "st"))
    assert cli.main(["runner", "serve", "--config", str(path)]) == serve.EXIT_CONFIG
    assert "maity runner pair" in capsys.readouterr().err


def test_serve_refuses_a_credential_of_another_hub(
    tmp_path: Path, home: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    path = paired(tmp_path, fake)
    path.write_text(path.read_text().replace(fake.url, "https://other.example"))
    assert cli.main(["runner", "serve", "--config", str(path)]) == serve.EXIT_CONFIG
    assert "pair again for this hub" in capsys.readouterr().err


def test_serve_with_a_broken_configuration_exits_78(
    tmp_path: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "runner.toml"
    path.write_text('[hub]\nurl = "https://h.example"\ntypo = 1\n')
    assert cli.main(["runner", "serve", "--config", str(path)]) == serve.EXIT_CONFIG
    assert "hub.typo: unknown key" in capsys.readouterr().err


def test_status_without_a_service(
    tmp_path: Path, home: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    path = paired(tmp_path, fake)
    capsys.readouterr()
    assert cli.main(["runner", "status", "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert "rnr-0002" in out and "not running" in out


def test_sigterm_stops_polling_and_exits_0(
    tmp_path: Path, home: Path, fake: fakehub.FakeHub
) -> None:
    import signal
    import subprocess
    import time

    path = paired(tmp_path, fake)

    def slow_poll(seen: fakehub.Seen) -> tuple[Any, ...]:
        time.sleep(0.2)
        return (200, {"items": [], "cursor": 7, "superseded": False})

    fake.routes[("POST", "/api/v1/runner/hello")] = route(
        [(200, {"runner": {"id": "rnr-0002", "session_id": "rses-1"}, "placements": [],
                "cursor": 7})]
    )  # fmt: skip
    fake.routes[("GET", "/api/v1/runner/events")] = slow_poll
    process = subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, "-m", "maity", "runner", "serve", "--config", str(path)],
        stderr=subprocess.PIPE,
        text=True,
    )
    status = tmp_path / "st" / serve.STATUS_FILE
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not (
        status.exists() and json.loads(status.read_text()).get("connected")
    ):
        time.sleep(0.05)
    process.send_signal(signal.SIGTERM)
    _, err = process.communicate(timeout=20)
    assert process.returncode == 0, err
    assert "agents keep running" in err
    assert json.loads(status.read_text())["connected"] is False


# --- review round: no spin, 78 on local trouble, one service per state directory ------------


def test_empty_answers_that_do_not_hold_are_waited_out(tmp_path: Path) -> None:
    script = Script(HELLO, events(), events(), events())
    clock = Clock(poll_seconds=0.0)
    svc, _, _ = service(tmp_path, script, clock)
    run(svc)
    assert clock.slept == [serve.POLL_FLOOR] * 3


def test_retry_after_is_capped(tmp_path: Path) -> None:
    script = Script(("POST /runner/hello", err(429, "rate_limited", retry_after=99_999_999)), HELLO)
    svc, _, clock = service(tmp_path, script)
    run(svc)
    assert clock.slept == [serve.RETRY_AFTER_CAP]


def test_a_state_directory_that_cannot_be_written_ends_with_78(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = Script(HELLO)
    svc, _, _ = service(tmp_path, script)
    (tmp_path / "st").mkdir(mode=0o500)
    try:
        assert run(svc) == serve.EXIT_CONFIG
    finally:
        (tmp_path / "st").chmod(0o700)
    assert "cannot be written" in capsys.readouterr().err


def test_an_unreadable_runner_file_ends_with_78(
    tmp_path: Path, home: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    path = paired(tmp_path, fake)
    (tmp_path / "st" / serve.RUNNER_FILE).chmod(0o000)
    try:
        assert cli.main(["runner", "serve", "--config", str(path)]) == serve.EXIT_CONFIG
    finally:
        (tmp_path / "st" / serve.RUNNER_FILE).chmod(0o600)
    assert "cannot start" in capsys.readouterr().err


def test_a_second_service_on_the_same_state_directory_is_refused(tmp_path: Path) -> None:
    (tmp_path / "st").mkdir(mode=0o700)
    first = serve.hold_lock(tmp_path / "st")
    try:
        with pytest.raises(serve.Fatal, match="already runs"):
            serve.hold_lock(tmp_path / "st")
    finally:
        first.close()
    serve.hold_lock(tmp_path / "st").close()


def test_status_cleans_what_the_hub_wrote_and_ignores_a_reused_pid(
    tmp_path: Path, home: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    path = paired(tmp_path, fake)
    state.save_state(
        tmp_path / "st",
        {"pid": os.getpid(), "connected": True, "error": None,
         "placements": [{"id": "plc-1\x1b]8;;evil\x07", "project": "maity"}]},
        name=serve.STATUS_FILE,
    )  # fmt: skip
    capsys.readouterr()
    assert cli.main(["runner", "status", "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out
    assert "not running" in out  # this pid is pytest, not a runner


def test_the_unit_ships_with_the_package(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["runner", "unit"]) == 0
    unit = capsys.readouterr().out
    assert "KillMode=process" in unit and "RestartPreventExitStatus=78" in unit
    assert "PrivateTmp" not in unit.replace("No PrivateTmp", "")


def test_local_trouble_while_backing_off_ends_with_78(tmp_path: Path) -> None:
    script = Script(("POST /runner/hello", err(503)))
    svc, _, clock = service(tmp_path, script)
    (tmp_path / "st").mkdir(mode=0o500)
    try:
        assert run(svc) == serve.EXIT_CONFIG
    finally:
        (tmp_path / "st").chmod(0o700)
    assert clock.slept == []


def test_hub_words_never_forge_a_log_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile = hub.HubError("503: \x1b]8;;https://evil\x07x\x1b]8;;\x07\nFORGED line", status=503)
    script = Script(("POST /runner/hello", hostile), ("POST /runner/hello", err(404)))
    svc, _, _ = service(tmp_path, script)
    run(svc)
    logged = capsys.readouterr().err
    assert "\x1b" not in logged and "\x07" not in logged
    assert not any(line.startswith("FORGED") for line in logged.splitlines())


def test_a_page_that_does_not_move_the_cursor_is_waited_out(tmp_path: Path) -> None:
    script = Script(
        HELLO, events({"seq": 1}, cursor=5120), placements(), events({"seq": 1}, cursor=5120)
    )
    clock = Clock(poll_seconds=0.0)
    svc, _, _ = service(tmp_path, script, clock)
    run(svc)
    assert clock.slept[:1] == [serve.POLL_FLOOR]
