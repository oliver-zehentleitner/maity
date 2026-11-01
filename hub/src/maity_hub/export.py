"""A human's own data as one JSON document: `GET /me/export` (docs/api.md §2.9).

The export holds what is about the caller or written by them, and nothing that is only
another person's. Another person's text appears only as the title of the thing the
caller's own entry belongs to (a card, a request, a group chat), and only where the
caller may still read that thing now; otherwise the id alone. Redacted content is
exported as redacted: the tombstone's time and redactor, its reason only when the
caller redacted it themselves.

Never in it: a password hash, a session's cookie value or CSRF token, a credential or
its verifier, a join or enrollment token, a code hash, a nonce, a second factor's secret
or recovery code. What the document shows is picked field by field; where a row is read
whole for the hub's own read rules (`inbox.may_read`), only named fields leave it.

Not in this hub yet, so not in the export: handle aliases (§6.24), languages and the public
profile (§16.9).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import avatars, clock, group_chats, inbox, namespace, reports
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth import second_factor
from maity_hub.notifications import preferences as notification_preferences
from maity_hub.views import git_identity, principal_ids, ts

FORMAT = 1
# What one IN list carries at most: far below every engine's limit on bound parameters.
CHUNK = 500


def build(conn: Connection, human_id: str, now: datetime) -> dict[str, Any]:
    human = conn.execute(select(t.human).where(t.human.c.id == human_id)).one()
    mine = _memberships(conn, human_id)
    my_ids = {row.id for row in mine}
    readers = _readers(conn, mine)
    answered = _answers(conn, human_id, my_ids)
    project_ids = {row.project_id for row in mine} | {row.project_id for row in answered}
    names = namespace.full_names(conn, project_ids)
    agents = _agent_profiles(conn, human_id)
    agent_memberships = _agent_memberships(conn, [a.id for a in agents])
    member_ids = principal_ids(
        conn,
        [row.reports_to for row in mine] + [row.reports_to for row in agent_memberships],
    )
    titles = _Titles(conn, human_id, readers)
    member_project_ids = sorted({row.project_id for row in mine})
    return {
        "format": FORMAT,
        "exported_at": clock.rfc3339(now),
        "account": _account(conn, human),
        "sessions": _sessions(conn, human_id),
        # The state only, never the secret or a recovery code (§2.9, §2.8).
        "second_factor": {
            "enrolled": second_factor.enrolled(second_factor.factor_of(conn, human_id)),
            "recovery_codes_left": second_factor.recovery_codes_left(conn, human_id),
        },
        "forge_links": _forge_links(conn, human_id),
        "organisations": _organisations(conn, human_id),
        "abuse_reports": _abuse_reports(conn, human_id),
        # While the hub still keeps it, null otherwise: it ends with the first agent exchange or
        # after 30 days (§16.7.2).
        "campaign_origin": _campaign_origin(conn, human_id),
        "conversation_meat_proxy": _conversation_meat_proxy(conn, human_id),
        "organisation_invitations": _org_invitations(conn, human_id),
        "runners": _runners(conn, human_id),
        "agent_profiles": _agent_views(conn, agents, agent_memberships, names, member_ids),
        "memberships": [_membership_view(row, names, member_ids) for row in mine],
        "messages": _messages(conn, member_project_ids, my_ids, names, titles, chat=False),
        "chat_messages": _messages(conn, member_project_ids, my_ids, names, titles, chat=True),
        "requests_asked": _requests_asked(conn, member_project_ids, my_ids, names, titles),
        "answers_given": [_answer_view(row, names, titles) for row in answered],
        "cards_created": _cards_created(conn, member_project_ids, my_ids, names, titles),
        "card_reports": _card_reports(conn, member_project_ids, my_ids, names, titles),
        "card_approvals": _card_approvals(conn, member_project_ids, my_ids, names, titles),
        "card_notes": _card_notes(conn, my_ids, names, titles),
        "jour_fixe_answers": _jour_fixe_answers(conn, my_ids, names, human_id),
        "pinned_conversations": _pinned_conversations(conn, human_id),
    }


# --- helpers ---------------------------------------------------------------------------


def _chunks(values: Iterable[Any]) -> Iterator[list[Any]]:
    items = sorted(set(values))
    for start in range(0, len(items), CHUNK):
        yield items[start : start + CHUNK]


def _redaction(mark: Any, human_id: str) -> dict[str, Any]:
    """§8.5's tombstone as the export shows it: the reason only when it is the caller's."""
    mark = mark if isinstance(mark, dict) else {}
    own = mark.get("by") == human_id
    return {
        "at": mark.get("at"),
        "by": mark.get("by"),
        "reason": mark.get("reason") if own else None,
    }


class _Titles:
    """Another person's text, as a title, where the caller may still read it now.

    `readers` holds the caller's active human membership per project. Each lookup reads
    the rows it needs once, in batches, and keeps them."""

    def __init__(self, conn: Connection, human_id: str, readers: dict[str, Membership]) -> None:
        self.conn = conn
        self.human_id = human_id
        self.readers = readers
        self._cards: dict[str, Any] = {}
        self._requests: dict[str, Any] = {}
        self._conversations: dict[tuple[str, str], str | None] = {}

    def load_cards(self, card_ids: Iterable[str | None]) -> None:
        wanted = {i for i in card_ids if i and i not in self._cards}
        for chunk in _chunks(wanted):
            rows = self.conn.execute(
                select(t.card.c.id, t.card.c.project_id, t.card.c.title).where(
                    t.card.c.id.in_(chunk)
                )
            ).all()
            self._cards.update({row.id: row for row in rows})

    def card(self, card_id: str | None) -> dict[str, Any] | None:
        if card_id is None:
            return None
        self.load_cards([card_id])
        row = self._cards.get(card_id)
        mine = self.readers.get(row.project_id) if row is not None else None
        readable = row is not None and mine is not None and mine.may("project:read")
        return {"id": card_id, "title": row.title if readable and row is not None else None}

    def load_requests(self, rows: Iterable[Any]) -> None:
        self._requests.update({row.id: row for row in rows})

    def request(self, request_id: str) -> dict[str, Any]:
        row = self._requests.get(request_id)
        if row is None:
            row = self.conn.execute(select(t.request).where(t.request.c.id == request_id)).first()
            self._requests[request_id] = row
        readable = False
        if row is not None:
            if row.personal and row.to_human == self.human_id:
                readable = True  # `GET /requests/{id}` (§7)
            else:
                mine = self.readers.get(row.project_id)
                readable = mine is not None and inbox.may_read(self.conn, row, mine)
        return {"id": request_id, "title": row.title if readable and row is not None else None}

    def conversation(self, project_id: str, conversation_id: str) -> dict[str, Any]:
        """A direct chat has no title; a group chat's is shown while the caller is in it
        or reads it along (§9.2)."""
        if not group_chats.is_group(conversation_id):
            return {"id": conversation_id, "title": None}
        key = (project_id, conversation_id)
        if key not in self._conversations:  # one read per chat, however many messages
            mine = self.readers.get(project_id)
            title = None
            if mine is not None and group_chats.access(self.conn, conversation_id, mine):
                title = self.conn.execute(
                    select(t.conversation.c.title).where(t.conversation.c.id == conversation_id)
                ).scalar()
            self._conversations[key] = title
        return {"id": conversation_id, "title": self._conversations[key]}


# --- the account -----------------------------------------------------------------------


def _account(conn: Connection, human: Any) -> dict[str, Any]:
    settings = notification_preferences.view(conn, human.id, mail_available=False)
    email = dict(settings["email"])
    addresses = []
    if email.get("address"):
        addresses.append(
            {
                "address": email["address"],
                "state": email["address_status"],
                "verified_at": email["verified_at"],
                "disabled_at": email["disabled_at"],
                "hard_failures": email["hard_failures"],
            }
        )
    if email.get("pending_address"):
        addresses.append(
            {
                "address": email["pending_address"],
                "state": "pending",
                "verified_at": None,
                "disabled_at": None,
                "hard_failures": 0,
            }
        )
    for key in ("address", "address_status", "verified_at", "pending_address"):
        email.pop(key, None)
    for key in ("disabled_at", "hard_failures"):
        email.pop(key, None)
    prefs = conn.execute(
        select(t.preferences.c.markdown, t.preferences.c.version, t.preferences.c.updated_at).where(
            t.preferences.c.human_id == human.id
        )
    ).first()
    return {
        "id": human.id,
        "handle": human.handle,
        "display_name": human.display_name,
        **avatars.state(conn, human.id),
        "account_status": human.account_status,
        "created_at": ts(human.created_at),
        "registered_at": ts(human.registered_at),
        "last_login_at": ts(human.last_login_at),
        "terms": (
            {"version": human.terms_version, "accepted_at": ts(human.terms_accepted_at)}
            if human.terms_version is not None
            else None
        ),
        "limit": (
            {
                "until": ts(human.limit_until),
                "since": ts(human.limit_since),
                "reason": human.limit_reason,
            }
            if human.limit_until is not None
            else None
        ),
        "addresses": addresses,
        "preferences": (
            {
                "markdown": prefs.markdown,
                "version": prefs.version,
                "updated_at": ts(prefs.updated_at),
            }
            if prefs is not None
            else None
        ),
        "notification_settings": {
            "browser": settings["browser"],
            "email": email,
            "not_listening": settings["not_listening"],
        },
    }


def _sessions(conn: Connection, human_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(
            t.human_session.c.public_id,
            t.human_session.c.method,
            t.human_session.c.browser,
            t.human_session.c.os,
            t.human_session.c.created_at,
            t.human_session.c.last_seen_at,
            t.human_session.c.ended_at,
            t.human_session.c.ended_by,
        )
        # A sign-in still owing its second step is no session yet (§2.8.2).
        .where(
            t.human_session.c.human_id == human_id,
            t.human_session.c.sign_in_complete.is_(True),
        ).order_by(t.human_session.c.created_at, t.human_session.c.public_id)
    ).all()
    return [
        {
            "id": row.public_id,
            "method": row.method,
            "device": {"browser": row.browser, "os": row.os},
            "created_at": ts(row.created_at),
            "last_seen_at": ts(row.last_seen_at),
            "ended_at": ts(row.ended_at),
            "ended_by": row.ended_by,
        }
        for row in rows
    ]


def _organisations(conn: Connection, human_id: str) -> list[dict[str, Any]]:
    """The organisations the caller belongs to: handle, role, when they joined (§2.9, §6.26)."""
    rows = conn.execute(
        select(t.org.c.handle, t.org_member.c.role, t.org_member.c.joined_at)
        .join(t.org_member, t.org_member.c.org_id == t.org.c.id)
        .where(t.org_member.c.human_id == human_id, t.org.c.deleted_at.is_(None))
        .order_by(t.org_member.c.joined_at, t.org.c.id)
    ).all()
    return [{"handle": r.handle, "role": r.role, "joined": ts(r.joined_at)} for r in rows]


def _pinned_conversations(conn: Connection, human_id: str) -> list[dict[str, Any]]:
    """The chats the caller pinned (§9.3 "Pinned"): project, chat id, when."""
    rows = conn.execute(
        select(t.conversation_pin)
        .where(t.conversation_pin.c.human_id == human_id)
        .order_by(t.conversation_pin.c.pinned_at, t.conversation_pin.c.conversation_id)
    ).all()
    names = namespace.full_names(conn, {r.project_id for r in rows})
    return [
        {
            "project": names[r.project_id],
            "conversation_id": r.conversation_id,
            "pinned_at": ts(r.pinned_at),
        }
        for r in rows
    ]


def _campaign_origin(conn: Connection, human_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        select(t.campaign_origin).where(t.campaign_origin.c.human_id == human_id)
    ).first()
    if row is None:
        return None
    return {
        "variant": row.variant,
        "campaign": row.campaign,
        "registered_on": row.registered_at.date().isoformat(),
    }


def _conversation_meat_proxy(conn: Connection, human_id: str) -> list[dict[str, Any]]:
    """The person's own choice of the meat-proxy mode per conversation (§9.3)."""
    rows = conn.execute(
        select(t.conversation_meat_proxy)
        .where(t.conversation_meat_proxy.c.human_id == human_id)
        .order_by(
            t.conversation_meat_proxy.c.project_id, t.conversation_meat_proxy.c.conversation_id
        )
    )
    return [
        {
            "project_id": r.project_id,
            "conversation_id": r.conversation_id,
            "meat_proxy": bool(r.meat_proxy),
        }
        for r in rows
    ]


