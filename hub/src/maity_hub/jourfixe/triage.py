"""The report and its triage (docs/api.md §20.6).

The moderator writes the report by `report_due_at`, or the hub builds one from the
statement. Each proposal is decided by the moderator itself (`decided`, an admin agent
or a human owner or admin, within the rules and its owner's preferences) or filed to the
project owner as a `decision` request (`to_owner`). Nothing is executed directly: an
`adopt`, from either path, opens one ordinary card, unless the project is closed.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, insert, or_, select, update

from maity_hub import clock, inbox, namespace, preferences, ticker
from maity_hub import tables as t
from maity_hub.board import history
from maity_hub.errors import ApiError, invalid
from maity_hub.events import Actor, emit, lock_project
from maity_hub.forge import Forge
from maity_hub.ids import new_id
from maity_hub.jourfixe import choices, circle, views
from maity_hub.jourfixe.answers import refused
from maity_hub.policy import CLOSED_STATES, REASON_STATES
from maity_hub.scopes import in_admin_team

FINDINGS_MAX, PROPOSALS_MAX = 50, 20  # §1.7
# §1.7, in bytes of UTF-8: a finding (also one the hub builds), the summary, a reason.
FINDING_BYTES, SUMMARY_BYTES, REASON_BYTES = 1024, 8192, 2048
CARD_REASON = "jour fixe proposal"  # the reason §6.1 asks for in plan and review
OPTIONS = [{"id": "adopt", "label": "Adopt"}, {"id": "reject", "label": "Reject"}]


def _reload(conn: Connection, round_id: str) -> Any:
    return conn.execute(select(t.jour_fixe_round).where(t.jour_fixe_round.c.id == round_id)).one()


def _state(round_row: Any, message: str) -> ApiError:
    return ApiError(409, "jour_fixe_state", message, {"status": round_row.status, "step": None})


def _day(round_row: Any) -> date:
    zone = ZoneInfo((round_row.config or {}).get("timezone") or "UTC")
    opened: Any = round_row.opened_at
    found: date = opened.astimezone(zone).date()
    return found


def _membership_of(conn: Connection, project_id: str, member_id: str) -> Any:
    """The membership a member id names in the project, active or not."""
    return conn.execute(
        select(t.membership)
        .where(
            t.membership.c.project_id == project_id,
            or_(t.membership.c.agent_id == member_id, t.membership.c.human_id == member_id),
        )
        .order_by(t.membership.c.active.desc(), t.membership.c.id.desc())
    ).first()


# --- the moderator's report -------------------------------------------------------------------


def may_decide(conn: Connection, round_row: Any, mine: Any) -> bool:
    """A member of the admin team, agent or human: trust `owner` or `admin`, never a
    proxy (§20.6, §2.3); in a round of an owner's series only its `circle_owner`, or an
    admin agent of that owner, since the proposals are theirs to decide."""
    owner = circle.owner_of(round_row)
    if owner is None:
        return in_admin_team(mine.trust, mine.role)
    if mine.kind == "human":
        return bool(mine.principal_id == owner)
    return in_admin_team(mine.trust, mine.role) and mine.principal_id in circle.owner_agents(
        conn, round_row.project_id, owner
    )


def _basis_errors(conn: Connection, mine: Any, basis: dict[str, Any]) -> dict[str, str]:
    """§19.4's check: the decider's owner (a human decides on their own preferences) and a
    version of theirs that exists, 0 meaning none written."""
    if mine.kind == "agent":
        return preferences.basis_errors(conn, mine.principal_id, basis)
    if basis.get("human_id") != mine.principal_id:
        return {"basis": "not_owner_preferences"}
    version = basis.get("preferences_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        return {"basis": "unknown_version"}
    if version == 0:
        return {}
    found = conn.execute(
        select(t.preferences_version.c.version).where(
            t.preferences_version.c.human_id == mine.principal_id,
            t.preferences_version.c.version == version,
        )
    ).first()
    return {} if found is not None else {"basis": "unknown_version"}


def _statement_proposals(round_row: Any) -> dict[str, dict[str, Any]]:
    topics = (round_row.statement or {}).get("topics", [])
    return {p["id"]: {**p, "topic_id": topic["id"]} for topic in topics for p in topic["proposals"]}


def submit_report(
    conn: Connection, round_row: Any, mine: Any, body: dict[str, Any], actor: Actor, fg: Forge
) -> None:
    """The moderator's report, made final with what it files and opens."""
    lock_project(conn, round_row.project_id)
    round_row = _reload(conn, round_row.id)
    if mine.principal_id != round_row.moderator["member_id"]:
        raise refused("not_moderator", "only the round's moderator writes the report")
    if round_row.status != "reporting":
        raise _state(round_row, "the report is due once the exchange has closed, and only once")
    from maity_hub.jourfixe.exchange import too_long

    too_long(
        [("summary", body.get("summary"), SUMMARY_BYTES)]
        + [("findings", f["text"], FINDING_BYTES) for f in body["findings"]]
        + [("proposals", p.get("reason"), REASON_BYTES) for p in body["proposals"]]
    )
    topic_ids = {topic["id"] for topic in (round_row.statement or {}).get("topics", [])}
    from_statement = _statement_proposals(round_row)
    if any(f.get("topic_id") not in (None, *topic_ids) for f in body["findings"]):
        raise invalid({"findings": "unknown_topic"})
    proposals = []
    for n, p in enumerate(body["proposals"], 1):
        source = p.get("statement_proposal_id")
        if source is not None and (
            source not in from_statement or from_statement[source]["topic_id"] != p["topic_id"]
        ):
            raise invalid({"proposals": "unknown_statement_proposal"})
        if source is not None and from_statement[source].get("redaction") is not None:
            # Redacted before the report: nothing may be derived from the tombstoned text.
            raise invalid({"proposals": "redacted_statement_proposal"})
        if p.get("topic_id") not in (None, *topic_ids):
            raise invalid({"proposals": "unknown_topic"})
        if p["triage"] == "decided":
            if p.get("humans_only"):
                raise refused("humans_only", "only a human decides this: file it to the owner")
            if not may_decide(conn, round_row, mine):
                raise refused("may_not_decide", "this moderator may not decide a proposal")
            decision = p.get("decision")
            if decision is None:
                raise invalid({"proposals": "decision_required"})
            errors = _basis_errors(conn, mine, decision["basis"])
            if errors:
                raise invalid(errors)
        elif p.get("decision") is not None:
            raise invalid({"proposals": "decision_for_decided_only"})
        proposals.append(
            {
                "id": f"r{n}",
                "title": p["title"],
                "reason": p.get("reason"),
                "topic_id": p.get("topic_id"),
                "statement_proposal_id": source,
                "triage": p["triage"],
                "humans_only": bool(p.get("humans_only")),
                "decision": p.get("decision"),
                "request_id": None,
                "task_id": None,
                "redaction": None,
            }
        )
    report = {
        "by": mine.principal_id,
        "source": "moderator",
        "summary": body.get("summary"),
        "summary_redaction": None,
        "findings": [
            {
                "id": f"f{n}",
                "topic_id": f.get("topic_id"),
                "text": f["text"],
                "derived_from": None,
                "redaction": None,
            }
            for n, f in enumerate(body["findings"], 1)
        ],
        "proposals": proposals,
        "proposals_not_carded": [],
    }
    _finish(conn, round_row, report, mine.id, actor, fg)


