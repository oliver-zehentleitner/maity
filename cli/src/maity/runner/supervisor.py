"""Desired against actual, every TICK seconds (runner design §5.2, the reconcile table).

The connection (`serve`) hands over the placements as the hub wants them; the supervisor
compares them with the sessions tmux has and acts: start, restart after a backoff, stop with
grace, adopt a session it finds after its own restart, end a session no placement wants any
more. It reports what is actually there, one record per placement and only on a change of
(state, reason, detail, generation, restarts), each with the next `seq`, saved before it is
sent. A report the hub did not take is sent again on the next tick.

Long actions (clone, start) run as one task per placement, so a slow clone never holds up a
stop elsewhere. Everything else runs in the supervisor's own thread. `actual.json` keeps the
records across runner restarts; the sessions themselves are found again through their
`@maity_placement` and `@maity_generation` options.
"""

from __future__ import annotations

import json
import os
import random
import re
import stat
import subprocess
import threading
import time
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import __version__, hub, onboarding, state
from . import adapters, capabilities, config, loop, restart, targets, workspace
from .asuser import RUNNER, AsUser, Unreachable
from .targets import Target
from .tmux import Session, Tmux, TmuxError, session_name

TICK = 5.0
PICKUP_RETRY = 15.0
JOIN_TIMEOUT = 120.0
PICKUP_DETAILS = ("pickup_not_allowed", "pickup_used")
JOIN_DETAILS = ("code_invalid", "expired", "not_found", "rate_limited", "insecure_transport")
_JOIN_ERROR = re.compile(r"\bjoin: ([a-z_]+):")


class Retry(Exception):
    """A step that may succeed on the next tick (a pickup whose answer was lost)."""


def run_join(
    place: workspace.Workspace,
    url: str,
    code: str,
    cwd: Path,
    as_user: AsUser = RUNNER,
    agent_path: str | None = None,
) -> tuple[bool, str | None]:
    """`maity join --join-file -` in the clone: (joined, the `join_failed` detail when not;
    None when the CLI's error has no code in §15.7's list).

    `MAITY_STATE_DIR` points at the clone's own state directory, so the agent-side CLI
    finds it without running git in a clone the agent can write (§5.3). Python runs isolated
    (`-I`) from a directory outside the clone, so no module in the repository is imported
    by the process that reads the code. In the agent_user layout it runs as the agents'
    user, who then owns the credential; on an ssh host it is the host's own `maity`, found
    on the target's `agent_path`. Its output is never logged: an error names the join URL,
    and with it the token."""
    if not as_user.direct:  # sudo and ssh start empty: pass only what the join needs
        env = {state.STATE_DIR_ENV: str(place.credential.parent)}
        if not as_user.here and agent_path:
            env["PATH"] = agent_path
        cwd = Path("/")
    else:
        env = {k: v for k, v in os.environ.items() if k != state.STATE_DIR_ENV}
        env[state.STATE_DIR_ENV] = str(place.credential.parent)
    command = [
        *as_user.maity, "join", "--join-file", "-", "--no-resume", "--no-pointer",
        "--client", f"maity-runner/{__version__}",
    ]  # fmt: skip
    try:
        done = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
            as_user.argv(command, env) if not as_user.direct else command,
            cwd=cwd, env=None if not as_user.direct else env, input=f"{url}\n{code}\n",
            capture_output=True, text=True, timeout=JOIN_TIMEOUT, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return False, "network"
    if done.returncode == 0:
        return True, None
    found = _JOIN_ERROR.search(done.stderr)
    if found and found.group(1) in JOIN_DETAILS:
        return False, found.group(1)
    return False, "network" if "cannot reach" in done.stderr else None


RUNNING_AFTER = 10.0  # a process alive this long is `running`
KILL_AFTER = 10.0  # from SIGTERM to kill-session
ACTUAL_FILE = "actual.json"
APPROVED_FILE = "approved.json"
LOGS = "logs"
ADVERTISE_EVERY = 60.0  # at most one PATCH /runner for a changed `running` per this
LIVE = ("starting", "running", "stopping")
LIMIT_BACKOFF = 15 * 60.0  # reset_unknown: 15 min, doubling ...
LIMIT_BACKOFF_MAX = 2 * 3600.0  # ... up to 2 h
LIMIT_BYTES = 512
PLACEMENT_ID = re.compile(r"^plc-[0-9a-z-]{1,60}$")
HARNESS_ID = re.compile(r"^[a-z0-9-]{1,40}$")


