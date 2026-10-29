"""Abuse reports (docs/api.md §16.8): anyone signed in reports a profile, a project, a
message or a card they can read; the instance admin reads the report with its copy of the
target and resolves it.

A target the reporter cannot read is `not_found`, exactly as reading it would answer, so a
report never tells anyone that something exists. The copy (`snapshot`) holds text and
fields only, as the reporter could read them at that moment; it lives while the report is
open, at most 90 days, and is emptied 90 days after the report closed.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, func, insert, select, update

from maity_hub import clock, events, namespace
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.admin import instance_admin_id
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError, invalid, not_found, rate_limited
from maity_hub.ids import new_id
from maity_hub.notifications import records
from maity_hub.views import principal_id, ts

TYPES = ("profile", "project", "message", "card")
REASONS = ("spam", "abuse", "illegal", "prompt_injection", "impersonation", "other")
ACTIONS = ("dismiss", "hide", "remove", "suspend")
TEXT_MAX = 2048  # bytes, UTF-8 (§16.8)
PER_DAY, DAY = 20, timedelta(hours=24)  # reports per account
PER_TARGET = 3  # reports of one target per account
OPEN_FOR = timedelta(days=90)  # an open report then expires
KEPT_AFTER = timedelta(days=90)  # its content is emptied this long after it closed
INTERVAL = 3600.0  # seconds between retention sweeps

log = logging.getLogger(__name__)


def account_of(conn: Connection, caller: Caller) -> str:
    """The reporting account: a human itself, an agent's owner (§16.8 "per account")."""
    if caller.kind != "agent":
        return str(caller.human_id)
    owner: str = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == caller.principal_id)
    ).scalar_one()
    return owner


# --- the target, as the reporter can read it ------------------------------------------------


def _handle(conn: Connection, principal: str | None) -> str | None:
    if principal is None:
        return None
    if principal.startswith("agt-"):
        found = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == principal)
        ).scalar()
    else:
        found = conn.execute(select(t.human.c.handle).where(t.human.c.id == principal)).scalar()
    return str(found) if found is not None else None


def _author(conn: Connection, principal: str | None) -> dict[str, Any]:
    return {"id": principal, "handle": _handle(conn, principal)}


def _member(conn: Connection, caller: Caller, project: str | None) -> Membership:
    """The reporter's membership in the target's project, as a read takes it: `not_found`
    for a project it is not in, or one it cannot read."""
    if not isinstance(project, str) or not project:
        raise invalid({"target.project": "required"})
    mine = membership(conn, caller, project)
    if not mine.may("project:read"):
        raise not_found()
    return mine


def _shares_a_project(conn: Connection, caller: Caller, principal: str) -> bool:
    """Whether the reporter reads `principal`'s member view somewhere: an active
    membership of both in one project. An agent credential reaches its own project only."""
    m = t.membership.c
    theirs = select(m.project_id).where(
        m.active.is_(True), (m.agent_id == principal) | (m.human_id == principal)
    )
    if caller.kind == "agent":
        mine = select(m.project_id).where(m.id == caller.membership_id, m.active.is_(True))
    else:
        mine = select(m.project_id).where(m.human_id == caller.human_id, m.active.is_(True))
    return (
        conn.execute(
            select(m.project_id).where(m.project_id.in_(mine), m.project_id.in_(theirs))
        ).first()
        is not None
    )


def _profile(conn: Connection, caller: Caller, profile_id: str) -> dict[str, Any]:
    if profile_id.startswith("agt-"):
        row = conn.execute(
            select(t.agent_profile).where(
                t.agent_profile.c.id == profile_id, t.agent_profile.c.deleted_at.is_(None)
            )
        ).first()
        if row is None:
            raise not_found()
        own = caller.kind != "agent" and row.owner_id == caller.human_id
        if not (
            own or profile_id == caller.principal_id or _shares_a_project(conn, caller, profile_id)
        ):
            raise not_found()
        return {
            "type": "profile",
            "kind": "agent",
            "handle": row.handle,
            "display_name": row.display_name,
            "owner": _author(conn, row.owner_id),
            "author": _author(conn, profile_id),
        }
    if profile_id.startswith("hum-"):
        human = conn.execute(
            select(t.human).where(t.human.c.id == profile_id, t.human.c.deleted_at.is_(None))
        ).first()
        if human is None:
            raise not_found()
        if not (profile_id == caller.principal_id or _shares_a_project(conn, caller, profile_id)):
            raise not_found()
        return {
            "type": "profile",
            "kind": "human",
            "handle": human.handle,
            "display_name": human.display_name,
            "author": _author(conn, profile_id),
        }
    raise not_found()


