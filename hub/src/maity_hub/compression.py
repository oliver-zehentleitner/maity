"""Responses gzipped where the client asks for it (hub/context/serving.md).

Reads of the API and the dashboard's files (`/api/v1/`, `/assets/`) of 1024 bytes and more, at
level 6: the board's pages of cards are about four times smaller on the wire. Starlette
compresses a body of 128 KiB and more in a worker thread, so the event loop keeps answering
meanwhile. Left as they are: every write, where the hub hands out a credential, a join line
or a code; everything under `/api/v1/auth/`, the session with its CSRF token among it; and
every page outside these two prefixes (the shell, a join or link page, a public page), so
that no answer carries a secret compressed together with what the request sent. An
attachment's bytes go as they are stored, with their length: a file someone sent, often
compressed already, streamed against its digest.
"""

from __future__ import annotations

import re

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from maity_hub import API_VERSION

MINIMUM_SIZE = 1024
LEVEL = 6
READS = frozenset({"GET", "HEAD"})
COMPRESSED = (f"/api/{API_VERSION}/", "/assets/")
UNCOMPRESSED = (f"/api/{API_VERSION}/auth/",)
ATTACHMENT_BYTES = re.compile(r"/attachments/[^/]+/content$")


def compressed(method: str, path: str) -> bool:
    return (
        method in READS
        and path.startswith(COMPRESSED)
        and not path.startswith(UNCOMPRESSED)
        and not ATTACHMENT_BYTES.search(path)
    )


class Compression:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=MINIMUM_SIZE, compresslevel=LEVEL)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and compressed(str(scope.get("method")), str(scope.get("path"))):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)
