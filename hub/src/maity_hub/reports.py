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

from maity_hub import (
    attachment_store,
    clock,
    events,
    moderation,
    namespace,
    public_people,
    worker_runs,
)
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.admin import instance_admin_id
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError, invalid, not_found, rate_limited
from maity_hub.forge import Forge
from maity_hub.ids import new_id
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
    if not mine.may("project:read") or namespace.full_name(conn, mine.project) != project:
        # The current name only: a former slug must not confirm whose it was (§16.8).
        raise not_found()
    return mine


# --- what a stranger sees: the pages served now (§16.8, §16.9) ------------------------------


def _page(conn: Connection, pages: bool, path: str, view: str) -> Any:
    """The stored page of `path` with that view while the instance serves pages, else None.
    Its path is the current public name, so a former name finds no page."""
    if not pages:
        return None
    return conn.execute(
        select(t.public_page.c.target_id, t.public_page.c.data).where(
            t.public_page.c.path == path, t.public_page.c.view == view
        )
    ).first()


def _lists(page: Any, path: str) -> bool:
    """Whether a page's `agents` names the agent whose own page is `path`."""
    data = (page.data or {}) if page is not None else {}
    return any(isinstance(a, dict) and a.get("page") == path for a in data.get("agents") or [])


def _agent_shown(conn: Connection, pages: bool, agent: Any, owner: str) -> bool:
    """Whether a page served now shows the agent: its own page, its owner's agents page, or
    the page of a project it is named on (§16.8)."""
    path = f"/{owner}/agents/{agent.handle}"
    if _page(conn, pages, path, "agent") is not None:
        return True
    if _lists(_page(conn, pages, f"/{owner}/agents", public_people.AGENTS_VIEW), path):
        return True
    m = t.membership.c
    projects = conn.execute(
        select(t.project)
        .join(t.membership, m.project_id == t.project.c.id)
        .where(m.agent_id == agent.id, m.active.is_(True))
    ).all()
    return any(
        _lists(_page(conn, pages, f"/{namespace.full_name(conn, p)}", "project"), path)
        for p in projects
    )


def _on_project_page(conn: Connection, pages: bool, handle: str, project: str) -> tuple[str, str]:
    """The agent a served project page lists with this bare handle: `not_found` for none,
    `invalid` (`ambiguous_handle`) for more than one, since a report names one agent."""
    page = _page(conn, pages, f"/{project}", "project")
    if page is None:
        raise not_found()
    listed = [
        a
        for a in (page.data or {}).get("agents") or []
        if isinstance(a, dict) and a.get("handle") == handle
    ]
    if not listed:
        raise not_found()
    if len(listed) > 1:
        raise ApiError(
            400,
            "invalid",
            "the page lists this handle more than once; report from the agent's own page",
            {"reason": "ambiguous_handle"},
        )
    owner, _, rest = str(listed[0].get("page") or "").lstrip("/").partition("/agents/")
    return str(_agent_by_name(conn, f"{owner}/{rest}")[0].id), str(page.target_id)


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


def _agent_by_name(conn: Connection, name: str) -> tuple[Any, str]:
    """An agent's row and its owner's handle from its current global name `<owner>/<handle>`
    (§6.3); `not_found` for none. A former handle of either does not resolve (§16.8)."""
    owner, _, handle = name.partition("/")
    row = conn.execute(
        select(t.agent_profile)
        .join(t.human, t.human.c.id == t.agent_profile.c.owner_id)
        .where(
            t.human.c.handle == owner,
            t.agent_profile.c.handle == handle,
            t.agent_profile.c.deleted_at.is_(None),
        )
    ).first()
    if row is None:
        raise not_found()
    return row, owner


def _agent_shot(conn: Connection, row: Any) -> dict[str, Any]:
    return {
        "type": "profile",
        "id": row.id,
        "kind": "agent",
        "handle": row.handle,
        "display_name": row.display_name,
        "owner": _author(conn, row.owner_id),
        "author": _author(conn, row.id),
    }


def _human_shot(conn: Connection, human: Any) -> dict[str, Any]:
    return {
        "type": "profile",
        "id": human.id,
        "kind": "human",
        "handle": human.handle,
        "display_name": human.display_name,
        "author": _author(conn, human.id),
    }


def _reads_member(conn: Connection, caller: Caller, row: Any) -> bool:
    """Whether the caller reads the agent inside a membership: its owner, itself, or a
    member of a project it is in."""
    own = caller.kind != "agent" and row.owner_id == caller.human_id
    return own or row.id == caller.principal_id or _shares_a_project(conn, caller, row.id)


