"""The forge probe (docs/api.md §11): cached observations, reports, the open release.

A read from the forge never happens inside a database transaction: the
cache is read, the forge is asked with no connection held, and the result
is written in a short transaction of its own. Observations live in
`forge_observation`, one row per (project, kind, ref); releases read them
from there (`releases.py`).

The worker is one thread per hub process. It probes a card right after its
report and, on its own interval, every report still without an observation
and the open release's pull requests and tag.
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
REPORT_WINDOW = timedelta(days=1)  # reports a sweep still tries to observe


class Observation:
    def __init__(self, data: dict[str, Any], observed_at: datetime, fresh: bool) -> None:
        self.data, self.observed_at, self.fresh = data, observed_at, fresh

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


def _read(repository: str, kind: str, ref: str) -> dict[str, Any]:
    if kind == "pr":
        return forge.pull_request(repository, int(ref))
    if kind == "branch":
        return forge.branch(repository, ref)
    return forge.tag(repository, ref)


def observe(
    engine: Engine, project: Any, kind: str, ref: str, max_age: int = MAX_AGE
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
    data = _read(forge.repository_of(project.repository_url), kind, ref)
    observed_at = clock.now()
    with transaction(engine) as conn:
        lock_project(conn, project.id)  # one writer per project: delete + insert is the upsert
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
    return Observation(data, observed_at, fresh=True)


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


def observe_report(engine: Engine, card_id: str, max_age: int = 0) -> bool:
    """Fill `report.observed` and `mismatch`; True when the card changed."""
    with engine.connect() as conn:
        card = conn.execute(select(t.card).where(t.card.c.id == card_id)).first()
    if card is None or not card.report:
        return False
    project = _project(engine, card.project_id)
    if not forge.configured_for(project.repository_url):
        return False
    report = card.report
    branch = (
        observe(engine, project, "branch", report["branch"], max_age)
        if report.get("branch")
        else None
    )
    pr_number = (
        (report.get("pr") or {}).get("number") if report.get("pr_status") == "found" else None
    )
    pr = observe(engine, project, "pr", str(pr_number), max_age) if pr_number else None
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
    # A branch the forge no longer has (deleted after the merge) is not a contradiction.
    mismatch = bool(
        (pr and pr.data.get("found") and pr.data.get("head_sha") != report["pr"].get("head"))
        or (
            branch and branch.data["found"] and branch.data["head_sha"] != report.get("remote_head")
        )
    )
    with transaction(engine) as conn:
        lock_project(conn, card.project_id)
        current = conn.execute(select(t.card).where(t.card.c.id == card_id)).first()
        if current is None or not current.report:
            return False
        if current.report.get("reported_at") != report.get("reported_at"):
            return False  # a newer report came in meanwhile; its own probe fills it
        stored = {**current.report, "observed": observed, "mismatch": mismatch}
        if stored == current.report:
            return False
        conn.execute(update(t.card).where(t.card.c.id == card_id).values(report=stored))
        emit(
            conn,
            card.project_id,
            "probe_observed",
            _audience(conn, current),
            {"task": card_id, "observed": observed, "mismatch": mismatch},
            subject=("task", card_id),
        )
        releases.recheck(conn, card.project_id)
    return True


# --- the open release (§6.7) ------------------------------------------------------------------


def observe_release(engine: Engine, project_id: str, max_age: int = MAX_AGE) -> bool:
    """Refresh the open release's pull requests and tag; True when anything changed."""
    project = _project(engine, project_id)
    if project is None or not forge.configured_for(project.repository_url):
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
            for entry in releases.release_view(conn, card)["pull_requests"]
        ]
    refs.append(("tag", f"v{card.release_version}"))
    changed: dict[str, Any] = {}
    for kind, ref in refs:
        before = last(engine, project_id, kind, ref)
        after = observe(engine, project, kind, ref, max_age)
        if before is None or _state(before.data) != _state(after.data):
            changed[f"{kind}:{ref}"] = after.stamped()
    with transaction(engine) as conn:
        lock_project(conn, project_id)
        if changed:
            current = conn.execute(select(t.card).where(t.card.c.id == card.id)).first()
            emit(
                conn,
                project_id,
                "probe_observed",
                _audience(conn, current),
                {"task": card.id, "observations": changed},
                subject=("task", card.id),
            )
        releases.recheck(conn, project_id)
    return bool(changed)


def _state(data: dict[str, Any]) -> tuple[Any, ...]:
    """The parts whose change is worth an event; the observation time is not."""
    keys = ("found", "state", "head_sha", "checks", "mergeable", "merged_at", "sha")
    return tuple(data.get(k) for k in keys)


# --- the worker --------------------------------------------------------------------------------


def sweep(engine: Engine) -> None:
    """One round: every recent report without an observation, every open release."""
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
    observable = {p.id for p in projects if forge.configured_for(p.repository_url)}
    for card in cards:
        if card.project_id in observable and card.report.get("observed") is None:
            _guarded(observe_report, engine, card.id, MAX_AGE)
    for project_id in sorted(observable):
        _guarded(observe_release, engine, project_id)


def _guarded(work: Callable[..., Any], *args: Any) -> None:
    try:
        work(*args)
    except forge.ForgeUnavailableError as error:
        log.warning("probe: %s", error)  # the next round tries again
    except Exception:
        log.exception("probe: %s failed", work.__name__)


class Worker:
    """A daemon thread: the cards to probe now, and a sweep every `interval` seconds."""

    def __init__(self, engine: Engine, interval: float = INTERVAL) -> None:
        self.engine, self.interval = engine, interval
        self.jobs: queue.Queue[str | None] = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="maity-probe", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        if self.thread.is_alive():
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
                _guarded(sweep, self.engine)
                next_sweep = clock.now() + timedelta(seconds=self.interval)
                continue
            if job is None:
                return
            _guarded(observe_report, self.engine, job, 0)
