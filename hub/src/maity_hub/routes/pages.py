"""The pages the hub renders itself, outside the API (docs/api.md §16.7, §16.7.1): the
landing page at `/` for a visitor without a session while it is enabled, and the legal pages
at `/impressum`, `/privacy` and `/terms`, the last two with their earlier versions readable at
`/<page>/<version>`, linked from no public page.

The landing page loads the hub's own first-party files (`landing_files`, §16.7) and answers
with a Content-Security-Policy that allows exactly those; the legal pages carry no script.
They are the public host's only (the join host never routes here, §1.1).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import Connection, select

from maity_hub import (
    campaigns,
    landing,
    landing_stats,
    legal,
    maintenance,
    public_pages,
    public_projects,
    render,
)
from maity_hub import tables as t
from maity_hub.auth import caller as auth_caller
from maity_hub.deps import engine_of, origin_of, settings_of
from maity_hub.errors import not_found, rate_limited
from maity_hub.shell import shell_response

page_router = APIRouter()
router = APIRouter()  # under the API prefix

LANDING_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; "
    "font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
# The legal pages load the landing page's stylesheets and fonts, and no script (§16.7.5).
LEGAL_CSP = (
    "default-src 'none'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self'; "
    "base-uri 'none'; frame-ancestors 'none'"
)
PUBLIC = "public, max-age=60"
PRIVATE = "private, max-age=60"


def landing_html(
    conn: Connection,
    request: Request,
    setting: dict[str, Any],
    *,
    lang: str | None,
    variant: str | None = None,
    campaign: str | None = None,
) -> str:
    """The landing page of the saved setting (or one of its variants), for the language the
    visitor asked for. While variants or campaigns are set, every link to `/register` carries
    the visitor's origin, `v` and (for a campaign the admin created) `c` (§16.7.2)."""
    pages = setting["variants"][variant]["pages"] if variant else setting["pages"]
    chosen = render.choose_language(
        render.ordered_languages(pages, setting["default_language"]),
        setting["default_language"],
        lang,
        request.headers.get("accept-language"),
    )
    stats = landing_stats.current(conn) if landing_stats.named(setting) else None
    html = render.landing_document(
        setting,
        chosen,
        public_url=settings_of(request).public_url,
        legal=legal.public(legal.stored(conn)),
        stats=stats,
        variant=variant,
        social_image=settings_of(request).web_dir is not None,
    )
    if landing.configured(setting):
        html = render.carry_origin(
            html,
            variant or landing.DEFAULT_VARIANT,
            campaign,
            settings_of(request).public_url,
        )
    return html


def known_campaign(setting: dict[str, Any], code: str | None) -> str | None:
    """The campaign code of `?c=` when the admin created it, else none: an unknown or malformed
    code is treated as none, not echoed (§16.7.2)."""
    if code is not None and code in {one["code"] for one in setting["campaigns"]}:
        return code
    return None


def _count_view(
    conn: Connection,
    request: Request,
    setting: dict[str, Any],
    variant: str,
    campaign: str | None,
    as_: str | None,
) -> None:
    """A view of the main page or a variant, while variants or campaigns are set and the request
    is a browser's top-level navigation (§16.7.2); the sum of the day, nothing about the visit."""
    if landing.configured(setting) and campaigns.is_view(
        request.method, request.headers, as_public=as_ == "public"
    ):
        campaigns.view(conn, variant, campaign)


def landing_headers(setting: dict[str, Any]) -> dict[str, str]:
    """The landing page's headers: `private` while campaigns or variants are set, so that a
    shared cache does not swallow the views (§16.7.2); `public` otherwise (§16.7)."""
    return {
        "Cache-Control": PRIVATE if landing.configured(setting) else PUBLIC,
        "Vary": "Cookie, Accept-Language",
        "Content-Security-Policy": LANDING_CSP,
    }


@page_router.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def root(
    request: Request,
    lang: str | None = None,
    c: str | None = None,
    as_: str | None = Query(None, alias="as"),
) -> Response:
    """The landing page for a visitor without a valid session, or for anyone who asks to see
    it as one (`?as=public`), while it is enabled; the app shell otherwise (§16.7)."""
    settings = settings_of(request)
    # Read before the transaction below: the window has a connection of its own.
    window = maintenance.window_now(engine_of(request))
    with engine_of(request).begin() as conn:
        setting = landing.stored(conn)
        visitor = as_ == "public" or not auth_caller.has_live_session(conn, request.cookies)
        if setting["enabled"] and visitor:
            if window is not None and window["state"] == "running":
                return maintenance.refusal_page(window)  # type: ignore[no-any-return]
            campaign = known_campaign(setting, c)
            body = landing_html(conn, request, setting, lang=lang, campaign=campaign)
            _count_view(conn, request, setting, landing.DEFAULT_VARIANT, campaign, as_)
            body = maintenance.with_banner(body, window)
            return HTMLResponse(body, headers=landing_headers(setting))
    return _shell(settings)


