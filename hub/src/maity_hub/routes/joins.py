"""Joining a project: the join link, the join page and the exchange (docs/api.md §3).

A human creates a join; the dashboard shows one paste line with the URL
(128-bit token) and the code (60 bits). The URL answers the onboarding
page, the exchange trades the code for a credential once. The hub stores
only hashes of token and code; the credential is the response body and
nothing else, so that a tool saves it straight to a file.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from datetime import timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from markdown_it import MarkdownIt
from pydantic import Field
from sqlalchemy import Connection, insert, select, update
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from maity_hub import (
    briefings,
    clock,
    events,
    handles,
    idempotency,
    instances,
    limits,
    line,
    moderation,
    namespace,
    project_roles,
    takeovers,
    write_guard,
)
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.auth import credentials, second_factor
from maity_hub.auth.caller import require_secure_transport
from maity_hub.auth.leaks import revoke
from maity_hub.codes import code_matches, digest, new_code, new_token, normalise_code
from maity_hub.config import Settings
from maity_hub.db import retrying
from maity_hub.deps import HumanCaller, engine_of, origin_of, settings_of
from maity_hub.errors import ApiError, forbidden, invalid, not_found, rate_limited
from maity_hub.events import Actor, emit, lock_project
from maity_hub.ids import new_id
from maity_hub.models import HANDLE_PATTERN, GitIdentity, Strict, markdown, title
from maity_hub.namespace import ProjectRoute
from maity_hub.ratelimit import Limiter
from maity_hub.routes.agents import create_profile
from maity_hub.routes.members import validate_assignment
from maity_hub.scopes import MEMBER_RULE_ROLES, has_scope
from maity_hub.views import join_view, member_view, principal_id

router = APIRouter(route_class=ProjectRoute)
page_router = APIRouter(route_class=ProjectRoute)  # /join/{token}, outside the API prefix

TTL_DEFAULT, TTL_MIN, TTL_MAX = 900, 60, 3600
WRONG_CODES_BEFORE_BURN = 3
# What a member's own agent may hold (§3.1 "Bringing your own agent"): below governance.
MEMBER_RULE_TRUSTS = ("member", "guest")
EXCHANGE_BY_ADDRESS = Limiter(10, 60)
_TEMPLATE_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class JoinAgent(Strict):
    id: str | None = None
    handle: str | None = title(default=None, pattern=HANDLE_PATTERN)
    display_name: str | None = title(default=None)
    git_identity: GitIdentity | None = None


class JoinCreate(Strict):
    agent: JoinAgent
    trust: str | None = None
    role: str | None = None
    reports_to: str | None = None
    areas: list[str] | None = Field(default=None, max_length=50)
    capabilities: list[str] | None = Field(default=None, max_length=20)
    # What the human tells this agent about its job; in the resume packet, never on
    # the join page, which whoever holds the URL can read (§3.1).
    briefing: str | None = markdown(default=None)
    ttl_seconds: int = TTL_DEFAULT
    via: Literal["join", "public"] | None = None
    # For an agent that is already a member: which instance the join adds (§6.17).
    new_instance: bool | None = None
    replaces: str | None = Field(default=None, max_length=5)


class Exchange(Strict):
    code: str = Field(min_length=1, max_length=64)
    client: str = Field(min_length=1, max_length=200)


def load_join(conn: Connection, join_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.join_link).where(t.join_link.c.id == join_id)).one()
    return join_view(conn, row)


idempotency.LOADERS["join"] = idempotency.plain(load_join)


# --- the join link (human) --------------------------------------------------------


@router.post("/projects/{owner}/{slug}/joins")
def create_join(slug: str, body: JoinCreate, request: Request, caller: HumanCaller) -> JSONResponse:
    if not TTL_MIN <= body.ttl_seconds <= TTL_MAX:
        raise invalid({"ttl_seconds": "out_of_range"})
    settings = settings_of(request)
    via = body.via or ("join" if settings.join_url else "public")
    if via == "join" and settings.join_url is None:
        raise invalid({"via": "no_join_host"}, "this hub has no join host")

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        member_rule = not mine.may("members:admin")
        if member_rule:
            _require_member_rule(mine)
        second_factor.require_step_up(conn, settings, caller)  # mints a credential (§2.8.4)
        agent_id = _agent_for_join(
            conn,
            body.agent,
            caller.principal_id,
            member_rule,
            limits.of(conn, settings, "max_agents_per_human"),
        )
        existing = conn.execute(
            select(t.membership).where(
                t.membership.c.project_id == mine.project.id,
                t.membership.c.agent_id == agent_id,
                t.membership.c.active.is_(True),
            )
        ).first()
        reports_to = body.reports_to
        if member_rule:
            _check_member_limits(conn, body, mine, existing)
            if existing is None and reports_to is None:
                reports_to = mine.principal_id  # the agent reports to whoever brings it
        values = validate_assignment(
            conn,
            mine.project.id,
            kind="agent",
            role=body.role,
            reports_to=reports_to,
            areas=body.areas,
            capabilities=body.capabilities,
            trust=body.trust,
            current=(existing.trust, existing.role) if existing else ("member", "coder"),
            # A member's own boss again is no move: no depth check for it (§2.3).
            keeps_boss=existing.reports_to if existing else None,
        )
        if existing is not None:
            # A second clone of a member: a new instance, the membership as it is.
            # A role change goes through PATCH …/members/{id}, never through a join.
            differing = {
                k: "differs_from_membership" for k, v in values.items() if getattr(existing, k) != v
            }
            if body.briefing is not None and body.briefing != existing.briefing:
                differing["briefing"] = "differs_from_membership"
            if differing:
                raise invalid(differing, "the agent is a member; change its membership instead")
            values = {
                "trust": existing.trust,
                "role": existing.role,
                "reports_to": existing.reports_to,
                "areas": existing.areas,
                "capabilities": existing.capabilities,
            }
        # After the member's own trust and role are in: a new instance of an admin or a
        # proxy hands out a credential with that trust, which is the owner's to give.
        _require_owner_for(mine, values)
        _check_instance(conn, body, existing)
        if member_rule and existing is None:
            # The count and the new join are one step under the project's lock (§3.1).
            project = lock_project(conn, mine.project.id)
            _require_slot(conn, project, caller.principal_id, agent_id)
        values.setdefault("trust", "member")
        values.setdefault("role", "coder")
        values.setdefault("areas", [])
        values.setdefault("capabilities", [])
        token, code = new_token(), new_code()
        now = clock.now()
        join_id = new_id("join")
        conn.execute(
            insert(t.join_link).values(
                id=join_id,
                project_id=mine.project.id,
                token_hash=digest(token),
                code_hash=digest(normalise_code(code)),
                agent_id=agent_id,
                trust=values["trust"],
                role=values["role"],
                reports_to=values.get("reports_to"),
                areas=values["areas"],
                capabilities=values["capabilities"],
                briefing=body.briefing or None,
                via=via,
                new_instance=bool(body.new_instance),
                replaces=body.replaces,
                created_by=caller.principal_id,
                created_at=now,
                expires_at=now + timedelta(seconds=body.ttl_seconds),
                failed_attempts=0,
                member_rule=member_rule,
            )
        )
        join_url = join_link(settings, via, token)
        return idempotency.Outcome(
            201,
            "join",
            join_id,
            {
                "id": join_id,
                "join_url": join_url,
                "code": code,
                "paste_line": f"maity join {join_url} --code {code}",
                "agent_id": agent_id,
                "project": namespace.full_name(conn, mine.project),
                "expires_at": clock.rfc3339(now + timedelta(seconds=body.ttl_seconds)),
                "via": via,
            },
        )

    return idempotency.run(engine_of(request), request, caller, action)


def _require_owner_for(mine: Any, values: dict[str, Any]) -> None:
    """Trust `admin` and the role `proxy` are given only by a caller with trust `owner`
    (§2.3 "The owner's rights", §3.1)."""
    if (values.get("trust") == "admin" or values.get("role") == "proxy") and mine.trust != "owner":
        raise ApiError(
            403,
            "forbidden",
            "only an owner grants trust admin or the role proxy",
            {"reason": "owner_only"},
        )


def _check_instance(conn: Connection, body: JoinCreate, existing: Any) -> None:
    """A member's join says which instance it adds; a first join says neither (§3.1)."""
    if existing is None:
        if body.new_instance is not None or body.replaces is not None:
            field = "replaces" if body.replaces is not None else "new_instance"
            raise invalid({field: "not_a_member"}, "a first join creates the first instance")
        return
    if body.new_instance and body.replaces is not None:
        raise invalid({"instance": "one_of"}, "new_instance or replaces, not both")
    if body.replaces is not None:
        if not instances.INSTANCE_PATTERN.fullmatch(body.replaces):
            raise invalid({"replaces": "not_an_instance"})
        instances.require_active(conn, existing, body.replaces, "replaces")
        return
    if not body.new_instance:
        raise invalid({"instance": "required"}, "the agent is a member: new_instance or replaces")
    instances.refuse_over_quota(conn, existing)


