"""The forge probe (docs/api.md §11): cached observations, reports, the open release.

A read from the forge never happens inside a database transaction: the
cache is read, the forge is asked with no connection held, and the result
is written in a short transaction of its own. Observations live in
`forge_observation`, one row per (project, kind, ref); releases read them
from there (`releases.py`).

The worker is one thread per hub process. It probes a card right after its
report and, on its own interval, every report still without an observation
(on open cards of any age, and on cards closed within a day) and the open
release's pull requests and tag.

Whatever writes an observation (the worker, a report's probe, `GET /probe`)
compares it with the stored one under the project lock: a change to a ref
of the open release is announced there with `probe_observed`, and release
readiness is rechecked in the same transaction. So it does not matter who
saw a merge first.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, delete, insert, select, update

from maity_hub import clock, forge, releases
from maity_hub import tables as t
from maity_hub.events import emit, lock_project, transaction
from maity_hub.views import principal_id

log = logging.getLogger(__name__)

MAX_AGE = 60  # seconds an observation answers a read without asking the forge (§11)
INTERVAL = 300  # seconds between the worker's sweeps
REPORT_WINDOW = timedelta(days=1)  # closed cards whose report a sweep still tries to observe


class Observation:
    def __init__(
        self, data: dict[str, Any], observed_at: datetime, fresh: bool, changed: bool = False
    ) -> None:
        self.data, self.observed_at, self.fresh = data, observed_at, fresh
        self.changed = changed  # this read changed what is stored

    def shown(self) -> dict[str, Any]:
        """The shape of §11; a tag carries its own `observed_at` (§6.7 `release.tag`)."""
        data = dict(self.data)
        if "sha" in data:
            data["observed_at"] = clock.rfc3339(self.observed_at)
        return data

    def stamped(self) -> dict[str, Any]:
        """The shape with the time it was observed, for `details.last` and events."""
        return {**self.shown(), "observed_at": clock.rfc3339(self.observed_at)}


def _cached(conn: Connection, project_id: str, kind: str, ref: str) -> Any:
    return conn.execute(
        select(t.forge_observation).where(
            t.forge_observation.c.project_id == project_id,
            t.forge_observation.c.kind == kind,
            t.forge_observation.c.ref == ref,
        )
    ).first()


def _read(fg: forge.Forge, repository: str, kind: str, ref: str) -> dict[str, Any]:
    try:
        if kind == "pr":
            return fg.pull_request(repository, int(ref))
        if kind == "branch":
            return fg.branch(repository, ref)
        return fg.tag(repository, ref)
    except (KeyError, TypeError, AttributeError) as error:
        # An answer of another shape than the API documents: as good as none.
        raise forge.ForgeUnavailableError(
            f"the forge answered in an unexpected shape: {type(error).__name__}"
        ) from None


def observe(
    engine: Engine, fg: forge.Forge, project: Any, kind: str, ref: str, max_age: int = MAX_AGE
) -> Observation:
    """The observation of one ref, from the cache when younger than `max_age`.

    Raises `forge.ForgeUnavailableError` when the forge must be asked and
    does not answer; the caller decides what the last observation is worth.
    """
    with engine.connect() as conn:
        row = _cached(conn, project.id, kind, ref)
    now = clock.now()
    if row is not None and max_age > 0 and now - row.observed_at < timedelta(seconds=max_age):
        return Observation(dict(row.data), row.observed_at, fresh=False)
    # The time the read started: a slow read that began before a fast one is the
    # older observation, whenever it ends.
    observed_at = clock.now()
    data = _read(fg, forge.repository_of(project.repository_url), kind, ref)
    with transaction(engine) as conn:
        lock_project(conn, project.id)  # one writer per project: delete + insert is the upsert
        stored = _cached(conn, project.id, kind, ref)
        if stored is not None and stored.observed_at > observed_at:
            # A slower read that started earlier must not replace a newer one.
            return Observation(dict(stored.data), stored.observed_at, fresh=True)
        conn.execute(
            delete(t.forge_observation).where(
                t.forge_observation.c.project_id == project.id,
                t.forge_observation.c.kind == kind,
                t.forge_observation.c.ref == ref,
            )
        )
        conn.execute(
            insert(t.forge_observation).values(
                project_id=project.id, kind=kind, ref=ref, observed_at=observed_at, data=data
            )
        )
        observation = Observation(data, observed_at, fresh=True)
        observation.changed = stored is None or _state(stored.data) != _state(data)
        if observation.changed:
            _announce_for_release(conn, fg, project.id, kind, ref, observation)
            releases.recheck(conn, project.id, fg)
    return observation


def _announce_for_release(
    conn: Connection,
    fg: forge.Forge,
    project_id: str,
    kind: str,
    ref: str,
    observation: Observation,
) -> None:
    """`probe_observed` on the open release when the changed ref is one of its own."""
    card = conn.execute(
        select(t.card).where(
            t.card.c.project_id == project_id, t.card.c.release_in_flight.is_(True)
        )
    ).first()
    if card is None:
        return
    if kind == "tag":
        own = ref == f"v{card.release_version}"
    elif kind == "pr":
        numbers = {e["number"] for e in releases.release_view(conn, card, fg)["pull_requests"]}
        own = int(ref) in numbers
    else:
        own = False
    if own:
        emit(
            conn,
            project_id,
            "probe_observed",
            _audience(conn, card),
            {"task": card.id, "observations": {f"{kind}:{ref}": observation.stamped()}},
            subject=("task", card.id),
        )


def last(engine: Engine, project_id: str, kind: str, ref: str) -> Observation | None:
    """The stored observation, however old."""
    with engine.connect() as conn:
        row = _cached(conn, project_id, kind, ref)
    return None if row is None else Observation(dict(row.data), row.observed_at, fresh=False)


def _project(engine: Engine, project_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.project).where(t.project.c.id == project_id)).first()


def _audience(conn: Connection, card: Any) -> list[str]:
    holder = principal_id(conn, card.claim_holder)
    return [*([f"member:{holder}"] if holder else []), "role:admin"]


# --- reports (§6.6) ---------------------------------------------------------------------------


def observe_report(engine: Engine, fg: forge.Forge, card_id: str, max_age: int = 0) -> bool:
    """Fill `report.observed` and `mismatch`; True when the card changed."""
    with engine.connect() as conn:
        card = conn.execute(select(t.card).where(t.card.c.id == card_id)).first()
    if card is None or not card.report or card.report.get("code") is False:
        return False
    project = _project(engine, card.project_id)
    if not fg.configured_for(project.repository_url):
        return False
    report = card.report
    branch = (
        observe(engine, fg, project, "branch", report["branch"], max_age)
        if report.get("branch")
        else None
    )
    pr_number = (
        (report.get("pr") or {}).get("number") if report.get("pr_status") == "found" else None
    )
    pr = observe(engine, fg, project, "pr", str(pr_number), max_age) if pr_number else None
    times = [o.observed_at for o in (branch, pr) if o is not None]
    if not times:
        return False
    observed = {
        "pr_state": pr.data.get("state") if pr else None,
        "pr_head_sha": pr.data.get("head_sha") if pr else None,
        "checks": pr.data.get("checks") if pr else None,
        "branch_head_sha": branch.data.get("head_sha") if branch else None,
        "observed_at": clock.rfc3339(max(times)),
    }
    # A pull request the forge does not have contradicts the report; a branch it no
    # longer has (deleted after the merge) does not.
    mismatch = bool(
        (pr and (not pr.data.get("found") or pr.data.get("head_sha") != report["pr"].get("head")))
        or (
            branch and branch.data["found"] and branch.data["head_sha"] != report.get("remote_head")
        )
    )
    with transaction(engine) as conn:
        lock_project(conn, card.project_id)
        current = conn.execute(select(t.card).where(t.card.c.id == card_id)).first()
        if current is None or not current.report:
            return False
        if _core(current.report) != _core(report):
            return False  # a newer report came in meanwhile; its own probe fills it
        stored = {**current.report, "observed": observed, "mismatch": mismatch}
        if stored == current.report:
            return False
        conn.execute(update(t.card).where(t.card.c.id == card_id).values(report=stored))
        if _seen(current.report) == _seen(stored):
            return True  # only the time moved on: stored, not announced again
        emit(
            conn,
            card.project_id,
            "probe_observed",
            _audience(conn, current),
            {"task": card_id, "observed": observed, "mismatch": mismatch},
            subject=("task", card_id),
        )
        releases.recheck(conn, card.project_id, fg)
    return True


def _core(report: dict[str, Any]) -> dict[str, Any]:
    """The report as the agent sent it: two reports in the same second still differ."""
    return {k: v for k, v in report.items() if k not in ("observed", "mismatch")}


def _seen(report: dict[str, Any]) -> tuple[Any, Any]:
    observed = dict(report.get("observed") or {})
    observed.pop("observed_at", None)
    return observed, report.get("mismatch")


# --- the open release (§6.7) ------------------------------------------------------------------


def observe_release(
    engine: Engine, fg: forge.Forge, project_id: str, max_age: int = MAX_AGE
) -> bool:
    """Refresh the open release's pull requests and tag; True when anything changed."""
    project = _project(engine, project_id)
    if project is None or not fg.configured_for(project.repository_url):
        return False
    with engine.connect() as conn:
        card = conn.execute(
            select(t.card).where(
                t.card.c.project_id == project_id, t.card.c.release_in_flight.is_(True)
            )
        ).first()
        if card is None:
            return False
        refs = [
            ("pr", str(entry["number"]))
            for entry in releases.release_view(conn, card, fg)["pull_requests"]
        ]
    refs.append(("tag", f"v{card.release_version}"))
    changed = False
    for kind, ref in refs:  # each observe() announces and rechecks its own change
        changed = observe(engine, fg, project, kind, ref, max_age).changed or changed
    return changed


