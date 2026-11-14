"""A round as §20.7 shows it: in full to members, and as a minimal projection to an agent's
owner who reads along from outside the project."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection

from maity_hub import clock, events


@dataclass(frozen=True)
class Hidden:
    """A reader's hidden isolation windows (§6.2) as a round meets them: the statement and
    the posts by their `message_seq`, the round's opening and its report by their time,
    mapped as a card's history is (`events.window_times`)."""

    membership: Any
    times: list[tuple[Any, Any]]

    @classmethod
    def of(cls, conn: Connection, reader: Any) -> Hidden | None:
        """`None` for a reader without hidden windows: a human, an owner reading along from
        outside, an agent never lifted with `hide_isolation_events`."""
        row = getattr(reader, "row", None)
        if not events.windows_of(row):
            return None
        return cls(row, events.window_times(conn, reader.project.id, row))

    def at(self, value: Any) -> bool:
        return value is not None and any(start <= value <= end for start, end in self.times)

    def seq(self, value: Any) -> bool:
        return value is not None and events.seq_in_window(value, self.membership)

    def round(self, round_row: Any) -> bool:
        """The whole round: it opened while the reader was isolated (hub/context/jour-fixe.md)."""
        return self.at(round_row.opened_at)


def _ts(value: Any) -> str | None:
    return clock.rfc3339(value) if value is not None else None


def participants(round_row: Any, active: set[str]) -> list[dict[str, Any]]:
    """The current participants: invited, and still active members."""
    return [
        {k: i[k] for k in ("member_id", "kind", "handle")}
        for i in round_row.invited
        if i["member_id"] in active
    ]


def _redaction(redaction: Any, reader: Any, readers: set[str]) -> Any:
    """`{at, by, reason}` with the reason by §8.5's chat rule, as the message's own
    tombstone shows it: the thread's humans (`group_chats.reason_readers`) and the
    redactor read it; an agent, an owner reading along and a replay get null."""
    if redaction is None:
        return None
    from maity_hub.views import sees_chat_reasons

    mine = reader is not None and redaction.get("by") == reader.principal_id
    shown = sees_chat_reasons(reader, readers) or mine
    return {**redaction, "reason": redaction.get("reason") if shown else None}


def project_redaction(redaction: Any, reader: Any) -> Any:
    """A report's or an answer's `redaction` by §8.5's project rule: the human owners and
    admins and the redactor read the reason."""
    if redaction is None:
        return None
    from maity_hub.views import sees_reasons

    mine = reader is not None and redaction.get("by") == reader.principal_id
    return {
        **redaction,
        "reason": redaction.get("reason") if sees_reasons(reader) or mine else None,
    }


def _report(report: Any, reader: Any) -> Any:
    if report is None:
        return None
    return {
        **report,
        "summary_redaction": project_redaction(report.get("summary_redaction"), reader),
        "findings": [
            {**f, "redaction": project_redaction(f.get("redaction"), reader)}
            for f in report["findings"]
        ],
        "proposals": [
            {**p, "redaction": project_redaction(p.get("redaction"), reader)}
            for p in report["proposals"]
        ],
    }


def _statement(statement: Any, reader: Any, readers: set[str]) -> Any:
    if statement is None:
        return None
    topics = [
        {
            **topic,
            "proposals": [
                {**p, "redaction": _redaction(p.get("redaction"), reader, readers)}
                for p in topic["proposals"]
            ],
            "redaction": _redaction(topic.get("redaction"), reader, readers),
        }
        for topic in statement["topics"]
    ]
    return {**statement, "topics": topics}


def _posts(round_row: Any, reader: Any, readers: set[str]) -> list[dict[str, Any]]:
    return [post(p, reader, readers) for p in round_row.posts]


def post(
    found: dict[str, Any], reader: Any = None, readers: frozenset[str] | set[str] = frozenset()
) -> dict[str, Any]:
    """A post as §20.7 shows it to `reader`: `step_n` is the hub's own bookkeeping, and a
    redaction's reason only for whom §8.5 shows it (none without a reader, as on a
    replay)."""
    shown = {k: v for k, v in found.items() if k != "step_n"}
    shown["redaction"] = _redaction(found.get("redaction"), reader, set(readers))
    return shown


def full(
    round_row: Any,
    slug: str,
    active: set[str],
    reader: Any = None,
    readers: frozenset[str] | set[str] = frozenset(),
    hidden: Hidden | None = None,
) -> dict[str, Any]:
    """`readers`: who reads a redaction's reason in the round's thread (§8.5). `hidden`: the
    reader's isolation windows (§6.2), which drop the statement, the posts and the report
    that came about in one of them."""
    readers = set(readers)
    statement, posts, report = round_row.statement, round_row.posts, round_row.report
    if hidden is not None:
        if statement is not None and hidden.seq(statement.get("message_seq")):
            statement = None
        posts = [p for p in posts or [] if not hidden.seq(p.get("message_seq"))]
        if hidden.at(round_row.reported_at):
            report = None
    return {
        "id": round_row.id,
        "project": slug,
        "status": round_row.status,
        **series_fields(round_row),
        "trigger": round_row.trigger,
        "reason": round_row.reason,
        "skip_reason": round_row.skip_reason,
        "missed_slots": round_row.missed_slots,
        "scheduled_for": _ts(round_row.scheduled_for),
        "opened_at": _ts(round_row.opened_at),
        "answers_close_at": _ts(round_row.answers_close_at),
        "steps": round_row.steps,
        "exchange_closed_at": _ts(round_row.exchange_closed_at),
        "report_due_at": _ts(round_row.report_due_at),
        "reported_at": _ts(round_row.reported_at),
        "config": round_row.config,
        "moderator": round_row.moderator,
        "invited": round_row.invited,
        "participants": participants(round_row, active),
        "absent": round_row.absent,
        "answers_received": round_row.answers_received,
        "conversation_id": round_row.conversation_id,
        "statement": _statement(statement, reader, readers),
        "posts": [post(p, reader, readers) for p in posts],
        "report": _report(report, reader),
    }


def series_fields(round_row: Any) -> dict[str, Any]:
    """`series_id`, `topic` and `circle` of a round (§20.7), from the series' state the round
    opened with (`config`), so a round keeps them after its series is deleted; a round from
    before series existed reads as the series the upgrade made for it."""
    config = round_row.config or {}
    return {
        "series_id": round_row.series_id or config.get("id"),
        "topic": config.get("topic") or "How we work",
        "circle": config.get("circle") or "all",
    }


def minimal(
    round_row: Any,
    slug: str,
    active: set[str],
    reader: Any = None,
    readers: frozenset[str] | set[str] = frozenset(),
) -> dict[str, Any]:
    """For an observer from outside the project (§20.7): nothing about the members beyond
    the participant list, no answers, counts, config, moderator or eligibility."""
    report = _report(round_row.report, reader)
    if report is not None:
        report = {k: v for k, v in report.items() if k != "proposals_not_carded"}
        report["proposals"] = [
            {k: v for k, v in p.items() if k != "request_id"} for p in report.get("proposals", [])
        ]
    return {
        "id": round_row.id,
        "project": slug,
        "status": round_row.status,
        "opened_at": _ts(round_row.opened_at),
        "answers_close_at": _ts(round_row.answers_close_at),
        "exchange_closed_at": _ts(round_row.exchange_closed_at),
        "reported_at": _ts(round_row.reported_at),
        "participants": participants(round_row, active),
        "statement": _statement(round_row.statement, reader, set(readers)),
        "posts": _posts(round_row, reader, set(readers)),
        "report": report,
    }