# --- bringing your own agent (§3.1) ------------------------------------------------


def _limit(field: str) -> ApiError:
    return ApiError(
        403,
        "forbidden",
        "beyond what a member may give an agent of their own",
        {"reason": "member_join_limit", "field": field},
    )


def _may_bring(mine: Any) -> bool:
    """A human with trust `member` who may bring agents of their own: never an agent,
    whose joins go through `members:admin` alone."""
    return bool(mine.kind == "human" and mine.trust == "member")


def _require_own_joins(mine: Any) -> None:
    """Listing and revoking one's own joins (§3.1): whoever may bring agents, also while
    `member_agents` is `off`, since the joins already handed out stay usable."""
    if not _may_bring(mine):
        raise forbidden("members:admin")


def _require_member_rule(mine: Any) -> None:
    """Without `members:admin`, a join is a member's under `policy.member_agents`, or
    the scope's `forbidden` as before the rule (§3.1)."""
    if not _may_bring(mine) or mine.project.member_agents != "on":
        raise forbidden("members:admin")


def _within_limits(membership_row: Any) -> bool:
    """A membership a member's join may add an instance to: trust and role within §3.1."""
    return bool(
        membership_row.trust in MEMBER_RULE_TRUSTS and membership_row.role_base in MEMBER_RULE_ROLES
    )


