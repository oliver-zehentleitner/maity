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
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import hub, onboarding, sign, state
from . import capabilities, config, supervisor, targets

EXIT_CONFIG = 78  # EX_CONFIG; RestartPreventExitStatus in the unit
POLL_WAIT = 55
POLL_SLACK = 15.0  # the request timeout beyond the long-poll's own wait
REREAD_INTERVAL = 600.0
BACKOFF_CAP = 60.0
BACKOFF_RESET = 30.0  # a long-poll that lasted this long proves the connection
POLL_FLOOR = 1.0  # an empty long-poll that returned sooner is waited out: never spin
RETRY_AFTER_CAP = 3600.0
LOCK_FILE = "serve.lock"
STATUS_FILE = "status.json"
RUNNER_FILE = "runner.json"  # written by `pair`: hub, runner id, credential id
REVOKE = "revoke the runner in the dashboard"


class Fatal(Exception):
    """Retrying cannot help: the service ends with EXIT_CONFIG."""


class Stop(BaseException):
    """SIGTERM or SIGINT: stop polling; the agents keep running."""


def utc(stamp: float | None = None) -> str:
    moment = datetime.fromtimestamp(time.time() if stamp is None else stamp, tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message: str) -> None:
    """One line per event on standard error, in a format a service manager keeps."""
    print(f"{utc()} maity-runner: {message}", file=sys.stderr, flush=True)


def fatal_reason(err: hub.HubError) -> str | None:
    """Why `err` ends the service, or None when backing off and saying `hello` again can
    help (no answer, a 5xx, 408, 429, a clock skew the client could not settle in one go)."""
    if err.code == "credential_revoked":
        return (
            "the runner's credential was revoked; re-pair the runner in the dashboard and run "
            "`maity runner pair` here, or remove the runner"
        )
    if err.code == "timestamp_skew" or err.status is None:
        return None
    if err.status in (408, 429) or err.status >= 500:
        return None
    return f"the hub refuses this runner: {onboarding.inline(str(err))}"


def backoff(attempt: int, err: hub.HubError | None, rand: Callable[[], float]) -> float:
    """Full jitter: uniform in [0, min(cap, 2^attempt)] seconds, never below Retry-After."""
    delay = rand() * min(BACKOFF_CAP, 2.0**attempt)
    if err is not None and err.retry_after is not None:
        delay = max(delay, min(err.retry_after, RETRY_AFTER_CAP))
    return delay


@dataclass
class Service:
    cfg: config.Config
    client: hub.Client
    advertised: dict[str, Any]
    reconcile: Callable[[list[dict[str, Any]]], None] = lambda placements: None
    actual: Callable[[], list[dict[str, Any]]] = lambda: []
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    rand: Callable[[], float] = random.random
    cursor: int | None = None
    session_id: str | None = None
    placements: list[dict[str, Any]] = field(default_factory=list)
    last_read: float = 0.0
    connected: bool = False
    supervisor: supervisor.Supervisor | None = None

    # --- one connection --------------------------------------------------------------------

    def hello(self) -> None:
        packet = self.client.call(
            "POST",
            "/runner/hello",
            body={"client": hub.CLIENT, "capabilities": self.advertised, "actual": self.actual()},
        )
        runner = packet.get("runner") if isinstance(packet, dict) else None
        self.session_id = runner.get("session_id") if isinstance(runner, dict) else None
        cursor = packet.get("cursor")
        self.cursor = cursor if isinstance(cursor, int) else 0
        self.connected = True
        log(f"connected as {self._name(runner)}; session {onboarding.inline(self.session_id)}")
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
        return f"{onboarding.inline(runner.get('name'))} ({onboarding.inline(runner.get('id'))})"

    # --- the loop --------------------------------------------------------------------------

    def run(self) -> int:
        """Until a fatal answer (EXIT_CONFIG) or Stop (raised by the signal handler)."""
        attempt = 0
        while True:
            try:
                self.hello()
                while True:
                    started, before = self.monotonic(), self.cursor
                    woken = self.poll()
                    held = self.monotonic() - started
                    if held >= BACKOFF_RESET:
                        attempt = 0
                    if held < POLL_FLOOR and (not woken or self.cursor == before):
                        # An answer that neither held nor moved the cursor: never spin.
                        self.sleep(POLL_FLOOR - held)
                    if woken or self.monotonic() - self.last_read >= REREAD_INTERVAL:
                        self.read_placements()
            except Fatal as exc:
                return self._fatal(str(exc))
            except OSError as exc:  # local files, never the network (that is HubError)
                return self._fatal(f"local state cannot be written: {exc}")
            except hub.HubError as exc:
                reason = fatal_reason(exc)
                if reason is not None:
                    return self._fatal(reason)
                attempt += 1
                delay = backoff(attempt, exc, self.rand)
                self.connected = False
                text = onboarding.inline(str(exc))  # the hub's words: one line, no escapes
                try:
                    self.write_status(error=text, retry_in=delay)
                except OSError as local:
                    return self._fatal(f"local state cannot be written: {local}")
                log(f"{text}; trying again in {delay:.0f} s")
                self.sleep(delay)

    def _fatal(self, reason: str) -> int:
        self.connected = False
        try:
            self.write_status(error=reason)
        except OSError:
            pass  # the reason goes to the log either way
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
                    {
                        **{
                            k: p.get(k)
                            for k in ("id", "project", "project_id", "generation", "desired")
                        },
                        "agent": (p.get("agent") or {}).get("handle"),
                    }
                    for p in self.placements
                    # never a path or a line from an unchecked id
                    if isinstance(p.get("id"), str) and supervisor.PLACEMENT_ID.match(p["id"])
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