def _abuse_reports(conn: Connection, human_id: str) -> list[dict[str, Any]]:
    """The abuse reports the account filed, its agents' included (§16.8): what was reported,
    why, the caller's own text, status and action; never the copy of the target, which is
    the reported member's content, nor the instance admin's note."""
    rows = conn.execute(
        select(t.abuse_report)
        .where(t.abuse_report.c.account_id == human_id)
        .order_by(t.abuse_report.c.created_at, t.abuse_report.c.id)
    ).all()
    return [{**reports.own_view(conn, row), "text": row.text} for row in rows]


def _org_invitations(conn: Connection, human_id: str) -> list[dict[str, Any]]:
    """The invitations to organisations the caller sent: the organisation, the handle as they
    typed it, the role, how it stands and when; nothing of the request behind it (§2.9)."""
    rows = conn.execute(
        select(
            t.org.c.handle.label("org"),
            t.org_invitation.c.handle,
            t.org_invitation.c.role,
            t.org_invitation.c.live,
            t.org_invitation.c.closed_by,
            t.org_invitation.c.created_at,
            t.org_invitation.c.expires_at,
            t.org_invitation.c.closed_at,
        )
        .join(t.org, t.org.c.id == t.org_invitation.c.org_id)
        .where(t.org_invitation.c.invited_by == human_id)
        .order_by(t.org_invitation.c.created_at, t.org_invitation.c.id)
    ).all()
    return [
        {
            "organisation": r.org,
            "handle": r.handle,
            "role": r.role,
            "status": "open" if r.live else (r.closed_by or "closed"),
            "created": ts(r.created_at),
            "expires": ts(r.expires_at),
            "closed": ts(r.closed_at),
        }
        for r in rows
    ]


