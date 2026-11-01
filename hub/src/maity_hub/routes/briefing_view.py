"""What an agent is told (docs/api.md §19.3.1): the parts of the resume packet that say who it is
and how to work, as a resume of that membership would compute them now.

The view grants no right of its own: a part the caller may not read where it is served is its
outline, without the text. Reading opens no session, emits nothing and moves no cursor.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select

from maity_hub import (
    avatars,
    bridges,
    briefings,
    clock,
    guide,
    instances,
    ktw_skill,
    memory,
    mentions,
    namespace,
    onboarding,
    preferences,
    rules,
    setup_cards,
)
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of, settings_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid, not_found
from maity_hub.namespace import ProjectRoute
from maity_hub.routes.projects import arbiter_text
from maity_hub.views import isolated, paused

router = APIRouter(route_class=ProjectRoute)

KEEP_THE_WHY = ("enabled", "instruction", "skill", "config", "personal_defaults")
SOUL_OUTLINE = ("version", "by", "confirmed_by", "updated_at")
TEXT = "markdown"


def briefing_block(conn: Connection, project: Any, row: Any) -> dict[str, Any]:
    """`membership.briefing` and whose it is (§5.2): the membership's own, with who wrote it and
    its version (§6.2), else the project default with the setting's author and version, else
    none."""
    block = onboarding.briefing(project, row)
    if block["briefing_source"] == "membership":
        by = row.briefing_by
        block["briefing_by"] = briefings.writers(conn, {by}).get(by) if by else None
        block["briefing_version"] = row.briefing_version
    return block


def _caller_membership(conn: Connection, caller: Caller, slug: str) -> Membership | None:
    try:
        return membership(conn, caller, slug)
    except ApiError:
        return None  # an owner outside the project (§6.2)


def _outline(text: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if text is None else {k: v for k, v in text.items() if k != TEXT}


def _preferences(block: dict[str, Any], caller: Caller) -> dict[str, Any]:
    """A human's text only for that human (§19.4)."""
    return {
        **block,
        "items": [
            item if item["human"]["id"] == caller.human_id else _outline(item)
            for item in block["items"]
        ],
    }


def _memory(
    conn: Connection, told: Membership, agent_id: str, reader: Membership, owns: bool
) -> dict[str, Any]:
    """The compact view, each store only for a caller who reads it (§19.1, §19.2)."""
    block = memory.compact_block(conn, told, agent_id)
    soul = block["soul"]
    if not owns:
        block["soul"] = {key: soul[key] for key in SOUL_OUTLINE}
    readers = {
        "team": memory.reads_team(conn, reader, told.row),
        "role": memory.reads_role(reader, told.role),
        "community": reader.may("project:read"),
    }
    for store, reads in readers.items():
        if not reads:
            block[store] = {
                **({"role": told.role} if store == "role" else {}),
                "total": block[store]["total"],
            }
    return block


def _me(conn: Connection, agent: Any, owner: Any, credential: Any) -> dict[str, Any]:
    me = {
        "member_id": agent.id,
        "handle": agent.handle,
        "name": mentions.global_name(owner.handle, agent.handle),  # §6.3
        "display_name": agent.display_name,
        "avatar_url": avatars.urls(conn, [agent.id])[agent.id],
        "owner": {"id": owner.id, "handle": owner.handle},
    }
    if credential is not None:
        me |= {
            "instance": credential.instance,
            "address": instances.address(agent.id, credential.instance),
            "dormant": instances.dormant_view(credential),
        }
    return me


def _credential(conn: Connection, membership_id: int, instance: str | None) -> Any:
    if instance is None:
        return None
    c = t.credential.c
    found = conn.execute(
        select(t.credential).where(
            c.membership_id == membership_id, c.instance == instance, c.revoked_at.is_(None)
        )
    ).first()
    if found is None:
        raise invalid({"instance": "not_an_instance"})
    return found