def valid(p: Any) -> bool:
    """The fields the runner builds paths, names and URLs from, checked before any use."""
    if not isinstance(p, dict):
        return False
    space = p.get("workspace")
    generation = p.get("generation")
    return (
        isinstance(p.get("id"), str)
        and PLACEMENT_ID.match(p["id"]) is not None
        and isinstance(p.get("project"), str)
        and workspace.FULL_NAME.match(p["project"]) is not None
        and isinstance(p.get("project_id"), str)
        and workspace.TOKEN.match(p["project_id"]) is not None
        and isinstance(p.get("project_aliases", []), list)
        and all(
            isinstance(a, str) and workspace.FULL_NAME.match(a) is not None
            for a in p.get("project_aliases", [])
        )
        and isinstance(generation, int)
        and not isinstance(generation, bool)
        and generation >= 1
        and p.get("desired") in ("running", "stopped")
        and isinstance(space, dict)
        and isinstance(space.get("clone"), str)
        and workspace.TOKEN.match(space["clone"]) is not None
        and isinstance(p.get("harness"), str)
        and HARNESS_ID.match(p["harness"]) is not None
        and _count(p.get("seq", 0))
        and _count(p.get("stop_grace_seconds", 0))
        and p.get("stop_grace_seconds", 0) <= 900
        and isinstance(p.get("agent", {}), dict)
        and all(
            v is None or (isinstance(v, str) and len(v) <= 100)
            for v in ((p.get("agent") or {}).get("id"), (p.get("agent") or {}).get("handle"))
        )
    )


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def stamp(moment: float | None) -> str | None:
    if moment is None:
        return None
    return datetime.fromtimestamp(moment, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Record:
    """What the runner knows about one placement; persisted in actual.json."""

    generation: int = 0
    state: str | None = None
    reason: str | None = None
    detail: str | None = None
    exit_code: int | None = None
    restarts: int = 0
    crashes: list[float] = field(default_factory=list)
    retry_at: float | None = None
    started_at: float | None = None
    since: float = 0.0
    deadline_at: float | None = None
    kill_at: float | None = None
    session_hint: str | None = None
    seq: int = 0
    acked: list[Any] | None = None
    pending: dict[str, Any] | None = None
    waiting: str | None = None  # why nothing is done yet, logged once (join: R4, adapter: R5)
    joined_generation: int | None = None  # the generation this runner last joined for
    target: str | None = None  # where it runs; kept, so a `target: null` placement stays put
    limits_unknown: int = 0  # provider limits in a row without a reset time (§15.7 backoff)

    def key(self) -> list[Any]:
        return [self.state, self.reason, self.detail, self.generation, self.restarts]

    def enter(self, now: float, state_: str, reason: str | None = None, **fields: Any) -> None:
        if (state_, reason) != (self.state, self.reason):
            self.since = now
        self.state, self.reason = state_, reason
        self.detail = fields.pop("detail", None)
        if state_ not in ("exited", "failed", "stopped", "rate_limited"):
            self.exit_code = None
        for name, value in fields.items():
            setattr(self, name, value)


Log = Callable[[str], None]


@dataclass
class Supervisor:
    cfg: config.Config
    backend: Tmux | None  # the local target's tmux server; None on the ssh backend
    client: hub.Client | None
    log: Log
    probes: dict[str, capabilities.Probe]
    now: Callable[[], float] = time.time
    rand: Callable[[], float] = random.random
    desired: list[dict[str, Any]] = field(default_factory=list)
    synced: bool = False  # the hub's placements have been read at least once
    records: dict[str, Record] = field(default_factory=dict)
    tasks: dict[str, threading.Thread] = field(default_factory=dict)
    orphans: dict[str, float] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)
    first_tick: bool = True  # until the first tick after the hub's placements were read
    capabilities: dict[str, Any] | None = None  # for PATCH /runner when `running` changes
    advertised_running: int = 0
    advertised_at: float = 0.0
    advertised_counts: dict[str, int] = field(default_factory=dict)
    targets: dict[str, Target] = field(default_factory=dict)
    target_errors: dict[str, str] = field(default_factory=dict)  # the last one logged

    def __post_init__(self) -> None:
        if not self.targets and self.cfg.local is not None and self.backend is not None:
            self.targets = {"local": targets.local(self.cfg, self.probes, self.backend)}

    # --- what serve calls ------------------------------------------------------------------

    def update(self, placements: list[dict[str, Any]]) -> None:
        good = [p for p in placements if valid(p)]
        if len(good) != len(placements):
            ids = [
                onboarding.inline(p.get("id") if isinstance(p, dict) else p)
                for p in placements
                if not valid(p)
            ]
            self.log(f"supervisor: ignoring malformed placements: {', '.join(ids)[:300]}")
        with self.lock:
            self.desired = good
            self.synced = True

    def actual(self) -> list[dict[str, Any]]:
        """`actual` for `hello`."""
        with self.lock:
            return [
                {"placement_id": pid, "generation": r.generation, "state": r.state,
                 "target": r.target or self._default_target()}
                for pid, r in self.records.items() if r.state is not None
            ]  # fmt: skip

    # --- persistence -----------------------------------------------------------------------

    def load(self) -> None:
        if not self.cfg.state_dir.is_dir():
            return
        for pid, data in state.load_state(self.cfg.state_dir, name=ACTUAL_FILE).items():
            if isinstance(data, dict):
                known = {k: v for k, v in data.items() if k in Record.__dataclass_fields__}
                self.records[pid] = Record(**known)

    def save(self) -> None:
        with self.lock:
            data = {pid: asdict(r) for pid, r in self.records.items()}
        state.save_state(self.cfg.state_dir, data, name=ACTUAL_FILE)

    # --- the loop --------------------------------------------------------------------------

    def run(self, stopping: threading.Event) -> None:
        while not stopping.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - the supervisor outlives one bad tick
                self.log(f"supervisor: {type(exc).__name__}: {exc}")
            stopping.wait(TICK)

    def tick(self) -> None:
        now = self.now()
        snapshots: dict[str, dict[str, Session]] = {}
        for target in self.targets.values():
            try:
                target.connect(self.cfg.harnesses)
                assert target.backend is not None  # noqa: S101 - set by connect
                snapshots[target.name] = target.backend.sessions()
            except Unreachable as exc:
                self._reachable(target, False, now, str(exc))
                continue
            except (TmuxError, OSError) as exc:
                if self.target_errors.get(target.name) != str(exc):  # once per change
                    self.target_errors[target.name] = str(exc)
                    self.log(f"supervisor: {target.name}: {exc}")
                if not target.remote:
                    return  # the local tmux server is the whole picture
                continue
            self.target_errors.pop(target.name, None)
            self._reachable(target, True, now)
        with self.lock:
            desired = list(self.desired)
            synced = self.synced
            labelled = {
                s.placement: (name, s)
                for name, found in snapshots.items()
                for s in found.values()
                if s.placement
            }
            alive = {name: sum(1 for s in found.values() if not s.dead)
                     for name, found in snapshots.items()}  # fmt: skip
            for pid, task in self.tasks.items():
                where = self.records.get(pid, Record()).target
                if task.is_alive() and where in alive:
                    alive[where] += 1
            # A rate-limited placement keeps its slot on its target until it starts again
            # (§15.7).
            for p in desired:
                rec = self.records.get(p["id"])
                if p.get("desired") == "running" and rec is not None \
                        and rec.state == "rate_limited" and rec.target in alive:  # fmt: skip
                    alive[rec.target] += 1
            for placement in desired:
                try:
                    self._place(placement, labelled, snapshots, alive, now)
                except Exception as exc:  # noqa: BLE001 - one placement never stops the rest
                    self.log(f"supervisor: {placement['id']}: {type(exc).__name__}: {exc}")
            if synced:
                wanted = {p["id"] for p in desired}
                for name, found in snapshots.items():
                    self._orphans(self.targets[name], found, wanted, now)
                for pid in [pid for pid in self.records if pid not in wanted]:
                    if pid not in self.tasks:
                        del self.records[pid]  # closed or gone: nothing left to report
                self.first_tick = False
            running = {
                name: sum(1 for s in found.values() if not s.dead and s.placement in labelled)
                for name, found in snapshots.items()
            }
        self._report(desired)
        self._advertise(running, now)
        self.save()

    def _place(
        self,
        p: dict[str, Any],
        labelled: dict[str, tuple[str, Session]],
        snapshots: dict[str, dict[str, Session]],
        alive: dict[str, int],
        now: float,
    ) -> None:
        """Find where a placement runs, or should, and act on it there."""
        rec = self.records.get(p["id"])
        name = session_name(p["project_id"], p["workspace"]["clone"])
        found = labelled.get(p["id"])
        where: str | None
        mine: Session | None
        if found is not None:
            where, mine = found
        else:
            where, mine = self._choose(p, rec, snapshots, alive), None
        if where is None:
            return  # nowhere reachable to run it: its last reported state stands
        if where not in self.targets:
            record = self.records.setdefault(p["id"], Record(generation=p["generation"], since=now))
            if record.generation != p["generation"]:
                record.generation, record.restarts, record.crashes = p["generation"], 0, []
            record.enter(now, "failed", "harness_refused", detail="target_unknown")
            return
        if where not in snapshots:
            return  # unreachable: its last reported state stands
        target = self.targets[where]
        other = snapshots[where].get(name)
        blocking = other if other is not None and other is not mine else None
        total = sum(alive.values())
        started = self._step(p, target, mine, blocking, now, total, alive[where])
        alive[where] += started

    def _choose(
        self,
        p: dict[str, Any],
        rec: Record | None,
        snapshots: dict[str, dict[str, Session]],
        alive: dict[str, int],
    ) -> str | None:
        """The placement's own target; else where it ran before; else the first reachable
        target with a free slot (or, all full, the first reachable one, to wait there)."""
        if isinstance(p.get("target"), str):
            return str(p["target"])
        if rec is not None and rec.target is not None and rec.target in self.targets:
            return rec.target
        reachable = [name for name in self.targets if name in snapshots]
        for name in reachable:
            if alive[name] < self.targets[name].max_agents:
                return name
        return reachable[0] if reachable else None

    def _reachable(self, target: Target, up: bool, now: float, why: str = "") -> None:
        """Track a target's reachability; a change is advertised at once (§15.7)."""
        if target.reachable == up and (up or target.unreachable_since is not None):
            return
        target.reachable = up
        target.unreachable_since = None if up else (target.unreachable_since or now)
        if up:
            self.log(f"target {target.name}: reachable")
        else:
            self.log(f"target {target.name}: unreachable ({onboarding.inline(why)[:200]})")
        self._advertise(None, now, force=True)

    # --- one placement ---------------------------------------------------------------------

    def _step(
        self,
        p: dict[str, Any],
        target: Target,
        mine: Session | None,
        blocking: Session | None,
        now: float,
        alive: int,
        alive_here: int = 0,
    ) -> int:
        """Act on one placement on `target`. `mine` is the session labelled with it,
        `blocking` another session holding its name; `alive` counts the runner's sessions,
        `alive_here` the target's. Returns how many sessions it started (for capacity)."""
        backend = target.backend
        assert backend is not None  # noqa: S101 - a target in the snapshot is connected
        pid, generation = p["id"], p["generation"]
        task = self.tasks.get(pid)
        if task is not None:
            if not task.is_alive():
                del self.tasks[pid]
            return 0  # this tick's snapshot may predate the session the task just started
        rec = self.records.setdefault(pid, Record(generation=generation, since=now))
        rec.target = target.name
        if rec.generation != generation:
            rec.generation, rec.restarts, rec.crashes, rec.retry_at = generation, 0, [], None
            rec.state = rec.reason = rec.detail = None
            rec.waiting = None
            rec.exit_code = None
            rec.limits_unknown = 0

        if p.get("desired") == "stopped":
            if mine is not None and not mine.dead:
                self._stop(rec, mine, p, now, backend)
            else:
                if mine is not None:
                    backend.kill(mine.name)
                rec.enter(now, "stopped", "stopped_by_hub", deadline_at=None, kill_at=None,
                          retry_at=None)  # fmt: skip
            return 0
        if mine is None and blocking is not None:
            if blocking.placement is None:
                self._wait(rec, f"an unlabelled session {blocking.name} holds its name", pid)
            return 0  # another session holds this name: ended as an orphan first
        if mine is not None and mine.generation != generation:
            if not mine.dead:
                self._stop(rec, mine, p, now, backend)
                return 0
            backend.kill(mine.name)
            mine = None
        if mine is not None and not mine.dead:
            if rec.state != "stopping" and (self.first_tick or rec.state not in LIVE):
                rec.enter(now, "running", "adopted", started_at=None)
            elif rec.state == "starting" and now - (rec.started_at or now) >= RUNNING_AFTER:
                unconfined = p["harness"] == "claude-code" and not target.sandbox.get(
                    "claude-code", False
                )
                rec.enter(now, "running", detail="sandbox_unavailable" if unconfined else None)
            elif rec.state == "stopping":  # desired went back to running during a stop
                rec.enter(now, "running", deadline_at=None, kill_at=None)
            return 0
        if mine is not None and mine.dead:
            self._exited(rec, mine, now, backend, target)
            return 0
        if rec.state == "failed" or (rec.retry_at is not None and now < rec.retry_at):
            return 0
        if self.cfg.limits.require_local_approval and pid not in approved(self.cfg.state_dir):
            rec.enter(now, "pending", "awaiting_operator")  # §7.1: `maity runner approve`
            return 0
        # A restart at retry_at takes the slot it kept: it never waits for capacity (§15.7).
        own = rec.state == "rate_limited"
        if alive - own >= self.cfg.limits.max_agents or alive_here - own >= target.max_agents:
            rec.enter(now, "pending", "capacity")
            return 0
        return self._launch(p, rec, now, target)

    def _stop(
        self, rec: Record, session: Session, p: dict[str, Any], now: float, backend: Tmux
    ) -> None:
        if rec.state != "stopping":
            grace = min(int(p.get("stop_grace_seconds") or 0), self.cfg.limits.stop_grace_max)
            rec.enter(now, "stopping", deadline_at=now + grace, kill_at=None)
        elif rec.kill_at is None and now >= (rec.deadline_at or now):
            backend.terminate(session)
            rec.kill_at = now + KILL_AFTER
        elif rec.kill_at is not None and now >= rec.kill_at:
            backend.kill(session.name)

    def _exited(
        self, rec: Record, session: Session, now: float, backend: Tmux,
        target: Target | None = None,
    ) -> None:  # fmt: skip
        backend.kill(session.name)
        code = session.exit_status
        if rec.state == "stopping":
            rec.enter(now, "stopped", "stopped_by_hub", exit_code=code, deadline_at=None,
                      kill_at=None)  # fmt: skip
            return
        # An adopted session's start is unknown: its exit is not counted as a quick one.
        started = (
            rec.started_at
            if rec.started_at is not None
            else now - self.cfg.limits.restart.quick_exit
        )
        if code == loop.EXIT_REVOKED:
            rec.enter(now, "failed", "agent_credential_revoked", exit_code=code, retry_at=None)
            return
        if code == loop.EXIT_HOT_LOOP:
            rec.limits_unknown = 0
            rec.enter(now, "failed", "crash_loop", detail="hot_loop", exit_code=code, retry_at=None)
            return
        if code in (loop.EXIT_RATE_LIMITED, loop.EXIT_RATE_LIMITED_AFTER_CLEAN):
            if code == loop.EXIT_RATE_LIMITED_AFTER_CLEAN:
                rec.limits_unknown = 0  # a clean run since the last limit: a new row
            self._rate_limited(rec, now, target or self.targets[self._default_target()])
            return
        rec.limits_unknown = 0
        decision = restart.on_exit(self.cfg.limits.restart, rec.crashes, started, now, self.rand)
        if decision.crash_loop:
            rec.enter(now, "failed", "crash_loop", exit_code=code, crashes=decision.crashes,
                      retry_at=None)  # fmt: skip
            self.log(f"{session.name}: crash loop after {len(decision.crashes)} quick exits")
        else:
            rec.enter(now, "exited", exit_code=code, crashes=decision.crashes,
                      retry_at=decision.retry_at)  # fmt: skip

    def _rate_limited(self, rec: Record, now: float, target: Target) -> None:
        """The harness stopped for its provider's limit (§15.7): not a crash. `retry_at` is
        the fixed backoff, 15 minutes, doubling with each limit in a row up to 2 hours; the
        loop says by its exit code (23) when a run ended cleanly since its start, which
        starts the row over, as any other end of a run does. A reset time the harness names
        is not used until a real run shows where to read it (`reset_unknown` until then)."""
        pid = next((p for p, r in self.records.items() if r is rec), "")
        code = self._limit_exit_code(pid, target)
        rec.limits_unknown += 1
        backoff = min(LIMIT_BACKOFF * 2 ** (rec.limits_unknown - 1), LIMIT_BACKOFF_MAX)
        retry_at = now + backoff
        rec.enter(now, "rate_limited", "quota", detail="reset_unknown", retry_at=retry_at,
                  exit_code=code)  # fmt: skip
        self.log(f"{pid}: the harness stopped for its provider's limit; again at {stamp(retry_at)}")

    def _limit_file(self, pid: str, target: Target) -> Path:
        assert target.agent_files is not None  # noqa: S101 - connected before a launch
        return target.agent_files / "agents" / pid / adapters.LIMIT_FILE

    def _clear_limit_file(self, pid: str, target: Target) -> None:
        path = self._limit_file(pid, target)
        if not target.as_user.direct:  # through sudo, or on the ssh host
            target.as_user.run(["rm", "-f", "--", str(path)])
        else:
            path.unlink(missing_ok=True)

    def _limit_exit_code(self, pid: str, target: Target) -> int | None:
        """The harness's exit code from the loop's `limit.json`. The file is on the agents'
        side, which may have written or replaced it: a regular file only, never followed
        through a link, at most LIMIT_BYTES, and nothing but a plain exit code taken."""
        path, as_user = self._limit_file(pid, target), target.as_user
        try:
            if not as_user.direct:  # the agents' user, or the ssh host's
                # Opened without following a link and without blocking on a FIFO, so a file
                # swapped after any check cannot hold the read.
                done = as_user.run(["dd", f"if={path}", f"bs={LIMIT_BYTES}", "count=1",
                                    "iflag=nofollow,nonblock", "status=none"])  # fmt: skip
                raw = done.stdout if done.returncode == 0 else ""
            else:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        return None
                    raw = os.read(fd, LIMIT_BYTES).decode("utf-8", errors="replace")
                finally:
                    os.close(fd)
            data = json.loads(raw)
        except Exception:  # noqa: BLE001 - whatever the agents' side left there, no exit code
            return None
        code = data.get("exit_code") if isinstance(data, dict) else None
        valid = isinstance(code, int) and not isinstance(code, bool) and 0 <= code <= 255
        return code if valid else None

    # --- starting --------------------------------------------------------------------------

    def _refusal(self, p: dict[str, Any], target: Target) -> tuple[str, str | None] | None:
        limits = self.cfg.limits
        names = [p["project"], *p.get("project_aliases", [])]
        if not any(name in limits.projects for name in names):  # a renamed project stays in
            return ("project_refused", None)
        repository = p["workspace"].get("repository") or ""
        if not config.repository_allowed(repository, limits.repositories):
            return ("repository_refused", None)
        harness = self.cfg.harnesses.get(p.get("harness") or "")
        if harness is None:
            return ("harness_refused", None)
        if p.get("mode") not in harness.modes:
            return ("harness_refused", "mode_unsupported")
        model = p.get("model")
        if model is not None and model not in harness.models:
            return ("harness_refused", "model_unsupported")
        found = target.probes.get(harness.id)
        if found is not None and not found.available:
            return ("harness_missing", found.reason)
        repository = config.normalise_repository(p["workspace"].get("repository") or "")
        grant = self.cfg.repositories.get(repository, config.RepositoryGrant())
        if harness.id == "codex" and grant.allow:
            return ("harness_refused", None)  # Codex cannot honour a command allowlist
        if harness.require_sandbox and not target.sandbox.get(harness.id, False):
            return ("harness_refused", None)  # the operator asked for no run without it
        return None

    def _wait(self, rec: Record, why: str, name: str) -> int:
        if rec.waiting != why:
            rec.waiting = why
            self.log(f"{name}: not started yet: {why}")
        return 0

    def _launch(self, p: dict[str, Any], rec: Record, now: float, target: Target) -> int:
        name = session_name(p["project_id"], p["workspace"]["clone"])
        refused = self._refusal(p, target)
        if refused is not None:
            rec.enter(now, "failed", refused[0], detail=refused[1])
            return 0
        harness = self.cfg.harnesses[p["harness"]]
        if harness.id not in adapters.READY:
            return self._wait(rec, f"no adapter for {harness.id} in this version", name)
        as_user = target.as_user
        agent = p.get("agent") or {}
        try:
            place = workspace.find(
                self.cfg.state_dir,
                target.workspaces,
                p["project_id"],
                [p["project"], *p.get("project_aliases", [])],
                p["workspace"]["clone"],
                {v for v in (agent.get("id"), agent.get("handle")) if isinstance(v, str)},
                target.host,
            )
        except workspace.Refused as refused_:
            rec.enter(now, "failed", refused_.reason, detail=refused_.detail)
            return 0
        owner = agent.get("id") or agent.get("handle") or ""
        repository = p["workspace"].get("repository") or ""
        if agent.get("id") and agent.get("handle"):  # recorded under the handle before a join
            workspace.rebind(self.cfg.state_dir, place, agent["handle"], agent["id"])
        if as_user.exists(place.path):
            try:  # an existing directory that is not this agent's comes before its credential
                workspace.inspect(self.cfg, place, repository, owner, p["id"], as_user)
            except workspace.Refused as refused_:
                rec.enter(now, "failed", refused_.reason, detail=refused_.detail)
                return 0
        has_credential = as_user.exists(place.credential, "-f")
        # `rejoin` stays set until the hub sees the new credential; one rejoin per generation.
        rejoin = bool(p.get("rejoin")) and rec.joined_generation != p["generation"]
        join = rejoin or (not has_credential and not agent.get("credential_expected"))
        if not join and not has_credential:  # a credential was issued and is not in the clone
            rec.enter(now, "failed", "join_failed", detail="credential_missing")
            return 0
        if join and self.client is None:
            return 0
        retrying = rec.state in ("exited", "rate_limited")
        rec.enter(now, "starting", retry_at=None, started_at=now)
        if retrying:
            rec.restarts += 1
        task = threading.Thread(
            target=self._start,
            args=(p, rec, place, name, harness, agent, join, rejoin, target),
            daemon=True,
            name=f"maity-start-{p['id']}",
        )  # fmt: skip
        self.tasks[p["id"]] = task
        task.start()
        return 1

    def _start(
        self,
        p: dict[str, Any],
        rec: Record,
        place: workspace.Workspace,
        name: str,
        harness: config.Harness,
        agent: dict[str, Any],
        join: bool = False,
        rejoin: bool = False,
        target: Target | None = None,
    ) -> None:
        """The long part of a start, in its own thread: clone if missing, join if needed,
        then tmux."""
        target = target or self.targets[self._default_target()]
        assert target.backend is not None  # noqa: S101 - connected before a launch
        as_user = target.as_user
        owner = agent.get("id") or agent.get("handle") or ""
        try:
            if not self._wants(p["id"], p["generation"]):
                with self.lock:  # stopped or moved on while the task was queued
                    rec.enter(self.now(), "stopped", "stopped_by_hub")
                return
            workspace.prepare(
                self.cfg, place, p["workspace"].get("repository") or "", owner, p["id"],
                p["workspace"].get("branch"), as_user,
            )  # fmt: skip
            if join:
                self._join(p, place, owner, rejoin, target)
                with self.lock:
                    rec.joined_generation = p["generation"]
            if workspace.stale_index_lock(place.path, as_user=as_user):
                with self.lock:
                    rec.detail = "stale_index_lock"
            if not self._wants(p["id"], p["generation"]):  # the clone took a while
                with self.lock:
                    rec.enter(self.now(), "stopped", "stopped_by_hub")
                return
            launch = adapters.launch(self._context(p, harness, place, target))
            self._clear_limit_file(p["id"], target)  # only the loop of this run may leave one
            target.backend.start(
                name, place.path, launch.argv, launch.env, p["id"], p["generation"]
            )
        except workspace.Refused as refused:
            with self.lock:
                rec.enter(self.now(), "failed", refused.reason, detail=refused.detail,
                          exit_code=refused.exit_code)  # fmt: skip
            return
        except Retry as again:
            self.log(f"{name}: {again}; trying again in {PICKUP_RETRY:.0f} s")
            with self.lock:
                rec.retry_at = self.now() + PICKUP_RETRY
            return
        except Exception as exc:  # noqa: BLE001 - a start task never dies leaving `starting`
            # Counted like a quick exit: a passing tmux hiccup is retried after the backoff,
            # a lasting one ends in crash_loop instead of a permanent wrong reason.
            self.log(f"{name}: start failed: {type(exc).__name__}: {exc}")
            now = self.now()
            with self.lock:
                decision = restart.on_exit(
                    self.cfg.limits.restart, rec.crashes, now, now, self.rand
                )
                if decision.crash_loop:
                    rec.enter(now, "failed", "crash_loop", crashes=decision.crashes, retry_at=None)
                else:
                    rec.enter(now, "exited", crashes=decision.crashes, retry_at=decision.retry_at)
            return
        hint = target.attach_hint(name)
        with self.lock:
            rec.session_hint = hint if len(hint) <= 200 and hint.isascii() else None
        self.log(f"{name}: started generation {p['generation']}")

    # --- the join (§15.9) -------------------------------------------------------------------

    def _join(
        self,
        p: dict[str, Any],
        place: workspace.Workspace,
        owner: str,
        rejoin: bool,
        target: Target | None = None,
    ) -> None:
        """Pick up a join for the placement and run `maity join` in the clone. The URL and
        the code go to the child on stdin, never on a command line or into a log; the
        credential is written by the agent-side CLI, so the runner never holds it."""
        assert self.client is not None  # noqa: S101 - _launch checks it
        target = target or self.targets[self._default_target()]
        as_user = target.as_user
        if rejoin:  # only a rejoin removes a credential
            if not as_user.direct:
                as_user.run(["rm", "-f", "--", str(place.credential)])
            else:
                place.credential.unlink(missing_ok=True)
        try:
            pickup = self.client.call(
                "POST",
                f"/runner/placements/{p['id']}/join",
                body={"observed_generation": p["generation"]},
            )
        except hub.HubError as exc:
            if exc.status is None or exc.status >= 500 or exc.status == 429:
                raise Retry("the pickup got no answer") from None  # a re-pickup revokes it
            detail = exc.code if exc.code in PICKUP_DETAILS else None
            route = "/runner/placements/{id}/join"
            if exc.status == 404 and hub.offers(self.client.base, "post", route) is False:
                self.log(f"{place.path.name}: this hub has no runner pickup: no POST {route}")
                detail = "not_found"
            raise workspace.Refused("join_failed", detail) from None
        url, code = pickup.get("join_url"), pickup.get("code")
        if not isinstance(url, str) or not isinstance(code, str):
            raise workspace.Refused("join_failed")
        joined, why = run_join(place, url, code, self.cfg.state_dir, as_user, target.agent_path)
        if not joined:
            raise workspace.Refused("join_failed", why)
        try:
            if not as_user.direct:
                found = json.loads(as_user.read(place.credential.parent / state.STATE_FILE))
                member = found.get("member_id") if isinstance(found, dict) else None
            else:
                member = state.load_state(place.credential.parent).get("member_id")
        except (state.StateError, OSError, ValueError) as exc:  # joined; the record catches up
            self.log(f"{place.path.name}: joined, but its state cannot be read: {exc}")
            return
        if isinstance(member, str) and member != owner:
            workspace.rebind(self.cfg.state_dir, place, owner, member)

    def _context(
        self,
        p: dict[str, Any],
        harness: config.Harness,
        place: workspace.Workspace,
        target: Target | None = None,
    ) -> adapters.Context:
        target = target or self.targets[self._default_target()]
        assert target.agent_files is not None  # noqa: S101 - connected before a launch
        agent_dir = target.agent_files / "agents" / p["id"]
        target.as_user.mkdir(agent_dir)
        repository = config.normalise_repository(p["workspace"].get("repository") or "")
        found = target.probes.get(harness.id)
        private = self._private(target, place)
        return adapters.Context(
            placement=p,
            harness=harness,
            binary=found.path if found else None,
            clone=place.path,
            agent_dir=agent_dir,
            grant=self.cfg.repositories.get(repository, config.RepositoryGrant()),
            restart=self.cfg.limits.restart,
            sandbox=target.sandbox.get(harness.id, False),
            hosts=tuple(
                h
                for h in (
                    urllib.parse.urlsplit(self.cfg.hub_url).hostname,
                    urllib.parse.urlsplit(p["workspace"].get("repository") or "").hostname,
                )
                if h
            ),
            private=private,
            workspaces=target.workspaces.resolve() if target.as_user.here else target.workspaces,
            as_user=target.as_user,
        )

    def _private(self, target: Target, place: workspace.Workspace) -> tuple[Path, ...]:
        """What the agent's sandbox may not read, as the agents' side of `target` sees it: its
        user's home secrets, its own files (every agent's socket, log and settings) and the
        other clones' credentials it can list; here also the runner's state and config."""
        as_user = target.as_user
        assert target.agent_files is not None  # noqa: S101 - connected before a launch
        try:
            others = other_credentials(target.workspaces, place.path, as_user)
        except workspace.Refused:
            self.log(f"{place.path.name}: not every clone under {target.workspaces} on "
                     f"{target.name} could be listed; not starting an agent whose sandbox "
                     "might read another's credential")  # fmt: skip
            raise
        if not as_user.here:  # an ssh host: its home was read on connecting
            return private_paths(None, target.agent_files.parent, place.path, others,
                                 (target.agent_files,), here=False)  # fmt: skip
        home = config.home_of(as_user.user) if as_user.user else Path.home()
        return private_paths(self.cfg.state_dir, home, place.path, others,
                             (self.cfg.path, target.agent_files))  # fmt: skip

    @property
    def as_user(self) -> AsUser:
        """The local target's: who runs the agents on this machine."""
        local = self.targets.get("local")
        return local.as_user if local is not None else RUNNER

    def _default_target(self) -> str:
        return next(iter(self.targets), "local")

    def agent_path(self) -> str:
        """The PATH the agents get: where their sandbox tools must be found."""
        return capabilities.agent_path(self.cfg, os.environ.get("PATH", ""))

    def _wants(self, pid: str, generation: int) -> bool:
        with self.lock:
            return any(
                p["id"] == pid and p["generation"] == generation and p["desired"] == "running"
                for p in self.desired
            )

    # --- sessions nobody wants -------------------------------------------------------------

    def _orphans(
        self, target: Target, sessions: dict[str, Session], wanted: set[str], now: float
    ) -> None:
        """A session labelled with a placement this runner no longer has (deleted while it
        was offline) ends after `stop_grace_max`. A session without a label is one being
        started, or not this runner's: never touched."""
        for name, session in sessions.items():
            if session.placement is None or session.placement in wanted:
                self.orphans.pop(name, None)
                continue
            backend = target.backend
            assert backend is not None  # noqa: S101 - a target in the snapshot is connected
            if session.dead:
                backend.kill(name)
                self.orphans.pop(name, None)
                continue
            first = self.orphans.setdefault(name, now)
            if now - first >= self.cfg.limits.stop_grace_max + KILL_AFTER:
                backend.kill(name)
                self.log(f"{name}: ended (orphaned: placement {session.placement} is gone)")
            elif now - first >= self.cfg.limits.stop_grace_max:
                backend.terminate(session)

    # --- advertising -----------------------------------------------------------------------

    def _advertise(self, running: dict[str, int] | None, now: float, force: bool = False) -> None:
        """`PATCH /runner` with the targets' `running` and reachability: at most every
        ADVERTISE_EVERY seconds for a changed count, at once (`force`) for reachability."""
        if self.client is None or self.capabilities is None:
            return
        # Zero counts are left out, so a runner with nothing running matches its hello.
        counts = {
            k: v for k, v in (self.advertised_counts if running is None else running).items() if v
        }
        total = sum(counts.values())
        if not force and (
            counts == self.advertised_counts or now - self.advertised_at < ADVERTISE_EVERY
        ):
            return
        caps = {**self.capabilities, "running": total}
        entries = []
        for entry in caps.get("targets", []):
            target = self.targets.get(entry.get("name"))
            entry = {**entry, "running": counts.get(entry.get("name"), 0)}
            if target is not None:
                entry["reachable"] = target.reachable
                entry["unreachable_since"] = stamp(target.unreachable_since)
            entries.append(entry)
        caps["targets"] = entries
        try:
            self.client.call("PATCH", "/runner", body={"capabilities": caps})
        except hub.HubError as exc:
            self.log(f"supervisor: advertising running={total} failed ({exc})")
            return
        self.advertised_counts, self.advertised_at = counts, now
        self.advertised_running = total

    # --- reports ---------------------------------------------------------------------------

    def _body(self, rec: Record) -> dict[str, Any]:
        window = self.cfg.limits.restart.crash_window
        counting = rec.reason == "crash_loop" or bool(rec.crashes)
        return {
            "seq": rec.seq,
            "observed_generation": rec.generation,
            "state": rec.state,
            "reason": rec.reason,
            "detail": rec.detail,
            "exit_code": (
                rec.exit_code
                if rec.state in ("exited", "failed", "stopped", "rate_limited")
                else None
            ),
            "restarts": rec.restarts,
            "retry_at": stamp(rec.retry_at) if rec.state in ("exited", "rate_limited") else None,
            "crash_count": len(rec.crashes) if counting else None,
            "crash_window_seconds": window if counting else None,
            "deadline_at": stamp(rec.deadline_at) if rec.state == "stopping" else None,
            "target": rec.target or self._default_target(),
            "since": stamp(rec.since),
            "session_hint": rec.session_hint if rec.state in ("starting", "running") else None,
        }

    def _report(self, desired: list[dict[str, Any]]) -> None:
        with self.lock:
            outgoing: list[tuple[str, Record, dict[str, Any]]] = []
            for p in desired:
                rec = self.records.get(p["id"])
                if rec is None or rec.state is None:
                    continue
                key = rec.key()
                if key != rec.acked and (rec.pending is None or rec.pending["key"] != key):
                    rec.seq = max(rec.seq, p.get("seq") or 0) + 1  # validated in update()
                    rec.pending = {"key": key, "body": self._body(rec)}
                if rec.pending is not None:
                    outgoing.append((p["id"], rec, rec.pending))
        if not outgoing or self.client is None:
            return
        self.save()  # the seq is on disk before it is sent
        for pid, rec, pending in outgoing:
            try:
                self.client.call("POST", f"/runner/placements/{pid}/status", body=pending["body"])
            except hub.HubError as exc:
                if exc.code in ("stale_generation", "not_found"):
                    with self.lock:  # the hub moved on: settled, until the state changes
                        rec.acked, rec.pending = pending["key"], None
                    continue
                self.log(f"report for {pid} not taken ({exc}); sent again on the next tick")
                continue
            with self.lock:
                if rec.pending is pending:
                    rec.acked, rec.pending = pending["key"], None


