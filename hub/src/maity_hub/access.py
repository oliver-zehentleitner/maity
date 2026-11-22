"""Who may touch which project (docs/api.md §2.3).

A project the caller is not a member of does not exist for it: `not_found`,
never `forbidden`, so that projects cannot be enumerated. Within a project
the membership's trust and role decide, by scope.

The one exception is a public project's *outsider* (§2.3, "Reading a public project from
outside"): a signed-in human without an active membership reads the routes `OUTSIDE_READS`
names, and only those, as an `OutsideReader`. Closed by construction (hub/context/public-pages.md
3f9c2d71, "A signed-in outsider reads a public project through a closed list of member
routes"): a route is open to an outsider only when its endpoint calls `reader` and carries
`@outside_read`, and `ProjectRoute` answers an outsider's call to any other project route
`not_found` before its body or query is read (`gate`). A human who
owns an agent or a runner in the project passes the gate on `OWNER_CALLS` alone (§1.3), and
reads not-done `security` cards no more than any outsider does (`public_cards.shown`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import clock, namespace, proxy_go
from maity_hub import tables as t
from maity_hub.auth.caller import SESSION_COOKIE, Caller, session_alive, session_id_hash
from maity_hub.errors import ApiError, forbidden, not_found
from maity_hub.scopes import GOVERNANCE, has_scope

# What a bridge never calls under, for the agent it serves (§2.3, "The bridge").
BRIDGE_WITHHELD = frozenset({*GOVERNANCE, "line:lead"})


@dataclass(frozen=True)
class Membership:
    """The caller's own membership in one project, with the project row."""

    project: Any
    row: Any
    kind: str  # human, agent
    instance: str | None = None  # the calling agent instance (§6.17); None for a human
    bridged: bool = False  # a bridge calls as this agent, with `Maity-For` (§2.3)
    go: proxy_go.ProxyGo | None = None  # a proxy's call: the owner's go for it (§2.3)
    # A bridge's call: its own membership's hidden windows (§6.2), which the reads hide beside
    # the served agent's. `row` is then the agent's row with both (`events.carried_row`), also
    # after a `replace` with a row read again.
    bridge_windows: tuple[dict[str, int], ...] = ()

    def __post_init__(self) -> None:
        if self.bridge_windows:
            from maity_hub.events import carried_row

            object.__setattr__(self, "row", carried_row(self.row, self.bridge_windows))

    @property
    def id(self) -> int:
        membership_id: int = self.row.id
        return membership_id

    @property
    def role(self) -> str:
        role: str = self.row.role
        return role

    @property
    def role_base(self) -> str:
        """The built-in role whose scopes `role` has (§2.3 "Project roles")."""
        base: str = self.row.role_base
        return base

    @property
    def trust(self) -> str:
        """For a bridge's call the served agent's trust without what `owner` and `admin`
        add (§2.3): it acts in its role, never as part of the admin team."""
        trust: str = self.row.trust
        if self.bridged and trust in ("owner", "admin"):
            return "member"
        return trust

    @property
    def principal_id(self) -> str:
        principal: str = self.row.agent_id or self.row.human_id
        return principal

    def may(self, scope: str) -> bool:
        if self.bridged and scope in BRIDGE_WITHHELD:
            return False
        if self._needs_go(scope):
            return self.go is not None and self.go.spend()
        return has_scope(self.trust, self.role_base, self.kind, scope)

    def _needs_go(self, scope: str) -> bool:
        return (
            self.role_base == "proxy"
            and self.trust in ("owner", "admin")
            and proxy_go.gated(scope, self.kind)
        )

    def require(self, scope: str) -> None:
        if self.bridged and scope in BRIDGE_WITHHELD:
            raise ApiError(
                403,
                "forbidden",
                "a bridge calls under no governance scope and no line:lead",
                {"scope": scope, "reason": "bridge_no_governance"},
            )
        if self.may(scope):
            return
        if self._needs_go(scope):
            raise ApiError(
                403,
                "forbidden",
                "a proxy's governance call needs the owner's go for exactly this call",
                {
                    "scope": scope,
                    "reason": "proxy_needs_decision",
                    "on_request": self.go.reason if self.go is not None else "missing",
                },
            )
        raise forbidden(scope)


