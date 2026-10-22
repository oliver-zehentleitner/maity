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
import subprocess
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import __version__, hub, onboarding, state
from . import adapters, capabilities, config, loop, restart, workspace
from .asuser import RUNNER, AsUser
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
    place: workspace.Workspace, url: str, code: str, cwd: Path, as_user: AsUser = RUNNER
) -> tuple[bool, str | None]:
    """`maity join --join-file -` in the clone: (joined, the `join_failed` detail when not;
    None when the CLI's error has no code in §15.7's list).

    `MAITY_STATE_DIR` points at the clone's own state directory, so the agent-side CLI
    finds it without running git in a clone the agent can write (§5.3). Python runs isolated
    (`-I`) from a directory outside the clone, so no module in the repository is imported
    by the process that reads the code. In the agent_user layout it runs as the agents'
    user, who then owns the credential. Its output is never logged: an error names the join
    URL, and with it the token."""
    if as_user.user:  # sudo resets the environment: pass only what the join needs
        env = {state.STATE_DIR_ENV: str(place.credential.parent)}
        cwd = Path("/")
    else:
        env = {k: v for k, v in os.environ.items() if k != state.STATE_DIR_ENV}
        env[state.STATE_DIR_ENV] = str(place.credential.parent)
    command = [
        sys.executable, "-I", "-m", "maity", "join", "--join-file", "-", "--no-resume",
        "--no-pointer", "--client", f"maity-runner/{__version__}",
    ]  # fmt: skip
    try:
        done = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
            as_user.argv(command, env) if as_user.user else command,
            cwd=cwd, env=None if as_user.user else env, input=f"{url}\n{code}\n",
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
        and workspace.TOKEN.match(p["project"]) is not None
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

    def key(self) -> list[Any]:
        return [self.state, self.reason, self.detail, self.generation, self.restarts]

    def enter(self, now: float, state_: str, reason: str | None = None, **fields: Any) -> None:
        if (state_, reason) != (self.state, self.reason):
            self.since = now
        self.state, self.reason = state_, reason
        self.detail = fields.pop("detail", None)
        if state_ not in ("exited", "failed", "stopped"):
            self.exit_code = None
        for name, value in fields.items():
            setattr(self, name, value)


Log = Callable[[str], None]


