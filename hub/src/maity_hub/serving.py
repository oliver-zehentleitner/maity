"""The serving processes of `maity-hub serve` (hub/context/replicas.md: "Several workers per
pod", "Several pods").

With `MAITY_WORKERS` above 1, uvicorn's supervisor starts that many processes on one socket, and
each builds its app here from the environment: a spawned process inherits none of the parent's
objects. They share what they must through PostgreSQL, as replicas do, so more than one worker is
refused on any other database (`refusal`). The connection pool of the settings is the hub's
whole budget; each process holds its share (`per_worker`).
"""

from __future__ import annotations

import logging
from dataclasses import replace

from fastapi import FastAPI
from sqlalchemy.engine import make_url

from maity_hub.config import Settings


def configure_logging() -> None:
    """What `maity-hub` sets up before any command; a spawned worker sets it up again, or the
    hub's own `INFO` lines (the request log, `stats`) are lost."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Alembic logs its context on every revision lookup, i.e. on every health call.
    logging.getLogger("alembic").setLevel(logging.WARNING)


def refusal(settings: Settings) -> str | None:
    """Why the settings may not run several processes or pods, or None."""
    if settings.workers == 1 and settings.replicas == 1:
        return None
    backend = make_url(settings.database_url).get_backend_name()
    if backend != "postgresql":
        name = "MAITY_WORKERS" if settings.replicas == 1 else "MAITY_REPLICAS"
        value = settings.workers if settings.replicas == 1 else settings.replicas
        return (
            f"{name}={value} needs PostgreSQL: on {backend} the processes would not share "
            f"wake-ups, nonces and limits; set {name}=1"
        )
    if settings.replicas > 1 and settings.attachment_store == "local" and settings.attachment_dir:
        return (
            f"MAITY_REPLICAS={settings.replicas} with a local attachment directory: each pod "
            "would see only its own files; store attachments on S3, or run one replica"
        )
    return None


def connections(settings: Settings) -> int:
    """The most connections the whole deployment asks of the database: per pod its pool and
    overflow, one LISTEN connection per process (§8, hub/context/replicas.md), and one for the
    readiness probe, which holds none in between."""
    per_pod = settings.db_pool_size + settings.db_max_overflow + settings.workers + 1
    return settings.replicas * per_pod


def budget_warning(settings: Settings, max_connections: int, reserved: int) -> str | None:
    """A warning when the deployment may ask more connections than the database takes from
    ordinary roles, or None. Only a warning: a pooler in front may report its own limit."""
    room = max_connections - reserved
    asked = connections(settings)
    if asked <= room:
        return None
    return (
        f"the hub may ask {asked} database connections ({settings.replicas} pod(s) × "
        f"(pool {settings.db_pool_size} + overflow {settings.db_max_overflow} + "
        f"{settings.workers} listener(s) + 1 health)), the database takes {room}; lower "
        "MAITY_DB_POOL_SIZE / MAITY_DB_MAX_OVERFLOW or the replicas"
    )


def per_worker(settings: Settings) -> Settings:
    """The settings of one worker: its share of the pool, at least one connection, the overflow
    divided alike. One worker keeps the pool as it is."""
    n = settings.workers
    if n == 1:
        return settings
    return replace(
        settings,
        db_pool_size=max(1, settings.db_pool_size // n),
        db_max_overflow=settings.db_max_overflow // n,
    )


def app() -> FastAPI:
    """The app of one worker process, uvicorn's factory (`maity_hub.serving:app`)."""
    from maity_hub.app import create_app, serving_engine

    configure_logging()
    settings = per_worker(Settings.from_env())
    return create_app(settings, serving_engine(settings))
