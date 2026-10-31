"""Projects, their state, policy, absence and rules (docs/api.md §6.1, §6.9)."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field, field_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import Connection, delete, insert, select, update

from maity_hub import (
    agent_owners,
    attachments,
    availability,
    clock,
    commitment,
    handles,
    idempotency,
    images,
    ktw,
    moderation,
    namespace,
    onboarding,
    org_projects,
    orgs,
    placements,
    policy,
    project_names,
    public_pages,
    public_projects,
    releases,
    rules,
    setup_cards,
    ticker,
)
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.auth import second_factor
from maity_hub.deps import AnyCaller, HumanCaller, engine_of, reader_of, settings_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid
from maity_hub.events import Actor, emit, lock_project
from maity_hub.ids import new_id
from maity_hub.models import SLUG_PATTERN, Strict, markdown, title
from maity_hub.namespace import ProjectRoute
from maity_hub.onboarding import OnboardingIn
from maity_hub.scopes import in_admin_team
from maity_hub.views import confirmed_by_of, forge_of, member_view, principal_id, project_view

router = APIRouter(route_class=ProjectRoute)

BROADCAST = ["all"]
ABSENCE_AHEAD = timedelta(days=90)  # an absence cannot hold the owner's cover open (§6.1)


class RepositoryIn(Strict):
    url: str = Field(min_length=1, max_length=255)
    default_branch: str = Field(default="main", min_length=1, max_length=255)


class RepositoryConfirmIn(Strict):
    url: str = Field(min_length=1, max_length=255)


class PolicyIn(Strict):
    preset: str | None = None
    claim_policy: str | None = None
    done_authority: str | None = None
    contract_arbiter: str | None = None
    tag_authority: str | None = None
    steward_writes: str | None = None
    lease_seconds: int | None = None
    signing: str | None = None
    spawn_requests: str | None = None
    spawn_consent_by: str | None = None
    max_placements: int | None = None
    coordinator: str | None = None
    coordinator_substitute: str | None = None
    on_runner_revoke: str | None = None
    badge: str | None = None
    subtasks: str | None = None
    keep_the_why: str | None = None
    keep_the_why_defaults: str | None = None
    merged_closes: str | None = None
    jour_fixe: dict[str, Any] | None = None  # replaced as a whole (§20.1)
    jour_fixe_moderators: list[str] | None = None
    takeover_window_minutes: int | None = None
    member_agents: str | None = None
    member_agents_max: int | None = None
    agent_owners: str | None = None  # `members` or `anyone`; never null again once set (§6.1)
    outside_roles: list[str] | None = Field(default=None, max_length=50)


class AbsenceIn(Strict):
    until: datetime
    scope: str = Field(min_length=1, max_length=16384)


class TickerSettingsIn(Strict):
    """`settings.ticker` (§17.3): the switch for the automatic sources, the contract
    files and who implements which section; capped at 10 files, 200 keys, 20 tokens."""

    enabled: bool = False
    contract_files: list[str] = Field(default_factory=list, max_length=10)
    contract_implementers: dict[str, list[str]] = Field(default_factory=dict, max_length=200)


SECTION_KEY = re.compile(r"^(\*|\d+(\.\d+)*)$")
IMPLEMENTER = re.compile(r"^(member|role|trust|area):\S{1,255}$")


def _check_ticker(settings: TickerSettingsIn) -> None:
    errors: dict[str, str] = {}
    if any(not f or len(f) > 255 for f in settings.contract_files):
        errors["settings.ticker.contract_files"] = "invalid"
    for key, tokens in settings.contract_implementers.items():
        if not SECTION_KEY.match(key):
            errors["settings.ticker.contract_implementers"] = "invalid"
        elif len(tokens) > 20:
            errors["settings.ticker.contract_implementers"] = "too_many"
        elif any(not IMPLEMENTER.match(x) for x in tokens):
            errors["settings.ticker.contract_implementers"] = "invalid"
    if errors:
        raise invalid(errors)


class SettingsIn(Strict):
    """Top-level keys (§6.1): a key named replaces its whole value, `null` removes it."""

    release_checklist: list[str] | None = Field(default=None, max_length=50)
    ticker: TickerSettingsIn | None = None
    onboarding: OnboardingIn | None = None
    language: str | None = None

    @field_validator("language", mode="before")
    @classmethod
    def known_language(cls, value: Any) -> Any:
        if value is not None and value not in ("en", "de"):
            raise PydanticCustomError("unknown_language", "choose en or de")
        return value


class MemoryIn(Strict):
    provider: str


PROVIDERS = ("none", "keep-the-why")


def _provider(memory: MemoryIn | None) -> bool | None:
    """Whether the body names `keep-the-why` as the memory provider, or None when it names
    none (§6.1)."""
    named = None if memory is None else memory.provider
    if named is None:
        return None
    if named not in PROVIDERS:
        raise invalid({"memory.provider": "unknown_provider"})
    return named == "keep-the-why"


class ProjectCreate(Strict):
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = title()
    # The handle of an organisation to create the project in (§6.26); the caller's own
    # handle or nothing is the default of §6.1.
    owner: str | None = Field(default=None, max_length=64)
    repository: RepositoryIn | None = None
    memory: MemoryIn | None = None
    setup: Any = None  # parsed by setup_cards.parse, for the reasons §6.21 names
    policy: PolicyIn | None = None


class ProjectPatch(Strict):
    slug: str | None = Field(default=None, pattern=SLUG_PATTERN)  # a rename (§6.25)
    name: str | None = title(default=None)
    repository: RepositoryIn | None = None
    memory: MemoryIn | None = None
    setup: Any = None
    state: str | None = None
    state_note: str | None = markdown(default=None)
    policy: PolicyIn | None = None
    absence: AbsenceIn | None = None
    settings: SettingsIn | None = None
    rules_markdown: str | None = markdown(default=None)
    # The project's public page and its text (§16.9): the namespace owner's, not the policy's.
    public_page: Literal["off", "on"] | None = None
    public_about: str | None = None
    reason: str | None = Field(default=None, max_length=16384)


def _load(conn: Connection, project_id: str) -> Any:
    return conn.execute(select(t.project).where(t.project.c.id == project_id)).one()


# What a public project shows outside it (§6.20, §16.8): `hide` turns these off.
PUBLIC_OFF = {"badge": "off"}


def hide_by_moderation(conn: Connection, project_id: str, reason: str, actor: Actor) -> None:
    """`hide` on a project (§16.8): members-only, its README badge off, with the
    `policy_changed` a `PATCH` would write."""
    project = lock_project(conn, project_id)
    current = policy.of(project)
    new = {**current, **PUBLIC_OFF}
    if new == current:
        return
    conn.execute(
        update(t.project).where(t.project.c.id == project_id).values(**policy.columns(new))
    )
    rules.bump(
        conn,
        project,
        "policy_changed",
        BROADCAST,
        {"old": current, "new": new, "reason": reason},
        actor=actor,
    )


def archive_by_moderation(conn: Connection, project_id: str, reason: str, actor: Actor) -> None:
    """`remove` on a project (§16.8): archived as a `PATCH {state: archived}` archives it."""
    project = lock_project(conn, project_id)
    if project.state == "archived":
        return
    conn.execute(
        update(t.project)
        .where(t.project.c.id == project_id)
        .values(state="archived", state_changed_at=clock.now())
    )
    rules.bump(
        conn,
        project,
        "state_changed",
        BROADCAST,
        {"old": project.state, "new": "archived", "reason": reason},
        actor=actor,
    )
    placements.project_archived(conn, project_id, actor, None)
    public_pages.touch(conn, public_projects.KIND, project_id)  # an archived project has no page


def _repository_columns(repository: RepositoryIn | None) -> dict[str, Any]:
    if repository is None:
        return {"repository_url": None, "repository_default_branch": None}
    url = repository.url.rstrip("/")
    if not url.startswith("https://") or forge_of(url) is None or url.count("/") != 4:
        raise invalid(
            {"repository.url": "not_a_configured_forge"},
            "the repository must be https://<forge host>/<owner>/<name> on a configured forge",
        )
    return {"repository_url": url, "repository_default_branch": repository.default_branch}


def _apply_policy(
    conn: Connection,
    project_id: str,
    current: dict[str, Any],
    change: PolicyIn,
    owner_id: str,
    instance_rule: str,
    memory_on: bool,
) -> dict[str, Any]:
    proposed = dict(current)
    if change.preset is not None:
        if change.preset not in policy.PRESETS:
            raise invalid({"policy.preset": "unknown"})
        # A preset refills every field but those it must not loosen or reset (§6.1).
        kept = {name: current[name] for name in policy.KEPT_ON_PRESET}
        proposed = {**policy.filled(change.preset, owner_id), **kept}
    errors: dict[str, str] = {}
    for name, choices in policy.CHOICES.items():
        value = getattr(change, name)
        if value is not None:
            if value not in choices:
                errors[f"policy.{name}"] = "unknown"
            proposed[name] = value
    if change.lease_seconds is not None:
        if not policy.LEASE_MIN <= change.lease_seconds <= policy.LEASE_MAX:
            errors["policy.lease_seconds"] = "out_of_range"
        proposed["lease_seconds"] = change.lease_seconds
    if change.max_placements is not None:
        if not 0 <= change.max_placements <= policy.MAX_PLACEMENTS_MAX:
            errors["policy.max_placements"] = "out_of_range"
        proposed["max_placements"] = change.max_placements
    if "keep_the_why" in change.model_fields_set and change.keep_the_why is None:
        # Only `required` or `optional` (§6.1): a null would clear the human's value.
        errors["policy.keep_the_why"] = "unknown"
    if change.keep_the_why == "required" and not memory_on:
        errors["policy.keep_the_why"] = "no_memory_provider"
    if change.member_agents_max is not None:
        if not 0 <= change.member_agents_max <= policy.MEMBER_AGENTS_MAX_MAX:
            errors["policy.member_agents_max"] = "out_of_range"
        proposed["member_agents_max"] = change.member_agents_max
    if change.outside_roles is not None:
        roles = list(dict.fromkeys(change.outside_roles))
        found = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
        # The contract names the field plain here, not under `policy.` (§6.1, §6.2).
        problem = agent_owners.role_errors(found, roles) or agent_owners.check_policy(
            conn, found, roles
        )
        if problem is not None:
            errors["outside_roles"] = problem
        proposed["outside_roles"] = roles
    if change.on_runner_revoke == "keep" and instance_rule == "stop_floor":
        # The operator made stop a floor (§15.3, §16): no project keeps its agents.
        errors["policy.on_runner_revoke"] = "stop_floor"
    window = change.takeover_window_minutes
    if window is not None:
        if not policy.WINDOW_MIN <= window <= policy.WINDOW_MAX:
            errors["policy.takeover_window_minutes"] = "out_of_range"
        proposed["takeover_window_minutes"] = window
    if change.contract_arbiter is not None:
        arbiter = change.contract_arbiter
        if arbiter != "trust:admin" and not _is_member(conn, project_id, arbiter):
            errors["policy.contract_arbiter"] = "not_a_member"
        elif arbiter != "trust:admin" and _is_guest(conn, project_id, arbiter):
            errors["policy.contract_arbiter"] = "guest"
        proposed["contract_arbiter"] = arbiter
    if change.coordinator is not None:
        if (
            change.coordinator != "trust:admin"
            and _agent_role(conn, project_id, change.coordinator) is None
        ):
            errors["policy.coordinator"] = "not_an_agent_member"
        proposed["coordinator"] = change.coordinator
    if "jour_fixe" in change.model_fields_set:
        from maity_hub.jourfixe import schedule

        stored = None if change.jour_fixe is None else schedule.filled(change.jour_fixe)
        if stored is not None:
            errors.update(schedule.errors(stored, lambda m: _is_member(conn, project_id, m)))
        proposed["jour_fixe"] = stored
    if "jour_fixe_moderators" in change.model_fields_set:
        from maity_hub.jourfixe import rounds

        order = change.jour_fixe_moderators
        if order is not None and not rounds.admin_agents_only(conn, project_id, order):
            errors["policy.jour_fixe_moderators"] = "not_admin_agent"
        proposed["jour_fixe_moderators"] = order
    if "coordinator_substitute" in change.model_fields_set:
        stand_in = change.coordinator_substitute
        if stand_in is not None and _agent_role(conn, project_id, stand_in) != "admin":
            errors["policy.coordinator_substitute"] = "not_an_agent_admin"
        proposed["coordinator_substitute"] = stand_in
    if errors:
        raise invalid(errors)
    return proposed


def _set_keep_the_why(change: PolicyIn | None) -> dict[str, Any]:
    """The column of a human's own `policy.keep_the_why`, when the body names it."""
    if change is not None and "keep_the_why" in change.model_fields_set:
        return {"keep_the_why_policy": change.keep_the_why}
    return {}


