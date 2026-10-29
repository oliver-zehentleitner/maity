"""Redaction in a round (docs/api.md §20.8): one rule for every copy.

Redacting a text tombstones it everywhere the hub derived it from that text, in the same
transaction. The statement and the posts are messages and are redacted through them
(`exchange.redact_copy`); an answer, the report's summary, a finding and a report
proposal through `POST …/rounds/{id}/redact`. A report proposal's text travels further:
into its decision request and that request's events, into the card an adoption opened
and the events that carry its title, and into `jour_fixe_reported`. A text a person
rephrased by hand is not a derived copy; it is a target of its own.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.board import history
from maity_hub.errors import ApiError, invalid, not_found
from maity_hub.events import Actor, emit, lock_project
from maity_hub.jourfixe import answers
from maity_hub.jourfixe.answers import refused
from maity_hub.scopes import in_admin_team

REDACTED_TITLE = "[redacted jour fixe proposal]"
REDACTED_TEXT = "[redacted]"


def mark(reason: str, by: str) -> dict[str, Any]:
    """A round copy's `redaction`."""
    return {"at": clock.rfc3339(clock.now()), "by": by, "reason": reason}


def _reload(conn: Connection, round_id: str) -> Any:
    return conn.execute(select(t.jour_fixe_round).where(t.jour_fixe_round.c.id == round_id)).one()


# --- events -----------------------------------------------------------------------------------


def _tombstone_event(conn: Connection, seq: int, redaction: dict[str, Any], actor: Any) -> None:
    """Replace one event's payload with §8.5's tombstone and announce it to the event's
    own audience; an event already redacted is left as it is."""
    row = conn.execute(select(t.event).where(t.event.c.seq == seq)).first()
    if row is None or row.redacted:
        return
    tombstone = {"redacted": True, **redaction}
    won = conn.execute(
        update(t.event)
        .where(t.event.c.seq == seq, t.event.c.redacted.is_(False))
        .values(payload=tombstone, redacted=True)
    ).rowcount
    if won == 1:
        emit(
            conn,
            row.project_id,
            "event_redacted",
            list(row.audience or []),
            {"seq": seq, "reason": redaction["reason"]},
            actor=actor,
            subject=("event", str(seq)),
            conversation_id=row.conversation_id,
        )


def _events_of(conn: Connection, subject: tuple[str, str], kinds: tuple[str, ...]) -> list[Any]:
    return list(
        conn.execute(
            select(t.event).where(
                t.event.c.subject_type == subject[0],
                t.event.c.subject_id == subject[1],
                t.event.c.kind.in_(kinds),
            )
        )
    )


# --- a report proposal and everything copied from it -------------------------------------------


def _card_of(conn: Connection, round_id: str, proposal_id: str) -> Any:
    """The card an adoption of the proposal opened, by its `jour_fixe` mark."""
    rows = conn.execute(select(t.card).where(t.card.c.jour_fixe.isnot(None))).all()
    return next(
        (
            r
            for r in rows
            if r.jour_fixe.get("round_id") == round_id
            and r.jour_fixe.get("proposal_id") == proposal_id
        ),
        None,
    )


def _redact_request(
    conn: Connection, request_id: str, redaction: dict[str, Any], actor: Any
) -> None:
    """The decision request: title the placeholder, summary gone; its created and
    answered events tombstoned."""
    conn.execute(
        update(t.request)
        .where(t.request.c.id == request_id)
        .values(title=REDACTED_TITLE, summary=None)
    )
    for event in _events_of(conn, ("request", request_id), ("request_created", "request_answered")):
        _tombstone_event(conn, event.seq, redaction, actor)


