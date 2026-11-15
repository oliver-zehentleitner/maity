"""Maintenance windows (docs/api.md §16.12, hub/context/maintenance.md).

At most one window is active or upcoming. Its state comes from the clock on every read, so a
window ends at `until` by itself; the deadlines that fell into it move by its length once,
on the first read after its end (`settle`). While it runs, the middleware answers `503
maintenance` (`refusal`), and the sweeps that decide on deadlines by themselves wait
(`running_now`).
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from html import escape
from typing import Any

from sqlalchemy import Connection, Engine, and_, select, update

from maity_hub import clock, events
from maity_hub import tables as t
from maity_hub.ids import new_id

log = logging.getLogger(__name__)

TEXT_MAX = 500
MARGIN = timedelta(minutes=1)  # deadlines this soon after `until` move too (§16.12)
AGENTS_MAX = 200
MODES = ("accept_all", "refuse_all", "accept_only", "refuse_for")
CACHE_SECONDS = 5.0  # how long one replica trusts its last read of the window


def _process_monotonic() -> float:
    return time.monotonic()


# The cache's clock; tests hold it still, so a slow runner does not re-read the window mid-test.
monotonic: Callable[[], float] = _process_monotonic

_lock = threading.Lock()
_cached: tuple[float, dict[str, Any] | None] | None = None


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def current(conn: Connection) -> Any:
    """The window that is active or upcoming now, or None. One the clock has passed but whose
    deadlines are not moved yet is settled first, in this transaction."""
    now = clock.now()
    settle(conn, now)
    return conn.execute(
        select(t.maintenance_window).where(
            t.maintenance_window.c.cancelled_at.is_(None),
            t.maintenance_window.c.ends_at > now,
        )
    ).first()


def state(row: Any, now: datetime | None = None) -> str:
    return "running" if row.starts_at <= (now or clock.now()) else "upcoming"


def view(row: Any | None, *, admin: bool = False) -> dict[str, Any] | None:
    """`{from, until, text, state}` of a window, for `GET /maintenance`, `/me` and the packet;
    the admin's read adds who set it and when."""
    if row is None:
        return None
    found: dict[str, Any] = {
        "from": clock.rfc3339(row.starts_at),
        "until": clock.rfc3339(row.ends_at),
        "text": row.text,
        "state": state(row),
    }
    if admin:
        found |= {
            "by": row.updated_by,
            "created_at": clock.rfc3339(row.created_at),
            "updated_at": clock.rfc3339(row.updated_at),
        }
    return found


def window_now(engine: Engine) -> dict[str, Any] | None:
    """The view of the current window, read at most every few seconds per process: what the
    middleware asks on every request. `forget` drops it after a change on this replica."""
    global _cached
    with _lock:
        if _cached is not None and monotonic() - _cached[0] < CACHE_SECONDS:
            found = _cached[1]
            # The clock may pass `from` inside the cache's few seconds; past `until` the
            # window is read again, so the deadlines are settled before a sweep acts on them.
            if found is None or _parse(found["until"]) > clock.now():
                return _refreshed(found)
    with engine.begin() as conn:
        found = view(current(conn))
    with _lock:
        _cached = (monotonic(), found)
    return found


def _refreshed(found: dict[str, Any] | None) -> dict[str, Any] | None:
    if found is None:
        return None
    now = clock.now()
    if found["state"] == "upcoming" and _parse(found["from"]) <= now:
        return {**found, "state": "running"}
    return found


def forget() -> None:
    """Drop this replica's cached window (after a change, and in tests)."""
    global _cached
    with _lock:
        _cached = None


def running_now(engine: Engine) -> bool:
    """Whether a window runs: the sweeps that decide on deadlines wait then (§16.12)."""
    found = window_now(engine)
    return found is not None and found["state"] == "running"


PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width"><meta name="robots" '
    'content="noindex"><title>Maintenance</title>{style}</head><body><main><h1>Maintenance</h1>'
    "<p>Back at {until} UTC.</p><p>{text}</p></main>{product}</body></html>"
)


# The frame of the 503 page (§16.7.5, §16.12): the last one read, kept per process. A request
# never reads it itself, so the page that says the hub is down never waits for the database it
# protects (a used-up pool would hold it up to the pool's timeout); a stale or missing frame is
# read again in one thread of its own, and the page is the small one until a frame is there.
FRAME_SECONDS = 60.0  # a kept frame this old is read again
FRAME_MAX_SECONDS = 120.0  # a kept frame this old is no longer served: the small page instead
RETRY_SECONDS = 10.0  # after a failed read, the next one waits this long: no log storm
_frame: tuple[float, dict[str, Any]] | None = None
_frame_reading = False
_frame_failed: float | None = None  # when the last read failed


def cached_frame(engine: Engine) -> dict[str, Any] | None:
    """The last frame read while it is younger than `FRAME_MAX_SECONDS`, else None (the small
    page); starts one read in the background when it is missing or older than `FRAME_SECONDS`.
    Touches no database in the caller. At most one read runs at a time, in a daemon thread that
    ends with the read; after a failed one the next waits `RETRY_SECONDS`, so a database that
    keeps failing costs one read and one warning per 10 s, and its last frame goes once it is two
    minutes old."""
    global _frame_reading
    with _lock:
        held = _frame
        now = monotonic()
        stale = held is None or now - held[0] >= FRAME_SECONDS
        resting = _frame_failed is not None and now - _frame_failed < RETRY_SECONDS
        start = stale and not resting and not _frame_reading
        if start:
            _frame_reading = True
    if start:
        _in_background(refresh_frame, engine)
    return held[1] if held is not None and now - held[0] < FRAME_MAX_SECONDS else None


def _in_background(read: Callable[[Engine], None], engine: Engine) -> None:
    """One daemon thread for one read; it ends with the read (tests run it in place)."""
    threading.Thread(target=read, args=(engine,), name="maintenance-frame", daemon=True).start()


def refresh_frame(engine: Engine) -> None:
    """Read the frame and keep it; on any failure keep the last one (the page falls back)."""
    global _frame, _frame_reading, _frame_failed
    found: dict[str, Any] | None = None
    try:
        found = frame_of(engine)
    except Exception:  # noqa: BLE001 - a failed read only means the small page
        log.warning(
            "the maintenance page's frame could not be read; the last one is served until it is"
            " two minutes old, then the small page"
        )
    with _lock:
        if found is not None:
            _frame = (monotonic(), found)
            _frame_failed = None
        else:
            _frame_failed = monotonic()
        _frame_reading = False


def forget_frame() -> None:
    """Drop the kept frame (in tests)."""
    global _frame, _frame_reading, _frame_failed
    with _lock:
        _frame = None
        _frame_reading = False
        _frame_failed = None


def frame_of(engine: Engine) -> dict[str, Any]:
    """What the frame of the pages without a session is drawn from (§16.7.5): the landing
    setting, the legal pages served and the counters its sections name."""
    from maity_hub import landing, landing_stats, legal

    with engine.begin() as conn:
        setting = landing.stored(conn)
        return {
            "setting": setting,
            "legal": legal.public(legal.stored(conn)),
            "stats": landing_stats.for_frame(conn, setting),
        }