def _forge_links(conn: Connection, human_id: str) -> list[dict[str, Any]]:
    """The caller's forge access (§11.4): each App installation they linked and their own
    token, as login, kind and when it was made, never a token (§2.9)."""
    links = conn.execute(
        select(
            t.forge_link.c.forge,
            t.forge_link.c.account_login,
            t.forge_link.c.status,
            t.forge_link.c.linked_at,
        )
        .where(t.forge_link.c.human_id == human_id)
        .order_by(t.forge_link.c.linked_at, t.forge_link.c.id)
    ).all()
    found = [
        {
            "kind": "app",
            "forge": row.forge,
            "login": row.account_login,
            "status": row.status,
            "created": ts(row.linked_at),
        }
        for row in links
    ]
    token = conn.execute(
        select(
            t.forge_token.c.forge,
            t.forge_token.c.login,
            t.forge_token.c.status,
            t.forge_token.c.set_at,
        ).where(t.forge_token.c.human_id == human_id)
    ).first()
    if token is not None:
        found.append(
            {
                "kind": "token",
                "forge": token.forge,
                "login": token.login,
                "status": token.status,
                "created": ts(token.set_at),
            }
        )
    return found


def _runners(conn: Connection, human_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(
            t.runner.c.id,
            t.runner.c.name,
            t.runner.c.created_at,
            t.runner.c.updated_at,
            t.runner.c.removed_at,
            t.runner.c.last_seen_at,
            t.runner.c.version,
        )
        .where(t.runner.c.owner_id == human_id)
        .order_by(t.runner.c.created_at, t.runner.c.id)
    ).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "created_at": ts(row.created_at),
            "updated_at": ts(row.updated_at),
            "removed_at": ts(row.removed_at),
            "last_seen_at": ts(row.last_seen_at),
            "version": row.version,
        }
        for row in rows
    ]