# --- the report the hub builds (§20.6, no report in time) -------------------------------------


def _cut(text: str, topic_id: str) -> str:
    """At most 1 KiB, cut at a character boundary with a visible marker."""
    if len(text.encode()) <= FINDING_BYTES:
        return text
    marker = f" … [cut; full text in topic {topic_id} of the statement]"
    room = FINDING_BYTES - len(marker.encode())
    return text.encode()[:room].decode(errors="ignore") + marker


def build_report(conn: Connection, round_row: Any) -> None:
    """At `report_due_at` without a report: one finding per topic, every statement
    proposal to the owner, no summary; nothing tombstoned, and empty without a statement."""
    topics = [
        topic
        for topic in (round_row.statement or {}).get("topics", [])
        if topic.get("redaction") is None
    ]
    findings: list[dict[str, Any]] = []
    for topic in topics:
        text = topic["title"] + (f"\n\n{topic['summary']}" if topic.get("summary") else "")
        findings.append(
            {
                "id": f"f{len(findings) + 1}",
                "topic_id": topic["id"],
                "text": _cut(text, topic["id"]),
                "derived_from": f"topic:{topic['id']}",
                "redaction": None,
            }
        )
    proposals = [
        {
            "id": f"r{n}",
            "title": p["title"],
            "reason": p.get("reason"),
            "topic_id": topic["id"],
            "statement_proposal_id": p["id"],
            "triage": "to_owner",
            "humans_only": False,
            "decision": None,
            "request_id": None,
            "task_id": None,
            "redaction": None,
        }
        for n, (topic, p) in enumerate(
            (
                (topic, p)
                for topic in topics
                for p in topic["proposals"]
                if p.get("redaction") is None
            ),
            1,
        )
    ]  # the statement's caps (20 topics, 20 proposals) hold the report's (§1.7)
    report = {
        "by": None,
        "source": "hub",
        "summary": None,
        "summary_redaction": None,
        "findings": findings,
        "proposals": proposals,
        "proposals_not_carded": [],
    }
    moderator = _membership_of(conn, round_row.project_id, round_row.moderator["member_id"])
    _finish(conn, round_row, report, moderator.id, None, None)


