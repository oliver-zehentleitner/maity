"""Jour fixe rounds (docs/api.md §20.1–§20.3, §20.7): who is present, who moderates, how a
round opens, is skipped or missed, and how its answer window closes.

A round opens with the moderator and the present members recorded as invited, each agent
with the instance its team's `wake` rule selects; the questions go out once, in
`jour_fixe_opened`. Absent members are not asked, not woken and not chased.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, delete, func, insert, or_, select, update

from maity_hub import availability, clock
from maity_hub import tables as t
from maity_hub.errors import ApiError
from maity_hub.events import Actor, emit, lock_project
from maity_hub.ids import new_id
from maity_hub.jourfixe import schedule
from maity_hub.policy import CLOSED_STATES

OPEN = ("answering", "statement", "exchange", "reporting")  # not yet final
MANUAL_PER_DAY = 2
LATE = timedelta(minutes=10)  # a slot noticed later than this was missed
QUESTIONS = (
    "1. What went well?",
    "2. What went badly?",
    "3. What would help, or how would you improve it?",
)


def defaults() -> dict[str, Any]:
    return schedule.filled({})


# --- who is present (§20.2) -------------------------------------------------------------------


def _instances(conn: Connection, membership_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """Per agent membership its active instances with a live session: whether it listens,
    when it last called, and how many cards it holds."""
    from maity_hub import listening

    if not membership_ids:
        return {}
    rows = conn.execute(
        select(
            t.credential.c.membership_id,
            t.credential.c.instance,
            t.agent_session.c.id.label("session_id"),
            t.agent_session.c.last_seen_at,
        )
        .join(t.agent_session, t.agent_session.c.credential_id == t.credential.c.id)
        .where(
            t.credential.c.membership_id.in_(membership_ids),
            t.credential.c.revoked_at.is_(None),
            t.agent_session.c.live.is_(True),
        )
    ).all()
    claims: dict[tuple[int, str], int] = {}
    for holder, instance, count in conn.execute(
        select(t.card.c.claim_holder, t.card.c.claim_instance, func.count())
        .where(
            t.card.c.claim_holder.in_(membership_ids),
            t.card.c.status.notin_(("done", "cancelled")),
        )
        .group_by(t.card.c.claim_holder, t.card.c.claim_instance)
    ):
        claims[(holder, instance)] = count
    found: dict[int, list[dict[str, Any]]] = {m: [] for m in membership_ids}
    for row in rows:
        found[row.membership_id].append(
            {
                "instance": row.instance,
                "listening": listening.is_listening(row.session_id),
                "last_seen_at": row.last_seen_at,
                "claims": claims.get((row.membership_id, row.instance), 0),
            }
        )
    return found


def selected_instance(member: Any, instances: list[dict[str, Any]]) -> str | None:
    """The listening instance the team's `wake` rule selects (§20.2, §6.18): under `lead`
    the lead; under `next_free` the one holding the fewest claims, ties to the one idle
    longest; under `all` the one with the most recent call. None when none listens."""
    listening = [i for i in instances if i["listening"]]
    if not listening:
        return None
    if member.wake == "lead":
        lead = [i for i in listening if i["instance"] == member.lead_instance]
        return str(lead[0]["instance"]) if lead else None
    if member.wake == "next_free":
        chosen = min(listening, key=lambda i: (i["claims"], i["last_seen_at"], i["instance"]))
        return str(chosen["instance"])
    chosen = max(listening, key=lambda i: (i["last_seen_at"], i["instance"]))
    return str(chosen["instance"])


def presence(conn: Connection, project: Any, members: list[Any]) -> dict[int, dict[str, Any]]:
    """Per membership `{present, instance?, absent_reason?}` as §20.2 defines present."""
    now = clock.now()
    # Public as `presences_of`/`humans_of` once the cover PR (#285) lands.
    presences = availability._presences(conn, members)
    humans = availability._humans(conn, members)
    instances = _instances(conn, [m.id for m in members if m.agent_id is not None])
    found: dict[int, dict[str, Any]] = {}
    for member in members:
        state = availability.computed(
            member, presences[member.id], humans.get(member.human_id), project, now
        )["state"]
        if state != "available":
            found[member.id] = {"present": False, "absent_reason": "not_available"}
        elif member.agent_id is None:
            online = presences[member.id] == "online"
            found[member.id] = (
                {"present": True} if online else {"present": False, "absent_reason": "not_online"}
            )
        else:
            instance = selected_instance(member, instances.get(member.id, []))
            found[member.id] = (
                {"present": True, "instance": instance}
                if instance is not None
                else {"present": False, "absent_reason": "no_listening_instance"}
            )
    return found


# --- the moderator order (§20.2) --------------------------------------------------------------


def admin_agents_only(conn: Connection, project_id: str, order: list[str]) -> bool:
    """Whether every id names an active agent member with the role `admin`."""
    agents = set(
        conn.execute(
            select(t.membership.c.agent_id).where(
                t.membership.c.project_id == project_id,
                t.membership.c.active.is_(True),
                t.membership.c.role == "admin",
                t.membership.c.agent_id.isnot(None),
            )
        ).scalars()
    )
    return all(m in agents for m in order)


def _handles(conn: Connection, agent_ids: list[str]) -> dict[str, str]:
    if not agent_ids:
        return {}
    return {
        r.id: r.handle
        for r in conn.execute(
            select(t.agent_profile.c.id, t.agent_profile.c.handle).where(
                t.agent_profile.c.id.in_(agent_ids)
            )
        )
    }


def moderator_order(conn: Connection, project: Any) -> list[Any]:
    """The admin agents in moderating order: an explicit list first, then by minutes
    online in the last 24 hours, most first, ties by handle and member id."""
    admins = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project.id,
            t.membership.c.active.is_(True),
            t.membership.c.role == "admin",
            t.membership.c.agent_id.isnot(None),
        )
    ).all()
    since = clock.now() - timedelta(hours=24)
    minutes: dict[int, int] = dict(
        conn.execute(
            select(t.presence_minute.c.membership_id, func.count())
            .where(
                t.presence_minute.c.membership_id.in_([a.id for a in admins] or [-1]),
                t.presence_minute.c.minute > since,
            )
            .group_by(t.presence_minute.c.membership_id)
        ).all()
    )
    handles = _handles(conn, [a.agent_id for a in admins])
    by_default = sorted(
        admins, key=lambda a: (-int(minutes.get(a.id, 0)), handles[a.agent_id], a.agent_id)
    )
    explicit = project.jour_fixe_moderators or []
    first = [a for agent_id in explicit for a in admins if a.agent_id == agent_id]
    return first + [a for a in by_default if a not in first]


def record_presence(conn: Connection, now: datetime) -> None:
    """The minute's count for every agent membership with an instance `online` (§5.3: a
    call within 120 seconds or a long-poll open); older than a day is pruned. Shown to
    nobody (§20.2)."""
    from maity_hub import instances, listening

    minute = now.replace(second=0, microsecond=0)
    live = conn.execute(
        select(
            t.agent_session.c.membership_id,
            t.agent_session.c.id,
            t.agent_session.c.last_seen_at,
        ).where(t.agent_session.c.live.is_(True))
    ).all()
    online = sorted(
        {
            m
            for m, session, seen in live
            if instances.presence(seen, True, listening.is_listening(session)) == "online"
        }
    )
    known = set(
        conn.execute(
            select(t.presence_minute.c.membership_id).where(t.presence_minute.c.minute == minute)
        ).scalars()
    )
    for membership_id in online:
        if membership_id not in known:
            conn.execute(
                insert(t.presence_minute).values(membership_id=membership_id, minute=minute)
            )
    conn.execute(
        delete(t.presence_minute).where(t.presence_minute.c.minute < now - timedelta(hours=25))
    )


# --- opening, skipping, missing (§20.1, §20.3) -----------------------------------------------


class Refused(ApiError):
    """A round that cannot open: a manual start answers it, a scheduled slot records it."""


def _refuse(code: str, message: str, details: dict[str, Any] | None = None) -> Refused:
    return Refused(409, code, message, details)


def current(conn: Connection, project_id: str) -> Any | None:
    """The round that is not yet final."""
    return conn.execute(
        select(t.jour_fixe_round).where(
            t.jour_fixe_round.c.project_id == project_id,
            t.jour_fixe_round.c.status.in_(OPEN),
        )
    ).first()


def _members(conn: Connection, project_id: str) -> list[Any]:
    return list(
        conn.execute(
            select(t.membership)
            .where(t.membership.c.project_id == project_id, t.membership.c.active.is_(True))
            .order_by(t.membership.c.id)
        ).all()
    )


def _principal(row: Any) -> str:
    return str(row.agent_id or row.human_id)


def _who(conn: Connection, rows: list[Any]) -> dict[int, dict[str, Any]]:
    """`{member_id, kind, handle}` per membership row."""
    agents = _handles(conn, [r.agent_id for r in rows if r.agent_id])
    humans_ids = [r.human_id for r in rows if r.human_id]
    humans = (
        dict(
            conn.execute(
                select(t.human.c.id, t.human.c.handle).where(t.human.c.id.in_(humans_ids))
            ).all()
        )
        if humans_ids
        else {}
    )
    return {
        r.id: {
            "member_id": _principal(r),
            "kind": "agent" if r.agent_id else "human",
            "handle": agents.get(r.agent_id) if r.agent_id else humans.get(r.human_id),
        }
        for r in rows
    }


def prepare(conn: Connection, project: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Who would be invited, who moderates and who is absent, or `Refused` naming why the
    round cannot open now."""
    if project.state in CLOSED_STATES:
        raise _refuse("project_closed", f"the project is {project.state}")
    running = current(conn, project.id)
    if running is not None:
        raise _refuse("jour_fixe_open", "an earlier round is not yet final", {"round": running.id})
    members = _members(conn, project.id)
    present = presence(conn, project, members)
    who = _who(conn, members)
    if config["moderator"] == "admin_agent":
        candidates = moderator_order(conn, project)
    else:
        candidates = [m for m in members if _principal(m) == config["moderator"]]
    moderator = next((m for m in candidates if present[m.id]["present"]), None)
    if moderator is None:
        raise _refuse("no_moderator", "nobody to moderate is present")
    invited = [m for m in members if present[m.id]["present"]]
    if len(invited) < 2:
        raise _refuse("too_few", "fewer than two members are present")
    return {
        "moderator": {
            "member_id": _principal(moderator),
            "instance": present[moderator.id].get("instance"),
        },
        "invited": [
            {**who[m.id], **({"instance": present[m.id]["instance"]} if m.agent_id else {})}
            for m in invited
        ],
        "absent": [
            {**who[m.id], "absent_reason": present[m.id]["absent_reason"]}
            for m in members
            if not present[m.id]["present"]
        ],
    }


