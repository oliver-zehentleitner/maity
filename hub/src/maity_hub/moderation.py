"""Moderation (docs/api.md §16.8): what resolving an abuse report changes.

The instance admin gets exactly the authority the action needs over exactly the reported
target. The hub makes the change as actor `{kind: "moderation", report_id}` and writes the
event the change would write anyway. `hide` and `remove` leave a hold on the target that
ordinary writes cannot undo; `suspend` stops an account until the operator lifts it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from maity_hub import account_deletion, attachment_store, clock, public_pages, write_guard
from maity_hub import tables as t
from maity_hub.auth import email_links, leaks, sessions
from maity_hub.errors import ApiError, invalid
from maity_hub.events import Actor
from maity_hub.forge import Forge
from maity_hub.notifications import records
from maity_hub.views import principal_id, ts

HOLDING = ("hide", "remove")
ENDED_BY = REVOKED_REASON = "suspended"


def actor(report_id: str) -> Actor:
    return Actor(None, report_id=report_id)


# --- holds ----------------------------------------------------------------------------------


def target_key(report: Any) -> tuple[str, str]:
    """The hold's stable key: a project by its id (a rename changes its full name), a
    message by `<project id>/<seq>`, a card or a profile by its own id."""
    if report.target_type == "project":
        return "project", str(report.project_id)
    if report.target_type == "message":
        return "message", f"{report.project_id}/{report.target_id}"
    return report.target_type, report.target_id


def hold(conn: Connection, target_type: str, target_id: str) -> Any | None:
    """The newest hold on the target, or None."""
    h = t.moderation_hold.c
    return conn.execute(
        select(t.moderation_hold)
        .where(h.target_type == target_type, h.target_id == target_id)
        .order_by(h.at.desc(), h.report_id.desc())
        .limit(1)
    ).first()


def holds_of(conn: Connection, target_type: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    """The newest hold's view per target among `ids` that has one."""
    if not ids:
        return {}
    h = t.moderation_hold.c
    found: dict[str, dict[str, Any]] = {}
    for row in conn.execute(
        select(t.moderation_hold)
        .where(h.target_type == target_type, h.target_id.in_(ids))
        .order_by(h.at, h.report_id)
    ):
        found[row.target_id] = {"action": row.action, "report_id": row.report_id, "at": ts(row.at)}
    return found


def view(row: Any | None) -> dict[str, Any] | None:
    """`moderation` in a held target's view (§16.8)."""
    if row is None:
        return None
    return {"action": row.action, "report_id": row.report_id, "at": ts(row.at)}


def held() -> ApiError:
    return ApiError(
        403,
        "forbidden",
        "a moderation hold stands on this; only an instance admin lifts it",
        {"reason": "moderation_hold"},
    )


def refuse_held(conn: Connection, target_type: str, target_id: str, *actions: str) -> None:
    """`moderation_hold` when a hold of one of `actions` (any, when none is given) stands."""
    found = hold(conn, target_type, target_id)
    if found is not None and (not actions or found.action in actions):
        raise held()


# --- suspension -----------------------------------------------------------------------------


def account_suspended() -> ApiError:
    return ApiError(
        403, "account_suspended", "an instance admin suspended this account; it gets no access"
    )


def suspended(conn: Connection, human_id: str | None) -> bool:
    if human_id is None:
        return False
    at = conn.execute(select(t.human.c.suspended_at).where(t.human.c.id == human_id)).scalar()
    return at is not None


def refuse_suspended(conn: Connection, human_id: str | None) -> None:
    """Refuse an issue to a suspended account. The account lock is taken shared first, as
    every write of the account takes it (§2.9): a suspension in progress holds it
    exclusively, so the issue waits for it and then reads the column committed. Callers
    run this before their other locks, the order the suspension takes them in."""
    if human_id is None:
        return
    write_guard.share(conn, human_id)
    if suspended(conn, human_id):
        raise account_suspended()


