"""The statement and the exchange (docs/api.md §20.5).

The moderator's statement opens the exchange: per topic a response step for every current
participant, a reply step for the members a response addressed, a rejoinder for the
authors of responses that got a reply, and up to three further steps the moderator adds.
A step with nobody eligible is not opened; the exchange then closes. Every text goes to
the round's thread as a message that wakes nobody: each step wakes its eligible members
once, through `jour_fixe_step_opened`.

The steps live in the round's `steps` list. A further step the moderator asked for and
that has not opened yet is an entry with `opened_at` null; there is at most one.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock, group_chats
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid
from maity_hub.events import Actor, emit, lock_project
from maity_hub.jourfixe import rounds
from maity_hub.jourfixe.answers import refused
from maity_hub.views import principal_ids

PROPOSALS_PER_TOPIC, PROPOSALS_MAX = 5, 20
FURTHER_MAX = 3


def _state(round_row: Any, step: str | None, message: str) -> ApiError:
    return ApiError(409, "jour_fixe_state", message, {"status": round_row.status, "step": step})


def _ended(step: dict[str, Any], now: datetime) -> bool:
    """The step's window is over."""
    return now >= datetime.fromisoformat(step["closes_at"])


def _reload(conn: Connection, round_id: str) -> Any:
    return conn.execute(select(t.jour_fixe_round).where(t.jour_fixe_round.c.id == round_id)).one()


def _window(round_row: Any) -> timedelta:
    return timedelta(minutes=(round_row.config or rounds.defaults())["step_window_minutes"])


# --- who takes part now (§20.7) ---------------------------------------------------------------


def participants_now(conn: Connection, round_rows: list[Any]) -> dict[str, set[str]]:
    """Per round the member ids of its current participants: invited, still active
    members, and still in the round's thread when it has one. One query per kind."""
    if not round_rows:
        return {}
    project_ids = {r.project_id for r in round_rows}
    active = {
        (r.project_id, r.agent_id or r.human_id)
        for r in conn.execute(
            select(
                t.membership.c.project_id, t.membership.c.agent_id, t.membership.c.human_id
            ).where(t.membership.c.project_id.in_(project_ids), t.membership.c.active.is_(True))
        )
    }
    threads = [r.conversation_id for r in round_rows if r.conversation_id]
    inside: dict[str, set[str]] = {c: set() for c in threads}
    if threads:
        for conversation_id, agent_id, human_id in conn.execute(
            select(
                t.conversation_participant.c.conversation_id,
                t.membership.c.agent_id,
                t.membership.c.human_id,
            )
            .join(t.membership, t.membership.c.id == t.conversation_participant.c.membership_id)
            .where(
                t.conversation_participant.c.conversation_id.in_(threads),
                t.conversation_participant.c.here.is_(True),
            )
        ):
            inside[conversation_id].add(agent_id or human_id)
    found: dict[str, set[str]] = {}
    for row in round_rows:
        current = {
            i["member_id"] for i in row.invited if (row.project_id, i["member_id"]) in active
        }
        if row.conversation_id:
            current &= inside[row.conversation_id]
        found[row.id] = current
    return found


def _participants(conn: Connection, round_row: Any) -> list[str]:
    """In invitation order."""
    now = participants_now(conn, [round_row])[round_row.id]
    return [i["member_id"] for i in round_row.invited if i["member_id"] in now]


# --- the thread (§20.5) -----------------------------------------------------------------------


def open_thread(conn: Connection, project: Any, title: str, invited: list[str]) -> str:
    """The round's group chat, created by the hub with the invited members (§20.5)."""
    return group_chats.create(conn, project, None, title, invited, None, hub_thread=True)