def _own_manager(conn: Connection, mine: Any, member_id: str) -> bool:
    """`member_id` is an agent of the caller with the role `manager` in this project,
    so a member brings a manager and the team below it (§3.1)."""
    found = conn.execute(
        select(t.membership.c.id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(
            t.membership.c.project_id == mine.project.id,
            t.membership.c.agent_id == member_id,
            t.membership.c.active.is_(True),
            t.membership.c.role == "manager",
            t.agent_profile.c.owner_id == mine.principal_id,
        )
    ).first()
    return found is not None


def _check_member_limits(conn: Connection, body: JoinCreate, mine: Any, existing: Any) -> None:
    """The limits of §3.1 a member's join stays within, the first broken one named."""
    if body.trust is not None and body.trust not in MEMBER_RULE_TRUSTS:
        raise _limit("trust")
    base = project_roles.base_of(mine.project, body.role) if body.role is not None else None
    if base is not None and base not in MEMBER_RULE_ROLES:
        raise _limit("role")  # a role the project does not have is `invalid` below
    if (
        body.reports_to is not None
        and body.reports_to != mine.principal_id
        and not _own_manager(conn, mine, body.reports_to)
    ):
        raise _limit("reports_to")
    if body.areas:
        raise _limit("areas")
    if body.capabilities:
        raise _limit("capabilities")
    if existing is not None and not _within_limits(existing):
        # A membership an admin raised beyond the limits gets new instances only
        # through `members:admin`.
        raise _limit("agent")


def _agents_held(conn: Connection, project_id: str, owner_id: str) -> set[str]:
    """The owner's distinct agent profiles with an active membership in the project or an
    open first join to it (§3.1): a profile counts once, an instance join not at all."""
    owned = select(t.agent_profile.c.id).where(t.agent_profile.c.owner_id == owner_id)
    members = conn.execute(
        select(t.membership.c.agent_id).where(
            t.membership.c.project_id == project_id,
            t.membership.c.active.is_(True),
            t.membership.c.agent_id.in_(owned),
        )
    ).scalars()
    j = t.join_link.c
    open_joins = conn.execute(
        select(j.agent_id).where(
            j.project_id == project_id,
            j.agent_id.in_(owned),
            j.new_instance.is_(False),
            j.replaces.is_(None),
            j.placement_id.is_(None),
            j.used_at.is_(None),
            j.burned_at.is_(None),
            j.revoked_at.is_(None),
            j.expires_at > clock.now(),
        )
    ).scalars()
    return set(members) | set(open_joins)


def _require_slot(conn: Connection, project: Any, owner_id: str, agent_id: str) -> None:
    """The owner's agents stay within `policy.member_agents_max`, read under the
    project's lock the caller took."""
    held = _agents_held(conn, project.id, owner_id)
    if agent_id not in held and len(held) >= project.member_agents_max:
        raise ApiError(
            403,
            "forbidden",
            "you hold as many agents in this project as its policy allows",
            {"reason": "member_agents_max", "max": project.member_agents_max},
        )


def _recheck_member_rule(conn: Connection, row: Any, project: Any, member: Any) -> None:
    """A member's join at the exchange, under the project lock (§3.3): what may have
    changed since it was issued. A failure voids it, answered as a revoked join; a
    creator raised to `members:admin` meanwhile keeps it, and `member_agents` turned
    `off` does not void it."""
    creator = conn.execute(
        select(t.membership.c.trust, t.membership.c.role_base).where(
            t.membership.c.project_id == row.project_id,
            t.membership.c.human_id == row.created_by,
            t.membership.c.active.is_(True),
        )
    ).first()
    if creator is None:
        raise not_found()
    if has_scope(creator.trust, creator.role_base, "human", "members:admin"):
        return
    if creator.trust != "member":  # a guest now, or anything else below: void
        raise not_found()
    if member is not None:
        if not _within_limits(member):
            raise not_found()
        return
    # What the member would hold once this join is exchanged: the distinct profiles of
    # their memberships and open first joins, this join's own included, against the
    # maximum now. Another open join naming the same profile is no exemption: a lowered
    # maximum holds for it too.
    held = _agents_held(conn, row.project_id, row.created_by) | {row.agent_id}
    if len(held) > project.member_agents_max:
        raise not_found()


def live_profile(conn: Connection, agent_id: str) -> None:
    """Lock the agent's profile, and refuse a deleted one: a deleted profile never joins
    again (§6.3). Join creation, the exchange and the profile's deletion all take this
    lock first, before the join and the project, so a deletion cannot commit between
    the check and the new membership."""
    deleted = conn.execute(
        select(t.agent_profile.c.deleted_at)
        .where(t.agent_profile.c.id == agent_id)
        .with_for_update()
    ).one()
    if deleted.deleted_at is not None:
        raise not_found()


def _agent_for_join(
    conn: Connection,
    agent: JoinAgent,
    owner_id: str,
    member_rule: bool = False,
    limit: int | None = None,
) -> str:
    if agent.id is not None:
        if agent.handle is not None or agent.display_name is not None:
            raise invalid({"agent": "id_or_handle"}, "name an agent by id, or create one")
        owned = conn.execute(
            select(t.agent_profile.c.id).where(
                t.agent_profile.c.id == agent.id, t.agent_profile.c.owner_id == owner_id
            )
        ).first()
        if owned is None and member_rule:
            raise _limit("agent")  # never another human's (§3.1)
        if owned is None:
            raise invalid({"agent.id": "not_yours"}, "a join names one of your own agents")
        live_profile(conn, agent.id)
        return agent.id
    if agent.handle is None or agent.display_name is None:
        raise invalid(
            {"agent": "id_or_handle"}, "name an agent by id, or give handle and display_name"
        )
    return create_profile(
        conn, owner_id, agent.handle, agent.display_name, agent.git_identity, limit
    )


@router.get("/projects/{owner}/{slug}/joins")
def list_joins(slug: str, request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        query = select(t.join_link).where(t.join_link.c.project_id == mine.project.id)
        if not mine.may("members:admin"):
            _require_own_joins(mine)
            query = query.where(t.join_link.c.created_by == mine.principal_id)
        rows = conn.execute(query.order_by(t.join_link.c.created_at.desc())).all()
        return JSONResponse({"items": [join_view(conn, r) for r in rows], "next_cursor": None})


@router.delete("/projects/{owner}/{slug}/joins/{join_id}")
def revoke_join(slug: str, join_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        own_only = not mine.may("members:admin")
        if own_only:
            _require_own_joins(mine)
        row = conn.execute(
            select(t.join_link).where(
                t.join_link.c.id == join_id, t.join_link.c.project_id == mine.project.id
            )
        ).first()
        if row is None or (own_only and row.created_by != mine.principal_id):
            raise not_found()
        if row.revoked_at is None:
            state = _spent(row)
            if state is not None:
                raise ApiError(
                    409,
                    "invalid_transition",
                    f"a {state} join cannot be revoked",
                    {"from": state, "to": "revoked"},
                )
            conn.execute(
                update(t.join_link)
                .where(t.join_link.c.id == join_id)
                .values(revoked_at=clock.now())
            )
        return idempotency.Outcome(200, "join", join_id, load_join(conn, join_id))

    return idempotency.run(engine_of(request), request, caller, action)


def _spent(row: Any) -> str | None:
    if row.used_at is not None:
        return "used"
    if row.burned_at is not None:
        return "burned"
    if row.expires_at <= clock.now():
        return "expired"
    return None


def _usable(conn: Connection, token: str) -> Any:
    row = conn.execute(select(t.join_link).where(t.join_link.c.token_hash == digest(token))).first()
    if row is None or row.revoked_at is not None or _spent(row) is not None:
        raise not_found()
    return row


# --- the join page --------------------------------------------------------------------


def _template() -> str:
    """docs/join-page.md: shipped in the wheel, read from the checkout otherwise."""
    shipped = files("maity_hub") / "join-page.md"
    if shipped.is_file():
        text = shipped.read_text(encoding="utf-8")
    else:
        text = (Path(__file__).resolve().parents[4] / "docs" / "join-page.md").read_text(
            encoding="utf-8"
        )
    return re.sub(r"\A\s*<!--.*?-->\s*", "", text, flags=re.S)


_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~])")


def _md(text: str) -> str:
    """Text a human typed (a project name), safe inside the Markdown template."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


# Put first on the page when the project's policy has `signing: required` (§3.2, step 7).
_SIGNING_REQUIRED = """## This project requires the CLI

Every call after the exchange must be signed, and only the `maity` command
signs: a call with the bearer credential is refused with `signature_required`.
Install the CLI and join with it:

```sh
{{cli_install}}
maity join {{join_link}} --code <code>
```

If you cannot install it yet, the exchange in section 3 still works and
stores the credential where the CLI looks for it; the calls with `curl.conf`
after it are refused. Install the CLI then and run `maity resume --hub {{hub}}`
once.
"""


def join_link(settings: Settings, via: str, token: str) -> str:
    """The join URL on the join host (no prefix, §1.1) or on the public URL."""
    if via == "join" and settings.join_url is not None:
        return f"{settings.join_url}/{token}"
    return f"{settings.public_url}/join/{token}"


def exchange_url(settings: Settings, on_join_host: bool, token: str) -> str:
    """Where the page's exchange recipe posts: the same URL on the join host."""
    if on_join_host and settings.join_url is not None:
        return f"{settings.join_url}/{token}"
    return f"{settings.public_url}/api/v1/join/{token}"


def render_page(
    conn: Connection, row: Any, token: str, settings: Settings, on_join_host: bool = False
) -> tuple[str, str]:
    """The page as Markdown, and its title. Every URL after the exchange is the public
    URL's, also on the join host (§3.2)."""
    hub = settings.public_url
    link = join_link(settings, "join" if on_join_host else "public", token)
    project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
    handle = row.new_agent_handle  # a profile the exchange creates (a runner's pickup)
    if row.agent_id is not None:
        handle = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == row.agent_id)
        ).scalar_one()
    reports_to = principal_id(conn, row.reports_to)
    if reports_to is not None:
        boss = (
            conn.execute(
                select(t.agent_profile.c.handle).where(t.agent_profile.c.id == reports_to)
            ).scalar()
            or conn.execute(select(t.human.c.handle).where(t.human.c.id == reports_to)).scalar()
        )
        reports_to_text = f"`{boss}`"
    else:
        reports_to_text = "nobody"
    values = {
        "project_name": _md(project.name),
        "project_repository": _md(project.repository_url or "not configured"),
        "project": namespace.full_name(conn, project),
        "handle": handle,
        "role": row.role,
        "areas": ", ".join(f"`{a}`" for a in row.areas) or "none",
        "reports_to": reports_to_text,
        "hub": hub,
        "token": token,
        "join_link": link,
        # The host `maity join` keys an identity's directory by outside a clone (cli/README).
        "join_host": urllib.parse.urlsplit(link).netloc.lower(),
        "cli_install": settings.cli_install,
        "exchange_url": exchange_url(settings, on_join_host, token),
        "signing_required": (
            _SIGNING_REQUIRED.replace("{{hub}}", hub)
            .replace("{{join_link}}", link)
            .replace("{{cli_install}}", settings.cli_install)
            if project.signing == "required"
            else ""
        ),
        "cli_status": (
            "This project requires it: every call after the exchange must be signed."
            if project.signing == "required"
            else "It is optional:"
        ),
    }
    text = _TEMPLATE_PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), _template())
    return text, f"Join {project.name} on Maity"