# In the agents' home: logins and keys a sandboxed command never needs. A list, so not every
# secret a home can hold; the README says so. The forge login (gh) is not among them:
# pushing needs it, and the agents share the operator's in the single layout.
HOME_SECRETS = (
    ".ssh", ".gnupg", ".codex", ".claude", ".claude.json", ".git-credentials", ".netrc",
    ".config/maity-runner", ".local/state/maity-runner", ".aws", ".azure", ".config/gcloud",
    ".kube", ".docker", ".local/share/opencode", ".config/opencode",
)  # fmt: skip


def private_paths(
    state_dir: Path | None, home: Path, clone: Path, others: Sequence[Path] = (),
    extra: Sequence[Path] = (), here: bool = True,
) -> tuple[Path, ...]:  # fmt: skip
    """What no sandboxed command may read: the runner's state (on the runner's machine), the
    secrets in the agents' home, other clones' credentials (`others`) and `extra` (the
    runner's configuration, the agents' own files). A path that contains the clone is left
    out: it would hide the clone itself. Paths on an ssh host (`here` false) are never
    resolved against this machine's file system."""

    def norm(path: Path) -> Path:
        return path.resolve() if here else path

    clone = norm(clone)
    found = [*((norm(state_dir),) if state_dir else ()), *(home / n for n in HOME_SECRETS)]
    found += [*others, *(norm(path) for path in extra)]
    return tuple(dict.fromkeys(p for p in found if p != clone and p not in clone.parents))


