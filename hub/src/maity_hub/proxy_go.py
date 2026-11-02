"""The owner's go for one governance call of a proxy (docs/api.md §2.3 "The proxy").

A proxy holds no governance scope of its own: each call under one names, in the signed
`Maity-On-Request`, a request of its own carrying `action`, which a human with trust `owner`
answered `go`. The go binds exactly one call and is spent in that call's transaction, so a
call that fails leaves it unused and two calls racing on it succeed at most once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock, events
from maity_hub import tables as t
from maity_hub.auth.caller import OnRequest
from maity_hub.events import Actor
from maity_hub.scopes import GOVERNANCE, HUMAN_ONLY

VALID_FOR = timedelta(hours=24)
# `requests:answer` is the proxy's own: a relay needs no go (§2.3).
_GATED = frozenset(GOVERNANCE) - {"requests:answer"}


def gated(scope: str, kind: str) -> bool:
    """Whether the go opens this scope for a proxy. What only a human holds stays closed to
    an agent proxy, with or without one: it stays an agent."""
    return scope in _GATED and (kind == "human" or scope not in HUMAN_ONLY)


@dataclass(eq=False)
class ProxyGo:
    """One proxy's call within one transaction; `reason` names the last refusal."""

    conn: Connection
    project_id: str
    membership_id: int
    header: OnRequest | None
    actor: Actor
    reason: str = "missing"

    def _refusal(self, row: Any) -> str | None:
        assert self.header is not None
        if row is None or row.project_id != self.project_id:
            return "not_bound"
        if row.asked_by != self.membership_id or row.action is None:
            return "not_bound"
        if row.status != "answered":
            return "unanswered"
        if (row.answer or {}).get("reply_id") != "go":
            return "declined"
        if row.action_used_at is not None:
            return "used"
        if clock.now() > row.answered_at + VALID_FOR:
            return "expired"
        action = row.action
        call = self.header
        if (
            action["method"] != call.method
            or action["path"] != call.path
            or action["query"] != call.query
            or action["body_sha256"] != call.body_sha256
        ):
            return "mismatch"
        return None

    def spend(self) -> bool:
        """True when this call holds the go, spending it the first time it is asked."""
        if self.header is None:
            self.reason = "missing"
            return False
        row: Any = self.conn.execute(
            select(t.request).where(t.request.c.id == self.header.request_id)
        ).first()
        if self.header.spent_seq is not None and row.action_used_seq == self.header.spent_seq:
            return True  # this call spent it, and the spend stands
        refusal = self._refusal(row)
        if refusal is not None:
            self.reason = refusal
            return False
        now = clock.now()
        done = self.conn.execute(
            update(t.request)
            .where(t.request.c.id == row.id, t.request.c.action_used_at.is_(None))
            .values(action_used_at=now)
        ).rowcount
        if done != 1:  # another call took it first
            self.reason = "used"
            return False
        seq = events.emit(
            self.conn,
            self.project_id,
            "request_action_used",
            ["trust:owner", "trust:admin"],
            {
                "id": row.id,
                "method": row.action["method"],
                "path": row.action["path"],
                "query": row.action["query"],
                "body_sha256": row.action["body_sha256"],
                "used_at": clock.rfc3339(now),
            },
            actor=self.actor,
            subject=("request", row.id),
        )
        self.conn.execute(
            update(t.request).where(t.request.c.id == row.id).values(action_used_seq=seq)
        )
        self.header.spent_seq = seq
        return True