_HTML = MarkdownIt("commonmark", {"html": False}).enable("table")


def _html(markdown: str, title_text: str, dashboard: str = "/") -> str:
    body = _HTML.render(markdown)
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title_text)}</title>\n</head>\n<body>\n<main>\n{body}</main>\n"
        "<footer><p>This page is documentation for the agent you are adding. "
        f'It has no form and performs no call. <a href="{html.escape(dashboard)}">'
        "Open the dashboard</a>.</p>"
        "</footer>\n</body>\n</html>\n"
    )


# The join host's answer to a token-shaped path that no longer works (§1.1): never
# which of the reasons applies.
_DEAD_LINK = """# This join link no longer works

Ask the person who sent it to you for a new join line. Nobody needs to do
anything else.
"""


async def _page(token: str, request: Request) -> Response:
    engine = engine_of(request)
    settings = settings_of(request)
    on_join_host = bool(request.scope["state"].get("join_host"))
    dashboard = f"{settings.public_url}/" if on_join_host else "/"

    def run() -> tuple[str, str]:
        with engine.begin() as conn:
            return render_page(conn, _usable(conn, token), token, settings, on_join_host)

    try:
        markdown, title_text = await run_in_threadpool(run)
        status = 200
    except ApiError as error:
        if not (on_join_host and error.status == 404):
            raise
        markdown, title_text, status = _DEAD_LINK, "This join link no longer works", 404
    # The dead link is the envelope's `not_found` for a client reading the header (§1.3).
    headers = {"Maity-Error": "not_found"} if status == 404 else None
    if "text/html" in request.headers.get("accept", ""):
        return Response(
            _html(markdown, title_text, dashboard),
            status_code=status,
            media_type="text/html; charset=utf-8",
            headers=headers,
        )
    return Response(
        markdown,
        status_code=status,
        media_type="text/markdown; charset=utf-8",
        headers=headers,
    )