def other_credentials(workspaces: Path, clone: Path, as_user: AsUser) -> list[Path]:
    """The credential directories of the other clones under `workspaces` as they stand now
    (a clone made later is covered from the agent's next start), listed as the agents' user,
    who owns them and may be the only one able to list them. A listing that is not complete
    fails closed (`workspace.Refused`): an unreadable directory could hide a credential, and
    the sandbox would start without its deny."""
    root = workspaces.resolve() if as_user.here else workspaces
    refused = workspace.Refused("harness_refused")
    if as_user.direct:
        found: list[Path] = []
        try:
            for project in root.iterdir() if root.is_dir() else ():
                if project.is_dir() and not project.is_symlink():
                    found += [d / ".git" / "maity" for d in project.iterdir()
                              if (d / ".git" / "maity").is_dir()]  # fmt: skip
        except OSError as exc:
            raise refused from exc
    elif not as_user.exists(root, "-d"):
        found = []  # no clone yet: nothing to hide
    else:
        done = as_user.run(["find", str(root), "-mindepth", "4", "-maxdepth", "4", "-type", "d",
                            "-path", "*/.git/maity", "-print0"])  # fmt: skip
        if done.returncode != 0:  # some directory could not be read: the list may be short
            raise refused
        found = [Path(p) for p in done.stdout.split("\0") if p]
    own = (clone.resolve() if as_user.here else clone) / ".git" / "maity"
    return sorted(p for p in found if p != own)


