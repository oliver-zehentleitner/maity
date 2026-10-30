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

from fastapi import APIRouter, Request
from fastapi.responses import Response

from maity_hub import landing, legal
from maity_hub.deps import engine_of, settings_of
from maity_hub.errors import not_found

router = APIRouter()

CACHE = {"Cache-Control": "public, max-age=3600"}


def _set_pages(pages: dict[str, Any]) -> list[tuple[str, str]]:
    """The legal pages that are set as `(address, version)`, in the order of §16.7.1."""
    return [
        (f"/{legal.ADDRESS[page]}", one["version"])
        for page, one in pages.items()
        if one is not None
    ]


def robots(public_url: str, enabled: bool, pages: dict[str, Any]) -> str:
    if not enabled:
        return "User-agent: *\nAllow: /$\nDisallow: /\n"
    allowed = "Allow: /$\n" + "".join(f"Allow: {a}$\n" for a, _ in _set_pages(pages))
    return f"User-agent: *\n{allowed}Disallow: /\n\nSitemap: {public_url.rstrip('/')}/sitemap.xml\n"


def sitemap(
    public_url: str, root_updated_at: str | None, enabled: bool, pages: dict[str, Any]
) -> str | None:
    base = public_url.rstrip("/")
    urls = []
    if enabled:
        lastmod = f"\n    <lastmod>{root_updated_at}</lastmod>" if root_updated_at else ""
        urls.append(f"  <url>\n    <loc>{base}/</loc>{lastmod}\n  </url>\n")
    for address, version in _set_pages(pages):
        urls.append(
            f"  <url>\n    <loc>{base}{address}</loc>\n    <lastmod>{version}</lastmod>\n  </url>\n"
        )
    if not urls:
        return None
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(urls)
        + "</urlset>\n"
    )


@router.get("/robots.txt", include_in_schema=False)
def get_robots(request: Request) -> Response:
    with engine_of(request).begin() as conn:
        enabled = bool(landing.stored(conn)["enabled"])
        pages = legal.stored(conn)["pages"]
    text = robots(settings_of(request).public_url, enabled, pages)
    return Response(text, media_type="text/plain; charset=utf-8", headers=CACHE)


@router.get("/sitemap.xml", include_in_schema=False)
def get_sitemap(request: Request) -> Response:
    with engine_of(request).begin() as conn:
        value = landing.stored(conn)
        pages = legal.stored(conn)["pages"]
    text = sitemap(
        settings_of(request).public_url, value["updated_at"], bool(value["enabled"]), pages
    )
    if text is None:
        raise not_found()
    return Response(text, media_type="application/xml; charset=utf-8", headers=CACHE)