def refusal_page(
    found: dict[str, Any],
    frame: dict[str, Any] | None = None,
    accept_language: str | None = None,
) -> Any:
    """The `503` page of the hub's own pages while a window runs (§16.12): in the landing page's
    header and footer around the door (§16.7.5) where `frame` could be read, else the small page
    with the product line, so it never depends on more than the window it reports."""
    from html import escape

    from starlette.responses import HTMLResponse

    from maity_hub import product_line, render

    headers = {"Retry-After": str(retry_after(found))}
    if frame is not None:
        content = (
            "<h1>Maintenance</h1>"
            f'<p class="intro">Back at {escape(found["until"])} UTC.</p>'
            f"<p>{escape(found['text'])}</p>"
        )
        page = render.door_document(
            lang="en",
            title="Maintenance",
            content=content,
            setting=frame["setting"],
            legal=frame["legal"],
            stats=frame["stats"],
            accept_language=accept_language,
        )
        # It also answers the paths with a token in them (`/join/…`, `/mail/…`): no referrer.
        door = {"Content-Security-Policy": render.DOOR_CSP, "Referrer-Policy": "no-referrer"}
        return HTMLResponse(page, status_code=503, headers={**headers, **door})
    page = PAGE.format(
        until=escape(found["until"]),
        text=escape(found["text"]),
        style=product_line.HEAD,
        product=product_line.html("en"),
    )
    return HTMLResponse(page, status_code=503, headers={**headers, **product_line.HEADERS})


def retry_after(found: dict[str, Any]) -> int:
    """Seconds until the window's `until`, at least 1."""
    left = (_parse(found["until"]) - clock.now()).total_seconds()
    return max(1, math.ceil(left))


# --- the banner of the hub's own pages -----------------------------------------------------

BANNER_STYLE = (
    "margin:0;padding:.6em 1em;background:#fff4ce;color:#3d2e00;border-bottom:1px solid #e0c060;"
    "font:15px/1.4 system-ui,sans-serif;text-align:center"
)


def _utc(stamp: str) -> str:
    """`2026-11-02 13:30` from an RFC 3339 UTC timestamp."""
    return _parse(stamp).strftime("%Y-%m-%d %H:%M")


def banner(found: dict[str, Any] | None) -> str:
    """The line the hub's own pages carry while a window exists (§16.12), in UTC: the server
    does not know the reader's time zone. Empty without one. While it runs only the legal
    pages are served with it; the other pages answer the small 503 page."""
    if found is None:
        return ""
    line = f"Maintenance {_utc(found['from'])}–{_utc(found['until'])} UTC: {found['text']}"
    return f'<p class="maintenance-banner" role="status" style="{BANNER_STYLE}">{escape(line)}</p>'


def with_banner(html: str, found: dict[str, Any] | None) -> str:
    """`html` with the banner as the first thing in its `<body>`; unchanged without one."""
    line = banner(found)
    if not line:
        return html
    start = html.find("<body")
    end = html.find(">", start) if start >= 0 else -1
    if end < 0:
        return html
    return html[: end + 1] + line + html[end + 1 :]


def etag(tag: str, found: dict[str, Any] | None) -> str:
    """A stored page's `ETag` with the banner it is served with: a reader whose cache holds
    the page without the banner (or with an older window) gets the page again, not a 304."""
    line = banner(found)
    if not line:
        return tag
    return '"' + hashlib.sha256((tag + line).encode("utf-8")).hexdigest() + '"'


# --- changes by the instance admin -------------------------------------------------------


def _record(conn: Connection, row: Any, action: str, by: str, now: datetime) -> None:
    conn.execute(
        t.maintenance_change.insert().values(
            id=new_id("maintenance_change"),
            window_id=row.id,
            action=action,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            text=row.text,
            by=by,
            at=now,
        )
    )


def put(conn: Connection, starts_at: datetime, ends_at: datetime, text: str, by: str) -> Any:
    """Create the window, or change the active or upcoming one; returns the row. The caller
    has checked the fields (`check`)."""
    now = clock.now()
    row = current(conn)
    if row is None:
        window_id = new_id("maintenance_window")
        conn.execute(
            t.maintenance_window.insert().values(
                id=window_id,
                starts_at=starts_at,
                ends_at=ends_at,
                text=text,
                created_by=by,
                created_at=now,
                updated_by=by,
                updated_at=now,
            )
        )
        action = "created"
    else:
        window_id = row.id
        conn.execute(
            update(t.maintenance_window)
            .where(t.maintenance_window.c.id == window_id)
            .values(starts_at=starts_at, ends_at=ends_at, text=text, updated_by=by, updated_at=now)
        )
        action = "changed"
    saved = conn.execute(
        select(t.maintenance_window).where(t.maintenance_window.c.id == window_id)
    ).one()
    _record(conn, saved, action, by, now)
    broadcast(conn, "maintenance_scheduled", saved, by)
    forget()
    return saved


