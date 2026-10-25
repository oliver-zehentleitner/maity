"""Project memory and setup cards (docs/api.md §6.1, §6.21).

A project chooses its memory provider when it is created, and the setup that goes with the
choice is done by an agent, through cards and pull requests, never by the hub. The hub
stores the provider and the options chosen, and opens one `setup` card per option: when the
project is created with a repository, or when its repository is first set. It recreates
nothing, writes nothing into a repository and never checks whether a pull request landed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.board import history
from maity_hub.errors import invalid
from maity_hub.events import Actor, emit
from maity_hub.forge import Forge
from maity_hub.ids import new_id
from maity_hub.policy import CLOSED_STATES, REASON_STATES

KEEP_THE_WHY, NONE = "keep-the-why", "none"
PROVIDERS = (NONE, KEEP_THE_WHY)
KIND = "setup"
OPTIONS = ("keep_the_why_init", "keep_the_why_badge", "maity_badge")  # the cards' order
KEEP_THE_WHY_OPTIONS = ("keep_the_why_init", "keep_the_why_badge")
REASON = "project setup"  # the reason §6.1 asks for in freeze and fixes-only
TITLES = {
    "keep_the_why_init": "Set up Keep the Why in the repository",
    "keep_the_why_badge": "Add the Keep the Why badge to the README",
    "maity_badge": "Add the Maity badge to the README",
}
FINISHED = ("done", "cancelled")  # a setup card in neither still waits


# --- the provider --------------------------------------------------------------------------


def uses_keep_the_why(project: Any) -> bool:
    return bool(project.memory_provider == KEEP_THE_WHY)


def memory_view(project: Any) -> dict[str, str]:
    return {"provider": project.memory_provider}


def provider_of(memory: Any, alias: bool | None) -> str | None:
    """The provider a body names through `memory` or its alias `keep_the_why`; None when
    it names none. Both given and disagreeing is `invalid`."""
    named = None
    if memory is not None:
        if not isinstance(memory, dict) or set(memory) - {"provider"}:
            extra = sorted(set(memory) - {"provider"}) if isinstance(memory, dict) else []
            raise invalid({f"memory.{extra[0]}" if extra else "memory": "unknown_field"})
        named = memory.get("provider")
        if named not in PROVIDERS:
            raise invalid({"memory.provider": "unknown_provider"}, "keep-the-why or none")
    if alias is None:
        return named
    from_alias = KEEP_THE_WHY if alias else NONE
    if named is not None and named != from_alias:
        raise invalid({"keep_the_why": "conflicts_with_memory"}, "memory and keep_the_why disagree")
    return from_alias


# --- the options ---------------------------------------------------------------------------


def options(raw: Any, provider: str) -> dict[str, Any]:
    """The setup as stored: the three booleans with §6.21's defaults (the two Keep the Why
    options true when absent and false under `none`, the Maity badge false when absent),
    and `cards` null until they are made."""
    given: dict[str, Any] = {}
    if raw is not None:
        if not isinstance(raw, dict):
            raise invalid({"setup": "not_an_object"})
        unknown = sorted(set(raw) - set(OPTIONS))
        if unknown:
            raise invalid({f"setup.{unknown[0]}": "unknown_field"})
        wrong = [k for k in OPTIONS if k in raw and not isinstance(raw[k], bool)]
        if wrong:
            raise invalid({f"setup.{wrong[0]}": "not_a_boolean"})
        given = raw
    chosen = {
        "keep_the_why_init": given.get("keep_the_why_init", True),
        "keep_the_why_badge": given.get("keep_the_why_badge", True),
        "maity_badge": given.get("maity_badge", False),
    }
    if provider != KEEP_THE_WHY:  # offered with Keep the Why only (§6.21)
        for key in KEEP_THE_WHY_OPTIONS:
            chosen[key] = False
    return {**chosen, "cards": None}


# --- the cards -----------------------------------------------------------------------------


def _body(option: str, project: Any, public_url: str) -> str:
    repository = project.repository_url
    branch = project.repository_default_branch or "main"
    what = {
        "keep_the_why_init": (
            f"If the repository {repository} has no root `.keep-the-why`, set Keep the Why "
            "up with its default settings (the skill's project init: `context/`, "
            "`.keep-the-why`, the `AGENTS.md` pointer)."
        ),
        "keep_the_why_badge": (f"Add the Keep the Why badge to the `README.md` of {repository}."),
        "maity_badge": (
            f"Add the Maity badge to the `README.md` of {repository}:\n\n"
            f"```markdown\n[![maity]({public_url}/badge/{project.slug}.svg)]"
            f"({public_url}/#/p/{project.slug}/overview)\n```"
        ),
    }[option]
    nothing = {
        "keep_the_why_init": "a root `.keep-the-why` already exists",
        "keep_the_why_badge": "the badge is already in the README",
        "maity_badge": "the badge is already in the README",
    }[option]
    return (
        f"{what}\n\n"
        "**Acceptance:** for a change, a pull request in the repository against its "
        f"default branch (`{branch}`), never a direct push to the default branch; report "
        "the card with the pull request, and it goes to `review` as any card. When nothing "
        f"needs changing ({nothing}), report the card with `code: false` and the reason, "
        "no empty pull request."
    )


def _open_card(
    conn: Connection,
    project: Any,
    option: str,
    created_by: int,
    public_url: str,
    actor: Actor,
    fg: Forge,
) -> str:
    """One `setup` card, open and unassigned, with its `task_created` (§6.21)."""
    from maity_hub.routes.tasks import CREATED, audience  # tasks builds on this module
    from maity_hub.views import task_view

    now = clock.now()
    card_id = new_id("task")
    conn.execute(
        insert(t.card).values(
            id=card_id,
            project_id=project.id,
            kind=KIND,
            title=TITLES[option],
            body=_body(option, project, public_url),
            mentions=[],
            label="chore",
            status="open",
            area="/",
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
    )
    card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
    view = task_view(conn, card, fg)
    fields = [name for name in CREATED if name in view and view[name] not in (None, [])]
    entry = history.created(conn, card_id, {name: view[name] for name in fields}, actor)
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
            "reason": REASON if project.state in REASON_STATES else None,
        },
        actor=actor,
        subject=("task", card_id),
    )
    history.stamp(conn, [entry], seq)
    return card_id


def make_cards(
    conn: Connection, project: Any, created_by: int, public_url: str, actor: Actor, fg: Forge
) -> None:
    """The setup cards, once: for a project that chose a setup, has a repository, has
    none made yet and is not closed. Every true option one card, in the table's order."""
    setup = project.setup
    if setup is None or setup.get("cards") is not None or project.repository_url is None:
        return
    if project.state in CLOSED_STATES:  # §6.1 has no exception for the hub
        return
    made = [
        _open_card(conn, project, option, created_by, public_url, actor, fg)
        for option in OPTIONS
        if setup.get(option)
    ]
    conn.execute(
        update(t.project).where(t.project.c.id == project.id).values(setup={**setup, "cards": made})
    )


# --- the resume packet ---------------------------------------------------------------------


def waiting(conn: Connection, project: Any) -> list[dict[str, Any]] | None:
    """`setup` of the resume packet (§5.2): the setup cards neither done nor cancelled, in
    card order, each `{id, title, status, holder}`; None when there are none."""
    ids = (project.setup or {}).get("cards") or []
    if not ids:
        return None
    rows = {
        r.id: r
        for r in conn.execute(
            select(t.card).where(t.card.c.id.in_(ids), t.card.c.status.notin_(FINISHED))
        )
    }
    if not rows:
        return None
    from maity_hub.views import principal_ids

    holders = principal_ids(conn, (r.claim_holder for r in rows.values()))
    return [
        {
            "id": card_id,
            "title": rows[card_id].title,
            "status": rows[card_id].status,
            "holder": holders.get(rows[card_id].claim_holder),
        }
        for card_id in ids
        if card_id in rows
    ]