@router.get("/join/{token}")
async def join_page(token: str, request: Request) -> Response:
    return await _page(token, request)


@page_router.get("/join/{token}")
async def public_join_page(token: str, request: Request) -> Response:
    return await _page(token, request)


# --- the exchange -------------------------------------------------------------------------


@router.post("/join/{token}")
async def exchange(token: str, body: Exchange, request: Request) -> Response:
    origin = origin_of(request)
    settings = settings_of(request)
    # The answer is a credential: it travels like one (§2.5).
    require_secure_transport(origin, settings.allow_plain_http)
    if request.headers.get("authorization"):
        raise forbidden(message="the exchange takes no credential")
    wait = EXCHANGE_BY_ADDRESS.hit(origin.address)
    if wait:
        raise rate_limited(wait)
    engine = engine_of(request)

    def run() -> tuple[str, str, str, str, str, str] | None:
        """The credential facts, or None for a wrong code (recorded and committed)."""
        with events.transaction(engine) as conn:
            row = _usable(conn, token)
            # The owner's account lock before any other (§2.9): a suspension or a
            # deletion takes it first; `_consume` refuses a suspended account under it.
            owner = _owner(conn, row)
            if owner is not None:
                write_guard.share(conn, owner)
            if row.agent_id is not None:  # a pickup's new profile does not exist yet (§15.9)
                live_profile(conn, row.agent_id)  # first, as the deletion takes it (§6.3)
            # Take an attempt slot before comparing: one conditional UPDATE, so
            # concurrent guesses cannot all read the same count (a lost update
            # would let more than three codes be tried, or unburn a join).
            now = clock.now()
            slot = conn.execute(
                update(t.join_link)
                .where(
                    t.join_link.c.id == row.id,
                    t.join_link.c.failed_attempts < WRONG_CODES_BEFORE_BURN,
                    t.join_link.c.used_at.is_(None),
                    t.join_link.c.burned_at.is_(None),
                    t.join_link.c.revoked_at.is_(None),
                    t.join_link.c.expires_at > now,
                )
                .values(failed_attempts=t.join_link.c.failed_attempts + 1)
            ).rowcount
            if slot != 1:
                raise not_found()
            if code_matches(body.code, row.code_hash):
                return _consume(conn, row, body.client)
            conn.execute(
                update(t.join_link)
                .where(
                    t.join_link.c.id == row.id,
                    t.join_link.c.failed_attempts >= WRONG_CODES_BEFORE_BURN,
                    t.join_link.c.burned_at.is_(None),
                )
                .values(burned_at=now)
            )
        return None

    outcome = await run_in_threadpool(retrying, run)
    if outcome is None:
        raise ApiError(403, "code_invalid", "the code does not match this join")
    value, credential_id, agent_id, project_slug, signing, instance = outcome
    return Response(
        value,
        status_code=201,
        media_type="text/plain; charset=utf-8",
        headers={
            "Maity-Credential-Id": credential_id,
            "Maity-Member-Id": agent_id,
            "Maity-Instance": instance,
            "Maity-Project": project_slug,
            "Maity-Hub": settings.public_url,
            # The page's curl recipe prints the headers: a project that refuses
            # bearer calls says so in the same step (§3.3).
            "Maity-Signing": signing,
        },
    )


