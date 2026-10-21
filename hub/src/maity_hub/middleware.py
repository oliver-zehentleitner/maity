"""Every request passes through here before routing (docs/api.md §1, §2.2, §2.5).

- the client address and scheme, from forwarded headers of trusted proxies only;
- the body cap (64 KiB) and the credential filter over body and query string;
- the headers every response carries: `Maity-Server-Time`, `Cache-Control:
  no-store`, `X-Content-Type-Options: nosniff`, and a CSP on HTML.
"""

from __future__ import annotations

import contextlib
from collections.abc import MutableMapping
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from maity_hub import clock, net
from maity_hub.auth import credentials
from maity_hub.auth.leaks import revoke_leaked
from maity_hub.config import Settings
from maity_hub.errors import error_response

BODY_CAP = 64 * 1024
CSP = "default-src 'self'"


class HubMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings, engine: Engine) -> None:
        self.app = app
        self.settings = settings
        self.engine = engine

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        origin = net.resolve(scope, self.settings.trusted_proxies)
        scope.setdefault("state", {})["origin"] = origin
        send = _with_headers(send)

        declared = _content_length(scope)
        if declared is not None and declared > BODY_CAP:
            await _too_large(scope, receive, send)
            return
        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > BODY_CAP:
                await _too_large(scope, receive, send)
                return

        found = credentials.find_all(body) + credentials.find_all(scope.get("query_string", b""))
        if found:
            # Refused all the same when the database is down; a verified leak is
            # revoked on its next sighting.
            with contextlib.suppress(OperationalError, InterfaceError):
                await run_in_threadpool(self._revoke, found)
            response = error_response(
                400,
                "credential_in_payload",
                "the request contains a string in the hub's credential format",
            )
            await response(scope, receive, send)
            return

        scope["state"]["body"] = body
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    def _revoke(self, found: list[credentials.Presented]) -> None:
        with self.engine.begin() as conn:
            revoke_leaked(conn, found)


def _content_length(scope: Scope) -> int | None:
    for key, value in scope.get("headers", []):
        if key.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = error_response(413, "payload_too_large", "the body is over 64 KiB")
    await response(scope, receive, send)


def _with_headers(send: Send) -> Send:
    async def wrapped(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in _SET]
            content_type = next(
                (v for k, v in message.get("headers", []) if k.lower() == b"content-type"), b""
            )
            headers += [
                (b"maity-server-time", clock.rfc3339(clock.now(), millis=True).encode()),
                (b"cache-control", b"no-store"),
                (b"x-content-type-options", b"nosniff"),
            ]
            if content_type.startswith(b"text/html"):
                headers.append((b"content-security-policy", CSP.encode()))
            message["headers"] = headers
        await send(message)

    return wrapped


_SET = {b"maity-server-time", b"cache-control", b"x-content-type-options"}
