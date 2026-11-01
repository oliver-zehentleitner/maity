"""How a ticker item is read (docs/api.md §17.5): who may read a decision, `detail`,
the per-reader shape, and who it wakes.

Kept apart from `ticker.py`, which writes items through `events`: `events` and
`views` read through these functions on every read path, so this module imports
neither of them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.replies import replies
from maity_hub.scopes import has_scope, tokens_of


def may_read_request(request: Any, member: Any) -> bool:
    """§7's readers of a request, from a membership row or a `ticker.Member`: the asker and
    the member asked for, the addressee (a member, the owner, every holder of the role),
    and whoever holds `requests:answer`."""
    membership_id = getattr(member, "membership_id", None) or member.id
    trust, role, base = member.trust, member.role, member.role_base
    kind = getattr(member, "kind", None)
    if kind not in ("human", "agent"):
        kind = "agent" if member.agent_id else "human"
    if membership_id in (request.asked_by, request.on_behalf_of):
        return True
    if request.to_kind == "member" and request.to_member == membership_id:
        return True
    if request.to_kind == "owner" and trust == "owner":
        return True
    if request.to_kind == "role" and request.to_role in tokens_of(trust, role, base):
        return True
    return has_scope(trust, base, kind, "requests:answer")


def _decision_request(row: Any) -> str | None:
    """The request a decision item is about; from its subject, which a redaction keeps
    (the payload it replaces, §8.5)."""
    if row.kind != "ticker" or row.subject_type != "request":
        return None
    request_id: str | None = row.subject_id
    return request_id


def withheld(conn: Connection, rows: Sequence[Any], membership: Any) -> frozenset[int]:
    """The `seq`s of the decision items among `rows`, redacted ones included, that
    `membership` may not read now: no item and no placeholder for it (§17.5)."""
    if membership is None:
        return frozenset()
    wanted = {r.seq: _decision_request(r) for r in rows}
    ids = {request_id for request_id in wanted.values() if request_id}
    if not ids:
        return frozenset()
    requests = {
        r.id: r for r in conn.execute(select(t.request).where(t.request.c.id.in_(ids))).all()
    }
    hidden = set()
    for seq, request_id in wanted.items():
        if request_id is None:
            continue
        request = requests.get(request_id)
        if request is None or not may_read_request(request, membership):
            hidden.add(seq)
    return frozenset(hidden)


def sees_everyones(reader: Any) -> bool:
    """Human owners and admins see every member's reasons and subscription (§17.5, §17.8)."""
    return reader is not None and reader.kind == "human" and reader.trust in ("owner", "admin")


def details(conn: Connection, rows: Sequence[Any]) -> dict[int, dict[str, Any]]:
    """`detail` of the live decision items among `rows`, read now: the request's title and
    the label of the chosen reply; `null` for an answer in words, whose text never
    appears (§17.5)."""
    wanted = {r.seq: _decision_request(r) for r in rows if not r.redacted}
    ids = {request_id for request_id in wanted.values() if request_id}
    if not ids:
        return {}
    requests = {
        r.id: r for r in conn.execute(select(t.request).where(t.request.c.id.in_(ids))).all()
    }
    found: dict[int, dict[str, Any]] = {}
    for seq, request_id in wanted.items():
        request = requests.get(request_id) if request_id else None
        if request is None:
            continue
        chosen = (request.answer or {}).get("reply_id")
        options = replies(getattr(request, "class"), request.options or [])
        label = next((o["label"] for o in options if o["id"] == chosen), None)
        found[seq] = {"request_title": request.title, "reply_label": label}
    return found


def shaped_audience(audience: list[str], reader: Any) -> list[str]:
    """`all` and the reader's own token, for everyone but human owners and admins."""
    if sees_everyones(reader):
        return audience
    principal = reader.principal_id if reader is not None else None
    return [a for a in audience if a == "all" or a == f"member:{principal}"]


def shaped(
    payload: dict[str, Any], audience: list[str], reader: Any, detail: Any
) -> tuple[dict[str, Any], list[str]]:
    """A live ticker item's payload and audience as `reader` sees them (§17.5)."""
    out = {**payload, "detail": detail if payload.get("type") == "decision" else None}
    if sees_everyones(reader):
        return out, audience
    principal = reader.principal_id if reader is not None else None
    out["reasons"] = [r for r in payload.get("reasons", []) if r.get("member_id") == principal]
    return out, shaped_audience(audience, reader)


def reason_of(payload: dict[str, Any], principal: str) -> dict[str, Any] | None:
    found: dict[str, Any] | None = next(
        (r for r in payload.get("reasons", []) if r.get("member_id") == principal), None
    )
    return found


def wakes(row: Any, principal: str) -> bool:
    """§17.5: `all` never wakes; a member is woken only by a reason with `wake: true`. A
    redacted item wakes no one."""
    if row.redacted:
        return False
    entry = reason_of(row.payload or {}, principal)
    return bool(entry and entry.get("wake"))


def ticker_subjects(conn: Connection, rows: Sequence[Any]) -> set[str]:
    """The `subject_id`s of the `event_redacted` among `rows` that removed a ticker item."""
    seqs = {
        int(r.subject_id)
        for r in rows
        if r.kind == "event_redacted" and r.subject_type == "event" and r.subject_id
    }  # a round's redaction (§20.8) names the round, not a seq
    if not seqs:
        return set()
    return {
        str(seq)
        for seq in conn.execute(
            select(t.event.c.seq).where(t.event.c.seq.in_(seqs), t.event.c.kind == "ticker")
        ).scalars()
    }
