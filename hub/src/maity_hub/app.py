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

from maity_hub import (
    API_VERSION,
    __version__,
    availability,
    errors,
    forge,
    images,
    longpoll,  # noqa: F401  (subscribes the long-poll to new events)
    probe,
    registration_accounts,
    takeovers,
)
from maity_hub.auth import device_codes as codes
from maity_hub.auth import sign_in_settings as sign_in
from maity_hub.config import ConfigError, Settings
from maity_hub.db import current_revision, head_revision, make_engine
from maity_hub.errors import error_response
from maity_hub.forge_webhook import check_secrets
from maity_hub.mail import outbox
from maity_hub.mail import settings as mail
from maity_hub.mail.environment import MailConfigError
from maity_hub.middleware import HubMiddleware
from maity_hub.routes import (
    admin,
    agents,
    avatars,
    badges,
    board,
    contract_text,
    conversations,
    device_codes,
    forge_webhook,
    joins,
    jour_fixe,
    keep_the_why,
    limit,
    mail_settings,
    me_session,
    members,
    memory,
    notifications,
    placements,
    preferences,
    project_images,
    project_messages,
    projects,
    requests,
    runner,
    runners,
    sign_in_settings,
    swarm,
    tasks,
    ticker,
)
from maity_hub.routes import (
    attachments as attachment_routes,
)
from maity_hub.routes import auth as auth_routes
from maity_hub.routes import events as events_routes
from maity_hub.routes import invitations as invitation_routes
from maity_hub.routes import landing as landing_routes
from maity_hub.routes import me as me_routes
from maity_hub.routes import probe as probe_routes
from maity_hub.routes import registration as registration_routes
from maity_hub.routes import takeovers as takeover_routes

log = logging.getLogger(__name__)

MARKDOWN = "text/markdown; charset=utf-8"


class SchemaNotCurrentError(RuntimeError):
    """The database is not at the migration head; `maity-hub migrate` has not run."""


def create_app(settings: Settings, engine: Engine | None = None) -> FastAPI:
    engine = (
        engine
        if engine is not None
        else make_engine(settings.database_url, settings.db_pool_size, settings.db_max_overflow)
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        require_current_schema(engine)
        with engine.connect() as conn:
            try:
                mail.check_at_startup(conn, settings.mail, settings.secret_key)
            except MailConfigError as error:
                raise ConfigError(str(error)) from None
        check_secrets(engine, settings.secret_key)
        with engine.begin() as conn:
            # A method the environment switched off voids its open codes at once (§2.6.5).
            if not sign_in.device_code_enabled(conn, settings):
                codes.void_open(conn)
        reader = forge.Forge(settings.forge_github_token)
        worker = probe.Worker(engine, reader) if reader.token is not None else None
        _app.state.probe = worker
        if worker is not None:
            worker.start()
        # Forge images are read without a token for a public repository, so this one
        # runs whether or not the hub holds a token (docs/api.md §11.2).
        image_worker = images.Worker(engine, reader)
        image_worker.start()
        # Limits end and sessions go away without a request to notice it (§6.12).
        availability_worker = availability.Worker(engine)
        availability_worker.start()
        registrations_worker = registration_accounts.Worker(engine)
        registrations_worker.start()
        from maity_hub.jourfixe import worker as jour_fixe_worker

        jour_fixe_clock = jour_fixe_worker.Worker(engine)  # the schedule acts on its own
        jour_fixe_clock.start()
        # A takeover's window ends without anybody calling (docs/api.md §6.19).
        takeover_worker = takeovers.Worker(engine)
        takeover_worker.start()
        # The outbox is sent in the background, with the settings in effect (§16.2, §18.7).
        mail_worker = outbox.Worker(engine, settings.mail, settings.secret_key)
        mail_worker.start()
        yield
        mail_worker.stop()
        takeover_worker.stop()
        jour_fixe_clock.stop()
        registrations_worker.stop()
        availability_worker.stop()
        image_worker.stop()
        if worker is not None:
            worker.stop()
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
    app.state.probe = None  # the worker, from startup on when a forge token is set
    errors.install(app)
    prefix = f"/api/{API_VERSION}"
    app.include_router(_api_router(), prefix=prefix)
    app.include_router(auth_routes.router, prefix=prefix)
    app.include_router(device_codes.router, prefix=prefix)
    app.include_router(me_routes.router, prefix=prefix)
    app.include_router(notifications.router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)
    app.include_router(registration_routes.router, prefix=prefix)
    app.include_router(invitation_routes.router, prefix=prefix)
    app.include_router(landing_routes.router, prefix=prefix)
    app.include_router(mail_settings.router, prefix=prefix)
    app.include_router(sign_in_settings.router, prefix=prefix)
    app.include_router(me_session.router, prefix=prefix)
    app.include_router(limit.router, prefix=prefix)
    app.include_router(projects.router, prefix=prefix)
    app.include_router(project_images.router, prefix=prefix)
    app.include_router(keep_the_why.router, prefix=prefix)
    app.include_router(members.router, prefix=prefix)
    app.include_router(agents.router, prefix=prefix)
    app.include_router(avatars.router, prefix=prefix)
    app.include_router(joins.router, prefix=prefix)
    app.include_router(tasks.router, prefix=prefix)
    app.include_router(board.router, prefix=prefix)
    app.include_router(contract_text.router, prefix=prefix)
    app.include_router(takeover_routes.router, prefix=prefix)
    app.include_router(requests.router, prefix=prefix)
    app.include_router(events_routes.router, prefix=prefix)
    app.include_router(conversations.router, prefix=prefix)
    app.include_router(attachment_routes.router, prefix=prefix)
    app.include_router(project_messages.router, prefix=prefix)
    app.include_router(probe_routes.router, prefix=prefix)
    app.include_router(runners.router, prefix=prefix)
    app.include_router(runner.router, prefix=prefix)
    app.include_router(placements.router, prefix=prefix)
    app.include_router(ticker.router, prefix=prefix)
    app.include_router(memory.router, prefix=prefix)
    app.include_router(preferences.router, prefix=prefix)
    app.include_router(jour_fixe.router, prefix=prefix)
    app.include_router(forge_webhook.router, prefix=prefix)
    app.include_router(joins.page_router)  # /j/{token}, before the dashboard mount
    app.include_router(runners.page_router)  # /r/{token}, likewise
    app.include_router(badges.router)  # public /badge/*.svg, before the dashboard
    app.include_router(swarm.router, prefix=prefix)  # the members' and the public swarm page
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
        api_version=API_VERSION,
        hub_version=__version__,
        public_url=settings.public_url,
        cli_install=settings.cli_install,
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


# Parts of web/ that belong to the dashboard's development, not to the page:
# the fixture data it is tested against and its tools.
NOT_SERVED = {"api", "fixtures", "tools"}


class DashboardFiles(StaticFiles):
    """Static files without dotfiles, the API prefix, or web/'s development parts.

    A `.env`, `.git/` or `.htaccess` that ends up in the dashboard directory is
    never served, no file can answer for an API path, and `fixtures/` and
    `tools/` stay in the repository.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        # `path` is normalised; the root arrives as ".".
        parts = [part for part in path.replace("\\", "/").split("/") if part != "."]
        if any(part.startswith(".") for part in parts) or parts[:1] and parts[0] in NOT_SERVED:
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
