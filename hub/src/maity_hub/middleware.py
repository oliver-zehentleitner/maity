"""Every request passes through here before routing (docs/api.md §1, §2.2, §2.5).

- the client address and scheme, from forwarded headers of trusted proxies only;
- the body cap (64 KiB) and the credential filter over body and query string;
- the headers every response carries: `Maity-Server-Time`, `Cache-Control:
  no-store`, `X-Content-Type-Options: nosniff`, and a CSP on HTML.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import unquote_to_bytes

from sqlalchemy import Engine
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.concurrency import run_in_threadpool
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from maity_hub import clock, events, forge_webhook, join_host, net
from maity_hub.auth import credentials
from maity_hub.auth.leaks import revoke_leaked
from maity_hub.config import Settings
from maity_hub.errors import error_response

log = logging.getLogger(__name__)
# The hub's own request log; the server's access log is off (§1.1).
access = logging.getLogger("maity_hub.access")

BODY_CAP = 64 * 1024
# An uploaded logo, banner or avatar may be up to 1 MiB (docs/api.md §1.7, §11.2,
# §6.10); past it the answer is `invalid` with `fields.body: too_large`, not 413.
IMAGE_CAP = 1024 * 1024
_IMAGE_UPLOAD = re.compile(
    r"^/api/v1/(projects/[^/]+/(logo|banner)|me/avatar|agents/[^/]+/avatar)$"
)
# The landing page's Markdown may be 64 KiB decoded (§16.7); JSON escaping can grow it up
# to four times on the wire, so its PATCH alone takes a larger body.
LANDING_CAP = 256 * 1024
# An attachment upload is one raw file of up to 10 MiB (§8.7); the body cap of §1.7 does not
# apply to it, the file cap does.
ATTACHMENT_CAP = 10 * 1024 * 1024
_ATTACHMENT_UPLOAD = re.compile(r"^/api/v1/projects/[^/]+/attachments$")
_LANDING_SETTINGS = "/api/v1/admin/settings/landing"
CSP = "default-src 'self'"
# The private Cache-Control a route may set instead of no-store: the project images
# (images.HEADERS) and the avatars, revalidated on every use (avatars.HEADERS).
ROUTE_CACHE = frozenset({b"private, max-age=21600", b"private, no-cache"})
# The answers a visitor without a session may cache: the badge, the swarm page and the
# instance's landing page (§16.7).
PUBLIC_PATHS = re.compile(r"/badge/[^/]+\.svg|/api/v1/swarm/[^/]+|/api/v1/landing")


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
        # Decided before anything is logged: the log masks every path there (§1.1).
        on_join_host = join_host.is_join_host(scope, self.settings)
        scope["state"]["on_join_host"] = on_join_host
        public = (
            not on_join_host
            and scope.get("method") == "GET"
            and bool(PUBLIC_PATHS.fullmatch(scope.get("path", "")))
        )
        send = _with_headers(send, public=public)

        if not on_join_host and forge_webhook.matches(scope):
            # Signed, not authenticated, and limited before its body is read (§17.4).
            status = 500
            try:
                status = await forge_webhook.handle(
                    scope, receive, send, self.engine, self.settings.secret_key
                )
            except Exception:
                # In the envelope like any other route (§1.3); the body is not logged.
                log.exception("unhandled error on %s %s", scope.get("method"), _logged_path(scope))
                await error_response(500, "internal", "an unexpected failure")(scope, receive, send)
            finally:
                access.info("%s %s %s", scope.get("method"), _logged_path(scope), status)
            return

        if not on_join_host and _unrouted(scope):
            # Nothing here would read it: 404 before the cap, and the body is never read.
            await _not_found(scope, receive, send)
            return
        cap, refuse = _body_cap(scope)
        declared = _content_length(scope)
        if declared is not None and declared > cap:
            await refuse(scope, receive, send)
            return
        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > cap:
                await refuse(scope, receive, send)
                return

        raw_query: bytes = scope.get("query_string", b"")
        # The query is matched raw and percent-decoded (§2.2): `mty1%2E…` too.
        found = (
            credentials.find_all(body)
            + credentials.find_all(raw_query)
            + credentials.find_all(unquote_to_bytes(raw_query))
        )
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
            access.info("%s %s %s", scope.get("method"), _logged_path(scope), 400)
            return

        scope["state"]["body"] = body
        # A `+` in a query is a literal plus in this API (§2.2), but the query
        # parser underneath reads it as a space; encoding it keeps both the
        # parameters and the canonical query the same as the client meant.
        scope["state"]["raw_query"] = raw_query
        scope["query_string"] = raw_query.replace(b"+", b"%2B")
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        started = False

        status = 500

        async def tracking(message: Message) -> None:
            nonlocal started, status
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
            await send(message)

        if on_join_host:
            answer = join_host.route(scope, self.settings)
            if answer is not None:  # not the join: nothing else is served there (§1.1)
                await answer(scope, replay, tracking)
                access.info("%s %s %s", scope.get("method"), _logged_path(scope), status)
                return
        try:
            await self.app(scope, replay, tracking)
        except Exception:
            # Anything unexpected still answers in the envelope with every header
            # of §1.1; the message names no internals (§1.3).
            log.exception("unhandled error on %s %s", scope.get("method"), _logged_path(scope))
            if started:
                raise
            response = error_response(500, "internal", "an unexpected failure")
            await response(scope, receive, send)
        finally:
            access.info("%s %s %s", scope.get("method"), _logged_path(scope), status)

    def _revoke(self, found: list[credentials.Presented]) -> None:
        with events.transaction(self.engine) as conn:
            revoke_leaked(conn, found)


_TOKEN_PATHS = (
    re.compile(r"^(/join/)[^/]+"),
    re.compile(r"^(/j/)[^/]+"),
    re.compile(r"^(/api/v1/join/)[^/]+"),
    re.compile(r"^(/r/)[^/]+"),
    re.compile(r"^(/api/v1/runners/pair/)[^/]+"),
    re.compile(r"^(/api/v1/invitations/)[^/]+"),  # the invitation's token (§3.4)
    re.compile(r"^(/mail/(?:verify|unsubscribe|second-factor-reset)/)[^/]+"),  # §18.6
)


_FIRST_SEGMENT = re.compile(r"^(/)[^/]+")


def _logged_path(scope: Scope) -> str:
    """The path for the log: never a query string, join and pairing tokens as `…` (§1.1).
    On the join host any path not rewritten to the join may still carry its token
    (`HEAD /{token}`, `/{token}/`): its first segment is masked as well."""
    path = str(scope.get("path", ""))
    masked = path
    for pattern in _TOKEN_PATHS:
        masked = pattern.sub(r"\1…", masked)
    if masked == path and scope.get("state", {}).get("on_join_host"):
        masked = _FIRST_SEGMENT.sub(r"\1…", path)
    return masked


def _content_length(scope: Scope) -> int | None:
    for key, value in scope.get("headers", []):
        if key.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _unrouted(scope: Scope) -> bool:
    """An API path no route of this hub serves, whatever the method (a route with the
    path but not the method is routed: it answers 405). The dashboard's files, mounted
    at `/`, never answer for `/api/`."""
    path = str(scope.get("path", ""))
    router = getattr(scope.get("app"), "router", None)
    if not path.startswith("/api/") or router is None:
        return False
    # Where the router redirects a path that differs by its trailing slashes (307), as
    # Starlette does it (all of them stripped, or one added), that path is routed too.
    candidates = [path]
    if getattr(router, "redirect_slashes", False) and path != "/":
        candidates.append(path.rstrip("/") if path.endswith("/") else path + "/")
    for candidate in candidates:
        probe = {**scope, "path": candidate}
        for route in router.routes:
            if getattr(route, "name", None) != "web" and route.matches(probe)[0] != Match.NONE:
                return False
    return True


async def _not_found(scope: Scope, receive: Receive, send: Send) -> None:
    response = error_response(404, "not_found", "no such resource")
    await response(scope, receive, send)
    access.info("%s %s %s", scope.get("method"), _logged_path(scope), 404)


def _body_cap(scope: Scope) -> tuple[int, Callable[[Scope, Receive, Send], Awaitable[None]]]:
    """The largest body this request may send, and how a larger one is refused."""
    method, path = scope.get("method"), scope.get("path", "")
    if method == "PUT" and _IMAGE_UPLOAD.match(path):
        return IMAGE_CAP, _image_too_large
    if method == "POST" and _ATTACHMENT_UPLOAD.match(path):
        return ATTACHMENT_CAP, functools.partial(_too_large, cap=ATTACHMENT_CAP)
    if method == "PATCH" and path == _LANDING_SETTINGS:
        return LANDING_CAP, functools.partial(_too_large, cap=LANDING_CAP)
    return BODY_CAP, _too_large


async def _too_large(scope: Scope, receive: Receive, send: Send, cap: int = BODY_CAP) -> None:
    size = f"{cap // 1024 // 1024} MiB" if cap >= 1024 * 1024 else f"{cap // 1024} KiB"
    response = error_response(413, "payload_too_large", f"the body is over {size}")
    await response(scope, receive, send)
    access.info("%s %s %s", scope.get("method"), _logged_path(scope), 413)


async def _image_too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = error_response(
        400, "invalid", "the image is over 1 MiB", {"fields": {"body": "too_large"}}
    )
    await response(scope, receive, send)
    access.info("%s %s %s", scope.get("method"), _logged_path(scope), 400)


def _with_headers(send: Send, *, public: bool = False) -> Send:
    async def wrapped(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            given = message.get("headers", [])
            headers = [(k, v) for k, v in given if k.lower() not in _SET]
            content_type = next((v for k, v in given if k.lower() == b"content-type"), b"")
            # Every answer is no-store, except the caching a route may choose from
            # ROUTE_CACHE: the logo, banner and avatars, revalidated by ETag (§1.1, §11.2,
            # §6.10). Only a successful GET of the public badge, swarm page or landing page
            # may choose public caching (§6.20, §6.22, §16.7).
            chosen = next((v for k, v in given if k.lower() == b"cache-control"), None)
            public_cache = (
                public and message["status"] in (200, 304) and chosen == b"public, max-age=60"
            )
            cache = chosen if chosen in ROUTE_CACHE or public_cache else b"no-store"
            headers += [
                (b"maity-server-time", clock.rfc3339(clock.now(), millis=True).encode()),
                (b"cache-control", cache),
                (b"x-content-type-options", b"nosniff"),
            ]
            if content_type.startswith(b"text/html"):
                headers.append((b"content-security-policy", CSP.encode()))
            message["headers"] = headers
        await send(message)

    return wrapped


_SET = {b"maity-server-time", b"cache-control", b"x-content-type-options"}
