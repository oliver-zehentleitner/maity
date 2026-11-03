"""The serving processes of `maity-hub serve` (hub/context/replicas.md, "Several workers per pod").

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
    """Why the settings may not run several workers, or None."""
    if settings.workers == 1:
        return None
    backend = make_url(settings.database_url).get_backend_name()
    if backend != "postgresql":
        return (
            f"MAITY_WORKERS={settings.workers} needs PostgreSQL: on {backend} the processes "
            "would not share wake-ups, nonces and limits; set MAITY_WORKERS=1"
        )
    return None


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
