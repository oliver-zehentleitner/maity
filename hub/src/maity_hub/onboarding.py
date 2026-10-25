"""Project onboarding (§6.1): live defaults and a sticky per-membership check-in."""

from __future__ import annotations

from typing import Any

from pydantic import Field
from sqlalchemy import Connection, func, select, update

from maity_hub import clock, policy
from maity_hub import tables as t
from maity_hub.errors import invalid
from maity_hub.models import Strict, markdown
from maity_hub.scopes import ROLES


class OnboardingIn(Strict):
    briefing: str | None = markdown(default=None)
    check_in_with: str | None = Field(default=None, min_length=1, max_length=200)
    # A read/edited/sent-back object is accepted. Only the hub writes these facts.
    version: Any = None
    by: Any = None
    updated_at: Any = None

    def content(self) -> dict[str, Any]:
        return self.model_dump(include={"briefing", "check_in_with"}, exclude_none=True)


def settings(project: Any) -> dict[str, Any]:
    value = (project.settings or {}).get("onboarding")
    return dict(value) if isinstance(value, dict) else {"check_in_with": "coordinator"}


def members(conn: Connection, project_id: str) -> list[Any]:
    return list(
        conn.execute(
            select(
                t.membership,
                func.coalesce(t.agent_profile.c.handle, t.human.c.handle).label("handle"),
            )
            .select_from(t.membership)
            .outerjoin(t.agent_profile, t.membership.c.agent_id == t.agent_profile.c.id)
            .outerjoin(t.human, t.membership.c.human_id == t.human.c.id)
            .where(t.membership.c.project_id == project_id, t.membership.c.active.is_(True))
        ).all()
    )


def principal(row: Any) -> str:
    value: str = row.agent_id or row.human_id
    return value


def identity(row: Any) -> dict[str, Any]:
    return {
        "id": principal(row),
        "handle": row.handle,
        "kind": "agent" if row.agent_id else "human",
    }


def target(conn: Connection, project: Any) -> Any | None:
    """Resolve live members, with stable role ordering; availability stand-ins follow §6.12."""
    token = settings(project).get("check_in_with")
    if not token:
        return None
    rows = members(conn, project.id)
    ordered = sorted(rows, key=lambda row: (row.handle, principal(row)))
    if token != "coordinator":
        if token.startswith("role:"):
            matches = [row for row in ordered if row.role == token.removeprefix("role:")]
        else:
            matches = [row for row in ordered if principal(row) == token]
        if matches:
            return matches[0]
        if not token.startswith("role:"):
            return None
    coordinator = policy.of(project).get("coordinator", "role:admin")
    if coordinator == "role:admin":
        candidates = [row for row in ordered if row.agent_id and row.role == "admin"]
    else:
        candidates = [row for row in ordered if principal(row) == coordinator]
    if candidates:
        return candidates[0]
    owners = sorted(
        [row for row in rows if row.human_id and row.role == "owner"],
        key=lambda row: (row.joined_at, principal(row)),
    )
    return owners[0] if owners else None


def validate(conn: Connection, project: Any, body: OnboardingIn) -> None:
    token = body.check_in_with
    if not token or token == "coordinator":
        return
    field = "settings.onboarding.check_in_with"
    if token.startswith("role:"):
        if token.removeprefix("role:") not in ROLES:
            raise invalid({field: "unknown_role"})
    elif not any(principal(row) == token for row in members(conn, project.id)):
        raise invalid({field: "not_a_member"})


def replace_setting(
    conn: Connection,
    project: Any,
    body: OnboardingIn | None,
    actor_member: int | None,
    by: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None]:
    """Return changed, stored value and text-free event value; caller holds project lock.
    The writer is the acting member, or `by` for a human who is none (§6.3's cascade)."""
    old = (project.settings or {}).get("onboarding")
    content = body.content() if body is not None else None
    old_content = (
        {k: v for k, v in old.items() if k in {"briefing", "check_in_with"}}
        if isinstance(old, dict)
        else None
    )
    if content == old_content:
        return False, old, None
    if body is not None:
        validate(conn, project, body)
    if by is None:
        by = identity(next(row for row in members(conn, project.id) if row.id == actor_member))
    version = project.onboarding_version + 1
    conn.execute(
        update(t.project).where(t.project.c.id == project.id).values(onboarding_version=version)
    )
    metadata = {
        "version": version,
        "by": by,
        "updated_at": clock.rfc3339(clock.now()),
    }
    if content is None:
        return True, None, None
    stored = {**content, **metadata}
    return True, stored, {**metadata, "check_in_with": content.get("check_in_with")}