def _project(conn: Connection, caller: Caller, full_name: str) -> tuple[str, dict[str, Any]]:
    mine = _member(conn, caller, full_name)
    project = mine.project
    owner = namespace.owner_of(conn, project)
    return project.id, {
        "type": "project",
        "full_name": namespace.full_name(conn, project),
        "name": project.name,
        "repository_url": project.repository_url,
        "author": {"id": owner["id"], "handle": owner["handle"]},
    }


def _card(
    conn: Connection, caller: Caller, card_id: str, project: str | None
) -> tuple[str, dict[str, Any]]:
    mine = _member(conn, caller, project)
    card = conn.execute(
        select(t.card).where(t.card.c.id == card_id, t.card.c.project_id == mine.project.id)
    ).first()
    if card is None:
        raise not_found()
    return mine.project.id, {
        "type": "card",
        "project": namespace.full_name(conn, mine.project),
        "kind": card.kind,
        "title": card.title,
        "body": card.body,
        "author": _author(conn, principal_id(conn, card.created_by)),
    }


def _seq(value: str) -> int:
    """An event seq, as a number or as the message id `evt-<seq>` the inbox shows."""
    text = value.removeprefix("evt-")
    if not text.isdigit():
        raise not_found()
    return int(text)


def _message(
    conn: Connection, caller: Caller, message_id: str, project: str | None
) -> tuple[str, dict[str, Any]]:
    mine = _member(conn, caller, project)
    row = conn.execute(
        select(t.event).where(
            t.event.c.seq == _seq(message_id),
            t.event.c.project_id == mine.project.id,
            t.event.c.kind == "message",
        )
    ).first()
    if row is None:
        raise not_found()
    hidden = events.hidden_redactions(conn, [row], mine.row)
    if not events.readable_by(row, mine.row, mine.principal_id, hidden):
        raise not_found()
    payload = row.payload or {}
    return mine.project.id, {
        "type": "message",
        "project": namespace.full_name(conn, mine.project),
        "seq": row.seq,
        "conversation_id": row.conversation_id,
        "at": ts(row.at),
        "body": None if row.redacted else payload.get("body"),
        "redacted": bool(row.redacted),
        "author": _author(conn, principal_id(conn, row.actor_membership)),
    }


def target(
    conn: Connection, caller: Caller, given: dict[str, Any]
) -> tuple[str, str, str | None, dict[str, Any]]:
    """(type, id, project id, snapshot) of what the caller reports, read as the caller may
    read it; `not_found` for anything it cannot read."""
    kind, target_id = given.get("type"), given.get("id")
    if kind not in TYPES:
        raise invalid({"target.type": "unknown"})
    if not isinstance(target_id, str) or not target_id or len(target_id) > 255:
        raise invalid({"target.id": "required"})
    project = given.get("project")
    if kind == "profile":
        return kind, target_id, None, _profile(conn, caller, target_id)
    if kind == "project":
        project_id, shot = _project(conn, caller, target_id)
        return kind, shot["full_name"], project_id, shot
    if kind == "card":
        project_id, shot = _card(conn, caller, target_id, project)
        return kind, target_id, project_id, shot
    project_id, shot = _message(conn, caller, target_id, project)
    return kind, str(shot["seq"]), project_id, shot


# --- filing a report ------------------------------------------------------------------------


def _limit(conn: Connection, account: str, kind: str, target_id: str, now: datetime) -> None:
    """20 per account per 24 hours, 3 per target per account (§16.8), counted from the
    stored reports under the account's row lock, so two at once cannot both pass."""
    conn.execute(select(t.human.c.id).where(t.human.c.id == account).with_for_update())
    r = t.abuse_report.c
    recent = (
        conn.execute(
            select(r.created_at)
            .where(r.account_id == account, r.created_at > now - DAY)
            .order_by(r.created_at)
        )
        .scalars()
        .all()
    )
    if len(recent) >= PER_DAY:
        oldest = recent[len(recent) - PER_DAY]
        raise rate_limited(max(1, int((oldest + DAY - now).total_seconds())))
    same = conn.execute(
        select(func.count()).where(
            r.account_id == account, r.target_type == kind, r.target_id == target_id
        )
    ).scalar_one()
    if same >= PER_TARGET:
        raise rate_limited(int(DAY.total_seconds()))


