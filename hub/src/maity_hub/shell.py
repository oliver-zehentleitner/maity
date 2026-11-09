"""The app shell and the dashboard's files (docs/api.md §16.11).

Every path the hub does not answer itself is `index.html`, the shell; the dashboard's scripts,
stylesheets and brand files are served under `/assets/`. The shell names each of them with
`?v=<version>`, the digest of the body the hub sends, and a request carrying that version may be
cached for good (hub/context/serving.md). `shell_response` is also what `/` answers to a visitor
with a session or while the landing page is off (§16.7).
"""

from __future__ import annotations

import gzip
import hashlib
import json
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
from starlette.datastructures import Headers, QueryParams
from starlette.exceptions import HTTPException
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
# holds no data, and a deploy must reach a browser at once. Asked for under its version, the
# digest of the very body sent, it may be kept for good: a deploy changes the shell, and with it
# the version of every file that changed (hub/context/serving.md).
ASSET_CACHE = "no-cache"
ASSET_IMMUTABLE = "public, max-age=31536000, immutable"
# A version is this many hex digits of the body's SHA-256, as `/assets/landing/` writes it.
VERSION_DIGITS = 16
# `url(...)` in a stylesheet: quoted or not, as the dashboard's stylesheets write them.
_CSS_URL = re.compile(r"""url\(\s*(?P<q>["']?)(?P<ref>[^"')\s]+)(?P=q)\s*\)""")


@dataclass(frozen=True)
class AssetForm:
    """What a dashboard file is served as: the bytes read once (`data`; a stylesheet with its
    `url()`s carrying the versions in `refs`), their strong ETag and version and, for a
    compressible file of `compression.MINIMUM_SIZE` and more, their gzip form with an ETag of its
    own. Every answer is sent from these bytes, never from the file again, so an ETag and a
    version always name exactly the body that goes with them."""

    mtime_ns: int
    size: int
    media_type: str
    data: bytes
    etag: str
    version: str
    gzipped: bytes | None
    gzip_etag: str | None
    refs: tuple[tuple[str, str], ...] = ()


# A file's forms by its path, kept while its change time and size stay the same, and for a
# stylesheet while every file it names keeps its version.
_FORMS: dict[str, AssetForm] = {}


def _asset_path(root: str, full_path: str) -> str | None:
    """`full_path` as a path under `/assets/` (`css/fonts/x.woff2`), or None when it is not a
    dashboard file there: outside `root`, outside `ASSET_DIRS`, a dotfile, not a regular file."""
    relative = os.path.relpath(full_path, root)
    parts = relative.split(os.sep)
    if parts[0] in (os.curdir, os.pardir) or len(parts) < 2 or parts[0] not in ASSET_DIRS:
        return None
    if any(part.startswith(".") for part in parts) or not os.path.isfile(full_path):
        return None
    return "/".join(parts)


def _versioned_css(
    root: str, full_path: str, text: str
) -> tuple[bytes, tuple[tuple[str, str], ...]]:
    """A stylesheet with `?v=<version>` on every `url()` that names a dashboard file beside it
    (fonts, brand pictures): the stylesheet's own version then changes with theirs. Anything
    else (an absolute or `data:` address, a query, another stylesheet) stays as written."""
    refs: dict[str, str] = {}

    def versioned(found: re.Match[str]) -> str:
        ref = found["ref"]
        if ref.startswith("/") or ":" in ref or "?" in ref or "#" in ref or ref.endswith(".css"):
            return found[0]
        target = os.path.normpath(os.path.join(os.path.dirname(full_path), ref))
        if _asset_path(root, target) is None:
            return found[0]
        version = asset_form(target, os.stat(target), root).version
        refs[target] = version
        return f"url({found['q']}{ref}?v={version}{found['q']})"

    return _CSS_URL.sub(versioned, text).encode(), tuple(sorted(refs.items()))


def _refs_current(known: AssetForm, root: str) -> bool:
    for target, version in known.refs:
        try:
            if asset_form(target, os.stat(target), root).version != version:
                return False
        except OSError:
            return False
    return True


def asset_form(full_path: str, stat_result: os.stat_result, root: str) -> AssetForm:
    """The ETag comes from the file's content, not from its time and size as Starlette's: an
    image built with normalised file times could otherwise keep an old ETag for a changed file
    of the same size. Read once per file and process, again when its change time or size
    moves. The gzip form is made here too, at the middleware's level and with no time in its
    header, so the same content always gives the same bytes and the same ETag. The version is
    taken from the body as sent, so a stylesheet's from its versioned `url()`s."""
    known = _FORMS.get(full_path)
    if (
        known is not None
        and (known.mtime_ns, known.size) == (stat_result.st_mtime_ns, stat_result.st_size)
        and _refs_current(known, root)
    ):
        return known
    with open(full_path, "rb") as file:
        data = file.read()
    media_type = guess_type(full_path)[0] or "text/plain"
    refs: tuple[tuple[str, str], ...] = ()
    if media_type == "text/css":
        data, refs = _versioned_css(root, full_path, data.decode("utf-8"))
    digest = hashlib.sha256(data).hexdigest()
    gzipped = None
    if len(data) >= compression.MINIMUM_SIZE and not compression.already_compressed(media_type):
        gzipped = gzip.compress(data, compresslevel=compression.LEVEL, mtime=0)
    form = AssetForm(
        mtime_ns=stat_result.st_mtime_ns,
        size=stat_result.st_size,
        media_type=media_type,
        data=data,
        etag=f'"{digest[:32]}"',
        version=digest[:VERSION_DIGITS],
        gzipped=gzipped,
        gzip_etag=None if gzipped is None else f'"{digest[:32]}-gzip"',
        refs=refs,
    )
    _FORMS[full_path] = form
    return form