def owner_account(conn: Connection, principal: str | None) -> str | None:
    """The account behind a principal: a human itself, an agent's owner."""
    if principal is None:
        return None
    if principal.startswith("agt-"):
        found = conn.execute(
            select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == principal)
        ).scalar()
        return str(found) if found is not None else None
    return principal


def suspension_of(conn: Connection, membership: Any) -> dict[str, Any] | None:
    """A suspended account's membership acts as paused (§16.8, §5.3): the `paused` shape,
    or None."""
    account = owner_account(conn, membership.agent_id or membership.human_id)
    if account is None:
        return None
    at = conn.execute(select(t.human.c.suspended_at).where(t.human.c.id == account)).scalar()
    if at is None:
        return None
    return {"reason": "account suspended", "since": ts(at), "by": None}


def suspensions(conn: Connection, rows: Any, owner_of: dict[str, str]) -> dict[int, dict[str, Any]]:
    """`suspension_of` for several memberships in one query: membership id → `paused`
    shape, for those whose account is suspended. `owner_of` maps their agents to owners."""
    account = {r.id: (owner_of.get(r.agent_id) if r.agent_id else r.human_id) for r in rows}
    wanted = {a for a in account.values() if a is not None}
    if not wanted:
        return {}
    since = dict(
        conn.execute(
            select(t.human.c.id, t.human.c.suspended_at).where(
                t.human.c.id.in_(wanted), t.human.c.suspended_at.isnot(None)
            )
        ).all()
    )
    return {
        membership: {"reason": "account suspended", "since": ts(since[a]), "by": None}
        for membership, a in account.items()
        if a in since
    }


def suspend(conn: Connection, human_id: str, report_id: str) -> None:
    """The account signs in no more, and every session and credential it holds ends at
    once: its agents' credentials and its runners' credentials, so its placements stop.
    The order is a deletion's (§2.9): the account lock first and exclusively, so no issue
    that read the account before this commits hands out a credential after it; then the
    credentials, which lock their projects; the human's own rows last, as project work
    locks the project before the human."""
    account_deletion.lock_account(conn, human_id)
    m, c = t.membership.c, t.credential.c
    agents = select(t.agent_profile.c.id).where(t.agent_profile.c.owner_id == human_id)
    credentials = conn.execute(
        select(c.id)
        .join(t.membership, m.id == c.membership_id)
        .where(c.revoked_at.is_(None), (m.human_id == human_id) | m.agent_id.in_(agents))
        .order_by(c.id)
    ).scalars()
    for credential_id in list(credentials):
        leaks.revoke(conn, credential_id, REVOKED_REASON, None)
    r = t.runner_credential.c
    runner_credentials = conn.execute(
        select(r.id)
        .join(t.runner, t.runner.c.id == r.runner_id)
        .where(t.runner.c.owner_id == human_id, r.revoked_at.is_(None))
        .order_by(r.id)
    ).scalars()
    for credential_id in list(runner_credentials):
        leaks.revoke_runner_credential(conn, credential_id, REVOKED_REASON, None)
    sessions.end_where(conn, t.human_session.c.human_id == human_id, ENDED_BY)
    email_links.void_human(conn, human_id)  # a mailed sign-in link or code dies too
    conn.execute(
        update(t.human)
        .where(t.human.c.id == human_id, t.human.c.suspended_at.is_(None))
        .values(suspended_at=clock.now(), suspended_report=report_id)
    )


def unsuspend(conn: Connection, human_id: str) -> bool:
    """The operator lifts a suspension; True when one stood. Nothing comes back by itself:
    the account signs in again, and its agents join again."""
    lifted = (
        conn.execute(
            update(t.human)
            .where(t.human.c.id == human_id, t.human.c.suspended_at.isnot(None))
            .values(suspended_at=None, suspended_report=None)
        ).rowcount
        == 1
    )
    if lifted:
        public_pages.touch(conn, "person", human_id, removal=False)  # the page may return
    return lifted


