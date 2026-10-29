"""`GET /robots.txt` and `GET /sitemap.xml` (docs/api.md §16.7, Search engines).

Two plain files at the root, outside `/api/v1`, without a session and without a cookie,
answered for the public host only (the join host answers `not_found`, `join_host`). What
they say follows the landing page: while it is enabled a crawler may read the root and the
files the page is drawn from, and the sitemap lists the root; while it is not, a crawler is
asked to fetch nothing but the root, and the root answers `noindex` (the middleware).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from maity_hub import landing
from maity_hub.deps import engine_of, settings_of
from maity_hub.errors import not_found

router = APIRouter()

CACHE = {"Cache-Control": "public, max-age=3600"}
# What a crawler that renders the landing page must be allowed to fetch (§16.7).
ALLOWED = (
    "/$",
    "/assets/",
    "/api/v1/auth/session$",
    "/api/v1/openapi.json$",
    "/api/v1/landing$",
)


def robots(public_url: str, enabled: bool) -> str:
    if not enabled:
        return "User-agent: *\nAllow: /$\nDisallow: /\n"
    allowed = "".join(f"Allow: {path}\n" for path in ALLOWED)
    return f"User-agent: *\n{allowed}Disallow: /\n\nSitemap: {public_url.rstrip('/')}/sitemap.xml\n"


def sitemap(public_url: str, updated_at: str | None) -> str:
    lastmod = f"\n    <lastmod>{updated_at}</lastmod>" if updated_at else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url>\n    <loc>{public_url.rstrip('/')}/</loc>{lastmod}\n  </url>\n"
        "</urlset>\n"
    )


@router.get("/robots.txt", include_in_schema=False)
def get_robots(request: Request) -> Response:
    with engine_of(request).begin() as conn:
        enabled = bool(landing.stored(conn)["enabled"])
    text = robots(settings_of(request).public_url, enabled)
    return Response(text, media_type="text/plain; charset=utf-8", headers=CACHE)


@router.get("/sitemap.xml", include_in_schema=False)
def get_sitemap(request: Request) -> Response:
    with engine_of(request).begin() as conn:
        value = landing.stored(conn)
    if not value["enabled"]:
        raise not_found()
    text = sitemap(settings_of(request).public_url, value["updated_at"])
    return Response(text, media_type="application/xml; charset=utf-8", headers=CACHE)
