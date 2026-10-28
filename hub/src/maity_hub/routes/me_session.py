"""The resume packet and the agent's own `paused` (docs/api.md §5.2, §5.3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field, StrictBool
from sqlalchemy import Connection, func, insert, select, update

from maity_hub import (
    API_VERSION,
    __version__,
    availability,
    avatars,
    briefings,
    clock,
    environment,
    events,
    group_chats,
    idempotency,
    instances,
    memory,
    mentions,
    namespace,
    onboarding,
    preferences,
    ranks,
    rules,
    ticker,
)
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth.caller import CLOSED_STATUSES, Caller
from maity_hub.db import retrying
from maity_hub.deps import AgentCaller, AnyCaller, engine_of, settings_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid
from maity_hub.forge import Forge
from maity_hub.ids import new_id
from maity_hub.models import Strict
from maity_hub.namespace import ProjectRoute
from maity_hub.policy import CLOSED_STATES
from maity_hub.policy import of as policy_of
from maity_hub.routes.conversations import conversation_packet
from maity_hub.routes.me import human_body
from maity_hub.routes.members import PausedIn, change_of, load_member, set_paused
from maity_hub.routes.projects import arbiter_text
from maity_hub.scopes import listed_scopes
from maity_hub.views import (
    absence,
    event_views,
    git_identity,
    meat_proxy_view,
    member_views,
    paused,
    principal_id,
    project_language,
    repository,
    task_views,
    ts,
)

router = APIRouter(route_class=ProjectRoute)

PACKET_EVENTS = 100  # then `truncated: true` (§1.7)
PACKET_REQUESTS = 100  # per list, then `requests.truncated: true`
# `hints.wait_timeout` (§5.2): seconds a `wait` should run, below the point where the
# harness kills a command under its default tool settings. Read from each harness's
# source, --help and docs (docs/agents.md, "Staying on duty, per harness"); the hub
# cannot know a per-call timeout the agent might pass. A name not listed gets the
# default: no known kill.
WAIT_TIMEOUT_DEFAULT = 600
_WAIT_TIMEOUTS = {
    25: ("cline", "cline cli"),  # SIGKILL after 30 s, not settable
    110: ("opencode",),  # 120 s default kill
    170: ("hermes", "hermes agent"),  # 180 s default
    280: ("kimi", "kimi code", "kimi cli"),  # 300 s cap
    290: ("omp", "oh my pi"),  # 300 s default
    540: ("claude code", "claude"),  # a timed-out command moves to the background; -p has 10 min
}
WAIT_TIMEOUTS = {name: seconds for seconds, names in _WAIT_TIMEOUTS.items() for name in names}


def wait_timeout(harness: str | None) -> int:
    """The hint for a declared harness, by name as agents write it ("Claude Code",
    "claude-code", "Oh-My-Pi"): case, hyphens, underscores and spacing do not matter."""
    name = " ".join((harness or "").lower().replace("-", " ").replace("_", " ").split())
    return WAIT_TIMEOUTS.get(name, WAIT_TIMEOUT_DEFAULT)


KEEP_THE_WHY_INSTRUCTION = rules.KEEP_THE_WHY

# The operations an agent may call, by scope; each slice adds its rows (§5.2).
OPERATIONS: list[tuple[str, str, str | None]] = [
    ("GET", "/me", None),
    ("POST", "/me/resume", None),
    ("PATCH", "/me", None),
    ("POST", "/me/limit", None),
    ("GET", "/help", None),
    ("GET", "/projects", None),
    ("GET", "/projects/{owner}/{slug}", "project:read"),
    ("GET", "/projects/{owner}/{slug}/rules", "project:read"),
    ("GET", "/projects/{owner}/{slug}/members", "project:read"),
    ("GET", "/projects/{owner}/{slug}/members/{id}", "project:read"),
    # An admin agent within §2.3 ᵃ: member and reviewer agents, never itself.
    ("PATCH", "/projects/{owner}/{slug}/members/{id}", "members:admin"),
    ("DELETE", "/projects/{owner}/{slug}/members/{id}", "members:admin"),
    ("GET", "/projects/{owner}/{slug}/tasks", "project:read"),
    ("GET", "/projects/{owner}/{slug}/tasks/{id}", "project:read"),
    ("POST", "/projects/{owner}/{slug}/tasks", "tasks:write"),
    ("PATCH", "/projects/{owner}/{slug}/tasks/{id}", "tasks:write"),
    ("POST", "/projects/{owner}/{slug}/tasks/{id}/claim", "tasks:write"),
    ("POST", "/projects/{owner}/{slug}/tasks/{id}/release", "tasks:write"),
    ("POST", "/projects/{owner}/{slug}/tasks/{id}/checkpoint", "tasks:write"),
    ("POST", "/projects/{owner}/{slug}/tasks/{id}/report", "tasks:write"),
    ("POST", "/projects/{owner}/{slug}/tasks/{id}/assign", "tasks:admin"),
    ("GET", "/projects/{owner}/{slug}/requests", "project:read"),
    ("GET", "/projects/{owner}/{slug}/requests/{id}", "project:read"),
    ("POST", "/projects/{owner}/{slug}/requests", "requests:ask"),
    ("POST", "/projects/{owner}/{slug}/requests/{id}/answer", "requests:ask"),
    ("POST", "/projects/{owner}/{slug}/requests/{id}/withdraw", "requests:ask"),
    ("GET", "/projects/{owner}/{slug}/events", "project:read"),
    ("POST", "/projects/{owner}/{slug}/events", "events:post"),
    ("GET", "/projects/{owner}/{slug}/conversations", None),
    ("GET", "/projects/{owner}/{slug}/conversations/{agent_id}/messages", None),
    ("POST", "/projects/{owner}/{slug}/conversations/{agent_id}/messages", None),
]


class EnvironmentIn(Strict):
    """Declared, never verified (§5.2): ids the client derives per hub."""

    home: str | None = Field(default=None, pattern=environment.ID.pattern)
    workspace: str | None = Field(default=None, pattern=environment.ID.pattern)


class ResumeIn(Strict):
    harness: str | None = Field(default=None, max_length=200)
    harness_version: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    client: str = Field(min_length=1, max_length=200)
    cursor: int | None = Field(default=None, ge=0)
    environment: EnvironmentIn | None = None
    # A runner supervises this session (§15.11): `maity-runner/<version>`.
    supervisor: str | None = Field(default=None, pattern=r"^maity-runner/[A-Za-z0-9.+_-]{1,64}$")


class MePatch(Strict):
    """An agent's `paused`, or a human's own profile switches (`meat_proxy`, §5.2)."""

    paused: PausedIn | None = None
    meat_proxy: StrictBool | None = None


def _own_membership(conn: Connection, caller: Caller) -> Membership:
    row = conn.execute(select(t.membership).where(t.membership.c.id == caller.membership_id)).one()
    project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
    return Membership(project, row, "agent", caller.instance)


@router.post("/me/resume")
def resume(body: ResumeIn, request: Request, caller: AgentCaller) -> JSONResponse:
    return JSONResponse(retrying(lambda: _resume(body, request, caller)))


def _resume(body: ResumeIn, request: Request, caller: Caller) -> dict[str, Any]:
    settings = settings_of(request)
    with events.transaction(engine_of(request)) as conn:
        mine = _own_membership(conn, caller)
        # Serialise with other writes to the project: two resumes of one
        # credential must not both open its live session.
        events.lock_project(conn, mine.project.id)
        now = clock.now()
        # Rows in the order every authenticated call touches them (credential,
        # membership, session, cards), so that the two never wait on each other
        # in a cycle; InnoDB answers such a cycle with a deadlock.
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == caller.credential_id)
            .values(
                last_used_at=now,
                resumed_at=func.coalesce(t.credential.c.resumed_at, now),
            )
        )
        # The instance's own pause ends with its next session too (§5.3).
        conn.execute(
            update(t.credential)
            .where(
                t.credential.c.id == caller.credential_id,
                t.credential.c.paused_by == caller.agent_id,
            )
            .values(paused_reason=None, paused_since=None, paused_by=None)
        )
        if mine.row.paused_since is not None and mine.row.paused_by == caller.agent_id:
            # The agent's own pause ends with its next session; a human's stays.
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id == mine.id)
                .values(paused_reason=None, paused_since=None, paused_by=None)
            )
        previous = conn.execute(
            select(t.agent_session)
            .where(t.agent_session.c.credential_id == caller.credential_id)
            .order_by(t.agent_session.c.started_at.desc())
        ).first()
        conn.execute(
            update(t.agent_session)
            .where(
                t.agent_session.c.credential_id == caller.credential_id,
                t.agent_session.c.live.is_(True),
            )
            .values(live=None, ended_at=now)
        )
        if body.cursor is not None:
            cursor = body.cursor
        elif previous is not None:
            cursor = previous.acknowledged_seq
        else:
            # A new instance (§6.17) starts at the project's head, not at 0: the handover
            # replaces the backlog, and `GET …/events?after=` still serves the history (§8.3).
            cursor = events.highest_readable(
                conn, mine.project.id, mine.row, caller.principal_id
            )
        session_id = new_id("session")
        conn.execute(
            insert(t.agent_session).values(
                id=session_id,
                credential_id=caller.credential_id,
                membership_id=mine.id,
                harness=body.harness,
                harness_version=body.harness_version,
                model=body.model,
                client=body.client,
                user_agent=request.headers.get("user-agent"),
                started_at=now,
                last_seen_at=now,
                events_at=now,  # a resume counts as a call for events (§5.3)
                acknowledged_seq=cursor,
                live=True,
                env_home=body.environment.home if body.environment else None,
                env_workspace=body.environment.workspace if body.environment else None,
                supervisor=body.supervisor,
            )
        )
        environment.refresh(conn, mine.project.id, mine.id)
        conn.execute(
            update(t.card)
            .where(
                t.card.c.claim_holder == mine.id,
                t.card.c.claim_instance == caller.instance,
                t.card.c.status.notin_(CLOSED_STATUSES),
            )
            .values(claim_session_id=session_id)
        )
        session = {
            "id": session_id,
            "started_at": ts(now),
            "harness": body.harness,
            "model": body.model,
            "client": body.client,
        }
        actor = events.Actor(
            mine.id, session_id, caller.credential_id, caller.via, body.harness, body.model
        )
        started = events.emit(
            conn,
            mine.project.id,
            "session_started",
            [],
            {**session, "harness_version": body.harness_version},
            actor=actor,
            subject=("session", session_id),
        )
        # The member's next resume clears its limit (§6.12); a returning agent is
        # announced before its packet is built.
        if mine.row.limit_until is not None:
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id == mine.id)
                .values(**availability.NO_LIMIT)
            )
        availability.reconcile_ids(conn, [mine.id], actor)
        mine = _own_membership(conn, caller)  # with the pause cleared
        packet = _packet(conn, mine, caller, body, cursor, started, session, settings)
    return packet


def _packet(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    body: ResumeIn,
    cursor: int,
    started_seq: int,
    session: dict[str, Any],
    settings: Any,
) -> dict[str, Any]:
    project = events.lock_project(conn, mine.project.id)
    fg = Forge(settings.forge_github_token)
    agent = conn.execute(
        select(t.agent_profile).where(t.agent_profile.c.id == caller.agent_id)
    ).one()
    owner = conn.execute(select(t.human).where(t.human.c.id == agent.owner_id)).one()
    # A group chat's message that does not mention the agent is counted in
    # `conversations` instead, so a busy chat cannot push the work out (§5.2).
    rows, examined, truncated = events.read(
        conn,
        project.id,
        mine.row,
        caller.principal_id,
        cursor,
        PACKET_EVENTS,
        chat_windows=group_chats.windows(conn, mine.id),
    )
    events_cursor = rows[-1].seq if truncated else max(examined, started_seq, cursor)
    rows = [r for r in rows if r.seq != started_seq]  # never the session's own start
    events.mark_delivered(conn, rows, caller.principal_id)
    rules_seq = project.rules_changed_seq or 0
    changed = body.cursor is None or body.cursor < rules_seq
    rules_block: dict[str, Any] = {"version": project.rules_version, "changed": changed}
    if changed or body.supervisor is not None:  # the supervised duty is in every packet
        rules_block["markdown"] = rules.generate(
            project,
            mine.trust,
            mine.role,
            arbiter_text(conn, project),
            supervised=body.supervisor is not None,
        )
    members = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project.id, t.membership.c.active.is_(True)
        )
    ).all()
    meat_proxies = {
        row.id: row.meat_proxy
        for row in conn.execute(
            select(t.human.c.id, t.human.c.meat_proxy).where(
                t.human.c.id.in_([m.human_id for m in members if m.human_id is not None])
            )
        )
    }
    peers = []
    areas = []
    for row, view in zip(members, member_views(conn, members), strict=True):
        areas += [{"path": path, "owner": view["id"]} for path in row.areas]
        if row.id != mine.id:
            peers.append(
                {
                    "member_id": view["id"],
                    "kind": view["kind"],
                    "handle": view["handle"],
                    **({"name": view["name"]} if "name" in view else {}),  # agents (§6.3)
                    "trust": view["trust"],
                    "role": view["role"],
                    "areas": view["areas"],
                    "presence": view["presence"],
                    "paused": view["paused"],
                    "availability": view["availability"],  # §6.12
                    "covered_by": view["covered_by"],
                    **(
                        meat_proxy_view(meat_proxies[view["id"]]) if view["kind"] == "human" else {}
                    ),
                }
            )
    peers.sort(key=lambda p: (p["kind"] != "human", p["handle"]))
    areas.sort(key=lambda a: (a["path"], a["owner"]))
    # This instance's: the cards it holds, and those assigned to it or to the team
    # with no instance chosen (§5.2).
    held = conn.execute(
        select(t.card)
        .where(
            t.card.c.claim_holder == mine.id,
            t.card.c.claim_instance == caller.instance,
            t.card.c.status.notin_(CLOSED_STATUSES),
        )
        .order_by(t.card.c.updated_at.desc())
    ).all()
    assigned = conn.execute(
        select(t.card).where(
            t.card.c.assigned_to == mine.id,
            t.card.c.assigned_instance.is_(None) | (t.card.c.assigned_instance == caller.instance),
            t.card.c.claim_holder.is_(None),
            t.card.c.status == "open",
        )
    ).all()
    assigned = sorted(assigned, key=ranks.column_key)  # the card order, its priority (§6.4)
    siblings = [
        {
            key: view[key]
            for key in ("id", "address", "harness", "model", "presence", "paused", "lead", "claims")
        }
        for view in instances.views(conn, [mine.row], {agent.id: agent.handle}).get(mine.id, [])
        if view["id"] != caller.instance
    ]
    scopes = listed_scopes(mine.trust, mine.role, "agent")
    # Below the rules, never a permission (§19.4); the owner's text once, here or there.
    preferences_block, owner_preferences = preferences.packet(conn, mine, cursor)
    written = briefings.writers(conn, {mine.row.briefing_by} if mine.row.briefing_by else set())
    return {
        "server_time": clock.rfc3339(clock.now()),
        "api_version": API_VERSION,
        "hub_version": __version__,
        # First of the contents: the soul is what an agent loads before anything (§19.3).
        "memory": memory.packet_block(conn, mine, agent.id, cursor),
        **(
            {"onboarding": check_in}
            if (check_in := onboarding.hint(conn, project, mine.row))
            else {}
        ),
        "session": session,
        # Supervised: the runner starts a run on each event, so no wait to time (§15.11).
        "hints": (
            {"duty": "supervised"}
            if body.supervisor is not None
            else {"duty": "self", "wait_timeout": wait_timeout(body.harness)}
        ),
        "me": {
            "member_id": agent.id,
            "handle": agent.handle,
            "name": mentions.global_name(owner.handle, agent.handle),  # §6.3
            "display_name": agent.display_name,
            "avatar_url": avatars.urls(conn, [agent.id])[agent.id],
            "instance": caller.instance,
            "address": instances.address(agent.id, caller.instance or ""),
            "owner": {"id": owner.id, "handle": owner.handle, **meat_proxy_view(owner.meat_proxy)},
            "git_identity": git_identity(agent),
        },
        "membership": {
            "trust": mine.trust,
            "role": mine.role,
            "reports_to": principal_id(conn, mine.row.reports_to),
            "areas": mine.row.areas,
            "capabilities": mine.row.capabilities,
            "scopes": scopes,
            # Its own pause, the team's or this instance's, so the agent knows to rest.
            "paused": paused(mine.row) or instances.paused_view(_credential(conn, caller)),
            **_briefing(project, mine.row, written),
            "team": instances.team(conn, mine.row),
            "owner_preferences": owner_preferences,
            "availability_policy": availability.policy_of(mine.row),  # §6.12
            "covering": [],  # cover by a substitute is not built yet (§6.12)
            "placement": _placement_block(conn, mine.id),
        },
        "team": siblings,
        "project": {
            "language": project_language(project),
            "id": project.id,
            "full_name": namespace.full_name(conn, project),
            "slug": project.slug,
            "name": project.name,
            "state": project.state,
            "state_note": project.state_note,
            "state_changed_at": ts(project.state_changed_at),
            "repository": repository(project, settings),
            "policy": policy_of(project),
            "absence": absence(project),
            "keep_the_why": project.keep_the_why,
            "rules_version": project.rules_version,
        },
        "rules": rules_block,
        "preferences": preferences_block,
        "areas": areas,
        "keep_the_why": {
            "enabled": project.keep_the_why,
            "instruction": KEEP_THE_WHY_INSTRUCTION if project.keep_the_why else None,
        },
        "claims": task_views(conn, held, fg),
        "assigned": task_views(conn, assigned, fg),
        "requests": _requests_block(conn, mine, cursor),
        "ticker": ticker.packet(conn, mine, cursor),
        "events": {
            "after": cursor,
            "items": event_views(conn, rows, mine),
            "cursor": events_cursor,
            "truncated": truncated,
        },
        "conversations": conversation_packet(conn, mine, caller),
        "peers": peers,
        "operations": operations(
            project, mine.trust, mine.role, namespace.full_name(conn, project)
        ),
    }


def _briefing(project: Any, membership: Any, written: dict[str, Any]) -> dict[str, Any]:
    """`membership.briefing` and whose it is (§5.2): the membership's own, with who wrote
    it and its version (§6.2), else the project default with the setting's author and
    version, else none."""
    block = onboarding.briefing(project, membership)
    if block["briefing_source"] == "membership":
        block["briefing_by"] = (
            written.get(membership.briefing_by) if membership.briefing_by else None
        )
        block["briefing_version"] = membership.briefing_version
    return block


def _placement_block(conn: Connection, membership_id: int) -> dict[str, Any] | None:
    """`membership.placement` (§15.11): the active placement running this membership."""
    row = conn.execute(
        select(t.placement, t.runner.c.name.label("runner_name"))
        .join(t.runner, t.runner.c.id == t.placement.c.runner_id)
        .where(t.placement.c.membership_id == membership_id, t.placement.c.active.is_(True))
    ).first()
    if row is None:
        return None
    return {
        "id": row.id,
        "runner_name": row.runner_name,
        "harness": row.harness,
        "mode": row.mode,
        "stop_grace_seconds": row.stop_grace_seconds,
    }


def _requests_block(conn: Connection, mine: Membership, cursor: int) -> dict[str, Any]:
    """§5.2: what I asked and is open, what was answered since my cursor, what I may answer."""
    from maity_hub import inbox
    from maity_hub.routes.requests import request_view

    rows = conn.execute(
        select(t.request)
        .where(t.request.c.project_id == mine.project.id)
        .order_by(t.request.c.created_at)
    ).all()
    mine_open = [r for r in rows if r.status == "open" and inbox.is_asker(r, mine)]
    answered_ids = set(
        conn.execute(
            select(t.event.c.subject_id).where(
                t.event.c.project_id == mine.project.id,
                t.event.c.kind == "request_answered",
                t.event.c.seq > cursor,
            )
        ).scalars()
    )
    answered = [r for r in rows if r.id in answered_ids and inbox.is_asker(r, mine)]
    to_answer = [
        r
        for r in rows
        if r.status == "open"
        and not inbox.is_asker(r, mine)
        and inbox.may_answer(conn, r, mine)
        and (inbox.addressed_to(conn, r, mine) or mine.may("requests:answer"))
    ]
    # Bounded like the rest of the packet (§5.2): an admin may answer everything open.
    return {
        "mine_open": [request_view(conn, r) for r in mine_open[:PACKET_REQUESTS]],
        "answered_since_cursor": [request_view(conn, r) for r in answered[:PACKET_REQUESTS]],
        "to_answer": [request_view(conn, r) for r in to_answer[:PACKET_REQUESTS]],
        "truncated": any(len(x) > PACKET_REQUESTS for x in (mine_open, answered, to_answer)),
    }


def operations(project: Any, trust: str, role: str, full_name: str) -> list[str]:
    allowed = []
    for method, path, scope in OPERATIONS:
        if scope is not None and scope not in listed_scopes(trust, role, "agent"):
            continue
        if project.state in CLOSED_STATES and (
            path.endswith("/claim") or (method == "POST" and path.endswith("/tasks"))
        ):
            continue
        allowed.append(f"{method} {path.replace('{owner}/{slug}', full_name)}")
    return allowed


def _credential(conn: Connection, caller: Caller) -> Any:
    return conn.execute(select(t.credential).where(t.credential.c.id == caller.credential_id)).one()


def load_human_profile(conn: Connection, human_id: str) -> dict[str, Any]:
    """A human's `PATCH /me` answer: `/me` as it is now (§5.1), also on a replay."""
    return {**human_body(conn, human_id), "server_time": clock.rfc3339(clock.now())}


