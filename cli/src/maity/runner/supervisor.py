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
import secrets
import subprocess
import threading
import time
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import __version__, clonecheck, hub, onboarding, state
from . import (
    adapters,
    capabilities,
    config,
    limitread,
    loop,
    restart,
    scratch,
    scratchop,
    targets,
    workspace,
)
from .asuser import RUNNER, AsUser, Unreachable
from .capabilities import ClaudeSeccomp
from .targets import Target
from .tmux import IDLE, WAITING, WORKING, Session, Tmux, TmuxError, session_name

TICK = 5.0
PICKUP_RETRY = 15.0
JOIN_TIMEOUT = 120.0
# `join_failed` carries the hub's own error code (§15.7): any code in this form, never text.
DETAIL_CODE = hub.ERROR_CODE  # fullmatch only
# The child's last stderr line under MAITY_ERROR_LINE=<nonce> (cli.main), and nothing else.
_ERROR_LINE = re.compile(
    r"maity-error ([0-9a-f]{32}): (?:-|([a-z][a-z0-9_]{0,63})(?: ([a-z][a-z0-9_]{0,63}))?)"
)


def join_detail(code: str | None, reason: Any = None) -> str | None:
    """The `join_failed` detail for a hub refusal: its error code, or for `forbidden` the
    `details.reason` that says which rule refused (`member_join_limit`, `member_agents_max`,
    §3.1). None when neither has the form of a code, or `code` is no string at all."""
    if code == "forbidden" and isinstance(reason, str) and DETAIL_CODE.fullmatch(reason):
        return reason
    return code if isinstance(code, str) and DETAIL_CODE.fullmatch(code) else None


def _code_or_dash(value: Any) -> str:
    """`value` when it has the form of a code, else `-`: only values of code form reach the
    log, so no line break, control character, message text or token-shaped value does. The
    form says nothing about where a value came from: an unknown code shows as itself."""
    return value if isinstance(value, str) and DETAIL_CODE.fullmatch(value) else "-"


def refusal_line(step: str, code: Any, reason: Any = None, why: Any = None) -> str:
    """The warning the runner logs for a refused join step (`pickup` or `exchange`, §15.9):
    the hub's code, `details.reason` and `details.why`, each in code form or `-`. A pickup's
    `pickup_not_allowed` names its cause only in `why` (`credential_issued`, `handle_taken`,
    …), which the reported detail does not carry (tsk-fveaj86ec6e2)."""
    return (
        f"warning: join {step} refused: {_code_or_dash(code)}"
        f" (reason {_code_or_dash(reason)}, why {_code_or_dash(why)})"
    )


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
    """`maity join --join-file -` in the clone: (joined, the `join_failed` detail when not:
    the hub's code, `network`, or None). The detail comes only from the child's last stderr
    line, `maity-error <nonce>: …` with this call's own nonce (`MAITY_ERROR_LINE`), built from
    the error's code fields: no message or traceback text knows the nonce, so none can pass for
    a code.

    `MAITY_STATE_DIR` points at the clone's own state directory, so the agent-side CLI
    finds it without running git in a clone the agent can write (§5.3). Python runs isolated
    (`-I`) from a directory outside the clone, so no module in the repository is imported
    by the process that reads the code. In the agent_user layout it runs as the agents'
    user, who then owns the credential; on an ssh host it is the host's own `maity`, found
    on the target's `agent_path`. Its output is never logged: an error names the join URL,
    and with it the token."""
    nonce = secrets.token_hex(16)  # only this call's own machine line carries it
    if not as_user.direct:  # sudo and ssh start empty: pass only what the join needs
        env = {state.STATE_DIR_ENV: str(place.credential.parent), hub.ERROR_LINE_ENV: nonce}
        if not as_user.here and agent_path:
            env["PATH"] = agent_path
        cwd = Path("/")
    else:
        env = {k: v for k, v in os.environ.items() if k != state.STATE_DIR_ENV}
        env[state.STATE_DIR_ENV] = str(place.credential.parent)
        env[hub.ERROR_LINE_ENV] = nonce
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
    lines = done.stderr.splitlines()
    found = _ERROR_LINE.fullmatch(lines[-1]) if lines else None
    if found is None or not secrets.compare_digest(found.group(1), nonce) or not found.group(2):
        return False, None
    if found.group(2) == "network" and found.group(3) is None:
        return False, "network"
    return False, join_detail(found.group(2), found.group(3))


RUNNING_AFTER = 10.0  # a process alive this long is `running`
# Codex's folder prompt at an interactive start (Codex 0.169, tui/src/onboarding): the
# runner answers only its restricted choice, looked for this long after the start.
FOLDER_PROMPT = "Folder access"
OPEN_RESTRICTED = "Open restricted"
TRUST_FOLDER = "Trust and continue"
FOLDER_PROMPT_WITHIN = 180.0
# The harnesses whose run without their OS sandbox is reported (`sandbox_unavailable`): those
# whose allowlist relies on it. Codex's sandbox is its whole confinement and is checked apart.
UNCONFINED_REPORTED = ("claude-code", "antigravity")
KILL_AFTER = 10.0  # from SIGTERM to kill-session
ACTUAL_FILE = "actual.json"
# The random leaf names the runner chose for each agy `/tmp` scratch (workspace layout): the
# name is not the placement id, so the runner keeps the names here to find each placement's own
# scratch again for removal on close and across a runner restart. Its own file, not the clone's,
# which the agent can write.
TMP_NAMES_FILE = "tmp_scratch.json"
# placement id -> leaves under the per-user `/tmp` parent an earlier start could not remove,
# retried at every start and at the close, so a failed removal orphans nothing (review A1769).
TMP_STALE_FILE = "tmp_scratch_stale.json"
APPROVED_FILE = "approved.json"
LOGS = "logs"
# The agent-side state the runner reads after a join (its member id): far below this.
STATE_MAX = 64 * 1024
ADVERTISE_EVERY = 60.0  # at most one PATCH /runner for a changed `running` per this
SIZE_EVERY = 600.0  # a placement's clone and scratch are measured at most this often
LIVE = ("starting", "running", "stopping")
# The idle check of an interactive session (§15.14): a pane is read at most once per IDLE_EVERY;
# the minutes come from the placement's `health.settings`, these are the contract's defaults.
IDLE_EVERY = 60.0
HANG_AFTER_MINUTES = 30
REPLY_WITHIN_MINUTES = 10
TYPED_TRIES, TYPED_PAUSE = 10, 0.2  # up to 2 s for the nudge's line to show in the pane
NUDGE_CAP = 3  # nudges answered in a row without a `maity wait`: the next quiet spell ends it
NUDGE_LINE = (
    "maity runner: you have not been listening for a while: no `maity wait` ran and nothing "
    "changed on this screen. Run `maity resume` if you lost track, then go back to your wait "
    "loop."
)
LIMIT_BACKOFF = 15 * 60.0  # reset_unknown: 15 min, doubling ...
LIMIT_BACKOFF_MAX = 2 * 3600.0  # ... up to 2 h
PLACEMENT_ID = clonecheck.PLACEMENT_ID  # one pattern, beside clonecheck.placement_id
HARNESS_ID = re.compile(r"^[a-z0-9-]{1,40}$")