def _post_message(
    conn: Connection,
    round_row: Any,
    body: str,
    actor: Actor | None,
    *,
    topic_id: str | None,
    step: str,
    post_id: str | None,
) -> int:
    """One message in the round's thread, to its participants; it wakes nobody."""
    conversation = group_chats.find(conn, round_row.project_id, round_row.conversation_id)
    # The participants, and every human owner, who reads along (§20.5).
    audience = [*group_chats.audience(group_chats.stays(conn, conversation.id)), "role:owner"]
    payload = {
        "type": "chat",
        "to": conversation.id,
        "body": body,
        "conversation_id": conversation.id,
        "task_id": None,
        "mentions": [],  # posts are not scanned for mentions (§20.5)
        "conversation": {"id": conversation.id, "kind": "group", "title": conversation.title},
        "jour_fixe": {
            "round_id": round_row.id,
            "topic_id": topic_id,
            "step": step,
            "post_id": post_id,
        },
    }
    return emit(
        conn,
        round_row.project_id,
        "message",
        audience,
        payload,
        actor=actor,
        conversation_id=conversation.id,
    )


def _render(topics: list[dict[str, Any]], handles: dict[str, str]) -> str:
    lines = ["**Statement**"]
    for topic in topics:
        lines += ["", f"### {topic['id']} · {topic['title']}"]
        if topic.get("summary"):
            lines += ["", topic["summary"]]
        if topic["items"]:
            lines.append("")
            for item in topic["items"]:
                who = "anonymous" if item["from"] == "anonymous" else handles.get(item["from"])
                lines.append(f"- {item['text']} ({who or item['from']})")
        if topic["proposals"]:
            lines += ["", "Proposals:"]
            for proposal in topic["proposals"]:
                lines.append(f"- {proposal['id']} {proposal['title']}: {proposal['reason']}")
    return "\n".join(lines)


# --- the statement (§20.5 step 1) -------------------------------------------------------------


def _is_moderator(round_row: Any, mine: Any) -> bool:
    return bool(mine.principal_id == round_row.moderator["member_id"])


def _answerers(conn: Connection, round_row: Any) -> set[str]:
    """Members whose named answer is in the round."""
    authors = conn.execute(
        select(t.jour_fixe_answer.c.author).where(
            t.jour_fixe_answer.c.round_id == round_row.id,
            t.jour_fixe_answer.c.anonymous.is_(False),
            t.jour_fixe_answer.c.withdrawn.is_(False),
        )
    ).scalars()
    return set(principal_ids(conn, authors).values())


def submit_statement(
    conn: Connection, round_row: Any, mine: Any, topics: list[dict[str, Any]], actor: Actor
) -> Any:
    lock_project(conn, round_row.project_id)
    round_row = _reload(conn, round_row.id)
    if not _is_moderator(round_row, mine):
        raise refused("not_moderator", "only the round's moderator writes the statement")
    first = round_row.steps[0] if round_row.steps else None
    if round_row.status != "statement" or first is None or _ended(first, clock.now()):
        raise _state(round_row, "statement", "the statement step is not open")
    proposals = [p for topic in topics for p in topic.get("proposals", [])]
    if len(proposals) > PROPOSALS_MAX or any(
        len(topic.get("proposals", [])) > PROPOSALS_PER_TOPIC for topic in topics
    ):
        raise invalid(
            {"topics": "too_many_proposals"}, "at most 5 proposals per topic and 20 in all"
        )
    answerers = _answerers(conn, round_row)
    if any(
        item["from"] != "anonymous" and item["from"] not in answerers
        for topic in topics
        for item in topic.get("items", [])
    ):
        raise invalid({"items": "not_an_answerer"}, "cite a member whose named answer is in")
    numbered = [
        {
            "id": f"t{n}",
            "title": topic["title"],
            "summary": topic.get("summary"),
            "items": [
                {"id": f"t{n}.i{k}", "text": item["text"], "from": item["from"]}
                for k, item in enumerate(topic.get("items", []), 1)
            ],
            "proposals": [
                {"id": f"t{n}.s{k}", "title": p["title"], "reason": p.get("reason")}
                for k, p in enumerate(topic.get("proposals", []), 1)
            ],
            "redaction": None,
        }
        for n, topic in enumerate(topics, 1)
    ]
    handles = {i["member_id"]: i["handle"] for i in round_row.invited}
    seq = _post_message(
        conn,
        round_row,
        _render(numbered, handles),
        actor,
        topic_id=None,
        step="statement",
        post_id=None,
    )
    conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.id == round_row.id)
        .values(
            statement={
                "by": round_row.moderator["member_id"],
                "message_seq": seq,
                "topics": numbered,
            }
        )
    )
    _close_current(conn, _reload(conn, round_row.id))
    return _reload(conn, round_row.id)