def asset_versions(web_dir: Path) -> dict[str, str]:
    """Every dashboard file's version by its path under `/assets/` (`js/app.js`). Each file is
    read once per process (`asset_form`); later calls only look at change times and sizes."""
    root = os.path.realpath(web_dir)
    found: dict[str, str] = {}
    for top in sorted(ASSET_DIRS):
        for here, dirs, files in os.walk(os.path.join(root, top)):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(files):
                full_path = os.path.join(here, name)
                path = _asset_path(root, full_path)
                if path is not None:
                    found[path] = asset_form(full_path, os.stat(full_path), root).version
    return found


# One range of bytes (`bytes=0-9`, `bytes=5-`, `bytes=-10`); any other `Range` gets the whole body.
# ASCII digits (RFC 9110 §14.1.2), at most 18, which no file here reaches: a longer number would
# make `int()` fail (its 4300-digit limit) and the answer a 500, not the whole body.
_RANGE = re.compile(r"bytes=([0-9]{0,18})-([0-9]{0,18})")


def byte_range(request: Headers, etag: str, size: int) -> tuple[int, int] | None:
    """The one range of the stored form a request asks for, first and last byte, or None for the
    whole body. There is no `Last-Modified`, so an `If-Range` is compared with the ETag alone: a
    date, a weak or another tag gets the whole body. A range that is not one satisfiable span
    is ignored, as RFC 9110 §14.2 lets a server do, and the whole body is sent."""
    asked = request.get("range")
    if not asked:
        return None
    if_range = request.get("if-range")
    if if_range is not None and (if_range.startswith("W/") or if_range != etag):
        return None
    found = _RANGE.fullmatch(asked.strip())
    if found is None or not (found[1] or found[2]):
        return None
    if found[1]:
        first = int(found[1])
        last = min(int(found[2]), size - 1) if found[2] else size - 1
    else:
        first, last = max(size - int(found[2]), 0), size - 1
    return (first, last) if first <= last else None


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

    @property
    def root(self) -> str:
        return os.path.realpath(os.fspath(self.directory or "."))

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        # Starlette runs this in a worker thread: the file is read, hashed and gzipped here,
        # not on the event loop.
        full_path, stat_result = super().lookup_path(path)
        if stat_result is not None and stat.S_ISREG(stat_result.st_mode):
            asset_form(full_path, stat_result, self.root)
        return full_path, stat_result

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        form = asset_form(os.fspath(full_path), stat_result, self.root)
        request = Headers(scope=scope)
        # For good only under the version of the body this hub sends: another version (a
        # shell from a pod with other files, a stale link) or none gets the current file,
        # revalidated (hub/context/serving.md).
        asked = QueryParams(scope.get("query_string", b"")).getlist("v")
        current = asked == [form.version]
        headers = {"Cache-Control": ASSET_IMMUTABLE if current else ASSET_CACHE}
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
            # The bytes the ETag and the version were taken from, never the file read again: a
            # file replaced meanwhile can not go out under them (review of #1543). No
            # Last-Modified, so `If-Modified-Since` never answers 304. A range is of these bytes.
            headers |= {"ETag": form.etag, "Accept-Ranges": "bytes"}
            span = byte_range(request, form.etag, len(form.data))
            body = form.data
            if span is not None and status_code == 200:
                first, last = span
                headers["Content-Range"] = f"bytes {first}-{last}/{len(form.data)}"
                body, status_code = form.data[first : last + 1], 206
            response = Response(
                body, status_code=status_code, media_type=form.media_type, headers=headers
            )
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


# A file of the dashboard the shell names (`src="js/app.js"`, `href="css/app.css"`).
_ASSET_REF = re.compile(rb'(\s(?:src|href)=")((?:brand|css|js|vendor)/[^"?#]+)(")')
_HEAD_END = re.compile(rb"</head>", re.IGNORECASE)
# The files a script asks for later, by a name it builds (an i18n catalog, Keep the Why's files, a
# brand picture): the shell lists their versions in a data block, `M.assetQuery` reads it.
LATER = ("brand/", "js/i18n/", "vendor/")
VERSIONS_ID = "maity-assets"


def versioned(page: bytes, web_dir: Path) -> bytes:
    """The shell with `?v=<version>` on every file of the dashboard it names, and the versions
    of the files a script loads later in `<script type="application/json" id="maity-assets">`,
    a data block that is never run, so the CSP stays as it is (§16.11). A name without a file
    stays as written."""
    versions = asset_versions(web_dir)

    def named(found: re.Match[bytes]) -> bytes:
        version = versions.get(found[2].decode("utf-8", "replace"))
        if version is None:
            return found[0]
        return found[1] + found[2] + b"?v=" + version.encode() + found[3]

    page = _ASSET_REF.sub(named, page)
    later = {path: version for path, version in versions.items() if path.startswith(LATER)}
    data = json.dumps(later, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")
    block = f'<script type="application/json" id="{VERSIONS_ID}">{data}</script>'.encode()
    closed = _HEAD_END.search(page)
    if closed is None:
        return page
    return page[: closed.start()] + block + page[closed.start() :]


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
        return page_in_shell(versioned(shell, self.web_dir), body)

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
        versioned(shell_document((web_dir / "index.html").read_bytes(), public_url), web_dir),
        media_type="text/html",
        headers=SHELL_HEADERS,
    )
