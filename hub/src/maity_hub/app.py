"""The ASGI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from string import Template

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.routing import Mount

from maity_hub import (
    API_VERSION,
    __version__,
    attachment_store,
    attachments,
    availability,
    commitment,
    errors,
    forge,
    forge_access,
    images,
    longpoll,  # noqa: F401  (subscribes the long-poll to new events)
    namespace,
    not_listening,
    not_listening_digest,
    org_invitations,
    probe,
    public_pages,
    public_people,  # noqa: F401  (registers the kind of page)
    registration_accounts,
    reports,
    request_stats,
    takeovers,
    write_guard,
)
from maity_hub.auth import device_codes as codes
from maity_hub.auth import sign_in_settings as sign_in
from maity_hub.config import ConfigError, Settings
from maity_hub.db import (
    APPLICATION_SERVING,
    current_revision,
    head_revision,
    make_engine,
    make_health_engine,
)
from maity_hub.errors import error_response
from maity_hub.forge_webhook import check_secrets
from maity_hub.mail import outbox
from maity_hub.mail import settings as mail
from maity_hub.mail.environment import MailConfigError
from maity_hub.middleware import HubMiddleware
from maity_hub.notifications import mailer
from maity_hub.routes import (
    admin,
    agents,
    avatars,
    badges,
    board,
    contract_text,
    conversations,
    device_codes,
    email_sign_in,
    forge_links,
    forge_webhook,
    joins,
    jour_fixe,
    keep_the_why,
    limit,
    mail_links,
    mail_settings,
    me_session,
    member_settings,
    members,
    memory,
    notification_settings,
    notifications,
    overview,
    pages,
    placements,
    preferences,
    project_images,
    project_messages,
    projects,
    register_page,
    requests,
    runner,
    runners,
    seo,
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
from maity_hub.routes import legal as legal_routes
from maity_hub.routes import (
    limits as limits_routes,
)
from maity_hub.routes import me as me_routes
from maity_hub.routes import orgs as orgs_routes
from maity_hub.routes import probe as probe_routes
from maity_hub.routes import registration as registration_routes
from maity_hub.routes import reports as report_routes
from maity_hub.routes import second_factor as second_factor_routes
from maity_hub.routes import takeovers as takeover_routes
from maity_hub.shell import AssetFiles, ShellRoute

log = logging.getLogger(__name__)

MARKDOWN = "text/markdown; charset=utf-8"


class SchemaNotCurrentError(RuntimeError):
    """The database is not at the migration head; `maity-hub migrate` has not run."""


def serving_engine(settings: Settings) -> Engine:
    """The engine of a serving hub: the pool and the PostgreSQL timeouts of the settings.
    `maity-hub serve` builds it here too, so a setting reaches the engine the hub runs on."""
    return make_engine(
        settings.database_url,
        settings.db_pool_size,
        settings.db_max_overflow,
        settings.db_pool_recycle,
        settings.db_statement_timeout,
        settings.db_idle_in_transaction_timeout,
        APPLICATION_SERVING,
    )


def create_app(settings: Settings, engine: Engine | None = None) -> FastAPI:
    engine = engine if engine is not None else serving_engine(settings)
    health_engine = make_health_engine(engine)  # the probe's own connection, outside the pool
    write_guard.install(engine)  # no write of a deleted account commits (§2.9)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        require_current_schema(engine)
        with engine.connect() as conn:
            holders = namespace.reserved_holders(conn)
            if holders:  # `maity-hub migrate` refuses these; a hub started past it says so
                log.error("words that docs/api.md §16.11 reserves are held: %s", ", ".join(holders))
            try:
                mail.check_at_startup(conn, settings.mail, settings.secret_key)
            except MailConfigError as error:
                raise ConfigError(str(error)) from None
        check_secrets(engine, settings.secret_key)
        # Every public page again before any is served (§16.9), then the safety net's worker.
        public_pages.startup(engine, settings)
        with engine.begin() as conn:
            # A method the environment switched off voids its open codes at once (§2.6.5).
            if not sign_in.device_code_enabled(conn, settings):
                codes.void_open(conn)
            if not sign_in.email_link_enabled(conn, settings):
                from maity_hub.auth import email_links

                email_links.void_open(conn)
            # A second factor the environment switched off is told, once (§2.8.5).
            source = sign_in.resolve(conn, settings)["second_factor"][1]
            sign_in.note_second_factor(
                conn, settings, "environment" if source == "env" else "admin"
            )
        reader = forge.Forge(settings.forge_github_token, access=_app.state.forge_access)
        # The owner's grants read too (§11.4): an App, or tokens sealed with the key.
        sources = (settings.forge_github_token, settings.github_app, settings.secret_key)
        worker = probe.Worker(engine, reader) if any(s is not None for s in sources) else None
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
        # A session that stopped reading is noticed without anybody asking (§5.3).
        not_listening_worker = not_listening.Worker(engine)
        not_listening_worker.start()
        # The owners' digest of instances that are away, on the hour (§5.3).
        digest_worker = not_listening_digest.Worker(engine)
        digest_worker.start()
        commitment_worker = commitment.Worker(engine)
        commitment_worker.start()
        registrations_worker = registration_accounts.Worker(engine)
        registrations_worker.start()
        # An open report expires and a closed one's content goes on time (§16.8).
        reports_worker = reports.Worker(engine)
        reports_worker.start()
        # An organisation's invitation expires without anybody calling (docs/api.md §6.26).
        invitations_worker = org_invitations.Worker(engine)
        invitations_worker.start()
        from maity_hub.jourfixe import worker as jour_fixe_worker

        jour_fixe_clock = jour_fixe_worker.Worker(engine)  # the schedule acts on its own
        jour_fixe_clock.start()
        # A takeover's window ends without anybody calling (docs/api.md §6.19).
        takeover_worker = takeovers.Worker(engine)
        takeover_worker.start()
        # The outbox is sent in the background, with the settings in effect (§16.2, §18.7).
        mail_worker = outbox.Worker(engine, settings.mail, settings.secret_key)
        mail_worker.start()
        # Pending uploads expire and stray blobs go without a request to notice it (§8.7).
        file_store = attachment_store.optional_store(settings)
        sweeper = attachments.Worker(engine, file_store) if file_store is not None else None
        if sweeper is not None:
            sweeper.start()
        notify_worker = mailer.Worker(
            engine, settings.mail, settings.secret_key, settings.public_url
        )
        notify_worker.start()
        stats_reporter = request_stats.Reporter(engine)
        stats_reporter.start()
        pages_worker = public_pages.Worker(engine, settings)
        pages_worker.start()
        yield
        pages_worker.stop()
        stats_reporter.stop()
        notify_worker.stop()
        if sweeper is not None:
            sweeper.stop()
        mail_worker.stop()
        takeover_worker.stop()
        jour_fixe_clock.stop()
        reports_worker.stop()
        invitations_worker.stop()
        registrations_worker.stop()
        commitment_worker.stop()
        availability_worker.stop()
        not_listening_worker.stop()
        digest_worker.stop()
        image_worker.stop()
        if worker is not None:
            worker.stop()
        engine.dispose()
        if health_engine is not None:
            health_engine.dispose()

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
    app.state.health_engine = health_engine or engine
    app.state.forge_access = forge_access.ForgeAccess(
        engine, settings.github_app, settings.secret_key
    )
    app.state.probe = None  # the worker, from startup on when a forge token is set
    errors.install(app)
    prefix = f"/api/{API_VERSION}"
    app.include_router(_api_router(), prefix=prefix)
    app.include_router(auth_routes.router, prefix=prefix)
    app.include_router(device_codes.router, prefix=prefix)
    app.include_router(second_factor_routes.router, prefix=prefix)
    app.include_router(me_routes.router, prefix=prefix)
    app.include_router(notifications.router, prefix=prefix)
    app.include_router(forge_links.router, prefix=prefix)
    app.include_router(notification_settings.router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)
    app.include_router(report_routes.router, prefix=prefix)
    app.include_router(registration_routes.router, prefix=prefix)
    app.include_router(invitation_routes.router, prefix=prefix)
    app.include_router(landing_routes.router, prefix=prefix)
    app.include_router(orgs_routes.router, prefix=prefix)
    app.include_router(legal_routes.router, prefix=prefix)
    app.include_router(mail_settings.router, prefix=prefix)
    app.include_router(sign_in_settings.router, prefix=prefix)
    app.include_router(me_session.router, prefix=prefix)
    app.include_router(limit.router, prefix=prefix)
    app.include_router(limits_routes.router, prefix=prefix)
    app.include_router(projects.router, prefix=prefix)
    app.include_router(project_images.router, prefix=prefix)
    app.include_router(keep_the_why.router, prefix=prefix)
    app.include_router(members.router, prefix=prefix)
    app.include_router(member_settings.router, prefix=prefix)
    app.include_router(agents.router, prefix=prefix)
    app.include_router(avatars.router, prefix=prefix)
    app.include_router(joins.router, prefix=prefix)
    app.include_router(tasks.router, prefix=prefix)
    app.include_router(board.router, prefix=prefix)
    app.include_router(contract_text.router, prefix=prefix)
    app.include_router(takeover_routes.router, prefix=prefix)
    app.include_router(overview.router, prefix=prefix)
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
    app.include_router(joins.page_router)  # /join/{token}, before the app shell
    app.include_router(runners.page_router)  # /r/{token}, likewise
    app.include_router(email_sign_in.router, prefix=prefix)
    app.include_router(email_sign_in.page_router)
    app.include_router(mail_links.page_router)  # /mail/*, likewise
    app.include_router(register_page.page_router)  # the registration's link page, likewise
    app.include_router(badges.router)  # public /badge/*.svg, before the dashboard
    app.include_router(seo.router)  # /robots.txt and /sitemap.xml, before the dashboard
    app.include_router(pages.page_router)  # `/` and the legal pages, before the app shell
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
        engine: Engine = request.app.state.health_engine
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


def _mount_web(app: FastAPI, settings: Settings) -> None:
    web_dir = settings.web_dir
    if web_dir is not None and web_dir.is_dir():
        # Mounted last: the API routes above take precedence over files.
        app.router.routes.append(Mount("/assets", app=AssetFiles(directory=web_dir), name="assets"))
        app.router.routes.append(ShellRoute(web_dir))
    elif settings.web_dir_required:
        raise ConfigError(f"MAITY_WEB_DIR {web_dir} is not a directory")
    elif web_dir is None:
        log.warning("no dashboard configured (MAITY_WEB_DIR); serving the API only")
    else:
        log.warning("no dashboard at %s; serving the API only", web_dir)