def _agent_role(conn: Connection, project_id: str, member_id: str) -> str | None:
    """`admin` for an active admin agent (trust `admin`, never a proxy, §2.3), else the
    agent's role; None when the id names no active agent member."""
    row = conn.execute(
        select(t.membership.c.trust, t.membership.c.role).where(
            t.membership.c.project_id == project_id,
            t.membership.c.agent_id == member_id,
            t.membership.c.active.is_(True),
        )
    ).first()
    if row is None:
        return None
    return "admin" if in_admin_team(row.trust, row.role) else str(row.role)


def _is_guest(conn: Connection, project_id: str, principal: str) -> bool:
    return bool(member_row(conn, project_id, principal).trust == "guest")


def _is_member(conn: Connection, project_id: str, principal: str) -> bool:
    try:
        member_row(conn, project_id, principal)
    except ApiError:  # not_found is the answer here, not an error
        return False
    return True


def _export(project: Any, request: Request) -> dict[str, Any] | None:
    """From the cache only: building a view never waits on a read (§11.3)."""
    return ktw.export_for_view(reader_of(request), project.id, project.repository_url)


def _stored(conn: Connection, project: Any, request: Request) -> dict[str, int] | None:
    """The project's attachment bytes against its quota, for a caller with `project:admin`
    in it (§8.7); anyone else gets None."""
    caller = getattr(request.state, "caller", None)
    if caller is None:
        return None
    try:
        mine = membership(conn, caller, namespace.full_name(conn, project))
    except ApiError:
        return None
    if not mine.may("project:admin"):
        return None
    return {
        "used": attachments.used(conn, project.id),
        "quota": settings_of(request).attachment_quota,
    }