def questions(
    config: dict[str, Any], moderator_handle: str, close_at: datetime, local_date: date
) -> str:
    zone = ZoneInfo(config.get("timezone") or "UTC")
    local = close_at.astimezone(zone).strftime("%H:%M")
    utc = close_at.strftime("%H:%M")
    tz_name = config.get("timezone") or "UTC"
    return "\n".join(
        [
            f"Jour fixe {local_date.isoformat()}, moderated by {moderator_handle}. "
            "Your answer goes to the moderator only.",
            f"Answer by {local} {tz_name} ({utc}Z), or not at all — both are fine.",
            *QUESTIONS,
            "You may answer anonymously.",
        ]
    )


def _wake_tokens(entries: list[dict[str, Any]]) -> list[str]:
    """`instance:<member>#<id>` of each agent's selected instance, `member:` of a human."""
    tokens = []
    for entry in entries:
        if entry["kind"] == "agent":
            tokens.append(f"instance:{entry['member_id']}#{entry['instance']}")
        else:
            tokens.append(f"member:{entry['member_id']}")
    return tokens


def open_round(
    conn: Connection,
    project: Any,
    *,
    trigger: str,
    scheduled_for: datetime,
    reason: str | None,
    actor: Actor | None,
) -> Any:
    """Open a round now with the policy as it is, or the defaults when it has none; `Refused`
    when it cannot (§20.1). The questions go out once, in `jour_fixe_opened`."""
    lock_project(conn, project.id)
    config = project.jour_fixe or defaults()
    prepared = prepare(conn, project, config)
    now = clock.now()
    close_at = now + timedelta(minutes=config["answer_window_minutes"])
    round_id = new_id("jour_fixe")
    from maity_hub.jourfixe import exchange

    zone = ZoneInfo(config.get("timezone") or "UTC")
    day = now.astimezone(zone).date()
    conn.execute(
        insert(t.jour_fixe_round).values(
            id=round_id,
            project_id=project.id,
            status="answering",
            trigger=trigger,
            mode="chat",
            reason=reason,
            scheduled_for=scheduled_for,
            opened_at=now,
            answers_close_at=close_at,
            steps=[],
            config=config,
            moderator=prepared["moderator"],
            invited=prepared["invited"],
            absent=prepared["absent"],
            answers_received=0,
            posts=[],
            tag_key=secrets.token_hex(32),
            created_at=now,
        )
    )
    # This hub runs group chats: every round runs in its own thread (§20.5), created once
    # the round exists, so the thread's view names it.
    thread = exchange.open_thread(
        conn, project, f"Jour fixe {day.isoformat()}", [i["member_id"] for i in prepared["invited"]]
    )
    conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.id == round_id)
        .values(conversation_id=thread)
    )
    moderator_entry = next(
        i for i in prepared["invited"] if i["member_id"] == prepared["moderator"]["member_id"]
    )
    text = questions(config, moderator_entry["handle"], close_at, day)
    emit(
        conn,
        project.id,
        "jour_fixe_opened",
        [*_wake_tokens(prepared["invited"]), "role:owner"],
        {
            "round_id": round_id,
            "moderator": prepared["moderator"]["member_id"],
            "questions": text,
            "answers_close_at": clock.rfc3339(close_at),
        },
        actor=actor,
        subject=("jour_fixe", round_id),
    )
    return conn.execute(select(t.jour_fixe_round).where(t.jour_fixe_round.c.id == round_id)).one()


