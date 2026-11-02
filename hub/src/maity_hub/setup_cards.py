"""The setup cards of a project's memory choice (docs/api.md §6.21).

The hub never writes into a repository: for every option the creator left on it opens
one card, and an agent does the work through a pull request.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import clock, namespace
from maity_hub import tables as t
from maity_hub.board import history
from maity_hub.errors import invalid
from maity_hub.events import Actor, emit
from maity_hub.forge import Forge
from maity_hub.ids import new_id
from maity_hub.policy import REASON_STATES

# The options in the order of the §6.21 table, which is also the order of the cards.
OPTIONS = (
    "keep_the_why_init",
    "keep_the_why_badge",
    "keep_the_why_ci",
    "keep_the_why_dashboard",
    "maity_badge",
)
DEFAULTS = {
    "keep_the_why_init": True,
    "keep_the_why_badge": True,
    "keep_the_why_ci": True,
    "keep_the_why_dashboard": True,
    "maity_badge": False,
}
KEEP_THE_WHY_OPTIONS = (
    "keep_the_why_init",
    "keep_the_why_badge",
    "keep_the_why_ci",
    "keep_the_why_dashboard",
)
TITLES = {
    "keep_the_why_init": "Set up Keep the Why in the repository",
    "keep_the_why_badge": "Add the Keep the Why badge to the README",
    "keep_the_why_ci": "Run the Keep the Why linter in CI",
    "keep_the_why_dashboard": "Publish the Keep the Why dashboard",
    "maity_badge": "Add the Maity badge to the README",
}
# The URL path below the documentation site's root the dashboard is published under.
DASHBOARD_PATH = "dashboard_path"
DASHBOARD_PATH_DEFAULT = "keep-the-why-dashboard"
_SEGMENT = re.compile(r"[a-z0-9][a-z0-9._-]{0,62}", re.ASCII)
REASON = "project setup"

ACCEPTANCE = (
    "Acceptance: for a change, open a pull request in the repository against its default "
    "branch, never a direct push to the default branch, and report the card with the pull "
    "request. When nothing needs changing, report the card with `code: false` and say why: "
    "no empty pull request."
)


def _is_dashboard_path(value: Any) -> bool:
    """One to five segments of `[a-z0-9][a-z0-9._-]{0,62}` joined by `/`: no leading or
    trailing slash, no `..` (§6.21)."""
    if not isinstance(value, str) or ".." in value:
        return False
    segments = value.split("/")
    return 1 <= len(segments) <= 5 and all(_SEGMENT.fullmatch(s) for s in segments)


def parse(raw: Any, memory_on: bool) -> dict[str, Any]:
    """The options and `dashboard_path` of a `setup` body (§6.21): an absent key takes its
    default, a non-boolean option is `not_a_boolean`, a path out of shape (`null`
    included) `format`, an unknown key `unknown_field`. The Keep the Why options are
    `false` whatever was sent under the provider `none`, and the path is kept only while
    `keep_the_why_dashboard` is `true`: dropped otherwise, read back `null`."""
    if raw is None:
        raw = {}
    errors: dict[str, str] = {}
    if not isinstance(raw, dict):
        raise invalid({"setup": "not_an_object"})
    for key, value in raw.items():
        if key == DASHBOARD_PATH:
            if not _is_dashboard_path(value):
                errors[f"setup.{key}"] = "format"
        elif key not in OPTIONS:
            errors[f"setup.{key}"] = "unknown_field"
        elif not isinstance(value, bool):
            errors[f"setup.{key}"] = "not_a_boolean"
    if errors:
        raise invalid(errors)
    options: dict[str, Any] = {key: raw.get(key, DEFAULTS[key]) for key in OPTIONS}
    if not memory_on:
        for key in KEEP_THE_WHY_OPTIONS:
            options[key] = False
    options[DASHBOARD_PATH] = (
        raw.get(DASHBOARD_PATH, DASHBOARD_PATH_DEFAULT)
        if options["keep_the_why_dashboard"]
        else None
    )
    return options


def stored(options: dict[str, Any]) -> dict[str, Any]:
    """Chosen, nothing created yet (`cards` is `null`)."""
    return {**options, "cards": None}


def view(project: Any) -> dict[str, Any]:
    """`setup` of the project view (§6.1). A project from before the CI, dashboard and path
    options has them as `false`, `false` and `null`, written by the migration that added them."""
    value: dict[str, Any] = project.setup
    return value


def _body(key: str, project: Any, hub_url: str, full_name: str) -> str:
    repository = project.repository_url
    path = project.setup.get(DASHBOARD_PATH)
    if key == "keep_the_why_init":
        what = (
            f"Set up Keep the Why in {repository} with its default settings: the skill's "
            "project init (`context/`, `.keep-the-why`, the `AGENTS.md` pointer). If the "
            "repository already has a root `.keep-the-why`, there is nothing to change."
        )
    elif key == "keep_the_why_badge":
        what = (
            f"Add the Keep the Why badge to the `README.md` of {repository}, as the Keep "
            "the Why skill documents it. If the README already has it, there is nothing "
            "to change."
        )
    elif key == "keep_the_why_ci":
        what = (
            f"Run `ktw-lint` in the CI of {repository} for every directory with a "
            "`.keep-the-why`, so that a pull request with a broken entry fails. A "
            "repository without CI gets a new workflow on the forge's own CI (GitHub "
            "Actions, GitLab CI/CD) that runs only this step. Accepted when a pull "
            "request's run shows the lint step green."
        )
    elif key == "keep_the_why_dashboard":
        what = (
            f"Publish the Keep the Why dashboard where {repository} publishes its "
            "documentation (GitHub Pages, GitLab Pages or the forge's equivalent), under "
            f"the path `{path}` below the site's root, for the root and every child "
            "directory with its own `.keep-the-why` (a child's below "
            f"`{path}/<child directory>/`). Into the `dashboard-state:` line of each of "
            "those `.keep-the-why` write the URL of that dashboard's `state.json`, "
            f"`https://<site root>/{path}[/<child directory>]/state.json`, not the page's "
            "URL: the hub reads JSON from that line, and a page URL leaves the members at "
            "`ktw_unavailable`. Accepted when each written URL answers over HTTPS with "
            "the JSON after the merge. A repository with no such publishing is reported "
            "with `code: false`, saying what is missing."
        )
    else:
        # The §6.20 snippet with path addresses (§16.11): it stays in a README for good,
        # and no `/#/…` route is served or redirected.
        snippet = f"[![maity]({hub_url}/badge/{full_name}.svg)]({hub_url}/{full_name}/overview)"
        what = (
            f"Add the Maity badge to the `README.md` of {repository}:\n\n```markdown\n"
            f"{snippet}\n```\n\nThe badge already serves; this card only puts the snippet "
            "into the README. If it is already there, there is nothing to change."
        )
    return f"{what}\n\n{ACCEPTANCE}"


def create(
    conn: Connection,
    project: Any,
    hub_url: str,
    creator: int,
    actor: Actor,
    fg: Forge,
) -> list[str]:
    """One card per option that is `true`, in the order of `OPTIONS`, each with its
    `task_created` event, and `setup.cards` set to their ids (`[]` when no option is on).
    The caller checks that the project may have them: it has a repository, its `setup`
    holds no cards yet, it is not archived."""
    from maity_hub.routes.tasks import CREATED, audience
    from maity_hub.views import task_view

    options: dict[str, Any] = project.setup
    full_name = namespace.full_name(conn, project)
    reason = REASON if project.state in REASON_STATES else None
    ids: list[str] = []
    for key in OPTIONS:
        if not options.get(key):
            continue
        now = clock.now()
        card_id = new_id("task")
        conn.execute(
            insert(t.card).values(
                id=card_id,
                project_id=project.id,
                kind="setup",
                title=TITLES[key],
                body=_body(key, project, hub_url, full_name),
                mentions=[],
                label="chore",
                status="open",
                area="/",
                created_by=creator,
                created_at=now,
                updated_at=now,
            )
        )
        card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
        card_view = task_view(conn, card, fg)
        fields = [
            name for name in CREATED if name in card_view and card_view[name] not in (None, [])
        ]
        entry = history.created(conn, card_id, {name: card_view[name] for name in fields}, actor)
        seq = emit(
            conn,
            project.id,
            "task_created",
            audience(conn, card),
            {
                **{k: v for k, v in card_view.items() if k != "body"},  # never in an event
                "fields": fields,
                "history": [entry],
                "project_state": project.state,
                "reason": reason,
            },
            actor=actor,
            subject=("task", card_id),
        )
        history.stamp(conn, [entry], seq)
        ids.append(card_id)
    conn.execute(
        update(t.project)
        .where(t.project.c.id == project.id)
        .values(setup={**options, "cards": ids})
    )
    return ids


def waiting(conn: Connection, project_id: str) -> list[dict[str, Any]]:
    """The packet's `setup` (§5.2): the setup cards that are not `done` or `cancelled`, in
    card order, each `{id, title, status, holder}`; empty when none waits."""
    from maity_hub.views import principal_id

    rows = conn.execute(
        select(t.card)
        .where(
            t.card.c.project_id == project_id,
            t.card.c.kind == "setup",
            t.card.c.status.notin_(("done", "cancelled")),
        )
        .order_by(t.card.c.created_at, t.card.c.id)
    ).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "status": row.status,
            "holder": principal_id(conn, row.claim_holder),
        }
        for row in rows
    ]