# --- profiles and memberships ----------------------------------------------------------

_MEMBERSHIP_COLUMNS = (
    t.membership.c.id,
    t.membership.c.project_id,
    t.membership.c.agent_id,
    t.membership.c.trust,
    t.membership.c.role,
    t.membership.c.reports_to,
    t.membership.c.areas,
    t.membership.c.own_settings,
    t.membership.c.joined_at,
    t.membership.c.removed_at,
)


def _memberships(conn: Connection, human_id: str) -> Sequence[Any]:
    """Every membership the human ever had, the ended ones included."""
    return conn.execute(
        select(*_MEMBERSHIP_COLUMNS)
        .where(t.membership.c.human_id == human_id)
        .order_by(t.membership.c.joined_at, t.membership.c.id)
    ).all()


def _readers(conn: Connection, mine: Sequence[Any]) -> dict[str, Membership]:
    """The caller's active membership per project, as the read rules take it."""
    active = [row.id for row in mine if row.removed_at is None]
    if not active:
        return {}
    rows = conn.execute(select(t.membership).where(t.membership.c.id.in_(active))).all()
    projects = {
        p.id: p
        for p in conn.execute(
            select(t.project).where(t.project.c.id.in_({r.project_id for r in rows}))
        ).all()
    }
    return {row.project_id: Membership(projects[row.project_id], row, "human") for row in rows}