def cancel(conn: Connection, row: Any, by: str) -> None:
    """Withdraw an upcoming window."""
    now = clock.now()
    conn.execute(
        update(t.maintenance_window)
        .where(t.maintenance_window.c.id == row.id)
        .values(cancelled_at=now, updated_by=by, updated_at=now)
    )
    _record(conn, row, "cancelled", by, now)
    broadcast(conn, "maintenance_cancelled", row, by)
    forget()


def end(conn: Connection, row: Any, by: str) -> None:
    """End a running window now: its `until` becomes now, and the deadlines move at once."""
    now = clock.now()
    conn.execute(
        update(t.maintenance_window)
        .where(t.maintenance_window.c.id == row.id)
        .values(ends_at=now, updated_by=by, updated_at=now)
    )
    ended = conn.execute(
        select(t.maintenance_window).where(t.maintenance_window.c.id == row.id)
    ).one()
    _record(conn, ended, "ended", by, now)
    settle(conn, now)
    forget()


def check(fields: dict[str, Any], running: Any | None) -> dict[str, str]:
    """The field errors of a `PUT` (§16.12): `from` before `until`, `until` in the future,
    the text 1–500 characters; a running window keeps its `from`."""
    errors: dict[str, str] = {}
    starts_at, ends_at, text = fields["from"], fields["until"], fields["text"]
    if not text:
        errors["text"] = "too_short"
    elif len(text) > TEXT_MAX:
        errors["text"] = "too_long"
    if ends_at <= clock.now():
        errors["until"] = "until_past"
    if starts_at >= ends_at:
        errors["from"] = "from_after_until"
    if running is not None and state(running) == "running" and starts_at != running.starts_at:
        errors["from"] = "running"
    return errors


# --- the deadlines that fell into a window --------------------------------------------------


def settle(conn: Connection, now: datetime) -> None:
    """Move the deadlines that fell into each window that is over and not yet settled, by the
    window's length, once (a conditional update claims the window, so two replicas do not
    both move them)."""
    over = conn.execute(
        select(t.maintenance_window).where(
            t.maintenance_window.c.cancelled_at.is_(None),
            t.maintenance_window.c.settled_at.is_(None),
            t.maintenance_window.c.ends_at <= now,
        )
    ).all()
    for row in over:
        claimed = conn.execute(
            update(t.maintenance_window)
            .where(
                t.maintenance_window.c.id == row.id,
                t.maintenance_window.c.settled_at.is_(None),
            )
            .values(settled_at=now)
        ).rowcount
        if claimed:
            shift(conn, row.starts_at, row.ends_at)


def _inside(column: Any, starts_at: datetime, ends_at: datetime) -> Any:
    return and_(column.is_not(None), column > starts_at, column <= ends_at + MARGIN)


