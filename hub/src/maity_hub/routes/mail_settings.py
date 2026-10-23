"""`/admin/settings/mail` (docs/api.md §16.2, §16.3): the instance's SMTP settings and the
test send, for the instance admin. Human only; an agent or runner credential is refused
before anything is read. The password is write-only, and no value from a body is echoed
or logged."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from maity_hub import ratelimit
from maity_hub.admin import instance_admin_id
from maity_hub.deps import HumanCaller, engine_of, settings_of
from maity_hub.errors import ApiError, forbidden, invalid, rate_limited
from maity_hub.mail import address, headers, settings, smtp

router = APIRouter()

# Five test sends per hour per instance admin (§16.3).
test_limiter = ratelimit.Limiter(5, 3600)


def _require_admin(conn: Connection, caller: HumanCaller) -> None:
    if caller.principal_id != instance_admin_id(conn):
        raise forbidden("instance:admin")


@router.get("/admin/settings/mail")
def get_mail(request: Request, caller: HumanCaller) -> JSONResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        return JSONResponse(settings.view(conn, settings.resolve(conn, hub.mail, hub.secret_key)))


@router.patch("/admin/settings/mail")
def patch_mail(
    request: Request, caller: HumanCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        settings.patch(conn, hub.mail, hub.secret_key, body)
        return JSONResponse(settings.view(conn, settings.resolve(conn, hub.mail, hub.secret_key)))


@router.post("/admin/settings/mail/test")
def test_mail(
    request: Request, caller: HumanCaller, body: Annotated[dict[str, Any] | None, Body()] = None
) -> JSONResponse:
    hub = settings_of(request)
    body = body or {}
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        # The body names the recipient and nothing else: no host, port or TLS mode, so
        # the test send reaches no other address from inside the hub's network.
        extra = {name: "extra_forbidden" for name in body if name != "to"}
        if extra:
            raise invalid(extra)
        to = body.get("to")
        # Without `to`, the admin's own verified address (§18.4), which the hub does not
        # hold until notification settings exist.
        if to is None:
            raise invalid({"to": "required"})
        if not address.valid(to):
            raise invalid({"to": "invalid"})
        resolved = settings.resolve(conn, hub.mail, hub.secret_key)
    if not resolved.complete:
        raise ApiError(
            409,
            "mail_not_configured",
            "the mail settings are not complete",
            {"missing": resolved.missing},
        )
    wait = test_limiter.hit(caller.principal_id)
    if wait:
        raise rate_limited(wait)
    sender = resolved.sender
    assert sender is not None
    line = f"Maity test mail from {hub.public_url}"
    mail = headers.message(
        sender=sender.address,
        sender_name=sender.name,
        to=to,
        subject=line,
        body=line + "\n",
        reply_to=resolved.value("reply_to"),
    )
    outcome = smtp.send(resolved, mail)
    with engine_of(request).begin() as conn:
        answer = outcome.view()
        settings.record_test(conn, answer)
    return JSONResponse(answer)