def _profile(
    conn: Connection, caller: Caller, profile_id: str, project: Any, pages: bool
) -> dict[str, Any]:
    if "/" in profile_id:  # an agent's global name, from a page of its owner or a project
        row, owner = _agent_by_name(conn, profile_id)
        if not (_reads_member(conn, caller, row) or _agent_shown(conn, pages, row, owner)):
            raise not_found()
        return _agent_shot(conn, row)
    if project is not None:  # the bare handle a served project page shows, with its name
        if not isinstance(project, str) or not project:
            raise invalid({"target.project": "required"})
        agent_id, project_id = _on_project_page(conn, pages, profile_id, project)
        row = conn.execute(select(t.agent_profile).where(t.agent_profile.c.id == agent_id)).one()
        # The project it was reported from, so the reporter's list names it the same way.
        return {**_agent_shot(conn, row), "project": project_id}
    if profile_id.startswith("agt-"):  # a member's read only; a stranger has no such id
        row = conn.execute(
            select(t.agent_profile).where(
                t.agent_profile.c.id == profile_id, t.agent_profile.c.deleted_at.is_(None)
            )
        ).first()
        if row is None or not _reads_member(conn, caller, row):
            raise not_found()
        return _agent_shot(conn, row)
    if profile_id.startswith("hum-"):
        human = conn.execute(
            select(t.human).where(t.human.c.id == profile_id, t.human.c.deleted_at.is_(None))
        ).first()
        if human is None:
            raise not_found()
        if not (profile_id == caller.principal_id or _shares_a_project(conn, caller, profile_id)):
            raise not_found()
        return _human_shot(conn, human)
    # A person's current handle, as their page shows it at `/{handle}`.
    human = conn.execute(
        select(t.human).where(t.human.c.handle == profile_id, t.human.c.deleted_at.is_(None))
    ).first()
    if human is None:
        raise not_found()
    if not (
        human.id == caller.principal_id
        or _shares_a_project(conn, caller, human.id)
        or _page(conn, pages, f"/{human.handle}", "person") is not None
    ):
        raise not_found()
    return _human_shot(conn, human)


def _project(
    conn: Connection, caller: Caller, full_name: str, pages: bool
) -> tuple[str, dict[str, Any]]:
    try:
        project = _member(conn, caller, full_name).project
    except ApiError as refused:
        page = _page(conn, pages, f"/{full_name}", "project")
        if refused.code != "not_found" or page is None:
            raise
        project = conn.execute(select(t.project).where(t.project.c.id == page.target_id)).one()
    owner = namespace.owner_of(conn, project)
    return project.id, {
        "type": "project",
        "full_name": namespace.full_name(conn, project),
        "name": project.name,
        "repository_url": project.repository_url,
        "author": {"id": owner["id"], "handle": owner["handle"]},
    }