def _boss_still_here(conn: Connection, reports_to: int | None) -> int | None:
    """The link's `reports_to` while it names an active member and the chain still has
    room for the new member, else null (§6.2, §2.3 "Depth"). Read under the project
    lock: `row` was read before it, and a removal may have committed in between, so the
    link's own column cannot be trusted here."""
    if reports_to is None:
        return None
    active = conn.execute(
        select(t.membership.c.id, t.membership.c.project_id).where(
            t.membership.c.id == reports_to, t.membership.c.active.is_(True)
        )
    ).first()
    if active is None or not line.fits(conn, active.project_id, reports_to):
        return None
    return reports_to


def _owner(conn: Connection, row: Any) -> str | None:
    """The account a join issues for: the profile's owner (None once the profile is
    gone), or the creator for a profile the exchange creates."""
    if row.agent_id:
        return moderation.owner_account(conn, row.agent_id)
    return str(row.created_by)


def _consume(conn: Connection, row: Any, client: str) -> tuple[str, str, str, str, str, str]:
    moderation.refuse_suspended(conn, _owner(conn, row))  # no credential for it (§16.8)
    # Serialise with every other write to the project: two first exchanges for
    # one new agent must not both insert its membership.
    lock_project(conn, row.project_id)
    now = clock.now()
    consumed = conn.execute(
        update(t.join_link)
        .where(
            t.join_link.c.id == row.id,
            t.join_link.c.used_at.is_(None),
            t.join_link.c.burned_at.is_(None),
            t.join_link.c.revoked_at.is_(None),
        )
        .values(used_at=now)
    ).rowcount
    if consumed != 1:  # a concurrent exchange won
        raise not_found()
    if row.placement_id is not None:
        _require_pickup_holds(conn, row)
    project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
    if row.member_rule:
        _recheck_member_rule(conn, row, project, _active_member(conn, row))
    agent_id = row.agent_id or _create_for_join(conn, row)
    member = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == row.project_id,
            t.membership.c.agent_id == agent_id,
            t.membership.c.active.is_(True),
        )
    ).first()
    if member is None and (row.replaces is not None or (row.placement_id and row.agent_id)):
        # A pickup for a member, or a rejoin, never brings back a member a human removed
        # (§15.9): it answers as every join that no longer works (§1.1).
        raise not_found()
    if member is None:
        result = conn.execute(
            insert(t.membership).values(
                project_id=row.project_id,
                agent_id=agent_id,
                trust=row.trust,
                role=row.role,
                # A role still named by an open join cannot be removed (§2.3).
                role_base=project_roles.base_of(project, row.role),
                reports_to=_boss_still_here(conn, row.reports_to),
                areas=row.areas,
                capabilities=row.capabilities,
                briefing=row.briefing,
                joined_at=now,
            )
        )
        key = result.inserted_primary_key
        assert key is not None
        membership_id = int(key[0])
        # Version 1, by whoever made the join (§6.2), even when it carries no text.
        briefings.record(conn, membership_id, row.briefing, row.created_by, now)
    else:
        membership_id = member.id
        _recheck_instance(conn, row, member)
    joined = member is None
    credential_id = new_id("credential")
    value, verifier = credentials.issue(credential_id)
    instance = instances.next_id(conn, membership_id)
    conn.execute(
        insert(t.credential).values(
            id=credential_id,
            membership_id=membership_id,
            instance=instance,
            replaces=row.replaces,
            verifier=verifier,
            join_id=row.id,
            client=client,
            created_at=now,
        )
    )
    conn.execute(update(t.join_link).where(t.join_link.c.id == row.id).values(instance=instance))
    if row.replaces is not None and member is not None:
        # Moved before the revocation, so that the lead passes on and is never null.
        _move_to_replacement(conn, member, row.replaces, instance, credential_id)
        if row.placement_id is None:  # a rejoin's instance is revoked already (§15.9),
            # and `_recheck_instance` checked it: nothing to revoke, no second revocation
            old = instances.require_active(conn, member, row.replaces, "replaces")
            revoke(conn, old.id, "replaced", by=row.created_by)
            emit(
                conn,
                row.project_id,
                "credential_revoked",
                [f"member:{row.agent_id}", "trust:owner"],
                {"credential_id": old.id, "reason": "replaced", "instance": row.replaces},
                actor=Actor(membership_id=membership_id, credential_id=credential_id),
                subject=("credential", old.id),
            )
    if row.placement_id is not None:  # a runner's pickup: the placement now runs on it
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == row.placement_id)
            .values(
                credential_id=credential_id,
                rejoin=False,
                membership_id=membership_id,
                updated_at=now,
            )
        )
    if joined:
        new = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
        emit(
            conn,
            row.project_id,
            "member_joined",
            ["all"],
            member_view(conn, new),
            actor=Actor(membership_id=membership_id, credential_id=credential_id),
            subject=("member", agent_id),
        )
    name = namespace.full_name(conn, project)  # the join answer's project (§6.25)
    return value, credential_id, agent_id, name, project.signing, instance


