"""The owner's digest of agent instances that are away (docs/api.md §5.3).

An instance is *away* when its session's episode (`not_listening_since`, `not_listening`) has
lasted the owner's threshold for that project, or when it is a *stalled holder*: it holds a
claim and its latest session's `last_seen_at` is that long ago, the session open or revoked.
The threshold is the owner's own override for the project (§6.2), else their personal
`not_listening.minutes` (§18.4). Once an hour, on the hour (UTC), the worker looks at every
owner's away instances.

`bell` keeps the account record `agents_not_listening`. The table is append-only, so the
worker writes only when the state flips: `{instances, holding}` when an owner's first instance
becomes away, `{instances: 0, holding: 0}` when none is away any more or the mode leaves
`bell`. Whether the bell's item is open, and the counts in its title, are derived when it is
read (`away_of`), so it is listed exactly while an instance is away.

`inbox` keeps one personal request per owner, with no project (`filed_by: hub`, no asker). It
is never rewritten: it stores the lines it shows (`request.not_listening`), and when the lines
the hour would show differ, it is withdrawn and, while an away instance is not silenced, a new
one filed, so an answer from a page that has not seen the change is `request_not_open`.
Answering `seen` records, per owner and listed instance, the `last_seen_at` and the episode's
`since` the request showed (`not_listening_seen`); an instance is silenced while one matches.
The digest replaces the request per episode the hub filed before, in every mode: the first
hour withdraws those still open.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, and_, func, insert, select, update

from maity_hub import clock, maintenance, worker_runs
from maity_hub import tables as t
from maity_hub.cards import CLOSED as CLOSED_CARDS
from maity_hub.events import lock_project, transaction
from maity_hub.notifications import preferences, records

log = logging.getLogger(__name__)

RECORD = "agents_not_listening"
CHECK_EVERY = 60.0  # seconds between the worker's looks at the clock
# Half an hour, not one: the pods look at the clock at different seconds, and with a full hour the
# pass that started at 10:00:30 would refuse every pod that looks at 11:00:05.
ONE_PASS_PER_HOUR = 1800.0

EPISODE = "episode"
HOLDER = "stalled_holder"


@dataclass(frozen=True)
class Away:
    agent_id: str
    handle: str
    instance: str
    project_id: str
    membership_id: int
    kind: str  # EPISODE or HOLDER
    last_seen_at: datetime
    since: datetime | None = None  # the episode's start; None for a stalled holder
    cards: tuple[str, ...] = ()  # the cards a stalled holder holds
    reason: str | None = None  # a stalled holder's (§5.3)

    @property
    def key(self) -> tuple[int, str]:
        return (self.membership_id, self.instance)

    @property
    def started(self) -> datetime:
        """Where its length is counted from: the episode's start, or the last sign of life."""
        return self.since if self.since is not None else self.last_seen_at


