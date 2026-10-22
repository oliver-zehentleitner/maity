"""`maity runner serve`: the connection to the hub (runner design §5.2, docs/api.md §15.8).

`hello` opens a runner session and hands over the placements and a cursor; one long-poll
on `/runner/events` keeps the runner `listening` and wakes it; after every wake, and every
REREAD_INTERVAL regardless, it re-reads `/runner/placements`. An event is a wake-up only, so
a lost or duplicated one costs nothing. What happens to the placements is `reconcile`, the
local backend's business (R3); this module only keeps the desired state current.

A connection error, a 5xx, a 429 or a clock skew backs off with full jitter and starts again
with `hello`. A revoked credential, a configuration error, a hub that refuses the runner
and a second `serve` taking over the stream end the service with EXIT_CONFIG, which the
systemd unit does not restart: retrying cannot fix any of them. Agents keep running in
every case; ending them is a placement's or the operator's decision, never the connection's.
"""

from __future__ import annotations

import os
import random
import signal
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import hub, sign, state
from . import capabilities, config

EXIT_CONFIG = 78  # EX_CONFIG; RestartPreventExitStatus in the unit
POLL_WAIT = 55
POLL_SLACK = 15.0  # the request timeout beyond the long-poll's own wait
REREAD_INTERVAL = 600.0
BACKOFF_CAP = 60.0
BACKOFF_RESET = 30.0  # a long-poll that lasted this long proves the connection
STATUS_FILE = "status.json"
RUNNER_FILE = "runner.json"  # written by `pair`: hub, runner id, credential id
REVOKE = "revoke the runner in the dashboard"


class Fatal(Exception):
    """Retrying cannot help: the service ends with EXIT_CONFIG."""


class Stop(BaseException):
    """SIGTERM or SIGINT: stop polling; the agents keep running."""


def utc(stamp: float | None = None) -> str:
    moment = datetime.fromtimestamp(time.time() if stamp is None else stamp, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message: str) -> None:
    """One line per event on standard error, in a format a service manager keeps."""
    print(f"{utc()} maity-runner: {message}", file=sys.stderr, flush=True)


def fatal_reason(err: hub.HubError) -> str | None:
    """Why `err` ends the service, or None when backing off and saying `hello` again can
    help (no answer, a 5xx, 408, 429, a clock skew the client could not settle in one go)."""
    if err.code == "credential_revoked":
        return f"the runner's credential was revoked; {REVOKE} and pair again, or remove it"
    if err.code == "timestamp_skew" or err.status is None:
        return None
    if err.status in (408, 429) or err.status >= 500:
        return None
    return f"the hub refuses this runner: {err}"


def backoff(attempt: int, err: hub.HubError | None, rand: Callable[[], float]) -> float:
    """Full jitter: uniform in [0, min(cap, 2^attempt)] seconds, never below Retry-After."""
    delay = rand() * min(BACKOFF_CAP, 2.0**attempt)
    if err is not None and err.retry_after is not None:
        delay = max(delay, err.retry_after)
    return delay