def _redact_card(
    conn: Connection,
    card: Any,
    texts: tuple[str, str | None, str, str],
    redaction: dict[str, Any],
    actor: Any,
) -> None:
    """While the card still carries the hub's text: its title the placeholder and the
    reason in its body `[redacted]`, as hub edits; every history entry holding them
    redacted as §6.15 redacts one, and `task.title` in the card's mention and note events
    written under that title, each rewritten event announced.

    `texts` is (title, reason, the body the hub wrote, that body with the placeholder):
    a title or body that is no longer exactly the hub's was edited by a person since."""
    title, reason, hub_body, placeholder_body = texts
    changes: dict[str, Any] = {}
    if card.title == title:
        changes["title"] = REDACTED_TITLE
    if reason and card.body == hub_body:
        changes["body"] = placeholder_body
    if changes:
        conn.execute(
            update(t.card).where(t.card.c.id == card.id).values(**changes, updated_at=clock.now())
        )
        from maity_hub.routes.tasks import audience

        emit(  # the hub's own edit: an event only, no history entry (§6.15)
            conn,
            card.project_id,
            "task_updated",
            audience(conn, card),
            {"id": card.id, "fields": sorted(changes), "history": []},
            actor=None,
            subject=("task", card.id),
        )
    tombstone = {"redacted": True, **redaction}
    entries = conn.execute(
        select(t.card_history).where(
            t.card_history.c.card_id == card.id,
            t.card_history.c.field.in_(("created", "title", "body")),
            t.card_history.c.redacted.is_(False),
        )
    ).all()
    rewritten: set[int] = set()  # one write's event holds several entries: one notice
    for entry in entries:
        held = list(_strings((entry.before, entry.after)))
        holds = any(title in text or (reason and reason in text) for text in held)
        if holds and history.redact(conn, entry, tombstone) and entry.event_seq is not None:
            rewritten.add(entry.event_seq)
    for seq in sorted(rewritten):
        _announce(conn, seq, redaction, actor)
    for event in _events_of(conn, ("task", card.id), ("mentioned", "note_added")):
        task = (event.payload or {}).get("task") or {}
        if not event.redacted and task.get("title") == title:
            payload = {**event.payload, "task": {**task, "title": tombstone}}
            conn.execute(update(t.event).where(t.event.c.seq == event.seq).values(payload=payload))
            _announce(conn, event.seq, redaction, actor)


def _announce(conn: Connection, seq: int, redaction: dict[str, Any], actor: Any) -> None:
    """`event_redacted` for an event whose values a redaction rewrote, to the event's own
    audience (§8.5, §20.8)."""
    row = conn.execute(select(t.event).where(t.event.c.seq == seq)).one()
    emit(
        conn,
        row.project_id,
        "event_redacted",
        list(row.audience or []),
        {"seq": seq, "reason": redaction["reason"]},
        actor=actor,
        subject=("event", str(seq)),
        conversation_id=row.conversation_id,
    )


def _strings(value: Any) -> Iterator[str]:
    """Every string a stored value holds, however deep, as it is stored."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def redact_proposal(
    conn: Connection, round_row: Any, proposal_id: str, redaction: dict[str, Any], actor: Any
) -> bool:
    """A report proposal and every copy of it; False when it was redacted already."""
    report = round_row.report
    proposal = next((p for p in report["proposals"] if p["id"] == proposal_id), None)
    if proposal is None or proposal["redaction"] is not None:
        return False
    title, reason = proposal["title"], proposal.get("reason")
    report = {
        **report,
        "proposals": [
            (
                {**p, "title": None, "reason": None, "redaction": redaction}
                if p["id"] == proposal_id
                else p
            )
            for p in report["proposals"]
        ],
    }
    conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.id == round_row.id)
        .values(report=report)
    )
    if proposal.get("request_id"):
        _redact_request(conn, proposal["request_id"], redaction, actor)
    card = _card_of(conn, round_row.id, proposal_id)
    if card is not None:
        from maity_hub.jourfixe.triage import card_body

        texts = (
            title,
            reason,
            card_body(round_row, proposal),
            card_body(round_row, {"reason": REDACTED_TEXT}),
        )
        _redact_card(conn, card, texts, redaction, actor)
    for event in _events_of(conn, ("jour_fixe", round_row.id), ("jour_fixe_reported",)):
        _tombstone_event(conn, event.seq, redaction, actor)
    return True


# --- the statement's derived copies (§20.8) -----------------------------------------------------


def statement_redacted(
    conn: Connection,
    round_id: str,
    topic_ids: list[str],
    proposal_ids: list[str],
    redaction: dict[str, Any],
    actor: Any,
) -> None:
    """After the statement's message was redacted: the hub-built findings derived from its
    topics, and the report proposals drawn from its proposals, with all they reach."""
    round_row = _reload(conn, round_id)
    if round_row.report is None:
        return
    derived = {f"topic:{topic_id}" for topic_id in topic_ids}
    findings = [
        {**f, "text": None, "redaction": redaction} if f.get("derived_from") in derived else f
        for f in round_row.report["findings"]
    ]
    conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.id == round_id)
        .values(report={**round_row.report, "findings": findings})
    )
    for proposal in _reload(conn, round_id).report["proposals"]:
        if proposal.get("statement_proposal_id") in proposal_ids:
            redact_proposal(conn, _reload(conn, round_id), proposal["id"], redaction, actor)


# --- POST …/rounds/{id}/redact ------------------------------------------------------------------


def _answer_readers(conn: Connection, round_row: Any, row: Any) -> list[str]:
    """§20.3's readers by `member:`: the moderator, the human owners and admins, and a
    named answer's author; never the author of an anonymous one."""
    humans = conn.execute(
        select(t.membership.c.human_id).where(
            t.membership.c.project_id == round_row.project_id,
            t.membership.c.active.is_(True),
            t.membership.c.human_id.isnot(None),
            t.membership.c.trust.in_(("owner", "admin")),
        )
    ).scalars()
    tokens = [f"member:{round_row.moderator['member_id']}", *(f"member:{h}" for h in humans)]
    if not row.anonymous and row.author is not None:
        author = conn.execute(select(t.membership).where(t.membership.c.id == row.author)).one()
        tokens.append(f"member:{author.agent_id or author.human_id}")
    return list(dict.fromkeys(tokens))