def membership(conn: Connection, caller: Caller, slug: str) -> Membership:
    """The caller's active membership in the project `slug` names: its full name
    `<owner>/<slug>`, current or an alias (§6.25), as `ProjectRoute` hands it to a route."""
    project = namespace.resolve(conn, slug)
    if project is None or caller.kind == "runner":  # a runner is no member (§15.1)
        raise not_found()
    # An agent credential belongs to one membership, of one project (§2.2): the
    # profile's memberships elsewhere are not reachable through it.
    principal = (
        t.membership.c.id == caller.membership_id
        if caller.kind == "agent"
        else t.membership.c.human_id == caller.human_id
    )
    row = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project.id,
            principal,
            t.membership.c.active.is_(True),
        )
    ).first()
    if row is None:
        raise not_found()
    go = (
        proxy_go.ProxyGo(conn, project.id, row.id, caller.on_request, caller.actor(row.id))
        if row.role_base == "proxy"
        else None
    )
    bridge_windows: tuple[dict[str, int], ...] = ()
    if caller.bridge is not None:
        bridge_windows = tuple(
            conn.execute(
                select(t.membership.c.isolation_windows).where(
                    t.membership.c.id == caller.bridge.membership_id
                )
            ).scalar()
            or ()
        )
    return Membership(
        project,
        row,
        caller.kind,
        caller.instance,
        caller.bridge is not None,
        go,
        bridge_windows,
    )


# --- the outsider of a public project (§2.3) ------------------------------------------------

API = "/api/v1"  # the prefix every `ProjectRoute` router of the API is included with
API_PROJECT = f"{API}/projects/{{owner}}/{{slug}}"

# The project routes an outsider reads, as (method, path template) the app lists them: every one
# a GET (§2.3). Each endpoint calls `reader` and carries `@outside_read`; `test_outside_reads`
# holds the three together, and `ProjectRoute` answers an outsider's call to any other project
# route `not_found` (`gate`).
OUTSIDE_READS = frozenset(
    {
        ("GET", API_PROJECT),
        ("GET", f"{API_PROJECT}/members"),
        ("GET", f"{API_PROJECT}/members/{{member_id}}"),
        ("GET", f"{API_PROJECT}/tasks"),
        ("GET", f"{API_PROJECT}/tasks/{{card_id}}"),
        ("GET", f"{API_PROJECT}/tasks/{{card_id}}/history"),
        ("GET", f"{API_PROJECT}/tasks/{{card_id}}/notes"),
        ("GET", f"{API_PROJECT}/logo"),
        ("GET", f"{API_PROJECT}/banner"),
        # The Why view, only while the hub last found the repository public (§11.3, §11.5).
        ("GET", f"{API_PROJECT}/keep-the-why"),
        ("GET", f"{API_PROJECT}/keep-the-why/export"),
        ("GET", f"{API_PROJECT}/keep-the-why/bodies"),
    }
)

# The outside reads open to an outsider only while the hub last found the project's repository
# public, and only in a namespace the instance's token serves (§2.3, §11.4): `ProjectRoute` still
# passes them through `gate`, which answers an outsider `not_found` before the query is read
# otherwise, so no validation answer reaches an outsider the route is closed to. The endpoint
# then asks the forge itself (`routes/keep_the_why._outside_reader`).
PUBLIC_REPOSITORY_READS = frozenset(
    {
        ("GET", f"{API_PROJECT}/keep-the-why"),
        ("GET", f"{API_PROJECT}/keep-the-why/export"),
        ("GET", f"{API_PROJECT}/keep-the-why/bodies"),
    }
)

