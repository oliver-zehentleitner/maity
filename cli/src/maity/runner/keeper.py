"""The thread that keeps the runner's managed harness tools (§15.16): installs a missing one
at start, looks for a newer version once a day, carries out the owner's `Update now`, and
advertises `capabilities.tools`. Its own hub client, so an install that takes minutes never
holds up the event wait; it reads `GET /runner` at most once a minute, and only while some
tool is updated.

A version is used from the next session start on: the probe of the harness is replaced, and
the supervisor launches with its absolute path; a running session keeps the binary it
started with (`Record.binary`).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from maity import __version__, hub
from maity.runner import capabilities, config, tools
from maity.runner.asuser import AsUser

CHECK_EVERY = 24 * 3600.0
READ_EVERY = 60.0
LOGIN_TIMEOUT = 30
# The tool's own question whether it is logged in; exit 0 means yes (§15.16 "Logins").
LOGIN_STATUS = {"claude-code": ("auth", "status"), "codex": ("login", "status")}

Log = Callable[[str], None]


def stamp(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age(text: str | None, now: float) -> float | None:
    try:
        then = datetime.strptime(text or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return now - then.timestamp()


def managed(harness: config.Harness) -> bool:
    return harness.install or harness.update != "never"


def logged_in(harness_id: str, binary: str, as_user: AsUser) -> bool:
    """The tool's own login answer; the runner never reads or handles a credential."""
    args = LOGIN_STATUS.get(harness_id)
    if args is None:
        return True
    try:
        done = as_user.run([binary, *args], timeout=LOGIN_TIMEOUT)
    except Exception:  # noqa: BLE001 - a tool that cannot answer is not logged in
        return False
    return done.returncode == 0


