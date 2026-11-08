"""Responses gzipped where the client asks for it (hub/context/serving.md).

Reads of the API and the dashboard's files (`/api/v1/`, `/assets/`) of 1024 bytes and more, at
level 6 (the dashboard's own files under `/assets/` by `shell.AssetFiles`, with an ETag per
encoding; everything else here): the board's pages of cards are about four times smaller on the
wire. Starlette compresses a body of 128 KiB and more in a worker thread, so the event loop
keeps answering meanwhile. Left as they are: every write, where the hub hands out a credential,
a join line or a code; everything under `/api/v1/auth/`, the session with its CSRF token among
it; the join and invitation documents a token opens (`/api/v1/join/{token}`,
`/api/v1/invitations/{token}`), which carry it; and every page outside these two prefixes (the
shell, a join or link page, a public page), so that no answer carries a secret compressed
together with what the request sent. An attachment's bytes go as they are stored, with their
length: a file someone sent, often compressed already, streamed against its digest.
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
UNCOMPRESSED = (
    f"/api/{API_VERSION}/auth/",
    f"/api/{API_VERSION}/join/",
    f"/api/{API_VERSION}/invitations/",
)
# The dashboard's own files (`shell.ASSET_DIRS`): `shell.AssetFiles` gzips them itself, so each
# encoding carries its own strong ETag and a `304` its `Vary` (hub/context/serving.md c6768529).
OWN_ENCODING = ("/assets/brand/", "/assets/css/", "/assets/js/", "/assets/vendor/")
# Named here rather than taken from Starlette's default, which older releases kept shorter.
ALREADY_COMPRESSED = (
    "application/gzip",
    "application/x-gzip",
    "application/zip",
    "application/grpc",
    "audio/*",
    "font/woff",
    "font/woff2",
    "image/avif",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/event-stream",
    "video/*",
)
ATTACHMENT_BYTES = re.compile(r"/attachments/[^/]+/content$")


def compressed(method: str, path: str) -> bool:
    return (
        method in READS
        and path.startswith(COMPRESSED)
        and not path.startswith(UNCOMPRESSED)
        and not path.startswith(OWN_ENCODING)
        and not ATTACHMENT_BYTES.search(path)
    )


def already_compressed(media_type: str) -> bool:
    """Whether a type is on `ALREADY_COMPRESSED`, as Starlette's middleware tells it."""
    media_type = media_type.partition(";")[0].strip().lower()
    return not {media_type, media_type.partition("/")[0] + "/*"}.isdisjoint(ALREADY_COMPRESSED)


# A weight as RFC 9110 §12.4.2 writes it: 0 to 1, at most three decimals.
_QVALUE = re.compile(r"0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?")  # DIGIT is ASCII (RFC 5234)


def accepts_gzip(accept_encoding: str) -> bool:
    """Whether `Accept-Encoding` takes gzip (RFC 9110 §12.5.3): an entry for `gzip` decides
    wherever it stands, `*` only when gzip is not named; a weight above 0 accepts. A weight
    outside the grammar (`q=2`, `q=inf`, `q=x`) accepts nothing."""
    named: float | None = None
    wildcard: float | None = None
    for part in accept_encoding.split(","):
        name, *params = (piece.strip() for piece in part.split(";"))
        coding = name.lower()
        if coding not in ("gzip", "*"):
            continue
        weight = 1.0
        for param in params:
            key, _, value = param.partition("=")
            if key.strip().lower() == "q":
                value = value.strip()
                # An invalid weight counts as 0: the entry refuses, it never accepts.
                weight = float(value) if _QVALUE.fullmatch(value) else 0.0
        if coding == "gzip":
            named = weight if named is None else max(named, weight)
        else:
            wildcard = weight if wildcard is None else max(wildcard, weight)
    chosen = named if named is not None else wildcard
    return chosen is not None and chosen > 0


class Compression:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.gzip = GZipMiddleware(
            app,
            minimum_size=MINIMUM_SIZE,
            compresslevel=LEVEL,
            exclude_content_types=ALREADY_COMPRESSED,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and compressed(str(scope.get("method")), str(scope.get("path"))):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)
