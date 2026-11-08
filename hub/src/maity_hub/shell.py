"""The app shell and the dashboard's files (docs/api.md §16.11).

Every path the hub does not answer itself is `index.html`, the shell; the dashboard's scripts,
stylesheets and brand files are served under `/assets/`. `shell_response` is also what `/`
answers to a visitor with a session or while the landing page is off (§16.7).
"""

from __future__ import annotations

import gzip
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from html import escape
from mimetypes import guess_type
from pathlib import Path

from fastapi import Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse
from starlette.routing import BaseRoute, Match
from starlette.staticfiles import NotModifiedResponse
from starlette.types import Receive, Scope, Send

from maity_hub import compression, paths, public_pages
from maity_hub.errors import error_response

# The built files the dashboard names under `/assets/` (§16.11): web/'s directories of
# scripts, stylesheets and brand files, and the vendored libraries (web/vendor/). Everything
# else in web/ (the page itself, fixtures, tools, the README, context/) is not served as a file.
ASSET_DIRS = frozenset({"brand", "css", "js", "vendor"})
SHELL_HEADERS = {
    "Cache-Control": "no-cache",  # small, and it must follow a deploy at once (§16.11)
    "X-Robots-Tag": "noindex",
    "Vary": "Cookie",  # the same address is a page for a visitor and the shell for a member (§16.9)
}


# A dashboard file is revalidated on every use (docs/api.md §1, §16.11; req-s246xb6k1mpp): it
# holds no data, and a deploy must reach a browser at once.
ASSET_CACHE = "no-cache"


@dataclass(frozen=True)
class AssetForm:
    """What a dashboard file is served as: its content's strong ETag and, for a compressible
    file of `compression.MINIMUM_SIZE` and more, its gzip form with an ETag of its own."""

    mtime_ns: int
    size: int
    media_type: str
    etag: str
    gzipped: bytes | None
    gzip_etag: str | None


# A file's forms by its path, kept while its change time and size stay the same.
_FORMS: dict[str, AssetForm] = {}


def asset_form(full_path: str, stat_result: os.stat_result) -> AssetForm:
    """The ETag comes from the file's content, not from its time and size as Starlette's: an
    image built with normalised file times could otherwise keep an old ETag for a changed file
    of the same size. Read once per file and process, again when its change time or size
    moves. The gzip form is made here too, at the middleware's level and with no time in its
    header, so the same content always gives the same bytes and the same ETag."""
    known = _FORMS.get(full_path)
    if known is not None and (known.mtime_ns, known.size) == (
        stat_result.st_mtime_ns,
        stat_result.st_size,
    ):
        return known
    with open(full_path, "rb") as file:
        data = file.read()
    digest = hashlib.sha256(data).hexdigest()[:32]
    media_type = guess_type(full_path)[0] or "text/plain"
    gzipped = None
    if len(data) >= compression.MINIMUM_SIZE and not compression.already_compressed(media_type):
        gzipped = gzip.compress(data, compresslevel=compression.LEVEL, mtime=0)
    form = AssetForm(
        mtime_ns=stat_result.st_mtime_ns,
        size=stat_result.st_size,
        media_type=media_type,
        etag=f'"{digest}"',
        gzipped=gzipped,
        gzip_etag=None if gzipped is None else f'"{digest}-gzip"',
    )
    _FORMS[full_path] = form
    return form


class AssetFileResponse(FileResponse):
    """A dashboard file as it is stored. It has no `Last-Modified`, so an `If-Range` is
    compared with the ETag alone, and a date never selects a range."""

    def _should_use_range(self, http_if_range: str) -> bool:
        return not http_if_range.startswith("W/") and http_if_range == self.headers["etag"]


