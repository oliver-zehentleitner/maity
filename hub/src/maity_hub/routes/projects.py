"""Projects, their state, policy, absence and rules (docs/api.md §6.1, §6.9)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from sqlalchemy import Connection, delete, insert, select, update

from maity_hub import clock, idempotency, images, ktw, placements, policy, releases, rules, ticker
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.deps import AnyCaller, HumanCaller, engine_of, reader_of, settings_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid
from maity_hub.events import emit
from maity_hub.ids import new_id
from maity_hub.models import SLUG_PATTERN, Strict, markdown, title
from maity_hub.views import forge_of, member_view, principal_id, project_view

router = APIRouter()

BROADCAST = ["all"]


class RepositoryIn(Strict):
    url: str = Field(min_length=1, max_length=255)
    default_branch: str = Field(default="main", min_length=1, max_length=255)


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
IMPLEMENTER = re.compile(r"^(member|role|area):\S{1,255}$")


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


class ProjectCreate(Strict):
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = title()
    repository: RepositoryIn | None = None
    keep_the_why: bool = False
    policy: PolicyIn | None = None


class ProjectPatch(Strict):
    name: str | None = title(default=None)
    repository: RepositoryIn | None = None
    keep_the_why: bool | None = None
    state: str | None = None
    state_note: str | None = markdown(default=None)
    policy: PolicyIn | None = None
    absence: AbsenceIn | None = None
    settings: SettingsIn | None = None
    rules_markdown: str | None = markdown(default=None)
    reason: str | None = Field(default=None, max_length=16384)


def _load(conn: Connection, project_id: str) -> Any:
    return conn.execute(select(t.project).where(t.project.c.id == project_id)).one()


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
    conn: Connection, project_id: str, current: dict[str, Any], change: PolicyIn, owner_id: str
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
    if change.contract_arbiter is not None:
        arbiter = change.contract_arbiter
        if arbiter != "role:admin" and not _is_member(conn, project_id, arbiter):
            errors["policy.contract_arbiter"] = "not_a_member"
        proposed["contract_arbiter"] = arbiter
    if errors:
        raise invalid(errors)
    return proposed


def _is_member(conn: Connection, project_id: str, principal: str) -> bool:
    try:
        member_row(conn, project_id, principal)
    except ApiError:  # not_found is the answer here, not an error
        return False
    return True


def _export(project: Any, request: Request) -> dict[str, Any] | None:
    """From the cache only: building a view never waits on a read (§11.3)."""
    return ktw.export_for_view(reader_of(request), project.id, project.repository_url)


def _view(conn: Connection, project: Any, request: Request) -> dict[str, Any]:
    shown = images.views(conn, [project.id])[project.id]
    return project_view(project, settings_of(request), shown, _export(project, request))


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
        return JSONResponse(
            {
                "items": [
                    project_view(r, settings, shown[r.id], _export(r, request)) for r in rows
                ],
                "next_cursor": None,
            }
        )


@router.post("/projects")
def create_project(body: ProjectCreate, request: Request, caller: HumanCaller) -> JSONResponse:

    def action(conn: Connection) -> idempotency.Outcome:
        if conn.execute(select(t.project.c.id).where(t.project.c.slug == body.slug)).first():
            raise invalid({"slug": "taken"}, "a project with this slug exists")
        now = clock.now()
        project_id = new_id("project")
        filled = policy.filled("hierarchical", caller.principal_id)
        conn.execute(
            insert(t.project).values(
                id=project_id,
                slug=body.slug,
                name=body.name,
                state="build",
                state_changed_at=now,
                keep_the_why=body.keep_the_why,
                **_repository_columns(body.repository),
                **policy.columns(filled),
                settings={"release_checklist": []},
                rules_version=1,
                created_at=now,
            )
        )
        result = conn.execute(
            insert(t.membership).values(
                project_id=project_id,
                human_id=caller.human_id,
                role="owner",
                areas=["/"],
                capabilities=[],
                joined_at=now,
                last_seen_at=now,
                changed_via=caller.via,
            )
        )
        key = result.inserted_primary_key
        assert key is not None
        owner = int(key[0])
        if body.policy is not None:
            proposed = _apply_policy(conn, project_id, filled, body.policy, caller.principal_id)
            conn.execute(
                update(t.project)
                .where(t.project.c.id == project_id)
                .values(**policy.columns(proposed))
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
        project = _load(conn, project_id)
        return idempotency.Outcome(201, "project", project_id, _view(conn, project, request))

    return idempotency.run(engine_of(request), request, caller, action)


@router.get("/projects/{slug}")
def get_project(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        return JSONResponse(_view(conn, mine.project, request))


@router.patch("/projects/{slug}")
def patch_project(
    slug: str, body: ProjectPatch, request: Request, caller: AnyCaller
) -> JSONResponse:
    given = body.model_fields_set

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        _refuse_for_agents(mine, body, given)
        _authorise_patch(mine, given)
        project = mine.project
        actor = caller.actor(mine.id)
        owner_id = _owner_id(conn, project.id)
        values: dict[str, Any] = {}
        rules_inputs_changed = False
        if "name" in given and body.name is not None and body.name != project.name:
            values["name"] = body.name
            rules_inputs_changed = True
        if "repository" in given:
            values.update(_repository_columns(body.repository))
        if "settings" in given and body.settings is not None:
            # §6.1: merged by top-level key. A key named replaces its whole value (nested
            # objects are not merged), `null` removes it so it reads as its default, and a
            # key not named stays; `{}` changes nothing.
            named = body.settings.model_fields_set
            if body.settings.ticker is not None:
                _check_ticker(body.settings.ticker)
            dumped = body.settings.model_dump()
            merged = dict(project.settings or {})
            for key in named:
                if dumped[key] is None:
                    merged.pop(key, None)
                else:
                    merged[key] = dumped[key]
            if merged != (project.settings or {}):
                values["settings"] = merged
            was_on = ticker.settings(project)["enabled"]
            now_on = bool((merged.get("ticker") or {}).get("enabled"))
            # Switched on now, or on from before the merges were announced (an install
            # upgraded with the ticker on has no start yet): merges count from now.
            if now_on and (not was_on or ticker.merges_since(conn, project.id) is None):
                ticker.switched_on(conn, project.id)
        new_policy = None
        if "policy" in given and body.policy is not None:
            new_policy = _apply_policy(conn, project.id, policy.of(project), body.policy, owner_id)
            if new_policy == policy.of(project):
                new_policy = None
        state_changes = "state" in given and body.state != project.state
        if state_changes and body.state not in policy.STATES:
            raise invalid({"state": "unknown"})
        if (state_changes or new_policy is not None) and not body.reason:
            raise invalid({"reason": "required"}, "a change of state or policy needs a reason")
        if values:
            conn.execute(update(t.project).where(t.project.c.id == project.id).values(**values))
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
        if new_policy is not None:
            conn.execute(
                update(t.project)
                .where(t.project.c.id == project.id)
                .values(**policy.columns(new_policy))
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
                    subject=("project", project.slug),
                )
        for name in ("rules_markdown", "keep_the_why"):
            new_value = getattr(body, name)
            if name in given and new_value is not None and new_value != getattr(project, name):
                conn.execute(
                    update(t.project).where(t.project.c.id == project.id).values({name: new_value})
                )
                rules_inputs_changed = True
        # The name, a note without a state change, the owner's text and the Keep the
        # Why line are rules inputs without an event of their own: one rules_changed.
        if rules_inputs_changed:
            payload = {"reason": body.reason} if body.reason else {}
            rules.bump(conn, project, "rules_changed", BROADCAST, payload, actor=actor)
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
}


def _refuse_for_agents(mine: Membership, body: Any, given: set[str]) -> None:
    """`humans_only` for what §2.3 lists as no agent's, before any other check."""
    if mine.kind != "agent":
        return
    policy = body.policy.model_fields_set if "policy" in given and body.policy else set()
    if policy & HUMANS_ONLY_POLICY or "rules_markdown" in given or body.state == "archived":
        raise humans_only("no agent changes this, whatever its role")