@dataclass
class Service:
    cfg: config.Config
    client: hub.Client
    advertised: dict[str, Any]
    reconcile: Callable[[list[dict[str, Any]]], None] = lambda placements: None
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    rand: Callable[[], float] = random.random
    cursor: int | None = None
    session_id: str | None = None
    placements: list[dict[str, Any]] = field(default_factory=list)
    last_read: float = 0.0
    connected: bool = False

    # --- one connection --------------------------------------------------------------------

    def hello(self) -> None:
        packet = self.client.call(
            "POST",
            "/runner/hello",
            body={"client": hub.CLIENT, "capabilities": self.advertised, "actual": []},
        )
        runner = packet.get("runner") if isinstance(packet, dict) else None
        self.session_id = runner.get("session_id") if isinstance(runner, dict) else None
        cursor = packet.get("cursor")
        self.cursor = cursor if isinstance(cursor, int) else 0
        self.connected = True
        log(f"connected as {self._name(runner)}; session {self.session_id}")
        self._take(packet.get("placements"))

    def poll(self) -> bool:
        """One long-poll; True when it returned events (a wake-up)."""
        answer = self.client.call(
            "GET",
            "/runner/events",
            query=[("after", str(self.cursor or 0)), ("wait", str(POLL_WAIT))],
            timeout=POLL_WAIT + POLL_SLACK,
        )
        if not isinstance(answer, dict):
            raise hub.HubError("the event stream answered with something that is not an object")
        if answer.get("superseded"):
            raise Fatal(
                "another `maity runner serve` with this credential took over the event stream; "
                "run one service per runner"
            )
        cursor = answer.get("cursor")
        if isinstance(cursor, int):
            self.cursor = cursor
        items = answer.get("items")
        return bool(items)

    def read_placements(self) -> None:
        answer = self.client.call("GET", "/runner/placements")
        self._take(answer.get("items") if isinstance(answer, dict) else None)

    def _take(self, placements: Any) -> None:
        self.placements = [p for p in placements or [] if isinstance(p, dict)]
        self.last_read = self.monotonic()
        self.write_status()
        self.reconcile(self.placements)

    @staticmethod
    def _name(runner: Any) -> str:
        if not isinstance(runner, dict):
            return "this runner"
        return f"{runner.get('name')} ({runner.get('id')})"

    # --- the loop --------------------------------------------------------------------------

    def run(self) -> int:
        """Until a fatal answer (EXIT_CONFIG) or Stop (raised by the signal handler)."""
        attempt = 0
        while True:
            try:
                self.hello()
                while True:
                    started = self.monotonic()
                    woken = self.poll()
                    if self.monotonic() - started >= BACKOFF_RESET:
                        attempt = 0
                    if woken or self.monotonic() - self.last_read >= REREAD_INTERVAL:
                        self.read_placements()
            except Fatal as exc:
                return self._fatal(str(exc))
            except hub.HubError as exc:
                reason = fatal_reason(exc)
                if reason is not None:
                    return self._fatal(reason)
                attempt += 1
                delay = backoff(attempt, exc, self.rand)
                self.connected = False
                self.write_status(error=str(exc), retry_in=delay)
                log(f"{exc}; trying again in {delay:.0f} s")
                self.sleep(delay)

    def _fatal(self, reason: str) -> int:
        self.connected = False
        self.write_status(error=reason)
        log(f"stopping: {reason}. Agents keep running.")
        return EXIT_CONFIG

    # --- local state -----------------------------------------------------------------------

    def write_status(self, error: str | None = None, retry_in: float | None = None) -> None:
        """`<state_dir>/status.json`, read by `maity runner status` without the hub."""
        state.save_state(
            self.cfg.state_dir,
            {
                "pid": os.getpid(),
                "connected": self.connected,
                "session_id": self.session_id,
                "cursor": self.cursor,
                "error": error,
                "retry_at": utc(time.time() + retry_in) if retry_in is not None else None,
                "placements": [
                    {k: p.get(k) for k in ("id", "project", "generation", "desired")}
                    for p in self.placements
                ],
                "updated_at": utc(),
            },
            name=STATUS_FILE,
        )


# --- the command -----------------------------------------------------------------------------


@contextmanager
def stop_on_signals() -> Iterator[None]:
    def handler(signum: int, frame: Any) -> None:
        raise Stop

    previous = {s: signal.signal(s, handler) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        yield
    finally:
        for signum, old in previous.items():
            signal.signal(signum, old)


def open_service(cfg: config.Config, runner_state: dict[str, Any]) -> Service:
    """The service for `cfg`; Fatal when the state directory cannot be used."""
    base = hub.hub_base(cfg.hub_url)
    paired = runner_state.get("hub")
    if paired and paired != base:
        raise Fatal(
            f"the credential in {cfg.state_dir} was issued by {hub.safe_url(paired)}, not by "
            f"{base}; pair again for this hub"
        )
    if not state.has_credential(cfg.state_dir):
        raise Fatal(f"no runner credential in {cfg.state_dir}; run `maity runner pair` first")
    try:
        state.check_private(cfg.state_dir, REVOKE)
        state.check_private(state.credential_path(cfg.state_dir), REVOKE)
        key = sign.signing_key(state.read_credential(cfg.state_dir))
    except (state.StateError, sign.CredentialFormatError) as exc:
        raise Fatal(str(exc)) from None
    path = capabilities.agent_path(cfg, os.environ.get("PATH", ""))
    probes = {h.id: capabilities.probe(h, path) for h in cfg.harnesses.values()}
    for harness_id, found in probes.items():
        if not found.available:
            log(f"harness {harness_id} is advertised as unavailable ({found.reason})")
    return Service(cfg, hub.Client(base, key), capabilities.build(cfg, probes))


def serve(config_path: Path) -> int:
    try:
        cfg = config.load(config_path)
    except config.ConfigError as exc:
        for problem in exc.problems:
            log(problem)
        return EXIT_CONFIG
    try:
        runner_state = state.load_state(cfg.state_dir, name=RUNNER_FILE)
        service = open_service(cfg, runner_state)
    except (Fatal, state.StateError, hub.HubError) as exc:
        log(f"cannot start: {exc}")
        return EXIT_CONFIG
    log(f"serving {hub.safe_url(cfg.hub_url)} from {config_path}")
    with stop_on_signals():
        try:
            return service.run()
        except Stop:
            service.connected = False
            service.write_status(error="stopped")
            log("stopped by signal; agents keep running")
            return 0