class AssetFiles(StaticFiles):
    """The files under `/assets/`: scripts, stylesheets and brand files, no dotfiles; each
    answered `no-cache` with a strong ETag of its content, per encoding, and `304` when
    `If-None-Match` names it."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        # `path` is normalised; the root arrives as ".".
        parts = [part for part in path.replace("\\", "/").split("/") if part != "."]
        if len(parts) < 2 or parts[0] not in ASSET_DIRS or any(p.startswith(".") for p in parts):
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        # Starlette runs this in a worker thread: the file is read, hashed and gzipped here,
        # not on the event loop.
        full_path, stat_result = super().lookup_path(path)
        if stat_result is not None and stat.S_ISREG(stat_result.st_mode):
            asset_form(full_path, stat_result)
        return full_path, stat_result

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        form = asset_form(os.fspath(full_path), stat_result)
        request = Headers(scope=scope)
        headers = {"Cache-Control": ASSET_CACHE}
        response: Response
        if form.gzipped is not None:
            # Which form is sent depends on Accept-Encoding: every answer says so, a 304 too.
            headers["Vary"] = "Accept-Encoding"
        if (
            form.gzipped is not None
            and form.gzip_etag is not None
            and compression.accepts_gzip(request.get("accept-encoding", ""))
        ):
            headers |= {"ETag": form.gzip_etag, "Content-Encoding": "gzip"}
            response = Response(
                form.gzipped, status_code=status_code, media_type=form.media_type, headers=headers
            )
        else:
            headers["ETag"] = form.etag
            response = AssetFileResponse(
                full_path, status_code=status_code, stat_result=stat_result, headers=headers
            )
            # Only the content decides: no Last-Modified, so `If-Modified-Since` never answers
            # 304 and a date `If-Range` never selects a range.
            del response.headers["last-modified"]
        if self.is_not_modified(response.headers, request):
            return NotModifiedResponse(response.headers)
        return response


# The dashboard's invitation page, `/invite/{token}` (§16.11): the token is in its path.
INVITE = "/invite/"
BASE = b'<base href="/assets/">'
_HEAD = re.compile(rb"<head(?:\s[^>]*)?>", re.IGNORECASE)
_SOCIAL_IMAGE = re.compile(rb'(property="og:image" content=")(brand/[^"]+")')


def shell_document(page: bytes, public_url: str) -> bytes:
    """`index.html` with `<base href="/assets/">` right after `<head>`: the file names its
    scripts, stylesheets and brand files relative to itself, so that it also opens from
    `file://` in fixture mode; served at any depth of a path, the base makes them load
    from `/assets/` (§16.11 leaves a `<base>` to the dashboard). A crawler reads no `<base>`
    and needs a whole address, which only the hub knows, so the social image gets one."""
    assets = escape(public_url.rstrip("/"), quote=True).encode() + b"/assets/"
    page = _SOCIAL_IMAGE.sub(lambda found: found[1] + assets + found[2], page)
    opened = _HEAD.search(page)
    if opened is None:
        return page
    return page[: opened.end()] + BASE + page[opened.end() :]


_PAGE = re.compile(
    r"<title>(?P<title>.*?)</title>(?P<meta><meta name=\"description\"[^>]*>)?"
    r"(?P<canonical><link rel=\"canonical\"[^>]*>)(?P<robots><meta name=\"robots\"[^>]*>)?.*"
    r"<main class=\"wrap\">(?P<main>.*)</main></body>",
    re.DOTALL,
)
_SHELL_TITLE = re.compile(rb"<title>.*?</title>", re.DOTALL)
_SHELL_DESCRIPTION = re.compile(rb'<meta name="description"[^>]*>')
_SHELL_MAIN = re.compile(rb'<main id="main">.*?</main>', re.DOTALL)
_SHELL_OG_TITLE = re.compile(rb'<meta property="og:title"[^>]*>')
_SHELL_OG_DESCRIPTION = re.compile(rb'<meta property="og:description"[^>]*>')
_CONTENT = re.compile(r'content="([^"]*)"')


def page_in_shell(shell: bytes, body: str) -> bytes | None:
    """The shell carrying a stored page: its title, description and canonical link in the head,
    its text in `<main>`, for a crawler and until the dashboard draws the view. None when
    either document is not of the shape expected: the caller serves the bare page."""
    found = _PAGE.search(body)
    if found is None or not (_SHELL_TITLE.search(shell) and _SHELL_MAIN.search(shell)):
        return None
    title = f"<title>{found['title']}</title>".encode()
    head = found["canonical"].encode() + (found["robots"] or "").encode()  # `noindex` stays
    described = found["meta"].encode() if found["meta"] else b""
    done = _SHELL_DESCRIPTION.sub(lambda _: described, shell, count=1)
    # A shared link shows the page's name and text, already escaped in the stored document.
    og_title = f'<meta property="og:title" content="{found["title"]}">'.encode()
    done = _SHELL_OG_TITLE.sub(lambda _: og_title, done, count=1)
    words = _CONTENT.search(found["meta"] or "")
    og_text = f'<meta property="og:description" content="{words[1]}">'.encode() if words else b""
    done = _SHELL_OG_DESCRIPTION.sub(lambda _: og_text, done, count=1)
    done = _SHELL_TITLE.sub(lambda _: title + head, done, count=1)
    inner = found["main"].encode()
    return _SHELL_MAIN.sub(
        lambda _: b'<main id="main" data-public-page>' + inner + b"</main>", done, count=1
    )


class ShellRoute(BaseRoute):
    """The app shell for every path the hub does not answer itself (§16.11).

    A route of its own, matching last, so that a wrong method on a hub path is still the
    router's `405` and an unknown hub path is `not_found`, not the shell. Any method but
    `GET` and `HEAD` on a path that is the shell's is `not_found`.
    """

    def __init__(self, web_dir: Path, public_url: str) -> None:
        self.web_dir = web_dir
        self.public_url = public_url
        self.name = "shell"

    def _inside_shell(self, body: str) -> bytes | None:
        shell = shell_document((self.web_dir / "index.html").read_bytes(), self.public_url)
        return page_in_shell(shell, body)

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] != "http" or paths.is_hub_path(scope.get("path", "")):
            return Match.NONE, {}
        return Match.FULL, {}

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        response: Response | None
        if scope["method"] in ("GET", "HEAD"):
            # A stored public page first, for a visitor, while the instance serves pages (§16.9).
            response = await run_in_threadpool(
                public_pages.answer, Request(scope, receive), self._inside_shell
            )
            if response is None:
                response = shell_response(self.web_dir, self.public_url)
            if scope.get("path", "").startswith(INVITE):
                # The invitation's token is in the path: from the shell's first request on,
                # nothing sends it on in a `Referer` (§16.13), maintenance window or not.
                response.headers["Referrer-Policy"] = "no-referrer"
        else:
            response = error_response(404, "not_found", "no such resource")
        await response(scope, receive, send)


def shell_response(web_dir: Path, public_url: str) -> Response:
    """`index.html` as the shell: `200`, `no-cache`, `noindex` (§16.11)."""
    return Response(
        shell_document((web_dir / "index.html").read_bytes(), public_url),
        media_type="text/html",
        headers=SHELL_HEADERS,
    )