def _authorise_patch(mine: Membership, given: set[str]) -> None:
    # The absence is written by the owner, the human it concerns, and nobody else (§6.1).
    if "absence" in given and (mine.role != "owner" or mine.kind != "human"):
        raise forbidden(message="the absence is set by the owner only")
    if given - {"absence", "reason"}:
        mine.require("project:admin")


def _absence(project: Any) -> dict[str, Any] | None:
    if project.absence_until is None:
        return None
    return {"until": clock.rfc3339(project.absence_until), "scope": project.absence_scope}


def _owner_id(conn: Connection, project_id: str) -> str:
    row = conn.execute(
        select(t.membership.c.human_id)
        .where(
            t.membership.c.project_id == project_id,
            t.membership.c.role == "owner",
            t.membership.c.active.is_(True),
        )
        .order_by(t.membership.c.joined_at)
    ).first()
    if row is None:
        raise RuntimeError("a project without an owner")
    owner: str = row.human_id
    return owner


@router.get("/projects/{slug}/rules")
def get_rules(slug: str, request: Request, caller: AnyCaller) -> Response:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        text = rules.generate(mine.project, mine.role, arbiter_text(conn, mine.project))
    return Response(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"ETag": f'"{mine.project.rules_version}"'},
    )


def arbiter_text(conn: Connection, project: Any) -> str:
    if project.contract_arbiter == "role:admin":
        return "the admin role"
    try:
        row = member_row(conn, project.id, project.contract_arbiter)
    except ApiError:  # a former member: name the id
        return f"`{project.contract_arbiter}`"
    return f"`{principal_id(conn, row.id)}`"