def _membership_view(row: Any, names: dict[str, str], member_ids: dict[int, str]) -> dict[str, Any]:
    return {
        "project": names.get(row.project_id),
        "project_id": row.project_id,
        "trust": row.trust,
        "role": row.role,
        "reports_to": member_ids.get(row.reports_to) if row.reports_to is not None else None,
        "areas": list(row.areas or []),
        # The person's own settings in this project, `null` for the personal default (§6.2).
        "own_settings": {
            "not_listening": {
                "minutes": ((row.own_settings or {}).get("not_listening") or {}).get("minutes")
            }
        },
        "joined_at": ts(row.joined_at),
        "left_at": ts(row.removed_at),
    }


def _agent_profiles(conn: Connection, human_id: str) -> Sequence[Any]:
    return conn.execute(
        select(
            t.agent_profile.c.id,
            t.agent_profile.c.handle,
            t.agent_profile.c.display_name,
            t.agent_profile.c.git_name,
            t.agent_profile.c.git_email,
            t.agent_profile.c.created_at,
            t.agent_profile.c.deleted_at,
        )
        .where(t.agent_profile.c.owner_id == human_id)
        .order_by(t.agent_profile.c.created_at, t.agent_profile.c.id)
    ).all()


def _agent_memberships(conn: Connection, agent_ids: list[str]) -> list[Any]:
    found: list[Any] = []
    for chunk in _chunks(agent_ids):
        found += conn.execute(
            select(*_MEMBERSHIP_COLUMNS)
            .where(t.membership.c.agent_id.in_(chunk))
            .order_by(t.membership.c.joined_at, t.membership.c.id)
        ).all()
    return found


def _agent_views(
    conn: Connection,
    agents: Sequence[Any],
    memberships: list[Any],
    names: dict[str, str],
    member_ids: dict[int, str],
) -> list[dict[str, Any]]:
    missing = {row.project_id for row in memberships} - names.keys()
    names.update(namespace.full_names(conn, missing))
    souls: dict[str, Any] = {}
    for chunk in _chunks(a.id for a in agents):
        souls.update(
            {
                row.agent_id: row
                for row in conn.execute(
                    select(
                        t.soul.c.agent_id,
                        t.soul.c.markdown,
                        t.soul.c.version,
                        t.soul.c.updated_at,
                    ).where(t.soul.c.agent_id.in_(chunk))
                ).all()
            }
        )
    by_agent: dict[str, list[Any]] = {}
    for row in memberships:
        by_agent.setdefault(row.agent_id, []).append(row)
    views = []
    for agent in agents:
        soul = souls.get(agent.id)
        views.append(
            {
                "id": agent.id,
                "handle": agent.handle,
                "display_name": agent.display_name,
                "git_identity": git_identity(agent),
                "created_at": ts(agent.created_at),
                "deleted_at": ts(agent.deleted_at),
                "soul": (
                    {
                        "markdown": soul.markdown,
                        "version": soul.version,
                        "updated_at": ts(soul.updated_at),
                    }
                    if soul is not None
                    else None
                ),
                "memberships": [
                    _membership_view(row, names, member_ids) for row in by_agent.get(agent.id, [])
                ],
            }
        )
    return views


# --- what they wrote in projects -------------------------------------------------------


def _events(conn: Connection, project_ids: list[str], kind: str, my_ids: set[int]) -> Iterator[Any]:
    """The caller's events of one kind, project by project: each query runs on the
    project's `(project_id, kind, seq)` index, never over the whole log."""
    if not my_ids:
        return
    for project_id in project_ids:
        yield from conn.execute(
            select(t.event)
            .where(
                t.event.c.project_id == project_id,
                t.event.c.kind == kind,
                t.event.c.actor_membership.in_(my_ids),
            )
            .order_by(t.event.c.seq)
        ).all()