def shift(conn: Connection, starts_at: datetime, ends_at: datetime) -> None:
    """Every deadline the hub acts on by itself, to someone's disadvantage, that fell into the
    window or the minute after it, `(starts_at, ends_at + 1 min]`, moves by the window's length
    (§16.12): a claim's lease, an open jour fixe round's answers, report and steps'
    `closes_at`, a substitution's grace (by the outage's start), an unconfirmed KTW
    `acknowledge_by`, an open takeover's objection window, open project and organisation
    invitations, accounts waiting for approval, and a held address change. Sessions, tokens,
    codes and sign-in links keep their expiry, and so do limits and absences a person set."""
    length = ends_at - starts_at

    def move(table: Any, column: Any, *where: Any) -> None:
        # Row by row: date arithmetic in SQL differs between SQLite, PostgreSQL and MariaDB,
        # and a window touches few rows.
        keys = list(table.primary_key.columns)
        found = conn.execute(
            select(*keys, column).where(_inside(column, starts_at, ends_at), *where)
        ).all()
        for row in found:
            conn.execute(
                update(table)
                .where(*(key == row._mapping[key] for key in keys))
                .values({column.name: row._mapping[column] + length})
            )

    move(t.card, t.card.c.lease_until)
    credential = t.credential.c
    move(
        t.credential,
        credential.ktw_acknowledge_by,
        credential.revoked_at.is_(None),
        credential.ktw_acknowledged_at.is_(None),
    )
    move(t.takeover, t.takeover.c.window_ends_at, t.takeover.c.status == "open")
    invitation = t.invitation.c
    move(
        t.invitation,
        invitation.expires_at,
        invitation.used_at.is_(None),
        invitation.revoked_at.is_(None),
        invitation.voided_at.is_(None),
        invitation.declined_at.is_(None),
    )
    move(t.org_invitation, t.org_invitation.c.expires_at, t.org_invitation.c.closed_at.is_(None))
    move(
        t.account_registration,
        t.account_registration.c.expires_at,
        t.account_registration.c.status == "pending",
    )
    rounds = t.jour_fixe_round.c
    move(t.jour_fixe_round, rounds.answers_close_at, rounds.status == "answering")
    move(t.jour_fixe_round, rounds.report_due_at, rounds.status == "reporting")
    open_rounds = conn.execute(
        select(rounds.id, rounds.steps).where(
            rounds.reported_at.is_(None), rounds.steps.is_not(None)
        )
    ).all()
    for found in open_rounds:
        steps = _shifted_steps(found.steps, starts_at, ends_at, length)
        if steps is not None:
            conn.execute(update(t.jour_fixe_round).where(rounds.id == found.id).values(steps=steps))
    _shift_held_changes(conn, starts_at, ends_at, length)
    _shift_outages(conn, starts_at, ends_at, length)


def _shift_outages(
    conn: Connection, starts_at: datetime, ends_at: datetime, length: timedelta
) -> None:
    """A substitution's grace runs from the start of an outage (§6.12); when its end falls into
    the window and the policy has not acted yet, the outage's start moves, so the grace ends
    that much later."""
    from maity_hub.availability import policy_of

    member = t.membership.c
    found = conn.execute(
        select(t.membership).where(
            member.active.is_(True), member.outage_since.is_not(None), member.cover_state.is_(None)
        )
    ).all()
    for row in found:
        due = row.outage_since + timedelta(minutes=policy_of(row)["grace_minutes"])
        if starts_at < due <= ends_at + MARGIN:
            conn.execute(
                update(t.membership)
                .where(member.id == row.id)
                .values(outage_since=row.outage_since + length)
            )


def _shift_held_changes(
    conn: Connection, starts_at: datetime, ends_at: datetime, length: timedelta
) -> None:
    """A held address change lapses `HELD_FOR` after `requested_at`; when that falls into the
    window, `requested_at` moves, so the change lapses that much later."""
    from maity_hub.notifications.preferences import HELD_FOR

    settings = t.notification_settings.c
    held = conn.execute(
        select(settings.human_id, settings.address_change).where(
            settings.address_change.is_not(None)
        )
    ).all()
    for found in held:
        change = found.address_change
        if not isinstance(change, dict) or not isinstance(change.get("requested_at"), str):
            continue
        requested = _parse(change["requested_at"])
        if starts_at < requested + HELD_FOR <= ends_at + MARGIN:
            moved = {**change, "requested_at": clock.rfc3339(requested + length)}
            conn.execute(
                update(t.notification_settings)
                .where(settings.human_id == found.human_id)
                .values(address_change=moved)
            )