def _active_member(conn: Connection, row: Any) -> Any:
    if row.agent_id is None:
        return None
    return conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == row.project_id,
            t.membership.c.agent_id == row.agent_id,
            t.membership.c.active.is_(True),
        )
    ).first()


def _require_pickup_holds(conn: Connection, row: Any) -> None:
    """A runner's pickup (§15.9) is exchanged only while what it was picked up for still
    holds, read under the project lock: the placement active, approved, `desired: running`
    and at the join's generation on the same runner, and that runner not removed and with
    a live credential. Otherwise it answers as every join that no longer works (§1.1)."""
    p = t.placement.c
    placement = conn.execute(
        select(p.runner_id, p.closed_at, p.desired, p.approval_status, p.generation).where(
            p.id == row.placement_id
        )
    ).first()
    runner = conn.execute(
        select(t.runner.c.removed_at).where(t.runner.c.id == row.runner_id)
    ).first()
    live = conn.execute(
        select(t.runner_credential.c.id).where(
            t.runner_credential.c.runner_id == row.runner_id,
            t.runner_credential.c.revoked_at.is_(None),
        )
    ).first()
    if (
        placement is None
        or placement.runner_id != row.runner_id
        or placement.closed_at is not None
        or placement.desired != "running"
        or placement.approval_status != "approved"
        or placement.generation != row.generation
        or runner is None
        or runner.removed_at is not None
        or live is None
    ):
        raise not_found()