def _invited(round_row: Any, mine: Any) -> bool:
    return any(i["member_id"] == mine.principal_id for i in round_row.invited)


def _redact_answer(
    conn: Connection, round_row: Any, mine: Any, answer_id: str, reason: str, actor: Actor
) -> None:
    row = conn.execute(
        select(t.jour_fixe_answer).where(
            t.jour_fixe_answer.c.id == answer_id, t.jour_fixe_answer.c.round_id == round_row.id
        )
    ).first()
    own = row is not None and not row.anonymous and row.author == mine.id
    if row is None or not (answers.readers_see_all(round_row, mine) or own):
        raise not_found()  # what the caller cannot read does not exist for it (§8.5)
    moderator = mine.principal_id == round_row.moderator["member_id"]
    human = mine.kind == "human"
    if row.anonymous:
        allowed = (
            moderator
            or (human and mine.may("events:admin"))
            or (
                human
                and in_admin_team(mine.trust, mine.role)
                and not answers.window_open(round_row)
            )
        )
    else:
        allowed = moderator or (human and (own or mine.may("events:admin")))
    if not allowed:
        if not human:
            raise refused("humans_only", "an agent redacts only as the round's moderator")
        raise ApiError(
            403, "forbidden", "you may not redact this answer", {"scope": "events:admin"}
        )
    if row.redaction is not None:
        return
    redaction = mark(reason, mine.principal_id)
    won = conn.execute(
        update(t.jour_fixe_answer)
        .where(t.jour_fixe_answer.c.id == row.id, t.jour_fixe_answer.c.redaction.is_(None))
        .values(went_well=None, went_badly=None, would_help=None, redaction=redaction)
    ).rowcount
    if won == 1:
        emit(
            conn,
            round_row.project_id,
            "event_redacted",
            _answer_readers(conn, round_row, row),
            {"round_id": round_row.id, "target": f"answer:{row.id}", "reason": reason},
            actor=actor,
            subject=("jour_fixe", round_row.id),
        )


def redact(
    conn: Connection, round_row: Any, mine: Any, target: str, reason: str, actor: Actor
) -> None:
    lock_project(conn, round_row.project_id)
    round_row = _reload(conn, round_row.id)
    kind, _, ident = target.partition(":")
    if kind in ("statement", "post"):
        raise invalid(
            {"target": "redact_the_message"}, "redact the message of the statement or post"
        )
    if kind == "answer" and ident:
        _redact_answer(conn, round_row, mine, ident, reason, actor)
        return
    if kind not in ("summary", "finding", "proposal") or (kind == "summary") == bool(ident):
        raise invalid({"target": "unknown"})
    report = round_row.report
    if report is None:
        raise not_found()
    if mine.kind != "human":
        raise refused("humans_only", "an agent never redacts the report")
    if not (mine.may("events:admin") or _invited(round_row, mine)):
        raise ApiError(
            403, "forbidden", "you may not redact this report", {"scope": "events:admin"}
        )
    redaction = mark(reason, mine.principal_id)
    if kind == "proposal":
        if not any(p["id"] == ident for p in report["proposals"]):
            raise not_found()
        changed = redact_proposal(conn, round_row, ident, redaction, actor)
    elif kind == "finding":
        finding = next((f for f in report["findings"] if f["id"] == ident), None)
        if finding is None:
            raise not_found()
        changed = finding["redaction"] is None
        findings = [
            {**f, "text": None, "redaction": redaction} if f["id"] == ident else f
            for f in report["findings"]
        ]
        report = {**report, "findings": findings}
    else:
        changed = report.get("summary_redaction") is None
        report = {**report, "summary": None, "summary_redaction": redaction}
    if not changed:
        return  # redacted already: the round as it is
    if kind != "proposal":
        conn.execute(
            update(t.jour_fixe_round)
            .where(t.jour_fixe_round.c.id == round_row.id)
            .values(report=report)
        )
    emit(
        conn,
        round_row.project_id,
        "event_redacted",
        ["all"],
        {"round_id": round_row.id, "target": target, "reason": reason},
        actor=actor,
        subject=("jour_fixe", round_row.id),
    )
