"""The forge webhook (docs/api.md §17.4): a signed trigger that makes the probe look now.

`POST /api/v1/projects/{slug}/forge/webhook` carries no credential and no cookie; the
forge signs the body with the project's secret (`X-Hub-Signature-256`). It is handled
here, from the middleware, before the body is read: an unknown project, one without a
secret and the limits answer first, so junk cannot make the hub read a megabyte per
attempt. Every refusal looks the same (`webhook_signature`, or `rate_limited` past a
limit), so the path tells nobody whether a project exists or has a secret.

The body is a trigger, never a fact: a `pull_request` closed or a `deployment_status`
queues a read by the probe worker, which announces what the forge itself says.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
from typing import Any

from sqlalchemy import Connection, Engine, delete, insert, select, update
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from maity_hub import clock, events, secretbox, ticker
from maity_hub import tables as t
from maity_hub.errors import ApiError, error_response
from maity_hub.ratelimit import Limiter

log = logging.getLogger(__name__)

PATH = re.compile(r"^/api/v1/projects/([a-z0-9][a-z0-9-]{1,62})/forge/webhook$")
BODY_CAP = 1024 * 1024
FIELD = "forge_webhook.secret"  # the associated data of the sealed secret
# §17.4: 60 verified deliveries a minute per project; 60 unverified requests a minute
# per project and source address; 60 a minute per source address for every request
# naming a project that does not exist or has no secret.
VERIFIED = Limiter(60, 60)
UNVERIFIED = Limiter(60, 60)
NOBODY = Limiter(60, 60)


def matches(scope: Scope) -> bool:
    return scope.get("method") == "POST" and bool(PATH.match(str(scope.get("path", ""))))


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return bytes(value).decode("latin-1")
    return None


def _lookup(engine: Engine, slug: str) -> tuple[Any, Any] | None:
    with engine.connect() as conn:
        project = conn.execute(select(t.project).where(t.project.c.slug == slug)).first()
        if project is None:
            return None
        hook = conn.execute(
            select(t.forge_webhook).where(t.forge_webhook.c.project_id == project.id)
        ).first()
        return (project, hook) if hook is not None else None


def _limited(seconds: int) -> Any:
    return error_response(
        429, "rate_limited", "too many requests", {}, {"Retry-After": str(seconds)}
    )


def _refused() -> Any:
    return error_response(401, "webhook_signature", "the delivery is not signed for this hook", {})


async def handle(
    scope: Scope, receive: Receive, send: Send, engine: Engine, key: bytes | None
) -> int:
    """Answer one delivery; returns the status for the request log."""
    slug = PATH.match(str(scope["path"])).group(1)  # type: ignore[union-attr]
    source = scope["state"]["origin"].address
    found = await run_in_threadpool(_lookup, engine, slug) if key is not None else None
    if found is None:
        # Nothing to check against: refused before the body, from one bucket per address.
        wait = NOBODY.hit(source)
        response = _limited(wait) if wait else _refused()
        await response(scope, receive, send)
        return 429 if wait else 401
    project, hook = found
    bucket = f"{project.id}|{source}"
    wait = UNVERIFIED.blocked(bucket)
    if wait:
        await _limited(wait)(scope, receive, send)
        return 429
    body = b""
    more = True
    while more:
        message = await receive()
        if message["type"] == "http.disconnect":
            return 499
        body += message.get("body", b"")
        more = message.get("more_body", False)
        if len(body) > BODY_CAP:
            UNVERIFIED.hit(bucket)
            await error_response(413, "payload_too_large", "the body is over 1 MiB", {})(
                scope, receive, send
            )
            return 413
    try:
        secret = secretbox.open_sealed(key, FIELD, hook.secret_sealed)  # type: ignore[arg-type]
    except secretbox.SealedError:
        # Fail loud: the hook cannot verify anything until its secret is rotated.
        log.error(
            "forge webhook of %s: the stored secret does not open with MAITY_SECRET_KEY",
            project.slug,
        )
        UNVERIFIED.hit(bucket)
        await _refused()(scope, receive, send)
        return 401
    given = _header(scope, b"x-hub-signature-256") or ""
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(given.encode(), expected.encode()):
        UNVERIFIED.hit(bucket)
        await _refused()(scope, receive, send)
        return 401
    wait = VERIFIED.hit(project.id)
    if wait:
        await run_in_threadpool(_record, engine, project.id, "rate_limited")
        await _limited(wait)(scope, receive, send)
        return 429
    result = _dispatch(scope, project, body)
    await run_in_threadpool(_record, engine, project.id, result)
    await JSONResponse({}, status_code=202)(scope, receive, send)
    return 202


def _dispatch(scope: Scope, project: Any, body: bytes) -> str:
    """Queue the probe's read for what the delivery names; `ok` or `ignored`."""
    kind = _header(scope, b"x-github-event")
    delivery = _header(scope, b"x-github-delivery")
    worker = getattr(getattr(scope.get("app"), "state", None), "probe", None)
    if kind == "ping":
        return "ok"
    if worker is None or not ticker.settings(project)["enabled"]:
        return "ignored"  # the hub announces only what it observed itself
    try:
        payload = json.loads(body)
    except ValueError:
        return "ignored"
    if kind == "pull_request" and payload.get("action") == "closed":
        worker.merges_now(project.id, delivery)
        return "ok"
    if kind == "deployment_status":
        deployment_id = (payload.get("deployment") or {}).get("id")
        if isinstance(deployment_id, int):
            worker.deploy_now(project.id, deployment_id, delivery)
            return "ok"
    return "ignored"


