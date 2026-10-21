"""The ASGI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from string import Template

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.routing import Match, Mount
from starlette.types import Scope

from maity_hub import API_VERSION, __version__, errors, events
from maity_hub.config import ConfigError, Settings
from maity_hub.db import current_revision, head_revision, make_engine
from maity_hub.errors import error_response
from maity_hub.middleware import HubMiddleware
from maity_hub.routes import auth as auth_routes
from maity_hub.routes import me as me_routes

log = logging.getLogger(__name__)

MARKDOWN = "text/markdown; charset=utf-8"


class SchemaNotCurrentError(RuntimeError):
    """The database is not at the migration head; `maity-hub migrate` has not run."""


def create_app(settings: Settings, engine: Engine | None = None) -> FastAPI:
    engine = engine if engine is not None else make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        require_current_schema(engine)
        yield
        engine.dispose()

    app = FastAPI(
        title="Maity hub",
        version=__version__,
        lifespan=lifespan,
        # No Swagger UI: it loads its assets from a CDN, and /help is the description.
        docs_url=None,
        redoc_url=None,
        openapi_url=f"/api/{API_VERSION}/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    errors.install(app)
    events.install(engine)
    prefix = f"/api/{API_VERSION}"
    app.include_router(_api_router(), prefix=prefix)
    app.include_router(auth_routes.router, prefix=prefix)
    app.include_router(me_routes.router, prefix=prefix)
    _mount_web(app, settings)
    if settings.public_url_guessed:
        log.warning(
            "MAITY_PUBLIC_URL is not set and the hub binds a wildcard address; "
            "links in /help use %s",
            settings.public_url,
        )
    app.add_middleware(HubMiddleware, settings=settings, engine=engine)
    if settings.allow_plain_http:
        log.warning(
            "MAITY_ALLOW_PLAIN_HTTP is set: bearer credentials and cookies travel over plain "
            "HTTP; run this only where the hub is reachable from a private network"
        )
    return app


def require_current_schema(engine: Engine) -> None:
    current, head = current_revision(engine), head_revision(engine)
    if current != head:
        raise SchemaNotCurrentError(
            f"database schema is at {current or 'nothing'}, the hub needs {head}: "
            "run `maity-hub migrate` first"
        )


def render_help(settings: Settings) -> str:
    # Template rather than str.format: the document is full of literal braces
    # (JSON examples, `{id}` in routes); only $-placeholders are substituted.
    template = Template((files("maity_hub") / "help.md").read_text(encoding="utf-8"))
    return template.safe_substitute(
        api_version=API_VERSION, hub_version=__version__, public_url=settings.public_url
    )


def _api_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health(request: Request) -> JSONResponse:
        engine: Engine = request.app.state.engine
        try:
            current = current_revision(engine)
        except SQLAlchemyError:
            log.exception("health: database unreachable")
            return error_response(503, "database_unavailable", "the database is unreachable")
        head = head_revision(engine)
        if current != head:
            return error_response(
                503,
                "schema_outdated",
                "the database is not at the migration head",
                {"revision": current, "head": head},
            )
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "api": API_VERSION,
                "database": {"reachable": True, "revision": current, "head": head},
            }
        )

    @router.get("/help", response_class=Response)
    def help_(request: Request) -> Response:
        return Response(render_help(request.app.state.settings), media_type=MARKDOWN)

    return router


class DashboardFiles(StaticFiles):
    """Static files without dotfiles and without anything under the API prefix.

    A `.env`, `.git/` or `.htaccess` that ends up in the dashboard directory is
    never served, and no file can answer for an API path.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        # `path` is normalised; the root arrives as ".".
        parts = [part for part in path.replace("\\", "/").split("/") if part != "."]
        if any(part.startswith(".") for part in parts) or parts[:1] == ["api"]:
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


class WebMount(Mount):
    """The dashboard at `/`, which never claims a path under `/api`.

    A plain mount at `/` fully matches every path, so the router would never
    fall back to a route that matched the path but not the method: a wrong
    method on an API path would be the mount's 404 instead of `405` with
    `Allow` (docs/api.md §1.3).
    """

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        path = scope.get("path", "")
        if path == "/api" or path.startswith("/api/"):
            return Match.NONE, {}
        return super().matches(scope)


def _mount_web(app: FastAPI, settings: Settings) -> None:
    web_dir = settings.web_dir
    if web_dir is not None and web_dir.is_dir():
        # Mounted last: the API routes above take precedence over files.
        app.router.routes.append(
            WebMount("/", app=DashboardFiles(directory=web_dir, html=True), name="web")
        )
    elif settings.web_dir_required:
        raise ConfigError(f"MAITY_WEB_DIR {web_dir} is not a directory")
    elif web_dir is None:
        log.warning("no dashboard configured (MAITY_WEB_DIR); serving the API only")
    else:
        log.warning("no dashboard at %s; serving the API only", web_dir)
