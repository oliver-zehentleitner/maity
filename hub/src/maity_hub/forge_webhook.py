"""The forge webhook (docs/api.md §17.4): a signed trigger that makes the probe look now.

`POST /api/v1/projects/{slug}/forge/webhook` carries no credential and no cookie; the
forge signs the body with the project's secret (`X-Hub-Signature-256`). It is handled
here, from the middleware, before the body is read: an unknown project, one without a
secret, a body declared over the cap and the limits answer first, so junk cannot make
the hub read a megabyte per attempt. Every refusal looks the same for every slug
(`webhook_signature`, `payload_too_large`, or `rate_limited` past a limit), so the path
tells nobody whether a project exists or has a secret.

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
FIELD = "forge_webhook.secret"


def field(project_id: str) -> str:
    """The associated data of a project's sealed secret: the field and the project, so a
    value copied into another field or another project's row does not open."""
    return f"{FIELD}:{project_id}"


# The forge's delivery id, kept as `origin.delivery` (§17.4) only in this shape; GitHub's
# is a UUID. Anything else is stored as null: the header is the sender's to fill.
DELIVERY = re.compile(r"^[A-Za-z0-9-]{1,64}$")
# §17.4: 60 verified deliveries a minute per project; 60 unverified requests a minute
# per project and source address; 60 a minute per source address for every request
# that does not verify, whatever slug it names (`NOBODY`, one bucket per address).
VERIFIED = Limiter(60, 60)
UNVERIFIED = Limiter(60, 60)
NOBODY = Limiter(60, 60)


def matches(scope: Scope) -> bool:
    return scope.get("method") == "POST" and bool(PATH.match(str(scope.get("path", ""))))


def _headers(scope: Scope, name: bytes) -> list[str]:
    return [
        bytes(value).decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.lower() == name
    ]


def _header(scope: Scope, name: bytes) -> str | None:
    found = _headers(scope, name)
    return found[0] if found else None


def _declared(scope: Scope) -> int | None:
    """The one declared Content-Length, or None when it is missing, repeated or no number."""
    found = _headers(scope, b"content-length")
    if len(found) != 1 or not found[0].isdigit():
        return None
    return int(found[0])


def _lookup(engine: Engine, slug: str, key: bytes) -> tuple[Any, bytes] | None:
    """The project and its opened secret; None for no project, no secret or a secret the
    key does not open, which all answer alike (§17.4)."""
    with engine.connect() as conn:
        project = conn.execute(select(t.project).where(t.project.c.slug == slug)).first()
        if project is None:
            return None
        hook = conn.execute(
            select(t.forge_webhook).where(t.forge_webhook.c.project_id == project.id)
        ).first()
    if hook is None:
        return None
    try:
        return project, secretbox.open_sealed(key, field(project.id), hook.secret_sealed)
    except secretbox.SealedError:
        # Fail loud: the hook verifies nothing until its secret is rotated (§16.2's rule).
        log.error(
            "forge webhook of %s: the stored secret does not open with MAITY_SECRET_KEY",
            project.slug,
        )
        return None


def _limited(seconds: int) -> Any:
    return error_response(
        429, "rate_limited", "too many requests", {}, {"Retry-After": str(seconds)}
    )


def _refused() -> Any:
    return error_response(401, "webhook_signature", "the delivery is not signed for this hook", {})


def _too_large() -> Any:
    return error_response(
        413, "payload_too_large", "the body is over 1 MiB or declares no length", {}
    )


async def _answer(response: Any, scope: Scope, receive: Receive, send: Send) -> int:
    await response(scope, receive, send)
    return int(response.status_code)


async def handle(
    scope: Scope, receive: Receive, send: Send, engine: Engine, key: bytes | None
) -> int:
    """Answer one delivery; returns the status for the request log.

    Every request that does not verify counts against its source address (`NOBODY`),
    whether the slug exists or not, and is answered `rate_limited` past that limit, so
    neither the answer nor the limit tells a known slug from an unknown one. Only a
    known slug's request reads its body, and only after taking a place in the bucket of
    its project and address (`UNVERIFIED`), given back once the signature verifies: at
    most 60 bodies per project and address are ever read at once, and a verified
    delivery is never refused for what others sent from the same forge address."""
    slug = PATH.match(str(scope["path"])).group(1)  # type: ignore[union-attr]
    source = scope["state"]["origin"].address

    async def refuse(response: Any) -> int:
        wait = NOBODY.hit(source)
        return await _answer(_limited(wait) if wait else response, scope, receive, send)

    declared = _declared(scope)
    if declared is None or declared > BODY_CAP:
        return await refuse(_too_large())
    found = await run_in_threadpool(_lookup, engine, slug, key) if key is not None else None
    if found is None:
        # Nothing to check against: refused before the body.
        return await refuse(_refused())
    project, secret = found
    bucket = f"{project.id}|{source}"
    wait = UNVERIFIED.hit(bucket)
    if wait:
        return await refuse(_limited(wait))
    body = b""
    more = True
    while more:
        message = await receive()
        if message["type"] == "http.disconnect":
            return 499
        body += message.get("body", b"")
        more = message.get("more_body", False)
        if len(body) > BODY_CAP:
            return await refuse(_too_large())
    given = _headers(scope, b"x-hub-signature-256")
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    # One signature or none: with two, which one the forge meant is anyone's guess.
    if len(given) != 1 or not hmac.compare_digest(given[0].encode(), expected.encode()):
        return await refuse(_refused())
    UNVERIFIED.give_back(bucket, 1)
    wait = VERIFIED.hit(project.id)
    if wait:
        await run_in_threadpool(_record, engine, project.id, "rate_limited")
        return await _answer(_limited(wait), scope, receive, send)
    result = _dispatch(scope, project, body)
    if result == "invalid":
        await run_in_threadpool(_record, engine, project.id, "ignored")
        return await _answer(
            error_response(400, "invalid", "the body is not a JSON object", {"fields": {}}),
            scope,
            receive,
            send,
        )
    await run_in_threadpool(_record, engine, project.id, result)
    return await _answer(JSONResponse({}, status_code=202), scope, receive, send)