def _messages(
    conn: Connection,
    project_ids: list[str],
    my_ids: set[int],
    names: dict[str, str],
    titles: _Titles,
    *,
    chat: bool,
) -> list[dict[str, Any]]:
    rows = [
        row
        for row in _events(conn, project_ids, "message", my_ids)
        if (row.conversation_id is not None) == chat
    ]
    titles.load_cards(
        (row.payload or {}).get("task_id") for row in rows if not row.redacted and row.payload
    )
    out = []
    for row in rows:
        payload = row.payload or {}
        item: dict[str, Any] = {
            "project": names.get(row.project_id),
            "id": f"evt-{row.seq}",
            "seq": row.seq,
            "at": ts(row.at),
        }
        if chat:
            item["conversation"] = titles.conversation(row.project_id, row.conversation_id)
        if row.redacted:
            item.update(redacted=True, redaction=_redaction(payload, titles.human_id))
        else:
            item.update(
                type=payload.get("type"),
                body=payload.get("body"),
                attachments=payload.get("attachments") or [],
                redacted=False,
            )
            if not chat:
                item.update(
                    to=payload.get("to"),
                    task=titles.card(payload.get("task_id")),
                    # What a review result judged and read (§8.4): null for every other type.
                    review=payload.get("review"),
                )
        out.append(item)
    return out


_REQUEST_COLUMNS = (
    t.request.c.id,
    t.request.c.project_id,
    t.request.c["class"].label("klass"),
    t.request.c.title,
    t.request.c.summary,
    t.request.c.tried,
    t.request.c.options,
    t.request.c.priority,
    t.request.c.task_id,
    t.request.c.status,
    t.request.c.created_at,
    t.request.c.answered_at,
    t.request.c.withdrawn_at,
    t.request.c.withdraw_reason,
    t.request.c.asked_by,
    t.request.c.filed_by,
)


def _requests_asked(
    conn: Connection,
    project_ids: list[str],
    my_ids: set[int],
    names: dict[str, str],
    titles: _Titles,
) -> list[dict[str, Any]]:
    if not my_ids:
        return []
    rows: list[Any] = []
    for chunk in _chunks(project_ids):
        rows += conn.execute(
            select(*_REQUEST_COLUMNS).where(
                t.request.c.project_id.in_(chunk),
                t.request.c.asked_by.in_(my_ids),
                # What the hub files on someone's behalf is not their writing (§7), nor
                # is what it builds from others' words: a takeover's escalation carries the
                # other party's objection (§6.19), a jour fixe decision a proposal (§20.6).
                t.request.c.filed_by.is_(None),
                t.request.c.takeover_id.is_(None),
                t.request.c.jour_fixe.is_(None),
            )
        ).all()
    rows.sort(key=lambda r: (r.created_at, r.id))
    withdrawn_by_me = _withdrawn_by(conn, [r.id for r in rows if r.withdrawn_at], my_ids)
    titles.load_cards(row.task_id for row in rows)
    return [
        {
            "project": names.get(row.project_id),
            "id": row.id,
            "class": row.klass,
            "title": row.title,
            "summary": row.summary,
            "tried": row.tried,
            "options": row.options,
            "priority": row.priority,
            "task": titles.card(row.task_id),
            "status": row.status,
            "created_at": ts(row.created_at),
            # The answer is the answerer's text: only that and when it came.
            "answered_at": ts(row.answered_at),
            "withdrawn_at": ts(row.withdrawn_at),
            # Whoever withdrew wrote the reason: the caller's own only (§2.9).
            "withdraw_reason": row.withdraw_reason if row.id in withdrawn_by_me else None,
        }
        for row in rows
    ]


def _withdrawn_by(conn: Connection, request_ids: list[str], my_ids: set[int]) -> set[str]:
    """The requests among `request_ids` whose withdrawal was the caller's own."""
    found: set[str] = set()
    for chunk in _chunks(request_ids):
        found |= set(
            conn.execute(
                select(t.event.c.subject_id).where(
                    t.event.c.kind == "request_withdrawn",
                    t.event.c.subject_id.in_(chunk),
                    t.event.c.actor_membership.in_(my_ids),
                )
            ).scalars()
        )
    return found