def _recheck_instance(conn: Connection, row: Any, member: Any) -> None:
    """The join's instance rules again under the project lock (§3.3): another
    exchange may have used the slot or revoked the instance to replace since. The
    code is then not consumed: the transaction rolls back."""
    if row.replaces is not None and row.placement_id is not None:
        # A placement's rejoin: a revoked instance, and one more active instance (§15.9).
        instances.require_replaceable(conn, member, row.replaces, "replaces", revoked=True)
        instances.refuse_over_quota(conn, member)
    elif row.replaces is not None:
        instances.require_active(conn, member, row.replaces, "replaces")
    elif row.new_instance:
        instances.refuse_over_quota(conn, member)
    else:
        # A join made before instances existed, for a member: it adds one.
        instances.refuse_over_quota(conn, member)


def _move_to_replacement(
    conn: Connection, member: Any, old: str, new: str, credential_id: str
) -> None:
    """The replaced instance's claims, checkpoints and place as lead move to the new
    instance, each card with a `task_claimed` naming `replaces` (§6.17)."""
    from maity_hub.routes.tasks import audience  # tasks imports this module's neighbours

    now = clock.now()
    held = conn.execute(
        select(t.card).where(
            t.card.c.claim_holder == member.id,
            t.card.c.claim_instance == old,
            t.card.c.status.notin_(("done", "cancelled")),
        )
    ).all()
    for card in held:
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card.id)
            .values(claim_instance=new, claim_session_id=None, updated_at=now)
        )
    conn.execute(
        update(t.card)
        .where(t.card.c.assigned_to == member.id, t.card.c.assigned_instance == old)
        .values(assigned_instance=new)
    )
    if member.lead_instance == old:
        conn.execute(
            update(t.membership).where(t.membership.c.id == member.id).values(lead_instance=new)
        )
    actor = Actor(membership_id=member.id, credential_id=credential_id)
    for card in held:
        card = conn.execute(select(t.card).where(t.card.c.id == card.id)).one()
        emit(
            conn,
            member.project_id,
            "task_claimed",
            audience(conn, card),
            {
                "holder": member.agent_id,
                "instance": new,
                "replaces": old,
                "lease_until": clock.rfc3339(card.lease_until) if card.lease_until else None,
            },
            actor=actor,
            subject=("task", card.id),
        )
        # A takeover from the replaced instance ends with it (§6.19).
        takeovers.reconcile(conn, card.id, actor, decided=False)


def _create_for_join(conn: Connection, row: Any) -> str:
    """The profile a pickup's join names by handle (§15.9): created at the exchange,
    owned by the human who created the placement. A handle that human has meanwhile given
    another agent ends the join here, answered as every join that no longer works (§1.1):
    the placement cannot become that agent, and the runner's next pickup reports it."""
    taken = conn.execute(
        select(t.agent_profile.c.id).where(
            t.agent_profile.c.owner_id == row.created_by,
            t.agent_profile.c.handle == row.new_agent_handle,
        )
    ).first()
    if taken is not None or handles.holder(conn, row.created_by, row.new_agent_handle) not in (
        None,
        "placement",
    ):
        raise not_found()
    # `POST /agents` does not take the project lock: a profile of that handle may land
    # after the check above. Its `invalid`, or the unique constraint, is still a join
    # that no longer works, never a 400 or a 500 that tells the holder of the link more.
    try:
        return create_profile(
            conn, row.created_by, row.new_agent_handle, row.new_agent_display_name, None,
            placement=True,
        )  # fmt: skip
    except IntegrityError:
        raise not_found() from None
    except ApiError as error:
        if error.code == "invalid":
            raise not_found() from None
        raise