def record_skip(
    conn: Connection,
    project: Any,
    *,
    slot: datetime,
    status: str,
    skip_reason: str,
    missed_slots: int | None = None,
) -> str:
    """A scheduled slot that does not run (§20.1): recorded, never caught up, and told
    with `jour_fixe_skipped`."""
    now = clock.now()
    round_id = new_id("jour_fixe")
    conn.execute(
        insert(t.jour_fixe_round).values(
            id=round_id,
            project_id=project.id,
            status=status,
            trigger="schedule",
            mode="chat",
            skip_reason=skip_reason,
            missed_slots=missed_slots,
            scheduled_for=slot,
            steps=[],
            config=project.jour_fixe,
            invited=[],
            absent=[],
            answers_received=0,
            posts=[],
            created_at=now,
        )
    )
    emit(
        conn,
        project.id,
        "jour_fixe_skipped",
        ["role:owner", "role:admin"],
        {
            "round_id": round_id,
            "status": status,
            "skip_reason": skip_reason,
            "scheduled_for": clock.rfc3339(slot),
            "missed_slots": missed_slots,
        },
        subject=("jour_fixe", round_id),
    )
    return round_id


def manual_starts_today(conn: Connection, project_id: str) -> int:
    since = clock.now() - timedelta(hours=24)
    found: int = conn.execute(
        select(func.count())
        .select_from(t.jour_fixe_round)
        .where(
            t.jour_fixe_round.c.project_id == project_id,
            t.jour_fixe_round.c.trigger == "manual",
            t.jour_fixe_round.c.created_at > since,
        )
    ).scalar_one()
    return found


