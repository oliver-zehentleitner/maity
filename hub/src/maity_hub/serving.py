"""The serving processes of `maity-hub serve` (hub/context/replicas.md: "Several workers per
pod", "Several pods").

With `MAITY_WORKERS` above 1, uvicorn's supervisor starts that many processes on one socket, and
each builds its app here from the environment: a spawned process inherits none of the parent's
objects. They share what they must through PostgreSQL, as replicas do, so more than one worker is
refused on any other database (`refusal`). The connection pool of the settings is the hub's
whole budget; each process holds its share (`per_worker`), and splits it between its sync and
its async engine (`pool_shares`).
"""

from __future__ import annotations

import logging
from dataclasses import replace

from fastapi import FastAPI
from sqlalchemy.engine import make_url

from maity_hub import attachment_store
from maity_hub.config import Settings
from maity_hub.db import SHARED_POOL_SIZE


def configure_logging() -> None:
    """What `maity-hub` sets up before any command; a spawned worker sets it up again, or the
    hub's own `INFO` lines (the request log, `stats`) are lost."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Alembic logs its context on every revision lookup, i.e. on every health call.
    logging.getLogger("alembic").setLevel(logging.WARNING)


def pool_shares(settings: Settings) -> tuple[int, int]:
    """The pooled connections of one process's sync and async engine, from its settings (after
    `per_worker`): the async engine holds `db_async_pool_size`, at least one and never all, and
    the sync engine the rest of the pool share and the whole overflow, so the two never ask for
    more than the pool share did alone (hub/context/replicas.md). That holds on a server
    database; on SQLite the engines take no pool sizes and keep SQLAlchemy's default for a file
    database each (5 + 10), with no server connection budget to keep."""
    async_share = min(max(settings.db_async_pool_size, 1), settings.db_pool_size - 1)
    return settings.db_pool_size - async_share, async_share


def pool_refusal(settings: Settings) -> str | None:
    """Why a process's pool share cannot be split (`pool_shares`), or None: each engine needs
    one pooled connection, since SQLAlchemy reads `pool_size=0` as no limit."""
    if make_url(settings.database_url).get_backend_name() == "sqlite":
        return None
    share = per_worker(settings)
    if share.db_pool_size >= MIN_POOL_PER_WORKER:
        return None
    if settings.workers == 1:
        return (
            f"MAITY_DB_POOL_SIZE must be at least {MIN_POOL_PER_WORKER} (it is "
            f"{settings.db_pool_size}): the pool is split between the sync and the async engine, "
            "and each needs one connection"
        )
    return (
        f"MAITY_WORKERS={settings.workers} needs MAITY_DB_POOL_SIZE of at least "
        f"{MIN_POOL_PER_WORKER * settings.workers} (it is {settings.db_pool_size}): each "
        "process holds its share of the pool, split between its sync and its async engine, "
        "and a share of 0 would be no limit at all"
    )


def refusal(settings: Settings) -> str | None:
    """Why the settings may not run as they are, or None: the pool split (`pool_refusal`), and
    what several processes or pods need."""
    split = pool_refusal(settings)
    if split is not None:
        return split
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
    if (
        settings.replicas > 1
        and attachment_store.configured(settings)
        and not attachment_store.shared(settings)
    ):
        return (
            f"MAITY_REPLICAS={settings.replicas} with a local attachment directory: each pod "
            "would see only its own files; store attachments on S3, or run one replica"
        )
    return None


# The minimum share of the pool per process: one connection for each of its two engines. In the
# request handlers of the measured test files no request held two of the serving pool at once
# (PostgreSQL, tsk-zm2z04ep2cma), so one is enough to be correct; more is throughput, the
# operator's choice. Background passes take from the sync pool and compete for its share. Neither
# can be 0: SQLAlchemy reads `pool_size=0` as no limit (hub/context/replicas.md, entry 4e24abd8).
MIN_POOL_PER_WORKER = 2


def pods_at_most(settings: Settings) -> int:
    """The pods that may run at once: the replicas, and during a rolling update of more than
    one the surge pod beside them (the chart's `maxSurge: 1`)."""
    return settings.replicas + (1 if settings.replicas > 1 else 0)


def connections(settings: Settings) -> int:
    """The most connections the whole deployment asks of the database, from what each worker
    holds (`per_worker`, so the two stay one arithmetic): per process its share of the pool and
    of the overflow, the shared-counter pool and one LISTEN connection (hub/context/replicas.md),
    per pod one for the readiness probe, which holds none in between. Count every pod that may
    run at once.
    """
    share = per_worker(settings)
    shared = (
        SHARED_POOL_SIZE
        if make_url(settings.database_url).get_backend_name() == "postgresql"
        else 0
    )
    per_pod = settings.workers * (share.db_pool_size + share.db_max_overflow + shared + 1) + 1
    return pods_at_most(settings) * per_pod


def budget_warning(settings: Settings, max_connections: int, reserved: int) -> str | None:
    """A warning when the deployment may ask more connections than the database takes from
    ordinary roles, or None. Only a warning: a pooler in front may report its own limit."""
    room = max_connections - reserved
    asked = connections(settings)
    if asked <= room:
        return None
    share = per_worker(settings)
    sync_share, async_share = pool_shares(share)
    shared = (
        f" + {SHARED_POOL_SIZE} shared"
        if make_url(settings.database_url).get_backend_name() == "postgresql"
        else ""
    )
    return (
        f"the hub may ask {asked} database connections ({pods_at_most(settings)} pod(s) at once "
        f"× ({settings.workers} process(es) × (pool {share.db_pool_size} "
        f"({sync_share} sync + {async_share} async) + overflow "
        f"{share.db_max_overflow}{shared} + 1 listener) + 1 health)), the database takes {room}; "
        "lower MAITY_DB_POOL_SIZE / MAITY_DB_MAX_OVERFLOW or the replicas"
    )


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
        db_async_pool_size=max(settings.db_async_pool_size // n, 1),
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