# The project routes a human who is no member keeps as the owner of an agent or a runner in the
# project (§1.3's `not_found` row, §2.3), as (method, path template): the only routes the gate
# passes for such an owner of a public project, whose route then answers as it always did
# (`_owns_a_part`); any other route answers them `not_found` before its body is read, as it does
# any outsider. Not here: the owner calls §1.3 names as not built (`POST …/takeovers/{id}/respond`
# answers members only, `DELETE …/tasks/{id}/objection-hold` has no route) and the meat-proxy
# mode, which an owner reading along does not set (§9.3).
OWNER_CALLS = frozenset(
    {
        # Reading a group chat along, and its writes there answered `forbidden` (`observer`)
        # but for the verdict, which it may give (§9.2, §9.7); pinning a chat it reads (§9.3).
        ("GET", f"{API_PROJECT}/conversations"),
        ("GET", f"{API_PROJECT}/conversations/{{conversation_id}}"),
        ("PATCH", f"{API_PROJECT}/conversations/{{conversation_id}}"),
        ("GET", f"{API_PROJECT}/conversations/{{conversation_id}}/messages"),
        ("POST", f"{API_PROJECT}/conversations/{{conversation_id}}/messages"),
        ("POST", f"{API_PROJECT}/conversations/{{conversation_id}}/participants"),
        ("DELETE", f"{API_PROJECT}/conversations/{{conversation_id}}/participants/{{member_id}}"),
        ("PUT", f"{API_PROJECT}/conversations/{{conversation_id}}/messages/{{seq}}/verdict"),
        ("DELETE", f"{API_PROJECT}/conversations/{{conversation_id}}/messages/{{seq}}/verdict"),
        ("PUT", f"{API_PROJECT}/conversations/{{conversation_id}}/pin"),
        ("DELETE", f"{API_PROJECT}/conversations/{{conversation_id}}/pin"),
        ("POST", f"{API_PROJECT}/events"),
        ("POST", f"{API_PROJECT}/events/{{seq}}/redact"),
        # The attachments of the messages it reads along (§9.2, §8.7).
        ("GET", f"{API_PROJECT}/attachments/{{attachment_id}}"),
        ("GET", f"{API_PROJECT}/attachments/{{attachment_id}}/content"),
        ("DELETE", f"{API_PROJECT}/attachments/{{attachment_id}}"),
        # A round its agent is a current participant of, as the minimal projection (§20.7).
        ("GET", f"{API_PROJECT}/jour-fixe/rounds/{{round_id}}"),
        # Its agent's briefings (§6.2), its agent's membership (§6.18, §19.4) and a connection
        # its agent serves as the bridge (§2.3).
        ("GET", f"{API_PROJECT}/members/{{member_id}}/briefings"),
        ("GET", f"{API_PROJECT}/members/{{member_id}}/briefing"),  # the one view (§19.3.1)
        ("PATCH", f"{API_PROJECT}/members/{{member_id}}"),
        ("DELETE", f"{API_PROJECT}/members/{{member_id}}/bridges/{{bridge_id}}"),
        # The placements on its runner (§15.3, §15.6).
        ("PATCH", f"{API_PROJECT}/placements/{{placement_id}}"),
        ("DELETE", f"{API_PROJECT}/placements/{{placement_id}}"),
    }
)

OUTSIDE_READ_MARK = "__maity_outside_read__"


def outside_read[Endpoint: Callable[..., Any]](endpoint: Endpoint) -> Endpoint:
    """Marks an endpoint an outsider reads (§2.3); its route is in `OUTSIDE_READS`."""
    setattr(endpoint, OUTSIDE_READ_MARK, True)
    return endpoint


@dataclass(frozen=True)
class OutsideRow:
    """The membership row an outsider does not have: no trust, no role and no hidden window
    (§6.2), so the reads that filter by a reader's row hide nothing more and nothing less."""

    human_id: str
    id: int = -1
    agent_id: None = None
    trust: None = None
    role: None = None
    role_base: None = None
    isolation_windows: tuple[dict[str, int], ...] = ()
    isolated_since: None = None