# --- the account a report concerns ----------------------------------------------------------


def _live_author(conn: Connection, report: Any) -> str | None:
    """The target's author as it stands, for a report whose copy was emptied."""
    if report.target_type == "profile":
        return str(report.target_id)
    if report.target_type == "project":
        return conn.execute(
            select(t.project.c.owner_id).where(t.project.c.id == report.project_id)
        ).scalar()
    if report.target_type == "card":
        created_by = conn.execute(
            select(t.card.c.created_by).where(t.card.c.id == report.target_id)
        ).scalar()
        return principal_id(conn, created_by)
    acted = conn.execute(
        select(t.event.c.actor_membership).where(t.event.c.seq == int(report.target_id))
    ).scalar()
    return principal_id(conn, acted)


def account_of(conn: Connection, report: Any) -> str | None:
    """The account an action concerns (§16.8): a profile's account (an agent's owner's); a
    message's or card's author as the copy recorded them; a project's namespace owner at
    the time of the report. None when that account no longer exists."""
    author = ((report.snapshot or {}).get("author") or {}).get("id")
    if report.target_type == "profile":
        author = report.target_id
    if author is None:
        author = _live_author(conn, report)
    account = owner_account(conn, author)
    if account is None:
        return None
    gone = conn.execute(select(t.human.c.deleted_at).where(t.human.c.id == account)).first()
    return None if gone is None or gone.deleted_at is not None else account


def org_of(conn: Connection, report: Any) -> str | None:
    """The organisation that owns the reported project (§6.26), by the owner the report's copy
    recorded, else as it stands: None for a project of a human and for every other target."""
    if report.target_type != "project":
        return None
    author = ((report.snapshot or {}).get("author") or {}).get("id")
    if author is None:
        author = _live_author(conn, report)
    return author if isinstance(author, str) and author.startswith("org-") else None


# --- the actions ----------------------------------------------------------------------------


def suspend_org(conn: Connection, org_id: str, report: Any, note: str | None) -> list[str]:
    """`suspend` on a project of an organisation applies to the organisation, never to a person
    (§16.8, §6.26): it takes no new project and no transfer in, its page is off, every open
    transfer into it is withdrawn, and each of its projects that is not archived is archived as
    `remove` archives one. A hold on the organisation (`moderation` in its view) marks it, lifted
    as every hold is; its owners, admins and members are untouched. Returns the owners, whom the
    notice goes to."""
    from maity_hub import org_projects, orgs, project_names
    from maity_hub.routes.projects import archive_by_moderation

    org = orgs.lock(conn, org_id)
    if org is None:
        raise ApiError(
            400,
            "invalid",
            "the organisation no longer exists",
            {"fields": {"action": "no_org"}, "reason": "no_org"},
        )
    by = actor(report.id)
    reason = _reason(report, note)
    conn.execute(
        insert(t.moderation_hold).values(
            report_id=report.id,
            target_type="org",
            target_id=org_id,
            action="suspend",
            at=clock.now(),
        )
    )
    conn.execute(update(t.org).where(t.org.c.id == org_id).values(public_page="off"))
    project_names.withdraw_into(conn, org_id, reason)
    for project in org_projects.projects_of(conn, org_id):
        if project.state != "archived":
            archive_by_moderation(conn, project.id, reason, by)
    return org_projects.owners_of(conn, org_id)


def _reason(report: Any, note: str | None) -> str:
    return note or f"moderation: {report.reason}"


def _hide(conn: Connection, report: Any, note: str | None) -> None:
    """A project's public surfaces go off; a profile, a message or a card is not served
    publicly anywhere yet (§16.9), so its hold is all there is to it."""
    if report.target_type == "project":
        from maity_hub.routes.projects import hide_by_moderation

        hide_by_moderation(conn, report.project_id, _reason(report, note), actor(report.id))