def briefing(project: Any, membership: Any) -> dict[str, Any]:
    if membership.briefing is not None:
        return {"briefing": membership.briefing, "briefing_source": "membership"}
    value = settings(project)
    if value.get("briefing") is not None:
        return {
            "briefing": value["briefing"],
            "briefing_source": "project",
            "briefing_by": value.get("by"),
            "briefing_version": value.get("version"),
        }
    return {"briefing": None, "briefing_source": None}


def hint(conn: Connection, project: Any, membership: Any) -> dict[str, Any] | None:
    if membership.agent_id is None or membership.onboarded_at is not None:
        return None
    resolved = target(conn, project)
    if resolved is None or principal(resolved) == principal(membership):
        return None
    return {
        "check_in_with": {
            "member_id": principal(resolved),
            "handle": resolved.handle,
            "kind": "agent" if resolved.agent_id else "human",
        },
        "instruction": (
            f"Send @{resolved.handle} a message before taking any work: "
            "say that you joined and ask how to start."
        ),
    }


def observe(
    conn: Connection,
    project: Any,
    kind: str,
    payload: dict[str, Any],
    actor_member: int | None,
    at: Any,
) -> None:
    """Called in the event transaction, under the project lock. No event or wake of its own."""
    if kind == "task_claimed":
        condition = t.membership.c.agent_id == payload.get("holder")
    elif kind == "message" and actor_member is not None:
        row = conn.execute(select(t.membership).where(t.membership.c.id == actor_member)).one()
        if row.agent_id is None or row.onboarded_at is not None:
            return
        if payload.get("type") == "chat" and payload.get("conversation_id") != row.agent_id:
            return  # A direct conversation is keyed by the agent; a group never counts.
        resolved = target(conn, project)
        if resolved is None:
            return
        to = payload.get("to")
        # Direct chat payloads carry the real other party; group chats do not use a member to.
        reaches = to in {principal(resolved), f"role:{resolved.role}"}
        if isinstance(to, str) and to.startswith(principal(resolved) + "#"):
            reaches = True
        if not reaches:
            return
        condition = t.membership.c.id == actor_member
    else:
        return
    conn.execute(
        update(t.membership)
        .where(
            t.membership.c.project_id == project.id,
            t.membership.c.active.is_(True),
            t.membership.c.agent_id.is_not(None),
            t.membership.c.onboarded_at.is_(None),
            condition,
        )
        .values(onboarded_at=at)
    )


def member_removed(conn: Connection, project_id: str, removed: str, actor: Any) -> None:
    """A named seat returns to coordinator; keep briefing and all other settings."""
    from maity_hub.events import emit, lock_project

    project = lock_project(conn, project_id)
    current = (project.settings or {}).get("onboarding")
    if not isinstance(current, dict) or current.get("check_in_with") != removed:
        return
    body = OnboardingIn(briefing=current.get("briefing"), check_in_with="coordinator")
    by = None
    if actor.membership_id is None:  # an owner deleting a profile, no member here (§6.3)
        handle = conn.execute(
            select(t.human.c.handle).where(t.human.c.id == actor.human_id)
        ).scalar_one()
        by = {"id": actor.human_id, "handle": handle, "kind": "human"}
    _, stored, announcement = replace_setting(conn, project, body, actor.membership_id, by)
    merged = {**project.settings, "onboarding": stored}
    conn.execute(update(t.project).where(t.project.c.id == project_id).values(settings=merged))
    emit(
        conn,
        project_id,
        "project_updated",
        ["all"],
        {"fields": {"settings.onboarding": announcement}},
        actor=actor,
        subject=("project", project.slug),
    )
