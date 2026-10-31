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
from maity_hub.jourfixe import circle, schedule
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
            t.credential.c.dormant_since.is_(None),  # never chosen, as if not listening (§6.17)
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
    heard = listening.which((row.session_id for row in rows), conn)  # one read for all
    for row in rows:
        found[row.membership_id].append(
            {
                "instance": row.instance,
                "listening": row.session_id in heard,
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
    presences = availability.presences_of(conn, members)
    humans = availability.humans_of(conn, members)
    dormant = availability.dormants_of(conn, members)
    instances = _instances(conn, [m.id for m in members if m.agent_id is not None])
    found: dict[int, dict[str, Any]] = {}
    for member in members:
        state = availability.computed(
            member,
            presences[member.id],
            humans.get(member.human_id),
            project,
            now,
            dormant=member.id in dormant,
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


def moderator_order(conn: Connection, series_id: str, members: list[Any]) -> list[Any]:
    """The members holding the series' moderator right (§20.2), most minutes online in the last
    24 hours first, ties by handle and member id."""
    from maity_hub.jourfixe import series as series_mod

    holding = set(series_mod.moderators(conn, series_id))
    candidates = [m for m in members if m.id in holding]
    if not candidates:
        return []
    since = clock.now() - timedelta(hours=24)
    minutes: dict[int, int] = dict(
        conn.execute(
            select(t.presence_minute.c.membership_id, func.count())
            .where(
                t.presence_minute.c.membership_id.in_([c.id for c in candidates]),
                t.presence_minute.c.minute > since,
            )
            .group_by(t.presence_minute.c.membership_id)
        ).all()
    )
    who = _who(conn, candidates)
    return sorted(
        candidates,
        key=lambda m: (-int(minutes.get(m.id, 0)), who[m.id]["handle"] or "", _principal(m)),
    )


def record_presence(conn: Connection, now: datetime) -> None:
    """The minute's count for every agent membership with an instance `online` and every
    human membership `online` (§5.3: a call within 120 seconds or a long-poll open); older
    than a day is pruned. Shown to nobody (§20.2)."""
    from maity_hub import instances, listening

    minute = now.replace(second=0, microsecond=0)
    live = conn.execute(
        select(
            t.agent_session.c.membership_id,
            t.agent_session.c.id,
            t.agent_session.c.last_seen_at,
        ).where(t.agent_session.c.live.is_(True))
    ).all()
    heard = listening.which((session for _, session, _ in live), conn)
    found = {
        m
        for m, session, seen in live
        if instances.presence(seen, True, session in heard) == "online"
    }
    humans = conn.execute(
        select(t.membership).where(
            t.membership.c.active.is_(True), t.membership.c.human_id.isnot(None)
        )
    ).all()
    if humans:
        presences = availability.presences_of(conn, humans)
        found |= {h.id for h in humans if presences.get(h.id) == "online"}
    online = sorted(found)
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


def current(conn: Connection, series_id: str) -> Any | None:
    """The series' round that is not yet final; rounds of different series run side by
    side (§20.1)."""
    return conn.execute(
        select(t.jour_fixe_round).where(
            t.jour_fixe_round.c.series_id == series_id,
            t.jour_fixe_round.c.status.in_(OPEN),
        )
    ).first()


def _opted_out(conn: Connection, series_id: str) -> set[int]:
    return set(
        conn.execute(
            select(t.jour_fixe_opt_out.c.membership_id).where(
                t.jour_fixe_opt_out.c.series_id == series_id
            )
        ).scalars()
    )


def _in_circle(conn: Connection, series: Any, members: list[Any]) -> set[int]:
    """The memberships of the series' circle (§20.2): an owner with that owner's agents, the
    humans, or everyone."""
    if series.circle == "all":
        return {m.id for m in members}
    if series.circle == "humans":
        return {m.id for m in members if m.agent_id is None}
    owners = dict(
        conn.execute(
            select(t.agent_profile.c.id, t.agent_profile.c.owner_id).where(
                t.agent_profile.c.id.in_([m.agent_id for m in members if m.agent_id] or [""])
            )
        ).all()
    )
    return {
        m.id
        for m in members
        if m.human_id == series.circle_owner
        or (m.agent_id is not None and owners.get(m.agent_id) == series.circle_owner)
    }


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


def prepare(conn: Connection, project: Any, series: Any) -> dict[str, Any]:
    """Who would be invited, who moderates and who is absent, or `Refused` naming why the
    round cannot open now (§20.1, §20.2). The circle decides who is asked; a moderator
    outside it moderates and answers nothing."""
    if project.state in CLOSED_STATES:
        raise _refuse("project_closed", f"the project is {project.state}")
    running = current(conn, series.id)
    if running is not None:
        raise _refuse("jour_fixe_open", "an earlier round is not yet final", {"round": running.id})
    out = _opted_out(conn, series.id)
    members = [m for m in _members(conn, project.id) if m.id not in out]
    present = presence(conn, project, members)
    who = _who(conn, members)
    circle = _in_circle(conn, series, members)
    moderator = next(
        (m for m in moderator_order(conn, series.id, members) if present[m.id]["present"]), None
    )
    if moderator is None:
        raise _refuse("no_moderator", "nobody to moderate is present")
    invited = [m for m in members if m.id in circle and present[m.id]["present"]]
    taking_part = {m.id for m in invited} | {moderator.id}
    if len(taking_part) < 2 or not invited:
        raise _refuse("too_few", "fewer than two members are present")
    return {
        "moderator": {
            "member_id": _principal(moderator),
            "instance": present[moderator.id].get("instance"),
        },
        "moderator_entry": {
            **who[moderator.id],
            **({"instance": present[moderator.id]["instance"]} if moderator.agent_id else {}),
        },
        "invited": [
            {**who[m.id], **({"instance": present[m.id]["instance"]} if m.agent_id else {})}
            for m in invited
        ],
        "absent": [
            {**who[m.id], "absent_reason": present[m.id]["absent_reason"]}
            for m in members
            if m.id in circle and not present[m.id]["present"]
        ],
    }


def questions(
    config: dict[str, Any], topic: str, moderator_handle: str, close_at: datetime, local_date: date
) -> str:
    zone = ZoneInfo(config.get("timezone") or "UTC")
    local = close_at.astimezone(zone).strftime("%H:%M")
    utc = close_at.strftime("%H:%M")
    tz_name = config.get("timezone") or "UTC"
    return "\n".join(
        [
            f"Jour fixe {local_date.isoformat()} — {topic} — moderated by {moderator_handle}.",
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


def round_config(conn: Connection, series: Any) -> dict[str, Any]:
    """The series as it is at a round's start, without its moderators (§20.7 `config`)."""
    from maity_hub.jourfixe import series as series_mod

    shown = series_mod.view(conn, series)
    return {k: v for k, v in shown.items() if k not in ("moderators", "pending_moderators")}


def open_round(
    conn: Connection,
    project: Any,
    series: Any,
    *,
    trigger: str,
    scheduled_for: datetime,
    reason: str | None,
    actor: Actor | None,
) -> Any:
    """Open a round of the series now; `Refused` when it cannot (§20.1). The questions go out
    once, in `jour_fixe_opened`."""
    from maity_hub.jourfixe import exchange
    from maity_hub.jourfixe import series as series_mod

    lock_project(conn, project.id)
    config = round_config(conn, series)
    prepared = prepare(conn, project, series)
    now = clock.now()
    close_at = now + timedelta(minutes=config["answer_window_minutes"])
    round_id = new_id("jour_fixe")
    zone = ZoneInfo(config.get("timezone") or "UTC")
    day = now.astimezone(zone).date()
    conn.execute(
        insert(t.jour_fixe_round).values(
            id=round_id,
            project_id=project.id,
            series_id=series.id,
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
    # Every round runs in its own thread (§20.5), created once the round exists, so the
    # thread's view names it. The moderator is in it whether or not it is in the circle.
    people = [i["member_id"] for i in prepared["invited"]]
    if prepared["moderator"]["member_id"] not in people:
        people.append(prepared["moderator"]["member_id"])
    keeper = series.circle_owner if series.circle == "owner" else None
    thread = exchange.open_thread(conn, project, f"Jour fixe {day.isoformat()}", people, keeper)
    conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.id == round_id)
        .values(conversation_id=thread)
    )
    text = questions(config, series.topic, prepared["moderator_entry"]["handle"], close_at, day)
    audience = [*_wake_tokens(prepared["invited"]), *series_mod.keeper_tokens(conn, series)]
    emit(
        conn,
        project.id,
        "jour_fixe_opened",
        list(dict.fromkeys(audience)),
        {
            "round_id": round_id,
            "series_id": series.id,
            "topic": series.topic,
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
    series: Any,
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
            series_id=series.id,
            status=status,
            trigger="schedule",
            mode="chat",
            skip_reason=skip_reason,
            missed_slots=missed_slots,
            scheduled_for=slot,
            steps=[],
            config=round_config(conn, series),
            invited=[],
            absent=[],
            answers_received=0,
            posts=[],
            created_at=now,
        )
    )
    from maity_hub.jourfixe import series as series_mod

    emit(
        conn,
        project.id,
        "jour_fixe_skipped",
        series_mod.keeper_tokens(conn, series) or ["trust:owner"],
        {
            "round_id": round_id,
            "series_id": series.id,
            "status": status,
            "skip_reason": skip_reason,
            "scheduled_for": clock.rfc3339(slot),
            "missed_slots": missed_slots,
        },
        subject=("jour_fixe", round_id),
    )
    return round_id


def manual_starts_today(conn: Connection, series_id: str) -> int:
    """Rounds of the series started by hand in the last 24 hours (§20.1: at most 2)."""
    since = clock.now() - timedelta(hours=24)
    found: int = conn.execute(
        select(func.count())
        .select_from(t.jour_fixe_round)
        .where(
            t.jour_fixe_round.c.series_id == series_id,
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
        [
            *wake_now(conn, round_row.project_id, round_row.moderator["member_id"]),
            *circle.owners(round_row),
        ],
        {
            "round_id": round_row.id,
            "answers_received": round_row.answers_received,
            "statement_due_at": clock.rfc3339(statement_due),
        },
        subject=("jour_fixe", round_row.id),
    )


# --- the schedule's slots (§20.1) -------------------------------------------------------------


def anchor_date(series: Any) -> date:
    """The day the weekly interval counts from: the first occurrence after the schedule was
    last set, in its zone."""
    from maity_hub.jourfixe import series as series_mod

    policy = series_mod.schedule_of(series)
    set_at = series.anchor or clock.now()
    weekly_once = {**policy, "recurrence": {**policy["recurrence"], "interval": 1}}
    first = schedule.next_slot(weekly_once, set_at, set_at.date())
    zone = ZoneInfo(policy["timezone"])
    return (first or set_at).astimezone(zone).date()


def next_at(series: Any, now: datetime) -> datetime | None:
    """The series' next slot in UTC, or None when it opens none (§20.9)."""
    from maity_hub.jourfixe import series as series_mod

    policy = series_mod.schedule_of(series)
    if not policy["enabled"] or policy.get("recurrence") is None:
        return None
    return schedule.next_slot(policy, now, anchor_date(series))


def due_slots(series: Any, now: datetime) -> list[datetime]:
    """The series' slots between the last one handled and now."""
    from maity_hub.jourfixe import series as series_mod

    policy = series_mod.schedule_of(series)
    if not policy["enabled"] or policy.get("recurrence") is None:
        return []
    after = series.last_slot or series.anchor or now
    return schedule.slots_between(policy, after, now, anchor_date(series))


def handle_schedule(conn: Connection, project_id: str) -> None:
    """Open, skip or record as missed each series' due slots (§20.1): a slot noticed more than
    10 minutes late is missed, all such slots of a series in one record with `missed_slots`."""
    from maity_hub.jourfixe import moderators
    from maity_hub.jourfixe import series as series_mod

    project = lock_project(conn, project_id)
    moderators.end_gone(conn, project)  # rights whose member, owner or freedom went (§20.2)
    moderators.file_missing(conn, project)  # the upgrade's consents still to file (§20.1)
    now = clock.now()
    for series in series_mod.of_project(conn, project_id):
        if (
            series.circle == "owner"
            and series.enabled
            and not series_mod.owner_member(conn, series)
        ):
            # The owner left: the series opens no round until they return (§20.1).
            conn.execute(
                update(t.jour_fixe_series)
                .where(t.jour_fixe_series.c.id == series.id)
                .values(enabled=False)
            )
            continue
        slots = due_slots(series, now)
        if not slots:
            continue
        conn.execute(
            update(t.jour_fixe_series)
            .where(t.jour_fixe_series.c.id == series.id)
            .values(last_slot=slots[-1])
        )
        late = [s for s in slots if now - s > LATE]
        timely = [s for s in slots if now - s <= LATE]
        if late:
            record_skip(
                conn,
                project,
                series,
                slot=late[-1],
                status="missed",
                skip_reason="hub_down",
                missed_slots=len(late),
            )
        for slot in timely[-1:]:  # several at once only after an outage: the newest counts
            try:
                with conn.begin_nested():
                    open_round(
                        conn,
                        project,
                        series,
                        trigger="schedule",
                        scheduled_for=slot,
                        reason=None,
                        actor=None,
                    )
            except Refused as refused:
                reason = "round_open" if refused.code == "jour_fixe_open" else refused.code
                record_skip(conn, project, series, slot=slot, status="skipped", skip_reason=reason)


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
    from maity_hub.jourfixe import exchange, triage

    exchange.handle_deadlines(conn, project_id)
    triage.handle_deadlines(conn, project_id)