@dataclass
class Keeper:
    cfg: config.Config
    client: hub.Client | None
    log: Log
    probes: dict[str, capabilities.Probe]  # the supervisor's own dict, replaced in place
    advertised: dict[str, Any]  # the capabilities object hello and PATCH /runner send
    agent_path: str
    as_user: AsUser
    sessions_on: Callable[[str, str | None], int] = lambda harness_id, binary: 0
    advertise: Callable[[], None] = lambda: None
    now: Callable[[], float] = time.time
    pause: Callable[[float], None] = time.sleep
    lock: threading.RLock = field(default_factory=threading.RLock)
    started: bool = False

    # --- what the runner reports ----------------------------------------------------------

    def entries(self) -> list[dict[str, Any]]:
        """`capabilities.tools`: one per harness the configuration lists, and `maity`."""
        out = []
        for harness in self.cfg.harnesses.values():
            if harness.id == "stub":
                continue
            found = self.probes.get(harness.id)
            if managed(harness):
                entry = tools.report(
                    self.cfg.tools_dir,
                    harness.id,
                    install=harness.install,
                    update=harness.update,
                    sessions_on_older=self.sessions_on(harness.id, found.path if found else None),
                )
                if entry["state"] == "missing" and harness.install:
                    entry["state"] = "installing"
                if found is not None and found.reason == "login_needed":
                    entry["state"], entry["reason"] = "login_needed", None
            else:  # what it finds, untouched (§15.16: nothing changes from today)
                version = found.version if found is not None else None
                entry = {
                    "id": harness.id, "install": False, "update": "never",
                    "version": version, "previous_version": None, "latest": None,
                    "state": "current" if version else "missing", "reason": None,
                    "checked_at": None, "updated_at": None, "sessions_on_older": 0,
                    "update_requested_at": None,
                }  # fmt: skip
            out.append(entry)
        out.append(
            {
                "id": "maity", "install": False, "update": "never",
                "version": capabilities.ascii_text(__version__, 80), "previous_version": None,
                "latest": None, "state": "current", "reason": None, "checked_at": None,
                "updated_at": None, "sessions_on_older": 0, "update_requested_at": None,
            }  # fmt: skip
        )
        return out

    def refresh(self, harness: config.Harness) -> None:
        """Probe the harness again: the managed binary, its version answer, and its login."""
        found = capabilities.probe(harness, self.agent_path, self.as_user, self.cfg.tools_dir)
        if found.available and managed(harness) and found.path is not None:
            if not logged_in(harness.id, found.path, self.as_user):
                found = capabilities.Probe(found.path, found.version, "login_needed")
        self.probes[harness.id] = found
        for entry in self.advertised.get("harnesses", []):
            if entry.get("id") == harness.id:
                entry.update(version=found.version, available=found.available,
                             reason=found.reason)  # fmt: skip

    def publish(self) -> None:
        with self.lock:
            self.advertised["tools"] = self.entries()
        self.advertise()

    # --- what the runner does -------------------------------------------------------------

    def take(self, harness: config.Harness, requested_at: str | None = None) -> None:
        factory = tools.INSTALLERS.get(harness.id)
        if factory is None:
            return
        state = tools.load(self.cfg.tools_dir, harness.id)
        self.log(
            f"tools: {harness.id}: {'installing' if state.version is None else 'checking'}"
            + (f" (Update now of {requested_at})" if requested_at else "")
        )
        with self.lock:
            state.state = "installing" if state.version is None else "updating"
            tools.save(self.cfg.tools_dir, harness.id, state)
        self.publish()
        result = tools.take(
            self.cfg.tools_dir, harness.id, factory(), stamp(self.now()), requested_at=requested_at
        )
        if result.state == "failed":
            self.log(f"tools: {harness.id}: failed ({result.reason})")
        elif result.version != state.version:
            self.log(f"tools: {harness.id}: {result.version} for new sessions")
        self.refresh(harness)
        self.publish()

    def requests(self) -> list[tuple[str, str]]:
        """The owner's `Update now` requests, from `GET /runner` (§15.16)."""
        if self.client is None:
            return []
        try:
            view = self.client.call("GET", "/runner")
        except hub.HubError as exc:
            self.log(f"tools: reading Update now failed ({exc})")
            return []
        items = view.get("update_requests") if isinstance(view, dict) else None
        found = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("tool"), str):
                at = item.get("requested_at")
                if isinstance(at, str):
                    found.append((item["tool"], at))
        return found

    def step(self) -> None:
        """One round: the first install, the daily check, the requests."""
        now = self.now()
        for harness in self.cfg.harnesses.values():
            if not managed(harness):
                continue
            current = tools.binary(self.cfg.tools_dir, harness.id)
            known = self.probes.get(harness.id)
            if self.started and (str(current) if current else None) != (known and known.path):
                self.refresh(harness)  # `maity runner tools rollback` on this machine
                self.publish()
            state = tools.load(self.cfg.tools_dir, harness.id)
            if not self.started and state.version is None and harness.install:
                self.take(harness)
            elif harness.update == "daily":
                age = _age(state.checked_at, now)
                if age is None or age >= CHECK_EVERY:
                    self.take(harness)
        self.started = True
        if not any(h.update == "daily" for h in self.cfg.harnesses.values()):
            return
        for tool_id, requested_at in self.requests():
            asked = self.cfg.harnesses.get(tool_id)
            if asked is None or asked.update != "daily":
                continue  # the hub refuses those; one that slips through is left standing
            if tools.load(self.cfg.tools_dir, tool_id).update_requested_at == requested_at:
                continue
            self.take(asked, requested_at=requested_at)

    def run(self, stopping: threading.Event) -> None:
        for harness in self.cfg.harnesses.values():
            if managed(harness):
                self.refresh(harness)
        self.publish()
        while not stopping.is_set():
            try:
                self.step()
            except Exception as exc:  # noqa: BLE001 - the keeper never takes the runner down
                self.log(f"tools: {type(exc).__name__}: {exc}")
            stopping.wait(READ_EVERY)