def _state(data: dict[str, Any]) -> tuple[Any, ...]:
    """The parts whose change is worth an event; the observation time is not."""
    keys = ("found", "state", "head_sha", "checks", "mergeable", "merged_at", "sha")
    return tuple(data.get(k) for k in keys)


# --- the worker --------------------------------------------------------------------------------


def sweep(engine: Engine, fg: forge.Forge, stop: threading.Event | None = None) -> None:
    """One round: every report without an observation on an open card or one closed
    within REPORT_WINDOW, then every open release. The round ends at the first read
    the forge does not answer (down or rate-limited: the rest would fail alike) and
    when `stop` is set."""
    since = clock.now() - REPORT_WINDOW
    with engine.connect() as conn:
        projects = conn.execute(
            select(t.project.c.id, t.project.c.repository_url).where(
                t.project.c.repository_url.is_not(None)
            )
        ).all()
        cards = conn.execute(
            select(t.card.c.id, t.card.c.report, t.card.c.project_id).where(
                t.card.c.report.is_not(None),
                (t.card.c.closed_at.is_(None)) | (t.card.c.closed_at > since),
            )
        ).all()
    observable = {p.id for p in projects if fg.configured_for(p.repository_url)}
    work: list[tuple[Callable[..., Any], tuple[Any, ...]]] = [
        (observe_report, (engine, fg, card.id, MAX_AGE))
        for card in cards
        if card.project_id in observable
        and card.report.get("observed") is None
        and card.report.get("code") is not False
    ]
    work += [(observe_release, (engine, fg, project_id)) for project_id in sorted(observable)]
    for job, args in work:
        if stop is not None and stop.is_set():
            return
        if not _guarded(job, *args):
            return