@dataclass(frozen=True)
class OutsideReader:
    """A signed-in human who reads a public project without an active membership in it
    (§2.3). No `Membership`: no write path takes one, it holds `project:read` alone, and it
    is never refused `forbidden`, which would say a scope exists for it: `not_found`."""

    project: Any
    principal_id: str
    row: OutsideRow = field(repr=False)
    kind: str = "human"
    id: int = -1
    trust: None = None
    role: None = None
    role_base: None = None
    instance: None = None
    bridged: bool = False
    go: None = None

    def may(self, scope: str) -> bool:
        return scope == "project:read"

    def require(self, scope: str) -> None:
        if not self.may(scope):
            raise not_found()


def reader(conn: Connection, caller: Caller, slug: str) -> Membership | OutsideReader:
    """Who reads the project `slug` names through one of `OUTSIDE_READS`: the caller's active
    membership when there is one (`membership`); otherwise an `OutsideReader` for a signed-in
    human (a dashboard session, never an agent, bridge or runner credential) while the project
    is public for outsiders now (`public_projects.public_for_outsiders`: public pages on, its
    page on, not archived, no hold, its owner in good standing), read on every call; otherwise
    `not_found`, as `membership` answers. A removed member reads as an outsider."""
    try:
        return membership(conn, caller, slug)
    except ApiError as refused:
        if refused.code != "not_found":
            raise
        if caller.kind != "human" or caller.via != "cookie" or caller.human_id is None:
            raise
        if caller.bridge is not None:
            raise
        from maity_hub import public_projects  # the public pages' modules, as `stars` reads them

        project = namespace.resolve(conn, slug)
        if project is None:
            raise
        if project.id not in public_projects.public_for_outsiders(conn, [project.id]):
            raise
        return OutsideReader(project, caller.human_id, OutsideRow(caller.human_id))


def _session_human(conn: Connection, cookie: str) -> str | None:
    """The human a live session cookie names, or None. One read; it writes nothing (the
    authentication after the gate writes the call's presence, §2.4)."""
    if not cookie.isascii():
        return None
    row = conn.execute(
        select(
            t.human_session.c.human_id,
            t.human_session.c.ended_at,
            t.human_session.c.expires_at,
            t.human_session.c.last_seen_at,
            t.human.c.deleted_at,
        )
        .join(t.human, t.human.c.id == t.human_session.c.human_id)
        .where(t.human_session.c.id_hash == session_id_hash(cookie))
    ).first()
    if row is None or row.ended_at is not None or row.deleted_at is not None:
        return None
    if not session_alive(row, clock.now()):
        return None
    return str(row.human_id)


def is_outsider(
    conn: Connection,
    cookie: str,
    slug: str,
    owner_call: bool = False,
    public_repository_read: bool = False,
    instance_namespaces: frozenset[str] | None = None,
) -> bool:
    """Whether the session cookie's human is an outsider of the public project `slug` names
    (§2.3) for this call. Cheapest refusals first: the project's own row (no page, archived,
    and for one of `PUBLIC_REPOSITORY_READS` (`public_repository_read`) a repository the hub
    last found public in a namespace the instance's token serves (`instance_namespaces`, None
    without a token), which opens the read to an outsider), then the session, then the
    human's membership, for one of `OWNER_CALLS` (`owner_call`) the owner's reads, and only
    then the whole public test."""
    project = namespace.resolve(conn, slug)
    if project is None or project.public_page != "on" or project.state == "archived":
        return False
    if (
        public_repository_read
        and project.repository_public is True
        and instance_serves_project(conn, project, instance_namespaces)
    ):
        return False  # the read is open to an outsider: the route answers them
    return _outsider_of(conn, cookie, project, owner_call)


def _outsider_of(conn: Connection, cookie: str, project: Any, owner_call: bool = False) -> bool:
    """`is_outsider` past the project's own row: the session, the membership, for one of
    `OWNER_CALLS` the owner's reads, and the whole public test."""
    human_id = _session_human(conn, cookie)
    if human_id is None:
        return False
    member = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == project.id,
            t.membership.c.human_id == human_id,
            t.membership.c.active.is_(True),
        )
    ).first()
    if member is not None:
        return False
    if owner_call and _owns_a_part(conn, project.id, human_id):
        return False
    from maity_hub import public_projects

    return project.id in public_projects.public_for_outsiders(conn, [project.id])


