"""The ASGI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

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
        docs_url=f"/api/{API_VERSION}/docs",
        redoc_url=None,
        openapi_url=f"/api/{API_VERSION}/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.include_router(_api_router(), prefix=f"/api/{API_VERSION}")
    _mount_web(app, settings)
    return app


def require_current_schema(engine: Engine) -> None:
    current, head = current_revision(engine), head_revision(engine)
    if current != head:
        raise SchemaNotCurrentError(
            f"database schema is at {current or 'nothing'}, the hub needs {head}: "
            "run `maity-hub migrate` first"
        )


def _api_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health(request: Request) -> JSONResponse:
        engine: Engine = request.app.state.engine
        body: dict[str, Any] = {"status": "ok", "version": __version__, "api": API_VERSION}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            current, head = current_revision(engine), head_revision(engine)
        except SQLAlchemyError:
            log.exception("health: database unreachable")
            body.update(status="error", database={"reachable": False})
            return JSONResponse(body, status_code=503)
        body["database"] = {"reachable": True, "revision": current, "head": head}
        if current != head:
            body["status"] = "error"
            return JSONResponse(body, status_code=503)
        return JSONResponse(body)

    @router.get("/help", response_class=Response)
    def help_(request: Request) -> Response:
        settings: Settings = request.app.state.settings
        template = (files("maity_hub") / "help.md").read_text(encoding="utf-8")
        body = template.format(
            api_version=API_VERSION, hub_version=__version__, public_url=settings.public_url
        )
        return Response(body, media_type=MARKDOWN)

    return router


def _mount_web(app: FastAPI, settings: Settings) -> None:
    web_dir = settings.web_dir
    if web_dir is not None and web_dir.is_dir():
        # Mounted last: the API routes above take precedence over files.
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    elif settings.web_dir_required:
        raise ConfigError(f"MAITY_WEB_DIR {web_dir} is not a directory")
    else:
        log.warning("no dashboard at %s; serving the API only", web_dir)
