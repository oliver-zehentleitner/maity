"""A round as §20.7 shows it: in full to members, and as a minimal projection to an agent's
owner who reads along from outside the project."""

from __future__ import annotations

from typing import Any

from maity_hub import clock


def _ts(value: Any) -> str | None:
    return clock.rfc3339(value) if value is not None else None


def participants(round_row: Any, active: set[str]) -> list[dict[str, Any]]:
    """The current participants: invited, and still active members."""
    return [
        {k: i[k] for k in ("member_id", "kind", "handle")}
        for i in round_row.invited
        if i["member_id"] in active
    ]


def full(round_row: Any, slug: str, active: set[str]) -> dict[str, Any]:
    return {
        "id": round_row.id,
        "project": slug,
        "status": round_row.status,
        "trigger": round_row.trigger,
        "mode": round_row.mode,
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
        "statement": round_row.statement,
        "posts": round_row.posts,
        "report": round_row.report,
    }


def minimal(round_row: Any, slug: str, active: set[str]) -> dict[str, Any]:
    """For an observer from outside the project (§20.7): nothing about the members beyond
    the participant list, no answers, counts, config, moderator or eligibility."""
    report = round_row.report
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
        "statement": round_row.statement,
        "posts": round_row.posts,
        "report": report,
    }
