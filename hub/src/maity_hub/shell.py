"""The app shell and the dashboard's files (docs/api.md §16.11).

Every path the hub does not answer itself is `index.html`, the shell; the dashboard's scripts,
stylesheets and brand files are served under `/assets/`. `shell_response` is also what `/`
answers to a visitor with a session or while the landing page is off (§16.7).
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.routing import BaseRoute, Match
from starlette.types import Receive, Scope, Send

from maity_hub import paths
from maity_hub.errors import error_response

# The built files the dashboard names under `/assets/` (§16.11): web/'s three directories of
# scripts, stylesheets and brand files. Everything else in web/ (the page itself, fixtures,
# tools, the README, context/) is not served as a file.
ASSET_DIRS = frozenset({"brand", "css", "js"})
SHELL_HEADERS = {
    "Cache-Control": "no-cache",  # small, and it must follow a deploy at once (§16.11)
    "X-Robots-Tag": "noindex",
}


class AssetFiles(StaticFiles):
    """The files under `/assets/`: scripts, stylesheets and brand files, no dotfiles."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        # `path` is normalised; the root arrives as ".".
        parts = [part for part in path.replace("\\", "/").split("/") if part != "."]
        if len(parts) < 2 or parts[0] not in ASSET_DIRS or any(p.startswith(".") for p in parts):
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


BASE = b'<base href="/assets/">'
_HEAD = re.compile(rb"<head(?:\s[^>]*)?>", re.IGNORECASE)


def shell_document(page: bytes) -> bytes:
    """`index.html` with `<base href="/assets/">` right after `<head>`: the file names its
    scripts, stylesheets and brand files relative to itself, so that it also opens from
    `file://` in fixture mode; served at any depth of a path, the base makes them load
    from `/assets/` (§16.11 leaves a `<base>` to the dashboard)."""
    opened = _HEAD.search(page)
    if opened is None:
        return page
    return page[: opened.end()] + BASE + page[opened.end() :]


class ShellRoute(BaseRoute):
    """The app shell for every path the hub does not answer itself (§16.11).

    A route of its own, matching last, so that a wrong method on a hub path is still the
    router's `405` and an unknown hub path is `not_found`, not the shell. Any method but
    `GET` and `HEAD` on a path that is the shell's is `not_found`.
    """

    def __init__(self, web_dir: Path) -> None:
        self.web_dir = web_dir
        self.name = "shell"

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] != "http" or paths.is_hub_path(scope.get("path", "")):
            return Match.NONE, {}
        return Match.FULL, {}

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        response: Response
        if scope["method"] in ("GET", "HEAD"):
            response = shell_response(self.web_dir)
        else:
            response = error_response(404, "not_found", "no such resource")
        await response(scope, receive, send)


def shell_response(web_dir: Path) -> Response:
    """`index.html` as the shell: `200`, `no-cache`, `noindex` (§16.11)."""
    return Response(
        shell_document((web_dir / "index.html").read_bytes()),
        media_type="text/html",
        headers=SHELL_HEADERS,
    )