# --- filing, opening, final -------------------------------------------------------------------


def _file_request(
    conn: Connection, round_row: Any, proposal: dict[str, Any], asker: int, actor: Actor | None
) -> str:
    """A `decision` request to the owner for one proposal (§20.6, §7); in a round of an
    owner's series to its `circle_owner`, personal when that human is no longer a member."""
    from maity_hub.routes.requests import _member_of

    keeper = circle.owner_of(round_row)
    member = _member_of(conn, round_row.project_id, keeper) if keeper else None
    personal = keeper is not None and member is None
    to: dict[str, Any] = {"to_kind": "owner"}
    if member is not None:
        to = {"to_kind": "member", "to_member": member.id}
    elif personal:
        to = {"to_kind": "human", "to_human": keeper, "personal": True}
    request_id = new_id("request")
    round_line = f"From the jour fixe of {_day(round_row).isoformat()} (round {round_row.id})."
    summary = f"{proposal['reason']}\n\n{round_line}" if proposal.get("reason") else round_line
    conn.execute(
        insert(t.request).values(
            {
                "id": request_id,
                "project_id": round_row.project_id,
                "class": "decision",
                "title": proposal["title"],
                "summary": summary,
                "mentions": [],
                "options": OPTIONS,
                "priority": "normal",
                **to,
                "asked_by": asker,
                "while_open": "proceed_provisionally",
                "humans_only": proposal["humans_only"],
                "jour_fixe": {"round_id": round_row.id, "proposal_id": proposal["id"]},
                "status": "open",
                "created_at": clock.now(),
            }
        )
    )
    from maity_hub.routes.requests import load_request

    if keeper is not None:
        audience = [] if personal else [f"member:{keeper}"]
        if personal:
            from maity_hub.notifications import records
            from maity_hub.routes.requests import _row

            records.personal_request(conn, _row(conn, request_id))
    else:
        owner = inbox.owner_membership(conn, round_row.project_id)
        audience = [f"member:{owner.human_id}"] if owner else ["trust:owner"]
    emit(
        conn,
        round_row.project_id,
        "request_created",
        audience,
        load_request(conn, request_id),
        actor=actor,
        subject=("request", request_id),
    )
    return request_id


def open_card(
    conn: Connection,
    project: Any,
    marker: dict[str, str],
    title: str,
    body: str,
    decider: int,
    actor: Actor,
    fg: Forge,
) -> str | None:
    """One ordinary card for an adopted proposal: open, unassigned, `jour_fixe` set.
    None in a closed project, which opens no card (§6.1)."""
    if project.state in CLOSED_STATES:
        return None
    from maity_hub.routes.tasks import CREATED, audience
    from maity_hub.views import task_view

    now = clock.now()
    card_id = new_id("task")
    conn.execute(
        insert(t.card).values(
            id=card_id,
            project_id=project.id,
            kind="task",
            title=title,
            body=body,
            mentions=[],
            status="open",
            created_by=decider,
            jour_fixe=marker,
            created_at=now,
            updated_at=now,
        )
    )
    card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
    view = task_view(conn, card, fg)
    fields = [name for name in CREATED if name in view and view[name] not in (None, [])]
    entry = history.created(conn, card_id, {name: view[name] for name in fields}, actor)
    reason = CARD_REASON if project.state in REASON_STATES else None
    seq = emit(
        conn,
        project.id,
        "task_created",
        audience(conn, card),
        {
            **{k: v for k, v in view.items() if k != "body"},  # never in an event
            "fields": fields,
            "history": [entry],
            "project_state": project.state,
            "reason": reason,
        },
        actor=actor,
        subject=("task", card_id),
    )
    history.stamp(conn, [entry], seq)
    return card_id


def card_body(round_row: Any, proposal: dict[str, Any]) -> str:
    line = f"From the jour fixe of {_day(round_row).isoformat()} (round {round_row.id})."
    return f"{proposal['reason']}\n\n{line}" if proposal.get("reason") else line