# --- posts (§20.5 steps 2–4 and further steps) ------------------------------------------------


def current_step(round_row: Any) -> dict[str, Any] | None:
    """The open step: opened, not yet closed."""
    for step in reversed(round_row.steps or []):
        if step["opened_at"] is not None:
            return step if step["closed_at"] is None else None
    return None


def submit_post(
    conn: Connection, round_row: Any, mine: Any, body: dict[str, Any], actor: Actor
) -> dict[str, Any]:
    lock_project(conn, round_row.project_id)
    round_row = _reload(conn, round_row.id)
    step = current_step(round_row)
    if (
        round_row.status != "exchange"
        or step is None
        or step["kind"] != body["step"]
        or _ended(step, clock.now())
    ):
        raise _state(round_row, step["kind"] if step else None, "that step is not open")
    me = mine.principal_id
    if me not in step["eligible"] or me not in _participants(conn, round_row):
        raise refused("not_eligible", "you may not post in this step")
    topic_id = body["topic_id"]
    if topic_id not in step["topics"]:
        raise invalid({"topic_id": "unknown_topic"})
    posts = round_row.posts or []
    if any(p["step_n"] == step["n"] and p["topic_id"] == topic_id and p["by"] == me for p in posts):
        raise _state(round_row, step["kind"], "one post per topic in a step")
    to = list(dict.fromkeys(body.get("to") or []))
    if to and step["kind"] not in ("response", "further"):
        raise invalid({"to": "responses_only"}, "only a response or a further step addresses")
    if to and (me in to or not set(to) <= set(_participants(conn, round_row))):
        raise invalid({"to": "not_a_participant"}, "address other current participants")
    in_reply_to = list(dict.fromkeys(body.get("in_reply_to") or []))
    if step["kind"] == "reply":
        addressed = {
            p["id"]
            for p in posts
            if p["step"] == "response" and p["topic_id"] == topic_id and me in p["to"]
        }
        if not in_reply_to or not set(in_reply_to) <= addressed:
            raise invalid({"in_reply_to": "not_addressed"}, "name the responses that addressed you")
    elif in_reply_to:
        raise invalid({"in_reply_to": "replies_only"})
    if step["kind"] == "rejoinder" and not _replied_to(posts, topic_id, me):
        raise refused("not_eligible", "your response on this topic received no reply")
    post_id = f"p{len(posts) + 1}"
    seq = _post_message(
        conn, round_row, body["body"], actor, topic_id=topic_id, step=step["kind"], post_id=post_id
    )
    post = {
        "id": post_id,
        "step": step["kind"],
        "step_n": step["n"],
        "kind": step["kind"],
        "topic_id": topic_id,
        "by": me,
        "to": to,
        "in_reply_to": in_reply_to,
        "body": body["body"],
        "message_seq": seq,
        "redaction": None,
    }
    conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.id == round_row.id)
        .values(posts=[*posts, post])
    )
    return post


def _replied_to(posts: list[dict[str, Any]], topic_id: str, author: str) -> bool:
    mine = {p["id"] for p in posts if p["step"] == "response" and p["by"] == author}
    return any(
        p["step"] == "reply" and p["topic_id"] == topic_id and mine & set(p["in_reply_to"])
        for p in posts
    )