def valid(p: Any) -> bool:
    """The fields the runner builds paths, names and URLs from, checked before any use."""
    if not isinstance(p, dict):
        return False
    space = p.get("workspace")
    generation = p.get("generation")
    return (
        isinstance(p.get("id"), str)
        and PLACEMENT_ID.fullmatch(p["id"]) is not None
        and isinstance(p.get("project"), str)
        and workspace.FULL_NAME.fullmatch(p["project"]) is not None
        and isinstance(p.get("project_id"), str)
        and workspace.TOKEN.fullmatch(p["project_id"]) is not None
        and isinstance(p.get("project_aliases", []), list)
        and all(
            isinstance(a, str) and workspace.FULL_NAME.fullmatch(a) is not None
            for a in p.get("project_aliases", [])
        )
        and isinstance(generation, int)
        and not isinstance(generation, bool)
        and generation >= 1
        and p.get("desired") in ("running", "stopped")
        and isinstance(space, dict)
        and isinstance(space.get("clone"), str)
        and workspace.TOKEN.fullmatch(space["clone"]) is not None
        and isinstance(p.get("harness"), str)
        and HARNESS_ID.fullmatch(p["harness"]) is not None
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


def agent_dir_for(as_user: AsUser, agent_files: Path, placement: str) -> Path:
    """`<agent files>/agents/<placement>`, made as the agents' user: `agents/` made and kept
    0700 by the runner itself, since a mkdir with parents gives the mode to the last directory
    only, so under a umask of 002 it would be 0775, which `maity gh`'s lead commands refuse
    (`ghpr.owned_layout`, review A1758 of #2054); an older runner's 0775 is tightened."""
    agents = agent_files / "agents"
    as_user.mkdir(agents)
    as_user.tighten(agents)
    agent_dir = agents / placement
    as_user.mkdir(agent_dir)
    return agent_dir


def stamp(moment: float | None) -> str | None:
    if moment is None:
        return None
    return datetime.fromtimestamp(moment, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class GateView:
    """What the start gate decided on for one harness: its probe and its sandbox. The
    launch uses the same view, so a tool the keeper swaps in between (§15.16) never starts
    under the other binary's sandbox decision."""

    found: capabilities.Probe | None
    sandbox: bool
    held: bool

    @staticmethod
    def of(target: Target, harness_id: str) -> GateView:
        return GateView(
            target.probes.get(harness_id),
            target.sandbox.get(harness_id, False),
            harness_id in target.held,
        )


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
    # The idle check of an interactive session (§15.14): when it was last read, a hash of
    # its pane then, since when it is quiet, when it was nudged, when it was ended for it.
    idle_checked_at: float | None = None
    pane: str | None = None
    quiet_since: float | None = None
    nudged_at: float | None = None
    hung_at: float | None = None
    hung_exits: list[float] = field(default_factory=list)  # for the crash cap (§15.14)
    binary: str | None = None  # the harness binary this session started with (§15.16)
    # Its OS sandbox as the start gate decided (GateView); None for a record from before.
    sandbox: bool | None = None
    resume: bool = False  # the next start resumes the harness's session (after `hung`)
    # Fresh sessions started in this generation (§15.7 `sessions`), and whether the hub reads
    # them: one whose placement carries `fresh_session` (§15.6) takes the field in a report.
    sessions: int = 0
    reports_sessions: bool = False
    nudges: int = 0  # nudges answered since a `maity wait` was last seen
    unsent: bool = False  # the nudge's line is typed but did not show yet: Enter waits for it
    left_typed: bool = False  # a dropped nudge's line may still sit in the input: not again
    # The sizes of its clone and its scratch as last measured (§15.5), for `maity runner
    # status`; None until measured or where there is none.
    clone_bytes: int | None = None
    scratch_bytes: int | None = None
    sized_at: float | None = None
    # Codex's folder prompt at an interactive start: None while looked for, else `answered`,
    # `left` (a prompt the runner does not answer, until it is gone) or `none` (not seen in
    # time, or gone).
    folder_prompt: str | None = None

    def calm(self) -> None:
        """Forget the idle check: a new start, or an agent that is listening again."""
        self.idle_checked_at = self.pane = self.quiet_since = self.nudged_at = None
        self.nudges, self.unsent, self.left_typed = 0, False, False

    def key(self) -> list[Any]:
        # Not `sessions`: it moves only at a start, between `starting` and `running`, and the
        # report of `running` carries it; a key of its own would send `starting` twice.
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


def changed(pid: str, rec: Record) -> str:
    """The log line for a placement's new reported state: codes and numbers only, so no
    URL, join code or credential can reach it."""
    words = [w for w in (rec.state, rec.reason, rec.detail) if w]
    restarts = f", restart {rec.restarts}" if rec.restarts else ""
    return f"{pid}: {' '.join(words)} (generation {rec.generation}{restarts})"


def _minutes(value: Any, default: int) -> float:
    """A `health.settings` value in seconds: an integer from 1 to 1440 (§15.14), else the
    default."""
    good = isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 1440
    return float(value if good else default) * 60


@dataclass
class Supervisor:
    cfg: config.Config
    backend: Tmux | None  # the local target's tmux server; None on the ssh backend
    client: hub.Client | None
    log: Log
    probes: dict[str, capabilities.Probe]
    now: Callable[[], float] = time.time
    rand: Callable[[], float] = random.random
    pause: Callable[[float], None] = time.sleep
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
    # A reconnect bumps `invalidation_gen`; a successful advertise records the generation it sent
    # for in `advertised_gen`. They differ exactly while a reconnect's resend is still owed, which
    # forces `_advertise` to send whatever the count is and gates the commit against a race.
    invalidation_gen: int = 0
    advertised_gen: int = 0
    targets: dict[str, Target] = field(default_factory=dict)
    target_errors: dict[str, str] = field(default_factory=dict)  # the last one logged
    # The placements the hub reads as closed (`GET /runner/placements?closed=true`), and those
    # whose scratch is gone since this service started (§15.5).
    closed_placements: list[dict[str, Any]] = field(default_factory=list)
    scratch_cleared: set[str] = field(default_factory=set)
    # placement id -> the random leaf name of its agy `/tmp` scratch (TMP_NAMES_FILE).
    scratch_names: dict[str, str] = field(default_factory=dict)
    # placement id -> earlier leaves not yet removed (TMP_STALE_FILE).
    scratch_stale: dict[str, list[str]] = field(default_factory=dict)
    # Serialises the TMP_NAMES_FILE write: `_save_scratch_names` holds it across snapshot + write,
    # so two start threads (or a start and a tick) never race a stale snapshot over a fresh one.
    scratch_names_lock: threading.Lock = field(default_factory=threading.Lock)

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

    def closed(self, placements: list[dict[str, Any]]) -> None:
        """The hub's closed placements of this runner: their scratch goes at the next tick."""
        good = [
            p for p in placements
            if isinstance(p, dict) and isinstance(p.get("id"), str)
            and PLACEMENT_ID.fullmatch(p["id"]) is not None and p.get("active") is False
            and isinstance(p.get("project_id"), str)
            and workspace.TOKEN.fullmatch(p["project_id"]) is not None
        ]  # fmt: skip
        with self.lock:
            self.closed_placements = good

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
        names = state.load_state(self.cfg.state_dir, name=TMP_NAMES_FILE)
        self.scratch_names = {
            pid: leaf for pid, leaf in names.items()
            if isinstance(pid, str) and isinstance(leaf, str)
        }  # fmt: skip
        stale = state.load_state(self.cfg.state_dir, name=TMP_STALE_FILE)
        self.scratch_stale = {
            pid: [leaf for leaf in leaves if isinstance(leaf, str)]
            for pid, leaves in stale.items()
            if isinstance(pid, str) and isinstance(leaves, list)
        }  # fmt: skip

    def save(self) -> None:
        with self.lock:
            data = {pid: asdict(r) for pid, r in self.records.items()}
        state.save_state(self.cfg.state_dir, data, name=ACTUAL_FILE)
        self._save_scratch_names()

    def _save_scratch_names(self) -> None:
        """Persist the agy `/tmp` scratch leaf names (TMP_NAMES_FILE): written as soon as one is
        chosen or cleared, so a crash never leaves the runner unable to find a leaf to remove.
        `scratch_names_lock` is held across the snapshot and the write, so a concurrent `_start`
        worker or a `tick()` cannot write a stale snapshot over a fresher one (the write is not
        under `self.lock`, so it never blocks a tick)."""
        with self.scratch_names_lock:
            with self.lock:
                names = dict(self.scratch_names)
                stale = {pid: list(leaves) for pid, leaves in self.scratch_stale.items() if leaves}
            # The stale record first: a leaf moved there from the names record must be on disk
            # there before the names record forgets it, so a stop between the two writes loses
            # no leaf (review A1769); it is then in both, and its second removal finds nothing.
            state.save_state(self.cfg.state_dir, stale, name=TMP_STALE_FILE)
            state.save_state(self.cfg.state_dir, names, name=TMP_NAMES_FILE)

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
        self._clear_scratch(set(labelled), set(snapshots))
        self._measure(desired, now)
        self.save()

    # --- the scratch (§15.5) ---------------------------------------------------------------

    def _clear_scratch(self, live: set[str], seen: set[str]) -> None:
        """Remove the scratch of each placement the hub reads as closed, on every target whose
        sessions this tick read (`seen`), unless a session of it still runs; a target whose
        sessions could not be read keeps every scratch until they can. Each removal is logged
        and written to `removed.jsonl`. A placement whose scratch could not be removed
        everywhere is tried again."""
        with self.lock:
            closed = [p for p in self.closed_placements
                      if p["id"] not in self.scratch_cleared and p["id"] not in live]  # fmt: skip
        for p in closed:
            done = True
            for target in self.targets.values():
                if target.name not in seen or (target.remote and target.agent_files is None):
                    done = False  # its sessions are unknown: unknown means kept
                    continue
                if not self._remove_tmpdir(p, target):
                    done = False
                if target.as_user.here and not self._remove_stale(p, target):
                    done = False  # an earlier leaf still there: tried again next time
                try:
                    located = self._scratch_location(p, target)
                    if located is None:
                        continue  # no /tmp scratch on this target (an ssh host): none to remove
                    path, in_tmp = located
                    removed = (
                        scratch.tmp_remove(path, target.as_user)
                        if in_tmp
                        else scratch.remove(path, target.as_user)
                    )
                except workspace.Refused:
                    break
                except scratchop.OnTheWay as exc:  # a link, a foreign-owned or wrong-shaped
                    self.log(f"{p['id']}: scratch left on {target.name}: "  # name; logged once
                             f"{onboarding.inline(str(exc))[:200]}")  # fmt: skip
                    continue
                except (OSError, subprocess.SubprocessError) as exc:
                    self.log(f"{p['id']}: scratch not removed on {target.name}: {exc}")
                    done = False
                    continue
                if removed is not None:
                    scratch.log_removal(self.cfg.state_dir, p["id"], path, removed, "closed")
                    self.log(f"{p['id']}: scratch removed on {target.name} ({removed} bytes): "
                             "the placement is closed")  # fmt: skip
                if not self._remove_pg_pass(p, target):
                    done = False
            if done:
                with self.lock:
                    self.scratch_cleared.add(p["id"])
                    had_name = self.scratch_names.pop(p["id"], None) is not None
                if had_name:  # its recorded leaf is gone with it
                    self._save_scratch_names()

    def _remove_tmpdir(self, p: dict[str, Any], target: Target) -> bool:
        """Remove the leaf of a closed placement's own TMPDIR (`_tmpdir`) under the per-user
        `/tmp` parent, when it had one: a placement whose scratch is beside its clone records
        a leaf name only for that. agy's leaf is its scratch and goes with it
        (`_scratch_location`). False when the removal should be tried again; a link or a
        directory another user holds is logged and left, as for a scratch."""
        if workspace.scratch_in_tmp(p.get("harness") or ""):
            return True
        with self.lock:
            leaf = self.scratch_names.get(p["id"])
        if leaf is None or not target.as_user.here:
            return True
        try:
            path = workspace.tmp_scratch_of(target.as_user.uid(), leaf)
            removed = scratch.tmp_remove(path, target.as_user)
        except workspace.Refused:
            return True
        except scratchop.OnTheWay as exc:
            self.log(f"{p['id']}: TMPDIR left on {target.name}: "
                     f"{onboarding.inline(str(exc))[:200]}")  # fmt: skip
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            self.log(f"{p['id']}: TMPDIR not removed on {target.name}: {exc}")
            return False
        if removed is not None:
            scratch.log_removal(self.cfg.state_dir, p["id"], path, removed, "closed")
            self.log(f"{p['id']}: TMPDIR removed on {target.name} ({removed} bytes): "
                     "the placement is closed")  # fmt: skip
        return True

    def _remove_pg_pass(self, p: dict[str, Any], target: Target) -> bool:
        """The closed placement's test cluster password file removed from the holder on
        `target` (its name only, never through a link); False when it could not be, so the
        sweep tries again. The password itself is never logged."""
        if not workspace.SCRATCH_ID.fullmatch(p["id"]):
            return True
        root = target.workspaces if target.host else target.workspaces.resolve()
        leaf = root / scratchop.PG_HOLDER / p["id"]
        try:
            target.as_user.pg("remove", root, leaf)
        except scratchop.Unsupported:  # a host whose maity has no holder made none to remove
            return True
        except scratchop.OnTheWay as exc:  # a holder that is a link or another user's: left
            self.log(f"{p['id']}: password file left on {target.name}: "
                     f"{onboarding.inline(str(exc))[:200]}")  # fmt: skip
        except (OSError, subprocess.SubprocessError) as exc:
            self.log(f"{p['id']}: password file not removed on {target.name}: "
                     f"{onboarding.inline(str(exc))[:200]}")  # fmt: skip
            return False
        return True

    def _measure(self, desired: list[dict[str, Any]], now: float) -> None:
        """The sizes of each placement's clone and scratch on its target, at most every
        SIZE_EVERY, for `maity runner status` (§15.5); never sent to the hub."""
        for p in desired:
            with self.lock:
                rec = self.records.get(p["id"])
                where = rec.target if rec is not None else None
                due = rec is not None and (rec.sized_at is None or now - rec.sized_at >= SIZE_EVERY)
            target = self.targets.get(where or self._default_target())
            if rec is None or not due or target is None or not target.reachable:
                continue
            try:
                harness = self.cfg.harnesses.get(p.get("harness") or "")
                place = workspace.locate(
                    target.workspaces, p["project_id"], p["workspace"]["clone"], target.host,
                    folder=workspace.uses_folder(harness.id if harness else ""),
                )  # fmt: skip
                located = self._scratch_location(p, target)
            except workspace.Refused:
                continue
            clone = scratch.size(place.path, target.as_user)
            if located is None:
                room = None
            elif located[1]:
                room = scratch.tmp_measure(located[0], target.as_user)
            else:
                room = scratch.measure(located[0], target.as_user)
            with self.lock:
                rec.clone_bytes, rec.scratch_bytes, rec.sized_at = clone, room, now

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
                record.sessions = 0  # the failure report is the new generation's (§15.7)
            record.reports_sessions = "fresh_session" in p
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
        if not up and target.remote:
            # The host that answers under this name when it comes back may be another machine
            # or a new kernel: its seccomp preflight is read again (_seccomp).
            target.seccomp = None
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
        rec.reports_sessions = "fresh_session" in p
        if rec.generation != generation:
            rec.generation, rec.restarts, rec.crashes, rec.retry_at = generation, 0, [], None
            rec.hung_exits, rec.resume, rec.sessions = [], False, 0
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
            if rec.state in ("starting", "running") and p.get("mode") == "interactive":
                if self.cfg.harnesses[p["harness"]].id == "codex":
                    self._folder_prompt(rec, mine, backend, now)
            if rec.state != "stopping" and (self.first_tick or rec.state not in LIVE):
                # A live session of this generation was started, whether or not a save of its
                # count reached actual.json: a later resume in it continues it, never a reset.
                rec.sessions = max(rec.sessions, 1)
                rec.enter(now, "running", "adopted", started_at=None)
            elif rec.state == "starting" and now - (rec.started_at or now) >= RUNNING_AFTER:
                on = rec.sandbox  # the start's own view, not the tool in use now (§15.16)
                if on is None:
                    on = target.sandbox.get(p["harness"], False)
                unconfined = p["harness"] in UNCONFINED_REPORTED and not on
                rec.enter(now, "running", detail="sandbox_unavailable" if unconfined else None)
            elif rec.state == "stopping":  # desired went back to running during a stop
                rec.enter(now, "running", deadline_at=None, kill_at=None)
            elif rec.state == "running" and p.get("mode") == "interactive":
                if not self._prompt_shown(p, mine, backend):  # no line into a prompt
                    self._idle(p, rec, mine, backend, now)
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
            rec.hung_at = None
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
            rec.hung_at = None
            rec.enter(now, "stopped", "stopped_by_hub", exit_code=code, deadline_at=None,
                      kill_at=None)  # fmt: skip
            return
        if rec.hung_at is not None:  # the runner ended it for not listening
            self._hung_exit(rec, now, code)
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
        folder = next((d for d, c in loop.EXIT_FOLDER.items() if c == code), None)
        if folder is not None:  # the loop's check before a run (§15.5): as before a start
            rec.enter(now, "failed", "workspace_in_use", detail=folder, exit_code=code,
                      retry_at=None)  # fmt: skip
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

    def _folder_prompt(self, rec: Record, session: Session, backend: Tmux, now: float) -> None:
        """Codex asks at an interactive start about a folder it is told not to trust (the
        clone, `trust_level = "untrusted"`, so the clone's own `.codex` configuration is not
        loaded), and nobody answers: the agent never starts. Its first choice, already
        highlighted, is "Open restricted", which keeps the folder untrusted and saves nothing;
        the runner presses Enter once that shows, with nobody attached. A folder prompt
        without it (one that would trust the folder) is never answered: said in the log, as
        a harness waiting on a first-run prompt. Looked for only `FOLDER_PROMPT_WITHIN` after
        the start; the pane's text is only matched, never kept (Tmux.pane_has)."""
        if rec.folder_prompt is not None or rec.started_at is None:
            return
        if now - rec.started_at > FOLDER_PROMPT_WITHIN:
            rec.folder_prompt = "none"
            return
        shown = backend.pane_has(session.name, (FOLDER_PROMPT, OPEN_RESTRICTED, TRUST_FOLDER))
        if shown is None or FOLDER_PROMPT not in shown:
            return
        if OPEN_RESTRICTED not in shown or TRUST_FOLDER in shown:
            rec.folder_prompt = "left"
            self.log(
                f"{session.name}: waiting on a first-run prompt: Codex asks about its folder "
                "without offering only to open it restricted; not answered"
            )
            return
        if backend.attached(session.name) is not False:  # a person there answers it
            return
        try:
            backend.submit(session.name)
        except TmuxError as exc:
            self.log(f"{session.name}: cannot answer Codex's folder prompt: {exc}")
            return
        rec.folder_prompt = "answered"
        self.log(f"{session.name}: answered Codex's folder prompt with \"Open restricted\"; "
                 "the clone stays untrusted")  # fmt: skip

    def _prompt_shown(self, p: dict[str, Any], session: Session, backend: Tmux) -> bool:
        """Whether a Codex session's pane may show its folder prompt, looked at on every
        check, before the idle check may type: a prompt shown, or a look that cannot tell,
        keeps the idle line out of it, however long it stays and whenever it shows; one look
        that misses it decides that check only."""
        if self.cfg.harnesses[p["harness"]].id != "codex":
            return False
        shown = backend.pane_has(session.name, (FOLDER_PROMPT,))
        return shown is None or FOLDER_PROMPT in shown

    def _idle(
        self, p: dict[str, Any], rec: Record, session: Session, backend: Tmux, now: float
    ) -> None:
        """The runner's own check of an interactive session (§15.14). The agent stopped
        listening when the harness has no process below it but its own helpers (no `maity
        wait`, no tool it runs, however quiet) and its pane is unchanged, for
        `hang_after_minutes`. Nobody attached: one line typed into the pane and sent. A pane
        still as it was before Enter `reply_within_minutes` later (the harness did not even
        take the line), or a quiet spell after `NUDGE_CAP` answered nudges with no wait in
        between: the session is ended and started again, resuming it, reported `exited`,
        `hung`, `idle`. Before a nudge's Enter, a person attached, any other process below
        the harness, a changed pane, or anything the runner cannot read starts the count
        again; after it, a change or a process is the answer, and a person attached or an
        unreadable look leaves the nudge waiting while the reply time runs on."""
        if rec.hung_at is not None:  # ended for it: kill-session if TERM was not enough
            if now - rec.hung_at >= KILL_AFTER:
                backend.kill(session.name)
                self._hung_exit(rec, now, None)
            return
        if rec.idle_checked_at is not None and now - rec.idle_checked_at < IDLE_EVERY:
            return
        rec.idle_checked_at = now
        below = backend.activity(session)
        if below == WAITING:  # it listens again: the idle ends and nudges in a row start over
            rec.hung_exits, rec.nudges = [], 0
        attached = backend.attached(session.name)
        digest = backend.pane_digest(session.name)
        if below != IDLE or attached is not False or digest is None:
            if rec.nudged_at is not None and not rec.unsent:
                if below == WORKING:  # the harness started something on the nudge: an answer
                    rec.nudges += 1
                elif below != WAITING:  # a look it cannot use: the nudge still waits for one
                    return
            # A line typed but never sent is dropped; it may still sit in the input, unless a
            # person is at the pane: what is there then is theirs, the next nudge types afresh.
            rec.left_typed = (rec.left_typed or rec.unsent) and attached is False
            rec.pane, rec.quiet_since, rec.nudged_at, rec.unsent = digest, None, None, False
            return
        if rec.unsent and rec.nudged_at is not None:  # the line did not show in time
            if digest == rec.pane:  # still not: its Enter waits until it shows
                reply = _minutes(
                    ((p.get("health") or {}).get("settings") or {}).get("reply_within_minutes"),
                    REPLY_WITHIN_MINUTES,
                )
                if now - rec.nudged_at >= reply:
                    self.log(f"{session.name}: the nudge's line did not show in "
                             f"{reply / 60:.0f} min; ending it to resume its session")  # fmt: skip
                    backend.terminate(session)
                    rec.hung_at = now
                return
            try:  # it shows now: measured before its Enter
                backend.submit(session.name)
            except TmuxError as exc:
                self.log(f"{session.name}: cannot send the nudge: {exc}")
                return
            rec.pane, rec.nudged_at, rec.unsent = digest, now, False
            return
        if rec.quiet_since is None or digest != rec.pane:
            if rec.nudged_at is not None:  # a change after its Enter: the nudge was answered
                rec.nudges += 1
            rec.pane, rec.quiet_since, rec.nudged_at = digest, now, None
            return
        settings = (p.get("health") or {}).get("settings") or {}
        hang = _minutes(settings.get("hang_after_minutes"), HANG_AFTER_MINUTES)
        reply = _minutes(settings.get("reply_within_minutes"), REPLY_WITHIN_MINUTES)
        if rec.nudged_at is None:
            if now - rec.quiet_since < hang:
                return
            if rec.nudges >= NUDGE_CAP:
                self.log(f"{session.name}: answered {rec.nudges} nudges without going back to "
                         "its wait; ending it to resume its session")  # fmt: skip
                backend.terminate(session)
                rec.hung_at = now
                return
            try:  # the baseline is the pane with the line typed, before Enter: any answer counts
                if rec.left_typed:  # the dropped line is still there: send it, never a second
                    shown: str | None = digest
                else:
                    backend.type_text(session.name, NUDGE_LINE)
                    shown = self._typed(backend, session.name, digest)
                if shown is not None:
                    backend.submit(session.name)
            except TmuxError as exc:
                self.log(f"{session.name}: cannot nudge: {exc}")
                return
            rec.nudged_at, rec.left_typed = now, False
            rec.pane, rec.unsent = (digest, True) if shown is None else (shown, False)
            self.log(f"{session.name}: not listening for {(now - rec.quiet_since) / 60:.0f} min; "
                     "nudged in its pane")  # fmt: skip
            return
        if now - rec.nudged_at < reply:
            return
        self.log(f"{session.name}: still not listening {reply / 60:.0f} min after the nudge; "
                 "ending it to resume its session")  # fmt: skip
        backend.terminate(session)
        rec.hung_at = now

    def _typed(self, backend: Tmux, name: str, before: str) -> str | None:
        """The pane once the nudge's line shows, before Enter: what "unchanged" is measured
        against from then on, so whatever the harness does with the line, an answer
        included, is a change. A line that does not show within the window (a stalled
        screen, a slow read) gives None: its Enter waits for the next look, which measures
        the pane first, so neither its late echo nor an answer becomes the baseline."""
        for _ in range(TYPED_TRIES):
            digest = backend.pane_digest(name)
            if digest != before:
                return digest
            self.pause(TYPED_PAUSE)
        return None

    def _hung_exit(self, rec: Record, now: float, code: int | None) -> None:
        """The end of a session the idle check ended: `exited`, `hung`, `idle` (§15.7),
        restarted after the first backoff step and resumed. These ends are counted on their
        own and in a row: a hung session never ends quickly, so no `crash_window` would hold
        `crash_cap` of them (one takes 40 minutes by default). `crash_cap` idle ends with no
        `maity wait` seen in between hold the placement as `failed`, `hung`, `idle`; a wait
        seen below the harness starts the row over."""
        policy = self.cfg.limits.restart
        rec.hung_exits = [*rec.hung_exits, now]
        rec.hung_at = None
        rec.calm()
        rec.resume = True
        if len(rec.hung_exits) >= policy.crash_cap:
            rec.enter(now, "failed", "hung", detail="idle", exit_code=code, retry_at=None)
            self.log(f"{rec.target or 'local'}: held after {len(rec.hung_exits)} idle ends")
        else:
            rec.enter(now, "exited", "hung", detail="idle", exit_code=code,
                      retry_at=now + restart.delay(policy, 0, self.rand))  # fmt: skip

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
        through a link, at most limitread.LIMIT_BYTES, and nothing but a plain exit code taken."""
        path, as_user = self._limit_file(pid, target), target.as_user
        assert target.agent_files is not None  # noqa: S101 - connected before a launch
        under = str(target.agent_files)  # the agents' directory: read from it down
        try:
            if not as_user.direct:  # the agents' user, or the ssh host's
                # Read there by the runner's own module (limitread): opened without following
                # a link and without blocking on a FIFO, so a file swapped after any check
                # cannot hold the read. A host's `maity` without it reads nothing: no code.
                argv = [*as_user.runner_module("limitread"), "--under", under, str(path)]
                done = as_user.run(argv, env={"PATH": target.agent_path})
                raw = done.stdout if done.returncode == 0 else ""
            else:
                raw = limitread.read(str(path), under=under) or ""
            data = json.loads(raw)
        except Exception:  # noqa: BLE001 - whatever the agents' side left there, no exit code
            return None
        code = data.get("exit_code") if isinstance(data, dict) else None
        valid = isinstance(code, int) and not isinstance(code, bool) and 0 <= code <= 255
        return code if valid else None

    # --- starting --------------------------------------------------------------------------

    def _refusal(
        self, p: dict[str, Any], target: Target, view: GateView | None = None
    ) -> tuple[str, str | None] | None:
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
        view = view or GateView.of(target, harness.id)
        found = view.found
        if found is not None and not found.available:
            return ("harness_missing", found.reason)
        on = view.sandbox
        if capabilities.sandbox_refused(harness, on, view.held):
            return ("harness_refused", None)  # no run without it, or held back by its version
        if harness.id == "codex" and not on:
            # The grant parts Codex starts without are left out only for its sandbox to take
            # their place; without it, a grant that asked for them refuses the start.
            repository = config.normalise_repository(p["workspace"].get("repository") or "")
            if adapters.codex_left_out(
                self.cfg.repositories.get(repository, config.RepositoryGrant())
            ):
                return ("harness_refused", None)
        if on and harness.id == "claude-code":
            # The sandboxed session relies on the runner's hook; settings that switch hooks
            # off would start it without one. Read at every start: they change without us.
            why = capabilities.claude_hooks_off(target.as_user)
            if why is not None:
                self.log(capabilities.claude_hooks_line(why))
                return ("harness_refused", None)
            # The placement pins its Unix socket settings; the agents' user's settings are
            # merged in, so a start waits until they carry none (capabilities.SOCKET_SETTINGS).
            why = capabilities.claude_socket_settings(target.as_user)
            if why is not None:
                self.log(capabilities.claude_socket_settings_line(why))
                return ("harness_refused", None)
            # Every placement runs as the same OS user: the seccomp step is what keeps a
            # sandboxed command away from the other placements' sockets, and Claude Code says
            # nothing when it cannot run (capabilities.claude_seccomp).
            seccomp = self._seccomp(target)
            if seccomp.outcome != "ok":
                self.log(capabilities.claude_seccomp_line(seccomp))
                return ("harness_refused", None)
        return None

    def _probe_warning(self, target: Target, view: GateView, name: str) -> None:
        """A sandboxed Claude Code start on Linux whose installed version is not the one
        whose `check` probe last passed on `target` is logged, never refused: the runner
        installs Claude Code itself, and refusing every start after a version pin until
        `check` runs would be an outage (cli/context/runner.md). Logged once per target and
        installed version for the service's run."""
        if not view.sandbox or not capabilities.claude_seccomp_applies(target.as_user):
            return
        installed = view.found.version if view.found is not None else None
        if installed in target.probe_warned:
            return
        passed = capabilities.probe_passed(self.cfg.state_dir, target.name)
        stale = capabilities.probe_stale_line(passed, installed)
        if stale is not None:
            target.probe_warned.add(installed)
            self.log(f"{name}: {target.name}: {stale}")

    def _seccomp(self, target: Target) -> ClaudeSeccomp:  # the field `capabilities` hides it
        """The seccomp preflight for `target` (Linux only, `ok` elsewhere): an `ok` is kept for
        the service's lifetime, on an ssh host until it turns unreachable (_reachable); any
        other answer is read again at the next start, so a host that could not be read starts
        once it can."""
        if not capabilities.claude_seccomp_applies(target.as_user):
            return ClaudeSeccomp("ok")
        if target.seccomp is not None:
            return target.seccomp
        found = capabilities.claude_seccomp(target.as_user)
        if found.outcome == "ok":
            target.seccomp = found
        return found

    def _wait(self, rec: Record, why: str, name: str) -> int:
        if rec.waiting != why:
            rec.waiting = why
            self.log(f"{name}: not started yet: {why}")
        return 0

    def _launch(self, p: dict[str, Any], rec: Record, now: float, target: Target) -> int:
        name = session_name(p["project_id"], p["workspace"]["clone"])
        view = GateView.of(target, p.get("harness") or "")  # under the lock the keeper takes
        refused = self._refusal(p, target, view)
        if refused is not None:
            rec.enter(now, "failed", refused[0], detail=refused[1])
            return 0
        harness = self.cfg.harnesses[p["harness"]]
        if harness.id not in adapters.READY:
            return self._wait(rec, f"no adapter for {harness.id} in this version", name)
        if harness.id == "claude-code":
            self._probe_warning(target, view, name)
        if harness.id == "codex":  # starts without what it cannot enforce, said at each start
            repository = config.normalise_repository(p["workspace"].get("repository") or "")
            grant = self.cfg.repositories.get(repository, config.RepositoryGrant())
            for part in adapters.codex_left_out(grant):
                self.log(f"{name}: repositories.{repository}: {part}")
        as_user = target.as_user
        agent = p.get("agent") or {}
        try:
            place = workspace.locate(
                target.workspaces, p["project_id"], p["workspace"]["clone"], target.host,
                folder=workspace.uses_folder(harness.id),
            )  # fmt: skip
        except workspace.Refused as refused_:
            rec.enter(now, "failed", refused_.reason, detail=refused_.detail)
            return 0
        owner = agent.get("id") or agent.get("handle") or ""
        if agent.get("id") and agent.get("handle"):  # recorded under the handle before a join
            workspace.rebind(self.cfg.state_dir, place, agent["handle"], agent["id"])
        if as_user.exists(place.path) and (
            not place.folder
            or as_user.exists(place.repo)
            or place.key in workspace.records(self.cfg.state_dir)
        ):
            # An existing directory that is not this agent's comes before its credential. Only
            # the runner's record here: the clone itself is read in the start task, outside the
            # lock this runs under (workspace.prepare). A workspace folder without its clone and
            # without a record is one a failed clone left, or a stray one: `prepare` takes it
            # when empty and refuses it otherwise (workspace_not_bare).
            try:
                workspace.owned(self.cfg, place, owner, p["id"])
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
        rec.calm()
        rec.folder_prompt = None
        rec.enter(now, "starting", retry_at=None, started_at=now)
        rec.sandbox = view.sandbox
        if retrying:
            rec.restarts += 1
        task = threading.Thread(
            target=self._start,
            args=(p, rec, place, name, harness, agent, join, rejoin, target, view),
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
        view: GateView | None = None,
    ) -> None:
        """The long part of a start, in its own thread: clone if missing, join if needed,
        then tmux; with the binary and sandbox the gate decided on (`view`)."""
        target = target or self.targets[self._default_target()]
        assert target.backend is not None  # noqa: S101 - connected before a launch
        as_user = target.as_user
        owner = agent.get("id") or agent.get("handle") or ""
        try:
            if not self._wants(p["id"], p["generation"]):
                with self.lock:  # stopped or moved on while the task was queued
                    rec.enter(self.now(), "stopped", "stopped_by_hub")
                return
            # A Claude Code subagent's leftover worktree under the clone's `.claude/worktrees/`
            # would read as unsupported and refuse the start (worktree, §15.5): clear it first, by
            # file operations only (the runner runs no git in an existing clone). Only this agent's
            # own existing clone is touched — `workspace.owned` refuses a clone another agent or a
            # person holds before anything is pruned — and a worktree pointing elsewhere is left,
            # so a planted redirect still refuses the start. Gated on either a `.claude/worktrees`
            # directory or a `.git/worktrees` registration, so a stale entry left without its
            # working tree is still cleared; a restart's prune discards uncommitted work in the
            # leftover worktree, since there is no in-session save.
            if as_user.exists(place.repo) and (
                as_user.exists(place.repo / ".claude" / "worktrees", "-d")
                or as_user.exists(place.repo / ".git" / "worktrees", "-d")
            ):
                workspace.owned(self.cfg, place, owner, p["id"])
                try:
                    pruned = as_user.worktree_prune(place.repo)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    self.log(f"{p['id']}: worktree prune skipped: {exc}")
                else:
                    if pruned.get("removed"):
                        where = ", ".join(str(w) for w in pruned["removed"])
                        self.log(f"{p['id']}: cleared leftover worktree(s): {where}")
            workspace.prepare(
                self.cfg, place, p["workspace"].get("repository") or "", owner, p["id"],
                p["workspace"].get("branch"), as_user,
            )  # fmt: skip
            # agy loads what lies in its start directory and above it: a workspace folder holds
            # the clone and nothing else, outside any work tree, at its real path (§15.5).
            workspace.check_folder(place, as_user)
            if join:
                self._join(p, place, owner, rejoin, target)
                with self.lock:
                    rec.joined_generation = p["generation"]
            if workspace.stale_index_lock(place.repo, as_user=as_user):
                with self.lock:
                    rec.detail = "stale_index_lock"
            if not self._wants(p["id"], p["generation"]):  # the clone took a while
                with self.lock:
                    rec.enter(self.now(), "stopped", "stopped_by_hub")
                return
            scratch = self._scratch(p, harness, target)
            # A reset (§15.6): the generation's first session is a fresh one, never the last
            # conversation resumed; a later resume in it (after `hung`) continues the new one.
            reset = bool(p.get("fresh_session")) and rec.sessions == 0
            context = self._context(p, harness, place, target, rec.resume and not reset,
                                    view=view, scratch=scratch)  # fmt: skip
            launch = adapters.launch(context)
            if (scratch is not None and not workspace.scratch_in_tmp(harness.id)
                    and adapters.gets_test_cluster(harness.id)
                    and adapters.pg_dir(scratch) is None):  # fmt: skip
                self.log(f"{p['id']}: no MAITY_PG_DIR: a PostgreSQL socket under "
                         f"{scratch / adapters.PG} would not fit a Unix socket path; "
                         "set a shorter workspaces root")  # fmt: skip
            self._clear_limit_file(p["id"], target)  # only the loop of this run may leave one
            target.backend.start(
                name, place.path, launch.argv, launch.env, p["id"], p["generation"]
            )
        except workspace.Refused as refused:
            if refused.why:  # the runner's log only; the report keeps the codes
                self.log(f"{p['id']}: {refused.reason}: {refused.why}")
            with self.lock:
                rec.enter(self.now(), "failed", refused.reason, detail=refused.detail,
                          exit_code=refused.exit_code)  # fmt: skip
            return
        except adapters.NotYet as refused:
            # A fail-closed adapter refusal (opencode's model guard): a clean harness_refused,
            # not a crash-loop-counted start failure, since retrying cannot fix a model that is
            # not among the harness's configured ones.
            self.log(f"{name}: {refused}")
            with self.lock:
                rec.enter(self.now(), "failed", "harness_refused", detail="model_unsupported")
            return
        except Retry as again:
            self.log(f"{name}: {again}; trying again in {PICKUP_RETRY:.0f} s")
            with self.lock:
                rec.retry_at = self.now() + PICKUP_RETRY
            return
        except scratchop.Unsupported as old:
            # An ssh host whose `maity` predates the codex launch-write op cannot anchor the
            # home. The no-scratch fall-back would put CODEX_HOME back under the hidden state
            # directory (the original incident: no command runs), so refuse the placement with
            # a clear reason the operator can act on, rather than crash-looping it.
            #
            # The reason goes to the runner's log only. `harness_refused`'s detail is a closed
            # contract list (docs/api.md §15.7) with no code for this; an unknown detail makes
            # the hub answer `invalid`, so the runner would re-send the rejected report every
            # tick and the refusal would never be recorded. The report therefore carries no
            # detail (a contract detail-code is deferred to a follow-up card). `retry_at` stays
            # None, so the start still does not crash-loop and only a new generation retries.
            # `old` carries the host's own message, the host version among it when it names one.
            self.log(
                f"{p['id']}: codex placement refused: the host's maity is too old for the "
                f"codex launch-write op: {old}"
            )
            with self.lock:
                rec.enter(self.now(), "failed", "harness_refused", retry_at=None)
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
            rec.resume = False
            rec.binary = context.binary
            if not launch.resumed:
                rec.sessions += 1
        self.log(f"{name}: started generation {p['generation']}")
        if reset and not launch.resumed:
            self.log(f"{name}: reset: a fresh session, the last one not resumed")
        if harness.id == "opencode":  # name the model in effect: the placement's, or the default
            self.log(f"{name}: opencode model {p.get('model') or harness.default_model}")
        found = (view or GateView.of(target, harness.id)).found  # the version that started
        warning = capabilities.unchecked(harness.id, found.version if found else None)
        if warning is not None:
            self.log(f"{name}: {warning}")

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
            # A 404 (the placement gone, or no such route) is not the join token's `not_found`.
            gone = exc.status == 404
            reason, why = exc.details.get("reason"), exc.details.get("why")
            self.log(f"{p['id']}: {refusal_line('pickup', exc.code, reason, why)}")
            detail = None if gone else join_detail(exc.code, reason)
            raise workspace.Refused("join_failed", detail) from None
        url, code = pickup.get("join_url"), pickup.get("code")
        if not isinstance(url, str) or not isinstance(code, str):
            raise workspace.Refused("join_failed")
        joined, why = run_join(place, url, code, self.cfg.state_dir, as_user, target.agent_path)
        if not joined:
            # The child's machine line carries the code only (for `forbidden`, the reason in
            # its place), and the exchange answers `not_found` without a why (§15.9).
            self.log(f"{p['id']}: {refusal_line('exchange', why)}")
            raise workspace.Refused("join_failed", why)
        try:
            if not as_user.direct:
                path = place.credential.parent / state.STATE_FILE
                found = json.loads(as_user.read_whole(path, STATE_MAX, under=place.path))
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
        resume: bool = False,
        view: GateView | None = None,
        scratch: Path | None = None,
    ) -> adapters.Context:
        target = target or self.targets[self._default_target()]
        view = view or GateView.of(target, harness.id)
        assert target.agent_files is not None  # noqa: S101 - connected before a launch
        agent_dir = agent_dir_for(target.as_user, target.agent_files, p["id"])
        repository = config.normalise_repository(p["workspace"].get("repository") or "")
        found = view.found
        # The password holder first, so every sandbox of this start is denied a path that exists;
        # only here: an ssh host's sessions get no test cluster (adapters.pg_launch).
        holder = self._pg_holder(target) if target.as_user.here else None
        private = self._private(target, place, scratch)
        if holder is not None:
            private = (*private, holder)
        pg_pass = None
        # Not on an ssh host: pgenv runs as this interpreter's module (adapters.pg_launch). Not
        # for a harness whose sandbox refuses the cluster's Unix socket (gets_test_cluster): no
        # password file is drawn for it. The holder is still made and denied, for the others.
        if (holder is not None and scratch is not None and not workspace.scratch_in_tmp(harness.id)
                and adapters.gets_test_cluster(harness.id)
                and target.as_user.here and adapters.pg_dir(scratch) is not None):  # fmt: skip
            pg_pass = self._pg_pass(p, holder, target)
        tmp_parent = self._tmp_scratch_parent(target, harness)
        if tmp_parent is not None:
            self._make_tmp_parent(tmp_parent, target)
        tmpdir = (
            self._tmpdir(p, scratch, target)
            if tmp_parent is not None and harness.id in workspace.OWN_TMPDIR_HARNESSES
            else None
        )
        return adapters.Context(
            placement=p,
            harness=harness,
            binary=found.path if found else None,
            version=found.version if found else None,  # the probe the sandbox gate reads too
            clone=place.repo,
            folder=place.path if place.folder else None,
            agent_dir=agent_dir,
            grant=self.cfg.repositories.get(repository, config.RepositoryGrant()),
            restart=self.cfg.limits.restart,
            sandbox=view.sandbox,
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
            agent_path=target.agent_path,
            resume=resume,
            git=self.cfg.git,
            scratch=scratch,
            tmp_scratch_parent=tmp_parent,
            tmpdir=tmpdir,
            pg_pass=pg_pass,
        )

    def _tmpdir(self, p: dict[str, Any], scratch: Path | None, target: Target) -> Path | None:
        """A short TMPDIR of the placement's own where its scratch's `tmp` leaves no room for a
        Unix socket (adapters.scratch_tmpdir), as under the default `~/maity-workspaces`:
        `tmp` in a fresh leaf under the per-user `/tmp` parent this placement's sandbox hides
        (workspace.tmp_scratch_of, made as agy's scratch is, `_tmp_scratch`), opened again for
        this placement alone or kept from its sandbox (adapters) and removed with it
        (`_clear_scratch`). Called only for a placement that is given that parent and whose
        harness takes such a leaf (workspace.OWN_TMPDIR_HARNESSES, on this machine: Codex as its
        TMPDIR, Claude Code as its CLAUDE_CODE_TMPDIR). None where the scratch's own `tmp` fits,
        where a leaf would not fit either (a long uid on macOS), or where it cannot be made: the
        session then starts without one, as before (tsk-0zb9mgzmbwn4, tsk-k7svzz2p4v7y)."""
        if scratch is not None and adapters.scratch_tmpdir(scratch) is not None:
            return None
        try:
            uid = target.as_user.uid()
            longest = workspace.tmp_scratch_of(uid, "0" * 32) / "tmp"
        except (OSError, workspace.Refused):
            return None
        if not adapters.fits_socket(longest):
            return None
        leaf = self._tmp_scratch(p, target, "temp directory")
        return None if leaf is None else leaf / "tmp"

    def _make_tmp_parent(self, parent: Path, target: Target) -> None:
        """Create the per-user `/tmp` scratch parent (0700, owned by the agents' user) before a
        placement that only hides it starts, so the deny path the sandbox is given is a real
        directory. A missing deny path leaves some sandboxes a placeholder file at it; an agy
        placement of the same user would then see a file where its parent must be and get no
        scratch. Best effort: a failure is logged, the hiding still holds, and the agy start
        makes the parent itself if it is still missing."""
        try:
            scratch.tmp_make_parent(parent, target.as_user)
        except (scratchop.OnTheWay, OSError, subprocess.SubprocessError) as exc:
            self.log(f"the shared /tmp scratch parent was not pre-created on {target.name}: "
                     f"{onboarding.inline(str(exc))[:200]}")  # fmt: skip

    def _tmp_scratch_parent(self, target: Target, harness: config.Harness) -> Path | None:
        """The agy per-user `/tmp` scratch parent to hide from this placement's sandbox, or None.
        Only a placement whose sandbox hides that parent is given it (workspace.hides_tmp_scratch_
        parent): such a placement may run as the same user as an agy one, so the parent is hidden
        from it and the deny/none path is set to it; an agy placement owns it and is not given it
        here, and a harness that opens no such rule (opencode, stub) is given None so the runner
        pre-creates nothing for it. None too where there is no local `/tmp` scratch (an ssh host,
        or no uid). This single field drives both the sandbox's deny path (adapters) and the
        runner's pre-create (_make_tmp_parent), so the two cannot name different placements."""
        if not workspace.hides_tmp_scratch_parent(harness.id) or not target.as_user.here:
            return None
        try:
            uid = target.as_user.uid()
        except OSError:
            return None
        return workspace.TMP_SCRATCH_ROOT.resolve() / f"maity-scratch-{uid}"

    def _scratch(self, p: dict[str, Any], harness: config.Harness, target: Target) -> Path | None:
        """The placement's scratch, made as the agents' user with `tmp` in it (§15.5); None
        for a harness that gets none (workspace.SCRATCH_HARNESSES). A restart or an adoption
        finds the beside-clone scratch as it was; agy's `/tmp` scratch is emptied and remade
        with a fresh name at every start, so nothing in it survives a restart (`_tmp_scratch`).
        Through a link the agents made the runner makes nothing, and a scratch it cannot make
        (a host whose `maity` has no `scratchop` yet) is none either: the session then starts
        without one, and the log says why. agy's scratch goes under `/tmp` instead of beside the
        clone, its sandbox being unable to write there."""
        if harness.id not in workspace.SCRATCH_HARNESSES:
            return None
        if workspace.scratch_in_tmp(harness.id):
            return self._tmp_scratch(p, target)
        path = workspace.scratch_of(target.workspaces, p["project_id"], p["id"], target.host)
        try:
            scratch.make(path, target.as_user)
        except scratchop.OnTheWay:
            self.log(f"{p['id']}: no scratch: a directory on the way to {path} is a link")
            return None
        except (OSError, subprocess.SubprocessError) as exc:  # a host's maity without it, too
            self.log(f"{p['id']}: no scratch on {target.name}: {onboarding.inline(str(exc))[:200]}")
            return None
        return path

    def _pg_holder(self, target: Target) -> Path | None:
        """The test clusters' password holder (scratchop.PG_HOLDER) under `target`'s workspaces
        root, made 0700 before any settings of this start are written, so its path exists when
        a sandbox is told to deny it; None when it cannot be made (the log says why), and then
        no session of this start gets a test cluster."""
        root = target.workspaces if target.host else target.workspaces.resolve()
        holder = root / scratchop.PG_HOLDER
        try:
            target.as_user.pg("make", root, holder)
        except (scratchop.OnTheWay, OSError, subprocess.SubprocessError) as exc:
            self.log(f"no test cluster password holder on {target.name}: "
                     f"{onboarding.inline(str(exc))[:200]}")  # fmt: skip
            return None
        return holder

    def _pg_pass(self, p: dict[str, Any], holder: Path, target: Target) -> Path | None:
        """The placement's password file in `holder`, drawn once and kept across restarts; None
        when it is not one the runner vouches for (the log says why), and then the session gets
        no test cluster: without the password it would be made with trust."""
        leaf = holder / str(p["id"])
        try:
            made = target.as_user.pg("make", holder.parent, leaf)
        except (scratchop.OnTheWay, OSError, subprocess.SubprocessError) as exc:
            self.log(f"{p['id']}: no MAITY_PG_DIR: {onboarding.inline(str(exc))[:200]}")
            return None
        if made.get("pg_pass") is not True:
            self.log(f"{p['id']}: no MAITY_PG_DIR: its password file is not one the runner made")
            return None
        return leaf

    def _tmp_scratch(self, p: dict[str, Any], target: Target, what: str = "scratch") -> Path | None:
        """agy's scratch under the host's shared temp directory (workspace.tmp_scratch_of),
        owned by the uid agy runs as: its sandbox makes the beside-clone `.scratch` read-only,
        so the scratch goes to the host-shared writable location instead. Any earlier leaf of
        this placement is removed and a leaf with a fresh, random name is made, so nothing
        carries across a restart; the chosen name is recorded (TMP_NAMES_FILE) so the session
        and the supervisor find this placement's own scratch again. None when the uid is unknown
        (an ssh host) or a level is a link or a directory another user holds, the session then
        starting without one.

        The new name is recorded *before* the leaf is made, so a crash or an OnTheWay between
        the make and a later save can never orphan a leaf the runner cannot find again. The
        previous run's leaf is removed first, while it is still the recorded name; its name is
        dropped from the record only once it is actually gone. A leaf that cannot be removed is
        kept on record (`scratch_stale`) and tried again at every start and at the close, so a
        failed removal orphans nothing (review A1769). `what` names the leaf in the log: the
        agy scratch, or a placement's own TMPDIR (`_tmpdir`)."""
        try:
            uid = target.as_user.uid()
        except OSError as exc:
            self.log(f"{p['id']}: no {what} on {target.name}: {onboarding.inline(str(exc))[:200]}")
            return None
        self._remove_stale(p, target, uid)
        with self.lock:
            old = self.scratch_names.get(p["id"])
        if old is not None:  # a prior run's leaf: the leaf is made fresh each start
            try:
                scratch.tmp_remove(workspace.tmp_scratch_of(uid, old), target.as_user)
            except (OSError, subprocess.SubprocessError) as exc:  # OnTheWay included
                self.log(f"{p['id']}: previous {what} leaf not removed on {target.name}: "
                         f"{onboarding.inline(str(exc))[:200]}")  # fmt: skip
                if not isinstance(exc, scratchop.OnTheWay):  # a link or a foreign one: left
                    with self.lock:  # kept on record, tried again at the next start or close
                        kept = self.scratch_stale.setdefault(p["id"], [])
                        if old not in kept:
                            kept.append(old)
            except workspace.Refused:
                pass  # not a leaf name the runner makes: nothing to remove
            else:  # gone: drop its recorded name before the new one takes its place
                with self.lock:
                    if self.scratch_names.get(p["id"]) == old:
                        del self.scratch_names[p["id"]]
                self._save_scratch_names()
        leaf = secrets.token_hex(16)
        try:
            path = workspace.tmp_scratch_of(uid, leaf)
        except workspace.Refused:
            return None
        with self.lock:  # recorded before the leaf is made: a crash after the make cannot orphan it
            self.scratch_names[p["id"]] = leaf
        self._save_scratch_names()
        try:
            scratch.tmp_make(path, target.as_user)
        except (scratchop.OnTheWay, OSError, subprocess.SubprocessError) as exc:
            # The name stays recorded; the next start removes or replaces it, so it is not orphaned.
            self.log(f"{p['id']}: no {what} on {target.name}: {onboarding.inline(str(exc))[:200]}")
            return None
        return path

    def _remove_stale(self, p: dict[str, Any], target: Target, uid: int | None = None) -> bool:
        """Try again to remove every leaf of this placement that an earlier start could not
        (`scratch_stale`); True when none is left. A link or a directory another user holds
        is logged and dropped, as a scratch's would be; any other failure keeps the leaf on
        record for the next try."""
        with self.lock:
            stale = list(self.scratch_stale.get(p["id"], ()))
        if not stale:
            return True
        if uid is None:
            try:
                uid = target.as_user.uid()
            except OSError:
                return False
        left: list[str] = []
        for leaf in stale:
            try:
                scratch.tmp_remove(workspace.tmp_scratch_of(uid, leaf), target.as_user)
            except workspace.Refused:
                continue  # not a leaf name the runner makes: nothing to remove
            except scratchop.OnTheWay as exc:
                self.log(f"{p['id']}: earlier leaf left on {target.name}: "
                         f"{onboarding.inline(str(exc))[:200]}")  # fmt: skip
            except (OSError, subprocess.SubprocessError) as exc:
                self.log(f"{p['id']}: earlier leaf not removed on {target.name}: {exc}")
                left.append(leaf)
        with self.lock:
            if left:
                self.scratch_stale[p["id"]] = left
            else:
                self.scratch_stale.pop(p["id"], None)
        self._save_scratch_names()
        return not left

    def _scratch_location(self, p: dict[str, Any], target: Target) -> tuple[Path, bool] | None:
        """Where a placement's scratch is on `target` and whether it is the `/tmp` one (agy):
        beside the clone, or under the shared temp directory for a harness whose sandbox cannot
        write beside the clone. Decided from the placement's own recorded harness, not an active
        config entry, so a placement closed after its harness was taken out of the configuration
        is still swept. None when the `/tmp` one cannot be worked out (an ssh host has no uid, or
        no leaf name was recorded for this placement). workspace.Refused for a bad token."""
        if workspace.scratch_in_tmp(p.get("harness") or ""):
            try:
                uid = target.as_user.uid()
            except OSError:
                return None
            with self.lock:
                leaf = self.scratch_names.get(p["id"])
            if leaf is None:
                return None
            return workspace.tmp_scratch_of(uid, leaf), True
        return workspace.scratch_of(target.workspaces, p["project_id"], p["id"], target.host), False

    def _private(
        self, target: Target, place: workspace.Workspace, scratch: Path | None = None
    ) -> tuple[Path, ...]:
        """What the agent's sandbox may not read, as the agents' side of `target` sees it: its
        user's home secrets, its own files (every agent's socket, log and settings), the
        other clones' credentials and the other placements' scratch (all but `scratch`, its
        own) it can list; here also the runner's state and config."""
        as_user = target.as_user
        assert target.agent_files is not None  # noqa: S101 - connected before a launch
        try:
            others = other_credentials(target.workspaces, place.repo, as_user)
        except workspace.Refused:
            self.log(f"{place.path.name}: not every clone under {target.workspaces} on "
                     f"{target.name} could be listed; not starting an agent whose sandbox "
                     "might read another's credential")  # fmt: skip
            raise
        try:
            others += other_scratches(target.workspaces, scratch, as_user, target.host)
        except workspace.Refused:
            self.log(f"{place.path.name}: not every scratch under {target.workspaces} on "
                     f"{target.name} could be listed; not starting an agent whose sandbox "
                     "might read another placement's scratch")  # fmt: skip
            raise
        if not as_user.here:  # an ssh host: its home was read on connecting
            return private_paths(None, target.agent_files.parent, place.repo, others,
                                 (target.agent_files,), here=False)  # fmt: skip
        home = config.home_of(as_user.user) if as_user.user else Path.home()
        return private_paths(self.cfg.state_dir, home, place.repo, others,
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

    def sessions_on(self, harness_id: str, binary: str | None) -> int:
        """Running sessions of `harness_id` that started with another binary than `binary`
        (`sessions_on_older`, §15.16); unknown binaries (started before this) count too."""
        with self.lock:
            harness_of = {p["id"]: p["harness"] for p in self.desired}
            return sum(
                1
                for pid, rec in self.records.items()
                if rec.state == "running"
                and harness_of.get(pid) == harness_id
                and rec.binary != binary
            )

    def binaries_in_use(self) -> set[str] | None:
        """The harness binaries live sessions started from, so `tools.prune` keeps their
        versions; None when a live session's binary is not known."""
        with self.lock:
            live = [r for r in self.records.values()
                    if r.state in ("starting", "running", "stopping")]  # fmt: skip
            if any(r.binary is None for r in live):
                return None
            return {r.binary for r in live if r.binary is not None}

    def advertise_now(self) -> None:
        """`PATCH /runner` at once: the capabilities themselves changed (a tool, §15.16)."""
        self._advertise(None, self.now(), force=True)

    def advertised_capabilities(self) -> dict[str, Any]:
        """A copy of the capabilities for serve's `hello`, with the live `running` counts in it.

        `hello` runs on serve's connection thread while `_advertise` runs on this tick thread,
        and both reach the one shared capabilities dict. The copy is read under `self.lock` -- the
        lock `_advertise`'s write-back also takes -- so the two coordinate over the `running`
        fields and a reconnect carries the count last counted here, never the `running: 0` the
        dict was first built with (the reconnect that leaves the hub reading 0/N while agents run,
        tsk-yfc9n6kmvs52)."""
        with self.lock:
            if not isinstance(self.capabilities, dict):
                return self.capabilities  # type: ignore[return-value]
            caps = {**self.capabilities}
            caps["targets"] = [
                dict(t) if isinstance(t, dict) else t for t in self.capabilities.get("targets", [])
            ]
            return caps

    def reconnected(self) -> None:
        """Serve calls this after each `hello`. The hub's stored `running` is then whatever that
        hello carried, which may be stale, so mark an invalidation: bump the generation so the
        next `_advertise` sends even when the count is 0, the counts dict is empty, or the count
        is unchanged. The invalidation is a generation, not an emptied cache -- an empty cache
        reads as `nothing to send` (a 0 count never reaches the hub, tsk-yfc9n6kmvs52)."""
        with self.lock:
            self.invalidation_gen += 1

    def _advertise(self, running: dict[str, int] | None, now: float, force: bool = False) -> None:
        """`PATCH /runner` with the targets' `running` and reachability: at most every
        ADVERTISE_EVERY seconds for a changed count, at once (`force`) for reachability, and
        always once an invalidation (a reconnect) is pending, whatever the count."""
        if self.client is None or self.capabilities is None:
            return
        with self.lock:
            # Zero counts are left out, so a runner with nothing running matches its hello.
            counts = {
                k: v
                for k, v in (self.advertised_counts if running is None else running).items()
                if v
            }
            gen = self.invalidation_gen
            dirty = gen != self.advertised_gen  # a reconnect is pending
            # A pending invalidation sends regardless of the count being unchanged or throttled.
            if (
                not force
                and not dirty
                and (counts == self.advertised_counts or now - self.advertised_at < ADVERTISE_EVERY)
            ):
                return
            total = sum(counts.values())
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
        # The network call is made without the lock held.
        try:
            self.client.call("PATCH", "/runner", body={"capabilities": caps})
        except hub.HubError as exc:
            self.log(f"supervisor: advertising running={total} failed ({exc})")
            return
        with self.lock:
            # Commit only if no invalidation arrived while this PATCH was in flight; otherwise a
            # stale (older) PATCH would write its counts into `advertised_counts`/
            # `advertised_running`/the capabilities, over the live state. Left uncommitted it stays
            # dirty (its captured `gen` is older than the reconnect's) and the next tick re-sends.
            if self.invalidation_gen != gen:
                return
            self.advertised_counts, self.advertised_at = counts, now
            self.advertised_running = total
            # Advance the advertised generation only on a live send (`running` is the tick's
            # per-target counts). A forced cached send (`running is None`: `advertise_now`, a
            # reachability change) leaves the generation behind, so a reconnect's invalidation
            # stays pending and the next live tick re-sends the current count, not the cache.
            if running is not None:
                self.advertised_gen = gen
            # The live counts also go back into the shared capabilities, so serve's next `hello`
            # carries this total and these per-target counts, not the 0 the dict was built with.
            # `self.lock` guards these `running` fields -- the one place the tick thread and
            # serve's hello thread coordinate over the shared dict (see `advertised_capabilities`).
            self.capabilities["running"] = total
            for entry in self.capabilities.get("targets", []):
                entry["running"] = counts.get(entry.get("name"), 0)

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
            # Only to a hub that knows the field: an older one refuses a report that has it.
            **({"sessions": rec.sessions} if rec.reports_sessions else {}),
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
                    self.log(changed(p["id"], rec))
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
    ".kube", ".docker", ".local/share/opencode", ".config/opencode", ".gemini",
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
    # The home resolved too: with a link in its path, its secrets and the runner's own
    # configuration (resolved) would no longer be seen as one inside the other
    # (adapters.outermost).
    found = [*((norm(state_dir),) if state_dir else ()),
             *(norm(home) / n for n in HOME_SECRETS)]  # fmt: skip
    found += [*others, *(norm(path) for path in extra)]
    return tuple(dict.fromkeys(p for p in found if p != clone and p not in clone.parents))


def other_credentials(workspaces: Path, clone: Path, as_user: AsUser) -> list[Path]:
    """The credential directories of the other clones under `workspaces` as they stand now,
    a workspace folder's clone `repo` included
    (a clone made later is covered from the agent's next start), listed as the agents' user,
    who owns them and may be the only one able to list them. A start whose other clones
    cannot be checked completely is refused (`workspace.Refused`): an unreadable directory
    could hide a credential, and the sandbox would start without its deny. Each is named
    where it lies, as the agents' side resolves it; one inside the workspaces root is named
    below `workspaces` as given (resolved here), the form the clone's own path and the
    root's deny have."""
    root = workspaces.resolve() if as_user.here else workspaces
    refused = workspace.Refused("harness_refused")
    if as_user.direct:
        found: list[Path] = []
        try:
            for project in root.iterdir() if root.is_dir() else ():
                if project.is_dir() and not project.is_symlink():
                    found += [c / ".git" / "maity" for d in project.iterdir()
                              for c in (d, d / workspace.REPO)
                              if (c / ".git" / "maity").is_dir()]  # fmt: skip
        except OSError as exc:
            raise refused from exc
        real_root, real_clone = root, clone.resolve()
    elif not as_user.exists(root, "-d"):
        return []  # no clone yet: nothing to hide
    else:
        real_root, real_clone = _canonical([root, clone], as_user, refused)
        found = _listed(real_root, as_user, refused)
    own = _below_root(real_clone, real_root, root) / ".git" / "maity"
    named = {_below_root(p, real_root, root) for p in _canonical(found, as_user, refused)}
    return sorted(named - {own})


def other_scratches(
    workspaces: Path, own: Path | None, as_user: AsUser, host: str = ""
) -> list[Path]:
    """The scratch of every other placement under `workspaces` as it stands now
    (`<root>/<project>/.scratch/<placement id>`, workspace.scratch_of), so the sandbox hides
    them as it hides the other clones' credentials (tsk-w7qtcbzcshn9, the security review of
    #2032). The list covers the scratches there at the start (tsk-rbys2j9q0m48 tracks the rest,
    as for the other clones' credentials). Named as scratch_of
    names them: below the root resolved here, as given on an
    ssh host. A listing that cannot be completed refuses the start (`workspace.Refused`): an
    unreadable `.scratch` could hide one, and the sandbox would start without its deny."""
    root = workspaces if host else workspaces.resolve()
    refused = workspace.Refused("harness_refused")
    found: list[Path] = []
    if as_user.direct:
        try:
            for project in root.iterdir() if root.is_dir() else ():
                holder = project / workspace.SCRATCH
                if project.is_symlink() or holder.is_symlink() or not holder.is_dir():
                    continue
                found += [root / project.name / workspace.SCRATCH / e.name
                          for e in holder.iterdir()]  # fmt: skip
        except OSError as exc:
            raise refused from exc
    elif as_user.exists(root, "-d"):
        # The root with a trailing slash, so a root that is a link is listed through it; only the
        # projects' own `.scratch` (never a clone's content, which may be unreadable) is read.
        listed = as_user.run(["sh", "-c", _SCRATCHES, "sh", f"{root}/"])
        if listed.returncode != 0:  # some `.scratch` could not be read: the list may be short
            raise refused
        for entry in listed.stdout.split("\0"):
            names = Path(entry).parts[-3:] if entry else ()
            if len(names) == 3 and names[1] == workspace.SCRATCH:
                found.append(root / names[0] / workspace.SCRATCH / names[2])
    return sorted(set(found) - ({own} if own is not None else set()))


# Every entry of every project's `.scratch` under the root given (with a trailing slash), one
# NUL after each: the projects are the root's own entries (a project's name never starts with a
# dot, workspace.TOKEN), a project or a `.scratch` that is a link is skipped, as on the direct
# side. A root, a project or a `.scratch` that cannot be read and searched ends with 3, as a
# PermissionError does on the direct side: it could hide a scratch (the review of #2032).
_SCRATCHES = r"""[ -r "$1" ] && [ -x "$1" ] || exit 3
for p in "$1"*; do
  [ -d "$p" ] && ! [ -L "$p" ] || continue
  [ -r "$p" ] && [ -x "$p" ] || exit 3
  h=$p/.scratch
  [ -d "$h" ] && ! [ -L "$h" ] || continue
  [ -r "$h" ] && [ -x "$h" ] || exit 3
  find "$h" -mindepth 1 -maxdepth 1 -print0 || exit 3
done
[ -r "$1" ] && [ -x "$1" ] || exit 3"""


# For each clone entry given: its two places for a credential, looked at through a link as
# Path.is_dir does on the direct side, one NUL after each found. A place that cannot be
# looked at (a directory on its way, where it lies, that cannot be searched) ends the
# listing with 3, as a PermissionError does there: it could hide one. Only `test` and
# `readlink -n` (no `realpath -m`, which not every system has; `-n` keeps a name's own
# last line break on every system). Links the system does not resolve are followed here
# one by one; what cannot be checked completely (a loop, a chain too long to follow, a
# place that cannot be searched) ends the listing with 3: the start is refused.
_SLOTS = r"""blocked() (
  q=$1 n=${3:-0}
  if [ -e "$q" ]; then
    if [ "$2" = self ] && [ -d "$q" ] && ! [ -x "$q" ]; then exit 0; fi
    exit 1
  fi
  p=${q%/*}
  [ -n "$p" ] || p=/
  if [ "$p" != "$q" ] && blocked "$p" self "$n"; then exit 0; fi
  [ -L "$q" ] || exit 1
  [ "$n" -lt 40 ] || exit 0
  t=$(readlink -n -- "$q" && printf x) || exit 0
  t=${t%x}
  case $t in /*) ;; *) t=${p%/}/$t ;; esac
  blocked "$t" "$2" $((n + 1))
)
for d; do
  for c in "$d" "$d/repo"; do
    for q in "$c" "$c/.git"; do
      if blocked "$q" self; then exit 3; fi
    done
    if blocked "$c/.git/maity" parent; then exit 3; fi
    if [ -d "$c/.git/maity" ]; then printf '%s\0' "$c/.git/maity"; fi
  done
done"""


# Each path resolved, one NUL after each, its name kept exactly (a trailing newline too).
_REALPATHS = r"""for p; do
  r=$(realpath -- "$p" && printf x) || exit 3
  printf '%s\0' "${r%?x}"
done"""


def _listed(root: Path, as_user: AsUser, refused: workspace.Refused) -> list[Path]:
    """The credential directories under the real directory `root`, listed as the agents'
    user on their side, as the direct side lists them: every clone's two places for one
    (`<clone>/.git/maity`, `<clone>/repo/.git/maity`) under every project that is not a
    link, looked at through a link."""
    entries = as_user.run(["find", str(root), "-mindepth", "2", "-maxdepth", "2", "-print0"])
    if entries.returncode != 0:  # some directory could not be read: the list may be short
        raise refused
    clones = [d for d in entries.stdout.split("\0") if d]
    if not clones:
        return []
    checked = as_user.run(["sh", "-c", _SLOTS, "sh", *clones])
    if checked.returncode != 0:
        raise refused
    return [Path(p) for p in checked.stdout.split("\0") if p]


def _below_root(path: Path, real_root: Path, root: Path) -> Path:
    """`path`, resolved on the agents' side, named below `root` when it lies in `real_root`
    (what `root` resolves to there); a path outside it stays as it was resolved."""
    try:
        return root / path.relative_to(real_root)
    except ValueError:
        return path


def _canonical(paths: list[Path], as_user: AsUser, refused: workspace.Refused) -> list[Path]:
    """`paths` as the agents' side resolves them, so that a path's place in the listing is
    its place on disk (adapters.outermost compares them as written). Resolved where the
    agents run, as their user; any path that cannot be resolved fails closed."""
    if not paths:
        return []
    if as_user.direct:
        try:
            return [path.resolve(strict=True) for path in paths]
        except OSError as exc:
            raise refused from exc
    done = as_user.run(["sh", "-c", _REALPATHS, "sh", *(str(path) for path in paths)])
    resolved = [Path(p) for p in done.stdout.split("\0")[:-1]]
    if done.returncode != 0 or len(resolved) != len(paths):
        raise refused
    return resolved


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