idempotency.LOADERS["human_profile"] = idempotency.plain(load_human_profile)


@router.patch("/me")
def patch_me(body: MePatch, request: Request, caller: AnyCaller) -> JSONResponse:
    given = body.model_fields_set

    def human_action(conn: Connection) -> idempotency.Outcome:
        if "paused" in given:
            raise invalid({"paused": "agents_only"})
        if body.meat_proxy is None:
            raise invalid({"meat_proxy": "required"}, "nothing to change")
        assert caller.human_id is not None
        conn.execute(
            update(t.human)
            .where(t.human.c.id == caller.human_id)
            .values(meat_proxy=body.meat_proxy)
        )
        return idempotency.Outcome(
            200, "human_profile", caller.human_id, load_human_profile(conn, caller.human_id)
        )

    def action(conn: Connection) -> idempotency.Outcome:
        if "meat_proxy" in given:
            raise humans_only("only a human sets their own profile")
        if "paused" not in given:
            raise invalid({"paused": "required"}, "nothing to change")
        mine = _own_membership(conn, caller)
        credential = _credential(conn, caller)
        for row in (mine.row, credential):
            if row.paused_since is None or row.paused_by == caller.agent_id:
                continue
            # Someone else's pause is not the agent's to lift or replace (§5.3): a
            # human's, or an admin agent's, which `by` names.
            by_agent = str(row.paused_by).startswith("agt-")
            raise ApiError(
                403,
                "forbidden",
                f"{'an admin agent' if by_agent else 'a human'} paused you; "
                "only they or an admin can change it",
                {"reason": "paused_by_admin" if by_agent else "paused_by_human"},
            )
        # The calling instance's own pause; its siblings carry on (§5.3).
        set_paused(
            conn,
            change_of(mine, caller),
            mine.row,
            body.paused.reason if body.paused else None,
            instance=caller.instance,
        )
        return idempotency.Outcome(200, "member", str(mine.id), load_member(conn, str(mine.id)))

    if caller.kind not in ("human", "agent"):
        raise forbidden(message="this endpoint is for humans and agent credentials")
    return idempotency.run(
        engine_of(request), request, caller, human_action if caller.kind == "human" else action
    )