@dataclass
class Supervisor:
    cfg: config.Config
    backend: Tmux
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
                 "target": "local"}
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
        try:
            sessions = self.backend.sessions()
        except TmuxError as exc:
            self.log(f"supervisor: {exc}")
            return
        with self.lock:
            desired = list(self.desired)
            synced = self.synced
            labelled = {s.placement: s for s in sessions.values() if s.placement}
            starting = sum(1 for t in self.tasks.values() if t.is_alive())
            alive = sum(1 for s in sessions.values() if not s.dead) + starting
            for placement in desired:
                name = session_name(placement["project"], placement["workspace"]["clone"])
                mine = labelled.get(placement["id"])
                other = sessions.get(name)
                blocking = other if other is not None and other is not mine else None
                try:
                    alive += self._step(placement, mine, blocking, now, alive)
                except Exception as exc:  # noqa: BLE001 - one placement never stops the rest
                    self.log(f"supervisor: {placement['id']}: {type(exc).__name__}: {exc}")
            if synced:
                wanted = {p["id"] for p in desired}
                self._orphans(sessions, wanted, now)
                for pid in [pid for pid in self.records if pid not in wanted]:
                    if pid not in self.tasks:
                        del self.records[pid]  # closed or gone: nothing left to report
                self.first_tick = False
            running = sum(1 for s in sessions.values() if not s.dead and s.placement in labelled)
        self._report(desired)
        self._advertise(running, now)
        self.save()

    # --- one placement ---------------------------------------------------------------------

    def _step(
        self,
        p: dict[str, Any],
        mine: Session | None,
        blocking: Session | None,
        now: float,
        alive: int,
    ) -> int:
        """Act on one placement. `mine` is the session labelled with it, `blocking` another
        session holding its name. Returns how many sessions it started (for capacity)."""
        pid, generation = p["id"], p["generation"]
        task = self.tasks.get(pid)
        if task is not None:
            if not task.is_alive():
                del self.tasks[pid]
            return 0  # this tick's snapshot may predate the session the task just started
        rec = self.records.setdefault(pid, Record(generation=generation, since=now))
        if rec.generation != generation:
            rec.generation, rec.restarts, rec.crashes, rec.retry_at = generation, 0, [], None
            rec.state = rec.reason = rec.detail = None
            rec.waiting = None
            rec.exit_code = None

        if p.get("desired") == "stopped":
            if mine is not None and not mine.dead:
                self._stop(rec, mine, p, now)
            else:
                if mine is not None:
                    self.backend.kill(mine.name)
                rec.enter(now, "stopped", "stopped_by_hub", deadline_at=None, kill_at=None,
                          retry_at=None)  # fmt: skip
            return 0
        if mine is None and blocking is not None:
            if blocking.placement is None:
                self._wait(rec, f"an unlabelled session {blocking.name} holds its name", pid)
            return 0  # another session holds this name: ended as an orphan first
        if mine is not None and mine.generation != generation:
            if not mine.dead:
                self._stop(rec, mine, p, now)
                return 0
            self.backend.kill(mine.name)
            mine = None
        if mine is not None and not mine.dead:
            if rec.state != "stopping" and (self.first_tick or rec.state not in LIVE):
                rec.enter(now, "running", "adopted", started_at=None)
            elif rec.state == "starting" and now - (rec.started_at or now) >= RUNNING_AFTER:
                harness = self.cfg.harnesses.get(p["harness"])
                unconfined = (
                    harness is not None
                    and harness.id == "claude-code"
                    and not capabilities.sandbox_available(harness, self.agent_path())
                )
                rec.enter(now, "running", detail="sandbox_unavailable" if unconfined else None)
            elif rec.state == "stopping":  # desired went back to running during a stop
                rec.enter(now, "running", deadline_at=None, kill_at=None)
            return 0
        if mine is not None and mine.dead:
            self._exited(rec, mine, now)
            return 0
        if rec.state == "failed" or (rec.retry_at is not None and now < rec.retry_at):
            return 0
        if self.cfg.limits.require_local_approval and pid not in approved(self.cfg.state_dir):
            rec.enter(now, "pending", "awaiting_operator")  # §7.1: `maity runner approve`
            return 0
        if alive >= self.cfg.limits.max_agents:
            rec.enter(now, "pending", "capacity")
            return 0
        return self._launch(p, rec, now)

    def _stop(self, rec: Record, session: Session, p: dict[str, Any], now: float) -> None:
        if rec.state != "stopping":
            grace = min(int(p.get("stop_grace_seconds") or 0), self.cfg.limits.stop_grace_max)
            rec.enter(now, "stopping", deadline_at=now + grace, kill_at=None)
        elif rec.kill_at is None and now >= (rec.deadline_at or now):
            self.backend.terminate(session)
            rec.kill_at = now + KILL_AFTER
        elif rec.kill_at is not None and now >= rec.kill_at:
            self.backend.kill(session.name)

    def _exited(self, rec: Record, session: Session, now: float) -> None:
        self.backend.kill(session.name)
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
            rec.enter(now, "failed", "crash_loop", detail="hot_loop", exit_code=code, retry_at=None)
            return
        decision = restart.on_exit(self.cfg.limits.restart, rec.crashes, started, now, self.rand)
        if decision.crash_loop:
            rec.enter(now, "failed", "crash_loop", exit_code=code, crashes=decision.crashes,
                      retry_at=None)  # fmt: skip
            self.log(f"{session.name}: crash loop after {len(decision.crashes)} quick exits")
        else:
            rec.enter(now, "exited", exit_code=code, crashes=decision.crashes,
                      retry_at=decision.retry_at)  # fmt: skip

    # --- starting --------------------------------------------------------------------------

    def _refusal(self, p: dict[str, Any]) -> tuple[str, str | None] | None:
        limits = self.cfg.limits
        if p["project"] not in limits.projects:
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
        found = self.probes.get(harness.id)
        if found is not None and not found.available:
            return ("harness_missing", found.reason)
        repository = config.normalise_repository(p["workspace"].get("repository") or "")
        grant = self.cfg.repositories.get(repository, config.RepositoryGrant())
        if harness.id == "codex" and grant.allow:
            return ("harness_refused", None)  # Codex cannot honour a command allowlist
        if harness.require_sandbox and not capabilities.sandbox_available(
            harness, self.agent_path()
        ):
            return ("harness_refused", None)  # the operator asked for no run without it
        return None

    def _wait(self, rec: Record, why: str, name: str) -> int:
        if rec.waiting != why:
            rec.waiting = why
            self.log(f"{name}: not started yet: {why}")
        return 0

    def _launch(self, p: dict[str, Any], rec: Record, now: float) -> int:
        name = session_name(p["project"], p["workspace"]["clone"])
        refused = self._refusal(p)
        if refused is not None:
            rec.enter(now, "failed", refused[0], detail=refused[1])
            return 0
        harness = self.cfg.harnesses[p["harness"]]
        if harness.id not in adapters.READY:
            return self._wait(rec, f"no adapter for {harness.id} in this version", name)
        if self.cfg.local is None:
            return 0
        try:
            place = workspace.locate(
                self.cfg.local.workspaces, p["project"], p["workspace"]["clone"]
            )
        except workspace.Refused as refused_:
            rec.enter(now, "failed", refused_.reason, detail=refused_.detail)
            return 0
        agent = p.get("agent") or {}
        owner = agent.get("id") or agent.get("handle") or ""
        repository = p["workspace"].get("repository") or ""
        if agent.get("id") and agent.get("handle"):  # recorded under the handle before a join
            workspace.rebind(self.cfg.state_dir, place, agent["handle"], agent["id"])
        if self.as_user.exists(place.path):
            try:  # an existing directory that is not this agent's comes before its credential
                workspace.inspect(self.cfg, place, repository, owner, p["id"], self.as_user)
            except workspace.Refused as refused_:
                rec.enter(now, "failed", refused_.reason, detail=refused_.detail)
                return 0
        has_credential = self.as_user.exists(place.credential, "-f")
        # `rejoin` stays set until the hub sees the new credential; one rejoin per generation.
        rejoin = bool(p.get("rejoin")) and rec.joined_generation != p["generation"]
        join = rejoin or (not has_credential and not agent.get("credential_expected"))
        if not join and not has_credential:  # a credential was issued and is not in the clone
            rec.enter(now, "failed", "join_failed", detail="credential_missing")
            return 0
        if join and self.client is None:
            return 0
        retrying = rec.state == "exited"
        rec.enter(now, "starting", retry_at=None, started_at=now)
        if retrying:
            rec.restarts += 1
        task = threading.Thread(
            target=self._start, args=(p, rec, place, name, harness, agent, join, rejoin),
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
    ) -> None:
        """The long part of a start, in its own thread: clone if missing, join if needed,
        then tmux."""
        owner = agent.get("id") or agent.get("handle") or ""
        try:
            if not self._wants(p["id"], p["generation"]):
                with self.lock:  # stopped or moved on while the task was queued
                    rec.enter(self.now(), "stopped", "stopped_by_hub")
                return
            workspace.prepare(
                self.cfg, place, p["workspace"].get("repository") or "", owner, p["id"],
                p["workspace"].get("branch"), self.as_user,
            )  # fmt: skip
            if join:
                self._join(p, place, owner, rejoin)
                with self.lock:
                    rec.joined_generation = p["generation"]
            if workspace.stale_index_lock(place.path, as_user=self.as_user):
                with self.lock:
                    rec.detail = "stale_index_lock"
            if not self._wants(p["id"], p["generation"]):  # the clone took a while
                with self.lock:
                    rec.enter(self.now(), "stopped", "stopped_by_hub")
                return
            launch = adapters.launch(self._context(p, harness, place))
            self.backend.start(name, place.path, launch.argv, launch.env, p["id"], p["generation"])
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
        hint = f"tmux -S {self.backend.socket} attach -t {name}"
        with self.lock:
            rec.session_hint = hint if len(hint) <= 200 and hint.isascii() else None
        self.log(f"{name}: started generation {p['generation']}")

    # --- the join (§15.9) -------------------------------------------------------------------

    def _join(
        self, p: dict[str, Any], place: workspace.Workspace, owner: str, rejoin: bool
    ) -> None:
        """Pick up a join for the placement and run `maity join` in the clone. The URL and
        the code go to the child on stdin, never on a command line or into a log; the
        credential is written by the agent-side CLI, so the runner never holds it."""
        assert self.client is not None  # noqa: S101 - _launch checks it
        if rejoin:  # only a rejoin removes a credential
            if self.as_user.user:
                self.as_user.run(["rm", "-f", "--", str(place.credential)])
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
            raise workspace.Refused("join_failed", detail) from None
        url, code = pickup.get("join_url"), pickup.get("code")
        if not isinstance(url, str) or not isinstance(code, str):
            raise workspace.Refused("join_failed")
        joined, why = run_join(place, url, code, self.cfg.state_dir, self.as_user)
        if not joined:
            raise workspace.Refused("join_failed", why)
        try:
            if self.as_user.user:
                found = json.loads(self.as_user.read(place.credential.parent / state.STATE_FILE))
                member = found.get("member_id") if isinstance(found, dict) else None
            else:
                member = state.load_state(place.credential.parent).get("member_id")
        except (state.StateError, OSError, ValueError) as exc:  # joined; the record catches up
            self.log(f"{place.path.name}: joined, but its state cannot be read: {exc}")
            return
        if isinstance(member, str) and member != owner:
            workspace.rebind(self.cfg.state_dir, place, owner, member)

    def _context(
        self, p: dict[str, Any], harness: config.Harness, place: workspace.Workspace
    ) -> adapters.Context:
        assert self.cfg.local is not None  # noqa: S101 - the local backend's supervisor
        agent_dir = self.cfg.local.agent_files / "agents" / p["id"]
        self.as_user.mkdir(agent_dir)
        repository = config.normalise_repository(p["workspace"].get("repository") or "")
        found = self.probes.get(harness.id)
        workspaces = self.cfg.local.workspaces
        # The agents' side, as the agents' user sees it: its home, its files (tmux socket,
        # every agent's log and settings) and the clones it owns.
        home = config.home_of(self.as_user.user) if self.as_user.user else Path.home()
        private = private_paths(
            self.cfg.state_dir, home, place.path,
            other_credentials(workspaces, place.path, self.as_user),
            (self.cfg.path, self.cfg.local.agent_files),
        )  # fmt: skip
        return adapters.Context(
            placement=p,
            harness=harness,
            binary=found.path if found else None,
            clone=place.path,
            agent_dir=agent_dir,
            grant=self.cfg.repositories.get(repository, config.RepositoryGrant()),
            restart=self.cfg.limits.restart,
            sandbox=capabilities.sandbox_available(harness, self.agent_path()),
            hosts=tuple(
                h
                for h in (
                    urllib.parse.urlsplit(self.cfg.hub_url).hostname,
                    urllib.parse.urlsplit(p["workspace"].get("repository") or "").hostname,
                )
                if h
            ),
            private=private,
            workspaces=workspaces.resolve() if workspaces else None,
            as_user=self.as_user,
        )

    @property
    def as_user(self) -> AsUser:
        local = self.cfg.local
        return AsUser(local.agent_user if local and local.layout == "agent_user" else None)

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

    def _orphans(self, sessions: dict[str, Session], wanted: set[str], now: float) -> None:
        """A session labelled with a placement this runner no longer has (deleted while it
        was offline) ends after `stop_grace_max`. A session without a label is one being
        started, or not this runner's: never touched."""
        for name, session in sessions.items():
            if session.placement is None or session.placement in wanted:
                self.orphans.pop(name, None)
                continue
            if session.dead:
                self.backend.kill(name)
                self.orphans.pop(name, None)
                continue
            first = self.orphans.setdefault(name, now)
            if now - first >= self.cfg.limits.stop_grace_max + KILL_AFTER:
                self.backend.kill(name)
                self.log(f"{name}: ended (orphaned: placement {session.placement} is gone)")
            elif now - first >= self.cfg.limits.stop_grace_max:
                self.backend.terminate(session)

    # --- advertising -----------------------------------------------------------------------

    def _advertise(self, running: int, now: float) -> None:
        """`PATCH /runner` with the new `running`, at most every ADVERTISE_EVERY seconds."""
        if self.client is None or self.capabilities is None:
            return
        if running == self.advertised_running or now - self.advertised_at < ADVERTISE_EVERY:
            return
        caps = {**self.capabilities, "running": running}
        caps["targets"] = [{**t, "running": running} for t in caps.get("targets", [])]
        try:
            self.client.call("PATCH", "/runner", body={"capabilities": caps})
        except hub.HubError as exc:
            self.log(f"supervisor: advertising running={running} failed ({exc})")
            return
        self.advertised_running, self.advertised_at = running, now

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
            "exit_code": rec.exit_code if rec.state in ("exited", "failed", "stopped") else None,
            "restarts": rec.restarts,
            "retry_at": stamp(rec.retry_at) if rec.state == "exited" else None,
            "crash_count": len(rec.crashes) if counting else None,
            "crash_window_seconds": window if counting else None,
            "deadline_at": stamp(rec.deadline_at) if rec.state == "stopping" else None,
            "target": "local",
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
    state_dir: Path, home: Path, clone: Path, others: Sequence[Path] = (),
    extra: Sequence[Path] = (),
) -> tuple[Path, ...]:  # fmt: skip
    """What no sandboxed command may read: the runner's state, the secrets in the agents'
    home, other clones' credentials (`others`) and `extra` (the runner's configuration, the
    agents' own files). A path that contains the clone is left out: it would hide the
    clone itself."""
    clone = clone.resolve()
    found = [state_dir.resolve(), *(home / name for name in HOME_SECRETS), *others]
    found += [path.resolve() for path in extra]
    return tuple(dict.fromkeys(p for p in found if p != clone and p not in clone.parents))