def _reset_profile(conn: Connection, report: Any) -> None:
    from maity_hub import avatars

    owner = report.target_id
    table = t.agent_profile if owner.startswith("agt-") else t.human
    row = conn.execute(select(table).where(table.c.id == owner)).first()
    if row is None:
        return
    avatars.lock_owner(conn, owner)
    before = avatars.state(conn, owner)
    avatars.remove_upload(conn, owner)
    avatars.announce(conn, owner, before, actor(report.id))
    if row.display_name != row.handle:
        conn.execute(update(table).where(table.c.id == owner).values(display_name=row.handle))


def _remove(
    conn: Connection,
    report: Any,
    note: str | None,
    fg: Forge,
    store: attachment_store.LocalStore | None,
) -> None:
    """Each with the note as its reason; the ordinary rules of who may do it do not apply
    to this one change (§16.8)."""
    by = actor(report.id)
    reason = _reason(report, note)
    if report.target_type == "message":
        from maity_hub.routes.events import tombstone

        row = conn.execute(
            select(t.event).where(
                t.event.c.seq == int(report.target_id),
                t.event.c.project_id == report.project_id,
            )
        ).first()
        if row is not None:
            tombstone(
                conn, report.project_id, row, reason, list(row.audience or []), None, by, store
            )
    elif report.target_type == "card":
        from maity_hub.routes.tasks import cancel_by_moderation

        cancel_by_moderation(conn, report.target_id, by, fg)
    elif report.target_type == "project":
        from maity_hub.routes.projects import archive_by_moderation

        archive_by_moderation(conn, report.project_id, reason, by)
    else:
        _reset_profile(conn, report)


def apply(
    conn: Connection,
    report: Any,
    action: str,
    note: str | None,
    fg: Forge,
    store: attachment_store.LocalStore | None = None,
) -> None:
    """Make the change `action` asks for. Resolving again replaces the report's hold;
    `dismiss` lifts it and restores nothing. A suspension is the operator's to lift."""
    account = account_of(conn, report)
    org_id = org_of(conn, report)
    owners: list[str] = []
    if action == "suspend" and account is None and org_id is None:
        raise ApiError(
            400,
            "invalid",
            "the account no longer exists",
            {"fields": {"action": "no_account"}, "reason": "no_account"},
        )
    conn.execute(delete(t.moderation_hold).where(t.moderation_hold.c.report_id == report.id))
    if action == "dismiss":
        if account is not None:  # a lifted hold may bring the person's page back
            public_pages.touch(conn, "person", account, removal=False)
        return
    if action == "hide":
        _hide(conn, report, note)
    elif action == "remove":
        _remove(conn, report, note, fg, store)
    elif org_id is not None:
        owners = suspend_org(conn, org_id, report, note)
    elif account is not None:
        suspend(conn, account, report.id)
    if action in HOLDING:
        kind, key = target_key(report)
        conn.execute(
            insert(t.moderation_hold).values(
                report_id=report.id, target_type=kind, target_id=key, action=action, at=clock.now()
            )
        )
    if account is not None:  # a hidden, removed or suspended person has no page (§16.9)
        public_pages.touch(conn, "person", account)
    again = report.status == "resolved" and report.action == action and report.note == note
    # The affected account's notice: the action and the note, never the reporter. A repeat of
    # the same resolution tells it nothing new. For an organisation's suspension and for an
    # action on a project of an organisation, every owner of the organisation gets it (§16.8).
    if org_id is not None and action != "dismiss":
        from maity_hub import org_projects

        recipients = owners if action == "suspend" else org_projects.owners_of(conn, org_id)
    else:
        recipients = [account] if account is not None else []
    if not again:
        for recipient in recipients:
            records.write(
                conn,
                recipient,
                "moderation_applied",
                {"report": report.id, "action": action, "type": report.target_type, "note": note},
            )


def check(action: Any) -> None:
    if action not in ("dismiss", *HOLDING, "suspend"):
        raise invalid({"action": "unknown"})