def _record(engine: Engine, project_id: str, result: str) -> None:
    """The last verified delivery, shown on the webhook (§17.4); never an event."""
    with engine.begin() as conn:
        conn.execute(
            update(t.forge_webhook)
            .where(t.forge_webhook.c.project_id == project_id)
            .values(last_delivery_at=clock.now(), last_result=result)
        )


# --- the admin's side: the view, creating, rotating and removing the secret ------------


def url(public_url: str, slug: str) -> str:
    return f"{public_url}/api/v1/projects/{slug}/forge/webhook"


def view(conn: Connection, project: Any, public_url: str) -> dict[str, Any]:
    hook = conn.execute(
        select(t.forge_webhook).where(t.forge_webhook.c.project_id == project.id)
    ).first()
    return {
        "configured": hook is not None,
        "url": url(public_url, project.slug),
        "created_at": clock.rfc3339(hook.created_at) if hook else None,
        "rotated_at": clock.rfc3339(hook.rotated_at) if hook and hook.rotated_at else None,
        "last_delivery_at": (
            clock.rfc3339(hook.last_delivery_at) if hook and hook.last_delivery_at else None
        ),
        "last_result": hook.last_result if hook else None,
    }


def rotate(conn: Connection, project: Any, key: bytes | None, actor: events.Actor, by: str) -> str:
    """Create or rotate the secret; the previous one stops working at once. Returns the
    new secret, which no other answer ever shows again."""
    if key is None:
        raise ApiError(409, "secret_key_missing", "the instance has no MAITY_SECRET_KEY")
    events.lock_project(conn, project.id)
    secret = secrets.token_urlsafe(32)
    sealed = secretbox.seal(key, FIELD, secret.encode())
    now = clock.now()
    exists = conn.execute(
        select(t.forge_webhook.c.project_id).where(t.forge_webhook.c.project_id == project.id)
    ).first()
    if exists:
        conn.execute(
            update(t.forge_webhook)
            .where(t.forge_webhook.c.project_id == project.id)
            .values(secret_sealed=sealed, rotated_at=now)
        )
    else:
        conn.execute(
            insert(t.forge_webhook).values(
                project_id=project.id, secret_sealed=sealed, created_at=now
            )
        )
    _changed(conn, project.id, "rotated" if exists else "created", actor, by)
    return secret


def remove(conn: Connection, project: Any, actor: events.Actor, by: str) -> None:
    events.lock_project(conn, project.id)
    gone = conn.execute(
        delete(t.forge_webhook).where(t.forge_webhook.c.project_id == project.id)
    ).rowcount
    if gone:
        _changed(conn, project.id, "removed", actor, by)


def _changed(conn: Connection, project_id: str, action: str, actor: events.Actor, by: str) -> None:
    """`forge_webhook_changed` to the owners and admins; never the secret (§17.12)."""
    events.emit(
        conn,
        project_id,
        "forge_webhook_changed",
        ["role:owner", "role:admin"],
        {"action": action, "by": by},
        actor=actor,
    )