# --- further steps (§20.5) --------------------------------------------------------------------


def add_step(
    conn: Connection,
    round_row: Any,
    mine: Any,
    reason: str,
    members: list[str] | None,
    topics: list[str] | None,
) -> Any:
    lock_project(conn, round_row.project_id)
    round_row = _reload(conn, round_row.id)
    if not _is_moderator(round_row, mine):
        raise refused("not_moderator", "only the round's moderator adds a step")
    steps = round_row.steps or []
    step = current_step(round_row)
    further = [s for s in steps if s["kind"] == "further"]
    if (
        round_row.status != "exchange"
        or step is None
        or _ended(step, clock.now())
        or any(s["opened_at"] is None for s in further)
        or len(further) >= FURTHER_MAX
    ):
        raise _state(round_row, step["kind"] if step else None, "no further step now")
    current = _participants(conn, round_row)
    named = list(dict.fromkeys(members)) if members is not None else current
    if not named or not set(named) <= set(current):
        raise invalid({"members": "not_a_participant"}, "name current participants")
    topic_ids = [topic["id"] for topic in round_row.statement["topics"]]
    on = list(dict.fromkeys(topics)) if topics is not None else topic_ids
    if not on or not set(on) <= set(topic_ids):
        raise invalid({"topics": "unknown_topic"})
    pending = {
        "n": None,
        "kind": "further",
        "opened_at": None,
        "closes_at": None,
        "closed_at": None,
        "reason": reason,
        "eligible": named,
        "topics": on,
    }
    conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.id == round_row.id)
        .values(steps=[*steps, pending])
    )
    return _reload(conn, round_row.id)


# --- the clock: steps close, the next opens, the exchange closes ------------------------------


CHAIN = {
    "statement": ("response", "reply", "rejoinder"),
    "response": ("reply", "rejoinder"),
    "reply": ("rejoinder",),
}


def _eligible(round_row: Any, kind: str, everyone: list[str]) -> tuple[list[str], list[str]]:
    """(members, topics) of a standard step, from the posts so far."""
    posts = round_row.posts or []
    if kind == "response":
        return everyone, [topic["id"] for topic in round_row.statement["topics"]]
    if kind == "reply":
        found = [p for p in posts if p["step"] == "response" and p["to"]]
        members = [m for p in found for m in p["to"]]
    else:  # rejoinder: the authors of responses that received a reply
        answered = {r for p in posts if p["step"] == "reply" for r in p["in_reply_to"]}
        found = [p for p in posts if p["step"] == "response" and p["id"] in answered]
        members = [p["by"] for p in found]
    return list(dict.fromkeys(members)), list(dict.fromkeys(p["topic_id"] for p in found))


def _close_current(conn: Connection, round_row: Any) -> None:
    """Close the open step and open the first one after it that has anyone eligible: the
    standard steps in order, then a pending further step. None left: the exchange closes."""
    now = clock.now()
    steps = [dict(s) for s in round_row.steps]
    opened = [s for s in steps if s["opened_at"] is not None]
    pending = next((s for s in steps if s["opened_at"] is None), None)
    done = opened[-1]
    done["closed_at"] = clock.rfc3339(now)
    if round_row.statement is None:  # no statement, no exchange (§20.5)
        _close_exchange(conn, round_row, opened)
        return
    current = _participants(conn, round_row)
    candidates: list[tuple[str, list[str], list[str], dict[str, Any] | None]] = [
        (kind, *_eligible(round_row, kind, current), None) for kind in CHAIN.get(done["kind"], ())
    ]
    if pending is not None:
        candidates.append(("further", pending["eligible"], pending["topics"], pending))
    for kind, members, topics, further in candidates:
        eligible = [m for m in members if m in current]
        if not eligible:
            continue  # a step with nobody eligible is not opened
        step = {
            "n": max(s["n"] for s in opened) + 1,
            "kind": kind,
            "opened_at": clock.rfc3339(now),
            "closes_at": clock.rfc3339(now + _window(round_row)),
            "closed_at": None,
            "reason": further["reason"] if further else None,
            "eligible": eligible,
            "topics": topics,
        }
        waiting = [pending] if pending is not None and further is None else []
        conn.execute(
            update(t.jour_fixe_round)
            .where(t.jour_fixe_round.c.id == round_row.id)
            .values(status="exchange", steps=[*opened, step, *waiting])
        )
        tokens = [w for m in eligible for w in rounds.wake_now(conn, round_row.project_id, m)]
        emit(
            conn,
            round_row.project_id,
            "jour_fixe_step_opened",
            tokens,
            {
                "round_id": round_row.id,
                "step": step["n"],
                "kind": kind,
                "topics": topics,
                "closes_at": step["closes_at"],
                "reason": step["reason"],
            },
            subject=("jour_fixe", round_row.id),
        )
        return
    _close_exchange(conn, round_row, opened)