def _view(conn: Connection, project: Any, request: Request) -> dict[str, Any]:
    shown = images.views(conn, [project.id])[project.id]
    owner = namespace.owner_of(conn, project)["handle"]
    aliases = namespace.aliases_of(conn, project.id)
    view = project_view(
        project,
        settings_of(request),
        owner,
        shown,
        _export(project, request),
        aliases,
        _stored(conn, project, request),
        confirmed_by_of(conn, [project])[project.id],
    )
    held = moderation.view(moderation.hold(conn, "project", project.id))
    if held is not None:  # only while a hold stands (§16.8)
        view["moderation"] = held
    return view


def load_project(conn: Connection, project_id: str, request: Request) -> dict[str, Any]:
    return _view(conn, _load(conn, project_id), request)


idempotency.LOADERS["project"] = load_project


@router.get("/projects")
def list_projects(request: Request, caller: AnyCaller) -> JSONResponse:
    settings = settings_of(request)
    with engine_of(request).begin() as conn:
        query = select(t.project).join(t.membership, t.membership.c.project_id == t.project.c.id)
        if caller.kind == "agent":
            query = query.where(t.membership.c.id == caller.membership_id)
        else:
            query = query.where(
                t.membership.c.human_id == caller.human_id, t.membership.c.active.is_(True)
            )
        rows = conn.execute(query.order_by(t.project.c.slug)).all()
        shown = images.views(conn, [r.id for r in rows])
        names = namespace.full_names(conn, [r.id for r in rows])
        aliases = namespace.aliases_by(conn, [r.id for r in rows])
        confirmed = confirmed_by_of(conn, rows)
        return JSONResponse(
            {
                "items": [
                    project_view(
                        r,
                        settings,
                        names[r.id].split("/")[0],
                        shown[r.id],
                        _export(r, request),
                        aliases[r.id],
                        _stored(conn, r, request),
                        confirmed[r.id],
                    )
                    for r in rows
                ],
                "next_cursor": None,
            }
        )