def delivery_id(scope: Scope) -> str | None:
    value = _header(scope, b"x-github-delivery")
    return value if value is not None and DELIVERY.fullmatch(value) else None


def _object(payload: dict[str, Any], name: str) -> dict[str, Any]:
    found = payload.get(name)
    return found if isinstance(found, dict) else {}


def _dispatch(scope: Scope, project: Any, body: bytes) -> str:
    """Queue the probe's read for what the delivery names; `ok`, `ignored`, or `invalid`
    for a body that is not a JSON object."""
    kind = _header(scope, b"x-github-event")
    delivery = delivery_id(scope)
    worker = getattr(getattr(scope.get("app"), "state", None), "probe", None)
    if kind == "ping":
        return "ok"
    try:
        payload = json.loads(body)
    except ValueError:
        return "invalid"
    if not isinstance(payload, dict):
        return "invalid"
    if worker is None or not ticker.settings(project)["enabled"]:
        return "ignored"  # the hub announces only what it observed itself
    if kind == "pull_request" and payload.get("action") == "closed":
        number = _object(payload, "pull_request").get("number")
        worker.merges_now(project.id, delivery, number if isinstance(number, int) else None)
        return "ok"
    if kind == "deployment_status":
        deployment_id = _object(payload, "deployment").get("id")
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


def view(conn: Connection, project: Any, public_url: str, key: bytes | None) -> dict[str, Any]:
    """`configured` only for a secret the instance key opens: one it cannot open counts
    as not set, as §16.2 has it for the SMTP password, and verifies no delivery."""
    hook = conn.execute(
        select(t.forge_webhook).where(t.forge_webhook.c.project_id == project.id)
    ).first()
    return {
        "configured": hook is not None and _opens(key, project.id, hook.secret_sealed),
        "url": url(public_url, project.slug),
        "created_at": clock.rfc3339(hook.created_at) if hook else None,
        "rotated_at": clock.rfc3339(hook.rotated_at) if hook and hook.rotated_at else None,
        "last_delivery_at": (
            clock.rfc3339(hook.last_delivery_at) if hook and hook.last_delivery_at else None
        ),
        "last_result": hook.last_result if hook else None,
    }


def _opens(key: bytes | None, project_id: str, sealed: bytes) -> bool:
    if key is None:
        return False
    try:
        secretbox.open_sealed(key, field(project_id), sealed)
    except secretbox.SealedError:
        return False
    return True


def check_secrets(engine: Engine, key: bytes | None) -> int:
    """At startup: how many stored webhook secrets the instance key does not open, logged
    loud once; those hooks refuse every delivery until their secret is rotated."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.project.c.id, t.project.c.slug, t.forge_webhook.c.secret_sealed).join(
                t.project, t.project.c.id == t.forge_webhook.c.project_id
            )
        ).all()
    unusable = sorted(row.slug for row in rows if not _opens(key, row.id, row.secret_sealed))
    if unusable:
        log.error(
            "%d forge webhook secret(s) cannot be opened (%s): MAITY_SECRET_KEY is %s; "
            "their deliveries are refused until the secret is rotated",
            len(unusable),
            ", ".join(unusable),
            "unset" if key is None else "not the key they were sealed with",
        )
    return len(unusable)


def rotate(conn: Connection, project: Any, key: bytes | None, actor: events.Actor, by: str) -> str:
    """Create or rotate the secret; the previous one stops working at once. Returns the
    new secret, which no other answer ever shows again."""
    if key is None:
        raise ApiError(409, "secret_key_missing", "the instance has no MAITY_SECRET_KEY")
    events.lock_project(conn, project.id)
    secret = secrets.token_urlsafe(32)
    sealed = secretbox.seal(key, field(project.id), secret.encode())
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