def open_why_project(
    conn: Connection, cookie: str, slug: str, instance_namespaces: frozenset[str]
) -> Any | None:
    """For one of `PUBLIC_REPOSITORY_READS` that `is_outsider` let through: the project row
    when the caller is an outsider whom the stored checks open it to (a repository the hub
    last found public, a namespace the instance's token serves), for `gate` to ask the forge
    live before the query is read; None for anyone else, whom the route answers as before."""
    project = namespace.resolve(conn, slug)
    if project is None or project.repository_public is not True:
        return None
    if not instance_serves_project(conn, project, instance_namespaces):
        return None
    return project if _outsider_of(conn, cookie, project) else None


def _lenient_max_age(request: Any) -> int:
    """The query's `max_age` before FastAPI reads it, for the visibility answer's window alone:
    parsed exactly as the route parses it (`ktw.max_age_of`, the same pydantic type), else the
    default (absent, or refused by the route later)."""
    from maity_hub import ktw

    found = ktw.max_age_of(request.query_params.get("max_age"))
    return ktw.DEFAULT_MAX_AGE if found is None else found


async def _why_visible_now(request: Any, project: Any, token: str) -> None:
    """The forge's answer on the repository before the query is read (`ktw_reads.
    outside_visible`, one function with the endpoint's, which then reuses the kept answer):
    `not_found` when not public or unanswered. The live ask runs in a worker thread, outside
    any database connection. A spent budget passes: the endpoint answers `probe_unavailable`
    with its `retry_at` after the query is read."""
    from anyio import to_thread

    from maity_hub import forge, ktw_reads

    max_age = _lenient_max_age(request)
    try:
        visible, asked = await to_thread.run_sync(
            ktw_reads.outside_visible, token, project.id, project.repository_url, max_age
        )
    except forge.ForgeUnavailableError:
        return
    if asked:
        ktw_reads.asked_now(project.id, project.repository_url)
    if not visible:
        raise not_found()


def instance_serves_project(
    conn: Connection, project: Any, instance_namespaces: frozenset[str] | None
) -> bool:
    """Whether the instance's token serves the project's namespace (§11.4), as the public
    view's **Why** decides it (`public_project_views.render_views`): `instance_namespaces` is
    the operator's own namespaces while the hub holds a token, None otherwise. Reads only."""
    if instance_namespaces is None:
        return False
    from maity_hub import forge_access  # it resolves projects through `namespace`, as here

    owner = namespace.full_name(conn, project).split("/", 1)[0]
    return forge_access.serves(instance_namespaces, owner)


