"""The forge webhook's settings (docs/api.md §17.4): its view and its secret, for a human
with `project:admin`. Deliveries are answered by `maity_hub.forge_webhook` itself."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select

from maity_hub import forge_webhook, idempotency
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.deps import HumanCaller, engine_of, settings_of

router = APIRouter()


@router.get("/projects/{slug}/forge/webhook")
def get_webhook(slug: str, request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:admin")
        return JSONResponse(
            forge_webhook.view(
                conn, mine.project, settings_of(request).public_url, settings_of(request).secret_key
            )
        )


@router.post("/projects/{slug}/forge/webhook/secret")
def rotate_secret(slug: str, request: Request, caller: HumanCaller) -> JSONResponse:
    """The secret is answered once, here; a replay does not show it again (§17.4)."""
    settings = settings_of(request)

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("project:admin")
        secret = forge_webhook.rotate(
            conn, mine.project, settings.secret_key, caller.actor(mine.id), mine.principal_id
        )
        body = {"secret": secret, "url": forge_webhook.url(settings.public_url, slug)}
        return idempotency.Outcome(201, "forge_webhook", mine.project.id, body)

    return idempotency.run(engine_of(request), request, caller, action)


@router.delete("/projects/{slug}/forge/webhook/secret")
def remove_secret(slug: str, request: Request, caller: HumanCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("project:admin")
        forge_webhook.remove(conn, mine.project, caller.actor(mine.id), mine.principal_id)
        view = forge_webhook.view(
            conn, mine.project, settings_of(request).public_url, settings_of(request).secret_key
        )
        return idempotency.Outcome(200, "forge_webhook", mine.project.id, view)

    return idempotency.run(engine_of(request), request, caller, action)


def _replayed(conn: Connection, project_id: str, request: Request) -> dict[str, object]:
    """A replay answers the webhook's view, never the secret again."""
    project = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
    return forge_webhook.view(
        conn, project, settings_of(request).public_url, settings_of(request).secret_key
    )


idempotency.LOADERS["forge_webhook"] = _replayed