def _close_exchange(conn: Connection, round_row: Any, steps: list[dict[str, Any]]) -> None:
    """The exchange is over, or never began: the thread closes, the report is due. A
    further step still pending never opens."""
    now = clock.now()
    hours = (round_row.config or rounds.defaults())["report_window_hours"]
    due = now + timedelta(hours=hours)
    conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.id == round_row.id)
        .values(status="reporting", steps=steps, exchange_closed_at=now, report_due_at=due)
    )
    if round_row.conversation_id:
        conversation = group_chats.find(conn, round_row.project_id, round_row.conversation_id)
        group_chats.close_thread(conn, conversation)
    emit(
        conn,
        round_row.project_id,
        "jour_fixe_exchange_closed",
        [
            *rounds.wake_now(conn, round_row.project_id, round_row.moderator["member_id"]),
            "role:owner",
        ],
        {"round_id": round_row.id, "report_due_at": clock.rfc3339(due)},
        subject=("jour_fixe", round_row.id),
    )


def handle_deadlines(conn: Connection, project_id: str) -> None:
    """Every step whose window ended closes; what follows opens at once."""
    now = clock.now()
    rows = conn.execute(
        select(t.jour_fixe_round).where(
            t.jour_fixe_round.c.project_id == project_id,
            t.jour_fixe_round.c.status.in_(("statement", "exchange")),
        )
    ).all()
    for row in rows:
        step = current_step(row)
        if step is not None and _ended(step, now):
            _close_current(conn, row)


# --- redaction of a round's message (§20.8) ---------------------------------------------------


def redact_copy(conn: Connection, marker: dict[str, Any], redaction: dict[str, Any]) -> None:
    """The round's copy of a redacted statement or post becomes a tombstone, in the same
    transaction as the message: the text null, `redaction` `{at, by, reason}`."""
    row = conn.execute(
        select(t.jour_fixe_round).where(t.jour_fixe_round.c.id == marker["round_id"])
    ).first()
    if row is None:
        return
    if marker["step"] == "statement" and row.statement is not None:
        topics = [
            {
                **topic,
                "title": None,
                "summary": None,
                "items": [{**item, "text": None} for item in topic["items"]],
                "proposals": [
                    {**p, "title": None, "reason": None, "redaction": redaction}
                    for p in topic["proposals"]
                ],
                "redaction": redaction,
            }
            for topic in row.statement["topics"]
        ]
        values: dict[str, Any] = {"statement": {**row.statement, "topics": topics}}
    else:
        values = {
            "posts": [
                (
                    {**p, "body": None, "redaction": redaction}
                    if p["id"] == marker.get("post_id")
                    else p
                )
                for p in row.posts
            ]
        }
    conn.execute(update(t.jour_fixe_round).where(t.jour_fixe_round.c.id == row.id).values(**values))