def hold_lock(state_dir: Path) -> Any:
    """An exclusive lock on the state directory for as long as this service runs: a second
    `serve` on the same host is refused at start, instead of taking the event stream from
    the first and leaving both stopped on `superseded`."""
    import fcntl

    handle = os.fdopen(os.open(state_dir / LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600), "r+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise Fatal(f"another `maity runner serve` already runs on {state_dir}") from None
    return handle


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
    probes: dict[str, capabilities.Probe] = {}
    found_targets = None
    if cfg.backend == "ssh":
        # Each host is reached once before the first hello, so what is advertised is what
        # the hosts have; one that does not answer is advertised unreachable.
        found_targets = targets.build(cfg, probes)
        for target in found_targets:
            try:
                target.connect(cfg.harnesses)
                target.reachable = True
            except OSError as exc:
                log(f"target {target.name}: unreachable ({exc})")
    else:
        path = capabilities.agent_path(cfg, os.environ.get("PATH", ""))
        as_user = supervisor.agents_user(cfg)
        probes = {h.id: capabilities.probe(h, path, as_user) for h in cfg.harnesses.values()}
        for harness_id, found in probes.items():
            if not found.available:
                log(f"harness {harness_id} is advertised as unavailable ({found.reason})")
    service = Service(
        cfg, hub.Client(base, key), capabilities.build(cfg, probes, targets=found_targets)
    )
    # Its own client: reports go out while the connection thread sits in a long-poll.
    sup = supervisor.build(
        cfg, hub.Client(base, key), log, probes, service.advertised, found_targets
    )
    service.reconcile, service.actual = sup.update, sup.actual
    service.supervisor = sup
    return service


def serve(config_path: Path) -> int:
    try:
        cfg = config.load(config_path)
    except config.ConfigError as exc:
        for problem in exc.problems:
            log(problem)
        return EXIT_CONFIG
    missing = config.unsupported(cfg)
    if missing:
        for problem in missing:
            log(problem)
        return EXIT_CONFIG
    try:
        runner_state = state.load_state(cfg.state_dir, name=RUNNER_FILE)
        service = open_service(cfg, runner_state)
        lock = hold_lock(cfg.state_dir)
    except (Fatal, state.StateError, hub.HubError, OSError) as exc:
        log(f"cannot start: {exc}")
        return EXIT_CONFIG
    log(f"serving {hub.safe_url(cfg.hub_url)} from {config_path}")
    stopping = threading.Event()
    if service.supervisor is not None:
        threading.Thread(
            target=service.supervisor.run, args=(stopping,), daemon=True, name="maity-supervisor"
        ).start()
    with stop_on_signals():
        try:
            return service.run()
        except Stop:
            service.connected = False
            try:
                service.write_status(error="stopped")
            except OSError:
                pass
            log("stopped by signal; agents keep running")
            return 0
        finally:
            stopping.set()
            lock.close()
