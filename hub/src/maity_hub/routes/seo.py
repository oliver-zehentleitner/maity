"""`GET /robots.txt` and `GET /sitemap.xml` (docs/api.md §16.7, Search engines).

Two plain files at the root, outside `/api/v1`, without a session and without a cookie,
answered for the public host only (the join host answers `not_found`, `join_host`). What
they say follows the landing page and the legal pages: while the landing page is enabled a
crawler may read the root and the legal pages that are set (the hub renders them itself, so
it needs none of the dashboard's files); while it is not, a crawler is asked to fetch nothing
but the root, and the root answers `noindex` (the app shell says so itself, §16.11).
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import Connection, select

from maity_hub import landing, legal, paths
from maity_hub import tables as t
from maity_hub.deps import engine_of, settings_of
from maity_hub.errors import not_found
from maity_hub.views import ts

router = APIRouter()

CACHE = {"Cache-Control": "public, max-age=3600"}


def _set_pages(pages: dict[str, Any]) -> list[tuple[str, str]]:
    """The legal pages that are set as `(address, version)`, in the order of §16.7.1."""
    return [
        (f"/{legal.ADDRESS[page]}", one["version"])
        for page, one in pages.items()
        if one is not None
    ]


MAX_URLS = 50_000  # a sitemap file holds at most 50,000 URLs and 50 MB (§16.9)
MAX_BYTES = 50 * 1024 * 1024
NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


def robots(
    public_url: str,
    enabled: bool,
    pages: dict[str, Any],
    public_pages: bool = False,
    has_urls: bool = True,
) -> str:
    """The `Sitemap:` line is there whenever the sitemap lists at least one URL, and only
    then (§16.7)."""
    sitemap_line = f"\nSitemap: {public_url.rstrip('/')}/sitemap.xml\n" if has_urls else ""
    if public_pages:
        # Every path but the reserved first segments (§16.9, §16.11); the legal pages stay
        # open. `/word/` and `/word` itself, so that a handle `word-x` is not caught.
        closed = sorted((paths.RESERVED_FIRST | paths.HUB_FIRST) - set(legal.ADDRESS.values()))
        return (
            "User-agent: *\n"
            + "".join(f"Disallow: /{first}/\nDisallow: /{first}$\n" for first in closed)
            + sitemap_line
        )
    if not enabled:
        return "User-agent: *\nAllow: /$\nDisallow: /\n"
    allowed = "Allow: /$\n" + "".join(f"Allow: {a}$\n" for a, _ in _set_pages(pages))
    return f"User-agent: *\n{allowed}Disallow: /\n{sitemap_line}"


def _url(base: str, address: str, lastmod: str | None) -> str:
    stamp = f"\n    <lastmod>{escape(lastmod)}</lastmod>" if lastmod else ""
    return f"  <url>\n    <loc>{escape(base + address)}</loc>{stamp}\n  </url>\n"


def urls(
    conn: Connection,
    public_url: str,
    root_updated_at: str | None,
    enabled: bool,
    pages: dict[str, Any],
    public_pages: bool,
) -> list[str]:
    """Every entry of the sitemap: the root and the legal pages as before, then every public
    page at its canonical address with the `lastmod` of its inputs (§16.9)."""
    base = public_url.rstrip("/")
    found = [_url(base, "/", root_updated_at)] if enabled else []
    found += [_url(base, address, version) for address, version in _set_pages(pages)]
    if public_pages:
        for row in conn.execute(
            select(t.public_page.c.path, t.public_page.c.lastmod).order_by(t.public_page.c.path)
        ):
            found.append(_url(base, row.path, ts(row.lastmod)))
    return found


def chunks(entries: list[str]) -> list[list[str]]:
    """The entries in files of at most `MAX_URLS` and `MAX_BYTES`."""
    wrapper = len(urlset([]).encode())  # the file's own `<urlset>` counts against the limit
    files: list[list[str]] = [[]]
    size = wrapper
    for entry in entries:
        weight = len(entry.encode())
        if files[-1] and (len(files[-1]) >= MAX_URLS or size + weight > MAX_BYTES):
            files.append([])
            size = wrapper
        files[-1].append(entry)
        size += weight
    return files if entries else []


def urlset(entries: list[str]) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="{NAMESPACE}">\n'
        + "".join(entries)
        + "</urlset>\n"
    )


def index(public_url: str, count: int) -> str:
    base = public_url.rstrip("/")
    parts = "".join(
        f"  <sitemap>\n    <loc>{base}/sitemap-{n}.xml</loc>\n  </sitemap>\n"
        for n in range(1, count + 1)
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="{NAMESPACE}">\n'
        + parts
        + "</sitemapindex>\n"
    )


def _entries(request: Request) -> tuple[list[list[str]], str]:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        value = landing.stored(conn)
        pages = legal.stored(conn)["pages"]
        entries = urls(
            conn,
            hub.public_url,
            value["updated_at"],
            bool(value["enabled"]),
            pages,
            hub.public_pages,
        )
    return chunks(entries), hub.public_url


@router.get("/robots.txt", include_in_schema=False)
def get_robots(request: Request) -> Response:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        value = landing.stored(conn)
        enabled = bool(value["enabled"])
        pages = legal.stored(conn)["pages"]
        found = urls(conn, hub.public_url, value["updated_at"], enabled, pages, hub.public_pages)
    text = robots(hub.public_url, enabled, pages, hub.public_pages, bool(found))
    return Response(text, media_type="text/plain; charset=utf-8", headers=CACHE)


@router.get("/sitemap.xml", include_in_schema=False)
def get_sitemap(request: Request) -> Response:
    files, public_url = _entries(request)
    if not files:
        raise not_found()
    text = urlset(files[0]) if len(files) == 1 else index(public_url, len(files))
    return Response(text, media_type="application/xml; charset=utf-8", headers=CACHE)


@router.get("/sitemap-{part}.xml", include_in_schema=False)
def get_sitemap_part(part: str, request: Request) -> Response:
    """One part of a sitemap that is an index (§16.9); a hub whose sitemap is one file has none,
    and what is no number is `not_found` like any other unknown part."""
    files, _ = _entries(request)
    if (
        not (part.isascii() and part.isdigit())
        or not len(files) >= 2
        or not 1 <= int(part) <= len(files)
    ):
        raise not_found()
    return Response(
        urlset(files[int(part) - 1]), media_type="application/xml; charset=utf-8", headers=CACHE
    )
