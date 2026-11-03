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
    if settings.db_pool_size // settings.workers < MIN_POOL_PER_WORKER:
        return (
            f"MAITY_WORKERS={settings.workers} needs MAITY_DB_POOL_SIZE of at least "
            f"{MIN_POOL_PER_WORKER * settings.workers} (it is {settings.db_pool_size}): each "
            f"process holds its share and needs {MIN_POOL_PER_WORKER}, since a request may hold "
            "one connection while a shared count takes another"
        )
    return None


# A request may hold its transaction's connection while a shared count or the forge budget takes
# a second one from the same pool (hub/context/replicas.md, "Rate limits"): a process with fewer
# waits on itself.
MIN_POOL_PER_WORKER = 2


def per_worker(settings: Settings) -> Settings:
    """The settings of one worker: its share of the pool and of the overflow, rounded down, so
    the processes together never hold more than the settings name (`refusal` makes sure the
    share is enough). One worker keeps the pool as it is."""
    n = settings.workers
    if n == 1:
        return settings
    return replace(
        settings,
        db_pool_size=settings.db_pool_size // n,
        db_max_overflow=settings.db_max_overflow // n,
    )


def app() -> FastAPI:
    """The app of one worker process, uvicorn's factory (`maity_hub.serving:app`). The parent ran
    the checks and the one-time work of a start already (`cli._serve_workers`). A worker that
    cannot build its app exits with uvicorn's start failure, so the supervisor stops instead of
    starting it again and again."""
    from uvicorn.config import STARTUP_FAILURE

    from maity_hub.app import create_app, serving_engine

    configure_logging()
    try:
        settings = per_worker(Settings.from_env())
        return create_app(settings, serving_engine(settings), started=True)
    except Exception:
        logging.getLogger(__name__).exception("a worker could not build its app")
        raise SystemExit(STARTUP_FAILURE) from None
