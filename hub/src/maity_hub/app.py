"""The ASGI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from string import Template
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.types import Scope

from maity_hub import API_VERSION, __version__
from maity_hub.config import ConfigError, Settings
from maity_hub.db import current_revision, head_revision, make_engine

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
    app.include_router(_api_router(), prefix=f"/api/{API_VERSION}")
    _mount_web(app, settings)
    if settings.public_url_guessed:
        log.warning(
            "MAITY_PUBLIC_URL is not set and the hub binds a wildcard address; "
            "links in /help use %s",
            settings.public_url,
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
        body: dict[str, Any] = {"status": "ok", "version": __version__, "api": API_VERSION}
        try:
            current = current_revision(engine)
        except SQLAlchemyError:
            log.exception("health: database unreachable")
            body.update(status="error", database={"reachable": False})
            return JSONResponse(body, status_code=503)
        head = head_revision(engine)
        body["database"] = {"reachable": True, "revision": current, "head": head}
        if current != head:
            body["status"] = "error"
            return JSONResponse(body, status_code=503)
        return JSONResponse(body)

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


def _mount_web(app: FastAPI, settings: Settings) -> None:
    web_dir = settings.web_dir
    if web_dir is not None and web_dir.is_dir():
        # Mounted last: the API routes above take precedence over files.
        app.mount("/", DashboardFiles(directory=web_dir, html=True), name="web")
    elif settings.web_dir_required:
        raise ConfigError(f"MAITY_WEB_DIR {web_dir} is not a directory")
    elif web_dir is None:
        log.warning("no dashboard configured (MAITY_WEB_DIR); serving the API only")
    else:
        log.warning("no dashboard at %s; serving the API only", web_dir)
