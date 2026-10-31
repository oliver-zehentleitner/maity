"""The pages the hub renders itself, outside the API (docs/api.md §16.7, §16.7.1): the
landing page at `/` for a visitor without a session while it is enabled, and the legal pages
at `/impressum`, `/privacy` and `/terms` with their earlier versions at `/<page>/<version>`.

The landing page loads the hub's own first-party files (`landing_files`, §16.7) and answers
with a Content-Security-Policy that allows exactly those; the legal pages carry no script.
They are the public host's only (the join host never routes here, §1.1).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import Connection, select

from maity_hub import landing, landing_stats, legal, render
from maity_hub import tables as t
from maity_hub.auth import caller as auth_caller
from maity_hub.deps import engine_of, settings_of
from maity_hub.errors import not_found
from maity_hub.shell import shell_response

page_router = APIRouter()

LANDING_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; "
    "font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
LEGAL_CSP = "default-src 'none'; style-src 'unsafe-inline'"
PUBLIC = "public, max-age=60"


def landing_html(
    conn: Connection, request: Request, setting: dict[str, Any], *, lang: str | None
) -> str:
    """The landing page of the saved setting, for the language the visitor asked for."""
    pages = setting["pages"]
    chosen = render.choose_language(
        list(pages), setting["default_language"], lang, request.headers.get("accept-language")
    )
    stats = landing_stats.current(conn) if landing_stats.named(setting) else None
    return render.landing_document(
        setting,
        chosen,
        public_url=settings_of(request).public_url,
        legal=legal.public(legal.stored(conn)),
        stats=stats,
    )


@page_router.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def root(
    request: Request,
    lang: str | None = None,
    as_: str | None = Query(None, alias="as"),
) -> Response:
    """The landing page for a visitor without a valid session, or for anyone who asks to see
    it as one (`?as=public`), while it is enabled; the app shell otherwise (§16.7)."""
    settings = settings_of(request)
    with engine_of(request).begin() as conn:
        setting = landing.stored(conn)
        visitor = as_ == "public" or not auth_caller.has_live_session(conn, request.cookies)
        if setting["enabled"] and visitor:
            body = landing_html(conn, request, setting, lang=lang)
            return HTMLResponse(
                body,
                headers={
                    "Cache-Control": PUBLIC,
                    "Vary": "Cookie, Accept-Language",
                    "Content-Security-Policy": LANDING_CSP,
                },
            )
    if settings.web_dir is None or not (settings.web_dir / "index.html").is_file():
        raise not_found()  # a hub without a dashboard serves the API alone
    return shell_response(settings.web_dir)


def legal_html(
    conn: Connection,
    request: Request,
    page: str,
    version: str | None,
    lang: str | None,
) -> str:
    """One legal page: the served version, or an earlier one by its version."""
    setting = legal.stored(conn)
    served = setting["pages"][page]
    if version is None:
        if served is None:
            raise not_found()
        version = served["version"]
    row = conn.execute(
        select(t.legal_version).where(
            t.legal_version.c.page == page, t.legal_version.c.version == version
        )
    ).first()
    if row is None:
        raise not_found()
    texts: dict[str, dict[str, str]] = row.languages
    chosen = render.choose_language(
        list(texts), setting["default_language"], lang, request.headers.get("accept-language")
    )
    versions = [
        v
        for v in conn.execute(
            select(t.legal_version.c.version)
            .where(t.legal_version.c.page == page)
            .order_by(t.legal_version.c.version.desc())
        ).scalars()
        if v != version
    ]
    return render.legal_document(
        page=page,
        lang=chosen,
        title=texts[chosen]["title"],
        source=texts[chosen]["markdown"],
        version=version,
        earlier=versions,
        current=served["version"] if served else None,
        languages=list(texts),
        legal=legal.public(setting),
        setting=landing.stored(conn),
        public_url=settings_of(request).public_url,
    )


def _legal_route(page: str, address: str) -> None:
    @page_router.api_route(
        f"/{address}", methods=["GET", "HEAD"], include_in_schema=False, name=f"legal_{page}"
    )
    def current(request: Request, lang: str | None = None) -> Response:
        with engine_of(request).begin() as conn:
            body = legal_html(conn, request, page, None, lang)
        return _answer(body)

    @page_router.api_route(
        f"/{address}/{{version}}",
        methods=["GET", "HEAD"],
        include_in_schema=False,
        name=f"legal_{page}_old",
    )
    def earlier(version: str, request: Request, lang: str | None = None) -> Response:
        with engine_of(request).begin() as conn:
            body = legal_html(conn, request, page, version, lang)
        return _answer(body)


def _answer(body: str) -> Response:
    return HTMLResponse(
        body,
        headers={
            "Cache-Control": PUBLIC,
            "Vary": "Cookie, Accept-Language",
            "Content-Security-Policy": LEGAL_CSP,
        },
    )


for _page, _address in legal.ADDRESS.items():
    _legal_route(_page, _address)