def _card(
    conn: Connection, caller: Caller, card_id: str, project: str | None, pages: bool
) -> tuple[str, dict[str, Any]]:
    try:
        project_row = _member(conn, caller, project).project
    except ApiError as refused:
        # A stranger reads a card only through its own page (§16.8, §16.9).
        page = _page(conn, pages, f"/{project}/tasks/{card_id}", "card")
        if refused.code != "not_found" or page is None:
            raise
        project_row = conn.execute(
            select(t.project)
            .join(t.card, t.card.c.project_id == t.project.c.id)
            .where(t.card.c.id == page.target_id)
        ).one()
    card = conn.execute(
        select(t.card).where(t.card.c.id == card_id, t.card.c.project_id == project_row.id)
    ).first()
    if card is None:
        raise not_found()
    return project_row.id, {
        "type": "card",
        "project": namespace.full_name(conn, project_row),
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
    conn: Connection, caller: Caller, given: dict[str, Any], pages: bool = False
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
        shot = _profile(conn, caller, target_id, project, pages)
        from_page = shot.pop("project", None)
        return kind, shot["id"], from_page, shot
    if kind == "project":
        # Keyed by its id, not its full name: the limit and the admin's view outlast a
        # rename or a transfer (§6.25).
        project_id, shot = _project(conn, caller, target_id, pages)
        return kind, project_id, project_id, shot
    if kind == "card":
        project_id, shot = _card(conn, caller, target_id, project, pages)
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
        # For good, not for a day: no `Retry-After` that would have a client try again
        # in vain (§16.8).
        raise ApiError(429, "rate_limited", "this target was reported 3 times already")


def create(
    conn: Connection, caller: Caller, body: dict[str, Any], pages: bool = False
) -> dict[str, Any]:
    """File a report and the instance admin's request about it; `{id, created_at}`."""
    reason, text = body.get("reason"), body.get("text")
    if reason not in REASONS:
        raise invalid({"reason": "unknown"})
    if text is not None and (not isinstance(text, str) or len(text.encode()) > TEXT_MAX):
        raise invalid({"text": "too_long" if isinstance(text, str) else "not_text"})
    given = body.get("target")
    if not isinstance(given, dict):
        raise invalid({"target": "required"})
    kind, target_id, project_id, snapshot = target(conn, caller, given, pages)
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
        # The instance admin's personal request, open while the report is (§16.8, §7): ids
        # and kinds only, never the content; mailed by the `inbox` mode through its record.
        from maity_hub import catalog
        from maity_hub.notifications import preferences
        from maity_hub.routes.requests import file_hub_report

        words = catalog.section("notify", preferences.text_language(conn, admin))
        file_hub_report(conn, admin, report_id, words["reported"].format(reason=reason, type=kind))
    return {"id": report_id, "created_at": ts(now)}


# --- views ----------------------------------------------------------------------------------


def _target_view(row: Any, conn: Connection) -> dict[str, Any]:
    """A project by its full name as it is now (§6.25), the rest by its id."""
    shown: dict[str, Any] = {"type": row.target_type, "id": row.target_id}
    if row.project_id is not None:
        name = namespace.full_names(conn, [row.project_id]).get(row.project_id)
        if row.target_type == "project":
            shown["id"] = name
        else:
            shown["project"] = name
    return shown


def _public_target(conn: Connection, row: Any, pages: bool) -> dict[str, Any]:
    """The reporter's form of the target (§16.8 "Limits"): its current public name while its
    page is served now, else `null` with a neutral word; never an account or member id, a
    former name or an alias. A message keeps its seq and the project's name as it is now."""
    if row.target_type == "message":
        return _target_view(row, conn)
    gone = {"type": row.target_type, "id": None, "label": row.target_type}
    full = (
        namespace.full_names(conn, [row.project_id]).get(row.project_id)
        if row.project_id is not None
        else None
    )
    if row.target_type == "project":
        if full and _page(conn, pages, f"/{full}", "project") is not None:
            return {"type": "project", "id": full}
        return gone
    if row.target_type == "card":
        if full and _page(conn, pages, f"/{full}/tasks/{row.target_id}", "card") is not None:
            return {"type": "card", "id": row.target_id, "project": full}
        return gone
    if str(row.target_id).startswith("hum-"):
        human = conn.execute(
            select(t.human).where(t.human.c.id == row.target_id, t.human.c.deleted_at.is_(None))
        ).first()
        if human is not None and _page(conn, pages, f"/{human.handle}", "person") is not None:
            return {"type": "profile", "id": human.handle}
        return {**gone, "label": "person"}
    agent = conn.execute(
        select(t.agent_profile, t.human.c.handle.label("owner_handle"))
        .join(t.human, t.human.c.id == t.agent_profile.c.owner_id)
        .where(t.agent_profile.c.id == row.target_id, t.agent_profile.c.deleted_at.is_(None))
    ).first()
    neutral = {**gone, "label": "agent"}
    if agent is None:
        return neutral
    path = f"/{agent.owner_handle}/agents/{agent.handle}"
    if row.project_id is not None:  # reported by its handle on a project page
        if full and _lists(_page(conn, pages, f"/{full}", "project"), path):
            return {"type": "profile", "id": agent.handle, "project": full}
        return neutral
    if _agent_shown(conn, pages, agent, agent.owner_handle):
        return {"type": "profile", "id": f"{agent.owner_handle}/{agent.handle}"}
    return neutral


def own_view(conn: Connection, row: Any, pages: bool | None = None) -> dict[str, Any]:
    """The reporter's view: status and action only (§16.8), never the note. With `pages`
    (whether the instance serves public pages), the target in the reporter's form."""
    return {
        "id": row.id,
        "created_at": ts(row.created_at),
        "target": _target_view(row, conn) if pages is None else _public_target(conn, row, pages),
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
    conn: Connection,
    admin_id: str,
    report_id: str,
    action: Any,
    note: Any,
    fg: Forge,
    store: attachment_store.BlobStore | None = None,
) -> dict[str, Any]:
    """Resolve the report and make its action's change, or replace the action of a
    resolved one (§16.8): its hold is replaced, `dismiss` lifts it."""
    if action not in ACTIONS:
        raise invalid({"action": "unknown"})
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
    moderation.apply(conn, row, action, note, fg, store)
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
    _withdraw_requests(conn, [report_id], "resolved")
    found = conn.execute(select(t.abuse_report).where(t.abuse_report.c.id == report_id)).one()
    return admin_view(conn, found, snapshot=True)


# --- retention ------------------------------------------------------------------------------


def expire(conn: Connection) -> None:
    """Close what stayed open 90 days as `expired`, with no action, and empty the content of
    what closed 90 days ago (§16.8). Rows stay as the record."""
    now = clock.now()
    r = t.abuse_report.c
    due = r.status == "open", r.created_at <= now - OPEN_FOR
    expiring = list(conn.execute(select(r.id).where(*due)).scalars())
    if expiring:
        conn.execute(
            update(t.abuse_report)
            .where(r.id.in_(expiring), *due)
            .values(status="expired", closed_at=now)
        )
        _withdraw_requests(conn, expiring, "expired")
    conn.execute(
        update(t.abuse_report)
        .where(r.closed_at.isnot(None), r.closed_at <= now - KEPT_AFTER, r.purged_at.is_(None))
        .values(snapshot=None, text=None, note=None, purged_at=now)
    )


def _withdraw_requests(conn: Connection, report_ids: list[str], reason: str) -> None:
    """The instance admin's requests about these reports close with them (§16.8)."""
    from maity_hub.routes.requests import withdraw_report_request

    for report_id in report_ids:
        withdraw_report_request(conn, report_id, reason)


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
                with worker_runs.claim(self.engine, "reports", self.interval) as held:
                    if held is None:
                        continue
                    with self.engine.begin() as conn:
                        expire(conn)
            except Exception:
                log.exception("the abuse report retention sweep failed")