def _shell(settings: Any) -> Response:
    if settings.web_dir is None or not (settings.web_dir / "index.html").is_file():
        raise not_found()  # a hub without a dashboard serves the API alone
    return shell_response(settings.web_dir, settings.public_url)


@router.get("/public/pages/{path:path}")
def read_public_page(path: str, request: Request) -> Response:
    """What a visitor's dashboard reads (§16.9): no caller, the same answer for everyone."""
    return public_pages.read(request, path)


@page_router.api_route("/explore", methods=["GET", "HEAD"], include_in_schema=False)
def explore(request: Request) -> Response:
    """The public projects (§16.9), for every visitor, with or without a session; the shell
    while the instance serves no public pages, as for any address it does not have."""
    settings = settings_of(request)
    if not settings.public_pages:
        return _shell(settings)
    wait = public_pages.BY_ADDRESS.hit(origin_of(request).address)
    if wait:
        raise rate_limited(wait)
    window = maintenance.window_now(engine_of(request))
    with engine_of(request).begin() as conn:
        frame = landing.stored(conn)
        body = public_projects.explore_html(
            conn,
            settings,
            setting=frame,
            legal=legal.public(legal.stored(conn)),
            stats=landing_stats.for_frame(conn, frame),
            accept_language=request.headers.get("accept-language"),
        )
        body = maintenance.with_banner(body, window)
    return HTMLResponse(
        body,
        headers={
            "Cache-Control": public_pages.CACHE,
            "Vary": "Cookie, Accept-Language",
            "Content-Security-Policy": LEGAL_CSP,
            "X-Content-Type-Options": "nosniff",
        },
    )


@page_router.api_route("/for/{slug}", methods=["GET", "HEAD"], include_in_schema=False)
def variant(request: Request, slug: str, lang: str | None = None, c: str | None = None) -> Response:
    """A variant of the landing page (§16.7.2), for every visitor, with or without a session,
    while the landing page is enabled and the variant exists; the app shell otherwise, as an
    unknown path would be, so that an address does not tell whether a variant existed."""
    window = maintenance.window_now(engine_of(request))
    with engine_of(request).begin() as conn:
        setting = landing.stored(conn)
        if setting["enabled"] and slug in setting["variants"]:
            campaign = known_campaign(setting, c)
            body = landing_html(conn, request, setting, lang=lang, variant=slug, campaign=campaign)
            body = maintenance.with_banner(body, window)
            _count_view(conn, request, setting, slug, campaign, None)
            return HTMLResponse(body, headers=landing_headers(setting))
    return _shell(settings_of(request))


def legal_html(
    conn: Connection,
    request: Request,
    page: str,
    version: str | None,
    lang: str | None,
) -> str:
    """One legal page: the served version, or an earlier one by its version where the page
    serves those."""
    if version is not None and page not in legal.EARLIER_SERVED:
        raise not_found()
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
    frame = landing.stored(conn)
    return render.legal_document(
        page=page,
        lang=chosen,
        title=texts[chosen]["title"],
        source=texts[chosen]["markdown"],
        version=version,
        current=served["version"] if served else None,
        languages=list(texts),
        legal=legal.public(setting),
        setting=frame,
        public_url=settings_of(request).public_url,
        stats=landing_stats.for_frame(conn, frame),
    )


def _legal_route(page: str, address: str) -> None:
    @page_router.api_route(
        f"/{address}", methods=["GET", "HEAD"], include_in_schema=False, name=f"legal_{page}"
    )
    def current(request: Request, lang: str | None = None) -> Response:
        window = maintenance.window_now(engine_of(request))  # read first: its own connection
        with engine_of(request).begin() as conn:  # readable during a window (§16.12)
            body = legal_html(conn, request, page, None, lang)
        return _answer(maintenance.with_banner(body, window))

    @page_router.api_route(
        f"/{address}/{{version}}",
        methods=["GET", "HEAD"],
        include_in_schema=False,
        name=f"legal_{page}_old",
    )
    def earlier(version: str, request: Request, lang: str | None = None) -> Response:
        window = maintenance.window_now(engine_of(request))  # read first: its own connection
        with engine_of(request).begin() as conn:  # readable during a window (§16.12)
            body = legal_html(conn, request, page, version, lang)
        return _answer(maintenance.with_banner(body, window))


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