def wake_now(conn: Connection, project_id: str, member_id: str) -> list[str]:
    """Whom a later step wakes for a member: a human as `member:`, an agent at the instance
    its team's rule selects now, never the one recorded at the opening; nobody when no
    instance listens (§20.2)."""
    member = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project_id,
            or_(t.membership.c.agent_id == member_id, t.membership.c.human_id == member_id),
            t.membership.c.active.is_(True),
        )
    ).first()
    if member is None:
        return []
    if member.agent_id is None:
        return [f"member:{member_id}"]
    instance = selected_instance(member, _instances(conn, [member.id])[member.id])
    return [f"instance:{member_id}#{instance}"] if instance is not None else []


# --- the answer window closes (§20.4, §20.5) ------------------------------------------------


def close_answers(conn: Connection, round_row: Any) -> None:
    """Destroy the round's key and every tag: from now on nothing in the hub's live state
    links an anonymous answer to its author. Then wake the moderator for the statement."""
    now = clock.now()
    step_window = timedelta(minutes=(round_row.config or defaults())["step_window_minutes"])
    statement_due = now + step_window
    steps = [
        {
            "n": 1,
            "kind": "statement",
            "opened_at": clock.rfc3339(now),
            "closes_at": clock.rfc3339(statement_due),
            "closed_at": None,
            "reason": None,
            "eligible": [round_row.moderator["member_id"]],
        }
    ]
    won = conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.id == round_row.id, t.jour_fixe_round.c.status == "answering")
        .values(status="statement", tag_key=None, steps=steps)
    ).rowcount
    if won != 1:
        return
    conn.execute(delete(t.jour_fixe_tag).where(t.jour_fixe_tag.c.round_id == round_row.id))
    conn.execute(
        update(t.jour_fixe_answer)
        .where(t.jour_fixe_answer.c.round_id == round_row.id)
        .values(tag=None)
    )
    emit(
        conn,
        round_row.project_id,
        "jour_fixe_answers_closed",
        [*wake_now(conn, round_row.project_id, round_row.moderator["member_id"]), "role:owner"],
        {
            "round_id": round_row.id,
            "answers_received": round_row.answers_received,
            "statement_due_at": clock.rfc3339(statement_due),
        },
        subject=("jour_fixe", round_row.id),
    )