def _shifted_steps(
    steps: Any, starts_at: datetime, ends_at: datetime, length: timedelta
) -> list[Any] | None:
    """The round's steps with each `closes_at` inside the window moved, or None when none is."""
    if not isinstance(steps, list):
        return None
    moved = False
    out: list[Any] = []
    for step in steps:
        live = isinstance(step, dict) and step.get("closed_at") is None
        closes = step.get("closes_at") if live else None
        if isinstance(closes, str):
            at = _parse(closes)
            if starts_at < at <= ends_at + MARGIN:
                step = {**step, "closes_at": clock.rfc3339(at + length)}
                moved = True
        out.append(step)
    return out if moved else None


# --- the broadcast and each owner's choice --------------------------------------------------


def choice(value: Any) -> dict[str, Any]:
    """An owner's stored `broadcasts` choice as `{mode, agents}`; never set is `accept_all`."""
    if isinstance(value, dict) and value.get("mode") in MODES:
        return {"mode": value["mode"], "agents": list(value.get("agents") or [])}
    return {"mode": "accept_all", "agents": []}


def accepts(choice: Any, agent_id: str) -> bool:
    """Whether an owner's `broadcasts` choice lets the hub's broadcast reach `agent_id`."""
    if not isinstance(choice, dict):
        return True  # never set: accept_all
    mode, listed = choice.get("mode", "accept_all"), set(choice.get("agents") or [])
    if mode == "refuse_all":
        return False
    if mode == "accept_only":
        return agent_id in listed
    if mode == "refuse_for":
        return agent_id not in listed
    return True


def broadcast(conn: Connection, kind: str, row: Any, by: str) -> None:
    """One event per project with at least one agent member whose owner accepts, addressed to
    those agents alone (§16.12, §8.2). No hub-wide stream exists."""
    members = conn.execute(
        select(t.membership.c.id, t.membership.c.project_id, t.membership.c.agent_id)
        .where(t.membership.c.active.is_(True), t.membership.c.agent_id.is_not(None))
        .order_by(t.membership.c.project_id, t.membership.c.id)
    ).all()
    owners = dict(
        conn.execute(
            select(t.agent_profile.c.id, t.agent_profile.c.owner_id).where(
                t.agent_profile.c.id.in_({m.agent_id for m in members})
            )
        ).all()
    )
    choices = dict(
        conn.execute(
            select(t.human.c.id, t.human.c.broadcasts).where(t.human.c.id.in_(set(owners.values())))
        ).all()
    )
    audience: dict[str, list[str]] = {}
    for m in members:
        if accepts(choices.get(owners.get(m.agent_id)), m.agent_id):
            audience.setdefault(m.project_id, []).append(f"member:{m.agent_id}")
    payload = {
        "window": {
            "from": clock.rfc3339(row.starts_at),
            "until": clock.rfc3339(row.ends_at),
            "text": row.text,
        },
        "by": by,
    }
    for project_id, tokens in audience.items():
        events.emit(conn, project_id, kind, tokens, payload, actor=events.Actor(None, human_id=by))


def check_choice(body: dict[str, Any], own_agents: Iterable[str]) -> dict[str, str]:
    """The field errors of `PATCH /me/broadcasts`."""
    errors: dict[str, str] = {}
    mode, agents = body.get("mode"), body.get("agents") or []
    if mode not in MODES:
        errors["mode"] = "invalid"
    if not isinstance(agents, list) or not all(isinstance(a, str) for a in agents):
        errors["agents"] = "invalid"
        return errors
    if len(agents) > AGENTS_MAX:
        errors["agents"] = "too_many"
    elif mode in ("accept_all", "refuse_all") and agents:
        errors["agents"] = "not_allowed"
    elif set(agents) - set(own_agents):
        errors["agents"] = "not_your_agent"
    return errors