def _answers(conn: Connection, human_id: str, my_ids: set[int]) -> list[Any]:
    """Every request the human answered: through a membership, and the personal ones
    (cross-owner consents, takeovers, an agent's outage) they answered without one."""
    found: dict[str, Any] = {}
    for chunk in _chunks(my_ids):
        for row in conn.execute(select(t.request).where(t.request.c.answered_by.in_(chunk))).all():
            found[row.id] = row
    personal = conn.execute(
        select(t.request).where(
            t.request.c.to_human == human_id,
            t.request.c.personal.is_(True),
            t.request.c.answered_by.is_(None),
            t.request.c.answered_at.is_not(None),
        )
    ).all()
    for row in personal:
        if isinstance(row.answer, dict) and row.answer.get("by") == human_id:
            found[row.id] = row
    return sorted(found.values(), key=lambda r: (r.answered_at, r.id))


def _answer_view(row: Any, names: dict[str, str], titles: _Titles) -> dict[str, Any]:
    titles.load_requests([row])
    answer = row.answer if isinstance(row.answer, dict) else {}
    return {
        "project": names.get(row.project_id),
        "id": row.id,
        "request": titles.request(row.id),
        "answered_at": ts(row.answered_at),
        "reply_id": answer.get("reply_id"),
        "text": answer.get("text"),
        "talk": bool(answer.get("talk")),
    }


def _cards_created(
    conn: Connection,
    project_ids: list[str],
    my_ids: set[int],
    names: dict[str, str],
    titles: _Titles,
) -> list[dict[str, Any]]:
    """A card the caller created, with the title and body as they wrote them: its
    `created` history entry (§6.15), not the current fields, which another member may
    have edited since. A card from before the history has no such entry: then its
    current title, if readable, and no text of its own."""
    if not my_ids:
        return []
    rows: list[Any] = []
    for chunk in _chunks(project_ids):
        rows += conn.execute(
            select(
                t.card.c.id,
                t.card.c.project_id,
                t.card.c.kind,
                t.card.c.status,
                t.card.c.created_at,
                t.card.c.jour_fixe,
            ).where(t.card.c.project_id.in_(chunk), t.card.c.created_by.in_(my_ids))
        ).all()
    rows.sort(key=lambda r: (r.created_at, r.id))
    created: dict[str, Any] = {}
    for chunk in _chunks(row.id for row in rows):
        for found in conn.execute(
            select(
                t.card_history.c.card_id,
                t.card_history.c.after,
                t.card_history.c.redacted,
                t.card_history.c.redaction,
            ).where(t.card_history.c.card_id.in_(chunk), t.card_history.c.field == "created")
        ).all():
            created[found.card_id] = found
    titles.load_cards(row.id for row in rows)
    out = []
    for row in rows:
        entry = created.get(row.id)
        written: dict[str, Any] | None
        # A card a jour fixe adopted carries the proposer's words, not the caller's (§20.6).
        if entry is None or row.jour_fixe is not None:
            written = None
        elif entry.redacted:
            written = {"redacted": True, "redaction": _redaction(entry.redaction, titles.human_id)}
        else:
            after = entry.after if isinstance(entry.after, dict) else {}
            written = {"title": after.get("title"), "body": after.get("body"), "redacted": False}
        out.append(
            {
                "project": names.get(row.project_id),
                "id": row.id,
                "kind": row.kind,
                "created_at": ts(row.created_at),
                "card": titles.card(row.id),
                "as_created": written,
            }
        )
    return out


_REPORT_FIELDS = (
    "summary",
    "head",
    "branch",
    "upstream",
    "remote_head",
    "pr",
    "pr_status",
    "pr_unknown_reason",
    "reported_instance",
)


def _card_reports(
    conn: Connection,
    project_ids: list[str],
    my_ids: set[int],
    names: dict[str, str],
    titles: _Titles,
) -> list[dict[str, Any]]:
    """Every report the caller filed, from the log: a card keeps only its latest."""
    rows = list(_events(conn, project_ids, "task_reported", my_ids))
    titles.load_cards(row.subject_id for row in rows)
    out = []
    for row in rows:
        item: dict[str, Any] = {
            "project": names.get(row.project_id),
            "id": f"evt-{row.seq}",
            "at": ts(row.at),
            "card": titles.card(row.subject_id),
        }
        payload = row.payload or {}
        if row.redacted:
            item.update(redacted=True, redaction=_redaction(payload, titles.human_id))
        else:
            item.update({key: payload.get(key) for key in _REPORT_FIELDS}, redacted=False)
        out.append(item)
    return out