# --- the schedule's slots (§20.1) -------------------------------------------------------------


def anchor_date(project: Any) -> date:
    """The day the weekly interval counts from: the first occurrence after the schedule
    was last set, in its zone."""
    policy = project.jour_fixe
    set_at = project.jour_fixe_anchor or clock.now()
    weekly_once = {**policy, "recurrence": {**policy["recurrence"], "interval": 1}}
    first = schedule.next_slot(weekly_once, set_at, set_at.date())
    zone = ZoneInfo(policy["timezone"])
    return (first or set_at).astimezone(zone).date()


def due_slots(project: Any, now: datetime) -> list[datetime]:
    """The slots between the last one handled and now."""
    policy = project.jour_fixe
    if not policy or not policy.get("enabled"):
        return []
    after = project.jour_fixe_last_slot or project.jour_fixe_anchor or now
    return schedule.slots_between(policy, after, now, anchor_date(project))


def handle_schedule(conn: Connection, project_id: str) -> None:
    """Open, skip or record as missed the project's due slots (§20.1): a slot noticed more
    than 10 minutes late is missed, all such slots in one record with `missed_slots`."""
    project = lock_project(conn, project_id)
    now = clock.now()
    slots = due_slots(project, now)
    if not slots:
        return
    conn.execute(
        update(t.project).where(t.project.c.id == project.id).values(jour_fixe_last_slot=slots[-1])
    )
    late = [s for s in slots if now - s > LATE]
    timely = [s for s in slots if now - s <= LATE]
    if late:
        record_skip(
            conn,
            project,
            slot=late[-1],
            status="missed",
            skip_reason="hub_down",
            missed_slots=len(late),
        )
    for slot in timely[-1:]:  # several at once only after an outage: the newest counts
        try:
            with conn.begin_nested():
                open_round(
                    conn, project, trigger="schedule", scheduled_for=slot, reason=None, actor=None
                )
        except Refused as refused:
            reason = "round_open" if refused.code == "jour_fixe_open" else refused.code
            record_skip(conn, project, slot=slot, status="skipped", skip_reason=reason)


def handle_deadlines(conn: Connection, project_id: str) -> None:
    """Act on every deadline that passed, the ones the hub slept through included."""
    lock_project(conn, project_id)
    now = clock.now()
    due = conn.execute(
        select(t.jour_fixe_round).where(
            t.jour_fixe_round.c.project_id == project_id,
            t.jour_fixe_round.c.status == "answering",
            t.jour_fixe_round.c.answers_close_at <= now,
        )
    ).all()
    for round_row in due:
        close_answers(conn, round_row)
    from maity_hub.jourfixe import exchange

    exchange.handle_deadlines(conn, project_id)