def other_credentials(workspaces: Path, clone: Path, as_user: AsUser) -> list[Path]:
    """The credential directories of the other clones under `workspaces` as they stand now
    (a clone made later is covered from the agent's next start), listed as the agents' user,
    who owns them and may be the only one able to list them."""
    root = workspaces.resolve()
    if not as_user.user:
        found = [d / ".git" / "maity" for d in root.glob("*/*") if (d / ".git" / "maity").is_dir()]
    else:
        done = as_user.run(["find", str(root), "-mindepth", "4", "-maxdepth", "4", "-type", "d",
                            "-path", "*/.git/maity", "-print0"])  # fmt: skip
        found = [Path(p) for p in done.stdout.split("\0") if p] if done.returncode == 0 else []
    own = clone.resolve() / ".git" / "maity"
    return sorted(p for p in found if p != own)


def local_backend(cfg: config.Config) -> Tmux:
    """The tmux server of `cfg`'s local backend (also for `stop-all`, without the hub)."""
    assert cfg.local is not None  # noqa: S101 - config.parse guarantees it for kind = local
    as_user = AsUser(cfg.local.agent_user if cfg.local.layout == "agent_user" else None)
    return Tmux(
        socket=cfg.local.tmux_socket,
        conf=cfg.local.agent_files / "tmux.conf",
        home=str(as_user.home()) if as_user.user else os.environ.get("HOME", ""),
        agent_path=capabilities.agent_path(cfg, os.environ.get("PATH", "")),
        logs=cfg.local.agent_files / LOGS,
        as_user=as_user,
    )


def approved(state_dir: Path) -> dict[str, Any]:
    """Placements the operator approved on this host (`maity runner approve`)."""
    return state.load_state(state_dir, name=APPROVED_FILE) if state_dir.is_dir() else {}


def build(cfg: config.Config, client: hub.Client | None, log: Log,
          probes: dict[str, capabilities.Probe],
          capabilities_: dict[str, Any] | None = None) -> Supervisor:  # fmt: skip
    """The supervisor for the local backend of `cfg`."""
    supervisor = Supervisor(
        cfg, local_backend(cfg), client, log, probes, capabilities=capabilities_
    )
    supervisor.load()
    return supervisor