def _episodes(conn: Connection, owner_id: str | None = None) -> list[Any]:
    """Every session in an episode, with its agent's owner, handle, instance and project."""
    query = (
        select(
            t.agent_session.c.not_listening_since.label("since"),
            t.agent_session.c.last_seen_at,
            t.membership.c.id.label("membership_id"),
            t.membership.c.agent_id,
            t.membership.c.project_id,
            t.agent_profile.c.owner_id,
            t.agent_profile.c.handle,
            t.credential.c.instance,
        )
        .join(t.membership, t.membership.c.id == t.agent_session.c.membership_id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .join(t.credential, t.credential.c.id == t.agent_session.c.credential_id)
        .where(t.agent_session.c.not_listening_since.isnot(None))
    )
    if owner_id is not None:
        query = query.where(t.agent_profile.c.owner_id == owner_id)
    return list(conn.execute(query).all())


def _paused_by_another(row: Any, agent_id: str) -> bool:
    """A pause a human, an admin agent or the manager set; the agent's own does not count."""
    return row.paused_since is not None and row.paused_by != agent_id


def _holders(conn: Connection, owner_id: str | None, now: datetime) -> list[Any]:
    """Every agent instance that holds a claim, with what the digest needs about it: its latest
    session's `last_seen_at`, whether that session ended, and its reason. Claims a bridge
    holds (no instance) and instances under someone else's pause are left out (§5.3)."""
    c = t.card.c
    query = (
        select(
            c.id.label("card_id"),
            c.claim_instance.label("instance"),
            t.membership.c.id.label("membership_id"),
            t.membership.c.agent_id,
            t.membership.c.project_id,
            t.membership.c.paused_since,
            t.membership.c.paused_by,
            t.membership.c.limit_until,
            t.agent_profile.c.owner_id,
            t.agent_profile.c.handle,
        )
        .join(t.membership, t.membership.c.id == c.claim_holder)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(
            c.claim_holder.isnot(None),
            c.claim_instance.isnot(None),
            c.status.notin_(CLOSED_CARDS),  # a closed card keeps its holder's columns
        )
        .order_by(c.id)
    )
    if owner_id is not None:
        query = query.where(t.agent_profile.c.owner_id == owner_id)
    held: dict[tuple[int, str], dict[str, Any]] = {}
    for row in conn.execute(query):
        if _paused_by_another(row, row.agent_id):
            continue
        entry = held.setdefault((row.membership_id, row.instance), {"row": row, "cards": []})
        entry["cards"].append(row.card_id)
    if not held:
        return []
    credentials = {
        (r.membership_id, r.instance): r
        for r in conn.execute(
            select(t.credential).where(t.credential.c.membership_id.in_({k[0] for k in held}))
        )
        if (r.membership_id, r.instance) in held
    }
    sessions = {
        r.credential_id: r for r in _latest_sessions(conn, {c.id for c in credentials.values()})
    }  # equal starts: the last id wins
    found = []
    for key, entry in held.items():
        row, credential = entry["row"], credentials.get(key)
        if credential is None or _paused_by_another(credential, row.agent_id):
            continue
        session = sessions.get(credential.id)
        if session is None:
            continue  # never resumed: no sign of life to count from
        found.append(
            (
                row,
                credential,
                session,
                tuple(entry["cards"]),
                _reason(row, credential, session, now),
            )
        )
    return found


def _latest_sessions(conn: Connection, credential_ids: set[str]) -> list[Any]:
    """Each credential's latest session, ended or not, by start, and only that one: the bell
    reads this live, and the history of ended sessions grows without bound."""
    if not credential_ids:
        return []
    s = t.agent_session
    latest = (
        select(s.c.credential_id, func.max(s.c.started_at).label("started_at"))
        .where(s.c.credential_id.in_(credential_ids))
        .group_by(s.c.credential_id)
        .subquery()
    )  # once per credential, along `ix_agent_session_credential_started`
    return list(
        conn.execute(
            select(s)
            .join(
                latest,
                and_(
                    s.c.credential_id == latest.c.credential_id,
                    s.c.started_at == latest.c.started_at,
                ),
            )
            .order_by(s.c.started_at, s.c.id)
        )
    )


def _reason(member: Any, credential: Any, session: Any, now: datetime) -> str:
    """Why a stalled holder stopped, as far as the hub knows (§5.3), first match wins."""
    if credential.revoked_at is not None or session.ended_at is not None:
        return "session_ended"
    if member.limit_until is not None and member.limit_until > now:
        return "limit"
    if credential.paused_since is not None or member.paused_since is not None:
        return "paused"  # someone else's pause left it out already, so this one is its own
    if session.not_listening_since is not None:
        return "not_listening"
    return "silent"


def _thresholds(conn: Connection, owner_id: str, project_ids: set[str]) -> dict[str, int]:
    """Minutes per project for this owner: their override there, else their personal
    default (§6.2), whether or not they are a member of the project."""
    personal = int(preferences.preferences(conn, owner_id)["not_listening"]["minutes"])
    found = dict.fromkeys(project_ids, personal)
    if not project_ids:
        return found
    for project_id, own in conn.execute(
        select(t.membership.c.project_id, t.membership.c.own_settings).where(
            t.membership.c.human_id == owner_id,
            t.membership.c.active.is_(True),
            t.membership.c.project_id.in_(project_ids),
        )
    ):
        minutes = ((own or {}).get("not_listening") or {}).get("minutes")
        if minutes is not None:
            found[project_id] = int(minutes)
    return found


def away_of(conn: Connection, owner_id: str, now: datetime | None = None) -> list[Away]:
    """The owner's instances that are away now: the episodes, oldest first, then the stalled
    holders, longest silent first. An instance that is both is listed once, as a stalled
    holder, since its line names the cards."""
    now = now or clock.now()
    episodes = _episodes(conn, owner_id)
    holders = _holders(conn, owner_id, now)
    minutes = _thresholds(
        conn,
        owner_id,
        {r.project_id for r in episodes} | {h[0].project_id for h in holders},
    )

    def long_enough(project_id: str, start: datetime) -> bool:
        return now - start >= timedelta(minutes=minutes[project_id])

    stalled = [
        Away(
            row.agent_id,
            row.handle,
            row.instance,
            row.project_id,
            row.membership_id,
            HOLDER,
            session.last_seen_at,
            cards=cards,
            reason=reason,
        )
        for row, _credential, session, cards, reason in holders
        if long_enough(row.project_id, session.last_seen_at)
    ]
    taken = {a.key for a in stalled}
    listed = [
        Away(
            r.agent_id,
            r.handle,
            r.instance,
            r.project_id,
            r.membership_id,
            EPISODE,
            r.last_seen_at,
            since=r.since,
        )
        for r in episodes
        if long_enough(r.project_id, r.since) and (r.membership_id, r.instance) not in taken
    ]
    return sorted(listed, key=lambda a: (a.started, a.handle, a.instance)) + sorted(
        stalled, key=lambda a: (a.started, a.handle, a.instance)
    )


def latest(conn: Connection, owner_id: str, now: datetime | None = None) -> Any | None:
    """The owner's newest `agents_not_listening` record within the window the bell reads
    (`records.KEPT`), open when its count is not 0. An open record that left the window is
    not seen, so `reconcile` writes a new one and the bell keeps listing it."""
    since = (now or clock.now()) - records.KEPT
    return conn.execute(
        select(t.account_record)
        .where(
            t.account_record.c.human_id == owner_id,
            t.account_record.c.type == RECORD,
            t.account_record.c.at >= since,
        )
        .order_by(t.account_record.c.n.desc())
        .limit(1)
    ).first()


def _is_open(row: Any | None) -> bool:
    return row is not None and int((row.data or {}).get("instances", 0)) > 0


def withdraw_episode_requests(conn: Connection, owner_id: str) -> None:
    """Withdraw the per-episode requests still open for the owner's sessions, filed before
    the digest replaced them (§5.3). The session forgets the request only if it still holds
    this one."""
    from maity_hub.routes.requests import withdraw_hub_notice

    s = t.agent_session.c
    held = conn.execute(
        select(s.id, s.not_listening_request_id, t.membership.c.project_id)
        .join(t.membership, t.membership.c.id == s.membership_id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(t.agent_profile.c.owner_id == owner_id, s.not_listening_request_id.isnot(None))
        .order_by(t.membership.c.project_id, s.id)
    ).all()
    # The projects' locks first, as the episode's own check takes them (not_listening.check):
    # the request's withdrawal emits under that lock, so the other order could deadlock.
    for project_id in sorted({row.project_id for row in held}):
        lock_project(conn, project_id)
    for session_id, request_id, _ in held:
        withdraw_hub_notice(conn, request_id, "the owner's digest replaces it")
        conn.execute(
            update(t.agent_session)
            .where(s.id == session_id, s.not_listening_request_id == request_id)
            .values(not_listening_request_id=None)
        )


TITLE = "{n} of your agent instances are not listening"
TITLE_AWAY = "{n} of your agent instances are away"
ADVICE = (
    "Their harness may have stopped its wait loop, or the agent is busy without waiting;"
    " start the loops again or end the sessions."
)
HOLDER_ADVICE = (
    "Instances that stopped while holding cards: start them again, or have their cards moved."
)
NONE_LEFT = "no agent instance is away any more"
MODE_LEFT = "the owner's not_listening.mode is no longer inbox"
CHANGED = "what the digest shows changed; a new one follows when something is new"


def _digest_requests(owner_id: str) -> Any:
    """The owner's digest requests: personal, filed by the hub, with neither project nor
    organisation, which no other request is."""
    r = t.request.c
    return select(t.request).where(
        r.to_human == owner_id,
        r.personal.is_(True),
        r.filed_by == "hub",
        r.project_id.is_(None),
        r.org_id.is_(None),
    )


def open_digest(conn: Connection, owner_id: str) -> Any | None:
    return conn.execute(_digest_requests(owner_id).where(t.request.c.status == "open")).first()


def _stamp(at: datetime | None) -> str | None:
    return None if at is None else at.isoformat()


def lines(away: list[Away]) -> list[dict[str, Any]]:
    """What a digest request shows of each away instance, stored with it: compared on the
    hour, recorded at `seen`."""
    return [
        {
            "membership_id": a.membership_id,
            "instance": a.instance,
            "kind": a.kind,
            "since": _stamp(a.since),
            "last_seen_at": _stamp(a.last_seen_at),
            "cards": list(a.cards),
            "reason": a.reason,
        }
        for a in away
    ]


def _shown(stored: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The part of the stored lines a reader sees: an episode's line shows its start, not its
    last call, which moves while the instance keeps calling (§5.3)."""
    return [
        {k: v for k, v in line.items() if not (line.get("kind") == EPISODE and k == "last_seen_at")}
        for line in stored or []
    ]


def _seen(conn: Connection, owner_id: str) -> dict[tuple[int, str], Any]:
    s = t.not_listening_seen.c
    return {
        (r.membership_id, r.instance): r
        for r in conn.execute(select(t.not_listening_seen).where(s.human_id == owner_id))
    }


def silenced(away: Away, seen: dict[tuple[int, str], Any]) -> bool:
    """Whether the owner already saw this (§5.3, "Silence after `seen`"): no call since a
    request they answered showed it (1), or, listed as an episode, that episode (2)."""
    record = seen.get(away.key)
    if record is None:
        return False
    if record.last_seen_at == away.last_seen_at:
        return True
    return away.kind == EPISODE and record.since is not None and record.since == away.since


def record_seen(conn: Connection, request: Any, human_id: str) -> None:
    """The owner answered `seen` to this digest request: record, per instance it showed, its
    `last_seen_at` and, for an episode, its `since`. A later record replaces an earlier one
    for the same instance, as the earlier can never match again; an episode's start stays
    when the instance is listed as a stalled holder this time."""
    shown = request.not_listening or []
    if not shown:
        return
    seen = _seen(conn, human_id)
    s = t.not_listening_seen.c
    for line in shown:
        key = (int(line["membership_id"]), str(line["instance"]))
        last = datetime.fromisoformat(line["last_seen_at"])
        since = datetime.fromisoformat(line["since"]) if line.get("since") else None
        old = seen.get(key)
        if old is None:
            conn.execute(
                insert(t.not_listening_seen).values(
                    human_id=human_id,
                    membership_id=key[0],
                    instance=key[1],
                    last_seen_at=last,
                    since=since,
                )
            )
            continue
        conn.execute(
            update(t.not_listening_seen)
            .where(s.human_id == human_id, s.membership_id == key[0], s.instance == key[1])
            .values(
                last_seen_at=max(last, old.last_seen_at),
                since=since if since is not None else old.since,
            )
        )


def _summary(conn: Connection, away: list[Away]) -> str:
    from maity_hub import namespace

    names = namespace.full_names(conn, {a.project_id for a in away})
    shown = []
    for a in away:
        where = f"{a.handle} ({a.instance}) in {names[a.project_id]}"
        if a.kind == EPISODE:
            shown.append(f"{where}, since {_minute(a.started)} (UTC)")
        else:
            shown.append(
                f"{where} holds {', '.join(a.cards)}, last seen {_minute(a.last_seen_at)}"
                f" (UTC), {a.reason}"
            )
    advice = [ADVICE] if any(a.kind == EPISODE for a in away) else []
    advice += [HOLDER_ADVICE] if any(a.kind == HOLDER for a in away) else []
    return "\n".join(shown) + "\n\n" + " ".join(advice)


def _minute(at: datetime) -> str:
    return at.strftime("%Y-%m-%d %H:%M")


def title(away: list[Away]) -> str:
    """`not listening` when every instance is listed as an episode, else `away` (§5.3)."""
    text = TITLE if all(a.kind == EPISODE for a in away) else TITLE_AWAY
    return text.format(n=len(away))


def _inbox(conn: Connection, owner_id: str, now: datetime | None) -> None:
    """One open digest request while an instance is away that the owner has not seen yet.
    It is never rewritten: when what it would show changed, it is withdrawn and, while an
    away instance is not silenced, a new one filed (§5.3)."""
    from maity_hub.routes.requests import close_request, file_hub_digest

    away = away_of(conn, owner_id, now)
    shown = lines(away)
    found = open_digest(conn, owner_id)
    if found is not None:
        # A request filed before the lines were stored has none, and counts as changed.
        if found.not_listening is not None and _shown(found.not_listening) == _shown(shown):
            return
        close_request(conn, found.id, "withdrawn", None, reason=CHANGED if away else NONE_LEFT)
    seen = _seen(conn, owner_id)
    if away and not all(silenced(a, seen) for a in away):
        file_hub_digest(conn, owner_id, title(away), _summary(conn, away), shown)


def reconcile(conn: Connection, owner_id: str, now: datetime | None = None) -> None:
    """Bring one owner's record and requests in line with their mode and their away
    instances. The old per-episode requests go first, under their projects' locks; then the
    owner's row is locked, the order every path takes (project, then human), so two passes
    over the same owner run one after the other and the second sees what the first wrote."""
    withdraw_episode_requests(conn, owner_id)
    records.lock_human(conn, owner_id)
    mode = preferences.preferences(conn, owner_id)["not_listening"]["mode"]
    if mode == "inbox":
        _inbox(conn, owner_id, now)
    else:
        _close_digest(conn, owner_id)
    away = away_of(conn, owner_id, now) if mode == "bell" else []
    open_ = _is_open(latest(conn, owner_id, now))
    if away and not open_:
        records.write(
            conn,
            owner_id,
            RECORD,
            {"instances": len(away), "holding": sum(a.kind == HOLDER for a in away)},
        )
    elif not away and open_:
        records.write(conn, owner_id, RECORD, {"instances": 0, "holding": 0})


def _close_digest(conn: Connection, owner_id: str) -> None:
    from maity_hub.routes.requests import close_request

    found = open_digest(conn, owner_id)
    if found is not None:
        close_request(conn, found.id, "withdrawn", None, reason=MODE_LEFT)


def mode_changed(conn: Connection, owner_id: str, old: str, new: str) -> None:
    """A change of `not_listening.mode` takes effect at the `PATCH` (§5.3): leaving
    `bell` closes an open record, leaving `inbox` withdraws an open digest request, both at
    once. The digest request has no project, so withdrawing it emits no event and needs no
    events transaction. The human's lock first, as the hourly pass takes it: a pass that read
    the old mode commits before this looks for its digest."""
    records.lock_human(conn, owner_id)
    if old == "bell" and new != "bell" and _is_open(latest(conn, owner_id)):
        records.write(conn, owner_id, RECORD, {"instances": 0, "holding": 0})
    if old == "inbox" and new != "inbox":
        _close_digest(conn, owner_id)


def run(
    engine: Engine, now: datetime | None = None, stop: worker_runs.Stopping | None = None
) -> None:
    """One hour's pass over every owner with an episode, a holding instance, a record or an
    open digest request."""
    now = now or clock.now()
    with engine.connect() as conn:
        owners = {r.owner_id for r in _episodes(conn) if r.owner_id}
        owners |= {h[0].owner_id for h in _holders(conn, None, now) if h[0].owner_id}
        owners |= {
            h
            for h in conn.execute(
                select(t.account_record.c.human_id)
                .where(t.account_record.c.type == RECORD)
                .distinct()
            ).scalars()
        }
        r = t.request.c
        owners |= {
            h
            for h in conn.execute(
                select(r.to_human)
                .where(
                    r.status == "open",
                    r.personal.is_(True),
                    r.filed_by == "hub",
                    r.project_id.is_(None),
                    r.org_id.is_(None),
                )
                .distinct()
            ).scalars()
        }
    for owner_id in sorted(owners):
        if stop is not None and stop.is_set():
            return
        with transaction(engine) as conn:
            reconcile(conn, owner_id, now)


def next_hour(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


class Worker:
    """Runs `run` on the hour (UTC), looking at the clock once a minute (§5.3)."""

    def __init__(self, engine: Engine, interval: float | None = None) -> None:
        self.engine = engine
        self.interval = CHECK_EVERY if interval is None else interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._due = next_hour(clock.now())

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="maity-not-listening-digest", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            now = clock.now()
            if now < self._due:
                continue
            try:
                if maintenance.running_now(self.engine):
                    continue  # the hour's digest comes after the window (§16.12)
                self._due = next_hour(now)
                with worker_runs.claim(
                    self.engine, "not-listening-digest", ONE_PASS_PER_HOUR, self._stop
                ) as held:
                    if held is not None:
                        run(self.engine, now, held)
            except Exception:
                log.exception("the not-listening digest failed")