def _creation_owner(
    conn: Connection, caller: Any, owner: str | None
) -> tuple[str, Any, str | None]:
    """The namespace owner a new project is created in, the organisation and the caller's
    role in it (None for the caller's own namespace). An organisation the caller is no member
    of is `invalid` (`owner: unknown`), the same for every such handle; a member whom
    `members_create_projects` does not allow is `forbidden` (`org_role`) (§6.26). The
    organisation's row is locked, and the role read under the lock, before any project's."""
    assert caller.human_id is not None
    own = conn.execute(select(t.human.c.handle).where(t.human.c.id == caller.human_id)).scalar()
    gave_up = handles.aliases(conn, [caller.human_id])[caller.human_id]  # §6.24
    if owner is None or owner == own or owner in gave_up:
        return str(caller.human_id), None, None
    found = conn.execute(
        select(t.org.c.id)
        .join(t.org_member, t.org_member.c.org_id == t.org.c.id)
        .where(
            t.org.c.handle == owner,
            t.org.c.deleted_at.is_(None),
            t.org_member.c.human_id == caller.human_id,
        )
    ).scalar()
    if found is None:
        raise invalid({"owner": "unknown"})
    org = orgs.lock(conn, found)
    role = orgs.role_of(conn, found, caller.human_id) if org is not None else None
    if org is None or role is None:
        raise invalid({"owner": "unknown"})
    if role == "member" and not org.members_create_projects:
        raise orgs.org_role()
    moderation.refuse_held(conn, "org", str(org.id), "suspend")  # no new project while suspended
    return str(org.id), org, role


@router.post("/projects")
def create_project(body: ProjectCreate, request: Request, caller: HumanCaller) -> JSONResponse:

    named = _provider(body.memory)
    memory_on = True if named is None else named  # the default provider is keep-the-why (§6.1)
    setup = setup_cards.parse(body.setup, memory_on)
    if body.repository is not None:  # refuse a bad repository before anything is written
        _repository_columns(body.repository)
    words = namespace.app_words(request.app)
    assert caller.human_id is not None  # a human caller

    def action(conn: Connection) -> idempotency.Outcome:
        # The creator is the namespace owner, or an organisation they may create in:
        # `<handle>/<slug>`, the slug free among the owner's projects and their aliases, and
        # never a word that follows a project in a route (§6.25, §6.26).
        if body.slug in words:
            raise invalid({"slug": "reserved"}, "this slug is a word of the API's routes")
        owner_id, org, org_role = _creation_owner(conn, caller, body.owner)
        if namespace.taken(conn, owner_id, body.slug):
            raise invalid({"slug": "taken"}, "this namespace has a project with this slug")
        now = clock.now()
        project_id = new_id("project")
        filled = policy.filled("hierarchical", caller.principal_id)
        if setup["maity_badge"]:  # the creating human's choice, no policy_changed (§6.21)
            filled["badge"] = "members"
        conn.execute(
            insert(t.project).values(
                id=project_id,
                **namespace.owner_values(owner_id),
                slug=body.slug,
                name=body.name,
                state="build",
                state_changed_at=now,
                keep_the_why=memory_on,
                setup=setup_cards.stored(setup),
                **_repository_columns(body.repository),
                **policy.columns(filled),
                settings={"release_checklist": []},
                rules_version=1,
                rules_text_digest=rules.text_digest(),
                created_at=now,
            )
        )
        result = conn.execute(
            insert(t.membership).values(
                project_id=project_id,
                human_id=caller.human_id,
                trust="owner",
                role="coder",
                role_base="coder",
                areas=["/"],
                capabilities=[],
                joined_at=now,
                last_seen_at=now,
                changed_via=caller.via,
                # an owner of the organisation holds a membership the hub keeps (§6.26)
                org_keep="created" if org_role == "owner" else None,
            )
        )
        key = result.inserted_primary_key
        assert key is not None
        owner = int(key[0])
        if body.policy is not None:
            proposed = _apply_policy(
                conn,
                project_id,
                filled,
                body.policy,
                caller.principal_id,
                settings_of(request).on_runner_revoke,
                memory_on,
            )
            conn.execute(
                update(t.project)
                .where(t.project.c.id == project_id)
                .values(**policy.columns(proposed), **_set_keep_the_why(body.policy))
            )
        member = conn.execute(select(t.membership).where(t.membership.c.id == owner)).one()
        emit(
            conn,
            project_id,
            "member_joined",
            BROADCAST,
            member_view(conn, member),
            actor=caller.actor(owner),
            subject=("member", caller.principal_id),
        )
        if org is not None:  # every other owner of the organisation is an owner here (§6.26)
            org_projects.keep_all_owners(
                conn,
                org.id,
                conn.execute(select(t.project).where(t.project.c.id == project_id)).one(),
            )
        project = _load(conn, project_id)
        if project.repository_url is not None:
            setup_cards.create(
                conn,
                project,
                settings_of(request).public_url,
                owner,
                caller.actor(owner),
                reader_of(request),
            )
            project = _load(conn, project_id)
        return idempotency.Outcome(201, "project", project_id, _view(conn, project, request))

    return idempotency.run(engine_of(request), request, caller, action)