def agents_user(cfg: config.Config) -> AsUser:
    """Who runs the agents' commands on this machine: their user in the agent_user layout."""
    local = cfg.local
    return AsUser(local.agent_user if local and local.layout == "agent_user" else None)


def local_backend(cfg: config.Config) -> Tmux:
    """The tmux server of `cfg`'s local backend (also for `stop-all`, without the hub)."""
    backend = targets.local(cfg, {}).backend
    assert backend is not None  # noqa: S101 - built by targets.local
    return backend


def approved(state_dir: Path) -> dict[str, Any]:
    """Placements the operator approved on this host (`maity runner approve`)."""
    return state.load_state(state_dir, name=APPROVED_FILE) if state_dir.is_dir() else {}


def build(cfg: config.Config, client: hub.Client | None, log: Log,
          probes: dict[str, capabilities.Probe],
          capabilities_: dict[str, Any] | None = None,
          found: list[Target] | None = None) -> Supervisor:  # fmt: skip
    """The supervisor for `cfg`'s targets: `local`, or one per ssh host."""
    by_name = {t.name: t for t in (found if found is not None else targets.build(cfg, probes))}
    supervisor = Supervisor(
        cfg, by_name["local"].backend if "local" in by_name else None, client, log, probes,
        capabilities=capabilities_, targets=by_name,
    )  # fmt: skip
    supervisor.load()
    return supervisor
