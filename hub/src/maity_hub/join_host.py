"""The optional join host (docs/api.md §1.1): the same hub under a second hostname,
answering the agent join and nothing else.

`GET /{token}` is the join page and `POST /{token}` the exchange; both are routed to
the public routes by rewriting the path, never by a redirect, so the CLI and the
curl recipe work without following one. A token-shaped path is always the join. Any
other `GET` is a `302` to the public start page, any other method `not_found`. The
host carries no session: cookies and an `Authorization` header are dropped before a
route sees them.
"""

from __future__ import annotations

import re
from typing import Any

from starlette.responses import RedirectResponse, Response
from starlette.types import Scope

from maity_hub.config import Settings
from maity_hub.errors import error_response

# One segment in the join token's alphabet and length (`secrets.token_urlsafe(16)`, §3.1).
TOKEN_PATH = re.compile(r"^/([A-Za-z0-9_-]{22})\Z")
_DROPPED = {b"cookie", b"authorization"}


def hostname(host: str) -> str:
    """The name in a `Host` header: lower case, without the port and trailing dots."""
    host = host.strip().lower()
    if host.startswith("["):
        name = host[: host.find("]") + 1] if "]" in host else host
    else:
        name = host.partition(":")[0]
    return name.rstrip(".")


def requested_host(scope: Scope) -> str:
    """The hostname the `Host` header names; `X-Forwarded-Host` is not read."""
    for name, value in scope.get("headers", []):
        if name == b"host":
            return hostname(value.decode("latin-1"))
    return ""


def is_join_host(scope: Scope, settings: Settings) -> bool:
    """Matched on the hostname alone, so `join.example.`, `:80` or `:0443` are the
    join host too: a variant never reaches the public app (fails closed). The public
    URL names another hostname (`parse_join_url`)."""
    return settings.join_host is not None and requested_host(scope) == settings.join_host


def route(scope: Scope, settings: Settings) -> Response | None:
    """Rewrite `scope` to the public route of the join, or the answer for anything
    else on the join host."""
    match = TOKEN_PATH.match(scope.get("path", ""))
    method = scope.get("method")
    if match and method in ("GET", "POST"):
        token = match.group(1)
        path = f"/join/{token}" if method == "GET" else f"/api/v1/join/{token}"
        scope["path"] = path
        scope["raw_path"] = path.encode("ascii")
        scope["headers"] = [(k, v) for k, v in scope.get("headers", []) if k not in _DROPPED]
        state: dict[str, Any] = scope.setdefault("state", {})
        state["join_host"] = True
        return None
    if method == "GET":
        return RedirectResponse(f"{settings.public_url}/", status_code=302)
    return error_response(404, "not_found", "no such resource")