def create(conn: Connection, caller: Caller, body: dict[str, Any]) -> dict[str, Any]:
    """File a report and the instance admin's `report_open` inbox item; `{id, created_at}`."""
    reason, text = body.get("reason"), body.get("text")
    if reason not in REASONS:
        raise invalid({"reason": "unknown"})
    if text is not None and (not isinstance(text, str) or len(text.encode()) > TEXT_MAX):
        raise invalid({"text": "too_long" if isinstance(text, str) else "not_text"})
    given = body.get("target")
    if not isinstance(given, dict):
        raise invalid({"target": "required"})
    kind, target_id, project_id, snapshot = target(conn, caller, given)
    account = account_of(conn, caller)
    now = clock.now()
    _limit(conn, account, kind, target_id, now)
    report_id = new_id("abuse_report")
    conn.execute(
        insert(t.abuse_report).values(
            id=report_id,
            reporter=caller.principal_id,
            account_id=account,
            target_type=kind,
            target_id=target_id,
            project_id=project_id,
            reason=reason,
            text=text,
            snapshot=snapshot,
            status="open",
            created_at=now,
        )
    )
    admin = instance_admin_id(conn)
    if admin is not None:
        # The instance admin's `inbox` item, open while the report is (§16.8, §18.1):
        # ids and kinds only, never the content.
        records.write(
            conn, admin, "report_open", {"report": report_id, "reason": reason, "type": kind}
        )
    return {"id": report_id, "created_at": ts(now)}


# --- views ----------------------------------------------------------------------------------


def _target_view(row: Any, conn: Connection) -> dict[str, Any]:
    shown: dict[str, Any] = {"type": row.target_type, "id": row.target_id}
    if row.target_type in ("message", "card") and row.project_id is not None:
        shown["project"] = namespace.full_names(conn, [row.project_id]).get(row.project_id)
    return shown


def own_view(conn: Connection, row: Any) -> dict[str, Any]:
    """The reporter's view: status and action only (§16.8), never the note."""
    return {
        "id": row.id,
        "created_at": ts(row.created_at),
        "target": _target_view(row, conn),
        "reason": row.reason,
        "status": row.status,
        "action": row.action,
    }


def admin_view(conn: Connection, row: Any, *, snapshot: bool) -> dict[str, Any]:
    shown = {
        **own_view(conn, row),
        "reporter": {"id": row.reporter, "handle": _handle(conn, row.reporter)},
        "text": row.text,
        "note": row.note,
        "resolved_at": ts(row.resolved_at),
        "closed_at": ts(row.closed_at),
    }
    if snapshot:
        shown["snapshot"] = row.snapshot
    return shown


# --- resolving ------------------------------------------------------------------------------


def resolve(
    conn: Connection, admin_id: str, report_id: str, action: Any, note: Any
) -> dict[str, Any]:
    """Resolve the report, or replace the action of a resolved one (§16.8). Only `dismiss`
    exists yet; `hide`, `remove` and `suspend` come with the moderation actions."""
    if action not in ACTIONS:
        raise invalid({"action": "unknown"})
    if action != "dismiss":
        raise invalid({"action": "not_available"}, "only dismiss is available yet")
    if note is not None and not isinstance(note, str):
        raise invalid({"note": "not_text"})
    expire(conn)
    row = conn.execute(
        select(t.abuse_report).where(t.abuse_report.c.id == report_id).with_for_update()
    ).first()
    if row is None:
        raise not_found()
    if row.status == "expired":
        raise ApiError(
            409, "invalid_transition", "the report expired", {"from": "expired", "to": "resolved"}
        )
    now = clock.now()
    conn.execute(
        update(t.abuse_report)
        .where(t.abuse_report.c.id == report_id)
        .values(
            status="resolved",
            action=action,
            note=note,
            resolved_by=admin_id,
            resolved_at=now,
            closed_at=row.closed_at if row.status == "resolved" else now,
        )
    )
    found = conn.execute(select(t.abuse_report).where(t.abuse_report.c.id == report_id)).one()
    return admin_view(conn, found, snapshot=True)


# --- retention ------------------------------------------------------------------------------


def expire(conn: Connection) -> None:
    """Close what stayed open 90 days as `expired`, with no action, and empty the content of
    what closed 90 days ago (§16.8). Rows stay as the record."""
    now = clock.now()
    r = t.abuse_report.c
    conn.execute(
        update(t.abuse_report)
        .where(r.status == "open", r.created_at <= now - OPEN_FOR)
        .values(status="expired", closed_at=now)
    )
    conn.execute(
        update(t.abuse_report)
        .where(r.closed_at.isnot(None), r.closed_at <= now - KEPT_AFTER, r.purged_at.is_(None))
        .values(snapshot=None, text=None, note=None, purged_at=now)
    )


class Worker:
    """Runs `expire` in the background, so retention holds whether anyone looks or not."""

    def __init__(self, engine: Engine, interval: float | None = None) -> None:
        self.engine = engine
        self.interval = INTERVAL if interval is None else interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-reports", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                with self.engine.begin() as conn:
                    expire(conn)
            except Exception:
                log.exception("the abuse report retention sweep failed")