def _view(
    conn: Connection,
    project: Any,
    target: Any,
    caller: Caller,
    reader: Membership | None,
    credential: Any,
    settings: Any,
) -> dict[str, Any]:
    told = Membership(project, target, "agent")
    agent = conn.execute(
        select(t.agent_profile).where(t.agent_profile.c.id == target.agent_id)
    ).one()
    owner = conn.execute(select(t.human).where(t.human.c.id == agent.owner_id)).one()
    owns = owner.id == caller.human_id
    head = {
        "generated_at": clock.rfc3339(clock.now()),
        "me": _me(conn, agent, owner, credential),
    }
    if target.isolated_since is not None:  # the small packet it would get (§6.2)
        return {
            **head,
            "membership": {
                "trust": told.trust,
                "role": told.role,
                "isolated": isolated(target),
            },
            "project": {
                "id": project.id,
                "full_name": namespace.full_name(conn, project),
                "slug": project.slug,
                "name": project.name,
                "state": project.state,
            },
        }
    texts, given = preferences.texts(conn, told)
    outside = {
        **briefing_block(conn, project, target),
        "owner_preferences": given if owns else _outline(given),
        "team": instances.team(conn, target),
        "paused": paused(target) or (credential and instances.paused_view(credential)) or None,
    }
    if reader is None:  # what §6.2 lets an owner outside read of the agent
        return {**head, "membership": outside}
    bridging = bool(bridges.views(conn, [told.id])[told.id]["bridging_for"])
    placed = conn.execute(
        select(t.placement.c.id).where(
            t.placement.c.membership_id == told.id, t.placement.c.active.is_(True)
        )
    ).first()
    waiting = setup_cards.waiting(conn, project.id)
    check_in = onboarding.hint(conn, project, target)
    loading = ktw_skill.loading_block(project, settings)
    return {
        **head,
        **({"onboarding": check_in} if check_in else {}),
        "membership": {
            "trust": told.trust,
            "role": told.role,
            "guide": guide.of(project, told.trust, told.role, bridging=bridging),
            "isolated": None,
            **outside,
        },
        "rules": {
            "version": project.rules_version,
            "markdown": rules.generate(
                project,
                told.trust,
                told.role,
                arbiter_text(conn, project),
                supervised=placed is not None,
                bridging=bridging,
            ),
        },
        "preferences": _preferences(texts, caller),
        **({"setup": waiting} if waiting else {}),
        "keep_the_why": {
            **{key: loading[key] for key in KEEP_THE_WHY if key in loading},
            "instruction": rules.KEEP_THE_WHY if project.keep_the_why else None,
        },
        "memory": _memory(conn, told, agent.id, reader, owns),
    }


@router.get("/projects/{owner}/{slug}/members/{member_id}/briefing")
def read_briefing(
    slug: str,
    member_id: str,
    request: Request,
    caller: AnyCaller,
    instance: str | None = Query(default=None),
) -> JSONResponse:
    """§19.3.1: for the human who owns the agent profile and humans with `members:admin`."""
    with engine_of(request).begin() as conn:
        project = namespace.resolve(conn, slug)
        if project is None or caller.kind == "runner":
            raise not_found()
        if caller.kind != "human":
            membership(conn, caller, slug)  # not_found outside the project
            raise humans_only("a human reads what an agent is told")
        reader = _caller_membership(conn, caller, slug)
        try:
            target = member_row(conn, project.id, member_id)
        except ApiError:
            target = None
        if target is None:
            raise not_found()
        owns = instances.owns_agent(conn, caller, target)
        if not owns and reader is None:
            raise not_found()
        if target.agent_id is None:
            raise invalid({"member": "not_an_agent"})
        if not owns and (reader is None or not reader.may("members:admin")):
            raise forbidden("members:admin", "the agent's owner or an admin reads it")
        credential = _credential(conn, target.id, instance)
        view = _view(conn, project, target, caller, reader, credential, settings_of(request))
        return JSONResponse(view)