def _guarded(work: Callable[..., Any], *args: Any) -> bool:
    """Run one piece of work; False when the forge did not answer."""
    try:
        work(*args)
    except forge.ForgeUnavailableError as error:
        log.warning("probe: %s", error)  # the next round tries again
        return False
    except Exception:
        log.exception("probe: %s failed", work.__name__)
    return True


class Worker:
    """A daemon thread: the cards to probe now, and a sweep every `interval` seconds."""

    def __init__(self, engine: Engine, fg: forge.Forge, interval: float = INTERVAL) -> None:
        self.engine, self.fg, self.interval = engine, fg, interval
        self.jobs: queue.Queue[str | None] = queue.Queue()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, name="maity-probe", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        if self.thread.is_alive():
            self.stopping.set()  # a sweep stops between two reads
            self.jobs.put(None)
            self.thread.join(timeout=forge.TIMEOUT * 3)

    def report_stored(self, card_id: str) -> None:
        """Called after a report's transaction committed; never waits on the forge."""
        self.jobs.put(card_id)

    def _run(self) -> None:
        next_sweep = clock.now()
        while True:
            wait = max(0.0, (next_sweep - clock.now()).total_seconds())
            try:
                job = self.jobs.get(timeout=wait)
            except queue.Empty:
                _guarded(sweep, self.engine, self.fg, self.stopping)
                next_sweep = clock.now() + timedelta(seconds=self.interval)
                continue
            if job is None:
                return
            _guarded(observe_report, self.engine, self.fg, job, 0)