def _finish(
    conn: Connection,
    round_row: Any,
    report: dict[str, Any],
    asker: int,
    actor: Actor | None,
    fg: Forge | None,
) -> None:
    """File the requests, open the cards of decided adoptions, and make the report final."""
    project = conn.execute(select(t.project).where(t.project.c.id == round_row.project_id)).one()
    for proposal in report["proposals"]:
        if proposal["triage"] == "to_owner":
            proposal["request_id"] = _file_request(conn, round_row, proposal, asker, actor)
        elif proposal["decision"]["outcome"] == "adopt":
            # Only the moderator decides, so a decided proposal always has a caller.
            assert actor is not None and fg is not None
            marker = {"round_id": round_row.id, "proposal_id": proposal["id"]}
            card_id = open_card(
                conn,
                project,
                marker,
                proposal["title"],
                card_body(round_row, proposal),
                asker,
                actor,
                fg,
            )
            if card_id is None:
                report["proposals_not_carded"].append(
                    {"proposal_id": proposal["id"], "reason": "project_closed"}
                )
            else:
                proposal["task_id"] = card_id
    now = clock.now()
    conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.id == round_row.id)
        .values(status="reported", reported_at=now, report=report)
    )
    found = (
        conn.execute(
            select(t.jour_fixe_series).where(t.jour_fixe_series.c.id == round_row.series_id)
        ).first()
        if round_row.series_id
        else None
    )
    recipients = choices.tokens(conn, found) if found is not None else []
    emit(
        conn,
        round_row.project_id,
        "jour_fixe_reported",
        list(dict.fromkeys([*circle.audience(conn, round_row, ["all"]), *recipients])),
        {
            "round_id": round_row.id,
            **{k: v for k, v in views.series_fields(round_row).items() if k != "circle"},
            "source": report["source"],
            "proposals": [
                {
                    "id": p["id"],
                    "title": p["title"],
                    "triage": p["triage"],
                    "outcome": (p["decision"] or {}).get("outcome"),
                    "request_id": p["request_id"],
                    "task_id": p["task_id"],
                }
                for p in report["proposals"]
            ],
        },
        actor=actor,
        subject=("jour_fixe", round_row.id),
    )
    _ticker(conn, project, round_row, report)


def _ticker(conn: Connection, project: Any, round_row: Any, report: dict[str, Any]) -> None:
    """One item when the report is final, counts only, `all` alone, no wake (§20.9); none
    for an owner's series, whose round stays with its owner (§20.7)."""
    if not ticker.settings(project)["enabled"] or circle.owner_of(round_row) is not None:
        return
    decided = sum(1 for p in report["proposals"] if p["triage"] == "decided")
    to_owner = len(report["proposals"]) - decided
    text = (
        f"Jour fixe {_day(round_row).isoformat()}: {round_row.answers_received} answers, "
        f"{len(report['proposals'])} proposals ({decided} decided, {to_owner} to the owner)"
    )
    ticker.write(
        conn,
        project.id,
        kind="jour_fixe",
        text=text,
        url=f"/{namespace.full_name(conn, project)}/jour-fixe/{round_row.id}",
        audience=ticker.Audience(),
        origin="hub",
        subject=("jour_fixe", round_row.id),
        dedupe_key=f"jour_fixe:{round_row.id}",
    )


# --- an answer to a filed request (§20.6) -----------------------------------------------------


def settle(
    conn: Connection, request: Any, reply_id: str | None, mine: Any, actor: Actor, fg: Forge
) -> None:
    """An `adopt` answer to a request the hub filed for a proposal opens its card; any
    other answer opens nothing."""
    marker = request.jour_fixe
    if marker is None or reply_id != "adopt":
        return
    round_row = _reload(conn, marker["round_id"])
    proposal = next(p for p in round_row.report["proposals"] if p["id"] == marker["proposal_id"])
    project = conn.execute(select(t.project).where(t.project.c.id == request.project_id)).one()
    if proposal["redaction"] is not None:
        # Redacted before its adoption: the card opens with the placeholders a redaction
        # leaves on a card, so no text of the proposal comes back (§20.8).
        from maity_hub.jourfixe.redaction import REDACTED_TEXT, REDACTED_TITLE

        title, body = REDACTED_TITLE, card_body(round_row, {"reason": REDACTED_TEXT})
    else:
        title, body = proposal["title"], card_body(round_row, proposal)
    open_card(conn, project, dict(marker), title, body, mine.id, actor, fg)


def handle_deadlines(conn: Connection, project_id: str) -> None:
    """Build the report of every round whose `report_due_at` passed without one."""
    rows = conn.execute(
        select(t.jour_fixe_round).where(
            t.jour_fixe_round.c.project_id == project_id,
            t.jour_fixe_round.c.status == "reporting",
            t.jour_fixe_round.c.report_due_at <= clock.now(),
        )
    ).all()
    for row in rows:
        build_report(conn, row)