def _card_approvals(
    conn: Connection,
    project_ids: list[str],
    my_ids: set[int],
    names: dict[str, str],
    titles: _Titles,
) -> list[dict[str, Any]]:
    """Every signature the caller gave on a card (§6.4), from the log: a card clears them."""
    rows = [
        row
        for row in _events(conn, project_ids, "task_updated", my_ids)
        if "approvals" in ((row.payload or {}).get("fields") or [])
    ]
    titles.load_cards(row.subject_id for row in rows)
    return [
        {
            "project": names.get(row.project_id),
            "id": f"evt-{row.seq}",
            "at": ts(row.at),
            "card": titles.card(row.subject_id),
        }
        for row in rows
    ]


def _card_notes(
    conn: Connection, my_ids: set[int], names: dict[str, str], titles: _Titles
) -> list[dict[str, Any]]:
    rows: list[Any] = []
    for chunk in _chunks(my_ids):
        rows += conn.execute(
            select(
                t.card_note.c.id,
                t.card_note.c.card_id,
                t.card_note.c.body,
                t.card_note.c.state,
                t.card_note.c.created_at,
                t.card_note.c.redacted,
                t.card_note.c.redaction,
                t.card.c.project_id,
            )
            .join(t.card, t.card.c.id == t.card_note.c.card_id)
            .where(t.card_note.c.author.in_(chunk))
        ).all()
    rows.sort(key=lambda r: (r.created_at, r.id))
    titles.load_cards(row.card_id for row in rows)
    out = []
    for row in rows:
        item: dict[str, Any] = {
            "project": names.get(row.project_id),
            "id": row.id,
            "created_at": ts(row.created_at),
            "card": titles.card(row.card_id),
            "state": row.state,
        }
        if row.redacted:
            item.update(redacted=True, redaction=_redaction(row.redaction, titles.human_id))
        else:
            item.update(body=row.body, redacted=False)
        out.append(item)
    return out


def _jour_fixe_answers(
    conn: Connection, my_ids: set[int], names: dict[str, str], human_id: str
) -> list[dict[str, Any]]:
    """Named answers only: an anonymous one stores no author (§20.4)."""
    rows: list[Any] = []
    for chunk in _chunks(my_ids):
        rows += conn.execute(
            select(
                t.jour_fixe_answer.c.id,
                t.jour_fixe_answer.c.round_id,
                t.jour_fixe_answer.c.went_well,
                t.jour_fixe_answer.c.went_badly,
                t.jour_fixe_answer.c.would_help,
                t.jour_fixe_answer.c.withdrawn,
                t.jour_fixe_answer.c.redaction,
                t.jour_fixe_round.c.project_id,
                t.jour_fixe_round.c.opened_at,
                t.jour_fixe_round.c.scheduled_for,
            )
            .join(t.jour_fixe_round, t.jour_fixe_round.c.id == t.jour_fixe_answer.c.round_id)
            .where(
                t.jour_fixe_answer.c.author.in_(chunk),
                t.jour_fixe_answer.c.anonymous.is_(False),
            )
        ).all()
    rows.sort(key=lambda r: (r.scheduled_for, r.id))
    out = []
    for row in rows:
        item: dict[str, Any] = {
            "project": names.get(row.project_id),
            "id": row.id,
            "round_id": row.round_id,
            # An answer stores no time of its own: the round's opening is when it was asked.
            "round_opened_at": ts(row.opened_at or row.scheduled_for),
            "withdrawn": bool(row.withdrawn),
        }
        if row.redaction is not None:
            item.update(redacted=True, redaction=_redaction(row.redaction, human_id))
        else:
            item.update(
                went_well=row.went_well,
                went_badly=row.went_badly,
                would_help=row.would_help,
                redacted=False,
            )
        out.append(item)
    return out


def filename(handle: str, now: datetime) -> str:
    return f"maity-export-{handle}-{now.date().isoformat()}.json"