def _owns_a_part(conn: Connection, project_id: str, human_id: str) -> bool:
    """Whether the human, no member, owns an agent that holds or held a membership in the
    project, or a runner a placement of the project runs on. Such an owner keeps the calls
    §1.3 lists for them, `OWNER_CALLS` and only those: the gate passes them there, and those
    routes answer them as they always did; any other route of the project answers them
    `not_found` before its body is read, as it answers any outsider."""
    agent = conn.execute(
        select(t.membership.c.id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(t.membership.c.project_id == project_id, t.agent_profile.c.owner_id == human_id)
        .limit(1)
    ).first()
    if agent is not None:
        return True
    runner = conn.execute(
        select(t.placement.c.id)
        .join(t.runner, t.runner.c.id == t.placement.c.runner_id)
        .where(t.placement.c.project_id == project_id, t.runner.c.owner_id == human_id)
        .limit(1)
    ).first()
    return runner is not None


async def gate(
    request: Any, owner_call: bool = False, public_repository_read: bool = False
) -> None:
    """`not_found` for an outsider's call to a project route not in `OUTSIDE_READS` (§2.3),
    before FastAPI reads its body or its query, so that no validation answer (`400 invalid`)
    tells an outsider what a route takes. `ProjectRoute` calls it for such a route, with
    `owner_call` for one of `OWNER_CALLS`, and with `public_repository_read` for one of
    `PUBLIC_REPOSITORY_READS`, which it opens to an outsider only while the project's stored
    `repository_public` is true and the instance's token serves its namespace (the app's
    settings: `forge_github_token`, `forge_instance_namespaces`) and the forge, asked live when
    its kept answer is older than the request's window (`_why_visible_now`), says the
    repository is public (the lead, seq 186723). Members, the owners
    `_owns_a_part` names on one of `OWNER_CALLS`, strangers to a private or unknown project,
    agents, bridges, runners and callers without a session pass unchanged: their call is
    answered exactly as before. A
    stranger to a private or unknown project needs no gate: the body is validated before the
    route's membership read for both alike, so `invalid` tells the one from the other no
    more than `not_found` does. It costs nothing while public pages are off, without a
    session cookie, or with a non-empty `Authorization` header; otherwise the project's
    resolve, and only for a project whose page is on the session's and the membership's read,
    and only for a human without a membership there (the owner's reads on one of
    `OWNER_CALLS`) and the public test.

    The caller is read as `caller.authenticate` reads it: a non-empty `Authorization` header
    authenticates and the cookie alongside is ignored, so such a call is no cookie caller's;
    an empty one authenticates nothing, and the cookie decides. `Maity-For` authenticates
    nothing on its own: a bridge calls with its own `Authorization` (§2.3), and a cookie
    caller with `Maity-For` is still that cookie's human, so it is gated as any outsider."""
    from maity_hub import public_pages

    if not public_pages.serving():
        return
    if request.headers.get("authorization"):  # as `caller.authenticate`: the header decides
        return
    cookie = request.cookies.get(SESSION_COOKIE)
    slug = (request.scope.get("path_params") or {}).get("slug")
    if not cookie or not slug:
        return
    instance = None  # the namespaces the instance's token serves (§11.4), from the settings
    token = None
    if public_repository_read:
        hub = request.app.state.settings
        token = hub.forge_github_token
        if token is not None:
            instance = hub.forge_instance_namespaces
    engine = request.app.state.async_engine
    opened = None
    async with engine.connect() as conn:
        outsider = await conn.run_sync(
            is_outsider, cookie, slug, owner_call, public_repository_read, instance
        )
        if not outsider and token is not None and instance is not None:
            opened = await conn.run_sync(open_why_project, cookie, slug, instance)
    if outsider:
        raise not_found()
    if opened is not None and token is not None:
        await _why_visible_now(request, opened, token)  # after the connection is closed


def member_row_or_removed(conn: Connection, project_id: str, principal_id: str) -> Any:
    """The active membership, else the most recently removed one: a removed member
    stays addressable for a repeated DELETE and its credentials (§6.2, §10)."""
    row = conn.execute(
        select(t.membership)
        .where(
            t.membership.c.project_id == project_id,
            (t.membership.c.agent_id == principal_id) | (t.membership.c.human_id == principal_id),
        )
        .order_by(t.membership.c.active.is_(True).desc(), t.membership.c.joined_at.desc())
    ).first()
    if row is None:
        raise not_found()
    return row


def member_row(conn: Connection, project_id: str, principal_id: str) -> Any:
    """The active membership of a principal (`hum-…` or `agt-…`) in a project."""
    row = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project_id,
            (t.membership.c.agent_id == principal_id) | (t.membership.c.human_id == principal_id),
            t.membership.c.active.is_(True),
        )
    ).first()
    if row is None:
        raise not_found()
    return row


def owns_agent(conn: Connection, caller: Caller, agent_id: str) -> bool:
    """The caller is the human who owns the agent profile, a deleted one included (§6.3)."""
    if caller.kind != "human":
        return False
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent_id)
    ).scalar()
    return owner is not None and owner == caller.human_id
