"""The forge's budget per source as every replica sees it, on PostgreSQL (hub/context/replicas.md
83da2bfa). One small UNLOGGED row per source: what the last answers said is left, and until when
the source is held. `in_flight` stays with the process, as it bounds that process's reads.

The budget guards the forge, not a decision of the hub: a database that does not answer costs the
sharing, never a read, and the process goes on with what it knows itself.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta
from typing import Any

from sqlalchemy import Engine, case, delete, func, select
from sqlalchemy.dialects import postgresql

from maity_hub import tables as t
from maity_hub import write_guard

log = logging.getLogger(__name__)

KEPT = timedelta(hours=2)  # a window is an hour; installation tokens are minted anew every hour
SWEEP_EVERY = 1000  # writes per process between deletes of the sources nobody reads any more

_engine: list[Engine | None] = [None]
_writes = [0]
_lock = threading.Lock()


def configure(engine: Engine | None) -> None:
    """Share the budgets through `engine` when it is PostgreSQL; None turns sharing off."""
    _engine[0] = engine if engine is not None and engine.dialect.name == "postgresql" else None


def read(source: str) -> Any | None:
    """The source's row, or None: nothing shared yet, or the database did not answer."""
    engine = _engine[0]
    if engine is None:
        return None
    try:
        with engine.begin() as conn:
            write_guard.exempt(conn)  # a forge read may run inside a human's request
            return conn.execute(
                select(t.forge_budget).where(t.forge_budget.c.source == source)
            ).first()
    except Exception:
        log.warning("the shared forge budget could not be read", exc_info=True)
        return None


def write(
    source: str, limit: int | None, remaining: int | None, reset: float | None, until: float
) -> None:
    """Merge what this process knows, the same way `forge._merge` does: answers of one window keep
    the lowest `remaining`, a later reset replaces it, an earlier one changes nothing."""
    engine = _engine[0]
    if engine is None:
        return
    b = t.forge_budget.c
    statement = postgresql.insert(t.forge_budget).values(
        source=source,
        limit=limit,
        remaining=remaining,
        reset=reset,
        until=until,
        seen_at=func.timezone("UTC", func.now()),
    )
    new = statement.excluded
    newer = (new.reset.is_not(None)) & (b.reset.is_(None) | (new.reset > b.reset))
    statement = statement.on_conflict_do_update(
        index_elements=["source"],
        set_={
            "limit": func.coalesce(new.limit, b.limit),
            "remaining": case(
                (newer, new.remaining),
                (new.reset < b.reset, b.remaining),
                else_=func.least(new.remaining, b.remaining),
            ),
            "reset": func.greatest(new.reset, b.reset),
            "until": func.greatest(new.until, b.until),
            "seen_at": new.seen_at,
        },
    )
    with _lock:
        _writes[0] += 1
        sweep = _writes[0] % SWEEP_EVERY == 0
    try:
        with engine.begin() as conn:
            write_guard.exempt(conn)
            conn.execute(statement)
            if sweep:
                conn.execute(
                    delete(t.forge_budget).where(
                        b.seen_at < func.timezone("UTC", func.now()) - KEPT
                    )
                )
    except Exception:
        log.warning("the shared forge budget could not be written", exc_info=True)