@router.get("/projects/{owner}/{slug}")
def get_project(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        return JSONResponse(_view(conn, mine.project, request))


@router.patch("/projects/{owner}/{slug}")
def patch_project(
    slug: str, body: ProjectPatch, request: Request, caller: AnyCaller
) -> JSONResponse:
    given = body.model_fields_set
    words = namespace.app_words(request.app)

    def action(conn: Connection) -> idempotency.Outcome:
        if "setup" in given:
            raise invalid({"setup": "read_only"}, "the setup options are set at creation only")
        mine = membership(conn, caller, slug)
        found_owner = mine.project.owner_org_id
        if "slug" in given and found_owner is not None:
            # A rename reads the namespace, and so the organisation's row (§6.26): that row
            # before the project's.
            orgs.lock(conn, found_owner)
        # Membership's project snapshot may precede another writer's commit. Merge settings
        # and make policy/event decisions from the current row under the shared project lock.
        mine = replace(mine, project=lock_project(conn, mine.project.id))
        if "slug" in given and mine.project.owner_org_id != found_owner:
            raise orgs.project_moved()  # moved meanwhile: its new owner is unlocked
        _refuse_for_agents(mine, body, given)
        _authorise_patch(mine, body, given)
        if given & PUBLIC_FIELDS:
            _namespace_owner_only(conn, mine)
        project = mine.project
        actor = caller.actor(mine.id)
        # A rename first, so that every event below names the project by its new full name.
        renamed = "slug" in given and body.slug is not None
        if renamed and project_names.rename(conn, mine, str(body.slug), words, actor):
            project = _load(conn, project.id)
            mine = replace(mine, project=project)
        owner_id = _owner_id(conn, project.id)
        values: dict[str, Any] = {}
        rules_inputs_changed = False
        settings_changed: dict[str, Any] = {}
        if "name" in given and body.name is not None and body.name != project.name:
            values["name"] = body.name
            rules_inputs_changed = True
        if "public_page" in given:
            if body.public_page is None:
                raise invalid({"public_page": "required"})
            if body.public_page != project.public_page:
                if body.public_page == "on":  # a hidden or removed project stays so (§16.8)
                    moderation.refuse_held(conn, "project", project.id)
                values["public_page"] = body.public_page
                # What the forge said belongs to the time the page was on: asked again.
                values["repository_public"] = None
                settings_changed["public_page"] = body.public_page
        if "public_about" in given:
            about = public_projects.check_about(body.public_about)
            if about != project.public_about:
                values["public_about"] = about
                settings_changed["public_about"] = about is not None  # the text is not an event
        if "repository" in given:
            columns = _repository_columns(body.repository)
            values.update(columns)
            if columns["repository_url"] != project.repository_url:
                # The owner confirmed the old URL, not this one, whoever changes it (§11.4).
                values["repository_owner_confirmed"] = False
                values["repository_confirmed_by"] = None
                values["repository_public"] = None  # the forge has not said anything of this one
        if "settings" in given and body.settings is not None:
            # §6.1: merged by top-level key. A key named replaces its whole value (nested
            # objects are not merged), `null` removes it so it reads as its default, and a
            # key not named stays; `{}` changes nothing.
            named = body.settings.model_fields_set
            if body.settings.ticker is not None:
                _check_ticker(body.settings.ticker)
            dumped = body.settings.model_dump()
            if "onboarding" in named:
                changed, stored, announcement = onboarding.replace_setting(
                    conn, project, body.settings.onboarding, mine.id
                )
                dumped["onboarding"] = stored
                if changed:
                    settings_changed["settings.onboarding"] = announcement
            merged = dict(project.settings or {})
            for key in named:
                if key == "language":
                    effective = dumped[key] or "en"
                    if effective != (merged.get(key) or "en"):
                        settings_changed["settings.language"] = effective
                elif key != "onboarding" and merged.get(key) != dumped[key]:
                    settings_changed[f"settings.{key}"] = (
                        True
                        if key == "release_checklist" and dumped[key] is not None
                        else dumped[key]
                    )
                if dumped[key] is None:
                    merged.pop(key, None)
                else:
                    merged[key] = dumped[key]
            if merged != (project.settings or {}):
                values["settings"] = merged
            was_on = ticker.settings(project)["enabled"]
            now_on = bool((merged.get("ticker") or {}).get("enabled"))
            if now_on and not was_on:  # merges count from the moment it is switched on
                ticker.switched_on(conn, project.id)
        provider = _provider(body.memory)
        memory_on = project.keep_the_why if provider is None else provider
        new_policy = None
        if "policy" in given and body.policy is not None:
            new_policy = _apply_policy(
                conn,
                project.id,
                policy.of(project),
                body.policy,
                owner_id,
                settings_of(request).on_runner_revoke,
                memory_on,
            )
            if new_policy == policy.of(project):
                new_policy = None
        # What a human set is compared as stored, not as read: `optional` under a provider
        # that is off reads the same as nothing, and still has to be kept (§6.23).
        explicit = _set_keep_the_why(body.policy)
        explicit_changes = (
            bool(explicit) and explicit["keep_the_why_policy"] != project.keep_the_why_policy
        )
        state_changes = "state" in given and body.state != project.state
        if state_changes and body.state not in policy.STATES:
            raise invalid({"state": "unknown"})
        # The README badge alone is a display choice: it needs no reason (§6.20), and its
        # policy_changed carries `reason: null` then. Every other policy field keeps it.
        current = policy.of(project)
        badge_only = new_policy is not None and {
            name for name in new_policy if new_policy[name] != current.get(name)
        } == {"badge"}
        needs_reason = (
            state_changes or (new_policy is not None and not badge_only) or explicit_changes
        )
        if needs_reason and not body.reason:
            raise invalid({"reason": "required"}, "a change of state or policy needs a reason")
        _refuse_against_a_hold(conn, project, state_changes, new_policy)
        if values:
            conn.execute(update(t.project).where(t.project.c.id == project.id).values(**values))
        if settings_changed:
            emit(
                conn,
                project.id,
                "project_updated",
                BROADCAST,
                {"fields": settings_changed},
                actor=actor,
                subject=("project", namespace.full_name(conn, project)),
            )
        if "repository" in given:
            if values.get("repository_url") != project.repository_url:
                # Observations are of the old repository: none of them answers for the new one.
                conn.execute(
                    delete(t.forge_observation).where(
                        t.forge_observation.c.project_id == project.id
                    )
                )
                # Nor are the forge's images and the Keep the Why export: the new
                # repository's are read afresh.
                images.forget_forge(conn, project.id)
                ktw.CACHE.forget(project.id)
            # whether the probe can observe it changed
            releases.recheck(conn, project.id, reader_of(request))
        if state_changes:
            now = clock.now()
            conn.execute(
                update(t.project)
                .where(t.project.c.id == project.id)
                .values(state=body.state, state_note=body.state_note, state_changed_at=now)
            )
            rules.bump(
                conn,
                project,
                "state_changed",
                BROADCAST,
                {"old": project.state, "new": body.state, "reason": body.reason},
                actor=actor,
            )
            if body.state == "archived":  # its placements close the uniform way (§15.5)
                placements.project_archived(conn, project.id, actor, mine.principal_id)
        elif "state_note" in given and body.state_note != project.state_note:
            conn.execute(
                update(t.project)
                .where(t.project.c.id == project.id)
                .values(state_note=body.state_note)
            )
            rules_inputs_changed = True
        if "repository" in given and project.repository_url is None:
            # The first repository opens the setup cards (§6.21), judged by the state this
            # PATCH leaves: a body that also archives opens none, one that also brings the
            # project back opens them, and they come after its state_changed.
            fresh = _load(conn, project.id)
            if (
                fresh.repository_url is not None
                and fresh.state != "archived"
                and isinstance(fresh.setup, dict)
                and fresh.setup.get("cards") is None
            ):
                setup_cards.create(
                    conn, fresh, settings_of(request).public_url, mine.id, actor, reader_of(request)
                )
        if new_policy is None and explicit_changes:
            conn.execute(update(t.project).where(t.project.c.id == project.id).values(**explicit))
            # The view may not move (`optional` under a provider that is off reads the
            # same), but a human changed the policy: version, event and reason as for any
            # policy change (§6.1).
            rules.bump(
                conn,
                project,
                "policy_changed",
                BROADCAST,
                {
                    "old": policy.of(project),
                    "new": {**policy.of(project), "keep_the_why": explicit["keep_the_why_policy"]},
                    "reason": body.reason,
                },
                actor=actor,
            )
        if new_policy is not None:
            conn.execute(
                update(t.project)
                .where(t.project.c.id == project.id)
                .values(**policy.columns(new_policy), **_set_keep_the_why(body.policy))
            )
            if new_policy["jour_fixe"] != policy.of(project)["jour_fixe"]:
                # A changed schedule counts its weeks from now and catches up on no slot
                # before it (§20.1).
                now = clock.now()
                conn.execute(
                    update(t.project)
                    .where(t.project.c.id == project.id)
                    .values(jour_fixe_anchor=now, jour_fixe_last_slot=now)
                )
            rules.bump(
                conn,
                project,
                "policy_changed",
                BROADCAST,
                {"old": policy.of(project), "new": new_policy, "reason": body.reason},
                actor=actor,
            )
        if "absence" in given:
            if body.absence is not None and body.absence.until > clock.now() + ABSENCE_AHEAD:
                raise invalid({"absence": "too_far"}, "an absence ends within 90 days")
            new_absence = (
                {"until": clock.rfc3339(body.absence.until), "scope": body.absence.scope}
                if body.absence
                else None
            )
            old = _absence(project)
            if new_absence != old:
                conn.execute(
                    update(t.project)
                    .where(t.project.c.id == project.id)
                    .values(
                        absence_until=body.absence.until if body.absence else None,
                        absence_scope=body.absence.scope if body.absence else None,
                    )
                )
                emit(
                    conn,
                    project.id,
                    "absence_changed",
                    BROADCAST,
                    {"old": old, "new": new_absence, "reason": body.reason},
                    actor=actor,
                    subject=("project", namespace.full_name(conn, project)),
                )
                availability.absence_changed(
                    conn,
                    _load(conn, project.id),
                    body.absence.until if body.absence else None,
                    actor,
                )
        for name, new_value in (
            ("rules_markdown", body.rules_markdown),
            ("keep_the_why", provider),
        ):
            if (
                (name in given or (name == "keep_the_why" and "memory" in given))
                and new_value is not None
                and new_value != getattr(project, name)
            ):
                conn.execute(
                    update(t.project).where(t.project.c.id == project.id).values({name: new_value})
                )
                rules_inputs_changed = True
        # The name, a note without a state change, the owner's text and the Keep the
        # Why line are rules inputs without an event of their own: one rules_changed.
        if rules_inputs_changed:
            payload = {"reason": body.reason} if body.reason else {}
            rules.bump(conn, project, "rules_changed", BROADCAST, payload, actor=actor)
        if new_policy is not None or explicit_changes or provider is not None:
            # An instance owes nothing once the policy is `optional` or the provider `none`.
            commitment.reconcile(conn, _load(conn, project.id))
        if new_policy is not None or "public_page" in given:
            # The setting may come to read `members`: agents of owners who are none go (§6.2).
            agent_owners.reconcile(conn, project.id, actor)
        if given & {"public_page", "public_about", "name", "slug", "state", "repository"}:
            # What the page shows, or whether it exists, changed: at once (§16.9).
            public_pages.touch(conn, public_projects.KIND, project.id)
        return idempotency.Outcome(
            200, "project", project.id, _view(conn, _load(conn, project.id), request)
        )

    return idempotency.run(engine_of(request), request, caller, action)


class TransferIn(Strict):
    to: str = Field(min_length=1, max_length=40)


@router.post("/projects/{owner}/{slug}/transfer")
def transfer_project(
    slug: str, body: TransferIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    """File the transfer to another namespace owner (§6.25): a consent request to the
    receiver, 202 with the request; the move happens on their `go`."""
    from maity_hub.routes.requests import load_request

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        found_owner = mine.project.owner_org_id
        # The organisations' rows before the project's, in the order of their ids (§6.26): the
        # one that owns it now, and the one it goes to.
        wanted = {mine.project.owner_org_id, body.to if body.to.startswith("org-") else None}
        for org_id in sorted(i for i in wanted if i is not None):
            orgs.lock(conn, org_id)
        mine = replace(mine, project=lock_project(conn, mine.project.id))
        if mine.project.owner_org_id != found_owner:  # moved meanwhile: its new owner is unlocked
            raise orgs.project_moved()
        # The authority first, so that a caller who may not transfer is `forbidden`, not asked for
        # the second factor; `transfer` checks it again for its other callers.
        project_names.authority(conn, mine)
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
        request_id = project_names.transfer(conn, mine, caller, body.to)
        if request_id is None:  # the move happened in the call: the project as it is now (§6.26)
            return idempotency.Outcome(
                200, "project", mine.project.id, load_project(conn, mine.project.id, request)
            )
        return idempotency.Outcome(202, "request", request_id, load_request(conn, request_id))

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{owner}/{slug}/repository/confirm")
def confirm_repository(
    slug: str, body: RepositoryConfirmIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    """The namespace owner confirms the project's repository for their own forge grants, for a
    project of an organisation any owner of it does (§11.4): only the URL they saw, and only
    while the project still carries it."""

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        found_owner = mine.project.owner_org_id
        if found_owner is not None:  # the organisation's row before the project's (§6.26)
            orgs.lock(conn, found_owner)
        mine = replace(mine, project=lock_project(conn, mine.project.id))
        project = mine.project
        if project.owner_org_id != found_owner:
            raise orgs.project_moved()
        if mine.kind != "human":
            raise humans_only("only the namespace owner confirms the repository")
        if project.owner_org_id is not None:
            if orgs.role_of(conn, project.owner_org_id, mine.row.human_id) != "owner":
                raise orgs.org_role()
        elif mine.row.human_id != project.owner_id:
            raise forbidden(message="only the project's namespace owner confirms its repository")
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
        if project.repository_url is None or body.url.rstrip("/") != project.repository_url:
            # A co-admin's change between what the owner saw and the click is never
            # confirmed with it.
            raise ApiError(
                409,
                "conflict",
                "the project's repository is not the one confirmed",
                {"reason": "repository_changed", "url": project.repository_url},
            )
        conn.execute(
            update(t.project)
            .where(t.project.c.id == project.id)
            .values(repository_owner_confirmed=True, repository_confirmed_by=mine.row.human_id)
        )
        return idempotency.Outcome(
            200, "project", project.id, _view(conn, _load(conn, project.id), request)
        )

    return idempotency.run(engine_of(request), request, caller, action)


# Fields that govern what humans decide: no agent changes them, whatever its role (§2.3).
HUMANS_ONLY_POLICY = {
    "spawn_consent_by",
    "signing",
    "tag_authority",
    "on_runner_revoke",
    "spawn_requests",
    "merged_closes",  # set by a human with project:admin (§6.1)
    "member_agents",  # who may bring agents into the project (§3.1, §6.1)
    "member_agents_max",
    "agent_owners",  # whether an agent's owner must be a member (§6.1, §6.2)
    "outside_roles",
    "keep_the_why",  # whether the project requires Keep the Why (§6.23)
    "keep_the_why_defaults",
}


def _refuse_against_a_hold(
    conn: Connection,
    project: Any,
    state_changes: bool,
    new_policy: dict[str, Any] | None,
) -> None:
    """A moderation hold (§16.8): a hidden or removed project stays members-only, and a
    removed one stays archived, until an instance admin lifts the hold. Only what this
    PATCH turns on is refused: a surface left as it was blocks no other policy change."""
    found = [moderation.hold(conn, "project", project.id)]
    if project.owner_org_id is not None:
        # The suspension of the organisation that owns it holds its projects the way `remove`
        # does (§16.8): archived, and nothing public turned on, until the hold is lifted. It
        # stands beside a hold of the project's own, whichever that is.
        found.append(moderation.hold(conn, "org", project.owner_org_id))
    holds = [h for h in found if h is not None]
    if not holds:
        return
    current = policy.of(project)
    if new_policy is not None and any(
        new_policy[k] != off and new_policy[k] != current[k] for k, off in PUBLIC_OFF.items()
    ):
        raise moderation.held()
    if state_changes and any(h.action in ("remove", "suspend") for h in holds):
        raise moderation.held()


def _refuse_for_agents(mine: Membership, body: Any, given: set[str]) -> None:
    """`humans_only` for what §2.3 lists as no agent's, before any other check."""
    if mine.kind != "agent":
        return
    if "slug" in given:
        raise humans_only("a project is renamed by a human")
    if body.settings is not None and "language" in body.settings.model_fields_set:
        raise humans_only("the project's language is set by a human")
    policy = body.policy.model_fields_set if "policy" in given and body.policy else set()
    if policy & HUMANS_ONLY_POLICY or "rules_markdown" in given or body.state == "archived":
        raise humans_only("no agent changes this, whatever its role")


PUBLIC_FIELDS = {"public_page", "public_about"}


def _namespace_owner_only(conn: Connection, mine: Membership) -> None:
    """The page is published under the namespace owner's name, so its existence and its words
    are theirs: the human who is the namespace owner, any owner of the organisation that is
    (§16.9, §6.26)."""
    project = mine.project
    if mine.kind != "human":
        raise humans_only("the public page is set by the namespace owner, a human")
    if project.owner_org_id is not None:
        if orgs.role_of(conn, project.owner_org_id, mine.row.human_id) != "owner":
            raise orgs.org_role()
    elif mine.row.human_id != project.owner_id:
        raise forbidden(message="only the project's namespace owner sets its public page")


def _authorise_patch(mine: Membership, body: ProjectPatch, given: set[str]) -> None:
    if (
        mine.kind == "agent"
        and in_admin_team(mine.trust, mine.role)
        and given == {"settings"}
        and body.settings is not None
        and body.settings.model_fields_set == {"onboarding"}
    ):
        return  # §2.3 ʰ: coordination alone, never a mixed project/settings PATCH.
    # The absence is written by the owner, the human it concerns, and nobody else (§6.1).
    if "absence" in given and (mine.trust != "owner" or mine.kind != "human"):
        raise forbidden(message="the absence is set by the owner only")
    if given - {"absence", "reason"}:
        mine.require("project:admin")
    # Launch is the owner's go (§6.1): an admin human is refused too.
    moves_to_launch = body.state == "launch" and mine.project.state != "launch"
    if moves_to_launch and (mine.trust != "owner" or mine.kind != "human"):
        raise forbidden(message="moving to launch is the owner's go")


def _absence(project: Any) -> dict[str, Any] | None:
    if project.absence_until is None:
        return None
    return {"until": clock.rfc3339(project.absence_until), "scope": project.absence_scope}


def _owner_id(conn: Connection, project_id: str) -> str:
    row = conn.execute(
        select(t.membership.c.human_id)
        .where(
            t.membership.c.project_id == project_id,
            t.membership.c.trust == "owner",
            t.membership.c.active.is_(True),
        )
        .order_by(t.membership.c.joined_at)
    ).first()
    if row is None:
        raise RuntimeError("a project without an owner")
    owner: str = row.human_id
    return owner


@router.get("/projects/{owner}/{slug}/rules")
def get_rules(slug: str, request: Request, caller: AnyCaller) -> Response:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        # The duty line follows the caller's session: a supervised one gets §15.11's (§6.9).
        supervised = (
            caller.kind == "agent"
            and conn.execute(
                select(t.agent_session.c.supervisor).where(
                    t.agent_session.c.id == caller.session_id
                )
            ).scalar()
            is not None
        )
        text = rules.generate(
            mine.project,
            mine.trust,
            mine.role,
            arbiter_text(conn, mine.project),
            supervised=supervised,
        )
    return Response(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"ETag": f'"{mine.project.rules_version}"'},
    )


def arbiter_text(conn: Connection, project: Any) -> str:
    if project.contract_arbiter == "trust:admin":
        return "the admin role"
    try:
        row = member_row(conn, project.id, project.contract_arbiter)
    except ApiError:  # a former member: name the id
        return f"`{project.contract_arbiter}`"
    return f"`{principal_id(conn, row.id)}`"
